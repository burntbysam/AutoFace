"""The export run: one plan row at a time, read-only toward the models.

THE CONTRACT (the one behavior that can damage models if gotten wrong):

- No document is ever saved. There is no ``Save``/``SaveAs``/``Update`` call
  anywhere in this package.
- A part already open in the session (the normal case — the drawing references
  it) is used in memory and never closed. If AutoFace had to create its flat
  pattern, the flat pattern is deleted again after the export so a later
  user-initiated Save All cannot persist anything AutoFace did.
- Only documents AutoFace itself opened are closed, always with
  ``Close(SkipSave:=True)``.
- An existing target file is never overwritten: ``WriteDataToFile`` would
  silently replace it, so existence is re-checked immediately before writing.

The pipeline is strictly sequential: one Inventor session, stateful documents.
"""

from __future__ import annotations

import os
from typing import Callable

from ..config import Config
from ..core.models import Plan, PlanRow, RowOutcome, RunResult
from . import com


def run_export(
    app,
    plan: Plan,
    config: Config,
    on_progress: Callable[[int, int], None] | None = None,
    on_row: Callable[[RowOutcome], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> RunResult:
    """Export every EXPORT row of the plan. One row failing never aborts."""
    result = RunResult()
    rows = plan.exportable
    total = len(rows)

    with com.silent_operation(app):
        for index, row in enumerate(rows):
            if should_cancel is not None and should_cancel():
                result.notes.append(
                    f"cancelled after {index} of {total} exports; the remaining "
                    "rows were not attempted"
                )
                break
            try:
                outcome = export_row(app, row, config.dwg_format)
            except Exception as exc:  # noqa: BLE001 - log and continue, always
                outcome = RowOutcome(
                    row=row, status="failed", detail=com.error_text(exc)
                )
            result.outcomes.append(outcome)
            if on_row is not None:
                on_row(outcome)
            if on_progress is not None:
                on_progress(index + 1, total)
    return result


def _find_document(app, model_path: str):
    """The part's in-memory document, opening it invisibly only as a last resort.

    Returns ``(document, opened_by_us)``. Everything the drawing references is
    already loaded, so the open path is rare (e.g. the user closed the model
    between scan and export).
    """
    documents = app.Documents
    wanted = model_path.casefold()
    try:
        document = documents.ItemByName(model_path)
        if document is not None:
            return document, False
    except Exception:  # noqa: BLE001 - hidden legacy member; fall through
        pass
    try:
        for index in range(1, int(documents.Count) + 1):
            document = documents.Item(index)
            if str(document.FullFileName or "").casefold() == wanted:
                return document, False
    except Exception:  # noqa: BLE001 - fall through to an explicit open
        pass
    document = documents.Open(model_path, False)  # invisible, AutoFace's to close
    return document, True


def _release(document, opened_by_us: bool) -> list[str]:
    """Close only what AutoFace opened; never save anything."""
    notes: list[str] = []
    if not opened_by_us:
        return notes
    try:
        document.ReleaseReference()
    except Exception:  # noqa: BLE001 - best effort
        pass
    try:
        document.Close(True)  # SkipSave: discard, leave the file untouched
    except Exception as exc:  # noqa: BLE001
        notes.append(f"could not close the part document: {com.error_text(exc)}")
    return notes


def _restore_flat_pattern_state(sheet_metal, created: bool) -> list[str]:
    """Undo a flat pattern AutoFace created, so the model is left as found."""
    notes: list[str] = []
    if not created:
        return notes
    try:
        sheet_metal.FlatPattern.Delete()
    except Exception as exc:  # noqa: BLE001
        notes.append(
            "the flat pattern AutoFace created could not be removed "
            f"({com.error_text(exc)}); do not save this part if you want it "
            "unchanged"
        )
        return notes
    try:
        # Best effort: clear the dirty flag so a later Save All has nothing of
        # ours to write. Harmless if the property refuses.
        sheet_metal.Document.Dirty = False
    except Exception:  # noqa: BLE001
        pass
    return notes


def export_row(app, row: PlanRow, dwg_format: str) -> RowOutcome:
    """Export one part's flat pattern to its target .dwg."""
    target = row.target_path
    if not target:
        return RowOutcome(
            row=row, status="failed", detail="no output folder was chosen"
        )
    if not row.model_path:
        return RowOutcome(row=row, status="failed", detail="no model path")

    # The preview checked too, but the disk may have changed since: never
    # overwrite, full stop.
    if os.path.exists(target):
        return RowOutcome(
            row=row,
            status="skipped",
            detail=f"target already exists — not overwritten: {row.target_relative}",
        )

    try:
        document, opened_by_us = com.with_busy_retry(
            lambda: _find_document(app, row.model_path)
        )
    except Exception as exc:  # noqa: BLE001 - a missing model is a flag
        return RowOutcome(
            row=row,
            status="failed",
            detail=f"could not open the model document: {com.error_text(exc)}",
        )
    notes: list[str] = []
    state = _FlatPatternState()
    try:
        status, detail = _export_resolved(document, dwg_format, target, state)
    except Exception as exc:  # noqa: BLE001 - one row must never abort the run
        status, detail = "failed", com.error_text(exc)
    finally:
        # Runs on every path above (success, failure, or crash), so the model
        # is always left exactly as it was found.
        if state.sheet_metal is not None:
            notes.extend(
                _restore_flat_pattern_state(state.sheet_metal, state.created)
            )
        notes.extend(_release(document, opened_by_us))

    if notes:
        detail = "; ".join(filter(None, [detail, *notes]))
    return RowOutcome(row=row, status=status, detail=detail)


class _FlatPatternState:
    """What must be undone afterwards, visible even if the body crashes."""

    def __init__(self) -> None:
        self.sheet_metal = None
        self.created = False


def _export_resolved(
    document, dwg_format: str, target: str, state: _FlatPatternState
) -> tuple[str, str]:
    """The export body for one resolved part document."""
    if str(document.SubType).upper() != com.SHEET_METAL_SUBTYPE:
        return "failed", "model is no longer a sheet metal part"
    state.sheet_metal = sheet_metal = document.ComponentDefinition

    if not bool(sheet_metal.HasFlatPattern):
        try:
            sheet_metal.Unfold()
            state.created = True
        except Exception as exc:  # noqa: BLE001 - the spec's unfold flag
            return (
                "failed",
                f"could not create a flat pattern: {com.error_text(exc)}",
            )
        try:
            sheet_metal.FlatPattern.ExitEdit()
        except Exception:  # noqa: BLE001 - some versions need no exit
            pass

    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        sheet_metal.DataIO.WriteDataToFile(dwg_format, target)
    except Exception as exc:  # noqa: BLE001
        return "failed", f"DWG export failed: {com.error_text(exc)}"

    if not os.path.exists(target):
        return "failed", "Inventor reported success but no file was written"
    return "exported", ""
