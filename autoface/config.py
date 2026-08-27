"""User configuration: the output folder, the thickness table, the DWG format.

One JSON file in ``%APPDATA%\\AutoFace\\config.json`` (created with defaults on
first use) so the shop can add a standard thickness or change the DWG format
string without touching code. Unknown keys survive a load/save round trip, so
a hand-edited file is never quietly stripped.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "config.json"

DEFAULT_THICKNESS_TABLE = {
    "0.125": "125",  # 1/8"
    "0.1875": "1875",  # 3/16"
}
# Inventor's default flat-pattern DWG, minus the layers CAM does not want:
# bend centerlines (IV_BEND, IV_BEND_DOWN), the point markers at hole centers
# (IV_ARC_CENTERS) and at punched-feature/slot centers (IV_TOOL_CENTER,
# IV_TOOL_CENTER_DOWN), and the bend-extent tangent lines flanking each bend
# (IV_TANGENT; IV_ROLL_TANGENT is their rolled-part counterpart). If a given
# Inventor version rejects the string (the --probe export check covers this),
# prepend "AcadVersion=2018&" to the options.
_HIDDEN_LAYERS = (
    "IV_BEND;IV_BEND_DOWN;IV_ARC_CENTERS;IV_TANGENT;IV_ROLL_TANGENT;"
    "IV_TOOL_CENTER;IV_TOOL_CENTER_DOWN"
)
DEFAULT_DWG_FORMAT = f"FLAT PATTERN DWG?InvisibleLayers={_HIDDEN_LAYERS}"

# Every hidden-layer list a previous release shipped as its default. A stored
# format string matching any of them (with or without the documented
# AcadVersion fallback) was never a user customization, so it upgrades to the
# current default; anything else the user typed is left alone.
_PREVIOUS_HIDDEN_LAYERS = (
    "",  # v0.1.0: bare "FLAT PATTERN DWG"
    "IV_BEND;IV_BEND_DOWN;IV_ARC_CENTERS",  # v0.1.1
    "IV_BEND;IV_BEND_DOWN;IV_ARC_CENTERS;IV_TANGENT;IV_ROLL_TANGENT",  # v0.1.3
)


def _legacy_formats() -> dict[str, str]:
    with_version = f"FLAT PATTERN DWG?AcadVersion=2018&InvisibleLayers={_HIDDEN_LAYERS}"
    mapping: dict[str, str] = {}
    for layers in _PREVIOUS_HIDDEN_LAYERS:
        if layers:
            mapping[f"FLAT PATTERN DWG?InvisibleLayers={layers}"] = DEFAULT_DWG_FORMAT
            mapping[
                f"FLAT PATTERN DWG?AcadVersion=2018&InvisibleLayers={layers}"
            ] = with_version
        else:
            mapping["FLAT PATTERN DWG"] = DEFAULT_DWG_FORMAT
            mapping["FLAT PATTERN DWG?AcadVersion=2018"] = with_version
    return mapping


_LEGACY_DWG_FORMATS = _legacy_formats()


def config_dir() -> Path:
    r"""``%APPDATA%\AutoFace`` on Windows; a dot-directory elsewhere (dev/tests)."""
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "AutoFace"
    return Path.home() / ".autoface"


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


@dataclass
class Config:
    output_root: str = ""
    thickness_table: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_THICKNESS_TABLE)
    )
    dwg_format: str = DEFAULT_DWG_FORMAT
    extras: dict = field(default_factory=dict)  # unknown keys, preserved

    def to_payload(self) -> dict:
        payload = dict(self.extras)
        payload["output_root"] = self.output_root
        payload["thickness_table"] = dict(self.thickness_table)
        payload["dwg_format"] = self.dwg_format
        return payload


def load_config(path: Path | None = None) -> Config:
    """Read the config, tolerating a missing or damaged file."""
    path = path or config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    if not isinstance(payload, dict):
        return Config()

    table = payload.get("thickness_table")
    if not isinstance(table, dict) or not table:
        table = dict(DEFAULT_THICKNESS_TABLE)
    else:
        table = {str(key): str(value) for key, value in table.items()}

    extras = {
        key: value
        for key, value in payload.items()
        if key not in ("output_root", "thickness_table", "dwg_format")
    }
    dwg_format = str(payload.get("dwg_format") or DEFAULT_DWG_FORMAT)
    dwg_format = _LEGACY_DWG_FORMATS.get(dwg_format, dwg_format)
    return Config(
        output_root=str(payload.get("output_root") or ""),
        thickness_table=table,
        dwg_format=dwg_format,
        extras=extras,
    )


def save_config(config: Config, path: Path | None = None) -> None:
    """Write the config; failure is soft (a read-only profile must not crash)."""
    path = path or config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config.to_payload(), indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass
