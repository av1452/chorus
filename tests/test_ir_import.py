"""LIRC, Flipper and code-library import tests."""

import pytest

from harmonyforge.errors import IRError
from harmonyforge.ir import flipper, lirc, protocols
from harmonyforge.ir.database import CodeLibrary, CodeSet

SPACE_ENC_CONF = """
begin remote
  name  SONY_TV
  bits  7
  flags SPACE_ENC|CONST_LENGTH
  header 2400 600
  one    1200 600
  zero    600 600
  ptrail  0
  post_data_bits 5
  post_data 0x01
  gap   45000
  frequency 40000
  begin codes
      KEY_POWER  0x15
      KEY_VOLUMEUP  0x12
  end codes
end remote
"""

RAW_CONF = """
begin remote
  name  RAW_TV
  flags RAW_CODES
  frequency 38000
  begin raw_codes
    name KEY_POWER
      9000 4500 560 1690
      560 560
    name KEY_MENU
      9000 4500 560 560
  end raw_codes
end remote
"""

FLIPPER_IR = """Filetype: IR signals file
Version: 1
#
name: Power
type: parsed
protocol: NECext
address: 34 12 00 00
command: 56 00 00 00
#
name: Vol_up
type: raw
frequency: 38000
duty_cycle: 0.330000
data: 9000 4500 560 1690 560 560
#
name: Unsupported
type: parsed
protocol: RCA
address: 01 00 00 00
command: 02 00 00 00
"""


def test_lirc_space_enc_parses_and_synthesises():
    remote = lirc.parse(SPACE_ENC_CONF)[0]
    assert remote.name == "SONY_TV"
    assert remote.frequency == 40000
    assert remote.buttons == ["KEY_POWER", "KEY_VOLUMEUP"]
    assert not remote.is_raw

    signal = remote.signal("KEY_POWER")
    assert signal.frequency == 40000
    # 12 bits total (7 + 5 post) -> leader pair + 12 bit pairs. ptrail is 0,
    # so the final space is widened to the 45 ms gap rather than appended.
    assert len(signal.durations) == 2 + 24
    assert signal.durations[-1] == 45000
    # It really is a Sony waveform.
    assert protocols.identify(signal).protocol == "SIRC"


def test_lirc_raw_codes_parse():
    remote = lirc.parse(RAW_CONF)[0]
    assert remote.is_raw
    assert remote.buttons == ["KEY_MENU", "KEY_POWER"]
    assert remote.signal("KEY_POWER").durations == (9000, 4500, 560, 1690, 560, 560)


def test_lirc_unknown_button_lists_options():
    remote = lirc.parse(SPACE_ENC_CONF)[0]
    with pytest.raises(IRError, match="KEY_POWER"):
        remote.signal("KEY_NOPE")


def test_lirc_comments_and_blank_lines_are_ignored():
    text = SPACE_ENC_CONF.replace("  bits  7", "  # a comment\n  bits  7\n\n")
    assert lirc.parse(text)[0].bits == 7


def test_lirc_without_timings_is_reported_not_guessed():
    text = """
begin remote
  name NO_TIMINGS
  bits 8
  flags RC6
  begin codes
    KEY_POWER 0x12
  end codes
end remote
"""
    remote = lirc.parse(text)[0]
    with pytest.raises(IRError, match="unsupported encoding"):
        remote.signal("KEY_POWER")


def test_lirc_multiple_remotes_in_one_file():
    remotes = lirc.parse(SPACE_ENC_CONF + RAW_CONF)
    assert [r.name for r in remotes] == ["SONY_TV", "RAW_TV"]


def test_flipper_parses_both_record_kinds():
    records = flipper.parse(FLIPPER_IR)
    assert [r.name for r in records] == ["Power", "Vol_up", "Unsupported"]
    assert records[0].kind == "parsed"
    assert records[0].address == 0x1234
    assert records[0].command == 0x56
    assert records[1].durations == (9000, 4500, 560, 1690, 560, 560)


def test_flipper_parsed_record_synthesises_the_right_code():
    record = flipper.parse(FLIPPER_IR)[0]
    decoded = protocols.identify(record.signal())
    assert decoded.protocol == "NECext"
    assert decoded.fields == {"address": 0x1234, "command": 0x56}


def test_flipper_unsupported_protocol_is_reported():
    record = flipper.parse(FLIPPER_IR)[2]
    with pytest.raises(IRError, match="cannot synthesise"):
        record.signal()


def test_flipper_rejects_a_non_ir_file():
    with pytest.raises(IRError, match="no IR records"):
        flipper.parse("hello world")


def test_flipper_dump_round_trip():
    signal = protocols.encode("NEC", address=4, command=12)
    object.__setattr__(signal, "name", "Power")
    text = flipper.dump([signal])
    assert "Filetype: IR signals file" in text
    assert "protocol: NEC" in text
    reparsed = flipper.parse(text)[0]
    assert protocols.identify(reparsed.signal()).fields == {
        "address": 4,
        "command": 12,
    }


def test_flipper_dump_falls_back_to_raw_for_unknown_signals():
    from harmonyforge.ir.signal import IRSignal

    text = flipper.dump([IRSignal(frequency=38000, durations=(111, 222, 333))])
    assert "type: raw" in text
    assert "data: 111 222 333" in text


def test_library_save_search_and_find(tmp_path):
    library = CodeLibrary(tmp_path / "codes")
    code_set = CodeSet("Sony TV", "Sony", "KDL-55", "television")
    code_set.add("PowerOn", protocols.encode("SIRC", address=1, command=0x2E))
    library.save(code_set)

    assert len(library) == 1
    assert library.find("sony-kdl-55").label == "Sony KDL-55"
    assert [c.slug for c in library.search("sony")] == ["sony-kdl-55"]
    assert library.find("sony-kdl-55").functions["PowerOn"].durations


def test_library_find_reports_no_match(tmp_path):
    library = CodeLibrary(tmp_path / "codes")
    with pytest.raises(IRError, match="no code set matching"):
        library.find("nothing")


def test_library_find_reports_ambiguity(tmp_path):
    library = CodeLibrary(tmp_path / "codes")
    for model in ("A1", "A2"):
        code_set = CodeSet(f"TV {model}", "Acme", model)
        code_set.add("Power", protocols.encode("NEC", address=1, command=1))
        library.save(code_set)
    with pytest.raises(IRError, match="matches 2 code sets"):
        library.find("acme")


def test_library_import_lirc(tmp_path):
    conf = tmp_path / "lircd.conf"
    conf.write_text(SPACE_ENC_CONF)
    library = CodeLibrary(tmp_path / "codes")
    sets = library.import_lirc(conf)
    assert len(sets) == 1
    assert set(sets[0].functions) == {"KEY_POWER", "KEY_VOLUMEUP"}


def test_library_import_flipper_infers_manufacturer_from_directory(tmp_path):
    folder = tmp_path / "Flipper-IRDB" / "Sony"
    folder.mkdir(parents=True)
    (folder / "Bravia.ir").write_text(FLIPPER_IR)

    library = CodeLibrary(tmp_path / "codes")
    code_set = library.import_flipper(folder / "Bravia.ir")
    assert code_set.manufacturer == "Sony"
    assert code_set.model == "Bravia"
    # The unsupported record is skipped, the other two kept.
    assert set(code_set.functions) == {"Power", "Vol_up"}
    assert "skipped" in code_set.notes


def test_library_import_tree_collects_problems(tmp_path):
    root = tmp_path / "db"
    (root / "Sony").mkdir(parents=True)
    (root / "Sony" / "Good.ir").write_text(FLIPPER_IR)
    (root / "Sony" / "Bad.ir").write_text("not an ir file")

    library = CodeLibrary(tmp_path / "codes")
    imported, problems = library.import_tree(root)
    assert [c.model for c in imported] == ["Good"]
    assert len(problems) == 1
    assert "Bad.ir" in problems[0]


def test_library_import_pronto(tmp_path):
    from harmonyforge.ir import pronto

    signal = protocols.encode("NEC", address=4, command=12)
    library = CodeLibrary(tmp_path / "codes")
    code_set = library.import_pronto(
        "Acme TV", {"Power": pronto.format_signal(signal)}, manufacturer="Acme"
    )
    imported = code_set.functions["Power"]
    # Cycle quantisation again: compare meaning, not microseconds.
    assert protocols.identify(imported).fields == {"address": 4, "command": 12}
    assert len(imported.durations) == len(signal.durations)


def test_library_round_trip_through_disk(tmp_path):
    library = CodeLibrary(tmp_path / "codes")
    code_set = CodeSet("X", "Acme", "X1")
    original = protocols.encode("RC5", address=5, command=0x35)
    code_set.add("Power", original)
    path = library.save(code_set)
    restored = library.load(path)
    assert restored.functions["Power"].durations == original.durations
    assert restored.functions["Power"].frequency == original.frequency


def test_library_iteration_skips_corrupt_files(tmp_path):
    library = CodeLibrary(tmp_path / "codes")
    code_set = CodeSet("Good", "Acme", "G1")
    code_set.add("Power", protocols.encode("NEC", address=1, command=1))
    library.save(code_set)
    (library.root / "broken.json").write_text("{nope")
    assert [c.model for c in library] == ["G1"]
