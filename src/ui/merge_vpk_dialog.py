"""
Диалог выбора VPK модов для объединения — стиль StyledDialog.
"""

import os
from pathlib import Path
from typing import List

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget,
)
from PySide6.QtCore import Qt

from src.data.translations import TRANSLATIONS
from src.config.app_config import AppConfig
from src.shared.logging_config import get_logger
from src.ui.styled_dialog import StyledDialog

logger = get_logger(__name__)


class MergeVPKDialog(StyledDialog):
    """Диалог для выбора VPK файлов для объединения."""

    def __init__(self, parent=None):
        if parent and hasattr(parent, 't'):
            self.t = parent.t
        else:
            config = AppConfig.load_config()
            lang = config.get('language') or 'en'
            self.t = TRANSLATIONS[lang]

        title = self.t.get('merge_vpk_title', 'Merge Mods')
        super().__init__(parent, title=title, width=500)

        self.selected_vpk_files = []
        self.checkboxes: list = []
        self.vpk_files_list: list = []

        self._build_ui()
        self.load_vpk_files()

    def _build_ui(self):
        c = self._c
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Хедер ─────────────────────────────────────────────────────── #
        desc = self.t.get('merge_vpk_description', 'Select mods to merge into one VPK')
        root.addWidget(self.make_header(
            self.t.get('merge_vpk_title', 'Merge Mods'),
            subtitle=desc,
        ))

        # ── Список VPK с прокруткой ───────────────────────────────────── #
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 12)
        body.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(220)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {c['border']};
                border-radius: 4px;
                background: rgba(255,255,255,0.02);
            }}
            QScrollBar:vertical {{
                background: transparent; width: 4px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {c['border_h']}; border-radius: 2px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self.scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self.scroll_content)
        self._scroll_layout.setSpacing(4)
        self._scroll_layout.setContentsMargins(12, 10, 12, 10)
        scroll.setWidget(self.scroll_content)
        body.addWidget(scroll, 1)

        # Select all / none
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        self.select_all_btn  = QPushButton(self.t.get('select_all', 'Select all'))
        self.deselect_all_btn = QPushButton(self.t.get('deselect_all', 'Select none'))
        for btn in (self.select_all_btn, self.deselect_all_btn):
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
        sel_row.addWidget(self.deselect_all_btn)
        sel_row.addStretch()
        body.addLayout(sel_row)

        root.addLayout(body)

        # ── Футер ─────────────────────────────────────────────────────── #
        root.addWidget(self.divider())

        self.cancel_btn = QPushButton(self.t.get('cancel', 'Cancel'))
        self.merge_btn  = QPushButton(self.t.get('merge', 'Merge'))
        self.merge_btn.setEnabled(False)
        root.addWidget(self.make_footer([self.cancel_btn, self.merge_btn]))

        # ── Сигналы ───────────────────────────────────────────────────── #
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        self.cancel_btn.clicked.connect(self.reject)
        self.merge_btn.clicked.connect(self.accept)

        self.resize(500, 460)

    def load_vpk_files(self):
        config = AppConfig.load_config()
        export_path = Path(config.get('export_folder', 'export'))
        c = self._c

        if not export_path.exists():
            self._no_files_msg()
            return

        vpk_files = sorted(export_path.glob("*.vpk"), key=lambda x: x.name.lower())
        if not vpk_files:
            self._no_files_msg()
            return

        for vpk_file in vpk_files:
            cb = QCheckBox(vpk_file.name)
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {c['text']};
                    font-size: 12px;
                    padding: 4px 2px;
                    spacing: 10px;
                }}
                QCheckBox::indicator {{
                    width: 15px; height: 15px;
                    border: 1px solid {c['border_h']};
                    border-radius: 3px;
                    background: rgba(255,255,255,0.03);
                }}
                QCheckBox::indicator:checked {{
                    background: {c['accent']};
                    border-color: {c['accent']};
                }}
                QCheckBox:hover {{ color: {c['text']}; }}
            """)
            cb.stateChanged.connect(self._on_checkbox_changed)
            self.checkboxes.append(cb)
            self.vpk_files_list.append(vpk_file)
            self._scroll_layout.addWidget(cb)

        self._scroll_layout.addStretch()

    def _no_files_msg(self):
        c = self._c
        lbl = QLabel(self.t.get('no_vpk_files', 'No VPK files found in export folder'))
        lbl.setStyleSheet(f"color: {c['text_sub']}; font-size: 12px; padding: 20px;")
        lbl.setAlignment(Qt.AlignCenter)
        self._scroll_layout.addWidget(lbl)

    def _on_checkbox_changed(self):
        self.merge_btn.setEnabled(any(cb.isChecked() for cb in self.checkboxes))

    def select_all(self):
        for cb in self.checkboxes:
            cb.setChecked(True)

    def deselect_all(self):
        for cb in self.checkboxes:
            cb.setChecked(False)

    def get_selected_files(self) -> List[Path]:
        return [
            self.vpk_files_list[i]
            for i, cb in enumerate(self.checkboxes)
            if cb.isChecked()
        ]
