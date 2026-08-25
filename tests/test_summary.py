"""Summary and log rendering."""

from autoface.core.models import (
    Classification,
    ModelKind,
    PlanRow,
    RowOutcome,
    RunResult,
    ScannedDrawing,
    ScannedRow,
)
from autoface.core.pipeline import build_plan
from autoface.core.summary import flag_lines, summarize_run
from autoface.core.thickness import ThicknessTable

INCH = 2.54
TABLE = ThicknessTable({"0.125": "125", "0.1875": "1875"})


def make_plan():
    drawing = ScannedDrawing(
        path="C:\\dwg\\8640-01101-I.idw",
        rows=(
            ScannedRow(
                "1",
                "PN-1",
                "SHEET,AL,SMOOTH,.125,10X10",
                ModelKind.SHEET_METAL,
                model_path="C:\\m\\1.ipt",
                thickness_cm=0.125 * INCH,
                has_flat_pattern=True,
            ),
            ScannedRow("2", "PN-2", "BRACKET", ModelKind.NOT_SHEET_METAL),
        ),
        note="second sheet has no parts list",
    )
    return build_plan([drawing], "C:\\out", TABLE, path_exists=lambda p: False)


def test_flag_lines_cover_skips_and_notes():
    plan = make_plan()
    lines = flag_lines(plan)
    assert "8640-01101-I: second sheet has no parts list" in lines
    assert any("Skip: not sheet metal" in line for line in lines)
    # The clean export row does not appear.
    assert not any("item 1 " in line and "PN-1" in line for line in lines)


def test_run_outcomes_replace_preview_lines_for_run_rows():
    plan = make_plan()
    export_row = plan.exportable[0]
    result = RunResult(
        outcomes=[RowOutcome(row=export_row, status="failed", detail="Unfold failed")]
    )
    lines = flag_lines(plan, result)
    assert any("Unfold failed" in line for line in lines)


def test_row_flags_survive_into_the_summary_even_for_exported_rows():
    # The thickness cross-check values must reach the log, not just the
    # preview tooltip.
    drawing = ScannedDrawing(
        path="C:\\dwg\\8640-01101-I.idw",
        rows=(
            ScannedRow(
                "1",
                "PN-1",
                "SHEET,AL,SMOOTH,.190,10X10",  # disagrees with the model
                ModelKind.SHEET_METAL,
                model_path="C:\\m\\1.ipt",
                thickness_cm=0.125 * INCH,
                has_flat_pattern=True,
            ),
        ),
    )
    plan = build_plan([drawing], "C:\\out", TABLE, path_exists=lambda p: False)
    row = plan.exportable[0]
    assert row.flags  # the cross-check flag is on the row
    result = RunResult(outcomes=[RowOutcome(row=row, status="exported")])
    lines = flag_lines(plan, result)
    assert any("cross-check" in line and "exported" in line for line in lines)


def test_total_skipped_counts_preview_and_run_skips():
    from autoface.core.summary import total_skipped

    plan = make_plan()  # one export row, one preview skip
    export_row = plan.exportable[0]
    result = RunResult(
        outcomes=[
            RowOutcome(row=export_row, status="skipped", detail="collision")
        ]
    )
    assert total_skipped(plan, result) == 2  # 1 preview + 1 run-time


def test_summarize_run_counts_and_header():
    plan = make_plan()
    export_row = plan.exportable[0]
    result = RunResult(
        outcomes=[RowOutcome(row=export_row, status="exported")],
    )
    text = summarize_run(plan, result, "C:\\out", "2026-08-25 14:12")
    assert "AutoFace run 2026-08-25 14:12" in text
    assert "Output folder: C:\\out" in text
    assert "Exported: 1" in text
    assert "Skipped:  1" in text  # the preview skip
    assert "Failed:   0" in text
    assert "Flags:" in text


def test_summarize_run_without_flags_says_so():
    row = PlanRow(
        drawing_path="C:\\dwg\\8640-01101-I.idw",
        drawing_label="8640-01101-I",
        item="1",
        part_number="PN-1",
        description="",
        thickness_display='0.125" (1/8")',
        classification=Classification.EXPORT,
        target_relative="RUN 11\\125\\8640-1101-1.dwg",
        target_path="C:\\out\\RUN 11\\125\\8640-1101-1.dwg",
    )
    from autoface.core.models import Plan

    plan = Plan(rows=(row,))
    result = RunResult(outcomes=[RowOutcome(row=row, status="exported")])
    text = summarize_run(plan, result, "C:\\out", "now")
    assert "No flags." in text
