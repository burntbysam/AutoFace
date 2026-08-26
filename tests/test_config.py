"""Config round trips, defaults, and damage tolerance."""

import json

from autoface.config import (
    Config,
    DEFAULT_DWG_FORMAT,
    DEFAULT_THICKNESS_TABLE,
    load_config,
    save_config,
)


def test_missing_file_gives_defaults(tmp_path):
    config = load_config(tmp_path / "config.json")
    assert config.output_root == ""
    assert config.thickness_table == DEFAULT_THICKNESS_TABLE
    assert config.dwg_format == DEFAULT_DWG_FORMAT


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    config = Config(output_root="C:\\out", thickness_table={"0.125": "125"})
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.output_root == "C:\\out"
    assert loaded.thickness_table == {"0.125": "125"}


def test_unknown_keys_survive(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"output_root": "C:\\x", "someday": {"a": 1}}), encoding="utf-8"
    )
    config = load_config(path)
    assert config.extras == {"someday": {"a": 1}}
    save_config(config, path)
    assert json.loads(path.read_text())["someday"] == {"a": 1}


def test_damaged_file_gives_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_config(path).thickness_table == DEFAULT_THICKNESS_TABLE
    path.write_text(json.dumps(["a", "list"]), encoding="utf-8")
    assert load_config(path).output_root == ""


def test_legacy_default_dwg_format_upgrades(tmp_path):
    # Earlier releases wrote the bare string as their default; a config
    # carrying it was never a customization and must pick up the new default.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"dwg_format": "FLAT PATTERN DWG"}), encoding="utf-8")
    assert load_config(path).dwg_format == DEFAULT_DWG_FORMAT


def test_legacy_acadversion_fallback_keeps_its_version_and_gains_the_layers(
    tmp_path,
):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"dwg_format": "FLAT PATTERN DWG?AcadVersion=2018"}),
        encoding="utf-8",
    )
    upgraded = load_config(path).dwg_format
    assert "AcadVersion=2018" in upgraded
    assert "IV_BEND;IV_BEND_DOWN;IV_ARC_CENTERS;IV_TANGENT" in upgraded


def test_each_previous_default_upgrades_to_the_current_one(tmp_path):
    previous_defaults = [
        "FLAT PATTERN DWG",
        "FLAT PATTERN DWG?InvisibleLayers=IV_BEND;IV_BEND_DOWN;IV_ARC_CENTERS",
    ]
    for stored in previous_defaults:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"dwg_format": stored}), encoding="utf-8")
        assert load_config(path).dwg_format == DEFAULT_DWG_FORMAT, stored
    assert "IV_TANGENT;IV_ROLL_TANGENT" in DEFAULT_DWG_FORMAT


def test_a_custom_dwg_format_is_left_alone(tmp_path):
    path = tmp_path / "config.json"
    custom = "FLAT PATTERN DWG?AcadVersion=2013&OuterProfileLayer=Burn"
    path.write_text(json.dumps({"dwg_format": custom}), encoding="utf-8")
    assert load_config(path).dwg_format == custom


def test_empty_thickness_table_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"thickness_table": {}}), encoding="utf-8")
    assert load_config(path).thickness_table == DEFAULT_THICKNESS_TABLE


def test_save_failure_is_soft(tmp_path):
    target = tmp_path / "not-a-dir"
    target.write_text("file blocks the directory", encoding="utf-8")
    save_config(Config(), target / "config.json")  # must not raise
