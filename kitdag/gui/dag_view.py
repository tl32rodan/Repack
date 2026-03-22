"""DAG visualization widget using QGraphicsView."""

import math
from typing import Dict, List, Optional, Tuple

from PySide2.QtCore import QPointF, Qt, Signal
from PySide2.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide2.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QVBoxLayout,
    QWidget,
)

from kitdag.core.dag import DAGBuilder
from kitdag.core.task import Task, TaskStatus


STATUS_COLORS = {
    TaskStatus.PASS: QColor(76, 175, 80),
    TaskStatus.FAIL: QColor(244, 67, 54),
    TaskStatus.SKIP: QColor(158, 158, 158),
    TaskStatus.PENDING: QColor(255, 193, 7),
    TaskStatus.RUNNING: QColor(33, 150, 243),
}

NODE_WIDTH = 120
NODE_HEIGHT = 40
H_SPACING = 160
V_SPACING = 70


class _NodeItem(QGraphicsEllipseItem):
    """A single DAG node."""

    def __init__(self, target_id: str, status: TaskStatus,
                 x: float, y: float):
        super().__init__(x, y, NODE_WIDTH, NODE_HEIGHT)
        self.target_id = target_id

        color = STATUS_COLORS.get(status, QColor(200, 200, 200))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(50, 50, 50), 1.5))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setToolTip(f"{target_id} [{status.value}]")

        label = QGraphicsSimpleTextItem(self._short_label(target_id), self)
        label.setFont(QFont("Sans", 7))
        label.setBrush(QBrush(QColor(255, 255, 255)))
        bounds = label.boundingRect()
        label.setPos(
            x + (NODE_WIDTH - bounds.width()) / 2,
            y + (NODE_HEIGHT - bounds.height()) / 2,
        )

    @staticmethod
    def _short_label(target_id: str) -> str:
        # Show step/branch for scoped IDs
        parts = target_id.split("/")
        if len(parts) >= 3:
            # step/lib=x/branch=y → step/y
            branch = parts[-1].split("=")[-1] if "=" in parts[-1] else parts[-1]
            return f"{parts[0]}/{branch}"
        if len(target_id) > 14:
            return target_id[:12] + ".."
        return target_id


class DAGViewWidget(QWidget):
    """Visualize the task dependency graph."""

    node_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene, self)
        self._view.setRenderHint(QPainter.Antialiasing)
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)
        layout.addWidget(self._view)

        self._scene.selectionChanged.connect(self._on_selection_changed)

    def update_dag(self, dag: DAGBuilder,
                   tasks: Dict[str, Task]) -> None:
        """Rebuild the DAG visualization."""
        self._scene.clear()

        stages = dag.get_execution_stages()
        if not stages:
            return

        node_positions: Dict[str, Tuple[float, float]] = {}

        for stage_idx, stage in enumerate(stages):
            x = stage_idx * H_SPACING + 20
            for node_idx, tid in enumerate(stage):
                y = node_idx * V_SPACING + 20
                status = tasks[tid].status if tid in tasks else TaskStatus.PENDING
                node = _NodeItem(tid, status, x, y)
                self._scene.addItem(node)
                node_positions[tid] = (x + NODE_WIDTH / 2, y + NODE_HEIGHT / 2)

        for tid in dag.get_all_tasks():
            deps = dag.get_dependencies(tid)
            if tid not in node_positions:
                continue
            tx, ty = node_positions[tid]
            for dep_id in deps:
                if dep_id not in node_positions:
                    continue
                dx, dy = node_positions[dep_id]
                self._draw_arrow(dx + NODE_WIDTH / 2, dy, tx - NODE_WIDTH / 2, ty)

        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _draw_arrow(self, x1: float, y1: float, x2: float, y2: float) -> None:
        pen = QPen(QColor(120, 120, 120), 1.5)

        path = QPainterPath()
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)

        item = QGraphicsPathItem(path)
        item.setPen(pen)
        self._scene.addItem(item)

        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_size = 8
        p1 = QPointF(
            x2 - arrow_size * math.cos(angle - math.pi / 6),
            y2 - arrow_size * math.sin(angle - math.pi / 6),
        )
        p2 = QPointF(
            x2 - arrow_size * math.cos(angle + math.pi / 6),
            y2 - arrow_size * math.sin(angle + math.pi / 6),
        )
        arrow_path = QPainterPath()
        arrow_path.moveTo(x2, y2)
        arrow_path.lineTo(p1)
        arrow_path.lineTo(p2)
        arrow_path.closeSubpath()

        arrow_item = QGraphicsPathItem(arrow_path)
        arrow_item.setBrush(QBrush(QColor(120, 120, 120)))
        arrow_item.setPen(QPen(Qt.NoPen))
        self._scene.addItem(arrow_item)

    def _on_selection_changed(self) -> None:
        items = self._scene.selectedItems()
        for item in items:
            if isinstance(item, _NodeItem):
                self.node_selected.emit(item.target_id)
                break
