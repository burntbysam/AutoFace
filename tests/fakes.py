"""A miniature Inventor COM object model for driving the adapter in tests.

The adapter is late-bound (plain attribute access), so duck-typed fakes
exercise the real code paths. Every mutating call is recorded in a shared
log — the never-save tests assert on what does NOT appear in it.
"""

from __future__ import annotations

SHEET_METAL_SUBTYPE = "{9C464203-9BAE-11D3-8BAD-0060B0CE6BB4}"
PART_SUBTYPE = "{4D29B490-49B2-11D0-93C3-7E0706000000}"
DESIGN_TRACKING = "{32853F0F-3444-11D1-9E93-0060B03C1CA6}"


class Enumerator:
    """1-based COM collection."""

    def __init__(self, items=()):
        self.items = list(items)

    @property
    def Count(self):
        return len(self.items)

    def Item(self, index):
        return self.items[index - 1]


class Cell:
    def __init__(self, value):
        self.Value = value


class Column:
    def __init__(self, title, property_type=0, file_property=None, id_error=False):
        self.Title = title
        self.PropertyType = property_type
        self._file_property = file_property  # (set guid, property id)
        self._id_error = id_error

    def GetFilePropertyId(self):
        if self._id_error or self._file_property is None:
            raise RuntimeError("GetFilePropertyId unavailable")
        return self._file_property


class BOMRow:
    def __init__(self, documents):
        self.ComponentDefinitions = Enumerator(
            [doc.ComponentDefinition for doc in documents]
        )


class DrawingBOMRow:
    def __init__(self, documents):
        self.BOMRow = BOMRow(documents)


class Row:
    def __init__(self, cells, referenced_documents=None, visible=True, broken=False):
        self._cells = {index: Cell(value) for index, value in cells.items()}
        self.Visible = visible
        self._broken = broken
        documents = referenced_documents or []
        self.ReferencedRows = Enumerator(
            [DrawingBOMRow(documents)] if documents else []
        )

    def Item(self, index):
        if self._broken:
            raise RuntimeError("row exploded")
        return self._cells[index]


class PartsList:
    def __init__(self, columns, rows):
        self.PartsListColumns = Enumerator(columns)
        self.PartsListRows = Enumerator(rows)


class Sheet:
    def __init__(self, parts_lists=()):
        self.PartsLists = Enumerator(parts_lists)


class Thickness:
    def __init__(self, value_cm):
        self.Value = value_cm


class FlatPattern:
    def __init__(self, log, name):
        self._log = log
        self._name = name

    def ExitEdit(self):
        self._log.append((self._name, "FlatPattern.ExitEdit"))

    def Delete(self):
        self._log.append((self._name, "FlatPattern.Delete"))


class DataIO:
    def __init__(self, log, name, fail=False):
        self._log = log
        self._name = name
        self._fail = fail

    def WriteDataToFile(self, format_string, path):
        self._log.append((self._name, "DataIO.WriteDataToFile", format_string, path))
        if self._fail:
            raise RuntimeError("translator error")
        with open(path, "wb") as handle:
            handle.write(b"DWG" + format_string.encode())


class SheetMetalDefinition:
    def __init__(
        self,
        document,
        log,
        thickness_cm=0.3175,
        has_flat_pattern=True,
        unfold_error=None,
        export_fail=False,
    ):
        self.Document = document
        self._log = log
        self.Thickness = Thickness(thickness_cm)
        self.HasFlatPattern = has_flat_pattern
        self._unfold_error = unfold_error
        self.FlatPattern = (
            FlatPattern(log, document.name) if has_flat_pattern else None
        )
        self.DataIO = DataIO(log, document.name, fail=export_fail)

    def Unfold(self):
        self._log.append((self.Document.name, "Unfold"))
        if self._unfold_error:
            raise RuntimeError(self._unfold_error)
        self.HasFlatPattern = True
        self.FlatPattern = FlatPattern(self._log, self.Document.name)


class PlainDefinition:
    """ComponentDefinition of a non-sheet-metal document."""

    def __init__(self, document):
        self.Document = document


class Document:
    """A part or assembly document."""

    def __init__(
        self,
        path,
        document_type=12290,
        subtype=SHEET_METAL_SUBTYPE,
        log=None,
        **definition_kwargs,
    ):
        self.name = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        self.FullFileName = path
        self.DocumentType = document_type
        self.SubType = subtype
        self.Dirty = True
        self._log = log if log is not None else []
        if document_type == 12290 and subtype == SHEET_METAL_SUBTYPE:
            self.ComponentDefinition = SheetMetalDefinition(
                self, self._log, **definition_kwargs
            )
        else:
            self.ComponentDefinition = PlainDefinition(self)

    def Close(self, skip_save=False):
        self._log.append((self.name, "Close", skip_save))

    def ReleaseReference(self):
        self._log.append((self.name, "ReleaseReference"))

    def Save(self):  # pragma: no cover - exists so calling it would be caught
        self._log.append((self.name, "Save"))
        raise AssertionError("Save must never be called")

    def __setattr__(self, key, value):
        if key == "Dirty" and hasattr(self, "_log"):
            self._log.append((self.name, "Dirty=", value))
        object.__setattr__(self, key, value)


class DrawingDocument:
    def __init__(self, path, sheets=(), document_type=12292):
        self.FullFileName = path
        self.DocumentType = document_type
        self.Sheets = Enumerator(sheets)


class Documents:
    def __init__(self, log, in_session=(), visible=(), openable=None):
        self._log = log
        self.in_session = list(in_session)  # everything loaded (incl. models)
        self.VisibleDocuments = Enumerator(list(visible))
        self._openable = dict(openable or {})  # path -> Document

    @property
    def Count(self):
        return len(self.in_session)

    def Item(self, index):
        return self.in_session[index - 1]

    def ItemByName(self, path):
        for document in self.in_session:
            if str(document.FullFileName).casefold() == path.casefold():
                return document
        raise RuntimeError("not found")

    def Open(self, path, visible=True):
        self._log.append(("Documents", "Open", path, visible))
        document = self._openable.get(path)
        if document is None:
            raise RuntimeError(f"file not found: {path}")
        self.in_session.append(document)
        return document


class Application:
    def __init__(self, log=None, in_session=(), visible=(), openable=None):
        self.log = log if log is not None else []
        self.Documents = Documents(self.log, in_session, visible, openable)
        self.SilentOperation = False

    def mutations(self):
        """Every logged call that could change a model or the session."""
        return [entry for entry in self.log if entry[1] not in ()]
