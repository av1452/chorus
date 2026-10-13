"""Command-line interface for harmonyforge."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__, devicedb
from .errors import HarmonyForgeError

log = logging.getLogger("harmonyforge")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _supports_colour(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


class Printer:
    """Terminal output with optional colour and a progress line."""

    def __init__(self, *, quiet: bool = False, colour: bool | None = None):
        self.quiet = quiet
        self.colour = _supports_colour(sys.stdout) if colour is None else colour
        self._progress_active = False

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.colour else text

    def say(self, text: str = "") -> None:
        if not self.quiet:
            self._clear_progress()
            print(text)

    def ok(self, text: str) -> None:
        self.say(f"{self._paint('✓', '32')} {text}")

    def warn(self, text: str) -> None:
        self._clear_progress()
        print(f"{self._paint('!', '33')} {text}", file=sys.stderr)

    def fail(self, text: str) -> None:
        self._clear_progress()
        print(f"{self._paint('✗', '31')} {text}", file=sys.stderr)

    def heading(self, text: str) -> None:
        self.say()
        self.say(self._paint(text, "1"))
        self.say(self._paint("─" * len(text), "2"))

    def progress(self, done: int, total: int, label: str) -> None:
        if self.quiet or not self.colour:
            return
        total = max(1, total)
        fraction = min(1.0, done / total)
        width = 28
        filled = int(width * fraction)
        bar = "█" * filled + "░" * (width - filled)
        sys.stdout.write(f"\r  {label:<8} {bar} {fraction * 100:5.1f}%")
        sys.stdout.flush()
        self._progress_active = True
        if fraction >= 1.0:
            self._clear_progress()

    def _clear_progress(self) -> None:
        if self._progress_active:
            sys.stdout.write("\r" + " " * 60 + "\r")
            sys.stdout.flush()
            self._progress_active = False


# ---------------------------------------------------------------------------
# Device access
# ---------------------------------------------------------------------------


def _open(args, printer: Printer):
    """Open and identify the attached remote."""
    from .usb.remote import HarmonyRemote
    from .usb.transport import open_remote

    transport = open_remote(args.backend)
    remote = HarmonyRemote(transport)
    identity = remote.identify()
    if not args.quiet:
        printer.ok(f"Found {identity.name} (firmware {identity.firmware})")
    return remote


# ---------------------------------------------------------------------------
# Commands: hardware
# ---------------------------------------------------------------------------


def cmd_detect(args, printer: Printer) -> int:
    """List attached remotes without claiming them."""
    from .usb.transport import enumerate_remotes

    devices = enumerate_remotes()
    if not devices:
        printer.fail("No Harmony remote found on USB.")
        printer.say()
        printer.say("Checklist:")
        printer.say("  1. Connect the remote with its USB cable (data, not")
        printer.say("     charge-only -- this is the usual culprit).")
        printer.say("  2. Older remotes must be powered on to enumerate.")
        printer.say("  3. Hub-based remotes (Hub, Elite, Companion, Ultimate)")
        printer.say("     never appear on USB -- use `harmonyforge hub discover`.")
        return 1

    printer.heading(f"{len(devices)} remote(s) attached")
    for info in devices:
        printer.say(f"  {info}")
        if info.is_usbnet:
            printer.warn(
                "  This is a usbnet-family remote (890/900/1100); "
                "harmonyforge cannot program it yet."
            )
    printer.say()
    printer.say("Run `harmonyforge identify` for full details.")
    return 0


def cmd_identify(args, printer: Printer) -> int:
    """Identify the attached remote in detail."""
    remote = _open(args, printer)
    try:
        identity = remote.identity
        assert identity is not None
        printer.heading("Remote")
        printer.say(identity.summary())

        if args.verbose:
            printer.heading("Architecture")
            arch = identity.architecture
            if arch is None:
                printer.warn("unknown architecture -- no layout data")
            else:
                for field_name in (
                    "index", "serial_location", "serial_address", "flash_base",
                    "firmware_base", "config_base", "cookie", "cookie_size",
                    "end_vector", "micro", "usb",
                ):
                    value = getattr(arch, field_name)
                    if isinstance(value, int) and field_name.endswith(
                        ("base", "address", "cookie")
                    ):
                        value = f"0x{value:06X}" if value >= 0 else str(value)
                    printer.say(f"  {field_name:<22} {value}")
            printer.heading("Serial numbers")
            for i, serial in enumerate(identity.serials, 1):
                printer.say(f"  serial{i}  {serial}")

        if not identity.valid_config:
            printer.warn(
                "This remote has no valid configuration stored. That is "
                "normal for a factory-reset remote."
            )
        return 0
    finally:
        remote.transport.close()


def cmd_backup(args, printer: Printer) -> int:
    """Read the remote's configuration to a file."""
    remote = _open(args, printer)
    try:
        identity = remote.identity
        assert identity is not None
        target = Path(args.output)

        printer.say(f"Reading configuration from {identity.name}...")
        blob = remote.read_config(progress=printer.progress)
        target.write_bytes(blob)

        meta = target.with_suffix(target.suffix + ".json")
        meta.write_text(
            json.dumps(
                {
                    "model": identity.name,
                    "skin": identity.skin,
                    "architecture": identity.architecture_index,
                    "protocol": identity.protocol,
                    "firmware": identity.firmware,
                    "hardware": identity.hardware,
                    "flash": identity.flash.name,
                    "serial": identity.serial,
                    "config_bytes": len(blob),
                    "valid_config": identity.valid_config,
                    "harmonyforge_version": __version__,
                },
                indent=2,
            )
            + "\n"
        )
        printer.ok(f"Wrote {len(blob):,} bytes to {target}")
        printer.ok(f"Wrote metadata to {meta}")
        printer.say()
        printer.say("Keep this file. It is the only way back to the remote's")
        printer.say("current state -- there is no undo on the device.")
        return 0
    finally:
        remote.transport.close()


def cmd_restore(args, printer: Printer) -> int:
    """Write a previously backed-up configuration blob to the remote."""
    source = Path(args.input)
    if not source.exists():
        printer.fail(f"no such file: {source}")
        return 1
    blob = source.read_bytes()

    remote = _open(args, printer)
    try:
        identity = remote.identity
        assert identity is not None

        meta_path = source.with_suffix(source.suffix + ".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                meta = {}
            if meta.get("skin") is not None and meta["skin"] != identity.skin:
                printer.fail(
                    f"This backup came from a {meta.get('model')} (skin "
                    f"{meta['skin']}) but the attached remote is "
                    f"{identity.name} (skin {identity.skin})."
                )
                printer.say(
                    "Writing it would brick the configuration. Pass --force "
                    "only if you are certain."
                )
                if not args.force:
                    return 1

        printer.warn(
            f"About to erase and rewrite {len(blob):,} bytes of configuration "
            f"on {identity.name}."
        )
        if not args.yes:
            reply = input("Type 'yes' to continue: ").strip().lower()
            if reply != "yes":
                printer.say("Aborted.")
                return 1

        remote.write_config(
            blob, verify=not args.no_verify, progress=printer.progress
        )
        printer.ok("Configuration written and verified.")
        printer.say("Disconnect the remote to let it restart.")
        return 0
    finally:
        remote.transport.close()


def cmd_read_flash(args, printer: Printer) -> int:
    """Dump an arbitrary flash range (for development and debugging)."""
    remote = _open(args, printer)
    try:
        addr = int(args.address, 0)
        length = int(args.length, 0)
        printer.say(f"Reading 0x{addr:06X}..0x{addr + length:06X}")
        data = remote.read_flash(addr, length, progress=printer.progress)
        if args.output:
            Path(args.output).write_bytes(data)
            printer.ok(f"Wrote {len(data):,} bytes to {args.output}")
        else:
            _hexdump(data, addr, printer)
        return 0
    finally:
        remote.transport.close()


def cmd_inspect_binary(args, printer: Printer) -> int:
    """Parse a backup's container structure (header and section table).

    This does not need the remote attached -- it works on a file already
    saved by `backup`. It only decodes the outer container; the content of
    each section is unmapped for most architectures. See
    docs/binary-config-format.md for exactly what is and is not known.
    """
    from . import devicedb
    from .config.binary import BinaryFormatError, parse_container

    source = Path(args.path)
    if not source.exists():
        printer.fail(f"no such file: {source}")
        return 1
    blob = source.read_bytes()

    architecture = args.architecture
    if architecture is None:
        meta_path = source.with_suffix(source.suffix + ".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                architecture = meta.get("architecture")
            except json.JSONDecodeError:
                pass
    if architecture is None:
        printer.fail(
            "no --architecture given, and no <file>.json sidecar to read it "
            "from. Pass it explicitly, e.g. --architecture 14."
        )
        return 2

    arch = devicedb.architecture(architecture)
    if arch is None:
        printer.fail(f"unknown architecture {architecture}")
        return 1

    try:
        header = parse_container(blob, architecture=architecture, config_base=arch.config_base)
    except BinaryFormatError as exc:
        printer.fail(str(exc))
        return 1

    printer.heading(f"Container (architecture {architecture})")
    printer.say(f"cookie:        {header.cookie!r}")
    printer.say(f"end_address:   0x{header.end_address:06X}")
    printer.say(f"unknown_field: 0x{header.unknown_field:X}")
    printer.say(f"config_base:   0x{header.config_base:06X}")
    printer.say()
    printer.say(f"{len(header.sections)} slots:")
    for section in header.sections:
        if not section.is_present:
            printer.say(f"  {section.index:2}: (absent)")
        elif section.length is not None:
            printer.say(
                f"  {section.index:2}: offset=0x{section.file_offset:06X} "
                f"length={section.length:,}"
            )
        else:
            printer.say(
                f"  {section.index:2}: offset=0x{section.file_offset:06X} "
                "length=(runs to end of blob)"
            )
    printer.say()
    printer.say(
        "This is the container only -- what each section actually contains "
        "is not decoded. See docs/binary-config-format.md."
    )
    return 0


def _hexdump(data: bytes, base: int, printer: Printer) -> None:
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk).ljust(47)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        printer.say(f"{base + offset:06X}  {hexpart}  |{text}|")


def cmd_remotes(args, printer: Printer) -> int:
    """List the remote models this tool knows about."""
    if args.search:
        hits = devicedb.search_models(args.search)
        if not hits:
            printer.fail(f"no model matching {args.search!r}")
            return 1
    else:
        hits = [(i, m) for i, m in enumerate(devicedb.MODELS) if m.known]

    printer.heading(f"{len(hits)} known remote models")
    printer.say(f"  {'skin':>4}  {'model':<26} {'maker':<14} internal name")
    for index, model in hits:
        printer.say(
            f"  {index:>4}  {model.name:<26} {model.manufacturer:<14} "
            f"{model.skin or ''}"
        )
    printer.say()
    printer.say("The skin ID is what the remote reports over USB.")
    printer.say("See HARDWARE.md for which models are programmable today.")
    return 0


# ---------------------------------------------------------------------------
# Commands: IR
# ---------------------------------------------------------------------------


def cmd_learn(args, printer: Printer) -> int:
    """Learn IR codes using the remote's learning eye."""
    from .ir import pronto, protocols
    from .ir.database import CodeLibrary, CodeSet
    from .ir.signal import average

    remote = _open(args, printer)
    try:
        library = CodeLibrary(args.library)
        if args.device:
            try:
                code_set = library.find(args.device)
                printer.say(f"Adding to existing code set: {code_set.label}")
            except HarmonyForgeError:
                code_set = CodeSet(
                    name=args.device,
                    manufacturer=args.manufacturer or "",
                    model=args.device,
                    source="learned",
                )
                printer.say(f"Creating new code set: {code_set.label}")
        else:
            code_set = None

        printer.say()
        printer.say("Hold the source remote 2-5 cm from the Harmony's IR")
        printer.say("learning window (the dark panel on the front edge),")
        printer.say("pointing straight at it.")
        printer.say()

        for name in args.names:
            captures = []
            for attempt in range(args.repeat):
                suffix = (
                    f" (capture {attempt + 1} of {args.repeat})"
                    if args.repeat > 1
                    else ""
                )
                input(f"  Press ENTER, then press '{name}'{suffix}... ")
                try:
                    signal = remote.learn_ir().snapped()
                except HarmonyForgeError as exc:
                    printer.fail(f"  {exc}")
                    break
                printer.ok(f"  captured {signal}")
                captures.append(signal)

            if not captures:
                continue

            if len(captures) > 1:
                try:
                    signal = average(captures)
                    printer.ok("  averaged the captures")
                except HarmonyForgeError as exc:
                    printer.warn(f"  {exc}; keeping the first capture")
                    signal = captures[0]
            else:
                signal = captures[0]

            decoded = protocols.identify(signal)
            if decoded:
                printer.ok(f"  recognised as {decoded}")
            else:
                printer.say("  (unrecognised protocol; stored as a raw capture)")

            if args.pronto:
                printer.say(f"  pronto: {pronto.format_signal(signal)}")

            if code_set is not None:
                code_set.add(name, signal)

        if code_set is not None and code_set.functions:
            path = library.save(code_set)
            printer.say()
            printer.ok(
                f"Saved {len(code_set.functions)} function(s) to {path}"
            )
        return 0
    finally:
        remote.transport.close()


def cmd_codes(args, printer: Printer) -> int:
    """Manage the local IR code library."""
    from .ir import pronto
    from .ir.database import CodeLibrary

    library = CodeLibrary(args.library)

    if args.codes_command == "list":
        sets = list(library)
        if not sets:
            printer.say(f"The code library at {library.root} is empty.")
            printer.say()
            printer.say("Fill it by learning codes from your original remotes:")
            printer.say("  harmonyforge learn --device 'Sony TV' PowerOn VolUp")
            printer.say()
            printer.say("Or import an existing collection:")
            printer.say("  harmonyforge codes import ~/Flipper-IRDB")
            return 0
        printer.heading(f"{len(sets)} code set(s) in {library.root}")
        for code_set in sets:
            printer.say(
                f"  {code_set.slug:<34} {len(code_set.functions):>4} functions"
                f"   {code_set.source}"
            )
        return 0

    if args.codes_command == "search":
        hits = library.search(args.query)
        if not hits:
            printer.fail(f"nothing matching {args.query!r}")
            return 1
        printer.heading(f"{len(hits)} match(es)")
        for code_set in hits:
            printer.say(f"  {code_set.slug:<34} {code_set.label}")
            printer.say(
                f"      {', '.join(sorted(code_set.functions)[:10])}"
                + (" ..." if len(code_set.functions) > 10 else "")
            )
        return 0

    if args.codes_command == "show":
        code_set = library.find(args.device)
        printer.heading(code_set.label)
        printer.say(f"slug:     {code_set.slug}")
        printer.say(f"source:   {code_set.source}")
        if code_set.notes:
            printer.say(f"notes:    {code_set.notes}")
        printer.say()
        for name in sorted(code_set.functions):
            signal = code_set.functions[name]
            printer.say(f"  {name:<22} {signal}")
            if args.pronto:
                printer.say(f"      {pronto.format_signal(signal)}")
        return 0

    if args.codes_command == "import":
        source = Path(args.path)
        if source.is_dir():
            printer.say(f"Scanning {source} for .ir and lircd.conf files...")
            imported, problems = library.import_tree(source)
            for code_set in imported:
                library.save(code_set)
            printer.ok(f"Imported {len(imported)} code set(s)")
            if problems:
                printer.warn(f"{len(problems)} file(s) could not be imported")
                for problem in problems[: args.show_problems]:
                    printer.say(f"    {problem}")
                if len(problems) > args.show_problems:
                    printer.say(
                        f"    ... and {len(problems) - args.show_problems} more"
                    )
            return 0 if imported else 1

        if source.suffix.lower() == ".ir":
            code_set = library.import_flipper(source)
            library.save(code_set)
            printer.ok(f"Imported {code_set}")
            return 0

        sets = library.import_lirc(source)
        for code_set in sets:
            library.save(code_set)
            printer.ok(f"Imported {code_set}")
        return 0

    if args.codes_command == "export":
        from .ir import flipper

        code_set = library.find(args.device)
        signals = [
            code_set.functions[name] for name in sorted(code_set.functions)
        ]
        for name, signal in zip(
            sorted(code_set.functions), signals, strict=True
        ):
            object.__setattr__(signal, "name", name)
        text = flipper.dump(signals)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            printer.ok(f"Wrote {args.output}")
        else:
            printer.say(text)
        return 0

    printer.fail("unknown codes subcommand")
    return 2


def cmd_pronto(args, printer: Printer) -> int:
    """Convert and inspect Pronto hex codes."""
    from .ir import pronto, protocols

    if args.pronto_command == "decode":
        signal = pronto.parse(" ".join(args.code))
        decoded = protocols.identify(signal)
        printer.heading("Pronto code")
        printer.say(f"carrier:    {signal.frequency} Hz")
        printer.say(f"durations:  {len(signal.durations)}")
        printer.say(f"length:     {signal.total_us / 1000:.2f} ms")
        printer.say(f"protocol:   {decoded if decoded else 'unrecognised'}")
        if args.verbose:
            printer.say()
            printer.say("  " + " ".join(str(d) for d in signal.durations))
        return 0

    if args.pronto_command == "encode":
        fields: dict[str, int] = {}
        for pair in args.field:
            if "=" not in pair:
                printer.fail(f"expected name=value, got {pair!r}")
                return 2
            key, _, value = pair.partition("=")
            fields[key.strip()] = int(value.strip(), 0)
        signal = protocols.encode(args.protocol, **fields)
        printer.say(pronto.format_signal(signal))
        return 0

    printer.fail("unknown pronto subcommand")
    return 2


# ---------------------------------------------------------------------------
# Commands: configuration
# ---------------------------------------------------------------------------


def cmd_config(args, printer: Printer) -> int:
    """Create, inspect and validate configuration files."""
    from .config.model import RemoteConfig

    if args.config_command == "new":
        target = Path(args.path)
        if target.exists() and not args.force:
            printer.fail(f"{target} already exists (use --force to overwrite)")
            return 1
        config = RemoteConfig(name=args.name, remote_model=args.model or "")
        config.save(target)
        printer.ok(f"Created {target}")
        printer.say()
        printer.say("Next steps:")
        printer.say("  harmonyforge learn --device 'My TV' PowerOn PowerOff")
        printer.say(f"  harmonyforge serve --config {target}")
        return 0

    config = RemoteConfig.load(args.path)

    if args.config_command == "show":
        printer.say(config.summary())
        return 0

    if args.config_command == "validate":
        warnings = config.validate()
        if not warnings:
            printer.ok(f"{args.path} looks good: no problems found.")
            return 0
        printer.heading(f"{len(warnings)} problem(s)")
        for warning in warnings:
            printer.warn(warning)
        return 1 if args.strict else 0

    printer.fail("unknown config subcommand")
    return 2


# ---------------------------------------------------------------------------
# Commands: hub
# ---------------------------------------------------------------------------


def cmd_hub(args, printer: Printer) -> int:
    """Talk to a Harmony Hub over the local network."""
    from .hub.client import HarmonyHub
    from .hub.discovery import discover

    if args.hub_command == "discover":
        printer.say("Searching for Harmony Hubs (SSDP)...")
        hubs = discover(timeout=args.timeout)
        if not hubs:
            printer.fail("No hubs answered.")
            printer.say()
            printer.say("SSDP is often blocked across VLANs or by client")
            printer.say("isolation. If you know the hub's IP, skip discovery:")
            printer.say("  harmonyforge hub info --address 192.168.1.50")
            return 1
        printer.heading(f"{len(hubs)} hub(s) found")
        for hub in hubs:
            printer.say(f"  {hub}")
        return 0

    if not args.address:
        printer.fail("--address is required (or run `hub discover` first)")
        return 2

    hub = HarmonyHub(args.address, timeout=args.timeout)

    if args.hub_command == "info":
        printer.heading(f"Hub at {hub.address}")
        printer.say(f"remote id:  {hub.remote_id}")
        with hub:
            printer.say(f"activities: {len(hub.activities())}")
            printer.say(f"devices:    {len(hub.devices())}")
            printer.say(f"running:    {hub.current_activity()}")
        return 0

    with hub:
        if args.hub_command == "activities":
            activities = hub.activities()
            current = hub.current_activity()
            printer.heading(f"{len(activities)} activities")
            for activity in activities:
                marker = " <- running" if activity.id == current else ""
                printer.say(f"  {activity}{marker}")
            return 0

        if args.hub_command == "devices":
            devices = hub.devices()
            printer.heading(f"{len(devices)} devices")
            for device in devices:
                printer.say(f"  {device}")
                if args.verbose:
                    printer.say(
                        f"      {', '.join(sorted(device.commands)[:12])}"
                        + (" ..." if len(device.commands) > 12 else "")
                    )
            return 0

        if args.hub_command == "start":
            hub.start_activity(args.activity)
            printer.ok(f"Started activity {args.activity}")
            return 0

        if args.hub_command == "off":
            hub.power_off()
            printer.ok("Everything off")
            return 0

        if args.hub_command == "send":
            hub.send_command(args.device, args.command, hold_ms=args.hold)
            printer.ok(f"Sent {args.command} to device {args.device}")
            return 0

        if args.hub_command == "export":
            config = hub.to_config()
            config.save(args.output)
            printer.ok(f"Exported hub structure to {args.output}")
            printer.say()
            printer.warn(
                "The hub does not expose IR waveforms, so the functions are "
                "placeholders. Learn or import the actual codes to fill them."
            )
            return 0

    printer.fail("unknown hub subcommand")
    return 2


# ---------------------------------------------------------------------------
# Commands: web UI
# ---------------------------------------------------------------------------


def cmd_serve(args, printer: Printer) -> int:
    """Run the local web interface."""
    from .server.app import serve

    printer.ok(f"harmonyforge {__version__}")
    printer.say(f"Open http://{args.host}:{args.port} in your browser.")
    printer.say("Press Ctrl+C to stop.")
    printer.say()
    try:
        serve(
            host=args.host,
            port=args.port,
            config_path=args.config,
            library_path=args.library,
            open_browser=not args.no_browser,
        )
    except KeyboardInterrupt:
        printer.say()
        printer.say("Stopped.")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harmonyforge",
        description=(
            "Program Logitech Harmony remotes without Logitech. "
            "An open replacement for the retired MyHarmony software."
        ),
        epilog="Full documentation: https://github.com/av1452/harmonyforge",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="suppress progress output"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show more detail"
    )
    parser.add_argument(
        "--debug", action="store_true", help="log protocol-level detail"
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "pyusb", "hidapi", "fake"),
        default="auto",
        help="USB backend to use (default: auto)",
    )
    parser.add_argument(
        "--library",
        metavar="DIR",
        default=None,
        help="IR code library directory (default: ~/.harmonyforge/codes)",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("detect", help="list attached remotes").set_defaults(
        func=cmd_detect
    )

    p = sub.add_parser("identify", help="identify the attached remote")
    p.set_defaults(func=cmd_identify)

    p = sub.add_parser("backup", help="save the remote's configuration")
    p.add_argument("output", help="file to write the config blob to")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("restore", help="write a saved configuration back")
    p.add_argument("input", help="config blob previously made with `backup`")
    p.add_argument("--yes", action="store_true", help="skip the confirmation")
    p.add_argument("--force", action="store_true", help="ignore a model mismatch")
    p.add_argument("--no-verify", action="store_true", help="skip read-back check")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("read-flash", help="dump a raw flash range")
    p.add_argument("address", help="start address, e.g. 0x020000")
    p.add_argument("length", help="byte count, e.g. 1024")
    p.add_argument("-o", "--output", help="write to a file instead of stdout")
    p.set_defaults(func=cmd_read_flash)

    p = sub.add_parser(
        "inspect-binary",
        help="parse a backup's container structure (header, section table)",
    )
    p.add_argument("path", help="a file previously written by `backup`")
    p.add_argument(
        "--architecture",
        type=int,
        help="override the architecture (default: read from the .json sidecar)",
    )
    p.set_defaults(func=cmd_inspect_binary)

    p = sub.add_parser("remotes", help="list known remote models")
    p.add_argument("-s", "--search", help="filter by name")
    p.set_defaults(func=cmd_remotes)

    p = sub.add_parser("learn", help="learn IR codes from another remote")
    p.add_argument("names", nargs="+", help="function names to learn")
    p.add_argument("-d", "--device", help="code set to store them in")
    p.add_argument("-m", "--manufacturer", help="device manufacturer")
    p.add_argument(
        "-r",
        "--repeat",
        type=int,
        default=1,
        help="captures to average per button (default: 1)",
    )
    p.add_argument("--pronto", action="store_true", help="print Pronto hex")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("codes", help="manage the IR code library")
    codes = p.add_subparsers(dest="codes_command", metavar="<subcommand>")
    codes.add_parser("list", help="list stored code sets")
    s = codes.add_parser("search", help="search code sets")
    s.add_argument("query")
    s = codes.add_parser("show", help="show one code set")
    s.add_argument("device")
    s.add_argument("--pronto", action="store_true", help="include Pronto hex")
    s = codes.add_parser("import", help="import .ir, lircd.conf, or a directory")
    s.add_argument("path")
    s.add_argument(
        "--show-problems",
        type=int,
        default=5,
        help="how many import failures to print (default: 5)",
    )
    s = codes.add_parser("export", help="export a code set as a Flipper .ir file")
    s.add_argument("device")
    s.add_argument("-o", "--output")
    p.set_defaults(func=cmd_codes)

    p = sub.add_parser("pronto", help="convert Pronto hex codes")
    pro = p.add_subparsers(dest="pronto_command", metavar="<subcommand>")
    s = pro.add_parser("decode", help="describe a Pronto code")
    s.add_argument("code", nargs="+", help="the hex words")
    s = pro.add_parser("encode", help="build a Pronto code from a protocol")
    s.add_argument("protocol", help="NEC, NECext, RC5, SIRC, Samsung32, ...")
    s.add_argument(
        "field",
        nargs="+",
        metavar="name=value",
        help="e.g. address=0x04 command=0x0C",
    )
    p.set_defaults(func=cmd_pronto)

    p = sub.add_parser("config", help="work with configuration files")
    cfg = p.add_subparsers(dest="config_command", metavar="<subcommand>")
    s = cfg.add_parser("new", help="create an empty configuration")
    s.add_argument("path")
    s.add_argument("-n", "--name", default="My Harmony")
    s.add_argument("-m", "--model", help="remote model this targets")
    s.add_argument("--force", action="store_true")
    s = cfg.add_parser("show", help="summarise a configuration")
    s.add_argument("path")
    s = cfg.add_parser("validate", help="check a configuration for problems")
    s.add_argument("path")
    s.add_argument(
        "--strict", action="store_true", help="exit non-zero on warnings"
    )
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("hub", help="control a Harmony Hub over the network")
    p.add_argument("-a", "--address", help="hub IP address")
    p.add_argument(
        "-t", "--timeout", type=float, default=5.0, help="seconds (default: 5)"
    )
    hub = p.add_subparsers(dest="hub_command", metavar="<subcommand>")
    hub.add_parser("discover", help="find hubs via SSDP")
    hub.add_parser("info", help="show hub summary")
    hub.add_parser("activities", help="list activities")
    hub.add_parser("devices", help="list devices")
    s = hub.add_parser("start", help="start an activity")
    s.add_argument("activity", help="activity id")
    hub.add_parser("off", help="stop all activities")
    s = hub.add_parser("send", help="send one IR command")
    s.add_argument("device", help="device id")
    s.add_argument("command", help="command name")
    s.add_argument("--hold", type=int, default=0, help="hold time in ms")
    s = hub.add_parser("export", help="export hub structure to a config file")
    s.add_argument("-o", "--output", default="hub-config.json")
    p.set_defaults(func=cmd_hub)

    p = sub.add_parser("serve", help="run the local web interface")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8737)
    p.add_argument("-c", "--config", help="configuration file to edit")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    printer = Printer(quiet=args.quiet)

    # Subcommands with their own subcommands need one chosen.
    for group in ("codes_command", "pronto_command", "config_command", "hub_command"):
        if hasattr(args, group) and getattr(args, group) is None:
            printer.fail(f"`{args.command}` needs a subcommand")
            printer.say(f"Try: harmonyforge {args.command} --help")
            return 2

    try:
        return args.func(args, printer)
    except HarmonyForgeError as exc:
        printer.fail(str(exc))
        return 1
    except KeyboardInterrupt:
        printer.say()
        printer.say("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
