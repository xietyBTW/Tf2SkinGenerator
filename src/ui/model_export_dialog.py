from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.themes import get_modern_styles


class ModelExportDialog(QDialog):
    def __init__(self, parent, title: str, description: str, file_names: List[str]):
        super().__init__(parent)
        self._styles = get_modern_styles()
        self._file_names = file_names
        self._selected: Optional[List[str]] = None

        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel(description)
        header.setWordWrap(True)
        header.setStyleSheet("color: #ccc; font-size: 12px;")
        layout.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid #333;
                border-radius: 4px;
                padding: 6px;
            }
            QListWidget::item {
                padding: 6px 6px;
            }
        """)
        layout.addWidget(self.list_widget, 1)

        for name in file_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)

        button_row = QWidget()
        button_row_layout = QHBoxLayout(button_row)
        button_row_layout.setContentsMargins(0, 0, 0, 0)
        button_row_layout.setSpacing(8)

        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.setStyleSheet(self._styles["button_secondary"])
        self.select_all_btn.setMinimumHeight(34)
        self.select_none_btn = QPushButton("Select none")
        self.select_none_btn.setStyleSheet(self._styles["button_secondary"])
        self.select_none_btn.setMinimumHeight(34)
        button_row_layout.addWidget(self.select_all_btn)
        button_row_layout.addWidget(self.select_none_btn)
        button_row_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(self._styles["button_secondary"])
        self.cancel_btn.setMinimumHeight(34)
        self.ok_btn = QPushButton("Export")
        self.ok_btn.setStyleSheet(self._styles["button_primary"])
        self.ok_btn.setMinimumHeight(34)
        button_row_layout.addWidget(self.cancel_btn)
        button_row_layout.addWidget(self.ok_btn)

        layout.addWidget(button_row)

        self.select_all_btn.clicked.connect(self._select_all)
        self.select_none_btn.clicked.connect(self._select_none)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._accept)

        self._apply_default_selection()

        self.resize(520, 520)

    def _apply_default_selection(self) -> None:
        lower = [n.lower() for n in self._file_names]
        reference_idx = None
        for i, n in enumerate(lower):
            if n.endswith("_reference.smd") or "reference" in n and n.endswith(".smd"):
                reference_idx = i
                break
        if reference_idx is not None:
            self.list_widget.item(reference_idx).setCheckState(Qt.Checked)
            return
        for i, n in enumerate(lower):
            if n.endswith(".smd"):
                self.list_widget.item(i).setCheckState(Qt.Checked)
                break

    def _select_all(self) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Checked)

    def _select_none(self) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Unchecked)

    def _accept(self) -> None:
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        self._selected = selected
        self.accept()

    def selected_files(self) -> Optional[List[str]]:
        return self._selected

    def set_button_texts(self, select_all: str, select_none: str, cancel: str, ok: str) -> None:
        self.select_all_btn.setText(select_all)
        self.select_none_btn.setText(select_none)
        self.cancel_btn.setText(cancel)
        self.ok_btn.setText(ok)
