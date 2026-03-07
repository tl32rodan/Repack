"""Log viewer widget - displays target execution logs."""

import os
from typing import Optional

from PySide2.QtCore import Qt, QFileSystemWatcher
from PySide2.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide2.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _LogHighlighter(QSyntaxHighlighter):
    """Simple highlighter: errors in red, warnings in yellow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._error_fmt = QTextCharFormat()
        self._error_fmt.setForeground(QColor(244, 67, 54))
        self._error_fmt.setFontWeight(QFont.Bold)

        self._warn_fmt = QTextCharFormat()
        self._warn_fmt.setForeground(QColor(255, 152, 0))

        self._header_fmt = QTextCharFormat()
        self._header_fmt.setForeground(QColor(100, 181, 246))

    def highlightBlock(self, text: str) -> None:
        lower = text.lower()
        if text.startswith("#"):
            self.setFormat(0, len(text), self._header_fmt)
        elif "error" in lower or "fatal" in lower or "fail" in lower:
            self.setFormat(0, len(text), self._error_fmt)
        elif "warning" in lower or "warn" in lower:
            self.setFormat(0, len(text), self._warn_fmt)


class LogViewerWidget(QWidget):
    """Displays log file content for a selected target."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_path: Optional[str] = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QHBoxLayout()
        self._title = QLabel("No log selected")
        self._title.setStyleSheet("font-weight: bold; font-size: 12px;")
        header.addWidget(self._title)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._reload)
        header.addWidget(self._refresh_btn)

        self._tail_btn = QPushButton("Tail")
        self._tail_btn.setCheckable(True)
        self._tail_btn.setToolTip("Auto-scroll to bottom on updates")
        header.addWidget(self._tail_btn)

        layout.addLayout(header)

        # Text area
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Monospace", 9))
        self._text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._highlighter = _LogHighlighter(self._text.document())
        layout.addWidget(self._text)

    def show_log(self, log_path: str) -> None:
        """Load and display a log file."""
        # Unwatch previous
        if self._current_path and self._current_path in self._watcher.files():
            self._watcher.removePath(self._current_path)

        self._current_path = log_path
        self._title.setText(os.path.basename(log_path))
        self._reload()

        # Watch for live updates
        if os.path.exists(log_path):
            self._watcher.addPath(log_path)

    def _reload(self) -> None:
        if not self._current_path:
            return
        if not os.path.exists(self._current_path):
            self._text.setPlainText(f"Log file not found: {self._current_path}")
            return

        with open(self._current_path) as f:
            content = f.read()
        self._text.setPlainText(content)

        if self._tail_btn.isChecked():
            scrollbar = self._text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_file_changed(self, path: str) -> None:
        if path == self._current_path:
            self._reload()

    def clear_log(self) -> None:
        self._text.clear()
        self._title.setText("No log selected")
        self._current_path = None
