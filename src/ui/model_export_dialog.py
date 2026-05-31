from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from src.ui.styled_dialog import StyledDialog


class ModelExportDialog(StyledDialog):
    def __init__(self, parent, title: str, description: str, file_names: List[str]):
        super().__init__(parent, title=title, width=520)
        self._file_names = file_names
        self._selected: Optional[List[str]] = None
        self.setModal(True)

        c = self._c
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Хедер ────────────────────────────────────────────────────── #
        root.addWidget(self.make_header(title))

        # ── Описание + список ─────────────────────────────────────────── #
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 12)
        body.setSpacing(10)

        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {c['text_sub']}; font-size: 11px;")
        body.addWidget(desc)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: rgba(255,255,255,0.02);
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 4px;
                color: {c['text']};
                font-size: 12px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 3px;
            }}
            QListWidget::item:hover {{
                background: rgba(255,255,255,0.04);
            }}
            QListWidget::item:selected {{
                background: rgba(255,255,255,0.06);
            }}
        """)
        body.addWidget(self.list_widget, 1)

        for name in file_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)

        # Кнопки select all / none
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        self.select_all_btn  = QPushButton("Select all")
        self.select_none_btn = QPushButton("Select none")
        for btn in (self.select_all_btn, self.select_none_btn):
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {c['text_sub']};
                    border: 1px solid {c['border']}; border-radius: 3px;
                    font-size: 11px; padding: 0 10px;
                }}
                QPushButton:hover {{
                    color: {c['text']}; border-color: {c['border_h']};
                }}
            """)
        sel_row.addWidget(self.select_all_btn)
        sel_row.addWidget(self.select_none_btn)
        sel_row.addStretch()
        body.addLayout(sel_row)

        root.addLayout(body)

        # ── Футер ─────────────────────────────────────────────────────── #
        root.addWidget(self.divider())

        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn     = QPushButton("Export")
        root.addWidget(self.make_footer([self.cancel_btn, self.ok_btn]))

        # ── Сигналы ───────────────────────────────────────────────────── #
        self.select_all_btn.clicked.connect(self._select_all)
        self.select_none_btn.clicked.connect(self._select_none)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._accept)

        self._apply_default_selection()
        self.resize(520, 480)

    def _apply_default_selection(self) -> None:
        lower = [n.lower() for n in self._file_names]
        for i, n in enumerate(lower):
            if n.endswith("_reference.smd") or ("reference" in n and n.endswith(".smd")):
                self.list_widget.item(i).setCheckState(Qt.Checked)
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
        self._selected = [
            self.list_widget.item(i).text()
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).checkState() == Qt.Checked
        ]
        self.accept()

    def selected_files(self) -> Optional[List[str]]:
        return self._selected

    def set_button_texts(self, select_all: str, select_none: str,
                         cancel: str, ok: str) -> None:
        self.select_all_btn.setText(select_all)
        self.select_none_btn.setText(select_none)
        self.cancel_btn.setText(cancel)
        self.ok_btn.setText(ok)
