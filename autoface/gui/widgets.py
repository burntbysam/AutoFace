"""Custom widgets: the preview table and the end-of-run summary dialog."""

from __future__ import annotations

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

from ..core.models import Plan, RunResult

PREVIEW_HEADERS = (
    "Drawing",
    "Item",
    "Part number",
    "Thickness",
    "Classification",
    "Target path",
)


class PreviewTable(QTableWidget):
    """One row per BOM item across all open drawings — the pre-export gate.

    This is the user's chance to catch a bad parse or thickness read before
    anything is written, so it shows exactly what the run will do: the
    resolved thickness, the classification, and the full target path.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(PREVIEW_HEADERS), parent)
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

    def show_plan(self, plan: Plan) -> None:
        self.setRowCount(len(plan.rows))
        for index, row in enumerate(plan.rows):
            values = (
                row.drawing_label,
                row.item,
                row.part_number,
                row.thickness_display,
                row.classification.label,
                row.target_relative,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setToolTip(row.drawing_path)
                elif column == len(values) - 1 and row.target_path:
                    item.setToolTip(row.target_path)
                elif row.flags:
                    item.setToolTip("\n".join(row.flags))
                self.setItem(index, column, item)


class SummaryDialog(QDialog):
    """End-of-run summary: counts, the scrollable flag list, and Save log."""

    SAVE_LOG_ROLE = QDialogButtonBox.ButtonRole.ActionRole

    def __init__(
        self,
        result: RunResult,
        flag_list: list[str],
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

        counts = QLabel(
            f"Exported {result.exported} · Skipped {result.skipped} · "
            f"Failed {result.failed}"
        )
        counts.setWordWrap(True)
        layout.addWidget(counts)

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
