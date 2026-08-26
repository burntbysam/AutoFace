# AutoFace

Batch flat-pattern DWG exporter for Autodesk Inventor drawings.

AutoFace walks the placed parts lists of the drawings (.idw) open in your
running Inventor session, finds the sheet metal parts behind them, and exports
each one's flat pattern as a .dwg, filed by RUN and thickness:

```
{output folder}\RUN 11\1875\8640-1101-1.dwg
{output folder}\RUN 11\125\8640-1101-5.dwg
```

Reference target: Inventor Professional 2025 (works with 2020–2026). Built as
a sibling tool to AutoBOM: one exe, self-updating, same look.

## How to run

1. Download `AutoFace.exe` from the
   [latest Windows build](https://github.com/burntbysam/AutoFace/releases/tag/windows-latest-build)
   and put it anywhere (no install, no admin rights). Windows will show
   "Windows protected your PC" the first time — **More info → Run anyway**.
2. Start Inventor and open the drawings you want to process. Open parts,
   assemblies and presentations are ignored; only visible `.idw` tabs count.
3. Run AutoFace, pick the output folder (remembered for next time), and press
   **Scan open drawings**.
4. Review the preview table — one row per parts-list item, with the resolved
   thickness, the classification, and the exact target path. Nothing has been
   written yet; this is where a bad filename parse or thickness read shows up.
   Click any column header to sort (click again to reverse) — item and part
   numbers sort numerically, thickness by value. Sorting is display-only;
   exports always run in drawing order.
5. Press **Export flat patterns**. The end-of-run summary shows counts and a
   flag list, and offers to save the log as a .txt next to the exports.

On first use, run the probes and the [manual test checklist](TESTING.md)
against one known drawing before trusting a batch.

## What gets exported, what gets skipped

For every visible row of every placed parts list (item numbers are read as
printed on the sheet, including manual renumbering — never from the
assembly's internal BOM):

| Row resolves to | Result |
|---|---|
| Sheet metal part, valid thickness | **Export** (purchased or normal BOM structure — both export) |
| Non-sheet-metal part | Skip: not sheet metal |
| Sub-assembly | Skip: sub-assembly (future versions will descend) |
| Virtual/custom row, no model file | Skip: no model |
| Thickness not in the table | Skip: invalid thickness |
| Target .dwg already exists | Skip: name collision (never overwritten) |
| Drawing name doesn't parse | Skip: unparseable drawing name |

Expected skips are silent: any skipped row whose BOM description never
claimed to be sheet (no `SHEET` callout, no thickness like `.190`) — support
assemblies, channel, hardware — still shows in the preview table and the
troubleshooting log, but stays out of the end-of-run counts and flag list. A
skip on a row whose description *does* say sheet stays counted and flagged
(that mismatch is an anomaly worth hearing about), and name collisions and
bad item numbers are always loud — those are DWGs that would have shipped
and did not.

Flat patterns: an existing flat pattern is used as-is. If a part has none,
AutoFace creates one via the API, exports it, then **deletes it again and
never saves the part** — the model on disk stays byte-identical. If the
unfold fails, the part is skipped and flagged with the error text.

Naming: a drawing named `8640-01101-I` gives job `8640`, assembly `1101`
(leading zeros stripped), suffix dropped, RUN folder `RUN 11` (first two
digits of the stripped assembly number). The export file is
`{job}-{assembly}-{item}.dwg` with the item exactly as printed.

Thickness: the part's sheet metal Thickness parameter is converted to inches
and rounded to the nearest 1/16". The BOM description is parsed as a
cross-check (e.g. the `.190` in `SHEET,AL,SMOOTH,.190,60X133.13`); **when the
two disagree, the description wins** for folder selection and the row is
flagged so you hear about it.

## Configuration

`%APPDATA%\AutoFace\config.json`, created with defaults on first use:

```json
{
  "output_root": "C:\\exports",
  "thickness_table": {
    "0.125": "125",
    "0.1875": "1875"
  },
  "dwg_format": "FLAT PATTERN DWG?InvisibleLayers=IV_BEND;IV_BEND_DOWN;IV_ARC_CENTERS;IV_TANGENT;IV_ROLL_TANGENT"
}
```

- **output_root** — the output folder; the UI writes this when you pick one.
- **thickness_table** — the valid thicknesses: inches (matched after rounding
  to 1/16") → folder name. Add a new standard thickness by adding a line, e.g.
  `"0.25": "250"` — no code change. If folder labels ever standardize to four
  digits, edit the values (`"0.125": "1250"` etc.).
- **dwg_format** — the Inventor DataIO format string. The default exports the
  cut profile only: bend centerlines (`IV_BEND`, `IV_BEND_DOWN`), hole-center
  point markers (`IV_ARC_CENTERS`), and the bend-extent tangent lines
  (`IV_TANGENT`, `IV_ROLL_TANGENT`) are all suppressed via `InvisibleLayers`.
  To bring any of them back, remove that entry from the list. If your
  Inventor version rejects the string (`AutoFace.exe --probe export` tells
  you), add `AcadVersion=2018&` in front of `InvisibleLayers`. Configs
  written by older AutoFace versions with a previous default are upgraded
  automatically.

## Updates

On launch AutoFace silently checks the fixed release tag
(`windows-latest-build`) for a newer build; Help → **Check for updates…** does
it on demand. An update is downloaded next to the exe, verified against the
published SHA256, made to pass its own `--selftest`, and only then swapped in
(the old build is kept as `.old` until the next launch). Machines without
GitHub access can be pointed at a copy of `latest.json` + `AutoFace.exe` on a
network share with the `AUTOFACE_UPDATE_URL` environment variable (https URL
or UNC path). AutoFace works fine offline — the check just does nothing.

## Command line

The same exe serves both faces: double-click for the GUI, or run with
arguments:

- `AutoFace.exe --selftest` — replays the spec's worked examples through the
  naming/thickness/classification pipeline; exits 0/1. CI and the updater
  gate on this.
- `AutoFace.exe --version` — prints e.g. `AutoFace 0.1.0 (build 42.a1b2c3d)`.
- `AutoFace.exe --probe all` (or `session`, `partslist`, `thickness`,
  `export`, `neversave`) — checks the Inventor API behaviour against your
  live session and writes `AutoFace-probe-results.txt` next to the exe.
  Run these once on first install (see [TESTING.md](TESTING.md)).

## Troubleshooting log

Every session quietly appends to a daily log in `%USERPROFILE%\AutoFace Logs`
(e.g. `AutoFace Logs\AutoFace-2026-08-26.log`): version and config at launch,
scan results and flags, one line per exported/skipped/failed row with the
error text, the full end-of-run summary, and update events. When something
looks wrong, send that day's file. Logging is best-effort (a machine where the
folder can't be written just runs without it) and files older than 60 days are
cleaned up automatically.

## Known limitations

- **Sub-assemblies are not descended.** Rows backed by an assembly are
  skipped and flagged. The classifier is structured so descending is a
  one-case extension in a future version.
- **One DWG flavor** — the single config format string is the only export
  customization; it ships with bend lines and hole-center markers suppressed.
- **Two thicknesses ship in the table** (1/8" → `125`, 3/16" → `1875`).
  Anything else is skipped and flagged until added to the config.
- Multi-body sheet metal parts use the document-level Thickness parameter;
  per-body overridden rules are not read (Inventor itself restricts flat
  patterns on those), and their unfold failures surface as flags.
- One Inventor session: exports run sequentially by design.
- The exe is not code-signed; expect the SmartScreen prompt on first run.

## Development

```
pip install -r requirements-dev.txt
python -m pytest            # 200+ tests, no Inventor needed (COM is faked)
python -m autoface          # GUI from source
pyinstaller packaging/autoface.spec   # build AutoFace.exe (on Windows)
```

CI (`.github/workflows/build-windows.yml`) tests, builds, self-tests and
publishes `AutoFace.exe` + `latest.json` to the `windows-latest-build` release
tag on every push that touches the app. `packaging/build-windows-exe.sh`
cross-builds on Linux under Wine when no Windows machine is handy.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and the Inventor API
map.
