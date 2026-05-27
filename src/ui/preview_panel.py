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
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from src.shared.logging_config import get_logger
from src.utils.themes import get_modern_styles

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Карточка одного текстурного слота (2D, drag-drop)
# ═══════════════════════════════════════════════════════════════════════════════

class _ExtraSlotCard(QWidget):
    """Карточка одного текстурного слота — drag-drop + Browse + превью."""

    image_changed = Signal(str, str)   # (material_name, image_path)

    _STYLE_IDLE = "border: 1px solid #333; border-radius: 4px; background: #1a1a1a;"
    _STYLE_HOT  = "border: 1px solid #555; border-radius: 4px; background: #222;"

    CARD_H = 500

    def __init__(self, material_name: str, parent=None):
        super().__init__(parent)
        self.material_name = material_name
        self._image_path: Optional[str] = None
        self._pix_source: Optional[QPixmap] = None

        self.setFixedSize(380, self.CARD_H)
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

        name_lbl = QLabel(material_name)
        name_lbl.setStyleSheet("color:#888; font-size:11px;")
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setFixedHeight(18)
        lay.addWidget(name_lbl)

        btn = QPushButton("Browse…")
        btn.setFixedHeight(24)
        btn.setStyleSheet("""
            QPushButton { background:transparent; color:#666;
                border:1px solid #333; border-radius:3px; font-size:11px; }
            QPushButton:hover { color:#aaa; border-color:#555; }
        """)
        btn.clicked.connect(self._browse)
        lay.addWidget(btn)

        self._show_placeholder()

    # ── public ────────────────────────────────────────────────────────────────

    def set_image(self, path: str) -> None:
        self._image_path = path or None
        if not path or not os.path.exists(path):
            self._pix_source = None   # без этого _refresh мог восстановить старый кадр
            self._show_placeholder()
            return
        pix = QPixmap(path)
        if pix.isNull():
            self._pix_source = None
            self._show_placeholder()
            return
        self._pix_source = pix
        # setStyleSheet до setPixmap — чтобы стиль применился до отрисовки
        # НЕ вызываем setText('') после _refresh: в Qt setText() переключает label
        # обратно в текстовый режим и стирает только что установленный pixmap!
        self._lbl.setStyleSheet(self._STYLE_IDLE)
        self._refresh()

    def get_image(self) -> Optional[str]:
        return self._image_path

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
        # clear() — канонический Qt-способ сбросить и текст и pixmap
        self._lbl.clear()
        self._lbl.setText("Drop texture here\nor click Browse")
        self._lbl.setStyleSheet("color:#444; font-size:10px; " + self._STYLE_IDLE)

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
            self._browse()
        super().mousePressEvent(event)


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
        self._custom_smd_mode: bool = False
        self._crithit_mode: bool = False
        self._crithit_class: str = 'soldier'

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

        # Стили кнопок 2D/3D
        self._btn_style_active = """
            QPushButton { background:#2a2a2a; color:#ccc; border:1px solid #444;
                padding:4px 16px; font-size:11px; font-weight:600; border-radius:3px; }
        """
        self._btn_style_inactive = """
            QPushButton { background:transparent; color:#555; border:1px solid #2a2a2a;
                padding:4px 16px; font-size:11px; border-radius:3px; }
            QPushButton:hover { background:rgba(255,255,255,0.04); color:#888; border-color:#383838; }
        """

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
        self.empty_state.setMinimumWidth(800)
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
        self.preview.setMinimumWidth(800)
        self.preview.setAcceptDrops(True)
        self.preview.hide()
        vlay.addWidget(self.preview)

        # Полоса карточек (многоматериальный режим)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent;")
        scroll.setFixedHeight(508)

        self._cards_bar = QWidget()
        self._cards_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        panel.setMinimumWidth(600)
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
        qt_w.setMinimumWidth(800)

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

    def _switch_to_2d(self) -> None:
        self.view_stack.setCurrentIndex(0)
        self.btn_2d.setStyleSheet(self._btn_style_active)
        self.btn_3d.setStyleSheet(self._btn_style_inactive)
        self.btn_load_3d.setVisible(False)
        self.btn_load_vpk.setVisible(False)
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

        if self._crithit_mode:
            self.btn_load_3d.setVisible(False)
            self.btn_load_vpk.setVisible(False)
            if self._3d_available:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, self._render_crithit_scene)
            return

        self.btn_load_3d.setVisible(True)
        self.btn_load_vpk.setVisible(True)
        self.btn_load_vpk.setEnabled(True)
        self._update_team_btn_visibility()

        # Переприменяем текущие текстуры к 3D если они загружены
        # (например, пользователь переключился в 2D, загрузил текстуру, вернулся в 3D)
        skip = (
            self._per_mesh_active
            and self.image_path is not None
            and self.image_path == self._per_mesh_base_image
        )
        if skip or not self._3d_available or not self._3d_widget:
            return

        from PySide6.QtCore import QTimer

        if self._card_mode and self._material_names:
            # Мульти-материал: применяем каждую текстуру к своему мешу
            tex_map = self._build_tex_map()
            if tex_map:
                static: dict = {}
                for mat, path in tex_map.items():
                    if path.lower().endswith('.gif'):
                        QTimer.singleShot(300, lambda p=path, m=mat: self._apply_gif_to_3d(p, m))
                    else:
                        static[mat] = path
                if static:
                    QTimer.singleShot(300, lambda m=static: self._3d_widget.apply_material_map(m))
        elif self.image_path and os.path.exists(self.image_path):
            path = self.image_path
            QTimer.singleShot(300, lambda p=path: self._apply_image_to_3d(p))

    def is_3d_mode(self) -> bool:
        return self.view_stack.currentIndex() == 1

    def _update_team_btn_visibility(self) -> None:
        # Показываем кнопки RED/BLU если:
        # - найдены BLU VPK-кадры (оружие/шапка с командной текстурой)
        # - есть пользовательские текстуры для BLU команды
        # - модель многоматериальная (персонажи — всегда имеют командные варианты)
        has_blu = bool(self._blu_frames or self._textures.get('blu') or self._card_mode)
        self.btn_red.setVisible(has_blu)
        self.btn_blu.setVisible(has_blu)

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
            # Обновляем image_path чтобы _set_material_slots взял правильный fallback
            main_key = self._material_names[0]
            main_path = paths.get(main_key)
            self.image_path = main_path if (main_path and os.path.exists(main_path)) else None

            # Пересоздаём карточки — гарантированное обновление UI независимо
            # от состояния Qt-виджетов (set_image на скрытых виджетах ненадёжен).
            # _set_material_slots читает _textures[_active_team], который уже = team.
            self._set_material_slots(self._material_names)
        else:
            key = self._material_names[0] if self._material_names else '__single__'
            path = paths.get(key)
            self._stop_gif()
            if path and os.path.exists(path):
                self.image_path = path
                self._show_image_in_preview(path)
            else:
                self.image_path = None
                self._clear_preview_label()

        self.vtf_path = None
        self.update_info_summary()

    def _restore_team_textures_3d(self, team: str) -> None:
        """Применяет текстуры команды к 3D модели."""
        from PySide6.QtCore import QTimer
        paths = self._textures.get(team, {})
        vpk_frames = self._red_frames if team == 'red' else self._blu_frames

        if self._card_mode and self._material_names:
            # Мульти-материал: строим per-material карту из пользовательских текстур
            tex_map: dict = {}
            for mat in self._material_names:
                p = paths.get(mat)
                if p and os.path.exists(p):
                    tex_map[mat] = p

            if tex_map:
                # Есть пользовательские текстуры — применяем их
                static: dict = {}
                for mat, p in tex_map.items():
                    if p.lower().endswith('.gif'):
                        QTimer.singleShot(50, lambda _p=p, _m=mat: self._apply_gif_to_3d(_p, _m))
                    else:
                        static[mat] = p
                if static:
                    QTimer.singleShot(50, lambda m=static: self._3d_widget.apply_material_map(m))
            elif team == 'red' and self._vpk_red_tex_map:
                # RED без пользовательских текстур: восстанавливаем исходный VPK tex_map
                # (_red_frames пуст для персонажей — их текстура хранится здесь)
                restore = dict(self._vpk_red_tex_map)
                QTimer.singleShot(50, lambda m=restore: self._3d_widget.apply_material_map(m))
            elif team == 'blu' and self._vpk_blu_tex_map:
                # BLU без пользовательских текстур: восстанавливаем BLU VPK tex_map
                # (многоматериальные персонажи — _blu_frames пуст, текстуры здесь)
                restore = dict(self._vpk_blu_tex_map)
                QTimer.singleShot(50, lambda m=restore: self._3d_widget.apply_material_map(m))
            else:
                # Fallback: применяем VPK кадры (для одиночных текстур)
                self._apply_vpk_frames(vpk_frames)
        else:
            key = self._material_names[0] if self._material_names else '__single__'
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

        self._last_3d_params = new_params
        self._pending_3d_params = new_params
        self._custom_smd_mode = False
        self._crithit_mode = False

        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()

        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_weapon', 'Select a weapon and click ▶ to load the model')
            )
        self.btn_load_3d.setEnabled(True)
        self.btn_load_vpk.setEnabled(True)

    def reset_3d_preview(self) -> None:
        """Полный сброс 3D (при смене режима на Spray/None)."""
        self._pending_3d_params = None
        self._last_3d_params = None
        self._custom_smd_mode = False
        self._crithit_mode = False
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

    def set_custom_model_mode(self, enabled: bool = True) -> None:
        self._custom_smd_mode = enabled
        self._pending_3d_params = None
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
        self._crithit_mode = True
        self._custom_smd_mode = False
        self._pending_3d_params = None
        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._reset_team_vpk_state()
        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_crithit', 'Switch to 3D tab — the soldier will appear automatically')
            )
        if self.is_3d_mode() and self._3d_available:
            self._render_crithit_scene()

    def update_3d_texture(self, path: str) -> None:
        """Обновляет текстуру на 3D модели (вызывается из внешнего кода)."""
        if self._3d_widget and self.is_3d_mode():
            self._apply_image_to_3d(path)

    # ═══════════════════════════════════════════════════════════════════════════
    # Кнопка «Загрузить 3D»
    # ═══════════════════════════════════════════════════════════════════════════

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
        w.failed.connect(self._on_3d_failed)
        w.start()
        self._3d_worker = w

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
        if self._3d_widget:
            self._3d_widget.load_model_files(obj_path, texture_path)

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

    def _on_3d_blu_multi_material(self, tex_map: dict) -> None:
        """Воркер нашёл BLU текстуры для многоматериальной модели (персонажи).

        Сохраняем BLU VPK tex_map для последующего восстановления 3D при переключении
        на BLU команду. Не применяем сразу — пользователь пока на RED.
        """
        if not tex_map:
            return
        self._vpk_blu_tex_map = dict(tex_map)
        logger.debug(f"[Panel] BLU multi-material: {len(tex_map)} материалов")
        # Кнопки уже должны быть видны благодаря _update_team_btn_visibility в
        # _on_3d_multi_material, но на всякий случай гарантируем их видимость
        self.btn_red.setVisible(True)
        self.btn_blu.setVisible(True)

    def _on_3d_multi_material(self, tex_map: dict) -> None:
        """Модель многоматериальная — применяем и создаём карточки."""
        if not (self._3d_widget and tex_map):
            return
        self._3d_widget.apply_material_map(tex_map)
        # Сохраняем RED VPK tex_map — нужен для восстановления при переключении команды
        # (для персонажей _red_frames = [], RED текстура хранится только здесь)
        if self._active_team == 'red' and not self._vpk_red_tex_map:
            self._vpk_red_tex_map = dict(tex_map)

        mat_keys = list(tex_map.keys())
        current_all = (
            self._material_names if self._card_mode else []
        )
        if len(mat_keys) > 1:
            if mat_keys != current_all:
                self._set_material_slots(mat_keys)
            # Для персонажей: показываем кнопки RED/BLU сразу после обнаружения
            # многоматериальной модели (даже если BLU VTF не найден в VPK)
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

    def _set_material_slots(self, names: List[str]) -> None:
        """Показывает карточки для списка материалов (или большое превью если < 2)."""
        # Очищаем старые виджеты
        lay = self._cards_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._card_widgets.clear()
        self._main_card = None

        if len(names) < 2:
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

        main_name = names[0]
        main_card = _ExtraSlotCard(main_name, parent=self._cards_bar)
        # Восстанавливаем уже загруженную текстуру (если была)
        saved = self._textures[self._active_team].get(main_name)
        if saved and os.path.exists(saved):
            main_card.set_image(saved)
        elif self.image_path and os.path.exists(self.image_path):
            main_card.set_image(self.image_path)
        main_card.image_changed.connect(self._on_main_card_changed)
        lay.addWidget(main_card)
        self._main_card = main_card

        for name in names[1:]:
            card = _ExtraSlotCard(name, parent=self._cards_bar)
            saved = self._textures[self._active_team].get(name)
            if saved and os.path.exists(saved):
                card.set_image(saved)
            card.image_changed.connect(self._on_extra_card_changed)
            lay.addWidget(card)
            self._card_widgets[name] = card

        lay.addStretch()

        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    def _on_main_card_changed(self, mat_name: str, path: str) -> None:
        """Пользователь сменил текстуру в главной карточке."""
        self._stop_gif()
        if path != self._per_mesh_base_image:
            self._per_mesh_active = False
            self._per_mesh_base_image = None
        self.image_path = path
        self.vtf_path = None
        self._textures.setdefault(self._active_team, {})[mat_name] = path
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

    def _on_extra_card_changed(self, mat_name: str, path: str) -> None:
        """Пользователь сменил текстуру в карточке доп. слота."""
        self._textures.setdefault(self._active_team, {})[mat_name] = path
        if self.is_3d_mode() and self._3d_widget and path and os.path.exists(path):
            from PySide6.QtCore import QTimer
            if path.lower().endswith('.gif'):
                QTimer.singleShot(300, lambda p=path, m=mat_name: self._apply_gif_to_3d(p, m))
            else:
                QTimer.singleShot(300, lambda p=path, m=mat_name: self._3d_widget.apply_material_map({m: p}))

    def get_slot_image_paths(self) -> dict:
        """Возвращает {material_name: path} для всех заполненных слотов (всегда RED для сборки)."""
        red = self._textures.get('red', {})
        return {k: v for k, v in red.items() if v and os.path.exists(v)}

    def _build_tex_map(self) -> dict:
        """Строит {mat: path} для всех слотов текущей команды (только существующие файлы)."""
        paths = self._textures.get(self._active_team, {})
        result = {}
        for mat in self._material_names:
            p = paths.get(mat)
            if p and os.path.exists(p):
                result[mat] = p
        return result

    # ═══════════════════════════════════════════════════════════════════════════
    # Загрузка изображений (2D)
    # ═══════════════════════════════════════════════════════════════════════════

    def load_image(self, path: str) -> None:
        """Загружает изображение (или GIF) в 2D Preview."""
        self._stop_gif()
        if path != self._per_mesh_base_image:
            self._per_mesh_active = False
            self._per_mesh_base_image = None

        self.image_path = path
        self.vtf_path = None

        # Сохраняем под активной командой
        key = self._material_names[0] if self._material_names else '__single__'
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
            import tempfile

            rgba, w, h = VTFLib.read_vtf_as_rgba(path)
            qimg = QImage(rgba, w, h, w * 4, QImage.Format_RGBA8888)
            if not qimg.isNull():
                rendered = True
                png_for_3d = tempfile.mktemp(suffix='.png')
                Image.frombytes("RGBA", (w, h), rgba).save(png_for_3d)
                self.image_path = png_for_3d

                # Сохраняем под активной командой
                key = self._material_names[0] if self._material_names else '__single__'
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

    def clear_preview(self) -> None:
        self._stop_gif()
        self.image_path = None
        self.vtf_path = None
        if self._card_mode and self._main_card:
            self._main_card.set_image('')
        else:
            self._clear_preview_label()
        self.update_info_summary()

    def get_image_path(self) -> Optional[str]:
        """Возвращает путь к главной текстуре (всегда RED для сборки)."""
        key = self._material_names[0] if self._material_names else '__single__'
        p = self._textures.get('red', {}).get(key)
        if p and os.path.exists(p):
            return p
        # Fallback: image_path (если пользователь ещё не переключал команды)
        if self.image_path and os.path.exists(self.image_path):
            return self.image_path
        return None

    def get_vtf_path(self) -> Optional[str]:
        return self.vtf_path

    def get_blu_image_path(self) -> Optional[str]:
        """Возвращает путь к пользовательской BLU текстуре (главный слот) или None."""
        blu = self._textures.get('blu', {})
        key = self._material_names[0] if self._material_names else '__single__'
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

        if path.lower().endswith('.gif'):
            def _try_gif():
                if self._gif_movie is not None:
                    return
                w = max(self.preview.width(), self.width(), 600)
                if not self._start_gif(path, w):
                    pix = QPixmap(path).scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.preview.setPixmap(pix)
            QTimer.singleShot(50, _try_gif)
        else:
            def _scale():
                w = max(self.preview.width(), self.width(), 600)
                pix = QPixmap(path).scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
            import tempfile

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
                tmp = tempfile.mktemp(suffix='.png', prefix=f'tf2_gif{i}_')
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
            tmp = tempfile.mktemp(suffix=ext, prefix='tf2_3ddrop_')
            with open(tmp, 'wb') as f:
                f.write(img_bytes)

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
            import tempfile
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image
            rgba, w, h = VTFLib.read_vtf_as_rgba(vtf_path)
            img = Image.frombytes("RGBA", (w, h), rgba)
            png = tempfile.mktemp(suffix='.png', prefix='tf2_model_tex_')
            img.save(png)
            return png
        except Exception as exc:
            logger.warning(f"VTF→PNG модели: {exc}")
            return ''

    # ═══════════════════════════════════════════════════════════════════════════
    # VPK мод
    # ═══════════════════════════════════════════════════════════════════════════

    def enable_vpk_mod_button(self, enabled: bool = True) -> None:
        self.btn_load_vpk.setEnabled(enabled)

    def get_loaded_vpk_mod_path(self) -> Optional[str]:
        return getattr(self, '_loaded_vpk_mod_path', None)

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

        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_converting_smd', 'Converting SMD...'))
        try:
            tmp_dir = tempfile.mkdtemp(prefix="tf2_smd_preview_")
            obj_path = os.path.join(tmp_dir, "model.obj")
            ok = SmdToObjService.convert(smd_path, obj_path)
            if not ok or not os.path.exists(obj_path):
                self._3d_widget.show_error(self.t.get('3d_error_convert', 'SMD conversion error'))
                return
            self._3d_widget.load_model_files(obj_path, self.image_path or '')
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
        self._active_team = 'red'   # сброс синхронизируем со стилями кнопок
        if hasattr(self, 'btn_red'):
            self.btn_red.setVisible(False)
            self.btn_red.setStyleSheet(self._team_style_on)
        if hasattr(self, 'btn_blu'):
            self.btn_blu.setVisible(False)
            self.btn_blu.setStyleSheet(self._team_style_off)

    # ═══════════════════════════════════════════════════════════════════════════
    # Drag & Drop (в 2D область)
    # ═══════════════════════════════════════════════════════════════════════════

    def setup_drag_drop(self):   # вызывается для обратной совместимости
        self.empty_state.setAcceptDrops(True)
        self.preview.setAcceptDrops(True)

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
    def is_image_file(self, fp): return self._is_image(fp)
    def is_vtf_file(self, fp): return self._is_vtf(fp)

    # ═══════════════════════════════════════════════════════════════════════════
    # Info summary
    # ═══════════════════════════════════════════════════════════════════════════

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
