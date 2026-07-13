"""
Переиспользуемые виджеты и хелперы панели превью.

Здесь живут самодостаточные строительные блоки, не зависящие от состояния
``PreviewPanel``:

* ``_load_pixmap`` / ``_vtf_to_temp_png`` — загрузка изображений и VTF→PNG;
* ``_HWheelScrollArea`` — горизонтальная прокрутка колесом мыши;
* ``_ExtraSlotCard`` — карточка одного текстурного слота (drag-drop + Browse);
* ``_SpyMaskVtfWorker`` — фоновое извлечение VTF масок шпиона в PNG.
"""

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QFileDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.shared.file_utils import get_temp_file_path
from src.shared.logging_config import get_logger
from src.ui.preview_icons import _make_gear_icon

logger = get_logger(__name__)


def _load_pixmap(path: str, opaque: bool = False) -> QPixmap:
    """
    Загружает QPixmap из файла.

    opaque=True — отбрасывает альфа-канал (RGB888): у игровых VTF альфа это
    маска бликов ($phong/$envmapmask), а не прозрачность, поэтому в 2D-превью
    её нужно игнорировать, иначе текстура выглядит полупрозрачной.
    """
    if opaque:
        img = QImage(path)
        if not img.isNull():
            return QPixmap.fromImage(img.convertToFormat(QImage.Format_RGB888))
    return QPixmap(path)


def _vtf_to_temp_png(vtf_path: str) -> Optional[str]:
    """
    Рендерит VTF (первый кадр) во временный PNG — для превью в карточке.
    Возвращает путь к PNG или None при ошибке чтения.
    """
    try:
        from src.services.vtflib_wrapper import VTFLib
        from PIL import Image
        rgba, w, h = VTFLib.read_vtf_as_rgba(vtf_path)
        png = str(get_temp_file_path(prefix='tf2_vtf_', suffix='.png'))
        Image.frombytes("RGBA", (w, h), rgba).save(png)
        return png
    except Exception as exc:
        logger.warning(f"VTF→PNG для карточки не удался ({vtf_path}): {exc}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# QScrollArea с горизонтальной прокруткой колесом мыши
# ═══════════════════════════════════════════════════════════════════════════════

class _HWheelScrollArea(QScrollArea):
    """
    QScrollArea, где колесо мыши прокручивает контент горизонтально.

    Используется для полосы карточек текстур: вертикального скролла там нет,
    поэтому любой поворот колеса перенаправляется на горизонтальный скроллбар.
    """

    def wheelEvent(self, event) -> None:
        h_bar = self.horizontalScrollBar()
        # angleDelta().y() — стандартный вертикальный поворот колеса (шаг = 120)
        # Умножаем на коэффициент чтобы один «клик» давал ~60px прокрутки
        delta = event.angleDelta().y()
        if delta != 0:
            h_bar.setValue(h_bar.value() - delta // 2)
            event.accept()
        else:
            super().wheelEvent(event)


# ═══════════════════════════════════════════════════════════════════════════════
# Карточка одного текстурного слота (2D, drag-drop)
# ═══════════════════════════════════════════════════════════════════════════════

class _ExtraSlotCard(QWidget):
    """Карточка одного текстурного слота — drag-drop + Browse + AI + превью."""

    image_changed = Signal(str, str)   # (material_name, image_path)
    settings_requested = Signal(str)   # (material_name) — открыть пер-текстурные настройки

    _STYLE_IDLE = "border: 1px solid #333; border-radius: 4px; background: #1a1a1a;"
    _STYLE_HOT  = "border: 1px solid #555; border-radius: 4px; background: #222;"
    _STYLE_CUSTOM = "border: 2px solid #d8b020; border-radius: 4px; background: #1a1a1a;"

    CARD_H = 500

    def __init__(self, material_name: str, display_name: str = '', parent=None):
        super().__init__(parent)
        self.material_name = material_name
        self._image_path: Optional[str] = None
        self._pix_source: Optional[QPixmap] = None
        self._custom = False   # есть ли пер-текстурный оверрайд настроек

        self.setFixedWidth(380)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        self._lbl = QLabel()
        self._lbl.setFixedSize(372, 448)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet(self._STYLE_IDLE)
        lay.addWidget(self._lbl)

        # ── Кнопка × — оверлей в правом верхнем углу изображения ──────────── #
        self._clear_btn = QPushButton("×", self._lbl)
        self._clear_btn.setFixedSize(22, 22)
        self._clear_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0,0,0,160);
                color: #aaa;
                border: 1px solid #555;
                border-radius: 3px;
                font-size: 15px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton:hover {
                background: rgba(180,40,40,210);
                color: #fff;
                border-color: #a00;
            }
        """)
        self._clear_btn.move(self._lbl.width() - 26, 4)
        self._clear_btn.hide()
        self._clear_btn.setCursor(Qt.ArrowCursor)
        self._clear_btn.clicked.connect(self._clear_image)

        # ── Кнопка-шестерёнка (пер-текстурные настройки) — левый верхний угол ── #
        from PySide6.QtCore import QSize
        self._gear_btn = QPushButton(self._lbl)
        self._gear_btn.setIcon(_make_gear_icon("#bbbbbb", 14))
        self._gear_btn.setIconSize(QSize(14, 14))
        self._gear_btn.setFixedSize(22, 22)
        self._gear_btn.setCursor(Qt.ArrowCursor)
        self._gear_btn.setToolTip(self.t.get('tex_settings_tip', 'Texture settings') if hasattr(self, 't') else 'Texture settings')
        self._gear_btn.setStyleSheet(
            "QPushButton { background: rgba(0,0,0,160); border:1px solid #555;"
            " border-radius:3px; padding:0; }"
            " QPushButton:hover { background: rgba(255,107,53,0.85); border-color:#ff6b35; }"
        )
        self._gear_btn.move(4, 4)
        self._gear_btn.clicked.connect(lambda: self.settings_requested.emit(self.material_name))

        # ── Бейдж оверрайда (левый нижний угол) ───────────────────────────── #
        self._badge = QLabel("", self._lbl)
        self._badge.setStyleSheet(
            "QLabel { background: rgba(216,176,32,0.18); color:#e3c24a;"
            " border:1px solid #8a7320; border-radius:4px; padding:1px 6px; font-size:10px; font-weight:bold; }"
        )
        self._badge.hide()

        self._name_lbl = QLabel(display_name or material_name)
        self._name_lbl.setStyleSheet("color:#888; font-size:11px;")
        self._name_lbl.setAlignment(Qt.AlignCenter)
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setFixedHeight(18)
        lay.addWidget(self._name_lbl)

        # Browse убран — клик по изображению (_lbl) уже открывает браузер.

        self._show_placeholder()

    # ── public ────────────────────────────────────────────────────────────────

    def set_image(self, path: str, opaque: bool = False) -> None:
        self._image_path = path or None
        if not path or not os.path.exists(path):
            self._pix_source = None
            self._show_placeholder()
            return

        # VTF рендерим в temp PNG для превью; _image_path остаётся исходным .vtf,
        # чтобы сборка взяла VTF как есть (без переконвертации). Альфа в VTF —
        # маска бликов, поэтому показываем непрозрачно (opaque).
        display_path = path
        if path.lower().endswith('.vtf'):
            png = _vtf_to_temp_png(path)
            if not png:
                self._pix_source = None
                self._show_placeholder()
                return
            display_path = png
            opaque = True

        pix = _load_pixmap(display_path, opaque)
        if pix.isNull():
            self._pix_source = None
            self._show_placeholder()
            return
        self._pix_source = pix
        self._lbl.setStyleSheet(self._border_style())
        self._refresh()
        self._clear_btn.show()
        self._clear_btn.raise_()
        self._gear_btn.raise_()
        if self._custom:
            self._badge.raise_()

    def get_image(self) -> Optional[str]:
        return self._image_path

    def set_display_name(self, name: str) -> None:
        """Меняет подпись карточки (имя материала) — напр. при переключении RED/BLU."""
        self._name_lbl.setText(name)

    def set_override_badge(self, text: str) -> None:
        """Показывает бейдж пер-текстурных настроек (напр. '1024 · DXT5') и
        акцентную рамку. Пустой текст — убрать (вернуться к обычной рамке)."""
        self._custom = bool(text)
        if text:
            self._badge.setText(text)
            self._badge.adjustSize()
            self._badge.move(6, self._lbl.height() - self._badge.height() - 6)
            self._badge.show()
            self._badge.raise_()
        else:
            self._badge.hide()
        # Перерисовываем рамку с учётом нового статуса (если картинка загружена).
        if self._pix_source is not None:
            self._lbl.setStyleSheet(self._border_style())

    def _border_style(self) -> str:
        return self._STYLE_CUSTOM if self._custom else self._STYLE_IDLE

    def reset(self) -> None:
        self._image_path = None
        self._pix_source = None
        self._show_placeholder()

    # ── internals ─────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if not self._pix_source or self._pix_source.isNull():
            return
        w, h = self._lbl.width(), self._lbl.height()
        if w > 0 and h > 0:
            self._lbl.setPixmap(
                self._pix_source.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._lbl.setMaximumSize(w, h)

    def _show_placeholder(self) -> None:
        self._lbl.clear()
        self._lbl.setText("Drop texture here\nor click Browse")
        self._lbl.setStyleSheet("color:#444; font-size:10px; " + self._STYLE_IDLE)
        if hasattr(self, '_clear_btn'):
            self._clear_btn.hide()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select texture for {self.material_name}",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp);;VTF Files (*.vtf);;All Files (*)",
        )
        if path:
            self.set_image(path)
            self.image_changed.emit(self.material_name, path)

    def _clear_image(self) -> None:
        """Пользователь нажал ×  — сбрасываем текстуру и сигнализируем."""
        self.reset()
        self.image_changed.emit(self.material_name, '')


    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            fp = event.mimeData().urls()[0].toLocalFile()
            if any(fp.lower().endswith(e) for e in
                   ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp', '.vtf')):
                self._lbl.setStyleSheet(self._STYLE_HOT)
                event.accept()
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        if self._image_path:
            self._lbl.setStyleSheet(self._STYLE_IDLE)
        else:
            self._show_placeholder()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            fp = urls[0].toLocalFile()
            if os.path.exists(fp):
                self.set_image(fp)
                self.image_changed.emit(self.material_name, fp)
                event.accept()
                return
        event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Открываем браузер только если клик попал в область изображения (_lbl),
            # а не в дочерние виджеты ниже (AI кнопку, панель промпта и т.п.)
            if self._lbl.geometry().contains(event.position().toPoint()):
                self._browse()
        super().mousePressEvent(event)


# ═══════════════════════════════════════════════════════════════════════════════
# Фоновое извлечение VTF масок шпиона → PNG
# ═══════════════════════════════════════════════════════════════════════════════

class _SpyMaskVtfWorker(QThread):
    """
    Извлекает игровые VTF масок шпиона → PNG в фоне. Один источник и для 3D-превью
    (переключатель маски), и для 2D-карточек (массовая загрузка превью).
    Эмитит (vtf_name, png_path) на каждую успешно извлечённую маску.
    """
    one = Signal(str, str)  # (vtf_name, png_path)

    def __init__(self, vtf_names, vpk_paths, out_dir, parent=None):
        super().__init__(parent)
        self._names = list(vtf_names)
        self._vpks = list(vpk_paths)
        self._dir = out_dir

    def run(self):
        from src.services import vtf_preview_service as vps
        os.makedirs(self._dir, exist_ok=True)
        paks = vps.open_vpks(self._vpks)
        for vtf in self._names:
            data = vps.read_from_vpks(paks, f"materials/models/player/spy/{vtf}.vtf")
            png = vps.vtf_bytes_to_png(
                data, os.path.join(self._dir, f"{vtf}.png"), self._dir)
            if png:
                self.one.emit(vtf, png)
