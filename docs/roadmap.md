# Roadmap

## The big missing piece: the binary config compiler

harmonyforge can read and write the remote's configuration region as an
opaque blob. It can model a configuration — devices, activities, button
maps — in its own format. What it **cannot** do yet is turn the second into
the first.

That matters, so here is exactly where the boundary sits.

**Works today**

- Read the config region off the remote (`backup`)
- Write a previously-read blob back (`restore`)
- Build, edit and validate a `RemoteConfig` in harmonyforge's format
- Collect, decode and organise all the IR codes it needs

**Does not work today**

- Compiling a `RemoteConfig` into the remote's native binary format

So you can back up, you can restore, and you can design a configuration. You
cannot yet push a *newly designed* configuration onto a USB remote.

### Why this is hard

It is not undocumented from zero anymore, which is worth being precise
about. The outer container — a header with a cookie/magic, an
end-of-config address, and a table of absolute flash addresses pointing at
~18 contiguous sections — is reverse-engineered and confirmed shared
across architectures 8, 9, 12 and 14 by the
[harmony-decompiler](https://github.com/trelowney/harmony-decompiler)
project. harmonyforge implements that container layer
(`config/binary.py`), independently re-verified against a real
architecture-14 backup — see `docs/binary-config-format.md`.

What remains genuinely unmapped is the **contents** of those sections for
architecture 12 and 14: the device table, the activity table, and the
button-to-matrix mapping. harmony-decompiler has done that depth of work
for architecture 9 (over 99% of a 525 config decodes); nobody has done it
for 12 or 14 yet. That is real, substantial reverse-engineering work, not
a thin remaining gap.

One hard-won finding changes how that work has to proceed:
**naive diffing between two config dumps does not work.** A config is a
compiled image full of absolute pointers, so any length-changing edit
reshuffles everything after it — two dumps differing by one small change
can disagree in 70-85% of their bytes, with the first difference always
landing on the end-of-config address itself. Collecting "before and after"
pairs, which is what this document used to recommend, does not shortcut
the problem the way it seems like it should.

### How to get there

In rough order of effort and payoff:

1. **Contribute real samples.** Not pairs — single backups, from different
   physical remotes on architecture 12 or 14 (the 665, the 700, the One).
   This is how harmony-decompiler established the 650/890 shared structure:
   comparing dumps from different contributors, not before/after diffing
   one person's remote. `harmonyforge backup` plus the `.json` sidecar is
   enough; no change needs to be made to the remote first.

2. **Map section contents**, following harmony-decompiler's own method on
   architecture 9 as the template: decompile to a structured
   representation, cross-validate against something independently
   checkable (they rendered the remote's own menu screens as bitmaps
   offline to confirm their decode), and require recompiling to produce
   byte-identical output before trusting any of it.

3. **Solve the button-matrix mapping separately.** Even a fully-decoded
   config stores buttons as keyboard-matrix coordinates in Logitech's
   internal ordering, not the remote's visual layout — this is unsolved
   even on the one architecture that is otherwise fully mapped, and needs
   its own evidence (hardware schematics, or systematic probing).

4. **Round-trip test.** Decompile a real blob, recompile it, and require
   the bytes to match exactly. Until that passes for architecture 14,
   writing a generated config to a 665 or 700 is not safe at any step.

If you have a 665, 700, or One and are willing to contribute a backup,
please [open an issue](https://github.com/av1452/harmonyforge/issues) or
send it to harmony-decompiler directly — either is the critical path right
now.

## Other planned work

### Hardware validation

Every USB code path is implemented and unit-tested, and none of it has
touched a physical remote. Confirmations — positive or negative — are the
second most useful contribution. Running `harmonyforge identify --verbose`
and pasting the output into an issue is enough to validate the identity path
for a model.

### The usbnet family (890, 900, 1100)

These present Ethernet-over-USB rather than HID, and locate their config
through an on-device region table rather than a fixed address. harmonyforge
detects them and declines rather than guessing. Supporting them means
implementing the region-table lookup and the USBNET transport;
[concordance](https://github.com/jaymzh/concordance) already does both, so
this is a porting job rather than research.

### Architecture 16 and 17 (300, 350, Link, Touch)

Identify works. These use a virtual-filesystem protocol ("MH") rather than
raw flash addressing, implemented in libconcord's `remote_mh.cpp`.

### Firmware updates

libconcord can flash firmware. harmonyforge deliberately does not: the
failure mode is a brick, and the safe-mode recovery path needs hardware
testing before it would be responsible to ship. Not planned until the read
and write paths have real mileage.

### More IR protocols

RC-6 (Microsoft MCE remotes), RCMM, NECext42, Sharp, Denon, Nokia NRC17.
Each is self-contained — a codec class plus a round-trip test — and
unrecognised codes already work as raw captures, so these are quality-of-life
rather than blocking. Good first contributions.

### IR transmission from the host

Sending codes from the computer, through a USB IR blaster or a Flipper Zero,
would let you verify a code is correct before committing it to the remote.
Currently the only way to test a code is to write it and try.

### Activity simulation

A dry-run that plays an activity's start sequence as a timeline, showing what
would be sent when and flagging races — a device being sent an input-select
command before its power-on delay has elapsed, for instance. Pure logic, no
hardware needed, and it would catch a large fraction of real configuration
bugs.

## Non-goals

**Reimplementing Logitech's cloud.** The point is local-first. Your
configuration is a file you own.

**Scraping Logitech's device database.** It is gone, and it was not ours. The
open collections — LIRC, Flipper-IRDB — plus the remote's own learning eye
cover the same ground legitimately.

**Supporting non-Harmony remotes.** The IR layer is generic enough to be
useful elsewhere, and is deliberately importable on its own, but the project
scope is Harmony hardware.
