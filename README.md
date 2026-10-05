# harmonyforge

**Program Logitech Harmony remotes without Logitech.**

Logitech discontinued the Harmony line in 2021, and the MyHarmony desktop
software plus the cloud service it depended on are gone. That left a lot of
perfectly good hardware unprogrammable: the remotes work, but you cannot
change what they do.

harmonyforge is an open replacement. It talks to the remote over USB
directly, keeps your configuration in a plain JSON file you own, and sources
IR codes from open databases instead of a dead cloud service.

```
pip install harmonyforge
harmonyforge detect
harmonyforge backup my-remote.bin     # do this first, always
harmonyforge serve                    # opens the editor in your browser
```

---

## What it does

| | |
|---|---|
| **Identify** | Reads model, firmware, hardware revision, flash chip, architecture and serial numbers straight off the device. |
| **Back up and restore** | Reads the remote's configuration region to a file, and writes it back with read-back verification. This is the safety net MyHarmony never gave you. |
| **Learn IR codes** | Uses the remote's own IR learning eye to capture codes from your original remotes, averaging multiple captures to cancel jitter. |
| **Recognise codes** | Decodes NEC, NEC extended, RC-5, Sony SIRC (12/15/20-bit), Panasonic/Kaseikyo, Samsung32 and JVC, so a learned blob becomes a named, reproducible command. |
| **Import code databases** | Reads LIRC `lircd.conf` files, Flipper Zero `.ir` files (including the whole Flipper-IRDB collection), and Pronto hex pasted from forums. |
| **Edit configurations** | A local web UI for devices, activities, start/stop sequences and per-activity button mapping. |
| **Validate** | Catches the mistakes that actually bite: power toggles that desynchronise, buttons pointing at functions that do not exist, inputs that are not real commands. |
| **Control Harmony Hubs** | Discovers hubs by SSDP and drives them over the local WebSocket API — activities, devices, individual commands. No account required. |

## Honest status

This matters more than a feature list, so read it before trusting the tool
with your remote.

**Verified in this repository, by an automated test suite of 262 tests:**
the wire format of every protocol command; the model, architecture and flash
tables; IR encode/decode round-trips across more than 20,000 parameter
combinations; Pronto conversion; LIRC and Flipper import; the configuration
model; the WebSocket client; and full erase/write/read/verify cycles against
a simulated remote.

**Not yet verified against physical hardware.** I do not have a Harmony
remote to test against. The USB protocol implementation is a careful port of
[libconcord](https://github.com/jaymzh/concordance), which has driven real
remotes for fifteen years, and the packet bytes are asserted against the
documented format — but ported code is not tested code.

So: **`identify`, `detect` and `backup` are safe to try** — they only read.
Treat `restore` and anything that writes to flash as unproven until someone
confirms it on your model. If you try it, please
[open an issue](https://github.com/av1452/harmonyforge/issues) either way;
hardware reports are the single most useful contribution right now.

The one thing harmonyforge **cannot** do yet is compile a `RemoteConfig` into
the remote's native binary config format. That format is undocumented and
model-specific. See [docs/roadmap.md](docs/roadmap.md) for what that means in
practice and how it is being approached.

## Which remote do you have?

Harmony splits into two incompatible families, and this decides everything.

**USB remotes** — 300, 350, 510, 520, 525, 550, 600, 650, 665, 700, 880, 890,
One, 1000, 1100, and the rest. These store their configuration in onboard
flash and were programmed by plugging into USB. This is harmonyforge's main
target.

**Hub-based remotes** — Hub, Elite, Companion, Ultimate, Smart Control. The
configuration lives on the hub and the remote is effectively a radio. These
never appear on USB; use the `hub` commands, which work over your network
without any cloud account.

Not sure? Plug it in and run `harmonyforge detect`. If nothing shows up, try
`harmonyforge hub discover`. See [HARDWARE.md](HARDWARE.md) for the
per-model support matrix.

## Installing

Needs Python 3.10 or newer and libusb.

```bash
# macOS
brew install libusb
pip install harmonyforge

# Debian / Ubuntu
sudo apt install libusb-1.0-0
pip install harmonyforge

# Windows: install a libusb driver for the remote with Zadig, then
pip install harmonyforge
```

On Linux, non-root USB access needs a udev rule:

```bash
sudo cp packaging/99-harmonyforge.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

From source:

```bash
git clone https://github.com/av1452/harmonyforge
cd harmonyforge
pip install -e ".[dev,yaml]"
pytest
```

## Walkthrough

### 1. Back up before anything else

```bash
harmonyforge identify          # confirm it is recognised
harmonyforge backup living-room-2026-10-04.bin
```

This writes the blob plus a `.json` sidecar recording the model and skin ID,
which `restore` checks before it will write anything. There is no undo on the
device, so keep the file.

### 2. Get IR codes

Learning from your original remotes is the most reliable route, because the
codes come from the actual hardware:

```bash
harmonyforge learn --device "Sony TV" --manufacturer Sony \
    --repeat 3 PowerOn PowerOff VolumeUp VolumeDown InputHDMI1
```

`--repeat 3` captures each button three times and averages them, which
cancels measurement jitter. Each capture is decoded as it arrives, so you
see `recognised as SIRC (command=0x15, address=0x01)` rather than an opaque
pile of numbers.

Or import an existing database. [Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB)
is the best-maintained open collection:

```bash
git clone https://github.com/Lucaslhm/Flipper-IRDB
harmonyforge codes import Flipper-IRDB
harmonyforge codes search sony
harmonyforge codes show sony-bravia --pronto
```

LIRC files and Pronto hex work too:

```bash
harmonyforge codes import /usr/share/lirc/remotes/sony/lircd.conf.rm-y181
harmonyforge pronto decode 0000 006D 0022 0002 0157 00AB 0015 0015 ...
harmonyforge pronto encode NEC address=0x04 command=0x0C
```

### 3. Build a configuration

```bash
harmonyforge config new living-room.json --name "Living Room" -m "Harmony 650"
harmonyforge serve --config living-room.json
```

The editor opens at `http://127.0.0.1:8737`. Add devices, pull codes in from
the library, then build activities: a start sequence that powers things on
and selects inputs, and a button map that routes each key to a device.

Then check it:

```bash
harmonyforge config validate living-room.json
```

### 4. Harmony Hub

```bash
harmonyforge hub discover
harmonyforge hub --address 192.168.1.50 activities
harmonyforge hub --address 192.168.1.50 start 12345678
harmonyforge hub --address 192.168.1.50 send 98765432 VolumeUp --hold 400
harmonyforge hub --address 192.168.1.50 export -o hub.json
```

`export` pulls the hub's device and activity structure into harmonyforge's
own format. Note that the hub does not expose IR waveforms, so the functions
come across as named placeholders you then fill in.

## Using it as a library

```python
from harmonyforge.usb.transport import open_remote
from harmonyforge.usb.remote import HarmonyRemote
from harmonyforge.ir import protocols, pronto

with open_remote() as transport:
    remote = HarmonyRemote(transport)
    print(remote.identify().summary())

    backup = remote.read_config()

    signal = remote.learn_ir().snapped()
    print(protocols.identify(signal))       # NEC (address=0x04, command=0x0C)
    print(pronto.format_signal(signal))     # 0000 006D 0022 ...
```

No hardware needed to explore the IR side:

```python
from harmonyforge.ir import protocols, pronto

signal = protocols.encode("RC5", address=5, command=0x35)
print(pronto.format_signal(signal))
print(protocols.identify(signal))
```

## Why the power style setting matters

The single most common Harmony complaint was "my activity leaves the TV off."
That is almost always a power *toggle*: one command that flips state. Send it
when the device is already on and you turn it off.

harmonyforge makes this explicit. Mark a device `discrete` and give it
separate `PowerOn`/`PowerOff` codes and activities become reliable. Mark it
`toggle` and `config validate` will warn you. Most TVs have undocumented
discrete power codes even when their own remote only has a toggle — worth
hunting for in a code database.

## Documentation

- [docs/getting-started.md](docs/getting-started.md) — a fuller walkthrough
- [docs/protocol-usb-hid.md](docs/protocol-usb-hid.md) — the USB wire protocol, documented
- [docs/config-format.md](docs/config-format.md) — the configuration file schema
- [docs/ir-codes.md](docs/ir-codes.md) — IR protocols, Pronto, and where to find codes
- [docs/hub-api.md](docs/hub-api.md) — the Harmony Hub local API
- [docs/architecture.md](docs/architecture.md) — how the code is laid out
- [docs/roadmap.md](docs/roadmap.md) — what is missing and what is next
- [HARDWARE.md](HARDWARE.md) — per-model support matrix
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to help

## Credits

harmonyforge stands entirely on
[**concordance / libconcord**](https://github.com/jaymzh/concordance) by
**Kevin Timmerman** and **Phil Dibowitz**, with later work by **Scott
Talbert**. They reverse-engineered the Harmony USB protocol and have
maintained it for over a decade. Every command constant, architecture table
and flash sector map here comes from their work. If you need battle-tested
Harmony programming today, use concordance — it has the hardware mileage this
project does not.

Also thanks to the [LIRC](https://www.lirc.org/) project and the
[Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB) contributors, whose
code collections are what make a post-Logitech device database possible.

See [NOTICE.md](NOTICE.md) for full attribution.

## Licence

GPL-3.0-or-later, matching libconcord, whose protocol work this derives from.
See [LICENSE](LICENSE).

Not affiliated with, endorsed by, or connected to Logitech. "Harmony" and
"Logitech" are trademarks of Logitech International S.A., used here only to
describe which hardware this software works with.
