"""The built-in self-test: the spec's worked examples run against the planner.

CI runs this against the built exe before publishing, and the updater runs it
against a downloaded build before swapping it in. It needs no Inventor: it
feeds the planner a synthetic session that exercises every classification and
checks the exact paths the spec calls out.
"""

from __future__ import annotations

import os

from .models import Classification, ModelKind, ScannedDrawing, ScannedRow
from .naming import parse_drawing_name
from .pipeline import build_plan
from .thickness import ThicknessTable, parse_description_thickness

_TABLE = {"0.125": "125", "0.1875": "1875"}

_EXISTING = {os.path.join("C:\\out", "RUN 11", "125", "8640-1101-9.dwg")}


def _sheet(item, thickness_cm, description, path="C:\\models\\part.ipt", **kw):
    return ScannedRow(
        item=item,
        part_number=kw.pop("part_number", f"PN-{item}"),
        description=description,
        model_kind=ModelKind.SHEET_METAL,
        model_path=path,
        thickness_cm=thickness_cm,
        has_flat_pattern=kw.pop("has_flat_pattern", True),
        **kw,
    )


def _synthetic_session() -> list[ScannedDrawing]:
    inch = 2.54
    return [
        ScannedDrawing(
            path="C:\\drawings\\8640-01101-I.idw",
            rows=(
                # The spec's two worked examples.
                _sheet("1", 0.190 * inch, "SHEET,AL,SMOOTH,.190,60X133.13"),
                _sheet("5", 0.125 * inch, "SHEET,AL,SMOOTH,.125,60X144"),
                # Description disagrees with the model: description wins.
                _sheet("2", 0.125 * inch, "SHEET,AL,SMOOTH,.190,10X10"),
                # Not in the thickness table.
                _sheet("3", 0.250 * inch, "SHEET,AL,SMOOTH,.250,10X10"),
                # The other classifications.
                ScannedRow("4", "PN-4", "BRACKET", ModelKind.NOT_SHEET_METAL),
                ScannedRow("6", "PN-6", "SUB ASSY", ModelKind.SUB_ASSEMBLY),
                ScannedRow("7", "PN-7", "VIRTUAL", ModelKind.NO_MODEL),
                # Collides with a file already on disk.
                _sheet("9", 0.125 * inch, "SHEET,AL,SMOOTH,.125,10X10"),
            ),
        ),
        ScannedDrawing(
            path="C:\\drawings\\NOT-A-JOB.idw",
            rows=(_sheet("1", 0.125 * inch, "SHEET,AL,SMOOTH,.125,10X10"),),
        ),
    ]


def run_selftest() -> tuple[bool, list[str]]:
    """Returns (ok, detail lines). Never raises."""
    lines: list[str] = []
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        mark = "ok" if ok else "FAIL"
        lines.append(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures += 1

    try:
        name = parse_drawing_name("C:\\drawings\\8640-01101-I.idw")
        check(
            "drawing name 8640-01101-I parses to job 8640, assembly 1101, RUN 11",
            name is not None
            and (name.job, name.assembly, name.run) == ("8640", "1101", "11"),
            repr(name),
        )
        check(
            'description ".190" parses out of SHEET,AL,SMOOTH,.190,60X133.13',
            parse_description_thickness("SHEET,AL,SMOOTH,.190,60X133.13") == 0.190,
        )

        plan = build_plan(
            _synthetic_session(),
            "C:\\out",
            ThicknessTable(_TABLE),
            path_exists=lambda p: p in _EXISTING,
        )
        by_item = {
            (row.drawing_label, row.item): row for row in plan.rows
        }

        row = by_item[("8640-01101-I", "1")]
        check(
            'item 1 (.190) -> RUN 11\\1875\\8640-1101-1.dwg',
            row.classification is Classification.EXPORT
            and row.target_relative == "RUN 11\\1875\\8640-1101-1.dwg",
            row.target_relative,
        )
        row = by_item[("8640-01101-I", "5")]
        check(
            'item 5 (.125) -> RUN 11\\125\\8640-1101-5.dwg',
            row.classification is Classification.EXPORT
            and row.target_relative == "RUN 11\\125\\8640-1101-5.dwg",
            row.target_relative,
        )
        row = by_item[("8640-01101-I", "2")]
        check(
            "description .190 overrides model .125 and is flagged",
            row.classification is Classification.EXPORT
            and row.target_relative == "RUN 11\\1875\\8640-1101-2.dwg"
            and any("cross-check" in flag for flag in row.flags),
            f"{row.target_relative} flags={row.flags}",
        )
        check(
            "quarter-inch part is Skip: invalid thickness",
            by_item[("8640-01101-I", "3")].classification
            is Classification.SKIP_INVALID_THICKNESS,
        )
        check(
            "non-sheet-metal part is skipped",
            by_item[("8640-01101-I", "4")].classification
            is Classification.SKIP_NOT_SHEET_METAL,
        )
        check(
            "sub-assembly row is skipped",
            by_item[("8640-01101-I", "6")].classification
            is Classification.SKIP_SUB_ASSEMBLY,
        )
        check(
            "row with no model is skipped",
            by_item[("8640-01101-I", "7")].classification
            is Classification.SKIP_NO_MODEL,
        )
        check(
            "existing file on disk is Skip: name collision, never overwritten",
            by_item[("8640-01101-I", "9")].classification
            is Classification.SKIP_NAME_COLLISION,
        )
        check(
            "unparseable drawing name skips its rows",
            by_item[("NOT-A-JOB", "1")].classification
            is Classification.SKIP_UNPARSEABLE_DRAWING,
        )
    except Exception as exc:  # noqa: BLE001 - a self-test must report, not die
        lines.append(f"  [FAIL] self-test crashed: {exc!r}")
        failures += 1

    return failures == 0, lines
