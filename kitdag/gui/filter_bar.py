"""Filter bar widget for searching and filtering kits/targets."""

from typing import Optional

from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from kitdag.core.target import TargetStatus


class FilterBarWidget(QWidget):
    """Search and filter bar for the summary table."""

    filter_changed = Signal(str)               # text filter
    status_filter_changed = Signal(list)        # list of TargetStatus to show

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Text search
        layout.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by kit name...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.filter_changed)
        layout.addWidget(self._search, stretch=1)

        # Status filter checkboxes
        layout.addWidget(QLabel("Show:"))
        self._status_checks = {}
        for status in [TargetStatus.PASS, TargetStatus.FAIL,
                       TargetStatus.PENDING, TargetStatus.SKIP]:
            cb = QCheckBox(status.value)
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_status_filter_changed)
            self._status_checks[status] = cb
            layout.addWidget(cb)

    def _on_status_filter_changed(self) -> None:
        active = [
            status for status, cb in self._status_checks.items()
            if cb.isChecked()
        ]
        self.status_filter_changed.emit(active)

    def get_text_filter(self) -> str:
        return self._search.text()

    def get_active_statuses(self) -> list:
        return [
            status for status, cb in self._status_checks.items()
            if cb.isChecked()
        ]
