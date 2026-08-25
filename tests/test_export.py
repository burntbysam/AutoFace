"""The export run — with the never-save contract as the headline.

These tests drive the real export code over fake COM objects and a real
temporary directory, and assert on the recorded call log: what got called,
and — more importantly — what never did.
"""

from pathlib import Path

from autoface.config import Config
from autoface.core.models import Classification, Plan, PlanRow
from autoface.inventor.export import export_row, run_export

from . import fakes


def plan_row(target, model_path="C:\\m\\part.ipt", item="1"):
    return PlanRow(
        drawing_path="C:\\dwg\\8640-01101-I.idw",
        drawing_label="8640-01101-I",
        item=item,
        part_number=f"PN-{item}",
        description="SHEET,AL,.125,10X10",
        thickness_display='0.125" (1/8")',
        classification=Classification.EXPORT,
        target_relative="RUN 11\\125\\8640-1101-" + item + ".dwg",
        target_path=str(target),
        model_path=model_path,
    )


def session_with(document):
    return fakes.Application(in_session=[document], visible=[])


def never_saved(log):
    assert not any(entry[1] in ("Save", "SaveAs", "Update") for entry in log), log


class TestNeverSave:
    def test_existing_flat_pattern_is_used_untouched(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt", has_flat_pattern=True)
        app = session_with(document)
        target = tmp_path / "RUN 11" / "125" / "8640-1101-1.dwg"

        outcome = export_row(app, plan_row(target), "FLAT PATTERN DWG")

        assert outcome.status == "exported"
        assert target.exists()
        calls = [entry[1] for entry in document._log]
        assert "Unfold" not in calls
        assert "FlatPattern.Delete" not in calls
        assert "Close" not in calls  # in-session part is never closed
        never_saved(document._log)

    def test_created_flat_pattern_is_deleted_after_export(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt", has_flat_pattern=False)
        app = session_with(document)
        target = tmp_path / "RUN 11" / "125" / "8640-1101-1.dwg"

        outcome = export_row(app, plan_row(target), "FLAT PATTERN DWG")

        assert outcome.status == "exported"
        assert target.exists()
        calls = [entry[1] for entry in document._log]
        assert calls.index("Unfold") < calls.index("DataIO.WriteDataToFile")
        assert calls.index("DataIO.WriteDataToFile") < calls.index(
            "FlatPattern.Delete"
        )
        assert ("part.ipt", "Dirty=", False) in document._log
        assert "Close" not in calls  # the drawing still references it
        never_saved(document._log)

    def test_created_flat_pattern_is_deleted_even_when_the_export_fails(
        self, tmp_path
    ):
        document = fakes.Document(
            "C:\\m\\part.ipt", has_flat_pattern=False, export_fail=True
        )
        app = session_with(document)
        outcome = export_row(
            app, plan_row(tmp_path / "8640-1101-1.dwg"), "FLAT PATTERN DWG"
        )

        assert outcome.status == "failed"
        assert "translator error" in outcome.detail
        calls = [entry[1] for entry in document._log]
        assert "FlatPattern.Delete" in calls
        never_saved(document._log)

    def test_documents_opened_by_autoface_are_closed_without_save(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt", has_flat_pattern=True)
        app = fakes.Application(openable={"C:\\m\\part.ipt": document})
        target = tmp_path / "8640-1101-1.dwg"

        outcome = export_row(app, plan_row(target), "FLAT PATTERN DWG")

        assert outcome.status == "exported"
        assert ("Documents", "Open", "C:\\m\\part.ipt", False) in app.log
        assert ("part.ipt", "ReleaseReference") in document._log
        assert ("part.ipt", "Close", True) in document._log  # SkipSave=True
        never_saved(document._log)


class TestExportRow:
    def test_unfold_failure_is_flagged_with_the_error_text(self, tmp_path):
        document = fakes.Document(
            "C:\\m\\part.ipt", has_flat_pattern=False, unfold_error="rip failed"
        )
        app = session_with(document)
        outcome = export_row(
            app, plan_row(tmp_path / "8640-1101-1.dwg"), "FLAT PATTERN DWG"
        )
        assert outcome.status == "failed"
        assert "rip failed" in outcome.detail
        # Nothing was created, so nothing is deleted.
        assert "FlatPattern.Delete" not in [entry[1] for entry in document._log]

    def test_existing_target_is_never_overwritten(self, tmp_path):
        target = tmp_path / "8640-1101-1.dwg"
        target.write_bytes(b"precious")
        document = fakes.Document("C:\\m\\part.ipt")
        app = session_with(document)

        outcome = export_row(app, plan_row(target), "FLAT PATTERN DWG")

        assert outcome.status == "skipped"
        assert "not overwritten" in outcome.detail
        assert target.read_bytes() == b"precious"
        assert document._log == []  # the part was never even touched

    def test_target_folders_are_created_on_demand(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt")
        app = session_with(document)
        target = tmp_path / "RUN 11" / "1875" / "8640-1101-1.dwg"
        outcome = export_row(app, plan_row(target), "FLAT PATTERN DWG")
        assert outcome.status == "exported"
        assert target.parent.is_dir()

    def test_the_configured_format_string_is_passed_through(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt")
        app = session_with(document)
        export_row(app, plan_row(tmp_path / "a.dwg"), "FLAT PATTERN DWG")
        write = next(
            entry for entry in document._log if entry[1] == "DataIO.WriteDataToFile"
        )
        assert write[2] == "FLAT PATTERN DWG"

    def test_missing_model_fails_cleanly(self, tmp_path):
        app = fakes.Application()  # nothing in session, nothing openable
        outcome = export_row(
            app, plan_row(tmp_path / "a.dwg"), "FLAT PATTERN DWG"
        )
        assert outcome.status == "failed"

    def test_non_sheet_metal_document_fails_cleanly(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt", subtype=fakes.PART_SUBTYPE)
        app = session_with(document)
        outcome = export_row(
            app, plan_row(tmp_path / "a.dwg"), "FLAT PATTERN DWG"
        )
        assert outcome.status == "failed"
        assert "no longer a sheet metal part" in outcome.detail


class TestRunExport:
    def config(self):
        return Config()

    def test_one_failure_never_aborts_the_run(self, tmp_path):
        bad = fakes.Document(
            "C:\\m\\bad.ipt", has_flat_pattern=False, unfold_error="boom"
        )
        good = fakes.Document("C:\\m\\good.ipt")
        app = fakes.Application(in_session=[bad, good])
        plan = Plan(
            rows=(
                plan_row(tmp_path / "8640-1101-1.dwg", "C:\\m\\bad.ipt", "1"),
                plan_row(tmp_path / "8640-1101-2.dwg", "C:\\m\\good.ipt", "2"),
            )
        )

        result = run_export(app, plan, self.config())

        assert result.failed == 1
        assert result.exported == 1
        assert (tmp_path / "8640-1101-2.dwg").exists()

    def test_progress_and_row_callbacks_fire_in_order(self, tmp_path):
        documents = [
            fakes.Document(f"C:\\m\\p{i}.ipt") for i in (1, 2, 3)
        ]
        app = fakes.Application(in_session=documents)
        plan = Plan(
            rows=tuple(
                plan_row(tmp_path / f"8640-1101-{i}.dwg", f"C:\\m\\p{i}.ipt", str(i))
                for i in (1, 2, 3)
            )
        )
        progress: list[tuple[int, int]] = []
        rows: list[str] = []

        run_export(
            app,
            plan,
            self.config(),
            on_progress=lambda done, total: progress.append((done, total)),
            on_row=lambda outcome: rows.append(outcome.row.item),
        )
        assert progress == [(1, 3), (2, 3), (3, 3)]
        assert rows == ["1", "2", "3"]

    def test_cancel_stops_between_rows(self, tmp_path):
        documents = [fakes.Document(f"C:\\m\\p{i}.ipt") for i in (1, 2)]
        app = fakes.Application(in_session=documents)
        plan = Plan(
            rows=tuple(
                plan_row(tmp_path / f"8640-1101-{i}.dwg", f"C:\\m\\p{i}.ipt", str(i))
                for i in (1, 2)
            )
        )
        cancelled = iter([False, True])

        result = run_export(
            app, plan, self.config(), should_cancel=lambda: next(cancelled)
        )
        assert len(result.outcomes) == 1
        assert any("cancelled" in note for note in result.notes)

    def test_silent_operation_is_set_and_restored(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt")
        app = fakes.Application(in_session=[document])
        seen: list[bool] = []

        original_write = document.ComponentDefinition.DataIO.WriteDataToFile

        def spying_write(format_string, path):
            seen.append(app.SilentOperation)
            return original_write(format_string, path)

        document.ComponentDefinition.DataIO.WriteDataToFile = spying_write
        plan = Plan(rows=(plan_row(tmp_path / "a.dwg"),))
        run_export(app, plan, self.config())

        assert seen == [True]  # prompts suppressed during the run
        assert app.SilentOperation is False  # and restored afterwards

    def test_only_export_rows_run(self, tmp_path):
        document = fakes.Document("C:\\m\\part.ipt")
        app = fakes.Application(in_session=[document])
        skip = PlanRow(
            drawing_path="C:\\dwg\\8640-01101-I.idw",
            drawing_label="8640-01101-I",
            item="9",
            part_number="PN-9",
            description="",
            thickness_display="—",
            classification=Classification.SKIP_SUB_ASSEMBLY,
        )
        plan = Plan(rows=(skip, plan_row(tmp_path / "a.dwg")))
        result = run_export(app, plan, self.config())
        assert len(result.outcomes) == 1
        assert result.exported == 1
