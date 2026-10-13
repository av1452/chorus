"""Tests for the config container parser.

Uses synthetic blobs built to the documented shape rather than a real
backup -- a real one is personal device data and does not belong in a
public repo. The synthetic fixtures are cross-checked against the real
Harmony 665 backup described in this port's commit history, not invented
from nothing: the offsets, field sizes and the architecture-14 signature
all come from an actual parse of real hardware data.
"""

from __future__ import annotations

import pytest

from chorus.config.binary import (
    CONTAINER_SIGNATURES,
    POINTER_TABLE_OFFSET,
    BinaryFormatError,
    parse_container,
)


def build_blob(
    architecture: int,
    config_base: int,
    section_lengths: list[int],
    *,
    corrupt_terminator: bool = False,
    corrupt_padding: bool = False,
    corrupt_header_marker: bool = False,
    corrupt_blob_marker: bool = False,
    wrong_base: int | None = None,
) -> bytes:
    """Build a container-shaped blob with ``len(section_lengths)`` real
    sections, each of the given length, filled with a repeating byte so
    a test can tell sections apart.
    """
    sig = CONTAINER_SIGNATURES[architecture]
    num_real = sig.slot_count - 1
    if len(section_lengths) != num_real:
        raise ValueError(
            f"architecture {architecture} needs exactly {num_real} section "
            f"lengths, got {len(section_lengths)}"
        )

    header_len = POINTER_TABLE_OFFSET + 4 * sig.slot_count + 3 + 4
    section_start = header_len
    addresses = []
    cursor = config_base + section_start
    for length in section_lengths:
        addresses.append(cursor)
        cursor += length
    total_sections_len = cursor - (config_base + section_start)

    blob_len = header_len + total_sections_len + 4  # trailing end marker
    end_address = (
        (wrong_base if wrong_base is not None else config_base)
        + blob_len
        - 4
    )

    out = bytearray(blob_len)
    out[0:4] = sig.cookie
    out[4:8] = end_address.to_bytes(4, "little")
    out[8:12] = (0x1400).to_bytes(4, "little")

    for i, addr in enumerate(addresses):
        offset = POINTER_TABLE_OFFSET + 4 * i
        out[offset : offset + 4] = addr.to_bytes(4, "little")
    terminator_offset = POINTER_TABLE_OFFSET + 4 * num_real
    out[terminator_offset : terminator_offset + 4] = (
        b"\x00\x00\x00\x01" if corrupt_terminator else b"\x00\x00\x00\x00"
    )

    padding_offset = terminator_offset + 4
    out[padding_offset : padding_offset + 3] = (
        b"\xff\x00\x00" if corrupt_padding else b"\x00\x00\x00"
    )
    marker_offset = padding_offset + 3
    out[marker_offset : marker_offset + 4] = (
        b"XXXX" if corrupt_header_marker else sig.header_end_marker
    )

    assert marker_offset + 4 == section_start
    for i, length in enumerate(section_lengths):
        fill = bytes([(i + 1) % 256]) * length
        start = section_start + sum(section_lengths[:i])
        out[start : start + length] = fill

    out[-4:] = b"YYYY" if corrupt_blob_marker else sig.blob_end_marker
    return bytes(out)


ARCH14_BASE = 0x030000
# 18 lengths, one per real section slot (arch 14 has 19 slots total, the
# last a null terminator). Shaped after a real Harmony 665 backup's own
# section lengths, scaled down for a fast test fixture.
ARCH14_LENGTHS = [
    1972, 7, 8, 14, 986, 16, 1000, 53, 2623,
    2316, 1940, 1427, 19, 260, 203, 28, 1, 500,
]


@pytest.fixture
def arch14_blob() -> bytes:
    return build_blob(14, ARCH14_BASE, ARCH14_LENGTHS)


def test_parses_a_well_formed_blob(arch14_blob):
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    assert header.architecture == 14
    assert header.cookie == b"GSPM"
    assert header.unknown_field == 0x1400
    assert header.config_base == ARCH14_BASE


def test_sections_have_correct_offsets_and_lengths(arch14_blob):
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    present = [s for s in header.sections if s.is_present]
    assert len(present) == len(ARCH14_LENGTHS)
    # The last real section has no next pointer to diff against, so its
    # length is deliberately None -- covered separately below.
    for section, expected_length in zip(
        present[:-1], ARCH14_LENGTHS[:-1], strict=True
    ):
        assert section.length == expected_length


def test_last_real_section_has_no_computed_length(arch14_blob):
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    present = [s for s in header.sections if s.is_present]
    assert present[-1].length is None
    assert all(s.length is not None for s in present[:-1])


def test_section_contents_are_readable(arch14_blob):
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    for i, expected_length in enumerate(ARCH14_LENGTHS[:-1]):
        data = header.read_section(arch14_blob, i)
        assert len(data) == expected_length
        assert data == bytes([(i + 1) % 256]) * expected_length


def test_reading_the_last_section_explains_why_it_cannot(arch14_blob):
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    last_index = len(ARCH14_LENGTHS) - 1
    with pytest.raises(BinaryFormatError, match="no computed length"):
        header.read_section(arch14_blob, last_index)


def test_section_lookup_rejects_unknown_index(arch14_blob):
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    with pytest.raises(BinaryFormatError, match="no section 99"):
        header.section(99)


def test_absent_section_is_reported_not_silently_zero(arch14_blob):
    # .section() returns a present-or-not answer for any in-range slot;
    # it does not raise just because the slot happens to be null.
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    terminator = header.section(len(ARCH14_LENGTHS))  # the terminator slot
    assert not terminator.is_present
    assert terminator.address == 0


def test_reading_an_absent_section_raises_rather_than_returning_garbage(
    arch14_blob,
):
    # read_section() is where "absent" actually becomes an error, since
    # there is nothing to read.
    header = parse_container(arch14_blob, architecture=14, config_base=ARCH14_BASE)
    with pytest.raises(BinaryFormatError, match="is null in this config"):
        header.read_section(arch14_blob, len(ARCH14_LENGTHS))


def test_unknown_architecture_lists_the_known_ones():
    with pytest.raises(BinaryFormatError, match="Known: 8, 9, 12, 14"):
        parse_container(b"\x00" * 100, architecture=255, config_base=0)


def test_wrong_cookie_is_reported_with_both_values(arch14_blob):
    corrupted = b"XXXX" + arch14_blob[4:]
    with pytest.raises(BinaryFormatError, match=r"GSPM.*XXXX"):
        parse_container(corrupted, architecture=14, config_base=ARCH14_BASE)


def test_non_null_terminator_is_rejected():
    blob = build_blob(14, ARCH14_BASE, ARCH14_LENGTHS, corrupt_terminator=True)
    with pytest.raises(BinaryFormatError, match="null terminator"):
        parse_container(blob, architecture=14, config_base=ARCH14_BASE)


def test_corrupt_padding_is_rejected():
    blob = build_blob(14, ARCH14_BASE, ARCH14_LENGTHS, corrupt_padding=True)
    with pytest.raises(BinaryFormatError, match="zero padding"):
        parse_container(blob, architecture=14, config_base=ARCH14_BASE)


def test_wrong_header_marker_is_rejected():
    blob = build_blob(14, ARCH14_BASE, ARCH14_LENGTHS, corrupt_header_marker=True)
    with pytest.raises(BinaryFormatError, match="header-end marker"):
        parse_container(blob, architecture=14, config_base=ARCH14_BASE)


def test_wrong_blob_end_marker_is_rejected():
    blob = build_blob(14, ARCH14_BASE, ARCH14_LENGTHS, corrupt_blob_marker=True)
    with pytest.raises(BinaryFormatError, match="truncated"):
        parse_container(blob, architecture=14, config_base=ARCH14_BASE)


def test_wrong_config_base_is_rejected(arch14_blob):
    with pytest.raises(BinaryFormatError, match="config_base mismatch"):
        parse_container(arch14_blob, architecture=14, config_base=0x999999)


def test_base_flag_bit_is_masked_before_giving_up():
    # Mirrors the real arch-9 discrepancy: concordance's documented
    # config_base for one architecture carries bit 23 set where the
    # header's own arithmetic does not.
    blob = build_blob(
        14, ARCH14_BASE | (1 << 23), ARCH14_LENGTHS, wrong_base=ARCH14_BASE
    )
    # The header computes a base of ARCH14_BASE from its own fields (since
    # we told build_blob the *real* base for its arithmetic via wrong_base,
    # while addressing sections against the flagged base) -- supplying the
    # flagged value should still be accepted once the flag bit is masked.
    header = parse_container(
        blob, architecture=14, config_base=ARCH14_BASE | (1 << 23)
    )
    assert header.config_base == ARCH14_BASE | (1 << 23)


@pytest.mark.parametrize("architecture", sorted(CONTAINER_SIGNATURES))
def test_every_known_architecture_round_trips_a_minimal_blob(architecture):
    sig = CONTAINER_SIGNATURES[architecture]
    lengths = [10] * (sig.slot_count - 1)
    blob = build_blob(architecture, 0x040000, lengths)
    header = parse_container(blob, architecture=architecture, config_base=0x040000)
    assert header.architecture == architecture
    assert len([s for s in header.sections if s.is_present]) == len(lengths)
