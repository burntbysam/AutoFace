"""The scan → preview → export flow, driven offscreen over fake COM objects."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

# Must be set before any Qt GUI object exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from autoface.config import Config  # noqa: E402
from autoface.core.models import ModelKind, ScannedDrawing, ScannedRow  # noqa: E402
from autoface.gui import app as appmod  # noqa: E402
from autoface.inventor import com as inventor_com  # noqa: E402
from autoface.inventor import export as export_module  # noqa: E402
from autoface.inventor import scan as scan_module  # noqa: E402

from . import fakes  # noqa: E402

INCH = 2.54


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def pump(qapp, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def scanned_drawing():
    return ScannedDrawing(
        path="C:\\dwg\\8640-01101-I.idw",
        rows=(
            ScannedRow(
                item="1",
                part_number="PN-1",
                description="SHEET,AL,SMOOTH,.190,60X133.13",
                model_kind=ModelKind.SHEET_METAL,
                model_path="C:\\m\\p1.ipt",
                thickness_cm=0.190 * INCH,
                has_flat_pattern=True,
            ),
            ScannedRow(
                item="2",
                part_number="PN-2",
                description="BRACKET",
                model_kind=ModelKind.NOT_SHEET_METAL,
                model_path="C:\\m\\p2.ipt",
            ),
        ),
    )


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    """A window with an isolated config and no network or COM access."""
    config = Config(output_root=str(tmp_path / "out"))
    monkeypatch.setattr(appmod, "load_config", lambda: config)
    monkeypatch.setattr(appmod, "save_config", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "check_for_update", lambda *a, **k: None)
    win = appmod.MainWindow()
    win.test_config = config
    yield win
    win.close()
    pump(qapp, lambda: win._scan_thread is None and win._export_thread is None, 5)


def patch_com(monkeypatch, app):
    monkeypatch.setattr(inventor_com, "initialize_thread", lambda: None)
    monkeypatch.setattr(inventor_com, "uninitialize_thread", lambda: None)
    monkeypatch.setattr(inventor_com, "attach", lambda: app)


class TestScanFlow:
    def test_scan_populates_the_preview_table(self, qapp, window, monkeypatch):
        patch_com(monkeypatch, object())
        monkeypatch.setattr(
            scan_module, "scan_session", lambda app: [scanned_drawing()]
        )

        window._scan()
        assert pump(qapp, lambda: window._plan is not None), "scan never finished"

        assert window.preview.rowCount() == 2
        assert window.preview.item(0, 1).text() == "1"
        assert window.preview.item(0, 4).text() == "Export"
        assert (
            window.preview.item(0, 5).text() == "RUN 11\\1875\\8640-1101-1.dwg"
        )
        assert window.preview.item(1, 4).text() == "Skip: not sheet metal"
        assert window.export_button.isEnabled()

    def test_no_open_drawings_is_said_in_the_ui(self, qapp, window, monkeypatch):
        patch_com(monkeypatch, object())
        monkeypatch.setattr(scan_module, "scan_session", lambda app: [])
        seen: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            staticmethod(lambda *args, **kwargs: seen.append(args[2])),
        )

        window._scan()
        assert pump(qapp, lambda: bool(seen)), "no message shown"
        assert "No drawings" in seen[0]
        assert not window.export_button.isEnabled()

    def test_inventor_not_running_is_said_in_the_ui(self, qapp, window, monkeypatch):
        monkeypatch.setattr(inventor_com, "initialize_thread", lambda: None)
        monkeypatch.setattr(inventor_com, "uninitialize_thread", lambda: None)

        def not_running():
            raise inventor_com.InventorNotRunning("Inventor is not running.")

        monkeypatch.setattr(inventor_com, "attach", not_running)
        seen: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            staticmethod(lambda *args, **kwargs: seen.append(args[2])),
        )

        window._scan()
        assert pump(qapp, lambda: bool(seen)), "no message shown"
        assert "Inventor is not running" in seen[0]

    def test_export_disabled_without_an_output_folder(
        self, qapp, window, monkeypatch
    ):
        window.test_config.output_root = ""
        patch_com(monkeypatch, object())
        monkeypatch.setattr(
            scan_module, "scan_session", lambda app: [scanned_drawing()]
        )
        window._scan()
        assert pump(qapp, lambda: window._plan is not None)
        assert not window.export_button.isEnabled()


class TestPreviewSorting:
    def make_table(self, qapp, rows):
        from autoface.core.models import Classification, Plan, PlanRow
        from autoface.gui.widgets import PreviewTable

        plan_rows = tuple(
            PlanRow(
                drawing_path=f"C:\\dwg\\{drawing}.idw",
                drawing_label=drawing,
                item=item,
                part_number=part,
                description="",
                thickness_display=thickness,
                classification=Classification.EXPORT,
                target_relative=f"RUN 11\\125\\{drawing}-{item}.dwg",
            )
            for drawing, item, part, thickness in rows
        )
        table = PreviewTable()
        table.show_plan(Plan(rows=plan_rows))
        return table

    def column(self, table, index):
        return [table.item(row, index).text() for row in range(table.rowCount())]

    def test_scan_order_until_the_user_sorts(self, qapp):
        table = self.make_table(
            qapp,
            [
                ("8640-01101-I", "2", "PN-B", '0.125" (1/8")'),
                ("8640-01101-I", "1", "PN-A", '0.19" (3/16")'),
            ],
        )
        try:
            assert self.column(table, 1) == ["2", "1"]  # untouched
        finally:
            table.deleteLater()

    def test_item_numbers_sort_numerically_not_lexically(self, qapp):
        from PySide6.QtCore import Qt

        table = self.make_table(
            qapp,
            [
                ("D", "10", "PN", "—"),
                ("D", "2", "PN", "—"),
                ("D", "1A", "PN", "—"),
                ("D", "1", "PN", "—"),
            ],
        )
        try:
            table.sortItems(1, Qt.SortOrder.AscendingOrder)
            assert self.column(table, 1) == ["1", "1A", "2", "10"]
            table.sortItems(1, Qt.SortOrder.DescendingOrder)
            assert self.column(table, 1) == ["10", "2", "1A", "1"]
        finally:
            table.deleteLater()

    def test_thickness_sorts_by_value_with_unknown_last(self, qapp):
        from PySide6.QtCore import Qt

        table = self.make_table(
            qapp,
            [
                ("D", "1", "PN", '0.19" (3/16")'),
                ("D", "2", "PN", "—"),
                ("D", "3", "PN", '0.125" (1/8")'),
            ],
        )
        try:
            table.sortItems(3, Qt.SortOrder.AscendingOrder)
            assert self.column(table, 3) == ['0.125" (1/8")', '0.19" (3/16")', "—"]
        finally:
            table.deleteLater()

    def test_rows_travel_whole_when_sorted(self, qapp):
        from PySide6.QtCore import Qt

        table = self.make_table(
            qapp,
            [
                ("D", "2", "PN-of-2", "—"),
                ("D", "1", "PN-of-1", "—"),
            ],
        )
        try:
            table.sortItems(1, Qt.SortOrder.AscendingOrder)
            assert self.column(table, 2) == ["PN-of-1", "PN-of-2"]
        finally:
            table.deleteLater()

    def test_the_sort_survives_a_rescan(self, qapp):
        from PySide6.QtCore import Qt
        from autoface.core.models import Classification, Plan, PlanRow

        table = self.make_table(
            qapp,
            [
                ("D", "2", "PN", "—"),
                ("D", "1", "PN", "—"),
            ],
        )
        try:
            table.sortItems(1, Qt.SortOrder.AscendingOrder)
            refreshed = Plan(
                rows=tuple(
                    PlanRow(
                        drawing_path="C:\\dwg\\D.idw",
                        drawing_label="D",
                        item=item,
                        part_number="PN",
                        description="",
                        thickness_display="—",
                        classification=Classification.EXPORT,
                        target_relative=f"RUN 11\\125\\D-{item}.dwg",
                    )
                    for item in ("30", "4", "20")
                )
            )
            table.show_plan(refreshed)
            assert self.column(table, 1) == ["4", "20", "30"]
        finally:
            table.deleteLater()


class TestSummaryDialog:
    def test_skipped_count_matches_the_saved_log(self, qapp):
        from autoface.core.models import RunResult
        from autoface.gui.widgets import SummaryDialog

        dialog = SummaryDialog(RunResult(), [], skipped_total=5)
        try:
            assert "Skipped 5" in dialog.counts_label.text()
        finally:
            dialog.deleteLater()


class TestCloseGuard:
    def test_declining_the_close_question_keeps_the_window_open(
        self, qapp, window, monkeypatch
    ):
        from PySide6.QtCore import QThread

        class SlowWorker(QThread):
            def __init__(self):
                super().__init__()
                self._cancelled = False

            def cancel(self):
                self._cancelled = True

            def run(self):
                while not self._cancelled:
                    time.sleep(0.02)

        worker = SlowWorker()
        window._export_thread = worker
        worker.start()
        try:
            monkeypatch.setattr(
                QMessageBox,
                "question",
                staticmethod(
                    lambda *a, **k: QMessageBox.StandardButton.No
                ),
            )
            window.show()
            window.close()
            assert window.isVisible(), "close was not refused"
            assert worker.isRunning(), "the worker must not be torn down"
        finally:
            monkeypatch.setattr(
                QMessageBox,
                "question",
                staticmethod(
                    lambda *a, **k: QMessageBox.StandardButton.Yes
                ),
            )
            window.close()  # accepted: cancels and waits for the worker
            assert not worker.isRunning()
            window._export_thread = None


class TestFolderPersistence:
    def test_choosing_a_folder_saves_the_config(self, qapp, window, monkeypatch):
        saved: list[str] = []
        monkeypatch.setattr(
            appmod, "save_config", lambda config, *a, **k: saved.append(config.output_root)
        )
        monkeypatch.setattr(
            appmod.QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *args, **kwargs: "/somewhere/out"),
        )
        window._choose_folder()
        assert saved == [str(Path("/somewhere/out"))]
        assert window.folder_edit.text() == str(Path("/somewhere/out"))


class TestExportFlow:
    def test_export_writes_files_and_shows_the_summary(
        self, qapp, window, tmp_path, monkeypatch
    ):
        from autoface import runlog

        runlog.teardown()
        log_path = runlog.setup("gui test", directory=tmp_path / "AutoFace Logs")
        out_root = tmp_path / "out"
        window.test_config.output_root = str(out_root)

        # Scan over plain data, then export over a fake COM session whose
        # DataIO writes real files.
        drawing = ScannedDrawing(
            path=str(tmp_path / "8640-01101-I.idw"),
            rows=(
                ScannedRow(
                    item="1",
                    part_number="PN-1",
                    description="SHEET,AL,SMOOTH,.125,60X144",
                    model_kind=ModelKind.SHEET_METAL,
                    model_path="C:\\m\\p1.ipt",
                    thickness_cm=0.125 * INCH,
                    has_flat_pattern=True,
                ),
            ),
        )
        document = fakes.Document("C:\\m\\p1.ipt")
        fake_app = fakes.Application(in_session=[document])
        patch_com(monkeypatch, fake_app)
        monkeypatch.setattr(scan_module, "scan_session", lambda app: [drawing])

        summaries: list[tuple[int, int]] = []
        monkeypatch.setattr(
            appmod.MainWindow,
            "_show_summary",
            lambda self, result: summaries.append(
                (result.exported, result.failed)
            ),
        )

        window._scan()
        assert pump(qapp, lambda: window._plan is not None)
        assert window.export_button.isEnabled()

        window._export()
        assert pump(qapp, lambda: bool(summaries)), "export never finished"
        assert summaries == [(1, 0)]

        target = out_root / "RUN 11" / "125" / "8640-1101-1.dwg"
        assert target.exists()
        # After the run the preview is replanned: the file now on disk shows
        # as a name collision so a second run cannot overwrite it.
        assert pump(
            qapp,
            lambda: window.preview.item(0, 4) is not None
            and "collision" in window.preview.item(0, 4).text(),
        )

        # The quiet troubleshooting log recorded the full pick list and the run.
        runlog.teardown()
        log_text = log_path.read_text(encoding="utf-8")
        assert "found: 8640-01101-I item 1 (PN-1)" in log_text
        assert "export started: 1 row(s)" in log_text
        assert "row: 8640-01101-I item 1" in log_text
        assert "run summary:" in log_text
        assert "Exported: 1" in log_text

    def test_export_failure_is_reported_per_row_not_fatal(
        self, qapp, window, tmp_path, monkeypatch
    ):
        out_root = tmp_path / "out"
        window.test_config.output_root = str(out_root)
        drawing = ScannedDrawing(
            path=str(tmp_path / "8640-01101-I.idw"),
            rows=(
                ScannedRow(
                    item="1",
                    part_number="PN-1",
                    description="SHEET,AL,SMOOTH,.125,60X144",
                    model_kind=ModelKind.SHEET_METAL,
                    model_path="C:\\m\\bad.ipt",
                    thickness_cm=0.125 * INCH,
                    has_flat_pattern=False,
                ),
                ScannedRow(
                    item="2",
                    part_number="PN-2",
                    description="SHEET,AL,SMOOTH,.125,60X144",
                    model_kind=ModelKind.SHEET_METAL,
                    model_path="C:\\m\\good.ipt",
                    thickness_cm=0.125 * INCH,
                    has_flat_pattern=True,
                ),
            ),
        )
        bad = fakes.Document(
            "C:\\m\\bad.ipt", has_flat_pattern=False, unfold_error="cannot unfold"
        )
        good = fakes.Document("C:\\m\\good.ipt")
        fake_app = fakes.Application(in_session=[bad, good])
        patch_com(monkeypatch, fake_app)
        monkeypatch.setattr(scan_module, "scan_session", lambda app: [drawing])

        results: list = []
        monkeypatch.setattr(
            appmod.MainWindow,
            "_show_summary",
            lambda self, result: results.append(result),
        )

        window._scan()
        assert pump(qapp, lambda: window._plan is not None)
        window._export()
        assert pump(qapp, lambda: bool(results))

        result = results[0]
        assert result.failed == 1
        assert result.exported == 1
        assert (out_root / "RUN 11" / "125" / "8640-1101-2.dwg").exists()
        log_text = window.log.toPlainText()
        assert "cannot unfold" in log_text
