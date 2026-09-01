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
from src.domain.preview.mode import PreviewMode, PreviewState
from src.app.preview_controller import Preview3DController
from src.domain.preview.session import PreviewSession

#: Подписи анимаций в выборе вида от первого лица. Ключи — имена Action из
#: weapon_anim_catalog; чего нет в таблице, показывается как есть.
_FP_ACTION_LABELS = {
    'IDLE':           {'ru': 'Покой',          'en': 'Idle'},
    'DRAW':           {'ru': 'Достать',        'en': 'Draw'},
    'HOLSTER':        {'ru': 'Убрать',         'en': 'Holster'},
    # Нейтрально: у стрелкового это выстрел, у ножа и биты — удар.
    'FIRE':           {'ru': 'Атака',          'en': 'Attack'},
    'ALT_FIRE':       {'ru': 'Альт. атака',    'en': 'Alt attack'},
    'RELOAD':         {'ru': 'Перезарядка',    'en': 'Reload'},
    'RELOAD_START':   {'ru': 'Перезарядка: начало', 'en': 'Reload start'},
    'RELOAD_FINISH':  {'ru': 'Перезарядка: конец',  'en': 'Reload finish'},
    'INSPECT_START':  {'ru': 'Осмотр: начало', 'en': 'Inspect start'},
    'INSPECT_IDLE':   {'ru': 'Осмотр',         'en': 'Inspect'},
    'INSPECT_END':    {'ru': 'Осмотр: конец',  'en': 'Inspect end'},
}
# Единый источник правды о текстурах превью (команды/стили/вариант) — см. модуль.
from src.domain.preview.texture_state import PreviewTextureState

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
from src.ui.preview_skybox_mixin import PreviewSkyboxMixin
from src.ui.preview_material_cards_mixin import PreviewMaterialCardsMixin


def vtf_bytes(width: int, height: int, fmt: str, flags, bpp_table) -> int:
    """Сколько примерно займёт готовый VTF.

    Мип-уровни добавляют примерно треть: 1 + 1/4 + 1/16 + ... = 4/3. Флаг
    NOMIP их отключает. Блочные форматы (DXT) считаем по битам на пиксель —
    для сторон, кратных четырём, это точно.
    """
    bits = bpp_table.get(fmt, 32)
    base = width * height * bits // 8
    return base if 'NOMIP' in (flags or ()) else base * 4 // 3


def human_size(num_bytes: int) -> str:
    """Байты человеку: КБ до мегабайта, дальше МБ с одним знаком."""
    kb = num_bytes / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    return f"{kb / 1024:.1f} MB"


class PreviewPanel(Preview3DMixin, PreviewSkinsMixin, PreviewCustomModelMixin,
                   PreviewTeamMixin, Preview2DImageMixin, PreviewCritHitMixin,
                   PreviewSkyboxMixin, PreviewMaterialCardsMixin, QWidget):
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

        # ── ЕДИНЫЙ источник правды о сеансе превью ────────────────────────── #
        # Всё, что панель ПОМНИТ (в отличие от того, что рисует), живёт в
        # PreviewSession (src/domain/preview/session.py): текстуры, режим,
        # кастомная модель, «Прочее», командные кадры. Старые имена полей
        # (_state, _pstate, _textures, _misc_mode, _custom_smd_path и т.п.) —
        # property-делегаты ниже, чтобы точки обращения не переписывать.
        self._session = PreviewSession()
        # «Сделать командным»: пользователь включил синтез BLU у некомандного оружия.
        self._force_team: bool = False

        # ── Слоты материалов (виджеты) ─────────────────────────────────────── #
        # _material_names заполняется после загрузки 3D (_on_3d_multi_material);
        # для рук — сразу из HAND_MODES. [0] = главный, [1:] = дополнительные.
        self._card_mode: bool = False
        self._has_blu: bool = False

        # ── «Прочее»: служебные материалы (глаза/убер/зомби), скрытые блэклистом ─ #
        # Их можно опционально отредактировать через отдельный селектор-тоггл.
        self._skin_worker = None
        self._skin_buttons: List[QPushButton] = []
        self._skin_button_indices: List[int] = []   # сырой индекс скина на кнопку
        # Режим загруженного custom-VPK мода: карточки строятся из VTF мода
        # (_on_vpk_mod_cards_ready). Защищает их от перетирания обычной
        # фильтрацией материалов модели в _on_3d_multi_material.
        # Пер-текстурные оверрайды настроек: {material: {size,format,flags,options}}.
        # Есть запись ⟺ у материала свои настройки (иначе — глобальные).
        # Хранятся в сеансе — оттуда же их берёт веб-представление.
        # Пер-текстурные файловые карты: {material: {map_id: spec}} из
        # MaterialMapsDialog. Хранятся в сеансе — тем же полем пользуется
        # веб-представление, и сборка берёт их из одного места.

        # ── 2D состояние ──────────────────────────────────────────────────── #
        # image_path — путь к активному изображению (None если не загружено)
        self.image_path: Optional[str] = None
        self.vtf_path: Optional[str] = None
        self._gif_movie = None
        self._gif_orig_size = None

        # ── 3D состояние ──────────────────────────────────────────────────── #
        self._3d_widget = None
        # Загрузку игровой модели ведёт контроллер (src/app): он держит воркер
        # и применяет к сессии всё, что следует из его сигналов, ДО того как
        # об этом узнает панель. Здесь остаётся только показ.
        self._preview3d = Preview3DController(self._session)
        self._connect_preview3d()
        #: Воркер режима QC-карточек — единственный путь, который ещё держит
        #: воркер сам (см. _start_qc_cards_worker).
        self._3d_worker = None
        self._fp_worker = None   # воркер вида от первого лица
        #: Собранные сцены: {(режим, вид, действие): {obj_path, textures, editable}}.
        #: Переключение видов не должно пересобирать геометрию заново.
        self._scene_cache: dict = {}
        #: Какую анимацию показываем в виде от первого лица (имя Action).
        self._fp_action: str = 'IDLE'
        #: Что умеет оружие каждого режима: {режим: [имя Action]}. Список
        #: приносит воркер, но показывать выбор надо и тогда, когда сцену взяли
        #: из кэша и воркер не запускался (см. _update_fp_action_combo).
        self._fp_actions: Dict[str, list] = {}
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
    # Делегаты сеанса (единый источник — self._session)
    #
    # Поля переехали в PreviewSession, но обращений к ним в панели и миксинах
    # сотни; делегаты позволяют держать состояние в домене, не переписывая
    # каждую точку. Новый код лучше писать сразу через self._session.
    # ═══════════════════════════════════════════════════════════════════════════

    @property
    def _state(self) -> PreviewTextureState:
        """Состояние текстур сеанса."""
        return self._session.textures

    @property
    def _pstate(self) -> PreviewState:
        """Режим превью сеанса."""
        return self._session.mode

    @property
    def _misc_materials(self):
        return self._session.misc_materials

    @_misc_materials.setter
    def _misc_materials(self, value) -> None:
        self._session.misc_materials = value

    @property
    def _misc_mode(self):
        return self._session.misc_mode

    @_misc_mode.setter
    def _misc_mode(self, value) -> None:
        self._session.misc_mode = value

    @property
    def _cards_before_misc(self):
        return self._session.cards_before_misc

    @_cards_before_misc.setter
    def _cards_before_misc(self, value) -> None:
        self._session.cards_before_misc = value

    @property
    def _skin_chosen(self):
        return self._session.skin_chosen

    @_skin_chosen.setter
    def _skin_chosen(self, value) -> None:
        self._session.skin_chosen = value

    @property
    def _tex_overrides(self) -> Dict[str, dict]:
        return self._session.texture_overrides

    @_tex_overrides.setter
    def _tex_overrides(self, value) -> None:
        self._session.texture_overrides = value

    @property
    def _tex_maps(self) -> Dict[str, dict]:
        return self._session.texture_maps

    @_tex_maps.setter
    def _tex_maps(self, value) -> None:
        self._session.texture_maps = value

    @property
    def _custom_vpk_mode(self):
        return self._session.custom_vpk_mode

    @_custom_vpk_mode.setter
    def _custom_vpk_mode(self, value) -> None:
        self._session.custom_vpk_mode = value

    @property
    def _custom_obj_path(self):
        return self._session.custom_obj_path

    @_custom_obj_path.setter
    def _custom_obj_path(self, value) -> None:
        self._session.custom_obj_path = value

    @property
    def _custom_model_materials(self):
        return self._session.custom_model_materials

    @_custom_model_materials.setter
    def _custom_model_materials(self, value) -> None:
        self._session.custom_model_materials = value

    @property
    def _applied_3d_tex(self):
        return self._session.applied_3d_tex

    @_applied_3d_tex.setter
    def _applied_3d_tex(self, value) -> None:
        self._session.applied_3d_tex = value

    @property
    def _pending_2d_refresh(self):
        return self._session.pending_2d_refresh

    @_pending_2d_refresh.setter
    def _pending_2d_refresh(self, value) -> None:
        self._session.pending_2d_refresh = value

    @property
    def _custom_smd_path(self):
        return self._session.custom_smd_path

    @_custom_smd_path.setter
    def _custom_smd_path(self, value) -> None:
        self._session.custom_smd_path = value

    @property
    def _custom_keep_materials(self):
        return self._session.custom_keep_materials

    @_custom_keep_materials.setter
    def _custom_keep_materials(self, value) -> None:
        self._session.custom_keep_materials = value

    @property
    def _custom_qc_text(self):
        return self._session.custom_qc_text

    @_custom_qc_text.setter
    def _custom_qc_text(self, value) -> None:
        self._session.custom_qc_text = value

    @property
    def _team_framerate(self):
        return self._session.team_framerate

    @_team_framerate.setter
    def _team_framerate(self, value) -> None:
        self._session.team_framerate = value

    @property
    def _blu_matches_red(self):
        return self._session.blu_matches_red

    @_blu_matches_red.setter
    def _blu_matches_red(self, value) -> None:
        self._session.blu_matches_red = value


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
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root.addWidget(self._build_toggle_bar())

        self.view_stack = QStackedWidget()
        self.view_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.page_2d = self._build_2d_page()
        self.view_stack.addWidget(self.page_2d)
        # page_3d добавляется в _init_3d_widget

        root.addWidget(self.view_stack, 1)
        root.addWidget(self._build_info_panel())

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
        # Вид от первого лица: руки класса с оружием, как в игре.
        self.btn_fp = QPushButton("FP")
        for _b in (self.btn_3d, self.btn_2d, self.btn_fp):
            _b.setFixedHeight(26)
            _b.setStyleSheet(self._btn_style_inactive)
        self.btn_3d.setStyleSheet(self._btn_style_active)
        self.btn_fp.setToolTip(
            'Вид от первого лица' if self._lang == 'ru' else 'First-person view')
        self.btn_fp.setVisible(False)   # только для оружия (см. _update_fp_button)
        self.btn_3d.clicked.connect(self._switch_to_3d)
        self.btn_2d.clicked.connect(self._switch_to_2d)
        self.btn_fp.clicked.connect(self._switch_to_fp)
        lay.addWidget(self.btn_3d)
        lay.addWidget(self.btn_fp)
        lay.addWidget(self.btn_2d)

        # Выбор анимации — только в виде от первого лица; наполняется тем, что
        # это оружие действительно умеет (см. _on_fp_actions_available).
        from PySide6.QtWidgets import QComboBox
        self.fp_action_combo = QComboBox()
        self.fp_action_combo.setFixedHeight(26)
        self.fp_action_combo.setMinimumWidth(130)
        self.fp_action_combo.setVisible(False)
        self.fp_action_combo.currentIndexChanged.connect(self._on_fp_action_chosen)
        lay.addWidget(self.fp_action_combo)

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
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vlay = QVBoxLayout(page)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        _border = "border:1px solid #333; border-radius:4px; background:#1a1a1a;"

        # Пустое состояние
        self.empty_state = QWidget()
        self.empty_state.setMinimumHeight(240)
        self.empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.empty_state.setMinimumWidth(440)
        self.empty_state.setObjectName("dropZone")
        self.empty_state.setStyleSheet(f"#dropZone {{ {_border} }}")
        self.empty_state.setAcceptDrops(True)
        e_lay = QVBoxLayout(self.empty_state)
        e_lay.setAlignment(Qt.AlignCenter)
        e_lay.setSpacing(16)

        self.empty_text = QLabel(self.t['drag_text'])
        self.empty_text.setStyleSheet(
            "border:none; background:transparent;"
            " color:#666; font-size:14px; font-weight:300;")
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
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview.setMinimumSize(440, 240)
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

    #: Бит на пиксель для форматов VTF. Чего нет в таблице — считаем 32.
    _VTF_BPP = {
        'DXT1': 4, 'DXT1 With One Bit Alpha': 4,
        'DXT3': 8, 'DXT5': 8, 'I8': 8, 'A8': 8,
        'IA88': 16, 'UV88': 16, 'RGB565': 16, 'BGR565': 16,
        'BGRX5551': 16, 'BGRA5551': 16, 'BGRA4444': 16,
        'RGB888': 24, 'BGR888': 24,
        'RGB888 Bluescreen': 24, 'BGR888 Bluescreen': 24,
        'RGBA16161616F': 64, 'RGBA16161616': 64,
    }

    def _build_info_panel(self) -> QWidget:
        """Сводка о будущем VTF — таблицей в две пары колонок.

        Стиль вешается на #infoPanel, а НЕ на QWidget: селектор по типу бьёт
        по всем потомкам, и каждая QLabel получала собственную рамку — именно
        так сводка когда-то и превратилась в пять коробок вместо одной.
        """
        from PySide6.QtWidgets import QGridLayout

        panel = QWidget()
        panel.setObjectName("infoPanel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        panel.setMinimumWidth(440)
        panel.setStyleSheet(
            "#infoPanel { background:rgba(255,255,255,0.02);"
            " border:1px solid #262626; border-radius:4px; }"
            " QLabel { border:none; background:transparent; }")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 11, 14, 13)
        lay.setSpacing(10)

        self.info_title = QLabel(self.t['info_title'])
        self.info_title.setStyleSheet(
            "font-size:10px; font-weight:600; letter-spacing:1px; color:#666;"
            " padding-bottom:9px; border-bottom:1px solid #1e1e1e;")
        lay.addWidget(self.info_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        grid.setContentsMargins(0, 0, 0, 0)

        # (атрибут значения, ключ подписи, строка, пара) — левая пара и правая
        rows = [
            ('info_resolution', 'info_resolution', 0, 0),
            ('info_source',     'info_source',     0, 1),
            ('info_format',     'info_format',     1, 0),
            ('info_weight',     'info_weight',     1, 1),
            ('info_flags',      'info_flags',      2, 0),
            ('info_filename',   'info_filename',   2, 1),
        ]
        self._info_captions = {}
        for attr, key, row, pair in rows:
            cap = QLabel("")
            cap.setStyleSheet("font-size:11px; color:#484848;")
            val = QLabel("")
            val.setStyleSheet("font-size:12px; color:#c8c8c8;")
            grid.addWidget(cap, row, pair * 2)
            grid.addWidget(val, row, pair * 2 + 1)
            self._info_captions[key] = cap
            setattr(self, attr, val)

        # Значения тянутся, подписи держат свою ширину — колонки выравниваются
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)

        self.info_summary = panel
        return panel

    def _init_3d_widget(self) -> None:
        from src.ui.preview_3d_widget import Preview3DWidget, is_webengine_available
        self._3d_available = is_webengine_available()
        self._3d_widget = Preview3DWidget.create(self)
        self._3d_widget.set_language(self._lang)

        qt_w = self._3d_widget.qt_widget
        qt_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        qt_w.setMinimumHeight(300)
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
        show = self.is_3d_mode() and not self._crithit_mode and not self._pstate.is_skybox
        # В виде от первого лица кнопки загрузки не при чём: сцену собирает
        # свой воркер, а подменять модель в руках нечем.
        show_load = show and not self._pstate.is_first_person
        self.btn_load_3d.setVisible(show_load)
        self.btn_load_vpk.setVisible(show_load)
        self._update_fp_button()
        # Выбор анимации — часть того же тулбара, и живёт по тем же правилам.
        self._update_fp_action_combo()
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
            self.btn_replace_model.setVisible(show_load and not is_player_body)

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
        self._leave_first_person()
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
        was_first_person = self._pstate.is_first_person
        restored = self._leave_first_person()
        self.view_stack.setCurrentIndex(1)
        self.btn_3d.setStyleSheet(self._btn_style_active)
        self.btn_2d.setStyleSheet(self._btn_style_inactive)
        self._update_3d_buttons_visibility()

        # В сцене стояла вьюмодель. Обычная модель уже собрана и лежит на
        # диске — её вернул сам выход из режима; воркер нужен, только если
        # файла нет.
        if was_first_person:
            if restored:
                return
            if self._pending_3d_params:
                self._start_3d_worker(*self._pending_3d_params)
                return

        if self._crithit_mode:
            if self._3d_available:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, self._render_crithit_scene)
            return

        if self._pstate.is_skybox:
            if self._3d_available:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, self._render_skybox_scene)
            return

        self.btn_load_vpk.setEnabled(True)
        self._update_team_btn_visibility()

        # Переприменяем текущие текстуры к 3D если они загружены
        # (например, пользователь переключился в 2D, загрузил текстуру, вернулся в 3D)
        self._reapply_textures_to_3d()

    # ── Вид от первого лица ──────────────────────────────────────────────── #

    def _switch_to_fp(self) -> None:
        """Показывает оружие в руках класса — так, как его видит игрок."""
        if self._3d_widget is None or not self._pending_3d_params:
            return
        from src.services.viewmodel_scene import VIEWMODEL_RIG
        self._pstate.enter(PreviewMode.FIRST_PERSON)
        self.view_stack.setCurrentIndex(1)
        self.btn_fp.setStyleSheet(self._btn_style_active)
        self.btn_3d.setStyleSheet(self._btn_style_inactive)
        self.btn_2d.setStyleSheet(self._btn_style_inactive)
        self._update_3d_buttons_visibility()
        # Риг ставим здесь, а не в воркере: это состояние вида, и вход в режим
        # обязан быть симметричен выходу (см. _leave_first_person).
        self._3d_widget.set_view_rig(dict(VIEWMODEL_RIG))
        if not self._show_cached_scene():
            self._start_fp_worker(*self._pending_3d_params)

    # ── Кэш собранных сцен ───────────────────────────────────────────────── #
    #
    # Геометрия обычного превью и вида от первого лица разная: в руке у
    # оружия расходятся подвижные части (у дробовика цевьё сдвинуто на 30
    # единиц относительно ствола), так что одним мешем обойтись нельзя. Зато
    # ПЕРЕСОБИРАТЬ её на каждое нажатие незачем — на прогретом кэше это
    # секунда с лишним. Собранный OBJ лежит на диске, и вернуться к нему
    # стоит десятки миллисекунд.
    #
    # Текстуры сюда не входят намеренно: они адресуются по имени материала,
    # имена в обеих сценах одинаковы, и пользовательские накладывает общий
    # _reapply_textures_to_3d.

    #: Сколько сцен держим. Каждая — временная папка с OBJ и PNG, поэтому
    #: память не бесконечная. Четырёх хватает на «потыкать туда-сюда».
    _SCENE_CACHE_LIMIT = 4

    def _fp_action_name(self) -> str:
        """Какое действие сейчас показываем в виде от первого лица."""
        return getattr(self, '_fp_action', 'IDLE')

    def _fp_mode_key(self) -> str:
        """Режим (класс + предмет), к которому относится вид от первого лица."""
        return ((self._pending_3d_params[1] if self._pending_3d_params else None)
                or self._weapon_mode or '')

    def _on_fp_actions_available(self, names: list) -> None:
        """Воркер разобрал модель анимаций класса: вот что умеет это оружие.

        Список приходит из модели анимаций: у одного оружия есть перезарядка,
        у другого только бросок — предлагать одинаковый набор всем значило бы
        обещать несуществующее. Здесь его только ЗАПОМИНАЕМ; показывает список
        _update_fp_action_combo.
        """
        self._fp_actions[self._fp_mode_key()] = list(names or [])
        self._update_fp_action_combo()

    def _update_fp_action_combo(self) -> None:
        """Выбор анимации — чистая функция состояния, а не отклик на сигнал.

        Раньше список наполнялся и показывался ТОЛЬКО из `actions_available`.
        Но воркер запускается не всегда: повторный вход в режим, смена команды
        и возврат к уже показанной анимации берут сцену из кэша — сигнала нет,
        и выпадающий список молча исчезал (его гасит выход из режима). Поэтому
        выученные действия помнятся по режиму, а список строится по ним при
        каждом обновлении тулбара — вместе с остальными его кнопками.
        """
        combo = getattr(self, 'fp_action_combo', None)
        if combo is None:
            return
        names = self._fp_actions.get(self._fp_mode_key()) or []
        if not names or not self._pstate.is_first_person:
            combo.setVisible(False)
            return
        current = self._fp_action_name()
        if current not in names:
            # Действия у оружия разные: перезарядки у биты нет. Оставить
            # выбранным недоступное значит подписать одно, а показать другое —
            # воркер в этом случае берёт первое доступное (см. _find_sequence).
            current = names[0]
            self._fp_action = current
        combo.blockSignals(True)
        combo.clear()
        for name in names:
            combo.addItem(_FP_ACTION_LABELS.get(name, {}).get(
                self._lang, name.replace('_', ' ').title()), name)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)
        combo.setVisible(True)

    def _on_fp_action_chosen(self, index: int) -> None:
        """Смена анимации: сцена другая, поэтому собираем её заново."""
        if index < 0 or not hasattr(self, 'fp_action_combo'):
            return
        name = self.fp_action_combo.itemData(index)
        if not name or name == self._fp_action_name():
            return
        previous = self._fp_action_name()
        self._fp_action = name
        if not (self._pstate.is_first_person and self._pending_3d_params):
            return
        if self._show_cached_scene(name):
            return
        # Сцена того же оружия уже на экране — меняются только дорожки. Полная
        # пересборка распаковывала бы те же самые текстуры заново (замер: около
        # секунды против нескольких миллисекунд). На границе перезарядки так
        # нельзя: там меняется сама геометрия рук (ракета солдата).
        from src.services.viewmodel_worker import same_arms_mesh
        if (self._scene_cache.get(self._scene_cache_key(previous))
                and same_arms_mesh(previous, name)):
            self._start_fp_clip_worker(*self._pending_3d_params)
        else:
            self._start_fp_worker(*self._pending_3d_params)

    def _scene_cache_key(self, action: Optional[str] = None) -> tuple:
        """Ключ сцены: режим (класс + оружие) и что в ней происходит.

        Действие входит в ключ, поэтому покой, перезарядка и осмотр одного
        оружия — разные сцены, и переключение между ними тоже не пересобирает
        уже собранное. Без явного действия берётся текущее. Подменённая модель
        и команда входят туда же: с ними сцена другая, хотя оружие то же.
        """
        mode = (
            (self._pending_3d_params[1] if self._pending_3d_params else None)
            or self._weapon_mode or ''
        )
        # Подменённая модель — другая сцена того же оружия. Без неё в ключе
        # возврат в FP показывал бы сток из кэша поверх кастомной геометрии.
        # Команда — тоже часть сцены: руки у семи классов командные, и их
        # текстуры приходят из воркера вместе с мешем.
        return (mode, 'fp', action or self._fp_action_name(),
                self._custom_smd_path or '', self._active_team)

    def remember_scene(self, obj_path: str, textures: dict, editable: list,
                       animated: Optional[dict] = None,
                       action: Optional[str] = None) -> None:
        """Запоминает собранную сцену, чтобы не пересобирать её при возврате.

        Сцена бывает двух видов: запечённая поза (файл OBJ) и анимация (данные
        скелета с дорожками). Кэшу разница безразлична — он хранит то, чем её
        показали.
        """
        if not animated and (not obj_path or not os.path.exists(obj_path)):
            return
        cache = self._scene_cache
        key = self._scene_cache_key(action)
        cache.pop(key, None)                       # освежаем позицию
        cache[key] = {'obj_path': obj_path,
                      'animated': animated,
                      'textures': dict(textures or {}),
                      'editable': list(editable or [])}
        while len(cache) > self._SCENE_CACHE_LIMIT:
            cache.pop(next(iter(cache)))           # самая давняя

    def _show_cached_scene(self, action: Optional[str] = None) -> bool:
        """Показывает сцену из кэша. False — её там нет, надо собирать.

        Показ идёт напрямую в виджет, а не через слоты воркера: слоты копят
        сцену по кусочкам (сигналы приходят порознь), и прогон кэша через них
        успел бы записать в кэш неполные данные.
        """
        key = self._scene_cache_key(action)
        data = self._scene_cache.get(key)
        if not data or not self._3d_widget:
            return False
        if data.get('animated'):
            self._3d_widget.load_viewmodel_animated(
                data['animated'], editable_mesh_names=list(data['editable']))
        elif not os.path.exists(data['obj_path']):
            self._scene_cache.pop(key, None)       # временную папку убрали
            return False
        else:
            self._3d_widget.load_model_files(
                data['obj_path'], "", normalize=False,
                editable_mesh_names=list(data['editable']))
        if data['textures']:
            self._3d_widget.apply_material_map(dict(data['textures']))
        self._run_after_model_load(
            lambda: self._reapply_textures_to_3d(delay_ms=0), fallback_ms=400)
        return True

    def _restore_plain_model(self) -> bool:
        """Возвращает обычную модель без перезапуска воркера.

        Вход в вид от первого лица состояние панели не трогает — карточки,
        текстуры и команда остаются от обычного превью, а `_cur_obj` всё ещё
        указывает на его OBJ. Значит достаточно снова показать тот файл.
        """
        if not self._3d_widget:
            return False
        # Подменённая модель тоже «обычное превью»: `_cur_obj` о ней не знает
        # (её показывает не воркер, а конвертер SMD), и без этой ветки возврат
        # из вида от первого лица подсовывал бы сток вместо пользовательской.
        custom = self._custom_obj_path
        if self._custom_smd_path and custom and os.path.exists(custom):
            self._3d_widget.load_model_files(custom, self.image_path or '',
                                             editable_mesh_names=[])
            self._run_after_model_load(
                lambda: self._reapply_textures_to_3d(delay_ms=0), fallback_ms=400)
            return True

        cur = self._cur_obj
        mode = (
            (self._pending_3d_params[1] if self._pending_3d_params else None)
            or self._weapon_mode
        )
        if not cur or cur[0] != mode:
            return False
        if not cur[1] or not os.path.exists(cur[1]):
            return False
        # Ограничение мешей снимаем вместе с загрузкой: обычная модель — вся
        # пользовательская, и фильтр от вьюмодели на ней остаться не должен.
        self._3d_widget.load_model_files(cur[1], cur[2], editable_mesh_names=[])
        self._run_after_model_load(
            lambda: self._reapply_textures_to_3d(delay_ms=0), fallback_ms=400)
        return True

    def _leave_first_person(self) -> bool:
        """Возврат к обычному превью: риг, воркер и сама сцена.

        Идемпотентно — вызывается из обоих переключателей вида и при смене
        предмета. Убрать вьюмодель из сцены обязан тот же метод, что её туда
        поставил: раньше это делал только `_switch_to_3d`, и путь FP → 2D → 3D
        (как и переход на шапки) оставлял оружие в руках уже после выхода.

        Returns:
            True — обычная модель уже вернулась в сцену (файл был на диске).
            False — вернуть нечего, решать вызывающему.
        """
        if not self._pstate.is_first_person:
            return False
        self._pstate.reset()
        self._stop_worker('_fp_worker')
        self.btn_fp.setStyleSheet(self._btn_style_inactive)
        if hasattr(self, 'fp_action_combo'):
            self.fp_action_combo.setVisible(False)
        if self._3d_widget:
            self._3d_widget.set_view_rig(None)
        return self._restore_plain_model()

    def _update_fp_button(self) -> None:
        """Кнопка есть только у оружия: у шапок и тел вида от первого лица нет.

        Единая точка — вызывается оттуда же, откуда обновляется видимость
        прочих кнопок 3D-вида.
        """
        if not hasattr(self, 'btn_fp'):
            return
        from src.data.item_kinds import kind_of
        mode = self._fp_mode_key()
        # Подменённую модель вид от первого лица показывает наравне с игровой:
        # сцена собирается тем же слиянием, что и мод. А вот загруженный VPK
        # так не разобрать — там уже скомпилированная MDL, и оружие в нём может
        # быть любым; предлагать по нему руки нечестно.
        custom = self._custom_vpk_mode
        available = (bool(self._pending_3d_params)
                     and kind_of(mode).is_weapon and not custom)
        self.btn_fp.setVisible(available and self._3d_available)
        if not available and self._pstate.is_first_person:
            self._leave_first_person()

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
        _can_force = self._is_force_team_eligible()
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
        """Стоит ли предлагать «сделать командным».

        Правило целиком в домене (PreviewSession.can_force_team): его же
        спрашивает веб-представление, поэтому переписывать его здесь второй раз
        нельзя — разъедется.

        Ключ и режим панель хранит у себя, поэтому передаёт их явно.
        """
        return self._session.can_force_team(self._weapon_key, self._weapon_mode)

    def _enable_force_team(self) -> None:
        """Включает «сделать командным»: показываем RED/BLU, прячем кнопку."""
        self._session.enable_force_team()
        if hasattr(self, 'btn_make_team'):
            self.btn_make_team.setVisible(False)
        self.btn_red.setVisible(True)
        self.btn_blu.setVisible(True)
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
        # Флаг и гашение варианта — правило домена (то же спрашивает веб).
        on = self._session.toggle_misc()
        self._sync_variant_buttons()
        if on:
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
            self._custom_obj_path = None

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
        if not outgoing_mode or outgoing_mode in ('hat', 'spray', 'critHIT',
                                                  'custom', 'skybox'):
            return None
        if (self._spy_mask_mode or self._australium_active
                or self._custom_smd_mode or self._custom_smd_path):
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
        # Сменился предмет — вид от первого лица показывает уже не его. Выходим
        # явно: `_pstate.reset()` ниже снял бы только флаг, оставив в сцене
        # оружие, риг камеры и выбор анимации от прошлого предмета.
        self._leave_first_person()
        # Обычная игровая модель — гасим спец-режимы (custom/critHIT/death/skybox).
        if self._pstate.is_skybox:
            self._exit_skybox_mode()
        if self._pstate.mode in (PreviewMode.CUSTOM, PreviewMode.CRITHIT,
                                 PreviewMode.DEATH, PreviewMode.SKYBOX):
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
        # Обычная игровая модель — гасим спец-режимы (custom/critHIT/death/skybox).
        if self._pstate.is_skybox:
            self._exit_skybox_mode()
        if self._pstate.mode in (PreviewMode.CUSTOM, PreviewMode.CRITHIT,
                                 PreviewMode.DEATH, PreviewMode.SKYBOX):
            self._pstate.reset()
        self._death_default_tex = ''
        self._cur_obj = None   # модель убрана — нечего запоминать
        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._reset_team_vpk_state()
        # Выбора больше нет: кнопка «от первого лица» и выбор анимации обязаны
        # уйти вместе с ним (переход на вкладку шапок оставлял их висеть).
        self._update_3d_buttons_visibility()
        if self._3d_widget:
            self._3d_widget.reset()
        self.btn_load_3d.setEnabled(False)

    def show_3d_no_tf2_message(self) -> None:
        self._pending_3d_params = None
        self._last_3d_params = None
        # Обычная игровая модель — гасим спец-режимы (custom/critHIT/death/skybox).
        if self._pstate.is_skybox:
            self._exit_skybox_mode()
        if self._pstate.mode in (PreviewMode.CUSTOM, PreviewMode.CRITHIT,
                                 PreviewMode.DEATH, PreviewMode.SKYBOX):
            self._pstate.reset()
        self._death_default_tex = ''
        self._cur_obj = None
        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()
        self._update_3d_buttons_visibility()
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
            # Переход из скайбокса: стоп его воркеров + снять фон-кубмапу.
            if self._pstate.is_skybox:
                self._exit_skybox_mode()
            self._pstate.enter(PreviewMode.CUSTOM)
        elif self._pstate.is_custom:
            self._pstate.reset()
        # Кастомная модель — не режим масок: прячем селекторы масок шпиона.
        self._sync_spy_mask_buttons()
        self._pending_3d_params = None
        if not enabled:
            self._custom_smd_path = None   # вышли из режима — забываем модель
            self._custom_obj_path = None
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

        Здесь же проходит граница работы: всё, что человек сделал над ПРОШЛЫМ
        предметом, сохраняется до сброса, а работа нового возвращается после.
        Правила — в work_keeper, общем со страницей.
        """
        # Работа уходящего предмета — пока поля ещё его.
        self.save_work()

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
        self._custom_obj_path = None
        self._custom_keep_materials = False
        self._custom_qc_text = None
        if hasattr(self, 'btn_edit_qc'):
            self.btn_edit_qc.setVisible(False)
        self._reset_skin_state()       # и стили оригинала
        self._state.reset_skybox()     # и грани скайбокса (стоковые/нарезанные)
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

        # Работа над НОВЫМ предметом — после всех сбросов, иначе они бы её и
        # стёрли. Карточки покажут вернувшиеся текстуры, когда приедут
        # материалы модели: разрешение идёт через то же состояние.
        self.restore_work()

    # ═══════════════════════════════════════════════════════════════════════════
    # Работа над предметом (сохранение правок между запусками)
    # ═══════════════════════════════════════════════════════════════════════════

    def _work_key(self) -> str:
        """Ключ работы текущего предмета (пустой — предмет ещё не опознан)."""
        from src.services import work_keeper
        # Показанный мод — это предмет 'custom' (так его называет
        # MainWindow.apply_selection_auto), иначе работа над модом легла бы под
        # ключ оружия, поверх которого он показан, — и разошлась бы со
        # страницей, где ключ считается по тому же правилу.
        mode = 'custom' if self._custom_vpk_mode else (self._weapon_mode or '')
        return work_keeper.key_for(
            mode, self._weapon_key or '',
            getattr(self, '_loaded_vpk_mod_path', '') or '')

    def save_work(self) -> None:
        """Сохраняет правки текущего предмета. Зовётся при смене предмета и
        при закрытии окна — двух моментах, когда работу можно потерять."""
        from src.services import work_keeper
        try:
            work_keeper.save(self._session, self._work_key())
        except Exception as exc:                      # noqa: BLE001
            # Сохранение работы не должно мешать самой работе.
            logger.warning(f"работа не сохранена: {exc}")

    def restore_work(self) -> bool:
        """Возвращает правки предмета в состояние панели."""
        from src.services import work_keeper
        try:
            return work_keeper.restore(self._session, self._work_key())
        except Exception as exc:                      # noqa: BLE001
            logger.warning(f"работа не восстановлена: {exc}")
            return False

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
        movie.setScaledSize(orig.scaled(*self._preview_box(preview_width),
                                        Qt.KeepAspectRatio))
        self._gif_movie = movie
        self.preview.setMovie(movie)
        movie.start()
        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # Сброс командных VPK-данных
    # ═══════════════════════════════════════════════════════════════════════════

    def _sync_team_widgets(self) -> None:
        """Виджетная половина сброса команд: прячет кнопки и карточку варианта.

        Подпись BLU возвращается к обычной, потому что «в стоке не отличается
        от RED» относилось к прошлой модели.
        """
        if hasattr(self, 'btn_blu'):
            self.btn_blu.setToolTip(self.t.get('3d_team_blu_tip', 'BLU team texture'))
            self.btn_blu.setVisible(False)
        if hasattr(self, 'btn_red'):
            self.btn_red.setVisible(False)
        if hasattr(self, 'btn_make_team'):
            self.btn_make_team.setVisible(False)
        if hasattr(self, 'btn_aus'):
            self.btn_aus.setVisible(False)
        self._sync_variant_buttons()
        if self._aus_card is not None:
            self._aus_card.setParent(None)
            self._aus_card.deleteLater()
            self._aus_card = None

    def _reset_team_vpk_state(self) -> None:
        """Забывает командные кадры и вариант, скрывает их кнопки.

        Половинки разделены намеренно: сессия чистит память, панель — виджеты
        (см. _reset_skin_state, там то же разделение).
        """
        self._session.reset_team_frames()
        self._sync_team_widgets()

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
    def _source_size(self):
        """Размеры исходной картинки без её полной распаковки."""
        if not self.image_path or not os.path.exists(self.image_path):
            return None
        from PySide6.QtGui import QImageReader
        sz = QImageReader(self.image_path).size()
        return (sz.width(), sz.height()) if sz.isValid() else None

    def update_info_summary(self) -> None:
        for key, cap in self._info_captions.items():
            cap.setText(self.t[key].rstrip(':'))

        def put(lbl, text, tone="#c8c8c8"):
            lbl.setText(text)
            lbl.setStyleSheet(f"font-size:12px; color:{tone};")

        if not hasattr(self.parent, 'settings_panel'):
            for lbl in (self.info_resolution, self.info_format,
                        self.info_source, self.info_weight):
                put(lbl, "—", "#484848")
            put(self.info_flags, self.t['info_none'], "#484848")
            put(self.info_filename, self.t['info_unset'], "#cc5522")
            return

        s = self.parent.settings_panel.get_settings()
        w, h = s.get('size', (512, 512))
        fmt = s.get('format', 'DXT1')
        flags = s.get('flags', [])

        put(self.info_resolution, f"{w}×{h}")
        put(self.info_format, fmt)
        put(self.info_flags,
            ", ".join(flags) if flags else self.t['info_none'],
            "#c8c8c8" if flags else "#484848")

        fn = s.get('filename', '')
        put(self.info_filename, fn or self.t['info_unset'],
            "#c8c8c8" if fn else "#cc5522")

        # Исходник: меньше цели — значит апскейл и мыло, предупреждаем
        src = self._source_size()
        if src is None:
            put(self.info_source, self.t['info_not_loaded'], "#484848")
        else:
            upscaled = src[0] < w or src[1] < h
            put(self.info_source, f"{src[0]}×{src[1]}",
                "#cc5522" if upscaled else "#c8c8c8")

        put(self.info_weight, human_size(vtf_bytes(w, h, fmt, flags,
                                                   self._VTF_BPP)))

    # ═══════════════════════════════════════════════════════════════════════════
    # Language
    # ═══════════════════════════════════════════════════════════════════════════

    def update_language(self, t: dict, lang: str = 'en') -> None:
        self.t = t
        self._lang = lang
        self.empty_text.setText(t['drag_text'])
        self.select_file_button.setText(t['select_file_btn'])
        self.info_title.setText(t['info_title'])
        self.update_info_summary()
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

    def _preview_box(self, width: int = 0) -> tuple:
        """Прямоугольник, в который вписывается картинка 2D-превью.

        Высота раньше была зашита числом 500 в трёх местах — ровно столько
        же, сколько виджет занимал жёстко. Теперь берём его фактический
        размер, иначе при растяжении окна картинка осталась бы прежней.
        """
        return (max(width, self.preview.width(), 440),
                max(self.preview.height(), 240))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.preview.isVisible():
            return
        from PySide6.QtCore import QTimer

        if self._gif_movie is not None and self._gif_orig_size is not None:
            def _resize_gif():
                self._gif_movie.setScaledSize(
                    self._gif_orig_size.scaled(*self._preview_box(),
                                               Qt.KeepAspectRatio))
            QTimer.singleShot(50, _resize_gif)
        elif self.image_path and os.path.exists(self.image_path):
            def _rescale():
                pix = QPixmap(self.image_path)
                if not pix.isNull():
                    self.preview.setPixmap(pix.scaled(
                        *self._preview_box(),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation))
            QTimer.singleShot(50, _rescale)
