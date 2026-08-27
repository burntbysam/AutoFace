"""AutoFace desktop window."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path

import PySide6
from PySide6.QtCore import Qt, QThread, QUrl, Signal, qVersion
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import Config, load_config, save_config
from ..runlog import logger
from ..core.models import (
    Classification,
    Plan,
    RowOutcome,
    RunResult,
    ScannedDrawing,
)
from ..core.pipeline import build_plan
from ..core.summary import flag_lines, summarize_run, total_skipped
from ..core.thickness import ThicknessTable
from ..updater import installer
from ..updater.github import (
    RELEASE_PAGE,
    UpdateCancelled,
    UpdateInfo,
    check_for_update,
    download_asset,
    manifest_url,
)
from ..version import build_details
from .widgets import PreviewTable, SummaryDialog


class UpdateCheck(QThread):
    """Runs the release check off the UI thread; failures are silent.

    This subclasses QThread and overrides run() rather than using the
    worker-object-plus-moveToThread pattern. That pattern needs something to
    keep a reference to the worker: a local one is garbage collected as soon as
    the launching function returns, the C++ object goes with it, and the check
    silently never runs. Overriding run() leaves nothing to lose track of, and
    the thread reaches the end of run() so `finished` is actually emitted.
    """

    # Not named `finished`; QThread already has a signal by that name.
    checked = Signal(object)

    def run(self) -> None:
        self.checked.emit(check_for_update())


class UpdateInstall(QThread):
    """Download, verify, self-test and swap in a new build."""

    stage = Signal(str)
    progress = Signal(int, int)  # received, total
    succeeded = Signal(str)  # path of the installed executable
    failed = Signal(str)

    def __init__(self, info: UpdateInfo, target: Path, parent=None) -> None:
        super().__init__(parent)
        self._info = info
        self._target = Path(target)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        staging = installer.staging_path(self._target)
        try:
            self.stage.emit("Downloading…")
            download_asset(
                self._info,
                staging,
                on_progress=lambda got, total: self.progress.emit(got, total),
                should_cancel=lambda: self._cancelled,
            )

            # Checksum is already verified inside download_asset; the self-test
            # is what catches a build that is intact but broken.
            self.stage.emit("Checking the new version…")
            ok, detail = installer.run_selftest(staging)
            if not ok:
                staging.unlink(missing_ok=True)
                self.failed.emit(
                    "The downloaded version failed its own self-test, so it was "
                    "not installed and your current copy is untouched.\n\n" + detail
                )
                return

            self.stage.emit("Installing…")
            installer.swap_in(staging, self._target)
        except UpdateCancelled:
            self.failed.emit("")  # cancelled: no error to report
            return
        except Exception as exc:  # noqa: BLE001 - surface anything, never crash
            Path(staging).unlink(missing_ok=True)
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(str(self._target))


class ScanWorker(QThread):
    """Attach to Inventor and read the session, entirely off the UI thread.

    COM objects are apartment-bound, so this thread attaches on its own and
    hands back only plain dataclasses; no COM object ever crosses a thread.
    """

    scanned = Signal(object)  # list[ScannedDrawing]
    failed = Signal(str)

    def run(self) -> None:
        from ..inventor import com as inventor_com
        from ..inventor.scan import scan_session

        try:
            inventor_com.initialize_thread()
        except inventor_com.InventorUnavailable as exc:
            self.failed.emit(str(exc))
            return
        app = None
        try:
            app = inventor_com.attach()
            drawings = inventor_com.with_busy_retry(lambda: scan_session(app))
        except (
            inventor_com.InventorNotRunning,
            inventor_com.InventorUnavailable,
        ) as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self.failed.emit(inventor_com.error_text(exc))
            return
        finally:
            # Drop the COM proxy before tearing down COM for this thread.
            app = None  # noqa: F841
            inventor_com.uninitialize_thread()
        self.scanned.emit(drawings)


class ExportWorker(QThread):
    """Runs the sequential export pipeline; same COM-per-thread rules."""

    progress = Signal(int, int)  # done, total
    row_done = Signal(object)  # RowOutcome
    finished_run = Signal(object)  # RunResult
    failed = Signal(str)

    def __init__(self, plan: Plan, config: Config, parent=None) -> None:
        super().__init__(parent)
        self._plan = plan
        self._config = config
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from ..inventor import com as inventor_com
        from ..inventor.export import run_export

        try:
            inventor_com.initialize_thread()
        except inventor_com.InventorUnavailable as exc:
            self.failed.emit(str(exc))
            return
        app = None
        try:
            app = inventor_com.attach()
            result = run_export(
                app,
                self._plan,
                self._config,
                on_progress=lambda done, total: self.progress.emit(done, total),
                on_row=lambda outcome: self.row_done.emit(outcome),
                should_cancel=lambda: self._cancelled,
            )
        except (
            inventor_com.InventorNotRunning,
            inventor_com.InventorUnavailable,
        ) as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self.failed.emit(inventor_com.error_text(exc))
            return
        finally:
            # Drop the COM proxy before tearing down COM for this thread.
            app = None  # noqa: F841
            inventor_com.uninitialize_thread()
        self.finished_run.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"AutoFace {__version__}")
        self.resize(1000, 680)
        self._config = load_config()
        self._scanned: list[ScannedDrawing] | None = None
        self._plan: Plan | None = None
        self._run_plan: Plan | None = None  # the plan as ticked for the last run
        self._result: RunResult | None = None
        self._update_thread: QThread | None = None
        self._install_thread: QThread | None = None
        self._scan_thread: QThread | None = None
        self._export_thread: QThread | None = None
        # An update leaves the previous build beside the new one; it cannot
        # be deleted while it is still running, so it is cleared on launch.
        installer.cleanup_backups()
        logger.info(
            "config: output_root=%r, thickness_table=%s, dwg_format=%r",
            self._config.output_root,
            self._config.thickness_table,
            self._config.dwg_format,
        )

        self._build_menu()
        self._build_body()
        self._update_ready_state()
        self._start_update_check()

    # -- construction --------------------------------------------------
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        update_action = QAction("Check for &updates…", self)
        update_action.triggered.connect(lambda: self._start_update_check(interactive=True))
        help_menu.addAction(update_action)
        about_action = QAction("&About AutoFace", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_body(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)

        intro = QLabel(
            "Open your drawings in Inventor, pick an output folder, then press "
            "<b>Scan open drawings</b>. Review the preview — every row shows "
            "where its flat pattern DWG will land — then press <b>Export</b>."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Output folder:"))
        self.folder_edit = QLineEdit(self._config.output_root)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Choose where the DWGs go…")
        folder_row.addWidget(self.folder_edit, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose)
        outer.addLayout(folder_row)

        actions = QHBoxLayout()
        self.scan_button = QPushButton("Scan open drawings")
        self.scan_button.clicked.connect(self._scan)
        actions.addWidget(self.scan_button)
        self.deselect_button = QPushButton("Deselect all")
        self.deselect_button.clicked.connect(
            lambda: self.preview.set_all_checked(False)
        )
        actions.addWidget(self.deselect_button)
        self.select_default_button = QPushButton("Select all sheet parts")
        self.select_default_button.clicked.connect(
            lambda: self.preview.set_all_checked(True)
        )
        actions.addWidget(self.select_default_button)
        actions.addStretch(1)
        self.export_button = QPushButton("Export flat patterns")
        self.export_button.setMinimumWidth(220)
        self.export_button.clicked.connect(self._export)
        actions.addWidget(self.export_button)
        outer.addLayout(actions)

        self.preview = PreviewTable()
        self.preview.selection_changed.connect(self._update_ready_state)
        outer.addWidget(self.preview, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        self.log.setPlaceholderText("Scan results and flags appear here.")
        outer.addWidget(self.log)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")

    # -- config / folder -----------------------------------------------
    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the output folder", self._config.output_root or str(Path.home())
        )
        if not chosen:
            return
        self._config.output_root = str(Path(chosen))
        save_config(self._config)  # persisted for the next run
        logger.info("output folder set to %r", self._config.output_root)
        self.folder_edit.setText(self._config.output_root)
        if self._scanned is not None:
            self._rebuild_plan()  # collision checks depend on the root
        self._update_ready_state()

    def _update_ready_state(self) -> None:
        scanning = self._scan_thread is not None and self._scan_thread.isRunning()
        exporting = (
            self._export_thread is not None and self._export_thread.isRunning()
        )
        busy = scanning or exporting
        self.scan_button.setEnabled(not busy)
        selectable = self.preview.selectable_count()
        selected = len(self.preview.selected_plan_indexes())
        has_plan = self._plan is not None and selectable > 0
        self.deselect_button.setEnabled(has_plan and not busy and selected > 0)
        self.select_default_button.setEnabled(
            has_plan and not busy and selected < selectable
        )
        self.export_button.setEnabled(
            selected > 0
            and bool(self._config.output_root)
            and not busy
        )
        if not self._config.output_root:
            self.statusBar().showMessage("Choose an output folder to begin")
        elif has_plan and not busy:
            self.statusBar().showMessage(
                f"{selected} of {selectable} sheet part(s) selected to export"
            )

    # -- scanning -------------------------------------------------------
    def _scan(self) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        self.log.clear()
        self.statusBar().showMessage("Scanning open drawings…")
        thread = ScanWorker(self)
        thread.scanned.connect(self._on_scanned)
        thread.failed.connect(self._on_scan_failed)
        thread.finished.connect(self._clear_scan_thread)
        self._scan_thread = thread
        self._update_ready_state()
        thread.start()

    def _clear_scan_thread(self) -> None:
        thread, self._scan_thread = self._scan_thread, None
        if thread is not None:
            thread.deleteLater()
        self._update_ready_state()

    def _on_scan_failed(self, message: str) -> None:
        logger.warning("scan failed: %s", message)
        self.statusBar().showMessage("Scan failed")
        self._append(message)
        QMessageBox.information(self, "Cannot scan", message)

    def _on_scanned(self, drawings: list[ScannedDrawing]) -> None:
        self._scanned = drawings
        if not drawings:
            logger.info("scan: no open .idw drawings")
            self._plan = None
            self.preview.show_plan(Plan())
            message = (
                "No drawings (.idw) are open in Inventor. Open the drawings to "
                "process, then press Scan again."
            )
            self.statusBar().showMessage("No open drawings")
            self._append(message)
            QMessageBox.information(self, "Nothing to scan", message)
            self._update_ready_state()
            return
        self._rebuild_plan()

    def _rebuild_plan(self, describe_in_log: bool = True) -> None:
        assert self._scanned is not None
        table = ThicknessTable(self._config.thickness_table)
        plan = build_plan(
            self._scanned,
            self._config.output_root,
            table,
        )
        self._plan = plan
        self.preview.show_plan(plan)

        total = len(plan.rows)
        exportable = len(plan.exportable)
        silent = sum(1 for planned in plan.rows if planned.silent)
        drawings = len(self._scanned)
        if describe_in_log:
            # A fresh preview replaces the log; a post-run refresh must not
            # wipe the run's per-row record.
            self.log.clear()
            skips = total - exportable - silent
            line = (
                f"Scanned {drawings} drawing(s): {total} parts list row(s), "
                f"{exportable} to export, {skips} to skip"
            )
            if silent:
                line += f", {silent} routine non-sheet row(s)"
            self._append(line + ".")
            logger.info("%s", line)
            # The complete pick list, silent rows included: the log shows
            # everything that was there to be picked from, then (during the
            # run) what was actually exported.
            for planned in plan.rows:
                found = (
                    f"found: {planned.drawing_label} item {planned.item} "
                    f"({planned.part_number}) {planned.description or '-'} "
                    f"-> {planned.classification.label}"
                )
                if planned.classification is Classification.EXPORT:
                    found += f" -> {planned.target_relative}"
                logger.info("%s", found)
            for flagged in flag_lines(plan):
                logger.info("preview flag: %s", flagged)
            if table.ignored:
                self._append(
                    "Config problem: ignored malformed thickness table "
                    f"key(s) {', '.join(repr(k) for k in table.ignored)} — "
                    'keys must be inches as decimals, e.g. "0.125".'
                )
            for note in plan.drawing_notes:
                self._append(f"Note: {note}")
            for line in flag_lines(plan):
                if line not in plan.drawing_notes:
                    self._append(line)
            if exportable and not self._config.output_root:
                self._append("Choose an output folder to enable the export.")
        self.statusBar().showMessage(
            f"Preview ready — {exportable} of {total} row(s) will export"
        )
        self._update_ready_state()

    # -- exporting ------------------------------------------------------
    def _run_plan_from_selection(self) -> Plan | None:
        """The plan as ticked in the preview: unticked rows become deselected."""
        if self._plan is None:
            return None
        chosen = self.preview.selected_plan_indexes()
        rows = tuple(
            replace(row, selected=False)
            if row.classification is Classification.EXPORT and index not in chosen
            else row
            for index, row in enumerate(self._plan.rows)
        )
        return Plan(rows=rows, drawing_notes=self._plan.drawing_notes)

    def _export(self) -> None:
        run_plan = self._run_plan_from_selection()
        if run_plan is None or not run_plan.exportable:
            return
        if self._export_thread is not None and self._export_thread.isRunning():
            return
        self._run_plan = run_plan
        for row in run_plan.deselected:
            logger.info(
                "deselected by the user: %s item %s (%s)",
                row.drawing_label,
                row.item,
                row.part_number,
            )
        total = len(run_plan.exportable)

        progress = QProgressDialog("Starting…", "Cancel", 0, total, self)
        progress.setWindowTitle("Exporting flat patterns")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)

        thread = ExportWorker(run_plan, self._config, self)

        def on_progress(done: int, count: int) -> None:
            progress.setMaximum(count)
            progress.setValue(done)
            progress.setLabelText(f"Exporting… {done} of {count}")

        def on_row(outcome: RowOutcome) -> None:
            self._append(outcome.line)
            if outcome.status == "failed":
                logger.error("row failed: %s", outcome.line)
            else:
                logger.info("row: %s", outcome.line)

        def on_failed(message: str) -> None:
            progress.close()
            self._clear_export_thread()
            logger.error("export run failed: %s", message)
            self.statusBar().showMessage("Export failed")
            QMessageBox.warning(self, "Export failed", message)

        def on_finished(result: RunResult) -> None:
            progress.close()
            self._clear_export_thread()
            self._result = result
            plan = self._run_plan or self._plan
            skipped = total_skipped(plan, result) if plan else result.skipped
            self.statusBar().showMessage(
                f"Done — exported {result.exported}, skipped {skipped}, "
                f"failed {result.failed}"
            )
            if plan is not None:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                logger.info(
                    "run summary:\n%s",
                    summarize_run(plan, result, self._config.output_root, timestamp),
                )
            self._show_summary(result)
            # The preview is now stale: exported files exist on disk, so a
            # re-plan shows them as collisions rather than pending work.
            if self._scanned is not None:
                self._rebuild_plan(describe_in_log=False)

        thread.progress.connect(on_progress)
        thread.row_done.connect(on_row)
        thread.failed.connect(on_failed)
        thread.finished_run.connect(on_finished)
        progress.canceled.connect(thread.cancel)

        self.statusBar().showMessage("Exporting…")
        self._append("")
        self._append(f"Export started: {total} row(s).")
        logger.info(
            "export started: %d row(s) into %r", total, self._config.output_root
        )
        self._export_thread = thread
        self._update_ready_state()
        thread.start()

    def _clear_export_thread(self) -> None:
        thread, self._export_thread = self._export_thread, None
        if thread is not None:
            thread.deleteLater()
        self._update_ready_state()

    def _show_summary(self, result: RunResult) -> None:
        plan = self._run_plan or self._plan
        assert plan is not None
        flags = flag_lines(plan, result)
        dialog = SummaryDialog(result, flags, total_skipped(plan, result), self)
        dialog.save_button.clicked.connect(lambda: self._save_log(result))
        dialog.exec()

    def _save_log(self, result: RunResult) -> None:
        plan = self._run_plan or self._plan
        assert plan is not None
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        root = self._config.output_root or str(Path.home())
        suggested = str(Path(root) / f"AutoFace-log-{stamp}.txt")
        name, _ = QFileDialog.getSaveFileName(
            self, "Save run log", suggested, "Text file (*.txt)"
        )
        if not name:
            self.statusBar().showMessage("Log not saved", 4000)
            return
        destination = Path(name)
        if destination.suffix.lower() != ".txt":
            destination = destination.with_suffix(".txt")
        try:
            destination.write_text(
                summarize_run(plan, result, self._config.output_root, timestamp),
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.critical(self, "Could not save log", str(exc))
            return
        self.statusBar().showMessage(f"Saved {destination.name}", 4000)

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    # -- updates -------------------------------------------------------
    def _start_update_check(self, interactive: bool = False) -> None:
        # Only an actually-running check blocks a new one. Testing the
        # attribute alone would wedge the menu item forever if a thread ever
        # failed to report that it had finished.
        if self._update_thread is not None and self._update_thread.isRunning():
            if interactive:
                self.statusBar().showMessage("Already checking for updates…", 4000)
            return

        thread = UpdateCheck(self)
        thread.checked.connect(
            lambda info: self._on_update_checked(info, interactive)
        )
        thread.finished.connect(self._clear_update_thread)
        # Parented to the window and held here, so nothing can be collected
        # while the check is in flight.
        self._update_thread = thread
        thread.start()

    def _clear_update_thread(self) -> None:
        thread, self._update_thread = self._update_thread, None
        if thread is not None:
            thread.deleteLater()

    def _on_update_checked(self, info: UpdateInfo | None, interactive: bool) -> None:
        if info is not None and info.available:
            logger.info(
                "update available: %s build %s (running %s build %s)",
                info.latest_version,
                info.latest_build_id,
                info.current_version,
                info.current_build_id,
            )
        if info is None:
            if interactive:
                QMessageBox.information(
                    self,
                    "Check for updates",
                    "Could not reach GitHub to check for updates.\n"
                    "AutoFace works fine offline — this only affects update checks.",
                )
            return
        if not info.available:
            if interactive:
                QMessageBox.information(
                    self, "Check for updates", f"AutoFace {__version__} is up to date."
                )
            return

        target = installer.current_executable()
        can_install = installer.can_install_in_place(target)

        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(
            f"AutoFace {info.latest_version} is available (you have {__version__})."
        )
        if can_install:
            box.setInformativeText(
                "AutoFace can download and install it for you, then restart. "
                "The new version is checked and tested before it replaces this one."
            )
        if info.notes:
            box.setDetailedText(info.notes)

        install = None
        if can_install:
            install = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
        open_page = box.addButton(
            "Open download page", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        if install is not None:
            box.setDefaultButton(install)
        box.exec()

        clicked = box.clickedButton()
        if install is not None and clicked is install:
            self._install_update(info, target)
        elif clicked is open_page:
            QDesktopServices.openUrl(QUrl(info.release_page or RELEASE_PAGE))

    def _install_update(self, info: UpdateInfo, target: Path) -> None:
        progress = QProgressDialog("Starting…", "Cancel", 0, 100, self)
        progress.setWindowTitle("Updating AutoFace")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)

        thread = UpdateInstall(info, target, self)

        def on_progress(received: int, total: int) -> None:
            if total > 0:
                progress.setMaximum(100)
                progress.setValue(int(received * 100 / total))
            else:
                progress.setMaximum(0)  # indeterminate
            progress.setLabelText(
                f"Downloading… {received / 1_048_576:.0f} of {total / 1_048_576:.0f} MB"
                if total
                else f"Downloading… {received / 1_048_576:.0f} MB"
            )

        def on_stage(text: str) -> None:
            progress.setLabelText(text)
            if not text.startswith("Downloading"):
                # Verifying and installing have no measurable progress.
                progress.setMaximum(0)

        def on_failed(message: str) -> None:
            progress.close()
            self._install_thread = None
            if message:  # empty means the user cancelled
                logger.error("update not installed: %s", message)
                QMessageBox.warning(self, "Update not installed", message)
            else:
                logger.info("update cancelled by the user")
                self.statusBar().showMessage("Update cancelled", 4000)

        def on_succeeded(path: str) -> None:
            progress.close()
            self._install_thread = None
            logger.info("update installed: %s -> %s", info.latest_version, path)
            answer = QMessageBox.question(
                self,
                "Update installed",
                f"AutoFace {info.latest_version} is installed.\n\n"
                "Restart now to use it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                # survived() deliberately waits a moment, so say why.
                self.statusBar().showMessage("Restarting AutoFace…")
                QApplication.processEvents()
                try:
                    process = installer.relaunch(Path(path))
                except OSError as exc:
                    QMessageBox.warning(
                        self,
                        "Could not restart",
                        "The update is installed — please start AutoFace again "
                        f"yourself.\n\n{exc}",
                    )
                    return
                if not installer.survived(process):
                    # Already installed, so this is not a failed update; the
                    # user just has to start it themselves.
                    QMessageBox.warning(
                        self,
                        "Could not restart",
                        "The update is installed, but the new version did not "
                        "stay running when it was started automatically.\n\n"
                        "Close AutoFace and start it again from "
                        f"{Path(path).name}.",
                    )
                    return
                self.close()
                QApplication.quit()

        thread.progress.connect(on_progress)
        thread.stage.connect(on_stage)
        thread.failed.connect(on_failed)
        thread.succeeded.connect(on_succeeded)
        progress.canceled.connect(thread.cancel)

        self._install_thread = thread
        thread.start()

    def closeEvent(self, event) -> None:
        """Never tear down a live worker: a QThread destroyed while running
        aborts the process, and an export worker is mid-COM-call in Inventor.
        """
        export = self._export_thread
        if export is not None and export.isRunning():
            answer = QMessageBox.question(
                self,
                "Export in progress",
                "An export is running. Stop after the current part and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            export.cancel()
            self.statusBar().showMessage("Finishing the current part…")
            QApplication.processEvents()
            # Cancellation lands between rows; one part can legitimately take
            # a while (a big Unfold, a busy-retry cycle), so wait generously.
            if not export.wait(120_000):
                self.statusBar().showMessage(
                    "Still exporting — try closing again when it finishes"
                )
                event.ignore()
                return

        # The remaining workers finish on their own in bounded time; a scan
        # or update check that will not die must still not be destroyed live.
        for thread in (
            self._update_thread,
            self._install_thread,
            self._scan_thread,
        ):
            if thread is not None and thread.isRunning():
                if hasattr(thread, "cancel"):
                    thread.cancel()
                if not thread.wait(15_000):
                    self.statusBar().showMessage(
                        "Waiting for a background task — try closing again "
                        "in a moment"
                    )
                    event.ignore()
                    return
        super().closeEvent(event)

    def about_rows(self) -> list[tuple[str, str]]:
        """Everything identifying this copy, for the About box and support."""
        rows = list(build_details())
        rows.append(("Qt", f"PySide6 {PySide6.__version__} / Qt {qVersion()}"))
        rows.append(("Updates", manifest_url()))
        return rows

    def _show_about(self) -> None:
        rows = self.about_rows()
        table = "".join(
            "<tr>"
            f"<td style='padding-right:14px; vertical-align:top'><b>{escape(label)}</b></td>"
            f"<td style='vertical-align:top'>{escape(value)}</td>"
            "</tr>"
            for label, value in rows
        )

        box = QMessageBox(self)
        box.setWindowTitle("About AutoFace")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<b>AutoFace {escape(__version__)}</b><br><br>"
            "Batch flat-pattern DWG exporter for Autodesk Inventor.<br>"
            "Walks the placed parts lists of your open drawings, exports each "
            "sheet metal part's flat pattern as a DWG, and files it by RUN and "
            "thickness.<br><br>"
            f"<table style='font-size:small'>{table}</table>"
        )
        copy = box.addButton("Copy details", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.exec()

        if box.clickedButton() is copy:
            # Plain text, so it can be pasted into an email when something is
            # wrong and the question is "which build are you on?".
            QApplication.clipboard().setText(
                "\n".join(f"{label}: {value}" for label, value in rows)
            )
            self.statusBar().showMessage("Build details copied to the clipboard", 4000)


def main(argv: list[str] | None = None) -> int:
    from ..runlog import setup as setup_runlog
    from ..version import describe

    setup_runlog(f"{describe()} — GUI session")
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AutoFace")
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    code = app.exec()
    logger.info("session closed (exit %d)", code)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
