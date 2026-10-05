"""Import IR codes from LIRC ``lircd.conf`` files.

LIRC's remote database is the largest free collection of IR codes in
existence and covers most of what Logitech's retired database did. Two
flavours appear in the wild:

* ``SPACE_ENC`` definitions, which describe a pulse-distance protocol
  parametrically (header/one/zero/ptrail/gap) plus a table of code values.
* ``raw_codes`` definitions, which list microsecond durations directly.

Both are handled. Anything else -- RC-6 style bi-phase definitions, or
``RCMM`` -- is reported rather than silently mangled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import IRError
from .signal import IRSignal

DEFAULT_FREQUENCY = 38000
DEFAULT_GAP = 40000


@dataclass
class LircRemote:
    """One ``begin remote`` block."""

    name: str = ""
    bits: int = 0
    flags: set[str] = field(default_factory=set)
    frequency: int = DEFAULT_FREQUENCY
    header: tuple[int, int] | None = None
    one: tuple[int, int] | None = None
    zero: tuple[int, int] | None = None
    plead: int = 0
    ptrail: int = 0
    pre_data_bits: int = 0
    pre_data: int = 0
    post_data_bits: int = 0
    post_data: int = 0
    pre: tuple[int, int] | None = None
    post: tuple[int, int] | None = None
    gap: int = DEFAULT_GAP
    toggle_bit_mask: int = 0
    #: button name -> code value (for SPACE_ENC remotes)
    codes: dict[str, int] = field(default_factory=dict)
    #: button name -> raw durations (for raw_codes remotes)
    raw_codes: dict[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def is_raw(self) -> bool:
        return bool(self.raw_codes)

    @property
    def buttons(self) -> list[str]:
        return sorted(self.raw_codes or self.codes)

    def signal(self, button: str) -> IRSignal:
        """Build the waveform for ``button``."""
        if button in self.raw_codes:
            durations = self.raw_codes[button]
            return IRSignal(
                frequency=self.frequency,
                durations=durations,
                name=button,
            )

        if button not in self.codes:
            raise IRError(
                f"{self.name!r} has no button {button!r}. "
                f"Available: {', '.join(self.buttons[:12])}"
                + (" ..." if len(self.buttons) > 12 else "")
            )
        return self._build_space_enc(button, self.codes[button])

    def _build_space_enc(self, button: str, code: int) -> IRSignal:
        if not self.one or not self.zero:
            raise IRError(
                f"{self.name!r} is not a raw remote but defines no "
                "one/zero timings, so harmonyforge cannot synthesise its "
                "waveform. This usually means an unsupported encoding "
                f"(flags: {'|'.join(sorted(self.flags)) or 'none'})."
            )

        durations: list[int] = []

        if self.header:
            durations.extend(self.header)
        if self.plead:
            durations.append(self.plead)

        def emit(value: int, width: int) -> None:
            for i in range(width - 1, -1, -1):
                mark, space = self.one if (value >> i) & 1 else self.zero
                durations.append(mark)
                durations.append(space)

        if self.pre_data_bits:
            emit(self.pre_data, self.pre_data_bits)
            if self.pre:
                durations.extend(self.pre)

        emit(code, self.bits)

        if self.post_data_bits:
            if self.post:
                durations.extend(self.post)
            emit(self.post_data, self.post_data_bits)

        if self.ptrail:
            durations.append(self.ptrail)

        # Normalise to mark-first, alternating, ending on a gap.
        if len(durations) % 2 == 0 and durations:
            durations[-1] = max(durations[-1], self.gap)
        else:
            durations.append(self.gap)

        return IRSignal(
            frequency=self.frequency, durations=tuple(durations), name=button
        )


_NUM = re.compile(r"^-?(?:0[xX][0-9a-fA-F]+|\d+)$")


def _num(token: str) -> int:
    if not _NUM.match(token):
        raise IRError(f"{token!r} is not a number in this lircd.conf")
    return int(token, 0)


def parse(text: str) -> list[LircRemote]:
    """Parse the contents of a ``lircd.conf`` into remote definitions."""
    remotes: list[LircRemote] = []
    current: LircRemote | None = None
    mode: str | None = None
    raw_name: str | None = None
    raw_buffer: list[int] = []

    def flush_raw() -> None:
        nonlocal raw_name, raw_buffer
        if current is not None and raw_name and raw_buffer:
            current.raw_codes[raw_name] = tuple(raw_buffer)
        raw_name, raw_buffer = None, []

    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        tokens = line.split()
        head = tokens[0].lower()

        if head == "begin" and len(tokens) > 1:
            what = tokens[1].lower()
            if what == "remote":
                current = LircRemote()
                mode = None
            elif what == "codes":
                mode = "codes"
            elif what == "raw_codes":
                mode = "raw_codes"
            continue

        if head == "end" and len(tokens) > 1:
            what = tokens[1].lower()
            if what == "raw_codes":
                flush_raw()
                mode = None
            elif what == "codes":
                mode = None
            elif what == "remote":
                flush_raw()
                if current is not None:
                    remotes.append(current)
                current, mode = None, None
            continue

        if current is None:
            continue

        if mode == "codes":
            # "NAME 0x1234" or "NAME 0x1234 0x5678" (we take the first value)
            if len(tokens) >= 2:
                try:
                    current.codes[tokens[0]] = _num(tokens[1])
                except IRError:
                    continue
            continue

        if mode == "raw_codes":
            if head == "name" and len(tokens) >= 2:
                flush_raw()
                raw_name = tokens[1]
                continue
            if raw_name:
                for token in tokens:
                    try:
                        raw_buffer.append(abs(_num(token)))
                    except IRError:
                        pass
            continue

        # Header fields.
        try:
            if head == "name" and len(tokens) >= 2:
                current.name = tokens[1]
            elif head == "bits":
                current.bits = _num(tokens[1])
            elif head == "flags":
                current.flags = {
                    f.strip().upper()
                    for f in " ".join(tokens[1:]).replace("|", " ").split()
                }
            elif head == "frequency":
                current.frequency = _num(tokens[1])
            elif head == "header" and len(tokens) >= 3:
                current.header = (_num(tokens[1]), _num(tokens[2]))
            elif head == "one" and len(tokens) >= 3:
                current.one = (_num(tokens[1]), _num(tokens[2]))
            elif head == "zero" and len(tokens) >= 3:
                current.zero = (_num(tokens[1]), _num(tokens[2]))
            elif head == "plead":
                current.plead = _num(tokens[1])
            elif head == "ptrail":
                current.ptrail = _num(tokens[1])
            elif head == "pre_data_bits":
                current.pre_data_bits = _num(tokens[1])
            elif head == "pre_data":
                current.pre_data = _num(tokens[1])
            elif head == "post_data_bits":
                current.post_data_bits = _num(tokens[1])
            elif head == "post_data":
                current.post_data = _num(tokens[1])
            elif head == "pre" and len(tokens) >= 3:
                current.pre = (_num(tokens[1]), _num(tokens[2]))
            elif head == "post" and len(tokens) >= 3:
                current.post = (_num(tokens[1]), _num(tokens[2]))
            elif head == "gap":
                current.gap = _num(tokens[1])
            elif head == "toggle_bit_mask":
                current.toggle_bit_mask = _num(tokens[1])
        except (IndexError, IRError) as exc:
            raise IRError(f"lircd.conf line {lineno}: {exc}") from exc

    flush_raw()
    if current is not None:
        remotes.append(current)
    return remotes


def load(path: str | Path) -> list[LircRemote]:
    """Parse a ``lircd.conf`` file from disk."""
    data = Path(path).read_text(encoding="utf-8", errors="replace")
    remotes = parse(data)
    if not remotes:
        raise IRError(f"{path} contains no 'begin remote' blocks")
    return remotes
