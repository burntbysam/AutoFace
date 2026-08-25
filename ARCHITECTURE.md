# AutoFace architecture plan

This is the Phase 0 / Phase 1 deliverable: the chosen stack, the Inventor API
map, packaging, and the update mechanism, with the reasoning. Implementation
follows this plan; anything the research could not verify without a live
Inventor session is listed under "Probes" and must be confirmed against a real
drawing before a batch run is trusted.

Reference target: the user runs **Autodesk Inventor Professional 2025
(2025.3, Build 356, 64-bit)**. Everything below was researched for Inventor
2020–2026 and probes verify against the live 2025.3 session.

## Decision: external app over iLogic

AutoFace is an **external Windows app** that attaches to the running Inventor
session over COM. iLogic is not used, not even as a thin execution layer.

Reasons, on the merits:

- Research confirmed working external-COM implementations for **every**
  operation this tool needs: session attach, open-document enumeration,
  placed-parts-list reads, sheet metal detection, thickness reads, flat
  pattern creation, flat-pattern DWG export, and close-without-save. No
  operation in this set is documented or credibly reported to work only (or
  meaningfully better) from inside Inventor.
- The two real advantages of in-process execution are performance on chatty
  call loops and immunity to COM busy-rejections. AutoFace's workload is a
  few hundred COM calls per run, not hundreds of thousands; the out-of-process
  penalty is seconds. Busy-rejection (`RPC_E_CALL_REJECTED` /
  `RPC_E_SERVERCALL_RETRYLATER`) is handled with a retry wrapper around every
  COM call, plus `Application.SilentOperation = True` for the duration of a
  run (restored after).
- iLogic would add real costs: rule files to deploy beside the exe (breaking
  the single-file requirement), a version-sensitive invocation boundary
  (Inventor 2025 — the user's release — moved to .NET 8 and broke early-bound
  external iLogic calls), and a poorer error channel (`RunExternalRule`
  returns only an integer status). Late-bound external COM is unaffected by
  the 2025 .NET 8 transition.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11 | Matches AutoBOM; one maintained toolchain for both tools |
| GUI | PySide6 (Qt Widgets) | AutoBOM's framework; sibling look comes free |
| Inventor access | pywin32, **late binding only** | `win32com.client.dynamic` never touches the makepy/gen_py cache, which is the #1 pywin32 failure mode inside PyInstaller one-file builds; late binding also makes one exe work across Inventor 2020–2026 |
| Packaging | PyInstaller one-file, `console=False`, `AutoFace.exe` | AutoBOM's packaging, spec-for-spec |
| Updates | AutoBOM's updater, ported | Fixed release tag + `latest.json` manifest + sha256 + self-test gate + rename-aside swap |
| CI | GitHub Actions `windows-latest` | Same workflow shape as AutoBOM's `build-windows.yml` |

Consequences of late binding: no `win32com.client.constants`, so enum values
are hard-coded in one constants module (values verified against the Inventor
type library and community interop dumps; a probe asserts them at runtime).

## Inventor API map

| Operation | API |
|---|---|
| Attach to running session | `pythoncom.GetActiveObject("Inventor.Application")` → QI `IDispatch` → `win32com.client.dynamic.Dispatch`; HRESULT `0x800401E3` (MK_E_UNAVAILABLE) = Inventor not running |
| Enumerate user-open drawings | `Application.Documents.VisibleDocuments`, filter `DocumentType == 12292` (kDrawingDocumentObject) **and** `FullFileName` ending `.idw` (12292 also matches Inventor-format `.dwg` drawings) |
| Placed parts list | iterate every `Sheet` in `DrawingDocument.Sheets`, every `PartsList` in `Sheet.PartsLists`; rows via `PartsList.PartsListRows`, skipping `row.Visible == False` |
| Columns | `PartsList.PartsListColumns`; ITEM column by `PropertyType == 45572` (kItemPartsListProperty); PART NUMBER / DESCRIPTION are `PropertyType == 45569` (kFileProperty) disambiguated by `GetFilePropertyId` (property set `{32853F0F-3444-11D1-9E93-0060B03C1CA6}`, id 5 = Part Number, 29 = Description); fall back to column `Title` match |
| Item number as printed | `row.Item(col).Value` — returns the displayed text **including user renumbering/static overrides**, which is exactly the spec's requirement. Never `BOMRow.ItemNumber` |
| Resolve row → model | `row.ReferencedRows` (empty ⇒ custom/virtual row, skip+flag) → `DrawingBOMRow.BOMRow.ComponentDefinitions.Item(1).Document`; failures ⇒ skip+flag |
| Classify | `Document.DocumentType`: 12291 (assembly) ⇒ Skip: sub-assembly; 12290 (part) + `SubType == "{9C464203-9BAE-11D3-8BAD-0060B0CE6BB4}"` ⇒ sheet metal; other part subtype ⇒ Skip: not sheet metal |
| Thickness | `SheetMetalComponentDefinition.Thickness.Value` — a `Parameter` in database units (cm for length); inches = value / 2.54 exactly |
| Flat pattern exists | `SheetMetalComponentDefinition.HasFlatPattern` |
| Create flat pattern | `Unfold()` then `FlatPattern.ExitEdit()`; any COM error ⇒ skip+flag with error text |
| Export DWG | `SheetMetalComponentDefinition.DataIO.WriteDataToFile(format, path)` with format `"FLAT PATTERN DWG"` (Inventor defaults; the format string is a config value). The DataIO route is the flat-pattern exporter; the DWG TranslatorAddIn is drawing-sheet-oriented and wrong for this job |
| Leave model untouched | see next section |

## The never-save contract (refined by research)

The spec's instruction — create the flat pattern, export, "close the part
document WITHOUT saving" — assumes closing unloads the part. Research shows it
does not when the part is still referenced by the open drawing (the normal
case): `Close(SkipSave:=True)` then leaves the document loaded **with the
created flat pattern in it and Dirty = True**, and a later user-initiated
"Save All" would persist that flat pattern to disk.

AutoFace therefore implements the strictly safer version of the same intent:

1. Parts referenced by an open drawing are used in-memory (they are already
   loaded); AutoFace never opens or closes them.
2. If AutoFace had to create a flat pattern, then after the export it deletes
   it again (`FlatPattern.Delete()`), returning the in-session document to the
   state it was found in, and best-effort clears `Dirty`.
3. Only documents AutoFace itself opened (not already in session — rare) are
   closed, with `Close(SkipSave:=True)` after `ReleaseReference()`.
4. AutoFace never calls `Save`/`SaveAs`/`Update` on any document, ever.

Pre-existing flat patterns are used as-is and never touched.

This is the one behavior that can damage models if gotten wrong; it has a
dedicated probe and a dedicated item on the manual test checklist (hash the
.ipt before/after a run that had to create the flat pattern).

## Core data flow

```
scan (COM, read-only)          plan (pure Python)           export (COM)
─────────────────────          ───────────────────          ─────────────
VisibleDocuments  ──────────►  parse drawing name           for each Export row:
  parts list rows              thickness table lookup         resolve part doc
  resolved model info          description cross-check        ensure flat pattern
  (plain dataclasses)          classification                 mkdirs, existence check
                               target path + collisions       DataIO export
                               = preview table rows            restore state, flag errors
```

The COM layer (`autoface/inventor/`) only *reads* Inventor state into plain
dataclasses and, in the export step, performs the per-row export. Everything
decidable without Inventor — filename parsing, the thickness table, the
description cross-check, classification, target paths, collision detection,
summaries — is pure Python in `autoface/core/`, fully unit-tested off-Windows.

Classification is an enum with one case per outcome
(`EXPORT`, `SKIP_NOT_SHEET_METAL`, `SKIP_SUB_ASSEMBLY`, `SKIP_NO_MODEL`,
`SKIP_INVALID_THICKNESS`, `SKIP_NAME_COLLISION`, `SKIP_UNPARSEABLE_DRAWING`),
so descending into sub-assemblies later is a one-case extension.

The export pipeline is strictly sequential — one Inventor session, stateful
documents; no COM parallelism. All COM work happens inside the worker thread
that runs it (`pythoncom.CoInitialize` per thread; COM objects never cross
threads).

## Naming and folders (from spec, config-backed)

- Drawing filename `{job}-{assy_raw}-{suffix}` (e.g. `8640-01101-I`): job =
  before first dash; assembly = second segment with leading zeros stripped
  (`01101` → `1101`); suffix dropped. Non-matching names ⇒ every row of that
  drawing previews as "Skip: unparseable drawing name".
- Export file `{job}-{assembly}-{item}.dwg`, item verbatim from the placed
  parts list.
- Folder `{root}\RUN {nn}\{thickness}\` where `nn` = first two digits of the
  stripped assembly number; thickness folder from the config table
  (`0.125 → "125"`, `0.1875 → "1875"`); model thickness rounded to the nearest
  1/16", description-parsed thickness wins on disagreement (flagged).
  Any rounded thickness not in the table ⇒ skip + flag.
- Existing target file ⇒ never overwrite; skip + flag. (`WriteDataToFile`
  would silently overwrite, so AutoFace checks first — and also pre-flags
  intra-run duplicates in the preview.)

## Config

`%APPDATA%\AutoFace\config.json`, created with defaults on first run:

```json
{
  "output_root": "",
  "thickness_table": { "0.125": "125", "0.1875": "1875" },
  "dwg_format": "FLAT PATTERN DWG"
}
```

- `output_root`: last-used output folder (UI persists it here).
- `thickness_table`: inches (as decimal strings, compared after rounding to
  1/16") → folder label. Editable; adding a thickness needs no code change.
  If labels ever standardize to four digits, edit the values (`"1250"` etc.).
- `dwg_format`: the DataIO format string. Default is bare ("Inventor default
  DWG export settings"); if a given Inventor version rejects the bare string
  (probe covers this), set `"FLAT PATTERN DWG?AcadVersion=2018"`.

## Packaging and updates (AutoBOM's, ported)

- `packaging/autoface.spec` (one-file, windowed, `VERSION` + optional
  `build_info.json` in `datas`), `packaging/launcher.py`,
  `packaging/build-windows-exe.sh` (Wine cross-build fallback).
- `VERSION` at repo root, `autoface/version.py` (`_bundle_dir`, `describe()`,
  `build_id`/`run_number`, `0.dev` sentinel), `scripts/bump_version.py`.
- `.github/workflows/build-windows.yml`: pytest → stamp `build_info.json` →
  pyinstaller → `Start-Process -Wait` self-test of the built exe → sha256 +
  `latest.json` manifest → publish `AutoFace.exe` + `latest.json` to fixed tag
  `windows-latest-build` (reused, `prerelease: false`).
- Updater (`autoface/updater/`): polls
  `https://github.com/burntbysam/AutoFace/releases/download/windows-latest-build/latest.json`
  (override with env `AUTOFACE_UPDATE_URL`, https or UNC path); version
  compare with same-version-later-build tiebreak; chunked cancellable download
  with delete-on-failure; sha256 gate; downloaded exe must pass its own
  `--selftest` (with scrubbed PyInstaller bootloader env) before the
  rename-aside swap (`.old`/`.new`, rollback on failure); silent check on
  launch, interactive check in the Help menu; `cleanup_backups()` every launch.
- One exe, two faces: no args → GUI; args → CLI (`--selftest`, `--version`,
  `--probe …`).

## UI (AutoBOM conventions, AutoFace content)

Single `QMainWindow` "AutoFace {version}": output-folder row (picker +
persisted path), "Scan open drawings" / "Export" buttons, the preview table
(`QTableWidget`: Drawing, Item, Part number, Thickness, Classification, Target
path — populated by a scan before anything is written), progress bar + status
line during the run, and an end-of-run summary dialog in AutoBOM's
FlagsDialog shape (styled heading, counts, scrollable flag list, "Save log…"
writing a .txt next to the exports). Long-running scan/export run in QThread
subclasses with signals (AutoBOM's threading pattern — no worker+moveToThread),
each doing its own COM attach. Inventor not running / no drawings open is
reported in the UI, run disabled.

## Probes (must run against a real session before trusting a batch)

`AutoFace.exe --probe all` (or individual names) writes
`AutoFace-probe-results.txt` next to the exe; the user pastes it back. The
probes are read-only except where stated:

1. `session` — attach, list VisibleDocuments with DocumentType/SubType;
   asserts the hard-coded enum values against a live session.
2. `partslist` — for one open drawing: columns (Title + PropertyType), each
   visible row's item/part number/description, and the resolved model path
   per row. Confirms as-printed item numbers on a renumbered list.
3. `thickness` — Thickness.Value for each sheet metal part + the computed
   inches and folder label.
4. `export` — exports ONE flat pattern to a temp folder with the bare
   `"FLAT PATTERN DWG"` format string (tests the AcadVersion-less default).
5. `neversave` — on a test part with no flat pattern: record file hash,
   Unfold → export → FlatPattern.Delete → verify hash unchanged and report
   the Dirty flag before/after.

## Known limitations (v1)

- Sub-assembly rows are skipped and flagged (classifier ready for descent).
- Default DWG export settings only.
- Two thicknesses in the shipped table (config-extendable).
- Multi-body sheet metal parts: the document-level Thickness parameter is
  used; per-body overridden rules are not read (Inventor itself restricts
  flat patterns there); failures surface as flags.
- If the same part file appears in several drawings' lists, each occurrence
  exports under its own drawing/item name (per spec: duplicates are fine).
