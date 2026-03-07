"""Summary table widgets for the two-layer status model.

Layer 1: Kit-level status (PASS/FAIL/PENDING)
Layer 2: Per-PVT output detail (from pvt_details) shown in PVT columns

Displays O/X/- status in a grid:
  - PVT kits tab: rows = kit names, columns = PVT corners (from pvt_details)
  - Other kits tab: rows = kit names, single status column

Supports:
  - Click to toggle status (PASS -> FAIL for re-run)
  - Color coding: O=green, X=red, -=gray
  - Right-click context menu for batch operations
"""

from typing import Dict, List, Optional

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

from kitdag.core.target import KitTarget, PvtStatus, TargetStatus


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

PVT_OK_COLOR = QColor(76, 175, 80)       # green
PVT_MISSING_COLOR = QColor(244, 67, 54)  # red
PVT_UNKNOWN_COLOR = QColor(158, 158, 158)  # gray


class SummaryTableWidget(QTabWidget):
    """Tabbed summary tables: PVT kits and other kits."""

    target_selected = Signal(str)          # emits target_id
    status_changed = Signal(str, str)      # emits (target_id, new_status)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pvt_table = _PvtKitTable()
        self._other_table = _OtherKitTable()

        self.addTab(self._pvt_table, "PVT Kits")
        self.addTab(self._other_table, "Other Kits")

        self._pvt_table.target_selected.connect(self.target_selected)
        self._pvt_table.status_changed.connect(self.status_changed)
        self._other_table.target_selected.connect(self.target_selected)
        self._other_table.status_changed.connect(self.status_changed)

    def update_data(
        self,
        pvt_kits: Dict[str, KitTarget],
        other_kits: Dict[str, KitTarget],
        pvts: List[str],
    ) -> None:
        """Update both tables with fresh data.

        Args:
            pvt_kits: {kit_name: KitTarget} — kits with pvt_details
            other_kits: {kit_name: KitTarget} — kits without PVT expansion
            pvts: ordered list of PVT corner names
        """
        self._pvt_table.update_data(pvt_kits, pvts)
        self._other_table.update_data(other_kits)

    def apply_filter(self, text: str) -> None:
        """Filter rows by kit name substring."""
        self._pvt_table.apply_filter(text)
        self._other_table.apply_filter(text)


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

    def _make_pvt_item(self, pvt_status: PvtStatus,
                       target_id: str) -> QTableWidgetItem:
        """Create a table cell for a per-PVT output check."""
        text = "O" if pvt_status.ok else "X"
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        color = PVT_OK_COLOR if pvt_status.ok else PVT_MISSING_COLOR
        item.setForeground(QBrush(QColor(255, 255, 255)))
        item.setBackground(QBrush(color))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, target_id)
        if not pvt_status.ok and pvt_status.missing_files:
            item.setToolTip("Missing: " + ", ".join(pvt_status.missing_files))
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


class _PvtKitTable(_BaseKitTable):
    """Two-layer table: rows = kit names, columns = Status + PVT corners.

    Column 0 = kit-level status (layer 1)
    Columns 1..N = per-PVT output status (layer 2, from pvt_details)
    """

    def update_data(
        self, kits: Dict[str, KitTarget], pvts: List[str]
    ) -> None:
        self.clear()
        kit_names = sorted(kits.keys())

        self.setRowCount(len(kit_names))
        self.setColumnCount(1 + len(pvts))
        self.setHorizontalHeaderLabels(["Status"] + pvts)
        self.setVerticalHeaderLabels(kit_names)

        for r, kit_name in enumerate(kit_names):
            target = kits[kit_name]

            # Column 0: kit-level status
            item = self._make_status_item(target)
            self.setItem(r, 0, item)

            # Build PVT lookup from pvt_details
            pvt_lookup = {p.pvt: p for p in target.pvt_details}

            # Columns 1..N: per-PVT output status
            for c, pvt in enumerate(pvts, start=1):
                pvt_status = pvt_lookup.get(pvt)
                if pvt_status:
                    pitem = self._make_pvt_item(pvt_status, target.id)
                else:
                    # No PVT detail available (kit hasn't run yet)
                    pitem = QTableWidgetItem("-")
                    pitem.setTextAlignment(Qt.AlignCenter)
                    pitem.setBackground(QBrush(PVT_UNKNOWN_COLOR))
                    pitem.setForeground(QBrush(QColor(255, 255, 255)))
                    pitem.setFlags(pitem.flags() & ~Qt.ItemIsEditable)
                    pitem.setData(Qt.UserRole, target.id)
                self.setItem(r, c, pitem)

        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)


class _OtherKitTable(_BaseKitTable):
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
