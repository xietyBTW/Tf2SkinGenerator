"""
Диалог импорта дополнительных текстур при сборке VPK.

Каждая текстура — карточка с двумя превью:
  ОРИГИНАЛ (из игры, placeholder)  →  НОВАЯ ТЕКСТУРА (drag-and-drop / browse)

Полностью переопределяет глобальные стили приложения внутри диалога.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QFileDialog,
)

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_IMG_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.gif', '.vtf'}

# ── Helpers ───────────────────────────────────────────────────────────────── #

def _load_config() -> dict:
    try:
        from src.config.app_config import AppConfig
        return AppConfig.load_config()
    except Exception:
        return {}


def _accent() -> str:
    cfg = _load_config()
    return "#4a90e2" if cfg.get("theme") == "blue" else "#ff6b35"


def _bg() -> str:
    cfg = _load_config()
    return "#0d1b2a" if cfg.get("theme") == "blue" else "#0a0a0a"


# ── Всплывающее превью (large hover popup) ─────────────────────────────────── #

class _PreviewPopup(QFrame):
    _SZ = 260

    def __init__(self, parent: QWidget) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self._SZ + 16, self._SZ + 16)
        self.setStyleSheet(
            "QFrame { background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 6px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        self._img = QLabel()
        self._img.setFixedSize(self._SZ, self._SZ)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setStyleSheet(
            "QLabel { background: #141414; border: 1px solid #222; border-radius: 3px; }"
        )
        lay.addWidget(self._img)

    def show_at(self, gpos: QPoint, pixmap: QPixmap) -> None:
        self._img.setPixmap(
            pixmap.scaled(self._SZ, self._SZ,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        )
        self.move(gpos.x() + 18, gpos.y() - self._SZ // 2)
        self.show()
        self.raise_()


# ── Левый блок: ОРИГИНАЛ (placeholder) ────────────────────────────────────── #

class _OriginalBox(QLabel):
    """Показывает заглушку «оригинальная текстура из игры»."""

    W, H = 100, 90

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setText("ОРИГИНАЛ\nИЗ ИГРЫ")
        self.setStyleSheet("""
            QLabel {
                background: #111111;
                border: 1px solid #1e1e1e;
                border-radius: 4px;
                color: #2a2a2a;
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }
        """)


# ── Правый блок: зона сброса новой текстуры ───────────────────────────────── #

class _DropZone(QLabel):
    """
    100×90 виджет для импорта новой текстуры.
    Пустой  — иконка «+», dashed border.
    Заполненный — миниатюра, по наведению — popup.
    ЛКМ — проводник, ПКМ — очистить.
    """

    W, H = 100, 90

    def __init__(self, name: str, display_name: str, accent: str,
                 popup: _PreviewPopup, parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self._display_name = display_name
        self._accent = accent
        self._popup = popup
        self._path: Optional[str] = None
        self._px_full: Optional[QPixmap] = None

        self.setFixedSize(self.W, self.H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_empty()

    # ── Public ───────────────────────────────────────────────────────────── #

    def set_path(self, path: str) -> None:
        self._path = path
        ext = os.path.splitext(path)[1].lower()
        if ext != ".vtf":
            px = QPixmap(path)
            if not px.isNull():
                self._px_full = px
                self.setPixmap(
                    px.scaled(self.W - 8, self.H - 8,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )
                self.setText("")
                self._apply_filled()
                return
        # VTF или не удалось открыть — текстовая заглушка
        self._px_full = None
        self.setPixmap(QPixmap())
        self.setText(os.path.splitext(os.path.basename(path))[0][:9])
        self.setStyleSheet("""
            QLabel {
                background: #131f13;
                border: 1px solid #2a4a2a;
                border-radius: 4px;
                color: #4a8a4a;
                font-size: 9px;
                font-weight: 600;
            }
        """)

    def clear_slot(self) -> None:
        self._path = None
        self._px_full = None
        self._apply_empty()

    def get_path(self) -> Optional[str]:
        return self._path

    # ── Private ──────────────────────────────────────────────────────────── #

    def _apply_empty(self) -> None:
        self.setPixmap(QPixmap())
        self.setText("+")
        self.setStyleSheet(f"""
            QLabel {{
                background: rgba(255,255,255,0.02);
                border: 2px dashed #252525;
                border-radius: 4px;
                color: #252525;
                font-size: 30px;
                font-weight: 100;
            }}
            QLabel:hover {{
                border-color: {self._accent};
                color: {self._accent};
                background: rgba(255,107,53,0.05);
            }}
        """)

    def _apply_filled(self) -> None:
        self.setStyleSheet(f"""
            QLabel {{
                background: #141414;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
            }}
            QLabel:hover {{
                border-color: {self._accent};
            }}
        """)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.window(),
            f'Выберите изображение — {self._display_name}',
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga *.gif *.vtf);;All Files (*)",
        )
        if path:
            self.set_path(path)

    # ── Events ───────────────────────────────────────────────────────────── #

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._browse()
        elif event.button() == Qt.MouseButton.RightButton and self._path:
            self.clear_slot()

    def enterEvent(self, _) -> None:
        if self._path and self._px_full:
            pos = self.mapToGlobal(QPoint(self.W, self.H // 2))
            self._popup.show_at(pos, self._px_full)

    def leaveEvent(self, _) -> None:
        self._popup.hide()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            ext = os.path.splitext(event.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in _IMG_EXTS:
                event.acceptProposedAction()
                self.setStyleSheet(f"""
                    QLabel {{
                        background: rgba(255,107,53,0.08);
                        border: 2px dashed {self._accent};
                        border-radius: 4px;
                        color: {self._accent};
                        font-size: 30px;
                    }}
                """)
                return
        event.ignore()

    def dragLeaveEvent(self, _) -> None:
        if self._path:
            self._apply_filled()
        else:
            self._apply_empty()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.splitext(path)[1].lower() in _IMG_EXTS:
                self.set_path(path)
                event.acceptProposedAction()
                return
        self._apply_empty() if not self._path else self._apply_filled()
        event.ignore()


# ── Карточка одной текстуры ───────────────────────────────────────────────── #

class _TextureCard(QWidget):
    """
    Карточка для одной текстуры:
      ┌─────────────────────────────────────────────┐
      │ Название текстуры              [BLU / ОБЩАЯ]│
      │                                             │
      │  [ОРИГИНАЛ]   →→→   [ + БРОСИТЬ / ОТКРЫТЬ] │
      │                         [ × Очистить ]      │
      └─────────────────────────────────────────────┘
    """

    def __init__(self, name: str, display_name: str, tex_type: str,
                 popup: _PreviewPopup, accent: str, bg: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self._accent = accent

        # Цвет карточки
        card_bg = "#0f0f0f" if bg == "#0a0a0a" else "#111820"
        hover_bg = "#121212" if bg == "#0a0a0a" else "#141e2a"

        self.setStyleSheet(f"""
            _TextureCard, QWidget#card {{
                background: {card_bg};
                border: 1px solid #1a1a1a;
                border-radius: 6px;
            }}
        """)

        # Контейнер с отступами
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet(f"""
            QWidget#card {{
                background: {card_bg};
                border: 1px solid #1a1a1a;
                border-radius: 6px;
            }}
            QWidget#card:hover {{
                border-color: #2a2a2a;
                background: {hover_bg};
            }}
        """)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # ── Строка: название + бейдж ─────────────────────────────────────── #
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        name_lbl = QLabel(display_name)
        name_lbl.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 12px;
                font-weight: 500;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
                background: transparent;
                border: none;
                padding: 0;
            }
        """)
        name_lbl.setToolTip(name)
        top_row.addWidget(name_lbl)

        top_row.addStretch()

        # Бейдж
        if tex_type == "blu":
            badge_txt, badge_fg, badge_bg = "BLU", "#5599cc", "rgba(85,153,204,0.12)"
        elif tex_type == "shared":
            badge_txt, badge_fg, badge_bg = "ОБЩАЯ", "#9977bb", "rgba(153,119,187,0.12)"
        else:
            badge_txt = badge_fg = badge_bg = ""

        if badge_txt:
            badge = QLabel(badge_txt)
            badge.setStyleSheet(f"""
                QLabel {{
                    color: {badge_fg};
                    background: {badge_bg};
                    border: 1px solid {badge_fg};
                    border-radius: 3px;
                    font-size: 9px;
                    font-weight: 700;
                    letter-spacing: 1px;
                    padding: 2px 6px;
                    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
                }}
            """)
            top_row.addWidget(badge)

        lay.addLayout(top_row)

        # ── Разделитель ──────────────────────────────────────────────────── #
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #1a1a1a; border: none; max-height: 1px;")
        lay.addWidget(sep)

        # ── Строка: ОРИГИНАЛ → НОВАЯ + кнопки ───────────────────────────── #
        preview_row = QHBoxLayout()
        preview_row.setSpacing(0)
        preview_row.setContentsMargins(0, 0, 0, 0)

        # Левый блок: ОРИГИНАЛ
        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        left_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._orig_box = _OriginalBox()
        left_col.addWidget(self._orig_box, alignment=Qt.AlignmentFlag.AlignHCenter)

        orig_lbl = QLabel("ОРИГИНАЛ")
        orig_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        orig_lbl.setStyleSheet("""
            QLabel {
                color: #2a2a2a;
                font-size: 9px;
                font-weight: 600;
                letter-spacing: 1px;
                background: transparent;
                border: none;
                padding: 0;
            }
        """)
        left_col.addWidget(orig_lbl)
        preview_row.addLayout(left_col)

        # Стрелка
        arrow_lbl = QLabel("→")
        arrow_lbl.setFixedWidth(40)
        arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow_lbl.setStyleSheet(f"""
            QLabel {{
                color: #333333;
                font-size: 20px;
                font-weight: 100;
                background: transparent;
                border: none;
                padding: 0;
                margin-bottom: 18px;
            }}
        """)
        preview_row.addWidget(arrow_lbl)

        # Правый блок: зона дропа + кнопки
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        right_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.drop_zone = _DropZone(name, display_name, accent, popup)
        right_col.addWidget(self.drop_zone, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Кнопки под зоной дропа
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        open_btn = QPushButton("Открыть…")
        open_btn.setFixedHeight(24)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #555555;
                border: 1px solid #222222;
                border-radius: 3px;
                font-size: 11px;
                font-weight: 400;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
                padding: 0 8px;
                min-width: 0;
                text-transform: none;
                letter-spacing: 0;
            }}
            QPushButton:hover {{
                border-color: {accent};
                color: {accent};
                background: rgba(255,107,53,0.06);
            }}
            QPushButton:pressed {{
                background: rgba(255,107,53,0.12);
            }}
        """)
        open_btn.clicked.connect(self.drop_zone._browse)
        btn_row.addWidget(open_btn)

        clear_btn = QPushButton("×")
        clear_btn.setFixedSize(24, 24)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Очистить — оставить оригинал из игры")
        clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #333333;
                border: 1px solid #1e1e1e;
                border-radius: 3px;
                font-size: 14px;
                font-weight: 300;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
                padding: 0;
                min-width: 0;
                text-transform: none;
                letter-spacing: 0;
            }
            QPushButton:hover {
                color: #cc4444;
                border-color: #cc4444;
                background: rgba(204,68,68,0.08);
            }
        """)
        clear_btn.clicked.connect(self.drop_zone.clear_slot)
        btn_row.addWidget(clear_btn)

        right_col.addLayout(btn_row)
        preview_row.addLayout(right_col)

        preview_row.addStretch()
        lay.addLayout(preview_row)

    def get_path(self) -> Optional[str]:
        return self.drop_zone.get_path()


# ── Локализация ───────────────────────────────────────────────────────────── #

_I18N = {
    "ru": {
        "title":    "ИМПОРТ ТЕКСТУР",
        "subtitle": "Замените текстуры модели своими изображениями",
        "hint":     "Перетащите файл в правый блок, нажмите «+» или «Открыть…».\n"
                    "Пустой слот — игровая текстура остаётся без изменений.",
        "cancel":   "Отменить сборку",
        "build":    "Начать сборку",
        "n_textures": "{n} текстур",
    },
    "en": {
        "title":    "IMPORT TEXTURES",
        "subtitle": "Replace model textures with your own images",
        "hint":     "Drag a file onto the right block, click «+» or «Open…».\n"
                    "Empty slots keep the original game texture unchanged.",
        "cancel":   "Cancel build",
        "build":    "Start build",
        "n_textures": "{n} textures",
    },
}


# ── Главный диалог ────────────────────────────────────────────────────────── #

class ExtraTexturesDialog(QDialog):
    """
    Единое окно выбора всех дополнительных текстур перед сборкой VPK.

    Принимает:
        textures   — [{name, display_name, type}]
        weapon_key — ключ оружия (для заголовка)
        language   — язык ('ru' / 'en')

    Возвращает через get_results():
        {name: path_or_None}   None = оставить оригинал из игры

    reject() → main_window отменяет сборку через requestInterruption().
    """

    def __init__(
        self,
        textures: List[Dict],
        weapon_key: str = "",
        parent=None,
        language: str = "en",
    ) -> None:
        super().__init__(parent)
        self._textures   = textures
        self._weapon_key = weapon_key
        self._lang       = language if language in _I18N else "en"
        self._t          = _I18N[self._lang]
        self._accent     = _accent()
        self._bg         = _bg()
        self._cards: Dict[str, _TextureCard] = {}

        self.setWindowTitle("TF2 Skin Generator — Импорт текстур")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(480)
        self.setMinimumHeight(300)
        self.resize(520, min(80 + len(textures) * 158, 700))

        # ── Полный переопределяющий QSS для диалога ───────────────────────── #
        # (подавляет глобальные стили приложения внутри этого окна)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self._bg};
                border: 1px solid #1a1a1a;
            }}
            QWidget {{
                background-color: transparent;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #2a2a2a;
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self._accent};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
                border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

        self._popup = _PreviewPopup(self)
        self._popup.hide()

        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Шапка ─────────────────────────────────────────────────────────── #
        header_bg = "#0f0f0f" if self._bg == "#0a0a0a" else "#0a1220"
        header = QWidget()
        header.setObjectName("header")
        header.setStyleSheet(f"""
            QWidget#header {{
                background: {header_bg};
                border-bottom: 1px solid #1a1a1a;
            }}
        """)
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(24, 18, 24, 16)
        h_lay.setSpacing(5)

        title = QLabel(self._t["title"])
        title.setStyleSheet(f"""
            QLabel {{
                color: {self._accent};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 3px;
                background: transparent;
                border: none;
                padding: 0;
            }}
        """)
        h_lay.addWidget(title)

        wk = self._weapon_key if self._weapon_key not in ("", "custom") else ""
        subtitle_text = (f"{wk}  ·  " if wk else "") + self._t["subtitle"]
        subtitle = QLabel(subtitle_text)
        subtitle.setStyleSheet("""
            QLabel {
                color: #555555;
                font-size: 12px;
                font-weight: 400;
                background: transparent;
                border: none;
                padding: 0;
            }
        """)
        h_lay.addWidget(subtitle)

        hint = QLabel(self._t["hint"])
        hint.setStyleSheet("""
            QLabel {
                color: #2e2e2e;
                font-size: 11px;
                background: transparent;
                border: none;
                padding: 0;
                margin-top: 4px;
            }
        """)
        hint.setWordWrap(True)
        h_lay.addWidget(hint)

        root.addWidget(header)

        # ── Область прокрутки с карточками ───────────────────────────────── #
        container = QWidget()
        container.setStyleSheet(f"background: {self._bg};")
        c_lay = QVBoxLayout(container)
        c_lay.setSpacing(6)
        c_lay.setContentsMargins(12, 12, 12, 12)

        for tex in self._textures:
            name = tex["name"]
            disp = tex.get("display_name") or name
            card = _TextureCard(
                name, disp, tex.get("type", "extra"),
                self._popup, self._accent, self._bg,
                container,
            )
            self._cards[name] = card
            c_lay.addWidget(card)

        c_lay.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # ── Разделитель ───────────────────────────────────────────────────── #
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #1a1a1a; border: none; max-height: 1px;")
        root.addWidget(sep)

        # ── Подвал ────────────────────────────────────────────────────────── #
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setStyleSheet(f"QWidget#footer {{ background: {self._bg}; border: none; }}")
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(20, 12, 20, 16)
        f_lay.setSpacing(10)

        # Счётчик слотов
        count_lbl = QLabel(self._t["n_textures"].format(n=len(self._textures)))
        count_lbl.setStyleSheet("""
            QLabel {
                color: #333333;
                font-size: 11px;
                background: transparent;
                border: none;
                padding: 0;
            }
        """)
        f_lay.addWidget(count_lbl)
        f_lay.addStretch()

        # Кнопка «Отменить сборку»
        cancel_btn = QPushButton(self._t["cancel"])
        cancel_btn.setFixedHeight(36)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #777777;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                font-size: 13px;
                font-weight: 400;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
                padding: 0 16px;
                text-transform: none;
                letter-spacing: 0;
            }
            QPushButton:hover {
                background-color: rgba(204,68,68,0.10);
                border-color: #cc4444;
                color: #cc6666;
            }
            QPushButton:pressed {
                background-color: rgba(204,68,68,0.18);
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        f_lay.addWidget(cancel_btn)

        # Кнопка «Начать сборку»
        build_btn = QPushButton(f"  {self._t['build']}  →")
        build_btn.setDefault(True)
        build_btn.setFixedHeight(36)
        build_btn.setMinimumWidth(140)
        build_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        build_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._accent};
                color: #0a0a0a;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                font-weight: 700;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
                padding: 0 20px;
                text-transform: none;
                letter-spacing: 0;
            }}
            QPushButton:hover {{
                background-color: {self._accent}dd;
            }}
            QPushButton:pressed {{
                background-color: {self._accent}aa;
            }}
        """)
        build_btn.clicked.connect(self.accept)
        f_lay.addWidget(build_btn)

        root.addWidget(footer)

    # ── Результат ─────────────────────────────────────────────────────────── #

    def closeEvent(self, event) -> None:
        self._popup.hide()
        super().closeEvent(event)
