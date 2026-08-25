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


def test_empty_thickness_table_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"thickness_table": {}}), encoding="utf-8")
    assert load_config(path).thickness_table == DEFAULT_THICKNESS_TABLE


def test_save_failure_is_soft(tmp_path):
    target = tmp_path / "not-a-dir"
    target.write_text("file blocks the directory", encoding="utf-8")
    save_config(Config(), target / "config.json")  # must not raise
