"""Encode/decode tests for the IR protocol codecs."""

import pytest

from harmonyforge.errors import IRError
from harmonyforge.ir import protocols
from harmonyforge.ir.signal import IRSignal


@pytest.mark.parametrize("address", [0, 1, 0x55, 0xAA, 0xFF])
@pytest.mark.parametrize("command", [0, 1, 0x3C, 0x80, 0xFF])
def test_nec_round_trip(address, command):
    signal = protocols.encode("NEC", address=address, command=command)
    decoded = protocols.identify(signal)
    assert decoded is not None
    assert decoded.protocol == "NEC"
    assert decoded.fields == {"address": address, "command": command}


def test_nec_carries_its_checksum():
    signal = protocols.encode("NEC", address=0x04, command=0x0C)
    # 32 bits -> leader pair + 32 bit pairs + trailer mark + gap
    assert len(signal.durations) == 2 + 64 + 2
    assert signal.frequency == 38000
    assert abs(signal.durations[0] - 9000) < 1
    assert abs(signal.durations[1] - 4500) < 1


@pytest.mark.parametrize("address", [0, 0x1234, 0xFFFF])
@pytest.mark.parametrize("command", [0, 0x56, 0xFF])
def test_necext_round_trip(address, command):
    signal = protocols.encode("NECext", address=address, command=command)
    decoded = protocols.identify(signal)
    assert decoded is not None
    assert decoded.fields["command"] == command
    # Plain NEC owns addresses whose halves are complementary.
    if (address & 0xFF) ^ ((address >> 8) & 0xFF) != 0xFF:
        assert decoded.protocol == "NECext"
        assert decoded.fields["address"] == address


def test_nec_and_necext_do_not_collide():
    # An address of 0x04 encodes as 04 FB in NEC, which NECext must decline.
    nec = protocols.encode("NEC", address=0x04, command=0x0C)
    assert protocols.NECExtended().decode(nec) is None
    assert protocols.NEC().decode(nec) is not None


@pytest.mark.parametrize("bits", [12, 15, 20])
def test_sirc_round_trip_all_widths(bits):
    signal = protocols.encode(
        "SIRC", address=1, command=0x15, extended=0x2A, bits=bits
    )
    decoded = protocols.identify(signal)
    assert decoded is not None
    assert decoded.protocol == "SIRC"
    assert decoded.fields["command"] == 0x15
    assert decoded.fields["bits"] == bits


def test_sirc_emits_three_frames_by_default():
    one = protocols.encode("SIRC", address=1, command=1, repeats=1)
    three = protocols.encode("SIRC", address=1, command=1, repeats=3)
    assert len(three.durations) == 3 * len(one.durations)


def test_sirc_rejects_bad_width():
    with pytest.raises(IRError, match="12, 15 or 20"):
        protocols.encode("SIRC", bits=13)


@pytest.mark.parametrize("address", range(0, 32, 7))
@pytest.mark.parametrize("command", [0, 1, 0x3F, 0x40, 0x7F])
@pytest.mark.parametrize("toggle", [0, 1])
def test_rc5_round_trip(address, command, toggle):
    signal = protocols.encode(
        "RC5", address=address, command=command, toggle=toggle
    )
    decoded = protocols.identify(signal)
    assert decoded is not None
    assert decoded.protocol == "RC5"
    assert decoded.fields == {
        "address": address,
        "command": command,
        "toggle": toggle,
    }


def test_rc5_extended_commands_use_the_field_bit():
    low = protocols.encode("RC5", address=5, command=0x05)
    high = protocols.encode("RC5", address=5, command=0x45)
    assert protocols.identify(low).fields["command"] == 0x05
    assert protocols.identify(high).fields["command"] == 0x45


def test_rc5_uses_36khz():
    assert protocols.encode("RC5", address=1, command=1).frequency == 36000


def test_kaseikyo_defaults_to_panasonic_and_checksums():
    signal = protocols.encode("Kaseikyo", address=0x80, command=0x3D)
    decoded = protocols.identify(signal)
    assert decoded.protocol == "Panasonic"
    assert decoded.fields["vendor"] == 0x2002
    assert decoded.fields["address"] == 0x80
    assert decoded.fields["command"] == 0x3D


def test_kaseikyo_other_vendor_keeps_generic_name():
    signal = protocols.encode(
        "Kaseikyo", vendor=0x5555, address=1, command=2
    )
    assert protocols.identify(signal).protocol == "Kaseikyo"


def test_samsung_requires_matching_address_halves():
    signal = protocols.encode("Samsung32", address=7, command=2)
    decoded = protocols.identify(signal)
    assert decoded.protocol == "Samsung32"
    assert decoded.fields == {"address": 7, "command": 2}


def test_jvc_round_trip():
    signal = protocols.encode("JVC", address=3, command=0x1B)
    decoded = protocols.identify(signal)
    assert decoded.protocol == "JVC"
    assert decoded.fields == {"address": 3, "command": 0x1B}


def test_identify_returns_none_for_noise():
    noise = IRSignal(frequency=38000, durations=(123, 456, 789, 321))
    assert protocols.identify(noise) is None


def test_identify_tolerates_jitter():
    clean = protocols.encode("NEC", address=0x04, command=0x0C)
    jittered = IRSignal(
        frequency=37900,
        durations=tuple(
            d + (37 if i % 3 == 0 else -29) for i, d in enumerate(clean.durations)
        ),
    )
    decoded = protocols.identify(jittered)
    assert decoded is not None
    assert decoded.fields == {"address": 0x04, "command": 0x0C}


def test_command_value_packs_bits():
    signal = protocols.encode("JVC", address=0x03, command=0x1B)
    decoded = protocols.identify(signal)
    assert decoded.value == int("".join(str(b) for b in decoded.bits), 2)


def test_aliases_resolve():
    assert protocols.get("sony") is protocols.get("SIRC")
    assert protocols.get("panasonic") is protocols.get("Kaseikyo")
    assert protocols.get("NEC") is protocols.get("nec")


def test_unknown_protocol_lists_alternatives():
    with pytest.raises(IRError, match="Known:"):
        protocols.get("Betamax")


@pytest.mark.parametrize(
    "name,fields",
    [
        ("NEC", {"address": 256, "command": 0}),
        ("NEC", {"address": 0, "command": -1}),
        ("RC5", {"address": 32, "command": 0}),
        ("RC5", {"address": 0, "command": 128}),
        ("JVC", {"address": 0, "command": 300}),
    ],
)
def test_out_of_range_fields_are_rejected(name, fields):
    with pytest.raises(IRError):
        protocols.encode(name, **fields)
