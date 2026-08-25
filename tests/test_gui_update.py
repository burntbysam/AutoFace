"""The update check must actually run, and must keep working after the first.

Regression cover for a bug where "Check for updates" appeared to do nothing:
the worker object was a local with no retained reference, so Python collected
it before the thread could call it. The check never ran, the thread never
finished, and the in-flight guard then blocked every later attempt forever.
"""

from __future__ import annotations

import os
import time

import pytest

# Must be set before any Qt GUI object exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autoface.gui import app as appmod  # noqa: E402
from autoface.updater.github import UpdateInfo  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def window(qapp, monkeypatch):
    """A window whose update check is instrumented and never touches the network."""
    calls: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        appmod.MainWindow,
        "_on_update_checked",
        lambda self, info, interactive: calls.append((info, interactive)),
    )
    win = appmod.MainWindow()
    win.calls = calls
    yield win
    win.close()


def pump(qapp, predicate, timeout=10.0):
    """Spin the event loop until predicate holds, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def offline(monkeypatch):
    monkeypatch.setattr(appmod, "check_for_update", lambda *a, **k: None)


def available(monkeypatch):
    info = UpdateInfo(
        current_version="1.0.0",
        current_build_id="1.aaaaaaa",
        latest_version="1.0.0",
        latest_build_id="9.bbbbbbb",
        url="https://example.invalid/AutoFace.exe",
    )
    monkeypatch.setattr(appmod, "check_for_update", lambda *a, **k: info)
    return info


class TestAutomaticCheck:
    def test_runs_on_launch(self, qapp, monkeypatch):
        offline(monkeypatch)
        calls: list = []
        monkeypatch.setattr(
            appmod.MainWindow,
            "_on_update_checked",
            lambda self, info, interactive: calls.append((info, interactive)),
        )
        win = appmod.MainWindow()
        try:
            assert pump(qapp, lambda: len(calls) >= 1), "startup check never reported"
            assert calls[0][1] is False  # not interactive
        finally:
            win.close()

    def test_thread_is_released_afterwards(self, qapp, window, monkeypatch):
        offline(monkeypatch)
        assert pump(qapp, lambda: window._update_thread is None), (
            "the thread never finished, which wedges every later check"
        )


class TestInteractiveCheck:
    def test_menu_check_reports_a_result(self, qapp, window, monkeypatch):
        offline(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)
        window.calls.clear()

        window._start_update_check(interactive=True)
        assert pump(qapp, lambda: any(c[1] for c in window.calls)), (
            "Check for updates did nothing"
        )

    def test_can_be_used_repeatedly(self, qapp, window, monkeypatch):
        offline(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)

        for attempt in range(3):
            window.calls.clear()
            window._start_update_check(interactive=True)
            assert pump(qapp, lambda: any(c[1] for c in window.calls)), (
                f"check {attempt + 1} did nothing"
            )
            pump(qapp, lambda: window._update_thread is None)

    def test_passes_the_update_through(self, qapp, window, monkeypatch):
        info = available(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)
        window.calls.clear()

        window._start_update_check(interactive=True)
        assert pump(qapp, lambda: any(c[1] for c in window.calls))
        delivered = [call for call in window.calls if call[1]][0][0]
        assert delivered is info
        assert delivered.available is True

    def test_a_second_check_while_one_runs_is_ignored_not_wedged(
        self, qapp, window, monkeypatch
    ):
        offline(monkeypatch)
        pump(qapp, lambda: window._update_thread is None)

        window._start_update_check(interactive=True)
        window._start_update_check(interactive=True)  # must not raise or deadlock
        assert pump(qapp, lambda: window._update_thread is None)
        # And the menu still works afterwards.
        window.calls.clear()
        window._start_update_check(interactive=True)
        assert pump(qapp, lambda: any(c[1] for c in window.calls))


class TestShutdown:
    def test_closing_during_a_check_does_not_hang(self, qapp, monkeypatch):
        offline(monkeypatch)
        win = appmod.MainWindow()
        win.show()
        win.close()  # must return promptly even with a check in flight
        assert pump(qapp, lambda: True)


class TestInstallThread:
    """UpdateInstall is the code that can leave a machine with no working app."""

    def local_update(self, tmp_path, payload=b"NEW BUILD"):
        source = tmp_path / "published.exe"
        source.write_bytes(payload)
        from autoface.updater.github import sha256_of

        return UpdateInfo(
            current_version="1.0.0",
            current_build_id="1.aaaaaaa",
            latest_version="1.1.0",
            latest_build_id="9.bbbbbbb",
            url=str(source),
            sha256=sha256_of(source),
            size=len(payload),
        )

    def drive(self, qapp, thread):
        done: list[tuple[str, str]] = []
        thread.succeeded.connect(lambda path: done.append(("ok", path)))
        thread.failed.connect(lambda message: done.append(("fail", message)))
        thread.start()
        pump(qapp, lambda: bool(done), timeout=30)
        pump(qapp, lambda: not thread.isRunning(), timeout=10)
        return done

    def test_installs_a_good_build(self, qapp, tmp_path, monkeypatch):
        target = tmp_path / "AutoFace.exe"
        target.write_bytes(b"OLD BUILD")
        monkeypatch.setattr(
            appmod.installer, "run_selftest", lambda *a, **k: (True, "SELF-TEST PASSED")
        )

        thread = appmod.UpdateInstall(self.local_update(tmp_path), target)
        done = self.drive(qapp, thread)

        assert done and done[0][0] == "ok", done
        assert target.read_bytes() == b"NEW BUILD"

    def test_refuses_a_build_that_fails_its_selftest(self, qapp, tmp_path, monkeypatch):
        target = tmp_path / "AutoFace.exe"
        target.write_bytes(b"OLD BUILD")
        monkeypatch.setattr(
            appmod.installer, "run_selftest", lambda *a, **k: (False, "rules missing")
        )

        thread = appmod.UpdateInstall(self.local_update(tmp_path), target)
        done = self.drive(qapp, thread)

        assert done and done[0][0] == "fail"
        # The working copy must be untouched, and the reject cleaned away.
        assert target.read_bytes() == b"OLD BUILD"
        assert not appmod.installer.staging_path(target).exists()

    def test_a_corrupt_download_never_reaches_the_selftest(
        self, qapp, tmp_path, monkeypatch
    ):
        target = tmp_path / "AutoFace.exe"
        target.write_bytes(b"OLD BUILD")
        info = self.local_update(tmp_path)
        bad = UpdateInfo(
            current_version=info.current_version,
            current_build_id=info.current_build_id,
            latest_version=info.latest_version,
            latest_build_id=info.latest_build_id,
            url=info.url,
            sha256="00" * 32,
            size=info.size,
        )
        ran = []
        monkeypatch.setattr(
            appmod.installer,
            "run_selftest",
            lambda *a, **k: (ran.append(1), (True, ""))[1],
        )

        done = self.drive(qapp, appmod.UpdateInstall(bad, target))
        assert done and done[0][0] == "fail"
        assert "checksum" in done[0][1]
        assert not ran, "a corrupt download must not be executed"
        assert target.read_bytes() == b"OLD BUILD"

    def test_cancelling_leaves_the_current_build_alone(self, qapp, tmp_path):
        target = tmp_path / "AutoFace.exe"
        target.write_bytes(b"OLD BUILD")

        thread = appmod.UpdateInstall(self.local_update(tmp_path), target)
        thread.cancel()
        done = self.drive(qapp, thread)

        assert done and done[0][0] == "fail"
        assert done[0][1] == ""  # empty message means cancelled, not an error
        assert target.read_bytes() == b"OLD BUILD"


class TestAboutDetails:
    def test_includes_build_and_environment(self, qapp, window):
        rows = dict(window.about_rows())
        for expected in ("Version", "Build", "Installed", "Python", "Qt", "Updates"):
            assert expected in rows, f"About is missing {expected}"

    def test_reports_the_update_source(self, qapp, window):
        # A shop pointed at a UNC share needs to see that, not the default.
        assert "latest.json" in dict(window.about_rows())["Updates"]

    def test_qt_row_names_both_bindings_and_toolkit(self, qapp, window):
        qt = dict(window.about_rows())["Qt"]
        assert "PySide6" in qt and "Qt" in qt

    def test_rows_are_copyable_as_plain_text(self, qapp, window):
        text = "\n".join(f"{k}: {v}" for k, v in window.about_rows())
        assert "Version:" in text and "Build:" in text
