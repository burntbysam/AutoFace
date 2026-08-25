"""Everything decidable without Inventor: naming, thickness, classification.

The COM layer reads Inventor state into the plain dataclasses in ``models``;
this package turns them into an export plan and, after a run, a summary. It
must stay importable and testable on any platform.
"""

from .models import (
    Classification,
    ModelKind,
    Plan,
    PlanRow,
    RowOutcome,
    RunResult,
    ScannedDrawing,
    ScannedRow,
)
from .naming import DrawingName, export_filename, parse_drawing_name, relative_target
from .pipeline import build_plan
from .summary import summarize_run
from .thickness import ThicknessTable, parse_description_thickness, resolve_thickness

__all__ = [
    "Classification",
    "DrawingName",
    "ModelKind",
    "Plan",
    "PlanRow",
    "RowOutcome",
    "RunResult",
    "ScannedDrawing",
    "ScannedRow",
    "ThicknessTable",
    "build_plan",
    "export_filename",
    "parse_description_thickness",
    "parse_drawing_name",
    "relative_target",
    "resolve_thickness",
    "summarize_run",
]
