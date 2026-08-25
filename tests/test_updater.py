from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from autoface.updater import github
from autoface.updater.github import (
    ENV_VAR,
    UpdateInfo,
    check_for_update,
    download_asset,
    manifest_url,
    parse_version,
    sha256_of,
)


def info(**overrides) -> UpdateInfo:
    base = dict(
        current_version="1.0.0",
        current_build_id="10.aaaaaaa",
        latest_version="1.0.0",
        latest_build_id="10.aaaaaaa",
        url="https://example.invalid/AutoFace.exe",
    )
    base.update(overrides)
    return UpdateInfo(**base)


class TestParseVersion:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1.0.0", (1, 0, 0)),
            ("v1.2.3", (1, 2, 3)),
            (" 1.10.0 ", (1, 10, 0)),
            ("1.0.0-beta", (1, 0, 0)),
        ],
    )
    def test_parsing(self, text, expected):
        assert parse_version(text) == expected

    def test_ordering_is_numeric_not_lexicographic(self):
        assert parse_version("1.10.0") > parse_version("1.9.0")

    def test_garbage_sorts_lowest(self):
        assert parse_version("nightly") == (0,)


class TestAvailability:
    def test_newer_version(self):
        assert info(latest_version="1.1.0").available is True

    def test_older_version(self):
        assert info(latest_version="0.9.0").available is False

    def test_identical_build_is_not_available(self):
        assert info().available is False

    def test_same_version_rebuilt_by_a_later_run_is_available(self):
        # The point of build_id: a fix shipped without a version bump must
        # still reach the shop floor.
        assert info(latest_build_id="11.bbbbbbb").available is True

    def test_same_version_earlier_run_is_not_available(self):
        assert info(latest_build_id="9.bbbbbbb").available is False

    def test_newer_version_wins_over_a_lower_run_number(self):
        assert info(latest_version="2.0.0", latest_build_id="1.ccccccc").available is True


class TestManifestUrl:
    def test_defaults_to_the_stable_tag(self):
        assert "windows-latest-build/latest.json" in manifest_url()

    def test_environment_override(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, r"\\server\share\AutoFace\latest.json")
        assert manifest_url() == r"\\server\share\AutoFace\latest.json"

    def test_blank_override_falls_back(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "   ")
        assert "windows-latest-build" in manifest_url()


class TestCheckForUpdate:
    def test_reads_a_manifest_from_a_local_path(self, tmp_path):
        manifest = tmp_path / "latest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": "2.0.0",
                    "build_id": "42.abcdef1",
                    "sha256": "ab" * 32,
                    "size": 123,
                    "url": "https://example.invalid/AutoFace.exe",
                    "notes": "what changed",
                }
            ),
            encoding="utf-8",
        )
        result = check_for_update(str(manifest))
        assert result.latest_version == "2.0.0"
        assert result.latest_build_id == "42.abcdef1"
        assert result.size == 123
        assert result.notes == "what changed"
        assert result.available is True

    def test_missing_file_returns_none(self, tmp_path):
        assert check_for_update(str(tmp_path / "absent.json")) is None

    def test_malformed_json_returns_none(self, tmp_path):
        manifest = tmp_path / "latest.json"
        manifest.write_text("{not json", encoding="utf-8")
        assert check_for_update(str(manifest)) is None

    def test_manifest_without_a_url_returns_none(self, tmp_path):
        manifest = tmp_path / "latest.json"
        manifest.write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
        assert check_for_update(str(manifest)) is None

    def test_network_failure_returns_none(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError("offline")

        monkeypatch.setattr(github.urllib.request, "urlopen", boom)
        assert check_for_update("https://example.invalid/latest.json") is None


class TestSchemeDetection:
    """A Windows drive letter must not be mistaken for a URL scheme.

    urlparse reads the ``C:`` of ``C:\\builds\\AutoFace.exe`` as scheme ``c``.
    Treating that as a protocol rejects every local path on Windows -- which is
    the only platform this ships on, and exactly where the UNC update source is
    meant to work. These run identically on any OS.
    """

    @pytest.mark.parametrize(
        "location",
        [
            "C:/Users/sam/AutoFace.exe",
            r"C:\builds\AutoFace.exe",
            r"\\server\share\AutoFace\latest.json",
            "/home/sam/AutoFace.exe",
            "relative/path.json",
        ],
    )
    def test_local_paths_are_not_remote(self, location):
        assert github.is_remote(location) is False

    @pytest.mark.parametrize(
        "location", ["https://example.invalid/a.exe", "http://example.invalid/a.exe"]
    )
    def test_urls_are_remote(self, location):
        assert github.is_remote(location) is True


class TestDownloadAsset:
    @pytest.mark.parametrize(
        "url", ["C:/builds/AutoFace.exe", r"\\server\share\AutoFace.exe"]
    )
    def test_local_and_unc_sources_are_permitted(self, url):
        # Regression: these raised "non-HTTPS URL" on Windows only.
        try:
            download_asset(info(url=url), Path("unused"))
        except ValueError as exc:
            assert "non-HTTPS" not in str(exc)
        except OSError:
            pass  # the path does not exist; the scheme check is what matters

    def test_rejects_non_https(self, tmp_path):
        with pytest.raises(ValueError):
            download_asset(
                info(url="http://example.invalid/a.exe"), tmp_path / "a.exe"
            )

    def test_verifies_the_checksum(self, tmp_path):
        source = tmp_path / "source.exe"
        source.write_bytes(b"payload")
        destination = tmp_path / "downloaded.exe"
        good = download_asset(
            info(url=str(source), sha256=sha256_of(source)), destination
        )
        assert good.read_bytes() == b"payload"

    def test_reports_progress(self, tmp_path):
        source = tmp_path / "source.exe"
        payload = b"x" * (github.CHUNK * 3 + 17)
        source.write_bytes(payload)
        seen: list[tuple[int, int]] = []

        github.download_asset(
            info(url=str(source), size=len(payload)),
            tmp_path / "out.exe",
            on_progress=lambda got, total: seen.append((got, total)),
        )
        assert len(seen) > 1, "a 50 MB download must report more than once"
        assert seen[-1][0] == len(payload)
        assert all(total == len(payload) for _, total in seen)

    def test_progress_is_monotonic(self, tmp_path):
        source = tmp_path / "source.exe"
        source.write_bytes(b"y" * (github.CHUNK * 4))
        seen: list[int] = []
        github.download_asset(
            info(url=str(source)),
            tmp_path / "out.exe",
            on_progress=lambda got, total: seen.append(got),
        )
        assert seen == sorted(seen)

    def test_cancellation_stops_and_leaves_nothing_behind(self, tmp_path):
        source = tmp_path / "source.exe"
        source.write_bytes(b"z" * (github.CHUNK * 8))
        destination = tmp_path / "out.exe"

        with pytest.raises(github.UpdateCancelled):
            github.download_asset(
                info(url=str(source)),
                destination,
                should_cancel=lambda: True,
            )
        # A half-written binary must never be left where it could be run.
        assert not destination.exists()

    def test_a_failed_download_leaves_nothing_behind(self, tmp_path, monkeypatch):
        source = tmp_path / "source.exe"
        source.write_bytes(b"w" * github.CHUNK * 2)
        destination = tmp_path / "out.exe"

        def explode(*args, **kwargs):
            raise OSError("connection reset")

        monkeypatch.setattr(github, "_open_source", explode)
        with pytest.raises(OSError):
            github.download_asset(info(url=str(source)), destination)
        assert not destination.exists()

    def test_a_mismatched_download_is_deleted(self, tmp_path):
        source = tmp_path / "source.exe"
        source.write_bytes(b"payload")
        destination = tmp_path / "downloaded.exe"
        with pytest.raises(ValueError, match="checksum mismatch"):
            download_asset(info(url=str(source), sha256="00" * 32), destination)
        # A binary that failed verification must not be left where it could run.
        assert not destination.exists()
