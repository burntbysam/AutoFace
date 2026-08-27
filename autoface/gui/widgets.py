"""Custom widgets: the preview table and the end-of-run summary dialog."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from ..core.models import Classification, Plan, RunResult

PREVIEW_HEADERS = (
    "Export",
    "Drawing",
    "Item",
    "Part number",
    "Thickness",
    "Classification",
    "Target path",
)
CHECK_COLUMN = 0

_NUMBER_CHUNKS = re.compile(r"(\d+)")
_THICKNESS_PREFIX = re.compile(r'\s*([0-9.]+)"')


def _natural_key(text: str):
    """Sort '2' before '10' and '8640-2' before '8640-10', case-insensitively."""
    return tuple(
        (0, int(chunk)) if chunk.isdigit() else (1, chunk.casefold())
        for chunk in _NUMBER_CHUNKS.split(str(text))
        if chunk
    )


def _thickness_key(display: str) -> float:
    """The numeric inches behind '0.19" (3/16")'; unknown ('—') sorts last."""
    match = _THICKNESS_PREFIX.match(display)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return float("inf")


class _SortableItem(QTableWidgetItem):
    """A cell that sorts by a supplied key instead of its display text."""

    def __init__(self, text: str, key) -> None:
        super().__init__(text)
        self._key = key

    def __lt__(self, other) -> bool:  # Qt calls this when sorting rows
        if isinstance(other, _SortableItem):
            return self._key < other._key
        return super().__lt__(other)


class PreviewTable(QTableWidget):
    """One row per BOM item across all open drawings — the pre-export gate.

    This is the user's chance to catch a bad parse or thickness read before
    anything is written, so it shows exactly what the run will do: the
    resolved thickness, the classification, and the full target path — plus
    a tick box per exportable row to hand-pick a partial run.
    """

    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(PREVIEW_HEADERS), parent)
        self._populating = False
        self.setHorizontalHeaderLabels(PREVIEW_HEADERS)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            len(PREVIEW_HEADERS) - 1, QHeaderView.ResizeMode.Stretch
        )
        # Click a header to sort, click again to reverse. Display-only: the
        # export always runs in drawing order. No indicator until the user
        # actually picks a column, so a fresh scan shows drawing order.
        self.setSortingEnabled(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.itemChanged.connect(self._on_item_changed)

    def _on_item_changed(self, item) -> None:
        if self._populating or item.column() != CHECK_COLUMN:
            return
        self.selection_changed.emit()

    def show_plan(self, plan: Plan) -> None:
        # Repopulating with sorting live would scatter half-filled rows;
        # remember the user's sort, fill, then re-apply it to the new data.
        header = self.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.setSortingEnabled(False)
        self._populating = True
        try:
            self.setRowCount(len(plan.rows))
            for index, row in enumerate(plan.rows):
                exportable = row.classification is Classification.EXPORT
                check = _SortableItem("", 0 if exportable else 1)
                check.setData(Qt.ItemDataRole.UserRole, index)
                if exportable:
                    check.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    check.setCheckState(Qt.CheckState.Checked)
                    check.setToolTip("Untick to leave this part out of the run")
                else:
                    check.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    )
                self.setItem(index, CHECK_COLUMN, check)

                values = (
                    (row.drawing_label, _natural_key(row.drawing_label)),
                    (row.item, _natural_key(row.item)),
                    (row.part_number, _natural_key(row.part_number)),
                    (row.thickness_display, _thickness_key(row.thickness_display)),
                    (
                        row.classification.label,
                        _natural_key(row.classification.label),
                    ),
                    (row.target_relative, _natural_key(row.target_relative)),
                )
                for offset, (value, key) in enumerate(values):
                    column = CHECK_COLUMN + 1 + offset
                    item = _SortableItem(str(value), key)
                    if offset == 0:
                        item.setToolTip(row.drawing_path)
                    elif column == len(PREVIEW_HEADERS) - 1 and row.target_path:
                        item.setToolTip(row.target_path)
                    elif row.flags:
                        item.setToolTip("\n".join(row.flags))
                    self.setItem(index, column, item)
        finally:
            self._populating = False

        self.setSortingEnabled(True)
        if 0 <= sort_section < len(PREVIEW_HEADERS):
            self.sortItems(sort_section, sort_order)
        else:
            header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.selection_changed.emit()

    # -- selection -----------------------------------------------------
    def _checkable_items(self):
        for index in range(self.rowCount()):
            item = self.item(index, CHECK_COLUMN)
            if item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                yield item

    def selected_plan_indexes(self) -> set[int]:
        """Plan-row indexes of the ticked rows, immune to display sorting."""
        return {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._checkable_items()
            if item.checkState() == Qt.CheckState.Checked
        }

    def selectable_count(self) -> int:
        return sum(1 for _ in self._checkable_items())

    def set_all_checked(self, checked: bool) -> None:
        """Deselect all (False) or reset to every exportable sheet part (True)."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._populating = True
        try:
            for item in self._checkable_items():
                item.setCheckState(state)
        finally:
            self._populating = False
        self.selection_changed.emit()


class SummaryDialog(QDialog):
    """End-of-run summary: counts, the scrollable flag list, and Save log."""

    SAVE_LOG_ROLE = QDialogButtonBox.ButtonRole.ActionRole

    def __init__(
        self,
        result: RunResult,
        flag_list: list[str],
        skipped_total: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        flagged = bool(flag_list)
        title = "⚠️ Run finished with flags" if flagged else "Run finished"
        self.setWindowTitle(title)
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        # skipped_total includes preview-classified skips, so this number
        # matches the saved .txt log exactly.
        skipped = result.skipped if skipped_total is None else skipped_total
        self.counts_label = QLabel(
            f"Exported {result.exported} · Skipped {skipped} · "
            f"Failed {result.failed}"
        )
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.counts_label)

        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(
            "\n".join(flag_list) if flag_list else "Nothing was skipped or flagged."
        )
        layout.addWidget(detail, 1)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("Save log…", self.SAVE_LOG_ROLE)
        close = buttons.addButton(
            "Close", QDialogButtonBox.ButtonRole.AcceptRole
        )
        close.setDefault(True)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
