"""Configuration model tests."""

import json

import pytest

from chorus.config.model import (
    Activity,
    Device,
    DeviceType,
    Function,
    PowerStyle,
    RemoteConfig,
    Step,
)
from chorus.errors import ConfigError
from chorus.ir import protocols


def sample_config() -> RemoteConfig:
    config = RemoteConfig(name="Living Room", remote_model="Harmony 650")
    tv = config.add_device(
        Device(
            "TV",
            manufacturer="Sony",
            model="KDL-55",
            type=DeviceType.TELEVISION,
            power_style=PowerStyle.DISCRETE,
            inputs=["InputHDMI1"],
        )
    )
    for name, command in [
        ("PowerOn", 0x2E),
        ("PowerOff", 0x2F),
        ("InputHDMI1", 0x25),
        ("VolUp", 0x12),
    ]:
        tv.add(
            Function.from_signal(
                name, protocols.encode("SIRC", address=1, command=command)
            )
        )
    activity = config.add_activity(
        Activity("WatchTV", label="Watch TV", primary_device="TV", volume_device="TV")
    )
    activity.start_sequence = [
        Step("TV", "PowerOn", 3000),
        Step("TV", "InputHDMI1", 500),
    ]
    activity.stop_sequence = [Step("TV", "PowerOff", 0)]
    activity.buttons = {"VolumeUp": "TV/VolUp"}
    return config


def test_function_identifies_its_protocol():
    function = Function.from_signal(
        "PowerOn", protocols.encode("NEC", address=4, command=12)
    )
    assert function.protocol == "NEC"
    assert function.display_name == "PowerOn"
    assert function.signal.frequency == 38000


def test_function_from_pronto_round_trips():
    original = Function.from_signal(
        "Power", protocols.encode("NEC", address=4, command=12)
    )
    restored = Function.from_pronto("Power", original.to_pronto())

    # Pronto stores durations as whole carrier cycles, and its divisor word
    # 0x6D means 38029 Hz rather than exactly 38000 -- so durations come back
    # quantised and very slightly stretched. What must survive is the decoded
    # meaning, which is what IRSignal.matches() tests for.
    assert restored.protocol == "NEC"
    assert restored.signal.matches(original.signal)


def test_function_needs_a_name():
    with pytest.raises(ConfigError, match="needs a name"):
        Function(name="")


def test_power_function_selection_respects_style():
    discrete = Device("A", power_style=PowerStyle.DISCRETE)
    discrete.add(Function("PowerOn", durations=(1,)))
    discrete.add(Function("PowerOff", durations=(1,)))
    discrete.add(Function("Power", durations=(1,)))
    assert discrete.power_on_function == "PowerOn"
    assert discrete.power_off_function == "PowerOff"

    toggle = Device("B", power_style=PowerStyle.TOGGLE)
    toggle.add(Function("Power", durations=(1,)))
    assert toggle.power_on_function == "Power"
    assert toggle.power_off_function == "Power"


def test_device_get_lists_alternatives_on_miss():
    device = Device("TV")
    device.add(Function("PowerOn", durations=(1,)))
    with pytest.raises(ConfigError, match="PowerOn"):
        device.get("Nope")


def test_duplicate_names_are_refused():
    config = sample_config()
    with pytest.raises(ConfigError, match="already exists"):
        config.add_device(Device("TV"))
    with pytest.raises(ConfigError, match="already exists"):
        config.add_activity(Activity("WatchTV"))


def test_resolve_reference():
    config = sample_config()
    assert config.resolve("TV/VolUp").name == "VolUp"
    with pytest.raises(ConfigError, match="Device/Function"):
        config.resolve("VolUp")
    with pytest.raises(ConfigError, match="no device named"):
        config.resolve("Ghost/VolUp")


def test_valid_config_has_no_warnings():
    assert sample_config().validate() == []


def test_validate_catches_dangling_button_target():
    config = sample_config()
    config.activity("WatchTV").buttons["Mute"] = "TV/Mute"
    warnings = config.validate()
    assert any("Mute" in w and "does not exist" in w for w in warnings)


def test_validate_catches_unknown_device_in_step():
    config = sample_config()
    config.activity("WatchTV").start_sequence.append(Step("Ghost", "PowerOn"))
    assert any("unknown device 'Ghost'" in w for w in config.validate())


def test_validate_catches_malformed_button_target():
    config = sample_config()
    config.activity("WatchTV").buttons["Mute"] = "justafunction"
    assert any("expected 'Device/Function'" in w for w in config.validate())


def test_validate_warns_about_toggle_power_on_a_tv():
    config = sample_config()
    config.device("TV").power_style = PowerStyle.TOGGLE
    assert any("power toggle" in w for w in config.validate())


def test_validate_warns_about_missing_discrete_codes():
    config = sample_config()
    del config.device("TV").functions["PowerOff"]
    assert any("discrete-power but lacks" in w for w in config.validate())


def test_validate_warns_about_an_input_that_is_not_a_function():
    config = sample_config()
    config.device("TV").inputs.append("InputHDMI9")
    assert any("InputHDMI9" in w for w in config.validate())


def test_validate_warns_about_an_empty_start_sequence():
    config = sample_config()
    config.activity("WatchTV").start_sequence = []
    assert any("no start sequence" in w for w in config.validate())


def test_activity_devices_used():
    assert sample_config().activity("WatchTV").devices_used == ["TV"]


def test_steps_need_both_parts():
    with pytest.raises(ConfigError, match="device and a function"):
        Step("", "PowerOn")
    with pytest.raises(ConfigError, match="device and a function"):
        Step("TV", "")


def test_dict_round_trip_is_lossless():
    config = sample_config()
    restored = RemoteConfig.from_dict(config.to_dict())
    assert restored.to_dict() == config.to_dict()
    assert restored.device("TV").get("VolUp").durations == (
        config.device("TV").get("VolUp").durations
    )


def test_json_file_round_trip(tmp_path):
    config = sample_config()
    path = config.save(tmp_path / "config.json")
    restored = RemoteConfig.load(path)
    assert restored.name == "Living Room"
    assert restored.function_count == 4
    assert restored.validate() == []


def test_saved_json_is_human_readable(tmp_path):
    path = sample_config().save(tmp_path / "config.json")
    data = json.loads(path.read_text())
    assert data["devices"]["TV"]["manufacturer"] == "Sony"
    assert "durations" in data["devices"]["TV"]["functions"]["VolUp"]


def test_load_rejects_a_future_schema(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema_version": 999}))
    with pytest.raises(ConfigError, match="Upgrade"):
        RemoteConfig.load(path)


def test_load_reports_bad_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        RemoteConfig.load(path)


def test_load_reports_a_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="no such config file"):
        RemoteConfig.load(tmp_path / "absent.json")


def test_summary_mentions_the_contents():
    summary = sample_config().summary()
    assert "Living Room" in summary
    assert "TV" in summary
    assert "Watch TV" in summary


def test_modified_timestamp_updates_on_save(tmp_path):
    config = sample_config()
    before = config.modified
    config.modified = "2000-01-01T00:00:00+00:00"
    config.save(tmp_path / "c.json")
    assert config.modified != "2000-01-01T00:00:00+00:00"
    assert before
