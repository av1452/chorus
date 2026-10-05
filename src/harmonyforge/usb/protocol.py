"""Wire protocol for HID-based Logitech Harmony remotes.

Every command is a single HID report. The first byte packs a command in the
high nibble and a length code in the low nibble::

    7 6 5 4   3 2 1 0
    command   length code

The length code is *not* a byte count. For reads the remote echoes a code that
maps to a payload size via :data:`READ_LEN_MAP`; for writes we pick a code from
:data:`WRITE_LEN_MAP` that covers the bytes still outstanding. The two maps
differ between "protocol 0" remotes (the Harmony 745, and any remote that has
fallen back to safe mode) and everything else.

Multi-byte flash addresses are 24-bit big-endian; lengths are 16-bit
big-endian.

Constants and framing follow libconcord (GPLv3), by Kevin Timmerman and
Phil Dibowitz. See NOTICE.md.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Nibble masks
# --------------------------------------------------------------------------

COMMAND_MASK = 0xF0
LENGTH_MASK = 0x0F

# --------------------------------------------------------------------------
# Commands (host -> remote). Low nibble is the length code, 0 unless fixed.
# --------------------------------------------------------------------------

COMMAND_INVALID = 0x00
COMMAND_GET_VERSION = 0x10
COMMAND_WRITE_FLASH = 0x30
COMMAND_WRITE_FLASH_DATA = 0x40
COMMAND_READ_FLASH = 0x50
COMMAND_START_IRCAP = 0x70
COMMAND_STOP_IRCAP = 0x80
COMMAND_WRITE_MISC = 0xA0
COMMAND_READ_MISC = 0xB0
COMMAND_ERASE_FLASH = 0xD3  # length code is fixed at 3
COMMAND_RESET = 0xE1  # length code is fixed at 1
COMMAND_DONE = 0xF1  # length code is fixed at 1

# Second byte of a flash command: which memory are we addressing?
PROM_TYPE_MCU_FLASH = 0x01
PROM_TYPE_MCU_EEPROM = 0x02
PROM_TYPE_MCU_ID = 0x03
PROM_TYPE_EXT_FLASH = 0x04

# Second byte of COMMAND_{READ,WRITE}_MISC.
MISC_EEPROM = 0x00
MISC_STATE = 0x01
MISC_INVALIDATE_FLASH = 0x02
MISC_QUEUE_ACTION = 0x03
MISC_PROGRAM = 0x04
MISC_INTERRUPT = 0x05
MISC_RAM = 0x06
MISC_REGISTER = 0x07
MISC_CLOCK_RECALCULATE = 0x08
MISC_QUEUE_EVENT = 0x09
MISC_RESTART_CONFIG = 0x0A

# Second byte of COMMAND_RESET.
RESET_USB = 0x01
RESET_DEVICE = 0x02
RESET_DEVICE_DISCONNECT = 0x03
RESET_TEST_FINISH = 0x04

# --------------------------------------------------------------------------
# Responses (remote -> host)
# --------------------------------------------------------------------------

RESPONSE_VERSION_DATA = 0x20
RESPONSE_READ_FLASH_DATA = 0x60
RESPONSE_IRCAP_DATA = 0x90
RESPONSE_READ_MISC_DATA = 0xC0
RESPONSE_DONE = 0xF0

# --------------------------------------------------------------------------
# Length-code tables
# --------------------------------------------------------------------------

#: Length code -> payload byte count, for RESPONSE_READ_FLASH_DATA on
#: protocol 0 remotes (745 / safe mode).
READ_LEN_MAP_PROTO0 = (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14)

#: Length code -> payload byte count for every other protocol. Codes 11-15
#: are unused and map to 0, which callers must treat as "no data".
READ_LEN_MAP = (0, 0, 1, 2, 3, 4, 5, 6, 14, 30, 62, 0, 0, 0, 0, 0)

#: Candidate write block sizes, largest first. Element 0 is the length code
#: that corresponds to element 1; the code decreases as we walk down the list.
WRITE_LEN_MAP_PROTO0 = (0x07, 7, 6, 5, 4, 3, 2, 1)
WRITE_LEN_MAP = (0x0A, 63, 31, 15, 7, 6, 5, 4, 3, 2, 1)

#: Largest number of bytes one read/write *setup* command may request.
MAX_READ_CHUNK_PROTO0 = 700
MAX_READ_CHUNK = 1022
MAX_WRITE_CHUNK_PROTO0 = 749
MAX_WRITE_CHUNK = 3150

#: Serial number region: three 16-byte GUIDs.
SERIAL_SIZE = 48

#: IR learning limits (milliseconds, except LENGTH which counts durations).
IR_LEARN_START_TIMEOUT = 5000
IR_LEARN_DONE_TIMEOUT = 500
MAX_IR_SIGNAL_DURATION = 5000
MAX_IR_SIGNAL_LENGTH = 1000


def read_len_map(protocol: int) -> tuple[int, ...]:
    """Return the response length table for ``protocol``."""
    return READ_LEN_MAP if protocol else READ_LEN_MAP_PROTO0


def write_len_map(protocol: int) -> tuple[int, ...]:
    """Return the write block-size table for ``protocol``."""
    return WRITE_LEN_MAP if protocol else WRITE_LEN_MAP_PROTO0


def max_read_chunk(protocol: int) -> int:
    return MAX_READ_CHUNK if protocol else MAX_READ_CHUNK_PROTO0


def max_write_chunk(protocol: int) -> int:
    return MAX_WRITE_CHUNK if protocol else MAX_WRITE_CHUNK_PROTO0


def pick_write_block(outstanding: int, protocol: int) -> tuple[int, int]:
    """Choose a write block size for ``outstanding`` remaining bytes.

    Returns ``(length_code, block_len)``. Walks the table from the largest
    block down until one fits, decrementing the length code in step -- the
    same traversal libconcord's ``WriteFlash`` performs.
    """
    table = write_len_map(protocol)
    code = table[0]
    i = 1
    while outstanding < table[i]:
        i += 1
        code -= 1
    return code, table[i]


# --------------------------------------------------------------------------
# Packet builders
# --------------------------------------------------------------------------


def _addr24(addr: int) -> tuple[int, int, int]:
    return (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF


def build(report_len: int, *payload: int) -> bytes:
    """Zero-pad ``payload`` out to a full ``report_len``-byte HID report."""
    if len(payload) > report_len:
        raise ValueError(
            f"payload of {len(payload)} bytes exceeds {report_len}-byte report"
        )
    return bytes(payload) + bytes(report_len - len(payload))


def get_version(report_len: int = 64) -> bytes:
    return build(report_len, COMMAND_GET_VERSION)


def read_flash(addr: int, length: int, report_len: int = 64) -> bytes:
    """Setup packet asking the remote to stream ``length`` bytes from ``addr``."""
    hi, mid, lo = _addr24(addr)
    return build(
        report_len,
        COMMAND_READ_FLASH | 0x05,
        hi,
        mid,
        lo,
        (length >> 8) & 0xFF,
        length & 0xFF,
    )


def write_flash_setup(addr: int, length: int, report_len: int = 64) -> bytes:
    """Setup packet announcing ``length`` bytes about to be written at ``addr``."""
    hi, mid, lo = _addr24(addr)
    return build(
        report_len,
        COMMAND_WRITE_FLASH | 0x05,
        hi,
        mid,
        lo,
        (length >> 8) & 0xFF,
        length & 0xFF,
    )


def write_flash_data(block: bytes, length_code: int, report_len: int = 64) -> bytes:
    return build(report_len, COMMAND_WRITE_FLASH_DATA | length_code, *block)


def done(command: int, report_len: int = 64) -> bytes:
    """Terminate a multi-packet transfer begun with ``command``."""
    return build(report_len, COMMAND_DONE, command)


def erase_flash(sector_addr: int, report_len: int = 64) -> bytes:
    hi, mid, lo = _addr24(sector_addr)
    return build(report_len, COMMAND_ERASE_FLASH, hi, mid, lo)


def read_misc(kind: int, addr: int, report_len: int = 64) -> bytes:
    return build(report_len, COMMAND_READ_MISC | 0x02, kind, addr & 0xFF)


def write_misc(kind: int, addr: int, value: int, report_len: int = 64) -> bytes:
    return build(
        report_len, COMMAND_WRITE_MISC | 0x03, kind, addr & 0xFF, value & 0xFF
    )


def invalidate_flash(report_len: int = 64) -> bytes:
    return build(report_len, COMMAND_WRITE_MISC | 0x01, MISC_INVALIDATE_FLASH)


def reset(kind: int, report_len: int = 64) -> bytes:
    return build(report_len, COMMAND_RESET, kind)


def start_ircap(report_len: int = 64) -> bytes:
    return build(report_len, COMMAND_START_IRCAP)


def stop_ircap(report_len: int = 64) -> bytes:
    return build(report_len, COMMAND_STOP_IRCAP)


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Response:
    """A decoded HID report from the remote."""

    command: int
    length_code: int
    raw: bytes

    @property
    def is_done(self) -> bool:
        return self.command == RESPONSE_DONE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Response(command=0x{self.command:02X}, "
            f"length_code={self.length_code}, raw={self.raw[:8].hex()}...)"
        )


def parse(data: bytes) -> Response:
    if not data:
        raise ValueError("empty response")
    return Response(data[0] & COMMAND_MASK, data[0] & LENGTH_MASK, bytes(data))


def check_sequence(received: int, expected: int) -> int:
    """Validate a stream sequence byte, returning the next expected value.

    Harmony 880 firmware occasionally reports 0x1F where 0x10 is expected.
    libconcord tolerates that specific glitch and resynchronises, so we do
    too. Raises :class:`ValueError` on any other mismatch.
    """
    if received == expected:
        return expected
    if received == 0x1F and expected == 0x10:
        return expected + 0x0F
    raise ValueError(
        f"out-of-order packet: expected sequence 0x{expected:02X}, "
        f"got 0x{received:02X}"
    )
