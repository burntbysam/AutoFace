"""The neversave probe must itself honor the never-save contract."""

from __future__ import annotations

from autoface.config import Config
from autoface.inventor import probes as probes_module
from autoface.inventor.probes import probe_neversave
from autoface.updater.github import sha256_of

from . import fakes


def make_session(tmp_path, export_fail):
    """A drawing referencing one sheet-metal part (real file, no flat pattern)."""
    model = tmp_path / "8640-1101-1.ipt"
    model.write_bytes(b"IPT MODEL BYTES")

    document = fakes.Document(
        str(model), has_flat_pattern=False, export_fail=export_fail
    )
    columns = [
        fakes.Column("ITEM", 45572),
        fakes.Column("PART NUMBER", 45569, (fakes.DESIGN_TRACKING, 5)),
        fakes.Column("DESCRIPTION", 45569, (fakes.DESIGN_TRACKING, 29)),
    ]
    row = fakes.Row(
        {1: "1", 2: "PN-1", 3: "SHEET,AL,.125,10X10"},
        referenced_documents=[document],
    )
    drawing = fakes.DrawingDocument(
        "C:\\dwg\\8640-01101-I.idw",
        [fakes.Sheet([fakes.PartsList(columns, [row])])],
    )
    app = fakes.Application(in_session=[drawing, document], visible=[drawing])
    return app, document, model


def run_probe(tmp_path, monkeypatch, export_fail):
    app, document, model = make_session(tmp_path, export_fail)
    monkeypatch.setattr(probes_module, "load_config", lambda: Config())
    before = sha256_of(model)
    lines = probe_neversave(app)
    after = sha256_of(model)
    return document, model, lines, before, after


def test_happy_path_creates_exports_and_deletes(tmp_path, monkeypatch):
    document, model, lines, before, after = run_probe(
        tmp_path, monkeypatch, export_fail=False
    )
    calls = [entry[1] for entry in document._log]
    assert "Unfold" in calls
    assert "DataIO.WriteDataToFile" in calls
    assert "FlatPattern.Delete" in calls
    assert before == after
    assert any("byte-identical" in line for line in lines)


def test_created_flat_pattern_is_deleted_even_when_the_export_fails(
    tmp_path, monkeypatch
):
    # The leak scenario: WriteDataToFile raises, and the probe must still
    # remove the flat pattern it created rather than leave it in the session.
    document, model, lines, before, after = run_probe(
        tmp_path, monkeypatch, export_fail=True
    )
    calls = [entry[1] for entry in document._log]
    assert "Unfold" in calls
    assert "FlatPattern.Delete" in calls
    assert any("export FAILED" in line for line in lines)
    assert before == after


def test_probe_never_saves(tmp_path, monkeypatch):
    document, *_ = run_probe(tmp_path, monkeypatch, export_fail=False)
    assert not any(
        entry[1] in ("Save", "SaveAs", "Update") for entry in document._log
    )


def test_a_pre_dirty_part_keeps_its_dirty_flag(tmp_path, monkeypatch):
    # fakes.Document starts Dirty=True: the probe must not clear it.
    document, model, lines, *_ = run_probe(tmp_path, monkeypatch, export_fail=False)
    assert document.Dirty is True
    assert any("left as found" in line for line in lines)
