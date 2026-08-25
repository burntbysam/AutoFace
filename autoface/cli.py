"""Command line: ``--selftest``, ``--version`` and the Inventor probes.

The same exe serves the GUI (no arguments) and this CLI. ``--selftest`` is
load-bearing: CI gates the published build on it and the updater refuses to
install a downloaded build that fails it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .version import describe

PROBE_NAMES = ("session", "partslist", "thickness", "export", "neversave")


def _output_path(filename: str) -> Path:
    """Next to the exe (or the working directory from source).

    AutoFace.exe is a windowed binary, so plain stdout is invisible when it is
    run from a console or Explorer; the probes and the self-test also write a
    file the user can actually read.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / filename
    return Path.cwd() / filename


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autoface",
        description="Batch flat-pattern DWG exporter for Autodesk Inventor.",
    )
    parser.add_argument("--version", action="version", version=describe())
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the built-in checks and exit 0/1 (used by CI and the updater)",
    )
    parser.add_argument(
        "--probe",
        choices=PROBE_NAMES + ("all",),
        help="run a read-only check against the live Inventor session and "
        "write AutoFace-probe-results.txt next to the executable",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        from .core.selftest import run_selftest

        ok, lines = run_selftest()
        report = "\n".join(
            [describe(), *lines, "SELF-TEST PASSED" if ok else "SELF-TEST FAILED"]
        )
        print(report)
        if getattr(sys, "frozen", False):
            # The windowed exe shows nothing in a console; leave the result
            # where the checklist can find it. Best effort only — CI and the
            # updater read the exit code, not this file.
            try:
                _output_path("AutoFace-selftest-results.txt").write_text(
                    report + "\n", encoding="utf-8"
                )
            except OSError:
                pass
        return 0 if ok else 1

    if args.probe:
        from .inventor.probes import run_probes

        names = PROBE_NAMES if args.probe == "all" else (args.probe,)
        report = run_probes(names)
        destination = _output_path("AutoFace-probe-results.txt")
        try:
            destination.write_text(report, encoding="utf-8")
            print(f"Probe results written to {destination}")
        except OSError as exc:
            print(f"Could not write {destination}: {exc}", file=sys.stderr)
            print(report)
            return 1
        print(report)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
