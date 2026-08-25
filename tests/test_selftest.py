"""The self-test must pass, and must fail loudly if the planner regresses."""

from autoface.core.selftest import run_selftest


def test_selftest_passes():
    ok, lines = run_selftest()
    assert ok, "\n".join(lines)
    # Every check reported, none failed.
    assert lines
    assert all("[ok]" in line for line in lines)


def test_selftest_reports_the_spec_examples():
    _, lines = run_selftest()
    text = "\n".join(lines)
    assert "RUN 11\\1875\\8640-1101-1.dwg" in text
    assert "RUN 11\\125\\8640-1101-5.dwg" in text
