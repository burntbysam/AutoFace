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
from .thickness import (
    ThicknessTable,
    looks_like_sheet_description,
    resolve_thickness,
)


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
            # The BOM description is the shop's own word on what the row is.
            # A skip on a row that never claimed to be sheet (assemblies,
            # channel, hardware…) is entirely expected and stays out of the
            # end-of-run summary; a skip on a row that DOES claim sheet is
            # news. Rows with scan notes always stay loud.
            expected_skip = (
                not looks_like_sheet_description(scanned.description)
                and not flags
            )
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
                silent: bool = False,
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
                    silent=silent,
                )

            if name is None:
                # The drawing-level problem still surfaces through this
                # drawing's sheet-claiming rows, which stay loud.
                rows.append(
                    row(Classification.SKIP_UNPARSEABLE_DRAWING, silent=expected_skip)
                )
                continue
            if scanned.model_kind is ModelKind.NO_MODEL:
                rows.append(row(Classification.SKIP_NO_MODEL, silent=expected_skip))
                continue
            if scanned.model_kind is ModelKind.SUB_ASSEMBLY:
                # Future versions descend into these; this is the one case to
                # replace when they do.
                rows.append(
                    row(Classification.SKIP_SUB_ASSEMBLY, silent=expected_skip)
                )
                continue
            if scanned.model_kind is ModelKind.NOT_SHEET_METAL:
                rows.append(
                    row(Classification.SKIP_NOT_SHEET_METAL, silent=expected_skip)
                )
                continue

            # Sheet metal document from here on — but the BOM description is
            # the authority on what the part IS. A tube or channel modeled as
            # a sheet metal document (folded tube with a 1/8" wall, say) must
            # not export as if it were 1/8" sheet.
            description_text = scanned.description.strip()
            if description_text and not looks_like_sheet_description(
                description_text
            ):
                rows.append(
                    row(Classification.SKIP_NOT_SHEET_PER_BOM, silent=expected_skip)
                )
                continue
            if not description_text:
                # Nothing to judge against: export on the model type alone,
                # but say so — a blank description must never silently drop
                # a real part, and never silently pass one either.
                flags.append(
                    "no BOM description to cross-check; exported on the "
                    "model's sheet metal type alone"
                )

            thickness_label = (
                table.label_for(resolution.effective_sixteenths)
                if resolution.effective_sixteenths is not None
                else None
            )
            if thickness_label is None:
                # e.g. a channel or extrusion modeled as a sheet metal doc:
                # its description says what it really is, so the silent rule
                # applies here too.
                rows.append(
                    row(Classification.SKIP_INVALID_THICKNESS, silent=expected_skip)
                )
                continue

            item = clean_item(scanned.item)
            if item is None:
                flags.append("item number is empty or not usable in a filename")
                rows.append(row(Classification.SKIP_BAD_ITEM))
                continue

            relative = relative_target(name, thickness_label, item)
            # The relative form is always rendered Windows-style (it is what
            # the preview shows); the absolute path is native so the export
            # can create and check it directly.
            absolute = (
                os.path.join(output_root, *relative.split("\\"))
                if output_root
                else ""
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
