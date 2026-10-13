# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `web/`: Chorus, a browser app merged in from the former `chorus-remote`
  repository (history preserved). Edits devices, activities and per-activity
  button maps in the browser, reads newer remotes and hubs over WebHID,
  exports/imports JSON, and works offline as a PWA. Published to GitHub Pages
  by the new `Web app` workflow.
- The web app now reads and writes the harmonyforge config format directly
  (same keys, same key order), with power style, warm-up time,
  volume/channel/primary roles, start and stop sequences, and the same checks
  as `config validate`. Setups saved by the earlier web app are converted
  automatically. `tests/test_web_config.py` loads a file exported by the web
  app and checks it round-trips byte for byte.
- `docs/protocol-packet-hid.md`: the packet protocol used by newer remotes
  and hubs, documented from static analysis of the MyHarmony client.
- `config/binary.py`: a parser for the config blob's internal container --
  header, cookie/magic, end-of-config address, and the section pointer
  table -- for architectures 8, 9, 12 and 14. Derived from the
  [harmony-decompiler](https://github.com/trelowney/harmony-decompiler)
  project's findings (see NOTICE.md), independently re-verified against a
  real Harmony 665 backup before relying on it: the cookie, computed
  `config_base`, and section 1's architecture/version record all matched
  values obtained through completely separate means (libconcord's
  architecture table, and a live USB identity read). Does not decode
  section contents, and writes nothing to a remote. See
  `docs/binary-config-format.md`.
- `harmonyforge inspect-binary`: CLI command exposing the above against a
  file saved by `backup`.
- 31 new tests against synthetic container blobs (20 for the parser's
  correctness and error paths, covering every architecture signature).

### Fixed

- `detect`, `identify` and other USB commands crashed with
  `usb.core.NoBackendError` when libusb was not installed (the default on
  Windows). They now explain how to install libusb on each platform, and
  `detect` falls back to hidapi when it is installed.
- `NECext` assumed an 8-bit command with a complement checksum. Real Apple
  TV remotes (2nd-gen 4K, 3rd-gen, checked independently) use a full 16-bit
  command with no checksum at all -- confirmed by checking every captured
  command byte pair across two device generations for the complement
  relationship a real checksum would show, and finding none. Re-verified
  with a 50,000-sample random sweep after the fix.
- `IRSignal.snapped()` picked the first common carrier frequency within
  tolerance rather than the nearest, so a learned 37904 Hz capture snapped
  to 36 kHz instead of 38 kHz.
- `HARDWARE.md` listed the Harmony 665 at architecture 7, by incorrect
  analogy to the 650. A live identity read against real hardware showed it
  is architecture 14 (the 700/One family), not 7.

### Changed

- The read path (`detect`, `identify`, `backup`) is now verified against a
  real Harmony 665, not only against the simulated remote. The write path
  remains unverified on any model.

### Known limitations

- No path yet from a `RemoteConfig` to the remote's native binary format.
  The blob's outer container is now understood (see Added, above); what is
  inside each section is not, for any architecture these remotes use. See
  [docs/roadmap.md](docs/roadmap.md).
- The write path has not been verified against physical hardware, on any
  model.
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
