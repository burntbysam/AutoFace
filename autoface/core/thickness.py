"""Thickness resolution: model parameter, description cross-check, folder label.

Two sources per part: the sheet metal Thickness parameter (centimeters — the
Inventor database length unit) and the thickness printed in the BOM
description (e.g. ``SHEET,AL,SMOOTH,.190,60X133.13``). Both are rounded to the
nearest 1/16". When they disagree, THE DESCRIPTION WINS for folder selection
and the row is flagged — that disagreement should never happen, the flag
exists so the user hears about it when it does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CM_PER_INCH = 2.54

# A description token that is a bare decimal under one inch, like ".190" or
# "0.1875". Dimension tokens ("60X133.13") and integers ("60") never match, so
# a width can't be mistaken for a thickness.
_THICKNESS_TOKEN = re.compile(r"^\d*\.\d+$")


def cm_to_inches(value_cm: float) -> float:
    return value_cm / CM_PER_INCH


def to_sixteenths(inches: float) -> int:
    """Round to the nearest 1/16", halves away from zero (0.09375 -> 2/16)."""
    return int(inches * 16 + 0.5)


def format_sixteenths(sixteenths: int) -> str:
    """A human fraction for the preview: 2 -> '1/8', 3 -> '3/16'."""
    numerator, denominator = sixteenths, 16
    while numerator % 2 == 0 and numerator and denominator > 1:
        numerator //= 2
        denominator //= 2
    if denominator == 1:
        return f'{numerator}"'
    return f'{numerator}/{denominator}"'


def looks_like_sheet_description(description: str) -> bool:
    """Whether the BOM description claims the part is sheet stock.

    Non-sheet rows (brackets, hardware, bus bar…) are routine in these BOMs
    and their skips are noise; a description that DOES claim sheet (a SHEET
    callout or a thickness token) on a part that turns out not to be sheet
    metal is an anomaly worth flagging.
    """
    text = str(description).upper()
    return "SHEET" in text or parse_description_thickness(description) is not None


def parse_description_thickness(description: str) -> float | None:
    """The thickness called out in a BOM description string, in inches.

    The first comma-separated token that is a bare decimal below one inch is
    taken as the thickness. Returns None when there is no such token, in which
    case the cross-check simply cannot run and the model parameter stands.
    """
    for token in str(description).split(","):
        token = token.strip()
        if _THICKNESS_TOKEN.match(token):
            try:
                value = float(token)
            except ValueError:  # pragma: no cover - regex already guarantees
                continue
            if 0 < value < 1:
                return value
    return None


class ThicknessTable:
    """The editable valid-thickness table from config.

    Keys are inches as decimal strings ("0.125"), values are folder labels
    ("125"). Matching happens on the nearest-1/16" grid, so ".190" and the
    0.1875 key land in the same cell. Adding a standard thickness is a config
    edit, not a code change.
    """

    def __init__(self, table: dict[str, str]) -> None:
        self._by_sixteenths: dict[int, str] = {}
        self.ignored: list[str] = []  # malformed keys, surfaced in the UI log
        for key, label in table.items():
            try:
                inches = float(str(key).strip())
            except ValueError:
                # A malformed key must not take the app down, but silently
                # dropping it would turn a config typo into mystery skips.
                self.ignored.append(str(key))
                continue
            self._by_sixteenths[to_sixteenths(inches)] = str(label)

    def label_for(self, sixteenths: int) -> str | None:
        return self._by_sixteenths.get(sixteenths)

    def __len__(self) -> int:
        return len(self._by_sixteenths)


@dataclass(frozen=True)
class ThicknessResolution:
    model_inches: float | None
    description_inches: float | None
    effective_sixteenths: int | None  # None when neither source gave a value
    mismatch: bool  # sources disagree on the 1/16" grid; description won

    @property
    def display(self) -> str:
        """Preview-table text, e.g ``0.190" (3/16")``."""
        source = (
            self.description_inches
            if self.mismatch and self.description_inches is not None
            else self.model_inches
        )
        if source is None and self.description_inches is not None:
            source = self.description_inches
        if source is None:
            return "—"
        text = f'{source:.4f}'.rstrip("0").rstrip(".")
        if self.effective_sixteenths is not None:
            return f'{text}" ({format_sixteenths(self.effective_sixteenths)})'
        return f'{text}"'


def resolve_thickness(
    thickness_cm: float | None, description: str
) -> ThicknessResolution:
    """Combine the model parameter and the description into one answer."""
    model_inches = cm_to_inches(thickness_cm) if thickness_cm is not None else None
    description_inches = parse_description_thickness(description)

    model_16 = to_sixteenths(model_inches) if model_inches is not None else None
    desc_16 = (
        to_sixteenths(description_inches) if description_inches is not None else None
    )

    if model_16 is not None and desc_16 is not None and model_16 != desc_16:
        return ThicknessResolution(model_inches, description_inches, desc_16, True)
    effective = model_16 if model_16 is not None else desc_16
    return ThicknessResolution(model_inches, description_inches, effective, False)
