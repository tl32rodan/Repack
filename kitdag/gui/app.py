"""Main GUI application window for kitdag.

Assembles all GUI widgets:
  - FilterBar (top)
  - SummaryTable tabs (left)
  - LogViewer (right)
  - DAGView (bottom)
  - Status bar with summary counts
"""

import sys
from typing import Dict, List, Optional

from PySide2.QtCore import Qt
from PySide2.QtWidgets import (
    QAction,
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from kitdag.core.dag import DAGBuilder
from kitdag.core.target import KitTarget, TargetStatus
from kitdag.gui.dag_view import DAGViewWidget
from kitdag.gui.filter_bar import FilterBarWidget
from kitdag.gui.log_viewer import LogViewerWidget
from kitdag.gui.summary_table import SummaryTableWidget


class MainWindow(QMainWindow):
    """Main window for kitdag GUI."""

    def __init__(
        self,
        targets: Dict[str, KitTarget],
        dag: DAGBuilder,
        pvts: List[str],
        corner_kit_names: List[str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("KitDAG Summary")
        self.setMinimumSize(1200, 800)

        self._targets = targets
        self._dag = dag
        self._pvts = pvts
        self._corner_kit_names = set(corner_kit_names)

        self._setup_ui()
        self._refresh_data()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Filter bar
        self._filter_bar = FilterBarWidget()
        self._filter_bar.filter_changed.connect(self._on_filter_changed)
        main_layout.addWidget(self._filter_bar)

        # Main splitter: summary (left) | log viewer (right)
        h_splitter = QSplitter(Qt.Horizontal)

        # Summary table
        self._summary_table = SummaryTableWidget()
        self._summary_table.target_selected.connect(self._on_target_selected)
        self._summary_table.status_changed.connect(self._on_status_changed)
        h_splitter.addWidget(self._summary_table)

        # Log viewer
        self._log_viewer = LogViewerWidget()
        h_splitter.addWidget(self._log_viewer)

        h_splitter.setStretchFactor(0, 3)
        h_splitter.setStretchFactor(1, 2)

        # Vertical splitter: tables+log (top) | DAG (bottom)
        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.addWidget(h_splitter)

        self._dag_view = DAGViewWidget()
        self._dag_view.node_selected.connect(self._on_target_selected)
        v_splitter.addWidget(self._dag_view)

        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(v_splitter)

        # Toolbar
        toolbar = QToolBar("Actions")
        self.addToolBar(toolbar)

        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self._refresh_data)
        toolbar.addAction(refresh_action)

        rerun_action = QAction("Re-run Failed", self)
        rerun_action.triggered.connect(self._rerun_failed)
        toolbar.addAction(rerun_action)

        # Status bar
        self._status_label = QLabel()
        self.statusBar().addWidget(self._status_label)

    def _refresh_data(self) -> None:
        """Refresh all widgets with current target data."""
        corner_kits: Dict[str, Dict[str, KitTarget]] = {}
        non_corner_kits: Dict[str, KitTarget] = {}

        for tid, target in self._targets.items():
            if target.kit_name in self._corner_kit_names:
                if target.kit_name not in corner_kits:
                    corner_kits[target.kit_name] = {}
                corner_kits[target.kit_name][target.pvt] = target
            else:
                non_corner_kits[target.kit_name] = target

        self._summary_table.update_data(corner_kits, non_corner_kits, self._pvts)
        self._dag_view.update_dag(self._dag, self._targets)
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        counts: Dict[str, int] = {}
        for t in self._targets.values():
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1

        parts = []
        for status in [TargetStatus.PASS, TargetStatus.FAIL,
                       TargetStatus.PENDING, TargetStatus.RUNNING, TargetStatus.SKIP]:
            count = counts.get(status.value, 0)
            if count > 0:
                parts.append(f"{status.value}: {count}")

        total = len(self._targets)
        self._status_label.setText(f"Total: {total} | " + " | ".join(parts))

    def _on_target_selected(self, target_id: str) -> None:
        target = self._targets.get(target_id)
        if target and target.log_path:
            self._log_viewer.show_log(target.log_path)

    def _on_filter_changed(self, text: str) -> None:
        self._summary_table.apply_filter(text)

    def _on_status_changed(self, target_id: str, new_status: str) -> None:
        target = self._targets.get(target_id)
        if target:
            target.status = TargetStatus(new_status)
            self._update_status_bar()

    def _rerun_failed(self) -> None:
        failed = [
            tid for tid, t in self._targets.items()
            if t.status == TargetStatus.FAIL
        ]
        if not failed:
            QMessageBox.information(self, "Re-run", "No failed targets to re-run.")
            return

        reply = QMessageBox.question(
            self, "Re-run",
            f"Re-run {len(failed)} failed target(s)?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for tid in failed:
                self._targets[tid].status = TargetStatus.PENDING
            self._refresh_data()

    def update_targets(self, targets: Dict[str, KitTarget]) -> None:
        """Update targets from engine (e.g., after re-run)."""
        self._targets = targets
        self._refresh_data()


class KitDAGApp:
    """Convenience class for launching the GUI."""

    @staticmethod
    def launch(
        targets: Dict[str, KitTarget],
        dag: DAGBuilder,
        pvts: List[str],
        corner_kit_names: List[str],
    ) -> int:
        """Launch the GUI application.

        Args:
            targets: All targets with current status.
            dag: Built DAG for visualization.
            pvts: List of PVT corner names.
            corner_kit_names: Names of corner-based kits.

        Returns:
            Application exit code.
        """
        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow(targets, dag, pvts, corner_kit_names)
        window.show()
        return app.exec_()
