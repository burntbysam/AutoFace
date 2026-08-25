"""The planner: classification, target paths, collisions, flags."""

import os

from autoface.core.models import (
    Classification,
    ModelKind,
    ScannedDrawing,
    ScannedRow,
)
from autoface.core.pipeline import build_plan
from autoface.core.thickness import ThicknessTable

INCH = 2.54
TABLE = ThicknessTable({"0.125": "125", "0.1875": "1875"})


def sheet_row(item, thickness_in=0.125, description=None, **kw):
    if description is None:
        description = f"SHEET,AL,SMOOTH,{thickness_in:.4f}".rstrip("0")
    return ScannedRow(
        item=item,
        part_number=kw.pop("part_number", f"PN-{item}"),
        description=description,
        model_kind=ModelKind.SHEET_METAL,
        model_path=kw.pop("model_path", f"C:\\models\\{item}.ipt"),
        thickness_cm=thickness_in * INCH,
        has_flat_pattern=kw.pop("has_flat_pattern", True),
        **kw,
    )


def drawing(rows, path="C:\\dwg\\8640-01101-I.idw", note=""):
    return ScannedDrawing(path=path, rows=tuple(rows), note=note)


def plan_of(rows, root="C:\\out", exists=lambda p: False, **kw):
    return build_plan([drawing(rows, **kw)], root, TABLE, path_exists=exists)


def test_export_row_gets_the_spec_target():
    plan = plan_of([sheet_row("1", 0.190, "SHEET,AL,SMOOTH,.190,60X133.13")])
    row = plan.rows[0]
    assert row.classification is Classification.EXPORT
    assert row.target_relative == "RUN 11\\1875\\8640-1101-1.dwg"
    # The absolute path is native to whatever OS runs the export.
    assert row.target_path == os.path.join(
        "C:\\out", "RUN 11", "1875", "8640-1101-1.dwg"
    )


def test_each_model_kind_maps_to_its_skip():
    plan = plan_of(
        [
            ScannedRow("2", "PN", "BRACKET", ModelKind.NOT_SHEET_METAL),
            ScannedRow("3", "PN", "SUB", ModelKind.SUB_ASSEMBLY),
            ScannedRow("4", "PN", "VIRT", ModelKind.NO_MODEL),
        ]
    )
    classifications = [row.classification for row in plan.rows]
    assert classifications == [
        Classification.SKIP_NOT_SHEET_METAL,
        Classification.SKIP_SUB_ASSEMBLY,
        Classification.SKIP_NO_MODEL,
    ]


def test_invalid_thickness_is_skipped():
    plan = plan_of([sheet_row("1", 0.25, "SHEET,AL,SMOOTH,.250,10X10")])
    assert plan.rows[0].classification is Classification.SKIP_INVALID_THICKNESS


def test_description_wins_and_is_flagged():
    plan = plan_of([sheet_row("1", 0.125, "SHEET,AL,SMOOTH,.190,60X133.13")])
    row = plan.rows[0]
    assert row.classification is Classification.EXPORT
    assert row.target_relative == "RUN 11\\1875\\8640-1101-1.dwg"  # 1875, not 125
    assert any("cross-check" in flag for flag in row.flags)


def test_collision_with_disk_is_skipped_never_overwritten():
    target = os.path.join("C:\\out", "RUN 11", "125", "8640-1101-5.dwg")
    plan = plan_of([sheet_row("5")], exists=lambda p: p == target)
    row = plan.rows[0]
    assert row.classification is Classification.SKIP_NAME_COLLISION
    assert row.target_path == target


def test_duplicate_targets_within_a_run_collide():
    plan = plan_of([sheet_row("5"), sheet_row("5", part_number="PN-other")])
    first, second = plan.rows
    assert first.classification is Classification.EXPORT
    assert second.classification is Classification.SKIP_NAME_COLLISION


def test_duplicate_check_is_case_insensitive_like_ntfs():
    rows = [sheet_row("5A")]
    plan = build_plan(
        [
            drawing(rows),
            drawing([sheet_row("5a")], path="C:\\dwg\\somewhere\\8640-01101-B.idw"),
        ],
        "C:\\out",
        TABLE,
        path_exists=lambda p: False,
    )
    assert plan.rows[0].classification is Classification.EXPORT
    assert plan.rows[1].classification is Classification.SKIP_NAME_COLLISION


def test_same_geometry_different_items_both_export():
    # Duplicate geometry under different item numbers is expected and fine.
    plan = plan_of(
        [
            sheet_row("5", model_path="C:\\models\\same.ipt"),
            sheet_row("6", model_path="C:\\models\\same.ipt"),
        ]
    )
    assert [row.classification for row in plan.rows] == [
        Classification.EXPORT,
        Classification.EXPORT,
    ]


def test_unparseable_drawing_name_skips_every_row():
    plan = plan_of(
        [sheet_row("1"), ScannedRow("2", "PN", "X", ModelKind.NOT_SHEET_METAL)],
        path="C:\\dwg\\WELDMENT DETAIL.idw",
    )
    assert all(
        row.classification is Classification.SKIP_UNPARSEABLE_DRAWING
        for row in plan.rows
    )


def test_bad_item_number_is_skipped():
    plan = plan_of([sheet_row("5/6")])
    assert plan.rows[0].classification is Classification.SKIP_BAD_ITEM


def test_no_output_root_plans_relative_targets_without_disk_checks():
    calls = []

    def exists(path):
        calls.append(path)
        return True  # would collide if it were ever consulted

    plan = plan_of([sheet_row("5")], root="", exists=exists)
    row = plan.rows[0]
    assert row.classification is Classification.EXPORT
    assert row.target_relative == "RUN 11\\125\\8640-1101-5.dwg"
    assert row.target_path == ""
    assert calls == []


def test_drawing_note_becomes_a_plan_note():
    plan = plan_of([], note="no parts list found on any sheet")
    assert plan.drawing_notes == ("8640-01101-I: no parts list found on any sheet",)


def test_scan_note_travels_into_row_flags():
    plan = plan_of(
        [ScannedRow("7", "PN", "X", ModelKind.NO_MODEL, note="resolve failed: boom")]
    )
    assert "resolve failed: boom" in plan.rows[0].flags


def test_exportable_property():
    plan = plan_of(
        [sheet_row("1"), ScannedRow("2", "PN", "X", ModelKind.SUB_ASSEMBLY)]
    )
    assert [row.item for row in plan.exportable] == ["1"]
