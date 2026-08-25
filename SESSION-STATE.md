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

1. Verification workflow `wf_0afc30e5-0f1` (6 spec reviewers + adversarial
   verification of findings). If its results were lost: re-run the script at
   `.../workflows/scripts/autoface-verify-wf_0afc30e5-0f1.js` or simply
   re-review against the spec emphasis areas (never-save, as-printed item
   numbers, thickness table, collision rule). Confirmed findings must be
   fixed and pushed.
2. GitHub Actions run #1 (`Build Windows executable`) on this branch —
   verify it went green and published `AutoFace.exe` + `latest.json` to the
   `windows-latest-build` release; if red, fix from the job logs.

## Then remaining

- Relay to the user: architecture summary, the probe/checklist gate
  (TESTING.md) they must run against a real drawing (they run Inventor
  Professional 2025.3), and the download link once CI publishes.
- Open questions for the user: none blocking; probes replace assumptions.

## Session preferences the user stated

- Failsafe session state to the repo when nearing token limits (this file).
- Prefer lighter models (Sonnet/Haiku) for checking/mechanical subagents;
  Fable-tier only where deep reasoning is load-bearing.
