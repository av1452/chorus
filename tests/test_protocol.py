"""Wire-format tests for the USB protocol layer."""

import pytest

from harmonyforge.usb import protocol as p


def test_get_version_packet():
    packet = p.get_version()
    assert len(packet) == 64
    assert packet[0] == 0x10
    assert packet[1:] == bytes(63)


def test_read_flash_packet_layout():
    packet = p.read_flash(0x020000, 1024)
    # command 0x50 | length code 5
    assert packet[0] == 0x55
    # 24-bit big-endian address
    assert packet[1:4] == bytes([0x02, 0x00, 0x00])
    # 16-bit big-endian length
    assert packet[4:6] == bytes([0x04, 0x00])


def test_write_flash_setup_layout():
    packet = p.write_flash_setup(0x1D0000, 3150)
    assert packet[0] == 0x35
    assert packet[1:4] == bytes([0x1D, 0x00, 0x00])
    assert int.from_bytes(packet[4:6], "big") == 3150


def test_erase_and_done_have_fixed_length_codes():
    assert p.erase_flash(0x004000)[0] == 0xD3
    assert p.done(p.COMMAND_WRITE_FLASH)[:2] == bytes([0xF1, 0x30])
    assert p.reset(p.RESET_DEVICE)[:2] == bytes([0xE1, 0x02])


def test_invalidate_flash_is_a_misc_write():
    packet = p.invalidate_flash()
    assert packet[0] == p.COMMAND_WRITE_MISC | 0x01
    assert packet[1] == p.MISC_INVALIDATE_FLASH


def test_report_length_is_honoured():
    assert len(p.get_version(8)) == 8
    with pytest.raises(ValueError):
        p.read_flash(0, 0, report_len=4)  # 6-byte payload will not fit


@pytest.mark.parametrize(
    "outstanding,expected_len",
    [(3150, 63), (63, 63), (62, 31), (31, 31), (30, 15), (7, 7), (5, 5), (1, 1)],
)
def test_pick_write_block_picks_largest_that_fits(outstanding, expected_len):
    code, length = p.pick_write_block(outstanding, protocol=1)
    assert length == expected_len
    # The length code must round-trip through the table.
    table = p.WRITE_LEN_MAP
    assert table[table[0] - code + 1] == length


def test_pick_write_block_protocol_zero():
    assert p.pick_write_block(749, protocol=0) == (7, 7)
    assert p.pick_write_block(2, protocol=0)[1] == 2


def test_read_len_maps_differ_by_protocol():
    assert p.read_len_map(0)[8] == 7
    assert p.read_len_map(1)[8] == 14
    assert p.max_read_chunk(0) == 700
    assert p.max_read_chunk(1) == 1022


def test_parse_splits_command_and_length():
    response = p.parse(bytes([0x27, 0x32]) + bytes(62))
    assert response.command == p.RESPONSE_VERSION_DATA
    assert response.length_code == 7
    assert not response.is_done


def test_parse_rejects_empty():
    with pytest.raises(ValueError):
        p.parse(b"")


def test_check_sequence_accepts_match_and_880_glitch():
    assert p.check_sequence(0x01, 0x01) == 0x01
    # The documented Harmony 880 firmware glitch.
    assert p.check_sequence(0x1F, 0x10) == 0x1F


def test_check_sequence_rejects_real_mismatch():
    with pytest.raises(ValueError, match="out-of-order"):
        p.check_sequence(0x05, 0x01)
