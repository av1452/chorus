# Configuration file format

A Chorus configuration is a single JSON file (YAML also works, with
PyYAML installed). It is designed to be read, diffed and kept in version
control — which is the thing a cloud-only configuration never was.

The [web app](../web/README.md) reads and writes this same format, so a file
can move between the browser and the command line.

## Top level

```json
{
  "schema_version": 1,
  "name": "Living Room",
  "remote_model": "Harmony 650",
  "remote_skin": 72,
  "created": "2026-10-04T18:00:00+00:00",
  "modified": "2026-10-04T18:30:00+00:00",
  "notes": "",
  "devices": { },
  "activities": { },
  "global_buttons": { }
}
```

`schema_version` is checked on load. A file from a newer Chorus is
refused rather than misread.

## Devices

Keyed by device name.

```json
"devices": {
  "TV": {
    "name": "TV",
    "manufacturer": "Sony",
    "model": "KDL-55W800",
    "type": "television",
    "power_style": "discrete",
    "inputs": ["InputHDMI1", "InputHDMI2"],
    "power_on_delay_ms": 4000,
    "inter_command_delay_ms": 100,
    "repeat_count": 1,
    "notes": "",
    "functions": { }
  }
}
```

**`type`** — one of `television`, `av_receiver`, `soundbar`,
`cable_satellite`, `streaming`, `bluray_dvd`, `game_console`, `projector`,
`amplifier`, `lighting`, `other`. Used to pick sensible defaults and to
decide which validation warnings apply.

**`power_style`** — the setting that decides whether your activities are
reliable:

- `discrete` — separate `PowerOn` and `PowerOff` commands. Always prefer
  this. Many devices have discrete codes that their own remote does not
  expose; a code database will often have them.
- `toggle` — one command that flips state. Activities can desynchronise,
  because the remote has no way to know the current state.
- `none` — no power control, or deliberately left alone.

**`power_on_delay_ms`** — how long to wait after powering this device on
before sending it anything else. Too short and input-select commands get
dropped while the device is still booting. Most TVs need 3000–6000.

**`inter_command_delay_ms`** — gap between consecutive commands to this
device. Raise it if a device misses rapid sequences.

**`repeat_count`** — how many times to send each frame. Some devices ignore a
single frame; Sony devices conventionally want three.

## Functions

An IR command, keyed by name within its device.

```json
"functions": {
  "PowerOn": {
    "name": "PowerOn",
    "label": "Power On",
    "frequency": 40000,
    "durations": [2400, 600, 1200, 600, 600, 600],
    "protocol": "SIRC",
    "source": "learned"
  }
}
```

**`frequency`** — carrier in Hz. 38000 is most common; Sony uses 40000,
Philips 36000.

**`durations`** — microseconds, strictly alternating mark (carrier on) and
space (carrier off), starting with a mark. A trailing space encodes the gap
before a repeat.

**`protocol`** — informational, filled in automatically when the waveform
decodes to a known protocol. An empty value just means "raw capture", which
works fine.

**`source`** — where it came from: `learned`, `pronto`, `lirc:<file>`,
`flipper:<file>`, `synthesised:<protocol>`. Useful when a code turns out to be
wrong and you need to know what to re-do.

### Naming conventions

Nothing enforces these, but consistency makes button mapping much easier:

| Purpose | Names |
|---|---|
| Power | `PowerOn`, `PowerOff`, `PowerToggle` |
| Volume | `VolumeUp`, `VolumeDown`, `Mute` |
| Channel | `ChannelUp`, `ChannelDown`, `PrevChannel` |
| Navigation | `DirectionUp`, `DirectionDown`, `DirectionLeft`, `DirectionRight`, `OK` |
| Transport | `Play`, `Pause`, `Stop`, `Rewind`, `FastForward`, `Record` |
| Inputs | `InputHDMI1`, `InputHDMI2`, `InputTV`, `InputAux` |
| Menus | `Menu`, `Exit`, `Back`, `Info`, `Guide`, `Home` |
| Digits | `0` … `9` |

## Activities

Keyed by activity name.

```json
"activities": {
  "WatchTV": {
    "name": "WatchTV",
    "label": "Watch TV",
    "icon": "",
    "primary_device": "CableBox",
    "volume_device": "AVR",
    "channel_device": "CableBox",
    "start_sequence": [
      { "device": "TV",  "function": "PowerOn",    "delay_ms": 4000, "repeat": 1 },
      { "device": "AVR", "function": "PowerOn",    "delay_ms": 3000, "repeat": 1 },
      { "device": "TV",  "function": "InputHDMI1", "delay_ms": 500,  "repeat": 1 },
      { "device": "AVR", "function": "InputCable", "delay_ms": 500,  "repeat": 1 }
    ],
    "stop_sequence": [
      { "device": "AVR", "function": "PowerOff", "delay_ms": 500, "repeat": 1 },
      { "device": "TV",  "function": "PowerOff", "delay_ms": 0,   "repeat": 1 }
    ],
    "buttons": {
      "VolumeUp":   "AVR/VolumeUp",
      "VolumeDown": "AVR/VolumeDown",
      "Mute":       "AVR/Mute",
      "ChannelUp":  "CableBox/ChannelUp",
      "OK":         "CableBox/OK"
    }
  }
}
```

**`start_sequence`** — ordered steps. `delay_ms` is the wait *after* that
step. Power the slowest device first so its warm-up overlaps the others.

**`stop_sequence`** — if empty, nothing is powered off.

**`buttons`** — physical button name to `"Device/Function"`. Anything not
listed falls through to `global_buttons`.

**`primary_device`** / **`volume_device`** / **`channel_device`** —
conveniences recording which device each key group belongs to.

## Global buttons

Mappings that apply outside any activity:

```json
"global_buttons": { "Mute": "AVR/Mute" }
```

## Validation

```bash
chorus config validate living-room.json
chorus config validate living-room.json --strict   # non-zero on warnings
```

Warnings, not errors: an incomplete config is still worth saving and editing.
`--strict` makes them fail, which is what you want in CI.

## YAML

Same structure. Needs `pip install 'chorus-remote[yaml]'`, and the format
follows the file extension:

```bash
chorus config show living-room.yaml
```
