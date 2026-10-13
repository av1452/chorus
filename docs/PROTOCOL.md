# How the original setup app works

These notes record what was learned by statically inspecting the publicly downloadable
Windows setup app (version 1.0.1.308) and the web application it loads (client version
19.1.0.35491). No code, templates or artwork from those files are included in this
repository; Chorus is an independent implementation of the behaviour described here.

Every statement below is tagged:

- **Observed**: read directly from the shipped files.
- **Inferred**: a reasonable reading of the evidence that has not been confirmed against real hardware.

## Architecture

| Piece | What it is | Evidence |
|---|---|---|
| Desktop app | A Chromium (CEF) window that opens a page on the vendor's setup server | Observed: the only app URL inside the executable is the setup page |
| Launcher | .NET 2.0 updater that downloads a newer app zip and registers a custom URL scheme | Observed: assembly metadata and strings |
| USB plugin | NPAPI plugin exposing raw HID read/write, device enumeration and VID/PID lookup to the page | Observed: exported function names in the plugin DLLs |
| Web app | Silverlight 5 application (bootstrapper plus a ~3.7 MB core package of 50 assemblies) | Observed: page markup and package manifests |
| Cloud | About 17 SOAP/WCF services for accounts, devices, activities, button mapping, IR analysis and **compiling** the remote's configuration | Observed: client service configuration |

The remote's configuration file is **built in the cloud** (a "compile" service) and only copied
to the remote over USB. Chorus can't rebuild that part without the vendor's device database.

## USB command protocol (newer remotes and hubs)

The driver doesn't hard-code a protocol. It runs XML "operation templates" (one set per
remote model) that describe each packet byte by byte. Chorus implements the rules below directly.

### Packet layout (Observed)

```
byte 0  service id      always 0xFF
byte 1  command id      0x00 ping, 0x01 open, 0x04 read, 0x07 close, 0xFF reset
byte 2  sequence        rolling counter: 0, 1, …, 63, 0, …
byte 3  parameter count
byte 4… parameters
```

The packet is zero-padded to the HID report width. A packet longer than the width is an error.

### Parameter encoding (Observed from the parameter writer's IL)

| Kind | Bytes |
|---|---|
| byte / word / 3-byte / dword | length byte (1/2/3/4) followed by the value, big-endian |
| null-terminated string | `0x80`, UTF-8 bytes, `0x00` |
| sized string / byte array | `0x80 | length`, then the bytes |

### Replies (Observed from the templates' check rules)

A successful reply starts with `0xFF`, then the command id, and byte 2 is not `0xFF`.
The reply to **open** carries the file handle at byte 5 and the file size as a big-endian
32-bit value at bytes 7–10.

### Reading a file (Observed sequence, Inferred framing)

1. `PING` (no parameters).
2. `OPEN` with parameters `"/sys/sysinfo"` and `"R"`.
3. Repeat `READ` with parameters `handle` (byte) and `6` (packets per read) until the
   whole file has arrived. Data packets are laid out as `[sequence, length, payload…]`;
   `0xFE` marks the end of a burst.
4. `CLOSE` with the handle.

### System information (Observed from the property parser)

The file is text up to the first NUL byte, with one `key value` pair per line
(split on the first space). The setup app reads `arch`, `skin`, `fw_ver`, `hw_ver`,
`fw_type`, a GUID and `serial_number`.

## Not yet confirmed

- Whether HID writes need a non-zero report ID on any model (Chorus uses the report ID
  the device's descriptor declares).
- The exact framing of `READ` bursts on real hardware. Chorus's parser tolerates both a
  command echo and data packets in the burst; the packet log on the USB remote screen
  shows the raw traffic so this can be checked.
- The older per-model protocol used by remotes listed as "not yet" in the app.
