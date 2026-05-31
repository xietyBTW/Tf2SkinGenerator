"""
Базовый стилизованный диалог — безрамочный dark-стиль для всего приложения.
Соответствует стилю BuildProgressDialog (загрузочного окна).
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QSizePolicy,
)
from PySide6.QtGui import QMouseEvent
from src.config.app_config import AppConfig

# ── Дизайн-токены ─────────────────────────────────────────────────────────── #
_DARK = {
    'bg':       '#0a0a0a',
    'surface':  '#111111',
    'border':   '#1e1e1e',
    'border_h': '#2a2a2a',
    'text':     '#c8c8c8',
    'text_dim': '#484848',
    'text_sub': '#666666',
    'accent':   '#cc5522',
}
_BLUE = {
    'bg':       '#0d1b2a',
    'surface':  '#121f30',
    'border':   '#1e3248',
    'border_h': '#2a4a6a',
    'text':     '#e0e1dd',
    'text_dim': '#3a5070',
    'text_sub': '#4a6888',
    'accent':   '#3a7fd4',
}


def _colors() -> dict:
    theme = AppConfig.get('theme', 'dark')
    return _BLUE if theme == 'blue' else _DARK


def _dialog_style(c: dict) -> str:
    return f"""
        QDialog {{
            background: {c['bg']};
            border: 1px solid {c['border']};
        }}
        QLabel {{
            background: transparent;
            border: none;
        }}
        QFrame {{
            background: transparent;
        }}
        QScrollBar:vertical {{
            background: transparent; width: 4px; margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {c['border_h']}; border-radius: 2px; min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def _btn_primary(c: dict) -> str:
    return f"""
        QPushButton {{
            background: {c['accent']}; color: #fff; border: none;
            border-radius: 4px; font-size: 12px; font-weight: 600;
            padding: 0 18px; min-height: 32px;
        }}
        QPushButton:hover {{ background: rgba(220,80,30,0.9); }}
        QPushButton:disabled {{ background: #2a2a2a; color: #555; }}
    """


def _btn_secondary(c: dict) -> str:
    return f"""
        QPushButton {{
            background: rgba(255,255,255,0.03); color: {c['text_sub']};
            border: 1px solid {c['border']}; border-radius: 4px;
            font-size: 12px; padding: 0 14px; min-height: 32px;
        }}
        QPushButton:hover {{
            color: {c['text']}; border-color: {c['border_h']};
            background: rgba(255,255,255,0.05);
        }}
        QPushButton:disabled {{ opacity: 0.4; }}
    """


def _divider(c: dict) -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {c['border']}; border: none;")
    return f


def _section_label(text: str, c: dict) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {c['text_dim']}; font-size: 9px; font-weight: 700; "
        f"letter-spacing: 0.12em;"
    )
    return lbl


class StyledDialog(QDialog):
    """
    Базовый безрамочный диалог в стиле приложения.

    Особенности:
    - Без системной рамки (FramelessWindowHint)
    - Перетаскивание за хедер мышью
    - Кнопка × в правом углу хедера
    - Единая dark/blue тема
    """

    def __init__(self, parent=None, title: str = "TF2 Skin Generator",
                 width: int = 480):
        super().__init__(parent)
        self._c = _colors()
        self._drag_pos: QPoint = QPoint()
        self._dragging = False

        self.setWindowTitle(title)
        self.setFixedWidth(width)

        # Безрамочный режим — как у BuildProgressDialog
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setModal(True)

        self.setStyleSheet(_dialog_style(self._c))

    # ── Перетаскивание ────────────────────────────────────────────────── #

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False

    # ── Helpers для дочерних классов ─────────────────────────────────── #

    def make_header(self, title: str, subtitle: str = "",
                    show_close: bool = True) -> QWidget:
        """Хедер с заголовком и кнопкой ×."""
        c = self._c
        h = 52 if not subtitle else 64
        w = QWidget()
        w.setFixedHeight(h)
        w.setStyleSheet(
            f"QWidget {{ background: {c['bg']}; "
            f"border-bottom: 1px solid {c['border']}; }}"
        )
        # Хедер перетаскивает окно
        w.mousePressEvent   = self.mousePressEvent
        w.mouseMoveEvent    = self.mouseMoveEvent
        w.mouseReleaseEvent = self.mouseReleaseEvent

        outer = QHBoxLayout(w)
        outer.setContentsMargins(20, 0, 12, 0)
        outer.setSpacing(0)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setAlignment(Qt.AlignVCenter)

        t = QLabel(title)
        t.setStyleSheet(
            f"color: {c['text']}; font-size: 13px; font-weight: 600;"
        )
        text_col.addWidget(t)

        if subtitle:
            s = QLabel(subtitle)
            s.setStyleSheet(f"color: {c['text_sub']}; font-size: 11px;")
            text_col.addWidget(s)

        outer.addLayout(text_col, 1)

        if show_close:
            close_btn = QPushButton("×")
            close_btn.setFixedSize(28, 28)
            close_btn.setCursor(Qt.PointingHandCursor)
            close_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {c['text_dim']};
                    border: none;
                    font-size: 18px;
                    font-weight: 300;
                    border-radius: 4px;
                    padding: 0;
                }}
                QPushButton:hover {{
                    background: rgba(255,255,255,0.06);
                    color: {c['text']};
                }}
            """)
            close_btn.clicked.connect(self.reject)
            outer.addWidget(close_btn, 0, Qt.AlignVCenter)

        return w

    def make_footer(self, buttons: list) -> QWidget:
        """Футер с кнопками. Последняя — primary."""
        c = self._c
        w = QWidget()
        w.setFixedHeight(56)
        w.setStyleSheet(
            f"QWidget {{ background: {c['surface']}; "
            f"border-top: 1px solid {c['border']}; }}"
        )
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(8)
        lay.addStretch()
        for i, btn in enumerate(buttons):
            is_primary = (i == len(buttons) - 1)
            btn.setStyleSheet(
                _btn_primary(c) if is_primary else _btn_secondary(c)
            )
            btn.setCursor(Qt.PointingHandCursor)
            lay.addWidget(btn)
        return w

    def label(self, text: str, size: int = 12, color: str = None) -> QLabel:
        c = self._c
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color or c['text']}; font-size: {size}px;")
        return lbl

    def divider(self) -> QFrame:
        return _divider(self._c)

    def section(self, text: str) -> QLabel:
        return _section_label(text, self._c)
