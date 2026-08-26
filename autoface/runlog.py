r"""The quiet troubleshooting log: %USERPROFILE%\AutoFace Logs.

Every session appends to a daily file (``AutoFace-2026-08-26.log``) so
"send me today's log" is the whole support workflow. Everything here is
best-effort: a locked directory, a full disk, or a hostile profile must
never take the app down — the log simply goes missing.

This is separate from the end-of-run summary the user explicitly saves
next to the exports; that one is theirs, this one is for troubleshooting.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

LOG_DIR_NAME = "AutoFace Logs"
RETENTION_DAYS = 60

logger = logging.getLogger("autoface")
# Without a real handler nothing must leak to stderr (the GUI has none).
logger.addHandler(logging.NullHandler())
logger.setLevel(logging.INFO)
logger.propagate = False

_handler: logging.FileHandler | None = None


def log_dir() -> Path:
    profile = os.environ.get("USERPROFILE", "").strip()
    base = Path(profile) if profile else Path.home()
    return base / LOG_DIR_NAME


def setup(context: str, directory: Path | None = None) -> Path | None:
    """Attach the daily log file and stamp the session. Soft-fails to None."""
    global _handler
    try:
        directory = Path(directory) if directory else log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"AutoFace-{datetime.now():%Y-%m-%d}.log"
        if _handler is None:
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s")
            )
            logger.addHandler(handler)
            _handler = handler
        _prune(directory)
        logger.info("=== %s ===", context)
        return path
    except OSError:
        return None


def teardown() -> None:
    """Detach the file handler (tests, and defensive re-setup)."""
    global _handler
    if _handler is not None:
        logger.removeHandler(_handler)
        try:
            _handler.close()
        except OSError:
            pass
        _handler = None


def _prune(directory: Path) -> None:
    """Delete log files past retention. Never raises."""
    cutoff = time.time() - RETENTION_DAYS * 86400
    try:
        for stale in directory.glob("AutoFace-*.log"):
            try:
                if stale.stat().st_mtime < cutoff:
                    stale.unlink()
            except OSError:
                continue
    except OSError:
        pass
