# IR codes

## How infrared remotes work

A remote blinks an LED at a **carrier frequency** — usually 38 kHz, with Sony
at 40 kHz and Philips at 36 kHz. Data rides on top as a pattern of
carrier-on (**mark**) and carrier-off (**space**) intervals.

So an IR code is two things: a carrier frequency, and a list of mark/space
durations in microseconds. That is exactly what `IRSignal` holds, and
everything else in Chorus converts to or from it.

```python
from chorus.ir.signal import IRSignal

signal = IRSignal(frequency=38000, durations=(9000, 4500, 560, 1690, 560))
```

Durations strictly alternate, starting with a mark.

## Protocols

A protocol is a convention for turning a number into a duration pattern.
Chorus implements the common ones in both directions, so it can
*synthesise* a code from a device/command number and *recognise* a learned
capture.

| Protocol | Carrier | Bits | Fields | Notes |
|---|---|---|---|---|
| NEC | 38 kHz | 32 | address, command | Most common. Sends each byte with its complement as a checksum. |
| NECext | 38 kHz | 32 | address (16-bit), command (16-bit) | No checksum on either field -- real-world example: Apple TV remotes. |
| Samsung32 | 38 kHz | 32 | address, command | Symmetric 4.5 ms leader; address sent twice. |
| JVC | 38 kHz | 16 | address, command | Long 8.4 ms leader, no checksum. |
| Kaseikyo / Panasonic | 37 kHz | 48 | vendor, genre, address, command | Vendor `0x2002` is Panasonic. Has a real checksum. |
| Sony SIRC | 40 kHz | 12/15/20 | address, command, extended | Pulse-*width* coded. Wants three frames 45 ms apart. |
| RC-5 | 36 kHz | 14 | address, command, toggle | Manchester coded. Toggle bit flips per keypress. |

```bash
chorus pronto encode NEC address=0x04 command=0x0C
chorus pronto encode SIRC address=1 command=0x15 bits=12
chorus pronto encode RC5 address=5 command=0x35
```

```python
from chorus.ir import protocols

signal = protocols.encode("NEC", address=0x04, command=0x0C)
print(protocols.identify(signal))   # NEC (address=0x04, command=0x0C)
```

`identify` returns `None` for anything it does not recognise. That is not a
failure — plenty of real devices use protocols not implemented here, and a
raw capture replays perfectly well without a name. Recognition is a
convenience: it names the code, and it lets you synthesise sibling buttons
you never captured.

### The toggle bit

RC-5 includes a bit that flips on every *new* keypress, so a receiver can
tell "pressed twice" from "held down". When replaying a captured RC-5 code,
sending the same toggle value repeatedly can read as a held key. Chorus
exposes `toggle` as a field so you can alternate it if a device behaves
oddly.

### Why protocol numbering differs between tools

LIRC stores Sony codes most-significant-bit-first, while Sony transmits
least-significant-bit-first. So LIRC's `0x15` and Chorus's decoded
`0x54` are the *same physical code*, numbered under different conventions.
The waveform is what matters and it is identical. Do not be alarmed when an
imported LIRC code decodes to a different-looking number.

## Pronto hex

Pronto hex (CCF) is the shared language of IR code sharing — remotecentral,
JP1, and most AV forums publish in it. With Logitech's database gone, this is
how you get codes out of a forum post and into your remote.

```
0000 006D 0022 0002 0157 00AB 0015 0015 ...
```

| Word | Meaning |
|---|---|
| 0 | format: `0000` raw modulated, `0100` raw unmodulated |
| 1 | carrier divisor; `carrier_hz = 4145146 / divisor` |
| 2 | burst-pair count of the "once" sequence |
| 3 | burst-pair count of the "repeat" sequence |
| 4+ | alternating mark/space durations, in carrier cycles |

`006D` is 109, giving 4145146 / 109 = 38029 Hz — the standard 38 kHz code.

```bash
chorus pronto decode 0000 006D 0022 0002 0157 00AB ...
```

```python
from chorus.ir import pronto

signal = pronto.parse("0000 006D 0004 0000 0157 00AB 0015 0040 0015 0689")
print(pronto.format_signal(signal))
```

### Precision

Pronto stores durations as whole carrier cycles, so converting a synthesised
signal into Pronto and back is not bit-exact: at 38 kHz one cycle is about
26 µs, and the divisor `0x6D` really means 38029 Hz rather than 38000, which
stretches long durations by about 0.08%. This is inherent to the format and
harmless — the decoded protocol and command come back identical. Codes that
*originate* as Pronto round-trip exactly, because they are already
cycle-aligned.

### Codes Pronto cannot share

Format words other than `0000` and `0100` — `5000`, `5001` and friends —
reference Pronto's own internal database rather than carrying the waveform.
They cannot be converted and Chorus refuses them with an explanation
rather than producing garbage.

## Where to get codes

### Learn them from the original remote

The most reliable source, and the only one guaranteed to match your actual
hardware:

```bash
chorus learn --device "Sony TV" --repeat 3 PowerOn PowerOff VolumeUp
```

`--repeat 3` averages three captures, cancelling jitter. Averaging refuses to
combine captures of different lengths, which is how a misfire gets caught
rather than averaged in.

### Flipper-IRDB

The most actively maintained open collection, laid out as
`Manufacturer/Model.ir`:

```bash
git clone --depth 1 https://github.com/Lucaslhm/Flipper-IRDB
chorus codes import Flipper-IRDB
```

Chorus infers the manufacturer from the directory name. Records using
protocols it cannot synthesise are skipped with a note rather than silently
dropped.

### LIRC

The largest free collection, and what most Linux IR work is built on:

```bash
chorus codes import /usr/share/lirc/remotes/sony/lircd.conf.rm-y181
```

Both `SPACE_ENC` (parametric) and `raw_codes` definitions are handled.
Bi-phase definitions (RC-6, RCMM) are reported as unsupported rather than
mangled — `raw_codes` always works, so re-recording as raw is the workaround.

### Forums

remotecentral.com's file area and the JP1 archives hold large numbers of
Pronto codes. Paste them straight into the editor's Pronto field, or:

```bash
chorus pronto decode <paste>
```

## The code library

Your codes live in `~/.chorus/codes` as one JSON file per device.
Greppable, diffable, and easy to share — the thing a cloud database never
was.

```bash
chorus codes list
chorus codes search samsung
chorus codes show samsung-un55j --pronto
chorus codes export samsung-un55j -o samsung.ir
```

Override the location with `--library DIR`.

## Working out an unknown device

If you have no original remote and no database entry, you can often guess:
manufacturers reuse protocols and address values across their whole range.

1. Find *any* code for the same manufacturer and decode it to learn the
   protocol and address.
2. Synthesise candidates by sweeping the command number:

```python
from chorus.ir import protocols, pronto

for command in range(0, 256):
    signal = protocols.encode("NEC", address=0x04, command=command)
    print(command, pronto.format_signal(signal))
```

3. Send them and watch what the device does.

Tedious, but it is how most code databases were built in the first place.
