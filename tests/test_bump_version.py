from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bump_version  # noqa: E402


class TestParse:
    def test_reads_three_parts(self):
        assert bump_version.parse("1.2.3") == (1, 2, 3)

    def test_tolerates_surrounding_whitespace(self):
        assert bump_version.parse(" 1.2.3\n") == (1, 2, 3)

    @pytest.mark.parametrize("text", ["1.2", "v1.2.3", "1.2.3.4", "", "abc"])
    def test_rejects_malformed(self, text):
        with pytest.raises(ValueError):
            bump_version.parse(text)


class TestBump:
    def test_patch_for_any_push(self):
        assert bump_version.bump((1, 0, 0), "patch") == (1, 0, 1)

    def test_minor_for_a_significant_feature(self):
        assert bump_version.bump((1, 0, 1), "minor") == (1, 1, 0)

    def test_major_for_an_overhaul(self):
        assert bump_version.bump((1, 1, 0), "major") == (2, 0, 0)

    def test_minor_resets_the_patch(self):
        assert bump_version.bump((1, 4, 9), "minor") == (1, 5, 0)

    def test_major_resets_both(self):
        assert bump_version.bump((1, 4, 9), "major") == (2, 0, 0)

    def test_double_digits_are_not_string_sorted(self):
        assert bump_version.bump((1, 9, 9), "patch") == (1, 9, 10)
        assert bump_version.bump((1, 9, 10), "minor") == (1, 10, 0)

    def test_unknown_level(self):
        with pytest.raises(ValueError):
            bump_version.bump((1, 0, 0), "sideways")


class TestRender:
    def test_round_trip(self):
        assert bump_version.render(bump_version.parse("2.10.4")) == "2.10.4"


class TestMain:
    def test_writes_the_file(self, tmp_path, monkeypatch, capsys):
        version_file = tmp_path / "VERSION"
        version_file.write_text("1.0.0\n", encoding="utf-8")
        monkeypatch.setattr(bump_version, "VERSION_FILE", version_file)

        assert bump_version.main(["patch"]) == 0
        assert version_file.read_text(encoding="utf-8") == "1.0.1\n"
        assert "1.0.0 -> 1.0.1" in capsys.readouterr().out

    def test_dry_run_changes_nothing(self, tmp_path, monkeypatch):
        version_file = tmp_path / "VERSION"
        version_file.write_text("1.0.0\n", encoding="utf-8")
        monkeypatch.setattr(bump_version, "VERSION_FILE", version_file)

        assert bump_version.main(["minor", "--dry-run"]) == 0
        assert version_file.read_text(encoding="utf-8") == "1.0.0\n"

    def test_malformed_version_file_is_an_error(self, tmp_path, monkeypatch):
        version_file = tmp_path / "VERSION"
        version_file.write_text("not a version", encoding="utf-8")
        monkeypatch.setattr(bump_version, "VERSION_FILE", version_file)

        assert bump_version.main(["patch"]) == 1

    def test_major_warns_that_it_needs_agreement(self, tmp_path, monkeypatch, capsys):
        version_file = tmp_path / "VERSION"
        version_file.write_text("1.0.0\n", encoding="utf-8")
        monkeypatch.setattr(bump_version, "VERSION_FILE", version_file)

        bump_version.main(["major"])
        assert "maintainer" in capsys.readouterr().err


class TestRepositoryVersion:
    def test_the_committed_version_is_well_formed(self):
        # A malformed VERSION would break the build stamp and the updater.
        assert bump_version.parse(
            (Path(__file__).resolve().parent.parent / "VERSION").read_text(
                encoding="utf-8"
            )
        )
