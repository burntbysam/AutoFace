"""End-of-run summary: counts, the flag list, and the saveable .txt log."""

from __future__ import annotations

from .models import Classification, Plan, RunResult


def flag_lines(plan: Plan, result: RunResult | None = None) -> list[str]:
    """One line per skipped/failed/flagged item, for the summary dialog."""
    lines: list[str] = list(plan.drawing_notes)
    reported: set[int] = set()

    if result is not None:
        for outcome in result.outcomes:
            if outcome.status != "exported" or outcome.row.flags:
                lines.append(outcome.line)
                reported.add(id(outcome.row))
        for note in result.notes:
            lines.append(note)

    for row in plan.rows:
        if id(row) in reported:
            continue
        if row.classification is Classification.EXPORT and not row.flags:
            continue
        prefix = f"{row.drawing_label} item {row.item or '?'}"
        if row.part_number:
            prefix += f" ({row.part_number})"
        detail = row.classification.label
        if row.flags:
            detail += " — " + "; ".join(row.flags)
        lines.append(f"{prefix}: {detail}")
    return lines


def summarize_run(
    plan: Plan, result: RunResult, output_root: str, timestamp: str
) -> str:
    """The saveable log: header, counts, then every flag line."""
    lines = [
        f"AutoFace run {timestamp}",
        f"Output folder: {output_root or '(not set)'}",
        "",
        f"Exported: {result.exported}",
        f"Skipped:  {result.skipped + _preview_skips(plan)}",
        f"Failed:   {result.failed}",
    ]
    flags = flag_lines(plan, result)
    if flags:
        lines += ["", "Flags:"]
        lines += [f"  {flag}" for flag in flags]
    else:
        lines += ["", "No flags."]
    return "\n".join(lines) + "\n"


def _preview_skips(plan: Plan) -> int:
    """Rows the preview already ruled out; they never reach the export run."""
    return sum(
        1 for row in plan.rows if row.classification is not Classification.EXPORT
    )
