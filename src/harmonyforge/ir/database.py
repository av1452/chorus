"""A local, on-disk library of IR code sets.

Logitech's value-add was a cloud database of codes for ~270,000 devices.
That is gone, so harmonyforge keeps a library on *your* disk instead,
populated from whatever sources you have:

* codes you learn from original remotes (the most reliable source);
* LIRC ``lircd.conf`` files;
* Flipper Zero ``.ir`` files, including the Flipper-IRDB collection;
* Pronto hex pasted from forums and code lists.

Each code set is one JSON file, so the library is greppable, diffable and
easy to share -- which is the thing a cloud database never was.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConfigError, IRError
from .signal import IRSignal

LIBRARY_VERSION = 1

#: Where the library lives unless told otherwise.
DEFAULT_LIBRARY = Path.home() / ".harmonyforge" / "codes"


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return cleaned or "unnamed"


@dataclass
class CodeSet:
    """Every IR code known for one device."""

    name: str
    manufacturer: str = ""
    model: str = ""
    device_type: str = ""
    #: Function name -> waveform.
    functions: dict[str, IRSignal] = field(default_factory=dict)
    source: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise IRError("a code set needs a name")

    @property
    def slug(self) -> str:
        parts = [p for p in (self.manufacturer, self.model or self.name) if p]
        return _slug("-".join(parts))

    @property
    def label(self) -> str:
        parts = [p for p in (self.manufacturer, self.model) if p]
        return " ".join(parts) or self.name

    def add(self, name: str, signal: IRSignal) -> None:
        self.functions[name] = signal

    def get(self, name: str) -> IRSignal:
        try:
            return self.functions[name]
        except KeyError:
            raise IRError(
                f"{self.label} has no function {name!r}. It has: "
                f"{', '.join(sorted(self.functions)[:15])}"
            ) from None

    def search_functions(self, query: str) -> list[str]:
        q = query.lower()
        return sorted(f for f in self.functions if q in f.lower())

    def to_dict(self) -> dict:
        return {
            "library_version": LIBRARY_VERSION,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "device_type": self.device_type,
            "source": self.source,
            "notes": self.notes,
            "functions": {
                name: signal.to_dict() for name, signal in self.functions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> CodeSet:
        code_set = cls(
            name=data.get("name", ""),
            manufacturer=data.get("manufacturer", ""),
            model=data.get("model", ""),
            device_type=data.get("device_type", ""),
            source=data.get("source", ""),
            notes=data.get("notes", ""),
        )
        for name, raw in (data.get("functions") or {}).items():
            raw = dict(raw)
            raw.setdefault("name", name)
            code_set.functions[name] = IRSignal.from_dict(raw)
        return code_set

    def __str__(self) -> str:
        return f"{self.label} -- {len(self.functions)} functions"


class CodeLibrary:
    """A directory of code-set JSON files."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else DEFAULT_LIBRARY

    def ensure(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def path_for(self, code_set: CodeSet) -> Path:
        return self.root / f"{code_set.slug}.json"

    def save(self, code_set: CodeSet) -> Path:
        """Write ``code_set`` to the library, replacing any same-slug entry."""
        self.ensure()
        target = self.path_for(code_set)
        target.write_text(
            json.dumps(code_set.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        return target

    def load(self, path: str | Path) -> CodeSet:
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{source} is not valid JSON: {exc}") from exc
        return CodeSet.from_dict(data)

    def __iter__(self) -> Iterator[CodeSet]:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.json")):
            try:
                yield self.load(path)
            except (ConfigError, IRError):
                continue

    def __len__(self) -> int:
        if not self.root.exists():
            return 0
        return len(list(self.root.glob("*.json")))

    def search(self, query: str) -> list[CodeSet]:
        """Find code sets whose name, maker or model matches ``query``."""
        q = query.lower()
        hits = []
        for code_set in self:
            haystack = " ".join(
                (
                    code_set.name,
                    code_set.manufacturer,
                    code_set.model,
                    code_set.device_type,
                )
            ).lower()
            if q in haystack:
                hits.append(code_set)
        return hits

    def find(self, slug_or_name: str) -> CodeSet:
        """Fetch one code set by slug, or by a unique name match."""
        direct = self.root / f"{_slug(slug_or_name)}.json"
        if direct.exists():
            return self.load(direct)

        hits = self.search(slug_or_name)
        if not hits:
            raise IRError(
                f"no code set matching {slug_or_name!r} in {self.root}. "
                "Run `harmonyforge codes list` to see what you have."
            )
        if len(hits) > 1:
            names = ", ".join(c.slug for c in hits[:8])
            raise IRError(
                f"{slug_or_name!r} matches {len(hits)} code sets ({names}). "
                "Use the exact slug."
            )
        return hits[0]

    # -- importers --------------------------------------------------------

    def import_lirc(self, path: str | Path) -> list[CodeSet]:
        """Import every remote in a ``lircd.conf``."""
        from . import lirc

        out = []
        for remote in lirc.load(path):
            code_set = CodeSet(
                name=remote.name or Path(path).stem,
                manufacturer="",
                model=remote.name,
                source=f"lirc:{Path(path).name}",
            )
            for button in remote.buttons:
                try:
                    code_set.functions[button] = remote.signal(button)
                except IRError:
                    continue
            if code_set.functions:
                out.append(code_set)
        if not out:
            raise IRError(
                f"{path} produced no usable codes. Its remotes may use an "
                "encoding harmonyforge cannot synthesise (RC-6 and RCMM "
                "definitions are not supported); raw_codes always work."
            )
        return out

    def import_flipper(self, path: str | Path) -> CodeSet:
        """Import a Flipper Zero ``.ir`` file as one code set."""
        from . import flipper

        source = Path(path)
        records = flipper.load(source)
        # Flipper-IRDB lays files out as Manufacturer/Model.ir
        manufacturer = source.parent.name if source.parent.name else ""
        code_set = CodeSet(
            name=source.stem,
            manufacturer=manufacturer if manufacturer not in (".", "") else "",
            model=source.stem,
            source=f"flipper:{source.name}",
        )
        skipped = []
        for record in records:
            try:
                code_set.functions[record.name] = record.signal()
            except IRError as exc:
                skipped.append(f"{record.name} ({exc})")
        if not code_set.functions:
            raise IRError(
                f"{path} produced no usable codes. Skipped: "
                f"{'; '.join(skipped[:3])}"
            )
        if skipped:
            code_set.notes = f"{len(skipped)} record(s) skipped on import"
        return code_set

    def import_pronto(
        self,
        name: str,
        codes: dict[str, str],
        *,
        manufacturer: str = "",
        model: str = "",
    ) -> CodeSet:
        """Build a code set from ``{function_name: pronto_hex}``."""
        from . import pronto

        code_set = CodeSet(
            name=name,
            manufacturer=manufacturer,
            model=model or name,
            source="pronto",
        )
        for function_name, code in codes.items():
            code_set.functions[function_name] = pronto.parse(code)
        return code_set

    def import_tree(self, root: str | Path) -> tuple[list[CodeSet], list[str]]:
        """Walk a directory importing every ``.ir`` and ``lircd.conf`` found.

        Built for pointing at a clone of Flipper-IRDB or the LIRC remotes
        database. Returns ``(imported, problems)``.
        """
        base = Path(root)
        if not base.exists():
            raise IRError(f"no such directory: {base}")

        imported: list[CodeSet] = []
        problems: list[str] = []

        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            try:
                if path.suffix.lower() == ".ir":
                    imported.append(self.import_flipper(path))
                elif path.name in ("lircd.conf",) or path.suffix == ".lircd":
                    imported.extend(self.import_lirc(path))
                else:
                    continue
            except (IRError, ConfigError, OSError) as exc:
                problems.append(f"{path.relative_to(base)}: {exc}")

        return imported, problems
