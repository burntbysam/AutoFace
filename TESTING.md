# AutoFace manual test checklist

Run this against **one known drawing** (e.g. `8640-01101-I`) before trusting
a batch. Steps 1–3 are read-only; step 4 writes one DWG to a temp folder;
step 5 is the never-save proof. Expect the whole pass to take ~15 minutes.

Setup: Inventor running, only the test drawing open, AutoFace.exe on disk.

## 1. Self-test and probes

- [ ] `AutoFace.exe --selftest` writes `AutoFace-selftest-results.txt` next
      to the exe ending in `SELF-TEST PASSED`. (The exe is a windowed binary,
      so the console shows nothing — read the file.)
- [ ] `AutoFace.exe --probe all` writes `AutoFace-probe-results.txt` next to
      the exe. Read it top to bottom:
  - [ ] **session**: your drawing is listed with `type=12292`; parts show
        `12290`; any assembly `12291`.
  - [ ] **partslist**: every printed row appears, with the right item
        numbers, and each row's `model:` line points at the file you expect.
  - [ ] **thickness**: each sheet metal part shows the thickness you know it
        has, and the folder label (`125` / `1875`) is right.
  - [ ] **export**: `OK: wrote N bytes`. If it failed, set
        `"dwg_format": "FLAT PATTERN DWG?AcadVersion=2018"` in
        `%APPDATA%\AutoFace\config.json` and re-run.
  - [ ] **neversave**: `OK: the .ipt on disk is byte-identical`. If it says
        `SKIP` (every part already has a flat pattern), see step 5.
- [ ] Open the DWG the export probe wrote (in your CAM tool or a DWG viewer):
      it is the flat pattern, correct outline, correct scale (1:1 in the
      part's units), bend lines present.

## 2. The preview is honest

- [ ] Start AutoFace, choose a scratch output folder, press **Scan open
      drawings**.
- [ ] Every printed parts-list row of the drawing appears — count them
      against the sheet.
- [ ] Item numbers match the printed table exactly. If you have ever
      renumbered rows: renumber one row in Edit Parts List, rescan, and
      confirm the preview follows the sheet, not the model BOM.
- [ ] Sheet metal rows say **Export** with the path you expect:
      `RUN 11\1875\8640-1101-{item}.dwg` for .190 parts,
      `RUN 11\125\...` for .125 parts.
- [ ] A known purchased sheet metal part (if the drawing has one) is
      **Export**, not skipped.
- [ ] Non-sheet-metal rows say **Skip: not sheet metal**; sub-assembly rows
      **Skip: sub-assembly**; virtual/custom rows **Skip: no model**.
- [ ] Any part outside 1/8" / 3/16" says **Skip: invalid thickness**.
- [ ] Close the drawing, open one with a non-conforming name (or rename a
      copy), rescan: its rows say **Skip: unparseable drawing name**.

## 3. Thickness cross-check

- [ ] Pick a row whose description carries a thickness (e.g.
      `SHEET,AL,SMOOTH,.190,...`) and confirm the preview thickness agrees.
- [ ] If you can, make a throwaway copy where description and model disagree:
      the preview must follow the **description** and the row must be flagged
      with both values.

## 4. First real export

- [ ] Press **Export flat patterns** into the scratch folder.
- [ ] `RUN {nn}` and thickness folders are created on demand; every exported
      file is where the preview said it would be.
- [ ] Each DWG opens and is the right part's flat pattern.
- [ ] The summary counts add up (exported + skipped + failed = preview rows),
      and **Save log…** writes a readable .txt next to the exports.
- [ ] Press Export again without clearing the folder: every previously
      exported row now says **Skip: name collision**, and no file's modified
      time changes. Nothing is ever overwritten.

## 5. THE NEVER-SAVE CHECK (do not skip this one)

This is the one behavior that could damage models if it regressed.

- [ ] Find (or make a copy of) a sheet metal part **without** a flat pattern,
      referenced by a test drawing. Note the .ipt's size and modified time
      (or hash it: `certutil -hashfile part.ipt SHA256`).
- [ ] `AutoFace.exe --probe neversave` reports
      `OK: the .ipt on disk is byte-identical`.
- [ ] Run a real export over that drawing. Afterwards:
  - [ ] The .ipt on disk is unchanged (same hash/size/mtime).
  - [ ] In Inventor, the part shows **no flat pattern** in the browser
        (AutoFace deleted the one it created).
  - [ ] Do **File → Save All** in Inventor, then re-check the hash: still
        unchanged (nothing of AutoFace's was pending).
- [ ] Confirm the drawing itself was never prompted to save and its file is
      unchanged.

## 6. Failure behaviour

- [ ] With Inventor closed, press Scan: a clear "Inventor is not running"
      message, no crash.
- [ ] With Inventor open but no drawings, press Scan: "No drawings are open"
      message.
- [ ] If you have a part that cannot unfold (lofted/imported geometry), point
      a drawing at it: the run continues past it and the summary flags it
      with the error text.

## 7. Update mechanism (once a second build exists)

- [ ] Launch an older build: it offers the update; **Update now** downloads,
      verifies, restarts into the new version (About shows the new build id).
- [ ] Kill the network and launch: AutoFace starts normally, no complaints.

When every box is checked, batches can be trusted. Re-run section 5 after any
Inventor upgrade or AutoFace update that touches the export path.
