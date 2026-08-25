"""Check for a newer AutoFace build.

The source is a small JSON manifest rather than the GitHub API. The API is rate
limited per IP (a shop behind one NAT can exhaust it between them) and its
"latest release" deliberately hides prereleases, so it is the wrong target for
"the current Windows build". CI republishes the manifest and the executable to
one fixed tag instead, and this polls that.

The manifest may live at an https URL or a plain path -- a UNC share such as
``\\\\server\\shared\\AutoFace\\latest.json`` is usually what a shop wants, since
it needs no GitHub access from the floor. Override with the
``AUTOFACE_UPDATE_URL`` environment variable.

Every failure is soft: a machine with no network must still start the app.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..version import build_id, run_number, version

REPO = "burntbysam/AutoFace"
# The tag CI republishes on every build. Explicit, because /releases/latest/
# excludes prereleases and would drift to any future tagged version.
RELEASE_TAG = "windows-latest-build"
RELEASE_PAGE = f"https://github.com/{REPO}/releases/tag/{RELEASE_TAG}"
DEFAULT_MANIFEST_URL = (
    f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/latest.json"
)
ENV_VAR = "AUTOFACE_UPDATE_URL"

TIMEOUT_SECONDS = 8
DOWNLOAD_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    current_build_id: str
    latest_version: str
    latest_build_id: str
    url: str
    sha256: str = ""
    size: int = 0
    notes: str = ""
    release_page: str = RELEASE_PAGE

    @property
    def available(self) -> bool:
        """Newer version, or the same version rebuilt by a later CI run."""
        latest, current = parse_version(self.latest_version), parse_version(
            self.current_version
        )
        if latest > current:
            return True
        if latest < current:
            return False
        return run_number(self.latest_build_id) > run_number(self.current_build_id)


def parse_version(text: str) -> tuple[int, ...]:
    """Turn ``v1.2.3`` into ``(1, 2, 3)``. Unparseable text sorts lowest."""
    parts: list[int] = []
    for chunk in str(text).strip().lstrip("vV").split("."):
        match = re.match(r"\d+", chunk.strip())
        if match is None:
            break
        parts.append(int(match.group(0)))
    return tuple(parts) if parts else (0,)


def manifest_url() -> str:
    return os.environ.get(ENV_VAR, "").strip() or DEFAULT_MANIFEST_URL


def _scheme(location: str) -> str:
    """The URL scheme, treating a Windows drive letter as no scheme at all.

    ``urlparse`` reads the ``C:`` of ``C:\\builds\\AutoFace.exe`` as a scheme.
    Any single letter is a drive, not a protocol -- getting this wrong rejects
    every local path on Windows, which is the only platform this runs on.
    """
    scheme = urlparse(str(location)).scheme.lower()
    return "" if len(scheme) < 2 else scheme


def is_remote(location: str) -> bool:
    return _scheme(location) in ("http", "https")


def _read_source(location: str, timeout: int) -> bytes:
    """Read an https URL or a local/UNC path."""
    if is_remote(location):
        request = urllib.request.Request(
            location, headers={"User-Agent": f"AutoFace/{version()}"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    return Path(location).read_bytes()


def check_for_update(url: str | None = None) -> UpdateInfo | None:
    """Return update information, or ``None`` when the check cannot complete."""
    location = url or manifest_url()
    try:
        payload = json.loads(_read_source(location, TIMEOUT_SECONDS).decode("utf-8"))
    except (
        urllib.error.URLError,
        ssl.SSLError,
        TimeoutError,
        ValueError,
        OSError,
    ):
        return None
    if not isinstance(payload, dict):
        return None

    latest_version = str(payload.get("version") or "").strip()
    download_url = str(payload.get("url") or "").strip()
    if not latest_version or not download_url:
        return None

    try:
        size = int(payload.get("size") or 0)
    except (TypeError, ValueError):
        size = 0

    return UpdateInfo(
        current_version=version(),
        current_build_id=build_id(),
        latest_version=latest_version,
        latest_build_id=str(payload.get("build_id") or ""),
        url=download_url,
        sha256=str(payload.get("sha256") or "").strip().lower(),
        size=size,
        notes=str(payload.get("notes") or "").strip(),
    )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class UpdateCancelled(Exception):
    """Raised when the user aborts a download."""


CHUNK = 256 * 1024


def _open_source(location: str, timeout: int):
    """Return ``(stream, total_bytes)`` for an https URL or a local/UNC path."""
    if is_remote(location):
        request = urllib.request.Request(
            location, headers={"User-Agent": f"AutoFace/{version()}"}
        )
        response = urllib.request.urlopen(request, timeout=timeout)
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        return response, total
    path = Path(location)
    return path.open("rb"), path.stat().st_size


def download_asset(
    info: UpdateInfo,
    destination: Path,
    on_progress=None,
    should_cancel=None,
) -> Path:
    """Download the new build and verify it before handing back the path.

    Streamed in chunks so a 50 MB download can report progress and be
    cancelled. A download that does not match the published checksum is
    deleted rather than left on disk where somebody might run it.
    """
    # Plain paths (empty scheme, UNC shares, Windows drive letters) are a
    # supported update source; a remote one must be encrypted.
    if _scheme(info.url) not in ("https", "file", ""):
        raise ValueError("refusing to download an update over a non-HTTPS URL")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    total = info.size or 0
    received = 0
    stream, stream_total = _open_source(info.url, DOWNLOAD_TIMEOUT_SECONDS)
    total = total or stream_total
    try:
        with destination.open("wb") as handle:
            while True:
                if should_cancel is not None and should_cancel():
                    raise UpdateCancelled()
                block = stream.read(CHUNK)
                if not block:
                    break
                handle.write(block)
                received += len(block)
                if on_progress is not None:
                    on_progress(received, total)
    except BaseException:
        # Never leave a partial or abandoned binary where it could be run.
        destination.unlink(missing_ok=True)
        raise
    finally:
        stream.close()

    if info.sha256:
        actual = sha256_of(destination)
        if actual != info.sha256:
            destination.unlink(missing_ok=True)
            raise ValueError(
                f"checksum mismatch: expected {info.sha256}, got {actual}"
            )
    return destination
