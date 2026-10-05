# Attribution

## concordance / libconcord

harmonyforge's USB protocol implementation derives from
[**concordance**](https://github.com/jaymzh/concordance) and its library
**libconcord**, licensed GPLv3.

Copyright © Kevin Timmerman
Copyright © Phil Dibowitz
With later contributions from Scott Talbert and others.

Specifically, the following are derived from libconcord:

- The command and response constants in `usb/protocol.py`, from
  `libconcord/protocol.h`
- The length-code tables, chunk caps and sequence-increment behaviour in
  `usb/protocol.py`, from `libconcord/remote.cpp`
- The entire contents of `devicedb.py` — the model, architecture, flash-chip
  and sector tables — mechanically translated from
  `libconcord/remote_info.h` by `tools/gen_devicedb.py`
- The identity-response parse, flash read/write/erase sequencing, and the IR
  capture word-stream decoding in `usb/remote.py`, from
  `libconcord/remote.cpp`
- The USB vendor and product ID ranges in `usb/transport.py`, from
  `libconcord/libusbhid.cpp` and `libconcord/gen_udev_support`
- The documentation in `docs/protocol-usb-hid.md`, which describes the
  protocol as libconcord implements it

Timmerman and Dibowitz reverse-engineered this protocol and have maintained
it for over a decade. harmonyforge is a reimplementation in Python with a
different interface; it is not a fork, and it adds no protocol knowledge of
its own. **If you need battle-tested Harmony programming today, use
concordance** — it has the hardware mileage this project does not.

harmonyforge is licensed GPL-3.0-or-later to match.

## LIRC

The [LIRC](https://www.lirc.org/) project defined the `lircd.conf` format
that `ir/lirc.py` reads, and maintains the largest free collection of IR
codes in existence. LIRC itself is GPL-licensed; no LIRC code is included
here, only support for its file format.

## Flipper-IRDB

[Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB) is the most actively
maintained open IR code collection, and the practical replacement for
Logitech's retired device database. `ir/flipper.py` reads and writes the
Flipper Zero `.ir` format. No database content is bundled.

## Pronto

The Pronto hex (CCF) format originated with Philips' Pronto remotes. The
format is publicly documented and widely implemented; `ir/pronto.py` is an
independent implementation.

## Protocol specifications

The IR protocol timings in `ir/protocols.py` come from published
specifications for NEC, Philips RC-5, Sony SIRC, Panasonic/Kaseikyo, Samsung
and JVC.

## Trademarks

"Logitech" and "Harmony" are trademarks of Logitech International S.A.
harmonyforge is not affiliated with, endorsed by, or connected to Logitech in
any way. The names are used solely to identify the hardware this software
interoperates with.
