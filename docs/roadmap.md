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

The binary format is undocumented, and nobody has fully reverse-engineered
it. libconcord — which has driven these remotes for fifteen years — has the
same gap: it moves config blobs between the cloud and the device, and
deliberately treats them as opaque. It never needed to generate one, because
Logitech's servers did that.

The format is also not one format. It varies by architecture and by firmware
revision, and it contains internal offset tables that have to be
self-consistent. A blob that is structurally wrong does not fail cleanly; it
produces a remote that behaves erratically.

### How to get there

In rough order of effort and payoff:

1. **Collect blobs.** The format becomes tractable with a corpus: several
   backups from the same model with known, deliberately-varied configurations
   (add one device; rename an activity; change one button). Diffing those
   isolates fields fast. This is the single most useful contribution anyone
   with a remote can make, and it needs no reverse-engineering skill — just
   `backup`, a change made with any still-working tool, and `backup` again.

2. **Map the header.** The cookie and end-vector are already known from the
   architecture table. The region immediately after almost certainly holds
   counts and offsets for the device and activity tables.

3. **Map the IR code table.** Probably the easiest large structure to find,
   because we can generate a config containing one known IR code and search
   the blob for its timings.

4. **Write a compiler per architecture**, starting with architecture 7 (the
   600/650/665 family) as the most common.

5. **Round-trip test**: decompile a real blob, recompile it, and require the
   bytes to match. Until that passes for a given model, writing a generated
   config to that model is not safe.

If you have a Harmony remote and are willing to help with step 1, please
[open an issue](https://github.com/av1452/harmonyforge/issues) — that is the
critical path.

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
