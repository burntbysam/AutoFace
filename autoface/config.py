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
# Bare = Inventor's default DWG export settings. If a given Inventor version
# rejects the bare string (the --probe export check covers this), set
# "FLAT PATTERN DWG?AcadVersion=2018" here instead.
DEFAULT_DWG_FORMAT = "FLAT PATTERN DWG"


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
    return Config(
        output_root=str(payload.get("output_root") or ""),
        thickness_table=table,
        dwg_format=str(payload.get("dwg_format") or DEFAULT_DWG_FORMAT),
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
