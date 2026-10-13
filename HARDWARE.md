# Hardware support

## Reading this table

- **Protocol implemented** — the command sequences and memory layout for this
  architecture are written and unit-tested against a simulated remote.
- **Hardware confirmed** — someone has run it against the physical remote and
  reported the result.

Only the Harmony 665's read path (identify, backup, and the binary container
parser) is hardware-confirmed so far — see `docs/binary-config-format.md`.
On Windows it has been confirmed through **both** backends: libusb, and
hidapi with Windows' own HID driver (no Zadig needed; `pip install hidapi`),
where two consecutive backups were byte-identical.
Nothing's write path has been confirmed on any model. If you own one of
these, running `chorus identify` and
[opening an issue](https://github.com/av1452/chorus/issues) with the
output is the most valuable contribution available right now — whether it
works or not.

## USB remotes

| Model | Skin | Arch | Protocol implemented | Hardware confirmed |
|---|---|---|---|---|
| Harmony 745 | 2 | 2 | yes | — |
| Harmony 748 | 7 | 3 | yes | — |
| Harmony 768 | 3 | 3 | yes | — |
| Harmony 628 | 13 | 7 | yes | — |
| Harmony 655 | 11 | 7 | yes | — |
| Harmony 659 | 9 | 7 | yes | — |
| Harmony 670 | 50 | 7 | yes | — |
| Harmony 675 | 16 | 7 | yes | — |
| Harmony 676 | 12 | 7 | yes | — |
| Harmony 680 | 14 | 7 | yes | — |
| Harmony 688 | 10 | 7 | yes | — |
| Harmony 600 | 71 | 7 | yes | — |
| Harmony 650 | 72 | 7 | yes | — |
| Harmony 880 / 880 Pro | 15 / 39 | 8 | yes | — |
| Harmony 885 | 17 | 8 | yes | — |
| Harmony 520 / 522 / 525 | 18 / 46 / 22 | 9 | yes | — |
| Harmony 550 / 552 / 555 | 41 / 51 / 48 | 9 | yes | — |
| Harmony 515 | 67 | 9 | yes | — |
| Harmony XBOX 360 | 36 | 9 | yes | — |
| Harmony One | 54 | 12 | yes | — |
| Harmony 665 | 75 | 14 | yes | **read path: yes** (USB ID `046d:c122`; libusb and hidapi) |
| Harmony 700 | 66 | 14 | yes | — |
| Harmony 720 | 44 | 7 | yes | — |
| Harmony 785 | 45 | 7 | yes | — |
| Harmony 300 / 350 | 78 / 104 | 16 | partial — identify only | — |
| Harmony 200 | 80 | — | partial — identify only | — |

### Not supported: the usbnet family

| Model | Skin | Arch | Why |
|---|---|---|---|
| Harmony 890 / 890 Pro | 19 / 40 | 10 | Config region must be looked up in an on-device table |
| Harmony 900 | 61 | 15 | Same, plus Z-Wave transport |
| Harmony 1000 / 1000i | 49 / 52 | 9 | Needs confirmation |
| Harmony 1100 | 63 | 11 | Same as 890 |

These present an Ethernet-over-USB interface (PID `0xC11F`) rather than the
HID interface Chorus uses, and locate their configuration through a
region table rather than at a fixed address. `identify` may work; reading and
writing configuration does not. [concordance](https://github.com/jaymzh/concordance)
supports several of these — use it for this family.

## Hub-based remotes

These never appear on USB. Use `chorus hub`, which works over your
local network with no Logitech account.

| Model | Local API | Notes |
|---|---|---|
| Harmony Hub | yes | WebSocket on port 8088 |
| Harmony Elite | yes | Via its hub |
| Harmony Companion | yes | Via its hub |
| Harmony Ultimate / Ultimate One | yes | Via its hub |
| Harmony Smart Control | yes | Via its hub |
| Harmony Touch | — | Arch 17; identify only |
| Harmony Link | — | Discontinued and bricked by Logitech in 2018 |

Requires hub firmware 4.15.206 or newer, which is what replaced the old XMPP
interface with the WebSocket one. Reading configuration, listing and starting
activities, and sending individual commands all work. The hub does not expose
IR waveforms, so `hub export` produces structure with placeholder functions.

## Other manufacturers

The Harmony platform was licensed out, and these use the same protocol:

| Model | Skin | Arch |
|---|---|---|
| Monster AVL-300 | 26–31 | 7–8 |
| Monster AVL-200 | 32–33 | 8 |
| Monster AV-100 | 37–38 | 9 |
| Harman Kardon TC-30 | 34, 35, 42, 43 | 7–9 |
| Logicool Harmony 882 (JP) | 47 | 8 |
| Logicool Harmony 552 (JP) | 51 | 9 |

## Flash chips

| Chip | Mfg/Dev ID | Size | Sectors |
|---|---|---|---|
| AMD Am29LV008B | `0x01`/`0x37` | 1 MB | non-uniform, bottom boot |
| AMD Am29LV160BB | `0x01`/`0x49` | 2 MB | non-uniform, bottom boot |
| AMD Am29LV116DB | `0x01`/`0x4C` | 2 MB | non-uniform, bottom boot |
| EON F16-100HIP | `0x15`/`0x1C` | 4 MB | uniform 64 KB |
| Saifun SA25F020 | `0xFF`/`0x11` | 256 KB | uniform 64 KB |
| Spansion S25FL004A | `0xFF`/`0x12` | 512 KB | uniform 64 KB |
| Atmel AT49BV322A | `0x1F`/`0xC8` | 4 MB | non-uniform |

Some firmware reports the manufacturer and device IDs swapped; Chorus
tries both orders before falling back to a conservative default.
