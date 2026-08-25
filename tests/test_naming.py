"""The naming scheme: the spec's examples are the contract."""

from autoface.core.naming import (
    DrawingName,
    clean_item,
    export_filename,
    parse_drawing_name,
    relative_target,
)


def test_spec_example_parses():
    name = parse_drawing_name("8640-01101-I")
    assert name == DrawingName(job="8640", assembly="1101", run="11")
    assert name.run_folder == "RUN 11"


def test_full_windows_path_parses_to_the_same_name():
    assert parse_drawing_name(r"C:\jobs\8640\8640-01101-I.idw") == parse_drawing_name(
        "8640-01101-I"
    )


def test_leading_zeros_are_stripped():
    assert parse_drawing_name("8640-00042-B").assembly == "42"


def test_run_is_first_two_digits_after_stripping():
    assert parse_drawing_name("8640-01101-I").run == "11"
    assert parse_drawing_name("8640-09950-I").run == "99"
    # A single-digit assembly gives a single-digit run.
    assert parse_drawing_name("8640-00007-A").run == "7"


def test_suffix_is_dropped_even_when_it_contains_dashes():
    name = parse_drawing_name("8640-01101-I-REV2")
    assert name is not None
    assert (name.job, name.assembly) == ("8640", "1101")


def test_unparseable_names_return_none():
    assert parse_drawing_name("NOT-A-JOB") is None  # assembly not numeric
    assert parse_drawing_name("8640") is None  # no dashes
    assert parse_drawing_name("8640-01101") is None  # no suffix
    assert parse_drawing_name("8640-0000-I") is None  # assembly all zeros
    assert parse_drawing_name("-01101-I") is None  # empty job


def test_export_filename_uses_item_verbatim():
    name = parse_drawing_name("8640-01101-I")
    assert export_filename(name, "5") == "8640-1101-5.dwg"
    assert export_filename(name, "12A") == "8640-1101-12A.dwg"  # no zero padding


def test_relative_target_matches_spec_examples():
    name = parse_drawing_name("8640-01101-I")
    assert relative_target(name, "1875", "1") == "RUN 11\\1875\\8640-1101-1.dwg"
    assert relative_target(name, "125", "5") == "RUN 11\\125\\8640-1101-5.dwg"


def test_clean_item():
    assert clean_item(" 5 ") == "5"
    assert clean_item("12A") == "12A"
    assert clean_item("") is None
    assert clean_item("   ") is None
    assert clean_item("5/6") is None  # not a legal filename component
    assert clean_item("a:b") is None
