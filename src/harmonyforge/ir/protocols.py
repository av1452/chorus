"""Encoders and decoders for the common consumer IR protocols.

Two jobs here. First, *encoding*: given a protocol and a device/command
number from a code list, synthesise the IR waveform -- this is how you add a
device without owning its original remote. Second, *decoding*: given a
learned capture, work out which protocol it is and what it says, which both
names the code for you and lets you generate the buttons you did not capture.

Timings follow the published protocol specifications. Decoding uses
proportional tolerance because learned captures carry real measurement
jitter.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from ..errors import IRError
from .signal import IRSignal


@dataclass(frozen=True)
class IRCommand:
    """A decoded IR command."""

    protocol: str
    #: Protocol-specific named values, e.g. ``{"address": 4, "command": 12}``.
    fields: dict[str, int] = field(default_factory=dict)
    #: The raw payload bits, most significant first.
    bits: tuple[int, ...] = ()

    @property
    def value(self) -> int:
        """The payload bits packed into a single integer."""
        out = 0
        for bit in self.bits:
            out = (out << 1) | bit
        return out

    def __str__(self) -> str:
        if self.fields:
            parts = ", ".join(
                f"{k}=0x{v:02X}" for k, v in self.fields.items()
            )
            return f"{self.protocol} ({parts})"
        return f"{self.protocol} (0x{self.value:X})"


def _within(actual: int, expected: int, tolerance: float, floor: int) -> bool:
    return abs(actual - expected) <= max(floor, expected * tolerance)


class Protocol:
    """Base class for an IR protocol codec."""

    name: ClassVar[str] = ""
    carrier: ClassVar[int] = 38000
    #: Absolute slack, in microseconds, allowed on every duration.
    jitter_us: ClassVar[int] = 200
    #: Proportional slack allowed on every duration.
    tolerance: ClassVar[float] = 0.3

    def encode(self, **fields: int) -> IRSignal:  # pragma: no cover - abstract
        raise NotImplementedError

    def decode(self, signal: IRSignal) -> IRCommand | None:  # pragma: no cover
        raise NotImplementedError

    def _ok(self, actual: int, expected: int) -> bool:
        return _within(actual, expected, self.tolerance, self.jitter_us)

    def _carrier_ok(self, signal: IRSignal) -> bool:
        return abs(signal.frequency - self.carrier) <= 0.2 * self.carrier


# ---------------------------------------------------------------------------
# Pulse-distance family: a leader, then bits distinguished by space length.
# NEC, Samsung, JVC and Panasonic all share this shape.
# ---------------------------------------------------------------------------


class PulseDistanceProtocol(Protocol):
    """Bits encoded as a fixed mark followed by a short or long space."""

    leader_mark: ClassVar[int] = 9000
    leader_space: ClassVar[int] = 4500
    bit_mark: ClassVar[int] = 560
    zero_space: ClassVar[int] = 560
    one_space: ClassVar[int] = 1690
    trailer_mark: ClassVar[int] = 560
    gap: ClassVar[int] = 40000
    bit_count: ClassVar[int] = 32
    #: True if each byte goes out least-significant bit first.
    lsb_first: ClassVar[bool] = True

    def _bits_to_signal(self, bits: Sequence[int]) -> IRSignal:
        durations = [self.leader_mark, self.leader_space]
        for bit in bits:
            durations.append(self.bit_mark)
            durations.append(self.one_space if bit else self.zero_space)
        durations.append(self.trailer_mark)
        durations.append(self.gap)
        return IRSignal(frequency=self.carrier, durations=tuple(durations))

    def _bytes_to_bits(self, values: Iterable[int]) -> list[int]:
        bits: list[int] = []
        for value in values:
            order = range(8) if self.lsb_first else range(7, -1, -1)
            for i in order:
                bits.append((value >> i) & 1)
        return bits

    def _bits_to_bytes(self, bits: Sequence[int]) -> list[int]:
        out = []
        for start in range(0, len(bits), 8):
            chunk = bits[start : start + 8]
            if len(chunk) < 8:
                break
            value = 0
            if self.lsb_first:
                for i, bit in enumerate(chunk):
                    value |= bit << i
            else:
                for bit in chunk:
                    value = (value << 1) | bit
            out.append(value)
        return out

    def _decode_bits(self, signal: IRSignal) -> list[int] | None:
        d = signal.durations
        needed = 2 + self.bit_count * 2 + 1
        if len(d) < needed:
            return None
        if not self._ok(d[0], self.leader_mark) or not self._ok(
            d[1], self.leader_space
        ):
            return None

        bits: list[int] = []
        for i in range(self.bit_count):
            mark = d[2 + i * 2]
            space = d[3 + i * 2]
            if not self._ok(mark, self.bit_mark):
                return None
            if self._ok(space, self.one_space):
                bits.append(1)
            elif self._ok(space, self.zero_space):
                bits.append(0)
            else:
                return None
        return bits


class NEC(Protocol):
    """NEC, the most common protocol: 8-bit address + 8-bit command.

    Sends address, inverted address, command, inverted command -- the
    inversions are a checksum, and verifying them makes NEC decoding
    very reliable.
    """

    name = "NEC"
    carrier = 38000

    class _Frame(PulseDistanceProtocol):
        carrier = 38000
        leader_mark = 9000
        leader_space = 4500
        bit_mark = 560
        zero_space = 560
        one_space = 1690
        trailer_mark = 560
        gap = 40000
        bit_count = 32
        lsb_first = True

    def __init__(self) -> None:
        self._frame = self._Frame()

    def encode(self, *, address: int = 0, command: int = 0, **_: int) -> IRSignal:
        if not 0 <= address <= 0xFF:
            raise IRError(f"NEC address must be 0-255, got {address}")
        if not 0 <= command <= 0xFF:
            raise IRError(f"NEC command must be 0-255, got {command}")
        payload = [address, (~address) & 0xFF, command, (~command) & 0xFF]
        bits = self._frame._bytes_to_bits(payload)
        return self._frame._bits_to_signal(bits)

    def decode(self, signal: IRSignal) -> IRCommand | None:
        if not self._frame._carrier_ok(signal):
            return None
        bits = self._frame._decode_bits(signal)
        if bits is None:
            return None
        a, na, c, nc = self._frame._bits_to_bytes(bits)
        if (a ^ na) != 0xFF or (c ^ nc) != 0xFF:
            return None  # NECext handles the non-complementing variant
        return IRCommand(
            self.name, {"address": a, "command": c}, tuple(bits)
        )


class NECExtended(Protocol):
    """NEC extended: a 16-bit address, so no address checksum."""

    name = "NECext"
    carrier = 38000

    def __init__(self) -> None:
        self._frame = NEC._Frame()

    def encode(self, *, address: int = 0, command: int = 0, **_: int) -> IRSignal:
        if not 0 <= address <= 0xFFFF:
            raise IRError(f"NECext address must be 0-65535, got {address}")
        if not 0 <= command <= 0xFF:
            raise IRError(f"NECext command must be 0-255, got {command}")
        payload = [
            address & 0xFF,
            (address >> 8) & 0xFF,
            command,
            (~command) & 0xFF,
        ]
        bits = self._frame._bytes_to_bits(payload)
        return self._frame._bits_to_signal(bits)

    def decode(self, signal: IRSignal) -> IRCommand | None:
        if not self._frame._carrier_ok(signal):
            return None
        bits = self._frame._decode_bits(signal)
        if bits is None:
            return None
        lo, hi, c, nc = self._frame._bits_to_bytes(bits)
        if (c ^ nc) != 0xFF:
            return None
        if (lo ^ hi) == 0xFF:
            return None  # plain NEC owns this
        return IRCommand(
            self.name, {"address": lo | (hi << 8), "command": c}, tuple(bits)
        )


class Samsung32(Protocol):
    """Samsung's 32-bit variant: a symmetric leader and a repeated address."""

    name = "Samsung32"
    carrier = 38000

    class _Frame(PulseDistanceProtocol):
        carrier = 38000
        leader_mark = 4500
        leader_space = 4500
        bit_mark = 560
        zero_space = 560
        one_space = 1690
        trailer_mark = 560
        gap = 40000
        bit_count = 32
        lsb_first = True

    def __init__(self) -> None:
        self._frame = self._Frame()

    def encode(self, *, address: int = 0, command: int = 0, **_: int) -> IRSignal:
        if not 0 <= address <= 0xFF or not 0 <= command <= 0xFF:
            raise IRError("Samsung32 address and command must each be 0-255")
        payload = [address, address, command, (~command) & 0xFF]
        return self._frame._bits_to_signal(self._frame._bytes_to_bits(payload))

    def decode(self, signal: IRSignal) -> IRCommand | None:
        if not self._frame._carrier_ok(signal):
            return None
        bits = self._frame._decode_bits(signal)
        if bits is None:
            return None
        a1, a2, c, nc = self._frame._bits_to_bytes(bits)
        if a1 != a2 or (c ^ nc) != 0xFF:
            return None
        return IRCommand(self.name, {"address": a1, "command": c}, tuple(bits))


class JVC(Protocol):
    """JVC: 16 bits, no checksum, with a notably long leader."""

    name = "JVC"
    carrier = 38000

    class _Frame(PulseDistanceProtocol):
        carrier = 38000
        leader_mark = 8400
        leader_space = 4200
        bit_mark = 525
        zero_space = 525
        one_space = 1575
        trailer_mark = 525
        gap = 45000
        bit_count = 16
        lsb_first = True

    def __init__(self) -> None:
        self._frame = self._Frame()

    def encode(self, *, address: int = 0, command: int = 0, **_: int) -> IRSignal:
        if not 0 <= address <= 0xFF or not 0 <= command <= 0xFF:
            raise IRError("JVC address and command must each be 0-255")
        return self._frame._bits_to_signal(
            self._frame._bytes_to_bits([address, command])
        )

    def decode(self, signal: IRSignal) -> IRCommand | None:
        if not self._frame._carrier_ok(signal):
            return None
        bits = self._frame._decode_bits(signal)
        if bits is None:
            return None
        address, command = self._frame._bits_to_bytes(bits)
        return IRCommand(
            self.name, {"address": address, "command": command}, tuple(bits)
        )


class Kaseikyo(Protocol):
    """Kaseikyo / Panasonic: 48 bits carrying a vendor ID and a checksum."""

    name = "Kaseikyo"
    carrier = 37000
    PANASONIC_VENDOR = 0x2002

    class _Frame(PulseDistanceProtocol):
        carrier = 37000
        leader_mark = 3456
        leader_space = 1728
        bit_mark = 432
        zero_space = 432
        one_space = 1296
        trailer_mark = 432
        gap = 74000
        bit_count = 48
        lsb_first = True

    def __init__(self) -> None:
        self._frame = self._Frame()

    def encode(
        self,
        *,
        vendor: int | None = None,
        genre: int = 0,
        address: int = 0,
        command: int = 0,
        **_: int,
    ) -> IRSignal:
        vendor = self.PANASONIC_VENDOR if vendor is None else vendor
        if not 0 <= vendor <= 0xFFFF:
            raise IRError("Kaseikyo vendor must be 0-65535")
        if not 0 <= address <= 0xFF or not 0 <= command <= 0xFF:
            raise IRError("Kaseikyo address and command must each be 0-255")

        vendor_lo = vendor & 0xFF
        vendor_hi = (vendor >> 8) & 0xFF
        vendor_parity = (vendor_lo ^ vendor_hi) & 0x0F
        b2 = (genre & 0x0F) << 4 | vendor_parity
        b3 = address
        b4 = command
        checksum = b2 ^ b3 ^ b4
        payload = [vendor_lo, vendor_hi, b2, b3, b4, checksum]
        return self._frame._bits_to_signal(self._frame._bytes_to_bits(payload))

    def decode(self, signal: IRSignal) -> IRCommand | None:
        if not self._frame._carrier_ok(signal):
            return None
        bits = self._frame._decode_bits(signal)
        if bits is None:
            return None
        vendor_lo, vendor_hi, b2, b3, b4, checksum = self._frame._bits_to_bytes(bits)
        if (b2 ^ b3 ^ b4) != checksum:
            return None
        vendor = vendor_lo | (vendor_hi << 8)
        name = "Panasonic" if vendor == self.PANASONIC_VENDOR else self.name
        return IRCommand(
            name,
            {
                "vendor": vendor,
                "genre": (b2 >> 4) & 0x0F,
                "address": b3,
                "command": b4,
            },
            tuple(bits),
        )


# ---------------------------------------------------------------------------
# Pulse-width family: bits distinguished by mark length.
# ---------------------------------------------------------------------------


class SonySIRC(Protocol):
    """Sony SIRC, in its 12, 15 and 20-bit forms.

    Sony devices expect three repeats of the frame 45 ms apart; a single
    frame is often ignored, so :meth:`encode` emits the repeats.
    """

    name = "SIRC"
    carrier = 40000

    leader_mark = 2400
    leader_space = 600
    one_mark = 1200
    zero_mark = 600
    bit_space = 600
    frame_period_us = 45000

    #: bit count -> (command bits, address bits, extended bits)
    LAYOUTS = {12: (7, 5, 0), 15: (7, 8, 0), 20: (7, 5, 8)}

    def encode(
        self,
        *,
        address: int = 0,
        command: int = 0,
        extended: int = 0,
        bits: int = 12,
        repeats: int = 3,
        **_: int,
    ) -> IRSignal:
        if bits not in self.LAYOUTS:
            raise IRError(
                f"SIRC supports 12, 15 or 20 bits, not {bits}"
            )
        cmd_bits, addr_bits, ext_bits = self.LAYOUTS[bits]
        if not 0 <= command < (1 << cmd_bits):
            raise IRError(f"SIRC command must fit in {cmd_bits} bits")
        if not 0 <= address < (1 << addr_bits):
            raise IRError(f"SIRC address must fit in {addr_bits} bits")
        if ext_bits and not 0 <= extended < (1 << ext_bits):
            raise IRError(f"SIRC extended must fit in {ext_bits} bits")

        payload: list[int] = []
        for i in range(cmd_bits):
            payload.append((command >> i) & 1)
        for i in range(addr_bits):
            payload.append((address >> i) & 1)
        for i in range(ext_bits):
            payload.append((extended >> i) & 1)

        durations: list[int] = []
        for _frame in range(max(1, repeats)):
            frame = [self.leader_mark, self.leader_space]
            for bit in payload:
                frame.append(self.one_mark if bit else self.zero_mark)
                frame.append(self.bit_space)
            elapsed = sum(frame)
            # Final space pads the frame out to its 45 ms period.
            frame[-1] = max(self.bit_space, self.frame_period_us - elapsed + frame[-1])
            durations.extend(frame)
        return IRSignal(frequency=self.carrier, durations=tuple(durations))

    def decode(self, signal: IRSignal) -> IRCommand | None:
        if not self._carrier_ok(signal):
            return None
        d = signal.durations
        if len(d) < 2 + 12 * 2:
            return None
        if not self._ok(d[0], self.leader_mark) or not self._ok(
            d[1], self.leader_space
        ):
            return None

        payload: list[int] = []
        i = 2
        while i + 1 < len(d):
            mark = d[i]
            if self._ok(mark, self.one_mark):
                payload.append(1)
            elif self._ok(mark, self.zero_mark):
                payload.append(0)
            else:
                break
            # A long space means the frame ended and a repeat follows.
            if d[i + 1] > 3 * self.bit_space:
                i += 2
                break
            i += 2

        if len(payload) not in self.LAYOUTS:
            return None
        cmd_bits, addr_bits, ext_bits = self.LAYOUTS[len(payload)]

        def take(start: int, count: int) -> int:
            value = 0
            for n in range(count):
                value |= payload[start + n] << n
            return value

        fields = {
            "command": take(0, cmd_bits),
            "address": take(cmd_bits, addr_bits),
        }
        if ext_bits:
            fields["extended"] = take(cmd_bits + addr_bits, ext_bits)
        fields["bits"] = len(payload)
        return IRCommand(self.name, fields, tuple(payload))


# ---------------------------------------------------------------------------
# Bi-phase (Manchester) family.
# ---------------------------------------------------------------------------


class RC5(Protocol):
    """Philips RC-5: 14 Manchester-coded bits at 36 kHz.

    A 1 bit is space-then-mark; a 0 bit is mark-then-space. The toggle bit
    flips on every new keypress, which is how receivers tell a held key from
    a repeated one.
    """

    name = "RC5"
    carrier = 36000
    half_bit = 889
    jitter_us = 250
    #: RC-5 repeats every 128 half-bit times.
    frame_period_us = 128 * 889

    def encode(
        self,
        *,
        address: int = 0,
        command: int = 0,
        toggle: int = 0,
        **_: int,
    ) -> IRSignal:
        if not 0 <= address <= 0x1F:
            raise IRError(f"RC5 address must be 0-31, got {address}")
        if not 0 <= command <= 0x7F:
            raise IRError(f"RC5 command must be 0-127, got {command}")

        # Start bit, field bit (inverted command bit 6), toggle, 5 address,
        # 6 command.
        bits = [1, 0 if command > 0x3F else 1, toggle & 1]
        bits += [(address >> i) & 1 for i in range(4, -1, -1)]
        bits += [(command >> i) & 1 for i in range(5, -1, -1)]

        levels: list[int] = []
        for bit in bits:
            levels += [0, 1] if bit else [1, 0]

        durations = self._levels_to_durations(levels)
        gap = max(self.half_bit, self.frame_period_us - sum(durations))
        if len(durations) % 2 == 0:
            # Already ends on a space (last command bit was 0): widen it
            # rather than emitting two spaces back to back.
            durations[-1] += gap
        else:
            durations.append(gap)
        return IRSignal(frequency=self.carrier, durations=tuple(durations))

    def _levels_to_durations(self, levels: Sequence[int]) -> list[int]:
        """Collapse a half-bit level sequence into mark/space durations.

        The first level is a mark by construction (RC-5's start bit is 1, so
        its first half is a space -- we drop that leading space because a
        signal must begin with a mark).
        """
        durations: list[int] = []
        # RC5 bit 1 = space,mark. The leading space carries no information
        # and cannot be transmitted, so start from the first mark.
        index = 0
        while index < len(levels) and levels[index] == 0:
            index += 1

        run_level = levels[index] if index < len(levels) else 1
        run = 0
        for level in levels[index:]:
            if level == run_level:
                run += 1
            else:
                durations.append(run * self.half_bit)
                run_level = level
                run = 1
        if run:
            durations.append(run * self.half_bit)
        return durations

    def decode(self, signal: IRSignal) -> IRCommand | None:
        if not self._carrier_ok(signal):
            return None
        levels = self._durations_to_levels(signal)
        if levels is None:
            return None

        # Re-insert the start bit's leading space, which was never sent.
        levels = [0] + levels
        if len(levels) == 27:
            # The last bit was a 0, so its trailing space was merged into the
            # inter-frame gap. Restore the half-bit it stands for.
            levels.append(0)
        if len(levels) < 28:
            return None
        levels = levels[:28]

        bits: list[int] = []
        for i in range(0, 28, 2):
            first, second = levels[i], levels[i + 1]
            if first == 0 and second == 1:
                bits.append(1)
            elif first == 1 and second == 0:
                bits.append(0)
            else:
                return None

        if bits[0] != 1:
            return None
        field, toggle = bits[1], bits[2]
        address = 0
        for bit in bits[3:8]:
            address = (address << 1) | bit
        command = 0
        for bit in bits[8:14]:
            command = (command << 1) | bit
        if field == 0:
            command |= 0x40

        return IRCommand(
            self.name,
            {"address": address, "command": command, "toggle": toggle},
            tuple(bits),
        )

    def _durations_to_levels(self, signal: IRSignal) -> list[int] | None:
        """Expand mark/space durations back into half-bit levels."""
        levels: list[int] = []
        for index, duration in enumerate(signal.durations):
            level = 1 if index % 2 == 0 else 0
            count = round(duration / self.half_bit)
            if count < 1:
                return None
            if count > 2:
                if level == 0 and index == len(signal.durations) - 1:
                    break  # trailing inter-frame gap
                return None
            if not _within(duration, count * self.half_bit, 0.35, self.jitter_us):
                return None
            levels += [level] * count
        return levels


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Decode order matters: the stricter, checksum-bearing protocols go first so
#: a NEC frame is never mistaken for its extended variant.
PROTOCOLS: tuple[Protocol, ...] = (
    NEC(),
    NECExtended(),
    Samsung32(),
    Kaseikyo(),
    JVC(),
    SonySIRC(),
    RC5(),
)

PROTOCOLS_BY_NAME: dict[str, Protocol] = {
    proto.name.lower(): proto for proto in PROTOCOLS
}
PROTOCOLS_BY_NAME["panasonic"] = PROTOCOLS_BY_NAME["kaseikyo"]
PROTOCOLS_BY_NAME["sony"] = PROTOCOLS_BY_NAME["sirc"]
PROTOCOLS_BY_NAME["samsung"] = PROTOCOLS_BY_NAME["samsung32"]


def get(name: str) -> Protocol:
    """Look up a protocol codec by name, case-insensitively."""
    try:
        return PROTOCOLS_BY_NAME[name.lower()]
    except KeyError:
        known = ", ".join(sorted({p.name for p in PROTOCOLS}))
        raise IRError(f"unknown IR protocol {name!r}. Known: {known}") from None


def encode(protocol: str, **fields: int) -> IRSignal:
    """Synthesise a signal for ``protocol`` from named field values."""
    return get(protocol).encode(**fields)


def identify(signal: IRSignal) -> IRCommand | None:
    """Work out which protocol ``signal`` is, or None if nothing matches.

    Unrecognised is not a failure: plenty of real devices use protocols not
    implemented here, and a raw capture works perfectly well without a name.
    """
    for proto in PROTOCOLS:
        try:
            decoded = proto.decode(signal)
        except Exception:  # a malformed capture should not abort the sweep
            continue
        if decoded is not None:
            return decoded
    return None
