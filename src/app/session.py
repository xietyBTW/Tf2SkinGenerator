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

from src.app.parts_editor import PartsEditor
from src.app.particles_editor import ParticlesEditor
from src.app.preview_controller import (
    Preview3DController, SkinDetectController, SkyboxController,
    ViewmodelController, VpkModController,
)
from src.domain.preview.session import PreviewSession
from src.shared.logging_config import get_logger
from src.shared.text_search import plain as _plain

logger = get_logger(__name__)

#: «Ответа ещё нет» для запомненного выбора текстуры. Отдельный сторож, потому
#: что сам ответ бывает None — это «взять главную текстуру».
_NO_CHOICE = object()


#: Подписи вариантов бодигрупп по слову в имени SMD.
_VARIANT_WORDS = (
    ('exploded', 'после взрыва'),
    ('broken', 'разбитая'),
    ('blank', 'без части'),
)


def _variant_label(smd_path: Optional[str], weapon_key: str) -> str:
    """Подпись варианта бодигруппы: знакомое слово из имени SMD, иначе то,
    что остаётся от имени без ключа оружия; нулевой обычно — «основной»."""
    if not smd_path:
        return 'без части'
    name = os.path.splitext(os.path.basename(smd_path))[0].lower()
    for word, label in _VARIANT_WORDS:
        if word in name:
            return label
    stem = os.path.splitext(os.path.basename(weapon_key or ''))[0].lower()
    for junk in (stem, 'c_', '_reference', 'reference', '_bodygroup', 'bodygroup'):
        if junk:
            name = name.replace(junk, '')
    name = name.strip('_ ')
    return name or 'основной'


def _part_kind(smd_name: str) -> str:
    """Что за сменная часть — по имени SMD. Пусто, если по имени не понять."""
    name = (smd_name or '').lower()
    if 'exploded' in name:
        return 'exploded'
    if 'broken' in name:
        return 'broken'
    return ''


def _existing_path(path: Optional[str]) -> Optional[str]:
    """Путь, если файл на месте, иначе None."""
    return path if path and os.path.isfile(path) else None


def _in_work_dir(path: str) -> bool:
    """Лежит ли путь в папке сохранённых работ (Windows регистр не различает)."""
    from src.services.work_store import WORK_DIR
    try:
        root = os.path.normcase(str(WORK_DIR.resolve())) + os.sep
        return os.path.normcase(os.path.abspath(path)).startswith(root)
    except (OSError, ValueError):
        return False


def _viewmodel_rig() -> dict:
    """Камера вида от первого лица. Импорт отложен — модуль тянет сцену."""
    from src.services.viewmodel_scene import VIEWMODEL_RIG
    return dict(VIEWMODEL_RIG)


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

    Порядок источников — от точного к догадке. Предмет называет items_game,
    оружие опознаётся по имени субъекта, у реплики класс стоит прямо в имени
    записи (`Scout.PainSharp01`) или выведен из пути к файлу. Если молчат все
    — само имя субъекта.
    """
    from src.data.sound_catalog import WHO_NAMES

    # Класс-субъект — раньше локализации: там он «ПОДРЫВНИК» капслоком с
    # экрана выбора класса, а в каталоге классы зовутся как в данных.
    if entry.subject.lower() in classes:
        return classes[entry.subject.lower()]
    if items:
        return items[0]
    if known:
        return known
    who = entry.who[0] if entry.who else ''
    if who in classes:
        return classes[who]
    if '.' in entry.name:
        return entry.subject.replace('_', ' ')
    return WHO_NAMES.get(who) or entry.name.replace('_', ' ')



#: Строка без разделителей и регистра — для поиска. В именах записей звука
#: Valve непоследователен: `Weapon_Scatter_Gun` рядом с `Weapon_Shotgun`, и
#: буквальное совпадение подстроки половину названий не находит. «ё» и «е»
#: тоже одно и то же: «ракетомет» обязан находить «Ракетомёт».
def _score(row: Dict[str, Any], words: List[str]) -> float:
    """Насколько строка отвечает запросу. Меньше нуля — не отвечает вовсе.

    Каждое слово обязано найтись; вес — по тому, ГДЕ нашлось: целый термин
    (имя предмета, класс, слот, группа) дороже его начала, начало — дороже
    вхождения в середину, а имя записи и путь файла — самое дешёвое. Так
    «bat» ставит биту выше «BatSaber», а тот — выше «combat».
    """
    total = 0.0
    terms = row['terms']
    for w in words:
        if w in terms:
            total += 8
        elif any(t.startswith(w) for t in terms):
            total += 4
        elif any(w in t for t in terms):
            total += 2
        elif w in row['name_plain']:
            total += 1
        elif w in row['blob']:
            total += 0.5
        else:
            return -1
    return total


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
        #: Свои звуки: {путь файла в игре: файл человека}. Только по файлам,
        #: не по записям: игра подменяет файл, а один файл бывает у девяти
        #: записей (`bat_miss.wav` — промах у девяти оружий), и хранить
        #: выбор по записи значило бы врать остальным восьми, что они
        #: нетронуты. Страница звуков живёт отдельно от предмета, и в
        #: состоянии превью ей места нет.
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
        #: История правок предмета: снимки `user_edits()` и позиция в них.
        #: Одна на всё — текстуры, части, свою модель, карты: красят и
        #: подставляют на ощупь, и «попробовал, не понравилось» должно
        #: откатываться, иначе человек боится трогать.
        self._edit_history: List[Dict[str, Any]] = []
        self._edit_pos = -1
        #: {путь в папке работы: своя копия} — см. `_shield_work_files`.
        self._undo_copies: Dict[str, str] = {}
        #: Переключатель состояния модели в превью: {имя бодигруппы: вариант}.
        #: Пусто — как в игре по умолчанию (целая бутылка). Только показ: в
        #: мод уходят все варианты, игра переключает их сама.
        self._bodygroups: Dict[str, int] = {}
        #: Гирлянда поверх оружия (праздничная версия / фестивайзер) — только
        #: показ, в сборку не идёт. Вид и предмет, для которого её включили;
        #: готовые гирлянды предмета, чтобы повторное включение было мгновенным;
        #: воркер сборки и кэш видов по ключу предмета.
        self._decor_kind = ''
        self._decor_for = ''
        self._decors: Dict[str, Any] = {}
        self._decor_worker = None
        self._decor_options: tuple = ('', [])
        #: Смена вида и событие готовой гирлянды — под одним замком: воркер
        #: зовёт `_on_decor` из своего потока, и без замка он мог пройти
        #: проверку за миг до выключения и прислать гирлянду уже после него.
        self._decor_lock = threading.Lock()
        #: Модели показанной шапки: {класс: mdl}. Пусто у обычной шапки — у неё
        #: одна модель на всех. Нужны сборке: мультиклассовая шапка собирается
        #: сразу под все выбранные классы.
        self._hat_models: Dict[str, str] = {}
        #: Правки по стилям шапки: {индекс стиля: снимок}. Стиль — отдельная
        #: модель, и правки одного к другому не относятся; сборка собирает все
        #: изменённые стили в ОДИН мод, как в окне приложения.
        self._hat_styles: Dict[int, Dict[str, Any]] = {}
        #: Краска для превью: ключ банки из `paints()` или пусто. Только показ —
        #: в мод краска не идёт, её накладывает игра.
        self._paint = ''
        #: Ключ шапки из каталога (основная модель). Стили — та же шапка с
        #: другой моделью, и работа у них одна: ключ работы берётся отсюда,
        #: а не из модели показанного стиля.
        self._hat_key = ''
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
        #: Редактор частиц: открытый PCF, его история и сборка.
        self.particles = ParticlesEditor(self)
        # У каждого подписчика СВОЯ очередь: с одной общей два открытых окна
        # делили бы события пополам вместо того, чтобы каждое получило все.
        self._subscribers: "list[queue.Queue[dict]]" = []
        self._lock = threading.Lock()
        #: Покраска частей модели: своя картинка или цвет на куске геометрии.
        self.parts = PartsEditor(self)
        self._bind()
        self._edits_reset()

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
        # Событие несёт РАЗРЕШЁННЫЕ грани (своя → нарезка → стоковая): и
        # стоковая загрузка, и нарезка панорамы приходят одним сигналом, а
        # что из них показать, решает домен.
        self.skybox.ready.connect(lambda _faces: self._put_skybox())
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
                     restore: bool = False,
                     hat: str = '') -> Dict[str, Any]:
        """
        Начинает загрузку 3D-превью предмета.

        restore — вернуть сохранённую работу. По умолчанию НЕТ: каталог
        показывает предмет таким, какой он в игре. Свои работы открываются
        своим списком (`works`), иначе выбор «Обрез» молча давал бы чужой
        обрез, и вернуться к игровому было нечем.

        hat — ключ шапки из каталога: у стилевой шапки модель у каждого стиля
        своя, а работа одна, и ключ работы берётся по шапке, а не по модели.

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
        self._remember_hat_style(style if mode == 'hat' else None,
                                 hat if mode == 'hat' else '')
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
        self._bodygroups = {}          # состояние — свойство показанной модели
        self._forget_decor()           # и гирлянда: у нового предмета своя
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
        # Показанный стиль снимком не держим: его правда — живые правки, а
        # снимок остаётся от прошлого ухода и вернул бы старое поверх нового.
        self._hat_styles.pop(self._hat_style, None)
        self._edits_reset()

        logger.info(f"load_preview: mode={mode!r} key={weapon_key!r}")
        # Работа с подменённой моделью открывается на НЕЙ: игровая геометрия
        # показала бы чужую текстуру не на том, для чего её рисовали.
        if not self._restore_custom_model(lang):
            self.controller.load_game_model(
                weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang,
                bodygroups=self._bodygroups)
            # Стили ищем параллельно: QC после декомпиляции окажется в кэше,
            # так что ждать своей очереди воркеру почти не придётся.
            self.skins.detect(weapon_key, mode, paths['misc_vpk'], lang=lang)
        self._mode = mode
        return {'started': True, 'mode': mode, 'weapon_key': weapon_key,
                # Какие стили уже правлены: страница ставит на них метку, иначе
                # про правку соседнего стиля вспоминают только в игре.
                'edited_styles': sorted(self._hat_styles)}

    def _remember_hat_style(self, style: Optional[int], hat: str = '') -> None:
        """
        Запоминает правки уходящего стиля шапки.

        ``style is None`` или другой ``hat`` — это НОВАЯ шапка, а не стиль
        номер ноль: правки её предшественницы к ней не относятся, и память
        чистится целиком.
        """
        if style is None or hat != self._hat_key:
            self._hat_styles = {}
            self._hat_key = hat
            self._hat_style = int(style or 0)
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
        else:
            # «Убрать всё» на стиле: прежний снимок иначе ушёл бы в мод.
            self._hat_styles.pop(self._hat_style, None)
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
        self._edits_reset()

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
        custom_smd, keep = '', False
        if not key and self.preview.custom_vpk_mode:
            key = self.preview.custom_vpk_weapon or ''
            custom_smd, keep = self.preview.custom_vpk_smd or '', True
        elif self.preview.custom_smd_path:
            # Своя модель (SMD либо импорт OBJ/GLB с запечённой подгонкой)
            # едет в руку тем же слиянием, что и в мод: одна кость — жёсткий
            # кусок на хвате, кости под игровыми именами — с анимацией частей.
            custom_smd = self.preview.custom_smd_path
            keep = bool(self.preview.custom_keep_materials)
        if not key:
            return {'error': 'Вид от первого лица есть только у оружия'}

        # Гирлянда едет в руку костями пушки — как в игре: без флага
        # `model_display_flags` она видна и от первого лица.
        decor = self._decor_scene_args(key)
        decor_smd = decor['decor_smd']

        # Та же сцена уже в кадре — меняем ОДНИ ДОРОЖКИ. Меш, скелет и
        # текстуры у одного оружия те же, и пересобирать их ради выбора
        # анимации значит каждый раз заново распаковывать текстуры.
        if not full and self.viewmodel.shows(key, mode, decor_smd):
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
                            custom_smd=custom_smd, keep_materials=keep,
                            decor_smd=decor_smd,
                            decor_prefix=decor['decor_prefix'])
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

    #: Сколько строк отдаём за раз. Записей в игре десять с половиной тысяч,
    #: и рисовать их все — секунды на пустом месте; дальше страница просит
    #: следующую порцию сама.
    SOUND_PAGE = 400

    #: Фасеты страницы звуков — в том порядке, в каком их показывает колонка.
    SOUND_FACETS = ('section', 'who', 'group', 'variant', 'format')

    def sounds(self, section: str = '', who: str = '', group: str = '',
               variant: str = '', fmt: str = '', own: bool = False,
               query: str = '', offset: int = 0,
               lang: str = 'ru') -> Dict[str, Any]:
        """Записи под фильтрами страницы и сами фильтры со счётчиками.

        Один ответ на всё: строки, сколько их всего, и для каждого фасета —
        сколько записей стоит за каждым его значением. Счётчик фасета
        считается БЕЗ его собственного фильтра: выбрав «Scout», человек
        видит, сколько у солдата, а не ноль у всех, кроме разведчика.
        Раздел — ось главная, и его счётчики не зависят от остальных
        фасетов вовсе: словари групп у разделов разные, и «Выстрел» иначе
        гасил бы «Реплики».
        """
        from src.data import sound_catalog as sc

        rows = self._sound_rows(lang)
        section = (section or '').strip().lower()
        who = (who or '').strip().lower()
        group = (group or '').strip().lower()
        variant = (variant or '').strip().lower()
        fmt = (fmt or '').strip().lower()
        # Разделители убираем с обеих сторон: скаттерган в игре записан
        # `Weapon_Scatter_Gun`, и поиск «scattergun» его не находил.
        words = [_plain(w) for w in (query or '').split() if _plain(w)]
        picks = self._wave_picks

        def is_own(row: Dict[str, Any]) -> bool:
            return any(w in picks for w in row['waves'])

        scores: Dict[str, float] = {}
        counts: Dict[str, Dict[str, int]] = {f: {} for f in self.SOUND_FACETS}
        #: Сколько записей стоит за «Все» в каждом фасете: сумма по значениям
        #: не годится, у дробовика четыре класса, и он считался бы четырежды.
        every: Dict[str, int] = {f: 0 for f in self.SOUND_FACETS}
        hits: List[Dict[str, Any]] = []
        #: Разделы, которые прочитались вовсе. Вкладка раздела стоит всегда,
        #: даже когда под поиском в нём пусто: исчезающие вкладки читаются
        #: как поломка, а ноль при слове — как ответ.
        present: set = set()
        for row in rows:
            present.add(row['section'])
            if own and not is_own(row):
                continue
            if words:
                score = _score(row, words)
                if score < 0:
                    continue
                scores[row['name']] = score
            ok = {
                'section': not section or row['section'] == section,
                'who': not who or who in row['who'],
                'group': not group or row['group'] == group,
                'variant': not variant or (variant == 'mvm') == row['mvm'],
                'format': not fmt or fmt in row['formats'],
            }
            if all(ok.values()):
                hits.append(row)
            tally = counts['section']
            tally[row['section']] = tally.get(row['section'], 0) + 1
            every['section'] += 1
            if not ok['section']:
                continue
            for facet in ('who', 'group', 'variant', 'format'):
                if not all(v for k, v in ok.items() if k != facet):
                    continue
                every[facet] += 1
                keys = ({'who': row['who'], 'group': (row['group'],),
                         'variant': ('mvm' if row['mvm'] else 'normal',),
                         'format': row['formats']})[facet]
                tally = counts[facet]
                for key in keys:
                    tally[key] = tally.get(key, 0) + 1

        classes = {c['key'].lower(): c['name'] for c in self._classes(lang)}
        who_names = {**{k: classes[k] for k in sc.CLASSES if k in classes},
                     **sc.WHO_NAMES}
        chosen = {'section': section, 'who': who, 'group': group,
                  'variant': variant, 'format': fmt}
        labels = {'section': sc.SECTION_NAMES, 'who': who_names,
                  'group': sc.GROUP_NAMES, 'variant': sc.VARIANT_NAMES,
                  'format': sc.FORMAT_NAMES}
        facets = {
            facet: [{'key': key, 'name': name, 'count': counts[facet].get(key, 0)}
                    for key, name in labels[facet].items()
                    if counts[facet].get(key) or key == chosen[facet]
                    or (facet == 'section' and key in present)]
            for facet in self.SOUND_FACETS}

        # Под поиском — по убыванию совпадения: «pistol» должен начинаться с
        # пистолета, а не с ракетницы, у которой пистолетный звук пустого
        # магазина. Без поиска — порядок скрипта: он и так группирует.
        if words:
            hits.sort(key=lambda row: -scores[row['name']])
        # `own` подставляем ЗДЕСЬ, а не храним в строках: иначе выбор одного
        # звука обесценивал весь разобранный каталог, и следующий же список
        # стоил секунду на пересборку десяти тысяч записей. Копию делаем
        # только для порции, что уедет наружу.
        offset = max(0, int(offset or 0))
        hidden = ('blob', 'terms', 'labels', 'name_plain')
        page = [{k: v for k, v in row.items() if k not in hidden}
                | self._own_state(row)
                for row in hits[offset:offset + self.SOUND_PAGE]]
        return {'rows': page, 'total': len(hits), 'offset': offset,
                'facets': facets, 'all': every,
                # Ничего не нашлось — может, опечатка: «scatergun».
                'suggest': (self._suggest(words, section, lang)
                            if words and not hits else []),
                # Пустой список сам по себе ничего не объясняет: страница по
                # этому флагу отличает «сузил до нуля» от «скрипты игры не
                # прочитались».
                'loaded': bool(rows),
                # Сколько своих звуков выбрано ВСЕГО. Страница видит только
                # свою порцию списка, и считать по ней — значит терять
                # выбранное, как только сменишь фильтр.
                'picked': self._picked_total(),
                'files': len(picks)}

    def _own_state(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Что у записи заменено: {own, own_waves, partial}.

        `own` — свой файл, если он один на все файлы записи; `own_waves` —
        по каждому файлу, откуда бы замена ни пришла (и через другую
        запись с тем же файлом); `partial` — заменена часть.
        """
        picks = self._wave_picks
        own_waves = {w: picks[w] for w in row['waves'] if w in picks}
        paths = set(own_waves.values())
        whole = len(own_waves) == len(row['waves']) and len(paths) == 1
        return {'own': next(iter(paths)) if whole else '',
                'own_waves': own_waves,
                'partial': bool(own_waves) and not whole}

    def _suggest(self, words: List[str], section: str,
                 lang: str) -> List[str]:
        """Похожие слова из словаря раздела: «scatergun» → «scattergun».

        Словарь — как записи ЗОВУТ (имена предметов, классы, группы), без
        имён файлов и ключей моделей: там мусора больше, чем подсказок.
        Сравниваем по сжатому виду, показываем как пишут.
        """
        import difflib

        vocab = self._sound_vocab(section, lang)
        out: List[str] = []
        # Сначала запрос целиком: «rocket lancher» — это «rocket launcher»,
        # а не «rocket» и «launcher» по отдельности.
        whole = ''.join(words)
        for near in difflib.get_close_matches(whole, vocab, n=2, cutoff=0.8):
            if near != whole and vocab[near] not in out:
                out.append(vocab[near])
        for w in words if not out else ():
            for near in difflib.get_close_matches(w, vocab, n=2, cutoff=0.72):
                label = vocab[near]
                if near != w and label not in out:
                    out.append(label)
        return out[:3]

    def _sound_vocab(self, section: str, lang: str) -> Dict[str, str]:
        """{сжатое слово: как пишут} по разделу — один раз на язык и раздел."""
        key = (section, lang)
        cache = getattr(self, '_sound_vocab_cache', None)
        if cache is None:
            cache = self._sound_vocab_cache = {}
        if key not in cache:
            vocab: Dict[str, str] = {}
            for row in self._sound_rows(lang):
                if section and row['section'] != section:
                    continue
                for label in row['labels']:
                    plain = _plain(label)
                    # С цифрами — имена файлов-сирот (`rocket1`), не слова.
                    if (len(plain) > 2 and '_' not in label
                            and not any(c.isdigit() for c in plain)):
                        vocab.setdefault(plain, label)
            cache[key] = vocab
        return cache[key]

    def _classes(self, lang: str) -> List[Dict[str, str]]:
        from src.app.api import classes as api_classes
        return [c for c in api_classes(lang) if c.get('key')]

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
        # Английские имена — в поиск: их знают и те, кто играет по-русски.
        loc_en = (loc if lang != 'ru'
                  else parse_localization(paths['root'], 'english'))
        titles = sound_catalog.GROUP_NAMES
        # items_game называет предмет лишь у каждой шестой записи. Остальные
        # опознаём по имени субъекта: `Weapon_Ambassador` — это `TF_Ambassador`
        # в локализации и `c_ambassador` в каталоге оружия. Без этого «посол» и
        # «нож» в поиске не находились вовсе: имена записей латинские.
        guess = self._subject_index(loc, lang)
        classes = {c['key'].lower(): c['name'] for c in self._classes(lang)}
        who_names = {**classes, **sound_catalog.WHO_NAMES}
        rows = []
        for entry in entries:
            items = [loc.get(token, loc.get(token.lower(), token))
                     for token in entry.items]
            items_en = [loc_en.get(token, loc_en.get(token.lower(), ''))
                        for token in entry.items]
            stem = _plain(entry.subject.removeprefix('Weapon_')
                          .removeprefix('Weapon'))
            found = guess.get(stem, ('', (), '', ()))
            named = ''
            if not found[2]:
                # Рабочее имя Valve в звуке и имя предмета в игре сходятся не
                # всегда: миниган там `Gatling`, «Мачина» — `SniperRailgun`.
                named = sound_catalog.SUBJECT_ITEMS.get(entry.subject, '')
                if named:
                    found = self._by_item(guess, named) or found
            known, cls, weapon_key = found[:3]
            aliases = found[3] if len(found) > 3 else ()
            if not known:
                # Постройки: предмета нет, имя в игре есть.
                for word in sound_catalog.words_of(entry.subject):
                    token = sound_catalog.BUILDING_TOKENS.get(word)
                    if token:
                        known = loc.get(token, '')
                        aliases = (loc_en.get(token, ''),)
                        break
            # Чей звук — от точного к догадке: items_game, каталог оружия,
            # имя записи. Нет ничего — «прочие»: без ключа под фильтром до
            # строки не добраться.
            who = list(entry.classes or cls or entry.who) or ['other']
            # У звуков мира говорящего нет (см. `make_entry`), а догадка по
            # имени субъекта тут ложная: `Grenade.Roll` — не чья-то граната.
            if entry.section == 'world':
                who = ['other']
            title = _sound_title(entry, items, known, classes)
            row = {
                'name': entry.name, 'event': entry.event,
                'group': entry.group, 'section': entry.section,
                'group_name': titles.get(entry.group, entry.group),
                'waves': list(entry.waves),
                # Дубли, свёрнутые в запись: по ним страница подписывает
                # файлы именами записей игры.
                'takes': list(entry.takes),
                'channel': entry.channel, 'volume': entry.volume,
                'level': entry.level, 'pitch': entry.pitch,
                'formats': sorted({w.rsplit('.', 1)[-1].lower()
                                   for w in entry.waves}),
                'items': items,
                'who': who,
                'mvm': entry.mvm,
                # У предмета берём его иконку из рюкзака, у остального —
                # картинку по субъекту: портрет класса, значок постройки.
                'icon': weapon_key or sound_catalog.icon_for(
                    entry.subject, entry.section, who[0]),
                # Подпись карточки: у связанной записи это сам предмет, иначе
                # опознанное по имени, иначе класс или само имя субъекта.
                'title': title,
            }
            # Слова для поиска — один раз здесь, а не на каждую букву. Термины
            # — то, по чему запись ЗОВУТ: имя предмета на обоих языках, ключ
            # модели, класс, слот, группа; совпадение с ними весит больше,
            # чем случайное вхождение в путь файла (см. `_score`).
            # `labels` — те же слова, но как их пишут люди: из них
            # собираются подсказки «возможно, вы имели в виду».
            row['labels'] = tuple(dict.fromkeys(
                t.strip().lower() for t in (
                    title, *items, *items_en, *aliases, named,
                    *(who_names.get(w, '') for w in who), row['group_name'],
                    entry.group)
                if t.strip()))
            row['terms'] = tuple(dict.fromkeys(
                _plain(t) for t in (
                    title, *items, *items_en, *aliases, named, stem,
                    *(who_names.get(w, '') for w in who),
                    entry.group, row['group_name'])
                if _plain(t)))
            # Поля через пробел, внутри поля разделителей нет: скаттерган в
            # игре записан `Weapon_Scatter_Gun`, и «scattergun» обязан
            # находиться, а склеивать соседние поля в одно слово незачем.
            row['name_plain'] = _plain(entry.name)
            row['blob'] = ' '.join(
                [*row['terms'], row['name_plain'],
                 *(_plain(w) for w in entry.waves)])
            rows.append(row)
        # Общие файлы: у кого ещё стоит тот же файл. Игра подменяет файл, и
        # заменив «промах» у биты, человек заменил его и у бутылки — об этом
        # надо сказать до сборки, а не после.
        owners: Dict[str, List[str]] = {}
        for row in rows:
            for wave in row['waves']:
                owners.setdefault(wave, []).append(row['name'])
        for row in rows:
            shared = {w: [n for n in owners[w] if n != row['name']]
                      for w in row['waves'] if len(owners[w]) > 1}
            row['shared'] = shared
            row['shared_count'] = len({n for names in shared.values()
                                       for n in names})
        self._sound_lang, self._sound_cache = lang, rows
        self._sound_vocab_cache = {}
        return rows

    def _subject_index(self, loc: Dict[str, str],
                       lang: str) -> Dict[str, tuple]:
        """{сжатое имя субъекта: (название предмета, классы, иконка)}.

        Два источника: локализация знает больше всего названий
        (`Weapon_Scatter_Gun` → «Обрез»), каталог оружия — единственный, кто
        знает КЛАСС и картинку. Чего нет ни там, ни там, получает значок
        раздела (`icon_for`) — на строку без картинки это не похоже.

        Каталог индексируется и по ключу модели, и по имени на ОБОИХ языках:
        `SUBJECT_ITEMS` называет предметы по-английски, и в русском
        интерфейсе «Machina» иначе не находилась. Классов у предмета
        бывает несколько — дробовик носят четверо, — и копятся все.
        """
        from src.data.weapons import (
            TF2_WEAPONS, WEAPON_SLOT_TYPES, get_weapon_type_name,
        )

        out: Dict[str, tuple] = {}
        for token, value in loc.items():
            if not token.lower().startswith('tf_'):
                continue
            stem = _plain(token[3:].removeprefix('Weapon_').removeprefix('weapon_'))
            if stem and stem not in out:
                out[stem] = (value, (), '', ())

        for cls_name, slots in TF2_WEAPONS.items():
            cls = cls_name.lower()
            for slot, weapons in slots.items():
                # Тело и руки класса — не оружие.
                if slot not in WEAPON_SLOT_TYPES:
                    continue
                # Слот на обоих языках — тоже слово для поиска: «scout melee»
                # должен находить биту, а «основное» — обрез.
                slot_terms = (slot, get_weapon_type_name(slot, 'ru'),
                              get_weapon_type_name(slot, 'en'))
                for key, names in weapons.items():
                    if isinstance(names, dict):
                        title = names.get(lang, names.get('ru', key))
                        aliases = tuple(dict.fromkeys(names.values()))
                    else:
                        title, aliases = names, (names,)
                    bare = key.removeprefix('c_').removeprefix('v_')
                    # Ключ каталога часто с хвостом класса (`c_flaregun_pyro`),
                    # а в звуке его нет — заводим и укороченный вид.
                    stems = {_plain(bare), _plain(bare.removesuffix('_' + cls)),
                             *(_plain(a) for a in aliases)}
                    terms = (*aliases, bare, *slot_terms)
                    for stem in stems:
                        if not stem:
                            continue
                        was_name, was_cls, was_key, was_terms = out.get(
                            stem, ('', (), '', ()))
                        out[stem] = (was_name or title,
                                     tuple(dict.fromkeys((*was_cls, cls))),
                                     was_key or key,
                                     tuple(dict.fromkeys((*was_terms, *terms))))
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
        # Записи с таким именем может не быть вовсе: тогда сборка её
        # молча пропустит, а в подвале будет висеть «Своих звуков: 1».
        row = self._row(name)
        if row is None:
            return {'error': 'Такой записи в игре нет'}
        skipped = 0
        if not path:
            for w in row['waves']:
                self._wave_picks.pop(w, None)
        else:
            trouble = (self._wrong_format(row['waves'], path)
                       or check_wav(path))
            if trouble:
                return {'error': f'Файл не подойдёт: {trouble}'}
            # Только совпавшие по расширению: у части записей файлы разных
            # форматов вперемешку, и WAV, положенный под именем `.mp3`,
            # дал бы в игре тишину вместо звука.
            kind = path.rsplit('.', 1)[-1].lower()
            fit = [w for w in row['waves'] if w.lower().endswith('.' + kind)]
            skipped = len(row['waves']) - len(fit)
            self._wave_picks.update({w: path for w in fit})
        return {'name': name, **self._own_state(row),
                'total': self._picked_total(), 'files': len(self._wave_picks),
                'skipped': skipped, 'affected': self._affected(row['waves'])}

    def _affected(self, waves: List[str]) -> Dict[str, Dict[str, Any]]:
        """Состояние всех записей, где стоят эти файлы, включая чужие.

        Заменив «промах» у биты, человек заменил его и у бутылки: её строка
        на странице обязана это показать сразу, а не после перезагрузки.
        """
        touched = set(waves)
        return {r['name']: self._own_state(r) for r in self._rows_any()
                if touched.intersection(r['waves'])}

    def _row(self, name: str) -> Optional[Dict[str, Any]]:
        """Запись каталога по имени. None — такой в игре нет."""
        return next((r for r in self._rows_any() if r['name'] == name), None)

    def _picked_total(self) -> int:
        """Сколько записей затронуто заменами — включая те, до которых
        замена дошла через общий файл."""
        picks = self._wave_picks
        if not picks:
            return 0
        return sum(1 for r in self._rows_any()
                   if any(w in picks for w in r['waves']))

    def clear_sounds(self) -> Dict[str, Any]:
        """Снимает все свои звуки разом."""
        self._wave_picks.clear()
        return {'total': 0, 'files': 0}

    def _set_wave(self, name: str, wave: str,
                  path: Optional[str]) -> Dict[str, Any]:
        """То же, но для ОДНОГО файла записи."""
        row = self._row(name)
        if row is None or wave not in row['waves']:
            return {'error': 'Такого файла у этой записи нет'}
        if not path:
            self._wave_picks.pop(wave, None)
        else:
            from src.services.sound_build_service import check_wav

            trouble = self._wrong_format([wave], path) or check_wav(path)
            if trouble:
                return {'error': f'Файл не подойдёт: {trouble}'}
            self._wave_picks[wave] = path
        return {'name': name, 'wave': wave, **self._own_state(row),
                'total': self._picked_total(), 'files': len(self._wave_picks),
                'affected': self._affected([wave])}

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

        if not self._wave_picks:
            return {'error': 'Не выбрано ни одного своего звука'}
        by_wave = dict(self._wave_picks)

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
                'sounds': self._picked_total()}

    def _sky_names_to_build(self) -> Optional[list]:
        """Какие имена небес перекрывает мод: выбранное либо ВСЕ стоковые.

        «Все карты» — каждая карта зовёт своё небо по имени в worldspawn, и
        одно небо на всю игру означает VMT под каждым именем (VTF при этом
        одни, см. build_skybox_vpk). Список — у установленной игры.
        """
        from src.data.skyboxes import SKY_ALL_MAPS_KEY
        from src.services.skybox_service import SkyboxService

        sky = getattr(self, '_sky_name', '')
        if not sky:
            return None
        if sky != SKY_ALL_MAPS_KEY:
            return [sky]
        paths = self.tf2_paths()
        return SkyboxService.enumerate_sky_names(
            '' if 'error' in paths else str(paths.get('root') or ''))

    def _skybox_faces(self) -> Dict[str, str]:
        """Что показывать по граням: своя → нарезка панорамы → стоковая."""
        from src.data.skyboxes import SKY_FACES

        out: Dict[str, str] = {}
        for face in SKY_FACES:
            got = self.preview.textures.resolve_skybox_face(face)
            if got:
                out[face] = got
        return out

    def _put_skybox(self) -> None:
        """Сообщает странице состояние неба целиком.

        Панорама едет отдельным полем: у неё своя карточка в ленте, и без неё
        человеку некуда положить фото 360° (ключ `SKY_PANO_KEY`, гранью он не
        является и в сборку идёт как `equirect`).
        """
        from src.data.skyboxes import SKY_PANO_KEY

        self._put('skybox', faces=self._skybox_faces(),
                  pano=self.preview.textures.skybox_pano() or '',
                  pano_key=SKY_PANO_KEY)

    def _after_skybox_texture(self, material: str, path) -> None:
        """Реакция на подмену грани или панорамы в режиме неба.

        Панораму надо НАРЕЗАТЬ: шесть граней из фото 360° делает воркер, и до
        этого превью её не видит вовсе — раньше перенос фото не менял ничего.
        Подмену одной грани достаточно показать: она уже в домене.
        """
        from src.data.skyboxes import SKY_FACES, SKY_PANO_KEY

        if material == SKY_PANO_KEY:
            if path:
                self.skybox.split(str(path))    # ready → _put_skybox
                return
            self.skybox.stop_split()
            with self._lock:
                self.preview.textures.skybox_split_faces = {}
        elif material not in SKY_FACES:
            return
        self._put_skybox()

    def load_skybox(self, sky_name: str) -> Dict[str, Any]:
        """Готовит грани стокового неба для показа кубмапой."""
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        from src.data.skyboxes import SKY_ALL_MAPS_KEY, SKY_PREVIEW_DEFAULT

        self._mode = 'skybox'
        # Какое небо перекрывать — знает сборка: без имени мод собрался бы
        # пустым (см. validate_skybox_request). «Все карты» — ключ, а не
        # небо: сборка развернёт его в полный список, а превью показывает
        # одно стоковое небо — своего у пункта нет.
        self._sky_name = sky_name
        with self._lock:
            self.preview.mode.enter(_skybox_mode())
            self._forget_model()
        self._edits_reset()
        # Небеса лежат и в hl2/ — оттуда же и грани, иначе половина списка
        # показывалась бы пустой (см. TF2Paths.skybox_vpks).
        from src.services.tf2_paths import TF2Paths
        shown = SKY_PREVIEW_DEFAULT if sky_name == SKY_ALL_MAPS_KEY else sky_name
        self.skybox.load(shown, TF2Paths.skybox_vpks(paths['root']))
        return {'started': True, 'sky': sky_name}

    def set_texture(self, material: str, path: Optional[str]) -> Dict[str, Any]:
        """
        Кладёт пользовательскую текстуру на материал (или снимает, path=None).

        Куда именно она попадёт — решает домен: активный стиль пишется в свои
        переопределения, нейтральный материал дублируется в обе команды, а под
        «сделать командным» дублирование запрещено. Эти правила накопились по
        багам, повторять их здесь нельзя.
        """
        # Покрашенная карточка: текстура становится основой под мазками, а не
        # заменой склейки (иначе мазки числились бы, а на модели их не было).
        under = self.parts.set_base(material, path)
        if under is None:
            with self._lock:
                self.preview.textures.set_texture(material, path)
        elif 'error' in under:
            return under
        self._autosave()
        # Небо — не материалы модели, а грани куба: страница показывает их
        # своим событием, и после подмены его надо повторить.
        from src.data.skyboxes import SKYBOX_MODE
        if getattr(self, '_mode', '') == SKYBOX_MODE:
            self._after_skybox_texture(material, path)
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

        from src.data.skyboxes import SKYBOX_MODE

        t = self.preview.textures
        # Главная текстура — то, что лежит на главном материале модели.
        main = t.stable_main()
        image = t.uploaded_for_mat(main) if main else None
        extra = t.uploaded_slot_paths()
        # У неба главного материала нет вовсе: «своя текстура» — это панорама
        # (её сборка режет сама) или подменённые грани. Слоты в сборку неба не
        # идут: там свои поля, а грани уже лежат в overrides.
        sky = t.skybox_build_data() if mode == SKYBOX_MODE else {}
        # Гирлянды поверх оружия собираются своими моделями: правлена может
        # быть одна гирлянда, и оружие тогда в мод не идёт вовсе.
        decor = self._decor_builds(paths['root']) if mode != SKYBOX_MODE else []
        if mode == SKYBOX_MODE:
            image = sky.get('equirect') or None
            extra = {}
            if not image and not sky.get('face_overrides'):
                return {'error': 'Загрузите панораму 360° или грани неба'}
        elif not image and not extra and not decor:
            return {'error': 'Не загружено ни одной своей текстуры'}

        # Гифка на части: превью держит один кадр, сборке нужны все. Полные
        # склейки печёт воркер (это десятки секунд), а запрос уже смотрит на
        # их будущие пути.
        decor_paths = [p for d in decor for teams in d['textures'].values()
                       for p in teams.values()]
        plan = self.parts.bake_plan([image, *extra.values(),
                                     *t.blu_uploaded_paths().values(), *decor_paths])
        baked = self.parts.baked_path
        image = baked(image)
        extra = {mat: baked(p) for mat, p in extra.items()}
        for d in decor:
            d['textures'] = {mat: {team: baked(p) for team, p in teams.items()}
                             for mat, teams in d['textures'].items()}

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
            # «Прочее» со страницы: сборка спрашивает про эти материалы так
            # же, как про доп. материалы геометрии.
            misc_materials=list(self.preview.misc_materials) or None,
            panel_blu_textures={mat: baked(p) for mat, p
                                in t.blu_uploaded_paths().items()} or None,
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
            decor_builds=decor or None,
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
            # Небо: какие имена перекрывает мод и чем заменены отдельные грани.
            # Панорама уехала в `image_path` — сборка режет её сама, в
            # выбранном разрешении.
            skybox_sky_names=(self._sky_names_to_build()
                              if mode == SKYBOX_MODE else None),
            skybox_face_overrides=(sky.get('face_overrides') or None),
        )

        from src.services.build_worker import BuildWorker
        w = BuildWorker(request=request,
                        prepare=(lambda report: self.parts.bake(plan, report))
                        if plan else None)

        # Сборка умеет СПРАШИВАТЬ у интерфейса недостающую текстуру и
        # блокируется до ответа (UiRequest, таймаут 300 секунд). Раньше здесь
        # отвечали сразу тем, что нашлось в сеансе, а «не нашлось» означает
        # «взять ГЛАВНУЮ текстуру» — то есть скин молча растекался на служебные
        # материалы. Теперь вопрос доходит до человека, как в окне приложения.
        w.request_extra_texture.connect(self._on_build_needs_texture)
        # Сменные части модели (бутылка целая/разбитая, набалдашник кабера до и
        # после взрыва) при подмене модели спрашиваются так же. Раньше сигнал
        # никто не слушал: сборка молча ждала ответа пять минут на каждую
        # часть и шла дальше с игровой геометрией.
        w.request_extra_model.connect(self._on_build_needs_model)
        w.texture_mismatch_warning.connect(
            lambda msg: w._texture_mismatch_req.answer(True))

        w.progress.connect(lambda pct, text: self._put('build_progress',
                                                       percent=pct, text=text))
        w.sub_progress.connect(lambda pct, text: self._put('build_progress',
                                                           percent=pct, text=text))
        w.finished.connect(lambda ok, msg: self._put('build_done',
                                                     ok=bool(ok), message=msg))
        w.finished.connect(lambda ok, msg: self.parts.drop_baked())
        w.error.connect(lambda msg: self._put('build_done', ok=False, message=msg))
        self._build = w
        self._texture_choice = _NO_CHOICE   # «ко всем» — на одну сборку
        w.start()
        return {'started': True, 'filename': request.filename}

    def _decor_builds(self, tf2_root: str) -> List[Dict[str, Any]]:
        """Правленые гирлянды предмета — для сборки, показаны они или нет.

        Правка гирлянды — часть работы, как текстура: выключенный показ её не
        отменяет. Текстуры — по материалу гирлянды, обе команды (карточка
        нейтральна, пока синюю не задали отдельно).
        """
        from src.services import festive_decor

        key = self._decor_key()
        models = festive_decor.kinds(key, tf2_root) if key else {}
        uploads = self.preview.textures.decor_uploads()
        out = []
        for kind, mdl in models.items():
            textures = {}
            for card, teams in uploads.items():
                card_kind, material = festive_decor.parse_card(card)
                if card_kind == kind and material:
                    textures[material] = dict(teams)
            fit = self.preview.decor_fit.get(kind)
            bends = self.preview.decor_bends.get(kind) or []
            if textures or fit or bends:
                out.append({'kind': kind, 'mdl': mdl, 'fit': dict(fit) if fit else None,
                            'bends': [dict(b) for b in bends], 'textures': textures,
                            # Оружие — ради позы превью: изгибы сделаны в ней.
                            'weapon': key})
        return out

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
        # Правка стиля хранится под БАЗОВЫМ материалом, а сборка спрашивает
        # материал строки $texturegroup по его имени (c_sd_cleaver_bloody) —
        # без этой связки Bloody у гильотины собирался бы игровым.
        uploaded = (self.preview.textures.uploaded_for_mat(material)
                    or self.preview.textures.style_upload_for(material))
        if uploaded:
            self._answer_texture_request(self.parts.baked_path(uploaded))
            return
        # Сборку отменяют: воркер дойдёт до проверки отмены только после
        # ответа, а каждый новый вопрос до неё показывал бы окно заново.
        build = self._build
        if build is not None and build.isInterruptionRequested():
            from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
            self._answer_texture_request(EXTRA_TEX_USE_GAME_ORIGINAL)
            return
        if self._texture_choice is not _NO_CHOICE:
            self._answer_texture_request(self._texture_choice)
            return
        self._put('need_texture', material=material, weapon_key=weapon_key,
                  remaining=int(remaining))

    # ── Сменная часть модели: вопрос страницы, ответ человека ─────────────── #

    def _on_build_needs_model(self, smd_name: str, weapon_key: str) -> None:
        """
        Сборке нужна геометрия сменной части (`$bodygroup`): своя модель
        подменила основную, а у оружия есть ещё состояния — разбитая бутылка,
        взорванный кабер. Игра переключает их сама, и мод должен дать каждое.
        """
        build = self._build
        if build is not None and build.isInterruptionRequested():
            self._answer_model_request(None)
            return
        self._put('need_model', part=smd_name, weapon_key=weapon_key,
                  kind=_part_kind(smd_name))

    def _answer_model_request(self, path: Optional[str]) -> None:
        build = self._build
        if build is not None and hasattr(build, 'set_extra_model_result'):
            build.set_extra_model_result(path)

    def answer_model(self, path: str = '') -> Dict[str, Any]:
        """Ответ страницы на ``need_model``: свой SMD либо пусто — игровая."""
        if path and not os.path.isfile(path):
            return {'error': 'Файл модели не найден'}
        self._answer_model_request(path or None)
        return {'ok': True}

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
        from src.shared.constants import (
            EXTRA_TEX_USE_GAME_ORIGINAL, EXTRA_TEX_USE_MAIN,
        )

        if choice == 'file' and path:
            value = path
        elif choice == 'main':
            value = EXTRA_TEX_USE_MAIN
        else:
            value = EXTRA_TEX_USE_GAME_ORIGINAL

        if apply_all:
            self._texture_choice = value
        self._answer_texture_request(value)
        return {'answered': choice}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Частицы — src/app/particles_editor.py (self.particles)
    # ═══════════════════════════════════════════════════════════════════════ #

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
        self._forget_decor()
        self._vpk_mod_path = path
        # Показанный мод — это и есть предмет: приложение так же переключает
        # категорию на «Кастомный мод» и ставит режим 'custom'.
        self._mode = 'custom'
        # Мод опознаётся файлом в библиотеке — по нему и находится работа.
        self.preview.forget_user_edits()
        self._restore_work()
        self._edits_reset()
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

        from src.domain.preview.material_cards import editable_material_cards
        from src.services import mesh_import_service

        pending = self._pending_model
        if keep is not None and pending and pending['src'] == (path or pending['src']):
            # Второй заход после ответа: SMD уже сконвертирован.
            smd, obj, materials = pending['smd'], pending['obj'], pending['materials']
            source, fit = pending['source'], pending['fit']
        else:
            if not path or not os.path.isfile(path):
                return {'error': 'Файл модели не найден'}
            # Источник помним у любой модели: подгонка (масштаб, поворот,
            # сдвиг) пересобирает SMD из него. У OBJ/GLB SMD делаем сами.
            source, fit = path, mesh_import_service.Fit()
            try:
                smd = self._bake_imported_mesh(path, fit)
            except mesh_import_service.MeshImportError as exc:
                return {'error': str(exc)}
            obj, materials = self._custom_model_obj(smd, ghost=True)
            if obj is None:
                return {'error': 'SMD не сконвертировался'}

        cards = [c.name for c in editable_material_cards(materials)]
        if keep is None:
            self._pending_model = {'src': path, 'smd': smd, 'obj': obj,
                                   'materials': materials, 'source': source,
                                   'fit': fit}
            return {'ask_keep': True, 'materials': cards,
                    'recommend_keep': len(cards) > 1}

        self._pending_model = None
        with self._lock:
            p = self.preview
            # Главный материал ИГРОВОЙ модели — до сброса: карточки «только
            # геометрии» приедут теми же именами, но позже, а текстуру из
            # файла класть надо сейчас.
            game_main = p.textures.stable_main()
            # Своя геометрия — свои треугольники: части прежней модели на ней
            # ничего не значат.
            p.forget_parts_layout()
            p.custom_smd_path = smd
            p.custom_obj_path = obj
            p.custom_keep_materials = bool(keep)
            p.custom_qc_text = None
            p.custom_source_path = source
            p.custom_fit = fit.to_dict() if fit else None
            p.reset_skins()
            # Командные кадры и вариант остались от ИГРОВОЙ модели — на чужой
            # геометрии они показывали бы не то. Для «только геометрии» их
            # вернёт воркер карточек.
            p.reset_team_frames()
            p.reset_misc()

        self._show_custom_model(obj, cards, lang)

        # Базовый цвет из MTL/glTF — сразу в слоты: «готовой» модели по её
        # материалам, «только геометрии» — первый найденный на главный
        # игровой материал (все её материалы схлопнутся в него).
        placed = self._place_imported_textures(
            source, cards if keep else [game_main] if game_main else [])

        self._autosave()
        logger.info(f"своя модель: {smd} keep={bool(keep)} материалов={len(cards)}")
        return {'started': True, 'keep': bool(keep), 'materials': cards,
                'obj': obj, 'fit': p.custom_fit, 'textures': placed,
                'simplified': (getattr(self, '_imported_simplified', None)
                               if source else None)}

    def _show_custom_model(self, obj: str, cards: List[str], lang: str) -> None:
        """
        Ставит свою геометрию в кадр.

        `obj` — её OBJ для вьювера, `cards` — материалы из SMD. У «готовой»
        модели они и есть карточки; у «только геометрии» карточки игровые, их
        привозит воркер без геометрии. Состояние (`custom_smd_path`, `keep`)
        к этому моменту уже выставлено — либо загрузкой, либо вернувшейся
        работой.
        """
        p = self.preview
        with self._lock:
            p.custom_obj_path = obj
            if p.custom_keep_materials:
                p.textures.material_names = cards
                p.textures.main_material = cards[0] if cards else None

        # Габариты считает та же дорожка, что и у игровой модели.
        self.controller.stop()
        # Сцена в руках собрана под ПРОШЛУЮ геометрию: забыть её, иначе
        # следующий запрос вида от первого лица получит одни дорожки.
        self.viewmodel.stop()
        self._on_model_ready(obj, '')
        # Подложку носителя `stop()` не отменяет: она про геометрию в кадре, а
        # та никуда не делась. Без возврата пушка под своей гирляндой серая.
        with self._lock:
            self.controller.apply_scene_extra()

        paths = self.tf2_paths()
        mode = getattr(self, '_mode', '')
        if 'error' in paths or not mode or not p.weapon_key:
            return
        # Стили оригинала пригодятся и своей модели: по ним переопределяют
        # текстуры вариантов. Сброшены выше — ищем заново.
        self.skins.detect(p.weapon_key, mode, paths['misc_vpk'], lang=lang)
        if not p.custom_keep_materials:
            self.controller.load_game_model(
                p.weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'],
                lang=lang, geometry=False)

    def _restore_custom_model(self, lang: str = 'ru') -> bool:
        """
        Своя модель из вернувшейся работы — в кадр. False — ставить нечего.

        Работа помнит SMD, а кадр после возврата показывал ИГРОВУЮ модель:
        текстура, нарисованная под свою геометрию, ложилась на чужую, и на
        экране было не то, что уйдёт в сборку. OBJ для вьювера живёт один
        запуск, поэтому собираем его заново из того же SMD.
        """
        from src.domain.preview.material_cards import editable_material_cards

        p = self.preview
        smd = p.custom_smd_path
        if not smd or not os.path.isfile(smd) or self._vpk_mod_path:
            return False
        # Призрак оригинала нужен подгонке, а она есть только у импорта.
        obj, materials = self._custom_model_obj(smd, ghost=bool(p.custom_source_path))
        if obj is None:
            logger.warning(f"своя модель из работы не показана: {smd}")
            return False
        cards = [c.name for c in editable_material_cards(materials)]
        with self._lock:
            # Кадры команд и «Прочее» — от игровой геометрии; правки человека
            # (текстуры, «сделать командным») уже на месте, их не трогаем.
            force = p.textures.force_team
            p.reset_team_frames()
            p.reset_misc()
            p.textures.force_team = force
        self._show_custom_model(obj, cards, lang)
        return True

    def _place_imported_textures(self, source: Optional[str], cards: List[str]) -> int:
        """Кладёт текстуры импортированной модели на карточки; сколько легло.

        `cards` — материалы «готовой» модели (свои имена) либо один главный
        игровой материал «только геометрии»: в него схлопнутся все её
        материалы, туда же идёт первая найденная картинка.
        """
        cached = getattr(self, '_imported_mesh', None)
        if not source or not cached or cached[0] != source or not cards:
            return 0
        textures = cached[1].textures if cached[1] is not None else {}
        if not textures:
            return 0
        by_card = [(m, textures[m]) for m in cards if m in textures]
        pairs = by_card or [(cards[0], next(iter(textures.values())))]
        with self._lock:
            for material, path in pairs:
                self.preview.textures.set_texture(material, path)
        return len(pairs)

    def _custom_model_obj(self, smd: str, ghost: bool):
        """OBJ своей модели для превью: (путь, материалы модели) или (None, []).

        `ghost` — добавить полупрозрачный оригинал оружия ориентиром для
        подгонки: без него человек не знает, куда повернуть и насколько
        увеличить. Его материалы идут с приставкой `ghost:` — вьювер по ней
        рисует призрак, а карточек по ним нет.
        """
        import os
        import tempfile

        from src.services import carrier_model, decompile_cache
        from src.services.smd_service import SMDService
        from src.services.smd_to_obj_service import MeshPart, SmdToObjService

        obj_dir = tempfile.mkdtemp(prefix='tf2_smd_preview_')
        obj = os.path.join(obj_dir, 'model.obj')
        # Пушка-НОСИТЕЛЬ остаётся в кадре: у праздничного оружия своей
        # моделью заменяют гирлянду, а не пушку под ней. У обычного
        # оружия носителя нет, и список пуст — на них это не влияет.
        carrier = self._carrier_for_preview()
        parts = [MeshPart(smd_path=smd, extra_smd_paths=tuple(carrier.smds))]
        if ghost:
            key = self.preview.weapon_key or ''
            qc = decompile_cache.find_cached_qc_for_weapon(key) if key else None
            ref = SMDService.find_reference_smd(os.path.dirname(qc), key) if qc else None
            if ref:
                parts.append(MeshPart(smd_path=ref, material_prefix='ghost:'))
            else:
                logger.info('призрак оригинала не показан: модель ещё не разобрана')
        ok, materials = SmdToObjService.convert_parts(parts, obj)
        if not ok or not os.path.exists(obj):
            return None, []
        # Материалы носителя и призрака предмету не принадлежат: карточек по
        # ним нет и в сборку они не идут — иначе своя модель гирлянды тянула
        # бы за собой ещё и текстуру базового обреза.
        own = carrier_model.materials(carrier)
        materials = [m for m in (materials or [])
                     if m not in own and not m.startswith('ghost:')]
        return obj, materials

    def _bake_imported_mesh(self, source: str, fit) -> str:
        """SMD с запечённой подгонкой: из OBJ/GLB — свой, из SMD — тот же с
        пересчитанными вершинами; лимиты studiomdl — ошибкой."""
        import os
        import tempfile

        from src.services import mesh_import_service

        # Разобранный меш держим: подгонка правится ползунком, и разбирать
        # 65k треугольников заново на каждый шаг — секунда впустую.
        cached = getattr(self, '_imported_mesh', None)
        if cached and cached[0] == source:
            _, mesh, out_dir = cached
        elif source.lower().endswith('.smd'):
            # Свой SMD: кости и веса остаются, двигаются только вершины.
            # Без подгонки файл идёт как есть — ничего не переписываем.
            self._imported_simplified = None
            if fit == mesh_import_service.Fit():
                return source
            out_dir = tempfile.mkdtemp(prefix='tf2_mesh_import_')
            self._imported_mesh = (source, None, out_dir)
            mesh = None
        else:
            mesh = mesh_import_service.load_mesh(source)
            # Скульпт из интернета на сотни тысяч треугольников studiomdl не
            # возьмёт — упрощаем сами, с сохранением UV; человеку об этом
            # скажет ответ загрузки. Слишком много материалов так не лечится.
            self._imported_simplified = None
            if mesh_import_service.over_limits(mesh):
                before = mesh.triangle_count
                mesh = mesh_import_service.simplify(mesh)
                self._imported_simplified = (before, mesh.triangle_count)
            problem = mesh_import_service.check_limits(mesh)
            if problem:
                raise mesh_import_service.MeshImportError(problem)
            if not mesh.has_uv:
                logger.warning(f"у модели нет UV-развёртки: {source}")
            # Одна папка на источник: SMD перезаписывается, а не плодится
            # по 15 МБ на каждый шаг ползунка.
            out_dir = tempfile.mkdtemp(prefix='tf2_mesh_import_')
            self._imported_mesh = (source, mesh, out_dir)
        stem = os.path.splitext(os.path.basename(source))[0]
        out = os.path.join(out_dir, stem + '.smd')
        if mesh is None:
            return mesh_import_service.transform_smd(source, out, fit)
        return mesh_import_service.write_smd(mesh, out, fit)

    def set_custom_fit(self, fit: Optional[dict] = None) -> Dict[str, Any]:
        """Подгонка импортированной модели: пересобирает SMD с запечённым
        трансформом. Сцену превью не перегружает — вьювер крутит модель сам
        тем же трансформом; SMD нужен сборке и виду от первого лица."""
        from src.services import mesh_import_service

        p = self.preview
        if not p.custom_source_path:
            return {'error': 'Подгонка есть только у импортированной модели'}
        parsed = mesh_import_service.Fit.from_dict(fit)
        try:
            smd = self._bake_imported_mesh(p.custom_source_path, parsed)
        except mesh_import_service.MeshImportError as exc:
            return {'error': str(exc)}
        with self._lock:
            p.custom_smd_path = smd
            p.custom_fit = parsed.to_dict()
        self._autosave()
        return {'fit': p.custom_fit}

    def drop_custom_model(self, lang: str = 'ru') -> Dict[str, Any]:
        """Забывает свою модель и возвращает в кадр игровую.

        Раньше сброс был только в состоянии: в кадре и в альбоме оставались
        своя геометрия и её карточки до перезагрузки предмета. Игровую модель
        грузим той же дорожкой, что и выбор предмета — с её карточками и
        стилями; правки текстур при этом остаются.
        """
        p = self.preview
        key, mode = p.weapon_key, getattr(self, '_mode', '')
        with self._lock:
            p.begin_game_model()
            p.custom_qc_text = None
        self._pending_model = None
        self._imported_mesh = None
        self.viewmodel.stop()        # сцена в руках была со своей моделью
        paths = self.tf2_paths()
        if key and mode and 'error' not in paths:
            self.controller.load_game_model(
                key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang)
            self.skins.detect(key, mode, paths['misc_vpk'], lang=lang)
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
                                   self._hat_key or self.preview.weapon_key,
                                   self._vpk_mod_path or '')

    @staticmethod
    def _autosave_on() -> bool:
        from src.services import work_keeper
        return work_keeper.is_enabled()

    def _autosave(self, step: bool = True) -> None:
        """Пишет правки предмета. Зовётся после КАЖДОГО изменения — потому
        здесь же и шаг истории отмены: второй список точек «после правки»
        разошёлся бы с первым.

        ``step=False`` — запомнить, но не шагом отмены: настройка кисти на
        модели ничего не меняет, и Ctrl+Z по ней был бы холостым."""
        from src.services import work_keeper
        if step:
            self._edits_commit()
        work_keeper.save(self.preview, self._work_key(),
                         self._style_snapshots(), self._item_id())

    # ═══════════════════════════════════════════════════════════════════════ #
    # История правок предмета: Ctrl+Z / Ctrl+Y
    # ═══════════════════════════════════════════════════════════════════════ #

    #: Глубже тридцати шагов не помнит никто.
    EDIT_HISTORY_LIMIT = 30

    def _edits_reset(self) -> None:
        """Точка отсчёта: предмет открыт (с работой или без). Раньше неё
        откатываться нельзя — там правки другого предмета."""
        self._edit_history = [self._edit_snapshot()]
        self._edit_pos = 0

    def _edit_snapshot(self) -> Dict[str, Any]:
        """Снимок правок — то же, что уходит на диск, своей копией."""
        import copy
        return self._shield_work_files(copy.deepcopy(self.preview.user_edits()))

    def _shield_work_files(self, node: Any) -> Any:
        """
        Пути в папку работы заменяет своими копиями.

        Вернувшаяся с диска работа ссылается в `work/<ключ>/files`, а
        автосохранение при каждой записи убирает оттуда всё, на что правки
        больше не ссылаются (и всю папку, когда правок не осталось). Снимку
        истории эти файлы ещё нужны: сняли текстуру — Ctrl+Z обязан её
        вернуть. Копия делается один раз на файл и живёт с сеансом.
        """
        if isinstance(node, dict):
            return {k: self._shield_work_files(v) for k, v in node.items()}
        if isinstance(node, list):
            return [self._shield_work_files(v) for v in node]
        if not isinstance(node, str) or not _in_work_dir(node):
            return node
        import shutil
        try:
            stat = os.stat(node)
        except OSError:
            return node
        # Ключ — вместе с размером и временем: под тем же именем в папке
        # работы позже может лежать другой файл, и старая копия соврала бы.
        key = f"{node}|{stat.st_size}|{stat.st_mtime_ns}"
        owned = self._undo_copies.get(key)
        if owned is None:
            owned = os.path.join(self._work_dir(),
                                 f"undo_{len(self._undo_copies)}_{os.path.basename(node)}")
            try:
                shutil.copy2(node, owned)
            except OSError as exc:
                logger.warning(f"копия для отмены не сделана: {exc}")
                return node
            self._undo_copies[key] = owned
        return owned

    def _edits_commit(self) -> None:
        """Шаг истории после правки. Снимок, равный текущему, не дублируем:
        часть правок пишет состояние дважды (положил текстуру и тут же
        пересобрал склейку), и Ctrl+Z на них был бы холостым."""
        snap = self._edit_snapshot()
        if self._edit_history and snap == self._edit_history[self._edit_pos]:
            return
        del self._edit_history[self._edit_pos + 1:]
        self._edit_history.append(snap)
        if len(self._edit_history) > self.EDIT_HISTORY_LIMIT:
            self._edit_history.pop(0)
        self._edit_pos = len(self._edit_history) - 1

    def edit_history(self) -> Dict[str, Any]:
        """Есть ли куда откатываться и что возвращать."""
        return {'undo': self._edit_pos > 0,
                'redo': 0 <= self._edit_pos < len(self._edit_history) - 1}

    def undo_edits(self, delta: int = -1, lang: str = 'ru') -> Dict[str, Any]:
        """
        Шаг по истории правок предмета: назад (delta < 0) или вперёд.

        Снимок ставится целиком поверх чистого состояния — так же, как
        возвращается работа с диска. Отдельно доделывается то, что снимок
        описывает, а в кадре само не появится: геометрия (своя ↔ игровая,
        другая подгонка), склейки частей (их файлы живут недолго — пересобрать
        дешевле, чем хранить) и грани неба.
        """
        from src.data.skyboxes import SKYBOX_MODE, SKY_PANO_KEY
        from src.services import mesh_import_service

        pos = self._edit_pos + int(delta)
        if pos < 0 or pos >= len(self._edit_history):
            return {'error': 'Отменять нечего' if delta < 0 else 'Возвращать нечего'}
        snap = self._edit_history[pos]
        p = self.preview
        mode = getattr(self, '_mode', '')

        with self._lock:
            was_smd, obj, was_fit = p.custom_smd_path, p.custom_obj_path, p.custom_fit
            was_pano = p.textures.skybox_pano()
            painted = set(p.part_textures) | set(p.part_colors)
            p.forget_user_edits()
            # Своя модель уходит — кадр возвращается к игровой: с её кадрами
            # команд, стилями и служебными материалами, как при выборе предмета.
            to_game = bool(was_smd) and not snap.get('custom_smd_path')
            if to_game:
                p.begin_game_model()
            p.apply_user_edits(snap)
            painted |= set(p.part_textures) | set(p.part_colors)
            # OBJ своей модели живёт один запуск — не терять, пока SMD тот же.
            if p.custom_smd_path == was_smd:
                p.custom_obj_path = obj
            self._edit_pos = pos

        paths = self.tf2_paths()
        if to_game:
            self.viewmodel.stop()
            if p.weapon_key and mode and 'error' not in paths:
                self.controller.load_game_model(
                    p.weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang)
                self.skins.detect(p.weapon_key, mode, paths['misc_vpk'], lang=lang)
        elif p.custom_smd_path != was_smd:
            self._restore_custom_model(lang)
        elif p.custom_source_path and p.custom_fit != was_fit:
            # SMD импортированной модели один на все подгонки: на диске лежит
            # последняя, а снимок вернул прежние числа — запечь их заново.
            try:
                smd = self._bake_imported_mesh(
                    p.custom_source_path, mesh_import_service.Fit.from_dict(p.custom_fit))
                with self._lock:
                    p.custom_smd_path = smd
            except mesh_import_service.MeshImportError as exc:
                logger.warning(f"подгонка после отмены не запеклась: {exc}")

        # Склейки частей: старые файлы уже могли уйти с диска (см.
        # `_drop_old_composites`), а без части — вернуть материалу основу.
        self.parts.recompose_slots(painted)

        if mode == SKYBOX_MODE:
            pano = p.textures.skybox_pano()
            if pano != was_pano:
                self._after_skybox_texture(SKY_PANO_KEY, pano)   # режет заново
            else:
                self._put_skybox()

        # Склейки пересобраны под новыми именами — снимок должен знать их,
        # иначе следующая же правка легла бы в историю дважды.
        with self._lock:
            self._edit_history[pos] = self._edit_snapshot()
        self._autosave()
        return {**self.view_state(), **self.edit_history()}

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
                'key': self._hat_key or self.preview.weapon_key or '',
                # Мультиклассовая шапка: у каждого класса своя модель, и без
                # них вернётся только та, что была показана.
                'per_class': dict(self._hat_models),
                # Показанный стиль и его модель: работа открывается на нём же,
                # а открытая на другом стиле — знает, чей снимок её правки.
                'style': self._hat_style,
                'model': self.preview.weapon_key or '',
                # Мод из VPK предметом каталога не опознаётся — только файлом.
                'mod': self._vpk_mod_path or ''}

    def _style_snapshots(self) -> Dict[int, Dict[str, Any]]:
        """Снимки НЕактивных стилей шапки — в работу вместе с правками."""
        return {i: snap for i, snap in self._hat_styles.items()
                if i != self._hat_style}

    def _restore_work(self, asked: bool = False) -> bool:
        """Возвращает сохранённые правки предмета."""
        from src.services import work_keeper
        with self._lock:
            key = self._work_key()
            restored = work_keeper.restore(self.preview, key, asked)
            if getattr(self, '_mode', '') == 'hat':
                restored = self._restore_hat_styles(key, asked, restored) or restored
        return restored

    def _restore_hat_styles(self, key: str, asked: bool, restored: bool) -> bool:
        """
        Возвращает снимки стилей шапки из работы.

        Правки работы принадлежат стилю, на котором её оставили. Открыли шапку
        на другом — они становятся его снимком, а показанному достаётся свой,
        если был: иначе текстура стиля «без усов» легла бы на модель с усами.
        """
        from src.services import work_keeper, work_store

        snaps = work_keeper.styles(key, asked)
        saved = work_store.item_of(key)
        left = int(saved.get('style') or 0)
        if restored and left != self._hat_style:
            models = (dict(saved.get('per_class') or {})
                      or ({'': saved['model']} if saved.get('model') else {}))
            snaps[left] = {'models': models, 'edits': self.preview.user_edits(),
                           'image_path': None}
            self.preview.forget_user_edits()
        mine = snaps.pop(self._hat_style, None)
        if mine:
            self.preview.apply_user_edits(mine.get('edits'))
        self._hat_styles = snaps
        return bool(mine or snaps)

    def forget_work(self, lang: str = 'ru') -> Dict[str, Any]:
        """Сбрасывает правки предмета — и в сеансе, и на диске."""
        from src.services import work_keeper
        with self._lock:
            had_custom = bool(self.preview.custom_smd_path)
            work_keeper.forget(self.preview, self._work_key())
            # Стили шапки — тот же предмет: оставить их правки значило бы
            # собрать в мод то, что человек только что попросил забыть.
            self._hat_styles = {}
        # Своя модель — тоже правка: состояние её забыло, а в кадре она
        # оставалась до перезагрузки предмета.
        if had_custom:
            self.drop_custom_model(lang)
        return self.view_state()

    def keep_work(self) -> Dict[str, Any]:
        """Сохраняет работу над предметом в библиотеку — по просьбе человека."""
        from src.services import work_keeper
        with self._lock:
            ok = work_keeper.keep(self.preview, self._work_key(),
                                  self._style_snapshots(), self._item_id())
        if not ok:
            return {'error': 'Сохранять нечего: правок нет'}
        return self.work_state()

    def restore_work(self, lang: str = 'ru') -> Dict[str, Any]:
        """Возвращает отложенную работу над открытым предметом."""
        # Замок берёт сам `_restore_work` — он же зовётся при открытии предмета.
        if not self._restore_work(asked=True):
            return {'error': 'Сохранённых правок у этого предмета нет'}
        # В работе была своя модель — в кадре должна стоять она, а не игровая.
        self._restore_custom_model(lang)
        # Вместе с правками вернулись и снимки соседних стилей — пометить.
        return {**self.view_state(), 'edited_styles': sorted(self._hat_styles)}

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
    # Части модели — src/app/parts_editor.py (self.parts)
    # ═══════════════════════════════════════════════════════════════════════ #

    def _decor_for_card(self, card: str):
        """Разобранная гирлянда, к которой относится карточка, — даже если
        сейчас показана другая или показ выключен: отмена и сборка гифок
        пересобирают склейки гирлянды и без неё в кадре."""
        from src.services import festive_decor
        kind, _material = festive_decor.parse_card(card)
        decor = self._decors.get(kind) if kind else None
        return decor if decor and decor.weapon_key == self._decor_key() else None


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
            'textures': self._painted(self.preview.visible_textures()),
            # Меши красятся ПОЛНЫМ набором: карточки отфильтрованы, а служебная
            # геометрия без текстуры осталась бы серой.
            'scene': self._painted(self.preview.scene_textures()),
            'paint': self._paint,
            'materials': self.preview.card_materials(),
            # Меши, которые носят ВЫБРАННУЮ карточку (маски маскировки: девять
            # текстур на одну голову). Пусто — обычное «карточка = материал».
            'card_mesh': self.preview.card_mesh(),
            'team': t.active_team,
            # Командной бывает и одна гирлянда: у обреза цвет команды не
            # меняется, а огоньки фестивайзера у синих синие.
            'has_teams': (self.preview.has_team_variant(is_hands) or t.force_team
                          or bool(self._decor_shown() and self._decor_shown().has_team)),
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
            # Подгонка есть только у импортированной модели (OBJ/GLB) и только
            # пока она в кадре (custom_obj_path): у SMD из Blender человек уже
            # всё выставил сам. Вернувшаяся с диска работа собирает OBJ заново
            # (`_restore_custom_model`), и подгонка у неё есть.
            'custom_fit': ((self.preview.custom_fit or {'scale': 1, 'rotate': [0, 0, 0],
                                                        'offset': [0, 0, 0]})
                           if self.preview.custom_source_path
                           and self.preview.custom_obj_path else None),
            'framerate': self.preview.team_framerate,
            'skins': self.preview.textures.skin_info,
            'active_skin': self.preview.textures.active_skin,
            # Вариантный стиль переопределяет базу выборочно: странице нужно
            # знать, что ещё можно в него добавить.
            'style': self.preview.active_style,
            'style_candidates': self.preview.style_candidates(),
            # Состояния модели (бодигруппы): переключатель под кадром.
            'bodygroups': self.bodygroups(),
            # Праздничная версия: какие гирлянды есть и какая включена.
            'festive_options': self.festive_options(),
            'festive': (self._decor_kind
                        if self._decor_kind and self._decor_for == self._decor_key()
                        else ''),
            # Свои текстуры гирлянды для вьювера ({меш: {команда: [кадры]}}):
            # её меши он красит своим слоем, мимо раздачи текстур предмета.
            # У мигающих лампочек своя картинка приходит кадрами мигания.
            'decor_textures': self._decor_textures_for_viewer(),
            # Подгонка показанной гирлянды и какие виды правлены (метка на
            # кнопке — правка гирлянды живёт и при выключенном показе).
            'decor_fit': self.preview.decor_fit.get(self._decor_kind),
            'decor_bends': self.preview.decor_bends.get(self._decor_kind) or [],
            'festive_edited': self._decor_edited_kinds(),
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

    def paints(self, lang: str = 'ru') -> List[Dict[str, Any]]:
        """Банки краски игры: [{key, name, red, blu}] с цветами #rrggbb."""
        from src.data import paints
        from src.data.hats_parser import parse_localization
        from src.data.weapon_model_index import get_items_game_path

        cache = getattr(self, '_paints_cache', None)
        if cache and cache[0] == lang:
            return cache[1]
        paths = self.tf2_paths()
        items = get_items_game_path(paths['root']) if 'error' not in paths else None
        if not items:
            return []
        loc = parse_localization(paths['root'], 'russian' if lang == 'ru' else 'english')
        rows = paints.parse(items.read_text(encoding='utf-8', errors='replace'), loc)
        hexed = [{**p, 'red': '#%02x%02x%02x' % p['red'], 'blu': '#%02x%02x%02x' % p['blu']}
                 for p in rows]
        self._paints_cache = (lang, hexed)
        return hexed

    def set_paint(self, key: str = '') -> Dict[str, Any]:
        """Выбирает краску для превью (пусто — без краски)."""
        self._paint = str(key or '')
        return self.view_state()

    def _painted(self, textures: Dict[str, str]) -> Dict[str, str]:
        """
        Те же текстуры, но покрашенные выбранной банкой — там, где игра красит.

        Красится материал, у которого в VMT есть маска (`$blendtintbybasealpha`):
        это знает картинка игрового оригинала, покрашенная при извлечении
        (vmt_tint.paintable). Своя текстура красится по СВОЕЙ альфе — так и в
        игре: маску рисует автор. Что не красится, отдаём как есть.
        """
        if not self._paint or not textures:
            return textures
        from src.services import vmt_tint
        from src.shared.constants import Team

        paint = next((p for p in self.paints() if p['key'] == self._paint), None)
        if paint is None:
            return textures
        t = self.preview.textures
        color = tuple(int((paint['blu'] if t.active_team == Team.BLU
                           else paint['red'])[i:i + 2], 16) for i in (1, 3, 5))
        out: Dict[str, str] = {}
        for mat, path in textures.items():
            stock = t.game_base(mat) or ''
            spec = vmt_tint.paintable(stock)
            if spec is None:
                out[mat] = path
                continue
            same = os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(stock))
            raw = vmt_tint.raw_of(stock) if same else path
            out[mat] = vmt_tint.painted(
                raw, vmt_tint.TintSpec(color, spec.over_base), self._work_dir()) or path
        return out

    def set_team(self, team: str) -> Dict[str, Any]:
        """Переключает команду и отдаёт новое состояние показа."""
        from src.shared.constants import Team

        wanted = Team.BLU if str(team).upper() == Team.BLU.upper() else Team.RED
        with self._lock:
            self.preview.textures.active_team = wanted
        return self.view_state()

    def bodygroups(self) -> List[Dict[str, Any]]:
        """
        Переключаемые состояния показанной модели: [{name, variants, chosen}].

        `$bodygroup` с двумя и более вариантами — переключатель, который игра
        дёргает сама (бутылка после крита разбивается, у кабера отлетает
        набалдашник). Превью показывает один вариант, и посмотреть остальные
        иначе нельзя. Только у оружия и шапок: у тел классов групп десятки, и
        основной меш там выбирается своими правилами.
        """
        from src.data.item_kinds import kind_of
        from src.services import decompile_cache
        from src.services.model_build_service import ModelBuildService

        key = self.preview.weapon_key
        mode = getattr(self, '_mode', '')
        kind = kind_of(mode)
        if (not key or not (kind.is_weapon or kind.is_hat)
                or self.preview.custom_smd_path or self.preview.custom_vpk_mode):
            return []
        qc = decompile_cache.find_cached_qc_for_weapon(key)
        if not qc:
            return []
        out = []
        for name, variants in ModelBuildService.extract_bodygroups(qc):
            if len(variants) < 2:
                continue
            out.append({
                'name': name,
                'chosen': int(self._bodygroups.get(name, 0)),
                'variants': [_variant_label(v, key) for v in variants],
            })
        return out

    def set_bodygroup(self, name: str = '', variant: int = 0,
                      lang: str = 'ru') -> Dict[str, Any]:
        """Показывает вариант бодигруппы: модель собирается заново тем же
        воркером (декомпиляция в кэше — это секунда), правки остаются."""
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths
        known = {g['name']: len(g['variants']) for g in self.bodygroups()}
        if name not in known or not 0 <= int(variant) < known[name]:
            return {'error': 'Такого состояния у модели нет'}
        if int(variant):
            self._bodygroups[name] = int(variant)
        else:
            self._bodygroups.pop(name, None)
        key, mode = self.preview.weapon_key, getattr(self, '_mode', '')
        self.viewmodel.stop()             # сцена в руках собрана под прежний вид
        self.controller.load_game_model(
            key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang,
            bodygroups=self._bodygroups)
        return self.view_state()

    def set_australium(self, active: bool) -> Dict[str, Any]:
        """Включает или гасит вариант Australium."""
        with self._lock:
            self.preview.textures.australium_active = bool(active)
        return self.view_state()

    def stop_preview(self) -> Dict[str, Any]:
        self.controller.stop()
        # Уход от предмета: досчитанная гирлянда легла бы на чужой кадр.
        self._forget_decor()
        return {'stopped': True}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Гирлянда поверх оружия
    # ═══════════════════════════════════════════════════════════════════════ #

    def _decor_key(self) -> str:
        """Модель, на которую вешается гирлянда; пусто — не оружие."""
        from src.data.item_kinds import kind_of

        p = self.preview
        if p.custom_vpk_mode:
            return p.custom_vpk_weapon or ''
        if not kind_of(getattr(self, '_mode', '')).is_weapon:
            return ''
        return p.weapon_key or ''

    def festive_options(self) -> List[str]:
        """Какие гирлянды игра вешает на показанное оружие (по порядку показа).

        Спрашивается при каждом состоянии показа, поэтому ответ держим до
        смены предмета: items_game уже разобран, но путь к игре читает конфиг.
        """
        from src.services import festive_decor

        key = self._decor_key()
        if self._decor_options[0] != key:
            paths = self.tf2_paths() if key else {'error': ''}
            found = ([] if 'error' in paths
                     else list(festive_decor.kinds(key, paths['root'])))
            self._decor_options = (key, found)
        return list(self._decor_options[1])

    def set_festive(self, kind: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Показывает праздничную версию оружия: гирлянду поверх модели.

        Гирлянда приезжает событием `festive_decor` и живёт во вьювере своим
        слоем; её материалы становятся карточками `deco:<вид>/<материал>`.
        Правки гирлянды (текстуры, части, подгонка) — часть работы и уходят в
        мод отдельной моделью (decor_build); выключенный показ их не
        отменяет и ничего не стоит. Первое включение — разбор модели
        гирлянды (около секунды), дальше из памяти.
        """
        kind = str(kind or '')
        key = self._decor_key()
        if kind and kind not in self.festive_options():
            return {'error': 'У этого предмета такой версии нет'}
        with self._decor_lock:
            self._decor_kind, self._decor_for = kind, key if kind else ''
            # Карточки прошлой гирлянды уходят сразу: новая ещё строится, а
            # выключенной в альбоме делать нечего. Правки её остаются в работе.
            self._show_decor_cards(None)
            if not kind:
                self._put('festive_decor', kind='')
        self._stop_decor()
        # Синюю команду могла включить одна гирлянда: у самого предмета её
        # нет, а у новой гирлянды может не быть (или она ещё строится) — кнопки
        # пропадут, и BLU залип бы невидимым, вместе с синими руками в кадре.
        from src.shared.constants import Team
        t = self.preview.textures
        if not (self.preview.has_team_variant(False) or t.force_team):
            t.active_team = Team.RED
        if not kind:
            return self.view_state()
        cached = self._decors.get(kind)
        if cached is not None and cached.weapon_key == key:
            self._show_decor_cards(cached)
            self._put('festive_decor', **cached.as_event())
            return self.view_state()

        paths = self.tf2_paths()
        if 'error' in paths:
            with self._decor_lock:
                self._decor_kind = self._decor_for = ''
            return paths
        from src.services.festive_decor import FestiveDecorWorker
        w = FestiveDecorWorker(key, kind, paths['misc_vpk'],
                               paths['textures_vpk'], paths['root'], lang=lang)
        w.progress.connect(lambda text: self._put('progress', text=text))
        w.ready.connect(self._on_decor)
        w.failed.connect(lambda message: self._on_decor_failed(key, kind, message))
        self._decor_worker = w
        w.start()
        return self.view_state()

    def _decor_textures_for_viewer(self) -> Dict[str, Dict[str, List[str]]]:
        """Свои текстуры гирлянды кадрами: мигают так же, как в игре.

        Кадры считаются один раз на картинку (ключ — путь и время файла) —
        состояние показа спрашивают после каждого действия.
        """
        from src.services import festive_decor

        cache = getattr(self, '_blink_cache', None)
        if cache is None:
            cache = self._blink_cache = {}
        out: Dict[str, Dict[str, List[str]]] = {}
        for card, teams in self.preview.textures.decor_uploads().items():
            decor = self._decor_for_card(card)
            stock = (decor.materials.get(card) or {}) if decor else {}
            out[card] = {}
            for team, path in teams.items():
                if not path:
                    out[card][team] = []
                    continue
                frames = stock.get(team) or []
                try:
                    key = (card, team, path, os.path.getmtime(path), tuple(frames))
                except OSError:
                    continue
                if key not in cache:
                    import tempfile
                    # Каждый мазок кистью — новая склейка, а с ней и новые
                    # кадры; старые больше не покажут.
                    if len(cache) > 64:
                        cache.clear()
                    target = tempfile.mkdtemp(prefix='tf2sg_blink_')
                    cache[key] = festive_decor.blink_like(
                        path, frames, target, card.replace(':', '_').replace('/', '_'))
                out[card][team] = cache[key]
        return out

    def _decor_edited_kinds(self) -> List[str]:
        """Виды гирлянд, у которых есть правки: текстуры или подгонка."""
        from src.services import festive_decor
        kinds = set(self.preview.decor_fit) | set(self.preview.decor_bends)
        kinds.update(festive_decor.parse_card(c)[0]
                     for c in self.preview.textures.decor_uploads())
        kinds.discard('')
        return sorted(kinds)

    def _decor_shown(self):
        """Готовая гирлянда, которая сейчас включена; None — выключена."""
        decor = self._decors.get(self._decor_kind) if self._decor_kind else None
        if decor is None or decor.weapon_key != self._decor_key():
            return None
        return decor

    def _on_decor(self, decor) -> None:
        # Пока строилась, человек мог выключить её, выбрать другую или уйти
        # к другому предмету.
        with self._decor_lock:
            if ((decor.weapon_key, decor.kind) != (self._decor_for, self._decor_kind)
                    or decor.weapon_key != self._decor_key()):
                return
            self._decors[decor.kind] = decor
            self._show_decor_cards(decor)
            self._put('festive_decor', **decor.as_event())

    def _on_decor_failed(self, key: str, kind: str, message: str) -> None:
        with self._decor_lock:
            if (key, kind) != (self._decor_for, self._decor_kind):
                return
            self._decor_kind = self._decor_for = ''
            self._put('festive_failed', kind=kind)
        logger.warning(f"гирлянда не собралась: {key}/{kind}: {message}")

    def _stop_decor(self) -> None:
        # Ждём воркер БЕЗ замка: его `_on_decor` сам берёт замок, и остановка
        # под ним простояла бы все три секунды.
        w, self._decor_worker = self._decor_worker, None
        if w is not None:
            w.stop(3000)

    def _forget_decor(self) -> None:
        """Новый предмет: гирлянда прошлого к нему не относится.

        Вьюверу говорим об этом сами: работа и мод из VPK открываются без
        сброса кадра, и оставшаяся гирлянда повисла бы на новой модели.
        """
        with self._decor_lock:
            if self._decor_kind:
                self._put('festive_decor', kind='')
            self._decor_kind = self._decor_for = ''
            self._decors = {}
            self._decor_options = ('', [])
            self._show_decor_cards(None)
        self._stop_decor()

    def _show_decor_cards(self, decor) -> None:
        """Карточки гирлянды в альбоме и её игровые кадры (None — убрать).

        Кадры кладутся в своё поле (`decor_stock`), а не в карты модели
        оружия: те переписываются каждой загрузкой модели — сменил состояние
        бутылки, и карточка гирлянды осталась бы пустой.
        """
        from src.shared.constants import Team
        with self._lock:
            p = self.preview
            if decor is None:
                p.decor_cards = []
                p.textures.decor_stock = {}
                return
            p.decor_cards = list(decor.materials)
            # Основа карточки — «все лампочки горят», а не первый кадр: в нём
            # один цвет погашен, и кисть по нему дала бы тёмный цвет.
            p.textures.decor_stock = {
                team: {c: (m.get('lit') or {}).get(team) or m[team][0]
                       for c, m in decor.materials.items() if m[team]}
                for team in (Team.RED, Team.BLU)}

    def set_decor_fit(self, fit: Optional[dict] = None) -> Dict[str, Any]:
        """Подгонка показанной гирлянды под свою модель.

        Вьювер двигает гирлянду сам и сразу; здесь — только числа. Их берут
        сборка (модель гирлянды пересобирается с запечённым сдвигом) и вид от
        первого лица. Единица не хранится: стоковая гирлянда — не правка.
        """
        from src.services import mesh_import_service

        kind = self._decor_kind
        if not kind or not self._decor_shown():
            return {'error': 'Сначала включите праздничную версию'}
        parsed = mesh_import_service.Fit.from_dict(fit)
        with self._lock:
            if parsed == mesh_import_service.Fit():
                self.preview.decor_fit.pop(kind, None)
            else:
                self.preview.decor_fit[kind] = parsed.to_dict()
        self._autosave()
        return {'fit': self.preview.decor_fit.get(kind)}

    def set_decor_bends(self, bends: Optional[List[dict]] = None) -> Dict[str, Any]:
        """Изгибы показанной гирлянды — списком целиком.

        Вьювер гнёт гирлянду сам и присылает итог после каждого движения;
        список целиком, а не «добавить»: так же приходят «выпрямить» (пусто)
        и откат, и порядок движений не зависит от порядка запросов.
        """
        kind = self._decor_kind
        if not kind or not self._decor_shown():
            return {'error': 'Сначала включите праздничную версию'}
        import math

        clean = []
        for bend in bends or ():
            try:
                c = [float(v) for v in bend['c']][:3]
                d = [float(v) for v in bend['d']][:3]
                r = float(bend['r'])
            except (KeyError, TypeError, ValueError):
                return {'error': 'Изгиб без точки, радиуса или сдвига'}
            # nan в SMD ломает компиляцию модели — такой изгиб не берём.
            if (len(c) == 3 and len(d) == 3 and r > 0
                    and all(map(math.isfinite, [*c, *d, r]))):
                clean.append({'c': c, 'r': r, 'd': d})
        with self._lock:
            if clean:
                self.preview.decor_bends[kind] = clean
            else:
                self.preview.decor_bends.pop(kind, None)
        self._autosave()
        return {'bends': self.preview.decor_bends.get(kind, [])}

    def _decor_scene_args(self, key: str) -> Dict[str, str]:
        """Гирлянда для сцены в руках: SMD с правками и имена её мешей."""
        from src.services import festive_decor
        decor = self._decor_shown()
        if not decor or decor.weapon_key != key:
            return {'decor_smd': '', 'decor_prefix': festive_decor.PREFIX}
        return {'decor_smd': festive_decor.shaped_smd(
                    decor.smd_path, self.preview.decor_fit.get(decor.kind),
                    self.preview.decor_bends.get(decor.kind),
                    festive_decor.weapon_pose(decor.weapon_key, decor.smd_path)),
                'decor_prefix': festive_decor.card(decor.kind, '')}

    def warm_up(self) -> None:
        """Греет индексы игровых архивов в фоне, пока страница рисуется.

        Каталог VPK (131 тысяча записей у tf2_textures + tf2_misc) разбирается
        полсекунды на архив, а нужен всем разделам разом: первый вход в
        звуки стоил 1,3 с, в частицы — 1,6 с, и три четверти этого — архивы.
        Кэш общий на потоки (см. vpk_cache), так что грев из фонового
        потока достаётся всем. Игры может не быть на месте — тогда тихо.
        """
        def warm() -> None:
            try:
                from src.services.tf2_paths import TF2Paths
                from src.services.vtf_preview_service import open_vpks

                paths = self.tf2_paths()
                if 'error' in paths:
                    return
                open_vpks([paths['misc_vpk'], paths['textures_vpk'],
                           *TF2Paths.resolve_hl2_vpks(paths['root']),
                           *self._sound_vpks(paths['tf_dir'])])
                # Банки краски — разбор items_game на секунду; первому
                # щелчку по «Краске» ждать его незачем.
                from src.config.app_config import AppConfig
                self.paints(AppConfig.load_config().get('language') or 'ru')
                # Индекс моделей из items_game: по нему у каждого оружия
                # спрашивают гирлянды, и первый выбор предмета не должен
                # ждать разбора восьми мегабайт.
                from src.data import viewmodel_anims
                viewmodel_anims.anim_index(paths['root'])
            except Exception as exc:                      # noqa: BLE001
                logger.debug(f"прогрев архивов не удался: {exc}")

        threading.Thread(target=warm, name='vpk-warm', daemon=True).start()

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
