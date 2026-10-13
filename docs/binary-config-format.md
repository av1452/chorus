# The config binary format

This is a different, separately-sourced layer from the rest of
Chorus's documentation. Everything else here traces back to
libconcord, which treats the configuration region as an opaque blob -- it
reads and writes it, but never looks inside. This page documents what is
inside, which is a different (and much less complete) body of knowledge.

## What's confirmed, and against what

All of this comes from the
[harmony-decompiler](https://github.com/trelowney/harmony-decompiler)
project (GPLv3), primarily `docs/FORMAT.md` in that repository, which
documents a byte-for-byte reverse engineering of a Harmony 525 (architecture
9) config, cross-checked against three other architectures by a thirteen-
sample corpus (`@dannybloe`, their issue #66).

**Independently re-confirmed here** against a real Harmony 665
(architecture 14) backup -- not taken on trust:

- The cookie `GSPM` decodes as exactly `0x4D505347`, the same value
  libconcord's own architecture table carries for architecture 14. Two
  unrelated reverse-engineering efforts, agreeing exactly.
- `config_base` recovered from the header's own fields
  (`end_address - blob_length + 4`) computes to exactly `0x030000` -- again,
  libconcord's independently-sourced value for this architecture.
- Section slot 1 decodes to `0E 0E 4B 0D 00 00 00` -- architecture `14, 14`,
  matching the architecture this same remote reported live over USB in the
  same session, from a completely different code path (the identity
  response, not the flash contents).

Three independent checks, zero discrepancies. That is why this module
exists rather than staying a one-off exploration.

## The container

A config blob (the raw flash bytes at `config_base` -- what
`chorus backup` saves, no XML wrapper) starts with:

```
0x00  4 bytes   cookie / magic (architecture-specific)
0x04  u32 LE    absolute flash address of end-of-config
0x08  u32 LE    unknown constant (0x1400 on both arch 9 and arch 14)
0x0C  u32[N]    section pointer table, N architecture-dependent, last entry null
...   3 bytes   zero padding
...   4 bytes   header-end marker (architecture-specific)
...            section contents (opaque past this point)
(end-4)  4 bytes   blob-end marker (architecture-specific, mirrors the cookie)
```

Addresses in the pointer table are **absolute flash addresses**, not file
offsets: `file_offset = address - config_base`. Sections are contiguous
with no gaps, so a section's length is simply the distance to the next
section's address -- except the last real section, which has no next
pointer to diff against.

### Per-architecture constants

| architecture | cookie | header-end marker | blob-end marker | slots |
|---|---|---|---|---|
| 8 | `TPTP` | `WLWL` | `DKDK` | 20 (one null mid-table, one trailing) |
| 9 | `AHCM` | `CMAH` | `MCHA` | 19 (last null) |
| 12 | `GSPM` | `LWJL` | `PTYY` | 21 |
| 14 | `GSPM` | `LWJL` | `PTYY` | 19 (last null) |

Architecture 8's table has a **null in the middle**, not only at the end --
reading until the first zero (the obvious implementation) silently
truncates it. `chorus.config.binary.Section.is_present` exists
because of this.

## What this gets you, and what it does not

`chorus.config.binary.parse_container()` gets you the header fields
and the byte range of each section. That is genuinely useful on its own --
`chorus inspect-binary <backup>` will show you the shape of your own
config without needing the remote attached.

**It does not decode what is inside any section.** That is a separate, much
larger body of work that harmony-decompiler has done in real depth for
architecture 9 (over 99% of a 525 config decodes, including the menu-screen
bitmaps and the key-binding tables) and barely touched for architecture 12
or 14. Nobody -- not harmony-decompiler, not this port -- has published a
device table, activity table, or button-matrix mapping for architecture 14.
That is the actual remaining work, and it is substantial: see
[FORMAT.md](https://github.com/trelowney/harmony-decompiler/blob/main/docs/FORMAT.md)
for the scale of what solving it for one architecture looked like.

One structural finding worth knowing before attempting it: **naive diffing
between two config dumps does not work.** Any logical change that alters a
structure's length reshuffles every absolute pointer after it in the file,
so two configs differing by one small edit can disagree in 70-85% of their
bytes. harmony-decompiler's approach -- decompile to a structured
representation, edit that, recompile, and require the result to be byte-
identical to a direct re-encoding -- exists specifically because patching
in place does not.

## What this means for Chorus's own roadmap

This closes part of the gap described in `docs/roadmap.md`, but not the
practical one. Understanding the container tells you *where* the device and
activity data would live; it does not tell you *what format* that data is
in for architecture 14, which is the part that would actually let
`RemoteConfig` compile into something writable. Nothing in this module
writes to a remote, and nothing should, until section contents are mapped
and a round-trip (decode a real config, re-encode it, get the identical
bytes back) has been demonstrated -- the same bar harmony-decompiler held
itself to before trusting its own output.

## Contributing

The single most useful thing you can add: a real backup (`chorus
backup`) from a Harmony 665, 700, or anything else on architecture 12 or
14, with its `.json` sidecar. No paired before/after samples needed --
per the diffing finding above, they would not help directly anyway.
Multiple independent samples from *different* remotes of the same
architecture are what let harmony-decompiler confirm the 650/890 shared
structure; the equivalent does not yet exist for 12/14.

If you want to go further than contributing a sample, consider sending it
to harmony-decompiler directly (they have the deeper methodology and
existing arch-9 code to extend) as well as or instead of this project --
this module's scope is deliberately limited to the part that is solidly
confirmed.
