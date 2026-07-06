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
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from src.shared.constants import Team
from src.shared.file_utils import get_temp_file_path
from src.shared.logging_config import get_logger
from src.utils.themes import get_modern_styles

logger = get_logger(__name__)

# Фильтр служебных материалов (глаза/зубы/sheen-оверлеи) — общий для UI и сборки.
from src.ui.preview_mode import PreviewMode, PreviewState
# Единый источник правды о текстурах превью (команды/стили/вариант) — см. модуль.
from src.ui.texture_state import PreviewTextureState

# Вынесенные из этого модуля строительные блоки панели превью
# (векторные иконки, карточка слота, скролл-область, воркер масок шпиона).
from src.ui.preview_icons import (
    _make_cube_icon, _make_replace_icon, _make_vpk_icon,
    _make_plus_icon, _make_eye_icon, _make_team_icon,
)
from src.ui.preview_widgets import (
    _HWheelScrollArea, _ExtraSlotCard, _SpyMaskVtfWorker,
)
from src.ui.preview_3d_mixin import Preview3DMixin
from src.ui.preview_skins_mixin import PreviewSkinsMixin
from src.ui.preview_custom_model_mixin import PreviewCustomModelMixin
from src.ui.preview_team_mixin import PreviewTeamMixin
from src.ui.preview_2d_image_mixin import Preview2DImageMixin
from src.ui.preview_crithit_mixin import PreviewCritHitMixin
from src.ui.preview_material_cards_mixin import PreviewMaterialCardsMixin


class PreviewPanel(Preview3DMixin, PreviewSkinsMixin, PreviewCustomModelMixin,
                   PreviewTeamMixin, Preview2DImageMixin, PreviewCritHitMixin,
                   PreviewMaterialCardsMixin, QWidget):
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

        # ── ЕДИНЫЙ источник правды о текстурах (команды/стили/вариант) ─────── #
        # Хранение, маршрутизация и разрешение — в PreviewTextureState
        # (src/ui/texture_state.py). Старые поля (_textures, _skin_overrides,
        # _vpk_*_tex_map, австралий-слоты и т.п.) — property-делегаты ниже.
        self._state = PreviewTextureState()
        # «Сделать командным»: пользователь включил синтез BLU у некомандного оружия.
        self._force_team: bool = False

        # ── Слоты материалов (виджеты) ─────────────────────────────────────── #
        # _material_names заполняется после загрузки 3D (_on_3d_multi_material);
        # для рук — сразу из HAND_MODES. [0] = главный, [1:] = дополнительные.
        self._card_mode: bool = False
        self._has_blu: bool = False

        # ── «Прочее»: служебные материалы (глаза/убер/зомби), скрытые блэклистом ─ #
        # Их можно опционально отредактировать через отдельный селектор-тоггл.
        self._misc_materials: List[str] = []   # блэклист-материалы текущей модели
        self._misc_mode: bool = False          # активен ли просмотр «Прочее»
        self._cards_before_misc: List[str] = []  # нормальный набор (для возврата)
        # Материалы, которые пользователь ЯВНО добавил в вариантный стиль через
        # «+» (карточка показывается даже пустой). Скин 0 тут не участвует.
        self._skin_chosen: Dict[int, set] = {}
        self._skin_worker = None
        self._skin_buttons: List[QPushButton] = []
        self._skin_button_indices: List[int] = []   # сырой индекс скина на кнопку
        # Режим загруженного custom-VPK мода: карточки строятся из VTF мода
        # (_on_vpk_mod_cards_ready). Защищает их от перетирания обычной
        # фильтрацией материалов модели в _on_3d_multi_material.
        self._custom_vpk_mode: bool = False
        # Точные имена материалов модели (из SMD) — для наложения текстур мода
        # на правильные меши в custom-VPK режиме.
        self._custom_model_materials: List[str] = []
        # Что сейчас реально показано в 3D по материалам — чтобы при переключении
        # стилей перезагружать в webview ТОЛЬКО изменившиеся текстуры (меньше лагов).
        self._applied_3d_tex: Dict[str, str] = {}
        # Пер-текстурные оверрайды настроек: {material: {size,format,flags,options}}.
        # Есть запись ⟺ у материала свои настройки (иначе — глобальные).
        self._tex_overrides: Dict[str, dict] = {}
        # Пер-текстурные файловые карты: {material: {map_id: spec}} из MaterialMapsDialog.
        self._tex_maps: Dict[str, dict] = {}

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
        # Отложенное применение после подтверждения загрузки модели из JS
        # (см. _run_after_model_load / _on_3d_model_loaded).
        self._model_load_cb = None
        self._model_load_token = None
        self._model_load_settle_ms: int = 50

        # ── Мини-память последнего оружия (1 слот) ────────────────────────── #
        # _cur_obj — (mode, obj_path, texture_path) сейчас загруженной модели,
        #            заполняется в _on_3d_ready (None если модель не загружена).
        # _mem_mode/_mem_data — снимок ПРЕДЫДУЩЕГО загруженного оружия для
        #            мгновенного восстановления при возврате (без воркера).
        #            Данные текстур — snapshot() модели; _restore_from_memory
        #            выставляет и _weapon_key/_weapon_mode, поэтому последующий
        #            update_extra_slots видит «то же оружие» и ничего не трогает.
        self._cur_obj: Optional[tuple] = None
        self._mem_mode: Optional[str] = None
        self._mem_data: Optional[dict] = None
        # Память по стилям шапки: правки применяются ПОСЛЕ загрузки модели стиля.
        self._pending_edit_state: Optional[dict] = None
        # Обновить 2D после загрузки модели (смена стиля без своих правок —
        # иначе в 2D остаётся пустое/старое окно, а текстура только в 3D).
        self._pending_2d_refresh: bool = False
        # Явный режим превью вместо россыпи взаимоисключающих булевых флагов
        # (_custom_smd_mode/_spy_mask_mode/_crithit_mode/_death_effect_mode теперь
        # — свойства, читающие из _pstate). Источник правды по «что показываем».
        self._pstate = PreviewState()
        self._custom_smd_path: Optional[str] = None   # путь загруженной кастомной модели
        # True — модель «готова»: сохранять её материалы как есть (многотекстурная).
        # False — заменить только геометрию (адаптировать под игровой материал).
        self._custom_keep_materials: bool = False
        # Отредактированный пользователем QC (исправленный). None = авто-QC.
        self._custom_qc_text: Optional[str] = None
        self._crithit_class: str = 'soldier'
        # Режим «эффект смерти»: та же модель-персонаж, что у крита, но
        # пользовательская текстура накладывается на саму МОДЕЛЬ (лёд/золото/огонь),
        # а не на billboard — чтобы показать, как эффект ляжет в игре.
        # PNG оригинальной игровой текстуры эффекта (дефолт, пока юзер не загрузил свою).
        self._death_default_tex: str = ''
        self._active_spy_mask: Optional[str] = None  # активный класс (cls_key)
        self._aus_card = None                          # карточка «Australium» в ряду типов текстур

        # ── Per-mesh drag tracking ─────────────────────────────────────────── #
        # True если пользователь перетащил текстуру на конкретный меш в 3D.
        # Сбрасывается при смене изображения или загрузке новой модели.
        self._per_mesh_active: bool = False
        self._per_mesh_base_image: Optional[str] = None

        # ── Командные кадры из VPK ────────────────────────────────────────── #
        # Данные (кадры/карты/маппинг) — в self._state; здесь только framerate.
        self._team_framerate: float = 0.0

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
    # Режим превью (взаимоисключающие флаги → свойства поверх _pstate)
    # ═══════════════════════════════════════════════════════════════════════════

    @property
    def _custom_smd_mode(self) -> bool:
        return self._pstate.is_custom

    @property
    def _spy_mask_mode(self) -> bool:
        return self._pstate.is_spy_masks

    @property
    def _crithit_mode(self) -> bool:
        # critHIT-сцена (персонаж+billboard) активна И в чистом critHIT, И в режиме
        # эффекта смерти — death переиспользует крит-инфраструктуру (раньше оба
        # булевых флага стояли True одновременно).
        return self._pstate.is_crithit or self._pstate.is_death

    @property
    def _death_effect_mode(self) -> bool:
        return self._pstate.is_death

    # ═══════════════════════════════════════════════════════════════════════════
    # Делегаты состояния текстур (единый источник — self._state)
    #
    # Существующий код панели обращается к этим полям напрямую (~50 точек);
    # property-делегаты позволяют мигрировать на PreviewTextureState без
    # одновременной правки всех точек: чтение/мутация словарей идут в модель.
    # ═══════════════════════════════════════════════════════════════════════════

    @property
    def _textures(self) -> Dict[str, Dict[str, str]]:
        return self._state.textures

    @_textures.setter
    def _textures(self, value: Dict[str, Dict[str, str]]) -> None:
        self._state.textures = value

    @property
    def _skin_overrides(self) -> Dict[int, Dict[str, str]]:
        return self._state.skin_overrides

    @_skin_overrides.setter
    def _skin_overrides(self, value: Dict[int, Dict[str, str]]) -> None:
        self._state.skin_overrides = value

    @property
    def _active_team(self) -> str:
        return self._state.active_team

    @_active_team.setter
    def _active_team(self, value: str) -> None:
        self._state.active_team = value

    @property
    def _force_team(self) -> bool:
        """«Сделать командным» — единый источник правды в модели (влияет на
        маршрутизацию set_texture: под force_team загрузка не дублируется в обе
        команды)."""
        return self._state.force_team

    @_force_team.setter
    def _force_team(self, value: bool) -> None:
        self._state.force_team = bool(value)

    @property
    def _active_skin(self) -> int:
        return self._state.active_skin

    @_active_skin.setter
    def _active_skin(self, value: int) -> None:
        self._state.active_skin = value

    @property
    def _original_skin_info(self) -> Optional[dict]:
        return self._state.skin_info

    @_original_skin_info.setter
    def _original_skin_info(self, value: Optional[dict]) -> None:
        self._state.skin_info = value

    @property
    def _material_names(self) -> List[str]:
        return self._state.material_names

    @_material_names.setter
    def _material_names(self, value: List[str]) -> None:
        self._state.material_names = value

    @property
    def _main_material_name(self) -> Optional[str]:
        return self._state.main_material

    @_main_material_name.setter
    def _main_material_name(self, value: Optional[str]) -> None:
        self._state.main_material = value

    @property
    def _vpk_blu_name_map(self) -> dict:
        return self._state.blu_name_map

    @_vpk_blu_name_map.setter
    def _vpk_blu_name_map(self, value: dict) -> None:
        self._state.blu_name_map = value

    @property
    def _vpk_red_tex_map(self) -> dict:
        return self._state.vpk_red_tex_map

    @_vpk_red_tex_map.setter
    def _vpk_red_tex_map(self, value: dict) -> None:
        self._state.vpk_red_tex_map = value

    @property
    def _vpk_blu_tex_map(self) -> dict:
        return self._state.vpk_blu_tex_map

    @_vpk_blu_tex_map.setter
    def _vpk_blu_tex_map(self, value: dict) -> None:
        self._state.vpk_blu_tex_map = value

    @property
    def _red_frames(self) -> List[str]:
        return self._state.red_frames

    @_red_frames.setter
    def _red_frames(self, value: List[str]) -> None:
        self._state.red_frames = value

    @property
    def _blu_frames(self) -> List[str]:
        return self._state.blu_frames

    @_blu_frames.setter
    def _blu_frames(self, value: List[str]) -> None:
        self._state.blu_frames = value

    @property
    def _australium_frame(self) -> Optional[str]:
        return self._state.australium_frame

    @_australium_frame.setter
    def _australium_frame(self, value: Optional[str]) -> None:
        self._state.australium_frame = value

    @property
    def _australium_active(self) -> bool:
        return self._state.australium_active

    @_australium_active.setter
    def _australium_active(self, value: bool) -> None:
        self._state.australium_active = value

    @property
    def _australium_user_tex(self) -> Optional[str]:
        return self._state.australium_user_tex

    @_australium_user_tex.setter
    def _australium_user_tex(self, value: Optional[str]) -> None:
        self._state.australium_user_tex = value

    @property
    def _australium_mat_name(self) -> Optional[str]:
        return self._state.australium_mat_name

    @_australium_mat_name.setter
    def _australium_mat_name(self, value: Optional[str]) -> None:
        self._state.australium_mat_name = value

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

        # Кнопка «Редактировать QC» — только для «готовой» модели (keep_materials).
        self.btn_edit_qc = QPushButton("QC")
        self.btn_edit_qc.setFixedHeight(26)
        self.btn_edit_qc.setStyleSheet(
            "QPushButton { background:transparent; border:1px solid #2a2a2a;"
            " border-radius:3px; padding:0 8px; color:#888; font-size:11px; font-weight:600; }"
            " QPushButton:hover { background:rgba(255,255,255,0.05); border-color:#555; color:#ccc; }"
        )
        self.btn_edit_qc.setToolTip(self.t.get('qc_edit_tip', 'Edit QC (jigglebones etc.)'))
        self.btn_edit_qc.setVisible(False)
        self.btn_edit_qc.clicked.connect(self._on_edit_qc_clicked)
        lay.addWidget(self.btn_edit_qc)

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
        self.btn_red.clicked.connect(lambda: self._switch_team(Team.RED))
        lay.addWidget(self.btn_red)

        self.btn_blu = QPushButton()
        self.btn_blu.setFixedSize(26, 26)
        self.btn_blu.setIcon(_make_team_icon("#2980b9"))
        self.btn_blu.setStyleSheet(self._team_style_off)
        self.btn_blu.setToolTip(self.t.get('3d_team_blu_tip', 'BLU team texture'))
        self.btn_blu.setVisible(False)
        self.btn_blu.clicked.connect(lambda: self._switch_team(Team.BLU))
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

        # «+» — сделать некомандное оружие командным (показать селектор RED/BLU).
        # В одном ряду с RED/BLU/Aus, тот же размер 26×26 — «+» рисуем иконкой
        # (как у остальных кнопок ряда), чтобы не зависеть от рендера текста.
        from PySide6.QtCore import QSize as _QSize_plus
        self.btn_make_team = QPushButton()
        self.btn_make_team.setFixedSize(26, 26)
        self.btn_make_team.setIcon(_make_plus_icon("#aaaaaa"))
        self.btn_make_team.setIconSize(_QSize_plus(14, 14))
        self.btn_make_team.setCursor(Qt.PointingHandCursor)
        self.btn_make_team.setToolTip(self.t.get(
            'make_team_tip',
            'Сделать оружие командным: добавить отдельную BLU-текстуру',
        ))
        self.btn_make_team.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #555;border-radius:4px;}"
            "QPushButton:hover{border-color:#888;}"
        )
        self.btn_make_team.setVisible(False)
        self.btn_make_team.clicked.connect(self._enable_force_team)
        lay.addWidget(self.btn_make_team)

        # «Прочее» — селектор служебных текстур (глаза/убер/зомби), скрытых
        # блэклистом. Круглая кнопка-тоггл в стиле команд, иконка — глаз.
        from PySide6.QtCore import QSize as _QSize_eye
        self.btn_misc = QPushButton()
        self.btn_misc.setFixedSize(26, 26)
        self.btn_misc.setIcon(_make_eye_icon("#cccccc"))
        self.btn_misc.setIconSize(_QSize_eye(16, 16))
        self.btn_misc.setStyleSheet(self._team_style_off)
        self.btn_misc.setCursor(Qt.PointingHandCursor)
        self.btn_misc.setToolTip(self.t.get(
            'misc_textures_tip',
            'Служебные текстуры (глаза/убер/зомби и т.п.) — обычно скрыты. '
            'Открыть для опциональной замены.'))
        self.btn_misc.setVisible(False)
        self.btn_misc.clicked.connect(self._toggle_misc)
        lay.addWidget(self.btn_misc)

        # ── Кнопки стилей (skinfamilies) — в том же ряду, что RED/BLU/Aus ──── #
        # Создаются динамически при определении стилей кастомной модели и
        # вставляются ПЕРЕД этим анкером, чтобы держаться правее aus.
        self._skin_anchor = QWidget()
        self._skin_anchor.setFixedWidth(0)
        lay.addWidget(self._skin_anchor)
        self._toolbar_layout = lay
        # Кнопки стилей — аккуратные «пилюли» с акцентом приложения (#ff6b35):
        # активный стиль залит акцентом, неактивные — обводка с подсветкой при наведении.
        self._skin_btn_style_on = (
            "QPushButton { background:#ff6b35; color:#fff; border:1px solid #ff6b35;"
            " padding:3px 14px; font-size:11px; font-weight:600; border-radius:13px; }"
            " QPushButton:hover { background:#ff7d4d; }"
        )
        self._skin_btn_style_off = (
            "QPushButton { background:transparent; color:#aaa; border:1px solid #3a3a3a;"
            " padding:3px 14px; font-size:11px; font-weight:500; border-radius:13px; }"
            " QPushButton:hover { color:#fff; border-color:#ff6b35;"
            " background:rgba(255,107,53,0.12); }"
        )

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
            try:
                bridge.model_loaded.connect(self._on_3d_model_loaded)
            except Exception as exc:
                logger.warning(f"3D bridge model_loaded: {exc}")

    # ── Подтверждение загрузки модели из JS (вместо магических задержек) ──── #

    def _run_after_model_load(self, fn, fallback_ms: int = 800,
                              settle_ms: int = 50) -> None:
        """Выполняет fn после подтверждения из JS, что модель добавлена в сцену.

        Один отложенный слот (последняя регистрация выигрывает — более поздний
        вызов всегда надмножество раннего). После подтверждения ждём settle_ms,
        чтобы уже поставленные в очередь Qt-сигналы воркера (multi_material →
        _card_mode/_material_names) успели обработаться. Fallback-таймер
        страхует случаи без подтверждения: fallback-виджет без WebEngine или
        подтверждение пришло раньше регистрации. Выполняется ровно один раз.
        """
        from PySide6.QtCore import QTimer
        token = object()
        self._model_load_token = token
        # Ожидаемый номер загрузки: ack с другим номером (устаревшая модель
        # при back-to-back смене) игнорируется — сработает fallback или ack
        # актуальной загрузки.
        self._model_load_seq = getattr(self._3d_widget, 'load_seq', None)

        def _fire():
            if self._model_load_token is token:
                self._model_load_token = None
                self._model_load_cb = None   # не держим замыкание до следующей регистрации
                fn()

        self._model_load_cb = _fire
        QTimer.singleShot(fallback_ms, _fire)
        self._model_load_settle_ms = settle_ms

    def _on_3d_model_loaded(self, load_seq: int = 0) -> None:
        """JS подтвердил: модель в сцене — выполняем отложенное применение.
        Устаревший ack (номер не совпал с ожидаемым) пропускаем."""
        cb = self._model_load_cb
        if cb is None:
            return
        expected = getattr(self, '_model_load_seq', None)
        if expected is not None and load_seq != expected:
            logger.debug(f"[3D ack] устаревший ack #{load_seq}, ждём #{expected}")
            return
        from PySide6.QtCore import QTimer
        QTimer.singleShot(self._model_load_settle_ms, cb)

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
            # Замену модели НЕ предлагаем для тела персонажа: у игрока сложный
            # скелет + flex + много bodygroups/LOD — подмена одной геометрией
            # почти всегда даёт битый результат. Для оружия/рук/шапок — оставляем.
            # Режим берём из 3D-параметров (они выставляются раньше _weapon_mode).
            from src.data.player_characters import PLAYER_BODY_MODE_KEYS
            cur_mode = (
                (self._pending_3d_params[1] if self._pending_3d_params else None)
                or (self._last_3d_params[1] if self._last_3d_params else None)
                or self._weapon_mode
            )
            is_player_body = cur_mode in PLAYER_BODY_MODE_KEYS
            self.btn_replace_model.setVisible(show and not is_player_body)

    def _variant_display_texture(self) -> Optional[str]:
        """
        Текстура активного ВАРИАНТА (Australium/Gold) или None, если вариант
        не активен. Своя загруженная текстура приоритетнее игрового кадра.

        Единственный источник ответа «что показывает вариант» — им пользуются
        и тумблер, и переключатели видов 2D/3D, чтобы вид не расходился с
        состоянием (раньше 2D↔3D игнорировали активный австралий).
        """
        return self._state.variant_display_texture()

    def _switch_to_2d(self) -> None:
        self.view_stack.setCurrentIndex(0)
        self.btn_2d.setStyleSheet(self._btn_style_active)
        self.btn_3d.setStyleSheet(self._btn_style_inactive)
        self._update_3d_buttons_visibility()
        # Командные кнопки остаются видны если есть BLU данные
        self._update_team_btn_visibility()
        # Приоритет отображения: активный вариант (Australium) → вариантный
        # стиль (skin > 0, раскладка карточек стиля) → текстуры активной команды.
        aus_tex = self._variant_display_texture()
        if aus_tex:
            self._show_variant_in_2d(aus_tex)
        elif self._original_skin_info and self._active_skin != 0:
            self._rebuild_cards_for_skin(self._active_skin)
        else:
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

    def _reapply_textures_to_3d(self, delay_ms: int = 50) -> None:
        """
        Повторно применяет пользовательские текстуры к 3D-модели поверх
        VPK-оригиналов. Вызывается при переключении в 3D и сразу после
        загрузки модели из игры (чтобы уже загруженная в 2D текстура
        применилась без повторного 2D→3D).

        delay_ms — короткая пауза очереди событий; «модель ещё грузится»
        страхуют JS-очереди сцены (см. _schedule_3d).
        """
        skip = (
            self._per_mesh_active
            and self.image_path is not None
            and self.image_path == self._per_mesh_base_image
        )
        if skip or not self._3d_available or not self._3d_widget:
            return

        # Активный вариант (Australium) приоритетнее командных текстур — иначе
        # возврат в 3D перекрашивал золотую модель обратно в команду.
        aus_tex = self._variant_display_texture()
        if aus_tex:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(delay_ms, lambda t=aus_tex: self._3d_widget.update_texture_file(t))
            return

        # Восстанавливаем текстуры: VPK-оригиналы + пользовательские поверх.
        # _restore_team_textures_3d строит полную карту и правильно
        # обрабатывает очищенные (×) слоты, возвращая им VPK-оригинал.
        from PySide6.QtCore import QTimer
        if self._custom_vpk_mode and self._custom_model_materials:
            if self._original_skin_info:
                # Стили определены → показываем АКТИВНЫЙ стиль (а не базовый).
                QTimer.singleShot(delay_ms, lambda: self._apply_skin_to_3d(self._active_skin))
            else:
                QTimer.singleShot(delay_ms, self._apply_custom_vpk_textures_to_3d)
        elif self._card_mode and self._material_names:
            QTimer.singleShot(delay_ms, lambda: self._restore_team_textures_3d(self._active_team))
        elif self.image_path and os.path.exists(self.image_path):
            path = self.image_path
            QTimer.singleShot(delay_ms, lambda p=path: self._apply_image_to_3d(p))

    def _schedule_3d(self, fn, delay_ms: int = 50) -> None:
        """Отложенный вызов обновления 3D-виджета.

        Небольшая пауза даёт очереди Qt-событий устаканиться. Исторические
        300мс были страховкой «модель ещё грузится» — теперь это закрывает
        сама JS-сцена: applyMaterialMap/updateTextureFromDataUrl/loadAnimated-
        Texture очередируют вызовы до готовности модели, а generation-guard'ы
        отменяют устаревшие async-колбэки.
        """
        from PySide6.QtCore import QTimer
        QTimer.singleShot(delay_ms, fn)

    def _apply_tex_to_3d_later(self, mat_name: str, path: str) -> None:
        """Единая точка наложения текстуры на 3D после смены в карточке/загрузки.

        Маршрутизация: critHIT-сцена → текстура сцены; GIF → анимированное
        наложение; иначе — обычная карта материала. Ничего не делает вне
        3D-режима.
        """
        if not (self.is_3d_mode() and self._3d_widget):
            return
        if self._crithit_mode:
            self._schedule_3d(lambda p=path: self._update_scene_texture(p))
        elif path.lower().endswith('.gif'):
            self._schedule_3d(lambda p=path, m=mat_name: self._apply_gif_to_3d(p, m))
        else:
            self._schedule_3d(lambda p=path, m=mat_name: self._3d_widget.apply_material_map({m: p}))

    def is_3d_mode(self) -> bool:
        return self.view_stack.currentIndex() == 1

    def _update_team_btn_visibility(self) -> None:
        """
        Единая точка синхронизации командных/вариантных кнопок тулбара.

        RED/BLU видимы только если у модели РЕАЛЬНО есть BLU-вариант:
          - _blu_frames        — BLU одним кадром (оружие/шапка с командной текстурой);
          - _vpk_blu_tex_map / _vpk_blu_name_map — per-material BLU (персонажи).
        (учёт _card_mode / _textures[Team.BLU] давал ложные кнопки у
        мульти-материальных шапок без командного разделения).

        Australium-кнопка видима, когда воркер извлёк вариант (_australium_frame).
        В режиме spy_masks всё скрыто — там своя панель масок.
        """
        if self._spy_mask_mode:
            self.btn_red.setVisible(False)
            self.btn_blu.setVisible(False)
            self.btn_aus.setVisible(False)
            if hasattr(self, 'btn_misc'):
                self.btn_misc.setVisible(False)
            return
        from src.data.player_hands import HAND_MODE_KEYS as _HMK_vis
        if self._weapon_mode in _HMK_vis:
            # Руки: переключатель только если есть РЕАЛЬНЫЙ командный материал —
            # у которого синее имя отличается от красного (engineer_red→engineer_blue,
            # medic_hands_red→medic_hands_blue). Чисто нейтральные руки (scout/spy/
            # heavy) команд не имеют → переключатель не показываем (ложный).
            has_blu = bool(self._vpk_blu_name_map) and any(
                str(bn).lower() != str(m).lower()
                for m, bn in self._vpk_blu_name_map.items()
            )
        else:
            has_blu = bool(
                self._blu_frames or self._vpk_blu_tex_map or self._vpk_blu_name_map
            )
        self.btn_red.setVisible(has_blu or self._force_team)
        self.btn_blu.setVisible(has_blu or self._force_team)
        self.btn_aus.setVisible(bool(self._australium_frame))
        # «+ Команда»: обычное оружие без нативной команды и без австралия —
        # предлагаем сделать командным (синтез BLU-строки при сборке).
        _can_force = (
            not has_blu and not self._force_team and not self._australium_frame
            and self._weapon_mode not in _HMK_vis and not self._spy_mask_mode
            and self._is_force_team_eligible()
        )
        if hasattr(self, 'btn_make_team'):
            self.btn_make_team.setVisible(bool(_can_force))
        # «Прочее» — если у модели есть служебные (блэклист) материалы. Не для
        # кастомных VPK-модов (там карточки строятся из мода) и не для рук.
        if hasattr(self, 'btn_misc'):
            _show_misc = bool(
                self._misc_materials and not self._custom_vpk_mode
                and self._weapon_mode not in _HMK_vis
            )
            self.btn_misc.setVisible(_show_misc)

    def _sync_variant_buttons(self) -> None:
        """
        Единая точка ПОДСВЕТКИ тулбара вариантов (RED/BLU/Australium/Прочее).

        Стили выводятся из состояния (_active_team / _australium_active /
        _misc_mode), а не мутируются каждым обработчиком по отдельности —
        иначе кнопки «залипали» при переходах команда↔австралий↔прочее.
        Видимостью кнопок управляет _update_team_btn_visibility.
        """
        if not hasattr(self, 'btn_red'):
            return   # тулбар ещё не построен
        aus = self._australium_active
        self.btn_red.setStyleSheet(
            self._team_style_on if (not aus and self._active_team == Team.RED)
            else self._team_style_off
        )
        self.btn_blu.setStyleSheet(
            self._team_style_on if (not aus and self._active_team == Team.BLU)
            else self._team_style_off
        )
        if hasattr(self, 'btn_aus'):
            self.btn_aus.setStyleSheet(self._aus_style_on if aus else self._aus_style_off)
        if hasattr(self, 'btn_misc'):
            self.btn_misc.setStyleSheet(
                self._team_style_on if self._misc_mode else self._team_style_off
            )

    def _is_force_team_eligible(self) -> bool:
        """Можно ли предложить «сделать командным» — обычное оружие/снаряд/насмешка
        (не шапка/персонаж/спец-режим/кастом/руки/пикап). Модель должна быть
        загружена (есть _weapon_key) — для одно-материального оружия _material_names
        может быть пустым, поэтому на него не опираемся.

        Пикапы (Health & Ammo) исключены: аптечки/патроны — нейтральные мировые
        предметы, командного варианта у них нет и синтезировать его нельзя."""
        mode = self._weapon_mode or ''
        if not mode or not self._weapon_key or self._weapon_key == '\x00':
            return False
        if mode in ('hat', 'custom'):
            return False
        from src.data.pickups import PICKUP_MODE_PREFIX
        if mode.startswith(PICKUP_MODE_PREFIX):
            return False
        from src.data.weapons import SPECIAL_MODES
        if mode in set(SPECIAL_MODES.values()):
            return False
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS, SPY_MASK_MODE_KEY
        if mode in PLAYER_BODY_MODE_KEYS or mode == SPY_MASK_MODE_KEY:
            return False
        return True

    def _enable_force_team(self) -> None:
        """Включает «сделать командным»: показываем RED/BLU, прячем кнопку."""
        self._force_team = True
        if hasattr(self, 'btn_make_team'):
            self.btn_make_team.setVisible(False)
        self.btn_red.setVisible(True)
        self.btn_blu.setVisible(True)
        self._active_team = Team.RED
        self._sync_variant_buttons()

    def get_force_team(self) -> bool:
        """Включён ли режим «сделать командным» (для BuildRequest.force_team)."""
        return bool(getattr(self, '_force_team', False))

    # ═══════════════════════════════════════════════════════════════════════════
    # Маски маскировки шпиона
    # ═══════════════════════════════════════════════════════════════════════════

    def _sync_spy_mask_buttons(self) -> None:
        """Видимость селекторов масок = режим масок активен. Единая точка —
        вызывать после любого перехода режима, чтобы кнопки не «залипали»."""
        vis = self._pstate.is_spy_masks
        for _cls_key, _btn in self._spy_mask_buttons:
            _btn.setVisible(vis)

    def set_spy_mask_mode(self, enabled: bool) -> None:
        """Включает/выключает режим масок шпиона (показывает кнопки классов)."""
        if enabled:
            self._pstate.enter(PreviewMode.SPY_MASKS)
        elif self._pstate.is_spy_masks:
            self._pstate.reset()
        self._sync_spy_mask_buttons()
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
        user_tex = self._textures.get(Team.RED, {}).get(vtf_name)
        if user_tex and os.path.exists(user_tex):
            from PySide6.QtCore import QTimer
            # Маска в SMD называется "mask_spy" — применяем к этому слоту
            QTimer.singleShot(100, lambda p=user_tex:
                              self._3d_widget.apply_material_map({'mask_spy': p}))
            return

        # Нет пользовательской текстуры — извлекаем из VPK в фоне (общий воркер).
        out_dir = os.path.join('tools', 'temp', 'spy_mask_preview')
        w = _SpyMaskVtfWorker(
            [vtf_name],
            [getattr(self, '_current_textures_vpk', None),
             getattr(self, '_current_misc_vpk', None)],
            out_dir, parent=self,
        )
        w.one.connect(lambda _n, png: self._3d_widget.apply_material_map({'mask_spy': png}))
        w.start()
        if not hasattr(self, '_mask_workers'):
            self._mask_workers = []
        self._mask_workers.append(w)

    def _toggle_misc(self) -> None:
        """Переключает просмотр «Прочее» — служебные (блэклист) текстуры.

        В режиме «Прочее» показываем карточки служебных материалов (их
        оригинальные игровые текстуры как превью), чтобы пользователь мог при
        желании заменить. Выход — возвращает обычные карточки. Главный материал
        (_main_material_name) сохраняется отдельно, поэтому сборка не путается.
        """
        if not self._misc_materials:
            return
        self._misc_mode = not self._misc_mode
        # «Прочее» — просмотр обычных (не вариантных) текстур: активный
        # австралий гасим, как это делает и переключение команды.
        self._australium_active = False
        self._sync_variant_buttons()
        if self._misc_mode:
            # Запоминаем обычный набор и показываем служебные карточки.
            self._cards_before_misc = list(self._material_names)
            self._set_material_slots(self._misc_materials, force_cards=True)
        else:
            # Возврат к обычным карточкам и текстурам активной команды.
            restore = self._cards_before_misc or [self._main_material_name or '']
            self._set_material_slots([m for m in restore if m])
            self._restore_team_textures_2d(self._active_team)
        if self._3d_available and self._3d_widget:
            self._restore_team_textures_3d(self._active_team)

    def get_main_material(self) -> Optional[str]:
        """Стабильное имя главного материала независимо от режима «Прочее».

        Сборка использует его, чтобы исключить главную текстуру из доп-слотов
        (она идёт отдельным from_path), даже когда в 2D открыт просмотр «Прочее»
        и _material_names временно содержит служебные материалы."""
        return self._state.stable_main()

    # ═══════════════════════════════════════════════════════════════════════════
    # Мини-память последнего оружия
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Память правок по стилям шапки (capture/restore вокруг смены модели) ── #

    def capture_edit_state(self) -> dict:
        """Снимок пользовательских правок текущего стиля (текстуры/SMD/VTF)."""
        return {
            'textures': {t: dict(d) for t, d in self._textures.items()},
            'image_path': self.image_path,
            'custom_smd': self._custom_smd_path,
            'custom_keep': getattr(self, '_custom_keep_materials', False),
            'vtf_path': self.vtf_path,
        }

    def edit_state_has_content(self, st: Optional[dict] = None) -> bool:
        """Есть ли в снимке реальные правки (для маркера «●» и сборки)."""
        st = st or self.capture_edit_state()
        if st.get('custom_smd') or st.get('vtf_path'):
            return True
        for d in (st.get('textures') or {}).values():
            if any(p and os.path.exists(p) for p in d.values()):
                return True
        ip = st.get('image_path')
        return bool(ip and os.path.exists(ip))

    def set_pending_edit_state(self, state: Optional[dict]) -> None:
        """Правки стиля, которые применятся ПОСЛЕ загрузки его модели."""
        self._pending_edit_state = state

    def trigger_pending_load(self) -> None:
        """Авто-загрузка модели текущего стиля (как клик ▶), без ручного нажатия.

        Если у стиля сохранена КАСТОМНАЯ модель — грузим сразу её (без захода
        через игровую). Иначе грузим игровую модель из отложенных параметров;
        отложенные текстуры применятся в обработчике готовности."""
        if not (self._3d_available and self._3d_widget):
            return
        st = self._pending_edit_state
        _smd = (st or {}).get('custom_smd')
        if st and _smd and os.path.exists(_smd):
            # Кастомная модель стиля: применяем текстуры/картинку и грузим её напрямую.
            self._pending_edit_state = None
            self._textures = {t: dict(d) for t, d in (st.get('textures') or {}).items()}
            self.image_path = st.get('image_path')
            self.vtf_path = st.get('vtf_path')
            self._load_custom_smd_file(_smd, keep_materials=bool(st.get('custom_keep')))
            # Текстуры стиля поверх кастомной модели + обновление 2D.
            self._refresh_views_after_style_restore()
            return
        # Свежий стиль — грузим игровую модель (правки применит _apply_pending_edit_state).
        # Флаг ставим ПОСЛЕ старта: _start_3d_worker его сбрасывает в начале.
        if self._pending_3d_params:
            self._start_3d_worker(*self._pending_3d_params)
            self._pending_2d_refresh = True

    def _apply_pending_edit_state(self) -> None:
        """Применяет отложенные правки стиля к свежезагруженной модели.

        Устойчиво к обоим случаям: мульти-материал (карточки → _textures) и
        одиночная текстура (image_path)."""
        st = self._pending_edit_state
        self._pending_edit_state = None
        # Флаг НЕ потребляем здесь: метод вызывается и из _on_3d_ready, и из
        # _on_3d_multi_material; данные текстуры (_vpk_red_tex_map) часто готовы
        # лишь ко второму, поэтому 2D надо обновить в ОБОИХ. Флаг сбрасывает
        # _start_3d_worker при следующей загрузке.
        refresh_2d = self._pending_2d_refresh
        if not st and not refresh_2d:
            return
        if st:
            self._textures = {t: dict(d) for t, d in (st.get('textures') or {}).items()}
            self.image_path = st.get('image_path')
            self.vtf_path = st.get('vtf_path')

            # Если у стиля была загружена КАСТОМНАЯ модель — перезагружаем её геометрию
            # (тихо, без диалога), иначе в 3D осталась бы игровая модель стиля.
            _smd = st.get('custom_smd')
            if _smd and os.path.exists(_smd):
                self._load_custom_smd_file(_smd, keep_materials=bool(st.get('custom_keep')))
                self._refresh_views_after_style_restore()
                return
            self._custom_smd_path = None

        # Единое надёжное обновление обеих вкладок (3D + 2D) из восстановленного
        # состояния — вместо разрозненных таймеров.
        self._refresh_views_after_style_restore()

    def _refresh_views_after_style_restore(self, delay_ms: int = 450) -> None:
        """Надёжно обновляет ОБЕ вкладки после восстановления/загрузки стиля.

        Переиспользует проверенные пути: _reapply_textures_to_3d (как при входе в
        3D) и _restore_team_textures_2d/_rebuild_cards_for_skin (как при входе в
        2D). Применяем к обеим: активная вкладка показывает текстуры стиля сразу,
        неактивная готова к переключению. Выполняется по подтверждению загрузки
        модели из JS; delay_ms — fallback-предел (как старая фикс-задержка)."""

        def _do():
            # 3D: восстановленные текстуры поверх загруженной модели (как 2D→3D).
            if self._3d_available and self._3d_widget:
                self._reapply_textures_to_3d(delay_ms=0)
            # 2D: если открыта — показываем текстуры стиля (как клик по кнопке 2D).
            if self.view_stack.currentIndex() == 0:
                if self._original_skin_info and self._active_skin != 0:
                    self._rebuild_cards_for_skin(self._active_skin)
                else:
                    self._restore_team_textures_2d(self._active_team)

        self._run_after_model_load(_do, fallback_ms=delay_ms)

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
        # Состояние панели уже не принадлежит уходящему режиму (напр. выбор
        # шапки вызывает update_extra_slots → _begin_new_weapon ДО set_3d_params,
        # и _state уже вычищен) — снимать нечего, иначе запомним пустоту.
        if self._weapon_mode != outgoing_mode:
            return None
        obj_path = self._cur_obj[1]
        if not obj_path or not os.path.exists(obj_path):
            return None

        # Данные текстур — снимком модели; остальное — виджетные поля.
        return {
            'mode': outgoing_mode,
            'weapon_key': self._weapon_key,
            'obj_path': obj_path,
            'texture_path': self._cur_obj[2],
            'has_blu': self._has_blu,
            'image_path': self.image_path,
            'team_framerate': self._team_framerate,
            'state': self._state.snapshot(),
        }

    def _restore_from_memory(self, data: dict) -> None:
        """Мгновенно восстанавливает оружие из снимка (без перезапуска воркера)."""
        # Сначала восстанавливаем модель текстур — _set_material_slots читает
        # её через _resolve_card_texture при пересоздании карточек.
        # (restore() выключает австралий — после возврата вариант неактивен.)
        self._state.restore(data['state'])
        self.image_path = data['image_path']
        self._has_blu = data['has_blu']
        self._team_framerate = data.get('team_framerate', 0.0)

        # Ключ/режим оружия — как в снимке: последующий update_extra_slots
        # увидит «то же оружие» и не затрёт восстановленное состояние.
        self._weapon_key = data.get('weapon_key', self._weapon_key)
        self._weapon_mode = data['mode']

        # Пересоздаём карточки слотов (метод сам выставит _card_mode/_material_names)
        self._set_material_slots(list(data['state'].get('material_names') or []))

        # Командные и Australium кнопки (учитывают восстановленное состояние)
        self._sync_variant_buttons()
        self._update_team_btn_visibility()

        # Мгновенно грузим модель — obj уже на диске, воркер не нужен
        if self._3d_widget and data['obj_path'] and os.path.exists(data['obj_path']):
            self._3d_widget.load_model_files(data['obj_path'], data['texture_path'])
            self._cur_obj = (data['mode'], data['obj_path'], data['texture_path'])
            # Пользовательские текстуры поверх — по подтверждению загрузки из JS.
            self._run_after_model_load(
                lambda: self._restore_team_textures_3d(self._active_team),
                fallback_ms=300)

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
        # Обычная игровая модель — гасим спец-режимы (custom/critHIT/death).
        if self._pstate.mode in (PreviewMode.CUSTOM, PreviewMode.CRITHIT, PreviewMode.DEATH):
            self._pstate.reset()
        self._death_default_tex = ''
        # Сохраняем VPK пути — нужны для _switch_spy_mask
        self._current_misc_vpk = misc_vpk_path
        self._current_textures_vpk = textures_vpk_path

        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()

        # ── Возврат на запомненное оружие → мгновенное восстановление ─────── #
        if self._mem_mode is not None and self._mem_mode == mode and self._mem_data is not None:
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
        # Обычная игровая модель — гасим спец-режимы (custom/critHIT/death).
        if self._pstate.mode in (PreviewMode.CUSTOM, PreviewMode.CRITHIT, PreviewMode.DEATH):
            self._pstate.reset()
        self._death_default_tex = ''
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
        # Обычная игровая модель — гасим спец-режимы (custom/critHIT/death).
        if self._pstate.mode in (PreviewMode.CUSTOM, PreviewMode.CRITHIT, PreviewMode.DEATH):
            self._pstate.reset()
        self._death_default_tex = ''
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
        if enabled:
            self._pstate.enter(PreviewMode.CUSTOM)
        elif self._pstate.is_custom:
            self._pstate.reset()
        # Кастомная модель — не режим масок: прячем селекторы масок шпиона.
        self._sync_spy_mask_buttons()
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
        self._sync_variant_buttons()
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
        # Подсветка (австралий гасит команды и наоборот) — из единой точки.
        self._sync_variant_buttons()
        from PySide6.QtCore import QTimer
        if self._australium_active:
            # Своя текстура приоритетнее игрового gold-кадра (единый резолвер).
            tex = self._variant_display_texture()
            QTimer.singleShot(50, lambda t=tex: self._3d_widget.update_texture_file(t))
            self._show_variant_in_2d(tex)
        else:
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
                self._textures.setdefault(Team.RED, {})[mat] = path
                self._textures.setdefault(Team.BLU, {})[mat] = path
            else:
                self._textures.get(Team.RED, {}).pop(mat, None)
                self._textures.get(Team.BLU, {}).pop(mat, None)
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

    # ═══════════════════════════════════════════════════════════════════════════
    # Материальные слоты (карточки в 2D)
    # ═══════════════════════════════════════════════════════════════════════════

    def _begin_new_weapon(self, weapon_key: str, mode: str) -> None:
        """ЕДИНАЯ точка полного сброса состояния при смене оружия.

        Идемпотентна и не зависит от порядка вызова set_3d_params /
        update_extra_slots: сбрасывает и пользовательское состояние
        (текстуры/стили/оверрайды), и командные VPK-данные с вариантом
        (через _reset_team_vpk_state — повторный вызов безвреден).
        """
        self._weapon_key = weapon_key
        self._weapon_mode = mode

        # ── Пользовательское состояние предыдущего оружия ─────────────────── #
        self._textures = {Team.RED: {}, Team.BLU: {}}
        self._hand_blu_chosen = set()   # выбранные через «+» нейтральные на BLU
        self._material_names = []
        self._main_material_name = None
        self._has_blu = False
        # «Прочее» предыдущего оружия недействительно (пересоберёт
        # _on_3d_multi_material после загрузки новой модели).
        self._misc_materials = []
        self._misc_mode = False
        self._cards_before_misc = []
        if hasattr(self, 'btn_misc'):
            self.btn_misc.setVisible(False)
        self.image_path = None
        self.vtf_path = None
        self._gif_cache = {}
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self._custom_smd_path = None   # сменили оружие — забываем кастомную модель
        self._custom_keep_materials = False
        self._custom_qc_text = None
        if hasattr(self, 'btn_edit_qc'):
            self.btn_edit_qc.setVisible(False)
        self._reset_skin_state()       # и стили оригинала
        self._tex_overrides = {}       # и пер-текстурные настройки (материалы другие)
        self._tex_maps = {}            # и пер-текстурные карты
        _sp = getattr(self.parent, 'settings_panel', None)   # и выходим из режима их редактирования
        if _sp is not None and hasattr(_sp, 'exit_texture_edit'):
            _sp.exit_texture_edit(restore=True)

        # ── Командные VPK-данные, вариант Australium, кнопки ──────────────── #
        # Раньше это делал только set_3d_params и update_extra_slots полагался
        # на порядок вызова (отсюда залипал австралий/кнопки при смене оружия).
        self._reset_team_vpk_state()
        self._stop_gif()

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
            import base64 as _b64
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
                        self._textures.setdefault(Team.RED, {})[vtf_name] = tmp
                        self._on_extra_card_changed(vtf_name, tmp)
                return

            # ── critHIT / эффект смерти ───────────────────────────────────── #
            # Дроп ведём через обычный load_image (БЕЗ _from_3d_drop): он выставит
            # image_path, обновит 2D и перерисует сцену с правильным роутингом
            # (death → текстура на модель, crit → billboard). С _from_3d_drop
            # повторное применение в 3D пропускалось, и текстура «зависала» на
            # billboard, пока не переключишь 2D↔3D.
            if self._crithit_mode:
                self.load_image(tmp)
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
        self._custom_vpk_mode = False
        self._applied_3d_tex = {}   # webview перезагружается → состояние сбрасываем
        self._team_framerate = 0.0
        # Данные команд и вариант — одним сбросом в модели.
        self._state.reset_team_data()
        self._state.reset_australium()
        if hasattr(self, 'btn_red'):
            self.btn_red.setVisible(False)
        if hasattr(self, 'btn_blu'):
            self.btn_blu.setVisible(False)
        # Сбрасываем «+ Команда» (force_team) — покажется снова при загрузке модели.
        self._force_team = False
        if hasattr(self, 'btn_make_team'):
            self.btn_make_team.setVisible(False)
        if hasattr(self, 'btn_aus'):
            self.btn_aus.setVisible(False)
        self._sync_variant_buttons()
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
