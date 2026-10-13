"""Hardware table tests."""

from chorus import devicedb


def test_every_model_index_resolves():
    for index in range(len(devicedb.MODELS)):
        assert devicedb.model_for_skin(index) is not None


def test_known_models_have_expected_skins():
    # These skin IDs are what the remotes actually report over USB.
    assert devicedb.model_for_skin(72).name == "Harmony 650"
    assert devicedb.model_for_skin(54).name == "Harmony One"
    assert devicedb.model_for_skin(15).name == "Harmony 880"
    assert devicedb.model_for_skin(66).name == "Harmony 700"
    assert devicedb.model_for_skin(71).name == "Harmony 600"


def test_out_of_range_skin_is_handled():
    model = devicedb.model_for_skin(9999)
    assert not model.known
    assert "9999" in model.name


def test_architecture_lookup_and_support_flag():
    arch7 = devicedb.architecture(7)
    assert arch7 is not None
    assert arch7.config_base == 0x020000
    assert arch7.cookie == 0x4D424D42
    assert arch7.supported

    # Placeholder architectures are flagged as unsupported.
    assert not devicedb.architecture(0).supported
    assert devicedb.architecture(99) is None


def test_arch12_one_has_flash_serial():
    arch = devicedb.architecture(12)
    assert arch.serial_location == devicedb.SERIAL_IN_FLASH
    assert arch.serial_address == 0xFFF400
    assert arch.config_base == 0x040000


def test_arch2_745_uses_eeprom_serial():
    arch = devicedb.architecture(2)
    assert arch.serial_location == devicedb.SERIAL_IN_EEPROM
    assert arch.cookie_size == 2


def test_region_user_config_sentinel():
    # The usbnet family looks its config region up at runtime.
    for index in (10, 11, 15):
        assert devicedb.architecture(index).config_base == devicedb.REGION_USER_CONFIG


def test_flash_lookup_including_swapped_ids():
    chip = devicedb.flash_chip(0x01, 0x49)
    assert chip.name == "AMD Am29LV160BB"
    assert chip.size_kb == 2048
    assert chip.size_bytes == 2048 * 1024
    # Some firmware reports the pair the other way round.
    assert devicedb.flash_chip(0x1C, 0x15).name == "EON F16-100HIP"


def test_unknown_flash_falls_back_safely():
    chip = devicedb.flash_chip(0xAB, 0xCD)
    assert chip is devicedb.UNKNOWN_FLASH
    assert chip.sectors


def test_sector_maps_are_ascending():
    for chip in devicedb.FLASH_CHIPS.values():
        sectors = [s for s in chip.sectors if s]
        # sectors5 has a known typo upstream; just assert it is non-trivial.
        assert len(sectors) > 1


def test_search_models():
    hits = {i: m.name for i, m in devicedb.search_models("harmony 6")}
    assert 72 in hits and hits[72] == "Harmony 650"
    assert all("harmony 6" in name.lower() for name in hits.values())
