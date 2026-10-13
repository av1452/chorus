"""The raw IR signal type everything else converts to and from."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..errors import IRError

#: Carrier frequencies we will snap a measured value to, since the remote's
#: learning eye reports a noisy estimate.
COMMON_FREQUENCIES = (
    30000, 33000, 36000, 36700, 38000, 40000, 56000, 415000, 455000,
)


@dataclass(frozen=True)
class IRSignal:
    """A modulated IR burst: a carrier frequency plus alternating durations.

    ``durations`` is in microseconds and strictly alternates mark (carrier
    on) and space (carrier off), starting with a mark. A trailing space is
    conventional but optional -- it encodes the gap before a repeat.
    """

    frequency: int
    durations: tuple[int, ...]
    name: str = ""

    def __post_init__(self) -> None:
        if self.frequency <= 0:
            raise IRError(f"carrier frequency must be positive, got {self.frequency}")
        if not self.durations:
            raise IRError("signal has no durations")
        if any(d < 0 for d in self.durations):
            raise IRError("signal contains a negative duration")

    @property
    def marks(self) -> tuple[int, ...]:
        """Carrier-on durations."""
        return self.durations[0::2]

    @property
    def spaces(self) -> tuple[int, ...]:
        """Carrier-off durations."""
        return self.durations[1::2]

    @property
    def total_us(self) -> int:
        return sum(self.durations)

    @property
    def period_us(self) -> float:
        """Carrier period, in microseconds."""
        return 1_000_000 / self.frequency

    def snapped(self, tolerance: float = 0.06) -> IRSignal:
        """Return a copy with the carrier snapped to the nearest common value.

        A learned frequency of 37904 Hz is almost certainly a 38 kHz device;
        storing the raw estimate makes codes needlessly device-specific.

        Picks the *nearest* candidate, not merely the first one in tolerance:
        36 kHz and 38 kHz are only 5.4% apart, so a first-match scan would
        drag a 37.9 kHz capture down to 36 kHz.
        """
        candidates = [
            candidate
            for candidate in COMMON_FREQUENCIES
            if abs(self.frequency - candidate) <= candidate * tolerance
        ]
        if not candidates:
            return self
        nearest = min(candidates, key=lambda c: abs(self.frequency - c))
        return replace(self, frequency=nearest)

    def without_trailing_space(self) -> IRSignal:
        """Drop a trailing space, if present."""
        if len(self.durations) % 2 == 0:
            return replace(self, durations=self.durations[:-1])
        return self

    def with_gap(self, gap_us: int) -> IRSignal:
        """Ensure the signal ends with a space of at least ``gap_us``."""
        durations = list(self.durations)
        if len(durations) % 2 == 0:
            durations[-1] = max(durations[-1], gap_us)
        else:
            durations.append(gap_us)
        return replace(self, durations=tuple(durations))

    def quantized(self, step_us: int = 10) -> IRSignal:
        """Round every duration to a multiple of ``step_us``.

        Learned signals carry measurement jitter; quantizing makes otherwise
        identical captures compare equal.
        """
        if step_us <= 1:
            return self
        rounded = tuple(
            max(step_us, round(d / step_us) * step_us) if d else 0
            for d in self.durations
        )
        return replace(self, durations=rounded)

    def matches(self, other: IRSignal, tolerance: float = 0.2) -> bool:
        """Compare two signals allowing per-duration drift.

        Used to tell whether two captures of the same button agree.
        """
        if len(self.durations) != len(other.durations):
            return False
        if abs(self.frequency - other.frequency) > 0.15 * max(
            self.frequency, other.frequency
        ):
            return False
        for a, b in zip(self.durations, other.durations, strict=True):
            allowance = max(100, tolerance * max(a, b))
            if abs(a - b) > allowance:
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "frequency": self.frequency,
            "durations": list(self.durations),
        }

    @classmethod
    def from_dict(cls, data: dict) -> IRSignal:
        return cls(
            frequency=int(data["frequency"]),
            durations=tuple(int(d) for d in data["durations"]),
            name=data.get("name", ""),
        )

    def __str__(self) -> str:
        label = f"{self.name}: " if self.name else ""
        return (
            f"{label}{self.frequency / 1000:.1f} kHz, "
            f"{len(self.durations)} durations, {self.total_us / 1000:.1f} ms"
        )


def average(signals: list[IRSignal]) -> IRSignal:
    """Average several captures of the same button into one cleaner signal.

    Raises :class:`IRError` if the captures disagree on structure, which
    usually means one of them was a misfire.
    """
    if not signals:
        raise IRError("nothing to average")
    if len(signals) == 1:
        return signals[0]

    reference = signals[0]
    for candidate in signals[1:]:
        if len(candidate.durations) != len(reference.durations):
            raise IRError(
                "captures have different lengths "
                f"({len(reference.durations)} vs {len(candidate.durations)}) "
                "-- recapture, keeping the remote still and pressing once"
            )

    count = len(signals)
    durations = tuple(
        sum(s.durations[i] for s in signals) // count
        for i in range(len(reference.durations))
    )
    frequency = sum(s.frequency for s in signals) // count
    return IRSignal(frequency=frequency, durations=durations, name=reference.name)
