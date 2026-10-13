# Contributing

## The two things that help most

### 1. Try it on your remote and report back

Every USB code path here is implemented and unit-tested, and none of it has
touched physical hardware. A single report — working or broken — is worth
more than a feature.

Safe to run (these only read):

```bash
chorus detect
chorus identify --verbose
chorus backup my-remote.bin
```

Then [open an issue](https://github.com/av1452/chorus/issues) with the
`identify --verbose` output and your model. If something failed, add
`--debug` and include the packet log.

Please don't run `restore` on a remote you care about until someone has
confirmed the write path on your model.

### 2. Contribute config blobs

The main thing blocking Chorus from fully replacing MyHarmony is that
nobody has reverse-engineered the binary configuration format (see
[docs/roadmap.md](docs/roadmap.md)). Cracking it needs a corpus of blobs with
*known* differences:

```bash
chorus backup before.bin
# change exactly one thing, using any tool that still works for you
chorus backup after.bin
```

A pair like that, with a note saying what changed, isolates fields
immediately. No reverse-engineering skill required — just a remote and five
minutes. This is the critical path.

## Development setup

```bash
git clone https://github.com/av1452/chorus
cd chorus
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,yaml]"
pytest
ruff check src tests
```

262 tests, no hardware needed, about a fifth of a second.

## Working without hardware

`FakeTransport` simulates a remote well enough to exercise the whole stack:

```python
from chorus.usb.transport import FakeTransport
from chorus.usb.remote import HarmonyRemote

remote = HarmonyRemote(FakeTransport())
print(remote.identify().summary())
```

It records every report sent, so tests can assert on exact wire bytes:

```python
transport = FakeTransport()
remote = HarmonyRemote(transport)
remote.identify()
assert transport.written[0][0] == 0x10   # COMMAND_GET_VERSION
```

Pass `identity=` to simulate a different model — see `tests/test_remote.py`
for examples covering several architectures.

The CLI accepts `--backend fake` for the same purpose.

## Adding an IR protocol

The most self-contained useful contribution. RC-6, RCMM, Sharp, Denon and
Nokia NRC17 are all unimplemented.

1. Subclass `Protocol` in `ir/protocols.py`. If it is pulse-distance coded
   (a leader, then bits distinguished by space length), subclass
   `PulseDistanceProtocol` and just set the timings — NEC, Samsung32, JVC and
   Kaseikyo are all a dozen lines each that way.
2. Implement `encode(**fields) -> IRSignal` and
   `decode(signal) -> IRCommand | None`.
3. Add it to `PROTOCOLS`. **Order matters**: protocols with checksums go
   before ones without, so a NEC frame is never claimed by a looser decoder.
4. Add a round-trip test sweeping the full parameter range, and a test that
   it does not collide with existing protocols.

`decode` must return `None` rather than raise when a signal is not its
protocol — `identify` sweeps every codec in turn.

## Adding remote support

If `identify` says *"reports architecture N, which has no known memory
layout"*, the architecture table needs an entry. `devicedb.py` is generated
from libconcord's `remote_info.h`, so:

1. Check whether libconcord already has it, and if so regenerate:
   `python tools/gen_devicedb.py path/to/remote_info.h out.json`
2. If not, it needs real reverse-engineering: `config_base`, the cookie,
   `end_vector`, and where the serial lives. Open an issue first.

## Style

- **Error messages say what to do.** Not `"USB error"` but `"Could not claim
  the remote's USB interface: ... Another program may be holding it (close
  MyHarmony if installed)"`. The person reading it has less context than the
  code did.
- **Comments explain why, not what.** `# RC-5 bit 1 = space,mark. The leading
  space carries no information and cannot be transmitted` earns its place;
  `# increment the counter` does not.
- **Raise `ChorusError` subclasses** for anything a user could cause —
  the CLI catches that type and prints it without a traceback.
- **Warn rather than refuse** on configuration problems. Half-built configs
  must stay saveable.
- Line length 88, `ruff check src tests` must pass.

## Destructive operations

Anything that writes to a remote needs:

- a confirmation prompt, with `--yes` to skip it
- read-back verification by default, with `--no-verify` to skip
- a model check against backup metadata, overridable with `--force`

Follow `cmd_restore` in `cli.py`. The failure mode is someone's remote, and
replacing one is no longer possible.

## Pull requests

Tests pass, `ruff` clean, one logical change per PR. For protocol changes,
say whether you verified against hardware and on which model — that
information is more valuable than the diff.
