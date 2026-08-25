"""Read the running session into plain data: drawings, rows, resolved models.

Read-only by construction — nothing in this module calls anything that could
modify a document. Item numbers, part numbers and descriptions come from the
placed parts list cells (``row.Item(col).Value``), which return the text as
printed on the sheet including user renumbering and static overrides. The
assembly's internal BOM is deliberately never consulted for item numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.models import ModelKind, ScannedDrawing, ScannedRow
from . import com


def scan_session(app) -> list[ScannedDrawing]:
    """Every user-open .idw drawing, with its parts-list rows resolved.

    ``VisibleDocuments`` is the set of documents open in visible windows —
    what the user sees as open tabs. ``Documents`` would also contain every
    invisibly-loaded referenced model, which is not the work queue.
    """
    drawings: list[ScannedDrawing] = []
    visible = app.Documents.VisibleDocuments
    for index in range(1, int(visible.Count) + 1):
        document = visible.Item(index)
        try:
            if int(document.DocumentType) != com.kDrawingDocumentObject:
                continue
            path = str(document.FullFileName or "")
            # kDrawingDocumentObject also matches Inventor-format .dwg
            # drawings; the spec's queue is .idw only.
            if not path.lower().endswith(".idw"):
                continue
        except Exception:  # noqa: BLE001 - an unreadable document is not queue
            continue
        drawings.append(scan_drawing(document))
    return drawings


def scan_drawing(document) -> ScannedDrawing:
    """All placed parts lists on all sheets of one drawing."""
    path = str(document.FullFileName or "")
    rows: list[ScannedRow] = []
    notes: list[str] = []
    lists_found = 0

    try:
        sheets = document.Sheets
        for sheet_index in range(1, int(sheets.Count) + 1):
            sheet = sheets.Item(sheet_index)
            parts_lists = sheet.PartsLists
            for list_index in range(1, int(parts_lists.Count) + 1):
                lists_found += 1
                scanned, note = scan_parts_list(parts_lists.Item(list_index))
                rows.extend(scanned)
                if note:
                    notes.append(note)
    except Exception as exc:  # noqa: BLE001 - a broken drawing must not abort
        notes.append(f"could not read parts lists: {com.error_text(exc)}")

    if lists_found == 0 and not notes:
        notes.append("no parts list found on any sheet")
    return ScannedDrawing(path=path, rows=tuple(rows), note="; ".join(notes))


@dataclass
class ColumnMap:
    """1-based parts-list column indexes; None when a column is absent."""

    item: int | None = None
    part_number: int | None = None
    description: int | None = None


def find_columns(parts_list) -> ColumnMap:
    """Locate ITEM / PART NUMBER / DESCRIPTION.

    Primary identification is PropertyType (+ GetFilePropertyId for the two
    iProperty columns) because column titles are user-editable and localized;
    the title match is the fallback for styles where the id lookup fails.
    """
    columns = parts_list.PartsListColumns
    result = ColumnMap()
    for index in range(1, int(columns.Count) + 1):
        column = columns.Item(index)
        property_type = None
        try:
            property_type = int(column.PropertyType)
        except Exception:  # noqa: BLE001 - fall through to the title match
            pass

        if property_type == com.kItemPartsListProperty and result.item is None:
            result.item = index
            continue
        if property_type == com.kFileProperty:
            try:
                # Two [out] parameters; late-bound pywin32 returns them as a
                # tuple: (property set id, property id).
                set_id, property_id = column.GetFilePropertyId()
                if str(set_id).upper() == com.DESIGN_TRACKING_PROPERTIES:
                    if property_id == com.PROPERTY_ID_PART_NUMBER:
                        result.part_number = result.part_number or index
                        continue
                    if property_id == com.PROPERTY_ID_DESCRIPTION:
                        result.description = result.description or index
                        continue
            except Exception:  # noqa: BLE001 - fall through to the title match
                pass

        try:
            title = str(column.Title or "").strip().upper()
        except Exception:  # noqa: BLE001
            title = ""
        if title == "ITEM" and result.item is None:
            result.item = index
        elif title == "PART NUMBER" and result.part_number is None:
            result.part_number = index
        elif title == "DESCRIPTION" and result.description is None:
            result.description = index
    return result


def _cell_text(row, column_index: int | None) -> str:
    if column_index is None:
        return ""
    try:
        return str(row.Item(column_index).Value or "").strip()
    except Exception:  # noqa: BLE001 - an unreadable cell reads as blank
        return ""


def scan_parts_list(parts_list) -> tuple[list[ScannedRow], str]:
    """Visible rows of one placed parts list, in printed order."""
    columns = find_columns(parts_list)
    if columns.item is None:
        return [], "parts list has no ITEM column; its rows were skipped"

    scanned: list[ScannedRow] = []
    rows = parts_list.PartsListRows
    for index in range(1, int(rows.Count) + 1):
        row = rows.Item(index)
        try:
            if not bool(row.Visible):
                continue  # hidden rows are not printed, so they are not work
        except Exception:  # noqa: BLE001 - visibility unknown: keep the row
            pass
        item = _cell_text(row, columns.item)
        part_number = _cell_text(row, columns.part_number)
        description = _cell_text(row, columns.description)
        kind, model_path, thickness_cm, has_flat_pattern, note = resolve_row(row)
        scanned.append(
            ScannedRow(
                item=item,
                part_number=part_number,
                description=description,
                model_kind=kind,
                model_path=model_path,
                thickness_cm=thickness_cm,
                has_flat_pattern=has_flat_pattern,
                note=note,
            )
        )
    return scanned, ""


def resolve_row(row):
    """Follow one row to its model document and classify it.

    Chain: ReferencedRows → DrawingBOMRow.BOMRow → ComponentDefinitions(1)
    → Document. Custom and virtual rows have no reachable file — they resolve
    to NO_MODEL with the reason in the note. A merged row (several referenced
    rows) is classified by its first model, which is what the printed item
    number stands for.
    """
    try:
        references = row.ReferencedRows
        if int(references.Count) == 0:
            return (
                ModelKind.NO_MODEL,
                "",
                None,
                None,
                "custom or virtual row (no model reference)",
            )
        component_definition = (
            references.Item(1).BOMRow.ComponentDefinitions.Item(1)
        )
        document = component_definition.Document
        document_type = int(document.DocumentType)
        model_path = str(document.FullFileName or "")

        if document_type == com.kAssemblyDocumentObject:
            return ModelKind.SUB_ASSEMBLY, model_path, None, None, ""
        if document_type != com.kPartDocumentObject:
            return (
                ModelKind.NOT_SHEET_METAL,
                model_path,
                None,
                None,
                f"unexpected document type {document_type}",
            )
        if str(document.SubType).upper() != com.SHEET_METAL_SUBTYPE:
            return ModelKind.NOT_SHEET_METAL, model_path, None, None, ""

        thickness_cm = None
        has_flat_pattern = None
        note = ""
        try:
            sheet_metal = document.ComponentDefinition
            thickness_cm = float(sheet_metal.Thickness.Value)
            has_flat_pattern = bool(sheet_metal.HasFlatPattern)
        except Exception as exc:  # noqa: BLE001 - thickness read is separable
            note = f"could not read sheet metal data: {com.error_text(exc)}"
        return ModelKind.SHEET_METAL, model_path, thickness_cm, has_flat_pattern, note
    except Exception as exc:  # noqa: BLE001 - an unresolvable row is a flag
        return (
            ModelKind.NO_MODEL,
            "",
            None,
            None,
            f"could not resolve model: {com.error_text(exc)}",
        )
