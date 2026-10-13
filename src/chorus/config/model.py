"""The configuration model: devices, activities, buttons and macros.

This is the part of MyHarmony that mattered. A Harmony remote's behaviour is
described by three things:

**Devices**
    Each physical box in your setup, with a named set of IR functions and
    enough metadata to know how to turn it on (a discrete power-on command,
    or a toggle you must not send twice) and which input it needs.

**Activities**
    "Watch TV" -- a named scene that powers the right devices on, selects the
    right inputs, and decides which device each button talks to while the
    activity is running.

**Button maps**
    Which device function each physical button sends, per activity.

The model is plain dataclasses with dict round-tripping, so a config is a
readable JSON (or YAML) file you can diff, review and keep in git -- which is
the main thing the cloud-only original never let you do.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ..errors import ConfigError
from ..ir import pronto
from ..ir.signal import IRSignal

SCHEMA_VERSION = 1


class DeviceType(str, Enum):
    """Broad device categories, used to pick sensible button defaults."""

    TELEVISION = "television"
    AV_RECEIVER = "av_receiver"
    SOUNDBAR = "soundbar"
    CABLE_SATELLITE = "cable_satellite"
    STREAMING = "streaming"
    BLURAY_DVD = "bluray_dvd"
    GAME_CONSOLE = "game_console"
    PROJECTOR = "projector"
    AMPLIFIER = "amplifier"
    LIGHTING = "lighting"
    OTHER = "other"


class PowerStyle(str, Enum):
    """How a device's power control behaves.

    This is the single most common source of "my activity leaves the TV off"
    problems: a toggle device sent two power commands ends up back where it
    started.
    """

    #: Separate PowerOn and PowerOff commands. Always prefer this.
    DISCRETE = "discrete"
    #: One Power command that flips state. Needs careful sequencing.
    TOGGLE = "toggle"
    #: Device has no power control (or should be left alone).
    NONE = "none"


@dataclass
class Function:
    """One IR command a device understands."""

    name: str
    #: Carrier frequency in Hz.
    frequency: int = 38000
    #: Alternating mark/space durations in microseconds.
    durations: tuple[int, ...] = ()
    #: Human label shown in the UI, if different from ``name``.
    label: str = ""
    #: Decoded protocol name, when known (purely informational).
    protocol: str = ""
    #: Where this code came from: "learned", "lirc", "flipper", "pronto"...
    source: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a function needs a name")
        self.durations = tuple(int(d) for d in self.durations)

    @property
    def signal(self) -> IRSignal:
        return IRSignal(
            frequency=self.frequency, durations=self.durations, name=self.name
        )

    @property
    def display_name(self) -> str:
        return self.label or self.name

    @classmethod
    def from_signal(
        cls, name: str, signal: IRSignal, *, source: str = "", label: str = ""
    ) -> Function:
        from ..ir import protocols

        decoded = protocols.identify(signal)
        return cls(
            name=name,
            frequency=signal.frequency,
            durations=signal.durations,
            label=label,
            protocol=decoded.protocol if decoded else "",
            source=source,
        )

    def to_pronto(self) -> str:
        return pronto.format_signal(self.signal)

    @classmethod
    def from_pronto(cls, name: str, code: str, **kwargs: Any) -> Function:
        signal = pronto.parse(code)
        return cls.from_signal(name, signal, source="pronto", **kwargs)


@dataclass
class Device:
    """One controllable box."""

    name: str
    manufacturer: str = ""
    model: str = ""
    type: DeviceType = DeviceType.OTHER
    power_style: PowerStyle = PowerStyle.TOGGLE
    functions: dict[str, Function] = field(default_factory=dict)
    #: Input-select function names, in menu order, e.g. ``["InputHDMI1", ...]``.
    inputs: list[str] = field(default_factory=list)
    #: Milliseconds to wait after powering this device on before sending more.
    power_on_delay_ms: int = 2000
    #: Milliseconds between repeated commands to this device.
    inter_command_delay_ms: int = 100
    #: How many times to repeat each IR frame. Some devices need 2-3.
    repeat_count: int = 1
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a device needs a name")
        self.type = DeviceType(self.type)
        self.power_style = PowerStyle(self.power_style)

    def add(self, function: Function) -> Function:
        """Add or replace a function."""
        self.functions[function.name] = function
        return function

    def get(self, name: str) -> Function:
        try:
            return self.functions[name]
        except KeyError:
            raise ConfigError(
                f"device {self.name!r} has no function {name!r}. "
                f"It has: {', '.join(sorted(self.functions)) or '(none)'}"
            ) from None

    @property
    def power_on_function(self) -> str | None:
        """The best command for turning this device on."""
        for candidate in ("PowerOn", "Power On", "PowerToggle", "Power"):
            if candidate in self.functions:
                if (
                    self.power_style == PowerStyle.DISCRETE
                    and candidate in ("PowerToggle", "Power")
                ):
                    continue
                return candidate
        return None

    @property
    def power_off_function(self) -> str | None:
        for candidate in ("PowerOff", "Power Off", "PowerToggle", "Power"):
            if candidate in self.functions:
                if (
                    self.power_style == PowerStyle.DISCRETE
                    and candidate in ("PowerToggle", "Power")
                ):
                    continue
                return candidate
        return None

    def validate(self) -> list[str]:
        """Return human-readable warnings about this device."""
        warnings: list[str] = []
        if not self.functions:
            warnings.append(
                f"device {self.name!r} has no IR functions -- learn or import "
                "codes for it"
            )
        if self.power_style == PowerStyle.DISCRETE and not (
            "PowerOn" in self.functions and "PowerOff" in self.functions
        ):
            warnings.append(
                f"device {self.name!r} is marked discrete-power but lacks "
                "PowerOn and/or PowerOff"
            )
        if self.power_style == PowerStyle.TOGGLE and self.type in (
            DeviceType.TELEVISION,
            DeviceType.AV_RECEIVER,
        ):
            warnings.append(
                f"device {self.name!r} uses a power toggle; activities may "
                "leave it in the wrong state. Check whether it has discrete "
                "PowerOn/PowerOff codes (most TVs do, undocumented)"
            )
        for input_name in self.inputs:
            if input_name not in self.functions:
                warnings.append(
                    f"device {self.name!r} lists input {input_name!r} which "
                    "is not one of its functions"
                )
        return warnings


@dataclass
class Step:
    """One action in an activity's start or stop sequence."""

    device: str
    function: str
    #: Milliseconds to wait *after* this step.
    delay_ms: int = 500
    #: How many times to send it.
    repeat: int = 1

    def __post_init__(self) -> None:
        if not self.device or not self.function:
            raise ConfigError("a step needs both a device and a function")


@dataclass
class Activity:
    """A named scene: what to power on, which inputs, and button routing."""

    name: str
    label: str = ""
    #: Steps run when the activity starts.
    start_sequence: list[Step] = field(default_factory=list)
    #: Steps run when the activity ends (empty means "power everything off").
    stop_sequence: list[Step] = field(default_factory=list)
    #: Physical button -> "Device/Function", e.g. ``{"VolumeUp": "AVR/VolUp"}``.
    buttons: dict[str, str] = field(default_factory=dict)
    #: Device whose volume keys are used, as a convenience default.
    volume_device: str = ""
    #: Device whose channel keys are used.
    channel_device: str = ""
    #: Device the transport/navigation keys drive.
    primary_device: str = ""
    icon: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("an activity needs a name")

    @property
    def display_name(self) -> str:
        return self.label or self.name

    @property
    def devices_used(self) -> list[str]:
        names: list[str] = []
        for step in list(self.start_sequence) + list(self.stop_sequence):
            if step.device not in names:
                names.append(step.device)
        for target in self.buttons.values():
            device = target.split("/", 1)[0]
            if device and device not in names:
                names.append(device)
        return names

    def validate(self, devices: dict[str, Device]) -> list[str]:
        warnings: list[str] = []

        def check(device_name: str, function_name: str, where: str) -> None:
            device = devices.get(device_name)
            if device is None:
                warnings.append(
                    f"activity {self.name!r}: {where} refers to unknown "
                    f"device {device_name!r}"
                )
            elif function_name not in device.functions:
                warnings.append(
                    f"activity {self.name!r}: {where} refers to "
                    f"{device_name!r} function {function_name!r}, which does "
                    "not exist"
                )

        for i, step in enumerate(self.start_sequence):
            check(step.device, step.function, f"start step {i + 1}")
        for i, step in enumerate(self.stop_sequence):
            check(step.device, step.function, f"stop step {i + 1}")
        for button, target in self.buttons.items():
            if "/" not in target:
                warnings.append(
                    f"activity {self.name!r}: button {button!r} maps to "
                    f"{target!r}, expected 'Device/Function'"
                )
                continue
            device_name, function_name = target.split("/", 1)
            check(device_name, function_name, f"button {button!r}")

        if not self.start_sequence:
            warnings.append(
                f"activity {self.name!r} has no start sequence, so selecting "
                "it will not turn anything on"
            )
        for attr, label in (
            ("volume_device", "volume_device"),
            ("channel_device", "channel_device"),
            ("primary_device", "primary_device"),
        ):
            value = getattr(self, attr)
            if value and value not in devices:
                warnings.append(
                    f"activity {self.name!r}: {label} is {value!r}, which is "
                    "not a known device"
                )
        return warnings


@dataclass
class RemoteConfig:
    """A complete remote configuration."""

    #: Human name for this config.
    name: str = "My Harmony"
    #: Remote model this config targets, e.g. "Harmony 650".
    remote_model: str = ""
    #: Skin ID reported by the remote, if known.
    remote_skin: int | None = None
    devices: dict[str, Device] = field(default_factory=dict)
    activities: dict[str, Activity] = field(default_factory=dict)
    #: Button maps that apply outside any activity (device mode).
    global_buttons: dict[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    created: str = ""
    modified: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.created = self.created or now
        self.modified = self.modified or now

    # -- mutation ---------------------------------------------------------

    def add_device(self, device: Device) -> Device:
        if device.name in self.devices:
            raise ConfigError(f"device {device.name!r} already exists")
        self.devices[device.name] = device
        return device

    def add_activity(self, activity: Activity) -> Activity:
        if activity.name in self.activities:
            raise ConfigError(f"activity {activity.name!r} already exists")
        self.activities[activity.name] = activity
        return activity

    def device(self, name: str) -> Device:
        try:
            return self.devices[name]
        except KeyError:
            raise ConfigError(
                f"no device named {name!r}. Known devices: "
                f"{', '.join(sorted(self.devices)) or '(none)'}"
            ) from None

    def activity(self, name: str) -> Activity:
        try:
            return self.activities[name]
        except KeyError:
            raise ConfigError(
                f"no activity named {name!r}. Known activities: "
                f"{', '.join(sorted(self.activities)) or '(none)'}"
            ) from None

    def resolve(self, target: str) -> Function:
        """Resolve a ``"Device/Function"`` reference."""
        if "/" not in target:
            raise ConfigError(
                f"{target!r} is not a 'Device/Function' reference"
            )
        device_name, function_name = target.split("/", 1)
        return self.device(device_name).get(function_name)

    def touch(self) -> None:
        self.modified = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # -- validation -------------------------------------------------------

    def validate(self) -> list[str]:
        """Collect every warning about this config.

        Returns warnings rather than raising, because a config that is
        incomplete is still worth saving and editing.
        """
        warnings: list[str] = []
        for device in self.devices.values():
            warnings.extend(device.validate())
        for activity in self.activities.values():
            warnings.extend(activity.validate(self.devices))
        for button, target in self.global_buttons.items():
            if "/" in target:
                device_name, function_name = target.split("/", 1)
                device = self.devices.get(device_name)
                if device is None:
                    warnings.append(
                        f"global button {button!r} refers to unknown device "
                        f"{device_name!r}"
                    )
                elif function_name not in device.functions:
                    warnings.append(
                        f"global button {button!r} refers to missing function "
                        f"{device_name}/{function_name}"
                    )
        if not self.activities:
            warnings.append(
                "config has no activities; the remote will only work in "
                "device mode"
            )
        return warnings

    @property
    def function_count(self) -> int:
        return sum(len(d.functions) for d in self.devices.values())

    def summary(self) -> str:
        lines = [
            f"Config:     {self.name}",
            f"Remote:     {self.remote_model or 'unspecified'}",
            f"Devices:    {len(self.devices)}",
            f"Activities: {len(self.activities)}",
            f"Functions:  {self.function_count}",
            f"Modified:   {self.modified}",
        ]
        if self.devices:
            lines.append("")
            lines.append("Devices:")
            for device in self.devices.values():
                lines.append(
                    f"  {device.name:<22} {device.type.value:<16} "
                    f"{len(device.functions):>3} functions"
                )
        if self.activities:
            lines.append("")
            lines.append("Activities:")
            for activity in self.activities.values():
                lines.append(
                    f"  {activity.display_name:<22} "
                    f"{len(activity.start_sequence):>2} start steps, "
                    f"{len(activity.buttons):>2} buttons"
                )
        return "\n".join(lines)

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "remote_model": self.remote_model,
            "remote_skin": self.remote_skin,
            "created": self.created,
            "modified": self.modified,
            "notes": self.notes,
            "devices": {
                name: {
                    "name": d.name,
                    "manufacturer": d.manufacturer,
                    "model": d.model,
                    "type": d.type.value,
                    "power_style": d.power_style.value,
                    "inputs": list(d.inputs),
                    "power_on_delay_ms": d.power_on_delay_ms,
                    "inter_command_delay_ms": d.inter_command_delay_ms,
                    "repeat_count": d.repeat_count,
                    "notes": d.notes,
                    "functions": {
                        fname: {
                            "name": f.name,
                            "label": f.label,
                            "frequency": f.frequency,
                            "durations": list(f.durations),
                            "protocol": f.protocol,
                            "source": f.source,
                        }
                        for fname, f in d.functions.items()
                    },
                }
                for name, d in self.devices.items()
            },
            "activities": {
                name: {
                    "name": a.name,
                    "label": a.label,
                    "icon": a.icon,
                    "volume_device": a.volume_device,
                    "channel_device": a.channel_device,
                    "primary_device": a.primary_device,
                    "buttons": dict(a.buttons),
                    "start_sequence": [asdict(s) for s in a.start_sequence],
                    "stop_sequence": [asdict(s) for s in a.stop_sequence],
                }
                for name, a in self.activities.items()
            },
            "global_buttons": dict(self.global_buttons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteConfig:
        version = data.get("schema_version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            raise ConfigError(
                f"config uses schema version {version}, but this build of "
                f"chorus understands up to {SCHEMA_VERSION}. Upgrade "
                "chorus."
            )

        config = cls(
            name=data.get("name", "My Harmony"),
            remote_model=data.get("remote_model", ""),
            remote_skin=data.get("remote_skin"),
            created=data.get("created", ""),
            modified=data.get("modified", ""),
            notes=data.get("notes", ""),
            schema_version=version,
        )

        for name, raw in (data.get("devices") or {}).items():
            device = Device(
                name=raw.get("name", name),
                manufacturer=raw.get("manufacturer", ""),
                model=raw.get("model", ""),
                type=DeviceType(raw.get("type", "other")),
                power_style=PowerStyle(raw.get("power_style", "toggle")),
                inputs=list(raw.get("inputs") or []),
                power_on_delay_ms=int(raw.get("power_on_delay_ms", 2000)),
                inter_command_delay_ms=int(
                    raw.get("inter_command_delay_ms", 100)
                ),
                repeat_count=int(raw.get("repeat_count", 1)),
                notes=raw.get("notes", ""),
            )
            for fname, fraw in (raw.get("functions") or {}).items():
                device.add(
                    Function(
                        name=fraw.get("name", fname),
                        label=fraw.get("label", ""),
                        frequency=int(fraw.get("frequency", 38000)),
                        durations=tuple(fraw.get("durations") or ()),
                        protocol=fraw.get("protocol", ""),
                        source=fraw.get("source", ""),
                    )
                )
            config.devices[device.name] = device

        for name, raw in (data.get("activities") or {}).items():
            activity = Activity(
                name=raw.get("name", name),
                label=raw.get("label", ""),
                icon=raw.get("icon", ""),
                volume_device=raw.get("volume_device", ""),
                channel_device=raw.get("channel_device", ""),
                primary_device=raw.get("primary_device", ""),
                buttons=dict(raw.get("buttons") or {}),
                start_sequence=[
                    Step(**s) for s in (raw.get("start_sequence") or [])
                ],
                stop_sequence=[
                    Step(**s) for s in (raw.get("stop_sequence") or [])
                ],
            )
            config.activities[activity.name] = activity

        config.global_buttons = dict(data.get("global_buttons") or {})
        return config

    # -- files ------------------------------------------------------------

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent) + "\n"

    def save(self, path: str | Path) -> Path:
        """Write this config to ``path``. Format follows the extension."""
        target = Path(path)
        self.touch()
        if target.suffix.lower() in (".yaml", ".yml"):
            target.write_text(_dump_yaml(self.to_dict()), encoding="utf-8")
        else:
            target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> RemoteConfig:
        """Read a config from a ``.json``, ``.yaml`` or ``.yml`` file."""
        source = Path(path)
        if not source.exists():
            raise ConfigError(f"no such config file: {source}")
        text = source.read_text(encoding="utf-8")
        if source.suffix.lower() in (".yaml", ".yml"):
            return cls.from_dict(_load_yaml(text, source))
        try:
            return cls.from_dict(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{source} is not valid JSON: {exc}") from exc


def _load_yaml(text: str, source: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise ConfigError(
            f"{source} is YAML, which needs PyYAML. Either install it "
            "(pip install 'chorus-remote[yaml]') or use a .json config."
        ) from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError(f"{source} does not contain a YAML mapping")
    return data


def _dump_yaml(data: dict[str, Any]) -> str:
    try:
        import yaml
    except ImportError as exc:
        raise ConfigError(
            "writing YAML needs PyYAML (pip install 'chorus-remote[yaml]'). "
            "Save with a .json extension instead."
        ) from exc
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
