"""IRSignal behaviour."""

import pytest

from chorus.errors import IRError
from chorus.ir.signal import IRSignal, average


def make(*durations, frequency=38000):
    return IRSignal(frequency=frequency, durations=durations)


def test_marks_and_spaces_alternate():
    signal = make(100, 200, 300, 400)
    assert signal.marks == (100, 300)
    assert signal.spaces == (200, 400)
    assert signal.total_us == 1000


def test_rejects_invalid_signals():
    with pytest.raises(IRError, match="positive"):
        IRSignal(frequency=0, durations=(1,))
    with pytest.raises(IRError, match="no durations"):
        IRSignal(frequency=38000, durations=())
    with pytest.raises(IRError, match="negative"):
        IRSignal(frequency=38000, durations=(100, -5))


def test_snapping_pulls_a_noisy_carrier_to_a_standard_value():
    assert make(100, frequency=37904).snapped().frequency == 38000
    assert make(100, frequency=36700).snapped().frequency == 36700
    # Far-off values are left alone rather than mangled.
    assert make(100, frequency=12345).snapped().frequency == 12345


def test_quantize_rounds_to_a_step():
    signal = make(997, 1003, 561).quantized(10)
    assert signal.durations == (1000, 1000, 560)


def test_with_gap_and_trailing_space_helpers():
    assert make(100, 200).without_trailing_space().durations == (100,)
    assert make(100).without_trailing_space().durations == (100,)
    assert make(100).with_gap(5000).durations == (100, 5000)
    assert make(100, 200).with_gap(5000).durations == (100, 5000)
    # An existing larger gap is preserved.
    assert make(100, 9000).with_gap(5000).durations == (100, 9000)


def test_matches_allows_drift_but_not_structural_change():
    a = make(1000, 500, 1000)
    assert a.matches(make(1030, 480, 970))
    assert not a.matches(make(1000, 500))
    assert not a.matches(make(1000, 500, 1000, 500))
    assert not a.matches(make(1000, 500, 1000, frequency=56000))


def test_average_of_one_is_itself():
    signal = make(1000, 500)
    assert average([signal]) is signal


def test_average_smooths_captures():
    result = average([make(1000, 500), make(1100, 450), make(900, 550)])
    assert result.durations == (1000, 500)


def test_average_rejects_mismatched_captures():
    with pytest.raises(IRError, match="different lengths"):
        average([make(1000, 500), make(1000, 500, 1000)])
    with pytest.raises(IRError, match="nothing to average"):
        average([])


def test_dict_round_trip():
    signal = IRSignal(frequency=40000, durations=(1, 2, 3), name="Power")
    assert IRSignal.from_dict(signal.to_dict()) == signal
