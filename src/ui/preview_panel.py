"""
Панель предварительного просмотра — 2D (изображение) и 3D (модель).

Логика работы
─────────────
1. Пользователь выбирает оружие/шапку
   → 2D: одно пустое поле загрузки
   → 3D: подсказка «нажмите ▶ для загрузки модели»

2. Пользователь нажимает ▶ (загрузка 3D)
   → 3D: модель извлекается из VPK и отображается
   → 2D: если модель многоматериальная → появляются карточки для каждого
          материала; одноматериальная → одно поле загрузки
   → Если QC содержит BLU текстуру → появляется переключатель RED/BLU

3. Переключение RED/BLU
   → Текстуры хранятся ОТДЕЛЬНО для каждой команды
   → Переключение команды восстанавливает её текстуры без сброса

4. Смена оружия/шапки
   → Полный сброс: карточки → одно поле, текстуры → пусто, команда → RED

5. Переключение между 2D и 3D
   → Текстуры и GIF-анимации НЕ сбрасываются
"""

import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from src.shared.file_utils import get_temp_file_path
from src.shared.logging_config import get_logger
from src.utils.themes import get_modern_styles

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


# Sentinel-ключ для главной текстуры когда у модели нет именованных материалов
# (одноматериальный случай). Используется только внутри панели для хранения в
# self._textures. НЕ является именем материала и НЕ должен попадать в сборку —
# главная текстура передаётся в билд отдельно через from_path.
SINGLE_TEX_KEY = '__single__'

# Фильтр служебных материалов (глаза/зубы/sheen-оверлеи) — общий для UI и сборки.
from src.data.material_filter import is_editable_material as _is_editable_material


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

    _STYLE_IDLE = "border: 1px solid #333; border-radius: 4px; background: #1a1a1a;"
    _STYLE_HOT  = "border: 1px solid #555; border-radius: 4px; background: #222;"

    CARD_H = 500

    def __init__(self, material_name: str, display_name: str = '', parent=None):
        super().__init__(parent)
        self.material_name = material_name
        self._image_path: Optional[str] = None
        self._pix_source: Optional[QPixmap] = None

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
        self._lbl.setStyleSheet(self._STYLE_IDLE)
        self._refresh()
        self._clear_btn.show()
        self._clear_btn.raise_()

    def get_image(self) -> Optional[str]:
        return self._image_path

    def set_display_name(self, name: str) -> None:
        """Меняет подпись карточки (имя материала) — напр. при переключении RED/BLU."""
        self._name_lbl.setText(name)

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
# Утилиты
# ═══════════════════════════════════════════════════════════════════════════════

def _team_priority(active_team: str) -> list:
    """Возвращает порядок проверки команд для поиска текстуры.

    Активная команда идёт первой — позволяет начать сборку с любой загруженной
    текстуры (RED или BLU), а не только с RED.
    """
    if active_team == 'blu':
        return ['blu', 'red']
    return ['red', 'blu']


# ═══════════════════════════════════════════════════════════════════════════════
# Основная панель
# ═══════════════════════════════════════════════════════════════════════════════

class PreviewPanel(QWidget):
    """2D + 3D панель предпросмотра с чистым управлением состоянием."""

    vpk_mod_loaded = Signal(str)   # путь к VPK моду

    # ── init ──────────────────────────────────────────────────────────────────

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.styles = get_modern_styles()

        # ── Идентификация текущего оружия ──────────────────────────────────── #
        # Используется для обнаружения смены оружия и предотвращения ложных сбросов.
        self._weapon_key: str = '\x00'   # sentinel — не совпадёт с реальным ключом
        self._weapon_mode: str = ''

        # ── Текстуры: {team: {mat_name: path}} ────────────────────────────── #
        self._textures: Dict[str, Dict[str, str]] = {'red': {}, 'blu': {}}
        self._active_team: str = 'red'

        # ── Слоты материалов ──────────────────────────────────────────────── #
        # Заполняется после загрузки 3D (через _on_3d_multi_material).
        # Для рук — заполняется сразу из HAND_MODES.
        # [0] = главный материал, [1:] = дополнительные.
        self._material_names: List[str] = []
        self._card_mode: bool = False
        self._has_blu: bool = False

        # ── Стили / skinfamilies (только для кастомной замены модели) ──────── #
        # Определяются из QC оригинальной модели через SkinDetectWorker.
        # _skin_overrides[skin_idx][mat_name] = путь к текстуре этого стиля.
        # Скин 0 — база; остальные наследуют скин 0, пока их не переопределят.
        self._original_skin_info: Optional[dict] = None
        self._active_skin: int = 0
        self._skin_overrides: Dict[int, Dict[str, str]] = {}
        # Материалы, которые пользователь ЯВНО добавил в вариантный стиль через
        # «+» (карточка показывается даже пустой). Скин 0 тут не участвует.
        self._skin_chosen: Dict[int, set] = {}
        self._skin_worker = None
        self._skin_buttons: List[QPushButton] = []

        # ── 2D состояние ──────────────────────────────────────────────────── #
        # image_path — путь к активному изображению (None если не загружено)
        self.image_path: Optional[str] = None
        self.vtf_path: Optional[str] = None
        self._gif_movie = None
        self._gif_orig_size = None

        # ── 3D состояние ──────────────────────────────────────────────────── #
        self._3d_widget = None
        self._3d_worker = None
        self._vpk_mod_worker = None
        self._3d_available: bool = False
        self._pending_3d_params: Optional[tuple] = None   # (key, mode, vpk, tex_vpk)
        self._last_3d_params: Optional[tuple] = None      # для обнаружения изменений

        # ── Мини-память последнего оружия (1 слот) ────────────────────────── #
        # _cur_obj — (mode, obj_path, texture_path) сейчас загруженной модели,
        #            заполняется в _on_3d_ready (None если модель не загружена).
        # _mem_mode/_mem_data — снимок ПРЕДЫДУЩЕГО загруженного оружия для
        #            мгновенного восстановления при возврате (без воркера).
        # _restoring_memory — флаг координации с update_extra_slots (чтобы он
        #            не затёр восстановленное состояние).
        self._cur_obj: Optional[tuple] = None
        self._mem_mode: Optional[str] = None
        self._mem_data: Optional[dict] = None
        self._restoring_memory: bool = False
        self._custom_smd_mode: bool = False
        self._custom_smd_path: Optional[str] = None   # путь загруженной кастомной модели
        # True — модель «готова»: сохранять её материалы как есть (многотекстурная).
        # False — заменить только геометрию (адаптировать под игровой материал).
        self._custom_keep_materials: bool = False
        self._crithit_mode: bool = False
        self._crithit_class: str = 'soldier'
        self._spy_mask_mode: bool = False      # режим масок маскировки шпиона
        self._active_spy_mask: Optional[str] = None  # активный класс (cls_key)
        self._australium_frame: Optional[str] = None  # PNG игрового варианта Australium/Gold
        self._australium_active: bool = False          # активен ли вариант в 3D
        self._australium_user_tex: Optional[str] = None  # своя текстура для Australium (отд. слот)
        self._australium_mat_name: Optional[str] = None   # имя gold-материала (для сборки)
        self._aus_card = None                          # карточка «Australium» в ряду типов текстур

        # ── Per-mesh drag tracking ─────────────────────────────────────────── #
        # True если пользователь перетащил текстуру на конкретный меш в 3D.
        # Сбрасывается при смене изображения или загрузке новой модели.
        self._per_mesh_active: bool = False
        self._per_mesh_base_image: Optional[str] = None

        # ── Командные кадры из VPK ────────────────────────────────────────── #
        self._red_frames: List[str] = []
        self._blu_frames: List[str] = []
        self._team_framerate: float = 0.0
        # Для мульти-материальных моделей (персонажи): исходные tex_map'ы из VPK
        # используются для восстановления командных текстур (т.к. _red/_blu_frames = [])
        self._vpk_red_tex_map: dict = {}
        self._vpk_blu_tex_map: dict = {}
        # Маппинг {red_mat_name: blu_display_name} для лейблов карточек BLU команды
        self._vpk_blu_name_map: dict = {}

        # ── GIF кэш {gif_path: (frame_paths, fps)} ───────────────────────── #
        self._gif_cache: Dict[str, tuple] = {}

        # ── Флаг «дроп пришёл из 3D, не обновлять 3D обратно» ────────────── #
        self._from_3d_drop: bool = False

        # ── i18n ──────────────────────────────────────────────────────────── #
        from src.config.app_config import AppConfig
        from src.data.translations import TRANSLATIONS
        config = AppConfig.load_config()
        self._lang = config.get('language') or 'en'
        self.t = TRANSLATIONS[self._lang]

        # ── Виджеты карточек ──────────────────────────────────────────────── #
        self._card_widgets: Dict[str, _ExtraSlotCard] = {}  # {mat_name: card}
        self._main_card: Optional[_ExtraSlotCard] = None

        self.setAcceptDrops(True)
        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════════════
    # UI
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root.addWidget(self._build_toggle_bar())

        self.view_stack = QStackedWidget()
        self.view_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.page_2d = self._build_2d_page()
        self.view_stack.addWidget(self.page_2d)
        # page_3d добавляется в _init_3d_widget

        root.addWidget(self.view_stack)
        root.addWidget(self._build_info_panel())
        root.addStretch(1)

        self._init_3d_widget()

        # По умолчанию — 3D режим
        self.view_stack.setCurrentIndex(1)
        self.btn_load_3d.setVisible(True)
        self.btn_load_vpk.setVisible(True)

    def _build_toggle_bar(self) -> QWidget:
        bar = QWidget()
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addStretch()

        # ── Кнопки выбора маски шпиона — СЛЕВА от 3D/2D ─────────────────── #
        self._mask_btn_style_off = """
            QPushButton { background:transparent; color:#666; border:1px solid #2a2a2a;
                border-radius:3px; font-size:9px; font-weight:bold; padding:0; }
            QPushButton:hover { color:#aaa; border-color:#555; }
        """
        self._mask_btn_style_on = """
            QPushButton { background:rgba(180,130,30,0.18); color:#e8b84b;
                border:1px solid #8a6a20; border-radius:3px;
                font-size:9px; font-weight:bold; padding:0; }
            QPushButton:hover { border-color:#c9993a; }
        """
        self._spy_mask_buttons: list = []
        from src.data.player_characters import SPY_DISGUISE_MASKS as _SDM
        for _cls_key, _vtf, _en, _ru, _lbl in _SDM:
            _name = _ru if self._lang == 'ru' else _en
            _mb = QPushButton(_lbl)
            _mb.setFixedSize(24, 22)
            _mb.setStyleSheet(self._mask_btn_style_off)
            _mb.setToolTip(_name)
            _mb.setVisible(False)
            _mb.clicked.connect(lambda checked=False, k=_cls_key: self._switch_spy_mask(k))
            lay.addWidget(_mb)
            self._spy_mask_buttons.append((_cls_key, _mb))

        lay.addSpacing(8)

        # Единые стили текстовых чипов тулбара: 2D/3D и кнопки стилей
        # (skinfamilies) выглядят одинаково — один источник вместо двух.
        def _chip_style(active: bool, h_pad: int = 16) -> str:
            if active:
                return (
                    "QPushButton { background:#2a2a2a; color:#ccc; border:1px solid #444;"
                    f" padding:4px {h_pad}px; font-size:11px; font-weight:600; border-radius:3px; }}"
                )
            return (
                "QPushButton { background:transparent; color:#555; border:1px solid #2a2a2a;"
                f" padding:4px {h_pad}px; font-size:11px; border-radius:3px; }}"
                " QPushButton:hover { background:rgba(255,255,255,0.04); color:#888; border-color:#383838; }"
            )

        self._btn_style_active = _chip_style(True)
        self._btn_style_inactive = _chip_style(False)

        self.btn_3d = QPushButton("3D")
        self.btn_2d = QPushButton("2D")
        self.btn_3d.setFixedHeight(26)
        self.btn_2d.setFixedHeight(26)
        self.btn_3d.setStyleSheet(self._btn_style_active)
        self.btn_2d.setStyleSheet(self._btn_style_inactive)
        self.btn_3d.clicked.connect(self._switch_to_3d)
        self.btn_2d.clicked.connect(self._switch_to_2d)
        lay.addWidget(self.btn_3d)
        lay.addWidget(self.btn_2d)

        # Кнопки-иконки (куб / vpk)
        lay.addSpacing(12)
        _icon_btn_style = """
            QPushButton { background:transparent; border:1px solid #2a2a2a; border-radius:3px; padding:0; }
            QPushButton:hover { background:rgba(255,255,255,0.05); border-color:#555; }
            QPushButton:pressed { background:rgba(255,255,255,0.08); }
            QPushButton:disabled { opacity:0.3; }
        """

        self.btn_load_3d = QPushButton()
        self.btn_load_3d.setFixedSize(26, 26)
        self.btn_load_3d.setIcon(_make_cube_icon("#666666"))
        self.btn_load_3d.setStyleSheet(_icon_btn_style)
        self.btn_load_3d.setToolTip(self.t.get('3d_load_model_tip', 'Load 3D model'))
        self.btn_load_3d.setVisible(False)
        self.btn_load_3d.clicked.connect(self._on_load_3d_clicked)
        lay.addWidget(self.btn_load_3d)

        self.btn_load_vpk = QPushButton()
        self.btn_load_vpk.setFixedSize(26, 26)
        self.btn_load_vpk.setIcon(_make_vpk_icon("#666666"))
        self.btn_load_vpk.setStyleSheet(_icon_btn_style)
        self.btn_load_vpk.setToolTip(self.t.get('3d_load_vpk_tip', 'Load VPK mod for 3D Preview'))
        self.btn_load_vpk.setVisible(False)
        self.btn_load_vpk.setEnabled(False)
        self.btn_load_vpk.clicked.connect(self._on_load_vpk_clicked)
        lay.addWidget(self.btn_load_vpk)

        # Кнопка «Заменить модель» — выбрать свою SMD и сразу увидеть её в 3D
        self.btn_replace_model = QPushButton()
        self.btn_replace_model.setFixedSize(26, 26)
        self.btn_replace_model.setIcon(_make_replace_icon("#666666"))
        self.btn_replace_model.setStyleSheet(_icon_btn_style)
        self.btn_replace_model.setToolTip(
            self.t.get('3d_replace_model_tip', 'Replace model with your own (SMD)')
        )
        self.btn_replace_model.setVisible(False)
        self.btn_replace_model.clicked.connect(self._on_replace_model_clicked)
        lay.addWidget(self.btn_replace_model)

        # Командные кнопки RED/BLU
        lay.addSpacing(8)
        self._team_style_off = """
            QPushButton { background:transparent; border:1px solid #2a2a2a; border-radius:13px; padding:0; }
            QPushButton:hover { border-color:#555; }
            QPushButton:pressed { background:rgba(255,255,255,0.08); }
        """
        self._team_style_on = """
            QPushButton { background:rgba(255,255,255,0.07); border:1px solid #555;
                border-radius:13px; padding:0; }
            QPushButton:hover { border-color:#888; }
        """

        self.btn_red = QPushButton()
        self.btn_red.setFixedSize(26, 26)
        self.btn_red.setIcon(_make_team_icon("#c0392b"))
        self.btn_red.setStyleSheet(self._team_style_on)   # RED активен по умолчанию
        self.btn_red.setToolTip(self.t.get('3d_team_red_tip', 'RED team texture'))
        self.btn_red.setVisible(False)
        self.btn_red.clicked.connect(lambda: self._switch_team('red'))
        lay.addWidget(self.btn_red)

        self.btn_blu = QPushButton()
        self.btn_blu.setFixedSize(26, 26)
        self.btn_blu.setIcon(_make_team_icon("#2980b9"))
        self.btn_blu.setStyleSheet(self._team_style_off)
        self.btn_blu.setToolTip(self.t.get('3d_team_blu_tip', 'BLU team texture'))
        self.btn_blu.setVisible(False)
        self.btn_blu.clicked.connect(lambda: self._switch_team('blu'))
        lay.addWidget(self.btn_blu)

        # ── Кнопка Australium/Gold variant ───────────────────────────────── #
        self._aus_style_off = """
            QPushButton { background:transparent; border:1px solid #2a2a2a;
                border-radius:13px; padding:0; }
            QPushButton:hover { border-color:#7a6a20; }
        """
        self._aus_style_on = """
            QPushButton { background:rgba(180,150,20,0.15); border:1px solid #8a7a20;
                border-radius:13px; padding:0; }
            QPushButton:hover { border-color:#c0a830; }
        """
        self.btn_aus = QPushButton()
        self.btn_aus.setFixedSize(26, 26)
        self.btn_aus.setIcon(_make_team_icon("#c8a820"))
        self.btn_aus.setStyleSheet(self._aus_style_off)
        self.btn_aus.setToolTip("Australium / Gold variant")
        self.btn_aus.setVisible(False)
        self.btn_aus.clicked.connect(self._toggle_australium)
        lay.addWidget(self.btn_aus)

        # ── Кнопки стилей (skinfamilies) — в том же ряду, что RED/BLU/Aus ──── #
        # Создаются динамически при определении стилей кастомной модели и
        # вставляются ПЕРЕД этим анкером, чтобы держаться правее aus.
        self._skin_anchor = QWidget()
        self._skin_anchor.setFixedWidth(0)
        lay.addWidget(self._skin_anchor)
        self._toolbar_layout = lay
        # Кнопки стилей — те же чипы, что и 2D/3D (чуть меньше отступы)
        self._skin_btn_style_on = _chip_style(True, h_pad=12)
        self._skin_btn_style_off = _chip_style(False, h_pad=12)

        self._active_spy_mask: Optional[str] = None   # активный класс маски

        return bar

    def _build_2d_page(self) -> QWidget:
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vlay = QVBoxLayout(page)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        _border = "border:1px solid #333; border-radius:4px; background:#1a1a1a;"

        # Пустое состояние
        self.empty_state = QWidget()
        self.empty_state.setFixedHeight(500)
        self.empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.empty_state.setMinimumWidth(440)
        self.empty_state.setStyleSheet(f"QWidget {{ {_border} }}")
        self.empty_state.setAcceptDrops(True)
        e_lay = QVBoxLayout(self.empty_state)
        e_lay.setAlignment(Qt.AlignCenter)
        e_lay.setSpacing(16)

        self.empty_text = QLabel(self.t['drag_text'])
        self.empty_text.setStyleSheet("color:#666; font-size:14px; font-weight:300; padding:40px;")
        self.empty_text.setAlignment(Qt.AlignCenter)
        e_lay.addWidget(self.empty_text)

        self.select_file_button = QPushButton(self.t['select_file_btn'])
        self.select_file_button.setStyleSheet("""
            QPushButton { background:transparent; color:#888; border:1px solid #333;
                padding:10px 24px; font-size:13px; font-weight:500; border-radius:4px; }
            QPushButton:hover { background:rgba(255,255,255,0.05); border-color:#555; color:#ccc; }
        """)
        self.select_file_button.clicked.connect(self.browse_image)
        e_lay.addWidget(self.select_file_button, alignment=Qt.AlignCenter)
        vlay.addWidget(self.empty_state)

        # Большое превью (одиночный режим)
        self._preview_style = "QLabel { border:1px solid #333; border-radius:4px; background:#1a1a1a; }"
        self.preview = QLabel()
        self.preview.setStyleSheet(self._preview_style)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(500)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preview.setMinimumWidth(440)
        self.preview.setAcceptDrops(True)
        self.preview.hide()
        vlay.addWidget(self.preview)

        # Полоса карточек (многоматериальный режим)
        # Используем _HWheelScrollArea: колесо мыши прокручивает карточки горизонтально
        scroll = _HWheelScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent;")
        scroll.setMinimumHeight(508)
        scroll.setMaximumHeight(700)   # запас для раскрытых AI-панелей

        self._cards_bar = QWidget()
        self._cards_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._cards_layout = QHBoxLayout(self._cards_bar)
        self._cards_layout.setContentsMargins(0, 4, 0, 4)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_bar)
        self._cards_scroll = scroll
        self._cards_scroll.hide()
        vlay.addWidget(self._cards_scroll)

        return page

    def _build_info_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedHeight(220)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        panel.setMinimumWidth(440)
        panel.setStyleSheet("""
            QWidget { background:rgba(255,255,255,0.02); border:1px solid #333; border-radius:4px; }
        """)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.info_title = QLabel(self.t['info_title'])
        self.info_title.setStyleSheet(
            "font-weight:600; font-size:13px; color:#ccc; padding-bottom:8px; border-bottom:1px solid #333;"
        )
        lay.addWidget(self.info_title)

        for attr in ('info_resolution', 'info_format', 'info_flags', 'info_filename'):
            lbl = QLabel("")
            lbl.setStyleSheet("font-size:12px; color:#888;")
            setattr(self, attr, lbl)
            lay.addWidget(lbl)

        self.info_summary = panel
        return panel

    def _init_3d_widget(self) -> None:
        from src.ui.preview_3d_widget import Preview3DWidget, is_webengine_available
        self._3d_available = is_webengine_available()
        self._3d_widget = Preview3DWidget.create(self)
        self._3d_widget.set_language(self._lang)

        qt_w = self._3d_widget.qt_widget
        qt_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        qt_w.setMinimumHeight(500)
        qt_w.setMinimumWidth(440)

        self.page_3d = qt_w
        self.view_stack.addWidget(self.page_3d)

        bridge = getattr(self._3d_widget, '_bridge', None)
        if bridge is not None:
            try:
                bridge.texture_dropped.connect(self._on_3d_texture_dropped)
            except Exception as exc:
                logger.warning(f"3D bridge texture_dropped: {exc}")
            try:
                bridge.per_mesh_applied.connect(self._on_3d_per_mesh_applied)
            except Exception as exc:
                logger.warning(f"3D bridge per_mesh_applied: {exc}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Переключение 2D / 3D
    # ═══════════════════════════════════════════════════════════════════════════

    def _update_3d_buttons_visibility(self) -> None:
        """
        Видимость кнопок «загрузить модель/VPK»: показываем только в 3D-виде
        и НЕ в крит-режиме. Единая точка истины — вызывается и при переключении
        вида (2D/3D), и при смене 3D-состояния (set_3d_params/set_crithit_mode),
        иначе после крита кнопки не возвращаются.
        """
        show = self.is_3d_mode() and not self._crithit_mode
        self.btn_load_3d.setVisible(show)
        self.btn_load_vpk.setVisible(show)
        if hasattr(self, 'btn_replace_model'):
            self.btn_replace_model.setVisible(show)

    def _switch_to_2d(self) -> None:
        self.view_stack.setCurrentIndex(0)
        self.btn_2d.setStyleSheet(self._btn_style_active)
        self.btn_3d.setStyleSheet(self._btn_style_inactive)
        self._update_3d_buttons_visibility()
        # Командные кнопки остаются видны если есть BLU данные
        self._update_team_btn_visibility()
        # Синхронизируем 2D с активной командой — карточки могли не обновиться
        # пока пользователь смотрел 3D и переключал команды там
        self._restore_team_textures_2d(self._active_team)

    def _switch_to_3d(self) -> None:
        if self._3d_widget is None:
            return
        self.view_stack.setCurrentIndex(1)
        self.btn_3d.setStyleSheet(self._btn_style_active)
        self.btn_2d.setStyleSheet(self._btn_style_inactive)
        self._update_3d_buttons_visibility()

        if self._crithit_mode:
            if self._3d_available:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, self._render_crithit_scene)
            return

        self.btn_load_vpk.setEnabled(True)
        self._update_team_btn_visibility()

        # Переприменяем текущие текстуры к 3D если они загружены
        # (например, пользователь переключился в 2D, загрузил текстуру, вернулся в 3D)
        self._reapply_textures_to_3d()

    def _reapply_textures_to_3d(self, delay_ms: int = 300) -> None:
        """
        Повторно применяет пользовательские текстуры к 3D-модели поверх
        VPK-оригиналов. Вызывается при переключении в 3D и сразу после
        загрузки модели из игры (чтобы уже загруженная в 2D текстура
        применилась без повторного 2D→3D).
        """
        skip = (
            self._per_mesh_active
            and self.image_path is not None
            and self.image_path == self._per_mesh_base_image
        )
        if skip or not self._3d_available or not self._3d_widget:
            return

        # Восстанавливаем текстуры: VPK-оригиналы + пользовательские поверх.
        # _restore_team_textures_3d строит полную карту и правильно
        # обрабатывает очищенные (×) слоты, возвращая им VPK-оригинал.
        from PySide6.QtCore import QTimer
        if self._card_mode and self._material_names:
            QTimer.singleShot(delay_ms, lambda: self._restore_team_textures_3d(self._active_team))
        elif self.image_path and os.path.exists(self.image_path):
            path = self.image_path
            QTimer.singleShot(delay_ms, lambda p=path: self._apply_image_to_3d(p))

    def is_3d_mode(self) -> bool:
        return self.view_stack.currentIndex() == 1

    def _update_team_btn_visibility(self) -> None:
        """
        Единая точка синхронизации командных/вариантных кнопок тулбара.

        RED/BLU видимы только если у модели РЕАЛЬНО есть BLU-вариант:
          - _blu_frames        — BLU одним кадром (оружие/шапка с командной текстурой);
          - _vpk_blu_tex_map / _vpk_blu_name_map — per-material BLU (персонажи).
        (учёт _card_mode / _textures['blu'] давал ложные кнопки у
        мульти-материальных шапок без командного разделения).

        Australium-кнопка видима, когда воркер извлёк вариант (_australium_frame).
        В режиме spy_masks всё скрыто — там своя панель масок.
        """
        if self._spy_mask_mode:
            self.btn_red.setVisible(False)
            self.btn_blu.setVisible(False)
            self.btn_aus.setVisible(False)
            return
        has_blu = bool(
            self._blu_frames or self._vpk_blu_tex_map or self._vpk_blu_name_map
        )
        self.btn_red.setVisible(has_blu)
        self.btn_blu.setVisible(has_blu)
        self.btn_aus.setVisible(bool(self._australium_frame))

    # ═══════════════════════════════════════════════════════════════════════════
    # Маски маскировки шпиона
    # ═══════════════════════════════════════════════════════════════════════════

    def set_spy_mask_mode(self, enabled: bool) -> None:
        """Включает/выключает режим масок шпиона (показывает кнопки классов)."""
        self._spy_mask_mode = enabled
        for _cls_key, _btn in self._spy_mask_buttons:
            _btn.setVisible(enabled)
        if enabled and self._active_spy_mask is None:
            # По умолчанию активируем первую маску (Scout)
            from src.data.player_characters import SPY_DISGUISE_MASKS
            if SPY_DISGUISE_MASKS:
                self._switch_spy_mask(SPY_DISGUISE_MASKS[0][0])
        elif not enabled:
            self._active_spy_mask = None

    def _switch_spy_mask(self, cls_key: str) -> None:
        """Переключает активную маску шпиона в 3D и 2D."""
        from src.data.player_characters import SPY_DISGUISE_MASKS
        self._active_spy_mask = cls_key

        # Обновляем стили кнопок
        for _key, _btn in self._spy_mask_buttons:
            _btn.setStyleSheet(
                self._mask_btn_style_on if _key == cls_key else self._mask_btn_style_off
            )

        # Находим vtf_name для этого класса
        vtf_name = next((m[1] for m in SPY_DISGUISE_MASKS if m[0] == cls_key), None)
        if not vtf_name:
            return

        # Прокручиваем 2D стрип к карточке этой маски
        if self._card_mode and vtf_name in self._card_widgets:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, lambda w=self._card_widgets[vtf_name]:
                              self._cards_scroll.ensureWidgetVisible(w))

        if not (self._3d_widget and self._3d_available):
            return

        # Если пользователь загрузил свою текстуру — используем её
        user_tex = self._textures.get('red', {}).get(vtf_name)
        if user_tex and os.path.exists(user_tex):
            from PySide6.QtCore import QTimer
            # Маска в SMD называется "mask_spy" — применяем к этому слоту
            QTimer.singleShot(100, lambda p=user_tex:
                              self._3d_widget.apply_material_map({'mask_spy': p}))
            return

        # Нет пользовательской текстуры — извлекаем из VPK в фоне
        from PySide6.QtCore import QThread, Signal as _Signal

        class _MaskExtractWorker(QThread):
            done = _Signal(str)  # png_path

            def __init__(self, vtf_name, misc_vpk, textures_vpk, preview_dir):
                super().__init__()
                self._vtf = vtf_name
                self._misc = misc_vpk
                self._tex = textures_vpk
                self._dir = preview_dir

            def run(self):
                try:
                    import vpk as vpklib
                    from src.services.vtflib_wrapper import VTFLib
                    from PIL import Image
                    vtf_path_in_vpk = f"materials/models/player/spy/{self._vtf}.vtf"
                    vtf_data = None
                    for vp in [self._tex, self._misc]:
                        if not vp or not os.path.exists(vp):
                            continue
                        try:
                            pak = vpklib.open(vp)
                            vtf_data = pak[vtf_path_in_vpk].read()
                            break
                        except (KeyError, Exception):
                            continue
                    if not vtf_data:
                        return
                    tmp = os.path.join(self._dir, f"_tmp_{self._vtf}.vtf")
                    with open(tmp, "wb") as f:
                        f.write(vtf_data)
                    frames, w, h = VTFLib.read_vtf_all_frames(tmp)
                    os.remove(tmp)
                    if frames:
                        img = Image.frombytes("RGBA", (w, h), frames[0])
                        out = os.path.join(self._dir, f"{self._vtf}.png")
                        img.save(out)
                        self.done.emit(out)
                except Exception:
                    pass

        # Сохраняем воркер чтобы не был удалён GC
        w = _MaskExtractWorker(
            vtf_name,
            getattr(self, '_current_misc_vpk', None),
            getattr(self, '_current_textures_vpk', None),
            os.path.join('tools', 'temp', 'spy_mask_preview'),
        )
        os.makedirs(os.path.join('tools', 'temp', 'spy_mask_preview'), exist_ok=True)
        w.done.connect(lambda png: self._3d_widget.apply_material_map({'mask_spy': png}))
        w.start()
        # Храним ссылку
        if not hasattr(self, '_mask_workers'):
            self._mask_workers = []
        self._mask_workers.append(w)

    # ═══════════════════════════════════════════════════════════════════════════
    # Команды RED / BLU
    # ═══════════════════════════════════════════════════════════════════════════

    def _switch_team(self, team: str) -> None:
        """Переключает активную команду и восстанавливает её текстуры."""
        if self._active_team == team:
            return
        self._active_team = team
        self.btn_red.setStyleSheet(
            self._team_style_on if team == 'red' else self._team_style_off
        )
        self.btn_blu.setStyleSheet(
            self._team_style_on if team == 'blu' else self._team_style_off
        )
        self._restore_team_textures_2d(team)
        if self._3d_available and self._3d_widget:
            self._restore_team_textures_3d(team)

    def _restore_team_textures_2d(self, team: str) -> None:
        """Показывает в 2D карточках/большом превью текстуры выбранной команды."""
        paths = self._textures.get(team, {})

        if self._card_mode and self._material_names:
            main_key = self._material_names[0]
            main_path = paths.get(main_key)
            self.image_path = main_path if (main_path and os.path.exists(main_path)) else None

            # Обновляем изображения в существующих карточках напрямую
            # (без полного пересоздания — чтобы нейтральные текстуры оставались).
            if self._card_widgets or self._main_card:
                self._update_card_images_for_team(team)
            else:
                # Карточки ещё не созданы — создаём
                self._set_material_slots(self._material_names)
        else:
            key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
            path = paths.get(key)
            self._stop_gif()
            if path and os.path.exists(path):
                self.image_path = path
                self._show_image_in_preview(path)
            else:
                # Своей текстуры для команды нет — показываем игровой кадр команды
                # (display-only, как делает 3D через _apply_vpk_frames). image_path
                # оставляем None: сборка не должна считать это пользовательской текстурой.
                self.image_path = None
                vpk_frames = self._blu_frames if team == 'blu' else self._red_frames
                if vpk_frames and os.path.exists(vpk_frames[0]):
                    self._show_image_in_preview(vpk_frames[0])
                else:
                    self._clear_preview_label()

        self.vtf_path = None
        self.update_info_summary()

    def _update_card_images_for_team(self, team: str) -> None:
        """Обновляет изображения в существующих карточках для выбранной команды.

        Вместо полного пересоздания (deleteLater + new cards) просто обновляем
        изображение каждой карточки. Для нейтральных текстур (sniper_lens и т.п.)
        берём из любой команды где она есть.
        """
        # Для BLU обновляем label карточки если есть маппинг имён
        def _display(mat_name: str) -> str:
            if team == 'blu' and self._vpk_blu_name_map:
                return self._vpk_blu_name_map.get(mat_name, mat_name)
            return mat_name

        # Главная карточка
        if self._main_card and self._material_names:
            main_name = self._material_names[0]
            self._main_card.set_display_name(_display(main_name))
            tex = self._resolve_card_texture(main_name)
            if tex and os.path.exists(tex):
                self._main_card.set_image(tex, opaque=self._is_game_texture(tex))
            elif self._original_skin_info and self._active_skin != 0:
                # Вариантный стиль без переопределения — карточка должна быть пустой.
                self._main_card.reset()
            elif not self._main_card.get_image():
                pass  # оставляем как есть

        # Дополнительные карточки
        for mat_name, card in self._card_widgets.items():
            card.set_display_name(_display(mat_name))
            tex = self._resolve_card_texture(mat_name)
            logger.debug(f"[restore 2D] team={team} mat={mat_name!r} tex={tex!r}")
            if tex and os.path.exists(tex):
                card.set_image(tex, opaque=self._is_game_texture(tex))
            else:
                # Нет текстуры для этой команды — сбрасываем карточку
                if not self._is_neutral_texture(mat_name):
                    card.reset()
                # Нейтральные оставляем как есть (уже показывают нужную текстуру)

    def _restore_team_textures_3d(self, team: str) -> None:
        """Применяет текстуры команды к 3D модели.

        Строит полную карту: VPK-оригиналы для всех слотов + пользовательские
        текстуры поверх. Это гарантирует что очищенные (×) слоты корректно
        возвращаются к игровому оригиналу, а не остаются с кастомной текстурой.
        """
        from PySide6.QtCore import QTimer
        paths = self._textures.get(team, {})
        vpk_frames = self._red_frames if team == 'red' else self._blu_frames
        vpk_map = self._vpk_red_tex_map if team == 'red' else self._vpk_blu_tex_map

        if self._card_mode and self._material_names:
            # Начинаем с VPK-оригиналов (база для всех слотов)
            full_map: dict = dict(vpk_map) if vpk_map else {}

            # Поверх накладываем пользовательские текстуры (только загруженные)
            for mat in self._material_names:
                p = paths.get(mat)
                if p and os.path.exists(p):
                    full_map[mat] = p
                elif mat in full_map:
                    pass   # Слот очищен — оставляем VPK-оригинал из базы

            if full_map:
                static: dict = {}
                for mat, p in full_map.items():
                    if p.lower().endswith('.gif'):
                        QTimer.singleShot(50, lambda _p=p, _m=mat: self._apply_gif_to_3d(_p, _m))
                    else:
                        static[mat] = p
                if static:
                    QTimer.singleShot(50, lambda m=static: self._3d_widget.apply_material_map(m))
            else:
                # VPK-карта пустая (оружие/шапка без мульти-материала) → кадры
                self._apply_vpk_frames(vpk_frames)
        else:
            key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
            path = paths.get(key)
            if path and os.path.exists(path):
                QTimer.singleShot(50, lambda p=path: self._apply_image_to_3d(p))
            else:
                self._apply_vpk_frames(vpk_frames)

    def _apply_vpk_frames(self, frames: List[str]) -> None:
        """Применяет VPK-кадры к 3D модели."""
        if not frames or not self._3d_widget:
            return
        if len(frames) > 1 and self._team_framerate > 0:
            self._3d_widget.update_animated_texture_files(frames, self._team_framerate)
        else:
            self._3d_widget.update_texture_file(frames[0])

    # ═══════════════════════════════════════════════════════════════════════════
    # Мини-память последнего оружия
    # ═══════════════════════════════════════════════════════════════════════════

    def _snapshot_outgoing(self, outgoing_mode: str) -> Optional[dict]:
        """
        Делает снимок состояния уходящего оружия для мгновенного восстановления.

        Возвращает None (не запоминаем), если:
          - модель не была загружена (_cur_obj пуст или о другом режиме);
          - режим не «обычное оружие/персонаж» (хаты, спрей, крит, кастом);
          - активны сложные спец-режимы (маски шпиона / australium / custom SMD),
            где состояние слишком связное — безопаснее перезагрузить заново.
        """
        if not self._cur_obj or self._cur_obj[0] != outgoing_mode:
            return None
        if not outgoing_mode or outgoing_mode in ('hat', 'spray', 'critHIT', 'custom'):
            return None
        if self._spy_mask_mode or self._australium_active or self._custom_smd_mode:
            return None
        obj_path = self._cur_obj[1]
        if not obj_path or not os.path.exists(obj_path):
            return None

        return {
            'mode': outgoing_mode,
            'obj_path': obj_path,
            'texture_path': self._cur_obj[2],
            'material_names': list(self._material_names),
            'card_mode': self._card_mode,
            'has_blu': self._has_blu,
            'active_team': self._active_team,
            'image_path': self.image_path,
            'textures': {t: dict(d) for t, d in self._textures.items()},
            'vpk_red_tex_map': dict(self._vpk_red_tex_map or {}),
            'vpk_blu_tex_map': dict(self._vpk_blu_tex_map or {}),
            'vpk_blu_name_map': dict(self._vpk_blu_name_map or {}),
            # VPK-кадры команд и вариант Australium — нужны для восстановления
            # кнопок RED/BLU и золотой кнопки без перезагрузки модели.
            'red_frames': list(self._red_frames or []),
            'blu_frames': list(self._blu_frames or []),
            'team_framerate': self._team_framerate,
            'australium_frame': self._australium_frame,
            'australium_mat_name': self._australium_mat_name,
            'australium_user_tex': self._australium_user_tex,
        }

    def _restore_from_memory(self, data: dict) -> None:
        """Мгновенно восстанавливает оружие из снимка (без перезапуска воркера)."""
        # Сначала восстанавливаем текстуры/команды — _set_material_slots читает
        # их через _resolve_card_texture при пересоздании карточек.
        self._textures = {t: dict(d) for t, d in data['textures'].items()}
        self.image_path = data['image_path']
        self._active_team = data['active_team']
        self._has_blu = data['has_blu']
        self._vpk_red_tex_map = dict(data.get('vpk_red_tex_map') or {})
        self._vpk_blu_tex_map = dict(data.get('vpk_blu_tex_map') or {})
        self._vpk_blu_name_map = dict(data.get('vpk_blu_name_map') or {})
        # VPK-кадры команд и вариант Australium (сброшены в _reset_team_vpk_state)
        self._red_frames = list(data.get('red_frames') or [])
        self._blu_frames = list(data.get('blu_frames') or [])
        self._team_framerate = data.get('team_framerate', 0.0)
        self._australium_frame = data.get('australium_frame')
        self._australium_mat_name = data.get('australium_mat_name')
        self._australium_user_tex = data.get('australium_user_tex')

        # Пересоздаём карточки слотов (метод сам выставит _card_mode/_material_names)
        self._set_material_slots(list(data['material_names']))

        # Командные и Australium кнопки (учитывают восстановленное состояние)
        self._australium_active = False
        self.btn_aus.setStyleSheet(self._aus_style_off)
        self._update_team_btn_visibility()

        # Мгновенно грузим модель — obj уже на диске, воркер не нужен
        if self._3d_widget and data['obj_path'] and os.path.exists(data['obj_path']):
            self._3d_widget.load_model_files(data['obj_path'], data['texture_path'])
            self._cur_obj = (data['mode'], data['obj_path'], data['texture_path'])
            # Переприменяем пользовательские текстуры поверх (после загрузки в JS)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, lambda: self._restore_team_textures_3d(self._active_team))

    # ═══════════════════════════════════════════════════════════════════════════
    # Публичный API — управление 3D
    # ═══════════════════════════════════════════════════════════════════════════

    def set_3d_params(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
    ) -> None:
        """Сохраняет параметры 3D загрузки. Модель грузится только при нажатии ▶."""
        new_params = (weapon_key, mode, misc_vpk_path, textures_vpk_path)
        if new_params == self._last_3d_params:
            return   # ничего не изменилось — не сбрасываем состояние

        # ── Мини-память: снимок уходящего оружия (до сброса состояния) ────── #
        outgoing_mode = self._last_3d_params[1] if self._last_3d_params else self._weapon_mode
        snap = self._snapshot_outgoing(outgoing_mode)
        if snap:
            self._mem_mode = snap['mode']
            self._mem_data = snap

        self._last_3d_params = new_params
        self._pending_3d_params = new_params
        self._custom_smd_mode = False
        self._crithit_mode = False
        # Сохраняем VPK пути — нужны для _switch_spy_mask
        self._current_misc_vpk = misc_vpk_path
        self._current_textures_vpk = textures_vpk_path

        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()

        # ── Возврат на запомненное оружие → мгновенное восстановление ─────── #
        if self._mem_mode is not None and self._mem_mode == mode and self._mem_data is not None:
            self._restoring_memory = True
            self._restore_from_memory(self._mem_data)
            self._mem_mode = None
            self._mem_data = None   # 1 слот — извлекли
            self.btn_load_3d.setEnabled(True)
            self.btn_load_vpk.setEnabled(True)
            self._update_3d_buttons_visibility()
            return

        # ── Обычный путь: убираем старую модель из сцены (disappear-fix) ──── #
        self._cur_obj = None
        if self._3d_widget:
            self._3d_widget.reset()
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_weapon', 'Select a weapon and click ▶ to load the model')
            )
        self.btn_load_3d.setEnabled(True)
        self.btn_load_vpk.setEnabled(True)
        # Вышли из крит-режима на обычное оружие — вернуть кнопки, если мы в 3D
        self._update_3d_buttons_visibility()

    def reset_3d_preview(self) -> None:
        """Полный сброс 3D (при смене режима на Spray/None)."""
        self._pending_3d_params = None
        self._last_3d_params = None
        self._custom_smd_mode = False
        self._crithit_mode = False
        self._cur_obj = None   # модель убрана — нечего запоминать
        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._reset_team_vpk_state()
        if self._3d_widget:
            self._3d_widget.reset()
        self.btn_load_3d.setEnabled(False)

    def show_3d_no_tf2_message(self) -> None:
        self._pending_3d_params = None
        self._last_3d_params = None
        self._custom_smd_mode = False
        self._crithit_mode = False
        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()
        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_no_tf2', 'Set TF2 folder in Settings to load original models')
            )
        self.btn_load_3d.setEnabled(False)
        self.btn_load_vpk.setEnabled(False)

    def get_custom_smd_path(self) -> Optional[str]:
        """Путь к кастомной модели, загруженной в превью (для сборки, чтобы не
        просить выбрать SMD повторно). None — если не загружена."""
        p = self._custom_smd_path
        return p if (p and os.path.isfile(p)) else None

    def set_custom_model_mode(self, enabled: bool = True) -> None:
        self._custom_smd_mode = enabled
        self._pending_3d_params = None
        if not enabled:
            self._custom_smd_path = None   # вышли из режима — забываем модель
        self._stop_worker('_3d_worker')
        if enabled:
            if self._3d_widget:
                self._3d_widget.show_prompt(
                    self.t.get('3d_prompt_smd', 'Click ▶ and select an SMD file')
                )
            self.btn_load_3d.setEnabled(True)
            self.btn_load_vpk.setEnabled(True)
        else:
            if self._3d_widget:
                self._3d_widget.reset()
            self.btn_load_3d.setEnabled(False)
            self.btn_load_vpk.setEnabled(False)

    def set_crithit_mode(self) -> None:
        # ── Снимок уходящего оружия в мини-память (ДО очистки состояния) ──── #
        # Переход в крит идёт через этот метод, а не set_3d_params, поэтому
        # снимок надо делать здесь — иначе возврат на оружие ничего не вернёт.
        snap = self._snapshot_outgoing(self._weapon_mode)
        if snap:
            self._mem_mode = snap['mode']
            self._mem_data = snap

        # Текстура/изображение оружия НЕ должны протекать в крит-сцену
        # (_render_crithit_scene использует self.image_path как текстуру биллборда).
        self.image_path = None
        self.vtf_path = None
        self._cur_obj = None

        self._crithit_mode = True
        self._custom_smd_mode = False
        self._pending_3d_params = None
        # Сбрасываем кэш последних 3D-параметров: иначе возврат на то же оружие,
        # что было до крита, вызовет ранний return в set_3d_params и _crithit_mode
        # останется True (кнопки не вернутся, крит-сцена зависнет).
        self._last_3d_params = None
        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._reset_team_vpk_state()
        # Прячем кнопки загрузки модели/VPK (крит-режим)
        self._update_3d_buttons_visibility()
        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_crithit', 'Switch to 3D tab — the soldier will appear automatically')
            )
        if self.is_3d_mode() and self._3d_available:
            self._render_crithit_scene()

    def _on_load_3d_clicked(self) -> None:
        if self._custom_smd_mode:
            self._load_custom_smd_via_dialog()
            return
        if not self._pending_3d_params:
            return
        weapon_key, mode, misc_vpk, textures_vpk = self._pending_3d_params
        self._start_3d_worker(weapon_key, mode, misc_vpk, textures_vpk)

    # ═══════════════════════════════════════════════════════════════════════════
    # Управление воркерами
    # ═══════════════════════════════════════════════════════════════════════════

    def _stop_worker(self, attr: str) -> None:
        """Останавливает воркер по имени атрибута и зануляет его."""
        w = getattr(self, attr, None)
        if w is not None and w.isRunning():
            w.requestInterruption()
            w.wait(3000)
        setattr(self, attr, None)

    def _start_3d_worker(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk: str,
        textures_vpk: str,
    ) -> None:
        if not self._3d_available or not self._3d_widget:
            return
        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()
        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_preparing', 'Preparing 3D model...'))

        from src.services.preview_3d_worker import Preview3DWorker
        w = Preview3DWorker(
            weapon_key=weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=self._lang,
            parent=self,
        )
        w.progress.connect(lambda txt: self._3d_widget and self._3d_widget.show_loading(txt))
        w.ready.connect(self._on_3d_ready)
        w.animated.connect(self._on_3d_animated)
        w.multi_material.connect(self._on_3d_multi_material)
        w.blu_ready.connect(self._on_3d_blu_ready)
        w.blu_multi_material.connect(self._on_3d_blu_multi_material)
        w.australium_ready.connect(self._on_australium_ready)
        w.failed.connect(self._on_3d_failed)
        w.start()
        self._3d_worker = w

    def _start_qc_cards_worker(self) -> None:
        """Извлекает текстуры/карточки из QC игровой модели, НЕ трогая геометрию.

        Режим «No, geometry only»: в 3D остаётся геометрия пользователя, но
        карточки и текстуры берутся из игрового QC ($texturegroup). Сигнал
        ready (геометрия оригинала) НЕ подключаем — вместо него применяем
        главную игровую текстуру глобально к пользовательской модели.
        """
        if not self._3d_available or not self._3d_widget or not self._pending_3d_params:
            return
        weapon_key, mode, misc_vpk, textures_vpk = self._pending_3d_params
        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()

        from src.services.preview_3d_worker import Preview3DWorker
        w = Preview3DWorker(
            weapon_key=weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=self._lang,
            parent=self,
        )
        # НЕ подключаем ready → геометрия оригинала не загружается.
        # Главную текстуру применяем глобально к геометрии пользователя.
        w.ready.connect(self._on_qc_cards_ready)
        w.animated.connect(self._on_3d_animated)
        w.multi_material.connect(self._on_3d_multi_material)
        w.blu_ready.connect(self._on_3d_blu_ready)
        w.blu_multi_material.connect(self._on_3d_blu_multi_material)
        w.australium_ready.connect(self._on_australium_ready)
        w.failed.connect(lambda e: (self.btn_load_3d.setEnabled(True),
                                    logger.info(f"[QC CARDS] {e}")))
        w.start()
        self._3d_worker = w

    def _on_qc_cards_ready(self, obj_path: str, texture_path: str) -> None:
        """ready в режиме geometry-only: геометрию НЕ перезагружаем (она
        пользовательская), применяем игровую текстуру глобально."""
        self.btn_load_3d.setEnabled(True)
        if texture_path:
            self._red_frames = [texture_path]
            if self._3d_widget and not self._card_mode:
                # Одно-материальная модель: показываем игровую текстуру глобально.
                self._3d_widget.update_texture_file(texture_path)

    def _start_vpk_mod_worker(self, user_vpk: str) -> None:
        if not self._3d_available or not self._3d_widget:
            return

        misc_vpk, textures_vpk = '', ''
        if self._pending_3d_params and len(self._pending_3d_params) >= 4:
            misc_vpk = self._pending_3d_params[2]
            textures_vpk = self._pending_3d_params[3]
        elif hasattr(self, 'parent') and hasattr(self.parent, 'settings_panel'):
            try:
                from src.services.tf2_paths import TF2Paths
                settings = self.parent.settings_panel.get_settings()
                tf2 = settings.get('tf2_game_folder', '')
                if tf2:
                    _, misc_vpk, _ = TF2Paths.resolve(tf2)
                    textures_vpk = TF2Paths.resolve_textures_vpk(tf2)
            except Exception:
                pass

        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._reset_team_vpk_state()

        self.btn_load_vpk.setEnabled(False)
        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_analyzing_vpk', 'Analyzing VPK mod...'))

        from src.services.preview_vpk_mod_worker import PreviewVpkModWorker
        w = PreviewVpkModWorker(
            user_vpk_path=user_vpk,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=self._lang,
            parent=self,
        )
        w.progress.connect(lambda txt: self._3d_widget and self._3d_widget.show_loading(txt))
        w.ready.connect(self._on_vpk_mod_ready)
        w.animated.connect(self._on_3d_animated)
        w.blu_ready.connect(self._on_3d_blu_ready)
        w.failed.connect(self._on_vpk_mod_failed)
        w.start()
        self._vpk_mod_worker = w

    # ── Коллбэки воркеров ─────────────────────────────────────────────────────

    def _on_3d_ready(self, obj_path: str, texture_path: str) -> None:
        self.btn_load_3d.setEnabled(True)
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self._active_team = 'red'   # всегда синхронизируем (кнопки уже сброшены)
        if texture_path:
            self._red_frames = [texture_path]
        # Запоминаем загруженную модель для мини-памяти (мгновенное восстановление)
        _loaded_mode = self._pending_3d_params[1] if self._pending_3d_params else self._weapon_mode
        self._cur_obj = (_loaded_mode, obj_path, texture_path)
        if self._3d_widget:
            self._3d_widget.load_model_files(obj_path, texture_path)
            # Применяем уже загруженную в 2D текстуру к свежей модели.
            # Задержка 400мс — чтобы выполниться после _on_3d_multi_material
            # (он выставляет _card_mode/_material_names) и загрузки модели в JS.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(400, self._reapply_textures_to_3d)

    def _on_vpk_mod_ready(self, obj_path: str, texture_path: str) -> None:
        self.btn_load_vpk.setEnabled(True)
        self.btn_load_3d.setEnabled(bool(self._pending_3d_params or self._custom_smd_mode))
        self._active_team = 'red'   # всегда синхронизируем (кнопки уже сброшены)
        if texture_path:
            self._red_frames = [texture_path]
        if self._3d_widget:
            self._3d_widget.load_model_files(obj_path, texture_path)

    def _on_vpk_mod_failed(self, error: str) -> None:
        logger.warning(f"VPK мод Preview: {error}")
        self.btn_load_vpk.setEnabled(True)
        self.btn_load_3d.setEnabled(bool(self._pending_3d_params or self._custom_smd_mode))
        if self._3d_widget:
            self._3d_widget.show_error(
                self.t.get('3d_error_prefix', 'Error: {error}').format(error=error)
            )

    def _on_3d_animated(self, frame_paths: list, framerate: float) -> None:
        """Воркер нашёл многокадровый VTF для RED команды."""
        if frame_paths:
            self._red_frames = frame_paths
            self._team_framerate = framerate
        if self._3d_widget and frame_paths:
            self._3d_widget.update_animated_texture_files(frame_paths, framerate)

    def _on_3d_blu_ready(self, frame_paths: list, framerate: float) -> None:
        """Воркер нашёл BLU текстуру — показываем переключатель команд."""
        if not frame_paths:
            return
        self._blu_frames = frame_paths
        if framerate > 0:
            self._team_framerate = framerate
        self.btn_red.setVisible(True)
        self.btn_blu.setVisible(True)

    def _on_australium_ready(self, png_path: str, mat_name: str = "") -> None:
        """
        Воркер нашёл Australium/Gold вариант: показываем золотую кнопку в
        тулбаре И отдельную карточку «Australium» в ряду типов текстур —
        чтобы вариант был виден и заменялся так же, как остальные типы.
        """
        if not png_path or not os.path.exists(png_path):
            return
        self._australium_frame = png_path
        self._australium_mat_name = (mat_name or "").lower() or None
        self._australium_active = False
        self.btn_aus.setStyleSheet(self._aus_style_off)
        self._update_team_btn_visibility()
        logger.info(
            f"[Panel] Australium вариант доступен: {os.path.basename(png_path)} "
            f"(материал: {self._australium_mat_name})"
        )

        # Australium как отдельный тип текстуры (карточка); для кастомных
        # моделей со стилями _append_australium_card сам ничего не сделает.
        if self._original_skin_info or self._custom_smd_mode:
            return
        if self._card_mode:
            self._append_australium_card(self._cards_layout)
        elif self._material_names:
            # Одиночная текстура → переключаемся на карточки, чтобы вариант
            # был виден (основная + Australium).
            self._set_material_slots(list(self._material_names), force_cards=True)

    def _append_australium_card(self, lay) -> None:
        """Добавляет карточку «Australium» в конец ряда карточек (если вариант есть)."""
        if not self._australium_frame:
            return
        if self._aus_card is not None:
            return  # уже есть — _set_material_slots пересоздаёт при rebuild
        # Кастомные модели со стилями: игровой texturegroup подавляется,
        # вариант не применяется — карточку не показываем.
        if self._original_skin_info or self._custom_smd_mode:
            return

        card = _ExtraSlotCard(
            '__australium__',
            display_name='Australium',
            parent=self._cards_bar,
        )
        card.setToolTip(self.t.get(
            'australium_card_tip',
            'Gold/Australium variant — upload your own texture or keep the game one',
        ))
        shown = (self._australium_user_tex
                 if (self._australium_user_tex and os.path.exists(self._australium_user_tex))
                 else self._australium_frame)
        card.set_image(shown, opaque=self._is_game_texture(shown))
        card.image_changed.connect(self._on_aus_card_changed)

        # Вставляем перед хвостовым stretch, если он есть
        idx = lay.count()
        if idx and lay.itemAt(idx - 1).spacerItem() is not None:
            lay.insertWidget(idx - 1, card)
        else:
            lay.addWidget(card)
        self._aus_card = card

    def _on_aus_card_changed(self, _mat: str, path: str) -> None:
        """Пользователь загрузил/очистил текстуру в карточке Australium."""
        if path and os.path.exists(path):
            self._set_australium_user_tex(path)
        else:
            self._set_australium_user_tex(None)
            # После очистки показываем игровой gold-вариант обратно
            if self._aus_card is not None and self._australium_frame:
                self._aus_card.set_image(
                    self._australium_frame,
                    opaque=self._is_game_texture(self._australium_frame),
                )

    def _toggle_australium(self) -> None:
        """Переключает Australium/обычный вариант — синхронно в 3D и 2D."""
        if not self._australium_frame or not self._3d_widget:
            return
        self._australium_active = not self._australium_active
        from PySide6.QtCore import QTimer
        if self._australium_active:
            self.btn_aus.setStyleSheet(self._aus_style_on)
            # Своя текстура для Australium имеет приоритет над игровым gold-вариантом
            tex = (self._australium_user_tex
                   if (self._australium_user_tex and os.path.exists(self._australium_user_tex))
                   else self._australium_frame)
            QTimer.singleShot(50, lambda t=tex: self._3d_widget.update_texture_file(t))
            self._show_variant_in_2d(tex)
        else:
            self.btn_aus.setStyleSheet(self._aus_style_off)
            # Возвращаем текстуру активной команды: VPK-оригинал + пользовательская
            # поверх. _restore_team_textures_3d корректно выбирает update_texture_file
            # для одиночного кадра (прямой update_animated с 1 кадром и fps=0 ломал текстуру).
            if self._3d_available and self._3d_widget:
                self._restore_team_textures_3d(self._active_team)
            # 2D: возвращаем текстуру активной команды
            self._restore_team_textures_2d(self._active_team)

    def _show_variant_in_2d(self, path: str) -> None:
        """Показывает вариант (Australium и т.п.) в 2D БЕЗ изменения сохранённых
        текстур — это превью игрового варианта, а не пользовательский выбор."""
        if not (path and os.path.exists(path)):
            return
        if self._card_mode and self._main_card:
            self._main_card.set_image(path, opaque=self._is_game_texture(path))
        else:
            self._show_image_in_preview(path)

    def _set_australium_user_tex(self, path: Optional[str]) -> None:
        """
        Сохраняет/сбрасывает СВОЮ текстуру для Australium (отдельный слот,
        не пересекается с обычной/командной). Применяет к 2D и 3D.
        Вызывается, когда пользователь грузит текстуру при активном Australium.
        """
        self._australium_user_tex = path or None
        # Зеркалим в _textures под именем gold-материала — чтобы сборка видела
        # австралий-текстуру: не блокировалась («загрузите текстуру»), не переспрашивала
        # её в callback'е, и при этом корректно спрашивала про ОРИГИНАЛ, если он не загружен.
        mat = self._australium_mat_name
        if mat:
            if path and os.path.exists(path):
                self._textures.setdefault('red', {})[mat] = path
                self._textures.setdefault('blu', {})[mat] = path
            else:
                self._textures.get('red', {}).pop(mat, None)
                self._textures.get('blu', {}).pop(mat, None)
        shown = path if (path and os.path.exists(path)) else self._australium_frame

        # Карточка Australium всегда отражает актуальную текстуру варианта
        if self._aus_card is not None and shown:
            self._aus_card.set_image(shown, opaque=self._is_game_texture(shown))

        # Главное превью и 3D подменяем ТОЛЬКО при активном gold-тумблере:
        # загрузка через карточку Australium не должна затирать основную текстуру.
        if self._australium_active:
            self._show_variant_in_2d(shown)
            if self._3d_available and self._3d_widget and shown:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(50, lambda t=shown: self._3d_widget.update_texture_file(t))

    def _on_3d_blu_multi_material(self, payload) -> None:
        """Воркер нашёл BLU текстуры для многоматериальной модели (персонажи).

        payload — кортеж (tex_map, name_map):
            tex_map:  {red_mat_name: blu_png_path}
            name_map: {red_mat_name: blu_display_name}

        Сохраняем для восстановления 3D при переключении на BLU.
        Не применяем сразу — пользователь пока на RED.
        """
        if not payload:
            return
        if isinstance(payload, tuple) and len(payload) == 2:
            tex_map, name_map = payload
        else:
            tex_map, name_map = payload, {}

        # Маппинг имён обновляем всегда — он нужен для лейблов карточек
        # даже если BLU VTF-текстуры не были найдены в VPK.
        if name_map:
            self._vpk_blu_name_map = dict(name_map)

        if tex_map:
            self._vpk_blu_tex_map = dict(tex_map)

        logger.debug(
            f"[Panel] BLU multi-material: {len(tex_map)} текстур, "
            f"{len(name_map)} имён"
        )
        # Кнопки RED/BLU показываем если есть хотя бы имена или текстуры
        if name_map or tex_map:
            self.btn_red.setVisible(True)
            self.btn_blu.setVisible(True)

    def _on_3d_multi_material(self, tex_map: dict) -> None:
        """Модель многоматериальная — применяем и создаём карточки."""
        if not (self._3d_widget and tex_map):
            return
        # В 3D применяем ВСЕ текстуры (включая глаза/зубы), иначе служебные меши
        # останутся без текстуры.
        self._3d_widget.apply_material_map(tex_map)
        if self._active_team == 'red' and not self._vpk_red_tex_map:
            self._vpk_red_tex_map = dict(tex_map)

        # А вот КАРТОЧКИ создаём только для редактируемых материалов — служебные
        # (eyeball_l/eyeball_r и т.п.) исключаем. Если после фильтра пусто
        # (вся модель «служебная») — оставляем как есть, чтобы не было пустоты.
        mat_keys = [m for m in tex_map.keys() if _is_editable_material(m)]
        if not mat_keys:
            mat_keys = list(tex_map.keys())
        current_all = (
            self._material_names if self._card_mode else []
        )
        if len(mat_keys) > 1:
            if mat_keys != current_all:
                self._set_material_slots(mat_keys)
            self._update_team_btn_visibility()
        elif mat_keys:
            self._material_names = mat_keys
            if self._card_mode:
                self._set_material_slots(mat_keys)


        # Руки: говорим 3D вьюверу какие меши редактируемы
        if self._pending_3d_params:
            mode = self._pending_3d_params[1]
            from src.data.player_hands import HAND_MODES, HAND_MODE_KEYS
            if mode in HAND_MODE_KEYS:
                textures_list = HAND_MODES.get(mode, {}).get("textures", [])
                hand_vtf_lower = {vtf.lower() for (_, vtf) in textures_list}
                _OVERLAY = ("_sheen2", "_sheen", "_overlay", "_fresnel")

                def _is_editable(mat: str) -> bool:
                    m = mat.lower()
                    if m in hand_vtf_lower:
                        return True
                    return any(m.endswith(s) and m[:-len(s)] in hand_vtf_lower for s in _OVERLAY)

                editable = [m for m in tex_map if _is_editable(m)]
                if editable:
                    self._3d_widget.set_editable_mesh_names(editable)

    def _on_3d_failed(self, error: str) -> None:
        logger.warning(f"3D Preview: {error}")
        self.btn_load_3d.setEnabled(True)
        if self._3d_widget:
            self._3d_widget.show_error(
                self.t.get('3d_unavailable', 'Model unavailable: {error}').format(error=error)
            )

    def _on_3d_per_mesh_applied(self) -> None:
        self._per_mesh_active = True
        self._per_mesh_base_image = self.image_path

    # ═══════════════════════════════════════════════════════════════════════════
    # Материальные слоты (карточки в 2D)
    # ═══════════════════════════════════════════════════════════════════════════

    def update_extra_slots(self, weapon_key: str, mode: str = '') -> None:
        """
        Сбрасывает и перенастраивает слоты при смене оружия/шапки.

        Сброс происходит ТОЛЬКО если weapon_key или mode изменились.
        Для оружий карточки появятся позже через _on_3d_multi_material.
        Для рук карточки определяются сразу из HAND_MODES (без 3D).
        """
        # Восстановление из мини-памяти уже выставило всё состояние в
        # set_3d_params/_restore_from_memory — не затираем его.
        if self._restoring_memory:
            self._restoring_memory = False
            self._weapon_key = weapon_key
            self._weapon_mode = mode
            return

        if weapon_key == self._weapon_key and mode == self._weapon_mode:
            return   # то же самое — ничего не сбрасываем

        self._weapon_key = weapon_key
        self._weapon_mode = mode

        # ── Полный сброс состояния предыдущего оружия ─────────────────────── #
        self._textures = {'red': {}, 'blu': {}}
        self._material_names = []
        self._has_blu = False
        self._active_team = 'red'
        self.image_path = None
        self.vtf_path = None
        self._gif_cache = {}
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self._custom_smd_path = None   # сменили оружие — забываем кастомную модель
        self._reset_skin_state()       # и стили оригинала
        # Сбрасываем кнопки команд
        self.btn_red.setVisible(False)
        self.btn_blu.setVisible(False)
        self.btn_red.setStyleSheet(self._team_style_on)
        self.btn_blu.setStyleSheet(self._team_style_off)
        self._stop_gif()

        from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES

        if mode in HAND_MODE_KEYS:
            # Руки — слоты известны статически
            textures = HAND_MODES.get(mode, {}).get('textures', [])
            all_names = [vtf_name for _, vtf_name in textures]
            self._set_material_slots(all_names)
        else:
            # Сбрасываем до одного слота. Карточки появятся через _on_3d_multi_material
            self._set_material_slots([])

    def update_extra_slots_spy_masks(self, mask_vtf_names: list) -> None:
        """Настраивает карточки для режима масок шпиона.

        Создаёт 9 карточек — по одной на маску каждого класса.
        Имена карточек соответствуют именам VTF файлов (mask_scout и т.д.).
        """
        from src.data.player_characters import SPY_DISGUISE_MASKS
        weapon_key = '__spy_masks__'
        mode = 'spy_masks'

        if weapon_key == self._weapon_key and mode == self._weapon_mode:
            return

        self._weapon_key = weapon_key
        self._weapon_mode = mode

        # Сброс состояния
        self._textures = {'red': {}, 'blu': {}}
        self._material_names = []
        self._has_blu = False
        self._active_team = 'red'
        self.image_path = None
        self.vtf_path = None
        self._gif_cache = {}
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self.btn_red.setVisible(False)
        self.btn_blu.setVisible(False)
        self._stop_gif()

        # Имена с красивыми подписями (class name как display_name)
        display_map = {m[1]: (m[3] if self._lang == 'ru' else m[2]) for m in SPY_DISGUISE_MASKS}
        names_with_display = [(n, display_map.get(n, n)) for n in mask_vtf_names]

        # Создаём карточки через _set_material_slots_with_display
        self._set_material_slots_with_display(names_with_display)

    def _set_material_slots_with_display(self, names_display: list) -> None:
        """Показывает карточки для пар (mat_name, display_name).
        Используется для масок шпиона где display_name = имя класса.
        """
        # Очищаем
        lay = self._cards_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._card_widgets.clear()
        self._main_card = None

        if not names_display:
            self._card_mode = False
            self._material_names = []
            self._cards_scroll.hide()
            self.preview.hide()
            self.empty_state.show()
            return

        self._card_mode = True
        self._material_names = [n for n, _ in names_display]

        for mat_name, disp_name in names_display:
            card = _ExtraSlotCard(mat_name, display_name=disp_name, parent=self._cards_bar)
            saved = self._textures['red'].get(mat_name)
            if saved and os.path.exists(saved):
                card.set_image(saved)
            card.image_changed.connect(self._on_extra_card_changed)
            lay.addWidget(card)
            self._card_widgets[mat_name] = card

        lay.addStretch()
        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    def _set_material_slots(self, names: List[str], force_cards: bool = False) -> None:
        """Показывает карточки для списка материалов (или большое превью если < 2).

        force_cards=True строит карточку даже для одного материала — нужно для
        кастомных моделей со стилями: чтобы у единственной текстуры была карточка
        с плюсиком, которую можно очистить/переопределить под каждый стиль.
        """
        # Очищаем старые виджеты
        lay = self._cards_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._card_widgets.clear()
        self._main_card = None
        self._aus_card = None

        if len(names) < 1 or (len(names) < 2 and not force_cards):
            # ── Одиночный режим ─────────────────────────────────────────────── #
            self._card_mode = False
            self._material_names = names
            self._cards_scroll.hide()
            if self.image_path and os.path.exists(self.image_path):
                self.empty_state.hide()
                self.preview.show()
            else:
                self.preview.hide()
                self.empty_state.show()
            return

        # ── Режим карточек ──────────────────────────────────────────────────── #
        self._card_mode = True
        self._material_names = list(names)

        # Для BLU команды лейбл карточки показывает BLU-имя текстуры (из QC skinfamilies),
        # а не RED-имя из SMD. Так пользователь видит реальное имя заменяемой текстуры.
        def _display(mat_name: str) -> str:
            if self._active_team == 'blu' and self._vpk_blu_name_map:
                return self._vpk_blu_name_map.get(mat_name, mat_name)
            return mat_name

        main_name = names[0]
        main_card = _ExtraSlotCard(main_name, display_name=_display(main_name),
                                   parent=self._cards_bar)
        # Восстанавливаем уже загруженную текстуру (если была)
        saved = self._resolve_card_texture(main_name)
        if saved and os.path.exists(saved):
            main_card.set_image(saved, opaque=self._is_game_texture(saved))
        elif self.image_path and os.path.exists(self.image_path):
            main_card.set_image(self.image_path)
        main_card.image_changed.connect(self._on_main_card_changed)
        lay.addWidget(main_card)
        self._main_card = main_card

        for name in names[1:]:
            card = _ExtraSlotCard(name, display_name=_display(name),
                                  parent=self._cards_bar)
            saved = self._resolve_card_texture(name)
            if saved and os.path.exists(saved):
                card.set_image(saved, opaque=self._is_game_texture(saved))
            card.image_changed.connect(self._on_extra_card_changed)
            lay.addWidget(card)
            self._card_widgets[name] = card

        # Australium — отдельный тип текстуры в конце ряда (если вариант найден)
        self._append_australium_card(lay)

        lay.addStretch()

        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    # ═══════════════════════════════════════════════════════════════════════════
    # Стили / skinfamilies (кастомная замена модели)
    # ═══════════════════════════════════════════════════════════════════════════

    def _reset_skin_state(self) -> None:
        """Убирает кнопки стилей (смена оружия / выход из кастома)."""
        self._original_skin_info = None
        self._active_skin = 0
        self._skin_overrides = {}
        self._skin_chosen = {}
        for b in self._skin_buttons:
            b.setParent(None)
            b.deleteLater()
        self._skin_buttons = []

    def _start_skin_detection(self) -> None:
        """Запускает фоновое определение стилей оригинальной модели.

        Вызывается ТОЛЬКО при загрузке кастомной модели — дефолтный путь
        (обычная игровая модель) этот код не трогает.
        """
        if not self._weapon_key or self._weapon_key == '\x00':
            return
        params = self._pending_3d_params
        misc_vpk = params[2] if params else ''
        mode = params[1] if params else (self._weapon_mode or '')
        try:
            from src.services.skin_detect_worker import SkinDetectWorker
        except Exception as exc:
            logger.debug(f"[SKIN] worker import failed: {exc}")
            return
        self._stop_worker('_skin_worker')
        w = SkinDetectWorker(
            weapon_key=self._weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk,
            lang=self._lang,
            parent=self,
        )
        w.detected.connect(self._on_skins_detected)
        w.failed.connect(lambda _e: logger.info(f"[SKIN] стили не определены: {_e}"))
        w.start()
        self._skin_worker = w

    def _on_skins_detected(self, info: dict) -> None:
        """Получили skin-info оригинала — строим полосу стилей."""
        if not info or info.get('num_skins', 0) < 2:
            # Один стиль — полоса не нужна, кастом собирается как одно-скиновый.
            self._reset_skin_state()
            return
        self._original_skin_info = info
        self._active_skin = 0
        self._skin_overrides = {0: {}}
        self._skin_chosen = {}
        # Единственная текстура → принудительно карточка, чтобы базовый стиль
        # тоже был карточкой (для единообразия переключения стилей).
        if not self._card_mode and self._material_names:
            self._set_material_slots(list(self._material_names), force_cards=True)
        self._populate_skin_bar(info)

    def _populate_skin_bar(self, info: dict) -> None:
        """Создаёт кнопки стилей в тулбаре (рядом с RED/BLU/Australium)."""
        from PySide6.QtWidgets import QPushButton
        for b in self._skin_buttons:
            b.setParent(None)
            b.deleteLater()
        self._skin_buttons = []

        roles = info.get('roles') or []
        num = info.get('num_skins', 0)
        # Вставляем перед анкером — кнопки держатся правее Australium.
        anchor_idx = self._toolbar_layout.indexOf(self._skin_anchor)
        for i in range(num):
            label = roles[i] if i < len(roles) else f"Skin {i}"
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(self.t.get('skin_style_tip', 'Model style (skinfamilies)'))
            btn.setStyleSheet(
                self._skin_btn_style_on if i == 0 else self._skin_btn_style_off
            )
            btn.clicked.connect(lambda _=False, idx=i: self._switch_skin(idx))
            self._toolbar_layout.insertWidget(anchor_idx + i, btn)
            self._skin_buttons.append(btn)

    def _switch_skin(self, idx: int) -> None:
        """Переключает активный стиль и перестраивает карточки под него."""
        if idx == self._active_skin:
            return
        if not self._original_skin_info:
            return
        self._active_skin = idx
        self._skin_overrides.setdefault(idx, {})
        for i, b in enumerate(self._skin_buttons):
            b.setStyleSheet(
                self._skin_btn_style_on if i == idx else self._skin_btn_style_off
            )
        self._rebuild_cards_for_skin(idx)

    def _rebuild_cards_for_skin(self, idx: int) -> None:
        """Полностью пересобирает полосу карточек под активный стиль.

        • Базовый стиль (0): обычные карточки всех материалов модели.
        • Доп. стиль (K>0): карточек НЕ видно. Показана кнопка «+ Добавить
          стиль» — по ней пользователь сам выбирает, какие материалы базы
          переопределить. Выбранный материал появляется отдельной карточкой
          и попадает в $texturegroup; невыбранные наследуют базу.
        """
        if idx == 0:
            # Базовый стиль — стандартная раскладка карточек.
            self._set_material_slots(list(self._material_names), force_cards=True)
            return

        # ── Вариантный стиль ────────────────────────────────────────────── #
        lay = self._cards_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._card_widgets.clear()
        self._main_card = None
        self._card_mode = True

        chosen = self._skin_chosen.setdefault(idx, set())
        overrides = self._skin_overrides.setdefault(idx, {})
        for mat in self._material_names:
            if mat not in chosen:
                continue
            card = _ExtraSlotCard(mat, display_name=mat, parent=self._cards_bar)
            ov = overrides.get(mat)
            if ov and os.path.exists(ov):
                card.set_image(ov)
            card.image_changed.connect(self._on_extra_card_changed)
            lay.addWidget(card)
            self._card_widgets[mat] = card

        # Кнопка «+ Добавить стиль» — если ещё есть материалы для добавления.
        if any(m not in chosen for m in self._material_names):
            from PySide6.QtWidgets import QPushButton
            add_btn = QPushButton(self.t.get('skin_add_style', '+ Add style'))
            add_btn.setObjectName('skin_add_btn')
            add_btn.setCursor(Qt.PointingHandCursor)
            add_btn.setFixedHeight(40)
            add_btn.setStyleSheet(
                "QPushButton#skin_add_btn { background:transparent; border:1px dashed #555;"
                " border-radius:6px; padding:10px 18px; color:#aaa; font-size:13px; }"
                " QPushButton#skin_add_btn:hover { border-color:#888; color:#ddd;"
                " background:rgba(255,255,255,0.04); }"
            )
            add_btn.clicked.connect(self._show_add_style_menu)
            lay.addWidget(add_btn)
            self._skin_add_btn = add_btn

        lay.addStretch()
        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    def _show_add_style_menu(self) -> None:
        """Меню выбора базового материала для переопределения в текущем стиле."""
        from PySide6.QtWidgets import QMenu
        idx = self._active_skin
        if idx == 0:
            return
        chosen = self._skin_chosen.setdefault(idx, set())
        available = [m for m in self._material_names if m not in chosen]
        if not available:
            return
        menu = QMenu(self)
        for mat in available:
            menu.addAction(mat, lambda _=False, m=mat: self._add_material_to_style(m))
        btn = getattr(self, '_skin_add_btn', None)
        if btn is not None:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec()

    def _add_material_to_style(self, mat: str) -> None:
        """Добавляет материал в текущий вариантный стиль (пустая карточка)."""
        idx = self._active_skin
        if idx == 0:
            return
        self._skin_chosen.setdefault(idx, set()).add(mat)
        self._rebuild_cards_for_skin(idx)

    def get_skin_overrides(self) -> Dict[int, Dict[str, str]]:
        """Для сборки: {skin_idx: {mat_name: texture_path}} (без скина 0).

        Скин 0 — база, в результат не входит. Возвращаем только доп. стили с
        реально заполненными текстурами. Пустой dict → одно-скиновая сборка.
        """
        if not self._original_skin_info:
            return {}
        result: Dict[int, Dict[str, str]] = {}
        for skin_idx, mats in self._skin_overrides.items():
            if skin_idx == 0:
                continue
            cleaned = {m: p for m, p in mats.items() if p and os.path.exists(p)}
            if cleaned:
                result[skin_idx] = cleaned
        return result

    def get_skin_build_data(self) -> Optional[dict]:
        """Данные для сборки $texturegroup кастомной модели.

        Returns None, если стилей нет (одно-скиновая сборка — генерация группы
        не нужна). Иначе:
            {
              'mesh_materials': [имена материалов меша, порядок = skin 0],
              'tg_overrides':   {skin_idx: {mat: variant_name}},  # для группы
              'variant_files':  {variant_name: texture_path},     # для VTF/VMT
            }
        Имя варианта = <материал>_<суффикс роли> (bloody/clean/… или skinN).
        Регистр имён сохраняется как в карточках/SMD — чтобы $texturegroup,
        имена VTF и материал модели совпадали.
        """
        import re as _re
        ov = self.get_skin_overrides()   # {skin: {mat: path}}
        if not ov:
            return None
        roles = (self._original_skin_info or {}).get('roles', [])

        def _suffix(idx: int) -> str:
            label = roles[idx] if idx < len(roles) else ''
            s = _re.sub(r'[^a-z0-9]+', '_', label.strip().lower()).strip('_')
            return s or f'skin{idx}'

        tg_overrides: Dict[int, Dict[str, str]] = {}
        variant_files: Dict[str, str] = {}
        for skin_idx, mats in ov.items():
            suf = _suffix(skin_idx)
            for mat, path in mats.items():
                vname = f"{mat}_{suf}"
                tg_overrides.setdefault(skin_idx, {})[mat] = vname
                variant_files[vname] = path
        if not tg_overrides:
            return None
        return {
            'mesh_materials': list(self._material_names),
            'tg_overrides': tg_overrides,
            'variant_files': variant_files,
        }

    def _on_main_card_changed(self, mat_name: str, path: str) -> None:
        """Пользователь сменил или сбросил текстуру в главной карточке."""
        # Если активен Australium — текстура идёт в его отдельный слот,
        # не затирая обычную/командную.
        if self._australium_active:
            self._set_australium_user_tex(path or None)
            return
        self._stop_gif()
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self.vtf_path = None

        if path:
            # Загрузка новой текстуры
            self.image_path = path
            self._store_texture(mat_name, path)
            self.update_info_summary()
            if self.is_3d_mode() and self._3d_widget and not self._crithit_mode:
                from PySide6.QtCore import QTimer
                if path.lower().endswith('.gif'):
                    QTimer.singleShot(300, lambda p=path, m=mat_name: self._apply_gif_to_3d(p, m))
                else:
                    QTimer.singleShot(300, lambda p=path, m=mat_name: self._3d_widget.apply_material_map({m: p}))
            elif self.is_3d_mode() and self._crithit_mode and self._3d_widget:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(300, lambda p=path: self._3d_widget.update_crithit_texture(p))
        else:
            # Сброс текстуры (нажат ×) — удаляем и восстанавливаем оригинал в 3D.
            # Вызываем restore независимо от текущего режима (2D или 3D) — иначе
            # при переключении обратно в 3D старая текстура остаётся на модели.
            self.image_path = None
            self._store_texture(mat_name, None)
            self.update_info_summary()
            if self._3d_widget and self._3d_available:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(300, lambda: self._restore_team_textures_3d(self._active_team))

    def _is_neutral_texture(self, mat_name: str) -> bool:
        """True если текстура не относится к конкретной команде (RED/BLU).

        Нейтральные текстуры (sniper_lens, c_arrow, eyeball_r и т.п.)
        одинаковы для обеих команд — их нужно хранить в обоих словарях
        чтобы карточка не пропадала при переключении команды.
        """
        if not self._vpk_blu_name_map:
            return True   # нет маппинга → считаем нейтральной
        return (mat_name not in self._vpk_blu_name_map and
                mat_name not in self._vpk_blu_name_map.values())

    def _store_texture(self, mat_name: str, path: Optional[str]) -> None:
        """Сохраняет текстуру в _textures.

        Нейтральные текстуры записываются в ОБЕ команды,
        командные — только в активную.
        """
        # ── Стили: на вариантном стиле (skin > 0) текстура принадлежит этому
        # стилю, а не команде — пишем в _skin_overrides, _textures не трогаем. #
        if self._original_skin_info and self._active_skin != 0:
            slot = self._skin_overrides.setdefault(self._active_skin, {})
            if path:
                slot[mat_name] = path
            else:
                slot.pop(mat_name, None)
            return

        if path:
            self._textures.setdefault(self._active_team, {})[mat_name] = path
            if self._is_neutral_texture(mat_name):
                other = 'blu' if self._active_team == 'red' else 'red'
                self._textures.setdefault(other, {})[mat_name] = path
                logger.debug(f"[neutral tex] '{mat_name}' → both teams: {path}")
            else:
                logger.debug(f"[team tex] '{mat_name}' → {self._active_team} only: {path}")
        else:
            self._textures.get(self._active_team, {}).pop(mat_name, None)
            if self._is_neutral_texture(mat_name):
                other = 'blu' if self._active_team == 'red' else 'red'
                self._textures.get(other, {}).pop(mat_name, None)

    def _on_extra_card_changed(self, mat_name: str, path: str) -> None:
        """Пользователь сменил или сбросил текстуру в карточке доп. слота."""
        if path:
            self._store_texture(mat_name, path)
            if self.is_3d_mode() and self._3d_widget:
                from PySide6.QtCore import QTimer
                if path.lower().endswith('.gif'):
                    QTimer.singleShot(300, lambda p=path, m=mat_name: self._apply_gif_to_3d(p, m))
                else:
                    QTimer.singleShot(300, lambda p=path, m=mat_name: self._3d_widget.apply_material_map({m: p}))
        else:
            # Сброс — удаляем из обеих команд если нейтральная.
            self._store_texture(mat_name, None)
            if self._3d_widget and self._3d_available:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(300, lambda: self._restore_team_textures_3d(self._active_team))

    def get_slot_image_paths(self) -> dict:
        """Возвращает {material_name: path} для всех заполненных слотов.

        Для каждого слота берётся первая найденная текстура в порядке:
          активная команда → RED → BLU.
        Позволяет начать сборку с любой загруженной текстуры.
        """
        result: dict = {}
        for team in _team_priority(self._active_team):
            for k, v in self._textures.get(team, {}).items():
                # SINGLE_TEX_KEY — это главная текстура (идёт в сборку через
                # from_path), а не именованный материал. Пропускаем, иначе в VPK
                # появятся мусорные __single__.vmt / __single__.vtf.
                if k == SINGLE_TEX_KEY:
                    continue
                if k not in result and v and os.path.exists(v):
                    result[k] = v
        return result

    def load_image(self, path: str) -> None:
        """Загружает изображение (или GIF) в 2D Preview."""
        # Australium активен — грузим в его отдельный слот, не трогая обычную.
        if self._australium_active:
            self._set_australium_user_tex(path or None)
            return
        self._stop_gif()
        if path != self._per_mesh_base_image:
            self._per_mesh_active = False
            self._per_mesh_base_image = None

        self.image_path = path
        self.vtf_path = None

        # Сохраняем под активной командой
        key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
        self._textures.setdefault(self._active_team, {})[key] = path

        if self._card_mode and self._main_card is not None:
            self._main_card.set_image(path)
        else:
            self._show_image_in_preview(path)

        # Обновляем 3D если видно
        if self.is_3d_mode() and self._3d_available and self._3d_widget \
                and not self._from_3d_drop:
            from PySide6.QtCore import QTimer
            if self._crithit_mode:
                QTimer.singleShot(300, lambda p=path: self._3d_widget.update_crithit_texture(p))
            elif self._card_mode and self._material_names:
                mat = self._material_names[0]
                if path.lower().endswith('.gif'):
                    QTimer.singleShot(300, lambda p=path, m=mat: self._apply_gif_to_3d(p, m))
                else:
                    QTimer.singleShot(300, lambda p=path, m=mat: self._3d_widget.apply_material_map({m: p}))
            else:
                QTimer.singleShot(300, lambda p=path: self._apply_image_to_3d(p))

        self.update_info_summary()

    def load_vtf(self, path: str) -> None:
        """Загружает VTF файл и отображает первый кадр."""
        if not os.path.exists(path):
            return
        self.vtf_path = path
        self.image_path = None
        png_for_3d: Optional[str] = None
        rendered = False

        try:
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image
            from PySide6.QtGui import QImage

            rgba, w, h = VTFLib.read_vtf_as_rgba(path)
            qimg = QImage(rgba, w, h, w * 4, QImage.Format_RGBA8888)
            if not qimg.isNull():
                rendered = True
                png_for_3d = str(get_temp_file_path(prefix='tf2_3d_', suffix='.png'))
                Image.frombytes("RGBA", (w, h), rgba).save(png_for_3d)
                self.image_path = png_for_3d

                # Сохраняем под активной командой
                key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
                self._textures.setdefault(self._active_team, {})[key] = png_for_3d

                if self._card_mode and self._main_card:
                    self._main_card.set_image(png_for_3d)
                else:
                    self.empty_state.hide()
                    self.preview.show()
                    self.preview.clear()
                    self.preview.setStyleSheet(self._preview_style)
                    pw = max(self.preview.width(), 600)
                    self.preview.setPixmap(
                        QPixmap.fromImage(qimg).scaled(pw, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
        except Exception as e:
            logger.warning(f"VTF рендер: {e}")

        if not rendered and not (self._card_mode and self._main_card):
            self.empty_state.hide()
            self.preview.show()
            self.preview.clear()
            self.preview.setStyleSheet(self._preview_style)
            self.preview.setText(f"VTF: {os.path.basename(path)}")
            self.preview.setStyleSheet(
                self._preview_style + "QLabel { color:#ccc; font-size:14px; }"
            )
            self.preview.setAlignment(Qt.AlignCenter)

        if png_for_3d and self._3d_available and self._3d_widget and self.is_3d_mode():
            if self._crithit_mode:
                self._3d_widget.update_crithit_texture(png_for_3d)
            elif self._card_mode and self._material_names:
                self._3d_widget.apply_material_map({self._material_names[0]: png_for_3d})
            else:
                self._3d_widget.update_texture_file(png_for_3d)

        self.update_info_summary()

    def get_vtf_path(self) -> Optional[str]:
        return self.vtf_path

    def get_red_image_path(self) -> Optional[str]:
        """Возвращает путь к RED текстуре для сборки.

        НЕ делает fallback на BLU — чтобы не подставлять BLU-текстуру как
        основную (RED) в BuildWorker.

        self.image_path используется как fallback только когда активна RED
        команда: в BLU-режиме он уже содержит BLU-текстуру (обновляется в
        _restore_team_textures_2d при переключении команды).

        Возвращает None если RED не загружена → build_vpk поставит sentinel
        и покажет диалог выбора.
        """
        key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
        p = self._textures.get('red', {}).get(key)
        if p and os.path.exists(p):
            return p
        # image_path как fallback только в RED-режиме (в BLU он содержит BLU-текстуру)
        if self._active_team != 'blu' and self.image_path and os.path.exists(self.image_path):
            return self.image_path
        return None

    def _is_game_texture(self, path: Optional[str]) -> bool:
        """
        True, если path — извлечённая из игры текстура (VPK-кадр команды /
        вариант Australium), а не пользовательская. Для таких в 2D-превью
        отбрасываем альфу (она у VTF — маска бликов, а не прозрачность).
        """
        if not path:
            return False
        if path == self._australium_frame:
            return True
        if path in self._red_frames or path in self._blu_frames:
            return True
        if (path in self._vpk_red_tex_map.values()
                or path in self._vpk_blu_tex_map.values()):
            return True
        return False

    def _resolve_card_texture(self, mat_name: str) -> Optional[str]:
        """Возвращает путь к текстуре для отображения в карточке при текущей команде.

        Для нейтральных текстур (не относящихся ни к RED ни к BLU команде,
        например sniper_lens, c_arrow) — показываем текстуру из любой команды
        где она была загружена, чтобы она не исчезала при переключении команды.

        Для командных текстур (есть в _vpk_blu_name_map) — строго активная команда.
        """
        # ── Стили (кастомная модель) ─────────────────────────────────────── #
        # Вариантный стиль (skin > 0) показывает ТОЛЬКО свою переопределённую
        # текстуру — без наследования базы/игры. Нет переопределения → None
        # (пустая карточка с плюсиком, чтобы пользователь выбрал сам).
        # Базовый стиль (skin 0) идёт по обычному пути ниже.
        if self._original_skin_info and self._active_skin != 0:
            sp = self._skin_overrides.get(self._active_skin, {}).get(mat_name)
            return sp if (sp and os.path.exists(sp)) else None

        active = self._active_team
        # Сначала ищем в активной команде
        p = self._textures.get(active, {}).get(mat_name)
        if p and os.path.exists(p):
            return p

        # Нейтральная текстура: не RED-ключ и не BLU-значение в маппинге
        is_team_specific = (
            mat_name in self._vpk_blu_name_map or
            mat_name in self._vpk_blu_name_map.values()
        ) if self._vpk_blu_name_map else False

        if not is_team_specific:
            # Ищем в другой команде тоже
            other = 'blu' if active == 'red' else 'red'
            p = self._textures.get(other, {}).get(mat_name)
            if p and os.path.exists(p):
                return p

        # Fallback: игровой оригинал текущей команды из VPK (превью того, что
        # заменяем). Так при переключении RED↔BLU карточка показывает текстуру
        # соответствующей команды, даже если пользователь свою не загружал.
        # Карты _vpk_*_tex_map ключуются по RED-имени материала — как и карточки.
        vpk_map = self._vpk_red_tex_map if active == 'red' else self._vpk_blu_tex_map
        g = vpk_map.get(mat_name)
        if g and os.path.exists(g):
            return g

        # Fallback для ГЛАВНОГО материала: если per-material карты команды нет
        # (BLU пришёл одним кадром через _blu_frames, как у некоторых шапок),
        # показываем кадр команды — так же, как 3D применяет его глобально.
        if self._material_names and mat_name == self._material_names[0]:
            frames = self._blu_frames if active == 'blu' else self._red_frames
            if frames and os.path.exists(frames[0]):
                return frames[0]

        return None

    def get_uploaded_texture_for_mat(self, mat_name: str) -> Optional[str]:
        """Возвращает путь к уже загруженной пользователем текстуре для данного
        материала, или None если не загружена.

        Логика (важно — не смешиваем RED и BLU):

        1. Если mat_name — RED-имя (ключ в _vpk_blu_name_map, напр. 'medic_head_red'):
           → смотрим ТОЛЬКО в _textures['red']. Не fallback-аем на BLU.
           Это гарантирует, что build спросит диалог когда RED не загружена,
           а не молча подставит BLU-текстуру.

        2. Если mat_name — BLU-имя (значение в _vpk_blu_name_map, напр. 'medic_head_blue'):
           → обратный поиск: BLU-имя → RED-ключ → _textures['blu'][RED-ключ].
           (Карточки хранят BLU-текстуры под RED-ключами.)

        3. Иначе (оружие/шапка без явного маппинга, руки):
           → прямой поиск в обеих командах.
        """
        if self._vpk_blu_name_map:
            # Случай 1: RED-имя (ключ в маппинге) → только _textures['red']
            if mat_name in self._vpk_blu_name_map:
                p = self._textures.get('red', {}).get(mat_name)
                return p if (p and os.path.exists(p)) else None

            # Случай 2: BLU-имя (значение в маппинге) → обратный поиск
            for red_key, blu_name in self._vpk_blu_name_map.items():
                if blu_name == mat_name:
                    p = self._textures.get('blu', {}).get(red_key)
                    return p if (p and os.path.exists(p)) else None

            # Случай 3: нейтральная текстура — не RED и не BLU в маппинге
            # (например sniper_lens, c_arrow, eyeball_r и т.п.).
            # Проверяем ОБЕ команды — текстура могла быть загружена в любой.
            for _team in ('red', 'blu'):
                p = self._textures.get(_team, {}).get(mat_name)
                if p and os.path.exists(p):
                    return p
            return None

        # Случай 4: маппинг пуст (одноматериальное оружие / 3D не загружалась).
        # Нейтральные текстуры ищем в обеих командах по прямому ключу.
        for _team in ('red', 'blu'):
            p = self._textures.get(_team, {}).get(mat_name)
            if p and os.path.exists(p):
                return p
        # Fallback: сборка спрашивает по BLU-имени материала ({weapon}_blue),
        # а у одноматериального оружия BLU-текстура хранится под ГЛАВНЫМ ключом.
        # Если имя похоже на BLU-вариант и BLU-текстура загружена — отдаём её,
        # чтобы сборка не переспрашивала уже загруженную текстуру голубой команды.
        if mat_name.lower().endswith(('_blue', '_blu')):
            blu = self.get_blu_image_path()
            if blu:
                return blu
        return None

    def get_blu_image_path(self) -> Optional[str]:
        """Возвращает путь к пользовательской BLU текстуре (главный слот) или None."""
        blu = self._textures.get('blu', {})
        key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
        p = blu.get(key)
        if p and os.path.exists(p):
            return p
        for p in blu.values():
            if p and os.path.exists(p):
                return p
        return None

    # ── Вспомогательные методы 2D ─────────────────────────────────────────────

    def _show_image_in_preview(self, path: str) -> None:
        """Показывает изображение в большом превью (не card_mode)."""
        from PySide6.QtCore import QTimer
        self.empty_state.hide()
        self.preview.show()
        self.preview.clear()
        self.preview.setStyleSheet(self._preview_style)
        self.preview.updateGeometry()

        opaque = self._is_game_texture(path)
        if path.lower().endswith('.gif'):
            def _try_gif():
                if self._gif_movie is not None:
                    return
                w = max(self.preview.width(), self.width(), 600)
                if not self._start_gif(path, w):
                    pix = _load_pixmap(path, opaque).scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.preview.setPixmap(pix)
            QTimer.singleShot(50, _try_gif)
        else:
            def _scale():
                w = max(self.preview.width(), self.width(), 600)
                pix = _load_pixmap(path, opaque).scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview.setPixmap(pix)
            QTimer.singleShot(50, _scale)

    def _clear_preview_label(self) -> None:
        self.preview.clear()
        self.preview.hide()
        self.empty_state.show()

    # ═══════════════════════════════════════════════════════════════════════════
    # Роутинг текстур в 3D
    # ═══════════════════════════════════════════════════════════════════════════

    def _apply_image_to_3d(self, path: str) -> None:
        """Применяет одиночное изображение к 3D модели (глобально)."""
        if not self._3d_widget or not self._3d_available or not os.path.exists(path):
            return
        if path.lower().endswith('.gif'):
            self._apply_gif_to_3d(path)
        else:
            self._3d_widget.update_texture_file(path)

    def _apply_gif_to_3d(self, gif_path: str, mat_name: str = '') -> None:
        """Декодирует GIF и запускает покадровую анимацию в 3D viewer.

        Результат кэшируется — повторные переключения 2D↔3D не декодируют заново.
        """
        if not self._3d_widget or not self._3d_available:
            return

        # Кэш
        cached = self._gif_cache.get(gif_path)
        if cached:
            frames, fps = cached
            if frames and all(os.path.exists(p) for p in frames):
                self._3d_widget.update_animated_texture_files(frames, fps, mat_name)
                return
            del self._gif_cache[gif_path]

        try:
            from PIL import Image

            gif = Image.open(gif_path)
            n = getattr(gif, 'n_frames', 1)
            if n <= 1:
                if mat_name:
                    self._3d_widget.apply_material_map({mat_name: gif_path})
                else:
                    self._3d_widget.update_texture_file(gif_path)
                return

            duration = gif.info.get('duration', 100) or 100
            fps = 1000.0 / duration
            frames = []
            for i in range(n):
                gif.seek(i)
                tmp = str(get_temp_file_path(prefix=f'tf2_gif{i}_', suffix='.png'))
                gif.convert('RGBA').save(tmp)
                frames.append(tmp)

            self._gif_cache[gif_path] = (frames, fps)
            self._3d_widget.update_animated_texture_files(frames, fps, mat_name)
        except Exception as exc:
            logger.warning(f"GIF→3D: {exc}")
            if mat_name:
                self._3d_widget.apply_material_map({mat_name: gif_path})
            else:
                self._3d_widget.update_texture_file(gif_path)

    # ═══════════════════════════════════════════════════════════════════════════
    # Дроп из 3D в 2D
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_3d_texture_dropped(self, data_url: str, material_name: str = '') -> None:
        """Пользователь перетащил текстуру в 3D viewer."""
        if not data_url:
            return
        try:
            import base64 as _b64, tempfile
            if ',' not in data_url:
                return
            header, b64data = data_url.split(',', 1)
            mime = 'image/png'
            if ':' in header and ';' in header:
                mime = header.split(':')[1].split(';')[0]
            ext_map = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif',
                       'image/webp': '.webp', 'image/bmp': '.bmp'}
            ext = ext_map.get(mime, '.png')
            img_bytes = _b64.b64decode(b64data)
            tmp = str(get_temp_file_path(prefix='tf2_3ddrop_', suffix=ext))
            with open(tmp, 'wb') as f:
                f.write(img_bytes)

            # ── Режим масок шпиона: роутим к АКТИВНОМУ классу маски ────────── #
            # В 3D всегда один материал "mask_spy" (имя из spy_mask.smd),
            # но нам нужно направить текстуру в слот текущего активного класса.
            if self._spy_mask_mode and self._active_spy_mask:
                from src.data.player_characters import SPY_DISGUISE_MASKS
                vtf_name = next(
                    (m[1] for m in SPY_DISGUISE_MASKS if m[0] == self._active_spy_mask),
                    None
                )
                if vtf_name:
                    card = self._card_widgets.get(vtf_name)
                    if card:
                        card.set_image(tmp)
                        card.image_changed.emit(vtf_name, tmp)
                    else:
                        self._textures.setdefault('red', {})[vtf_name] = tmp
                        self._on_extra_card_changed(vtf_name, tmp)
                return

            _norm = material_name.lower() if material_name else ''
            _extra_lc = {n.lower(): n for n in (
                self._material_names[1:] if len(self._material_names) > 1 else []
            )}
            _main_lc = (self._material_names[0].lower() if self._material_names else '')

            routed_extra = None
            if _norm and _norm in _extra_lc:
                routed_extra = _extra_lc[_norm]
            elif _norm:
                for lc, orig in _extra_lc.items():
                    if _norm.startswith(lc):
                        routed_extra = orig
                        break

            if routed_extra is not None:
                card = self._card_widgets.get(routed_extra)
                if card:
                    card.set_image(tmp)
                self._textures.setdefault(self._active_team, {})[routed_extra] = tmp
            else:
                self._from_3d_drop = True
                try:
                    self.load_image(tmp)
                finally:
                    self._from_3d_drop = False
        except Exception as exc:
            logger.warning(f"3D texture drop: {exc}")

    # ═══════════════════════════════════════════════════════════════════════════
    # CritHIT режим
    # ═══════════════════════════════════════════════════════════════════════════

    def _render_crithit_scene(self) -> None:
        if not self._3d_widget or not self._3d_available:
            return
        crit_path = self.image_path or ''
        class_name = self._crithit_class
        custom_model, model_tex = self._find_crithit_custom_model(class_name)

        if model_tex.lower().endswith('.vtf'):
            model_tex = self._convert_model_vtf(model_tex)

        if custom_model:
            if custom_model.lower().endswith('.smd'):
                import tempfile
                from src.services.smd_to_obj_service import SmdToObjService
                self._3d_widget.show_loading("Converting custom model...")
                tmp = tempfile.mkdtemp(prefix="tf2_crithit_")
                obj = os.path.join(tmp, "model.obj")
                ok = SmdToObjService.convert(custom_model, obj)
                if ok and os.path.exists(obj):
                    self._3d_widget.load_crithit_scene_with_model(obj, crit_path, model_tex)
                else:
                    self._3d_widget.load_crithit_scene(crit_path, model_tex)
            else:
                self._3d_widget.load_crithit_scene_with_model(custom_model, crit_path, model_tex)
        else:
            self._3d_widget.load_crithit_scene(crit_path, model_tex)

    @staticmethod
    def _find_crithit_custom_model(class_name: str = 'soldier') -> tuple:
        here = os.path.dirname(os.path.abspath(__file__))
        model_root = os.path.join(os.path.dirname(os.path.dirname(here)), "tools", "Model")
        MODEL_EXTS = ('.obj', '.smd')
        TEX_EXTS   = ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.vtf', '.webp')

        def _scan(folder):
            if not os.path.isdir(folder):
                return '', ''
            m = t = ''
            for name in sorted(os.listdir(folder)):
                if name.startswith('.'):
                    continue
                lo, full = name.lower(), os.path.join(folder, name)
                if not m and lo.endswith(MODEL_EXTS): m = full
                if not t and lo.endswith(TEX_EXTS):   t = full
            return m, t

        m, t = _scan(os.path.join(model_root, class_name.lower()))
        if m:
            return m, t
        return _scan(model_root)

    @staticmethod
    def _convert_model_vtf(vtf_path: str) -> str:
        try:
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image
            rgba, w, h = VTFLib.read_vtf_as_rgba(vtf_path)
            img = Image.frombytes("RGBA", (w, h), rgba)
            png = str(get_temp_file_path(prefix='tf2_model_tex_', suffix='.png'))
            img.save(png)
            return png
        except Exception as exc:
            logger.warning(f"VTF→PNG модели: {exc}")
            return ''

    # ═══════════════════════════════════════════════════════════════════════════
    # VPK мод
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_load_vpk_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('3d_select_vpk', 'Select VPK mod'),
            "",
            "VPK Files (*.vpk);;All Files (*)",
        )
        if not path:
            return
        self._loaded_vpk_mod_path = path
        self.vpk_mod_loaded.emit(path)
        self._start_vpk_mod_worker(path)

    # ═══════════════════════════════════════════════════════════════════════════
    # Custom SMD
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_replace_model_clicked(self) -> None:
        """Кнопка 🔄: выбрать свою модель и сразу показать её в 3D + карточки.
        Не требует предварительной загрузки оригинала: данные оригинала (кости/
        материалы) сборка тянет из игры сама. Замена включается автоматически —
        сборка видит загруженную модель через get_custom_smd_path().

        ВАЖНО: НЕ ставим self._custom_smd_mode — иначе кнопка-куб 🧊
        (_on_load_3d_clicked) начнёт грузить кастомную SMD вместо игровой модели.
        Эта кнопка полностью независима: грузит SMD напрямую, путь хранится в
        _custom_smd_path (его читает сборка)."""
        if not self._3d_available or not self._3d_widget:
            return
        if not self.is_3d_mode():
            self._switch_to_3d()
        self._load_custom_smd_via_dialog()

    def _ask_model_ready(self, mat_names: list) -> bool:
        """Спрашивает, готова ли модель (свои материалы) или это замена геометрии.

        Returns True — сохранять материалы пользователя (многотекстурная/готовая
        модель); False — заменить только геометрию, адаптировать под игровой
        материал (старое поведение для простых решей одной текстуры).
        """
        from PySide6.QtWidgets import QMessageBox
        from src.data.material_filter import filter_editable
        n_editable = len(filter_editable(mat_names or []))
        recommend_keep = n_editable > 1   # >1 материала → почти наверняка «готовая»

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(self.t.get('model_ready_title', 'Model type'))
        box.setText(self.t.get(
            'model_ready_text',
            'Is this model already game-ready (its own materials, rigged to the TF2 skeleton)?'
        ))
        info = (
            'Yes — keep the model\'s own materials as-is (multi-texture / ready models).\n'
            'No — replace geometry only and use the game texture (single material).'
            if self._lang != 'ru' else
            'Да — сохранить материалы модели как есть (многотекстурные / готовые модели).\n'
            'Нет — заменить только геометрию и использовать игровую текстуру (один материал).'
        )
        box.setInformativeText(info)
        yes = box.addButton(
            self.t.get('model_ready_yes', 'Yes, keep materials'), QMessageBox.YesRole
        )
        no = box.addButton(
            self.t.get('model_ready_no', 'No, geometry only'), QMessageBox.NoRole
        )
        box.setDefaultButton(yes if recommend_keep else no)
        box.exec()
        keep = box.clickedButton() is yes
        logger.info(
            f"[CUSTOM MODEL] mat_names={mat_names} editable={n_editable} "
            f"→ keep_user_materials={keep}"
        )
        return keep

    def get_custom_keep_materials(self) -> bool:
        """Для сборки: сохранять ли материалы пользовательской модели."""
        return self._custom_keep_materials

    def _load_custom_smd_via_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('3d_select_smd_title', 'Select SMD Model File'),
            "",
            "SMD Files (*.smd);;All Files (*)",
        )
        if path:
            self._load_custom_smd_file(path)

    def _load_custom_smd_file(self, smd_path: str) -> None:
        if not self._3d_available or not self._3d_widget:
            return
        import tempfile
        from src.services.smd_to_obj_service import SmdToObjService
        from src.data.material_filter import filter_editable

        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_converting_smd', 'Converting SMD...'))
        try:
            tmp_dir = tempfile.mkdtemp(prefix="tf2_smd_preview_")
            obj_path = os.path.join(tmp_dir, "model.obj")
            ok, mat_names = SmdToObjService.convert(smd_path, obj_path)
            if not ok or not os.path.exists(obj_path):
                self._3d_widget.show_error(self.t.get('3d_error_convert', 'SMD conversion error'))
                return

            # Запоминаем путь — чтобы сборка переиспользовала ту же модель,
            # а не просила выбрать SMD повторно.
            self._custom_smd_path = smd_path

            # Спрашиваем тип модели: «готова» (свои материалы) или «замена
            # геометрии» (игровой материал). По умолчанию рекомендуем по числу
            # материалов: >1 → почти наверняка модель со своими материалами.
            self._custom_keep_materials = self._ask_model_ready(mat_names or [])
            self._reset_skin_state()

            if self._custom_keep_materials:
                # ── «Готовая» модель: карточки по материалам САМОГО SMD ──────
                # Имена из меша пользователя, служебные (глаза/sheen) отфильтрованы.
                self._3d_widget.load_model_files(obj_path, self.image_path or '')
                editable = filter_editable(mat_names or [])
                if len(editable) > 1:
                    self._set_material_slots(editable)
                elif editable:
                    self._material_names = editable
                    self._card_mode = False
                logger.info(f"[CUSTOM MODEL keep] материалы из SMD → карточки: {editable}")
                # Стили (skinfamilies) оригинала — для переопределения под свои текстуры.
                self._start_skin_detection()
            else:
                # ── «Только геометрия»: карточки из QC игровой модели ─────────
                # Показываем ГЕОМЕТРИЮ ПОЛЬЗОВАТЕЛЯ, но карточки/текстуры берём из
                # QC игровой модели (там всё сводится к игровым текстурам). Воркер
                # извлекает их в фоне, НЕ перезагружая геометрию на оригинальную.
                logger.info("[CUSTOM MODEL geometry-only] геометрия пользователя + карточки из QC")
                self._3d_widget.load_model_files(obj_path, self.image_path or '')
                if self._pending_3d_params:
                    self._start_qc_cards_worker()
        except Exception as exc:
            logger.error(f"Custom SMD load: {exc}", exc_info=True)
            if self._3d_widget:
                self._3d_widget.show_error(self.t.get('3d_error_load', 'Model load error'))
        finally:
            self.btn_load_3d.setEnabled(True)

    # ═══════════════════════════════════════════════════════════════════════════
    # GIF helpers
    # ═══════════════════════════════════════════════════════════════════════════

    def _stop_gif(self) -> None:
        if self._gif_movie is not None:
            self._gif_movie.stop()
            self.preview.setMovie(None)
            self._gif_movie.deleteLater()
            self._gif_movie = None
        self._gif_orig_size = None

    def _start_gif(self, path: str, preview_width: int) -> bool:
        from PySide6.QtGui import QMovie, QImageReader
        reader = QImageReader(path)
        orig = reader.size()
        if not orig.isValid() or orig.width() <= 0:
            return False
        movie = QMovie(path)
        if not movie.isValid():
            movie.deleteLater()
            return False
        self._gif_orig_size = orig
        movie.setScaledSize(orig.scaled(preview_width, 500, Qt.KeepAspectRatio))
        self._gif_movie = movie
        self.preview.setMovie(movie)
        movie.start()
        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # Сброс командных VPK-данных
    # ═══════════════════════════════════════════════════════════════════════════

    def _reset_team_vpk_state(self) -> None:
        """Сбрасывает VPK-кадры команд и скрывает кнопки переключения."""
        self._red_frames = []
        self._blu_frames = []
        self._team_framerate = 0.0
        self._vpk_red_tex_map = {}
        self._vpk_blu_tex_map = {}
        self._vpk_blu_name_map = {}
        self._active_team = 'red'   # сброс синхронизируем со стилями кнопок
        if hasattr(self, 'btn_red'):
            self.btn_red.setVisible(False)
            self.btn_red.setStyleSheet(self._team_style_on)
        if hasattr(self, 'btn_blu'):
            self.btn_blu.setVisible(False)
            self.btn_blu.setStyleSheet(self._team_style_off)
        # Сбрасываем Australium (кнопку и карточку-тип)
        self._australium_frame = None
        self._australium_active = False
        self._australium_user_tex = None
        self._australium_mat_name = None
        if hasattr(self, 'btn_aus'):
            self.btn_aus.setVisible(False)
            self.btn_aus.setStyleSheet(self._aus_style_off)
        if self._aus_card is not None:
            self._aus_card.setParent(None)
            self._aus_card.deleteLater()
            self._aus_card = None

    # ═══════════════════════════════════════════════════════════════════════════
    # Drag & Drop (в 2D область)
    # ═══════════════════════════════════════════════════════════════════════════

    def browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('open_dialog_title', 'Select file'),
            "",
            f"{self.t.get('images_filter', 'Images')} "
            "(*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp);;VTF Files (*.vtf);;All Files (*.*)",
        )
        if path:
            if self._is_vtf(path):
                self.load_vtf(path)
            elif self._is_image(path):
                self.load_image(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            fp = event.mimeData().urls()[0].toLocalFile()
            if self._is_image(fp) or self._is_vtf(fp):
                event.accept()
                return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            fp = event.mimeData().urls()[0].toLocalFile()
            if self._is_vtf(fp):
                self.load_vtf(fp)
                event.accept()
                return
            if self._is_image(fp):
                self.load_image(fp)
                event.accept()
                return
        event.ignore()

    @staticmethod
    def _is_image(fp: str) -> bool:
        return any(fp.lower().endswith(e)
                   for e in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp'))

    @staticmethod
    def _is_vtf(fp: str) -> bool:
        return fp.lower().endswith('.vtf')

    # ── Совместимость с is_image_file / is_vtf_file ───────────────────────────
    def update_info_summary(self) -> None:
        if hasattr(self.parent, 'settings_panel'):
            s = self.parent.settings_panel.get_settings()
            sz = s.get('size', (512, 512))
            self.info_resolution.setText(f"{self.t['info_resolution']} {sz[0]}x{sz[1]}")
            self.info_format.setText(f"{self.t['info_format']} {s.get('format', 'DXT1')}")
            flags = s.get('flags', [])
            self.info_flags.setText(
                f"{self.t['info_flags']} {', '.join(flags)}" if flags else self.t['info_flags_none']
            )
            fn = s.get('filename', '')
            self.info_filename.setText(
                f"{self.t['info_filename']} {fn}" if fn else self.t['info_filename_none']
            )
        else:
            self.info_resolution.setText(f"{self.t['info_resolution']} -")
            self.info_format.setText(f"{self.t['info_format']} -")
            self.info_flags.setText(self.t['info_flags_none'])
            self.info_filename.setText(self.t['info_filename_none'])

    # ═══════════════════════════════════════════════════════════════════════════
    # Language
    # ═══════════════════════════════════════════════════════════════════════════

    def update_language(self, t: dict, lang: str = 'en') -> None:
        self.t = t
        self._lang = lang
        self.empty_text.setText(t['drag_text'])
        self.select_file_button.setText(t['select_file_btn'])
        self.info_title.setText(t['info_title'])
        if self.info_summary.isVisible():
            self.update_info_summary()
        self.btn_load_3d.setToolTip(t.get('3d_load_model_tip', 'Load 3D model'))
        self.btn_load_vpk.setToolTip(t.get('3d_load_vpk_tip', 'Load VPK mod for 3D Preview'))
        self.btn_red.setToolTip(t.get('3d_team_red_tip', 'RED team texture'))
        self.btn_blu.setToolTip(t.get('3d_team_blu_tip', 'BLU team texture'))
        if self._3d_widget:
            self._3d_widget.set_language(lang)

    # ═══════════════════════════════════════════════════════════════════════════
    # Resize
    # ═══════════════════════════════════════════════════════════════════════════

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.preview.isVisible():
            return
        from PySide6.QtCore import QTimer

        if self._gif_movie is not None and self._gif_orig_size is not None:
            def _resize_gif():
                w = max(self.preview.width(), self.width(), 600)
                self._gif_movie.setScaledSize(
                    self._gif_orig_size.scaled(w, 500, Qt.KeepAspectRatio)
                )
            QTimer.singleShot(50, _resize_gif)
        elif self.image_path and os.path.exists(self.image_path):
            def _rescale():
                w = max(self.preview.width(), self.width(), 600)
                pix = QPixmap(self.image_path)
                if not pix.isNull():
                    self.preview.setPixmap(
                        pix.scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
            QTimer.singleShot(50, _rescale)


# ═══════════════════════════════════════════════════════════════════════════════
# Иконки для кнопок панели
# ═══════════════════════════════════════════════════════════════════════════════

def _make_cube_icon(color: str = "#666666", size: int = 16):
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF
    from PySide6.QtCore import Qt, QPointF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    p.drawPolygon(QPolygonF([
        QPointF(s*.50, s*.04), QPointF(s*.94, s*.28),
        QPointF(s*.50, s*.52), QPointF(s*.06, s*.28),
    ]))
    p.drawPolygon(QPolygonF([
        QPointF(s*.06, s*.28), QPointF(s*.06, s*.72),
        QPointF(s*.50, s*.96), QPointF(s*.50, s*.52),
    ]))
    p.drawPolygon(QPolygonF([
        QPointF(s*.94, s*.28), QPointF(s*.94, s*.72),
        QPointF(s*.50, s*.96), QPointF(s*.50, s*.52),
    ]))
    p.end()
    return QIcon(pix)


def _make_replace_icon(color: str = "#666666", size: int = 16):
    """Иконка «заменить модель» — две стрелки-swap (⇄)."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QLineF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    # верхняя стрелка вправо
    p.drawLine(QLineF(s*.16, s*.36, s*.84, s*.36))
    p.drawLine(QLineF(s*.84, s*.36, s*.67, s*.24))
    p.drawLine(QLineF(s*.84, s*.36, s*.67, s*.48))
    # нижняя стрелка влево
    p.drawLine(QLineF(s*.84, s*.64, s*.16, s*.64))
    p.drawLine(QLineF(s*.16, s*.64, s*.33, s*.52))
    p.drawLine(QLineF(s*.16, s*.64, s*.33, s*.76))
    p.end()
    return QIcon(pix)


def _make_vpk_icon(color: str = "#666666", size: int = 16):
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QRectF, QLineF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    p.drawRect(QRectF(s*.08, s*.30, s*.84, s*.64))
    p.drawRect(QRectF(s*.18, s*.10, s*.64, s*.22))
    pen2 = QPen(QColor(color))
    pen2.setWidthF(0.9)
    p.setPen(pen2)
    for frac in (0.48, 0.60, 0.72):
        y = s * frac
        p.drawLine(QLineF(s*.18, y, s*.82, y))
    p.end()
    return QIcon(pix)


def _make_team_icon(fill_color: str, size: int = 16):
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QRectF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    m = s * .12
    col = QColor(fill_color)
    p.setBrush(col)
    pen = QPen(col.darker(130))
    pen.setWidthF(1.0)
    p.setPen(pen)
    p.drawEllipse(QRectF(m, m, s - 2*m, s - 2*m))
    p.end()
    return QIcon(pix)
