"""Behaviour when libusb (the pyusb backend) is missing."""

import sys
import types

import pytest
import usb.core

from harmonyforge.cli import main
from harmonyforge.errors import UsbBackendMissing
from harmonyforge.usb import transport


@pytest.fixture
def no_libusb(monkeypatch):
    def find(*args, **kwargs):
        raise usb.core.NoBackendError("No backend available")

    monkeypatch.setattr(usb.core, "find", find)


@pytest.fixture
def no_hidapi(monkeypatch):
    # A None entry makes `import hid` raise ImportError.
    monkeypatch.setitem(sys.modules, "hid", None)


@pytest.fixture
def fake_hidapi(monkeypatch):
    entries = [
        # Two HID collections of the same remote, plus an unrelated device.
        {"vendor_id": 0x046D, "product_id": 0xC12B, "path": b"a",
         "manufacturer_string": "Logitech", "product_string": "Harmony", "release_number": 0x0100},
        {"vendor_id": 0x046D, "product_id": 0xC12B, "path": b"b",
         "manufacturer_string": "Logitech", "product_string": "Harmony", "release_number": 0x0100},
        {"vendor_id": 0x046D, "product_id": 0xC52B, "path": b"c"},
    ]
    module = types.SimpleNamespace(enumerate=lambda: entries)
    monkeypatch.setitem(sys.modules, "hid", module)


def test_detect_explains_missing_libusb(no_libusb, no_hidapi, capsys):
    assert main(["detect"]) == 1
    captured = capsys.readouterr()
    message = captured.err + captured.out
    assert "pyusb could not find libusb" in message
    assert "pip install hidapi" in message
    assert "Traceback" not in message


def test_detect_falls_back_to_hidapi(no_libusb, fake_hidapi, capsys):
    assert main(["detect"]) == 0
    out = capsys.readouterr().out
    assert "1 remote(s) attached" in out
    assert "046d:c12b" in out


def test_open_remote_reports_libusb_not_hidapi(no_libusb, no_hidapi):
    with pytest.raises(UsbBackendMissing, match="libusb"):
        transport.open_remote()


def test_enumerate_without_backend_raises_clear_error(no_libusb):
    with pytest.raises(UsbBackendMissing):
        transport.PyUsbTransport.enumerate()
