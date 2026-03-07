"""Summary table widgets for corner-based and non-corner-based kits.

Displays O/X/- status in a grid:
  - Corner-based tab: rows = kit names, columns = PVT corners
  - Non-corner-based tab: rows = kit names, single status column

Supports:
  - Click to toggle status (PASS -> FAIL for re-run)
  - Color coding: O=green, X=red, -=gray
  - Right-click context menu for batch operations
"""

from typing import Dict, List, Optional, Callable

from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QBrush, QColor, QFont
from PySide2.QtWidgets import (
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from kitdag.core.target import KitTarget, TargetStatus


# Status display mapping
STATUS_DISPLAY = {
    TargetStatus.PASS: "O",
    TargetStatus.FAIL: "X",
    TargetStatus.SKIP: "-",
    TargetStatus.PENDING: "?",
    TargetStatus.RUNNING: "...",
}

STATUS_COLORS = {
    TargetStatus.PASS: QColor(76, 175, 80),       # green
    TargetStatus.FAIL: QColor(244, 67, 54),        # red
    TargetStatus.SKIP: QColor(158, 158, 158),      # gray
    TargetStatus.PENDING: QColor(255, 193, 7),     # amber
    TargetStatus.RUNNING: QColor(33, 150, 243),    # blue
}


class SummaryTableWidget(QTabWidget):
    """Tabbed summary tables: corner-based and non-corner-based kits."""

    target_selected = Signal(str)          # emits target_id
    status_changed = Signal(str, str)      # emits (target_id, new_status)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._corner_table = _CornerTable()
        self._non_corner_table = _NonCornerTable()

        self.addTab(self._corner_table, "Corner-Based Kits")
        self.addTab(self._non_corner_table, "Non-Corner-Based Kits")

        self._corner_table.target_selected.connect(self.target_selected)
        self._corner_table.status_changed.connect(self.status_changed)
        self._non_corner_table.target_selected.connect(self.target_selected)
        self._non_corner_table.status_changed.connect(self.status_changed)

    def update_data(
        self,
        corner_kits: Dict[str, Dict[str, KitTarget]],
        non_corner_kits: Dict[str, KitTarget],
        pvts: List[str],
    ) -> None:
        """Update both tables with fresh data.

        Args:
            corner_kits: {kit_name: {pvt: KitTarget}}
            non_corner_kits: {kit_name: KitTarget}
            pvts: ordered list of PVT corner names
        """
        self._corner_table.update_data(corner_kits, pvts)
        self._non_corner_table.update_data(non_corner_kits)

    def apply_filter(self, text: str) -> None:
        """Filter rows by kit name substring."""
        self._corner_table.apply_filter(text)
        self._non_corner_table.apply_filter(text)


class _BaseKitTable(QTableWidget):
    """Base table with shared functionality."""

    target_selected = Signal(str)
    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.cellClicked.connect(self._on_cell_clicked)
        self.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectItems)

        font = QFont("Monospace", 10)
        self.setFont(font)

        # target_id stored per cell
        self._cell_targets: Dict[tuple, str] = {}

    def _make_status_item(self, target: KitTarget) -> QTableWidgetItem:
        text = STATUS_DISPLAY.get(target.status, "?")
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        color = STATUS_COLORS.get(target.status, QColor(200, 200, 200))
        item.setForeground(QBrush(QColor(255, 255, 255)))
        item.setBackground(QBrush(color))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, target.id)
        return item

    def _on_cell_clicked(self, row: int, col: int) -> None:
        item = self.item(row, col)
        if item:
            target_id = item.data(Qt.UserRole)
            if target_id:
                self.target_selected.emit(target_id)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        """Double-click toggles PASS -> FAIL (to trigger re-run)."""
        item = self.item(row, col)
        if not item:
            return
        target_id = item.data(Qt.UserRole)
        if not target_id:
            return

        current = item.text()
        if current == "O":  # PASS -> mark as FAIL to re-run
            item.setText("X")
            color = STATUS_COLORS[TargetStatus.FAIL]
            item.setBackground(QBrush(color))
            self.status_changed.emit(target_id, "FAIL")

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        mark_fail = menu.addAction("Mark as FAIL (re-run)")
        mark_skip = menu.addAction("Mark as SKIP")

        selected = self.selectedItems()
        action = menu.exec_(self.mapToGlobal(pos))

        if action == mark_fail:
            for item in selected:
                tid = item.data(Qt.UserRole)
                if tid:
                    item.setText("X")
                    item.setBackground(QBrush(STATUS_COLORS[TargetStatus.FAIL]))
                    self.status_changed.emit(tid, "FAIL")
        elif action == mark_skip:
            for item in selected:
                tid = item.data(Qt.UserRole)
                if tid:
                    item.setText("-")
                    item.setBackground(QBrush(STATUS_COLORS[TargetStatus.SKIP]))
                    self.status_changed.emit(tid, "SKIP")

    def apply_filter(self, text: str) -> None:
        text = text.lower()
        for row in range(self.rowCount()):
            header = self.verticalHeaderItem(row)
            if header:
                visible = text in header.text().lower() if text else True
                self.setRowHidden(row, not visible)


class _CornerTable(_BaseKitTable):
    """2D table: rows = kit names, columns = PVT corners."""

    def update_data(
        self, kits: Dict[str, Dict[str, KitTarget]], pvts: List[str]
    ) -> None:
        self.clear()
        kit_names = sorted(kits.keys())

        self.setRowCount(len(kit_names))
        self.setColumnCount(len(pvts))
        self.setHorizontalHeaderLabels(pvts)
        self.setVerticalHeaderLabels(kit_names)

        for r, kit_name in enumerate(kit_names):
            targets = kits[kit_name]
            for c, pvt in enumerate(pvts):
                target = targets.get(pvt)
                if target:
                    item = self._make_status_item(target)
                else:
                    # No target for this PVT = SKIP
                    skip_target = KitTarget(kit_name=kit_name, pvt=pvt,
                                            status=TargetStatus.SKIP)
                    item = self._make_status_item(skip_target)
                self.setItem(r, c, item)

        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)


class _NonCornerTable(_BaseKitTable):
    """Single-column table: rows = kit names, column = status."""

    def update_data(self, kits: Dict[str, KitTarget]) -> None:
        self.clear()
        kit_names = sorted(kits.keys())

        self.setRowCount(len(kit_names))
        self.setColumnCount(1)
        self.setHorizontalHeaderLabels(["Status"])
        self.setVerticalHeaderLabels(kit_names)

        for r, kit_name in enumerate(kit_names):
            target = kits[kit_name]
            item = self._make_status_item(target)
            self.setItem(r, 0, item)

        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
