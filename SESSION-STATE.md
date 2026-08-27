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
2. DONE — CI runs #1–#8 all succeeded. The windows-latest-build release
   carries AutoFace.exe v0.2.0 (build 8.7db366c): cut-profile-only DWGs
   (bend/arc-center/slot-tool-center/tangent layers suppressed; legacy
   configs auto-upgrade), description-keyed silent skips (collisions and
   bad items always loud), full pick-list troubleshooting logging,
   click-to-sort preview columns, and per-part export selection (tick
   boxes, Deselect all / Select all sheet parts, deselected rows logged
   as their own 'Not selected' category). Nothing is in flight.

## Then remaining

- Only the user-side gate: they run --probe all + TESTING.md against a real
  drawing on their Inventor Professional 2025.3 and paste
  AutoFace-probe-results.txt back if anything looks off.

## Session preferences the user stated

- Failsafe session state to the repo when nearing token limits (this file).
- Subagents default to Opus (Sonnet/Haiku for light mechanical sweeps);
  Fable-tier only where it is actually necessary — it burns tokens fast and
  is overkill for checking agents.
