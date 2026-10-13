"""Read and write Flipper Zero ``.ir`` files.

The Flipper-IRDB community repository is the most actively maintained open IR
code collection today, which makes it the best single source for replacing
Logitech's database. The format is a flat list of ``#``-separated records,
each either ``parsed`` (protocol plus address/command) or ``raw``
(frequency plus durations).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import IRError
from . import protocols
from .signal import IRSignal

HEADER = "Filetype: IR signals file\nVersion: 1"
DEFAULT_DUTY_CYCLE = 0.33

#: Flipper protocol names mapped onto ours.
PROTOCOL_ALIASES = {
    "nec": "NEC",
    "necext": "NECext",
    "nec42": "NEC",
    "nec42ext": "NECext",
    "samsung32": "Samsung32",
    "rc5": "RC5",
    "rc5x": "RC5",
    "sirc": "SIRC",
    "sirc15": "SIRC",
    "sirc20": "SIRC",
    "kaseikyo": "Kaseikyo",
}

#: Flipper SIRC variants carry their width in the protocol name.
SIRC_WIDTHS = {"sirc": 12, "sirc15": 15, "sirc20": 20}


@dataclass
class FlipperRecord:
    """One button in a ``.ir`` file."""

    name: str
    kind: str  # "parsed" or "raw"
    protocol: str = ""
    address: int = 0
    command: int = 0
    frequency: int = 38000
    duty_cycle: float = DEFAULT_DUTY_CYCLE
    durations: tuple[int, ...] = ()

    def signal(self) -> IRSignal:
        """Render this record as a waveform."""
        if self.kind == "raw":
            if not self.durations:
                raise IRError(f"raw record {self.name!r} has no data")
            return IRSignal(
                frequency=self.frequency,
                durations=self.durations,
                name=self.name,
            )

        key = self.protocol.lower()
        mapped = PROTOCOL_ALIASES.get(key)
        if mapped is None:
            raise IRError(
                f"{self.name!r} uses protocol {self.protocol!r}, which "
                "chorus cannot synthesise. Re-export it from the "
                "Flipper as a raw signal, or learn it from the original "
                "remote with `chorus learn`."
            )

        fields: dict[str, int] = {
            "address": self.address,
            "command": self.command,
        }
        if key in SIRC_WIDTHS:
            fields["bits"] = SIRC_WIDTHS[key]
        signal = protocols.encode(mapped, **fields)
        return IRSignal(
            frequency=signal.frequency,
            durations=signal.durations,
            name=self.name,
        )


def _le_int(value: str) -> int:
    """Parse Flipper's little-endian space-separated hex byte lists."""
    parts = value.split()
    if not parts:
        return 0
    try:
        data = bytes(int(p, 16) for p in parts)
    except ValueError as exc:
        raise IRError(f"{value!r} is not a hex byte list") from exc
    return int.from_bytes(data, "little")


def parse(text: str) -> list[FlipperRecord]:
    """Parse the contents of a ``.ir`` file."""
    records: list[FlipperRecord] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if not current.get("name"):
            current.clear()
            return
        kind = current.get("type", "raw").strip().lower()
        record = FlipperRecord(name=current["name"].strip(), kind=kind)
        if kind == "raw":
            raw = current.get("data", "")
            try:
                record.durations = tuple(
                    abs(int(token)) for token in raw.split()
                )
            except ValueError as exc:
                raise IRError(
                    f"{record.name!r} has non-numeric raw data"
                ) from exc
            record.frequency = int(current.get("frequency", "38000") or 38000)
            record.duty_cycle = float(
                current.get("duty_cycle", DEFAULT_DUTY_CYCLE) or DEFAULT_DUTY_CYCLE
            )
        else:
            record.protocol = current.get("protocol", "").strip()
            record.address = _le_int(current.get("address", "00"))
            record.command = _le_int(current.get("command", "00"))
        records.append(record)
        current.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip().lower()
        if key in ("filetype", "version"):
            continue
        if key == "name":
            flush()
        current[key] = value

    flush()
    if not records:
        raise IRError("no IR records found; is this a Flipper .ir file?")
    return records


def load(path: str | Path) -> list[FlipperRecord]:
    """Parse a ``.ir`` file from disk."""
    return parse(Path(path).read_text(encoding="utf-8", errors="replace"))


def dump(signals: list[IRSignal], *, try_parsed: bool = True) -> str:
    """Serialise signals to ``.ir`` text.

    Signals whose protocol we recognise are written as compact ``parsed``
    records; the rest fall back to ``raw``.
    """
    out = [HEADER]
    for index, signal in enumerate(signals, 1):
        name = signal.name or f"Button_{index}"
        decoded = protocols.identify(signal) if try_parsed else None

        if decoded is not None and decoded.protocol.lower() in (
            "nec", "necext", "samsung32", "rc5",
        ):
            address = decoded.fields.get("address", 0)
            command = decoded.fields.get("command", 0)
            out.append("#")
            out.append(f"name: {name}")
            out.append("type: parsed")
            out.append(f"protocol: {decoded.protocol}")
            out.append(f"address: {_hex_bytes(address)}")
            out.append(f"command: {_hex_bytes(command)}")
        else:
            out.append("#")
            out.append(f"name: {name}")
            out.append("type: raw")
            out.append(f"frequency: {signal.frequency}")
            out.append(f"duty_cycle: {DEFAULT_DUTY_CYCLE:.6f}")
            out.append("data: " + " ".join(str(d) for d in signal.durations))
    return "\n".join(out) + "\n"


def _hex_bytes(value: int, width: int = 4) -> str:
    return " ".join(f"{b:02X}" for b in value.to_bytes(width, "little"))
