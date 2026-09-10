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

import hashlib
import os
import queue
import re
import threading
from typing import Any, Dict, List, Optional

from src.app.preview_controller import (
    Preview3DController, SkinDetectController, SkyboxController,
    ViewmodelController, VpkModController,
)
from src.domain.preview.session import PreviewSession
from src.shared.logging_config import get_logger
from src.shared.paths import data_dir

logger = get_logger(__name__)

#: «Ответа ещё нет» для запомненного выбора текстуры. Отдельный сторож, потому
#: что сам ответ бывает None — это «взять главную текстуру».
_NO_CHOICE = object()


def _paint_spec(color: Any, brush: Optional[Dict[str, Any]] = None
                ) -> Dict[str, Any]:
    """
    Цвет части в вид, понятный склейке.

    Хранится либо строка «#rrggbb», либо градиент словарём: старые работы
    писались строкой, и ломать их из-за новой возможности незачем.

    Направление раньше было флагом ``horizontal`` (два варианта), теперь это
    угол в градусах. Флаг из старых работ читаем и переводим здесь — так
    правило перевода одно на всё приложение, а склейка знает только угол.

    `brush` — настройки кисти на СЕЙЧАС: сила, точный цвет, окантовка. Они
    подставляются только там, где в самой записи ничего не сказано: у мазка
    настройки те, что были в момент нанесения, и переключатель кисти не должен
    задним числом менять уже покрашенное. Старые работы своих не помнят —
    им достаются нынешние, как и было.
    """
    at = dict(brush or {})

    def kept(name: str, fallback: Any) -> Any:
        got = color.get(name) if isinstance(color, dict) else None
        return at.get(name, fallback) if got is None else got

    if not isinstance(color, dict):
        return {'color': str(color),
                'strength': float(at.get('strength', 1.0)),
                'exact': bool(at.get('exact', False)),
                'edge': float(at.get('edge', 0.0)),
                'edge_color': at.get('edge_color') or None}
    angle = color.get('angle')
    if angle is None:
        angle = 90.0 if color.get('horizontal') else 0.0
    # Края и середина перехода. Их может не быть вовсе (работы до них и
    # обычный градиент от края до края), поэтому умолчания те же, что у слоя.
    start = _fraction(color.get('start'), 0.0)
    end = _fraction(color.get('end'), 1.0)
    return {'color': str(color.get('color') or ''),
            'color2': (str(color.get('color2')) if color.get('color2') else None),
            'angle': float(angle),
            # Настройки кисти в момент мазка: сила, точный цвет, окантовка.
            'strength': float(kept('strength', 1.0)),
            'exact': bool(kept('exact', False)),
            'edge': float(kept('edge', 0.0)),
            'edge_color': kept('edge_color', None) or None,
            'start': start,
            'end': end,
            'mid': _fraction(color.get('mid'), 0.5)}


def _fraction(value: Any, default: float) -> float:
    """Доля 0..1 из того, что прислала страница. Мусор — умолчание."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _image_spec(value: Any, brush: Optional[Dict[str, Any]] = None
                ) -> Dict[str, Any]:
    """
    Картинка части в вид, понятный склейке.

    Хранится либо путь строкой, либо словарь с настройкой посадки: как и у
    цвета с градиентом, старые работы писались строкой, и ломать их из-за новой
    возможности незачем.

    Умолчание — 'contain': растяжение по прямоугольнику корёжило логотипы, а
    заметно это становилось только в игре.
    """
    at = dict(brush or {})
    if not isinstance(value, dict):
        return {'path': str(value), 'fit': 'contain', 'angle': 0.0,
                'scale': 1.0, 'scale_y': 1.0, 'offset': (0.0, 0.0),
                'anchor': None,
                'edge': float(at.get('edge', 0.0)),
                'edge_color': at.get('edge_color') or None}
    offset = value.get('offset') or (0.0, 0.0)
    fit = str(value.get('fit') or 'contain')
    return {
        'path': str(value.get('path') or ''),
        'fit': fit if fit in ('contain', 'cover', 'stretch') else 'contain',
        'angle': float(value.get('angle') or 0.0),
        # Ноль и отрицательный масштаб — это исчезнувшая картинка; такой
        # «результат» человек примет за поломку, а не за свою настройку.
        'scale': max(0.05, min(20.0, float(value.get('scale') or 1.0))),
        # По высоте — свой множитель. Его может не быть (работы до растяжения
        # и картинки, которые тянули только за угол): тогда он равен ширинному.
        'scale_y': max(0.05, min(20.0, float(
            value.get('scale_y') or value.get('scale') or 1.0))),
        'offset': (float(offset[0]), float(offset[1])),
        # Габарит части, в который картинку вписали изначально. Появляется
        # только при переносе на новые части (см. `_reshape`): после разреза
        # наклейка должна остаться на том же месте развёртки, а не
        # перерисоваться заново в каждой половине.
        'anchor': _anchor(value.get('anchor')),
        # Окантовка — настройка кисти в момент, когда картинку клали.
        'edge': float(value.get('edge')
                      if value.get('edge') is not None
                      else at.get('edge', 0.0)),
        'edge_color': (value.get('edge_color')
                       or at.get('edge_color') or None),
    }


def _anchor(value: Any) -> Optional[tuple]:
    """Габарит (u0, v0, u1, v1) из работы. Мусор — как будто его нет."""
    try:
        u0, v0, u1, v1 = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    return (u0, v0, u1, v1) if u1 > u0 and v1 > v0 else None


#: Как называются склейки частей: `parts_<номер>.png`. Имя задаём мы сами
#: (см. `AppSession._recompose`), поэтому оно и служит признаком «наше» для
#: работы, вернувшейся с диска: множество путей переживает только один запуск.
#:
#: Хвост `_<номер>` дописывает `work_store`, когда рядом уже лежит файл с таким
#: именем от другого материала: на диске склейка зовётся `parts_1_25.png`, и
#: без этого хвоста в шаблоне «Убрать всё» её не узнавало.
_COMPOSITE_NAME = re.compile(r'^parts_\d+(?:_\d+)*\.png$', re.IGNORECASE)


def _is_composite_name(path: str) -> bool:
    """Похож ли файл на нашу склейку частей."""
    return bool(_COMPOSITE_NAME.match(os.path.basename(path or '')))


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


def _sound_title(entry, items: List[str], known: str,
                 classes: Dict[str, str]) -> str:
    """Подпись строки: чей это звук, человеческими словами.

    Порядок источников — от точного к догадке. У реплики класс стоит прямо в
    имени записи (`Scout.PainSharp01`), у оружейного звука предмет называет
    items_game, а если молчат оба — опознаём по имени субъекта.
    """
    if entry.subject.lower() in classes:
        return classes[entry.subject.lower()]
    if items:
        return items[0]
    return known or entry.subject.replace('_', ' ')


#: Строка без разделителей и регистра — для поиска. В именах записей звука
#: Valve непоследователен: `Weapon_Scatter_Gun` рядом с `Weapon_Shotgun`, и
#: буквальное совпадение подстроки половину названий не находит.
def _plain(text: str) -> str:
    return re.sub(r'[^0-9a-zA-Zа-яёА-ЯЁ]+', '', text or '').lower()


class AppSession:
    """Состояние превью, контроллер загрузки и очередь событий для страницы."""

    def __init__(self) -> None:
        self.preview = PreviewSession()
        self.controller = Preview3DController(self.preview)
        self.skins = SkinDetectController(self.preview)
        self.viewmodel = ViewmodelController(self.preview)
        #: Сцена насмешки — тот же контроллер, но свой экземпляр: у него свой
        #: воркер, и вид от первого лица не должен его гасить.
        self.taunt = ViewmodelController(self.preview)
        # Спец-режимы: крит и эффекты смерти показывают ту же анимированную
        # сцену, только вместо предмета в ней умирающий солдат.
        self.death = ViewmodelController(self.preview)
        #: Выбранные свои звуки: {имя записи: файл}. Страница звуков живёт
        #: отдельно от предмета, и в состоянии превью ей места нет.
        self._sound_picks: Dict[str, str] = {}
        #: Замены ОТДЕЛЬНЫХ файлов: {путь файла в игре: файл человека}. У 1274
        #: записей файлов несколько — обычно варианты одного звука, чтобы не
        #: приедался, — и менять иногда надо один, а не все сразу.
        self._wave_picks: Dict[str, str] = {}
        self._sound_cache: List[Dict[str, Any]] = []
        self._sound_lang: Optional[str] = None
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
        #: Отменённое — чтобы вернуть его вперёд. Любая новая правка список
        #: обнуляет: вернуться «в будущее», которого уже не будет, нельзя.
        self._parts_future: List[Any] = []
        #: Склейки, которые сделали мы сами. Отличать их от своей текстуры
        #: пользователя обязательно: иначе следующая склейка легла бы поверх
        #: предыдущей и «убрать картинку с части» ничего не вернуло бы.
        # Пути ВСЕХ склеек, что мы делали. Множество не чистится нарочно: по
        # нему `_recompose` отличает свою склейку от пользовательской текстуры,
        # и забытая запись означала бы, что склейка станет основой следующей —
        # правки копились бы слоями. Строки дёшевы, а вот файлы удаляем.
        self._composites: set = set()
        #: Порядок их появления: старые ФАЙЛЫ чистим, пути оставляем.
        self._compose_files: List[str] = []
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
        c.failed.connect(self._fail)

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
        v.clip.connect(lambda c: self._put('fp_clip', clip=c or {}))

        # Насмешка: та же анимированная сцена, но камера свободная — рига у
        # неё нет, персонажа смотрят со стороны.
        t = self.taunt
        t.progress.connect(lambda text: self._put('progress', text=text))
        t.failed.connect(self._fail)
        t.animated.connect(lambda scene: self._put('taunt_animated', scene=scene))
        t.materials.connect(lambda m: self._put('materials', materials=dict(m or {})))
        t.editable.connect(lambda n: self._put('fp_editable', names=list(n)))
        t.classes.connect(lambda c: self._put('taunt_classes', classes=list(c)))
        t.render_hints.connect(lambda h: self._put('render_hints', hints=h or {}))

        # Спец-режим: сцена приходит своим событием — странице надо знать, что
        # с ней делать (у крита билборд, у эффекта смерти текстура на всё тело).
        d = self.death
        d.progress.connect(lambda text: self._put('progress', text=text))
        d.failed.connect(self._fail)
        d.animated.connect(
            lambda scene: self._put('special_animated', scene=scene,
                                    mode=getattr(self, '_mode', '')))
        d.materials.connect(lambda m: self._put('materials', materials=dict(m or {})))
        d.render_hints.connect(lambda h: self._put('render_hints', hints=h or {}))
        v.render_hints.connect(lambda h: self._put('render_hints', hints=h or {}))
        v.failed.connect(self._fail)

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
        # Мод опознан: страница откроет вид от первого лица — там он и
        # проверяется, в руках и в движении.
        m.weapon.connect(
            lambda key, smd: self._put('mod_weapon', key=key, ready=bool(smd)))
        m.failed.connect(self._fail)

        # Скайбокс: шесть граней кубмапы.
        self.skybox.ready.connect(lambda faces: self._put('skybox', faces=faces))
        self.skybox.failed.connect(self._fail)

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

    def _fail(self, error: str) -> None:
        """
        Провал работы — с объяснением, а не одной технической строкой.

        `error` приходит от воркера как есть: это может быть текст исключения,
        вывод crowbar или studiomdl, сообщение Windows. На каком он языке —
        неизвестно, и человеку он обычно ничего не говорит.

        error_classifier разбирает его ПО СОДЕРЖИМОМУ и отдаёт понятный
        заголовок с объяснением на языке интерфейса. Тем самым работает и на
        английских сообщениях самих инструментов, и не требует, чтобы каждая
        строка в приложении была переведена.

        Исходный текст отдаём тоже: он нужен в «технических деталях» — тому,
        кто полезет разбираться, и тому, кому это пришлют.
        """
        from src.shared.error_classifier import classify

        try:
            from src.config.app_config import AppConfig
            language = AppConfig.load_config().get('language') or 'en'
        except Exception:                                    # noqa: BLE001
            language = 'en'

        title, detail = classify(str(error), language=language)
        self._put('failed', error=str(error), title=title, detail=detail)

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
                     style: Optional[int] = None,
                     restore: bool = False) -> Dict[str, Any]:
        """
        Начинает загрузку 3D-превью предмета.

        restore — вернуть сохранённую работу. По умолчанию НЕТ: каталог
        показывает предмет таким, какой он в игре. Свои работы открываются
        своим списком (`works`), иначе выбор «Обрез» молча давал бы чужой
        обрез, и вернуться к игровому было нечем.

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
                return self._load_texture_only(mode, restore, lang)
            return {'error': f'Для режима «{mode}» 3D-модели нет'}

        # Состояние сеанса чистит переход, а не контроллер: правила «что
        # забыть» живут в домене. Смена ПРЕДМЕТА забывает и пользовательские
        # текстуры — иначе скин одного оружия переезжает на другое.
        with self._lock:
            self.preview.begin_item(weapon_key, mode)
            # begin_game_model гасит custom_vpk_mode — мод перестаёт быть
            # источником сборки, и его путь тоже надо забыть.
            self.preview.begin_game_model()
            # И OBJ прошлого предмета: по нему считаются части, и оставленный
            # путь означал бы, что «разделить на части» разберёт ПРЕДЫДУЩУЮ
            # модель, пока новая ещё грузится. У скайбокса и спрея модели нет
            # вовсе, и там он висел бы до конца сеанса.
            self._obj_path = ''
        self.vpk_mod.stop()
        self._vpk_mod_path = None
        # Собранные сцены принадлежали ПРОШЛОМУ предмету: и вид от первого
        # лица, и насмешка. Не погасив их, мы получили бы кадр чужого
        # предмета поверх нового — воркер досчитает и пришлёт свою сцену.
        self.viewmodel.stop()
        self.taunt.stop()
        self.death.stop()

        # Правки возвращаем ДО запуска воркера: они лягут на карточки, как
        # только приедут материалы, и человек не увидит пустой альбом там, где
        # вчера была работа. Но ТОЛЬКО если работу и просили открыть: каталог
        # показывает предмет игровым.
        self._mode = mode
        if restore:
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

    def _forget_model(self) -> None:
        """Сцена без модели: резать больше нечего, путь к OBJ забываем."""
        self._obj_path = ''

    def _load_texture_only(self, mode: str, restore: bool = False,
                           lang: str = 'ru') -> Dict[str, Any]:
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
            # Карточка стояла пустой: у режима один материал, и что именно
            # заменяешь, было не видно. Кладём в неё игровую текстуру — ту
            # самую, что сейчас в игре.
            self.preview.textures.vpk_red_tex_map = (
                {SINGLE_TEX_KEY: self._game_texture(mode)}
                if self._game_texture(mode) else {})
            self._forget_model()
        self._mode = mode
        self._vpk_mod_path = None
        if restore:
            self._restore_work()

        logger.info(f"режим без модели: {mode}")
        # У крита и эффектов смерти сцена ЕСТЬ — персонаж: у крита текстура
        # висит билбордом над ним, у эффекта ложится на него самого. Модель
        # процедурная, если своя не положена в tools/Model.
        # `pending` говорит странице, что настоящая сцена уже собирается:
        # кубики-заглушку показывать не надо, иначе при каждом переключении
        # режима в кадре мелькает человечек из коробок.
        from src.services.death_scene_worker import SEQUENCES as _DEATHS

        self._put('texture_only', mode=mode, pending=(mode in _DEATHS),
                  **self._scene_for(mode))
        # Кубики-заглушка остаются запасным кадром: настоящую сцену собирает
        # воркер, и это секунды на распаковку модели и анимаций.
        self._start_death_scene(mode, lang)
        return {'texture_only': True, 'mode': mode}

    def _start_death_scene(self, mode: str, lang: str = 'ru') -> None:
        """Сцена смерти солдата под спец-режим — если игра на месте."""
        from src.services.death_scene_worker import SEQUENCES

        if mode not in SEQUENCES:
            return
        paths = self.tf2_paths()
        if 'error' in paths:
            return
        self.controller.stop()
        self.viewmodel.stop()
        self.taunt.stop()
        self.death.load_death(mode, paths['misc_vpk'], paths['textures_vpk'],
                              lang=lang)

    def _game_texture(self, mode: str) -> str:
        """Игровая текстура спец-режима как PNG. Считается один раз на режим."""
        if getattr(self, '_game_tex_mode', '') != mode:
            from src.services import special_scene_service as scene

            paths = self.tf2_paths()
            self._game_tex_mode = mode
            self._game_tex = ('' if 'error' in paths else scene.game_texture(
                mode, [paths['misc_vpk'], paths['textures_vpk']]))
        return self._game_tex

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
                model_texture = scene.game_texture(
                    mode, [paths['misc_vpk'], paths['textures_vpk']])
            return {'scene_kind': 'death', 'model': model,
                    'model_texture': model_texture}
        return {'scene_kind': 'crit', 'model': model,
                'model_texture': model_texture}

    def load_first_person(self, action: str = 'IDLE', lang: str = 'ru',
                          full: bool = False) -> Dict[str, Any]:
        """Собирает сцену «руки класса с оружием» для текущего предмета.

        full — собрать целиком, даже если сцена уже в кадре. Нужен странице
        как отход назад: если дорожки лечь не смогли (сцены на экране почему-то
        нет), она просит полную сборку, и без этого флага мы бы снова ответили
        одними дорожками — по кругу.
        """
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self, '_mode', '')
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        key = model_key_for(mode)
        # Чужой мод из VPK — тоже оружие, просто опознанное по путям внутри
        # файла. Показываем его тем же видом: скелет и анимации игровые, меш
        # из мода.
        custom_smd = ''
        if not key and self.preview.custom_vpk_mode:
            key = self.preview.custom_vpk_weapon or ''
            custom_smd = self.preview.custom_vpk_smd or ''
        if not key:
            return {'error': 'Вид от первого лица есть только у оружия'}

        # Та же сцена уже в кадре — меняем ОДНИ ДОРОЖКИ. Меш, скелет и
        # текстуры у одного оружия те же, и пересобирать их ради выбора
        # анимации значит каждый раз заново распаковывать текстуры.
        if not full and self.viewmodel.shows(key, mode):
            self.viewmodel.load_clip(key, mode, paths['misc_vpk'],
                                     paths['textures_vpk'], paths['root'],
                                     action=action, lang=lang)
            return {'started': True, 'action': action, 'clip_only': True}

        self.controller.stop()
        # Корень ИГРЫ, а не папка `tf`: по нему воркер читает items_game
        # (`viewmodel_anims.anim_info`) — оттуда и слот анимаций, и подмена
        # активностей, и пушка-носитель праздничной гирлянды. С `tf_dir`
        # items_game не находился, `anim_info` молча отдавал None, и слот
        # откатывался на нашу таблицу, а гирлянда висела в руке без пушки.
        # Панель приложения берёт тот же корень (`_tf2_root_for_fp`).
        self.viewmodel.load(key, mode, paths['misc_vpk'], paths['textures_vpk'],
                            paths['root'], action=action, lang=lang,
                            custom_smd=custom_smd,
                            keep_materials=bool(custom_smd))
        return {'started': True, 'action': action, 'rig': _viewmodel_rig()}

    def leave_first_person(self) -> Dict[str, Any]:
        """
        Выход из вида от первого лица.

        Убрать вьюмодель обязан тот же, кто её поставил: воркер сцены живёт до
        своей остановки, а подложка с текстурами рук — до своей очистки. Без
        этого руки оставались в кадре и после переключения вида: камера уже
        свободная, а оружие всё ещё держат. Обычную модель возвращает страница
        — у неё есть последний кадр превью, пересобирать его незачем.
        """
        self.viewmodel.stop()
        # Сцена насмешки уходит тем же выходом: она собрана так же и так же
        # держит подложку с текстурами персонажа.
        self.taunt.stop()
        with self._lock:
            self.preview.scene_extra_textures = {}
            self.preview.scene_item_materials = []
            # ...но у праздничного оружия подложка есть и у ОБЫЧНОЙ модели:
            # пушка-носитель под гирляндой. Поля под неё общие с видом от
            # первого лица, и без возврата текстура гирлянды ложилась на всю
            # модель разом — вьювер, увидев одну запись под служебным ключом,
            # кладёт её глобально.
            self.controller.apply_scene_extra()
        return self.view_state()

    def load_taunt(self, tf2_class: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Собирает сцену насмешки для выбранного реквизита.

        Реквизит опознаётся режимом (`taunt_<ключ>`): в нём и лежит ключ
        таблицы моделей. Класс задаёт человек — одну и ту же насмешку играют
        до девяти классов, и модель реквизита у каждого своя.
        """
        from src.data.simple_models import SIMPLE_MODEL_CATEGORIES

        mode = getattr(self, '_mode', '')
        simple = SIMPLE_MODEL_CATEGORIES.get('taunt')
        prefix = simple.mode_prefix if simple else ''
        if not simple or not mode.startswith(prefix):
            return {'error': 'Насмешку показывает только реквизит'}
        prop_key = mode[len(prefix):]
        item = simple.table.get(prop_key)
        if not item:
            return {'error': 'Насмешку показывает только реквизит'}

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        self.controller.stop()
        self.viewmodel.stop()
        self.taunt.load_taunt(prop_key, item['mdl_path'], paths['misc_vpk'],
                              paths['textures_vpk'], paths['root'],
                              tf2_class=tf2_class, lang=lang)
        return {'started': True, 'prop': prop_key, 'tf2_class': tf2_class}

    # ── Звуки ─────────────────────────────────────────────────────────────── #

    #: Сколько строк отдаём странице. Записей в игре десять с половиной тысяч,
    #: и рисовать их все — секунды на пустом месте: до сотой человек всё равно
    #: не долистает, он сузит фильтр.
    SOUND_PAGE = 400

    def sounds(self, family: str = '', tf2_class: str = '', query: str = '',
               section: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """Записи под фильтрами страницы: {rows, total}."""
        rows = self._sound_rows(lang)
        family = (family or '').strip().lower()
        tf2_class = (tf2_class or '').strip().lower()
        section = (section or '').strip().lower()
        # Разделители убираем с обеих сторон: скаттерган в игре записан
        # `Weapon_Scatter_Gun`, и поиск «scattergun» его не находил.
        words = [_plain(w) for w in (query or '').split() if _plain(w)]

        def fits(row: Dict[str, Any]) -> bool:
            if section and row['section'] != section:
                return False
            if family and row['family'] != family:
                return False
            # Класс знает только items_game: у стоковых записей его нет, и под
            # фильтром класса они не показываются — иначе фильтр не фильтрует.
            if tf2_class and tf2_class not in row['classes']:
                return False
            blob = _plain(f"{row['name']} {row['title']} "
                          f"{' '.join(row['waves'])} {' '.join(row['items'])}")
            return all(w in blob for w in words)

        # `own` подставляем ЗДЕСЬ, а не храним в строках: иначе выбор одного
        # звука обесценивал весь разобранный каталог, и следующий же список
        # стоил секунду на пересборку десяти тысяч записей.
        picks, by_wave = self._sound_picks, self._wave_picks
        # Копию строки делаем только для той страницы, что уедет наружу:
        # подходящих бывает десять тысяч, а показываем четыреста, и остальные
        # девять с половиной копировались зря на каждую букву в поиске.
        hits = [row for row in rows if fits(row)]
        found = [{**row, 'own': picks.get(row['name'], ''),
                  'own_waves': {w: by_wave[w] for w in row['waves']
                                if w in by_wave}}
                 for row in hits[:self.SOUND_PAGE]]
        # `section` — сколько записей в разделе ВСЕГО, до остальных фильтров.
        # По нему страница отличает «сузил до нуля» от «раздел не прочитался»:
        # пустой список сам по себе об этом молчит.
        in_section = sum(1 for row in rows
                         if not section or row['section'] == section)
        return {'rows': found, 'total': len(hits), 'section': in_section,
                # Сколько своих звуков выбрано ВСЕГО. Страница видит только
                # свою страницу списка, и считать по ней — значит терять
                # выбранное, как только сменишь фильтр.
                'picked': len(picks) + len(by_wave)}

    def sound_sections(self, lang: str = 'ru') -> List[Dict[str, str]]:
        """Разделы каталога: оружие, реплики, игрок, мир."""
        from src.data import sound_catalog

        names = sound_catalog.SECTION_NAMES
        have = {row['section'] for row in self._sound_rows(lang)}
        return [{'key': key, 'name': title}
                for key, title in names.items() if key in have]

    def sound_families(self, section: str = '',
                       lang: str = 'ru') -> List[Dict[str, str]]:
        """Семьи событий — только те, что есть в этом разделе.

        Список общий на все разделы, но у оружия не бывает боли, а у реплик —
        перезарядки: показывать пустые кнопки значит врать про фильтр.
        """
        from src.data import sound_catalog

        names = sound_catalog.FAMILY_NAMES
        section = (section or '').strip().lower()
        have = {row['family'] for row in self._sound_rows(lang)
                if not section or row['section'] == section}
        return [{'key': key, 'name': title}
                for key, title in names.items() if key in have]

    def _by_item(self, guess: Dict[str, tuple], item: str):
        """Предмет по его имени в игре. None — такого имени нет.

        Половина названий в игре с артиклем («The Buff Banner»), а называют их
        без него — пробуем оба вида.
        """
        for stem in (_plain(item), 'the' + _plain(item)):
            found = guess.get(stem)
            if found and found[2]:
                return found
        return None

    def _rows_any(self) -> List[Dict[str, Any]]:
        """Каталог на ТОМ языке, что уже разобран.

        Проверке формата и сборке язык безразличен — им нужны имена и файлы.
        Спросив каталог на своём языке, они выбрасывали чужой разбор, и
        страница платила за него ещё раз: две лишних секунды на каждый выбор.
        """
        return self._sound_rows(self._sound_lang or 'en')

    def _sound_rows(self, lang: str = 'ru') -> List[Dict[str, Any]]:
        """Каталог звуков как словари. Считается один раз на язык."""

        from src.app.api import classes as api_classes
        from src.data import sound_catalog
        from src.data.hats_parser import parse_localization
        from src.data.weapon_model_index import get_items_game_path

        if getattr(self, '_sound_lang', None) == lang:
            return self._sound_cache
        paths = self.tf2_paths()
        if 'error' in paths:
            return []
        # Сам звук лежит в своём VPK: скрипты в общем, файлы в `tf2_sound_*`.
        # Без него не нашлись бы «ничьи» файлы — те, чью связку с событием
        # Valve держит в зашифрованных `tf_weapon_*.ctx`.
        entries = sound_catalog.load(
            [*self._sound_vpks(paths['tf_dir']),
             paths['misc_vpk'], paths['textures_vpk']],
            get_items_game_path(paths['root']))
        # Предметы в items_game названы токенами (`TF_HamShank`) — человеку
        # нужно имя из игры.
        loc = parse_localization(paths['root'],
                                 'russian' if lang == 'ru' else 'english')
        titles = sound_catalog.FAMILY_NAMES
        # items_game называет предмет лишь у каждой шестой записи. Остальные
        # опознаём по имени субъекта: `Weapon_Ambassador` — это `TF_Ambassador`
        # в локализации и `c_ambassador` в каталоге оружия. Без этого «посол» и
        # «нож» в поиске не находились вовсе: имена записей латинские.
        guess = self._subject_index(loc, lang)
        classes = {c['key'].lower(): c['name']
                   for c in api_classes(lang) if c.get('key')}
        rows = []
        for entry in entries:
            items = [loc.get(token, loc.get(token.lower(), token))
                     for token in entry.items]
            stem = _plain(entry.subject.removeprefix('Weapon_')
                          .removeprefix('Weapon'))
            known, cls, weapon_key = guess.get(stem, ('', (), ''))
            if not weapon_key:
                # Рабочее имя Valve в звуке и имя предмета в игре сходятся не
                # всегда: миниган там `Gatling`, «Мачина» — `SniperRailgun`.
                named = sound_catalog.SUBJECT_ITEMS.get(entry.subject)
                if named:
                    known, cls, weapon_key = self._by_item(guess, named) or (
                        known, cls, weapon_key)
            rows.append({
                'name': entry.name, 'event': entry.event,
                'family': entry.family, 'section': entry.section,
                'family_name': titles.get(entry.family, entry.family),
                'waves': list(entry.waves),
                'items': items,
                'classes': list(entry.classes or cls),
                # У предмета берём его иконку из рюкзака, у остального —
                # картинку по субъекту: портрет класса, значок постройки.
                'icon': (weapon_key
                         or sound_catalog.icon_for(entry.subject,
                                                   entry.section)),
                # Подпись карточки: у связанной записи это сам предмет, иначе
                # опознанное по имени, иначе само имя субъекта.
                'title': _sound_title(entry, items, known, classes),
            })
        self._sound_lang, self._sound_cache = lang, rows
        return rows

    def _subject_index(self, loc: Dict[str, str],
                       lang: str) -> Dict[str, tuple]:
        """{сжатое имя субъекта: (название предмета, классы, иконка)}.

        Два источника: локализация знает больше всего названий
        (`Weapon_Scatter_Gun` → «Обрез»), каталог оружия — единственный, кто
        знает КЛАСС и картинку. Чего нет ни там, ни там, получает значок
        раздела (`icon_for`) — на строку без картинки это не похоже.

        Совпадение ищется по «сжатому» виду: Valve пишет то `Scatter_Gun`, то
        `Scattergun`, то `c_scattergun`.
        """
        from src.app.api import items as catalog_items

        out: Dict[str, tuple] = {}
        for token, value in loc.items():
            if not token.lower().startswith('tf_'):
                continue
            stem = _plain(token[3:].removeprefix('Weapon_').removeprefix('weapon_'))
            if stem and stem not in out:
                out[stem] = (value, (), '')

        for weapon in catalog_items('weapon', lang=lang):
            cls = (weapon.get('cls') or '').lower()
            bare = weapon['key'].removeprefix('c_').removeprefix('v_')
            # Ключ каталога часто с хвостом класса (`c_flaregun_pyro`), а в
            # звуке его нет — заводим и укороченный вид.
            for stem in {_plain(bare), _plain(bare.removesuffix('_' + cls))}:
                if not stem:
                    continue
                was_name = out.get(stem, ('', ()))[0]
                out[stem] = (was_name or weapon['name'], cls.split(),
                             weapon['key'])

        return out

    def set_sound(self, name: str, path: Optional[str],
                  wave: str = '') -> Dict[str, Any]:
        """Кладёт свой файл на запись целиком или на один её файл.

        `wave` — путь файла в игре. Пусто — замена на всю запись: у неё файлов
        бывает несколько, и обычно это варианты одного звука, которые меняют
        разом.
        """
        name = (name or '').strip()
        wave = (wave or '').strip()
        from src.services.sound_build_service import check_wav

        if not name:
            return {'error': 'Не выбран звук'}
        if wave:
            return self._set_wave(name, wave, path)
        if not path:
            self._sound_picks.pop(name, None)
        else:
            # Записи с таким именем может не быть вовсе: тогда сборка её
            # молча пропустит, а в подвале будет висеть «Своих звуков: 1».
            row = self._row(name)
            if row is None:
                return {'error': 'Такой записи в игре нет'}
            trouble = (self._wrong_format(row['waves'], path)
                       or check_wav(path))
            if trouble:
                return {'error': f'Файл не подойдёт: {trouble}'}
            self._sound_picks[name] = path
        return {'name': name, 'own': self._sound_picks.get(name, ''),
                'total': self._picked_total()}

    def _row(self, name: str) -> Optional[Dict[str, Any]]:
        """Запись каталога по имени. None — такой в игре нет."""
        return next((r for r in self._rows_any() if r['name'] == name), None)

    def _picked_total(self) -> int:
        return len(self._sound_picks) + len(self._wave_picks)

    def _set_wave(self, name: str, wave: str,
                  path: Optional[str]) -> Dict[str, Any]:
        """То же, но для ОДНОГО файла записи."""
        row = self._row(name)
        if row is None or wave not in row['waves']:
            return {'error': 'Такого файла у этой записи нет'}
        if not path:
            self._wave_picks.pop(wave, None)
            return {'name': name, 'wave': wave, 'own': '',
                    'total': self._picked_total()}
        from src.services.sound_build_service import check_wav

        trouble = self._wrong_format([wave], path) or check_wav(path)
        if trouble:
            return {'error': f'Файл не подойдёт: {trouble}'}
        self._wave_picks[wave] = path
        return {'name': name, 'wave': wave, 'own': path,
                'total': self._picked_total()}

    @staticmethod
    def _wrong_format(waves: List[str], path: str) -> str:
        """Пусто, если расширение файла подходит этим путям. Иначе — чем плохо.

        Игра зовёт файл по имени из записи, вместе с расширением: положив WAV
        под именем `.mp3`, мы получим в игре тишину. Реплики почти все в MP3,
        оружие почти всё в WAV — перепутать легко.

        У полусотни записей файлы РАЗНЫХ расширений вперемешку (у моторки
        разведчика и wav, и mp3). Годится файл, совпавший хоть с одним: свои
        достанутся им, чужие останутся игровыми (см. `build_sounds`).
        """
        want = {w.rsplit('.', 1)[-1].lower() for w in waves}
        got = (path or '').rsplit('.', 1)[-1].lower()
        if not want or got in want:
            return ''
        return ('игра ждёт здесь {}, а это {} — звук просто не зазвучит'
                .format('/'.join(sorted(k.upper() for k in want)),
                        got.upper() or '?'))

    def _sound_vpks(self, tf_dir: str) -> List[str]:
        """Все звуковые VPK игры плюс общий.

        Скрипты лежат в `tf2_misc`, а сами файлы — в отдельных архивах, и их
        несколько: `tf2_sound_misc` и по одному на язык озвучки
        (`tf2_sound_vo_english`). Имена не перечисляем — у человека может быть
        поставлена другая озвучка, и реплики из неё молчали бы.
        """
        import os

        out: List[str] = []
        # Рядом с `tf` лежит `hl2` — общее содержимое движка. Часть звуков
        # игрока и мира (`common/wpn_select.wav`, `items/smallmedkit1.wav`)
        # взята оттуда, и в архивах TF2 их нет вовсе.
        for folder in (tf_dir, os.path.join(os.path.dirname(tf_dir), 'hl2')):
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                continue
            out += [os.path.join(folder, name) for name in names
                    if name.endswith('_dir.vpk') and '_sound' in name]
        return out

    def sound_bytes(self, wave_path: str) -> Optional[bytes]:
        """Игровой звуковой файл как есть — странице его проигрывать."""

        from src.services import vtf_preview_service as vps

        paths = self.tf2_paths()
        if 'error' in paths:
            return None
        name = 'sound/' + (wave_path or '').replace(chr(92), '/').lstrip('/')
        # Скрипт пишет имя как попало (`vo/heavy_PainSevere01.mp3`), а в архиве
        # всё лежит строчными: у Valve так во всех звуковых VPK. Игра при
        # поиске регистр не различает, библиотека — различает.
        for pak in vps.open_vpks([*self._sound_vpks(paths['tf_dir']),
                                  paths['misc_vpk']]):
            for candidate in (name, name.lower()):
                try:
                    return pak[candidate].read()
                except KeyError:
                    continue
        return None

    def save_sound(self, name: str, wave: str = '') -> Dict[str, Any]:
        """Кладёт игровой звук записи в папку экспорта.

        Чтобы переделать звук, его сперва надо достать. Раньше единственным
        способом было прослушать его в приложении — а дальше человек оставался
        без файла. Сохраняем ИГРОВОЙ звук, а не выбранный: свой у него и так
        на диске.
        """
        row = self._row(name)
        if row is None:
            return {'error': 'Такой записи в игре нет'}

        # Один файл или все — у записи их бывает до восьмидесяти.
        wanted = ([wave] if wave in row['waves'] else
                  [] if wave else list(row['waves']))
        if not wanted:
            return {'error': 'Такого файла у этой записи нет'}

        export_folder, _ = self._export_settings()
        os.makedirs(export_folder, exist_ok=True)
        saved: List[str] = []
        for wave in wanted:
            data = self.sound_bytes(wave)
            if not data:
                continue
            # Только имя файла: путь внутри игры сюда переносить незачем, а
            # `..` в нём увёл бы запись мимо папки экспорта.
            target = os.path.join(export_folder, os.path.basename(wave))
            try:
                with open(target, 'wb') as f:
                    f.write(data)
            except OSError as exc:
                return {'error': f'Не удалось сохранить: {exc}'}
            saved.append(target)
        if not saved:
            return {'error': 'Файла этого звука в игре нет'}
        logger.info(f"[звук] сохранено из игры: {len(saved)} в {export_folder}")
        return {'path': saved[0], 'files': len(saved)}

    def build_sounds(self, filename: str = '') -> Dict[str, Any]:
        """Собирает VPK из выбранных звуков.

        Заменяем ВСЕ файлы записи: у полутора сотен записей их несколько, игра
        берёт случайный, и подменив один мы бы слышали свой звук через раз.
        """
        from src.services import sound_build_service as builder

        if not self._sound_picks and not self._wave_picks:
            return {'error': 'Не выбрано ни одного своего звука'}
        by_wave: Dict[str, str] = {}
        skipped = 0
        for row in self._rows_any():
            own = self._sound_picks.get(row['name'])
            if not own:
                continue
            kind = own.rsplit('.', 1)[-1].lower()
            # Только совпавшие по расширению: у части записей файлы разных
            # форматов вперемешку, и WAV, положенный под именем `.mp3`, дал бы
            # в игре тишину вместо звука.
            fit = [w for w in row['waves'] if w.lower().endswith('.' + kind)]
            skipped += len(row['waves']) - len(fit)
            by_wave.update({wave: own for wave in fit})
        # Замена ОТДЕЛЬНОГО файла ложится поверх: человек выбрал её позже и
        # прицельнее, чем «всю запись разом».
        by_wave.update(self._wave_picks)

        from src.shared.validators import validate_vpk_filename

        export_folder, _ = self._export_settings()
        name = (filename or 'sounds_mod').strip()
        if not name.lower().endswith('.vpk'):
            name += '.vpk'
        # Имя приходит из поля на странице и становится путём файла: тем же
        # правилом, что у сборки текстур, отсекаем слэши и точки-родители.
        good, trouble = validate_vpk_filename(name)
        if not good:
            return {'error': trouble}
        try:
            path = builder.build(by_wave, name, export_folder)
        except Exception as exc:                          # noqa: BLE001
            logger.error(f"[звук] сборка не удалась: {exc}", exc_info=True)
            return {'error': str(exc)}
        logger.info(f"[звук] собрано: {path}")
        return {'path': path, 'files': len(by_wave),
                'sounds': self._picked_total(), 'skipped': skipped}

    def load_skybox(self, sky_name: str) -> Dict[str, Any]:
        """Готовит грани стокового неба для показа кубмапой."""
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        self._mode = 'skybox'
        with self._lock:
            self.preview.mode.enter(_skybox_mode())
            self._forget_model()
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

    def cancel_build(self) -> Dict[str, Any]:
        """Останавливает идущую сборку.

        Сборка шапки на девять классов с текстурами 2048 идёт минуты, и
        передумать посреди неё человек должен иметь право. Воркер проверяет
        отмену между шагами сам — здесь только просьба остановиться; о
        завершении скажет его же `finished`.
        """
        build = self._build
        if build is None or not build.isRunning():
            return {'running': False}
        build.requestInterruption()
        # Ждущий вопрос о текстуре держит воркер на паузе: без ответа он не
        # дойдёт до проверки отмены и висел бы до таймаута в 300 секунд.
        if hasattr(build, 'set_extra_texture_result'):
            build.set_extra_texture_result(None)
        return {'running': True, 'cancelling': True}

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

    def _on_build_needs_texture(self, material: str, weapon_key: str,
                                remaining: int = 0) -> None:
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
        self._put('need_texture', material=material, weapon_key=weapon_key,
                  remaining=int(remaining))

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
        dest = data_dir() / 'export' / safe
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

    def _carrier_for_preview(self):
        """Пушка, на которой висит текущий предмет. Пусто — ни на чём.

        Праздничное оружие — навесная гирлянда: в кадре она не одна, и всё,
        что рисует предмет, обязано рисовать и носителя.
        """
        from src.services import carrier_model

        paths = self.tf2_paths()
        key = self.preview.weapon_key
        if 'error' in paths or not key:
            return carrier_model.NONE
        return carrier_model.find(key, paths['misc_vpk'], paths['root'])

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
        from src.services import carrier_model
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
            # Пушка-НОСИТЕЛЬ остаётся в кадре: у праздничного оружия своей
            # моделью заменяют гирлянду, а не пушку под ней. У обычного
            # оружия носителя нет, и список пуст — на них это не влияет.
            carrier = self._carrier_for_preview()
            ok, materials = SmdToObjService.convert(
                path, obj, extra_smd_paths=list(carrier.smds))
            if not ok or not os.path.exists(obj):
                return {'error': 'SMD не сконвертировался'}
            smd = path
            # Материалы носителя предмету не принадлежат: карточек по ним нет
            # и в сборку они не идут — иначе своя модель гирлянды тянула бы за
            # собой ещё и текстуру базового обреза.
            own = carrier_model.materials(carrier)
            materials = [m for m in (materials or []) if m not in own]

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
        # Подложку носителя `stop()` не отменяет: она про геометрию в кадре, а
        # та никуда не делась. Без возврата пушка под своей гирляндой серая.
        with self._lock:
            self.controller.apply_scene_extra()

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
        work_keeper.save(self.preview, self._work_key(),
                         self._style_files(), self._item_id())

    def _item_id(self) -> Dict[str, Any]:
        """
        Чем опознать предмет работы, кроме имени её папки.

        Имя папки — слаг: у шапки от `models/player/items/…/hat.mdl` в нём
        остаётся `models_player_items_…_hat.mdl`. По такому ключу не найти ни
        имени в каталоге, ни иконки, ни самой модели — работа по шапке
        показывалась строкой из подчёркиваний и не открывалась. Поэтому в
        работу кладём то, из чего она открывается.
        """
        return {'mode': getattr(self, '_mode', ''),
                'key': self.preview.weapon_key or '',
                # Мультиклассовая шапка: у каждого класса своя модель, и без
                # них вернётся только та, что была показана.
                'per_class': dict(self._hat_models),
                # Мод из VPK предметом каталога не опознаётся — только файлом.
                'mod': self._vpk_mod_path or ''}

    def _style_files(self) -> List[str]:
        """
        Файлы, на которые ссылаются снимки НЕактивных стилей шапки.

        Хранилище после записи убирает копии, которых нет в правках: иначе
        каждая склейка частей оставляла там свой файл навсегда. Но снимки
        стилей живут только в памяти сеанса, и без этой подсказки картинка
        соседнего стиля исчезла бы с диска — а в мод он собирается по ней.
        """
        out: List[str] = []
        for snap in self._hat_styles.values():
            edits = snap.get('edits') or {}
            out.append(snap.get('image_path'))
            out.append(edits.get('custom_smd_path'))
            out.append(edits.get('australium_user_tex'))
            for paths in (edits.get('textures') or {}).values():
                out.extend((paths or {}).values())
            for paths in (edits.get('skin_overrides') or {}).values():
                out.extend((paths or {}).values())
        return [p for p in out if p]

    def _restore_work(self, asked: bool = False) -> bool:
        """Возвращает сохранённые правки предмета."""
        from src.services import work_keeper
        with self._lock:
            restored = work_keeper.restore(self.preview, self._work_key(), asked)
            self._adopt_composites()
        return restored

    def _adopt_composites(self) -> None:
        """
        Признаёт своими склейки, вернувшиеся из сохранённой работы.

        `_composites` помнит только файлы ЭТОГО запуска, а после возврата к
        предмету путь ведёт в `work/<ключ>/files`. Пока приложение считало
        такую склейку ЧУЖОЙ текстурой, ломались сразу две вещи:

        * «Убрать всё» ничего не убирало — материал не возвращался к игровой
          текстуре, потому что снимать «пользовательскую» он не имел права;
        * следующая покраска брала прежнюю склейку ОСНОВОЙ, и цвета копились
          слоями: под новым цветом просвечивал старый.

        Признак — ИМЯ файла: склейку зовём мы сами, и по нему её видно даже
        тогда, когда данных частей уже нет. Такое состояние встречается: если
        «Убрать всё» однажды не сработало, части ушли, а склейка осталась
        висеть текстурой — и по данным частей её уже не опознать.
        """
        # Идём по самим восстановленным текстурам, а не по `material_names`:
        # список материалов на этот момент ещё пуст — он приезжает от воркера
        # ПОСЛЕ, а работа возвращается до его запуска.
        for by_team in self.preview.textures.textures.values():
            for path in (by_team or {}).values():
                if path and _is_composite_name(path):
                    self._composites.add(path)

    def forget_work(self) -> Dict[str, Any]:
        """Сбрасывает правки предмета — и в сеансе, и на диске."""
        from src.services import work_keeper
        with self._lock:
            work_keeper.forget(self.preview, self._work_key())
            # Стили шапки — тот же предмет: оставить их правки значило бы
            # собрать в мод то, что человек только что попросил забыть.
            self._hat_styles = {}
        return self.view_state()

    def keep_work(self) -> Dict[str, Any]:
        """Сохраняет работу над предметом в библиотеку — по просьбе человека."""
        from src.services import work_keeper
        with self._lock:
            ok = work_keeper.keep(self.preview, self._work_key(),
                                  self._style_files(), self._item_id())
        if not ok:
            return {'error': 'Сохранять нечего: правок нет'}
        return self.work_state()

    def restore_work(self) -> Dict[str, Any]:
        """Возвращает отложенную работу над открытым предметом."""
        # Замок берёт сам `_restore_work` — он же зовётся при открытии предмета.
        if not self._restore_work(asked=True):
            return {'error': 'Сохранённых правок у этого предмета нет'}
        return self.view_state()

    def forget_drafts(self, keys: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Удаляет черновики автосохранения. Сохранённые работы не трогает.

        ``keys`` — что именно удалять; None означает «все черновики», а пустой
        список — ничего: «снял все отметки» не должно означать «удали всё».
        Ключ, за которым лежит СОХРАНЁННАЯ работа, отбрасывается: страница
        присылает список, а удалить чужое по опечатке в нём нельзя.

        Черновик открытого сейчас предмета сбрасывается ещё и в сеансе —
        иначе автосохранение перепишет его на следующей же правке.
        """
        from src.services import work_store

        drafts = [d['key'] for d in work_store.list_drafts()]
        wanted = set(drafts) if keys is None else set(keys)
        current = self._work_key()
        removed, reset = 0, False
        for key in drafts:
            if key not in wanted:
                continue
            if key == current:
                self.forget_work()
                reset = True
                removed += 1
            elif work_store.forget(key):
                removed += 1
        logger.info(f"черновиков удалено: {removed}")
        # `reset` — знак странице перечитать вид: правки открытого предмета
        # ушли вместе с его черновиком.
        return {'removed': removed, 'reset': reset}

    def work_state(self) -> Dict[str, Any]:
        """Есть ли сейчас правки, лежит ли что-то на диске и как оно попало."""
        from src.services import work_store
        key = self._work_key()
        return {'has_edits': self.preview.has_user_edits(),
                'autosave': self._autosave_on(),
                # Черновик автосохранения тоже «есть на диске»: его можно и
                # вернуть, и забыть — просто в библиотеке его не показывают.
                'has_saved': bool(key) and work_store.holds_edits(key),
                'kept': work_store.is_kept(key)}

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

        model = mesh_parts_service.load(self._obj_path,
                                        self.preview.part_cuts)
        if not model:
            return {'error': 'Модель ещё не загружена'}

        names = list(model.materials)
        if len(names) == 1:
            # У одноматериальной модели карточка ВСЕГДА служебная, как её ни
            # назови: вьювер знает материал по имени из SMD и присылает его,
            # а работа хранится под ключом главной текстуры. Разойдясь здесь,
            # покраска ложилась в чужую карточку и на экране не появлялась.
            return model, names[0], self.preview.textures.storage_main_key()
        else:
            wanted = (material or self.preview.textures.stable_main() or '').lower()
            obj_mat = next((n for n in names if n.lower() == wanted), '')
            if not obj_mat:
                return {'error': 'У этого материала нет геометрии'}

        card = material or self.preview.textures.storage_main_key()
        return model, obj_mat, card

    def _shape_key(self, obj_mat: str) -> str:
        """
        Отпечаток РАЗБИЕНИЯ: модель, её время и сделанные разрезы.

        По нему решается, отдавать ли карты треугольников. Они занимают 96%
        ответа (у обреза 36 КБ из 38), а меняются только от резки — при том что
        сам ответ запрашивается после КАЖДОГО мазка кистью.
        """
        # Разрез — список НАБОРОВ островов, а не плоский список чисел: набор
        # собирает верх и низ пальца в одну часть. Отпечаток обязан различать
        # {0: [[1], [2]]} и {0: [[1, 2]]} — это разные разбиения.
        cuts = sorted(
            (int(g), tuple(sorted(tuple(sorted(int(i) for i in bundle))
                                  for bundle in v)))
            for g, v in (self.preview.part_cuts.get(obj_mat) or {}).items())
        stamp = 0.0
        try:
            stamp = os.path.getmtime(self._obj_path) if self._obj_path else 0.0
        except OSError:
            pass
        return f"{self._obj_path}|{stamp}|{obj_mat}|{cuts}"

    def parts(self, material: str = '', known_shape: str = '') -> Dict[str, Any]:
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

        shape = self._shape_key(obj_mat)
        out: Dict[str, Any] = {
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
                # Дробление настраивается на КУСОК, а не на часть: номер части
                # меняется вместе с разбиением, номер куска — нет.
                'chunk': part.chunk,
                'sub': part.sub,
                # Группа — куски, делящие развёртку: они режутся вместе.
                # Остров -1 означает «неразрезанный остаток куска».
                'group': part.group,
                # Острова, из которых собран отрезок; пусто — остаток куска.
                'islands': list(part.islands),
                # Место части на развёртке: по нему страница подсвечивает
                # область прямо на текстуре — иначе связь «кусок ↔ участок
                # картинки» видна только в голове у того, кто делал модель.
                'bbox': [round(v, 5) for v in part.uv_bbox],
            } for part in parts],
            'group_islands': model.group_islands.get(obj_mat) or {},
            'tint': self.preview.part_tint,
            'exact': bool(self.preview.part_exact),
            'edge': self.preview.part_edge,
            'edge_color': self.preview.part_edge_color,
            'shape': shape,
        }
        if known_shape != shape:
            # Карты «треугольник → часть» и «треугольник → остров»: по ним
            # вьювер выбирает и обводит. Отдаём, только когда разбиение
            # изменилось — на покраске они те же, а весят почти весь ответ.
            out['tri_part'] = tri_part
            out['tri_island'] = list(model.tri_island.get(obj_mat) or [])
        return out

    def _parts_snapshot(self) -> tuple:
        """Всё, что делает покраску такой, какая она есть.

        Сила тонировки и окантовка входят наравне с картинками и цветами:
        они тоже правки человека, и без них отмена ползунка была ХОЛОСТОЙ —
        снимок совпадал с текущим состоянием, кнопка не меняла ничего, а
        добравшись до начала, оставляла силу и окантовку от последнего шага.
        """
        return (
            {mat: dict(items) for mat, items in self.preview.part_textures.items()},
            {mat: dict(items) for mat, items in self.preview.part_colors.items()},
            self.preview.part_tint,
            self.preview.part_edge,
            self.preview.part_edge_color,
            self.preview.part_exact,
        )

    def _restore_parts(self, snap: tuple) -> None:
        """Ставит снимок на место."""
        (self.preview.part_textures, self.preview.part_colors,
         self.preview.part_tint, self.preview.part_edge,
         self.preview.part_edge_color, self.preview.part_exact) = snap

    def _remember_parts(self, card: str) -> None:
        """Снимок покраски ДО изменения — для отмены."""
        self._parts_history.append(self._parts_snapshot())
        del self._parts_history[:-20]      # глубже двадцати шагов не помнит никто
        # Новая правка отменяет «вперёд»: та ветка больше никогда не наступит.
        self._parts_future.clear()

    def undo_parts(self, material: str = '') -> Dict[str, Any]:
        """Откатывает последнее изменение покраски частей."""
        return self._step_parts(material, self._parts_history,
                                self._parts_future, 'Отменять нечего')

    def redo_parts(self, material: str = '') -> Dict[str, Any]:
        """Возвращает вперёд то, что отменили."""
        return self._step_parts(material, self._parts_future,
                                self._parts_history, 'Возвращать нечего')

    def _step_parts(self, material: str, take: List[Any], keep: List[Any],
                    empty: str) -> Dict[str, Any]:
        """Шаг по истории: снимок оттуда, текущее состояние — туда.

        Отмена и возврат — одно и то же движение в разные стороны, поэтому и
        код один: разъехавшись, они дали бы состояние, из которого не выйти
        ни назад, ни вперёд.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            if not take:
                return {'error': empty}
            keep.append(self._parts_snapshot())
            self._restore_parts(take.pop())
            self._recompose(model, obj_mat, card)
        self._autosave()
        return self.view_state()

    def set_part_texture(self, material: str = '', part: int = 0,
                         path: Optional[str] = None,
                         options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Кладёт картинку на одну часть (path=None — убирает с неё).

        ``options`` — как её посадить: вписать/заполнить/растянуть, поворот,
        масштаб, сдвиг. Пусто — вписать целиком с сохранением пропорций.

        Без пути, но с настройкой, — правка УЖЕ положенной картинки: так окно
        посадки двигает её, не заставляя выбирать файл заново.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        if path and not os.path.isfile(path):
            return {'error': 'Файл не найден'}

        with self._lock:
            self._remember_parts(card)
            chosen = self.preview.part_textures.setdefault(card, {})
            if not path and options is not None:
                had = chosen.get(int(part))
                if not had:
                    return {'error': 'На этой части нет картинки'}
                spec = _image_spec(had)
                # Якорь переживает правку посадки: он говорит, В ЧЁМ картинка
                # живёт (в габарите части, на которую её клали), а окно двигает
                # её ВНУТРИ этого габарита. Потеряв якорь здесь, картинка
                # прыгнула бы после разреза при первой же правке.
                spec.update({k: v for k, v in _image_spec(
                    {**options, 'path': spec['path']}).items()
                    if k not in ('path', 'anchor')})
                chosen[int(part)] = {**spec, 'offset': list(spec['offset'])}
            elif path:
                spec = _image_spec({**(options or {}), 'path': path})
                chosen[int(part)] = {**spec, 'offset': list(spec['offset'])}
            else:
                chosen.pop(int(part), None)
            self._recompose(model, obj_mat, card)
        self._autosave()
        return self.view_state()

    def set_part_colors(self, material: str = '',
                        colors: Optional[Dict[str, Any]] = None,
                        strength: Optional[float] = None,
                        exact: Optional[bool] = None) -> Dict[str, Any]:
        """
        Красит части: {номер части: цвет}, значение None — снять.

        Цвет — либо «#rrggbb», либо градиент
        ``{'color': ..., 'color2': ..., 'angle': градусы}``: одним цветом
        деталь выглядит плоской, а в настоящих скинах переход есть почти всегда.
        Угол: 0 — сверху вниз, дальше по часовой стрелке.

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
            if exact is not None:
                self.preview.part_exact = bool(exact)
            painted = self.preview.part_colors.setdefault(card, {})
            for part, color in (colors or {}).items():
                if color:
                    painted[int(part)] = (dict(color) if isinstance(color, dict)
                                          else str(color))
                else:
                    painted.pop(int(part), None)
            self._recompose(model, obj_mat, card)
        self._autosave()
        return self.view_state()

    def set_part_detail(self, material: str = '',
                        detail: float = 0.0) -> Dict[str, Any]:
        """
        Раздробить ВСЕ куски одинаково: доля 0..1 от числа швов каждого куска.

        Быстрый способ задать общий уровень; поштучно кусок правится
        ``set_chunk_detail``.
        """
        def everything(model, obj_mat) -> Dict[int, List[List[int]]]:
            share = max(0.0, min(1.0, float(detail)))
            out: Dict[int, List[List[int]]] = {}
            for group, count in (model.group_islands.get(obj_mat) or {}).items():
                if count < 2:
                    continue
                # Обычное округление, а не round(): у группы с одним швом
                # round(0.5) даёт 0 (банковское правило), и половина ползунка
                # не резала её вовсе — при том что резать там ровно один шов.
                take = int(share * (count - 1) + 0.5)
                # Острова пронумерованы от крупного, поэтому «первые N» — это
                # самые заметные куски, а не строчка швов на рукаве.
                if take:
                    out[group] = [[i] for i in range(take)]
            return out

        return self._reshape(material, everything)

    def part_mask(self, material: str = '', part: int = 0) -> Dict[str, Any]:
        """
        Картинка-подсветка одной части: её форма на развёртке.

        Прямоугольник (bbox) врал: у детали, лежащей на развёртке наискось, он
        накрывает половину текстуры и соседние куски заодно. Показывать надо ту
        же маску, по которой красит склейка.

        Файл кэшируется по отпечатку разбиения: наводят на части десятки раз, а
        форма меняется только от резки.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        polys = model.polygons(obj_mat, int(part))
        if not polys:
            return {'error': 'У этой части нет развёртки'}

        from src.services import texture_compose_service
        # Подсветку рисуем в пропорциях САМОЙ текстуры: у тела шпиона она
        # 1024×512, и квадратная маска ложилась на кадр растянутой — контуры
        # уезжали с деталей. Размер входит и в имя файла: сменят текстуру на
        # другую по форме — понадобится новая маска, а старая лежит в кэше и у
        # браузера.
        shape = self._texture_shape(card)
        stamp = hashlib.md5(
            self._shape_key(obj_mat).encode('utf-8')).hexdigest()[:10]
        tail = f"{shape[0]}x{shape[1]}" if shape else 'square'
        out = os.path.join(self._work_dir(), 'masks',
                           f"{stamp}_{int(part)}_{tail}.png")
        if not os.path.isfile(out):
            texture_compose_service.outline_png(polys, out, shape=shape)
        return {'part': int(part), 'mask': out}

    def _texture_shape(self, card: str):
        """Размер картинки, показанной на этом материале. None — не прочитать."""
        t = self.preview.textures
        path = t.uploaded_for_mat(card) or t.game_base(card)
        if not path or not os.path.isfile(path):
            return None
        try:
            from PIL import Image
            with Image.open(path) as im:
                return im.size
        except (OSError, ValueError):
            return None

    def part_shape(self, material: str = '', part: int = 0) -> Dict[str, Any]:
        """
        Развёртка одной части: по ней окно посадки рисует, куда ляжет картинка.

        Треугольники, а не прямоугольник: склейка маскирует по ним, и рамка
        врала бы — положенное в угол исчезало бы при сборке.

        Отдельным запросом, а не в общем списке частей: у крупного куска это
        тысячи треугольников, и возить их со всем списком незачем.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        one = next((p for p in model.parts_of(obj_mat) if p.index == int(part)),
                   None)
        if one is None:
            return {'error': 'Такой части нет'}

        image = (self.preview.part_textures.get(card) or {}).get(int(part))
        spec = _image_spec(image) if image else None
        frames: List[str] = []
        delays: List[int] = []
        if spec:
            spec['offset'] = list(spec['offset'])
            # Кадры анимации раскладываем сами: браузер их из гифки не достаёт,
            # а предпросмотр обязан показывать то же, что уйдёт в мод.
            from src.services import texture_compose_service
            frames, delays = texture_compose_service.export_frames(
                spec['path'], os.path.join(self._work_dir(), 'frames'),
                f"part{int(part)}")
        from src.services import texture_compose_service as _compose
        polys = model.polygons(obj_mat, one.index)
        return {
            'frames': frames,
            'delays': delays,
            # Куда приближать окно: габарит без редких дальних островков.
            # Обычный габарит у половины частей — почти вся текстура, и окно
            # тогда не приближает, а только центрирует.
            'dense': [round(v, 6) for v in _compose.dense_bbox(polys)],
            'part': one.index,
            # Габарит, в который вписана картинка. У наклейки, пережившей
            # разрез, это габарит ПРЕЖНЕЙ части (её якорь): окно посадки обязано
            # показывать ровно то, что соберёт склейка.
            'bbox': [round(v, 6) for v in
                     ((spec and spec.get('anchor')) or one.uv_bbox)],
            'polygons': [[[round(u, 6), round(v, 6)] for u, v in tri]
                         for tri in model.polygons(obj_mat, one.index)],
            'image': spec,
            # Основа — то, поверх чего человек и увидит свою картинку.
            'base': self.preview.textures.game_base(card) or '',
        }

    def toggle_part_island(self, material: str = '', group: int = 0,
                           island: int = 0) -> Dict[str, Any]:
        """
        Отрезает названный остров развёртки или приращивает его обратно.

        Именно названный: раньше резал счётчик «ещё один шов», и добраться до
        мизинца можно было только разрезав перед ним всё остальное.

        Режется ГРУППА — все куски, делящие эту развёртку. У рук шпиона левая и
        правая делят её целиком: в игре у них общие пиксели, и разрезать одну
        без другой нельзя даже теоретически.

        Остров, вынутый из набора, возвращается в остаток куска, а не остаётся
        отдельной частью: «прирастить обратно» должно значить ровно это.
        """
        def one(model, obj_mat) -> Dict[int, List[List[int]]]:
            out = self._cut_plan(obj_mat)
            made = [list(b) for b in out.get(int(group), ())]
            was = [b for b in made if int(island) in b]
            if was:
                for bundle in was:
                    bundle.remove(int(island))
            else:
                made.append([int(island)])
            made = [b for b in made if b]
            if made:
                out[int(group)] = made
            else:
                out.pop(int(group), None)
            return out

        return self._reshape(material, one)

    def merge_part_islands(self, material: str = '', group: int = 0,
                           islands: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Сводит отрезки в один: их острова становятся одной частью.

        Развёртка режет вещи не так, как их видит человек: палец у неё нередко
        разложен на верх и низ. Собрать его обратно и красить как одно целое —
        то, ради чего это и нужно.

        Берутся ЦЕЛЫЕ наборы, а не только названные острова: половину уже
        собранного пальца отрывать при слиянии не за чем.
        """
        wanted = {int(i) for i in (islands or ())}

        def join(model, obj_mat) -> Dict[int, List[List[int]]]:
            out = self._cut_plan(obj_mat)
            made = [list(b) for b in out.get(int(group), ())]
            touched = [b for b in made if wanted.intersection(b)]
            if len(touched) < 2:
                return out                      # сливать нечего — не трогаем
            rest = [b for b in made if b not in touched]
            rest.append(sorted({i for b in touched for i in b}))
            out[int(group)] = rest
            return out

        return self._reshape(material, join)

    def _cut_plan(self, obj_mat: str) -> Dict[int, List[List[int]]]:
        """Копия разрезов ЭТОГО материала, которую можно править отдельно.

        Материал обязателен: разрезы хранятся по нему, и без ключа сюда
        приходил весь словарь — с именами материалов вместо номеров групп.
        """
        return {int(g): [list(b) for b in v]
                for g, v in (self.preview.part_cuts.get(obj_mat) or {}).items()}

    def _reshape(self, material: str, plan) -> Dict[str, Any]:
        """
        Меняет дробление и переносит на новые части уже покрашенное.

        Перенос идёт ПО ТРЕУГОЛЬНИКАМ. Номер части от дробления зависит:
        оставить покраску привязанной к номеру значило бы молча перекрасить не
        то. Мелкое разбиение — измельчение крупного, поэтому каждая новая часть
        наследует цвет той старой, из которой вышла; при укрупнении наоборот —
        берётся цвет, занимавший бо́льшую часть.

        Историю отмены чистим: её шаги записаны в НОМЕРАХ прежнего разбиения, и
        откат после смены дробления красил бы наугад.
        """
        from collections import Counter

        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found
        was = model.parts_of(obj_mat)
        owner = {tri: part.index for part in was for tri in part.triangles}
        #: Габарит развёртки прежних частей: по нему наклейка остаётся на месте,
        #: когда часть под ней разрезали надвое.
        boxes = {part.index: tuple(part.uv_bbox) for part in was}
        wanted = plan(model, obj_mat)

        with self._lock:
            from src.services.mesh_parts_service import bundles_of
            # Разрезы — СВОИ у каждого материала: номера групп считаются внутри
            # материала, и общий словарь резал заодно соседний (у головы шпиона
            # и у его тела есть своя «группа 1»).
            self.preview.part_cuts[obj_mat] = {
                g: [list(b) for b in made]
                for g, made in bundles_of(wanted).items()}
            found = self._parts_model(material)
            if isinstance(found, dict):
                return found
            model, obj_mat, card = found

            images = self.preview.part_textures.get(card) or {}
            colors = self.preview.part_colors.get(card) or {}
            if images or colors:
                moved_images: Dict[int, Any] = {}
                moved_colors: Dict[int, Any] = {}
                for part in model.parts_of(obj_mat):
                    votes = Counter(owner[t] for t in part.triangles if t in owner)
                    if not votes:
                        continue
                    before = votes.most_common(1)[0][0]
                    # Слои переносим ПО ОТДЕЛЬНОСТИ. Раньше здесь стоял
                    # `elif` — наследие правила «у части либо картинка, либо
                    # цвет». Правило сняли, а перенос остался: у части с
                    # картинкой цвет при первом же разрезе исчезал.
                    if before in images:
                        spec = _image_spec(images[before])
                        # Якорь ставим ОДИН раз — при первом разрезе. Дальше он
                        # уже описывает исходное место картинки, и переписывать
                        # его габаритом половинки значило бы всё-таки её сдвинуть.
                        spec['anchor'] = spec['anchor'] or boxes.get(before)
                        moved_images[part.index] = {
                            **spec, 'offset': list(spec['offset']),
                            'anchor': list(spec['anchor']) if spec['anchor'] else None}
                    if before in colors:
                        moved_colors[part.index] = colors[before]
                self.preview.part_textures[card] = moved_images
                self.preview.part_colors[card] = moved_colors
                self._recompose(model, obj_mat, card)
            self._parts_history.clear()
            self._parts_future.clear()
        self._autosave()
        return self.view_state()

    def set_part_edge(self, material: str = '', width: float = 0.0,
                      color: str = '') -> Dict[str, Any]:
        """
        Окантовка частей: полоса своего цвета по краю каждой покрашенной части.

        Общая на предмет, как и сила тонировки: обводят обычно всю работу
        разом. Ширина — в долях стороны текстуры, чтобы одна и та же работа
        одинаково выглядела и в 512, и в 2048.

        Полоса ложится ВНУТРЬ части: наружу она вылезла бы на соседнюю деталь и
        покрасила чужое.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            self.preview.part_edge = max(0.0, min(0.1, float(width)))
            if color:
                self.preview.part_edge_color = str(color)
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
        # Сперва ЦВЕТ, потом картинки: цвет — это тонировка игровой текстуры
        # (детали под ней остаются), а картинка ложится на деталь сверху. У
        # одной части может быть и то, и другое: покрасил корпус и наклеил на
        # него свой знак — раньше второе действие молча стирало первое.
        # Настройки кисти на сейчас — только для записей, которые своих не
        # помнят (старые работы). У свежего мазка они уже внутри.
        brush = {'strength': self.preview.part_tint,
                 'exact': self.preview.part_exact,
                 'edge': self.preview.part_edge,
                 'edge_color': self.preview.part_edge_color}
        layers = [Layer(polygons=model.polygons(obj_mat, part),
                        **_paint_spec(color, brush))
                  for part, color in sorted(colors.items())]
        for part, image in sorted(images.items()):
            spec = _image_spec(image, brush)
            layers.append(Layer(polygons=model.polygons(obj_mat, part),
                                image=spec['path'], fit=spec['fit'],
                                image_angle=spec['angle'],
                                image_scale=spec['scale'],
                                image_scale_y=spec['scale_y'],
                                image_offset=spec['offset'],
                                anchor=spec['anchor'],
                                edge=spec['edge'],
                                edge_color=spec['edge_color']))
        # Имя со счётчиком: путь — это ещё и адрес картинки во вьювере, и по
        # прежнему имени браузер показал бы предыдущую склейку из кэша.
        self._compose_seq = getattr(self, '_compose_seq', 0) + 1
        out = os.path.join(self._work_dir(),
                           f"parts_{self._compose_seq}.png")
        result = texture_compose_service.compose(base, layers, out)
        if not result:
            return
        self._composites.add(result)
        self._compose_files.append(result)
        self._drop_old_composites()
        t.set_texture(card, result)

    #: Сколько склеек держим на диске. Одной мало: путь — это ещё и адрес
    #: картинки во вьювере и в альбоме, и удалить только что показанную нельзя,
    #: пока браузер её грузит. Больше — лишние мегабайты: у текстуры 2048x2048
    #: каждая склейка весит по несколько мегабайт.
    _KEEP_COMPOSITES = 4

    def _drop_old_composites(self) -> None:
        """
        Убирает с диска устаревшие склейки.

        Каждый мазок кистью писал новый файл и не удалял ни одного: за день
        работы во временной папке накопилось 1090 файлов на 248 МБ. К моменту
        следующей склейки предыдущая уже скопирована автосохранением в work/,
        так что работа человека от удаления не страдает.

        Назначенные материалам НЕ ТРОГАЕМ, сколько бы им ни было лет. Очередь
        была общей на всю модель, а склейка у каждого материала своя: покрасив
        голову шпиона, а потом тело, человек тремя мазками выталкивал из
        очереди ещё живую склейку головы. Файл исчезал, путь к нему оставался
        назначенным — и материал молча возвращался к игровой текстуре. Со
        стороны это выглядело как «цвета сами сбрасываются».
        """
        live = self._live_texture_paths()
        recent = set(self._compose_files[-self._KEEP_COMPOSITES:])
        keep: List[str] = []
        for path in self._compose_files:
            if path in live or path in recent:
                keep.append(path)
                continue
            try:
                os.remove(path)
            except OSError:
                pass          # уже нет или занят — не повод падать на покраске
        self._compose_files = keep

    def _live_texture_paths(self) -> set:
        """Пути, назначенные сейчас хоть какому-то материалу любой команды."""
        live: set = set()
        for slots in (self.preview.textures.textures or {}).values():
            live.update(path for path in (slots or {}).values() if path)
        return live

    def _work_dir(self) -> str:
        """Своя папка сеанса для склеек. Живёт до перезапуска, как и превью.

        Убирается на выходе: склейки весят по 2-3 МБ, держим четыре, и каждый
        запуск оставлял в %TEMP% свою папку `tf2sg_parts_*` навсегда. К этому
        моменту нужное уже скопировано в work/ автосохранением.
        """
        import atexit
        import shutil
        import tempfile

        folder = getattr(self, '_tmp_dir', '')
        if not folder or not os.path.isdir(folder):
            folder = tempfile.mkdtemp(prefix='tf2sg_parts_')
            self._tmp_dir = folder
            atexit.register(shutil.rmtree, folder, ignore_errors=True)
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
            # Меши, которые носят ВЫБРАННУЮ карточку (маски маскировки: девять
            # текстур на одну голову). Пусто — обычное «карточка = материал».
            'card_mesh': self.preview.card_mesh(),
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
            # Своя геометрия в кадре — можно предложить вернуть игровую.
            'has_custom': bool(self.preview.custom_smd_path),
            'framerate': self.preview.team_framerate,
            'skins': self.preview.textures.skin_info,
            'active_skin': self.preview.textures.active_skin,
            # Вариантный стиль переопределяет базу выборочно: странице нужно
            # знать, что ещё можно в него добавить.
            'style': self.preview.active_style,
            'style_candidates': self.preview.style_candidates(),
            # Есть ли что делить на части. Кнопка иначе висела бы доступной у
            # скайбокса, спрея и просто до того, как модель приехала, — и
            # обещала бы действие, которого нет.
            'can_split': bool(self._obj_path and os.path.isfile(self._obj_path)),
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
        # Crowbar — вторая обязательная половина: без него модель не
        # разобрать, а узнать об этом сейчас можно только по ошибке сборки.
        crowbar_ok, _ = TF2Paths.check_crowbar()
        # Насмешек с реквизитом в игре вчетверо больше, чем в выверенной
        # руками таблице, и список их лежит в items_game. Здесь первое место,
        # где путь к игре уже известен; повторные вызовы — сразу выход.
        from src.data import taunt_catalog
        taunt_catalog.merge(root)
        return {'root': root, 'tf_dir': tf_dir,
                'misc_vpk': misc_vpk, 'textures_vpk': textures_vpk or '',
                'crowbar': bool(crowbar_ok)}


#: Единственный сеанс процесса. Создаётся лениво: импорт модуля не должен
#: тянуть за собой воркеры и конфиг.
_session: Optional[AppSession] = None


def session() -> AppSession:
    global _session
    if _session is None:
        _session = AppSession()
    return _session
