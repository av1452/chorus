"""CLI surface tests."""

import json

import pytest

from harmonyforge.cli import build_parser, main


def test_parser_exposes_every_command():
    parser = build_parser()
    actions = [a for a in parser._actions if a.dest == "command"]
    assert actions, "no subparsers found"
    commands = set(actions[0].choices)
    assert {
        "detect", "identify", "backup", "restore", "read-flash", "remotes",
        "learn", "codes", "pronto", "config", "hub", "serve",
    } <= commands


def test_no_arguments_prints_help(capsys):
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_version_flag():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_remotes_lists_models(capsys):
    assert main(["remotes"]) == 0
    out = capsys.readouterr().out
    assert "Harmony 650" in out
    assert "skin" in out


def test_remotes_search_filters(capsys):
    assert main(["remotes", "--search", "880"]) == 0
    out = capsys.readouterr().out
    assert "Harmony 880" in out
    assert "Harmony 650" not in out


def test_remotes_search_miss_is_an_error(capsys):
    assert main(["remotes", "--search", "zzzz"]) == 1


def test_pronto_encode_then_decode(capsys):
    assert main(["pronto", "encode", "NEC", "address=0x04", "command=0x0C"]) == 0
    code = capsys.readouterr().out.strip()
    assert code.startswith("0000 006D")

    assert main(["pronto", "decode", *code.split()]) == 0
    out = capsys.readouterr().out
    assert "NEC" in out
    assert "address=0x04" in out


def test_pronto_encode_rejects_a_malformed_field(capsys):
    assert main(["pronto", "encode", "NEC", "address"]) == 2
    assert "name=value" in capsys.readouterr().err


def test_pronto_decode_reports_a_bad_code(capsys):
    assert main(["pronto", "decode", "ZZZZ"]) == 1
    assert "hex word" in capsys.readouterr().err


def test_subcommand_without_a_verb_is_an_error(capsys):
    assert main(["codes"]) == 2
    assert "needs a subcommand" in capsys.readouterr().err


def test_config_new_show_and_validate(tmp_path, capsys):
    path = tmp_path / "c.json"
    assert main(["config", "new", str(path), "--name", "Den", "-m", "Harmony 650"]) == 0
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["name"] == "Den"
    assert data["remote_model"] == "Harmony 650"
    capsys.readouterr()

    assert main(["config", "show", str(path)]) == 0
    assert "Den" in capsys.readouterr().out

    # An empty config warns about having no activities but still exits 0.
    assert main(["config", "validate", str(path)]) == 0
    assert "no activities" in capsys.readouterr().err
    # ...unless --strict is given.
    assert main(["config", "validate", str(path), "--strict"]) == 1


def test_config_new_refuses_to_clobber(tmp_path, capsys):
    path = tmp_path / "c.json"
    assert main(["config", "new", str(path)]) == 0
    capsys.readouterr()
    assert main(["config", "new", str(path)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert main(["config", "new", str(path), "--force"]) == 0


def test_config_show_reports_a_missing_file(capsys):
    assert main(["config", "show", "/nonexistent/x.json"]) == 1
    assert "no such config file" in capsys.readouterr().err


def test_codes_list_on_an_empty_library(tmp_path, capsys):
    assert main(["--library", str(tmp_path / "codes"), "codes", "list"]) == 0
    out = capsys.readouterr().out
    assert "empty" in out
    assert "harmonyforge learn" in out


def test_codes_import_and_show(tmp_path, capsys):
    ir_file = tmp_path / "Acme.ir"
    ir_file.write_text(
        "Filetype: IR signals file\nVersion: 1\n#\nname: Power\n"
        "type: parsed\nprotocol: NEC\naddress: 04 00 00 00\n"
        "command: 0C 00 00 00\n"
    )
    library = str(tmp_path / "codes")

    assert main(["--library", library, "codes", "import", str(ir_file)]) == 0
    assert "Imported" in capsys.readouterr().out

    assert main(["--library", library, "codes", "list"]) == 0
    assert "acme" in capsys.readouterr().out

    assert main(["--library", library, "codes", "show", "acme", "--pronto"]) == 0
    out = capsys.readouterr().out
    assert "Power" in out
    assert "0000 006D" in out


def test_codes_export_writes_a_flipper_file(tmp_path, capsys):
    ir_file = tmp_path / "Acme.ir"
    ir_file.write_text(
        "Filetype: IR signals file\nVersion: 1\n#\nname: Power\n"
        "type: parsed\nprotocol: NEC\naddress: 04 00 00 00\n"
        "command: 0C 00 00 00\n"
    )
    library = str(tmp_path / "codes")
    main(["--library", library, "codes", "import", str(ir_file)])
    capsys.readouterr()

    out_file = tmp_path / "out.ir"
    assert main(
        ["--library", library, "codes", "export", "acme", "-o", str(out_file)]
    ) == 0
    text = out_file.read_text()
    assert "Filetype: IR signals file" in text
    assert "Power" in text


def test_codes_search_miss(capsys, tmp_path):
    assert main(["--library", str(tmp_path), "codes", "search", "nope"]) == 1


def test_detect_with_no_remote_explains_itself(capsys):
    code = main(["detect"])
    # 1 when nothing is attached, 0 if a real remote happens to be present.
    assert code in (0, 1)
    if code == 1:
        captured = capsys.readouterr()
        message = captured.err + captured.out
        # Either no remote, or pyusb/libusb missing -- both must say so
        # plainly rather than traceback.
        assert "No Harmony remote found" in message or "pyusb" in message


def test_hub_requires_an_address(capsys):
    assert main(["hub", "info"]) == 2
    assert "--address is required" in capsys.readouterr().err
