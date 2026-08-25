"""Version and build identity.

``VERSION`` is the human version and changes when someone edits it. ``build_id``
changes on every CI build, which is what lets the updater recognise a rebuild of
the same version as newer -- otherwise a fix shipped without a version bump
would never reach the shop floor.
"""

from __future__ import annotations

import json
import platform
import sys
from functools import lru_cache
from pathlib import Path

_DEV_BUILD_ID = "0.dev"


def _bundle_dir() -> Path:
    """Where data files live: the PyInstaller temp dir, or the source tree."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def version() -> str:
    try:
        return (_bundle_dir() / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


@lru_cache(maxsize=1)
def build_info() -> dict:
    """The stamp CI writes next to the bundle; defaults for a local build."""
    try:
        data = json.loads((_bundle_dir() / "build_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": version(), "build_id": _DEV_BUILD_ID, "commit": ""}
    data.setdefault("version", version())
    data.setdefault("build_id", _DEV_BUILD_ID)
    data.setdefault("commit", "")
    return data


def build_id() -> str:
    return str(build_info()["build_id"])


def run_number(identifier: str) -> int:
    """The CI run number embedded in a build id such as ``42.a1b2c3d``."""
    head = str(identifier).split(".", 1)[0].strip()
    try:
        return int(head)
    except ValueError:
        return 0


def describe() -> str:
    info = build_info()
    if info["build_id"] == _DEV_BUILD_ID:
        return f"AutoFace {version()}"
    return f"AutoFace {version()} (build {info['build_id']})"


def is_ci_build() -> bool:
    """False for a build made locally, which carries no CI stamp."""
    return build_id() != _DEV_BUILD_ID


def build_details() -> list[tuple[str, str]]:
    """Label/value pairs identifying exactly what is running.

    Kept here rather than in the window so the same answer is available
    without a GUI, and so "which build is the shop actually on?" has one
    source. Qt and the update source are appended by the caller that knows
    about them.
    """
    info = build_info()
    details: list[tuple[str, str]] = [("Version", version())]

    if is_ci_build():
        details.append(("Build", build_id()))
    else:
        details.append(("Build", "local build (not from CI)"))

    commit = str(info.get("commit") or "")
    if commit:
        details.append(("Commit", commit[:12]))

    if getattr(sys, "frozen", False):
        details.append(("Installed", str(Path(sys.executable))))
    else:
        details.append(("Installed", "running from source"))

    details.append(("Python", platform.python_version()))
    return details
