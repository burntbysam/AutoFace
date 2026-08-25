"""Update checking and installation."""

from . import installer
from .github import (
    DEFAULT_MANIFEST_URL,
    ENV_VAR,
    RELEASE_PAGE,
    UpdateCancelled,
    UpdateInfo,
    check_for_update,
    download_asset,
    is_remote,
    manifest_url,
    parse_version,
    sha256_of,
)

__all__ = [
    "DEFAULT_MANIFEST_URL",
    "ENV_VAR",
    "RELEASE_PAGE",
    "UpdateCancelled",
    "UpdateInfo",
    "check_for_update",
    "download_asset",
    "installer",
    "is_remote",
    "manifest_url",
    "parse_version",
    "sha256_of",
]
