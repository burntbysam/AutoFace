"""The scan layer, driven through fake COM objects."""

from autoface.core.models import ModelKind
from autoface.inventor import com
from autoface.inventor.scan import find_columns, scan_drawing, scan_session

from . import fakes

INCH = 2.54

ITEM_COLUMN = fakes.Column("ITEM", com.kItemPartsListProperty)
PART_NUMBER_COLUMN = fakes.Column(
    "PART NUMBER", com.kFileProperty, (fakes.DESIGN_TRACKING, 5)
)
DESCRIPTION_COLUMN = fakes.Column(
    "DESCRIPTION", com.kFileProperty, (fakes.DESIGN_TRACKING, 29)
)


def sheet_metal_part(path="C:\\m\\part.ipt", **kw):
    return fakes.Document(path, log=[], **kw)


def standard_parts_list(rows):
    return fakes.PartsList(
        [ITEM_COLUMN, PART_NUMBER_COLUMN, DESCRIPTION_COLUMN], rows
    )


def drawing_with(rows, path="C:\\dwg\\8640-01101-I.idw"):
    return fakes.DrawingDocument(path, [fakes.Sheet([standard_parts_list(rows)])])


def row_for(document, item="1", part_number="PN", description="SHEET,AL,.125,10X10"):
    return fakes.Row(
        {1: item, 2: part_number, 3: description}, referenced_documents=[document]
    )


class TestScanSession:
    def test_only_visible_idw_drawings_are_queued(self):
        idw = drawing_with([row_for(sheet_metal_part())])
        dwg_drawing = fakes.DrawingDocument("C:\\dwg\\other.dwg", [])
        part_doc = fakes.DrawingDocument("C:\\m\\part.ipt", [], document_type=12290)
        app = fakes.Application(visible=[idw, dwg_drawing, part_doc])

        drawings = scan_session(app)
        assert [d.path for d in drawings] == ["C:\\dwg\\8640-01101-I.idw"]

    def test_invisible_referenced_documents_are_not_queued(self):
        # The models behind a drawing are in Documents but not VisibleDocuments.
        idw = drawing_with([row_for(sheet_metal_part())])
        model = sheet_metal_part()
        app = fakes.Application(in_session=[idw, model], visible=[idw])
        assert len(scan_session(app)) == 1


class TestScanDrawing:
    def test_reads_the_printed_cell_values(self):
        document = sheet_metal_part()
        # The cell shows "7" — a user override; there is no BOM lookup at all.
        drawing = drawing_with([row_for(document, item="7")])
        scanned = scan_drawing(drawing)
        row = scanned.rows[0]
        assert row.item == "7"
        assert row.part_number == "PN"
        assert row.model_kind is ModelKind.SHEET_METAL
        assert row.model_path == "C:\\m\\part.ipt"

    def test_hidden_rows_are_not_scanned(self):
        visible = row_for(sheet_metal_part(), item="1")
        hidden = row_for(sheet_metal_part("C:\\m\\other.ipt"), item="2")
        hidden.Visible = False
        scanned = scan_drawing(drawing_with([visible, hidden]))
        assert [row.item for row in scanned.rows] == ["1"]

    def test_all_sheets_and_lists_are_scanned(self):
        first = fakes.Sheet([standard_parts_list([row_for(sheet_metal_part(), item="1")])])
        second = fakes.Sheet(
            [
                standard_parts_list([row_for(sheet_metal_part(), item="2")]),
                standard_parts_list([row_for(sheet_metal_part(), item="3")]),
            ]
        )
        drawing = fakes.DrawingDocument("C:\\dwg\\8640-01101-I.idw", [first, second])
        scanned = scan_drawing(drawing)
        assert [row.item for row in scanned.rows] == ["1", "2", "3"]

    def test_no_parts_list_is_a_drawing_note(self):
        drawing = fakes.DrawingDocument(
            "C:\\dwg\\8640-01101-I.idw", [fakes.Sheet([])]
        )
        scanned = scan_drawing(drawing)
        assert scanned.rows == ()
        assert "no parts list" in scanned.note

    def test_missing_item_column_is_a_note_not_a_crash(self):
        parts_list = fakes.PartsList(
            [fakes.Column("QTY", 45575)], [row_for(sheet_metal_part())]
        )
        drawing = fakes.DrawingDocument(
            "C:\\dwg\\8640-01101-I.idw", [fakes.Sheet([parts_list])]
        )
        scanned = scan_drawing(drawing)
        assert scanned.rows == ()
        assert "no ITEM column" in scanned.note

    def test_sheet_metal_row_carries_thickness_and_flat_pattern(self):
        document = sheet_metal_part(
            thickness_cm=0.190 * INCH, has_flat_pattern=False
        )
        scanned = scan_drawing(drawing_with([row_for(document)]))
        row = scanned.rows[0]
        assert row.thickness_cm == 0.190 * INCH
        assert row.has_flat_pattern is False

    def test_classifies_assembly_rows(self):
        assembly = fakes.Document(
            "C:\\m\\sub.iam", document_type=12291, subtype="{whatever}"
        )
        scanned = scan_drawing(drawing_with([row_for(assembly)]))
        assert scanned.rows[0].model_kind is ModelKind.SUB_ASSEMBLY
        assert scanned.rows[0].model_path == "C:\\m\\sub.iam"

    def test_classifies_plain_parts(self):
        plain = fakes.Document("C:\\m\\plain.ipt", subtype=fakes.PART_SUBTYPE)
        scanned = scan_drawing(drawing_with([row_for(plain)]))
        assert scanned.rows[0].model_kind is ModelKind.NOT_SHEET_METAL

    def test_rows_without_references_are_no_model(self):
        virtual = fakes.Row({1: "9", 2: "PN", 3: "VIRTUAL"})
        scanned = scan_drawing(drawing_with([virtual]))
        row = scanned.rows[0]
        assert row.model_kind is ModelKind.NO_MODEL
        assert "no model reference" in row.note

    def test_resolution_errors_become_no_model_with_the_error_text(self):
        class ExplodingRow:
            Visible = True

            def Item(self, index):
                return fakes.Cell(str(index))

            @property
            def ReferencedRows(self):
                raise RuntimeError("BOM view is broken")

        exploding = ExplodingRow()
        scanned = scan_drawing(drawing_with([exploding]))
        row = scanned.rows[0]
        assert row.model_kind is ModelKind.NO_MODEL
        assert "BOM view is broken" in row.note

    def test_scan_never_mutates_anything(self):
        document = sheet_metal_part(has_flat_pattern=False)
        drawing = drawing_with([row_for(document)])
        scan_drawing(drawing)
        assert document._log == []

    def test_busy_errors_are_reraised_for_the_retry_wrapper(self):
        # A busy rejection must reach with_busy_retry, not silently turn a
        # row into "no model".
        class BusyError(Exception):
            hresult = com.RPC_E_CALL_REJECTED

        class BusyRow:
            Visible = True

            def Item(self, index):
                return fakes.Cell(str(index))

            @property
            def ReferencedRows(self):
                raise BusyError("call was rejected by callee")

        import pytest

        with pytest.raises(BusyError):
            scan_drawing(drawing_with([BusyRow()]))


class TestFindColumns:
    def test_maps_by_property_type_and_id(self):
        mapping = find_columns(standard_parts_list([]))
        assert (mapping.item, mapping.part_number, mapping.description) == (1, 2, 3)

    def test_falls_back_to_titles_when_id_lookup_fails(self):
        columns = [
            fakes.Column("ITEM", 0),
            fakes.Column("PART NUMBER", com.kFileProperty, id_error=True),
            fakes.Column("DESCRIPTION", com.kFileProperty, id_error=True),
        ]
        mapping = find_columns(fakes.PartsList(columns, []))
        assert (mapping.item, mapping.part_number, mapping.description) == (1, 2, 3)

    def test_renamed_iproperty_columns_still_map_by_id(self):
        columns = [
            fakes.Column("POS", com.kItemPartsListProperty),
            fakes.Column("ARTICLE", com.kFileProperty, (fakes.DESIGN_TRACKING, 5)),
            fakes.Column("TEXT", com.kFileProperty, (fakes.DESIGN_TRACKING, 29)),
        ]
        mapping = find_columns(fakes.PartsList(columns, []))
        assert (mapping.item, mapping.part_number, mapping.description) == (1, 2, 3)

    def test_a_title_lookalike_never_preempts_an_authoritative_column(self):
        # A custom column merely TITLED like the target sits to the left of
        # the real, PropertyType-identified column: the real one must win.
        columns = [
            fakes.Column("ITEM", 0),  # custom column that just says ITEM
            fakes.Column("POS", com.kItemPartsListProperty),  # the real one
            fakes.Column("DESCRIPTION", 0),  # custom look-alike
            fakes.Column("NOTES", com.kFileProperty, (fakes.DESIGN_TRACKING, 29)),
        ]
        mapping = find_columns(fakes.PartsList(columns, []))
        assert mapping.item == 2
        assert mapping.description == 4

    def test_titles_still_fill_slots_the_ids_could_not(self):
        columns = [
            fakes.Column("POS", com.kItemPartsListProperty),
            fakes.Column("PART NUMBER", com.kFileProperty, id_error=True),
        ]
        mapping = find_columns(fakes.PartsList(columns, []))
        assert (mapping.item, mapping.part_number) == (1, 2)
