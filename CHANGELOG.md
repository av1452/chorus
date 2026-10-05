# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Known limitations

- No path yet from a `RemoteConfig` to the remote's native binary format;
  `backup`/`restore` move opaque blobs. See [docs/roadmap.md](docs/roadmap.md).
- No code path has been verified against physical hardware.
- The usbnet family (890, 900, 1100) is detected but not programmable.

## [0.1.0] — 2026-10-04

First release.

### Added

- **USB protocol** — full HID command set for Harmony remotes: identity,
  flash read/write/erase, misc regions, reset, IR learning. Both length-code
  tables (protocol 0 and later), correct chunk caps, sequence validation
  including the documented Harmony 880 firmware glitch.
- **Hardware database** — 120 remote models, 18 architectures, 7 flash chips
  and 6 sector maps, generated from libconcord's tables by
  `tools/gen_devicedb.py`.
- **Transports** — pyusb/libusb and hidapi backends, plus `FakeTransport`,
  a simulated remote that makes the stack testable without hardware.
- **IR codecs** — NEC, NEC extended, Samsung32, JVC, Kaseikyo/Panasonic,
  Sony SIRC (12/15/20-bit) and RC-5, each with encode *and* decode, so
  learned captures are recognised and sibling codes can be synthesised.
- **Pronto hex** — full CCF conversion both ways, with clear refusal of the
  unconvertible `5000`-series database codes.
- **Importers** — LIRC `lircd.conf` (both `SPACE_ENC` and `raw_codes`),
  Flipper Zero `.ir` (parsed and raw records), and recursive directory import
  for collections like Flipper-IRDB.
- **Code library** — on-disk JSON code sets with search, at
  `~/.harmonyforge/codes`.
- **Configuration model** — devices, activities, start/stop sequences, button
  maps and macros, in a diffable JSON file, with validation that catches
  power-toggle desynchronisation, dangling button targets and unreachable
  inputs.
- **Harmony Hub support** — SSDP discovery, a dependency-free RFC 6455
  WebSocket client, and the local hub API: read configuration, list and start
  activities, send commands, export structure.
- **Web editor** — a local single-page UI served from `http.server`, with no
  frontend dependencies.
- **CLI** — `detect`, `identify`, `backup`, `restore`, `read-flash`,
  `remotes`, `learn`, `codes`, `pronto`, `config`, `hub`, `serve`.
- **Documentation** — the USB protocol written up in full, plus guides for
  getting started, the config format, IR codes, the hub API, the code
  architecture, and a roadmap.
- **262 tests**, no hardware required.
