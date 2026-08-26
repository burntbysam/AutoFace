"""Plain data passed between the Inventor layer, the planner and the UI.

The COM layer produces ``ScannedDrawing``/``ScannedRow`` (facts read from the
session, no decisions), the planner turns them into ``PlanRow`` (one preview
table line each), and the export run produces ``RowOutcome``/``RunResult``.
Nothing in here may import COM or Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModelKind(Enum):
    """What a parts-list row resolved to."""

    SHEET_METAL = "sheet metal part"
    NOT_SHEET_METAL = "non-sheet-metal part"
    SUB_ASSEMBLY = "sub-assembly"
    NO_MODEL = "no resolvable model"


class Classification(Enum):
    """Preview-table outcome for one parts-list row.

    One case per outcome so that future versions can turn a skip into real
    handling (descending into sub-assemblies) by adding one branch.
    """

    EXPORT = "Export"
    SKIP_NOT_SHEET_METAL = "Skip: not sheet metal"
    SKIP_SUB_ASSEMBLY = "Skip: sub-assembly"
    SKIP_NO_MODEL = "Skip: no model"
    SKIP_INVALID_THICKNESS = "Skip: invalid thickness"
    SKIP_BAD_ITEM = "Skip: invalid item number"
    SKIP_NAME_COLLISION = "Skip: name collision"
    SKIP_UNPARSEABLE_DRAWING = "Skip: unparseable drawing name"

    @property
    def label(self) -> str:
        return self.value


@dataclass(frozen=True)
class ScannedRow:
    """One visible placed-parts-list row, exactly as the drawing prints it."""

    item: str
    part_number: str
    description: str
    model_kind: ModelKind
    model_path: str = ""
    thickness_cm: float | None = None  # Thickness parameter, database units (cm)
    has_flat_pattern: bool | None = None
    note: str = ""  # scan-time diagnostic, e.g. the resolution error text


@dataclass(frozen=True)
class ScannedDrawing:
    path: str  # full path of the .idw
    rows: tuple[ScannedRow, ...] = ()
    note: str = ""  # e.g. "no parts list found on any sheet"


@dataclass(frozen=True)
class PlanRow:
    """One line of the preview table; the unit of work for the export run."""

    drawing_path: str
    drawing_label: str  # filename stem, for display
    item: str
    part_number: str
    description: str
    thickness_display: str  # what the preview shows, e.g. '0.1875" (3/16)'
    classification: Classification
    target_relative: str = ""  # 'RUN 11\\1875\\8640-1101-1.dwg'
    target_path: str = ""  # absolute, empty when no output root was set
    model_path: str = ""
    has_flat_pattern: bool | None = None
    flags: tuple[str, ...] = ()  # informational, e.g. the thickness cross-check
    # Silent rows still show in the preview but stay out of the end-of-run
    # skip count and flag list: a skip that is entirely expected (a BOM row
    # whose description never claimed to be sheet) is noise, not news.
    silent: bool = False


@dataclass(frozen=True)
class Plan:
    rows: tuple[PlanRow, ...] = ()
    drawing_notes: tuple[str, ...] = ()  # drawing-level flags

    @property
    def exportable(self) -> tuple[PlanRow, ...]:
        return tuple(
            row for row in self.rows if row.classification is Classification.EXPORT
        )


@dataclass(frozen=True)
class RowOutcome:
    """What actually happened to one plan row during the export run."""

    row: PlanRow
    status: str  # "exported" | "skipped" | "failed"
    detail: str = ""  # reason / error text for skipped and failed rows

    @property
    def line(self) -> str:
        base = f"{self.row.drawing_label} item {self.row.item}"
        if self.row.part_number:
            base += f" ({self.row.part_number})"
        if self.status == "exported":
            return f"{base}: exported {self.row.target_relative}"
        return f"{base}: {self.detail or self.status}"


@dataclass
class RunResult:
    outcomes: list[RowOutcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # run-level messages

    @property
    def exported(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "exported")

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")
