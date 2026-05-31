"""
Диалог ошибки — стилизован под dark-тему приложения.

Структура:
  [заголовок]
  ─────────────────────────────────────────
  Описание пользователю
  ─────────────────────────────────────────
  ▶ Технические детали   (скрыт по умолчанию)
  ─────────────────────────────────────────
  [Копировать детали]  [OK]
"""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.ui.styled_dialog import StyledDialog, _btn_primary, _btn_secondary


class ErrorDialog(StyledDialog):

    def __init__(
        self,
        parent,
        friendly_title: str,
        description: str,
        technical_details: str = "",
        language: str = "ru",
    ):
        win_title = "Ошибка" if language == "ru" else "Error"
        super().__init__(parent, title=win_title, width=540)
        self._language = language
        self._technical_details = technical_details.strip()
        self._details_visible = False
        self.setMinimumWidth(500)
        self.setMaximumWidth(720)

        self._build_ui(friendly_title, description)

    def _build_ui(self, title: str, description: str) -> None:
        is_ru = self._language == "ru"
        c = self._c
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Хедер ────────────────────────────────────────────────────── #
        root.addWidget(self.make_header(title))

        # ── Описание ─────────────────────────────────────────────────── #
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(12)

        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        desc.setStyleSheet(
            f"color: {c['text']}; font-size: 12px; line-height: 1.5;"
        )
        body.addWidget(desc)
        root.addLayout(body)

        # ── Технические детали ────────────────────────────────────────── #
        if self._technical_details:
            root.addWidget(self.divider())

            details_lay = QVBoxLayout()
            details_lay.setContentsMargins(20, 10, 20, 10)
            details_lay.setSpacing(8)

            toggle_text = "▶  Технические детали" if is_ru else "▶  Technical details"
            self._toggle_btn = QPushButton(toggle_text)
            self._toggle_btn.setFlat(True)
            self._toggle_btn.setCursor(Qt.PointingHandCursor)
            self._toggle_btn.setStyleSheet(
                f"QPushButton {{ text-align:left; color:{c['text_sub']}; "
                f"padding:0; border:none; font-size:11px; }}"
                f"QPushButton:hover {{ color:{c['text']}; }}"
            )
            self._toggle_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._toggle_btn.clicked.connect(self._toggle_details)
            details_lay.addWidget(self._toggle_btn)

            self._details_box = QTextEdit()
            self._details_box.setReadOnly(True)
            self._details_box.setPlainText(self._technical_details)
            self._details_box.setFont(QFont("Cascadia Mono, Consolas, Courier New", 9))
            self._details_box.setMinimumHeight(120)
            self._details_box.setMaximumHeight(260)
            self._details_box.setVisible(False)
            self._details_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._details_box.setStyleSheet(
                f"QTextEdit {{ background: {c['surface']}; color: {c['text']}; "
                f"border: 1px solid {c['border']}; border-radius: 4px; "
                f"padding: 8px; font-family: monospace; }}"
            )
            details_lay.addWidget(self._details_box)
            root.addLayout(details_lay)

        # ── Футер с кнопками ─────────────────────────────────────────── #
        root.addWidget(self.divider())

        buttons = []
        if self._technical_details:
            copy_label = "Копировать детали" if is_ru else "Copy details"
            copy_btn = QPushButton(copy_label)
            copy_btn.clicked.connect(self._copy_details)
            buttons.append(copy_btn)

        ok_btn = QPushButton("ОК" if is_ru else "OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        buttons.append(ok_btn)

        root.addWidget(self.make_footer(buttons))

    def _toggle_details(self) -> None:
        self._details_visible = not self._details_visible
        self._details_box.setVisible(self._details_visible)
        is_ru = self._language == "ru"
        arrow = "▼" if self._details_visible else "▶"
        label = (f"{arrow}  Технические детали" if is_ru
                 else f"{arrow}  Technical details")
        self._toggle_btn.setText(label)
        self.adjustSize()

    def _copy_details(self) -> None:
        QApplication.clipboard().setText(self._technical_details)

    @staticmethod
    def show(parent, friendly_title: str, description: str,
             technical_details: str = "", language: str = "ru") -> None:
        dlg = ErrorDialog(parent, friendly_title, description, technical_details, language)
        dlg.exec()
