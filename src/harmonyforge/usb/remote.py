"""High-level operations against a connected Harmony remote."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import devicedb
from ..errors import (
    ProtocolError,
    TransportTimeout,
    UnsupportedRemoteError,
    VerifyError,
)
from ..ir.signal import IRSignal
from . import protocol as p
from .transport import Transport

log = logging.getLogger(__name__)

#: Called as ``progress(done, total, label)`` during long transfers.
ProgressCallback = Callable[[int, int, str], None]

GUID_GROUPS = (4, 2, 2, 2, 6)


def _format_guid(raw: bytes, byte_swapped: bool = True) -> str:
    """Render 16 bytes as a GUID string.

    Most HID remotes store the first three groups little-endian (the classic
    mixed-endian GUID layout). Architecture 14 and the Z-Wave/usbnet families
    store them straight through.
    """
    if byte_swapped:
        ordered = bytes(
            (raw[3], raw[2], raw[1], raw[0], raw[5], raw[4], raw[7], raw[6])
        ) + raw[8:16]
    else:
        ordered = raw[:16]

    out, pos = [], 0
    for size in GUID_GROUPS:
        out.append(ordered[pos : pos + size].hex().upper())
        pos += size
    return "-".join(out)


@dataclass
class RemoteIdentity:
    """Everything the remote tells us about itself."""

    firmware_version: tuple[int, int]
    hardware_version: tuple[int, int, int]
    flash_manufacturer_id: int
    flash_device_id: int
    architecture_index: int
    firmware_type: int
    skin: int
    protocol: int

    model: devicedb.Model = field(default=None)  # type: ignore[assignment]
    architecture: devicedb.Architecture | None = None
    flash: devicedb.Flash = field(default=None)  # type: ignore[assignment]

    serials: tuple[str, str, str] = ("", "", "")
    valid_config: bool = False
    config_bytes_used: int = 0
    max_config_size: int = 0

    @property
    def name(self) -> str:
        return f"{self.model.manufacturer} {self.model.name}"

    @property
    def firmware(self) -> str:
        return f"{self.firmware_version[0]}.{self.firmware_version[1]}"

    @property
    def hardware(self) -> str:
        major, minor, micro = self.hardware_version
        return f"{major}.{minor}.{micro}" if micro else f"{major}.{minor}"

    @property
    def serial(self) -> str:
        """The primary serial number, which is what MyHarmony displayed."""
        return self.serials[0]

    @property
    def config_usage(self) -> float:
        """Fraction of config space in use, 0.0-1.0."""
        if not self.max_config_size:
            return 0.0
        return min(1.0, self.config_bytes_used / self.max_config_size)

    def summary(self) -> str:
        lines = [
            f"Model:            {self.name}",
            f"Skin ID:          {self.skin}",
            f"Firmware:         {self.firmware} (type {self.firmware_type})",
            f"Hardware:         {self.hardware}",
            f"Architecture:     {self.architecture_index}",
            f"Protocol:         {self.protocol}",
            f"Flash:            {self.flash.name} "
            f"({self.flash.size_kb} KB, IDs "
            f"0x{self.flash_manufacturer_id:02X}/0x{self.flash_device_id:02X})",
            f"Serial:           {self.serial or 'unknown'}",
            f"Config valid:     {'yes' if self.valid_config else 'no'}",
        ]
        if self.valid_config:
            lines.append(
                f"Config size:      {self.config_bytes_used} / "
                f"{self.max_config_size} bytes "
                f"({self.config_usage * 100:.1f}% used)"
            )
        if self.model.skin:
            lines.append(f"Internal name:    {self.model.skin}")
        return "\n".join(lines)


class HarmonyRemote:
    """A connected remote, speaking the HID flash protocol.

    ``identify()`` must run before any flash operation, since the
    architecture it discovers is what tells us where the config lives.
    """

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.identity: RemoteIdentity | None = None

    # -- plumbing ---------------------------------------------------------

    @property
    def report_len(self) -> int:
        return self.transport.report_len

    def _exchange(self, packet: bytes, timeout_ms: int = 1000) -> p.Response:
        self.transport.write(packet)
        return p.parse(self.transport.read(timeout_ms))

    def _require_identity(self) -> RemoteIdentity:
        if self.identity is None:
            self.identify()
        assert self.identity is not None
        return self.identity

    def _require_arch(self) -> devicedb.Architecture:
        identity = self._require_identity()
        arch = identity.architecture
        if arch is None or not arch.supported:
            raise UnsupportedRemoteError(
                f"{identity.name} reports architecture "
                f"{identity.architecture_index}, which has no known memory "
                "layout. Please open an issue with the output of "
                "`harmonyforge identify --verbose`."
            )
        return arch

    # -- identity ---------------------------------------------------------

    def identify(self, *, read_config_info: bool = True) -> RemoteIdentity:
        """Ask the remote what it is."""
        response = self._exchange(p.get_version(self.report_len))

        if response.command != p.RESPONSE_VERSION_DATA:
            raise ProtocolError(
                f"expected a version response, got 0x{response.command:02X}. "
                "If the remote was just plugged in, give it a few seconds and "
                "retry."
            )
        if response.length_code not in (5, 7, 8):
            raise ProtocolError(
                f"version response has unexpected length code "
                f"{response.length_code}"
            )

        raw = response.raw
        short = response.length_code < 6

        identity = RemoteIdentity(
            firmware_version=(raw[1] >> 4, raw[1] & 0x0F),
            hardware_version=(raw[2] >> 4, raw[2] & 0x0F, 0),
            flash_device_id=raw[3],
            flash_manufacturer_id=raw[4],
            architecture_index=2 if short else raw[5] >> 4,
            firmware_type=0 if short else raw[5] & 0x0F,
            skin=2 if short else raw[6],
            protocol=0,
        )
        if response.length_code >= 8:
            identity.protocol = identity.architecture_index
        elif response.length_code == 7:
            identity.protocol = raw[7]

        identity.model = devicedb.model_for_skin(identity.skin)
        identity.architecture = devicedb.architecture(identity.architecture_index)
        identity.flash = devicedb.flash_chip(
            identity.flash_manufacturer_id, identity.flash_device_id
        )

        self.identity = identity

        if read_config_info and identity.architecture is not None:
            try:
                self._read_config_header(identity)
                self._read_serial(identity)
            except Exception as exc:
                # A remote with a blank or foreign config still deserves to be
                # identified; losing the extras is not fatal.
                log.warning("Could not read config header or serial: %s", exc)

        return identity

    def _read_config_header(self, identity: RemoteIdentity) -> None:
        arch = identity.architecture
        if arch is None or not arch.supported:
            return
        if arch.config_base == devicedb.REGION_USER_CONFIG:
            # Region table lookup is not implemented for usbnet remotes yet.
            return

        head = self.read_flash(arch.config_base, 1024, identity=identity)

        if arch.cookie_size == 2:
            cookie = int.from_bytes(head[:2], "little")
        else:
            cookie = int.from_bytes(head[:4], "little")
        identity.valid_config = cookie == arch.cookie

        if identity.valid_config:
            identity.max_config_size = identity.flash.size_bytes - (
                arch.config_base - arch.flash_base
            )
            end = int.from_bytes(
                head[arch.end_vector : arch.end_vector + 3], "little"
            )
            identity.config_bytes_used = (
                end - (arch.config_base - arch.flash_base)
            ) + 4
        else:
            identity.config_bytes_used = 0
            identity.max_config_size = identity.flash.size_bytes - (
                arch.config_base - arch.flash_base
            )

    def _read_serial(self, identity: RemoteIdentity) -> None:
        arch = identity.architecture
        if arch is None or not arch.supported:
            return

        if arch.serial_location == devicedb.SERIAL_IN_EEPROM:
            raw = self.read_misc(
                p.MISC_EEPROM, arch.serial_address, p.SERIAL_SIZE
            )
        elif arch.serial_location == devicedb.SERIAL_IN_FLASH:
            raw = self.read_flash(
                arch.serial_address, p.SERIAL_SIZE, identity=identity
            )
        else:
            return

        swapped = identity.architecture_index != 14
        identity.serials = (
            _format_guid(raw[0:16], swapped),
            _format_guid(raw[16:32], swapped),
            _format_guid(raw[32:48], swapped),
        )

    # -- flash ------------------------------------------------------------

    def read_flash(
        self,
        addr: int,
        length: int,
        *,
        identity: RemoteIdentity | None = None,
        progress: ProgressCallback | None = None,
    ) -> bytes:
        """Read ``length`` bytes starting at ``addr``."""
        identity = identity or self._require_identity()
        protocol = identity.protocol
        len_map = p.read_len_map(protocol)
        chunk_cap = p.max_read_chunk(protocol)

        out = bytearray()
        end = addr + length
        cursor = addr

        while cursor < end:
            chunk = min(chunk_cap, end - cursor)
            self.transport.write(p.read_flash(cursor, chunk, self.report_len))

            expected_seq = 1
            while True:
                response = p.parse(self.transport.read(1000))

                if response.command == p.RESPONSE_DONE:
                    break
                if response.command != p.RESPONSE_READ_FLASH_DATA:
                    raise ProtocolError(
                        f"unexpected response 0x{response.command:02X} during "
                        f"flash read at 0x{cursor:06X}"
                    )

                expected_seq = p.check_sequence(response.raw[1], expected_seq)
                expected_seq = (expected_seq + 0x11) & 0xFF

                size = len_map[response.length_code]
                if size:
                    out += response.raw[2 : 2 + size]
                    cursor += size

            if progress:
                progress(min(len(out), length), length, "Reading")

        return bytes(out[:length])

    def verify_flash(
        self,
        addr: int,
        expected: bytes,
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Read back ``addr`` and raise :class:`VerifyError` on mismatch."""
        actual = self.read_flash(addr, len(expected), progress=progress)
        if actual != expected:
            for i, (a, b) in enumerate(zip(actual, expected, strict=False)):
                if a != b:
                    raise VerifyError(
                        f"flash differs at 0x{addr + i:06X}: "
                        f"remote has 0x{a:02X}, expected 0x{b:02X}"
                    )
            raise VerifyError(
                f"flash length differs: read {len(actual)} of {len(expected)} bytes"
            )

    def erase_flash(
        self,
        addr: int,
        length: int,
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Erase every flash sector overlapping ``[addr, addr + length)``.

        Flash erases whole sectors, so this will clear slightly more than the
        requested range whenever the range is not sector-aligned.
        """
        identity = self._require_identity()
        arch = self._require_arch()
        sectors = identity.flash.sectors
        base = arch.flash_base
        end = addr + length

        boundaries = [s + base for s in sectors if s]
        targets = []
        start = base
        for boundary in boundaries:
            if boundary > addr and start < end:
                targets.append(start)
            start = boundary
            if start >= end:
                break

        if not targets:
            raise ProtocolError(
                f"no flash sector covers 0x{addr:06X}-0x{end:06X} on "
                f"{identity.flash.name}"
            )

        for i, sector_addr in enumerate(targets):
            log.debug("erasing sector at 0x%06X", sector_addr)
            self.transport.write(p.erase_flash(sector_addr, self.report_len))
            self.transport.read(5000)
            if progress:
                progress(i + 1, len(targets), "Erasing")

    def write_flash(
        self,
        addr: int,
        data: bytes,
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Write ``data`` at ``addr``. The region must already be erased."""
        identity = self._require_identity()
        protocol = identity.protocol
        chunk_cap = p.max_write_chunk(protocol)

        cursor = addr
        end = addr + len(data)
        written = 0

        while cursor < end:
            chunk = min(chunk_cap, end - cursor)
            self.transport.write(
                p.write_flash_setup(cursor, chunk, self.report_len)
            )

            outstanding = chunk
            while outstanding:
                code, block_len = p.pick_write_block(outstanding, protocol)
                offset = cursor - addr
                block = data[offset : offset + block_len]
                self.transport.write(
                    p.write_flash_data(block, code, self.report_len)
                )
                cursor += block_len
                written += block_len
                outstanding -= block_len

            self.transport.write(p.done(p.COMMAND_WRITE_FLASH, self.report_len))
            self.transport.read(5000)

            if progress:
                progress(written, len(data), "Writing")

    # -- misc region ------------------------------------------------------

    def read_misc(self, kind: int, addr: int, length: int = 1) -> bytes:
        """Read ``length`` bytes from a non-flash region, one byte per round trip."""
        out = bytearray()
        for i in range(length):
            response = self._exchange(
                p.read_misc(kind, addr + i, self.report_len)
            )
            if response.command != p.RESPONSE_READ_MISC_DATA:
                raise ProtocolError(
                    f"unexpected response 0x{response.command:02X} reading "
                    f"misc region {kind} at 0x{addr + i:02X}"
                )
            out.append(response.raw[1])
        return bytes(out)

    def invalidate_config(self) -> None:
        """Mark the stored config invalid, so the remote re-reads it."""
        response = self._exchange(p.invalidate_flash(self.report_len))
        if response.command != p.RESPONSE_DONE:
            raise ProtocolError(
                f"invalidate failed with 0x{response.command:02X}"
            )

    def reset(self, kind: int = p.RESET_DEVICE) -> None:
        """Reboot the remote. The USB connection drops as a result."""
        try:
            self.transport.write(p.reset(kind, self.report_len))
        except Exception as exc:
            # Several models (the 785 notably) reset before ACKing the write.
            log.debug("reset write reported an error, ignoring: %s", exc)

    # -- config -----------------------------------------------------------

    def read_config(
        self, *, progress: ProgressCallback | None = None
    ) -> bytes:
        """Read the remote's current configuration blob.

        Reads only the bytes the remote says are in use when it reports a
        valid config, and the whole region otherwise.
        """
        identity = self._require_identity()
        arch = self._require_arch()

        if arch.config_base == devicedb.REGION_USER_CONFIG:
            raise UnsupportedRemoteError(
                f"{identity.name} stores its config in a region table, which "
                "harmonyforge cannot read yet (see docs/roadmap.md)."
            )

        length = (
            identity.config_bytes_used
            if identity.valid_config and identity.config_bytes_used > 0
            else identity.max_config_size
        )
        return self.read_flash(arch.config_base, length, progress=progress)

    def write_config(
        self,
        blob: bytes,
        *,
        verify: bool = True,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Erase the config region and write ``blob`` into it.

        This is the destructive operation. Take a backup with
        ``harmonyforge backup`` first -- there is no undo on the remote.
        """
        identity = self._require_identity()
        arch = self._require_arch()

        if arch.config_base == devicedb.REGION_USER_CONFIG:
            raise UnsupportedRemoteError(
                f"{identity.name} stores its config in a region table, which "
                "harmonyforge cannot write yet (see docs/roadmap.md)."
            )

        capacity = identity.flash.size_bytes - (arch.config_base - arch.flash_base)
        if len(blob) > capacity:
            raise ProtocolError(
                f"config is {len(blob)} bytes but only {capacity} bytes of "
                f"flash are available on this remote"
            )

        self.erase_flash(arch.config_base, len(blob), progress=progress)
        self.write_flash(arch.config_base, blob, progress=progress)
        if verify:
            self.verify_flash(arch.config_base, blob, progress=progress)
        self.invalidate_config()

    # -- IR learning ------------------------------------------------------

    def learn_ir(self, *, start_timeout_ms: int | None = None) -> IRSignal:
        """Capture one IR burst from the remote's learning eye.

        Point the source remote at the Harmony's IR learning window and press
        a button. Returns the captured signal; raises
        :class:`~harmonyforge.errors.IRError` if nothing arrives.
        """
        from ..errors import IRError

        start_timeout = start_timeout_ms or p.IR_LEARN_START_TIMEOUT
        self.transport.write(p.start_ircap(self.report_len))
        try:
            frequency, durations = self._learn_ir_loop(start_timeout)
        finally:
            try:
                self.transport.write(p.stop_ircap(self.report_len))
                # Drain whatever is still queued.
                for _ in range(64):
                    response = p.parse(
                        self.transport.read(p.IR_LEARN_DONE_TIMEOUT)
                    )
                    if response.command == p.RESPONSE_DONE:
                        break
            except Exception as exc:
                log.debug("while stopping IR capture: %s", exc)

        if not durations:
            raise IRError(
                "No IR signal captured. Hold the source remote 2-5 cm from the "
                "Harmony's learning eye (the dark window on the front edge) "
                "and press the button firmly."
            )
        return IRSignal(frequency=frequency or 38000, durations=tuple(durations))

    def _learn_ir_loop(self, start_timeout: int) -> tuple[int, list[int]]:
        from ..errors import IRError

        frequency = 0
        durations: list[int] = []
        word_index = 0
        t_on = 0
        t_off = 0
        t_total = 0
        expected_seq = 0

        while t_off < p.IR_LEARN_DONE_TIMEOUT * 1000:
            timeout = p.IR_LEARN_DONE_TIMEOUT if word_index else start_timeout
            try:
                response = p.parse(self.transport.read(timeout))
            except TransportTimeout:
                break

            if response.command == p.RESPONSE_DONE:
                break
            if response.command != p.RESPONSE_IRCAP_DATA:
                raise ProtocolError(
                    f"unexpected response 0x{response.command:02X} during IR "
                    "capture"
                )

            expected_seq = p.check_sequence(response.raw[1], expected_seq)
            expected_seq = (expected_seq + 0x10) & 0xFF

            raw = response.raw
            payload_len = raw[self.report_len - 1]
            if payload_len & 1:
                raise ProtocolError(
                    f"IR capture packet has odd payload length {payload_len}"
                )

            for offset in range(2, payload_len, 2):
                value = (raw[offset] << 8) | raw[offset + 1]

                if word_index > 2:
                    if word_index & 1:
                        # Odd words carry on+off elapsed time.
                        t_off = value - t_on if t_on else t_off + value
                    else:
                        # Even words carry on time; a nonzero one closes a pair.
                        t_on = value
                        if t_on:
                            durations.append(t_off)
                            durations.append(t_on)
                            t_total += t_off + t_on
                elif word_index == 1:
                    t_on = value
                elif word_index == 2 and t_on:
                    # Carrier cycle count over the first burst gives frequency.
                    frequency = value * 1_000_000 // t_on
                    durations.append(t_on)

                word_index += 1

            if (
                t_total > p.MAX_IR_SIGNAL_DURATION * 1000
                or len(durations) > p.MAX_IR_SIGNAL_LENGTH
            ):
                raise IRError(
                    "IR signal too long -- release the button sooner, or the "
                    "learning eye is picking up ambient interference "
                    "(fluorescent or LED lighting is a common cause)."
                )

        if durations and t_off:
            durations.append(t_off)
        return frequency, durations
