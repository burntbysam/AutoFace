# Session state (dev failsafe — safe to delete once v0.1 ships)

Continuation notes for the Claude Code session building AutoFace, so any
fresh session can resume from this branch alone. Human-relevant docs live in
README.md / ARCHITECTURE.md / TESTING.md; this file is only the in-flight
state.

## Where things stand

Branch `claude/autoface-dwg-exporter-0ekicr`, all work committed and pushed.
Complete and tested (217 pytest cases + `--selftest`):

- Core pipeline (`autoface/core/`): naming (zero-strip, suffix drop, RUN
  folder), thickness (cm→in, 1/16" rounding, description-wins cross-check,
  config-editable table), classification enum, collision rule (disk +
  intra-run), summary/log rendering, self-test replaying the spec examples.
- Inventor COM adapter (`autoface/inventor/`): late-bound attach, session
  scan (VisibleDocuments, placed parts lists as printed), export with the
  never-save contract (in-session parts never closed; created flat patterns
  deleted after export; only self-opened docs closed with SkipSave; existing
  targets never overwritten), busy-retry, SilentOperation guard, five
  `--probe` checks.
- GUI (`autoface/gui/`): AutoBOM conventions (PySide6, QThread-subclass
  workers, QProgressDialog, About/Copy details), folder picker persisted to
  `%APPDATA%\AutoFace\config.json`, preview table before export, summary
  dialog with Save log.
- Updater (`autoface/updater/`) + packaging (`packaging/`,
  `.github/workflows/build-windows.yml`): AutoBOM's mechanism ported
  verbatim (fixed tag `windows-latest-build`, `latest.json`, sha256 +
  `--selftest` gate, rename-aside swap, `AUTOFACE_UPDATE_URL` override).

## In flight at last save

1. DONE — the verification pass ran (6 reviewers, adversarial verification);
   all confirmed findings were fixed in commit 504d073 (dirty-flag safety,
   probe leak, close guard, two-pass column mapping, busy re-raise, summary
   count consistency, config diagnostics, selftest results file).
2. DONE — CI runs #1–#9 all succeeded. The windows-latest-build release
   carries AutoFace.exe v0.2.1 (build 9.8a46ce5). Everything from v0.2.0
   (cut-profile-only DWGs, description-keyed silent skips, pick-list
   logging, sortable columns, per-part selection) plus the BOM-description
   authority rule: a sheet-metal-modeled part exports ONLY if its
   description also reads as sheet — tubes/channels modeled as sheet
   metal classify 'Skip: not sheet per BOM' (silent); a blank description
   still exports but is flagged. Locked into --selftest. Nothing is in
   flight.

## Then remaining

- Only the user-side gate: they run --probe all + TESTING.md against a real
  drawing on their Inventor Professional 2025.3 and paste
  AutoFace-probe-results.txt back if anything looks off.

## Agreed future feature (do NOT build until the user says go)

Corner-relief ("notch") closure — decided 2026-08 but explicitly parked:

- Problem: Inventor's unfold bakes a small rectangular corner relief into
  the outer profile where two bends meet; the shop wants those corners
  closed (edges extended to a sharp intersection), per the user's redlined
  screenshots.
- Decision: Route 2 (post-process the exported geometry in AutoFace).
  DXF output is acceptable to their CAM, so switch the export to
  "FLAT PATTERN DXF" and post-process with ezdxf — no ODA converter, stays
  single-file. (Route 1, Trim-to-Bend in the sheet metal rule, was offered
  but the user chose Route 2.)
- Detection rule (from the user's redline): REMOVE only a short 3-segment
  rectangular indentation sitting at the junction of two long perpendicular
  edges (a corner relief) — replace it by extending both edges to their
  intersection; size-capped to a small multiple of the part's thickness
  (known per row). KEEP everything else — the user confirmed NO mid-edge /
  straight-edge relief ever needs removing, so anything not matching the
  corner signature is untouched.
- Safety requirements when built: conservative thresholds, log every
  closure per part in the run log, a config off-switch, a probe comparing
  raw vs cleaned geometry, and a new TESTING.md section — this edits cut
  geometry, so it gets never-save-level paranoia. Naming scheme keeps
  {job}-{assembly}-{item} with .dxf extension; collision rule unchanged.

## Session preferences the user stated

- Failsafe session state to the repo when nearing token limits (this file).
- Subagents default to Opus (Sonnet/Haiku for light mechanical sweeps);
  Fable-tier only where it is actually necessary — it burns tokens fast and
  is overkill for checking agents.
