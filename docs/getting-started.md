# Getting started

## Before you plug anything in

Two things decide how the rest of this goes.

**Which family is your remote?** USB remotes (300–1100, One) store their
configuration onboard and are programmed over USB. Hub-based remotes (Hub,
Elite, Companion, Ultimate, Smart Control) keep it on a hub and are driven
over your network. `chorus detect` and `chorus hub discover`
will tell you which you have.

**Have you taken a backup?** There is no undo on the device. Take one before
you write anything.

## Install

Chorus isn't on PyPI yet; install it from GitHub.

```bash
# Windows
pip install "chorus-remote[hidapi] @ git+https://github.com/av1452/chorus"

# macOS / Linux
brew install libusb          # macOS
# or: sudo apt install libusb-1.0-0
pip install "chorus-remote @ git+https://github.com/av1452/chorus"
```

On Linux, allow non-root access to the device:

```bash
sudo cp packaging/99-chorus.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

On Windows, the `hidapi` extra talks to the remote through Windows' own HID
driver, so no driver changes are needed: Chorus uses it automatically
when libusb isn't installed. (Installing a WinUSB driver with
[Zadig](https://zadig.akeo.ie/) also works, but replaces the remote's driver.)

## 1. Find the remote

```bash
chorus detect
```

Nothing found? In order of likelihood:

1. **The cable is charge-only.** This is the most common cause by a wide
   margin. Try a different cable.
2. **The remote is off.** Older models must be powered on to enumerate.
3. **Something else holds the interface.** Close any Logitech software.
4. **It is a hub remote.** Run `chorus hub discover` instead.

## 2. Identify it

```bash
chorus identify
chorus identify --verbose    # adds architecture detail and serials
```

```
Model:            Logitech Harmony 650
Skin ID:          72
Firmware:         3.2 (type 0)
Hardware:         1.0
Architecture:     7
Protocol:         7
Flash:            AMD Am29LV160BB (2048 KB, IDs 0x01/0x49)
Serial:           4D424D42-0001-0002-0003-0405060708090A
Config valid:     yes
Config size:      184320 / 2031616 bytes (9.1% used)
```

`Config valid: no` is normal on a factory-reset remote.

## 3. Back up

```bash
chorus backup living-room-2026-10-04.bin
```

You get two files: the raw blob, and a `.json` sidecar recording the model
and skin ID. `restore` checks the sidecar and refuses to write a backup from
a different model unless you pass `--force`.

Keep these. They are the only route back.

## 4. Collect IR codes

### Learning from your original remotes

The most reliable source, because the codes come off the real hardware:

```bash
chorus learn --device "Sony TV" --manufacturer Sony --repeat 3 \
    PowerOn PowerOff VolumeUp VolumeDown Mute InputHDMI1
```

Hold the source remote 2–5 cm from the Harmony's learning eye — the dark
window on the front edge — pointing straight at it. `--repeat 3` captures
each button three times and averages, cancelling jitter.

Each capture is decoded as it lands:

```
✓ captured 40.0 kHz, 26 durations, 64.2 ms
✓ recognised as SIRC (command=0x15, address=0x01)
```

A recognised protocol is a good sign: it means the capture is clean enough to
decode, and you can synthesise the buttons you did not capture.

If nothing is captured: move closer, press firmly, and get away from
fluorescent or LED lighting — both flood the sensor.

### Importing a database

[Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB) is the
best-maintained open collection:

```bash
git clone --depth 1 https://github.com/Lucaslhm/Flipper-IRDB
chorus codes import Flipper-IRDB
chorus codes list
chorus codes search bravia
chorus codes show sony-bravia --pronto
```

LIRC also works:

```bash
chorus codes import /usr/share/lirc/remotes/sony/lircd.conf.rm-y181
```

### Pronto hex from a forum

```bash
chorus pronto decode 0000 006D 0022 0002 0157 00AB 0015 0015 ...
```

Or synthesise from a known protocol and code number:

```bash
chorus pronto encode NEC address=0x04 command=0x0C
chorus pronto encode RC5 address=5 command=0x35
chorus pronto encode SIRC address=1 command=0x15 bits=12
```

## 5. Build a configuration

```bash
chorus config new living-room.json --name "Living Room" -m "Harmony 650"
chorus serve --config living-room.json
```

The editor opens at `http://127.0.0.1:8737`.

**Devices tab** — one entry per box. Set the power style honestly: if the
device has separate `PowerOn`/`PowerOff` codes, mark it `discrete`. If it has
only a toggle, mark it `toggle` and expect activities to be less reliable.
Set the power-on delay to however long the device really takes to accept
commands after waking — 2 s is a starting guess, many TVs need 4–6 s.

Then hit **Functions** on the device and pull codes in from the library, add
them from Pronto hex, or learn them directly.

**Activities tab** — build the start sequence (power on, select inputs), the
stop sequence, and the button map. Volume and channel keys usually want to go
to the receiver and the source respectively, not the TV.

## 6. Validate

```bash
chorus config validate living-room.json
```

This catches the mistakes that actually cause problems:

- buttons mapped to functions that do not exist
- activity steps naming unknown devices
- devices marked `discrete` without both power codes
- power toggles on TVs and receivers, which desynchronise
- inputs listed that are not real functions

## Harmony Hub

```bash
chorus hub discover
chorus hub -a 192.168.1.50 info
chorus hub -a 192.168.1.50 activities
chorus hub -a 192.168.1.50 devices --verbose
chorus hub -a 192.168.1.50 start 12345678
chorus hub -a 192.168.1.50 off
chorus hub -a 192.168.1.50 send 98765432 VolumeUp --hold 400
```

SSDP discovery fails across VLANs and on networks with client isolation. If
you know the IP, skip discovery and pass `-a` directly.

## Troubleshooting

**"Could not claim the remote's USB interface"** — something else has it.
Close Logitech software. On Linux, install the udev rule or run as root.

**"expected a version response, got 0x00"** — the remote was not ready.
Unplug, wait five seconds, plug back in, retry.

**"reports architecture N, which has no known memory layout"** — a model
nobody has mapped. Please open an issue with `identify --verbose` output.

**"stores its config in a region table"** — the usbnet family (890, 900,
1100). Not supported; try [concordance](https://github.com/jaymzh/concordance).

**IR learning captures nothing** — closer, firmer press, different lighting.

**IR learning says "signal too long"** — release the button sooner, or move
away from interference.
