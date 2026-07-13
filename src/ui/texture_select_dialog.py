"""
Диалог выбора текстур персонажа для экспорта.

Сканирует VPK в фоне, показывает ВСЕ найденные .vtf файлы с чекбоксами
и инлайн-миниатюрами (при наведении — полноразмерное превью).
Стиль полностью совпадает с остальными диалогами приложения.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

from src.data.player_characters import (
    PLAYER_CHARACTERS,
    get_player_body_extra_label,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


# ── Тема ─────────────────────────────────────────────────────────────────── #

def _load_accent() -> str:
    """Возвращает цвет акцента текущей темы приложения."""
    from src.utils.themes import get_accent_color
    return get_accent_color()


# ── Фоновый поток: сканирование + загрузка превью ───────────────────────── #

class _TextureLoader(QThread):
    """Сканирует папку персонажа в VPK, затем декодирует VTF-превью."""

    scan_complete = Signal(list)        # List[Tuple[str, str]]
    loaded        = Signal(str, object) # (vtf_name, QPixmap | None)

    def __init__(self, vpk_path: str, folder: str) -> None:
        super().__init__()
        self._vpk_path = vpk_path
        self._folder   = folder

    def run(self) -> None:
        # Один pak на весь прогон (скан + превью): vpk.open парсит весь индекс
        # архива, открывать его дважды незачем. Хэндл берём из общего
        # потоко-локального кэша — закрывать нельзя, им владеет кэш
        # (освобождается вместе с потоком).
        try:
            from src.services.vpk_cache import open_vpk_cached
            pak = open_vpk_cached(self._vpk_path)
        except Exception as exc:
            logger.warning(f"[TextureLoader] Не удалось открыть VPK: {exc}")
            pak = None
        if pak is None:
            self.scan_complete.emit([])
            return

        textures = self._scan_folder(pak)
        self.scan_complete.emit(textures)

        for folder, vtf_name in textures:
            if self.isInterruptionRequested():
                break
            px = self._load_one(pak, folder, vtf_name)
            self.loaded.emit(vtf_name, px)

    def _scan_folder(self, pak) -> List[Tuple[str, str]]:
        try:
            prefix = f"materials/models/player/{self._folder}/"
            out: List[Tuple[str, str]] = []
            for path in pak:
                if path.startswith(prefix) and path.lower().endswith(".vtf"):
                    rem = path[len(prefix):]
                    if "/" not in rem:
                        out.append((self._folder, rem[:-4]))
            out.sort(key=lambda x: x[1])
            logger.info(
                f"[TextureLoader] Найдено {len(out)} текстур "
                f"в player/{self._folder}/"
            )
            return out
        except Exception as exc:
            logger.warning(f"[TextureLoader] Ошибка сканирования: {exc}")
            return []

    def _load_one(self, pak, folder: str, vtf_name: str) -> Optional[QPixmap]:
        path = f"materials/models/player/{folder}/{vtf_name}.vtf"
        try:
            vtf_data = pak[path].read()
        except KeyError:
            return None
        try:
            from src.services.vtflib_wrapper import VTFLib
            import os, tempfile
            with tempfile.NamedTemporaryFile(suffix=".vtf", delete=False) as f:
                f.write(vtf_data)
                tmp = f.name
            try:
                frames, w, h = VTFLib.read_vtf_all_frames(tmp)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            if not frames:
                return None
            img = QImage(frames[0], w, h, QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(img)
        except Exception as exc:
            logger.debug(f"[TextureLoader] Ошибка декодирования {vtf_name}: {exc}")
            return None


# ── Всплывающее превью ───────────────────────────────────────────────────── #

class _PreviewPopup(QFrame):
    """Безрамочный попап с полноразмерным превью текстуры."""

    _SIZE = 240

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self._SIZE + 16, self._SIZE + 40)
        self.setStyleSheet("""
            QFrame {
                background: #0f0f0f;
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(self._SIZE, self._SIZE)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet(
            "border: 1px solid #222; background: #141414; border-radius: 3px;"
        )
        lay.addWidget(self._img_lbl)

        self._name_lbl = QLabel()
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setStyleSheet(
            "border: none; background: transparent; "
            "color: #555; font-size: 10px; font-family: 'Inter','Segoe UI',Arial;"
        )
        lay.addWidget(self._name_lbl)

    def show_at(self, global_pos: QPoint, pixmap: Optional[QPixmap],
                name: str = "") -> None:
        if pixmap:
            scaled = pixmap.scaled(
                self._SIZE, self._SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setText("")
        else:
            self._img_lbl.clear()
            self._img_lbl.setText("—")

        self._name_lbl.setText(name + ".vtf" if name else "")
        self.move(global_pos.x() + 12, global_pos.y() - self._SIZE // 2)
        self.show()
        self.raise_()


# ── Миниатюра-кнопка превью ──────────────────────────────────────────────── #

class _Thumbnail(QLabel):
    """
    40×40 виджет для предпросмотра текстуры прямо в строке.

    Состояния:
      - «·» серый   → ещё грузится
      - мини-пиксмап → текстура загружена, при наведении открывается попап
      - «—» тёмный   → файл не найден в VPK
    """

    def __init__(self, vtf_name: str, popup: _PreviewPopup,
                 parent: QWidget = None) -> None:
        super().__init__(parent)
        self._vtf_name = vtf_name
        self._popup    = popup
        self._px_full: Optional[QPixmap] = None
        self._loaded   = False

        self.setFixedSize(40, 40)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_state_loading()

    # ── Публичный API ─────────────────────────────────────────────────────── #

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._px_full = pixmap
        self._loaded  = True
        if pixmap:
            thumb = pixmap.scaled(
                36, 36,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(thumb)
            self.setText("")
            self.setToolTip("Наведите для просмотра")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setStyleSheet(
                "QLabel { background: #141414; border: 1px solid #2a2a2a;"
                " border-radius: 3px; }"
                "QLabel:hover { border-color: #ff6b35; }"
            )
        else:
            self._set_state_missing()

    # ── Состояния ─────────────────────────────────────────────────────────── #

    def _set_state_loading(self) -> None:
        self.setText("·")
        self.setToolTip("")
        self.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.03); border: 1px solid #1e1e1e;"
            " border-radius: 3px; color: #333; font-size: 18px; }"
        )

    def _set_state_missing(self) -> None:
        self.setText("—")
        self.setToolTip(self._vtf_name + ".vtf — файл не найден")
        self.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.02); border: 1px solid #1a1a1a;"
            " border-radius: 3px; color: #2a2a2a; font-size: 16px; }"
        )

    # ── События ───────────────────────────────────────────────────────────── #

    def enterEvent(self, _event) -> None:
        if self._loaded and self._px_full:
            pos = self.mapToGlobal(QPoint(self.width(), 0))
            self._popup.show_at(pos, self._px_full, self._vtf_name)

    def leaveEvent(self, _event) -> None:
        self._popup.hide()


# ── Строка списка ─────────────────────────────────────────────────────────── #

class _TextureRow(QWidget):
    """Одна строка: [чекбокс + метка] + [миниатюра]"""

    _STYLE_NORMAL = (
        "QWidget#row { background: transparent; border-bottom: 1px solid #141414; }"
    )
    _STYLE_HOVER = (
        "QWidget#row { background: rgba(255,255,255,0.025); border-bottom: 1px solid #141414; }"
    )

    def __init__(
        self,
        vtf_name: str,
        label: str,
        is_primary: bool,
        popup: _PreviewPopup,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("row")
        self.vtf_name   = vtf_name
        self._popup     = popup
        self._thumbnail = _Thumbnail(vtf_name, popup, self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 8, 6)
        lay.setSpacing(12)

        # Чекбокс с меткой
        self.checkbox = QCheckBox(label)
        self.checkbox.setChecked(True)
        self.checkbox.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        # Основная текстура — чуть ярче
        text_color = "#ffffff" if is_primary else "#aaaaaa"
        weight     = "500"     if is_primary else "400"
        self.checkbox.setStyleSheet(
            f"QCheckBox {{ color: {text_color}; font-size: 13px;"
            f" font-weight: {weight};"
            f" font-family: 'Inter','Segoe UI',Arial; }}"
        )
        lay.addWidget(self.checkbox)

        lay.addWidget(self._thumbnail)

        self.setStyleSheet(self._STYLE_NORMAL)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._thumbnail.set_pixmap(pixmap)

    def enterEvent(self, _event) -> None:
        self.setStyleSheet(self._STYLE_HOVER)

    def leaveEvent(self, _event) -> None:
        self.setStyleSheet(self._STYLE_NORMAL)


# ── Локализация ───────────────────────────────────────────────────────────── #

_I18N = {
    "ru": {
        "title":       "ЭКСПОРТ ТЕКСТУР",
        "subtitle":    "Выберите текстуры для экспорта",
        "select_all":  "Выбрать все",
        "deselect":    "Снять все",
        "export_btn":  "Экспортировать ({n})",
        "cancel":      "Отмена",
        "primary":     "Тело (RED)",
        "scanning":    "Сканирование VPK…",
        "no_textures": "Текстуры не найдены",
        "found":       "{n} текстур найдено",
    },
    "en": {
        "title":       "EXPORT TEXTURES",
        "subtitle":    "Select textures to export",
        "select_all":  "Select all",
        "deselect":    "Deselect all",
        "export_btn":  "Export ({n})",
        "cancel":      "Cancel",
        "primary":     "Body (RED)",
        "scanning":    "Scanning VPK…",
        "no_textures": "No textures found",
        "found":       "{n} textures found",
    },
}


# ── Главный диалог ────────────────────────────────────────────────────────── #

class TextureSelectDialog(QDialog):
    """
    Диалог выбора текстур персонажа для экспорта.

    Сканирует VPK и отображает ВСЕ найденные .vtf-файлы.
    Превью подгружаются асинхронно; при наведении на миниатюру
    открывается полноразмерный попап.

    Использование::

        dlg = TextureSelectDialog(mode, textures_vpk_path, language, parent)
        if dlg.exec() == QDialog.Accepted:
            selected = dlg.get_selected_textures()  # [(folder, vtf_name), ...]
    """

    def __init__(
        self,
        mode: str,
        textures_vpk_path: str,
        language: str = "en",
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._mode   = mode
        self._lang   = language if language in _I18N else "en"
        self._t      = _I18N[self._lang]
        self._accent = _load_accent()
        self._folder = PLAYER_CHARACTERS.get(mode, {}).get("folder", "")

        cfg_textures     = PLAYER_CHARACTERS.get(mode, {}).get("textures", [])
        self._primary_vtf = cfg_textures[0][1] if cfg_textures else ""

        char_name = PLAYER_CHARACTERS.get(mode, {}).get(self._lang, mode)

        self._all_textures: List[Tuple[str, str]] = []
        self._rows: Dict[str, _TextureRow] = {}

        self.setWindowTitle("TF2 Skin Generator")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(460)
        self.setMinimumHeight(420)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: #0a0a0a;
                border: 1px solid #1e1e1e;
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #2a2a2a;
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self._accent};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self._popup = _PreviewPopup(self)
        self._popup.hide()

        self._char_name = char_name
        self._setup_ui()
        self._start_loader(textures_vpk_path)

    # ── UI ────────────────────────────────────────────────────────────────── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Шапка ─────────────────────────────────────────────────────────── #
        header = QWidget()
        header.setStyleSheet("background: #0f0f0f; border-bottom: 1px solid #1e1e1e;")
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(24, 20, 24, 16)
        h_lay.setSpacing(4)

        title_lbl = QLabel(self._t["title"])
        title_lbl.setStyleSheet(
            f"color: {self._accent}; font-size: 11px; font-weight: 700;"
            " letter-spacing: 3px; font-family: 'Inter','Segoe UI',Arial;"
            " background: transparent; border: none;"
        )
        h_lay.addWidget(title_lbl)

        sub_lbl = QLabel(f"{self._char_name}  ·  {self._t['subtitle']}")
        sub_lbl.setStyleSheet(
            "color: #555; font-size: 12px; font-weight: 400;"
            " font-family: 'Inter','Segoe UI',Arial;"
            " background: transparent; border: none;"
        )
        h_lay.addWidget(sub_lbl)

        self._count_lbl = QLabel(self._t["scanning"])
        self._count_lbl.setStyleSheet(
            "color: #333; font-size: 11px; font-weight: 400;"
            " font-family: 'Inter','Segoe UI',Arial;"
            " background: transparent; border: none;"
        )
        h_lay.addWidget(self._count_lbl)

        root.addWidget(header)

        # ── Список ────────────────────────────────────────────────────────── #
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setSpacing(0)
        self._list_layout.setContentsMargins(0, 0, 0, 0)

        # Заглушка «Сканирование…»
        self._scanning_placeholder = QLabel(self._t["scanning"])
        self._scanning_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scanning_placeholder.setMinimumHeight(120)
        self._scanning_placeholder.setStyleSheet(
            "color: #333; font-size: 12px; font-style: italic;"
            " font-family: 'Inter','Segoe UI',Arial; background: transparent;"
        )
        self._list_layout.addWidget(self._scanning_placeholder)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        # ── Разделитель ───────────────────────────────────────────────────── #
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #1a1a1a; border: none; max-height: 1px;")
        root.addWidget(sep)

        # ── Подвал ────────────────────────────────────────────────────────── #
        footer = QWidget()
        footer.setStyleSheet("background: #0a0a0a; border: none;")
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(16, 12, 16, 16)
        f_lay.setSpacing(8)

        btn_all = QPushButton(self._t["select_all"])
        btn_all.setStyleSheet(self._secondary_style())
        btn_all.setMinimumHeight(34)
        btn_all.clicked.connect(lambda: self._set_all(True))

        btn_none = QPushButton(self._t["deselect"])
        btn_none.setStyleSheet(self._secondary_style())
        btn_none.setMinimumHeight(34)
        btn_none.clicked.connect(lambda: self._set_all(False))

        f_lay.addWidget(btn_all)
        f_lay.addWidget(btn_none)
        f_lay.addStretch()

        cancel_btn = QPushButton(self._t["cancel"])
        cancel_btn.setStyleSheet(self._secondary_style())
        cancel_btn.setMinimumHeight(34)
        cancel_btn.clicked.connect(self.reject)

        self._export_btn = QPushButton(self._t["export_btn"].format(n=0))
        self._export_btn.setEnabled(False)
        self._export_btn.setDefault(True)
        self._export_btn.setMinimumHeight(34)
        self._export_btn.setMinimumWidth(160)
        self._export_btn.setStyleSheet(self._primary_style())
        self._export_btn.clicked.connect(self.accept)

        f_lay.addWidget(cancel_btn)
        f_lay.addWidget(self._export_btn)

        root.addWidget(footer)

    def _primary_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {self._accent};
                color: #0a0a0a;
                border: none;
                padding: 0 20px;
                font-size: 13px;
                font-weight: 600;
                border-radius: 4px;
                font-family: 'Inter','Segoe UI',Arial;
            }}
            QPushButton:hover {{ background-color: {self._accent}cc; }}
            QPushButton:pressed {{ background-color: {self._accent}99; }}
            QPushButton:disabled {{
                background-color: #1e1e1e;
                color: #333;
            }}
        """

    def _secondary_style(self) -> str:
        return """
            QPushButton {
                background-color: transparent;
                color: #888;
                border: 1px solid #2a2a2a;
                padding: 0 16px;
                font-size: 13px;
                font-weight: 400;
                border-radius: 4px;
                font-family: 'Inter','Segoe UI',Arial;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.04);
                border-color: #444;
                color: #ccc;
            }
            QPushButton:pressed {
                background-color: rgba(255,255,255,0.07);
            }
        """

    # ── Загрузка ──────────────────────────────────────────────────────────── #

    def _start_loader(self, vpk_path: str) -> None:
        self._loader = _TextureLoader(vpk_path, self._folder)
        self._loader.scan_complete.connect(self._on_scan_complete)
        self._loader.loaded.connect(self._on_texture_loaded)
        self._loader.start()

    def _on_scan_complete(self, textures: List[Tuple[str, str]]) -> None:
        # Убираем заглушку
        if self._scanning_placeholder is not None:
            self._scanning_placeholder.setParent(None)
            self._scanning_placeholder = None
        # Убираем stretch
        last = self._list_layout.takeAt(self._list_layout.count() - 1)
        if last:
            del last

        if not textures:
            lbl = QLabel(self._t["no_textures"])
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumHeight(80)
            lbl.setStyleSheet(
                "color: #444; font-size: 12px; font-style: italic;"
                " font-family: 'Inter','Segoe UI',Arial; background: transparent;"
            )
            self._list_layout.addWidget(lbl)
            self._list_layout.addStretch()
            self._count_lbl.setText(self._t["no_textures"])
            return

        # Основная текстура первой, остальные — по алфавиту
        primary = [(f, v) for f, v in textures if v == self._primary_vtf]
        rest    = [(f, v) for f, v in textures if v != self._primary_vtf]
        self._all_textures = primary + rest

        for idx, (folder, vtf_name) in enumerate(self._all_textures):
            is_primary = (idx == 0)
            label = self._make_label(idx, vtf_name)
            row   = _TextureRow(vtf_name, label, is_primary, self._popup, self._container)
            row.checkbox.stateChanged.connect(self._update_export_btn)
            self._rows[vtf_name] = row
            self._list_layout.addWidget(row)

        self._list_layout.addStretch()

        n = len(self._all_textures)
        self._count_lbl.setText(self._t["found"].format(n=n))
        self._update_export_btn()

    def _make_label(self, idx: int, vtf_name: str) -> str:
        if idx == 0:
            return self._t["primary"]
        label = get_player_body_extra_label(self._mode, vtf_name, self._lang)
        return label  # если не в конфиге — возвращается vtf_name

    def _on_texture_loaded(self, vtf_name: str, pixmap) -> None:
        row = self._rows.get(vtf_name)
        if row:
            row.set_pixmap(pixmap)

    # ── Логика ───────────────────────────────────────────────────────────── #

    def _set_all(self, checked: bool) -> None:
        for row in self._rows.values():
            row.checkbox.setChecked(checked)

    def _update_export_btn(self) -> None:
        n = sum(1 for r in self._rows.values() if r.checkbox.isChecked())
        self._export_btn.setText(self._t["export_btn"].format(n=n))
        self._export_btn.setEnabled(n > 0)

    # ── Публичный API ────────────────────────────────────────────────────── #

    def get_selected_textures(self) -> List[Tuple[str, str]]:
        """Возвращает [(folder, vtf_name)] только для выбранных текстур."""
        selected = {
            vtf_name
            for vtf_name, row in self._rows.items()
            if row.checkbox.isChecked()
        }
        return [(f, v) for f, v in self._all_textures if v in selected]

    def closeEvent(self, event) -> None:
        self._popup.hide()
        if hasattr(self, "_loader") and self._loader.isRunning():
            self._loader.requestInterruption()
            self._loader.wait(1000)
        super().closeEvent(event)
