"""The naming and folder scheme.

Drawing filenames look like ``8640-01101-I``: job, assembly with leading
zeros, and a trailing suffix that is dropped entirely. Both transformations
(zero-stripping and suffix-dropping) are intentional and confirmed with the
user — do not "fix" them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath

# job: anything without a dash; assembly: digits only (it gets zero-stripped
# and sliced for the RUN folder); suffix: whatever remains, dropped.
_DRAWING_NAME = re.compile(r"^(?P<job>[^-]+)-(?P<assy>\d+)-(?P<suffix>.+)$")

# Characters Windows refuses in file names; an item number containing one
# cannot become a filename and the row is flagged instead.
_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class DrawingName:
    job: str
    assembly: str  # leading zeros stripped: "01101" -> "1101"
    run: str  # first two digits of the stripped assembly: "1101" -> "11"

    @property
    def run_folder(self) -> str:
        return f"RUN {self.run}"


def parse_drawing_name(path_or_name: str) -> DrawingName | None:
    """Parse ``{job}-{assy}-{suffix}`` from a drawing path or file name.

    Returns None when the name does not match — the caller shows the drawing's
    rows as "Skip: unparseable drawing name" rather than guessing.
    """
    stem = PureWindowsPath(str(path_or_name)).stem
    match = _DRAWING_NAME.match(stem)
    if match is None:
        return None
    assembly = match.group("assy").lstrip("0")
    if not assembly:  # "0000" strips to nothing; there is no assembly number
        return None
    return DrawingName(job=match.group("job"), assembly=assembly, run=assembly[:2])


def clean_item(item: str) -> str | None:
    """The item number as a filename component, or None when it cannot be one.

    Taken as-is from the placed parts list (no zero padding, no reformatting);
    only surrounding whitespace is dropped.
    """
    text = str(item).strip()
    if not text or _BAD_FILENAME_CHARS.search(text):
        return None
    return text


def export_filename(name: DrawingName, item: str) -> str:
    return f"{name.job}-{name.assembly}-{item}.dwg"


def relative_target(name: DrawingName, thickness_label: str, item: str) -> str:
    """Path under the output root: ``RUN 11\\1875\\8640-1101-1.dwg``."""
    return "\\".join([name.run_folder, thickness_label, export_filename(name, item)])
