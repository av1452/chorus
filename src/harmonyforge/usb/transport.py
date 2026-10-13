"""USB transport backends for HID-based Harmony remotes.

Harmony remotes expose a HID interface, but the reports they exchange are not
really HID-shaped: each report is a fixed-size blob whose length is the
interrupt endpoint's ``wMaxPacketSize`` (8 bytes on the old National
Semiconductor remotes, 64 on everything newer). Rather than go through a HID
report-descriptor parser we talk to the interrupt endpoints directly.

Three backends are provided:

:class:`PyUsbTransport`
    libusb via pyusb. The default, and the only one that works on macOS
    without extra privileges for these devices.
:class:`HidApiTransport`
    hidapi, for platforms where claiming the interface is awkward.
:class:`FakeTransport`
    A scripted in-memory remote used by the test suite and by
    ``harmonyforge --dry-run``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..errors import (
    RemoteNotFoundError,
    TransportError,
    TransportTimeout,
    UsbBackendMissing,
)

log = logging.getLogger(__name__)

#: Shown when pyusb is installed but libusb itself cannot be loaded.
LIBUSB_MISSING = (
    "pyusb could not find libusb, so harmonyforge cannot talk to USB devices.\n"
    "  Windows: install the hidapi fallback with `pip install hidapi`, or install\n"
    "           a libusb driver for the remote with Zadig (https://zadig.akeo.ie).\n"
    "  macOS:   brew install libusb\n"
    "  Linux:   sudo apt install libusb-1.0-0   (or your distro's equivalent)"
)


def _no_backend_error(usb_core) -> type[Exception]:
    # Older pyusb releases lack NoBackendError; match nothing in that case.
    return getattr(usb_core, "NoBackendError", ())

#: Logitech's vendor ID.
LOGITECH_VID = 0x046D
#: Harmony remotes occupy this product ID range.
LOGITECH_MIN_PID = 0xC110
LOGITECH_MAX_PID = 0xC14F
#: The older USBN960x-based remotes appear under National Semiconductor's ID
#: when running their bootloader.
NATIONAL_VID = 0x0400
NATIONAL_PID = 0xC359
#: The usbnet family (890, 900, 1100) presents an Ethernet interface instead.
USBNET_PID = 0xC11F


def is_harmony(vid: int, pid: int) -> bool:
    """True if ``(vid, pid)`` looks like a Harmony remote."""
    if vid == LOGITECH_VID and LOGITECH_MIN_PID <= pid <= LOGITECH_MAX_PID:
        return True
    return vid == NATIONAL_VID and pid == NATIONAL_PID


@dataclass
class DeviceInfo:
    """What the USB descriptors tell us before we speak the protocol."""

    vendor_id: int
    product_id: int
    manufacturer: str = ""
    product: str = ""
    version: int = 0
    #: Interrupt IN report length, in bytes.
    in_report_len: int = 64
    #: Interrupt OUT report length, in bytes.
    out_report_len: int = 64

    @property
    def is_usbnet(self) -> bool:
        return self.vendor_id == LOGITECH_VID and self.product_id == USBNET_PID

    def __str__(self) -> str:
        label = " ".join(x for x in (self.manufacturer, self.product) if x)
        return f"{label or 'Harmony remote'} [{self.vendor_id:04x}:{self.product_id:04x}]"


class Transport(ABC):
    """Exchanges fixed-size reports with a remote."""

    info: DeviceInfo

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Send one report. ``data`` must already be padded to report size."""

    @abstractmethod
    def read(self, timeout_ms: int = 1000) -> bytes:
        """Read one report, raising :class:`TransportTimeout` on timeout."""

    def close(self) -> None:  # noqa: B027 - optional hook, not abstract
        """Release the device. Safe to call more than once.

        A no-op by default: a transport with nothing to release need not
        override this.
        """

    @property
    def report_len(self) -> int:
        return self.info.out_report_len

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# pyusb / libusb
# ---------------------------------------------------------------------------


class PyUsbTransport(Transport):
    """libusb-backed transport, via pyusb."""

    def __init__(self, device=None, *, detach_kernel_driver: bool = True) -> None:
        try:
            import usb.core
            import usb.util
        except ImportError as exc:  # pragma: no cover
            raise TransportError(
                "pyusb is not installed. Install it with: pip install pyusb"
            ) from exc

        self._usb_util = usb.util
        self._dev = device if device is not None else self._find(usb.core)
        self._claimed = False
        self._ep_in = None
        self._ep_out = None
        self._configure(usb.util, detach_kernel_driver)

    @staticmethod
    def _find(usb_core):
        try:
            dev = usb_core.find(
                custom_match=lambda d: is_harmony(d.idVendor, d.idProduct)
            )
        except _no_backend_error(usb_core) as exc:
            raise UsbBackendMissing(LIBUSB_MISSING) from exc
        if dev is None:
            raise RemoteNotFoundError(
                "No Harmony remote found on USB. Plug the remote in with its "
                "USB cable, make sure it powers on, and try again."
            )
        return dev

    @staticmethod
    def enumerate() -> list[DeviceInfo]:
        """List every attached Harmony remote without claiming any of them."""
        try:
            import usb.core
            import usb.util
        except ImportError as exc:  # pragma: no cover
            raise TransportError("pyusb is not installed") from exc

        try:
            devices = list(usb.core.find(
                find_all=True, custom_match=lambda d: is_harmony(d.idVendor, d.idProduct)
            ))
        except _no_backend_error(usb.core) as exc:
            raise UsbBackendMissing(LIBUSB_MISSING) from exc

        found = []
        for dev in devices:
            info = DeviceInfo(dev.idVendor, dev.idProduct, version=dev.bcdDevice or 0)
            for attr, target in (("manufacturer", "manufacturer"), ("product", "product")):
                try:
                    setattr(info, target, getattr(dev, attr) or "")
                except Exception:
                    # String descriptors need the device opened, which may
                    # require privileges we do not have while enumerating.
                    pass
            found.append(info)
        return found

    def _configure(self, usb_util, detach: bool) -> None:
        dev = self._dev
        try:
            dev.set_configuration()
        except Exception as exc:
            log.debug("set_configuration failed (often harmless): %s", exc)

        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]

        if detach:
            self._maybe_detach(intf)

        try:
            usb_util.claim_interface(dev, intf.bInterfaceNumber)
            self._claimed = True
            self._intf = intf.bInterfaceNumber
        except Exception as exc:
            raise TransportError(
                f"Could not claim the remote's USB interface: {exc}\n"
                "Another program may be holding it (close MyHarmony or "
                "Harmony software if installed). On Linux you may need the "
                "udev rule from packaging/ or to run as root."
            ) from exc

        in_len = out_len = 64
        for ep in intf:
            is_interrupt = (
                usb_util.endpoint_type(ep.bmAttributes)
                == usb_util.ENDPOINT_TYPE_INTR
            )
            if not is_interrupt:
                continue
            direction = usb_util.endpoint_direction(ep.bEndpointAddress)
            if direction == usb_util.ENDPOINT_IN and self._ep_in is None:
                self._ep_in = ep
                in_len = ep.wMaxPacketSize
            elif direction == usb_util.ENDPOINT_OUT and self._ep_out is None:
                self._ep_out = ep
                out_len = ep.wMaxPacketSize

        if self._ep_in is None or self._ep_out is None:
            raise TransportError(
                "The remote does not expose the interrupt IN/OUT endpoint pair "
                "this protocol needs. If this is a Harmony Hub, Elite, "
                "Companion or Ultimate, use the hub commands instead."
            )

        self.info = DeviceInfo(
            vendor_id=dev.idVendor,
            product_id=dev.idProduct,
            version=dev.bcdDevice or 0,
            in_report_len=in_len,
            out_report_len=out_len,
        )
        for attr in ("manufacturer", "product"):
            try:
                setattr(self.info, attr, getattr(dev, attr) or "")
            except Exception:
                pass

    def _maybe_detach(self, intf) -> None:
        dev = self._dev
        try:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                dev.detach_kernel_driver(intf.bInterfaceNumber)
        except NotImplementedError:
            pass  # macOS and Windows
        except Exception as exc:
            log.debug("detach_kernel_driver failed: %s", exc)

    def write(self, data: bytes) -> None:
        try:
            self._ep_out.write(data, timeout=500)
        except Exception as exc:
            raise TransportError(f"USB write failed: {exc}") from exc

    def read(self, timeout_ms: int = 1000) -> bytes:
        try:
            return bytes(self._ep_in.read(self.info.in_report_len, timeout=timeout_ms))
        except Exception as exc:
            if "timeout" in str(exc).lower() or getattr(exc, "errno", None) == 60:
                raise TransportTimeout(
                    f"Remote did not respond within {timeout_ms} ms"
                ) from exc
            raise TransportError(f"USB read failed: {exc}") from exc

    def close(self) -> None:
        if self._claimed:
            try:
                self._usb_util.release_interface(self._dev, self._intf)
            except Exception as exc:  # pragma: no cover
                log.debug("release_interface failed: %s", exc)
            self._claimed = False
        try:
            self._usb_util.dispose_resources(self._dev)
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# hidapi
# ---------------------------------------------------------------------------


class HidApiTransport(Transport):
    """hidapi-backed transport, as an alternative to libusb."""

    def __init__(self, vendor_id: int | None = None, product_id: int | None = None):
        try:
            import hid
        except ImportError as exc:  # pragma: no cover
            raise TransportError(
                "hidapi is not installed. Install it with: pip install hidapi"
            ) from exc

        target = None
        for entry in hid.enumerate():
            if not is_harmony(entry["vendor_id"], entry["product_id"]):
                continue
            if vendor_id and entry["vendor_id"] != vendor_id:
                continue
            if product_id and entry["product_id"] != product_id:
                continue
            target = entry
            break

        if target is None:
            raise RemoteNotFoundError("No Harmony remote found via hidapi")

        self._dev = hid.device()
        self._dev.open_path(target["path"])
        self._dev.set_nonblocking(0)
        self.info = DeviceInfo(
            vendor_id=target["vendor_id"],
            product_id=target["product_id"],
            manufacturer=target.get("manufacturer_string") or "",
            product=target.get("product_string") or "",
        )

    @staticmethod
    def enumerate() -> list[DeviceInfo]:
        """List every attached Harmony remote that hidapi can see."""
        try:
            import hid
        except ImportError as exc:
            raise TransportError("hidapi is not installed") from exc

        found, seen = [], set()
        for entry in hid.enumerate():
            vid, pid = entry["vendor_id"], entry["product_id"]
            # hidapi lists one entry per HID collection; report each device once.
            if not is_harmony(vid, pid) or (vid, pid) in seen:
                continue
            seen.add((vid, pid))
            found.append(DeviceInfo(
                vid, pid,
                manufacturer=entry.get("manufacturer_string") or "",
                product=entry.get("product_string") or "",
                version=entry.get("release_number") or 0,
            ))
        return found

    def write(self, data: bytes) -> None:
        # hidapi prepends a report ID byte; these devices use report ID 0.
        try:
            self._dev.write(b"\x00" + data)
        except Exception as exc:
            raise TransportError(f"HID write failed: {exc}") from exc

    def read(self, timeout_ms: int = 1000) -> bytes:
        try:
            data = self._dev.read(self.info.in_report_len, timeout_ms)
        except Exception as exc:
            raise TransportError(f"HID read failed: {exc}") from exc
        if not data:
            raise TransportTimeout(f"Remote did not respond within {timeout_ms} ms")
        return bytes(data)

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Fake / dry-run
# ---------------------------------------------------------------------------


@dataclass
class FakeTransport(Transport):
    """An in-memory remote, for tests and ``--dry-run``.

    Emulates enough of the protocol to exercise identity, flash reads, flash
    writes and erases: it keeps a sparse byte map of "flash" and answers read
    requests out of it. ``written`` records every report the caller sent, so
    tests can assert on exact wire bytes.
    """

    identity: bytes = b""
    flash: dict[int, int] = field(default_factory=dict)
    info: DeviceInfo = field(
        default_factory=lambda: DeviceInfo(
            LOGITECH_VID, 0xC122, "Logitech", "Harmony 650 (simulated)"
        )
    )
    written: list[bytes] = field(default_factory=list)
    _pending: list[bytes] = field(default_factory=list, repr=False)
    _write_addr: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if not self.identity:
            # len nibble 7: fw 3.2, hw 1.0, flash 0x49/0x01, arch 7, skin 72
            self.identity = bytes([0x27, 0x32, 0x10, 0x49, 0x01, 0x70, 72, 0x07])

    def _read_byte(self, addr: int) -> int:
        return self.flash.get(addr, 0xFF)

    def seed_config(self, addr: int, data: bytes) -> None:
        """Place ``data`` at ``addr`` in the simulated flash."""
        for i, b in enumerate(data):
            self.flash[addr + i] = b

    def write(self, data: bytes) -> None:
        from . import protocol as p

        self.written.append(bytes(data))
        cmd = data[0] & p.COMMAND_MASK

        if cmd == p.COMMAND_GET_VERSION:
            self._pending.append(self._pad(self.identity))

        elif cmd == p.COMMAND_READ_FLASH:
            addr = (data[1] << 16) | (data[2] << 8) | data[3]
            length = (data[4] << 8) | data[5]
            seq = 1
            sent = 0
            while sent < length:
                block = min(62, length - sent)
                # Shrink to a representable size.
                code = next(
                    c
                    for c in range(10, 1, -1)
                    if p.READ_LEN_MAP[c] and p.READ_LEN_MAP[c] <= block
                )
                n = p.READ_LEN_MAP[code]
                payload = bytes(self._read_byte(addr + sent + i) for i in range(n))
                self._pending.append(
                    self._pad(bytes([p.RESPONSE_READ_FLASH_DATA | code, seq]) + payload)
                )
                seq = (seq + 0x11) & 0xFF
                sent += n
            self._pending.append(self._pad(bytes([p.RESPONSE_DONE, cmd])))

        elif cmd == p.COMMAND_WRITE_FLASH:
            self._write_addr = (data[1] << 16) | (data[2] << 8) | data[3]

        elif cmd == p.COMMAND_WRITE_FLASH_DATA:
            code = data[0] & p.LENGTH_MASK
            # Mirror the encoder: code -> block length.
            table = p.WRITE_LEN_MAP
            n = table[table[0] - code + 1]
            for i in range(n):
                self.flash[self._write_addr + i] = data[1 + i]
            self._write_addr += n

        elif cmd == p.COMMAND_ERASE_FLASH & p.COMMAND_MASK:
            addr = (data[1] << 16) | (data[2] << 8) | data[3]
            for key in [k for k in self.flash if k >= addr]:
                del self.flash[key]
            self._pending.append(self._pad(bytes([p.RESPONSE_DONE, cmd])))

        elif cmd == p.COMMAND_DONE & p.COMMAND_MASK:
            self._pending.append(self._pad(bytes([p.RESPONSE_DONE, data[1]])))

        elif cmd == p.COMMAND_READ_MISC:
            self._pending.append(
                self._pad(bytes([p.RESPONSE_READ_MISC_DATA | 1, 0x00]))
            )

        elif cmd == p.COMMAND_WRITE_MISC:
            self._pending.append(self._pad(bytes([p.RESPONSE_DONE, cmd])))

    def _pad(self, data: bytes) -> bytes:
        return data + bytes(max(0, self.info.in_report_len - len(data)))

    def read(self, timeout_ms: int = 1000) -> bytes:
        if not self._pending:
            raise TransportTimeout("FakeTransport has nothing queued")
        return self._pending.pop(0)


def open_remote(backend: str = "auto") -> Transport:
    """Open the first attached remote.

    ``backend`` may be ``"auto"``, ``"pyusb"``, ``"hidapi"`` or ``"fake"``.
    ``"auto"`` prefers libusb and falls back to hidapi.
    """
    if backend == "fake":
        return FakeTransport()
    if backend == "pyusb":
        return PyUsbTransport()
    if backend == "hidapi":
        return HidApiTransport()
    if backend != "auto":
        raise ValueError(f"unknown backend {backend!r}")

    try:
        return PyUsbTransport()
    except RemoteNotFoundError:
        raise
    except Exception as exc:
        log.debug("pyusb backend unavailable (%s); trying hidapi", exc)
        if not _hidapi_installed():
            # Report the libusb problem, not the missing optional fallback.
            if isinstance(exc, UsbBackendMissing):
                raise
            raise UsbBackendMissing(LIBUSB_MISSING) from exc
        return HidApiTransport()


def enumerate_remotes() -> list[DeviceInfo]:
    """List attached remotes via libusb, falling back to hidapi when libusb is missing."""
    try:
        return PyUsbTransport.enumerate()
    except UsbBackendMissing:
        if not _hidapi_installed():
            raise
        log.debug("libusb unavailable; enumerating with hidapi")
        return HidApiTransport.enumerate()


def _hidapi_installed() -> bool:
    try:
        import hid  # noqa: F401
    except ImportError:
        return False
    return True
