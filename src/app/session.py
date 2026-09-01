"""
Сеанс приложения для фронта: состояние превью, контроллер и очередь событий.

Зачем очередь. Воркеры работают в своих потоках и о представлении не знают —
контроллер применяет их сигналы к сеансу и эмитит своё событие. Доставить его
до страницы можно по-разному (SSE у dev-сервера, `evaluate_js` у pywebview),
и способ доставки не должен протекать в контроллер. Поэтому события просто
складываются в потокобезопасную очередь, а транспорт её разбирает.

Один сеанс на процесс: приложение однооконное, и держать несколько
одновременных загрузок всё равно нельзя — их сигналы перемешались бы в одном
состоянии.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Dict, List, Optional

from src.app.preview_controller import (
    Preview3DController, SkinDetectController, SkyboxController,
    ViewmodelController, VpkModController,
)
from src.domain.preview.session import PreviewSession
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: «Ответа ещё нет» для запомненного выбора текстуры. Отдельный сторож, потому
#: что сам ответ бывает None — это «взять главную текстуру».
_NO_CHOICE = object()


def _paint_spec(color: Any) -> Dict[str, Any]:
    """
    Цвет части в вид, понятный склейке.

    Хранится либо строка «#rrggbb», либо градиент словарём: старые работы
    писались строкой, и ломать их из-за новой возможности незачем.
    """
    if isinstance(color, dict):
        return {'color': str(color.get('color') or ''),
                'color2': (str(color.get('color2')) if color.get('color2') else None),
                'horizontal': bool(color.get('horizontal'))}
    return {'color': str(color)}


def _viewmodel_rig() -> dict:
    """Камера вида от первого лица. Импорт отложен — модуль тянет сцену."""
    from src.services.viewmodel_scene import VIEWMODEL_RIG
    return dict(VIEWMODEL_RIG)


def _tree_nodes(tree: list) -> List[dict]:
    """Иерархия систем в вид для каталога: {key, name, kids}.

    Вложенность в PCF настоящая (система тянет детей), и показывать её надо
    вложенностью же: в class_fx.pcf 104 системы, и плоским списком имён они
    читаются как свалка. Выбрать при этом можно любой узел — движок строит
    эффект от того, который назвали корнем.

    Циклы обрывает system_hierarchy, поэтому обход конечен.
    """
    return [{'key': name, 'name': name, 'kids': _tree_nodes(kids)}
            for name, kids in tree]


def _skybox_mode():
    """Режим превью «скайбокс» — импорт отложен, чтобы не тянуть данные зря."""
    from src.domain.preview.mode import PreviewMode
    return PreviewMode.SKYBOX

#: Сколько событий держим, если их никто не разбирает. Страница может быть
#: закрыта или перезагружаться — тогда очередь не должна расти бесконечно.
MAX_PENDING = 500


class AppSession:
    """Состояние превью, контроллер загрузки и очередь событий для страницы."""

    def __init__(self) -> None:
        self.preview = PreviewSession()
        self.controller = Preview3DController(self.preview)
        self.skins = SkinDetectController(self.preview)
        self.viewmodel = ViewmodelController(self.preview)
        self.skybox = SkyboxController(self.preview)
        self.vpk_mod = VpkModController(self.preview)
        #: Воркер сборки. Один на сеанс: две сборки разом писали бы в одну
        #: временную папку.
        self._build = None
        #: Воркер экспорта UV-шаблона.
        self._uv = None
        #: Текущий воркер-инструмент (извлечение, экспорт, объединение).
        self._tool = None
        #: Подготовленная декомпиляция модели: ждёт выбора файлов на странице.
        #: Пока она жива, за ней числится временный каталог.
        self._prepared: Optional[Dict[str, Any]] = None
        #: Сконвертированная своя модель, ждущая ответа «готова / только
        #: геометрия». Держим, чтобы не конвертировать SMD второй раз.
        self._pending_model: Optional[Dict[str, Any]] = None
        #: Показанный мод из VPK — его же собираем как источник.
        self._vpk_mod_path: Optional[str] = None
        #: OBJ показанной модели — источник частей (см. mesh_parts_service).
        self._obj_path: str = ''
        #: Прошлые состояния покраски частей: (материал, картинки, цвета).
        #: Красят на ощупь — «попробовал, не понравилось» должно откатываться,
        #: иначе человек боится трогать.
        self._parts_history: List[Any] = []
        #: Склейки, которые сделали мы сами. Отличать их от своей текстуры
        #: пользователя обязательно: иначе следующая склейка легла бы поверх
        #: предыдущей и «убрать картинку с части» ничего не вернуло бы.
        self._composites: set = set()
        #: Модели показанной шапки: {класс: mdl}. Пусто у обычной шапки — у неё
        #: одна модель на всех. Нужны сборке: мультиклассовая шапка собирается
        #: сразу под все выбранные классы.
        self._hat_models: Dict[str, str] = {}
        #: Правки по стилям шапки: {индекс стиля: снимок}. Стиль — отдельная
        #: модель, и правки одного к другому не относятся; сборка собирает все
        #: изменённые стили в ОДИН мод, как в окне приложения.
        self._hat_styles: Dict[int, Dict[str, Any]] = {}
        #: Индекс показанного стиля. Он же — «не собирать отдельно»: активный
        #: стиль уходит в мод основным путём.
        self._hat_style: int = 0
        #: Воркер диагностики. Один на сеанс: два отчёта разом не нужны.
        self._diag = None
        #: Запомненный ответ «применить ко всем» для недостающих текстур.
        #: Живёт одну сборку: следующая спрашивает заново. Сравнивать с None
        #: нельзя — None и есть один из ответов («взять главную»), поэтому
        #: «ответа ещё нет» помечено своим сторожем.
        self._texture_choice = _NO_CHOICE
        #: Разобранный PCF. Живёт между вызовами: правка параметров и сборка
        #: VPK работают с тем же деревом, что показано на экране.
        self.particles = None
        #: История правок эффекта: снимки и позиция в них.
        self._particle_history: List[Any] = []
        self._particle_pos = -1
        #: Во время отката новые снимки не пишем — иначе он сам стал бы правкой.
        self._restoring = False
        # У каждого подписчика СВОЯ очередь: с одной общей два открытых окна
        # делили бы события пополам вместо того, чтобы каждое получило все.
        self._subscribers: "list[queue.Queue[dict]]" = []
        self._lock = threading.Lock()
        self._bind()

    # ═══════════════════════════════════════════════════════════════════════ #
    # События
    # ═══════════════════════════════════════════════════════════════════════ #

    def _bind(self) -> None:
        """Переводит события контроллера в записи очереди."""
        c = self.controller
        c.progress.connect(lambda text: self._put('progress', text=text))
        c.model_ready.connect(self._on_model_ready)
        c.animated.connect(
            lambda frames, fps: self._put('animated', frames=list(frames), fps=fps))
        c.materials.connect(lambda m: self._put('materials', materials=dict(m or {})))
        c.blu_ready.connect(
            lambda frames, fps: self._put('blu_ready', frames=list(frames), fps=fps))
        c.blu_materials.connect(
            lambda tex, names: self._put('blu_materials',
                                         materials=dict(tex or {}),
                                         names=dict(names or {})))
        c.blu_same_as_red.connect(lambda: self._put('blu_same_as_red'))
        c.australium_ready.connect(
            lambda png, mat: self._put('australium', png=png, material=mat))
        c.render_hints.connect(lambda h: self._put('render_hints', hints=h or {}))
        # «Только карточки»: текстура игровой модели без её геометрии.
        c.cards_ready.connect(lambda tex: self._put('cards_ready', texture=tex))
        c.failed.connect(lambda error: self._put('failed', error=error))

        # Стили: приходят отдельным воркером после загрузки модели.
        self.skins.detected.connect(lambda info: self._put('skins', info=info))

        # Вид от первого лица: своя сцена, собирается по частям.
        v = self.viewmodel
        v.progress.connect(lambda text: self._put('progress', text=text))
        # Риг едет ВМЕСТЕ со сценой, а не ответом на запуск: ответ идёт по
        # HTTP, событие — по своему каналу, и сцена успевала прийти раньше.
        # Тогда камера не вставала и кадр оставался пустым.
        v.ready.connect(
            lambda obj: self._put('fp_ready', obj=obj, rig=_viewmodel_rig()))
        v.animated.connect(
            lambda scene: self._put('fp_animated', scene=scene, rig=_viewmodel_rig()))
        v.materials.connect(lambda m: self._put('materials', materials=dict(m or {})))
        v.editable.connect(lambda n: self._put('fp_editable', names=list(n)))
        v.actions.connect(lambda n: self._put('fp_actions', actions=list(n)))
        v.render_hints.connect(lambda h: self._put('render_hints', hints=h or {}))
        v.failed.connect(lambda error: self._put('failed', error=error))

        # Чужой мод из VPK: своя модель и свои карточки.
        m = self.vpk_mod
        m.progress.connect(lambda text: self._put('progress', text=text))
        m.ready.connect(self._on_model_ready)
        m.animated.connect(
            lambda frames, fps: self._put('animated', frames=list(frames), fps=fps))
        m.cards.connect(lambda cards: self._put('mod_cards', cards=list(cards)))
        # Имена мешей меняют то, КУДА ложатся текстуры мода: состояние уже
        # обновлено контроллером, странице достаточно перечитать показ.
        m.materials.connect(lambda names: self._put('materials', materials={}))
        m.skins.connect(lambda info: self._put('skins', info=info))
        m.failed.connect(lambda error: self._put('failed', error=error))

        # Скайбокс: шесть граней кубмапы.
        self.skybox.ready.connect(lambda faces: self._put('skybox', faces=faces))
        self.skybox.failed.connect(lambda error: self._put('failed', error=error))

    def _on_model_ready(self, obj_path: str, texture: str) -> None:
        """
        Модель собрана. Вместе с путями отдаём центр и масштаб.

        Считаем здесь, а не на странице: bounding box у Three.js сразу после
        загрузки ненадёжен, и приложение по той же причине считает его в Python
        (см. domain/preview/obj_bounds).
        """
        from src.domain.preview.obj_bounds import compute_obj_bounds

        cx = cy = cz = 0.0
        scale = 1.0
        try:
            with open(obj_path, 'r', encoding='utf-8') as f:
                cx, cy, cz, scale = compute_obj_bounds(f.read())
        except OSError as exc:
            logger.warning(f"не прочитать OBJ для габаритов: {exc}")

        # OBJ нужен и после показа: по нему считаются части модели, и номера
        # треугольников в нём те же, что вернёт вьювер по клику.
        self._obj_path = obj_path
        self._put('model_ready', obj=obj_path, texture=texture,
                  bounds={'cx': cx, 'cy': cy, 'cz': cz, 'scale': scale})

    def _put(self, event: str, **payload: Any) -> None:
        """Раздаёт событие всем подписчикам. Зовётся из потока воркера."""
        record = {'event': event, **payload}
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            if q.qsize() >= MAX_PENDING:
                # Подписчик не успевает или окно закрыто: старое уже неважно.
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
            q.put(record)

    def subscribe(self) -> "queue.Queue[dict]":
        """Заводит очередь для одного подписчика (окна, вкладки)."""
        q: "queue.Queue[dict]" = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    @staticmethod
    def drain(q: "queue.Queue[dict]", timeout: float = 25.0) -> List[dict]:
        """
        Ждёт события подписчика и отдаёт всё, что накопилось. Пустой список —
        таймаут: транспорту это сигнал, что соединение живо и можно ждать
        дальше.
        """
        try:
            first = q.get(timeout=timeout)
        except queue.Empty:
            return []
        out = [first]
        while True:
            try:
                out.append(q.get_nowait())
            except queue.Empty:
                return out

    # ═══════════════════════════════════════════════════════════════════════ #
    # Действия
    # ═══════════════════════════════════════════════════════════════════════ #

    def load_preview(self, mode: str, lang: str = 'ru',
                     model_key: Optional[str] = None,
                     per_class: Optional[Dict[str, str]] = None,
                     style: Optional[int] = None) -> Dict[str, Any]:
        """
        Начинает загрузку 3D-превью предмета.

        Возвращает не результат, а факт запуска: модель приезжает событиями.
        Ошибку конфигурации (нет TF2) отдаём сразу — гонять ради неё воркер
        незачем, а страница должна показать её на месте.
        """
        from src.domain.preview.model_key import model_key_for

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        # Имя режима воркеру не годится: у рук нужна модель предплечья, у тела
        # персонажа — путь к MDL. Правило целиком в домене.
        #
        # У шапок модель задаётся выбором в каталоге (у каждой свой mdl_path),
        # поэтому ключ можно передать явно — вывести его из режима «hat»
        # невозможно.
        # Мультиклассовая шапка приходит шаблоном (…_%s.mdl): показать такой
        # путь нельзя, поэтому берём модель первого класса, а весь набор
        # запоминаем для сборки.
        # Смена стиля — до подмены моделей: снимок делается ПРОШЛЫМ набором.
        self._remember_hat_style(style if mode == 'hat' else None)
        self._hat_models = dict(per_class or {}) if mode == 'hat' else {}
        if model_key and '%s' in model_key and self._hat_models:
            model_key = next(iter(self._hat_models.values()))

        weapon_key = model_key or model_key_for(mode)
        if not weapon_key:
            # Спрей и эффекты смерти — это ОДНА картинка без модели. Отсутствие
            # 3D здесь не ошибка: показывать надо пустой кадр под текстуру, а
            # не сообщение о поломке.
            from src.data.weapons import SPECIAL_MODES
            if mode in set(SPECIAL_MODES):
                return self._load_texture_only(mode)
            return {'error': f'Для режима «{mode}» 3D-модели нет'}

        # Состояние сеанса чистит переход, а не контроллер: правила «что
        # забыть» живут в домене. Смена ПРЕДМЕТА забывает и пользовательские
        # текстуры — иначе скин одного оружия переезжает на другое.
        with self._lock:
            self.preview.begin_item(weapon_key, mode)
            # begin_game_model гасит custom_vpk_mode — мод перестаёт быть
            # источником сборки, и его путь тоже надо забыть.
            self.preview.begin_game_model()
        self.vpk_mod.stop()
        self._vpk_mod_path = None

        # Правки возвращаем ДО запуска воркера: они лягут на карточки, как
        # только приедут материалы, и человек не увидит пустой альбом там, где
        # вчера была работа.
        self._mode = mode
        self._restore_work()
        # Память стилей свежее диска: с неё вернулись минуту назад, а автосохранение
        # человек мог и выключить.
        with self._lock:
            self.preview.apply_user_edits(
                (self._hat_styles.get(self._hat_style) or {}).get('edits'))

        logger.info(f"load_preview: mode={mode!r} key={weapon_key!r}")
        self.controller.load_game_model(
            weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang)
        # Стили ищем параллельно: QC после декомпиляции окажется в кэше, так что
        # ждать своей очереди воркеру почти не придётся.
        self.skins.detect(weapon_key, mode, paths['misc_vpk'], lang=lang)
        self._mode = mode
        return {'started': True, 'mode': mode, 'weapon_key': weapon_key,
                # Какие стили уже правлены: страница ставит на них метку, иначе
                # про правку соседнего стиля вспоминают только в игре.
                'edited_styles': sorted(self._hat_styles)}

    def _remember_hat_style(self, style: Optional[int]) -> None:
        """
        Запоминает правки уходящего стиля шапки.

        ``style is None`` — это НОВАЯ шапка, а не стиль номер ноль: правки её
        предшественницы к ней не относятся, и память чистится целиком.
        """
        if style is None:
            self._hat_styles = {}
            self._hat_style = 0
            return
        # У одноклассовой шапки покласcовых моделей нет — стиль собирается той
        # моделью, что показана. Без этого правки таких стилей молча терялись.
        models = dict(self._hat_models) or (
            {'': self.preview.weapon_key} if self.preview.weapon_key else {})
        if models and self.preview.has_user_edits():
            t = self.preview.textures
            main = t.stable_main()
            self._hat_styles[self._hat_style] = {
                'models': models,
                'edits': self.preview.user_edits(),
                # Главную текстуру считаем здесь: в снимке лежат имена
                # материалов, а какой из них главный, знает только живой сеанс.
                'image_path': t.uploaded_for_mat(main) if main else None,
            }
        self._hat_style = int(style)

    def _hat_style_builds(self) -> Optional[List[Dict[str, Any]]]:
        """Изменённые НЕактивные стили шапки — их сборка добавит в тот же мод."""
        builds = []
        for index, snap in self._hat_styles.items():
            if index == self._hat_style:
                continue
            edits = snap.get('edits') or {}
            textures = edits.get('textures') or {}
            if not (snap.get('image_path') or edits.get('custom_smd_path')
                    or any(textures.values())):
                continue
            builds.append({
                'mdl_paths': list((snap.get('models') or {}).values()),
                'replace_smd': edits.get('custom_smd_path'),
                'keep_materials': bool(edits.get('custom_keep_materials')),
                'image_path': snap.get('image_path'),
                'textures': textures,
            })
        return builds or None

    def _load_texture_only(self, mode: str) -> Dict[str, Any]:
        """
        Режим без модели: спрей и эффекты смерти.

        Показывать нечего, кроме самой картинки, поэтому вместо запуска воркера
        готовим один пустой кадр — в него человек и кладёт текстуру. Сборка
        такие режимы собирает из неё одной.
        """
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        self.controller.stop()
        self.viewmodel.stop()
        self.skins.stop()
        with self._lock:
            self.preview.begin_item(mode, mode)
            self.preview.begin_game_model()
            self.preview.textures.material_names = [SINGLE_TEX_KEY]
            self.preview.textures.main_material = SINGLE_TEX_KEY
        self._mode = mode
        self._vpk_mod_path = None
        self._restore_work()

        logger.info(f"режим без модели: {mode}")
        # У крита и эффектов смерти сцена ЕСТЬ — персонаж: у крита текстура
        # висит билбордом над ним, у эффекта ложится на него самого. Модель
        # процедурная, если своя не положена в tools/Model.
        self._put('texture_only', mode=mode, **self._scene_for(mode))
        return {'texture_only': True, 'mode': mode}

    def _scene_for(self, mode: str) -> Dict[str, Any]:
        """Из чего собрать сцену спец-режима: своя модель и текстура по умолчанию."""
        from src.data.weapons import VTF_ONLY_SPECIAL_MODES
        from src.services import special_scene_service as scene

        if mode == 'spray':
            return {'scene_kind': 'none'}

        model, model_texture = scene.find_scene_model('soldier')
        if model_texture.lower().endswith('.vtf'):
            model_texture = scene.vtf_to_png(model_texture)

        if mode in VTF_ONLY_SPECIAL_MODES:
            # Эффект смерти: пока своей текстуры нет, показываем игровую —
            # человек должен видеть то же, что и в игре.
            paths = self.tf2_paths()
            if not model_texture and 'error' not in paths:
                model_texture = scene.death_effect_texture(
                    mode, [paths['misc_vpk'], paths['textures_vpk']])
            return {'scene_kind': 'death', 'model': model,
                    'model_texture': model_texture}
        return {'scene_kind': 'crit', 'model': model,
                'model_texture': model_texture}

    def load_first_person(self, action: str = 'IDLE',
                          lang: str = 'ru') -> Dict[str, Any]:
        """Собирает сцену «руки класса с оружием» для текущего предмета."""
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self, '_mode', '')
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        key = model_key_for(mode)
        if not key:
            return {'error': 'Вид от первого лица есть только у оружия'}

        self.controller.stop()
        self.viewmodel.load(key, mode, paths['misc_vpk'], paths['textures_vpk'],
                            paths['tf_dir'], action=action, lang=lang)
        return {'started': True, 'action': action, 'rig': _viewmodel_rig()}

    def load_skybox(self, sky_name: str) -> Dict[str, Any]:
        """Готовит грани стокового неба для показа кубмапой."""
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        self._mode = 'skybox'
        with self._lock:
            self.preview.mode.enter(_skybox_mode())
        self.skybox.load(sky_name, [paths['misc_vpk'], paths['textures_vpk']])
        return {'started': True, 'sky': sky_name}

    def set_texture(self, material: str, path: Optional[str]) -> Dict[str, Any]:
        """
        Кладёт пользовательскую текстуру на материал (или снимает, path=None).

        Куда именно она попадёт — решает домен: активный стиль пишется в свои
        переопределения, нейтральный материал дублируется в обе команды, а под
        «сделать командным» дублирование запрещено. Эти правила накопились по
        багам, повторять их здесь нельзя.
        """
        with self._lock:
            self.preview.textures.set_texture(material, path)
        self._autosave()
        return self.view_state()

    def build(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Собирает VPK из текущего состояния превью.

        Параметры формата приходят от страницы, а ЧТО именно собирать — из
        сеанса: какие текстуры пользователь положил на какие материалы. Второй
        раз спрашивать это у представления незачем, оно и так лишь отражение.
        """
        from src.services.build_request import BuildRequest

        if self._build is not None and self._build.isRunning():
            return {'error': 'Сборка уже идёт'}

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        mode = getattr(self, '_mode', '')
        if not mode:
            return {'error': 'Сначала выберите предмет'}

        t = self.preview.textures
        # Главная текстура — то, что лежит на главном материале модели.
        main = t.stable_main()
        image = t.uploaded_for_mat(main) if main else None
        extra = t.uploaded_slot_paths()

        if not image and not extra:
            return {'error': 'Не загружено ни одной своей текстуры'}

        size = int(params.get('size') or 512)
        request = BuildRequest(
            image_path=image,
            mode=mode,
            filename=params.get('filename') or 'mod.vpk',
            size=(size, size),
            format_type=params.get('format') or 'DXT5',
            flags=list(params.get('flags') or []),
            vtf_options=dict(params.get('options') or {}),
            tf2_root_dir=paths['root'],
            export_folder=params.get('export_folder') or 'export',
            language=params.get('lang') or 'ru',
            panel_extra_textures=extra or None,
            panel_blu_textures=t.blu_uploaded_paths() or None,
            force_team=bool(t.force_team),
            isolate_shoulders=bool(params.get('isolate_shoulders')),
            # Карты материала (detail / самосвечение / phong): VTF по ним
            # генерит сборка, а VMT дописывает сама — страница их только
            # набирает.
            material_maps=(dict(self.preview.texture_maps) or None),
            # Свои настройки материала (разрешение, формат, флаги): сборка
            # накладывает их поверх глобальных сама.
            material_settings=(dict(self.preview.texture_overrides) or None),
            # Показанный мод из VPK: сборка берёт его содержимое за основу.
            custom_vpk_source_path=(self._vpk_mod_path
                                    if self.preview.custom_vpk_mode else None),
            # Шапка: путь к её MDL обязателен — по режиму «hat» модель не
            # найти, и сборка падала на поиске «оружия hat».
            hat_mdl_path=(self.preview.weapon_key if mode == 'hat' else None),
            hat_class_models=self._hat_models_for(params.get('hat_classes')),
            # Правленые соседние стили: у каждого своя модель и своя текстура,
            # но мод один — иначе человек собирал бы их по одному и вручную
            # склеивал.
            hat_style_builds=(self._hat_style_builds() if mode == 'hat' else None),
            # Краски из игры: с ними текстура красится командным цветом, как у
            # стоковой шапки. Спрашивает страница — умолчание «да», как в окне.
            hat_apply_game_paints=bool(params.get('hat_paints', True)),
            # Своя геометрия: включает замену сама фактом загрузки — отдельной
            # галочки на странице нет, как и в кнопке приложения.
            replace_model_enabled=bool(self.preview.custom_smd_path),
            replace_model_path=self.preview.custom_smd_path,
            replace_keep_materials=bool(self.preview.custom_keep_materials),
            # Правленый QC берётся только у «готовой» модели: у замены
            # геометрии сборка собирает QC сама.
            custom_qc_text=(self.preview.custom_qc_text
                            if self.preview.custom_keep_materials else None),
        )

        from src.services.build_worker import BuildWorker
        w = BuildWorker(request=request)

        # Сборка умеет СПРАШИВАТЬ у интерфейса недостающую текстуру и
        # блокируется до ответа (UiRequest, таймаут 300 секунд). Раньше здесь
        # отвечали сразу тем, что нашлось в сеансе, а «не нашлось» означает
        # «взять ГЛАВНУЮ текстуру» — то есть скин молча растекался на служебные
        # материалы. Теперь вопрос доходит до человека, как в окне приложения.
        w.request_extra_texture.connect(self._on_build_needs_texture)
        w.texture_mismatch_warning.connect(
            lambda msg: w._texture_mismatch_req.answer(True))

        w.progress.connect(lambda pct, text: self._put('build_progress',
                                                       percent=pct, text=text))
        w.sub_progress.connect(lambda pct, text: self._put('build_progress',
                                                           percent=pct, text=text))
        w.finished.connect(lambda ok, msg: self._put('build_done',
                                                     ok=bool(ok), message=msg))
        w.error.connect(lambda msg: self._put('build_done', ok=False, message=msg))
        self._build = w
        self._texture_choice = _NO_CHOICE   # «ко всем» — на одну сборку
        w.start()
        return {'started': True, 'filename': request.filename}

    def _hat_models_for(self, classes) -> Optional[Dict[str, str]]:
        """
        Модели мультиклассовой шапки под выбранные классы.

        Собирать все девять, когда человеку нужен один класс, — это девять
        моделей в моде вместо одной. Пустой выбор считаем «все»: молча собрать
        пустую шапку хуже, чем собрать лишнее.
        """
        if not self._hat_models:
            return None
        wanted = {str(c).lower() for c in (classes or [])}
        if not wanted:
            return dict(self._hat_models)
        picked = {cls: path for cls, path in self._hat_models.items()
                  if cls.lower() in wanted}
        return picked or dict(self._hat_models)

    # ── Недостающая текстура: вопрос страницы, ответ человека ────────────── #

    def _on_build_needs_texture(self, material: str, weapon_key: str) -> None:
        """
        Сборке не хватает текстуры для материала.

        Порядок тот же, что в окне: уже загруженная текстура отвечает сама,
        запомненный выбор «ко всем» отвечает следом, и только потом спрашиваем
        человека. Пока он думает, воркер стоит на UiRequest.
        """
        uploaded = self.preview.textures.uploaded_for_mat(material)
        if uploaded:
            self._answer_texture_request(uploaded)
            return
        if self._texture_choice is not _NO_CHOICE:
            self._answer_texture_request(self._texture_choice)
            return
        self._put('need_texture', material=material, weapon_key=weapon_key)

    def _answer_texture_request(self, value) -> None:
        """Отдаёт ответ ждущему воркеру сборки."""
        build = self._build
        if build is not None and hasattr(build, 'set_extra_texture_result'):
            build.set_extra_texture_result(value)

    def answer_texture(self, choice: str = 'game', path: str = '',
                       apply_all: bool = False) -> Dict[str, Any]:
        """
        Ответ страницы на ``need_texture``.

        Три варианта — те же, что в диалоге приложения:
          • ``game`` — оставить игровой оригинал (в мод не попадёт);
          • ``main`` — скопировать главную текстуру на этот материал;
          • ``file`` — своя картинка по пути ``path``.
        """
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

        if choice == 'file' and path:
            value = path
        elif choice == 'main':
            value = None                 # None у сборки означает «главную»
        else:
            value = EXTRA_TEX_USE_GAME_ORIGINAL

        if apply_all:
            self._texture_choice = value
        self._answer_texture_request(value)
        return {'answered': choice}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Частицы
    # ═══════════════════════════════════════════════════════════════════════ #

    def load_particles(self, source: str) -> Dict[str, Any]:
        """
        Разбирает PCF и отдаёт всё, что нужно рендереру.

        Ответом, а не событием: разбор с материалами занимает около секунды, а
        результат доходит до 9 МБ (VTF внутри уже развёрнуты в PNG data-URL).
        Гонять такое через поток событий незачем — страница всё равно ничего
        не может показать, пока не получит его целиком.
        """
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        from src.services.particle_editor_service import (
            ParticleEditorService, system_hierarchy,
        )

        svc = ParticleEditorService()
        try:
            if source.startswith('particles/'):
                svc.load_from_game(paths['root'], source)
            else:
                svc.load_file(source)
        except Exception as exc:                     # noqa: BLE001 — граница
            logger.warning(f"PCF {source} не разобран: {exc}")
            return {'error': str(exc)}

        self.particles = svc
        self._history_reset()
        systems = svc.systems_json()
        tree = _tree_nodes(system_hierarchy(systems, order=svc.system_names()))
        return {
            'systems': systems,
            'materials': svc.materials_json(paths['root']),
            'tree': tree,
            # Ключ именно такой: этот словарь уходит в loadParticleData
            # движка как есть, а он читает rootName. Показываем первый корень
            # сразу — пустая сцена после секундной загрузки выглядит поломкой.
            'rootName': tree[0]['key'] if tree else '',
        }

    def particle_params(self, system: str, lang: str = 'ru') -> List[dict]:
        """
        Крутилки простого режима для системы — то же, что в панели приложения.

        Схема одна на оба интерфейса (services/simple_params): подпись, границы
        и адреса атрибутов описаны там, здесь только чтение значений. value=None
        значит, что нужного модуля в системе нет — крутилку показывают
        бледной заготовкой, а не прячут: первая правка модуль создаст.
        """
        from src.data.translations import TRANSLATIONS
        from src.services import simple_params as sp

        systems = self.particles.systems_json() if self.particles else {}
        sys_json = systems.get(system)
        if sys_json is None:
            return []

        t = TRANSLATIONS.get(lang, TRANSLATIONS['en'])
        out: List[dict] = []
        for p in sp.SIMPLE_PARAMS:
            value = sp.read_param(sys_json, p)
            out.append({
                'key': p.key,
                'name': t.get(f'particles_sp_{p.key}', p.key),
                'hint': t.get(f'particles_sp_{p.key}_tip', ''),
                'kind': p.kind,
                'value': list(value) if isinstance(value, tuple) else value,
                'placeholder': (list(p.placeholder_value)
                                if isinstance(p.placeholder_value, tuple)
                                else p.placeholder_value),
                # Мягкие границы — для ползунка, жёсткие — предел ручного
                # ввода: в стоке встречаются emission_rate под миллион, и
                # запрет на них молча испортил бы чужой эффект.
                'min': p.minimum, 'max': p.maximum,
                'hard_min': p.minimum if p.hard_min is None else p.hard_min,
                'hard_max': p.maximum if p.hard_max is None else p.hard_max,
                'curve': p.curve,
                'decimals': p.decimals,
                'creatable': p.creatable,
                'missing': [list(m) for m in sp.missing_modules(sys_json, p)],
            })
        return out

    def set_particle_param(self, system: str, key: str,
                           value: Any) -> Dict[str, Any]:
        """
        Пишет значение крутилки и отдаёт обновлённые системы.

        Системы возвращаются целиком: движок обновляет сцену через
        updateSystems, а какие именно модули задел ensure_attr, странице знать
        незачем. Материалы при этом НЕ пересобираются — их PNG уже в кадре.
        """
        from src.services import simple_params as sp

        if self.particles is None:
            return {'error': 'PCF не загружен'}
        param = next((p for p in sp.SIMPLE_PARAMS if p.key == key), None)
        if param is None:
            return {'error': f'неизвестный параметр: {key}'}

        systems = self.particles.systems_json()
        sys_json = systems.get(system)
        if sys_json is None:
            return {'error': f'система не найдена: {system}'}

        # Правка заготовки И ЕСТЬ включение параметра: модуля под ним в
        # системе ещё нет, и создаём мы его сами — как панель приложения.
        # Отдельной кнопки «Включить» нет ни там, ни здесь.
        if sp.read_param(sys_json, param) is None:
            # creatable=False — модуль создавать нельзя. У эмиттеров это не
            # придирка: добавленный emit_instantaneously задваивает залп.
            if not param.creatable:
                return {'error': 'в этой системе нет модуля для этого параметра'}
            paths = self.tf2_paths()
            root = '' if 'error' in paths else paths['root']
            for group, fn in sp.missing_modules(sys_json, param):
                if not self.particles.add_module(system, group, fn, root):
                    return {'error': f'не удалось создать модуль {fn}'}
            sys_json = self.particles.systems_json().get(system, sys_json)

        calls = sp.write_calls(sys_json, param, value)
        if not calls:
            return {'error': 'в этой системе нужного модуля нет'}
        for group, idx, attr, attr_type, v in calls:
            self.particles.ensure_attr(system, group, idx, attr, attr_type, v)

        self._history_commit()
        return {'systems': self.particles.systems_json()}

    def particle_system(self, system: str, lang: str = 'ru') -> Dict[str, Any]:
        """
        Полное содержимое системы для экспертного режима.

        Всё, что есть в PCF: атрибуты самой системы и каждый модуль каждой
        группы со своими атрибутами. Правила показа те же, что в дереве
        приложения: служебные ключи (functionName, name, id) скрыты — они
        адресуют модуль, а не настраивают его; пустые forces/constraints не
        показываются, остальные группы видны всегда.
        """
        from src.data import particle_docs
        from src.services.particle_editor_service import MODULE_GROUPS

        systems = self.particles.systems_json() if self.particles else {}
        sys_json = systems.get(system)
        if sys_json is None:
            return {}

        def attrs_of(attrs: dict) -> List[dict]:
            out = []
            for name in sorted(attrs):
                if name in ('functionname', 'name', 'id'):
                    continue
                tv = attrs[name]
                out.append({
                    'name': name, 't': tv['t'], 'v': tv['v'],
                    'help': particle_docs.attr_help(name, lang) or '',
                    # Атрибуты с фиксированным набором значений редактор
                    # показывает списком, а не голым числом.
                    'enum': {str(k): particle_docs.enum_label(name, k, lang)
                             for k in (particle_docs.enum_values(name) or {})}
                            or None,
                })
            return out

        groups: List[dict] = [{
            'group': None,
            'modules': [{'index': 0, 'title': system, 'help': '',
                         'attrs': attrs_of(sys_json.get('attrs') or {})}],
        }]
        for group in MODULE_GROUPS:
            mods = sys_json.get(group) or []
            if not mods and group in ('forces', 'constraints'):
                continue
            groups.append({'group': group, 'modules': [
                {'index': i, 'title': m['functionName'],
                 'help': particle_docs.module_help(group, m['functionName'],
                                                   lang) or '',
                 'attrs': attrs_of(m.get('attrs') or {})}
                for i, m in enumerate(mods)
            ]})

        # Дети — тоже часть системы, и в дереве приложения у них своя ветка:
        # оттуда их цепляют и отцепляют. Параметров у ссылки нет, только имя.
        groups.append({'group': 'children', 'modules': [
            {'index': i, 'title': c.get('childName', ''), 'help': '', 'attrs': []}
            for i, c in enumerate(sys_json.get('children') or [])
        ]})
        return {'name': system, 'groups': groups}

    # ── Структура эффекта ──────────────────────────────────────────────── #
    #
    # Всё, что меняет состав систем и модулей. Каждая операция отдаёт свежие
    # системы И дерево: добавленный модуль виден в свойствах, а созданная или
    # переименованная система — ещё и в каталоге слева.

    def _particles_state(self, **extra: Any) -> Dict[str, Any]:
        """Свежий снимок для страницы после правки структуры."""
        from src.services.particle_editor_service import system_hierarchy

        self._history_commit()
        systems = self.particles.systems_json()
        out: Dict[str, Any] = {
            'systems': systems,
            'tree': _tree_nodes(system_hierarchy(
                systems, order=self.particles.system_names())),
        }
        out.update(extra)
        return out

    # ── История правок ─────────────────────────────────────────────────── #
    #
    # Снимками, а не обратимыми командами: снимок автоматически покрывает и
    # будущие операции — забыть «откат» для новой правки невозможно.

    #: Сколько шагов помним. Снимок explosion.pcf — около сотни килобайт.
    HISTORY_LIMIT = 30

    def _history_reset(self) -> None:
        """Начальное состояние после загрузки PCF."""
        self._particle_history = []
        self._particle_pos = -1
        if self.particles is None:
            return
        snap = self.particles.snapshot()
        if snap is not None:
            self._particle_history = [snap]
            self._particle_pos = 0

    def _history_commit(self) -> None:
        """Фиксирует состояние ПОСЛЕ правки. Во время отката молчит."""
        if (self._restoring or self.particles is None
                or self._particle_pos < 0):
            return
        snap = self.particles.snapshot()
        if snap is None:
            return
        # Ветка возврата после новой правки теряет смысл.
        del self._particle_history[self._particle_pos + 1:]
        self._particle_history.append(snap)
        if len(self._particle_history) > self.HISTORY_LIMIT:
            self._particle_history.pop(0)
        self._particle_pos = len(self._particle_history) - 1

    def particle_history(self) -> Dict[str, Any]:
        """Есть ли куда откатываться и возвращаться."""
        return {'undo': self._particle_pos > 0,
                'redo': 0 <= self._particle_pos < len(self._particle_history) - 1}

    def undo_particles(self, delta: int = -1) -> Dict[str, Any]:
        """Откат (-1) или возврат (+1) на шаг."""
        if (err := self._need_pcf()):
            return err
        pos = self._particle_pos + int(delta)
        if pos < 0 or pos >= len(self._particle_history):
            return {'error': 'дальше некуда'}

        self._restoring = True
        try:
            if not self.particles.restore(self._particle_history[pos]):
                return {'error': 'не удалось восстановить состояние'}
            self._particle_pos = pos
            out = self._particles_state()
        finally:
            self._restoring = False
        # Материалы отдаём вместе: откат мог вернуть или убрать свою текстуру.
        paths = self.tf2_paths()
        if 'error' not in paths:
            out['materials'] = self.particles.materials_json(paths['root'])
        out.update(self.particle_history())
        return out

    def _need_pcf(self) -> Optional[Dict[str, Any]]:
        return None if self.particles is not None else {'error': 'PCF не загружен'}

    def particle_module_catalog(self, group: str) -> List[str]:
        """Что можно добавить в эту группу: ходовое сверху, дальше всё из игры."""
        from src.services.particle_editor_service import ParticleEditorService

        paths = self.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        return ParticleEditorService.group_module_catalog(group, root)

    def add_particle_module(self, system: str, group: str,
                            function_name: str) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        paths = self.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        if not self.particles.add_module(system, group, function_name, root):
            return {'error': f'не удалось добавить {function_name}'}
        return self._particles_state()

    def remove_particle_module(self, system: str, group: str,
                               index: int) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.particles.remove_module(system, group, int(index)):
            return {'error': 'не удалось удалить модуль'}
        return self._particles_state()

    def particle_missing_attrs(self, system: str, group: Optional[str],
                               index: int, lang: str = 'ru') -> List[dict]:
        """
        Параметры, которых у модуля ещё нет.

        Значение подставляется такое, как в эффектах игры — иначе первый же
        добавленный параметр вырубал бы эффект нулём.
        """
        from src.data import particle_docs

        if self.particles is None:
            return []
        paths = self.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        found = self.particles.missing_attrs(system, group, int(index), root)
        return [{'name': name, 't': tv.get('t'), 'v': tv.get('v'),
                 'help': particle_docs.attr_help(name, lang) or ''}
                for name, tv in sorted(found.items())]

    def add_particle_attr(self, system: str, group: Optional[str], index: int,
                          attr: str, attr_type: str, value: Any) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.particles.ensure_attr(system, group, int(index), attr,
                                          attr_type, value):
            return {'error': f'не удалось добавить {attr}'}
        return self._particles_state()

    def remove_particle_attr(self, system: str, group: Optional[str],
                             index: int, attr: str) -> Dict[str, Any]:
        """Удаляет параметр — значение возвращается к умолчанию движка."""
        if (err := self._need_pcf()):
            return err
        if not self.particles.remove_attr(system, group, int(index), attr):
            return {'error': f'не удалось удалить {attr}'}
        return self._particles_state()

    # ── Копирование параметров ─────────────────────────────────────────── #

    def copy_particle_params(self, system: str, group: Optional[str] = None,
                             index: Optional[int] = None,
                             attr: Optional[str] = None) -> Dict[str, Any]:
        """
        Набор параметров для буфера обмена — формат панели приложения.

        Что именно копируем, задаёт адрес:
          ничего            — вся система (при вставке спросят, заменять ли
                              её целиком);
          group             — все модули этой группы;
          group + index     — один модуль;
          + attr            — один параметр этого модуля (или самой системы,
                              если группы нет).
        """
        from src.services.particle_editor_service import MODULE_GROUPS

        if (err := self._need_pcf()):
            return err
        sys_json = self.particles.systems_json().get(system)
        if sys_json is None:
            return {'error': f'система не найдена: {system}'}

        def clean(attrs: dict) -> dict:
            return {k: v for k, v in attrs.items()
                    if k not in ('functionname', 'name', 'id')}

        def module_at(g: str, i: int) -> Optional[dict]:
            try:
                return sys_json[g][int(i)]
            except (KeyError, IndexError, TypeError):
                return None

        payload: Dict[str, Any] = {'attrs': {}, 'modules': {}}

        # Один параметр — самый частый случай: перенести настройку, не трогая
        # остального в цели.
        if attr is not None:
            if group is None:
                tv = (sys_json.get('attrs') or {}).get(attr)
                if tv is None:
                    return {'error': f'параметра нет: {attr}'}
                payload['attrs'][attr] = tv
                return {'payload': payload}
            mod = module_at(group, index or 0)
            if mod is None:
                return {'error': 'модуль не найден'}
            tv = (mod.get('attrs') or {}).get(attr)
            if tv is None:
                return {'error': f'параметра нет: {attr}'}
            payload['modules'][group] = [[mod['functionName'], {attr: tv}]]
            return {'payload': payload}

        if group is not None and index is not None:
            mod = module_at(group, index)
            if mod is None:
                return {'error': 'модуль не найден'}
            payload['modules'][group] = [
                [mod['functionName'], clean(mod.get('attrs') or {})]]
            return {'payload': payload}

        if group is not None:
            mods = sys_json.get(group) or []
            if not mods:
                return {'error': f'в группе {group} нет модулей'}
            payload['modules'][group] = [
                [m['functionName'], clean(m.get('attrs') or {})] for m in mods]
            return {'payload': payload}

        payload['full'] = True              # полный набор → выбор при вставке
        payload['attrs'] = clean(sys_json.get('attrs') or {})
        for g in MODULE_GROUPS:
            for mod in sys_json.get(g) or []:
                payload['modules'].setdefault(g, []).append(
                    [mod['functionName'], clean(mod.get('attrs') or {})])
        return {'payload': payload}

    def paste_particle_params(self, system: str, payload: dict,
                              mode: str = 'overwrite') -> Dict[str, Any]:
        """Вставляет скопированный набор. mode: overwrite | keep | replace."""
        if (err := self._need_pcf()):
            return err
        report: list = []
        ok = self.particles.paste_params(system, payload or {}, mode=mode,
                                         report=report)
        if not ok:
            return {'error': '; '.join(str(r) for r in report[:3])
                             or 'вставить не удалось'}
        return self._particles_state(report=[str(r) for r in report])

    # ── Системы: копии, имена, дети ────────────────────────────────────── #

    def duplicate_particle_system(self, system: str,
                                  new_name: str) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.particles.duplicate_system(system, new_name):
            return {'error': 'не удалось дублировать — возможно, имя занято'}
        return self._particles_state(selected=new_name)

    def rename_particle_system(self, system: str,
                               new_name: str) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.particles.rename_system(system, new_name):
            return {'error': 'не удалось переименовать — возможно, имя занято'}
        return self._particles_state(selected=new_name)

    def remove_particle_system(self, system: str) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.particles.remove_system(system):
            return {'error': 'не удалось удалить систему'}
        return self._particles_state()

    def particle_children(self, system: str) -> List[dict]:
        """Дочерние системы: их отцепляют по индексу."""
        if self.particles is None:
            return []
        sys_json = self.particles.systems_json().get(system) or {}
        return [{'index': i, 'name': c.get('childName', ''),
                 'delay': c.get('delay', 0.0)}
                for i, c in enumerate(sys_json.get('children') or [])]

    def add_particle_child(self, parent: str, child: str,
                           delay: float = 0.0) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.particles.add_child(parent, child, float(delay)):
            return {'error': 'не подцепить: система не найдена или вышел бы цикл'}
        return self._particles_state()

    def remove_particle_child(self, parent: str, index: int) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.particles.remove_child(parent, int(index)):
            return {'error': 'не удалось отцепить'}
        return self._particles_state()

    def add_particle_layer(self, parent: str) -> Dict[str, Any]:
        """Готовый слой-подэффект: остаётся дать текстуру и покрутить."""
        if (err := self._need_pcf()):
            return err
        name = self.particles.add_layer(parent)
        if not name:
            return {'error': 'не удалось добавить слой'}
        return self._particles_state(selected=name)

    def set_particle_attr(self, system: str, group: Optional[str], index: int,
                          attr: str, value: Any) -> Dict[str, Any]:
        """Правка одного атрибута из экспертного режима."""
        if (err := self._need_pcf()):
            return err
        if not self.particles.set_attr(system, group, int(index), attr, value):
            return {'error': f'не удалось записать {attr}'}
        self._history_commit()
        return {'systems': self.particles.systems_json()}

    # ── Контрольные точки ──────────────────────────────────────────────── #
    #
    # В игре положение точек задаёт код (где оружие, какого цвета килстрик),
    # в превью их выставляет человек. Само превью ими и управляет — здесь
    # только то, чего страница знать не может: какие точки эффекту нужны и
    # где на модели находятся её точки крепления.

    def particle_control_points(self, system: str) -> Dict[str, Any]:
        """Номера точек, на которые ссылается эффект и его дочерние системы."""
        from src.services.particle_editor_service import (
            referenced_control_points,
        )

        if self.particles is None:
            return {'used': []}
        systems = self.particles.systems_json()
        sys_json = systems.get(system)
        if sys_json is None:
            return {'used': []}
        return {'used': referenced_control_points(sys_json, systems)}

    @staticmethod
    def particle_models() -> List[dict]:
        """
        Модели из кэша декомпиляции — на них сажают контрольную точку.

        Своей распаковки VPK здесь нет намеренно: Crowbar долгий, а модели
        попадают в кэш при обычной работе на вкладках оружия и шапок.
        """
        from src.services.model_attachments import (
            list_decompiled_models, reference_smd_for_qc,
        )
        # Без reference-SMD меш не собрать: в кэше лежат и папки одних анимаций
        # (__anims_*), предлагать их значит предлагать ошибку.
        return [{'label': label, 'qc': qc}
                for label, qc in list_decompiled_models()
                if reference_smd_for_qc(qc)]

    def particle_model_scene(self, qc: str) -> Dict[str, Any]:
        """
        Меш модели и её точки крепления для сцены превью.

        Оси Source сохраняем: эффект живёт в них же, иначе точка крепления
        уехала бы относительно частиц. В игре анюжуал висит именно на
        attachment, а не в произвольной точке.
        """
        import shutil
        import tempfile
        from pathlib import Path

        from src.services.model_attachments import (
            attachments_from_qc, reference_smd_for_qc,
        )
        from src.services.model_materials import resolve_model_textures
        from src.services.smd_to_obj_service import SmdToObjService

        smd = reference_smd_for_qc(qc)
        if not smd:
            return {'error': 'у этой модели нет reference-SMD'}

        tmp = tempfile.mkdtemp(prefix='tf2sg_cpmodel_')
        try:
            obj_path = str(Path(tmp) / 'model.obj')
            ok, mat_names = SmdToObjService.convert(
                smd, obj_path, keep_source_axes=True)
            if not ok or not Path(obj_path).is_file():
                return {'error': 'не удалось собрать меш модели'}
            obj = Path(obj_path).read_text(encoding='utf-8')
        except Exception as exc:                     # noqa: BLE001 — граница
            logger.warning(f"меш модели для точек не построен: {exc}")
            return {'error': str(exc)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        paths = self.tf2_paths()
        textures: Dict[str, Any] = {}
        try:
            # Без текстур модель просто серая — это не повод отказывать.
            textures = resolve_model_textures(
                qc, mat_names, '' if 'error' in paths else paths['root']) or {}
        except Exception as exc:                     # noqa: BLE001
            logger.debug(f"текстуры модели не найдены: {exc}")

        # unusual_* вперёд: именно на них игра вешает эффекты.
        found = attachments_from_qc(qc)
        order = sorted(found, key=lambda a: (
            not a.name.lower().startswith('unusual'), a.name.lower()))
        return {
            'obj': obj,
            'textures': textures,
            'attachments': [{'name': a.name, 'bone': a.bone,
                             'pos': list(a.pos), 'angles': list(a.angles)}
                            for a in order],
        }

    # ── Текстуры эффекта ───────────────────────────────────────────────── #
    #
    # Материал в PCF — путь к VMT; картинка к нему приезжает уже развёрнутой
    # в PNG. Заменить её можно двумя способами, и разница принципиальная:
    # своя картинка добавляет в мод НОВЫЙ файл (в казуале обход sv_pure его
    # не подхватит), а перевод на существующий материал игры работает везде.

    def _effect_materials(self, system: str) -> List[str]:
        """
        Материалы выбранного эффекта: сам корень плюс все дочерние.

        Именно эффекта, а не файла: в одном PCF десятки систем, и показывать
        карточку от чужого эффекта — предлагать заменить не ту текстуру.
        Порядок обхода сохраняем, повторы убираем.
        """
        systems = self.particles.systems_json()
        out: List[str] = []
        seen: set = set()
        visited: set = set()
        pending = [system]
        while pending:
            name = pending.pop(0)
            if name in visited:
                continue
            visited.add(name)
            s = systems.get(name)
            if s is None:
                continue
            mat = (s.get('attrs') or {}).get('material', {}).get('v')
            if mat and mat not in seen:
                seen.add(mat)
                out.append(mat)
            pending.extend(ch.get('childName')
                           for ch in (s.get('children') or []))
        return out

    def particle_materials(self, system: str = '') -> List[dict]:
        """Материалы эффекта с их картинками — карточки 2D."""
        paths = self.tf2_paths()
        if self.particles is None or 'error' in paths:
            return []
        found = self.particles.materials_json(paths['root'])
        names = (self._effect_materials(system) if system
                 else self.particles.material_names())
        out: List[dict] = []
        for name in names:
            info = found.get(name) or {}
            out.append({
                'name': name,
                'dataUrl': info.get('dataUrl', ''),
                'width': info.get('width', 0),
                'height': info.get('height', 0),
                # Покадровая анимация: своя картинка её собьёт, и об этом
                # надо предупредить до замены, а не после.
                'sheet': bool(info.get('sheet')),
                'custom': self.particles.is_custom_material(name),
            })
        return out

    def _materials_result(self) -> Dict[str, Any]:
        """Материалы и системы после правки — движку нужно и то, и другое."""
        self._history_commit()
        paths = self.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        return {
            'systems': self.particles.systems_json(),
            'materials': self.particles.materials_json(root),
        }

    def set_particle_texture(self, material: str, path: str,
                             max_size: int = 512) -> Dict[str, Any]:
        """Заменяет текстуру материала своей картинкой."""
        if (err := self._need_pcf()):
            return err
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths
        try:
            res = self.particles.set_material_texture(
                material, path, paths['root'], max_size=int(max_size))
        except Exception as exc:                     # noqa: BLE001 — граница
            logger.warning(f"текстура {material}: {exc}")
            return {'error': str(exc)}
        if res is None:
            return {'error': 'не удалось применить текстуру (см. журнал)'}
        return self._materials_result()

    def reset_particle_texture(self, material: str) -> Dict[str, Any]:
        """Возвращает текстуру игры (свою перезапись убираем)."""
        if (err := self._need_pcf()):
            return err
        if self.particles.reset_material_texture(material) is None:
            return {'error': 'у этого материала нет своей текстуры'}
        return self._materials_result()

    def game_particle_materials(self) -> List[str]:
        """Материалы всех эффектов игры — выбор вместо своей картинки."""
        from src.services.particle_editor_service import ParticleEditorService

        paths = self.tf2_paths()
        if 'error' in paths:
            return []
        return ParticleEditorService.game_effect_materials(paths['root'])

    def set_particle_material_to_game(self, material: str,
                                      game_material: str) -> Dict[str, Any]:
        """Переводит эффект на существующий материал игры."""
        if (err := self._need_pcf()):
            return err
        if not self.particles.set_material_to_game(material, game_material):
            return {'error': 'не удалось заменить материал'}
        return self._materials_result()

    def rename_particle_material(self, material: str,
                                 new_material: str) -> Dict[str, Any]:
        """
        Меняет путь материала у всех систем, где он встречается.

        Нужно, чтобы своя текстура не перезаписывала стоковый материал: с
        собственным путём замена перестаёт менять картинку у других эффектов
        игры.
        """
        if (err := self._need_pcf()):
            return err
        if not self.particles.rename_material(material, new_material):
            return {'error': 'не удалось переименовать — возможно, путь занят'}
        return self._materials_result()

    def use_particle_texture_colors(self, system: str) -> Dict[str, Any]:
        """Снимает подкраску: эффект показывает родные цвета текстур."""
        if (err := self._need_pcf()):
            return err
        removed = self.particles.use_texture_colors(system)
        out = self._materials_result()
        out['removed'] = removed
        return out

    # ── Файл: проверка, сохранение, сборка ─────────────────────────────── #

    def particle_lint(self, system: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Проверка перед сборкой: что в эффекте сломает его в игре.

        Те же правила, что в панели приложения. Часть находок чинится
        автоматически — у них есть адрес атрибута и правильное значение.
        """
        from src.data.translations import TRANSLATIONS
        from src.services import particle_lint

        if (err := self._need_pcf()):
            return err
        t = TRANSLATIONS.get(lang, TRANSLATIONS['en'])
        systems = self.particles.systems_json()
        found = particle_lint.check_systems(systems, system or '')
        paths = self.tf2_paths()
        if 'error' not in paths:
            found += particle_lint.check_game_conflicts(
                paths['root'], self.particles.pcf_vpk_path())
        return {'findings': [{
            'rule': f.rule,
            'system': f.system,
            'message': t.get(f.message_key, f.message_key).format(**f.params),
            'fixable': f.fixable,
        } for f in found]}

    def fix_particle_lint(self, system: str = '') -> Dict[str, Any]:
        """Чинит всё, что чинится автоматически, и говорит сколько."""
        from src.services import particle_lint

        if (err := self._need_pcf()):
            return err
        found = particle_lint.check_systems(self.particles.systems_json(),
                                            system or '')
        fixed = particle_lint.apply_fixes(self.particles, found)
        return self._particles_state(fixed=fixed)

    def save_particles(self, path: str) -> Dict[str, Any]:
        """Сохраняет правленый PCF отдельным файлом."""
        if (err := self._need_pcf()):
            return err
        try:
            self.particles.save(path)
        except Exception as exc:                     # noqa: BLE001 — граница
            return {'error': str(exc)}
        return {'path': path, 'size': self.particles.serialized_size()}

    def export_particles_vpk(self, name: str = 'particles_mod.vpk',
                             lang: str = 'ru') -> Dict[str, Any]:
        """
        Собирает VPK-мод: правленый PCF и заменённые текстуры.

        Предупреждение о переполнении отдаём отдельным полем: в казуале
        обход sv_pure не грузит PCF больше оригинального, и файл, выросший
        на пару килобайт, просто не заработает — молчать об этом нельзя.
        """
        from pathlib import Path

        if (err := self._need_pcf()):
            return err
        safe = Path(str(name)).name or 'particles_mod.vpk'
        if not safe.lower().endswith('.vpk'):
            safe += '.vpk'
        dest = Path('export') / safe
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            out = self.particles.export_vpk(str(dest), language=lang)
        except Exception as exc:                     # noqa: BLE001 — граница
            logger.warning(f"сборка VPK частиц не удалась: {exc}")
            return {'error': str(exc)}
        return {
            'path': str(out),
            'textures_vpk': getattr(self.particles, 'last_textures_vpk', None),
            'overflow': self.particles.casual_size_overflow(),
        }

    def particle_param_reference(self, path: str = '',
                                 for_ai: bool = False) -> Dict[str, Any]:
        """
        Справочник параметров модулей в JSON.

        Нужен, чтобы собрать набор параметров снаружи (в том числе языковой
        моделью) и вставить его сюда через буфер обмена. Вариант «для ИИ»
        кладёт внутрь и само задание.
        """
        import json
        from pathlib import Path

        from src.services.particle_editor_service import ParticleEditorService

        paths = self.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        materials = (self.particles.material_names()
                     if self.particles is not None else None)
        try:
            data = ParticleEditorService.param_reference(
                root, with_prompt=bool(for_ai), materials=materials)
            dest = Path(path or 'export/particle_params.json')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding='utf-8')
        except Exception as exc:                     # noqa: BLE001 — граница
            return {'error': str(exc)}
        return {'path': str(dest)}

    def export_uv(self, size: int = 1024) -> Dict[str, Any]:
        """
        Рисует UV-шаблон модели в папку экспорта.

        Отдельная операция, а не часть превью: модель декомпилируется
        (cache-aware) и по её развёртке рисуются швы. Нужна, чтобы глазами
        сверить, куда какой кусок текстуры садится.
        """
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self, '_mode', '')
        key = model_key_for(mode)
        if not key:
            return {'error': 'Для этого режима модели нет'}

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        if self._uv is not None and self._uv.isRunning():
            return {'error': 'Экспорт UV уже идёт'}

        from src.services.uv_template_worker import UVTemplateWorker
        w = UVTemplateWorker(
            tf2_root_dir=paths['root'],
            mode=mode,
            weapon_key=key,
            image_size=(int(size), int(size)),
        )
        w.progress.connect(lambda pct, text: self._put('progress', text=text))
        # Путь готового PNG воркер кладёт в output_path — берём его на finished.
        w.finished.connect(
            lambda ok, msg: self._put('uv_ready', ok=bool(ok), message=msg,
                                      path=w.output_path or '',
                                      # У каждого материала своя развёртка —
                                      # и свой файл.
                                      paths=list(w.output_paths)))
        w.error.connect(lambda msg: self._put('uv_ready', ok=False,
                                              message=msg, path=''))
        self._uv = w
        w.start()
        return {'started': True}

    def load_vpk_mod(self, path: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Показывает чужой мод из VPK: его модель и его текстуры.

        Предмет при этом не меняется: мод накладывается поверх текущего выбора,
        и его путь уходит в сборку как источник (``custom_vpk_source_path``) —
        так же, как в приложении.
        """
        import os

        if not path or not os.path.isfile(path):
            return {'error': 'VPK-файл не найден'}

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        self.controller.stop()
        self._vpk_mod_path = path
        # Показанный мод — это и есть предмет: приложение так же переключает
        # категорию на «Кастомный мод» и ставит режим 'custom'.
        self._mode = 'custom'
        # Мод опознаётся файлом в библиотеке — по нему и находится работа.
        self.preview.forget_user_edits()
        self._restore_work()
        self.vpk_mod.load(path, paths['misc_vpk'], paths['textures_vpk'], lang=lang)
        logger.info(f"мод из VPK: {path}")
        return {'started': True, 'path': path}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Диагностика мода
    # ═══════════════════════════════════════════════════════════════════════ #

    @staticmethod
    def _report_to_dict(report) -> Dict[str, Any]:
        """
        Отчёт диагностики в простых значениях.

        Enum и dataclass наружу не отдаём: транспорт их не сериализует, а
        представление про них знать не должно. Порядок берём у отчёта
        (``sorted``) — ошибки выше предупреждений.
        """
        return {
            'healthy': bool(report.is_healthy),
            'errors': len(report.errors),
            'warnings': len(report.warnings),
            'findings': [
                {
                    'severity': f.severity.value,
                    'code': f.code,
                    'title': f.title,
                    'detail': f.detail,
                    'fix': f.fix_hint,
                    'location': f.location,
                }
                for f in report.sorted()
            ],
        }

    def diagnose(self, path: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Проверяет собранный мод и отдаёт находки событием ``diagnostics``.

        Проверять можно любой VPK, не обязательно свой: диагностика читает
        файл, а не состояние сеанса.
        """
        import os

        if not path or not os.path.isfile(path):
            return {'error': 'VPK-файл не найден'}
        if self._diag is not None and self._diag.isRunning():
            return {'error': 'Проверка уже идёт'}

        from src.services.diagnostics_worker import DiagnosticsWorker
        w = DiagnosticsWorker(vpk_path=path, language=lang)
        w.finished.connect(
            lambda report: self._put('diagnostics', ok=True,
                                     report=self._report_to_dict(report)))
        w.error.connect(
            lambda message: self._put('diagnostics', ok=False, message=message))
        self._diag = w
        w.start()
        return {'started': True, 'path': path}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Своя модель и её QC
    # ═══════════════════════════════════════════════════════════════════════ #

    def load_custom_model(self, path: str = '', keep: Optional[bool] = None,
                          lang: str = 'ru') -> Dict[str, Any]:
        """
        Подставляет свою геометрию вместо игровой.

        Два шага, потому что от ответа зависит всё дальнейшее. «Готова» —
        модель со своими материалами: карточки берутся из её SMD, доступна
        правка QC. «Только геометрия» — на экране геометрия пользователя, а
        карточки и текстуры приезжают из игрового QC (там всё сводится к
        игровым текстурам).

        Рекомендацию считаем здесь: больше одного редактируемого материала —
        почти наверняка готовая модель.
        """
        import os
        import tempfile

        from src.domain.preview.material_cards import editable_material_cards
        from src.services.smd_to_obj_service import SmdToObjService

        pending = self._pending_model
        if keep is not None and pending and pending['smd'] == (path or pending['smd']):
            # Второй заход после ответа: SMD уже сконвертирован.
            smd, obj, materials = pending['smd'], pending['obj'], pending['materials']
        else:
            if not path or not os.path.isfile(path):
                return {'error': 'Файл модели не найден'}
            obj_dir = tempfile.mkdtemp(prefix='tf2_smd_preview_')
            obj = os.path.join(obj_dir, 'model.obj')
            ok, materials = SmdToObjService.convert(path, obj)
            if not ok or not os.path.exists(obj):
                return {'error': 'SMD не сконвертировался'}
            smd = path
            materials = list(materials or [])

        cards = [c.name for c in editable_material_cards(materials)]
        if keep is None:
            self._pending_model = {'smd': smd, 'obj': obj, 'materials': materials}
            return {'ask_keep': True, 'materials': cards,
                    'recommend_keep': len(cards) > 1}

        self._pending_model = None
        with self._lock:
            p = self.preview
            p.custom_smd_path = smd
            p.custom_obj_path = obj
            p.custom_keep_materials = bool(keep)
            p.custom_qc_text = None
            p.reset_skins()
            # Командные кадры и вариант остались от ИГРОВОЙ модели — на чужой
            # геометрии они показывали бы не то. Для «только геометрии» их
            # вернёт воркер карточек.
            p.reset_team_frames()
            p.reset_misc()
            if keep:
                p.textures.material_names = cards
                p.textures.main_material = cards[0] if cards else None

        # Габариты считает та же дорожка, что и у игровой модели.
        self.controller.stop()
        self._on_model_ready(obj, '')

        paths = self.tf2_paths()
        mode = getattr(self, '_mode', '')
        if keep:
            # Стили оригинала пригодятся и своей модели: по ним переопределяют
            # текстуры вариантов.
            if 'error' not in paths and mode and p.weapon_key:
                self.skins.detect(p.weapon_key, mode, paths['misc_vpk'], lang=lang)
        elif 'error' not in paths and mode and p.weapon_key:
            self.controller.load_game_model(
                p.weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'],
                lang=lang, geometry=False)

        self._autosave()
        logger.info(f"своя модель: {smd} keep={bool(keep)} материалов={len(cards)}")
        return {'started': True, 'keep': bool(keep), 'materials': cards,
                'obj': obj}

    def drop_custom_model(self) -> Dict[str, Any]:
        """Забывает свою модель — превью вернётся к игровой при перезагрузке."""
        with self._lock:
            self.preview.reset_custom_model()
            self.preview.custom_qc_text = None
        self._pending_model = None
        self._autosave()
        return {'dropped': True}

    def qc_text(self) -> Dict[str, Any]:
        """
        QC для правки: сохранённый пользователем либо исправленный авто-QC.

        Правка QC имеет смысл только у «готовой» модели: у замены геометрии
        сборка собирает QC сама под игровые материалы.
        """
        from src.services import decompile_cache
        from src.services.model_build_service import ModelBuildService

        p = self.preview
        if not p.custom_keep_materials:
            return {'error': 'QC правится только у своей готовой модели'}

        if p.custom_qc_text:
            # $texturegroup синхронизируем со стилями, правки человека при этом
            # не теряются.
            return {'text': ModelBuildService.replace_texturegroup_in_text(
                p.custom_qc_text, ''), 'edited': True}

        qc_path = decompile_cache.find_cached_qc_for_weapon(p.weapon_key)
        text = ModelBuildService.make_corrected_qc(qc_path or '', p.weapon_key, '')
        if not text.strip():
            return {'error': 'QC ещё не извлечён из игры — дождитесь загрузки модели'}
        return {'text': text, 'edited': False}

    def save_qc(self, text: str = '') -> Dict[str, Any]:
        """Запоминает правку QC; пустой текст — вернуться к авто-QC."""
        with self._lock:
            self.preview.custom_qc_text = text.strip() or None
        self._autosave()
        return {'edited': bool(self.preview.custom_qc_text)}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Работа над предметом: сохранение правок между запусками
    # ═══════════════════════════════════════════════════════════════════════ #

    def _work_key(self) -> str:
        """Ключ работы по текущему предмету (правило — в work_keeper)."""
        from src.services import work_keeper
        return work_keeper.key_for(getattr(self, '_mode', ''),
                                   self.preview.weapon_key,
                                   self._vpk_mod_path or '')

    @staticmethod
    def _autosave_on() -> bool:
        from src.services import work_keeper
        return work_keeper.is_enabled()

    def _autosave(self) -> None:
        """Пишет правки предмета. Зовётся после КАЖДОГО изменения."""
        from src.services import work_keeper
        work_keeper.save(self.preview, self._work_key())

    def _restore_work(self) -> bool:
        """Возвращает сохранённые правки предмета."""
        from src.services import work_keeper
        with self._lock:
            return work_keeper.restore(self.preview, self._work_key())

    def forget_work(self) -> Dict[str, Any]:
        """Сбрасывает правки предмета — и в сеансе, и на диске."""
        from src.services import work_keeper
        with self._lock:
            work_keeper.forget(self.preview, self._work_key())
            # Стили шапки — тот же предмет: оставить их правки значило бы
            # собрать в мод то, что человек только что попросил забыть.
            self._hat_styles = {}
        return self.view_state()

    def work_state(self) -> Dict[str, Any]:
        """Есть ли сейчас правки и сохраняются ли они."""
        return {'has_edits': self.preview.has_user_edits(),
                'autosave': self._autosave_on()}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Карты материала и правка VMT
    # ═══════════════════════════════════════════════════════════════════════ #

    def _card_key(self, material: str = '') -> str:
        """
        Материал, к которому относится правка карточки.

        Пустая строка — ГЛАВНЫЙ материал, и это не «не выбрано»: сборка
        сопоставляет её с texture_filename сама, а страница его имени не знает.

        Служебный ключ одноматериальной модели сюда попасть не должен: под ним
        правка легла бы в хранилище именем `__single__`, которого сборка не
        ищет, — то есть молча пропала бы.
        """
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        material = (material or '').strip()
        if not material:
            names = self.preview.textures.material_names
            material = names[0] if names else ''
        return '' if material == SINGLE_TEX_KEY else material

    def texture_maps(self, material: str = '') -> Dict[str, Any]:
        """Карты, уже назначенные материалу (для показа в диалоге)."""
        return dict(self.preview.texture_maps.get(self._card_key(material), {}))

    def set_texture_maps(self, material: str = '',
                         maps: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Записывает карты материала. Пустой набор снимает их совсем.

        Присланное проверяется (``normalize_maps``): запись уходит в генератор
        VTF и в VMT, и мусорный ключ там превращается в сломанный материал.
        """
        from src.data.material_maps import normalize_maps

        if not getattr(self, '_mode', ''):
            return {'error': 'Сначала выберите предмет'}

        key = self._card_key(material)
        clean = normalize_maps(maps or {})
        with self._lock:
            if clean:
                self.preview.texture_maps[key] = clean
            else:
                self.preview.texture_maps.pop(key, None)
        self._autosave()
        return {'material': key, 'maps': clean}

    def add_to_style(self, material: str = '') -> Dict[str, Any]:
        """Добавляет материал в активный стиль (пустой карточкой)."""
        with self._lock:
            ok = self.preview.add_to_style(material)
        if not ok:
            return {'error': 'В стиль можно добавить только материал модели'}
        self._autosave()
        return self.view_state()

    def drop_from_style(self, material: str = '') -> Dict[str, Any]:
        """Убирает материал из стиля — он вернётся к базовой текстуре."""
        with self._lock:
            self.preview.drop_from_style(material)
        self._autosave()
        return self.view_state()

    def texture_settings(self, material: str = '') -> Dict[str, Any]:
        """Свои настройки материала или пусто, если он собирается как все."""
        key = self._card_key(material)
        return {'material': key,
                'settings': dict(self.preview.texture_overrides.get(key, {}))}

    def set_texture_settings(self, material: str = '',
                             settings: Optional[Dict[str, Any]] = None
                             ) -> Dict[str, Any]:
        """
        Задаёт материалу свои настройки сборки; пустые — возврат к глобальным.

        Страница присылает полный набор (разрешение, формат, флаги, опции):
        частичная запись потребовала бы знать здесь, что именно на ней сейчас
        показано, а показанное — уже отражение этого состояния.
        """
        from src.data.texture_overrides import override_badge

        if not getattr(self, '_mode', ''):
            return {'error': 'Сначала выберите предмет'}

        key = self._card_key(material)
        clean = {k: v for k, v in (settings or {}).items()
                 if k in ('size', 'format', 'flags', 'options') and v is not None}
        with self._lock:
            if clean:
                self.preview.texture_overrides[key] = clean
            else:
                self.preview.texture_overrides.pop(key, None)
        self._autosave()
        return {'material': key, 'settings': clean,
                'badge': override_badge(clean)}

    def texture_badges(self) -> Dict[str, str]:
        """{материал: подпись} — у каких карточек свои настройки сборки."""
        from src.data.texture_overrides import override_badge
        return {mat: override_badge(ov)
                for mat, ov in self.preview.texture_overrides.items() if ov}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Части модели: своя картинка на отдельный кусок
    # ═══════════════════════════════════════════════════════════════════════ #

    def _parts_model(self, material: str = '') -> Any:
        """(разбор модели, имя материала в OBJ, ключ карточки) или ошибка.

        Имена расходятся: у одноматериальной модели карточка зовётся служебным
        ключом, а группа в OBJ — материалом из SMD. Связываем их здесь, чтобы
        дальше никто про это не думал.
        """
        from src.services import mesh_parts_service

        model = mesh_parts_service.load(self._obj_path)
        if not model:
            return {'error': 'Модель ещё не загружена'}

        names = list(model.materials)
        if len(names) == 1:
            obj_mat = names[0]
        else:
            wanted = (material or self.preview.textures.stable_main() or '').lower()
            obj_mat = next((n for n in names if n.lower() == wanted), '')
            if not obj_mat:
                return {'error': 'У этого материала нет геометрии'}

        card = material or self.preview.textures.storage_main_key()
        return model, obj_mat, card

    def parts(self, material: str = '') -> Dict[str, Any]:
        """
        Части модели: что показать списком и чем подсвечивать в 3D.

        `tri_part` — номер части для КАЖДОГО треугольника материала: вьювер
        отдаёт попадание мыши номером треугольника, и по-другому связать клик с
        частью нечем.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        chosen = self.preview.part_textures.get(card, {})
        colors = self.preview.part_colors.get(card, {})
        parts = model.parts_of(obj_mat)
        tri_part = [0] * len(model.uv.get(obj_mat) or [])
        for part in parts:
            for tri in part.triangles:
                if tri < len(tri_part):
                    tri_part[tri] = part.index

        return {
            'material': card,
            'parts': [{
                'id': part.index,
                'area': round(part.uv_area, 4),
                'triangles': len(part.triangles),
                # Куски, делящие развёртку, в игре красятся вместе — молчать
                # об этом нельзя.
                'shared': list(part.shared),
                'image': chosen.get(part.index),
                'color': colors.get(part.index),
                # Место части на развёртке: по нему страница подсвечивает
                # область прямо на текстуре — иначе связь «кусок ↔ участок
                # картинки» видна только в голове у того, кто делал модель.
                'bbox': [round(v, 5) for v in part.uv_bbox],
            } for part in parts],
            'tri_part': tri_part,
            'tint': self.preview.part_tint,
        }

    def _remember_parts(self, card: str) -> None:
        """Снимок покраски ДО изменения — для отмены."""
        self._parts_history.append((
            card,
            {mat: dict(items) for mat, items in self.preview.part_textures.items()},
            {mat: dict(items) for mat, items in self.preview.part_colors.items()},
        ))
        del self._parts_history[:-20]      # глубже двадцати шагов не помнит никто

    def undo_parts(self, material: str = '') -> Dict[str, Any]:
        """Откатывает последнее изменение покраски частей."""
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            if not self._parts_history:
                return {'error': 'Отменять нечего'}
            _card, images, colors = self._parts_history.pop()
            self.preview.part_textures = images
            self.preview.part_colors = colors
            self._recompose(model, obj_mat, card)
        self._autosave()
        return self.view_state()

    def set_part_texture(self, material: str = '', part: int = 0,
                         path: Optional[str] = None) -> Dict[str, Any]:
        """Кладёт картинку на одну часть (path=None — убирает с неё)."""
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        if path and not os.path.isfile(path):
            return {'error': 'Файл не найден'}

        with self._lock:
            self._remember_parts(card)
            chosen = self.preview.part_textures.setdefault(card, {})
            if path:
                chosen[int(part)] = path
                # У части либо картинка, либо цвет: два ответа на вопрос «чем
                # красить» означали бы, что один из них молча проигрывает.
                (self.preview.part_colors.get(card) or {}).pop(int(part), None)
            else:
                chosen.pop(int(part), None)
            self._recompose(model, obj_mat, card)
        self._autosave()
        return self.view_state()

    def set_part_colors(self, material: str = '',
                        colors: Optional[Dict[str, Any]] = None,
                        strength: Optional[float] = None) -> Dict[str, Any]:
        """
        Красит части: {номер части: цвет}, значение None — снять.

        Цвет — либо «#rrggbb», либо градиент
        ``{'color': ..., 'color2': ..., 'horizontal': bool}``: одним цветом
        деталь выглядит плоской, а в настоящих скинах переход есть почти всегда.

        Скопом, а не по одной: «раскрасить всё случайно» и сброс — это одно
        действие человека, и склейка на них должна быть одна.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            self._remember_parts(card)
            if strength is not None:
                self.preview.part_tint = min(1.0, max(0.05, float(strength)))
            painted = self.preview.part_colors.setdefault(card, {})
            for part, color in (colors or {}).items():
                if color:
                    painted[int(part)] = (dict(color) if isinstance(color, dict)
                                          else str(color))
                    (self.preview.part_textures.get(card) or {}).pop(int(part), None)
                else:
                    painted.pop(int(part), None)
            self._recompose(model, obj_mat, card)
        self._autosave()
        return self.view_state()

    def clear_parts(self, material: str = '') -> Dict[str, Any]:
        """Снимает с частей всё разом — «начать заново» одной кнопкой."""
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            self._remember_parts(card)
            self.preview.part_textures.pop(card, None)
            self.preview.part_colors.pop(card, None)
            self._recompose(model, obj_mat, card)
        self._autosave()
        return self.view_state()

    def _recompose(self, model: Any, obj_mat: str, card: str) -> None:
        """
        Пересобирает текстуру материала из картинок его частей.

        Склейка кладётся туда же, куда легла бы обычная своя текстура: дальше
        по конвейеру — сборка, автосохранение, превью — про части не знает
        никто, и знать не должен.
        """
        from src.services import texture_compose_service

        t = self.preview.textures
        images = self.preview.part_textures.get(card) or {}
        colors = self.preview.part_colors.get(card) or {}
        if not (images or colors):
            self.preview.part_textures.pop(card, None)
            self.preview.part_colors.pop(card, None)
            # Убрали последнее — материал возвращается к тому, что было под
            # склейкой.
            if t.uploaded_for_mat(card) in self._composites:
                t.set_texture(card, None)
            return

        # Основа: своя текстура пользователя, если она не наша же склейка.
        base = t.uploaded_for_mat(card)
        if not base or base in self._composites:
            base = t.game_base(card)

        Layer = texture_compose_service.Layer
        layers = [Layer(polygons=model.polygons(obj_mat, part), image=image)
                  for part, image in sorted(images.items())]
        layers += [Layer(polygons=model.polygons(obj_mat, part),
                         strength=self.preview.part_tint,
                         **_paint_spec(color))
                   for part, color in sorted(colors.items())]
        # Имя со счётчиком: путь — это ещё и адрес картинки во вьювере, и по
        # прежнему имени браузер показал бы предыдущую склейку из кэша.
        self._compose_seq = getattr(self, '_compose_seq', 0) + 1
        out = os.path.join(self._work_dir(),
                           f"parts_{self._compose_seq}.png")
        result = texture_compose_service.compose(base, layers, out)
        if not result:
            return
        self._composites.add(result)
        t.set_texture(card, result)

    def _work_dir(self) -> str:
        """Своя папка сеанса для склеек. Живёт до перезапуска, как и превью."""
        import tempfile

        folder = getattr(self, '_tmp_dir', '')
        if not folder or not os.path.isdir(folder):
            folder = tempfile.mkdtemp(prefix='tf2sg_parts_')
            self._tmp_dir = folder
        return folder

    def _vmt_target(self, material: str = '') -> Any:
        """(ключ правки, ключ модели, имя материала) либо словарь с ошибкой."""
        from src.data.weapons import SPECIAL_MODES
        from src.services import vmt_source_service

        mode = getattr(self, '_mode', '')
        if not mode:
            return {'error': 'Сначала выберите предмет'}
        if mode in set(SPECIAL_MODES) | {'custom'}:
            return {'error': 'Для этого режима редактор VMT недоступен'}

        target = vmt_source_service.resolve_target(
            mode, hat_mdl=self.preview.weapon_key)
        if target is None:
            return {'error': 'Для этого режима редактор VMT недоступен'}

        weapon_key, _display = target
        # Ключ хранения правки — имя материала: у главного он совпадает с
        # texture_filename, который сборка и ищет.
        return weapon_key, (self._card_key(material) or weapon_key)

    def open_vmt(self, material: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Отдаёт текст VMT для правки: сохранённую версию либо игровой оригинал.

        Оригинал возвращается всегда отдельным полем — по нему работает
        «вернуть как в игре», и без него сброс вернул бы саму правку.
        """
        from src.services.edited_vmt_service import EditedVMTService
        from src.services import vmt_source_service

        target = self._vmt_target(material)
        if isinstance(target, dict):
            return target
        weapon_key, edit_key = target
        mode = getattr(self, '_mode', '')

        paths = self.tf2_paths()
        tf2_root = '' if 'error' in paths else paths['root']

        original = None
        edited_path = EditedVMTService.get_edited_vmt(edit_key)
        if edited_path and os.path.exists(edited_path):
            original = EditedVMTService.read_original_backup(edit_key)
            if original is None and tf2_root:
                original = vmt_source_service.original_content(
                    mode, weapon_key, tf2_root, edit_key, lang)
            try:
                with open(edited_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError as exc:
                return {'error': f'не прочитать правку: {exc}'}
            return {'material': edit_key, 'content': content,
                    'original': original if original is not None else content,
                    'edited': True}

        if not tf2_root:
            return paths
        original = vmt_source_service.original_content(
            mode, weapon_key, tf2_root, edit_key, lang)
        if original is None:
            return {'error': f'Оригинальный VMT для «{edit_key}» не найден'}
        return {'material': edit_key, 'content': original,
                'original': original, 'edited': False}

    def save_vmt(self, material: str = '', content: str = '',
                 original: str = '') -> Dict[str, Any]:
        """Сохраняет правку VMT. Сломанный синтаксис не сохраняется."""
        from src.services import vmt_source_service

        target = self._vmt_target(material)
        if isinstance(target, dict):
            return target
        _weapon_key, edit_key = target

        ok, error, saved = vmt_source_service.save_edit(
            edit_key, content, original or None)
        if not ok:
            return {'error': error}
        return {'material': edit_key, 'content': saved, 'edited': True}

    def reset_vmt(self, material: str = '') -> Dict[str, Any]:
        """Удаляет правку: материал вернётся к игровому оригиналу."""
        from src.services.edited_vmt_service import EditedVMTService

        target = self._vmt_target(material)
        if isinstance(target, dict):
            return target
        _weapon_key, edit_key = target
        EditedVMTService.delete_edited_vmt(edit_key)
        return {'material': edit_key, 'edited': False}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Инструменты: извлечение оригиналов и объединение модов
    # ═══════════════════════════════════════════════════════════════════════ #

    @staticmethod
    def _export_settings() -> tuple:
        """Куда и в каком формате писать результат инструментов."""
        from src.config.app_config import AppConfig
        cfg = AppConfig.load_config()
        return (cfg.get('export_folder') or 'export',
                cfg.get('export_image_format') or 'PNG')

    def _run_tool(self, worker, done: str = 'tool_done') -> Dict[str, Any]:
        """
        Запускает воркер-инструмент и переводит его сигналы в события.

        Инструмент один на сеанс: две декомпиляции разом дерутся за один
        временный каталог — в приложении это ровно та же проверка
        (``_worker_busy``).
        """
        worker.progress.connect(lambda pct, text: self._put('progress', text=text))
        worker.finished.connect(
            lambda ok, msg: self._put(done, ok=bool(ok), message=msg))
        worker.error.connect(
            lambda msg: self._put(done, ok=False, message=msg))
        self._tool = worker
        worker.start()
        return {'started': True}

    def _tool_busy(self) -> bool:
        return self._tool is not None and self._tool.isRunning()

    def extract_model(self, lang: str = 'ru') -> Dict[str, Any]:
        """
        Декомпилирует модель предмета и отдаёт список готовых файлов.

        Операция двухшаговая, как и в приложении: сначала файлы готовятся во
        временном каталоге, потом человек выбирает, что из них сохранить
        (``export_model_files``). Список приезжает событием ``extract_files``.
        """
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self, '_mode', '')
        # Ключ предмета берём тот же, по которому грузилось превью: у шапок он
        # свой на каждую вещь и из режима не выводится.
        key = self.preview.weapon_key or model_key_for(mode)
        if not key:
            return {'error': f'Для режима «{mode}» модели нет'}

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths
        if self._tool_busy():
            return {'error': 'Извлечение уже идёт'}

        from src.services.extract_model_worker import ExtractModelWorker
        w = ExtractModelWorker(tf2_root_dir=paths['root'], mode=mode,
                               weapon_key=key, language=lang)
        w.progress.connect(lambda pct, text: self._put('progress', text=text))
        w.finished.connect(lambda ok, msg: self._model_prepared(w, ok, msg))
        w.error.connect(lambda msg: self._put('extract_files', ok=False,
                                              message=msg, files=[], selected=[]))
        self._tool = w
        w.start()
        return {'started': True}

    def _model_prepared(self, worker, ok: bool, message: str) -> None:
        """Файлы готовы во временном каталоге — ждём выбора страницы."""
        from src.services.extract_model_service import ExtractModelService

        files = list(getattr(worker, 'prepared_files', None) or [])
        temp = getattr(worker, 'prepared_temp_dir', None)
        decompile = getattr(worker, 'prepared_decompile_dir', None)
        if not (ok and files and temp and decompile):
            if temp:
                ExtractModelService.cleanup_temp_dir(temp)
            self._prepared = None
            self._put('extract_files', ok=False, message=message,
                      files=[], selected=[])
            return

        self._prepared = {'temp': temp, 'decompile': decompile,
                          'key': worker.weapon_key}
        self._put('extract_files', ok=True, message=message, files=files,
                  selected=ExtractModelService.default_export_selection(files))

    def export_model_files(self, files: Optional[List[str]] = None,
                           lang: str = 'ru') -> Dict[str, Any]:
        """
        Сохраняет выбранные файлы модели в папку экспорта.

        Пустой список — отказ: временный каталог тогда убирается сразу, иначе
        декомпиляция висела бы в temp до перезапуска.
        """
        from src.services.extract_model_service import ExtractModelService

        prepared = self._prepared
        if not prepared:
            return {'error': 'Сначала извлеките модель'}

        chosen = [f for f in (files or []) if f]
        if not chosen:
            ExtractModelService.cleanup_temp_dir(prepared['temp'])
            self._prepared = None
            return {'cancelled': True}
        if self._tool_busy():
            return {'error': 'Извлечение уже идёт'}

        export_folder, _ = self._export_settings()
        from src.services.export_model_files_worker import ExportModelFilesWorker
        w = ExportModelFilesWorker(
            temp_dir=prepared['temp'],
            decompile_dir=prepared['decompile'],
            selected_files=chosen,
            export_folder=export_folder,
            weapon_key=prepared['key'],
            language=lang,
        )
        self._prepared = None
        return self._run_tool(w)

    def character_textures(self) -> List[str]:
        """
        Текстуры персонажа в игровом VPK — из них выбирают, что извлекать.

        У тела персонажа их бывает под два десятка (лицо, части формы,
        экипировка), поэтому приложение спрашивает, а не тащит всё подряд.
        """
        from src.data.player_characters import PLAYER_CHARACTERS

        folder = PLAYER_CHARACTERS.get(getattr(self, '_mode', ''), {}).get('folder')
        if not folder:
            return []
        paths = self.tf2_paths()
        if 'error' in paths:
            return []

        from src.services.vpk_cache import open_vpk_cached
        try:
            pak = open_vpk_cached(paths['textures_vpk'])
        except OSError as exc:
            logger.warning(f"не открыть VPK текстур: {exc}")
            return []
        if pak is None:
            return []

        prefix = f"materials/models/player/{folder}/"
        return sorted(
            path[len(prefix):-4] for path in pak
            if path.startswith(prefix) and path.lower().endswith('.vtf')
            and '/' not in path[len(prefix):]
        )

    def extract_texture(self, textures: Optional[List[str]] = None,
                        lang: str = 'ru') -> Dict[str, Any]:
        """
        Извлекает оригинальные текстуры предмета в папку экспорта.

        У тела персонажа выбор обязателен: без списка возвращается
        ``need_textures`` — страница спрашивает, что брать, и зовёт снова.
        """
        from src.data.player_characters import (
            PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS,
        )
        from src.data.player_hands import HAND_MODE_KEYS, get_hand_textures
        from src.data.weapons import SPECIAL_MODES
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self, '_mode', '')
        if not mode:
            return {'error': 'Сначала выберите предмет'}
        if mode in SPECIAL_MODES:
            return {'error': 'Для этого режима оригинальной текстуры нет'}

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths
        if self._tool_busy():
            return {'error': 'Извлечение уже идёт'}

        export_folder, export_format = self._export_settings()

        # Шапка: своя цепочка QC → VMT → $baseTexture, у каждой вещи своя модель.
        if mode == 'hat':
            key = self.preview.weapon_key
            if not key:
                return {'error': 'Сначала выберите шапку'}
            from src.services.hat_texture_extract_worker import HatTextureExtractWorker
            return self._run_tool(HatTextureExtractWorker(
                hat_mdl_path=key, tf2_root_dir=paths['root'],
                export_folder=export_folder, export_format=export_format,
                language=lang))

        is_body = mode in PLAYER_BODY_MODE_KEYS

        if is_body:
            if not textures:
                return {'need_textures': self.character_textures()}
            folder = PLAYER_CHARACTERS.get(mode, {}).get('folder', '')
            explicit = [(folder, name) for name in textures]
        elif mode in HAND_MODE_KEYS:
            explicit = get_hand_textures(mode)
        else:
            explicit = None

        # У рук ключ — модель предплечья: под ним лежит QC в кэше декомпиляции,
        # и служба берёт из него ПОЛНЫЙ $texturegroup — те же текстуры, что
        # положит сборка (список в player_hands бывает неполным).
        #
        # У тела персонажа ключ не передаём НАМЕРЕННО: там список выбрал
        # человек, и подмена его группой из QC вернула бы всё подряд.
        key = '' if is_body else model_key_for(mode)
        if not key and not is_body:
            return {'error': f'Для режима «{mode}» текстуры не найти'}

        from src.services.extract_texture_worker import ExtractTextureWorker
        return self._run_tool(ExtractTextureWorker(
            textures_vpk_path=paths['textures_vpk'],
            weapon_key=key,
            export_folder=export_folder,
            export_format=export_format,
            language=lang,
            hand_textures=explicit,
            use_explicit_list=bool(explicit),
        ))

    def export_vpks(self) -> List[str]:
        """Имена собранных модов в папке экспорта — из них выбирают, что слить."""
        from pathlib import Path
        export_folder, _ = self._export_settings()
        folder = Path(export_folder)
        if not folder.is_dir():
            return []
        return sorted((f.name for f in folder.glob('*.vpk')), key=str.lower)

    def merge_vpk(self, files: Optional[List[str]] = None, name: str = '',
                  confirmed: bool = False, lang: str = 'ru') -> Dict[str, Any]:
        """
        Сливает несколько модов из папки экспорта в один VPK.

        Моды, трогающие одно оружие, друг друга затирают — о таких сначала
        предупреждаем (``duplicates``) и ждём подтверждения, как это делает
        окно приложения.
        """
        from pathlib import Path
        from src.services.merge_vpk_service import MergeVPKService

        chosen = [f for f in (files or []) if f]
        if len(chosen) < 2:
            return {'error': 'Выберите хотя бы два мода'}
        if not name.strip():
            return {'error': 'Задайте имя выходного файла'}
        if self._tool_busy():
            return {'error': 'Объединение уже идёт'}

        export_folder, _ = self._export_settings()
        # От страницы берём только имена: путь собираем сами, иначе она могла бы
        # указать файл за пределами папки экспорта.
        paths = [Path(export_folder) / Path(f).name for f in chosen]
        missing = [p.name for p in paths if not p.is_file()]
        if missing:
            return {'error': 'Не найдены: ' + ', '.join(missing)}

        if not confirmed:
            duplicates = MergeVPKService.check_duplicate_weapons(paths)
            if duplicates:
                return {'duplicates': {str(k): list(v) for k, v in duplicates.items()}}

        from src.services.merge_vpk_worker import MergeVpkWorker
        return self._run_tool(MergeVpkWorker(paths, name.strip(), export_folder, lang))

    def set_skin(self, index: int) -> Dict[str, Any]:
        """Переключает вариантный стиль. Что показывать — пересчитает домен."""
        with self._lock:
            self.preview.textures.active_skin = int(index)
        return self.view_state()

    def view_state(self) -> Dict[str, Any]:
        """
        Что показывать прямо сейчас: текстуры, команда, доступные варианты.

        Одно место вместо россыпи запросов — страница спрашивает его после
        любого изменения (смена команды, вариант, стиль) и применяет ответ
        целиком. Правила разрешения при этом остаются в домене.
        """
        from src.data.player_hands import HAND_MODE_KEYS

        t = self.preview.textures
        mode = (self.preview.current_object or ('', '', ''))[0]
        is_hands = bool(mode) and mode in HAND_MODE_KEYS

        return {
            'textures': self.preview.visible_textures(),
            # Меши красятся ПОЛНЫМ набором: карточки отфильтрованы, а служебная
            # геометрия без текстуры осталась бы серой.
            'scene': self.preview.scene_textures(),
            'materials': self.preview.card_materials(),
            'team': t.active_team,
            'has_teams': self.preview.has_team_variant(is_hands) or t.force_team,
            'blu_matches_red': self.preview.blu_matches_red,
            'has_australium': bool(t.australium_frame),
            'australium_active': t.australium_active,
            # «Прочее» — не для рук и не для мода из VPK: там карточки строятся
            # не из материалов модели.
            'has_misc': bool(self.preview.misc_materials
                             and not self.preview.custom_vpk_mode
                             and not is_hands),
            'misc_mode': self.preview.misc_mode,
            'force_team': t.force_team,
            'can_force_team': self.preview.can_force_team(),
            # Правка QC имеет смысл только у СВОЕЙ готовой модели: у замены
            # геометрии сборка собирает QC сама под игровые материалы.
            'custom_keep': bool(self.preview.custom_smd_path
                                and self.preview.custom_keep_materials),
            'framerate': self.preview.team_framerate,
            'skins': self.preview.textures.skin_info,
            'active_skin': self.preview.textures.active_skin,
            # Вариантный стиль переопределяет базу выборочно: странице нужно
            # знать, что ещё можно в него добавить.
            'style': self.preview.active_style,
            'style_candidates': self.preview.style_candidates(),
        }

    def toggle_misc(self, on: Optional[bool] = None) -> Dict[str, Any]:
        """Показывает служебные материалы («Прочее») или возвращает обычные."""
        with self._lock:
            self.preview.toggle_misc(on)
        return self.view_state()

    def force_team(self) -> Dict[str, Any]:
        """Включает «сделать командным» — сборка синтезирует BLU-строку."""
        with self._lock:
            self.preview.enable_force_team()
        self._autosave()
        return self.view_state()

    def set_team(self, team: str) -> Dict[str, Any]:
        """Переключает команду и отдаёт новое состояние показа."""
        from src.shared.constants import Team

        wanted = Team.BLU if str(team).upper() == Team.BLU.upper() else Team.RED
        with self._lock:
            self.preview.textures.active_team = wanted
        return self.view_state()

    def set_australium(self, active: bool) -> Dict[str, Any]:
        """Включает или гасит вариант Australium."""
        with self._lock:
            self.preview.textures.australium_active = bool(active)
        return self.view_state()

    def stop_preview(self) -> Dict[str, Any]:
        self.controller.stop()
        return {'stopped': True}

    @staticmethod
    def tf2_paths() -> Dict[str, Any]:
        """Пути к игровым VPK или понятная ошибка, если игра не найдена."""
        from src.config.app_config import AppConfig

        root = (AppConfig.load_config().get('tf2_game_folder') or '').strip()
        if not root:
            return {'error': 'Папка Team Fortress 2 не задана в настройках'}
        try:
            from src.services.tf2_paths import TF2Paths
            _, misc_vpk, tf_dir = TF2Paths.resolve(root)
            textures_vpk = TF2Paths.resolve_textures_vpk(root)
        except Exception as exc:  # noqa: BLE001 — путь задаёт пользователь
            return {'error': f'Не удалось разобрать папку игры: {exc}'}
        if not misc_vpk:
            return {'error': 'В папке игры не найден tf2_misc_dir.vpk'}
        return {'root': root, 'tf_dir': tf_dir,
                'misc_vpk': misc_vpk, 'textures_vpk': textures_vpk or ''}


#: Единственный сеанс процесса. Создаётся лениво: импорт модуля не должен
#: тянуть за собой воркеры и конфиг.
_session: Optional[AppSession] = None


def session() -> AppSession:
    global _session
    if _session is None:
        _session = AppSession()
    return _session
