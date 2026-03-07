"""DAG visualization widget using QGraphicsView."""

import math
from typing import Dict, List, Optional, Set, Tuple

from PySide2.QtCore import QPointF, QRectF, Qt, Signal
from PySide2.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide2.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QVBoxLayout,
    QWidget,
)

from kitdag.core.dag import DAGBuilder
from kitdag.core.target import KitTarget, TargetStatus


STATUS_COLORS = {
    TargetStatus.PASS: QColor(76, 175, 80),
    TargetStatus.FAIL: QColor(244, 67, 54),
    TargetStatus.SKIP: QColor(158, 158, 158),
    TargetStatus.PENDING: QColor(255, 193, 7),
    TargetStatus.RUNNING: QColor(33, 150, 243),
}

NODE_WIDTH = 120
NODE_HEIGHT = 40
H_SPACING = 160
V_SPACING = 70


class _NodeItem(QGraphicsEllipseItem):
    """A single DAG node (rounded rect via ellipse)."""

    def __init__(self, target_id: str, status: TargetStatus,
                 x: float, y: float):
        super().__init__(x, y, NODE_WIDTH, NODE_HEIGHT)
        self.target_id = target_id

        color = STATUS_COLORS.get(status, QColor(200, 200, 200))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(50, 50, 50), 1.5))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setToolTip(f"{target_id} [{status.value}]")

        # Label
        label = QGraphicsSimpleTextItem(self._short_label(target_id), self)
        label.setFont(QFont("Sans", 7))
        label.setBrush(QBrush(QColor(255, 255, 255)))
        # Center text
        bounds = label.boundingRect()
        label.setPos(
            x + (NODE_WIDTH - bounds.width()) / 2,
            y + (NODE_HEIGHT - bounds.height()) / 2,
        )

    @staticmethod
    def _short_label(target_id: str) -> str:
        parts = target_id.split("::")
        kit = parts[0]
        pvt = parts[1] if len(parts) > 1 else ""
        if len(kit) > 12:
            kit = kit[:10] + ".."
        if pvt and pvt != "ALL":
            return f"{kit}\n{pvt}"
        return kit


class DAGViewWidget(QWidget):
    """Visualize the target dependency graph."""

    node_selected = Signal(str)  # emits target_id

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
                   targets: Dict[str, KitTarget]) -> None:
        """Rebuild the DAG visualization."""
        self._scene.clear()

        stages = dag.get_execution_stages()
        if not stages:
            return

        node_positions: Dict[str, Tuple[float, float]] = {}
        node_items: Dict[str, _NodeItem] = {}

        # Layout: stages left to right, nodes in each stage top to bottom
        for stage_idx, stage in enumerate(stages):
            x = stage_idx * H_SPACING + 20
            for node_idx, tid in enumerate(stage):
                y = node_idx * V_SPACING + 20
                status = targets[tid].status if tid in targets else TargetStatus.PENDING
                node = _NodeItem(tid, status, x, y)
                self._scene.addItem(node)
                node_positions[tid] = (x + NODE_WIDTH / 2, y + NODE_HEIGHT / 2)
                node_items[tid] = node

        # Draw edges
        for tid in dag.get_all_targets():
            deps = dag.get_dependencies(tid)
            if tid not in node_positions:
                continue
            tx, ty = node_positions[tid]
            for dep_id in deps:
                if dep_id not in node_positions:
                    continue
                dx, dy = node_positions[dep_id]
                self._draw_arrow(dx + NODE_WIDTH / 2, dy, tx - NODE_WIDTH / 2, ty)

        # Fit view
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _draw_arrow(self, x1: float, y1: float, x2: float, y2: float) -> None:
        """Draw an arrow from (x1,y1) to (x2,y2)."""
        pen = QPen(QColor(120, 120, 120), 1.5)

        path = QPainterPath()
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)

        item = QGraphicsPathItem(path)
        item.setPen(pen)
        self._scene.addItem(item)

        # Arrowhead
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
