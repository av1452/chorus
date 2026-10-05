"""Pronto hex conversion tests."""

import pytest

from harmonyforge.errors import IRError
from harmonyforge.ir import pronto, protocols
from harmonyforge.ir.signal import IRSignal


def build_nec_pronto() -> str:
    """A structurally valid NEC code: 34 once-pairs + 2 repeat-pairs."""
    bits = [0] * 8 + [1] * 8 + [0, 1] * 8
    words = ["0157", "00AB"]
    for bit in bits:
        words += ["0015", "0040" if bit else "0015"]
    words += ["0015", "0689"]
    repeat = ["0157", "0055", "0015", "0E48"]
    header = ["0000", "006D", f"{len(words) // 2:04X}", f"{len(repeat) // 2:04X}"]
    return " ".join(header + words + repeat)


def test_frequency_and_divisor_round_trip():
    assert pronto.divisor_for(38000) == 0x6D
    assert pronto.frequency_for(0x6D) == 38029
    assert pronto.divisor_for(pronto.frequency_for(0x6D)) == 0x6D


def test_parse_nec_code_has_correct_leader():
    signal = pronto.parse(build_nec_pronto())
    assert abs(signal.frequency - 38000) < 100
    # NEC's leader is 9000 us mark, 4500 us space.
    assert abs(signal.durations[0] - 9000) < 60
    assert abs(signal.durations[1] - 4500) < 60


def test_parse_is_lenient_about_separators():
    code = build_nec_pronto()
    variants = [
        code.lower(),
        code.replace(" ", ",  "),
        "  " + code + "  ",
        " ".join("0x" + w for w in code.split()),
    ]
    reference = pronto.parse(code)
    for variant in variants:
        assert pronto.parse(variant).durations == reference.durations


def test_round_trip_is_lossless():
    original = pronto.parse(build_nec_pronto())
    again = pronto.parse(pronto.format_signal(original, repeat_pairs=2))
    assert again.durations == original.durations
    assert again.frequency == original.frequency


def test_header_pair_counts_are_written_correctly():
    signal = protocols.encode("NEC", address=4, command=12)
    words = pronto.format_signal(signal, repeat_pairs=0).split()
    assert words[0] == "0000"
    once_pairs = int(words[2], 16)
    assert int(words[3], 16) == 0
    assert len(words) - 4 == once_pairs * 2


def test_repeat_split_moves_pairs_to_the_repeat_sequence():
    signal = protocols.encode("NEC", address=4, command=12)
    words = pronto.format_signal(signal, repeat_pairs=3).split()
    assert int(words[3], 16) == 3


def test_odd_duration_count_is_padded_to_a_pair():
    signal = IRSignal(frequency=38000, durations=(1000, 500, 1000))
    words = pronto.format_signal(signal).split()
    assert int(words[2], 16) == 2  # two full pairs
    assert len(words) == 4 + 4


def test_unmodulated_format():
    signal = IRSignal(frequency=38000, durations=(1000, 500))
    words = pronto.format_signal(signal, modulated=False).split()
    assert words[0] == "0100"
    assert pronto.parse(" ".join(words)).frequency == pronto.UNMODULATED_REFERENCE_HZ


def test_rejects_truncated_header():
    with pytest.raises(IRError, match="4-word header"):
        pronto.parse("0000 006D 0001")


def test_rejects_wrong_pair_count():
    with pytest.raises(IRError, match="promises"):
        pronto.parse("0000 006D 0002 0000 0157 00AB")


def test_rejects_database_codes():
    with pytest.raises(IRError, match="unsupported Pronto format"):
        pronto.parse("5000 006D 0000 0000")


def test_rejects_non_hex():
    with pytest.raises(IRError, match="not a hex word"):
        pronto.parse("0000 006D 0001 0000 ZZZZ 00AB")


def test_rejects_empty():
    with pytest.raises(IRError, match="empty"):
        pronto.parse("   ")
