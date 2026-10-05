"""Hardware tables for Harmony remotes: models, architectures, flash chips.

A remote reports a numeric *skin* (model index) and *architecture* in its
identity response. The architecture determines where the config, firmware
and serial number live in the address space; the flash manufacturer/device
ID pair determines total size and the sector map used for erases.

Transcribed from libconcord's remote_info.h (GPLv3) by Kevin Timmerman and
Phil Dibowitz. Generated -- see tools/gen_devicedb.py. See NOTICE.md.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Serial number lives in the microcontroller's EEPROM.
SERIAL_IN_EEPROM = "eeprom"
#: Serial number lives in external flash.
SERIAL_IN_FLASH = "flash"

#: Sentinel ``config_base`` meaning "look the region up in the on-remote
#: region table" rather than using a fixed address. Z-Wave and usbnet
#: remotes (890, 900, 1100) do this.
REGION_USER_CONFIG = -1


@dataclass(frozen=True)
class Model:
    """A remote model, indexed by the skin ID the remote reports."""

    manufacturer: str
    name: str
    skin: str | None = None

    @property
    def known(self) -> bool:
        return self.manufacturer != "Unknown"


@dataclass(frozen=True)
class Flash:
    """An external flash chip, identified by (manufacturer, device) ID."""

    manufacturer_id: int
    device_id: int
    size_kb: int
    bits: int
    sectors: tuple[int, ...]
    name: str

    @property
    def size_bytes(self) -> int:
        return self.size_kb << 10


@dataclass(frozen=True)
class Architecture:
    """Address-space layout for a family of remotes."""

    index: int
    serial_location: str | int
    serial_address: int
    flash_base: int
    firmware_base: int
    config_base: int
    firmware_update_base: int
    firmware_4847_offset: int
    cookie: int
    cookie_size: int
    end_vector: int
    micro: str
    flash_size: int
    ram_size: int
    eeprom_size: int
    usb: str

    @property
    def supported(self) -> bool:
        """False for placeholder entries we have no layout data for."""
        return self.cookie != 0


# ---------------------------------------------------------------------------
# Flash sector maps. Each entry is the END address of a sector, so sector N
# spans [sectors[N-1], sectors[N]).
# ---------------------------------------------------------------------------

SECTORS1 = (
    0x004000, 0x006000, 0x008000, 0x010000, 0x020000, 0x030000, 0x040000,
    0x050000, 0x060000, 0x070000, 0x080000, 0x090000, 0x0A0000, 0x0B0000,
    0x0C0000, 0x0D0000, 0x0E0000, 0x0F0000, 0x100000, 0x000000,
)

SECTORS2 = (
    0x004000, 0x006000, 0x008000, 0x010000, 0x020000, 0x030000, 0x040000,
    0x050000, 0x060000, 0x070000, 0x080000, 0x090000, 0x0A0000, 0x0B0000,
    0x0C0000, 0x0D0000, 0x0E0000, 0x0F0000, 0x100000, 0x110000, 0x120000,
    0x130000, 0x140000, 0x150000, 0x160000, 0x170000, 0x180000, 0x190000,
    0x1A0000, 0x1B0000, 0x1C0000, 0x1D0000, 0x1E0000, 0x1F0000, 0x200000,
    0x000000,
)

SECTORS3 = (
    0x010000, 0x020000, 0x030000, 0x040000, 0x000000,
)

SECTORS4 = (
    0x010000, 0x020000, 0x030000, 0x040000, 0x050000, 0x060000, 0x070000,
    0x080000, 0x000000,
)

SECTORS5 = (
    0x010000, 0x020000, 0x030000, 0x040000, 0x050000, 0x060000, 0x070000,
    0x080000, 0x090000, 0x0A0000, 0x0B0000, 0x0C0000, 0x0D0000, 0x0E0000,
    0x0F0000, 0x100000, 0x110000, 0x120000, 0x130000, 0x140000, 0x150000,
    0x160000, 0x170000, 0x180000, 0x190000, 0x1A0000, 0x1B0000, 0x1C0000,
    0x1D0000, 0x1E0000, 0x1F0000, 0x200000, 0x210000, 0x220000, 0x230000,
    0x240000, 0x250000, 0x260000, 0x270000, 0x280000, 0x290000, 0x2A0000,
    0x2B0000, 0x2C0000, 0x2D0000, 0x2E0000, 0x2F0000, 0x300000, 0x310000,
    0x320000, 0x330000, 0x340000, 0x350000, 0x360000, 0x370000, 0x380000,
    0x390000, 0x3A0000, 0x3B0000, 0x3C0000, 0x1D0000, 0x3E0000, 0x3F0000,
    0x400000, 0x000000,
)

SECTORS6 = (
    0x000000, 0x002000, 0x004000, 0x006000, 0x008000, 0x00A000, 0x00C000,
    0x00E000, 0x010000, 0x020000, 0x030000, 0x040000, 0x050000, 0x060000,
    0x070000, 0x080000, 0x090000, 0x0A0000, 0x0B0000, 0x0C0000, 0x0D0000,
    0x0E0000, 0x0F0000, 0x100000, 0x110000, 0x120000, 0x130000, 0x140000,
    0x150000, 0x160000, 0x170000, 0x180000, 0x190000, 0x1A0000, 0x1B0000,
    0x1C0000, 0x1D0000, 0x1E0000, 0x1F0000, 0x200000, 0x210000, 0x220000,
    0x230000, 0x240000, 0x250000, 0x260000, 0x270000, 0x280000, 0x290000,
    0x2A0000, 0x2B0000, 0x2C0000, 0x2D0000, 0x2E0000, 0x2F0000, 0x300000,
    0x310000, 0x320000, 0x330000, 0x340000, 0x350000, 0x360000, 0x370000,
    0x380000, 0x390000, 0x3A0000, 0x3B0000, 0x3C0000, 0x3D0000, 0x3E0000,
    0x3F0000, 0x000000,
)


#: Every known flash chip, keyed by ``(manufacturer_id, device_id)``.
FLASH_CHIPS: dict[tuple[int, int], Flash] = {
    (0x01, 0x37): Flash(
        0x01, 0x37, 1024, 8, SECTORS1, "AMD Am29LV008B"
    ),
    (0x01, 0x49): Flash(
        0x01, 0x49, 2048, 16, SECTORS2, "AMD Am29LV160BB"
    ),
    (0x01, 0x4C): Flash(
        0x01, 0x4C, 2048, 8, SECTORS2, "AMD Am29LV116DB"
    ),
    (0x15, 0x1C): Flash(
        0x15, 0x1C, 4096, 8, SECTORS5, "EON F16-100HIP"
    ),
    (0xFF, 0x11): Flash(
        0xFF, 0x11, 256, 1, SECTORS3, "25F020"
    ),
    (0xFF, 0x12): Flash(
        0xFF, 0x12, 512, 1, SECTORS4, "25F040"
    ),
    (0x1F, 0xC8): Flash(
        0x1F, 0xC8, 4096, 8, SECTORS6, "Atmel AT49BV322A"
    ),
}

#: Fallback used when a remote reports a flash ID we have no entry for.
UNKNOWN_FLASH = Flash(0, 0, 1024, 8, SECTORS1, "unknown flash")


MODELS: tuple[Model, ...] = (
    Model("Unknown", "0", None),  # 0
    Model("Unknown", "1", None),  # 1
    Model("Logitech", "Harmony 745", None),  # 2
    Model("Logitech", "Harmony 768", None),  # 3
    Model("Unknown", "4", None),  # 4
    Model("Unknown", "5", None),  # 5
    Model("Unknown", "6", None),  # 6
    Model("Logitech", "Harmony 748", None),  # 7
    Model("Unknown", "8", None),  # 8
    Model("Logitech", "Harmony 659", None),  # 9
    Model("Logitech", "Harmony 688", None),  # 10
    Model("Logitech", "Harmony 655", None),  # 11
    Model("Logitech", "Harmony 676", None),  # 12
    Model("Logitech", "Harmony 628", None),  # 13
    Model("Logitech", "Harmony 680", None),  # 14
    Model("Logitech", "Harmony 880", "Espresso"),  # 15
    Model("Logitech", "Harmony 675", None),  # 16
    Model("Logitech", "Harmony 885", "Espresso"),  # 17
    Model("Logitech", "Harmony 520", "Mocha Decaf"),  # 18
    Model("Logitech", "Harmony 890", "Cappuccino"),  # 19
    Model("Logitech", "Harmony 891", "Whisky"),  # 20
    Model("Logitech", "Harmony 892", "Sugar"),  # 21
    Model("Logitech", "Harmony 525", "Mocha Decaf"),  # 22
    Model("Logitech", "Harmony 895", "Cappuccino"),  # 23
    Model("Logitech", "Harmony 896", "Whisky"),  # 24
    Model("Logitech", "Harmony 897", "Sugar"),  # 25
    Model("Monster", "AVL-300", "Godzilla"),  # 26
    Model("Monster", "AVL-300", "Whisky"),  # 27
    Model("Monster", "AVL-300", "Sugar"),  # 28
    Model("Monster", "AVL-300", "Godzilla"),  # 29
    Model("Monster", "AVL-300", "Whisky"),  # 30
    Model("Monster", "AVL-300", "Sugar"),  # 31
    Model("Monster", "AVL-200", "Godzilla"),  # 32
    Model("Monster", "AVL-200", "Godzilla"),  # 33
    Model("Harman Kardon", "TC-30", None),  # 34
    Model("Harman Kardon", "TC-30", None),  # 35
    Model("Logitech", "Harmony XBOX360", "Mountain Dew"),  # 36
    Model("Monster", "AV-100", None),  # 37
    Model("Monster", "AV-100", None),  # 38
    Model("Logitech", "Harmony 880 Pro", "Espresso"),  # 39
    Model("Logitech", "Harmony 890 Pro", "Cappuccino"),  # 40
    Model("Logitech", "Harmony 550", "Mocha Grande"),  # 41
    Model("Harman Kardon", "TC-30", None),  # 42
    Model("Harman Kardon", "TC-30", None),  # 43
    Model("Logitech", "Harmony 720", "Corona"),  # 44
    Model("Logitech", "Harmony 785", "Corona"),  # 45
    Model("Logitech", "Harmony 522", "Mocha Decaf"),  # 46
    Model("Logicool", "Harmony 882", "Espresso"),  # 47
    Model("Logitech", "Harmony 555", "Mocha Grande"),  # 48
    Model("Logitech", "Harmony 1000", "Cognac"),  # 49
    Model("Logitech", "Harmony 670", None),  # 50
    Model("Logicool", "Harmony 552", "Mocha Grande"),  # 51
    Model("Logitech", "Harmony 1000i", "Cognac"),  # 52
    Model("Unknown", "Unknown", None),  # 53
    Model("Logitech", "Harmony One", None),  # 54
    Model("Unknown", "Unknown", None),  # 55
    Model("Unknown", "Unknown", None),  # 56
    Model("Unknown", "Unknown", None),  # 57
    Model("Unknown", "Unknown", None),  # 58
    Model("Unknown", "Unknown", None),  # 59
    Model("Unknown", "Unknown", None),  # 60
    Model("Logitech", "Harmony 900", None),  # 61
    Model("Unknown", "Unknown", None),  # 62
    Model("Logitech", "Harmony 1100", None),  # 63
    Model("Unknown", "Unknown", None),  # 64
    Model("Unknown", "Unknown", None),  # 65
    Model("Logitech", "Harmony 700", "Molson"),  # 66
    Model("Logitech", "Harmony 515", None),  # 67
    Model("Unknown", "Unknown", None),  # 68
    Model("Logitech", "Harmony 700i", None),  # 69
    Model("Unknown", "Unknown", None),  # 70
    Model("Logitech", "Harmony 600", None),  # 71
    Model("Logitech", "Harmony 650", None),  # 72
    Model("Logitech", "Harmony 600i", None),  # 73
    Model("Logitech", "Harmony 650i", None),  # 74
    Model("Logitech", "Harmony 665", None),  # 75
    Model("Unknown", "Unknown", None),  # 76
    Model("Unknown", "Unknown", None),  # 77
    Model("Logitech", "Harmony 300", None),  # 78
    Model("Logitech", "Harmony 300i", None),  # 79
    Model("Logitech", "Harmony 200", None),  # 80
    Model("Logitech", "Harmony 200i", None),  # 81
    Model("Logitech", "Harmony Link", None),  # 82
    Model("Logitech", "Harmony Link (EMEA)", None),  # 83
    Model("Unknown", "Unknown", None),  # 84
    Model("Unknown", "Unknown", None),  # 85
    Model("Unknown", "Unknown", None),  # 86
    Model("Unknown", "Unknown", None),  # 87
    Model("Unknown", "Unknown", None),  # 88
    Model("Unknown", "Unknown", None),  # 89
    Model("Unknown", "Unknown", None),  # 90
    Model("Unknown", "Unknown", None),  # 91
    Model("Unknown", "Unknown", None),  # 92
    Model("Unknown", "Unknown", None),  # 93
    Model("Unknown", "Unknown", None),  # 94
    Model("Unknown", "Unknown", None),  # 95
    Model("Unknown", "Unknown", None),  # 96
    Model("Logitech", "Harmony Ultimate Hub", None),  # 97
    Model("Unknown", "Unknown", None),  # 98
    Model("Logitech", "Harmony Touch", None),  # 99
    Model("Logitech", "Harmony Ultimate", None),  # 100
    Model("Unknown", "Unknown", None),  # 101
    Model("Logitech", "Harmony Ultimate One", None),  # 102
    Model("Unknown", "Unknown", None),  # 103
    Model("Logitech", "Harmony 350", None),  # 104
    Model("Unknown", "Unknown", None),  # 105
    Model("Logitech", "Harmony Home Hub", None),  # 106
    Model("Unknown", "Unknown", None),  # 107
    Model("Unknown", "Unknown", None),  # 108
    Model("Unknown", "Unknown", None),  # 109
    Model("Unknown", "Unknown", None),  # 110
    Model("Unknown", "Unknown", None),  # 111
    Model("Logitech", "Harmony 950", None),  # 112
    Model("Unknown", "Unknown", None),  # 113
    Model("Unknown", "Unknown", None),  # 114
    Model("Unknown", "Unknown", None),  # 115
    Model("Unknown", "Unknown", None),  # 116
    Model("Unknown", "Unknown", None),  # 117
    Model("Unknown", "Unknown", None),  # 118
    Model("Unknown", "Unknown", None),  # 119
)


ARCHITECTURES: tuple[Architecture, ...] = (
    Architecture(
        index=0,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000000,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=1,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000000,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=2,
        serial_location=SERIAL_IN_EEPROM,
        serial_address=0x000010,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x006000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x000003A5,
        cookie_size=2,
        end_vector=2,
        micro="PIC16LF877",
        flash_size=8,
        ram_size=368,
        eeprom_size=256,
        usb="USBN9603",
    ),
    Architecture(
        index=3,
        serial_location=SERIAL_IN_FLASH,
        serial_address=0x000110,
        flash_base=0x000000,
        firmware_base=0x010000,
        config_base=0x020000,
        firmware_update_base=0x020000,
        firmware_4847_offset=2,
        cookie=0x00000369,
        cookie_size=2,
        end_vector=2,
        micro="PIC18LC801",
        flash_size=0,
        ram_size=1536,
        eeprom_size=0,
        usb="USBN9604",
    ),
    Architecture(
        index=4,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000000,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=5,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000000,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=6,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000000,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=7,
        serial_location=SERIAL_IN_FLASH,
        serial_address=0x000110,
        flash_base=0x000000,
        firmware_base=0x010000,
        config_base=0x020000,
        firmware_update_base=0x020000,
        firmware_4847_offset=2,
        cookie=0x4D424D42,
        cookie_size=4,
        end_vector=5,
        micro="PIC18LC801",
        flash_size=0,
        ram_size=1536,
        eeprom_size=0,
        usb="USBN9604",
    ),
    Architecture(
        index=8,
        serial_location=SERIAL_IN_FLASH,
        serial_address=0x000110,
        flash_base=0x000000,
        firmware_base=0x010000,
        config_base=0x020000,
        firmware_update_base=0x1D0000,
        firmware_4847_offset=4,
        cookie=0x50545054,
        cookie_size=4,
        end_vector=4,
        micro="PIC18LC801",
        flash_size=0,
        ram_size=1536,
        eeprom_size=0,
        usb="USBN9604",
    ),
    Architecture(
        index=9,
        serial_location=SERIAL_IN_FLASH,
        serial_address=0x200010,
        flash_base=0x800000,
        firmware_base=0x810000,
        config_base=0x820000,
        firmware_update_base=0x810000,
        firmware_4847_offset=4,
        cookie=0x4D434841,
        cookie_size=4,
        end_vector=4,
        micro="PIC18LF4550",
        flash_size=16,
        ram_size=2048,
        eeprom_size=256,
        usb="Internal",
    ),
    Architecture(
        index=10,
        serial_location=SERIAL_IN_FLASH,
        serial_address=0x000110,
        flash_base=0x000000,
        firmware_base=0x010000,
        config_base=REGION_USER_CONFIG,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000001,
        cookie_size=4,
        end_vector=4,
        micro="PIC18LC801",
        flash_size=0,
        ram_size=1536,
        eeprom_size=0,
        usb="USBN9604",
    ),
    Architecture(
        index=11,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=REGION_USER_CONFIG,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000001,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=12,
        serial_location=SERIAL_IN_FLASH,
        serial_address=0xFFF400,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x040000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x4D505347,
        cookie_size=4,
        end_vector=4,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=13,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000000,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=14,
        serial_location=SERIAL_IN_FLASH,
        serial_address=0xFFF400,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x030000,
        firmware_update_base=0x000000,
        firmware_4847_offset=8,
        cookie=0x4D505347,
        cookie_size=4,
        end_vector=4,
        micro="PIC18F67J50",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="Internal",
    ),
    Architecture(
        index=15,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=REGION_USER_CONFIG,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x00000001,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=16,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x4D505347,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
    Architecture(
        index=17,
        serial_location=0,
        serial_address=0x000000,
        flash_base=0x000000,
        firmware_base=0x000000,
        config_base=0x000000,
        firmware_update_base=0x000000,
        firmware_4847_offset=0,
        cookie=0x4D505347,
        cookie_size=0,
        end_vector=0,
        micro="",
        flash_size=0,
        ram_size=0,
        eeprom_size=0,
        usb="",
    ),
)


def model_for_skin(skin: int) -> Model:
    """Look up a model by reported skin ID, clamping out-of-range values."""
    if 0 <= skin < len(MODELS):
        return MODELS[skin]
    return Model("Unknown", f"skin {skin}", None)


def architecture(index: int) -> Architecture | None:
    """Look up an architecture by reported index, or None if unknown."""
    if 0 <= index < len(ARCHITECTURES):
        return ARCHITECTURES[index]
    return None


def flash_chip(manufacturer_id: int, device_id: int) -> Flash:
    """Look up a flash chip, falling back to a conservative default.

    Some firmware reports the manufacturer and device IDs swapped, so we
    try both orders before giving up.
    """
    chip = FLASH_CHIPS.get((manufacturer_id, device_id))
    if chip is None:
        chip = FLASH_CHIPS.get((device_id, manufacturer_id))
    return chip or UNKNOWN_FLASH


def search_models(query: str) -> list[tuple[int, Model]]:
    """Case-insensitive substring search over known model names."""
    q = query.lower()
    return [
        (i, m)
        for i, m in enumerate(MODELS)
        if m.known and q in m.name.lower()
    ]
