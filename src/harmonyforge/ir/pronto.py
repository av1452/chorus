"""Pronto hex ("CCF") conversion.

Pronto hex is the lingua franca of IR code sharing -- remotecentral.com,
JP1 and most AV forums publish codes in this format, which makes it the
practical replacement for Logitech's retired device database.

Format, as space-separated 4-digit hex words:

===== ==========================================================
word  meaning
===== ==========================================================
0     format: 0000 = raw modulated, 0100 = raw unmodulated
1     carrier divisor; ``carrier_hz = 4145146 / divisor``
2     burst-pair count of the "once" sequence
3     burst-pair count of the "repeat" sequence
4..   alternating mark/space durations, in carrier cycles
===== ==========================================================
"""

from __future__ import annotations

from ..errors import IRError
from .signal import IRSignal

#: Pronto's reference clock, in Hz. A divisor word of 0x006D gives 38028 Hz.
PRONTO_CLOCK = 4_145_146

FORMAT_RAW_MODULATED = 0x0000
FORMAT_RAW_UNMODULATED = 0x0100

#: Carrier assumed for unmodulated (0100) codes, which carry no divisor.
UNMODULATED_REFERENCE_HZ = 38_000


def divisor_for(frequency: int) -> int:
    """Pronto divisor word for a carrier frequency in Hz."""
    if frequency <= 0:
        raise IRError(f"carrier frequency must be positive, got {frequency}")
    divisor = round(PRONTO_CLOCK / frequency)
    if not 1 <= divisor <= 0xFFFF:
        raise IRError(f"carrier {frequency} Hz is outside Pronto's range")
    return divisor


def frequency_for(divisor: int) -> int:
    """Carrier frequency in Hz for a Pronto divisor word."""
    if divisor <= 0:
        raise IRError("Pronto divisor must be positive")
    return round(PRONTO_CLOCK / divisor)


def parse(text: str) -> IRSignal:
    """Parse a Pronto hex string into an :class:`IRSignal`.

    Accepts the usual sloppiness: any whitespace as separator, optional
    ``0x`` prefixes, upper or lower case. Both the "once" and "repeat"
    sequences are concatenated, which is what you want when sending a
    single press.
    """
    cleaned = text.replace(",", " ").replace("0x", " ").replace("0X", " ")
    tokens = cleaned.split()
    if not tokens:
        raise IRError("empty Pronto string")

    try:
        words = [int(t, 16) for t in tokens]
    except ValueError as exc:
        bad = next(t for t in tokens if not _is_hex(t))
        raise IRError(f"{bad!r} is not a hex word in this Pronto code") from exc

    if len(words) < 4:
        raise IRError(
            f"Pronto codes need at least a 4-word header, got {len(words)} words"
        )
    if any(w > 0xFFFF for w in words):
        raise IRError("Pronto words must be 4 hex digits (0000-FFFF)")

    fmt, divisor, once_pairs, repeat_pairs = words[:4]

    if fmt == FORMAT_RAW_UNMODULATED:
        frequency = UNMODULATED_REFERENCE_HZ
    elif fmt == FORMAT_RAW_MODULATED:
        frequency = frequency_for(divisor)
    else:
        raise IRError(
            f"unsupported Pronto format word {fmt:04X}. Only raw codes "
            "(0000 and 0100) are supported; 5000/5001-style codes reference "
            "a Pronto-internal database and cannot be converted."
        )

    payload = words[4:]
    expected = (once_pairs + repeat_pairs) * 2
    if expected and len(payload) != expected:
        raise IRError(
            f"Pronto header promises {expected} duration words "
            f"({once_pairs} once + {repeat_pairs} repeat pairs) but "
            f"{len(payload)} follow"
        )
    if not payload:
        raise IRError("Pronto code has a header but no burst data")

    period_us = 1_000_000 / frequency
    durations = tuple(max(1, round(cycles * period_us)) for cycles in payload)
    return IRSignal(frequency=frequency, durations=durations)


def format_signal(
    signal: IRSignal,
    *,
    repeat_pairs: int = 0,
    modulated: bool = True,
) -> str:
    """Render an :class:`IRSignal` as a Pronto hex string.

    ``repeat_pairs`` splits the tail of the signal into the repeat sequence;
    the default of 0 puts everything in the "once" sequence, which is what
    most tools expect from a learned code.
    """
    durations = list(signal.durations)
    if len(durations) % 2:
        # Pronto counts burst *pairs*, so a dangling mark needs a space.
        durations.append(max(signal.durations[-1] * 2, 10_000))

    period_us = 1_000_000 / signal.frequency
    cycles = [min(0xFFFF, max(1, round(d / period_us))) if d else 0 for d in durations]

    total_pairs = len(cycles) // 2
    if repeat_pairs < 0 or repeat_pairs > total_pairs:
        raise IRError(
            f"repeat_pairs must be between 0 and {total_pairs}, got {repeat_pairs}"
        )
    once_pairs = total_pairs - repeat_pairs

    fmt = FORMAT_RAW_MODULATED if modulated else FORMAT_RAW_UNMODULATED
    divisor = divisor_for(signal.frequency) if modulated else 0
    words = [fmt, divisor, once_pairs, repeat_pairs, *cycles]
    return " ".join(f"{w:04X}" for w in words)


def _is_hex(token: str) -> bool:
    try:
        int(token, 16)
        return True
    except ValueError:
        return False
