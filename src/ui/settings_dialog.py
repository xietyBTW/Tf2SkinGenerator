"""
Диалог настроек приложения — минималистичный дизайн.
"""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QComboBox, QCheckBox, QWidget, QFrame,
    QScrollArea,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from src.config.app_config import AppConfig
from src.shared.logging_config import get_logger
from src.ui.styled_dialog import StyledDialog

logger = get_logger(__name__)

# ── Токены дизайна ────────────────────────────────────────────────────────── #
_BG       = "#161616"
_SURFACE  = "#1d1d1d"
_BORDER   = "#262626"
_BORDER_H = "#383838"
_TEXT     = "#c0c0c0"
_TEXT_DIM = "#484848"
_TEXT_SUB = "#666"
_ACCENT   = "#cc5522"    # кнопка Save
_FH       = 34           # высота полей/кнопок


# ── Вспомогательные фабрики виджетов ─────────────────────────────────────── #

def _section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {_TEXT_DIM}; font-size: 10px; font-weight: 700; "
        f"letter-spacing: 0.10em; background: transparent; border: none;"
    )
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {_BORDER}; border: none;")
    return line


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {_TEXT_SUB}; font-size: 11.5px; background: transparent; border: none;"
    )
    return lbl


_FIELD_STYLE = f"""
    QLineEdit {{
        background: rgba(255,255,255,0.03);
        color: {_TEXT};
        border: 1px solid {_BORDER};
        border-radius: 4px;
        padding: 0 10px;
        font-size: 12px;
        selection-background-color: #444;
    }}
    QLineEdit:hover  {{ border-color: {_BORDER_H}; }}
    QLineEdit:focus  {{ border-color: #404040; background: rgba(255,255,255,0.045); }}
    QLineEdit::placeholder {{ color: #383838; }}
"""

_COMBO_STYLE = f"""
    QComboBox {{
        background: rgba(255,255,255,0.03);
        color: #888;
        border: 1px solid {_BORDER};
        border-radius: 4px;
        padding: 0 10px;
        font-size: 12px;
        min-height: {_FH}px;
        max-height: {_FH}px;
    }}
    QComboBox:hover {{ border-color: {_BORDER_H}; color: #aaa; }}
    QComboBox:on    {{ border-color: #404040; background: rgba(255,255,255,0.045); color: #aaa; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{
        image: none;
        border-left:  4px solid transparent;
        border-right: 4px solid transparent;
        border-top:   5px solid #484848;
        margin-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background: #181818;
        color: #888;
        border: 1px solid #303030;
        selection-background-color: #242424;
        selection-color: #c0c0c0;
        outline: none;
        padding: 2px 0;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 28px;
        padding: 0 10px;
        border: none;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: #202020;
        color: #b0b0b0;
    }}
"""

_BROWSE_STYLE = f"""
    QPushButton {{
        background: rgba(255,255,255,0.03);
        color: #555;
        border: 1px solid {_BORDER};
        border-radius: 4px;
        font-size: 14px;
        padding: 0;
    }}
    QPushButton:hover  {{ background: rgba(255,255,255,0.06); border-color: {_BORDER_H}; color: #888; }}
    QPushButton:pressed {{ background: rgba(255,255,255,0.09); }}
"""

import os as _os
_CHECKMARK_SVG = _os.path.join(
    _os.path.dirname(__file__), "resources", "checkmark.svg"
).replace("\\", "/")

_CHECK_STYLE = f"""
    QCheckBox {{
        color: {_TEXT_SUB};
        font-size: 12px;
        spacing: 8px;
        background: transparent;
        border: none;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {_BORDER_H};
        border-radius: 3px;
        background: rgba(255,255,255,0.03);
    }}
    QCheckBox::indicator:hover {{
        border-color: #505050;
        background: rgba(255,255,255,0.05);
    }}
    QCheckBox::indicator:checked {{
        background: rgba(255,255,255,0.06);
        border-color: #707070;
        image: url("{_CHECKMARK_SVG}");
    }}
    QCheckBox:hover {{ color: {_TEXT}; }}
"""


def _line_edit(placeholder: str = "") -> QLineEdit:
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setFixedHeight(_FH)
    w.setStyleSheet(_FIELD_STYLE)
    return w


def _combo() -> QComboBox:
    w = QComboBox()
    w.setFixedHeight(_FH)
    w.setFixedWidth(150)
    w.setStyleSheet(_COMBO_STYLE)
    return w


def _browse_btn() -> QPushButton:
    btn = QPushButton("···")
    btn.setFixedSize(_FH, _FH)
    btn.setStyleSheet(_BROWSE_STYLE)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def _pref_row(label_text: str, control: QWidget) -> QHBoxLayout:
    """Горизонтальная строка: подпись слева, контрол справа."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    lbl = QLabel(label_text)
    lbl.setStyleSheet(
        f"color: {_TEXT_SUB}; font-size: 12px; background: transparent; border: none;"
    )
    row.addWidget(lbl)
    row.addStretch()
    row.addWidget(control)
    return row


# ── Основной класс ────────────────────────────────────────────────────────── #

class SettingsDialog(StyledDialog):
    def __init__(self, parent=None):
        from src.data.translations import TRANSLATIONS
        self.config = AppConfig.load_config()
        current_lang = self.config.get('language') or 'en'
        self.t = TRANSLATIONS[current_lang]

        title = self.t.get('settings_title', 'Settings')
        super().__init__(parent, title=title, width=480)

        self._init_ui()
        self.load_settings()

    # ── Построение UI ─────────────────────────────────────────────────────── #

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Хедер от StyledDialog (безрамочный + перетаскивание + кнопка ×)
        root.addWidget(self.make_header(self.t.get('settings_title', 'Settings')))
        root.addWidget(self._build_body())
        root.addWidget(self._build_footer())

    def _build_body(self) -> QWidget:
        c = self._c   # цвета из StyledDialog (учитывает тему dark/blue)
        w = QWidget()
        w.setStyleSheet(f"background: {c['bg']};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(0)

        # ── Пути ─────────────────────────────────────────────────────────── #
        lay.addWidget(_section_header(self.t.get('section_paths', 'PATHS')))
        lay.addSpacing(12)

        lay.addWidget(_field_label(self.t.get('tf2_folder_label', 'TF2 Game Folder')))
        lay.addSpacing(5)
        tf2_row = QHBoxLayout()
        tf2_row.setSpacing(6)
        self.tf2_game_path = _line_edit(self.t.get('tf2_folder_placeholder', 'Path to TF2'))
        self._tf2_browse = _browse_btn()
        self._tf2_browse.clicked.connect(self.browse_tf2_game_folder)
        tf2_row.addWidget(self.tf2_game_path)
        tf2_row.addWidget(self._tf2_browse)
        lay.addLayout(tf2_row)
        lay.addSpacing(12)

        lay.addWidget(_field_label(self.t.get('export_folder_label', 'Export Folder')))
        lay.addSpacing(5)
        exp_row = QHBoxLayout()
        exp_row.setSpacing(6)
        self.export_folder_path = _line_edit(self.t.get('export_folder_placeholder', 'Select export folder'))
        self._exp_browse = _browse_btn()
        self._exp_browse.clicked.connect(self.browse_export_folder)
        exp_row.addWidget(self.export_folder_path)
        exp_row.addWidget(self._exp_browse)
        lay.addLayout(exp_row)

        lay.addSpacing(22)
        lay.addWidget(_divider())
        lay.addSpacing(22)

        # ── Настройки ────────────────────────────────────────────────────── #
        lay.addWidget(_section_header(self.t.get('section_preferences', 'PREFERENCES')))
        lay.addSpacing(12)

        self.language_combo = _combo()
        self.language_combo.addItem("Русский", "ru")
        self.language_combo.addItem("English", "en")
        lay.addLayout(_pref_row(self.t.get('language_label', 'Language'), self.language_combo))
        lay.addSpacing(10)

        self.export_format_combo = _combo()
        for fmt in ("VTF", "PNG", "TGA", "JPG"):
            self.export_format_combo.addItem(fmt, fmt)
        lay.addLayout(_pref_row(
            self.t.get('export_image_format_label', 'Export Format'),
            self.export_format_combo,
        ))
        lay.addSpacing(10)

        self.theme_combo = _combo()
        self.theme_combo.addItem(self.t.get('theme_dark', 'Dark'), "dark")
        self.theme_combo.addItem(self.t.get('theme_blue', 'Blue'), "blue")
        lay.addLayout(_pref_row(self.t.get('theme_label', 'Theme'), self.theme_combo))

        lay.addSpacing(22)
        lay.addWidget(_divider())
        lay.addSpacing(22)

        # ── Разработчик ──────────────────────────────────────────────────── #
        lay.addWidget(_section_header(self.t.get('section_developer', 'DEVELOPER')))
        lay.addSpacing(12)

        self.keep_temp_checkbox = QCheckBox(self.t.get('keep_temp_files', 'Keep temp files'))
        self.keep_temp_checkbox.setStyleSheet(_CHECK_STYLE)
        lay.addWidget(self.keep_temp_checkbox)
        lay.addSpacing(8)

        self.debug_mode_checkbox = QCheckBox(self.t.get('debug_mode', 'Debug mode'))
        self.debug_mode_checkbox.setStyleSheet(_CHECK_STYLE)
        lay.addWidget(self.debug_mode_checkbox)

        lay.addSpacing(22)
        lay.addWidget(_divider())
        lay.addSpacing(18)

        # ── Поддержка ────────────────────────────────────────────────────── #
        supp_row = QHBoxLayout()
        supp_row.setContentsMargins(0, 0, 0, 0)
        supp_lbl = QLabel(self.t.get('support_header', 'Support'))
        supp_lbl.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 11.5px; background: transparent; border: none;"
        )
        supp_btn = QPushButton(self.t.get('support', 'Open link'))
        supp_btn.setCursor(Qt.PointingHandCursor)
        supp_btn.setStyleSheet(f"""
            QPushButton {{
                color: #4e7baa;
                background: transparent;
                border: none;
                font-size: 11.5px;
                padding: 0;
            }}
            QPushButton:hover {{ color: #6a9ece; text-decoration: underline; }}
        """)
        supp_btn.clicked.connect(self.open_support_link)
        supp_row.addWidget(supp_lbl)
        supp_row.addStretch()
        supp_row.addWidget(supp_btn)
        lay.addLayout(supp_row)

        lay.addStretch()
        return w

    def _build_footer(self) -> QWidget:
        self.cancel_button = QPushButton(self.t.get('cancel', 'Cancel'))
        self.save_button   = QPushButton(self.t.get('save', 'Save'))
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.save_settings)
        return self.make_footer([self.cancel_button, self.save_button])

    # ── Логика ───────────────────────────────────────────────────────────── #

    def browse_tf2_game_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            self.t.get('tf2_folder_placeholder', 'Select TF2 folder'),
            self.tf2_game_path.text() or "",
        )
        if folder:
            self.tf2_game_path.setText(folder)

    def browse_export_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            self.t.get('export_folder_placeholder', 'Select export folder'),
            self.export_folder_path.text() or "",
        )
        if folder:
            self.export_folder_path.setText(folder)

    def load_settings(self):
        tf2_path = self.config.get("tf2_game_folder", "")
        if tf2_path:
            self.tf2_game_path.setText(tf2_path)

        export_path = self.config.get("export_folder", "export")
        self.export_folder_path.setText(export_path)

        idx = self.export_format_combo.findData(self.config.get("export_image_format", "PNG"))
        if idx >= 0:
            self.export_format_combo.setCurrentIndex(idx)

        idx = self.language_combo.findData(self.config.get("language", "en"))
        if idx >= 0:
            self.language_combo.setCurrentIndex(idx)

        idx = self.theme_combo.findData(self.config.get("theme", "dark"))
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

        self.keep_temp_checkbox.setChecked(self.config.get("keep_temp_files", False))
        self.debug_mode_checkbox.setChecked(self.config.get("debug_mode", False))

    def save_settings(self):
        self.config["tf2_game_folder"]  = self.tf2_game_path.text().strip()
        self.config["export_folder"]    = self.export_folder_path.text().strip() or "export"
        self.config["export_image_format"] = self.export_format_combo.currentData()
        self.config["language"]         = self.language_combo.currentData()
        self.config["theme"]            = self.theme_combo.currentData()
        self.config["keep_temp_files"]  = self.keep_temp_checkbox.isChecked()
        self.config["debug_mode"]       = self.debug_mode_checkbox.isChecked()

        AppConfig.save_config(self.config)

        # Применяем язык
        if hasattr(self.parent(), 'change_language_from_combo'):
            self.parent().change_language_from_combo(self.language_combo.currentIndex())

        # Применяем тему
        from src.utils.themes import apply_theme
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            apply_theme(app, self.config["theme"])

        self.accept()

    def open_support_link(self):
        QDesktopServices.openUrl(
            QUrl("https://steamcommunity.com/tradeoffer/new/?partner=394814324&token=GNGCagXk")
        )

