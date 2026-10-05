# The Harmony USB HID protocol

Reference documentation for the protocol `harmonyforge` speaks to USB
Harmony remotes. All of this derives from
[libconcord](https://github.com/jaymzh/concordance) by Kevin Timmerman and
Phil Dibowitz; it is written down here because a working open
implementation deserves readable documentation, and because the original
exists mainly as C.

## Finding the device

Harmony remotes claim:

| Vendor | VID | PID |
|---|---|---|
| Logitech | `0x046D` | `0xC110`–`0xC14F` |
| National Semiconductor | `0x0400` | `0xC359` |

The National Semiconductor ID belongs to the USBN9603/9604 controller used
on older remotes, which present under their own vendor ID in some states.

`0x046D:0xC11F` is the *usbnet* family (890, 900, 1100). Those present an
Ethernet-over-USB interface rather than the HID interface below, and need a
different protocol entirely.

## Transport

Despite being HID devices, these remotes are not addressed with HID report
semantics. Open interface 0 and use its interrupt IN/OUT endpoint pair
directly. The report size is the endpoint's `wMaxPacketSize`:

- **8 bytes** on the oldest National Semiconductor remotes
- **64 bytes** on everything newer

Every command is one report, zero-padded to that size. Every response is one
report. Responses must be read until the remote sends `RESPONSE_DONE`.

> On Windows, the HID stack prepends a report-ID byte. harmonyforge's
> `HidApiTransport` adds the leading `0x00`; `PyUsbTransport` writes to the
> endpoint directly and does not.

## Packet layout

The first byte packs a command in the high nibble and a *length code* in the
low nibble:

```
 bit  7  6  5  4   3  2  1  0
     ├─ command ─┤ ├─ length ─┤
```

The length code is **not a byte count**. It indexes a lookup table whose
contents depend on the protocol version (see below). Some commands have a
fixed length code baked into their constant — `COMMAND_ERASE_FLASH` is
`0xD3`, not `0xD0`.

Addresses are 24-bit big-endian across three bytes. Lengths are 16-bit
big-endian.

## Commands

| Name | Value | Notes |
|---|---|---|
| `GET_VERSION` | `0x10` | Identity. Always the first command. |
| `WRITE_FLASH` | `0x30` | Setup: announces address + length. |
| `WRITE_FLASH_DATA` | `0x40` | Payload packets. Length code selects block size. |
| `READ_FLASH` | `0x50` | Setup: requests address + length. |
| `START_IRCAP` | `0x70` | Begin IR learning. |
| `STOP_IRCAP` | `0x80` | End IR learning. |
| `WRITE_MISC` | `0xA0` | Second byte selects the region. |
| `READ_MISC` | `0xB0` | Second byte selects the region; one byte per round trip. |
| `ERASE_FLASH` | `0xD3` | Erases the sector containing the given address. |
| `RESET` | `0xE1` | Second byte selects reset kind. |
| `DONE` | `0xF1` | Terminates a multi-packet transfer; second byte echoes the command. |

Misc regions (second byte of `READ_MISC`/`WRITE_MISC`): `EEPROM` `0x00`,
`STATE` `0x01`, `INVALIDATE_FLASH` `0x02`, `QUEUE_ACTION` `0x03`,
`PROGRAM` `0x04`, `INTERRUPT` `0x05`, `RAM` `0x06`, `REGISTER` `0x07`,
`CLOCK_RECALCULATE` `0x08`, `QUEUE_EVENT` `0x09`, `RESTART_CONFIG` `0x0A`.

Reset kinds: `USB` `0x01`, `DEVICE` `0x02`, `DEVICE_DISCONNECT` `0x03`,
`TEST_FINISH` `0x04`.

## Responses

| Name | Value |
|---|---|
| `VERSION_DATA` | `0x20` |
| `READ_FLASH_DATA` | `0x60` |
| `IRCAP_DATA` | `0x90` |
| `READ_MISC_DATA` | `0xC0` |
| `DONE` | `0xF0` |

## Identity

Send `0x10` padded to the report size. The reply is `0x2X`, where `X` is the
length code — it must be 5, 7 or 8. Anything else means the remote is not
ready or is not a Harmony.

| Byte | Meaning |
|---|---|
| 0 | `0x20 \| length_code` |
| 1 | firmware version: major in high nibble, minor in low |
| 2 | hardware version: major in high nibble, minor in low |
| 3 | flash device ID |
| 4 | flash manufacturer ID |
| 5 | architecture in high nibble, firmware type in low |
| 6 | skin (model) ID |
| 7 | protocol version |

The short form (length code 5) stops after byte 4; architecture then defaults
to 2, skin to 2, and protocol to 0. With length code 7 the protocol comes
from byte 7; with length code 8 the protocol equals the architecture.

The **skin ID** indexes the model table — 72 is a Harmony 650, 54 a Harmony
One, 15 an 880. The **architecture** indexes the memory-layout table, which
is what tells you where the configuration lives. The **flash ID pair** selects
the chip's size and sector map; some firmware reports the two IDs swapped, so
try both orders.

## Length-code tables

### Reading

Length code from a `READ_FLASH_DATA` response maps to a payload byte count:

| Code | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11–15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| protocol 0 | 0 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10–14 |
| others | 0 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 14 | 30 | 62 | unused |

Protocol 0 means the Harmony 745, or any remote running in safe mode.

### Writing

Pick the largest block that covers the bytes still outstanding, walking down
the table and decrementing the length code in step:

- **protocol 0:** codes 7→1 give blocks 7, 6, 5, 4, 3, 2, 1
- **others:** codes 10→1 give blocks 63, 31, 15, 7, 6, 5, 4, 3, 2, 1

### Chunk caps

One setup command may request at most:

| | read | write |
|---|---|---|
| protocol 0 | 700 | 749 |
| others | 1022 | 3150 |

## Reading flash

```
-> 0x55, addr[2], addr[1], addr[0], len_hi, len_lo
<- 0x6X, seq, data...        (repeated)
<- 0xF0, 0x50                (done)
```

`seq` starts at `0x01` and increments by **`0x11`** per packet. A mismatch
means packet loss. One documented exception: Harmony 880 firmware sometimes
sends `0x1F` where `0x10` is expected; resynchronise rather than fail.

Loop the setup command until the whole range is covered.

## Writing flash

Flash must be erased before writing, and erase works a whole sector at a
time — so writing anything rewrites the sectors it touches.

```
-> 0x35, addr[2], addr[1], addr[0], len_hi, len_lo   (setup)
-> 0x4X, data...                                     (repeated)
-> 0xF1, 0x30                                        (done)
<- 0xF0, 0x30
```

Data packets are not individually acknowledged; only the terminating `DONE`
gets a reply, with a longer timeout (5 s) because the device is committing to
flash.

## Erasing flash

```
-> 0xD3, addr[2], addr[1], addr[0]
<- 0xF0, ...
```

The address must be a sector start. Sector boundaries come from the flash
chip's sector map — they are non-uniform on several chips, with small boot
sectors at the bottom. Allow 5 s for the reply.

## IR learning

```
-> 0x70                       (start)
<- 0x9X, seq, words...        (repeated)
-> 0x80                       (stop)
<- ... 0xF0                   (drain until done)
```

Sequence increments by `0x10` here, not `0x11`. The payload byte count lives
in the **last byte of the report** (`raw[report_len - 1]`) and must be even.
Words are 16-bit big-endian, starting at offset 2.

Decoding the word stream is the fiddly part:

- **word 0** — ignored
- **word 1** — on-time of the first burst
- **word 2** — carrier cycle count over that burst, so
  `frequency = word2 * 1_000_000 / word1`. Emit word 1 as the first mark.
- **word 3 onward** — odd words carry elapsed on+off time, even words carry
  on time. A nonzero even word closes a mark/space pair and both get emitted.

Capture ends when 500 ms passes with no signal. Abort past 5 s total or 1000
durations; in practice that means the learning eye is seeing interference,
and fluorescent or LED lighting is the usual cause.

## Memory layout

Per-architecture, from the architecture table:

| Field | Meaning |
|---|---|
| `flash_base` | Where flash starts in the address space |
| `firmware_base` | Firmware image start |
| `config_base` | Configuration region start |
| `cookie` / `cookie_size` | Magic value at `config_base` proving the config is valid |
| `end_vector` | Offset within the config header holding the end-of-config address |
| `serial_location` | `eeprom` or `flash` |
| `serial_address` | Where the three 16-byte serial GUIDs live |

Validity check: read 1024 bytes at `config_base`, take the first 2 or 4 bytes
little-endian, compare against `cookie`. If it matches, the 3 bytes at
`end_vector` give the end address, and
`config_bytes_used = end - (config_base - flash_base) + 4`.

Architecture 10, 11 and 15 use a `REGION_USER_CONFIG` sentinel instead of a
fixed `config_base`: the region has to be looked up in an on-device table.
harmonyforge declines these rather than guessing.

### Serial numbers

48 bytes, three 16-byte GUIDs. Most architectures store the first three
groups little-endian (classic mixed-endian GUID layout); architecture 14 and
the Z-Wave/usbnet families store them straight through.

## Known architectures

| Arch | Remotes | `config_base` | Micro |
|---|---|---|---|
| 2 | 745 | `0x006000` | PIC16LF877 |
| 3 | 748, 768 | `0x020000` | PIC18LC801 |
| 7 | 6xx | `0x020000` | PIC18LC801 |
| 8 | 880 | `0x020000` | PIC18LC801 |
| 9 | 360, 52x, 55x | `0x820000` | PIC18LF4550 |
| 10 | 890 | region table | PIC18LC801 |
| 11 | 1100 | region table | — |
| 12 | One | `0x040000` | — |
| 14 | 700 | `0x030000` | PIC18F67J50 |
| 15 | 900 | region table | — |
| 16 | 300 | — | — |
| 17 | Link, Touch | — | — |

## Verifying against hardware

If you have a remote and want to check this implementation, `--debug` logs
every packet:

```bash
harmonyforge --debug identify
harmonyforge --debug read-flash 0x020000 256
```

A dump of the first kilobyte of the config region, plus the full
`identify --verbose` output, is the most useful thing to attach to an issue.
