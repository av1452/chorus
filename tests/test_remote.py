"""End-to-end tests against the simulated remote."""

import pytest

from chorus import devicedb
from chorus.errors import ProtocolError, UnsupportedRemoteError, VerifyError
from chorus.usb import protocol as p
from chorus.usb.remote import HarmonyRemote, _format_guid
from chorus.usb.transport import FakeTransport


def make_remote(**kwargs) -> tuple[HarmonyRemote, FakeTransport]:
    transport = FakeTransport(**kwargs)
    arch = devicedb.architecture(7)
    # A valid config: the arch-7 cookie, then an end vector at offset 5.
    header = bytearray(1024)
    header[0:4] = arch.cookie.to_bytes(4, "little")
    end = arch.config_base - arch.flash_base + 4096
    header[arch.end_vector : arch.end_vector + 3] = end.to_bytes(3, "little")
    transport.seed_config(arch.config_base, bytes(header))
    return HarmonyRemote(transport), transport


def test_identify_parses_the_version_response():
    remote, _ = make_remote()
    identity = remote.identify()

    assert identity.firmware_version == (3, 2)
    assert identity.hardware_version == (1, 0, 0)
    assert identity.architecture_index == 7
    assert identity.skin == 72
    assert identity.model.name == "Harmony 650"
    assert identity.flash.name == "AMD Am29LV160BB"
    assert identity.protocol == 7
    assert identity.name == "Logitech Harmony 650"


def test_identify_detects_a_valid_config():
    remote, _ = make_remote()
    identity = remote.identify()
    assert identity.valid_config
    assert identity.config_bytes_used == 4100
    assert identity.max_config_size > 0
    assert 0.0 < identity.config_usage < 1.0
    assert "Harmony 650" in identity.summary()


def test_identify_flags_a_blank_config():
    transport = FakeTransport()
    remote = HarmonyRemote(transport)
    identity = remote.identify()
    assert not identity.valid_config
    assert identity.config_bytes_used == 0


def test_identify_rejects_a_wrong_response():
    transport = FakeTransport(identity=bytes([0x99, 0, 0, 0, 0, 0, 0, 0]))
    with pytest.raises(ProtocolError, match="expected a version response"):
        HarmonyRemote(transport).identify()


def test_identify_rejects_a_bad_length_code():
    transport = FakeTransport(identity=bytes([0x23, 0x32, 0x10, 0x49, 0x01]))
    with pytest.raises(ProtocolError, match="unexpected length code"):
        HarmonyRemote(transport).identify()


def test_short_identity_defaults_to_architecture_2():
    transport = FakeTransport(
        identity=bytes([0x25, 0x21, 0x10, 0x37, 0x01]) + bytes(59)
    )
    identity = HarmonyRemote(transport).identify()
    assert identity.architecture_index == 2
    assert identity.skin == 2
    assert identity.protocol == 0


def test_the_first_packet_sent_is_get_version():
    remote, transport = make_remote()
    remote.identify()
    assert transport.written[0][0] == p.COMMAND_GET_VERSION


def test_flash_write_read_round_trip():
    remote, transport = make_remote()
    remote.identify()

    payload = bytes((i * 7 + 3) & 0xFF for i in range(2000))
    remote.write_flash(0x030000, payload)
    assert remote.read_flash(0x030000, len(payload)) == payload


@pytest.mark.parametrize("size", [1, 5, 31, 63, 64, 100, 1022, 1023, 3151])
def test_round_trip_at_block_boundaries(size):
    """Exercise every write-block size and the chunk boundary."""
    remote, transport = make_remote()
    remote.identify()
    payload = bytes((i * 31 + 11) & 0xFF for i in range(size))
    remote.write_flash(0x040000, payload)
    assert remote.read_flash(0x040000, size) == payload


def test_verify_flash_passes_and_fails_precisely():
    remote, transport = make_remote()
    remote.identify()
    payload = bytes(range(64))
    remote.write_flash(0x050000, payload)

    remote.verify_flash(0x050000, payload)  # no exception

    wrong = bytearray(payload)
    wrong[10] ^= 0xFF
    with pytest.raises(VerifyError, match="0x05000A"):
        remote.verify_flash(0x050000, bytes(wrong))


def test_write_config_erases_writes_verifies_and_invalidates():
    remote, transport = make_remote()
    remote.identify()
    transport.written.clear()

    blob = bytes((i * 13) & 0xFF for i in range(512))
    remote.write_config(blob, verify=True)

    sent = [pkt[0] for pkt in transport.written]
    assert p.COMMAND_ERASE_FLASH in sent
    assert any(b & p.COMMAND_MASK == p.COMMAND_WRITE_FLASH for b in sent)
    assert any(b & p.COMMAND_MASK == p.COMMAND_READ_FLASH for b in sent)
    assert any(b == (p.COMMAND_WRITE_MISC | 0x01) for b in sent)

    arch = devicedb.architecture(7)
    assert remote.read_flash(arch.config_base, len(blob)) == blob


def test_write_config_refuses_an_oversized_blob():
    remote, _ = make_remote()
    identity = remote.identify()
    too_big = bytes(identity.flash.size_bytes + 1)
    with pytest.raises(ProtocolError, match="only"):
        remote.write_config(too_big)


def test_read_config_reads_only_the_used_bytes():
    remote, _ = make_remote()
    identity = remote.identify()
    assert len(remote.read_config()) == identity.config_bytes_used


def test_unsupported_architecture_is_reported_clearly():
    # Architecture 0 is a placeholder with no layout data.
    transport = FakeTransport(
        identity=bytes([0x27, 0x32, 0x10, 0x49, 0x01, 0x00, 72, 0x00]) + bytes(56)
    )
    remote = HarmonyRemote(transport)
    remote.identify()
    with pytest.raises(UnsupportedRemoteError, match="no known memory layout"):
        remote.read_config()


def test_region_table_architectures_are_declined_not_corrupted():
    transport = FakeTransport(
        identity=bytes([0x27, 0x32, 0x10, 0x49, 0x01, 0xA0, 19, 0x0A]) + bytes(56)
    )
    remote = HarmonyRemote(transport)
    remote.identify()
    with pytest.raises(UnsupportedRemoteError, match="region table"):
        remote.read_config()


def test_erase_covers_the_requested_range():
    remote, transport = make_remote()
    remote.identify()
    remote.write_flash(0x030000, bytes([0xAA] * 16))
    remote.erase_flash(0x030000, 16)
    # Erased flash reads back as 0xFF.
    assert remote.read_flash(0x030000, 16) == bytes([0xFF] * 16)


def test_progress_callback_receives_monotonic_counts():
    remote, _ = make_remote()
    remote.identify()
    seen = []
    remote.write_flash(
        0x030000, bytes(5000), progress=lambda done, total, _: seen.append(
            (done, total)
        )
    )
    assert seen
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)
    assert seen[-1][0] == 5000


def test_reset_survives_a_transport_that_drops():
    class Dropping(FakeTransport):
        def write(self, data):
            raise OSError("device went away")

    remote = HarmonyRemote(Dropping())
    remote.identity = None
    remote.reset()  # must not raise


def test_guid_formatting_both_orders():
    raw = bytes(range(16))
    swapped = _format_guid(raw, byte_swapped=True)
    straight = _format_guid(raw, byte_swapped=False)
    assert swapped == "03020100-0504-0706-0809-0A0B0C0D0E0F"
    assert straight == "00010203-0405-0607-0809-0A0B0C0D0E0F"
    assert len(swapped.split("-")) == 5
