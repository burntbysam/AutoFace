"""Thickness: units, rounding, description parsing, and the cross-check rule."""

import pytest

from autoface.core.thickness import (
    ThicknessTable,
    cm_to_inches,
    format_sixteenths,
    parse_description_thickness,
    resolve_thickness,
    to_sixteenths,
)

INCH = 2.54  # Inventor database length units are centimeters

TABLE = ThicknessTable({"0.125": "125", "0.1875": "1875"})


def test_cm_to_inches_is_exact():
    assert cm_to_inches(2.54) == 1.0
    assert cm_to_inches(0.3175) == pytest.approx(0.125)


def test_rounding_to_sixteenths():
    assert to_sixteenths(0.125) == 2
    assert to_sixteenths(0.1875) == 3
    assert to_sixteenths(0.190) == 3  # .190 is a 3/16 sheet
    assert to_sixteenths(0.118) == 2  # 3 mm plate reads as 1/8
    assert to_sixteenths(0.25) == 4


def test_format_sixteenths():
    assert format_sixteenths(2) == '1/8"'
    assert format_sixteenths(3) == '3/16"'
    assert format_sixteenths(4) == '1/4"'
    assert format_sixteenths(16) == '1"'


def test_description_parsing_spec_example():
    assert parse_description_thickness("SHEET,AL,SMOOTH,.190,60X133.13") == 0.190


def test_description_parsing_variants():
    assert parse_description_thickness("SHEET,AL,SMOOTH,0.125,60X144") == 0.125
    # Dimensions and integers never read as a thickness.
    assert parse_description_thickness("SHEET,AL,60X133.13") is None
    assert parse_description_thickness("SHEET,AL,60,144") is None
    assert parse_description_thickness("") is None
    assert parse_description_thickness("BRACKET, STEEL") is None
    # Values of an inch or more are not sheet thickness callouts.
    assert parse_description_thickness("PLATE,AL,1.25,10X10") is None


def test_table_lookup_on_the_sixteenth_grid():
    assert TABLE.label_for(2) == "125"
    assert TABLE.label_for(3) == "1875"
    assert TABLE.label_for(4) is None


def test_table_ignores_malformed_keys():
    table = ThicknessTable({"not-a-number": "999", "0.125": "125"})
    assert len(table) == 1
    assert table.label_for(2) == "125"


def test_agreeing_sources_use_the_model():
    resolution = resolve_thickness(0.190 * INCH, "SHEET,AL,SMOOTH,.190,60X133.13")
    assert resolution.effective_sixteenths == 3
    assert not resolution.mismatch


def test_disagreement_goes_with_the_description_and_flags():
    # Model says 1/8, description says .190 (3/16): description wins.
    resolution = resolve_thickness(0.125 * INCH, "SHEET,AL,SMOOTH,.190,60X133.13")
    assert resolution.mismatch
    assert resolution.effective_sixteenths == 3


def test_unparseable_description_leaves_the_model_value():
    resolution = resolve_thickness(0.125 * INCH, "SHEET,AL,SMOOTH")
    assert not resolution.mismatch
    assert resolution.effective_sixteenths == 2


def test_missing_model_thickness_falls_back_to_description():
    resolution = resolve_thickness(None, "SHEET,AL,SMOOTH,.125,60X144")
    assert resolution.effective_sixteenths == 2
    assert not resolution.mismatch


def test_nothing_resolvable():
    resolution = resolve_thickness(None, "BRACKET")
    assert resolution.effective_sixteenths is None
    assert resolution.display == "—"


def test_display_shows_source_and_fraction():
    resolution = resolve_thickness(0.190 * INCH, "SHEET,AL,SMOOTH,.190,60X133.13")
    assert resolution.display == '0.19" (3/16")'
    mismatch = resolve_thickness(0.125 * INCH, "SHEET,AL,SMOOTH,.190,60X133.13")
    assert mismatch.display == '0.19" (3/16")'  # the description's value shows
