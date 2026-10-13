"""The web app (web/) reads and writes the same config format as this package."""

import json
from pathlib import Path

from harmonyforge.cli import main
from harmonyforge.config.model import RemoteConfig

ROOT = Path(__file__).resolve().parents[1]
#: Written by the web app's own tests (web/test/store.test.js) from its editing helpers.
WEB_EXPORT = ROOT / "web" / "test" / "fixtures" / "web-export.json"


def test_web_export_loads_and_round_trips():
    raw = json.loads(WEB_EXPORT.read_text(encoding="utf-8"))
    config = RemoteConfig.load(WEB_EXPORT)
    assert config.to_dict() == raw
    # Same key order too, so a file saved by either side diffs cleanly.
    assert config.to_json() == WEB_EXPORT.read_text(encoding="utf-8")


def test_web_export_is_valid():
    config = RemoteConfig.load(WEB_EXPORT)
    assert config.validate() == []
    activity = config.activities["WatchAMovie"]
    assert activity.label == "Watch a movie"
    assert [(s.device, s.function) for s in activity.start_sequence] == [
        ("TV", "PowerOn"),
        ("Streamer", "PowerToggle"),
        ("TV", "InputHDMI2"),
    ]
    assert activity.buttons["OK"] == "Streamer/Select"


def test_cli_validates_web_export_strictly():
    assert main(["config", "validate", str(WEB_EXPORT), "--strict"]) == 0
