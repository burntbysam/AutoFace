#!/usr/bin/env python3
"""Bump the version in VERSION.

    python scripts/bump_version.py patch    # 1.0.0 -> 1.0.1   any push
    python scripts/bump_version.py minor    # 1.0.1 -> 1.1.0   feature added,
                                            #                  removed or overhauled
    python scripts/bump_version.py major    # 1.1.0 -> 2.0.0   whole app overhauled

Doing this by hand invites a forgotten or malformed bump, and VERSION drives
both the published release and what the updater compares against.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

LEVELS = ("major", "minor", "patch")


def parse(text: str) -> tuple[int, int, int]:
    match = _PATTERN.match(text.strip())
    if match is None:
        raise ValueError(f"VERSION must look like 1.2.3, found {text.strip()!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def bump(version: tuple[int, int, int], level: str) -> tuple[int, int, int]:
    """Raise one component and reset the ones below it."""
    major, minor, patch = version
    if level == "major":
        return major + 1, 0, 0
    if level == "minor":
        return major, minor + 1, 0
    if level == "patch":
        return major, minor, patch + 1
    raise ValueError(f"level must be one of {LEVELS}, got {level!r}")


def render(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("level", choices=LEVELS)
    parser.add_argument(
        "--dry-run", action="store_true", help="print the new version, change nothing"
    )
    args = parser.parse_args(argv)

    try:
        current = parse(VERSION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    updated = bump(current, args.level)
    if args.level == "major":
        # A major bump is the maintainer's call, never Claude's to take alone.
        print("note: major bumps need the maintainer's agreement first.", file=sys.stderr)

    if not args.dry_run:
        VERSION_FILE.write_text(render(updated) + "\n", encoding="utf-8")
    print(f"{render(current)} -> {render(updated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
