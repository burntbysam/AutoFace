"""Read-only checks against the live Inventor session.

Research pinned down the API on paper; these probes confirm it against the
user's actual Inventor version and a real drawing before a batch is trusted.
Run ``AutoFace.exe --probe all`` with Inventor open on a known drawing (e.g.
8640-01101-I) and paste AutoFace-probe-results.txt back for review.

Every probe is read-only except:
- ``export`` writes one .dwg into the Windows temp folder;
- ``neversave`` creates a flat pattern on ONE part that has none, exports it
  to temp, deletes the flat pattern again, and proves the .ipt on disk did not
  change (hash before == hash after). It never saves anything.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path, PureWindowsPath

from ..config import load_config
from ..core.thickness import cm_to_inches, format_sixteenths, to_sixteenths
from ..core.thickness import ThicknessTable
from ..version import describe
from . import com
from .scan import find_columns, resolve_row, scan_session


def run_probes(names: tuple[str, ...]) -> str:
    lines: list[str] = [f"{describe()} — probe report", ""]
    try:
        com.initialize_thread()
        app = com.attach()
    except com.InventorUnavailable as exc:
        return "\n".join(lines + [f"FAIL: {exc}"]) + "\n"
    except com.InventorNotRunning as exc:
        return "\n".join(lines + [f"FAIL: {exc}"]) + "\n"

    probes = {
        "session": probe_session,
        "partslist": probe_partslist,
        "thickness": probe_thickness,
        "export": probe_export,
        "neversave": probe_neversave,
    }
    for name in names:
        lines.append(f"=== probe: {name} ===")
        try:
            lines.extend(probes[name](app))
        except Exception as exc:  # noqa: BLE001 - a probe reports, never dies
            lines.append(f"FAIL: {com.error_text(exc)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _temp_dir() -> Path:
    directory = Path(tempfile.gettempdir()) / "AutoFace-probe"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sheet_metal_documents(app):
    """Unique sheet metal part documents referenced by the open drawings."""
    seen: set[str] = set()
    found = []
    for drawing in scan_session(app):
        for row in drawing.rows:
            key = row.model_path.casefold()
            if row.model_path and key not in seen and row.thickness_cm is not None:
                seen.add(key)
                if row.model_kind.name == "SHEET_METAL":
                    found.append(row)
    return found


def probe_session(app) -> list[str]:
    """Attach + enumeration; asserts the hard-coded enum values live."""
    lines = []
    documents = app.Documents
    visible = documents.VisibleDocuments
    lines.append(f"Documents.Count = {documents.Count} (includes referenced models)")
    lines.append(f"VisibleDocuments.Count = {visible.Count} (user-open tabs)")
    for index in range(1, int(visible.Count) + 1):
        document = visible.Item(index)
        try:
            document_type = int(document.DocumentType)
            try:
                subtype = str(document.SubType)
            except Exception:  # noqa: BLE001
                subtype = "(no SubType)"
            path = str(document.FullFileName or "(unsaved)")
            marker = ""
            if document_type == com.kDrawingDocumentObject:
                marker = "  <- drawing (12292)"
                if not path.lower().endswith(".idw"):
                    marker += " but not .idw — would be ignored"
            lines.append(f"  [{index}] type={document_type} subtype={subtype}")
            lines.append(f"      {path}{marker}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"  [{index}] unreadable: {com.error_text(exc)}")
    lines.append(
        "EXPECT: every open .idw tab listed with type=12292; parts 12290; "
        "assemblies 12291."
    )
    return lines


def probe_partslist(app) -> list[str]:
    """Columns, as-printed rows, and model resolution for one open drawing."""
    lines = []
    drawings = scan_session(app)
    if not drawings:
        return ["FAIL: no open .idw drawings found"]

    document = None
    visible = app.Documents.VisibleDocuments
    for index in range(1, int(visible.Count) + 1):
        candidate = visible.Item(index)
        if str(candidate.FullFileName or "").casefold() == drawings[0].path.casefold():
            document = candidate
            break
    if document is None:
        return ["FAIL: could not re-find the first drawing"]

    lines.append(f"Drawing: {drawings[0].path}")
    sheets = document.Sheets
    for sheet_index in range(1, int(sheets.Count) + 1):
        sheet = sheets.Item(sheet_index)
        parts_lists = sheet.PartsLists
        lines.append(f"Sheet {sheet_index}: {parts_lists.Count} parts list(s)")
        for list_index in range(1, int(parts_lists.Count) + 1):
            parts_list = parts_lists.Item(list_index)
            columns = parts_list.PartsListColumns
            lines.append(f"  Parts list {list_index} columns:")
            for column_index in range(1, int(columns.Count) + 1):
                column = columns.Item(column_index)
                try:
                    property_type = int(column.PropertyType)
                except Exception:  # noqa: BLE001
                    property_type = -1
                extra = ""
                if property_type == com.kFileProperty:
                    try:
                        set_id, property_id = column.GetFilePropertyId()
                        extra = f" filePropertyId=({set_id}, {property_id})"
                    except Exception as exc:  # noqa: BLE001
                        extra = f" GetFilePropertyId failed: {com.error_text(exc)}"
                lines.append(
                    f"    [{column_index}] '{column.Title}' "
                    f"propertyType={property_type}{extra}"
                )
            mapped = find_columns(parts_list)
            lines.append(
                f"  Mapped columns: item={mapped.item} "
                f"partNumber={mapped.part_number} description={mapped.description}"
            )
            rows = parts_list.PartsListRows
            for row_index in range(1, int(rows.Count) + 1):
                row = rows.Item(row_index)
                try:
                    visible_flag = bool(row.Visible)
                except Exception:  # noqa: BLE001
                    visible_flag = True
                item = (
                    str(row.Item(mapped.item).Value).strip() if mapped.item else "?"
                )
                kind, model_path, thickness_cm, has_fp, note = resolve_row(row)
                thickness = (
                    f"{cm_to_inches(thickness_cm):.4f} in"
                    if thickness_cm is not None
                    else "-"
                )
                lines.append(
                    f"    row {row_index}: item='{item}' visible={visible_flag} "
                    f"kind={kind.name} thickness={thickness} flatPattern={has_fp}"
                )
                lines.append(f"      model: {model_path or '(none)'}")
                if note:
                    lines.append(f"      note: {note}")
    lines.append(
        "EXPECT: item numbers exactly as the printed table shows them "
        "(renumber a row in Edit Parts List and re-run to confirm overrides "
        "are honoured)."
    )
    return lines


def probe_thickness(app) -> list[str]:
    """Thickness parameter -> inches -> folder label, per sheet metal part."""
    lines = []
    config = load_config()
    table = ThicknessTable(config.thickness_table)
    parts = _sheet_metal_documents(app)
    if not parts:
        return ["FAIL: no sheet metal parts found behind the open drawings"]
    for row in parts:
        inches = cm_to_inches(row.thickness_cm)
        sixteenths = to_sixteenths(inches)
        label = table.label_for(sixteenths) or "NOT IN TABLE -> would skip"
        lines.append(f"  {PureWindowsPath(row.model_path).name}")
        lines.append(
            f"    Thickness.Value={row.thickness_cm:.6f} cm -> {inches:.4f} in "
            f"-> {format_sixteenths(sixteenths)} -> folder '{label}'"
        )
    lines.append(
        "EXPECT: the cm value equals the model's Thickness parameter and the "
        "folder label matches the config table."
    )
    return lines


def probe_export(app) -> list[str]:
    """One DataIO DWG export with the configured (default: bare) format string."""
    lines = []
    config = load_config()
    parts = _sheet_metal_documents(app)
    candidates = [row for row in parts if row.has_flat_pattern] or parts
    if not candidates:
        return ["FAIL: no sheet metal part available to export"]
    row = candidates[0]

    document, opened = com.with_busy_retry(
        lambda: _find_document_for_probe(app, row.model_path)
    )
    try:
        sheet_metal = document.ComponentDefinition
        if not bool(sheet_metal.HasFlatPattern):
            return [
                f"SKIP: {PureWindowsPath(row.model_path).name} has no flat "
                "pattern; run the neversave probe instead"
            ]
        target = _temp_dir() / (PureWindowsPath(row.model_path).stem + ".dwg")
        target.unlink(missing_ok=True)
        lines.append(f"  format string: {config.dwg_format!r}")
        lines.append(f"  target: {target}")
        sheet_metal.DataIO.WriteDataToFile(config.dwg_format, str(target))
        if target.exists():
            lines.append(f"  OK: wrote {target.stat().st_size} bytes")
        else:
            lines.append("  FAIL: call returned but no file was written")
        lines.append(
            "EXPECT: a valid DWG. If the bare format string failed, set "
            '"dwg_format": "FLAT PATTERN DWG?AcadVersion=2018" in config.json '
            "and re-run."
        )
    finally:
        _close_probe_document(document, opened)
    return lines


def probe_neversave(app) -> list[str]:
    """Create->export->delete a flat pattern; prove the .ipt never changed."""
    lines = []
    config = load_config()
    parts = [row for row in _sheet_metal_documents(app) if not row.has_flat_pattern]
    if not parts:
        return [
            "SKIP: every sheet metal part behind the open drawings already has "
            "a flat pattern. Open a drawing referencing one without, then "
            "re-run."
        ]
    row = parts[0]
    model = Path(row.model_path)
    lines.append(f"  part: {model.name}")
    before = _sha256(model)
    lines.append(f"  file hash before: {before}")

    document, opened = com.with_busy_retry(
        lambda: _find_document_for_probe(app, row.model_path)
    )
    try:
        sheet_metal = document.ComponentDefinition
        lines.append(f"  Dirty before: {_dirty_of(document)}")
        sheet_metal.Unfold()
        try:
            sheet_metal.FlatPattern.ExitEdit()
        except Exception:  # noqa: BLE001
            pass
        lines.append("  created a flat pattern (in memory only)")

        target = _temp_dir() / (model.stem + "-neversave.dwg")
        target.unlink(missing_ok=True)
        sheet_metal.DataIO.WriteDataToFile(config.dwg_format, str(target))
        lines.append(
            f"  exported {target.stat().st_size if target.exists() else 0} bytes"
        )

        sheet_metal.FlatPattern.Delete()
        lines.append("  deleted the created flat pattern")
        try:
            document.Dirty = False
            lines.append("  cleared the Dirty flag")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"  could not clear Dirty ({com.error_text(exc)})")
        lines.append(f"  Dirty after: {_dirty_of(document)}")
    finally:
        _close_probe_document(document, opened)

    after = _sha256(model)
    lines.append(f"  file hash after:  {after}")
    if before == after:
        lines.append("  OK: the .ipt on disk is byte-identical")
    else:
        lines.append(
            "  FAIL: THE FILE CHANGED ON DISK — do not use AutoFace until this "
            "is understood"
        )
    lines.append(
        "EXPECT: identical hashes, and Dirty=False (or a note) at the end. "
        "Afterwards close the part in Inventor WITHOUT saving if it shows as "
        "modified."
    )
    return lines


def _find_document_for_probe(app, model_path: str):
    documents = app.Documents
    wanted = model_path.casefold()
    for index in range(1, int(documents.Count) + 1):
        document = documents.Item(index)
        try:
            if str(document.FullFileName or "").casefold() == wanted:
                return document, False
        except Exception:  # noqa: BLE001
            continue
    return documents.Open(model_path, False), True


def _close_probe_document(document, opened_by_us: bool) -> None:
    if not opened_by_us:
        return
    try:
        document.ReleaseReference()
    except Exception:  # noqa: BLE001
        pass
    try:
        document.Close(True)
    except Exception:  # noqa: BLE001
        pass


def _dirty_of(document) -> str:
    try:
        return str(bool(document.Dirty))
    except Exception as exc:  # noqa: BLE001
        return f"(unreadable: {com.error_text(exc)})"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
