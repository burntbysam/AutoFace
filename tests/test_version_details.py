from __future__ import annotations

import json
import sys

import pytest

from autoface import version as version_module


@pytest.fixture
def stamped(tmp_path, monkeypatch):
    """Pretend to be a CI build, the way build_info.json makes it."""
    (tmp_path / "VERSION").write_text("2.3.4\n", encoding="utf-8")
    (tmp_path / "build_info.json").write_text(
        json.dumps(
            {"version": "2.3.4", "build_id": "42.abcdef1", "commit": "abcdef1234567890"}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(version_module, "_bundle_dir", lambda: tmp_path)
    version_module.version.cache_clear()
    version_module.build_info.cache_clear()
    yield tmp_path
    version_module.version.cache_clear()
    version_module.build_info.cache_clear()


@pytest.fixture
def unstamped(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("2.3.4\n", encoding="utf-8")
    monkeypatch.setattr(version_module, "_bundle_dir", lambda: tmp_path)
    version_module.version.cache_clear()
    version_module.build_info.cache_clear()
    yield tmp_path
    version_module.version.cache_clear()
    version_module.build_info.cache_clear()


def as_dict(rows):
    return dict(rows)


class TestBuildDetailsStamped:
    def test_reports_the_ci_build_number(self, stamped):
        assert as_dict(version_module.build_details())["Build"] == "42.abcdef1"

    def test_reports_the_version(self, stamped):
        assert as_dict(version_module.build_details())["Version"] == "2.3.4"

    def test_reports_the_commit_short(self, stamped):
        assert as_dict(version_module.build_details())["Commit"] == "abcdef123456"

    def test_is_recognised_as_a_ci_build(self, stamped):
        assert version_module.is_ci_build() is True


class TestBuildDetailsUnstamped:
    def test_says_the_build_is_local(self, unstamped):
        assert "local" in as_dict(version_module.build_details())["Build"]

    def test_omits_the_commit_rather_than_showing_a_blank(self, unstamped):
        assert "Commit" not in as_dict(version_module.build_details())

    def test_is_not_a_ci_build(self, unstamped):
        assert version_module.is_ci_build() is False


class TestBuildDetailsAlways:
    def test_python_version_is_reported(self):
        assert as_dict(version_module.build_details())["Python"].count(".") >= 1

    def test_says_where_it_is_running_from(self):
        assert as_dict(version_module.build_details())["Installed"] == (
            "running from source"
        )

    def test_reports_the_executable_path_when_frozen(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert as_dict(version_module.build_details())["Installed"] == str(
            __import__("pathlib").Path(sys.executable)
        )

    def test_labels_are_unique(self):
        labels = [label for label, _ in version_module.build_details()]
        assert len(labels) == len(set(labels))

    def test_every_value_is_a_non_empty_string(self):
        for label, value in version_module.build_details():
            assert isinstance(value, str) and value, label
