"""
Сеанс приложения для фронта: состояние превью, контроллер и очередь событий

Зачем очередь. Воркеры работают в своих потоках и о представлении не знают -
контроллер применяет их сигналы к сеансу и эмитит своё событие. Доставить его
до страницы можно по-разному (SSE у dev-сервера, `evaluate_js` у pywebview),
и способ доставки не должен протекать в контроллер. Поэтому события просто
складываются в потокобезопасную очередь, а транспорт её разбирает

Один сеанс на процесс: приложение однооконное, и держать несколько
одновременных загрузок всё равно нельзя - их сигналы перемешались бы в одном
состоянии
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Dict, List, Optional

from src.app.build_editor import BuildEditor
from src.app.custom_model_editor import CustomModelEditor
from src.app.decor_editor import DecorEditor
from src.app.edit_history import EditHistory
from src.app.materials_editor import MaterialsEditor
from src.app.paintkit_editor import PaintkitEditor
from src.app.parts_editor import PartsEditor
from src.app.sheen_editor import SheenEditor
from src.app.particles_editor import ParticlesEditor
from src.app.sounds_editor import SoundsEditor
from src.app.tools_editor import ToolsEditor
from src.app.preview_controller import (
    Preview3DController, SkinDetectController, SkyboxController,
    ViewmodelController, VpkModController,
)
from src.domain.preview.session import PreviewSession
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Подписи вариантов бодигрупп по слову в имени SMD
_VARIANT_WORDS = (
    ('exploded', 'после взрыва'),
    ('broken', 'разбитая'),
    ('blank', 'без части'),
)


def _variant_label(smd_path: Optional[str], weapon_key: str) -> str:
    """Подпись варианта бодигруппы: знакомое слово из имени SMD, иначе то,
    что остаётся от имени без ключа оружия, нулевой обычно - «основной»"""
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


def _existing_path(path: Optional[str]) -> Optional[str]:
    """Путь, если файл на месте, иначе None"""
    return path if path and os.path.isfile(path) else None


def _viewmodel_rig() -> dict:
    """Камера вида от первого лица. Импорт отложен - модуль тянет сцену"""
    from src.services.viewmodel_scene import VIEWMODEL_RIG
    return dict(VIEWMODEL_RIG)


def _skybox_mode():
    """Режим превью «скайбокс» - импорт отложен, чтобы не тянуть данные зря"""
    from src.domain.preview.mode import PreviewMode
    return PreviewMode.SKYBOX

#: Сколько событий держим, если их никто не разбирает. Страница может быть
#: закрыта или перезагружаться - тогда очередь не должна расти бесконечно
MAX_PENDING = 500


class AppSession:
    """Состояние превью, контроллер загрузки и очередь событий для страницы"""

    def __init__(self) -> None:
        self.preview = PreviewSession()
        self.controller = Preview3DController(self.preview)
        self.skins = SkinDetectController(self.preview)
        self.viewmodel = ViewmodelController(self.preview)
        #: Сцена насмешки - тот же контроллер, но свой экземпляр: у него свой
        #: воркер, и вид от первого лица не должен его гасить
        self.taunt = ViewmodelController(self.preview)
        # Спец-режимы: крит и эффекты смерти показывают ту же анимированную
        # сцену, только вместо предмета в ней умирающий солдат
        self.death = ViewmodelController(self.preview)
        # Сцены не гасят загрузку превью (см. load_wear): доехавшая модель не
        # должна трогать поля подложки, пока сцена в кадре
        self.controller.scene_up = lambda: any(
            c.active for c in (self.viewmodel, self.taunt, self.death))
        #: Страница звуков: живёт отдельно от предмета
        self.sounds = SoundsEditor(self)
        #: Карты материала и правка VMT карточек
        self.materials = MaterialsEditor(self)
        self.skybox = SkyboxController(self.preview)
        self.vpk_mod = VpkModController(self.preview)
        #: Сборка мода и вопросы её воркера
        self.building = BuildEditor(self)
        #: Воркер экспорта UV-шаблона
        self._uv = None
        #: Инструменты: извлечение из игры, экспорт, объединение модов
        self.tools = ToolsEditor(self)
        #: Своя модель вместо игровой и её QC
        self.custom_model = CustomModelEditor(self)
        #: Показанный мод из VPK - его же собираем как источник
        self._vpk_mod_path: Optional[str] = None
        #: OBJ показанной модели - источник частей (см. mesh_parts_service)
        self._obj_path: str = ''
        #: История правок предмета (Ctrl+Z / Ctrl+Y): снимки `user_edits()`
        self.history = EditHistory(self._work_dir)
        #: Правки одного действия на нескольких карточках (War Paint) - один
        #: шаг истории: пока True, `_autosave` шаг не записывает
        self._edits_held = False
        #: Переключатель состояния модели в превью: {имя бодигруппы: вариант}.
        #: Пусто - как в игре по умолчанию (целая бутылка). Только показ: в
        #: мод уходят все варианты, игра переключает их сама
        self._bodygroups: Dict[str, int] = {}
        #: Что ждёт OBJ, который сейчас собирается (`_on_model_ready`): свой
        #: материал своего снаряда, склейки частей после отмены. Номера
        #: треугольников нового снаряда знает только новый OBJ
        self._after_model: List[Any] = []
        #: Гирлянда поверх оружия (праздничная версия / фестивайзер)
        self.decor = DecorEditor(self)
        #: Модели показанной шапки: {класс: mdl}. Пусто у обычной шапки - у неё
        #: одна модель на всех. Нужны сборке: мультиклассовая шапка собирается
        #: сразу под все выбранные классы
        self._hat_models: Dict[str, str] = {}
        #: Правки по стилям шапки: {индекс стиля: снимок}. Стиль - отдельная
        #: модель, и правки одного к другому не относятся, сборка собирает все
        #: изменённые стили в ОДИН мод, как в окне приложения
        self._hat_styles: Dict[int, Dict[str, Any]] = {}
        #: Краска для превью: ключ банки из `paints()` или пусто. Только показ -
        #: в мод краска не идёт, её накладывает игра
        self._paint = ''
        #: Ключ шапки из каталога (основная модель). Стили - та же шапка с
        #: другой моделью, и работа у них одна: ключ работы берётся отсюда,
        #: а не из модели показанного стиля
        self._hat_key = ''
        #: Индекс показанного стиля. Он же - «не собирать отдельно»: активный
        #: стиль уходит в мод основным путём
        self._hat_style: int = 0
        #: Воркер диагностики. Один на сеанс: два отчёта разом не нужны
        self._diag = None
        #: Блеск Killstreak: маска на модели и превью конструктора узора
        self.sheen = SheenEditor(self)
        #: War Paint показанного оружия
        self.paintkits = PaintkitEditor(self)
        #: Редактор частиц: открытый PCF, его история и сборка
        self.particles = ParticlesEditor(self)
        # У каждого подписчика СВОЯ очередь: с одной общей два открытых окна
        # делили бы события пополам вместо того, чтобы каждое получило все
        self._subscribers: "list[queue.Queue[dict]]" = []
        self._lock = threading.Lock()
        #: Смена предмета целиком - один вызов за раз. Сервер отвечает каждому
        #: запросу своим потоком, и два быстрых щелчка по каталогу шли через
        #: load_preview разом: оба гасили прошлый воркер, оба запускали свой,
        #: и в кадр приезжали обе модели, а сеанс помнил вперемешку
        self._load_lock = threading.Lock()
        #: Покраска частей модели: своя картинка или цвет на куске геометрии
        self.parts = PartsEditor(self)
        self._bind()
        self._edits_reset()

    # События

    def _bind(self) -> None:
        """Переводит события контроллера в записи очереди"""
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
        c.australium_ready.connect(
            lambda png, mat: self._put('australium', png=png, material=mat))
        c.render_hints.connect(lambda h: self._put('render_hints', hints=h or {}))
        # «Только карточки»: текстура игровой модели без её геометрии
        c.cards_ready.connect(lambda tex: self._put('cards_ready', texture=tex))
        c.failed.connect(self._fail)

        # Стили: приходят отдельным воркером после загрузки модели
        self.skins.detected.connect(lambda info: self._put('skins', info=info))

        # Вид от первого лица: своя сцена, собирается по частям
        v = self.viewmodel
        v.progress.connect(lambda text: self._put('progress', text=text))
        # Риг едет ВМЕСТЕ со сценой, а не ответом на запуск: ответ идёт по
        # HTTP, событие - по своему каналу, и сцена может прийти раньше, тогда
        # камера не встанет и кадр останется пустым
        v.ready.connect(
            lambda obj: self._put('fp_ready', obj=obj, rig=_viewmodel_rig()))
        v.animated.connect(
            lambda scene: self._put('fp_animated', scene=scene, rig=_viewmodel_rig()))
        v.materials.connect(lambda m: self._put('materials', materials=dict(m or {})))
        v.editable.connect(lambda n: self._put('fp_editable', names=list(n)))
        v.actions.connect(lambda n: self._put('fp_actions', actions=list(n)))
        v.clip.connect(lambda c: self._put('fp_clip', clip=c or {}))

        # Насмешка: та же анимированная сцена, но камера свободная - рига у
        # неё нет, персонажа смотрят со стороны
        t = self.taunt
        t.progress.connect(lambda text: self._put('progress', text=text))
        t.failed.connect(self._fail)
        t.animated.connect(lambda scene: self._put('taunt_animated', scene=scene))
        t.materials.connect(lambda m: self._put('materials', materials=dict(m or {})))
        t.editable.connect(lambda n: self._put('fp_editable', names=list(n)))
        t.classes.connect(lambda c: self._put('taunt_classes', classes=list(c)))
        # Сцена «На модели» у шапки идёт этим же контроллером: две сцены сразу
        # не бывают, а выход у них общий (leave_first_person)
        t.slots.connect(lambda info: self._put('wear_slots', **dict(info or {})))
        t.render_hints.connect(lambda h: self._put('render_hints', hints=h or {}))

        # Спец-режим: сцена приходит своим событием - странице надо знать, что
        # с ней делать (у крита билборд, у эффекта смерти текстура на всё тело)
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

        # Чужой мод из VPK: своя модель и свои карточки
        m = self.vpk_mod
        m.progress.connect(lambda text: self._put('progress', text=text))
        m.ready.connect(self._on_model_ready)
        m.animated.connect(
            lambda frames, fps: self._put('animated', frames=list(frames), fps=fps))
        m.cards.connect(lambda cards: self._put('mod_cards', cards=list(cards)))
        # Имена мешей меняют то, КУДА ложатся текстуры мода: состояние уже
        # обновлено контроллером, странице достаточно перечитать показ
        m.materials.connect(lambda names: self._put('materials', materials={}))
        m.skins.connect(lambda info: self._put('skins', info=info))
        # Мод опознан: страница откроет вид от первого лица - там он и
        # проверяется, в руках и в движении
        m.weapon.connect(
            lambda key, smd: self._put('mod_weapon', key=key, ready=bool(smd)))
        m.failed.connect(self._fail)

        # Скайбокс: шесть граней кубмапы.
        # Событие несёт РАЗРЕШЁННЫЕ грани (своя -> нарезка -> стоковая): и
        # стоковая загрузка, и нарезка панорамы приходят одним сигналом, а
        # что из них показать, решает домен
        self.skybox.ready.connect(lambda _faces: self._put_skybox())
        self.skybox.failed.connect(self._fail)

    def _on_model_ready(self, obj_path: str, texture: str) -> None:
        """
        Модель собрана. Вместе с путями отдаём центр и масштаб

        Считаем здесь, а не на странице: bounding box у Three.js сразу после
        загрузки ненадёжен, и приложение по той же причине считает его в Python
        (см. domain/preview/obj_bounds)
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
        # треугольников в нём те же, что вернёт вьювер по клику
        self._obj_path = obj_path
        # До события: страница по нему перечитывает показ, и материал своего
        # снаряда должен в него уже попасть
        pending, self._after_model = self._after_model, []
        for job in pending:
            try:
                job()
            except Exception:      # noqa: BLE001 - кадр важнее доделки
                logger.exception("доделка после загрузки модели не удалась")
        self._put('model_ready', obj=obj_path, texture=texture,
                  bounds={'cx': cx, 'cy': cy, 'cz': cz, 'scale': scale})

    def _fail(self, error: str) -> None:
        """
        Провал работы - с объяснением, а не одной технической строкой

        `error` приходит от воркера как есть: это может быть текст исключения,
        вывод crowbar или studiomdl, сообщение Windows. На каком он языке -
        неизвестно, и человеку он обычно ничего не говорит

        error_classifier разбирает его ПО СОДЕРЖИМОМУ и отдаёт понятный
        заголовок с объяснением на языке интерфейса. Тем самым работает и на
        английских сообщениях самих инструментов, и не требует, чтобы каждая
        строка в приложении была переведена

        Исходный текст отдаём тоже: он нужен в «технических деталях» - тому,
        кто полезет разбираться, и тому, кому это пришлют
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
        """Раздаёт событие всем подписчикам. Зовётся из потока воркера"""
        record = {'event': event, **payload}
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            if q.qsize() >= MAX_PENDING:
                # Подписчик не успевает или окно закрыто: старое уже неважно
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
            q.put(record)

    def subscribe(self) -> "queue.Queue[dict]":
        """Заводит очередь для одного подписчика (окна, вкладки)"""
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
        Ждёт события подписчика и отдаёт всё, что накопилось. Пустой список -
        таймаут: транспорту это сигнал, что соединение живо и можно ждать
        дальше
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

    # Действия

    def load_preview(self, mode: str, lang: str = 'ru',
                     model_key: Optional[str] = None,
                     per_class: Optional[Dict[str, str]] = None,
                     style: Optional[int] = None,
                     restore: bool = False,
                     hat: str = '') -> Dict[str, Any]:
        """
        Начинает загрузку 3D-превью предмета

        restore - вернуть сохранённую работу. По умолчанию НЕТ: каталог
        показывает предмет таким, какой он в игре. Свои работы открываются
        своим списком (`works`), иначе выбор «Обрез» молча давал бы чужой
        обрез, и вернуться к игровому было нечем

        hat - ключ шапки из каталога: у стилевой шапки модель у каждого стиля
        своя, а работа одна, и ключ работы берётся по шапке, а не по модели

        Возвращает не результат, а факт запуска: модель приезжает событиями.
        Ошибку конфигурации (нет TF2) отдаём сразу - гонять ради неё воркер
        незачем, а страница должна показать её на месте
        """
        with self._load_lock:
            return self._load_preview(mode, lang, model_key, per_class, style,
                                      restore, hat)

    def _load_preview(self, mode: str, lang: str,
                      model_key: Optional[str],
                      per_class: Optional[Dict[str, str]],
                      style: Optional[int], restore: bool,
                      hat: str) -> Dict[str, Any]:
        from src.domain.preview.model_key import model_key_for

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        # Имя режима воркеру не годится: у рук нужна модель предплечья, у тела
        # персонажа - путь к MDL. Правило целиком в домене
        #
        # У шапок модель задаётся выбором в каталоге (у каждой свой mdl_path),
        # поэтому ключ можно передать явно - вывести его из режима «hat»
        # невозможно.
        # Мультиклассовая шапка приходит шаблоном (…_%s.mdl): показать такой
        # путь нельзя, поэтому берём модель первого класса, а весь набор
        # запоминаем для сборки.
        # Смена стиля - до подмены моделей: снимок делается ПРОШЛЫМ набором
        self._remember_hat_style(style if mode == 'hat' else None,
                                 hat if mode == 'hat' else '')
        self._hat_models = dict(per_class or {}) if mode == 'hat' else {}
        if model_key and '%s' in model_key and self._hat_models:
            model_key = next(iter(self._hat_models.values()))

        weapon_key = model_key or model_key_for(mode)
        if not weapon_key:
            # Спрей и эффекты смерти - это ОДНА картинка без модели. Отсутствие
            # 3D здесь не ошибка: показывать надо пустой кадр под текстуру, а
            # не сообщение о поломке
            from src.data.weapons import SPECIAL_MODES
            if mode in set(SPECIAL_MODES):
                return self._load_texture_only(mode, restore, lang)
            return {'error': f'Для режима «{mode}» 3D-модели нет'}

        # Состояние сеанса чистит переход, а не контроллер: правила «что
        # забыть» живут в домене. Смена ПРЕДМЕТА забывает и пользовательские
        # текстуры - иначе скин одного оружия переезжает на другое
        with self._lock:
            self.preview.begin_item(weapon_key, mode)
            # begin_game_model гасит custom_vpk_mode - мод перестаёт быть
            # источником сборки, и его путь тоже надо забыть
            self.preview.begin_game_model()
            # И OBJ прошлого предмета: по нему считаются части, и оставленный
            # путь означал бы, что «разделить на части» разберёт ПРЕДЫДУЩУЮ
            # модель, пока новая ещё грузится. У скайбокса и спрея модели нет
            # вовсе, и там он висел бы до конца сеанса
            self._obj_path = ''
        self.vpk_mod.stop()
        self._vpk_mod_path = None
        self._bodygroups = {}          # состояние - свойство показанной модели
        self._after_model = []         # ждали модель прошлого предмета
        self.decor.forget()           # и гирлянда: у нового предмета своя
        # Собранные сцены принадлежали ПРОШЛОМУ предмету: и вид от первого
        # лица, и насмешка. Не погасив их, мы получили бы кадр чужого
        # предмета поверх нового - воркер досчитает и пришлёт свою сцену
        self.viewmodel.stop()
        self.taunt.stop()
        self.death.stop()

        # Правки возвращаем ДО запуска воркера: они лягут на карточки, как
        # только приедут материалы, и человек не увидит пустой альбом там, где
        # вчера была работа. Но ТОЛЬКО если работу и просили открыть: каталог
        # показывает предмет игровым
        self._mode = mode
        if restore:
            self._restore_work()
        # Память стилей свежее диска: с неё вернулись минуту назад, а автосохранение
        # человек мог и выключить
        with self._lock:
            self.preview.apply_user_edits(
                (self._hat_styles.get(self._hat_style) or {}).get('edits'))
        # Показанный стиль снимком не держим: его правда - живые правки, а
        # снимок остаётся от прошлого ухода и вернул бы старое поверх нового
        self._hat_styles.pop(self._hat_style, None)
        self._edits_reset()

        logger.info(f"load_preview: mode={mode!r} key={weapon_key!r}")
        # Работа с подменённой моделью открывается на НЕЙ: игровая геометрия
        # показала бы чужую текстуру не на том, для чего её рисовали
        if not self.custom_model.restore(lang):
            self.controller.load_game_model(
                weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang,
                bodygroups=self._bodygroups)
            # Стили ищем параллельно: QC после декомпиляции окажется в кэше,
            # так что ждать своей очереди воркеру почти не придётся. У оружия
            # `style` - строка скина, на которой открыть (Критокола у Бонка)
            self.skins.detect(weapon_key, mode, paths['misc_vpk'], lang=lang,
                              start_skin=0 if mode == 'hat' else int(style or 0))
        self._mode = mode
        self.decor.show_baked(lang)
        return {'started': True, 'mode': mode, 'weapon_key': weapon_key,
                # Какие стили уже правлены: страница ставит на них метку, иначе
                # про правку соседнего стиля вспоминают только в игре
                'edited_styles': sorted(self._hat_styles)}

    def _remember_hat_style(self, style: Optional[int], hat: str = '') -> None:
        """
        Запоминает правки уходящего стиля шапки

        ``style is None`` или другой ``hat`` - это НОВАЯ шапка, а не стиль
        номер ноль: правки её предшественницы к ней не относятся, и память
        чистится целиком
        """
        if style is None or hat != self._hat_key:
            self._hat_styles = {}
            self._hat_key = hat
            self._hat_style = int(style or 0)
            return
        # У одноклассовой шапки покласcовых моделей нет - стиль собирается той
        # моделью, что показана. Без этого правки таких стилей молча терялись
        models = dict(self._hat_models) or (
            {'': self.preview.weapon_key} if self.preview.weapon_key else {})
        if models and self.preview.has_user_edits():
            t = self.preview.textures
            main = t.stable_main()
            self._hat_styles[self._hat_style] = {
                'models': models,
                'edits': self.preview.user_edits(),
                # Главную текстуру считаем здесь: в снимке лежат имена
                # материалов, а какой из них главный, знает только живой сеанс
                'image_path': t.uploaded_for_mat(main) if main else None,
            }
        else:
            # «Убрать всё» на стиле: прежний снимок иначе ушёл бы в мод
            self._hat_styles.pop(self._hat_style, None)
        self._hat_style = int(style)

    def _hat_style_builds(self, classes=None) -> Optional[List[Dict[str, Any]]]:
        """Изменённые НЕактивные стили шапки - их сборка добавит в тот же мод

        Модели стиля - только выбранных классов: снятый класс не должен
        приехать в мод через соседний стиль
        """
        wanted = {str(c).lower() for c in (classes or [])}
        builds = []
        for index, snap in self._hat_styles.items():
            if index == self._hat_style:
                continue
            edits = snap.get('edits') or {}
            textures = edits.get('textures') or {}
            if not (snap.get('image_path') or edits.get('custom_smd_path')
                    or any(textures.values())):
                continue
            models = snap.get('models') or {}
            picked = [m for c, m in models.items() if str(c).lower() in wanted]
            builds.append({
                # Пустой выбор - «все», как у основной модели (_hat_models_for)
                'mdl_paths': picked or list(models.values()),
                'replace_smd': edits.get('custom_smd_path'),
                'keep_materials': bool(edits.get('custom_keep_materials')),
                'image_path': snap.get('image_path'),
                'textures': textures,
                # Материалы частей черновик не переносит - сборка скажет об этом
                'part_materials': bool(edits.get('part_materials')),
            })
        return builds or None

    def _forget_model(self) -> None:
        """Сцена без модели: резать больше нечего, путь к OBJ забываем"""
        self._obj_path = ''

    def _load_texture_only(self, mode: str, restore: bool = False,
                           lang: str = 'ru') -> Dict[str, Any]:
        """
        Режим без модели: спрей и эффекты смерти

        Показывать нечего, кроме самой картинки, поэтому вместо запуска воркера
        готовим один пустой кадр - в него человек и кладёт текстуру. Сборка
        такие режимы собирает из неё одной
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
            # заменяешь, было не видно. Кладём в неё игровую текстуру - ту
            # самую, что сейчас в игре
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
        # У крита и эффектов смерти сцена ЕСТЬ - персонаж: у крита текстура
        # висит билбордом над ним, у эффекта ложится на него самого. Модель
        # процедурная, если своя не положена в tools/Model.
        # `pending` говорит странице, что настоящая сцена уже собирается:
        # кубики-заглушку показывать не надо, иначе при каждом переключении
        # режима в кадре мелькает человечек из коробок
        from src.services.death_scene_worker import SEQUENCES as _DEATHS

        self._put('texture_only', mode=mode, pending=(mode in _DEATHS),
                  **self._scene_for(mode))
        # Кубики-заглушка остаются запасным кадром: настоящую сцену собирает
        # воркер, и это секунды на распаковку модели и анимаций
        self._start_death_scene(mode, lang)
        return {'texture_only': True, 'mode': mode}

    def _start_death_scene(self, mode: str, lang: str = 'ru') -> None:
        """Сцена смерти солдата под спец-режим - если игра на месте"""
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
        """Игровая текстура спец-режима как PNG. Считается один раз на режим"""
        if getattr(self, '_game_tex_mode', '') != mode:
            from src.services import special_scene_service as scene

            paths = self.tf2_paths()
            self._game_tex_mode = mode
            self._game_tex = ('' if 'error' in paths else scene.game_texture(
                mode, [paths['misc_vpk'], paths['textures_vpk']]))
        return self._game_tex

    def _scene_for(self, mode: str) -> Dict[str, Any]:
        """Из чего собрать сцену спец-режима: своя модель и текстура по умолчанию"""
        from src.data.weapons import VTF_ONLY_SPECIAL_MODES
        from src.services import special_scene_service as scene

        if mode == 'spray':
            return {'scene_kind': 'none'}

        model, model_texture = scene.find_scene_model('soldier')
        if model_texture.lower().endswith('.vtf'):
            model_texture = scene.vtf_to_png(model_texture)

        if mode in VTF_ONLY_SPECIAL_MODES:
            # Эффект смерти: пока своей текстуры нет, показываем игровую -
            # человек должен видеть то же, что и в игре
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
        """Собирает сцену «руки класса с оружием» для текущего предмета

        full - собрать целиком, даже если сцена уже в кадре. Нужен странице
        как отход назад: если дорожки лечь не смогли (сцены на экране почему-то
        нет), она просит полную сборку, и без этого флага мы бы снова ответили
        одними дорожками - по кругу
        """
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self, '_mode', '')
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        key = model_key_for(mode)
        # Чужой мод из VPK - тоже оружие, просто опознанное по путям внутри
        # файла. Показываем его тем же видом: скелет и анимации игровые, меш
        # из мода
        custom_smd, keep = '', False
        if not key and self.preview.custom_vpk_mode:
            key = self.preview.custom_vpk_weapon or ''
            custom_smd, keep = self.preview.custom_vpk_smd or '', True
        elif self.preview.custom_smd_path:
            # Своя модель (SMD либо импорт OBJ/GLB с запечённой подгонкой)
            # едет в руку тем же слиянием, что и в мод: одна кость - жёсткий
            # кусок на хвате, кости под игровыми именами - с анимацией частей
            custom_smd = self.preview.custom_smd_path
            keep = bool(self.preview.custom_keep_materials)
        if not key:
            return {'error': 'Вид от первого лица есть только у оружия'}

        # Гирлянда едет в руку костями пушки - как в игре: без флага
        # `model_display_flags` она видна и от первого лица
        decor = self.decor.scene_args(key)
        decor_smd = decor['decor_smd']

        # Та же сцена уже в кадре - меняем ОДНИ ДОРОЖКИ. Меш, скелет и
        # текстуры у одного оружия те же, и пересобирать их ради выбора
        # анимации значит каждый раз заново распаковывать текстуры
        if not full and self.viewmodel.shows(key, mode, decor_smd):
            self.viewmodel.load_clip(key, mode, paths['misc_vpk'],
                                     paths['textures_vpk'], paths['root'],
                                     action=action, lang=lang)
            return {'started': True, 'action': action, 'clip_only': True}

        # Превью предмета не гасим - см. load_wear: иначе вход в сцену до
        # конца загрузки оставлял альбом пустым.
        # Корень ИГРЫ, а не папка `tf`: по нему воркер читает items_game
        # (`viewmodel_anims.anim_info`) - оттуда и слот анимаций, и подмена
        # активностей, и пушка-носитель праздничной гирлянды. С `tf_dir`
        # items_game не находился, `anim_info` молча отдавал None, и слот
        # откатывался на нашу таблицу, а гирлянда висела в руке без пушки.
        # Панель приложения берёт тот же корень (`_tf2_root_for_fp`)
        self.viewmodel.load(key, mode, paths['misc_vpk'], paths['textures_vpk'],
                            paths['root'], action=action, lang=lang,
                            custom_smd=custom_smd, keep_materials=keep,
                            decor_smd=decor_smd,
                            decor_prefix=decor['decor_prefix'])
        return {'started': True, 'action': action, 'rig': _viewmodel_rig()}

    def leave_first_person(self) -> Dict[str, Any]:
        """
        Выход из вида от первого лица

        Убрать вьюмодель обязан тот же, кто её поставил: воркер сцены живёт до
        своей остановки, а подложка с текстурами рук - до своей очистки. Без
        этого руки оставались в кадре и после переключения вида: камера уже
        свободная, а оружие всё ещё держат. Обычную модель возвращает страница
        - у неё есть последний кадр превью, пересобирать его незачем
        """
        self.viewmodel.stop()
        # Сцена насмешки уходит тем же выходом: она собрана так же и так же
        # держит подложку с текстурами персонажа
        self.taunt.stop()
        with self._lock:
            self.preview.scene_extra_textures = {}
            self.preview.scene_item_materials = []
            # ...но у праздничного оружия подложка есть и у ОБЫЧНОЙ модели:
            # пушка-носитель под гирляндой. Поля под неё общие с видом от
            # первого лица, и без возврата текстура гирлянды ложилась на всю
            # модель разом - вьювер, увидев одну запись под служебным ключом,
            # кладёт её глобально
            self.controller.apply_scene_extra()
        return self.view_state()

    def load_taunt(self, tf2_class: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Собирает сцену насмешки для выбранного реквизита

        Реквизит опознаётся режимом (`taunt_<ключ>`): в нём и лежит ключ
        таблицы моделей. Класс задаёт человек - одну и ту же насмешку играют
        до девяти классов, и модель реквизита у каждого своя
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

        # Превью реквизита не гасим - см. load_wear
        self.viewmodel.stop()
        self.taunt.load_taunt(prop_key, item['mdl_path'], paths['misc_vpk'],
                              paths['textures_vpk'], paths['root'],
                              tf2_class=tf2_class, lang=lang)
        return {'started': True, 'prop': prop_key, 'tf2_class': tf2_class}

    def load_wear(self, tf2_class: str = '', slot: str = '',
                  lang: str = 'ru') -> Dict[str, Any]:
        """
        Сцена «На персонаже»: предмет на классе в игровой стойке

        Класс - из тех, кто носит предмет, слот - какое стоковое оружие у него в
        руках (от него зависит и стойка). Пусто - первый класс и первый слот.
        Оружие собирает `weapon_wear` (держат в руках или надевают)
        """
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths
        if getattr(self, '_mode', '') != 'hat':
            from src.app import weapon_wear
            args = weapon_wear.scene_args(self, paths['root'])
            if 'error' in args:
                return args
            self.viewmodel.stop()
            self.taunt.load_wear(misc_vpk=paths['misc_vpk'], textures_vpk=paths['textures_vpk'],
                                 tf2_root=paths['root'], tf2_class=tf2_class, slot=slot,
                                 lang=lang, **args)
            return {'started': True}
        item = self._hat_catalog_item(paths['root'], lang)
        # У мультиклассовой шапки модели по классам уже известны, у
        # одномодельной классы есть только в каталоге, модель у всех одна
        models = dict(self._hat_models) or (
            {c: self.preview.weapon_key for c in item.classes} if item else {})
        if not models:
            return {'error': 'Не удалось понять, какой класс носит эту шапку'}

        # Превью шапки НЕ гасим: смена стиля на этой сцене зовёт load_preview и
        # сразу load_wear, и остановка обрывала загрузку нового стиля - альбом
        # оставался пустым. Сцене оно не мешает: model_ready страница в сцене
        # не показывает, а состояние превью и подложка сцены - разные поля
        self.viewmodel.stop()
        self.taunt.load_wear(models, paths['misc_vpk'], paths['textures_vpk'],
                             paths['root'], tf2_class=tf2_class, slot=slot,
                             lang=lang, hidden_bodygroups=self._hat_hides(item))
        return {'started': True}

    def _hat_catalog_item(self, tf2_root: str, lang: str):
        """
        Строка каталога показанной шапки (HatItem) либо None

        Ищем по ключу шапки (модель из каталога), а если его нет - по любой её
        модели: класса или стиля. Каталог держит разбор в памяти, повторный
        проход дешёвый
        """
        from src.data.hats_parser import parse_hats

        def norm(p) -> str:
            return str(p or '').replace('\\', '/').lower()

        keys = {norm(self._hat_key), norm(self.preview.weapon_key)} - {''}
        for h in parse_hats(tf2_root, lang):
            own = {norm(h.mdl_path), *map(norm, (h.per_class_models or {}).values())}
            for st in h.styles or ():
                own.update(map(norm, (st.get('per_class_models') or {}).values()))
            if keys & own:
                return h
        return None

    def _hat_hides(self, item) -> Dict[str, int]:
        """
        Что шапка прячет у персонажа: сам предмет и его показанный стиль

        В игре это делает надетый предмет (`player_bodygroups`, у стиля -
        `additional_hidden_bodygroups`): шапка на голову солдата убирает его
        каску. Без этого каска в сцене торчала сквозь шапку
        """
        if item is None:
            return {}
        hides = dict(getattr(item, 'hidden_bodygroups', None) or {})
        styles = item.styles or []
        index = self._hat_style
        if isinstance(index, int) and 0 <= index < len(styles):
            hides.update(styles[index].get('hidden_bodygroups') or {})
        return hides

    # Звуки - src/app/sounds_editor.py (self.sounds)

    # Скайбокс, текстура и сборка

    def _sky_names_to_build(self) -> Optional[list]:
        """Какие имена небес перекрывает мод: выбранное либо ВСЕ стоковые

        «Все карты» - каждая карта зовёт своё небо по имени в worldspawn, и
        одно небо на всю игру означает VMT под каждым именем (VTF при этом
        одни, см. build_skybox_vpk). Список - у установленной игры
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
        """Что показывать по граням: своя -> нарезка панорамы -> стоковая"""
        from src.data.skyboxes import SKY_FACES

        out: Dict[str, str] = {}
        for face in SKY_FACES:
            got = self.preview.textures.resolve_skybox_face(face)
            if got:
                out[face] = got
        return out

    def _put_skybox(self) -> None:
        """Сообщает странице состояние неба целиком

        Панорама едет отдельным полем: у неё своя карточка в ленте, и без неё
        человеку некуда положить фото 360° (ключ `SKY_PANO_KEY`, гранью он не
        является и в сборку идёт как `equirect`)
        """
        from src.data.skyboxes import SKY_PANO_KEY

        self._put('skybox', faces=self._skybox_faces(),
                  pano=self.preview.textures.skybox_pano() or '',
                  pano_key=SKY_PANO_KEY)

    def _after_skybox_texture(self, material: str, path) -> None:
        """Реакция на подмену грани или панорамы в режиме неба

        Панораму надо НАРЕЗАТЬ: шесть граней из фото 360° делает воркер, и до
        этого превью её не видит вовсе.
        Подмену одной грани достаточно показать: она уже в домене
        """
        from src.data.skyboxes import SKY_FACES, SKY_PANO_KEY

        if material == SKY_PANO_KEY:
            if path:
                self.skybox.split(str(path))    # ready -> _put_skybox
                return
            self.skybox.stop_split()
            with self._lock:
                self.preview.textures.skybox_split_faces = {}
        elif material not in SKY_FACES:
            return
        self._put_skybox()

    def load_skybox(self, sky_name: str) -> Dict[str, Any]:
        """Готовит грани стокового неба для показа кубмапой"""
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        from src.data.skyboxes import SKY_ALL_MAPS_KEY, SKY_PREVIEW_DEFAULT

        self._mode = 'skybox'
        # Какое небо перекрывать - знает сборка: без имени мод собрался бы
        # пустым (см. validate_skybox_request). «Все карты» - ключ, а не
        # небо: сборка развернёт его в полный список, а превью показывает
        # одно стоковое небо - своего у пункта нет
        self._sky_name = sky_name
        with self._lock:
            self.preview.mode.enter(_skybox_mode())
            self._forget_model()
        self._edits_reset()
        # Небеса лежат и в hl2/ - оттуда же и грани, иначе половина списка
        # показывалась бы пустой (см. TF2Paths.skybox_vpks)
        from src.services.tf2_paths import TF2Paths
        shown = SKY_PREVIEW_DEFAULT if sky_name == SKY_ALL_MAPS_KEY else sky_name
        self.skybox.load(shown, TF2Paths.skybox_vpks(paths['root']))
        return {'started': True, 'sky': sky_name}

    def set_texture(self, material: str, path: Optional[str]) -> Dict[str, Any]:
        """
        Кладёт пользовательскую текстуру на материал (или снимает, path=None)

        Куда именно она попадёт - решает домен: активный стиль пишется в свои
        переопределения, нейтральный материал дублируется в обе команды, а под
        «сделать командным» дублирование запрещено. Эти правила накопились по
        багам, повторять их здесь нельзя
        """
        # Покрашенная карточка: текстура становится основой под мазками, а не
        # заменой склейки (иначе мазки числились бы, а на модели их не было)
        under = self.parts.set_base(material, path)
        if under is None:
            with self._lock:
                self.preview.textures.set_texture(material, path)
        elif 'error' in under:
            return under
        self._autosave()
        # Небо - не материалы модели, а грани куба: страница показывает их
        # своим событием, и после подмены его надо повторить
        from src.data.skyboxes import SKYBOX_MODE
        if getattr(self, '_mode', '') == SKYBOX_MODE:
            self._after_skybox_texture(material, path)
        return self.view_state()

    # Сборка - src/app/build_editor.py (self.building)
    # Гирлянда поверх оружия - src/app/decor_editor.py (self.decor)

    # Частицы - src/app/particles_editor.py (self.particles)

    def export_uv(self, size: int = 1024) -> Dict[str, Any]:
        """
        Рисует UV-шаблон модели в папку экспорта

        Отдельная операция, а не часть превью: модель декомпилируется
        (cache-aware) и по её развёртке рисуются швы. Нужна, чтобы глазами
        сверить, куда какой кусок текстуры садится
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
        # Путь готового PNG воркер кладёт в output_path - берём его на finished
        w.finished.connect(
            lambda ok, msg: self._put('uv_ready', ok=bool(ok), message=msg,
                                      path=w.output_path or '',
                                      # У каждого материала своя развёртка -
                                      # и свой файл
                                      paths=list(w.output_paths)))
        w.error.connect(lambda msg: self._put('uv_ready', ok=False,
                                              message=msg, path=''))
        self._uv = w
        w.start()
        return {'started': True}

    def normal_preview(self, screen: Optional[Dict[str, Any]] = None,
                       global_options: Optional[Dict[str, Any]] = None,
                       editing: Optional[str] = None) -> Dict[str, Any]:
        """
        Карта нормалей главной текстуры для 3D-превью - та же, что соберётся
        в мод (normal_map.make), только не больше 1024 px

        Настройки - как у сборки главного материала: свои настройки карточки
        (texture_overrides) важнее общих. ``screen`` - опции на экране,
        ``global_options`` - общие (при правке другой карточки на экране её
        настройки, а не общие), ``editing`` - какую карточку правят (None -
        никакую). ``{'off': True}`` - рельефа в сборке не будет

        ``stock`` в ответе - есть ли у материала родная нормаль игры: только
        тогда странице есть что предлагать галкой «Заменить родной рельеф»
        """
        import hashlib

        import numpy as np
        from PIL import Image

        from src.services import normal_map
        from src.shared.constants import Team

        main_key = self._card_key('')
        if editing is not None and self._card_key(editing) == main_key:
            options = dict(screen or {})
        else:
            own = self.preview.texture_overrides.get(main_key) or {}
            options = dict(own.get('options') if own.get('options') is not None
                           else (global_options if global_options is not None else screen) or {})
        if not options.get('normal'):
            return {'off': True}

        t = self.preview.textures
        material = t.stable_main()
        # Нормаль строится из RED: BLU в сборке получает её копию
        src = None
        if material:
            red = t.textures.get(Team.RED, {}).get(material)
            src = red if red and os.path.isfile(red) else t.game_base(material, Team.RED)
        if not src or not os.path.isfile(src):
            return {'error': 'Нет текстуры, из которой строить рельеф'}
        stock = self._stock_normal_for(material)
        settings = normal_map.NormalSettings.from_options(options)
        stamp = repr((src, os.path.getmtime(src), settings, stock is not None))
        out = os.path.join(self._work_dir(), 'normal_prev_'
                           + hashlib.sha1(stamp.encode('utf-8')).hexdigest()[:12] + '.png')
        if not os.path.isfile(out):
            with Image.open(src) as img:
                img = img.convert('RGB')          # у гифки - первый кадр
                if max(img.size) > 1024:
                    img.thumbnail((1024, 1024), Image.LANCZOS)
                rgb = np.asarray(img)
            Image.fromarray(normal_map.make(rgb, settings, stock), 'RGBA').save(out)
        # Прошлые картинки превью не нужны: ползунок иначе оставлял по файлу
        # в 2-3 МБ на каждое положение
        prev = self.__dict__.get('_normal_prev_file')
        if prev and prev != out:
            try:
                os.remove(prev)
            except OSError:
                pass
        self._normal_prev_file = out
        # Меш назван по материалу OBJ (у одноматериальной модели карточка -
        # служебный ключ): по этому имени вьювер и кладёт нормаль, не задевая
        # руки и тело в сценах
        found = self.parts._parts_model(material)
        mesh = found[1] if isinstance(found, tuple) else material
        return {'png': out, 'material': mesh or '', 'stock': stock is not None}

    def _stock_normal_for(self, material: str):
        """Родная нормаль материала (RGBA) или None; кэш на VMT"""
        from src.services import normal_map

        # У своей геометрии развёртка другая: родная нормаль легла бы мимо
        if self.preview.custom_smd_path:
            return None
        vmt = self.materials.open_vmt(material)
        paths = self.tf2_paths()
        if 'content' not in vmt or 'error' in paths:
            return None
        cache = self.__dict__.setdefault('_stock_normal_cache', {})
        key = vmt['content']
        if key not in cache:
            cache.clear()                         # одна модель за раз
            cache[key] = normal_map.stock_normal(
                key, [paths['textures_vpk'], paths['misc_vpk']])
        return cache[key]

    def class_icons(self) -> Dict[str, Any]:
        """Значки классов из игры для окон выбора классов"""
        from src.services.class_icons import class_icons
        paths = self.tf2_paths()
        if 'error' in paths:
            return {'icons': {}}
        return {'icons': class_icons(paths['textures_vpk'], paths['misc_vpk'])}

    # War Paint

    # Блеск Killstreak - src/app/sheen_editor.py (self.sheen)


    def _shown_mdl(self) -> str:
        """Файл модели показанного оружия - по нему War Paint и ищутся"""
        from src.data.weapons import WEAPON_MDL_PATHS
        key = self._shown_weapon()
        return WEAPON_MDL_PATHS.get(key) or f'{key}.mdl'

    # War Paint - src/app/paintkit_editor.py (self.paintkits)


    def load_vpk_mod(self, path: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Показывает чужой мод из VPK: его модель и его текстуры

        Предмет при этом не меняется: мод накладывается поверх текущего выбора,
        и его путь уходит в сборку как источник (``custom_vpk_source_path``) -
        так же, как в приложении
        """
        import os

        if not path or not os.path.isfile(path):
            return {'error': 'VPK-файл не найден'}

        paths = self.tf2_paths()
        if 'error' in paths:
            return paths

        self.controller.stop()
        self.decor.forget()
        self._vpk_mod_path = path
        # Показанный мод - это и есть предмет: приложение так же переключает
        # категорию на «Кастомный мод» и ставит режим 'custom'
        self._mode = 'custom'
        # Мод опознаётся файлом в библиотеке - по нему и находится работа
        self.preview.forget_user_edits()
        self._restore_work()
        self._edits_reset()
        self.vpk_mod.load(path, paths['misc_vpk'], paths['textures_vpk'], lang=lang)
        logger.info(f"мод из VPK: {path}")
        return {'started': True, 'path': path}

    # Диагностика мода

    @staticmethod
    def _report_to_dict(report) -> Dict[str, Any]:
        """
        Отчёт диагностики в простых значениях

        Enum и dataclass наружу не отдаём: транспорт их не сериализует, а
        представление про них знать не должно. Порядок берём у отчёта
        (``sorted``) - ошибки выше предупреждений
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
        Проверяет собранный мод и отдаёт находки событием ``diagnostics``

        Проверять можно любой VPK, не обязательно свой: диагностика читает
        файл, а не состояние сеанса
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

    # Своя модель и её QC

    # Своя модель и её QC - src/app/custom_model_editor.py (self.custom_model)


    # Работа над предметом: сохранение правок между запусками

    def _work_key(self) -> str:
        """Ключ работы по текущему предмету (правило - в work_keeper)"""
        from src.services import work_keeper
        return work_keeper.key_for(getattr(self, '_mode', ''),
                                   self._hat_key or self.preview.weapon_key,
                                   self._vpk_mod_path or '')

    @staticmethod
    def _autosave_on() -> bool:
        from src.services import work_keeper
        return work_keeper.is_enabled()

    def _autosave(self, step: bool = True) -> None:
        """Пишет правки предмета. Зовётся после КАЖДОГО изменения - потому
        здесь же и шаг истории отмены: второй список точек «после правки»
        разошёлся бы с первым

        ``step=False`` - запомнить, но не шагом отмены: настройка кисти на
        модели ничего не меняет, и Ctrl+Z по ней был бы холостым. Пока
        ``_edits_held`` - правки одного действия на нескольких карточках
        (War Paint) копятся в один шаг, его делает последний вызов"""
        from src.services import work_keeper
        if step and not getattr(self, '_edits_held', False):
            self._edits_commit()
        elif not self.preview.has_user_edits():
            # Одна настройка кисти - не работа. Пустое сохранение УДАЛЯЕТ
            # черновик (work_keeper.save), и сдвинутый ползунок на только что
            # открытом предмете стирал его работу, которую даже не вернули
            return
        work_keeper.save(self.preview, self._work_key(),
                         self._style_snapshots(), self._item_id())

    # История правок предмета: Ctrl+Z / Ctrl+Y

    # Сам стек снимков - src/app/edit_history.py (self.history), здесь -
    # снимок из состояния превью и то, как он ложится обратно на предмет

    def _edits_reset(self) -> None:
        """Точка отсчёта истории: предмет открыт (с работой или без)"""
        self.history.reset(self._edit_snapshot())

    def _edit_snapshot(self) -> Dict[str, Any]:
        """Снимок правок - то же, что уходит на диск, своей копией"""
        return self.history.snapshot(self.preview.user_edits())

    def _edits_commit(self) -> None:
        """Шаг истории после правки (повтор текущего снимка не пишется)"""
        self.history.commit(self._edit_snapshot())

    def edit_history(self) -> Dict[str, Any]:
        """Есть ли куда откатываться и что возвращать"""
        return self.history.state()

    def undo_edits(self, delta: int = -1, lang: str = 'ru') -> Dict[str, Any]:
        """
        Шаг по истории правок предмета: назад (delta < 0) или вперёд

        Снимок ставится целиком поверх чистого состояния - так же, как
        возвращается работа с диска. Отдельно доделывается то, что снимок
        описывает, а в кадре само не появится: геометрия (своя ↔ игровая,
        другая подгонка), склейки частей (их файлы живут недолго - пересобрать
        дешевле, чем хранить) и грани неба
        """
        from src.data.skyboxes import SKYBOX_MODE, SKY_PANO_KEY
        from src.services import mesh_import_service

        pos = self.history.pos + int(delta)
        snap = self.history.at(pos)
        if snap is None:
            return {'error': 'Отменять нечего' if delta < 0 else 'Возвращать нечего'}
        p = self.preview
        mode = getattr(self, '_mode', '')

        with self._lock:
            was_smd, obj, was_fit = p.custom_smd_path, p.custom_obj_path, p.custom_fit
            was_pano = p.textures.skybox_pano()
            was_decor = dict(p.decor_models)
            was_parts = dict(p.part_models)
            painted = set(p.part_textures) | set(p.part_colors)
            p.forget_user_edits()
            # Своя модель уходит - кадр возвращается к игровой: с её кадрами
            # команд, стилями и служебными материалами, как при выборе предмета
            to_game = bool(was_smd) and not snap.get('custom_smd_path')
            if to_game:
                p.begin_game_model()
            p.apply_user_edits(snap)
            painted |= set(p.part_textures) | set(p.part_colors)
            # OBJ своей модели живёт один запуск - не терять, пока SMD тот же
            if p.custom_smd_path == was_smd:
                p.custom_obj_path = obj
            self.history.move_to(pos)

        paths = self.tf2_paths()
        if to_game:
            self.viewmodel.stop()
            if p.weapon_key and mode and 'error' not in paths:
                self.controller.load_game_model(
                    p.weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang)
                self.skins.detect(p.weapon_key, mode, paths['misc_vpk'], lang=lang)
        elif p.custom_smd_path != was_smd:
            self.custom_model.restore(lang)
        elif p.custom_source_path and p.custom_fit != was_fit:
            # SMD импортированной модели один на все подгонки: на диске лежит
            # последняя, а снимок вернул прежние числа - запечь их заново
            try:
                smd = self.custom_model.bake_imported_mesh(
                    p.custom_source_path, mesh_import_service.Fit.from_dict(p.custom_fit))
                with self._lock:
                    p.custom_smd_path = smd
            except mesh_import_service.MeshImportError as exc:
                logger.warning(f"подгонка после отмены не запеклась: {exc}")

        # Своя модель снаряда сменилась - кадр игровой модели заново (своя
        # модель оружия и переход к игровой собирают его сами, ниже)
        shell_moved = p.part_models != was_parts and not to_game and not p.custom_smd_path
        # Склейки частей: старые файлы уже могли уйти с диска (см.
        # `_drop_old_composites`), а без части - вернуть материалу основу.
        # Сменился снаряд - мазки снимка лежат на треугольниках ЕГО снаряда, а
        # в кадре пока прежний: собираем, когда приедет модель
        if shell_moved:
            self._after_model.append(lambda: self._recompose_after_undo(painted, pos))
        else:
            self.parts.recompose_slots(painted)
        self.decor.reshow(was_decor, lang)
        if shell_moved:
            self._reload_item(lang)

        if mode == SKYBOX_MODE:
            pano = p.textures.skybox_pano()
            if pano != was_pano:
                self._after_skybox_texture(SKY_PANO_KEY, pano)   # режет заново
            else:
                self._put_skybox()

        # Склейки пересобраны под новыми именами - снимок должен знать их,
        # иначе следующая же правка легла бы в историю дважды
        with self._lock:
            self.history.refresh(pos, self._edit_snapshot())
        self._autosave()
        return {**self.view_state(), **self.edit_history()}

    def _recompose_after_undo(self, slots, pos: int) -> None:
        """Склейки частей шага `pos` по приехавшей модели его снаряда, снимок
        этого шага узнаёт их новые имена (как в `undo_edits`)"""
        self.parts.recompose_slots(slots)
        with self._lock:
            if self.history.pos == pos:
                self.history.refresh(pos, self._edit_snapshot())
        self._autosave(step=False)

    def _item_id(self) -> Dict[str, Any]:
        """
        Чем опознать предмет работы, кроме имени её папки

        Имя папки - слаг: у шапки от `models/player/items/…/hat.mdl` в нём
        остаётся `models_player_items_…_hat.mdl`. По такому ключу не найти ни
        имени в каталоге, ни иконки, ни самой модели - работа по шапке
        показывалась строкой из подчёркиваний и не открывалась. Поэтому в
        работу кладём то, из чего она открывается
        """
        return {'mode': getattr(self, '_mode', ''),
                'key': self._hat_key or self.preview.weapon_key or '',
                # Мультиклассовая шапка: у каждого класса своя модель, и без
                # них вернётся только та, что была показана
                'per_class': dict(self._hat_models),
                # Показанный стиль и его модель: работа открывается на нём же,
                # а открытая на другом стиле - знает, чей снимок её правки
                'style': self._hat_style,
                'model': self.preview.weapon_key or '',
                # Мод из VPK предметом каталога не опознаётся - только файлом
                'mod': self._vpk_mod_path or ''}

    def _style_snapshots(self) -> Dict[int, Dict[str, Any]]:
        """Снимки НЕактивных стилей шапки - в работу вместе с правками"""
        return {i: snap for i, snap in self._hat_styles.items()
                if i != self._hat_style}

    def _restore_work(self, asked: bool = False) -> bool:
        """Возвращает сохранённые правки предмета"""
        from src.services import work_keeper
        with self._lock:
            key = self._work_key()
            restored = work_keeper.restore(self.preview, key, asked)
            if getattr(self, '_mode', '') == 'hat':
                restored = self._restore_hat_styles(key, asked, restored) or restored
        return restored

    def _restore_hat_styles(self, key: str, asked: bool, restored: bool) -> bool:
        """
        Возвращает снимки стилей шапки из работы

        Правки работы принадлежат стилю, на котором её оставили. Открыли шапку
        на другом - они становятся его снимком, а показанному достаётся свой,
        если был: иначе текстура стиля «без усов» легла бы на модель с усами
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
        """Сбрасывает правки предмета - и в сеансе, и на диске"""
        from src.services import work_keeper
        with self._lock:
            had_custom = bool(self.preview.custom_smd_path)
            was_decor = dict(self.preview.decor_models)
            work_keeper.forget(self.preview, self._work_key())
            # Стили шапки - тот же предмет: оставить их правки значило бы
            # собрать в мод то, что человек только что попросил забыть
            self._hat_styles = {}
        # Своя модель - тоже правка: состояние её забыло, а в кадре она
        # оставалась до перезагрузки предмета
        if had_custom:
            self.custom_model.drop_custom_model(lang)
        self.decor.reshow(was_decor, lang)
        return self.view_state()

    def keep_work(self) -> Dict[str, Any]:
        """Сохраняет работу над предметом в библиотеку - по просьбе человека"""
        from src.services import work_keeper
        with self._lock:
            ok = work_keeper.keep(self.preview, self._work_key(),
                                  self._style_snapshots(), self._item_id())
        if not ok:
            return {'error': 'Сохранять нечего: правок нет'}
        return self.work_state()

    def restore_work(self, lang: str = 'ru') -> Dict[str, Any]:
        """Возвращает отложенную работу над открытым предметом"""
        # Замок берёт сам `_restore_work` - он же зовётся при открытии предмета
        was_decor = dict(self.preview.decor_models)
        if not self._restore_work(asked=True):
            return {'error': 'Сохранённых правок у этого предмета нет'}
        # В работе была своя модель - в кадре должна стоять она, а не игровая
        self.custom_model.restore(lang)
        self.decor.reshow(was_decor, lang)
        # Вместе с правками вернулись и снимки соседних стилей - пометить
        return {**self.view_state(), 'edited_styles': sorted(self._hat_styles)}

    def forget_drafts(self, keys: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Удаляет черновики автосохранения. Сохранённые работы не трогает

        ``keys`` - что именно удалять; None означает «все черновики», а пустой
        список - ничего: «снял все отметки» не должно означать «удали всё».
        Ключ, за которым лежит СОХРАНЁННАЯ работа, отбрасывается: страница
        присылает список, а удалить чужое по опечатке в нём нельзя

        Черновик открытого сейчас предмета сбрасывается ещё и в сеансе -
        иначе автосохранение перепишет его на следующей же правке
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
        # `reset` - знак странице перечитать вид: правки открытого предмета
        # ушли вместе с его черновиком
        return {'removed': removed, 'reset': reset}

    def work_state(self) -> Dict[str, Any]:
        """Есть ли сейчас правки, лежит ли что-то на диске и как оно попало"""
        from src.services import work_store
        key = self._work_key()
        return {'has_edits': self.preview.has_user_edits(),
                'autosave': self._autosave_on(),
                # Черновик автосохранения тоже «есть на диске»: его можно и
                # вернуть, и забыть - просто в библиотеке его не показывают
                'has_saved': bool(key) and work_store.holds_edits(key),
                'kept': work_store.is_kept(key)}

    # Карточка материала. Карты и правка VMT - src/app/materials_editor.py
    # (self.materials)

    def _card_key(self, material: str = '') -> str:
        """
        Материал, к которому относится правка карточки

        Пустая строка - ГЛАВНЫЙ материал, и это не «не выбрано»: сборка
        сопоставляет её с texture_filename сама, а страница его имени не знает

        Служебный ключ одноматериальной модели сюда попасть не должен: под ним
        правка легла бы в хранилище именем `__single__`, которого сборка не
        ищет, - то есть молча пропала бы
        """
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        material = (material or '').strip()
        if not material:
            names = self.preview.textures.material_names
            material = names[0] if names else ''
        return '' if material == SINGLE_TEX_KEY else material

    # Части модели - src/app/parts_editor.py (self.parts)


    def _tint_risks(self, paths) -> Dict[str, Any]:
        """
        {путь: (краска, маска оригинала)} - свои картинки без альфы на
        материалах, которые игра красит по альфе текстуры

        Краску знает игровой оригинал материала: при извлечении он покрашен
        (vmt_tint.apply_to_png), рядом лежит краска и исходник с маской.
        Команда своя у каждой картинки: у RED и BLU разные цвета в VMT
        """
        from src.services import vmt_tint

        t = self.preview.textures
        owners = {p: (mat, team) for team, mats in t.textures.items()
                  for mat, p in mats.items() if p}
        out: Dict[str, Any] = {}
        for path in paths:
            if not path or path in out or path not in owners:
                continue
            stock = t.game_base(*owners[path])
            spec = vmt_tint.paintable(stock)
            if spec is None or spec.is_neutral or not vmt_tint.lacks_alpha(path):
                continue
            out[path] = (spec, vmt_tint.raw_of(stock))
        return out

    def _fix_tint(self, risks: Dict[str, Any], how: str) -> Dict[str, str]:
        """
        Копии картинок с маской краски: `none` - пустая (игра не красит, как в
        превью), `mask` - маска игрового оригинала (красит те же места, что у
        стокового предмета). Оригинал человека не трогаем
        """
        from src.services import vmt_tint

        out: Dict[str, str] = {}
        for path, (_spec, raw) in risks.items():
            stem = os.path.splitext(os.path.basename(path))[0]
            dst = os.path.join(self._work_dir(), f'{stem}_tint_{how}.png')
            mask = raw if how == 'mask' and os.path.isfile(raw) else None
            if vmt_tint.with_mask(path, dst, mask):
                out[path] = dst
        return out

    def _work_dir(self) -> str:
        """Своя папка сеанса для склеек. Живёт до перезапуска, как и превью

        Убирается на выходе: склейки весят по 2-3 МБ, держим четыре, и каждый
        запуск оставлял в %TEMP% свою папку `tf2sg_parts_*` навсегда. К этому
        моменту нужное уже скопировано в work/ автосохранением
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


    # Инструменты: извлечение оригиналов и объединение модов

    @staticmethod
    def _bypass_method() -> str:
        """Способ обхода sv_pure из настроек, неизвестный - умолчание"""
        from src.config.app_config import AppConfig
        from src.shared.constants import SVPURE_BYPASS_DEFAULT, SVPURE_BYPASS_PREFIXES
        method = AppConfig.load_config().get('sv_pure_bypass')
        return method if method in SVPURE_BYPASS_PREFIXES else SVPURE_BYPASS_DEFAULT

    @staticmethod
    def _export_settings() -> tuple:
        """Куда и в каком формате писать результат инструментов"""
        from src.config.app_config import AppConfig
        from src.shared.paths import export_dir
        return (str(export_dir()),
                AppConfig.load_config().get('export_image_format') or 'PNG')

    # Инструменты - src/app/tools_editor.py (self.tools)


    def set_skin(self, index: int) -> Dict[str, Any]:
        """Переключает вариантный стиль. Что показывать - пересчитает домен"""
        with self._lock:
            self.preview.textures.active_skin = int(index)
        return self.view_state()

    def view_state(self) -> Dict[str, Any]:
        """
        Что показывать прямо сейчас: текстуры, команда, доступные варианты

        Одно место вместо россыпи запросов - страница спрашивает его после
        любого изменения (смена команды, вариант, стиль) и применяет ответ
        целиком. Правила разрешения при этом остаются в домене
        """
        from src.data.player_hands import HAND_MODE_KEYS

        t = self.preview.textures
        mode = (self.preview.current_object or ('', '', ''))[0]
        is_hands = bool(mode) and mode in HAND_MODE_KEYS

        return {
            'textures': self._painted(self.preview.visible_textures()),
            # Меши красятся ПОЛНЫМ набором: карточки отфильтрованы, а служебная
            # геометрия без текстуры осталась бы серой
            'scene': self._painted(self.preview.scene_textures()),
            # Куда в этой сцене ложится каждая карточка: {карточка: [меши]}.
            # Страница кладёт по нему временные картинки (предпросмотр War
            # Paint) в ту же раздачу, что и настоящие
            'card_scene': {c: self.preview.scene_names(c)
                           for c in self.preview.textures.material_names},
            'paint': self._paint,
            'materials': self.preview.card_materials(),
            # Меши, которые носят ВЫБРАННУЮ карточку (маски маскировки: девять
            # текстур на одну голову). Пусто - обычное «карточка = материал»
            'card_mesh': self.preview.card_mesh(),
            'team': t.active_team,
            # Командной бывает и одна гирлянда: у обреза цвет команды не
            # меняется, а огоньки фестивайзера у синих синие
            'has_teams': (self.preview.has_team_variant(is_hands) or t.force_team
                          or bool(self.decor.shown() and self.decor.shown().has_team)),
            'has_australium': bool(t.australium_frame),
            'australium_active': t.australium_active,
            # «Прочее» - не для рук и не для мода из VPK: там карточки строятся
            # не из материалов модели
            'has_misc': bool(self.preview.misc_materials
                             and not self.preview.custom_vpk_mode
                             and not is_hands),
            'misc_mode': self.preview.misc_mode,
            'force_team': t.force_team,
            'can_force_team': self.preview.can_force_team(),
            # Правка QC имеет смысл только у СВОЕЙ готовой модели: у замены
            # геометрии сборка собирает QC сама под игровые материалы
            'custom_keep': bool(self.preview.custom_smd_path
                                and self.preview.custom_keep_materials),
            # Своя геометрия в кадре - можно предложить вернуть игровую
            'has_custom': bool(self.preview.custom_smd_path),
            # Геометрия не стоковая - своя модель или модель из мода VPK:
            # гирлянду на ней есть смысл подгонять
            'custom_geometry': self._custom_geometry(),
            # Подгонка есть только у импортированной модели (OBJ/GLB) и только
            # пока она в кадре (custom_obj_path): у SMD из Blender человек уже
            # всё выставил сам. Вернувшаяся с диска работа собирает OBJ заново
            # (`custom_model.restore`), и подгонка у неё есть
            'custom_fit': ((self.preview.custom_fit or {'scale': 1, 'rotate': [0, 0, 0],
                                                        'offset': [0, 0, 0]})
                           if self.preview.custom_source_path
                           and self.preview.custom_obj_path else None),
            'framerate': self.preview.team_framerate,
            'skins': ({**self.preview.textures.skin_info, 'styles': self.preview.styles()}
                      if self.preview.textures.skin_info else None),
            'active_skin': self.preview.textures.active_skin,
            # Вариантный стиль переопределяет базу выборочно: странице нужно
            # знать, что ещё можно в него добавить
            'style': self.preview.active_style,
            'style_candidates': self.preview.style_candidates(),
            # Состояния модели (бодигруппы): переключатель под кадром
            'bodygroups': self.bodygroups(),
            # Праздничная версия: какие гирлянды есть и какая включена
            'festive_options': self.decor.festive_options(),
            'festive': (self.decor.kind
                        if self.decor.kind and self.decor.shown_for == self._shown_weapon()
                        else ''),
            # Свои текстуры гирлянды для вьювера ({меш: {команда: [кадры]}}):
            # её меши он красит своим слоем, мимо раздачи текстур предмета.
            # У мигающих лампочек своя картинка приходит кадрами мигания
            'decor_textures': self.decor.textures_for_viewer(),
            # Подгонка показанной гирлянды и какие виды правлены (метка на
            # кнопке - правка гирлянды живёт и при выключенном показе)
            'decor_fit': self.preview.decor_fit.get(self.decor.kind),
            'decor_bends': self.preview.decor_bends.get(self.decor.kind) or [],
            'festive_edited': self.decor.edited_kinds(),
            'festive_baked': self.decor.baked(),
            'can_bake_festive': not self.preview.custom_vpk_mode,
            # Виды гирлянд со своей моделью: «Убрать свою модель» спросит, что
            'decor_models': sorted(self.preview.decor_models),
            # Есть ли что делить на части. Кнопка иначе висела бы доступной у
            # скайбокса, спрея и просто до того, как модель приехала, - и
            # обещала бы действие, которого нет
            'can_split': bool(self._obj_path and os.path.isfile(self._obj_path)),
            # Части, ставшие своими материалами: какие треугольники каких мешей
            # вьювер рисует отдельно (src/services/part_materials.py)
            'part_materials': self.parts.part_material_view(),
        }

    def toggle_misc(self, on: Optional[bool] = None) -> Dict[str, Any]:
        """Показывает служебные материалы («Прочее») или возвращает обычные"""
        with self._lock:
            self.preview.toggle_misc(on)
        return self.view_state()

    def force_team(self) -> Dict[str, Any]:
        """Включает «сделать командным» - сборка синтезирует BLU-строку"""
        with self._lock:
            self.preview.enable_force_team()
        self._autosave()
        return self.view_state()

    def paints(self, lang: str = 'ru') -> List[Dict[str, Any]]:
        """Банки краски игры: [{key, name, red, blu}] с цветами #rrggbb"""
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
        from src.data.items_game_kv import ItemsGame
        game = ItemsGame.load(items)
        if game is None:
            return []
        loc = parse_localization(paths['root'], 'russian' if lang == 'ru' else 'english')
        rows = paints.parse(game, loc)
        hexed = [{**p, 'red': '#%02x%02x%02x' % p['red'], 'blu': '#%02x%02x%02x' % p['blu']}
                 for p in rows]
        self._paints_cache = (lang, hexed)
        return hexed

    def set_paint(self, key: str = '') -> Dict[str, Any]:
        """Выбирает краску для превью (пусто - без краски)"""
        self._paint = str(key or '')
        return self.view_state()

    def _painted(self, textures: Dict[str, str]) -> Dict[str, str]:
        """
        Те же текстуры, но покрашенные выбранной банкой - там, где игра красит

        Красится материал, у которого в VMT есть маска (`$blendtintbybasealpha`):
        это знает картинка игрового оригинала, покрашенная при извлечении
        (vmt_tint.paintable). Своя текстура красится по СВОЕЙ альфе - так и в
        игре: маску рисует автор. Что не красится, отдаём как есть
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
        # С материалами частей сцена зовёт исходный меш по имени из OBJ
        # (`_name_for_scene`), а его игровой оригинал лежит под ключом карточки
        cards = {base: entries[0].get('card') or base
                 for base, entries in self.preview.part_materials.items() if entries}
        # Одноматериальный предмет в сцене на персонаже назван настоящим именем
        # меша, а его оригинал лежит под служебным ключом: без этой связки
        # шапка на персонаже не перекрашивалась (Big Elfin Deal)
        from src.domain.preview.texture_state import SINGLE_TEX_KEY
        if t.material_names == [SINGLE_TEX_KEY]:
            cards.update({m: SINGLE_TEX_KEY for m in self.preview.scene_item_materials})
        out: Dict[str, str] = {}
        for mat, path in textures.items():
            stock = t.game_base(cards.get(mat, mat)) or ''
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
        """Переключает команду и отдаёт новое состояние показа"""
        from src.shared.constants import Team

        wanted = Team.BLU if str(team).upper() == Team.BLU.upper() else Team.RED
        with self._lock:
            self.preview.textures.active_team = wanted
        return self.view_state()

    def bodygroups(self) -> List[Dict[str, Any]]:
        """
        Переключаемые состояния показанной модели: [{name, variants, chosen}]

        `$bodygroup` с двумя и более вариантами - переключатель, который игра
        дёргает сама (бутылка после крита разбивается, у кабера отлетает
        набалдашник). Превью показывает один вариант, и посмотреть остальные
        иначе нельзя. Только у оружия и шапок: у тел классов групп десятки, и
        основной меш там выбирается своими правилами
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
        own = {part.lower() for part in self.preview.part_models}
        out = []
        for name, variants in ModelBuildService.extract_bodygroups(qc):
            if len(variants) < 2:
                continue
            # Снаряд в оружии (граната, ракета, стрела): в кадре он виден,
            # пока его не скрыли, - его правят, своя модель меняет его
            shown = ModelBuildService.projectile_variant(name, variants)
            part = (os.path.splitext(os.path.basename(variants[shown]))[0].lower()
                    if shown is not None else '')
            out.append({
                'name': name,
                'chosen': int(self._bodygroups.get(name, shown or 0)),
                'variants': ([('виден' if v else 'скрыт') for v in variants]
                             if shown is not None
                             else [_variant_label(v, key) for v in variants]),
                'default': shown or 0,
                'projectile': shown is not None,
                'custom': bool(part and part in own),
            })
        return out

    def set_bodygroup(self, name: str = '', variant: int = 0,
                      lang: str = 'ru') -> Dict[str, Any]:
        """Показывает вариант бодигруппы: модель собирается заново тем же
        воркером (декомпиляция в кэше - это секунда), правки остаются"""
        known = {g['name']: g for g in self.bodygroups()}
        if name not in known or not 0 <= int(variant) < len(known[name]['variants']):
            return {'error': 'Такого состояния у модели нет'}
        # Записан только выбор, отличный от показа по умолчанию: у снаряда
        # это «скрыт», у остальных - любой вариант, кроме нулевого
        if int(variant) != known[name]['default']:
            self._bodygroups[name] = int(variant)
        else:
            self._bodygroups.pop(name, None)
        return self._reload_item(lang)

    def _reload_item(self, lang: str = 'ru') -> Dict[str, Any]:
        """Игровая модель предмета заново, с выбранными состояниями и своими
        деталями: декомпиляция в кэше - секунда, правки остаются"""
        paths = self.tf2_paths()
        if 'error' in paths:
            return paths
        key, mode = self.preview.weapon_key, getattr(self, '_mode', '')
        self.viewmodel.stop()             # сцена в руках собрана под прежний вид
        self.controller.load_game_model(
            key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang,
            bodygroups=self._bodygroups)
        return self.view_state()

    # Снаряд в оружии: своя модель

    def _projectile_smd(self, group: str) -> Optional[str]:
        """SMD снаряда группы `group` показанной игровой модели (или None)"""
        from src.services import decompile_cache
        from src.services.model_build_service import ModelBuildService

        key = self.preview.weapon_key
        qc = decompile_cache.find_cached_qc_for_weapon(key) if key else None
        for name, variants in (ModelBuildService.extract_bodygroups(qc) if qc else ()):
            shown = ModelBuildService.projectile_variant(name, variants)
            if name == group and shown is not None:
                return variants[shown]
        return None

    def load_part_model(self, group: str = '', path: str = '',
                        lang: str = 'ru') -> Dict[str, Any]:
        """
        Своя модель снаряда, заряженного в оружие (граната Loch-n-Load,
        ракета сигнальной, стрела лука)

        Снаряд - деталь той же модели, на своей кости: игра двигает её рукой
        при перезарядке. Скелет и материал остаются игровыми, треугольники -
        свои (with_part_models в превью, _apply_model_replacement в сборке).
        SMD встаёт как его выставили в редакторе, по развёртке оружия. OBJ/GLB
        встают по габаритам игрового снаряда (fit_into), а развёртка у них
        своя - им свой материал с картинкой из файла, когда приедет модель
        (PartsEditor.own_projectile). Покраска прежнего снаряда уходит
        """
        from src.services import mesh_import_service

        if self.preview.custom_smd_path or self.preview.custom_vpk_mode:
            return {'error': 'Снаряд меняется на игровой модели оружия'}
        part = self._projectile_smd(group)
        if not part or not os.path.isfile(part):
            return {'error': 'У этого предмета нет такого снаряда'}
        if not path or not os.path.isfile(path):
            return {'error': 'Файл модели не найден'}
        import tempfile
        try:
            # Своя папка на загрузку: шаг отмены держит путь прежней модели
            smd, texture, simplified = _part_smd(
                path, part, tempfile.mkdtemp(prefix='part_', dir=self._work_dir()))
        except mesh_import_service.MeshImportError as exc:
            return {'error': str(exc)}
        base = os.path.splitext(os.path.basename(part))[0]
        self.parts.forget_projectile(part)
        with self._lock:
            self.preview.part_models[base] = smd
            self._bodygroups.pop(group, None)      # своя модель - сразу в кадр
            if not path.lower().endswith('.smd'):
                self._after_model.append(
                    lambda: self._own_projectile(group, base, smd, texture, lang))
        self._autosave()
        logger.info(f"своя модель снаряда {group}: {smd}")
        # Что приложение сделало само - странице для строки состояния
        done = {'simplified': simplified, 'texture': bool(texture)}
        return {**self._reload_item(lang), **{k: v for k, v in done.items() if v}}

    def drop_part_model(self, group: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """Возвращает снаряду группы `group` игровую модель (и его покраску -
        к нулю: она была по треугольникам своей)"""
        part = self._projectile_smd(group)
        base = os.path.splitext(os.path.basename(part))[0].lower() if part else ''
        if not any(k.lower() == base for k in self.preview.part_models):
            return self.view_state()
        self.parts.forget_projectile(part)
        with self._lock:
            for k in [k for k in self.preview.part_models if k.lower() == base]:
                self.preview.part_models.pop(k)
        self._autosave()
        return self._reload_item(lang)

    def _own_projectile(self, group: str, base: str, smd: str,
                        texture: Optional[str], lang: str) -> None:
        """Приехал OBJ со своим снарядом из OBJ/GLB: свой материал ему (тем же
        шагом отмены, что и загрузка) и VMT без карт развёртки оружия"""
        if self.preview.part_models.get(base) != smd:
            return                  # снаряд уже другой (отмена, новая загрузка)
        if group in self._bodygroups:
            # Снаряд скрыли, пока ехала модель: его треугольников в кадре нет.
            # Материал - когда его покажут снова
            self._after_model.append(
                lambda: self._own_projectile(group, base, smd, texture, lang))
            return
        name = self.parts.own_projectile(texture)
        if not name:
            return
        self._strip_uv_maps(name, lang)
        with self._lock:
            # ponytail: обычно это шаг загрузки. Если пока ехал кадр, успели
            # что-то поправить, - шаг той правки, а снимок загрузки остаётся без
            # материала, и Ctrl+Z к нему вернёт снаряд без него. Чинить -
            # дописывать материал во все снимки от загрузки до текущего
            if len(self.history):
                self.history.refresh(self.history.pos, self._edit_snapshot())
        self._autosave(step=False)

    def _strip_uv_maps(self, name: str, lang: str) -> None:
        """Убирает из VMT материала `name` текстуры, лежащие по развёртке
        исходного (карта нормалей Пушки и Детонатора): у своей модели снаряда
        развёртка другая, и они легли бы на неё пятнами"""
        from src.services import part_materials as pm

        got = self.materials.open_vmt(name, lang)
        if 'error' in got:
            return
        clean = pm.without_uv_maps(got['content'])
        if clean != got['content']:
            saved = self.materials.save_vmt(name, clean, got.get('original') or got['content'], lang)
            if 'error' in saved:
                logger.warning(f"VMT своего снаряда {name} не поправлен: {saved['error']}")

    def _shape_changed(self) -> bool:
        """Выбран вариант, меняющий саму модель (разбитая бутылка), а не
        только снаряд в оружии: он идёт в конце материала, и номера
        треугольников оружия от него не зависят"""
        if not self._bodygroups:
            return False
        shells = {g['name'] for g in self.bodygroups() if g['projectile']}
        return any(name not in shells for name in self._bodygroups)

    def set_australium(self, active: bool) -> Dict[str, Any]:
        """Включает или гасит вариант Australium"""
        with self._lock:
            self.preview.textures.australium_active = bool(active)
        return self.view_state()

    def stop_preview(self) -> Dict[str, Any]:
        self.controller.stop()
        # Уход от предмета: досчитанная гирлянда легла бы на чужой кадр
        self.decor.forget()
        return {'stopped': True}

    # Гирлянда поверх оружия

    def _shown_weapon(self) -> str:
        """Игровое оружие в кадре (у мода из VPK - то, что он заменяет);
        пусто - не оружие. По нему ищутся гирлянды и War Paint"""
        from src.data.item_kinds import kind_of

        p = self.preview
        if p.custom_vpk_mode:
            return p.custom_vpk_weapon or ''
        if not kind_of(getattr(self, '_mode', '')).is_weapon:
            return ''
        return p.weapon_key or ''

    def _custom_geometry(self) -> bool:
        """В кадре не стоковая геометрия: своя модель или MDL из мода"""
        p = self.preview
        return bool(p.custom_smd_path or (p.custom_vpk_mode and p.custom_vpk_own_model))


    def warm_up(self) -> None:
        """Греет индексы игровых архивов в фоне, пока страница рисуется

        Каталог VPK (131 тысяча записей у tf2_textures + tf2_misc) разбирается
        полсекунды на архив, а нужен всем разделам разом: первый вход в
        звуки стоил 1,3 с, в частицы - 1,6 с, и три четверти этого - архивы.
        Кэш общий на потоки (см. vpk_cache), так что грев из фонового
        потока достаётся всем. Игры может не быть на месте - тогда тихо
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
                           *self.sounds.sound_vpks(paths['tf_dir'])])
                # Банки краски - разбор items_game на секунду, первому
                # щелчку по «Краске» ждать его незачем
                from src.config.app_config import AppConfig
                self.paints(AppConfig.load_config().get('language') or 'ru')
                # Индекс моделей из items_game: по нему у каждого оружия
                # спрашивают гирлянды, и первый выбор предмета не должен
                # ждать разбора восьми мегабайт
                from src.data import viewmodel_anims
                viewmodel_anims.anim_index(paths['root'])
            except Exception as exc:                      # noqa: BLE001
                logger.debug(f"прогрев архивов не удался: {exc}")

        threading.Thread(target=warm, name='vpk-warm', daemon=True).start()

    @staticmethod
    def tf2_paths() -> Dict[str, Any]:
        """Пути к игровым VPK или понятная ошибка, если игра не найдена"""
        from src.config.app_config import AppConfig

        root = (AppConfig.load_config().get('tf2_game_folder') or '').strip()
        if not root:
            return {'error': 'Папка Team Fortress 2 не задана в настройках'}
        try:
            from src.services.tf2_paths import TF2Paths
            _, misc_vpk, tf_dir = TF2Paths.resolve(root)
            textures_vpk = TF2Paths.resolve_textures_vpk(root)
        except Exception as exc:  # noqa: BLE001 - путь задаёт пользователь
            return {'error': f'Не удалось разобрать папку игры: {exc}'}
        if not misc_vpk:
            return {'error': 'В папке игры не найден tf2_misc_dir.vpk'}
        # Crowbar - вторая обязательная половина: без него модель не
        # разобрать, а узнать об этом сейчас можно только по ошибке сборки
        crowbar_ok, _ = TF2Paths.check_crowbar()
        # Насмешек с реквизитом в игре вчетверо больше, чем в выверенной
        # руками таблице, и список их лежит в items_game. Здесь первое место,
        # где путь к игре уже известен, повторные вызовы - сразу выход
        from src.data import taunt_catalog
        taunt_catalog.merge(root)
        return {'root': root, 'tf_dir': tf_dir,
                'misc_vpk': misc_vpk, 'textures_vpk': textures_vpk or '',
                'crowbar': bool(crowbar_ok)}


#: Единственный сеанс процесса. Создаётся лениво: импорт модуля не должен
#: тянуть за собой воркеры и конфиг
_session: Optional[AppSession] = None


def session() -> AppSession:
    global _session
    if _session is None:
        _session = AppSession()
    return _session


def _part_smd(path: str, part_smd: str, out_dir: str):
    """(SMD в `out_dir`, картинка или None, (было, стало) треугольников или
    None) своей модели снаряда. SMD - копией как есть: загрузки лежат под
    постоянным именем, и следующий файл с тем же именем подменил бы снаряд в
    работе. OBJ/GLB - по габаритам игрового снаряда `part_smd`, с лимитами и
    упрощением своей модели, картинка - у материала, где больше всего
    треугольников (все материалы файла сливаются в один)

    Raises:
        mesh_import_service.MeshImportError: модель не читается или не влезет
    """
    import shutil

    from src.services import mesh_import_service

    if path.lower().endswith('.smd'):
        try:
            with open(path, encoding='utf-8') as f:
                ok = 'triangles' in f.read()
        except (OSError, UnicodeDecodeError):
            ok = False
        if not ok:
            raise mesh_import_service.MeshImportError('SMD не читается: нет треугольников')
        return shutil.copy2(path, os.path.join(out_dir, os.path.basename(path))), None, None
    mesh = mesh_import_service.load_mesh(path)
    simplified = None
    if mesh_import_service.over_limits(mesh):
        before = mesh.triangle_count
        mesh = mesh_import_service.simplify(mesh)
        simplified = (before, mesh.triangle_count)
    problem = mesh_import_service.check_limits(mesh)
    if problem:
        raise mesh_import_service.MeshImportError(problem)
    fit = mesh_import_service.fit_into(mesh.corners[:, :3],
                                       mesh_import_service.smd_points(part_smd))
    out = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + '.smd')
    textured = [(count, mesh.textures[name]) for name, _, count in mesh.groups
                if mesh.textures.get(name)]
    texture = max(textured)[1] if textured else None
    return mesh_import_service.write_smd(mesh, out, fit), texture, simplified


