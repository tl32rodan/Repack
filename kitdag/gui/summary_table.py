"""Matrix summary table: collapsible lib groups, branch×step grid, PVT sub-tables.

Layout:
  ▼ lib_a
  ┌──────────┬─────────┬─────────┬─────────┐
  │          │ step0   │ step1   │ step2   │
  ├──────────┼─────────┼─────────┼─────────┤
  │ ss       │   O     │   X     │  [+]    │
  │ tt       │   O     │   O     │  [+]    │
  │ em       │   ─     │   O     │   ─     │
  └──────────┴─────────┴─────────┴─────────┘

  ► lib_b (collapsed)

Clicking [+] expands a PVT sub-table below the row.
"""

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QBrush, QColor, QFont
from PySide2.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kitdag.core.task import Task, TaskStatus, VariantDetail


# Status display
STATUS_DISPLAY = {
    TaskStatus.PASS: "O",
    TaskStatus.FAIL: "X",
    TaskStatus.SKIP: "-",
    TaskStatus.PENDING: "?",
    TaskStatus.RUNNING: "...",
}

STATUS_COLORS = {
    TaskStatus.PASS: QColor(76, 175, 80),
    TaskStatus.FAIL: QColor(244, 67, 54),
    TaskStatus.SKIP: QColor(158, 158, 158),
    TaskStatus.PENDING: QColor(255, 193, 7),
    TaskStatus.RUNNING: QColor(33, 150, 243),
}

NA_COLOR = QColor(80, 80, 80)
VARIANT_OK_COLOR = QColor(76, 175, 80)
VARIANT_FAIL_COLOR = QColor(244, 67, 54)
VARIANT_UNKNOWN_COLOR = QColor(158, 158, 158)


class MatrixSummaryWidget(QWidget):
    """Collapsible lib groups with branch×step matrix tables."""

    task_selected = Signal(str)    # emits task_id
    status_changed = Signal(str, str)  # emits (task_id, new_status)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._scroll_content)
        self._layout.addWidget(self._scroll)

        self._lib_groups: Dict[str, _LibGroup] = {}

    def update_data(
        self,
        tasks: Dict[str, Task],
        step_order: List[str],
    ) -> None:
        """Rebuild the display from task data.

        Args:
            tasks: all tasks keyed by task.id
            step_order: ordered list of step names (columns)
        """
        # Clear existing groups
        for group in self._lib_groups.values():
            group.setParent(None)
            group.deleteLater()
        self._lib_groups.clear()

        # Group tasks by lib
        lib_tasks: Dict[str, List[Task]] = defaultdict(list)
        for task in tasks.values():
            lib = task.scope.get("lib", "(global)")
            lib_tasks[lib].append(task)

        # Create a group widget for each lib
        for lib in sorted(lib_tasks.keys()):
            group = _LibGroup(lib, lib_tasks[lib], step_order)
            group.task_selected.connect(self.task_selected)
            group.status_changed.connect(self.status_changed)
            self._lib_groups[lib] = group
            self._scroll_layout.addWidget(group)

        self._scroll_layout.addStretch()

    def apply_filter(self, text: str) -> None:
        """Filter lib groups by text."""
        text = text.lower()
        for lib, group in self._lib_groups.items():
            visible = text in lib.lower() if text else True
            group.setVisible(visible)


class _LibGroup(QWidget):
    """Collapsible group for one library."""

    task_selected = Signal(str)
    status_changed = Signal(str, str)

    def __init__(
        self,
        lib: str,
        tasks: List[Task],
        step_order: List[str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._lib = lib
        self._tasks = tasks
        self._step_order = step_order
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        self._header = QPushButton()
        self._header.setStyleSheet(
            "QPushButton { text-align: left; padding: 6px 10px; "
            "background: #2a2a2a; color: #eee; border: none; "
            "font-weight: bold; font-size: 12px; }"
            "QPushButton:hover { background: #3a3a3a; }"
        )
        self._header.clicked.connect(self._toggle_collapse)
        layout.addWidget(self._header)

        # Matrix table
        self._table = _BranchStepTable(tasks, step_order)
        self._table.task_selected.connect(self.task_selected)
        self._table.status_changed.connect(self.status_changed)
        layout.addWidget(self._table)

        # Detail panel for PVT sub-table
        self._detail_panel = _VariantDetailPanel()
        self._detail_panel.setVisible(False)
        layout.addWidget(self._detail_panel)

        self._table.detail_requested.connect(self._show_detail)

        self._update_header()

    def _update_header(self) -> None:
        arrow = "▼" if not self._collapsed else "►"
        # Count stats
        total = len(self._tasks)
        passed = sum(1 for t in self._tasks if t.status == TaskStatus.PASS)
        failed = sum(1 for t in self._tasks if t.status == TaskStatus.FAIL)
        branches = set(t.branch for t in self._tasks if t.branch)
        summary_parts = [f"{len(branches)} branches"]
        if passed:
            summary_parts.append(f"{passed} O")
        if failed:
            summary_parts.append(f"{failed} X")
        summary = ", ".join(summary_parts)
        self._header.setText(f"{arrow}  {self._lib}  ({summary})")

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._table.setVisible(not self._collapsed)
        if self._collapsed:
            self._detail_panel.setVisible(False)
        self._update_header()

    def _show_detail(self, task_id: str, task: Task) -> None:
        if task.variant_details:
            self._detail_panel.show_details(task)
            self._detail_panel.setVisible(True)
        else:
            self._detail_panel.setVisible(False)


class _BranchStepTable(QTableWidget):
    """Matrix table: rows=branches, columns=steps."""

    task_selected = Signal(str)
    status_changed = Signal(str, str)
    detail_requested = Signal(str, Task)

    def __init__(
        self,
        tasks: List[Task],
        step_order: List[str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._task_map: Dict[Tuple[str, str], Task] = {}

        # Collect branches and applicable steps
        branches = sorted(set(t.branch for t in tasks if t.branch))
        if not branches:
            branches = [""]

        # Build task lookup: (branch, step) -> task
        for t in tasks:
            self._task_map[(t.branch, t.step_name)] = t

        # Filter step_order to only include steps that have tasks
        active_steps = set(t.step_name for t in tasks)
        steps = [s for s in step_order if s in active_steps]

        self.setRowCount(len(branches))
        self.setColumnCount(len(steps))
        self.setHorizontalHeaderLabels(steps)
        self.setVerticalHeaderLabels(branches if branches != [""] else ["(all)"])

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.cellClicked.connect(self._on_cell_clicked)
        self.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectItems)
        self.setFont(QFont("Monospace", 10))

        # Populate cells
        for r, branch in enumerate(branches):
            for c, step in enumerate(steps):
                task = self._task_map.get((branch, step))
                if task is None:
                    # N/A: branch doesn't apply to this step
                    item = QTableWidgetItem("─")
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setBackground(QBrush(NA_COLOR))
                    item.setForeground(QBrush(QColor(120, 120, 120)))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                else:
                    has_details = bool(task.variant_details)
                    if has_details:
                        text = "[+]" if task.status == TaskStatus.PASS else "[X]"
                    else:
                        text = STATUS_DISPLAY.get(task.status, "?")
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter)
                    color = STATUS_COLORS.get(task.status, QColor(200, 200, 200))
                    item.setForeground(QBrush(QColor(255, 255, 255)))
                    item.setBackground(QBrush(color))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setData(Qt.UserRole, task.id)
                    if task.error_message:
                        item.setToolTip(task.error_message)
                self.setItem(r, c, item)

        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        item = self.item(row, col)
        if item:
            task_id = item.data(Qt.UserRole)
            if task_id:
                self.task_selected.emit(task_id)
                # Check if detail view should open
                for task in self._task_map.values():
                    if task.id == task_id:
                        self.detail_requested.emit(task_id, task)
                        break

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        item = self.item(row, col)
        if not item:
            return
        task_id = item.data(Qt.UserRole)
        if not task_id:
            return
        current = item.text()
        if current in ("O", "[+]"):
            item.setText("X")
            item.setBackground(QBrush(STATUS_COLORS[TaskStatus.FAIL]))
            self.status_changed.emit(task_id, "FAIL")

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
                    item.setBackground(QBrush(STATUS_COLORS[TaskStatus.FAIL]))
                    self.status_changed.emit(tid, "FAIL")
        elif action == mark_skip:
            for item in selected:
                tid = item.data(Qt.UserRole)
                if tid:
                    item.setText("-")
                    item.setBackground(QBrush(STATUS_COLORS[TaskStatus.SKIP]))
                    self.status_changed.emit(tid, "SKIP")


class _VariantDetailPanel(QWidget):
    """Expandable panel showing PVT × product sub-table."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 4, 4, 4)

        self._title = QLabel()
        self._title.setStyleSheet("font-weight: bold; color: #aaa;")
        layout.addWidget(self._title)

        self._table = QTableWidget()
        self._table.setFont(QFont("Monospace", 9))
        self._table.setAlternatingRowColors(True)
        self._table.setMaximumHeight(200)
        layout.addWidget(self._table)

    def show_details(self, task: Task) -> None:
        """Show variant detail sub-table for a task."""
        self._title.setText(f"Detail: {task.id}")

        if not task.variant_details:
            self._table.clear()
            return

        # Group by variant: {variant: {product: VariantDetail}}
        variants = []
        products = []
        grid: Dict[str, Dict[str, VariantDetail]] = {}
        seen_variants = []
        seen_products = set()

        for d in task.variant_details:
            if d.variant not in grid:
                grid[d.variant] = {}
                seen_variants.append(d.variant)
            grid[d.variant][d.product] = d
            if d.product not in seen_products:
                products.append(d.product)
                seen_products.add(d.product)

        variants = seen_variants

        self._table.setRowCount(len(variants))
        self._table.setColumnCount(len(products))
        self._table.setHorizontalHeaderLabels(products)
        self._table.setVerticalHeaderLabels(variants)

        for r, variant in enumerate(variants):
            for c, product in enumerate(products):
                detail = grid.get(variant, {}).get(product)
                if detail:
                    text = "O" if detail.ok else "X"
                    color = VARIANT_OK_COLOR if detail.ok else VARIANT_FAIL_COLOR
                    item = QTableWidgetItem(text)
                    if detail.message:
                        item.setToolTip(detail.message)
                else:
                    text = "-"
                    color = VARIANT_UNKNOWN_COLOR
                    item = QTableWidgetItem(text)

                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(QBrush(QColor(255, 255, 255)))
                item.setBackground(QBrush(color))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(r, c, item)

        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
