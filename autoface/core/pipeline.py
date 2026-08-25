"""Turn scanned drawings into the export plan the preview table shows.

Pure logic: every decision the spec makes before anything touches disk lives
here, so it is testable without Inventor. Filesystem lookups are injected
(``path_exists``) for the same reason.
"""

from __future__ import annotations

import os
from pathlib import PureWindowsPath
from typing import Callable, Iterable

from .models import (
    Classification,
    ModelKind,
    Plan,
    PlanRow,
    ScannedDrawing,
)
from .naming import clean_item, parse_drawing_name, relative_target
from .thickness import ThicknessTable, resolve_thickness


def _mismatch_flag(model_inches: float, description_inches: float) -> str:
    return (
        f'thickness cross-check: description says {description_inches:.4f}", '
        f'model parameter says {model_inches:.4f}" — used the description'
    )


def build_plan(
    drawings: Iterable[ScannedDrawing],
    output_root: str,
    table: ThicknessTable,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> Plan:
    """One PlanRow per parts-list row across all drawings, in scan order.

    ``output_root`` may be empty (no folder chosen yet): targets stay
    root-relative and the on-disk collision check is skipped; the intra-run
    duplicate check still runs. The export run refuses to start without a
    root, so nothing can be written from such a plan.
    """
    rows: list[PlanRow] = []
    notes: list[str] = []
    claimed: set[str] = set()  # relative targets, casefolded (NTFS-insensitive)

    for drawing in drawings:
        label = PureWindowsPath(drawing.path).stem
        if drawing.note:
            notes.append(f"{label}: {drawing.note}")
        name = parse_drawing_name(drawing.path)

        for scanned in drawing.rows:
            flags = [scanned.note] if scanned.note else []
            resolution = None
            if scanned.model_kind is ModelKind.SHEET_METAL:
                resolution = resolve_thickness(
                    scanned.thickness_cm, scanned.description
                )
                if resolution.mismatch:
                    flags.append(
                        _mismatch_flag(
                            resolution.model_inches, resolution.description_inches
                        )
                    )
            thickness_display = resolution.display if resolution else "—"

            def row(
                classification: Classification,
                target_relative: str = "",
                target_path: str = "",
            ) -> PlanRow:
                return PlanRow(
                    drawing_path=drawing.path,
                    drawing_label=label,
                    item=scanned.item,
                    part_number=scanned.part_number,
                    description=scanned.description,
                    thickness_display=thickness_display,
                    classification=classification,
                    target_relative=target_relative,
                    target_path=target_path,
                    model_path=scanned.model_path,
                    has_flat_pattern=scanned.has_flat_pattern,
                    flags=tuple(flags),
                )

            if name is None:
                rows.append(row(Classification.SKIP_UNPARSEABLE_DRAWING))
                continue
            if scanned.model_kind is ModelKind.NO_MODEL:
                rows.append(row(Classification.SKIP_NO_MODEL))
                continue
            if scanned.model_kind is ModelKind.SUB_ASSEMBLY:
                # Future versions descend into these; this is the one case to
                # replace when they do.
                rows.append(row(Classification.SKIP_SUB_ASSEMBLY))
                continue
            if scanned.model_kind is ModelKind.NOT_SHEET_METAL:
                rows.append(row(Classification.SKIP_NOT_SHEET_METAL))
                continue

            # Sheet metal from here on.
            thickness_label = (
                table.label_for(resolution.effective_sixteenths)
                if resolution.effective_sixteenths is not None
                else None
            )
            if thickness_label is None:
                rows.append(row(Classification.SKIP_INVALID_THICKNESS))
                continue

            item = clean_item(scanned.item)
            if item is None:
                flags.append("item number is empty or not usable in a filename")
                rows.append(row(Classification.SKIP_BAD_ITEM))
                continue

            relative = relative_target(name, thickness_label, item)
            absolute = (
                str(PureWindowsPath(output_root) / relative) if output_root else ""
            )

            if absolute and path_exists(absolute):
                flags.append(f"target already exists on disk: {relative}")
                rows.append(
                    row(Classification.SKIP_NAME_COLLISION, relative, absolute)
                )
                continue
            if relative.casefold() in claimed:
                flags.append(f"another row in this run already exports {relative}")
                rows.append(
                    row(Classification.SKIP_NAME_COLLISION, relative, absolute)
                )
                continue

            claimed.add(relative.casefold())
            rows.append(row(Classification.EXPORT, relative, absolute))

    return Plan(rows=tuple(rows), drawing_notes=tuple(notes))
