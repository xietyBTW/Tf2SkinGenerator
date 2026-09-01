"""
Фасад 3D-превью: запуск воркера игровой модели и его события.

Зачем слой. Раньше панель сама создавала Preview3DWorker, подключалась к его
девяти сигналам и в каждом обработчике мешала три разные вещи: правку
состояния сеанса, включение кнопок и вызовы 3D-виджета. Чтобы представление
можно было заменить целиком, состояние должно меняться до того, как о событии
узнает тот, кто рисует.

Контракт простой: контроллер владеет воркером, применяет к сессии всё, что
следует из его сигналов, и только потом эмитит СВОЁ событие. Подписчик
(сейчас — Qt-панель, потом — что угодно) занимается исключительно
отображением и про воркеры не знает.

Сигналы взяты из `src/services/base_worker` — того же механизма, на котором
работают воркеры: он без Qt, а доставку в поток UI обеспечивает диспетчер
(`src/ui/qt_dispatch.py`), если он установлен.
"""

from __future__ import annotations

from typing import Optional, Tuple

from src.domain.preview.session import PreviewSession
from src.services.base_worker import Signal
from src.shared.constants import Team
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def split_blu_multi_material(payload) -> Tuple[dict, dict]:
    """
    Разбирает payload сигнала blu_multi_material в (tex_map, name_map).

    Воркер шлёт либо пару (текстуры, имена), либо — в старых ветках — только
    словарь текстур. Разбор вынесен отдельно, потому что от него зависят и
    подписи карточек, и видимость переключателя команд.

    Returns:
        (tex_map, name_map); пустые словари, если payload пуст.
    """
    if not payload:
        return {}, {}
    if isinstance(payload, tuple) and len(payload) == 2:
        tex_map, name_map = payload
        return dict(tex_map or {}), dict(name_map or {})
    return dict(payload), {}


class Preview3DController:
    """Одна загрузка игровой модели в 3D: воркер, сессия, события."""

    # ── События для представления ─────────────────────────────────────────── #
    progress = Signal(str)                  # (текст статуса)
    model_ready = Signal(str, str)          # (obj_path, texture_path)
    animated = Signal(object, float)        # ([кадры RED], framerate)
    materials = Signal(object)              # {материал: png} — многоматериальная
    blu_ready = Signal(object, float)       # ([кадры BLU], framerate)
    blu_materials = Signal(object, object)  # (tex_map, name_map) — уже разобранные
    blu_same_as_red = Signal()              # BLU есть, но в стоке равен RED
    australium_ready = Signal(str, str)     # (png, имя материала)
    render_hints = Signal(object)           # свойства рисования материалов
    cards_ready = Signal(str)               # (texture) — геометрия НЕ трогается
    failed = Signal(str)                    # (текст ошибки)

    def __init__(self, session: PreviewSession):
        self._session = session
        self._worker = None

    # ═══════════════════════════════════════════════════════════════════════ #
    # Управление
    # ═══════════════════════════════════════════════════════════════════════ #

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def stop(self) -> None:
        """Останавливает текущую загрузку, если она идёт."""
        if self._worker is not None:
            self._worker.stop(3000)
            self._worker = None

    def load_game_model(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk: str,
        textures_vpk: str,
        lang: str = 'en',
        geometry: bool = True,
    ) -> None:
        """
        Начинает загрузку обычной игровой модели.

        Предыдущая загрузка останавливается: держать две одновременно нельзя —
        их сигналы перемешались бы в одной сессии.

        Состояние сеанса к этому моменту должно быть уже подготовлено вызовом
        ``PreviewSession.begin_game_model()``: контроллер отвечает за загрузку,
        а не за правила перехода между моделями.

        geometry=False — «только карточки»: в превью уже стоит геометрия
        пользователя, и заменять её оригинальной нельзя, а текстуры и материалы
        из игрового QC нужны (режим «заменить только геометрию»).
        """
        self.stop()

        from src.services.preview_3d_worker import Preview3DWorker
        w = Preview3DWorker(
            weapon_key=weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=lang,
        )
        self._bind(w, mode, geometry)
        self._worker = w
        w.start()

    def _bind(self, w, mode: str, geometry: bool = True) -> None:
        """Подписывает контроллер на сигналы воркера."""
        w.progress.connect(self.progress.emit)
        w.ready.connect(lambda obj, tex: self._on_ready(obj, tex, mode, geometry))
        w.animated.connect(self._on_animated)
        w.multi_material.connect(self._on_multi_material)
        w.blu_ready.connect(self._on_blu_ready)
        w.blu_multi_material.connect(self._on_blu_multi_material)
        w.blu_same_as_red.connect(self._on_blu_same_as_red)
        w.australium_ready.connect(self._on_australium_ready)
        w.render_hints.connect(lambda hints: self.render_hints.emit(hints or {}))
        w.failed.connect(self.failed.emit)

    # ═══════════════════════════════════════════════════════════════════════ #
    # Обработка сигналов воркера: сначала сессия, потом событие
    # ═══════════════════════════════════════════════════════════════════════ #

    def _on_ready(self, obj_path: str, texture_path: str, mode: str,
                  geometry: bool = True) -> None:
        s = self._session
        # Перетаскивание текстуры на конкретный меш относилось к прошлой модели.
        s.per_mesh_active = False
        s.per_mesh_base_image = None
        # Кнопки команд уже сброшены переходом — держим активную команду в тон.
        s.textures.active_team = Team.RED
        if texture_path:
            s.textures.red_frames = [texture_path]
            # Одноматериальная модель: multi_material для неё не придёт вовсе,
            # и без этой записи состояние не знало бы ни одного материала —
            # показывать было бы нечего. Ключ служебный (SINGLE_TEX_KEY), в
            # сборку он не попадает.
            if not s.textures.material_names:
                from src.domain.preview.texture_state import SINGLE_TEX_KEY
                s.textures.material_names = [SINGLE_TEX_KEY]
                s.textures.vpk_red_tex_map = {SINGLE_TEX_KEY: texture_path}
        if not geometry:
            # Геометрия пользовательская — оригинальную не показываем и в
            # current_object не пишем: там должно остаться то, что на экране.
            self.cards_ready.emit(texture_path)
            return
        s.current_object = (mode, obj_path, texture_path)
        self.model_ready.emit(obj_path, texture_path)

    def _on_animated(self, frame_paths: list, framerate: float) -> None:
        """У RED-команды многокадровый VTF."""
        if not frame_paths:
            return
        self._session.textures.red_frames = list(frame_paths)
        self._session.team_framerate = framerate
        self.animated.emit(frame_paths, framerate)

    def _on_blu_ready(self, frame_paths: list, framerate: float) -> None:
        """Нашлась BLU-текстура — у модели есть командный вариант."""
        if not frame_paths:
            return
        self._session.textures.blu_frames = list(frame_paths)
        # Нулевой framerate у BLU означает «кадр один», а не «сбрось скорость»:
        # частота уже могла прийти с RED и относится к обеим командам.
        if framerate > 0:
            self._session.team_framerate = framerate
        self.blu_ready.emit(frame_paths, framerate)

    def _on_australium_ready(self, png_path: str, mat_name: str) -> None:
        """
        Нашёлся вариантный кадр (Australium / Festive / Botkiller).

        Кладём его в сессию, а не просто пересылаем дальше: наличие варианта
        она берёт из australium_frame, и без этого кнопка варианта не
        появлялась ни у одного оружия — сигнал приходил, а состояние о нём
        не знало.
        """
        if not png_path:
            return
        t = self._session.textures
        t.australium_frame = png_path
        t.australium_mat_name = mat_name or None
        self.australium_ready.emit(png_path, mat_name)

    def _on_blu_same_as_red(self) -> None:
        self._session.blu_matches_red = True
        self.blu_same_as_red.emit()

    def _on_multi_material(self, tex_map: dict) -> None:
        if not tex_map:
            return
        from src.domain.preview.material_cards import (
            editable_material_cards, misc_material_names,
        )
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        s = self._session
        # Имена материалов модели: по ним потом разрешаются текстуры при смене
        # команды и стиля. Первый материал — главный, порядок сохраняем.
        #
        # Карточки — только РЕДАКТИРУЕМЫЕ материалы: глаза, зубы и sheen-оверлеи
        # отбрасывает тот же блэклист, что в приложении. Без фильтра страница
        # предлагала заменить то, что мод всё равно пишет оригиналом.
        # Остальное уходит в «Прочее» — на меши в 3D оно ложится всё равно
        # (scene_textures), иначе служебная геометрия осталась бы серой.
        #
        # Служебный ключ, поставленный в _on_ready «на случай одной текстуры»,
        # ОБЯЗАН уступить настоящим именам: этот сигнал и означает, что модель
        # многоматериальная. Иначе в превью остаётся одна текстура из трёх.
        if not s.textures.material_names or s.textures.material_names == [SINGLE_TEX_KEY]:
            cards = [c.name for c in editable_material_cards(tex_map)]
            s.textures.material_names = cards
            s.textures.main_material = cards[0] if cards else None
            s.misc_materials = misc_material_names(tex_map, cards)
            s.misc_mode = False
            s.textures.vpk_red_tex_map.pop(SINGLE_TEX_KEY, None)
        # Игровые оригиналы RED запоминаем ОДИН раз и только на своей команде:
        # на BLU сюда приходят синие текстуры, и они затёрли бы красные.
        if s.textures.active_team == Team.RED and not s.textures.vpk_red_tex_map:
            s.textures.vpk_red_tex_map = dict(tex_map)
        self.materials.emit(tex_map)

    def _on_blu_multi_material(self, payload) -> None:
        tex_map, name_map = split_blu_multi_material(payload)
        if not tex_map and not name_map:
            return
        s = self._session
        # Маппинг имён нужен подписям карточек даже когда синих VTF в VPK нет,
        # поэтому обновляется независимо от текстур.
        if name_map:
            s.textures.blu_name_map = dict(name_map)
        if tex_map:
            s.textures.vpk_blu_tex_map = dict(tex_map)
        logger.debug(
            f"BLU multi-material: {len(tex_map)} текстур, {len(name_map)} имён")
        self.blu_materials.emit(tex_map, name_map)


class VpkModController:
    """
    Показ ЧУЖОГО мода из VPK: его модель и его текстуры.

    Отличие от обычной загрузки — источник. Геометрия и материалы берутся из
    файла пользователя, а карточки строятся по VTF мода, а не по материалам
    игровой модели. Поэтому у сеанса поднимается custom_vpk_mode: обычная
    фильтрация материалов эти карточки перетёрла бы.
    """

    progress = Signal(str)
    ready = Signal(str, str)           # (obj_path, texture_path)
    animated = Signal(object, float)
    cards = Signal(object)             # [{name, display_name, preview_png}]
    materials = Signal(object)         # имена материалов модели (меши)
    skins = Signal(object)             # стили модели (skinfamilies)
    failed = Signal(str)

    def __init__(self, session: PreviewSession):
        self._session = session
        self._worker = None

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop(3000)
            self._worker = None

    def load(self, user_vpk: str, misc_vpk: str, textures_vpk: str,
             lang: str = 'en') -> None:
        """Начинает разбор мода. Состояние сеанса чистится ДО загрузки."""
        self.stop()

        s = self._session
        s.reset_skins()
        s.reset_team_frames()
        s.reset_misc()
        # Режим включается ПОСЛЕ сбросов: reset_team_frames его гасит.
        s.custom_vpk_mode = True
        s.custom_model_materials = []

        from src.services.preview_vpk_mod_worker import PreviewVpkModWorker
        w = PreviewVpkModWorker(
            user_vpk_path=user_vpk,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=lang,
        )
        w.progress.connect(self.progress.emit)
        w.ready.connect(self._on_ready)
        w.animated.connect(self._on_animated)
        w.cards_ready.connect(self._on_cards)
        w.materials_ready.connect(self._on_materials)
        w.skins_ready.connect(self._on_skins)
        w.failed.connect(self.failed.emit)
        self._worker = w
        w.start()

    # ── Сигналы воркера: сначала сессия, потом событие ───────────────────── #

    def _on_ready(self, obj_path: str, texture_path: str) -> None:
        s = self._session
        s.textures.active_team = Team.RED
        if texture_path:
            s.textures.red_frames = [texture_path]
        s.current_object = ('custom_vpk', obj_path, texture_path)
        self.ready.emit(obj_path, texture_path)

    def _on_animated(self, frames: list, framerate: float) -> None:
        if not frames:
            return
        self._session.textures.red_frames = list(frames)
        self._session.team_framerate = framerate
        self.animated.emit(frames, framerate)

    def _on_cards(self, cards: list) -> None:
        """
        Карточки мода. Превью его текстур кладём как ОРИГИНАЛЫ (vpk_red_tex_map).

        Так нетронутая карточка остаётся текстурой мода и в сборку как
        пользовательская не уходит; своё изображение перекроет её обычным
        путём — через textures[RED].
        """
        import os

        cards = list(cards or [])
        if not cards:
            return
        s = self._session
        names = [c['name'] for c in cards if c.get('name')]
        s.textures.material_names = names
        s.textures.main_material = names[0] if names else None
        for card in cards:
            png = card.get('preview_png')
            if png and os.path.exists(png):
                s.textures.vpk_red_tex_map[card['name']] = png
        self.cards.emit(cards)

    def _on_materials(self, materials: list) -> None:
        if not materials:
            return
        self._session.custom_model_materials = list(materials)
        self.materials.emit(materials)

    def _on_skins(self, info: dict) -> None:
        """
        У мода нашлись стили (skinfamilies).

        Мало запомнить их наличие: у мода СВОИ текстуры стилей, и без них
        переключение стиля показывало бы пустые карточки вместо того, что
        лежит в файле. Раскладываем их переопределениями — так же, как это
        делает панель приложения (``_on_vpk_mod_skins_ready``).
        """
        import os

        s = self._session
        s.textures.skin_info = info or None

        skin_textures = (info or {}).get('skin_textures') or {}
        for raw_index, by_material in skin_textures.items():
            index = int(raw_index)
            if not index or not by_material:
                continue           # базовый стиль показывает сами карточки
            chosen = s.skin_chosen.setdefault(index, set())
            overrides = s.textures.skin_overrides.setdefault(index, {})
            for base_material, png in by_material.items():
                if not png or not os.path.exists(png):
                    continue
                # Карточки названы по базовому материалу — под ним стиль и
                # переопределяется; имя меша подберёт resolve_mesh.
                overrides[base_material] = png
                chosen.add(base_material)

        self.skins.emit(info)


class SkinDetectController:
    """
    Стили модели (skinfamilies) — «Базовый», «Bloody», командные, австралий.

    Запускается ПОСЛЕ загрузки превью: QC к этому моменту уже лежит в кэше
    декомпиляции, и определение стилей обходится чтением файла. Своей модели у
    стилей нет — они лишь говорят, сколько вариантов у одной и той же.

    Отсутствие стилей — обычное дело (у большинства оружия их нет), поэтому
    провал детекта не ошибка: событие просто не приходит.
    """

    detected = Signal(object)      # skin_info: {num_skins, roles, is_team, ...}

    def __init__(self, session: PreviewSession):
        self._session = session
        self._worker = None

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop(3000)
            self._worker = None

    def detect(self, weapon_key: str, mode: str, misc_vpk: str,
               lang: str = 'en') -> None:
        self.stop()
        from src.services.skin_detect_worker import SkinDetectWorker

        w = SkinDetectWorker(weapon_key=weapon_key, mode=mode,
                             misc_vpk_path=misc_vpk, lang=lang)
        w.detected.connect(self._on_detected)
        # failed не пробрасываем: «стилей нет» — норма, а не поломка.
        w.failed.connect(lambda why: logger.debug(f"стили не найдены: {why}"))
        self._worker = w
        w.start()

    def _on_detected(self, info: dict) -> None:
        s = self._session
        s.textures.skin_info = info
        s.textures.active_skin = 0
        s.textures.skin_overrides = {}
        self.detected.emit(info)


class ViewmodelController:
    """
    Вид от первого лица: руки класса с оружием.

    Отдельный воркер и отдельная сцена — меш собирается слиянием рук и оружия,
    поэтому обычная модель тут не годится. Сцена приезжает по частям (меш,
    материалы, редактируемые имена), собирать её целиком — дело подписчика.
    """

    progress = Signal(str)
    ready = Signal(str)             # obj_path статичной сцены
    animated = Signal(object)       # сцена с дорожками костей
    materials = Signal(object)      # {материал: png}
    editable = Signal(object)       # какие меши разрешено перекрашивать
    actions = Signal(object)        # какие анимации есть у этого оружия
    render_hints = Signal(object)
    failed = Signal(str)

    def __init__(self, session: PreviewSession):
        self._session = session
        self._worker = None

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop(3000)
            self._worker = None

    def load(self, weapon_key: str, mode: str, misc_vpk: str, textures_vpk: str,
             tf2_root: str, action: str = 'IDLE', lang: str = 'en') -> None:
        self.stop()
        from src.data import viewmodel_anims
        from src.services.viewmodel_worker import ViewmodelPreviewWorker
        from src.services.weapon_anim_catalog import Action

        w = ViewmodelPreviewWorker(
            weapon_key=weapon_key,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            tf2_root=tf2_root,
            # Класс берём из режима: всеклассовое оружие принадлежит сразу
            # девяти классам, и в руках его надо показать у выбранного.
            tf2_class=viewmodel_anims.class_from_mode(mode),
            action=Action[action],
            # Рукава и перчатки у семи классов командные: на синей стороне
            # руки красит воркер, больше их красить некому.
            team=self._session.textures.active_team,
            lang=lang,
        )
        w.progress.connect(self.progress.emit)
        w.ready.connect(lambda obj, _tex: self.ready.emit(obj))
        w.animated_ready.connect(self.animated.emit)
        w.multi_material.connect(self._on_materials)
        w.editable_materials.connect(lambda n: self.editable.emit(list(n or [])))
        w.actions_available.connect(lambda n: self.actions.emit(list(n or [])))
        w.render_hints.connect(lambda h: self.render_hints.emit(h or {}))
        w.failed.connect(self.failed.emit)
        self._worker = w
        w.start()

    def _on_materials(self, tex_map: dict) -> None:
        """
        Материалы сцены — в сессию, как и у обычной модели.

        Без этого view_state о них не знает, и текстуры не на что разрешать:
        сцена показывалась серой.
        """
        if not tex_map:
            return
        t = self._session.textures
        t.material_names = list(tex_map)
        if not t.vpk_red_tex_map:
            t.vpk_red_tex_map = dict(tex_map)
        self.materials.emit(tex_map)


class SkyboxController:
    """Грани неба для 3D-превью: шесть PNG, которые вьювер ставит кубмапой."""

    ready = Signal(object)          # {грань: png}
    failed = Signal(str)

    def __init__(self, session: PreviewSession):
        self._session = session
        self._worker = None

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop(3000)
            self._worker = None

    def load(self, sky_name: str, vpk_paths) -> None:
        self.stop()
        from src.services.skybox_preview_worker import SkyboxFacesWorker

        w = SkyboxFacesWorker(sky_name=sky_name, vpk_paths=list(vpk_paths))
        w.ready.connect(self._on_ready)
        w.failed.connect(self.failed.emit)
        self._worker = w
        w.start()

    def _on_ready(self, faces: dict) -> None:
        self._session.textures.skybox_stock_faces = dict(faces or {})
        self.ready.emit(faces or {})
