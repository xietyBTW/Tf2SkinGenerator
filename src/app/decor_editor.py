"""
Гирлянда поверх оружия: праздничная версия и фестивайзер

Только показ - в сборку гирлянда идёт своими правками (текстуры, части,
подгонка, своя модель), их сеанс берёт отсюда же (`builds`). Включённый вид и
готовые гирлянды предмета живут здесь, карточки её материалов - в состоянии
превью сеанса, как у всего предмета

Доступ - `session().decor`; `api.py` зовёт его методы напрямую
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


def _garland_smd(path: str):
    """(SMD, {материал: картинка}) своей гирлянды. SMD - как есть, OBJ/GLB
    переводятся в SMD с теми же лимитами и упрощением, что у своей модели

    Raises:
        mesh_import_service.MeshImportError: модель не читается или не влезет
    """
    import tempfile

    from src.services import mesh_import_service

    import shutil

    out_dir = tempfile.mkdtemp(prefix='tf2sg_garland_')
    if path.lower().endswith('.smd'):
        # Копия: загрузки лежат под постоянным именем, и следующий файл с тем
        # же именем подменил бы гирлянду в работе (и в кэше показа)
        try:
            with open(path, encoding='utf-8') as f:
                ok = 'triangles' in f.read()
        except (OSError, UnicodeDecodeError):
            ok = False
        if not ok:
            raise mesh_import_service.MeshImportError('SMD не читается: нет треугольников')
        return shutil.copy2(path, os.path.join(out_dir, os.path.basename(path))), {}
    mesh = mesh_import_service.load_mesh(path)
    if mesh_import_service.over_limits(mesh):
        mesh = mesh_import_service.simplify(mesh)
    problem = mesh_import_service.check_limits(mesh)
    if problem:
        raise mesh_import_service.MeshImportError(problem)
    out = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + '.smd')
    return mesh_import_service.write_smd(mesh, out), dict(mesh.textures or {})


class DecorEditor:
    """Гирлянда показанного оружия и её правки"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Вид гирлянды и предмет, для которого её включили, готовые
        #: гирлянды предмета, чтобы повторное включение было мгновенным;
        #: воркер сборки и кэш видов по ключу предмета
        self.kind = ''
        self.shown_for = ''
        self._decors: Dict[str, Any] = {}
        self._decor_worker = None
        self._decor_options: tuple = ('', [])
        #: Смена вида и событие готовой гирлянды - под одним замком: воркер
        #: зовёт `_on_decor` из своего потока, и без замка он мог пройти
        #: проверку за миг до выключения и прислать гирлянду уже после него
        self._decor_lock = threading.Lock()
        #: Кадры мигания своих лампочек: {(карточка, команда, файл, ...): кадры}
        self._blink_cache: Dict[Any, Any] = {}

    def builds(self, tf2_root: str) -> List[Dict[str, Any]]:
        """Правленые гирлянды предмета - для сборки, показаны они или нет

        Правка гирлянды - часть работы, как текстура: выключенный показ её не
        отменяет. Текстуры - по материалу гирлянды, обе команды (карточка
        нейтральна, пока синюю не задали отдельно)
        """
        from src.services import festive_decor

        key = self._host._shown_weapon()
        models = festive_decor.kinds(key, tf2_root) if key else {}
        uploads = self._host.preview.textures.decor_uploads()
        baked = self.baked()
        out = []
        for kind, mdl in models.items():
            if baked and kind != baked:
                continue          # родная гирлянда вшитой станет пустой
            textures = {}
            for card, teams in uploads.items():
                card_kind, material = festive_decor.parse_card(card)
                if card_kind == kind and material:
                    textures[material] = dict(teams)
            fit = self._host.preview.decor_fit.get(kind)
            bends = self._host.preview.decor_bends.get(kind) or []
            smd = self._host.preview.decor_models.get(kind) or ''
            if textures or fit or bends or smd or kind == baked:
                out.append({'kind': kind, 'mdl': mdl, 'smd': smd,
                            'fit': dict(fit) if fit else None,
                            'bends': [dict(b) for b in bends], 'textures': textures,
                            # Оружие - ради позы превью: изгибы сделаны в ней
                            'weapon': key,
                            # Вшитая: в меш оружия (decor_bake), а все родные
                            # гирлянды в мод - пустыми, чтобы не задвоились
                            **({'bake': True, 'empty': list(models.values())}
                               if kind == baked else {})})
        return out

    def baked(self) -> str:
        """Вид гирлянды, вшитой в модель оружия, пусто - не вшита. У мода из
        VPK не бывает: его модель собирается своим конвейером"""
        p = self._host.preview
        return '' if p.custom_vpk_mode else p.decor_baked

    def bake(self, kind: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """«Сделать праздничным»: гирлянда вида `kind` становится частью модели
        оружия (decor_bake), пустой `kind` - снять. Вшитая показана в кадре, а
        выбор версии прячется: две гирлянды разом игра бы не повесила"""
        kind = str(kind or '')
        if kind and kind not in self.festive_options():
            return {'error': 'У этого предмета такой версии нет'}
        if self._host.preview.custom_vpk_mode:
            return {'error': 'У мода из VPK гирлянду не вшить'}
        # Вшить - сначала показать: не вышло (нет пути к игре) - и не вшита
        if kind:
            shown = self.set_festive(kind, lang)
            if 'error' in shown:
                return shown
        with self._host._lock:
            self._host.preview.decor_baked = kind
        self._host._autosave()
        return self.set_festive(kind, lang) if not kind else self._host.view_state()

    def show_baked(self, lang: str) -> None:
        """Вшитая гирлянда всегда в кадре: после открытия работы и отмены"""
        baked = self.baked()
        if baked and self.kind != baked and baked in self.festive_options():
            self.set_festive(baked, lang)

    def for_card(self, card: str):
        """Разобранная гирлянда, к которой относится карточка, - даже если
        сейчас показана другая или показ выключен: отмена и сборка гифок
        пересобирают склейки гирлянды и без неё в кадре"""
        from src.services import festive_decor
        kind, _material = festive_decor.parse_card(card)
        decor = self._decors.get(kind) if kind else None
        return decor if decor and decor.weapon_key == self._host._shown_weapon() else None

    def festive_options(self) -> List[str]:
        """Какие гирлянды игра вешает на показанное оружие (по порядку показа)

        Спрашивается при каждом состоянии показа, поэтому ответ держим до
        смены предмета: items_game уже разобран, но путь к игре читает конфиг
        """
        from src.services import festive_decor

        key = self._host._shown_weapon()
        if self._decor_options[0] != key:
            paths = self._host.tf2_paths() if key else {'error': ''}
            found = ([] if 'error' in paths
                     else list(festive_decor.kinds(key, paths['root'])))
            self._decor_options = (key, found)
        return list(self._decor_options[1])

    def set_festive(self, kind: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Показывает праздничную версию оружия: гирлянду поверх модели

        Гирлянда приезжает событием `festive_decor` и живёт во вьювере своим
        слоем, её материалы становятся карточками `deco:<вид>/<материал>`.
        Правки гирлянды (текстуры, части, подгонка) - часть работы и уходят в
        мод отдельной моделью (decor_build), выключенный показ их не
        отменяет и ничего не стоит. Первое включение - разбор модели
        гирлянды (около секунды), дальше из памяти
        """
        kind = str(kind or '')
        key = self._host._shown_weapon()
        if kind and kind not in self.festive_options():
            return {'error': 'У этого предмета такой версии нет'}
        if self.baked() and kind != self.baked():
            return {'error': 'Гирлянда вшита в модель: сначала снимите её'}
        with self._decor_lock:
            self.kind, self.shown_for = kind, key if kind else ''
            # Карточки прошлой гирлянды уходят сразу: новая ещё строится, а
            # выключенной в альбоме делать нечего. Правки её остаются в работе
            self._show_decor_cards(None)
            if not kind:
                self._host._put('festive_decor', kind='')
        self._stop_decor()
        # Синюю команду могла включить одна гирлянда: у самого предмета её
        # нет, а у новой гирлянды может не быть (или она ещё строится) - кнопки
        # пропадут, и BLU залип бы невидимым, вместе с синими руками в кадре
        from src.shared.constants import Team
        t = self._host.preview.textures
        if not (self._host.preview.has_team_variant(False) or t.force_team):
            t.active_team = Team.RED
        if not kind:
            return self._host.view_state()
        own = self._host.preview.decor_models.get(kind) or ''
        cached = self._decors.get(kind)
        if cached is not None and cached.weapon_key == key and cached.source == own:
            self._show_decor_cards(cached)
            self._host._put('festive_decor', **cached.as_event())
            return self._host.view_state()
        self._decors.pop(kind, None)

        paths = self._host.tf2_paths()
        if 'error' in paths:
            with self._decor_lock:
                self.kind = self.shown_for = ''
            return paths
        from src.services.festive_decor import FestiveDecorWorker
        w = FestiveDecorWorker(key, kind, paths['misc_vpk'],
                               paths['textures_vpk'], paths['root'], lang=lang,
                               custom_smd=own)
        w.progress.connect(lambda text: self._host._put('progress', text=text))
        w.ready.connect(self._on_decor)
        w.failed.connect(lambda message: self._on_decor_failed(key, kind, message))
        self._decor_worker = w
        w.start()
        return self._host.view_state()

    def reshow(self, was: Dict[str, str], lang: str) -> None:
        """Показанная гирлянда сменила модель (отмена, сброс, возврат работы) -
        собрать её заново; `was` - decor_models до перемены"""
        kind = self.kind
        if kind and was.get(kind) != self._host.preview.decor_models.get(kind):
            self.set_festive(kind, lang)
        self.show_baked(lang)

    def load_decor_model(self, kind: str, path: str, lang: str = 'ru') -> Dict[str, Any]:
        """Своя модель гирлянды вида `kind` вместо стоковой

        Независима от своей модели оружия: заменить можно и то, и другое.
        Скелет и QC остаются стоковыми (festive_decor.build), материалы -
        свои, картинки из MTL/glTF сразу ложатся на их карточки. Гирлянда
        включается - иначе замену не видно
        """
        from src.services import festive_decor, mesh_import_service
        from src.services.smd_service import SMDService

        kind = str(kind or '')
        if kind not in self.festive_options():
            return {'error': 'У этого предмета такой версии нет'}
        if not path or not os.path.isfile(path):
            return {'error': 'Файл модели не найден'}
        try:
            smd, textures = _garland_smd(path)
        except mesh_import_service.MeshImportError as exc:
            return {'error': str(exc)}
        with self._host._lock:
            # Краска и части прежней гирлянды - по её треугольникам
            self._host.preview.forget_decor_look(kind)
            self._host.preview.decor_models[kind] = smd
            for material, image in textures.items():
                name = SMDService._sanitize_material_name(material)
                self._host.preview.textures.set_texture(festive_decor.card(kind, name), image)
        self._host._autosave()
        return {**self.set_festive(kind, lang), 'textures': len(textures)}

    def drop_decor_model(self, kind: str, lang: str = 'ru') -> Dict[str, Any]:
        """Возвращает стоковую модель гирлянды вида `kind`"""
        kind = str(kind or '')
        with self._host._lock:
            dropped = self._host.preview.decor_models.pop(kind, None)
            if dropped:
                self._host.preview.forget_decor_look(kind)
        if not dropped:
            return self._host.view_state()
        self._host._autosave()
        if kind == self.kind:
            return self.set_festive(kind, lang)
        return self._host.view_state()

    def textures_for_viewer(self) -> Dict[str, Dict[str, List[str]]]:
        """Свои текстуры гирлянды кадрами: мигают так же, как в игре

        Кадры считаются один раз на картинку (ключ - путь и время файла) -
        состояние показа спрашивают после каждого действия
        """
        from src.services import festive_decor

        cache = getattr(self, '_blink_cache', None)
        if cache is None:
            cache = self._blink_cache = {}
        out: Dict[str, Dict[str, List[str]]] = {}
        for card, teams in self._host.preview.textures.decor_uploads().items():
            decor = self.for_card(card)
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
                    # Каждый мазок кистью - новая склейка, а с ней и новые
                    # кадры, старые больше не покажут
                    if len(cache) > 64:
                        cache.clear()
                    target = tempfile.mkdtemp(prefix='tf2sg_blink_')
                    cache[key] = festive_decor.blink_like(
                        path, frames, target, card.replace(':', '_').replace('/', '_'))
                out[card][team] = cache[key]
        return out

    def edited_kinds(self) -> List[str]:
        """Виды гирлянд, у которых есть правки: текстуры или подгонка"""
        from src.services import festive_decor
        kinds = (set(self._host.preview.decor_fit) | set(self._host.preview.decor_bends)
                 | set(self._host.preview.decor_models))
        kinds.update(festive_decor.parse_card(c)[0]
                     for c in self._host.preview.textures.decor_uploads())
        kinds.discard('')
        return sorted(kinds)

    def shown(self):
        """Готовая гирлянда, которая сейчас включена; None - выключена"""
        decor = self._decors.get(self.kind) if self.kind else None
        if decor is None or decor.weapon_key != self._host._shown_weapon():
            return None
        return decor

    def _on_decor(self, decor) -> None:
        # Пока строилась, человек мог выключить её, выбрать другую или уйти
        # к другому предмету
        with self._decor_lock:
            if ((decor.weapon_key, decor.kind) != (self.shown_for, self.kind)
                    or decor.weapon_key != self._host._shown_weapon()):
                return
            self._decors[decor.kind] = decor
            self._show_decor_cards(decor)
            self._host._put('festive_decor', **decor.as_event())

    def _on_decor_failed(self, key: str, kind: str, message: str) -> None:
        with self._decor_lock:
            if (key, kind) != (self.shown_for, self.kind):
                return
            self.kind = self.shown_for = ''
            self._host._put('festive_failed', kind=kind)
        logger.warning(f"гирлянда не собралась: {key}/{kind}: {message}")

    def _stop_decor(self) -> None:
        # Ждём воркер БЕЗ замка: его `_on_decor` сам берёт замок, и остановка
        # под ним простояла бы все три секунды
        w, self._decor_worker = self._decor_worker, None
        if w is not None:
            w.stop(3000)

    def forget(self) -> None:
        """Новый предмет: гирлянда прошлого к нему не относится

        Вьюверу говорим об этом сами: работа и мод из VPK открываются без
        сброса кадра, и оставшаяся гирлянда повисла бы на новой модели
        """
        with self._decor_lock:
            if self.kind:
                self._host._put('festive_decor', kind='')
            self.kind = self.shown_for = ''
            self._decors = {}
            self._decor_options = ('', [])
            self._show_decor_cards(None)
        self._stop_decor()

    def _show_decor_cards(self, decor) -> None:
        """Карточки гирлянды в альбоме и её игровые кадры (None - убрать)

        Кадры кладутся в своё поле (`decor_stock`), а не в карты модели
        оружия: те переписываются каждой загрузкой модели - сменил состояние
        бутылки, и карточка гирлянды осталась бы пустой
        """
        from src.shared.constants import Team
        with self._host._lock:
            p = self._host.preview
            if decor is None:
                p.decor_cards = []
                p.textures.decor_stock = {}
                return
            p.decor_cards = list(decor.materials)
            # Основа карточки - «все лампочки горят», а не первый кадр: в нём
            # один цвет погашен, и кисть по нему дала бы тёмный цвет
            p.textures.decor_stock = {
                team: {c: (m.get('lit') or {}).get(team) or m[team][0]
                       for c, m in decor.materials.items() if m[team]}
                for team in (Team.RED, Team.BLU)}

    def set_decor_fit(self, fit: Optional[dict] = None) -> Dict[str, Any]:
        """Подгонка показанной гирлянды под свою модель

        Вьювер двигает гирлянду сам и сразу, здесь - только числа. Их берут
        сборка (модель гирлянды пересобирается с запечённым сдвигом) и вид от
        первого лица. Единица не хранится: стоковая гирлянда - не правка
        """
        from src.services import mesh_import_service

        kind = self.kind
        if not kind or not self.shown():
            return {'error': 'Сначала включите праздничную версию'}
        parsed = mesh_import_service.Fit.from_dict(fit)
        with self._host._lock:
            if parsed == mesh_import_service.Fit():
                self._host.preview.decor_fit.pop(kind, None)
            else:
                self._host.preview.decor_fit[kind] = parsed.to_dict()
        self._host._autosave()
        return {'fit': self._host.preview.decor_fit.get(kind)}

    def set_decor_bends(self, bends: Optional[List[dict]] = None) -> Dict[str, Any]:
        """Изгибы показанной гирлянды - списком целиком

        Вьювер гнёт гирлянду сам и присылает итог после каждого движения;
        список целиком, а не «добавить»: так же приходят «выпрямить» (пусто)
        и откат, и порядок движений не зависит от порядка запросов
        """
        kind = self.kind
        if not kind or not self.shown():
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
            # nan в SMD ломает компиляцию модели - такой изгиб не берём
            if (len(c) == 3 and len(d) == 3 and r > 0
                    and all(map(math.isfinite, [*c, *d, r]))):
                clean.append({'c': c, 'r': r, 'd': d})
        with self._host._lock:
            if clean:
                self._host.preview.decor_bends[kind] = clean
            else:
                self._host.preview.decor_bends.pop(kind, None)
        self._host._autosave()
        return {'bends': self._host.preview.decor_bends.get(kind, [])}

    def scene_args(self, key: str) -> Dict[str, str]:
        """Гирлянда для сцены в руках: SMD с правками и имена её мешей"""
        from src.services import festive_decor
        decor = self.shown()
        if not decor or decor.weapon_key != key:
            return {'decor_smd': '', 'decor_prefix': festive_decor.PREFIX}
        return {'decor_smd': festive_decor.shaped_smd(
                    decor.smd_path, self._host.preview.decor_fit.get(decor.kind),
                    self._host.preview.decor_bends.get(decor.kind),
                    festive_decor.weapon_pose(decor.weapon_key, decor.smd_path)),
                'decor_prefix': festive_decor.card(decor.kind, '')}
