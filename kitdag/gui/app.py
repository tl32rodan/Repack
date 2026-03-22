"""Main GUI application window for kitdag.

Assembles all GUI widgets:
  - FilterBar (top)
  - MatrixSummary — collapsible lib groups (left)
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
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from kitdag.core.dag import DAGBuilder
from kitdag.core.task import Task, TaskStatus
from kitdag.gui.dag_view import DAGViewWidget
from kitdag.gui.filter_bar import FilterBarWidget
from kitdag.gui.log_viewer import LogViewerWidget
from kitdag.gui.summary_table import MatrixSummaryWidget


class MainWindow(QMainWindow):
    """Main window for kitdag GUI."""

    def __init__(
        self,
        tasks: Dict[str, Task],
        dag: DAGBuilder,
        step_order: List[str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("KitDAG Dashboard")
        self.setMinimumSize(1200, 800)

        self._tasks = tasks
        self._dag = dag
        self._step_order = step_order

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

        # Matrix summary table
        self._summary = MatrixSummaryWidget()
        self._summary.task_selected.connect(self._on_task_selected)
        self._summary.status_changed.connect(self._on_status_changed)
        h_splitter.addWidget(self._summary)

        # Log viewer
        self._log_viewer = LogViewerWidget()
        h_splitter.addWidget(self._log_viewer)

        h_splitter.setStretchFactor(0, 3)
        h_splitter.setStretchFactor(1, 2)

        # Vertical splitter: tables+log (top) | DAG (bottom)
        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.addWidget(h_splitter)

        self._dag_view = DAGViewWidget()
        self._dag_view.node_selected.connect(self._on_task_selected)
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
        """Refresh all widgets with current task data."""
        self._summary.update_data(self._tasks, self._step_order)
        self._dag_view.update_dag(self._dag, self._tasks)
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        counts: Dict[str, int] = {}
        for t in self._tasks.values():
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1

        parts = []
        for status in [TaskStatus.PASS, TaskStatus.FAIL,
                       TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.SKIP]:
            count = counts.get(status.value, 0)
            if count > 0:
                parts.append(f"{status.value}: {count}")

        total = len(self._tasks)
        self._status_label.setText(f"Total: {total} | " + " | ".join(parts))

    def _on_task_selected(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task and task.log_path:
            self._log_viewer.show_log(task.log_path)

    def _on_filter_changed(self, text: str) -> None:
        self._summary.apply_filter(text)

    def _on_status_changed(self, task_id: str, new_status: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus(new_status)
            self._update_status_bar()

    def _rerun_failed(self) -> None:
        failed = [
            tid for tid, t in self._tasks.items()
            if t.status == TaskStatus.FAIL
        ]
        if not failed:
            QMessageBox.information(self, "Re-run", "No failed tasks to re-run.")
            return

        reply = QMessageBox.question(
            self, "Re-run",
            f"Re-run {len(failed)} failed task(s)?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for tid in failed:
                self._tasks[tid].status = TaskStatus.PENDING
            self._refresh_data()

    def update_tasks(self, tasks: Dict[str, Task]) -> None:
        """Update tasks from engine (e.g., after re-run)."""
        self._tasks = tasks
        self._refresh_data()


class KitDAGApp:
    """Convenience class for launching the GUI."""

    @staticmethod
    def launch(
        tasks: Dict[str, Task],
        dag: DAGBuilder,
        step_order: List[str],
    ) -> int:
        """Launch the GUI application.

        Args:
            tasks: All tasks with current status.
            dag: Built DAG for visualization.
            step_order: Ordered list of step names.

        Returns:
            Application exit code.
        """
        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow(tasks, dag, step_order)
        window.show()
        return app.exec_()
