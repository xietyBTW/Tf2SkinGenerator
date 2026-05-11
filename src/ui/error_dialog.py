"""
Диалог ошибки с разворачиваемыми техническими деталями.

Структура:
  [иконка] Понятный заголовок (жирный)
           Описание для пользователя

  ─────────────────────────────────────────
  ▶ Технические детали          ← кнопка
  [монош. текст с raw ошибкой]  ← скрыт по умолчанию
  ─────────────────────────────────────────
  [Копировать детали]  [OK]
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame, QApplication, QSizePolicy, QStyle,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QPalette

from typing import Optional


class ErrorDialog(QDialog):

    def __init__(
        self,
        parent,
        friendly_title: str,
        description: str,
        technical_details: str = "",
        language: str = "ru",
    ):
        super().__init__(parent)
        self._language = language
        self._technical_details = technical_details.strip()
        self._details_visible = False

        win_title = "Ошибка" if language == "ru" else "Error"
        self.setWindowTitle(win_title)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setMinimumWidth(500)
        self.setMaximumWidth(720)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        self._build_ui(friendly_title, description)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self, title: str, description: str) -> None:
        is_ru = self._language == "ru"
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Верхняя секция: иконка + заголовок + описание ──────────────
        top = QVBoxLayout()
        top.setSpacing(10)
        top.setContentsMargins(24, 24, 24, 20)

        header = QHBoxLayout()
        header.setSpacing(14)
        header.setAlignment(Qt.AlignTop)

        # Иконка ошибки из системной темы
        icon_label = QLabel()
        icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxCritical)
        icon_label.setPixmap(icon.pixmap(36, 36))
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        header.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        title_label = QLabel(title)
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        title_label.setFont(f)
        title_label.setWordWrap(True)
        text_col.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        desc_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        text_col.addWidget(desc_label)

        header.addLayout(text_col, 1)
        top.addLayout(header)
        root.addLayout(top)

        # ── Разделитель ───────────────────────────────────────────────
        sep_top = self._make_separator()
        root.addWidget(sep_top)

        # ── Секция технических деталей ────────────────────────────────
        if self._technical_details:
            details_section = QVBoxLayout()
            details_section.setSpacing(8)
            details_section.setContentsMargins(24, 12, 24, 12)

            toggle_text = (
                "▶  Технические детали" if is_ru else "▶  Technical details"
            )
            self._toggle_btn = QPushButton(toggle_text)
            self._toggle_btn.setFlat(True)
            self._toggle_btn.setCursor(Qt.PointingHandCursor)
            self._toggle_btn.setStyleSheet(
                "QPushButton { text-align: left; color: #888888; padding: 0px; border: none; }"
                "QPushButton:hover { color: #aaaaaa; }"
            )
            self._toggle_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._toggle_btn.clicked.connect(self._toggle_details)
            details_section.addWidget(self._toggle_btn)

            self._details_box = QTextEdit()
            self._details_box.setReadOnly(True)
            self._details_box.setPlainText(self._technical_details)
            mono = QFont("Cascadia Mono, Consolas, Courier New", 9)
            mono.setStyleHint(QFont.Monospace)
            self._details_box.setFont(mono)
            self._details_box.setMinimumHeight(130)
            self._details_box.setMaximumHeight(280)
            self._details_box.setVisible(False)
            self._details_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            # Слегка тонируем фон текстового поля чтобы выглядело как консоль
            pal = self._details_box.palette()
            bg = pal.color(QPalette.Base)
            darker = QColor(
                max(0, bg.red() - 12),
                max(0, bg.green() - 12),
                max(0, bg.blue() - 12),
            )
            pal.setColor(QPalette.Base, darker)
            self._details_box.setPalette(pal)

            details_section.addWidget(self._details_box)
            root.addLayout(details_section)

            sep_bot = self._make_separator()
            root.addWidget(sep_bot)

        # ── Кнопки ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(24, 12, 24, 20)
        btn_row.setSpacing(8)
        btn_row.addStretch()

        if self._technical_details:
            copy_label = "Копировать детали" if is_ru else "Copy details"
            copy_btn = QPushButton(copy_label)
            copy_btn.setMinimumWidth(140)
            copy_btn.clicked.connect(self._copy_details)
            btn_row.addWidget(copy_btn)

        ok_btn = QPushButton("ОК" if is_ru else "OK")
        ok_btn.setDefault(True)
        ok_btn.setMinimumWidth(80)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        return sep

    def _toggle_details(self) -> None:
        self._details_visible = not self._details_visible
        self._details_box.setVisible(self._details_visible)
        is_ru = self._language == "ru"
        arrow = "▼" if self._details_visible else "▶"
        label = (
            f"{arrow}  Технические детали" if is_ru
            else f"{arrow}  Technical details"
        )
        self._toggle_btn.setText(label)
        self.adjustSize()

    def _copy_details(self) -> None:
        QApplication.clipboard().setText(self._technical_details)

    # ------------------------------------------------------------------
    # Удобный статический метод
    # ------------------------------------------------------------------

    @staticmethod
    def show(
        parent,
        friendly_title: str,
        description: str,
        technical_details: str = "",
        language: str = "ru",
    ) -> None:
        dlg = ErrorDialog(parent, friendly_title, description, technical_details, language)
        dlg.exec()
