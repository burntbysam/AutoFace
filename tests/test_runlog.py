"""The quiet troubleshooting log: best-effort, daily files, pruned."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from autoface import runlog


@pytest.fixture(autouse=True)
def clean_handler():
    runlog.teardown()
    yield
    runlog.teardown()


def test_setup_creates_the_directory_and_daily_file(tmp_path):
    path = runlog.setup("test session", directory=tmp_path / "AutoFace Logs")
    assert path is not None
    assert path.parent.name == "AutoFace Logs"
    assert path.name.startswith("AutoFace-") and path.name.endswith(".log")
    runlog.logger.info("hello from the test")
    runlog.teardown()
    text = path.read_text(encoding="utf-8")
    assert "=== test session ===" in text
    assert "hello from the test" in text


def test_sessions_append_to_the_same_daily_file(tmp_path):
    directory = tmp_path / "AutoFace Logs"
    first = runlog.setup("first", directory=directory)
    runlog.teardown()
    second = runlog.setup("second", directory=directory)
    runlog.teardown()
    assert first == second
    text = first.read_text(encoding="utf-8")
    assert "=== first ===" in text and "=== second ===" in text


def test_log_dir_uses_the_windows_profile_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert runlog.log_dir() == tmp_path / "AutoFace Logs"


def test_log_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("USERPROFILE", raising=False)
    assert runlog.log_dir() == Path.home() / "AutoFace Logs"


def test_setup_soft_fails_when_the_directory_cannot_exist(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the directory should go", encoding="utf-8")
    assert runlog.setup("x", directory=blocker / "AutoFace Logs") is None
    runlog.logger.info("must not raise with no handler")  # NullHandler eats it


def test_old_logs_are_pruned(tmp_path):
    directory = tmp_path / "AutoFace Logs"
    directory.mkdir()
    stale = directory / "AutoFace-2020-01-01.log"
    stale.write_text("ancient", encoding="utf-8")
    old = time.time() - (runlog.RETENTION_DAYS + 5) * 86400
    os.utime(stale, (old, old))
    fresh = directory / "AutoFace-fresh.log"
    fresh.write_text("recent", encoding="utf-8")

    runlog.setup("prune test", directory=directory)
    assert not stale.exists()
    assert fresh.exists()


def test_unrelated_files_are_never_pruned(tmp_path):
    directory = tmp_path / "AutoFace Logs"
    directory.mkdir()
    keeper = directory / "notes.txt"
    keeper.write_text("mine", encoding="utf-8")
    old = time.time() - (runlog.RETENTION_DAYS + 5) * 86400
    os.utime(keeper, (old, old))
    runlog.setup("prune test", directory=directory)
    assert keeper.exists()
