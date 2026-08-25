"""Replace the running executable with a downloaded build.

A bad update is worse than no update: this tool's output goes to CAM. So a
downloaded binary is never swapped in until it has matched the published
SHA256 *and* passed its own ``--selftest``. A build that shipped a broken
naming rule would quietly file DWGs into the wrong RUN or thickness folder,
which no checksum can catch.

Windows will not let a running process overwrite its own image, but it will
let it be *renamed*. So the live exe is renamed aside, the new one takes its
place, and the stale copy is deleted on the next launch -- no helper script to
leave behind, and one rename to undo if the swap fails.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

BACKUP_SUFFIX = ".old"
STAGING_SUFFIX = ".new"
SELFTEST_TIMEOUT = 180

# Windows process-creation flags.
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_executable() -> Path | None:
    """The running .exe, or None when running from source."""
    if not is_frozen():
        return None
    try:
        return Path(sys.executable).resolve()
    except OSError:  # pragma: no cover - defensive
        return None


def can_install_in_place(target: Path | None = None) -> bool:
    """True when an in-place update is possible.

    False from a source checkout (there is no single file to replace) and
    false when the executable sits somewhere unwritable, such as Program Files
    without elevation -- in which case the download page is still offered.
    """
    target = target or current_executable()
    if target is None:
        return False
    return os.access(target.parent, os.W_OK)


def staging_path(target: Path) -> Path:
    """Where the download lands: beside the target, so the swap is a rename."""
    target = Path(target)
    return target.with_name(target.name + STAGING_SUFFIX)


def backup_path(target: Path) -> Path:
    return Path(target).with_name(Path(target).name + BACKUP_SUFFIX)


# How a onefile bootloader tells a second stage "do not extract, use this
# directory". Inherited by any child we spawn, which makes the child run the
# PARENT's unpacked code and then lose it when the parent exits and deletes
# that directory. Confirmed present in the bootloader with `strings`.
_BOOTLOADER_VARS = (
    "_MEIPASS2",
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_ARCHIVE_FILE",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_PYI_SPLASH_IPC",
)


def child_environment() -> dict[str, str]:
    """A copy of the environment safe to hand another frozen executable.

    Without this, launching AutoFace.exe from AutoFace.exe hands the child our
    own unpacked-bundle directory. The child skips extraction and runs our
    code; we then exit and delete that directory out from under it, and it dies
    mid-import on a missing base_library.zip. It also means a self-test of a
    downloaded build would silently execute the *running* build instead --
    passing while proving nothing.
    """
    env = dict(os.environ)
    for name in _BOOTLOADER_VARS:
        env.pop(name, None)

    # PyInstaller stashes the pre-launch loader paths; a child must get the
    # originals rather than our bundled libraries.
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        original = env.pop(name + "_ORIG", None)
        if original is not None:
            env[name] = original
        elif is_frozen():
            env.pop(name, None)
    return env


def make_executable(candidate: Path) -> None:
    """Restore the executable bit, which a download does not carry on POSIX.

    Windows infers executability from the extension, so this is a no-op there.
    """
    if os.name == "nt":
        return
    try:
        mode = candidate.stat().st_mode
        candidate.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def run_selftest(candidate: Path, timeout: int = SELFTEST_TIMEOUT) -> tuple[bool, str]:
    """Run the downloaded binary's own self-test. Never raises."""
    candidate = Path(candidate)
    make_executable(candidate)
    kwargs = {}
    if os.name == "nt":
        # Do not flash a console window in the user's face.
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        finished = subprocess.run(
            [str(candidate), "--selftest"],
            capture_output=True,
            timeout=timeout,
            # Without a scrubbed environment this would run OUR code, not the
            # downloaded build's, and pass without testing anything.
            env=child_environment(),
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run the downloaded build: {exc}"
    output = (finished.stdout or b"").decode("utf-8", "replace").strip()
    if finished.returncode != 0:
        detail = output or (finished.stderr or b"").decode("utf-8", "replace").strip()
        return False, detail or f"self-test exited {finished.returncode}"
    return True, output


def swap_in(candidate: Path, target: Path) -> Path:
    """Put ``candidate`` in ``target``'s place, returning the backup path.

    The rename is what makes this work while the target is running. If the
    second step fails the first is undone, so a failed update leaves a working
    application rather than none at all.
    """
    candidate, target = Path(candidate), Path(target)
    backup = backup_path(target)

    if backup.exists():
        try:
            backup.unlink()
        except OSError:
            # A previous copy may still be locked by an exiting process; the
            # rename below will fail cleanly if it truly cannot be replaced.
            pass

    target.rename(backup)
    try:
        candidate.replace(target)
    except OSError:
        backup.rename(target)
        raise
    return backup


def cleanup_backups(target: Path | None = None) -> None:
    """Delete the previous build left behind by an update. Never raises."""
    target = target or current_executable()
    if target is None:
        return
    for stale in (backup_path(target), staging_path(target)):
        try:
            if stale.exists():
                stale.unlink()
        except OSError:
            # Still locked, or not ours to remove. It is a few tens of MB and
            # the next launch will try again; failing here would be worse.
            pass


def relaunch(target: Path) -> subprocess.Popen:
    """Start the new build detached, so it survives this process exiting."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(
        [str(target)],
        close_fds=True,
        cwd=str(Path(target).parent),
        env=child_environment(),
        **kwargs,
    )


def survived(process: subprocess.Popen, seconds: float = 3.0) -> bool:
    """True when the relaunched build is still alive a moment later.

    Popen succeeding only means the process started. It can still die during
    start-up, and the update has already been applied by then, so it matters
    that we can tell the difference and say "installed, please start it again"
    rather than leaving the user with only a crash dialog.
    """
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return True
    except Exception:  # noqa: BLE001 - never let a check break the update
        return True
    return False
