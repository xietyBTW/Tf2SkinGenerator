"""
Редактор частиц: разобранный PCF, его правка, история и сборка.

Живёт отдельно от сеанса предмета: эффект открывают из своего раздела, у него
своя история отмены и своя сцена с моделью для контрольных точек. От сеанса
нужны только пути к игре (`tf2_paths`) и очередь событий страницы (`_put`).

Доступ — `session().particles`; `api.py` зовёт его методы напрямую.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from src.shared.logging_config import get_logger
from src.shared.paths import data_dir
from src.shared.text_search import plain

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


def qc_is_y_up(qc_path: str) -> bool:
    """`$upaxis Y` в QC — модель (персонаж) лежит в SMD осью Y вверх."""
    try:
        with open(qc_path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return False
    return re.search(r'(?im)^\s*\$upaxis\s+"?y', text) is not None


def qc_is_player_item(qc_path: str) -> bool:
    """Косметика/реквизит игрока по `$modelname` (…/player/items/…)."""
    try:
        with open(qc_path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return False
    found = re.search(r'(?im)^\s*\$modelname\s+"([^"]+)"', text)
    return bool(found and 'player/items/' in found.group(1).replace('\\', '/').lower())


def angles_y_up_to_z_up(angles) -> List[float]:
    """Углы Source (pitch, yaw, roll) после поворота Y-up → Z-up."""
    from src.services.model_attachments import angle_matrix, concat_transforms, matrix_angles
    rot = [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    return list(matrix_angles(concat_transforms(rot, angle_matrix(*angles))))


def obj_y_up_to_z_up(obj_text: str) -> str:
    """Поворот OBJ из Y-up в Z-up: (x, y, z) → (x, −z, y), для вершин и нормалей."""
    out = []
    for line in obj_text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] in ('v', 'vn'):
            try:
                x, y, z = (float(v) for v in parts[1:])
            except ValueError:
                out.append(line)
                continue
            out.append(f"{parts[0]} {x:.6f} {-z:.6f} {y:.6f}")
        else:
            out.append(line)
    return '\n'.join(out) + '\n'


def obj_shift(obj_text: str, delta) -> str:
    """Сдвиг вершин OBJ на −delta (нормали не трогаем)."""
    out = []
    for line in obj_text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == 'v':
            try:
                x, y, z = (float(v) for v in parts[1:])
            except ValueError:
                out.append(line)
                continue
            out.append(f"v {x - delta[0]:.6f} {y - delta[1]:.6f} {z - delta[2]:.6f}")
        else:
            out.append(line)
    return '\n'.join(out) + '\n'


def tree_nodes(tree: list) -> List[dict]:
    """Иерархия систем в вид для каталога: {key, name, kids}.

    Вложенность в PCF настоящая (система тянет детей), и показывать её надо
    вложенностью же: в class_fx.pcf 104 системы, и плоским списком имён они
    читаются как свалка. Выбрать при этом можно любой узел — движок строит
    эффект от того, который назвали корнем.

    Циклы обрывает system_hierarchy, поэтому обход конечен.
    """
    return [{'key': name, 'name': name, 'kids': tree_nodes(kids)}
            for name, kids in tree]


class ParticlesEditor:
    """Открытый в редакторе эффект и всё, что с ним делают."""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Разобранный PCF. Живёт между вызовами: правка параметров и сборка
        #: VPK работают с тем же деревом, что показано на экране.
        self.pcf = None
        #: История правок эффекта: снимки и позиция в них.
        self._particle_history: List[Any] = []
        self._particle_pos = -1
        #: Во время отката новые снимки не пишем — иначе он сам стал бы правкой.
        self._restoring = False


    #: Сколько эффектов отдаём под поиском: систем в игре десять тысяч.
    EFFECTS_PAGE = 200

    def particle_effects(self, query: str = '', source: str = '',
                         lang: str = 'ru') -> Dict[str, Any]:
        """Эффекты игры по имени и по тому, чем они вызываются: {ready, items, facets}.

        Без запроса и без источника — необычные эффекты с именами из игры
        (то, что ищут чаще всего). С источником — все системы этого вида
        (оружие, постройки, игрок…), подписанные предметом: «Огнемёт»,
        «Турель». С запросом — поиск по всем 10 тысячам систем 134 файлов,
        включая имена предметов: «огнемёт» находит его вспышку и пламя.
        `ready` — собран ли индекс систем; до того ищем только по именам.
        """
        from src.data import particle_sources as ps

        rows, ready = self._effect_rows(lang)
        source = (source or '').strip().lower()
        words = [plain(w) for w in (query or '').split() if plain(w)]

        by_name = {row['system']: row for row in rows}
        counts: Dict[str, int] = {}
        #: Корни на показ, в порядке первого совпадения: {корень: [дети]}.
        found: Dict[str, List[Dict[str, Any]]] = {}
        matched: set = set()
        for row in rows:
            if words and not all(w in row['blob'] for w in words):
                continue
            if source and source not in row['kinds']:
                continue
            # Без запроса и источника — каталог: только необычные.
            if not words and not source and not row['name']:
                continue
            matched.add(row['system'])
            # Дочерняя встаёт под свой корень: у эффекта из тридцати систем
            # человеку нужна одна строка, а не тридцать.
            top = row['root'] or row['system']
            kids = found.setdefault(top, [])
            if row['root'] and by_name.get(top) is not None:
                kids.append(row)
        # Счётчики — по корням и по всей игре под запросом, а не по
        # показанному: из каталога необычных иначе нельзя было бы уйти в
        # «Оружие».
        for top in {r['root'] or r['system'] for r in rows
                    if not words or all(w in r['blob'] for w in words)}:
            for kind in self._root_kinds(by_name, top):
                counts[kind] = counts.get(kind, 0) + 1

        items: List[Dict[str, Any]] = []
        for top, kids in found.items():
            root = by_name.get(top)
            if root is None:
                continue
            # Совпал только корень — показываем всех его детей, чтобы было
            # что развернуть; совпали дети — только их.
            # `open` — раскрыть сразу: нашли только детей, а не корень;
            # когда совпал и корень, сотня раскрытых огнемётов — шум.
            hit = bool(kids) and top not in matched
            if not kids and top in matched:
                kids = [by_name[k] for k in self._children.get(top, ())
                        if k in by_name]
            items.append({**root, 'kids': sorted(kids, key=lambda it: it['system'].lower()),
                          'matched': top in matched, 'open': hit})

        if words:
            # Совпавшие целиком или с начала — выше: «crit» это crit_text,
            # а не bullet_tracer01_crit. Корень наследует лучший ранг детей.
            def rank_one(it: Dict[str, Any]) -> int:
                if any(w in it['keys'] for w in words):
                    return 0
                if any(k.startswith(w) for k in it['keys'] for w in words):
                    return 1
                return 2

            def rank(it: Dict[str, Any]) -> int:
                own = rank_one(it) if it['matched'] else 3
                return min([own, *(rank_one(k) for k in it['kids'])])
            items.sort(key=rank)
        elif source:
            # Под источником — по предмету, потом по имени: все вспышки
            # огнемёта рядом.
            items.sort(key=lambda it: (' '.join(it['labels']).lower() or '\uffff',
                                       it['system'].lower()))
        facets = [{'key': kind, 'name': name, 'count': counts.get(kind, 0)}
                  for kind, name in ps.KIND_NAMES.items()
                  if counts.get(kind) or kind == source]
        hidden = ('blob', 'keys', 'root', 'matched')
        strip = lambda it: {k: v for k, v in it.items() if k not in hidden}  # noqa: E731
        # Каталог отдаём весь (645 строк — его листают); список источника —
        # до восьмисот, поиск — первые двести: дальше уточняют запрос.
        page = (items if not words and not source
                else items[:self.EFFECTS_PAGE * (1 if words else 4)])
        return {'ready': ready,
                'items': [{**strip(it), 'kids': [strip(k) for k in it['kids']]}
                          for it in page],
                'total': len(items), 'facets': facets}

    def _root_kinds(self, by_name: Dict[str, dict], top: str) -> set:
        """Виды корня вместе с детьми: огнемёт зовёт эффект, у которого
        сам корень — «правила игры», а пламя — дети."""
        kinds = set(by_name[top]['kinds']) if top in by_name else set()
        for kid in self._children.get(top, ()):
            if kid in by_name:
                kinds.update(by_name[kid]['kinds'])
        return kinds

    def _effect_rows(self, lang: str):
        """Все эффекты игры со словами для поиска — один раз на язык.

        Строка стоит подписей на двух языках и десятка словарных обращений;
        на десять тысяч систем это полсекунды, и делать это на каждую
        букву запроса нельзя. Пока индекс систем строится, строк только
        необычные — и кэш не ставится, чтобы дождаться остальных.
        """
        from src.data import particle_sources as ps
        from src.data.hats_parser import parse_localization
        from src.data.unusual_effects import CATEGORY_NAMES
        from src.services.particle_editor_service import ParticleEditorService

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return [], False
        index = ParticleEditorService.system_index(paths['root'])
        roots = ParticleEditorService.system_roots(paths['root'])
        cache = getattr(self, '_effect_cache', None)
        if cache and cache[0] == (lang, len(index)):
            return cache[1], bool(index)
        #: {корень: [дети]} — для разворачивания и счётчиков.
        self._children: Dict[str, List[str]] = {}
        for kid, top in roots.items():
            self._children.setdefault(top, []).append(kid)

        unusuals = self._unusual_effects(lang)
        by_system = {fx['system']: fx for fx in unusuals}
        names = {fx['system']: fx['name'] for fx in unusuals if fx['name']}
        english = ({} if lang == 'en' else
                   {fx['system']: fx['name'] for fx in self._unusual_effects('en')})
        loc = parse_localization(paths['root'],
                                 'russian' if lang == 'ru' else 'english')
        loc_en = loc if lang == 'en' else parse_localization(paths['root'], 'english')
        order = {'cosmetic': 0, 'taunt': 1, 'weapon': 2, 'killstreak': 3,
                 'other': 4}
        # Необычные — первыми и по категориям (так идёт каталог), остальные
        # системы — в порядке индекса.
        pairs = [(fx['system'], index.get(fx['system'], ''))
                 for fx in sorted(unusuals, key=lambda fx: order.get(fx['category'], 9))]
        pairs += [(system, file) for system, file in index.items()
                  if system not in by_system]

        rows: List[Dict[str, Any]] = []
        for system, file in pairs:
            fx = by_system.get(system)
            name = fx['name'] if fx else ''
            labels = [l for l in ps.labels_of(system, file, loc, names, lang)
                      if l != name]
            labels_en = ps.labels_of(system, file, loc_en, english, 'en')
            rows.append({
                'system': system, 'file': file, 'name': name,
                # Эффект с именем из игры — сам себе корень, даже если в
                # файле он чей-то ребёнок: superrare_burning2 лежит под
                # superrare_test, а ищут его.
                'root': '' if name else roots.get(system, ''),
                'category': fx['category'] if fx else '',
                'category_name': CATEGORY_NAMES[fx['category']] if fx else '',
                'kinds': ps.kinds_of(system, file),
                'labels': labels,
                'blob': ' '.join(plain(t) for t in
                                 (system, name, english.get(system, ''),
                                  *labels, *labels_en)),
                'keys': [plain(t) for t in (system, name, *labels) if t],
            })
        if index:
            self._effect_cache = ((lang, len(index)), rows)
        return rows, bool(index)

    def _unusual_effects(self, lang: str) -> List[dict]:
        """Таблица необычных эффектов с именами на языке интерфейса."""
        from src.data import unusual_effects
        from src.data.hats_parser import parse_localization
        from src.data.weapon_model_index import get_items_game_path

        cache = getattr(self, '_unusual_cache', None)
        if cache is None:
            cache = self._unusual_cache = {}
        if lang not in cache:
            paths = self._host.tf2_paths()
            items_game = get_items_game_path(paths['root'])
            try:
                text = open(items_game, encoding='utf-8', errors='replace').read()
            except OSError:
                text = ''
            loc = parse_localization(paths['root'],
                                     'russian' if lang == 'ru' else 'english')
            cache[lang] = unusual_effects.parse(text, loc)
        return cache[lang]

    def load_particles(self, source: str) -> Dict[str, Any]:
        """
        Разбирает PCF и отдаёт всё, что нужно рендереру.

        Ответом, а не событием: разбор с материалами занимает около секунды, а
        результат доходит до 9 МБ (VTF внутри уже развёрнуты в PNG data-URL).
        Гонять такое через поток событий незачем — страница всё равно ничего
        не может показать, пока не получит его целиком.
        """
        paths = self._host.tf2_paths()
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

        self.pcf = svc
        self._history_reset()
        systems = svc.systems_json()
        tree = tree_nodes(system_hierarchy(systems, order=svc.system_names()))
        return {
            'systems': systems,
            'materials': svc.materials_json(paths['root']),
            'tree': tree,
            # Что отличается от игры — метки в дереве. Открыли файл с диска
            # без игрового собрата — пусто.
            'diff': self._particle_diff_all(systems),
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

        systems = self.pcf.systems_json() if self.pcf else {}
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

        if self.pcf is None:
            return {'error': 'PCF не загружен'}
        param = next((p for p in sp.SIMPLE_PARAMS if p.key == key), None)
        if param is None:
            return {'error': f'неизвестный параметр: {key}'}

        systems = self.pcf.systems_json()
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
            paths = self._host.tf2_paths()
            root = '' if 'error' in paths else paths['root']
            for group, fn in sp.missing_modules(sys_json, param):
                if not self.pcf.add_module(system, group, fn, root):
                    return {'error': f'не удалось создать модуль {fn}'}
            sys_json = self.pcf.systems_json().get(system, sys_json)

        calls = sp.write_calls(sys_json, param, value)
        if not calls:
            return {'error': 'в этой системе нужного модуля нет'}
        for group, idx, attr, attr_type, v in calls:
            self.pcf.ensure_attr(system, group, idx, attr, attr_type, v)

        self._history_commit()
        systems = self.pcf.systems_json()
        return {'systems': systems,
                'diff': self._particle_diff_all(systems),
                # Подробно — только для правленой системы: экспертное дерево
                # помечает изменённые строки, не перестраиваясь.
                'system_diff': self.particle_diff(system)}

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

        systems = self.pcf.systems_json() if self.pcf else {}
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
        return {'name': system, 'groups': groups,
                'diff': self.particle_diff(system)}

    # ── Структура эффекта ──────────────────────────────────────────────── #
    #
    # Всё, что меняет состав систем и модулей. Каждая операция отдаёт свежие
    # системы И дерево: добавленный модуль виден в свойствах, а созданная или
    # переименованная система — ещё и в каталоге слева.

    def _particles_state(self, **extra: Any) -> Dict[str, Any]:
        """Свежий снимок для страницы после правки структуры."""
        from src.services.particle_editor_service import system_hierarchy

        self._history_commit()
        systems = self.pcf.systems_json()
        out: Dict[str, Any] = {
            'systems': systems,
            'tree': tree_nodes(system_hierarchy(
                systems, order=self.pcf.system_names())),
            'diff': self._particle_diff_all(systems),
        }
        out.update(extra)
        return out

    def _particle_diff_all(self, systems: Dict[str, dict]) -> Dict[str, str]:
        """{система: added|changed|same} против игры. Пусто — стока нет."""
        from src.services.particle_editor_service import diff_systems

        paths = self._host.tf2_paths()
        if 'error' in paths or not hasattr(self.pcf, 'stock'):
            return {}
        stock = self.pcf.stock(paths['root'])
        if stock is None:
            return {}
        cached = getattr(self.pcf, '_stock_systems', None)
        if cached is None:
            cached = self.pcf._stock_systems = stock.systems_json()
        return {name: entry['status']
                for name, entry in diff_systems(systems, cached).items()}

    def particle_diff(self, system: str) -> Dict[str, Any]:
        """Чем система отличается от игры: атрибуты, модули, дочерние.

        Пустой ответ (без `status`) — сравнивать не с чем: файл не из игры
        и одноимённого в ней нет.
        """
        paths = self._host.tf2_paths()
        if 'error' in paths or not hasattr(self.pcf, 'stock_diff'):
            return {}
        return self.pcf.stock_diff(paths['root']).get(system) or {}

    def revert_particle_system(self, system: str) -> Dict[str, Any]:
        """Система как в игре — атрибуты, модули, дочерние."""
        if (err := self._need_pcf()):
            return err
        paths = self._host.tf2_paths()
        if not self.pcf.revert_system(paths.get('root', ''), system):
            return {'error': 'В игре такой системы нет — возвращать не к чему'}
        return self._particles_state(selected=system)

    def revert_particle_attr(self, system: str, group: Optional[str],
                             index: int, attr: str) -> Dict[str, Any]:
        """Один параметр как в игре (в игре его нет — убираем)."""
        if (err := self._need_pcf()):
            return err
        paths = self._host.tf2_paths()
        if not self.pcf.revert_attr(paths.get('root', ''), system,
                                          group, int(index), attr):
            return {'error': f'не удалось вернуть {attr}'}
        return self._particles_state(selected=system)

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
        if self.pcf is None:
            return
        snap = self.pcf.snapshot()
        if snap is not None:
            self._particle_history = [snap]
            self._particle_pos = 0

    def _history_commit(self) -> None:
        """Фиксирует состояние ПОСЛЕ правки. Во время отката молчит."""
        if (self._restoring or self.pcf is None
                or self._particle_pos < 0):
            return
        snap = self.pcf.snapshot()
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
            if not self.pcf.restore(self._particle_history[pos]):
                return {'error': 'не удалось восстановить состояние'}
            self._particle_pos = pos
            out = self._particles_state()
        finally:
            self._restoring = False
        # Материалы отдаём вместе: откат мог вернуть или убрать свою текстуру.
        paths = self._host.tf2_paths()
        if 'error' not in paths:
            out['materials'] = self.pcf.materials_json(paths['root'])
        out.update(self.particle_history())
        return out

    def _need_pcf(self) -> Optional[Dict[str, Any]]:
        return None if self.pcf is not None else {'error': 'PCF не загружен'}

    def particle_module_catalog(self, group: str) -> List[str]:
        """Что можно добавить в эту группу: ходовое сверху, дальше всё из игры."""
        from src.services.particle_editor_service import ParticleEditorService

        paths = self._host.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        return ParticleEditorService.group_module_catalog(group, root)

    def add_particle_module(self, system: str, group: str,
                            function_name: str) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        paths = self._host.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        if not self.pcf.add_module(system, group, function_name, root):
            return {'error': f'не удалось добавить {function_name}'}
        return self._particles_state()

    def remove_particle_module(self, system: str, group: str,
                               index: int) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.pcf.remove_module(system, group, int(index)):
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

        if self.pcf is None:
            return []
        paths = self._host.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        found = self.pcf.missing_attrs(system, group, int(index), root)
        return [{'name': name, 't': tv.get('t'), 'v': tv.get('v'),
                 'help': particle_docs.attr_help(name, lang) or ''}
                for name, tv in sorted(found.items())]

    def add_particle_attr(self, system: str, group: Optional[str], index: int,
                          attr: str, attr_type: str, value: Any) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.pcf.ensure_attr(system, group, int(index), attr,
                                          attr_type, value):
            return {'error': f'не удалось добавить {attr}'}
        return self._particles_state()

    def remove_particle_attr(self, system: str, group: Optional[str],
                             index: int, attr: str) -> Dict[str, Any]:
        """Удаляет параметр — значение возвращается к умолчанию движка."""
        if (err := self._need_pcf()):
            return err
        if not self.pcf.remove_attr(system, group, int(index), attr):
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
        sys_json = self.pcf.systems_json().get(system)
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
        ok = self.pcf.paste_params(system, payload or {}, mode=mode,
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
        if not self.pcf.duplicate_system(system, new_name):
            return {'error': 'не удалось дублировать — возможно, имя занято'}
        return self._particles_state(selected=new_name)

    def rename_particle_system(self, system: str,
                               new_name: str) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.pcf.rename_system(system, new_name):
            return {'error': 'не удалось переименовать — возможно, имя занято'}
        return self._particles_state(selected=new_name)

    def remove_particle_system(self, system: str) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.pcf.remove_system(system):
            return {'error': 'не удалось удалить систему'}
        return self._particles_state()

    def particle_children(self, system: str) -> List[dict]:
        """Дочерние системы: их отцепляют по индексу."""
        if self.pcf is None:
            return []
        sys_json = self.pcf.systems_json().get(system) or {}
        return [{'index': i, 'name': c.get('childName', ''),
                 'delay': c.get('delay', 0.0)}
                for i, c in enumerate(sys_json.get('children') or [])]

    def add_particle_child(self, parent: str, child: str,
                           delay: float = 0.0) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.pcf.add_child(parent, child, float(delay)):
            return {'error': 'не подцепить: система не найдена или вышел бы цикл'}
        return self._particles_state()

    def remove_particle_child(self, parent: str, index: int) -> Dict[str, Any]:
        if (err := self._need_pcf()):
            return err
        if not self.pcf.remove_child(parent, int(index)):
            return {'error': 'не удалось отцепить'}
        return self._particles_state()

    def add_particle_layer(self, parent: str) -> Dict[str, Any]:
        """Готовый слой-подэффект: остаётся дать текстуру и покрутить."""
        if (err := self._need_pcf()):
            return err
        name = self.pcf.add_layer(parent)
        if not name:
            return {'error': 'не удалось добавить слой'}
        return self._particles_state(selected=name)

    def set_particle_attr(self, system: str, group: Optional[str], index: int,
                          attr: str, value: Any) -> Dict[str, Any]:
        """Правка одного атрибута из экспертного режима."""
        if (err := self._need_pcf()):
            return err
        if not self.pcf.set_attr(system, group, int(index), attr, value):
            return {'error': f'не удалось записать {attr}'}
        self._history_commit()
        systems = self.pcf.systems_json()
        return {'systems': systems,
                'diff': self._particle_diff_all(systems),
                # Подробно — только для правленой системы: экспертное дерево
                # помечает изменённые строки, не перестраиваясь.
                'system_diff': self.particle_diff(system)}

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

        if self.pcf is None:
            return {'used': []}
        systems = self.pcf.systems_json()
        sys_json = systems.get(system)
        if sys_json is None:
            return {'used': []}
        return {'used': referenced_control_points(sys_json, systems)}

    #: Порядок групп в списке моделей для точек: сперва то, на что вешают
    #: анюжуалы — игроки и косметика, — потом остальное.
    _MODEL_GROUPS = ('player', 'hat', 'weapon', 'arms', 'other')

    def particle_models(self, lang: str = 'ru') -> List[dict]:
        """
        Модели из кэша декомпиляции — на них сажают контрольную точку.

        Своей распаковки VPK здесь нет намеренно: Crowbar долгий, а модели
        попадают в кэш при обычной работе на вкладках оружия и шапок.

        Список был сырым: хэши папок, `__player_scout`, полные пути к MDL,
        один разведчик дважды. Теперь запись — это модель игры: подпись из
        каталога (класс, название шапки или оружия), группа по пути модели,
        дубли по одному и тому же MDL схлопнуты.
        """
        from src.services.model_attachments import (
            list_decompiled_models_meta, reference_smd_for_qc,
        )

        names = self._model_names(lang)
        seen: Dict[str, dict] = {}
        for m in list_decompiled_models_meta():
            # Без reference-SMD меш не собрать: в кэше лежат и папки одних
            # анимаций (__anims_*), предлагать их значит предлагать ошибку.
            if not reference_smd_for_qc(m['qc']):
                continue
            mdl = (m['mdl'] or m['label']).lower()
            group, label = self._model_group_and_name(mdl, m['label'], names, lang)
            key = mdl
            if key in seen:
                continue
            seen[key] = {'label': label, 'qc': m['qc'], 'group': group, 'mdl': mdl}
        order = {g: i for i, g in enumerate(self._MODEL_GROUPS)}
        return sorted(seen.values(),
                      key=lambda x: (order.get(x['group'], 99), x['label'].lower()))

    def _model_names(self, lang: str) -> Dict[str, str]:
        """{путь модели (нижний регистр): название из каталогов игры}."""
        from src.data.player_characters import PLAYER_CHARACTERS

        names: Dict[str, str] = {}
        for info in PLAYER_CHARACTERS.values():
            names[info['mdl_path'].lower()] = info.get(lang) or info.get('en', '')
        paths = self._host.tf2_paths()
        if 'error' not in paths:
            try:
                from src.data.hats_parser import parse_hats
                for h in parse_hats(paths['root'], lang):
                    names.setdefault(h.mdl_path.replace('\\', '/').lower(), h.name)
            except Exception as exc:                 # noqa: BLE001 — каталог не обязателен
                logger.debug(f"каталог шапок для списка моделей не прочитан: {exc}")
        try:
            from src.app.api import items
            for w in items(category='weapon', lang=lang):
                names.setdefault('c:' + str(w.get('key', '')).lower(), w.get('name', ''))
        except Exception as exc:                     # noqa: BLE001
            logger.debug(f"каталог оружия для списка моделей не прочитан: {exc}")
        return names

    @staticmethod
    def _model_group_and_name(mdl: str, label: str, names: Dict[str, str],
                              lang: str) -> Tuple[str, str]:
        """Группа и подпись модели по её пути в игре."""
        base = os.path.splitext(os.path.basename(mdl))[0]
        if mdl.startswith('models/player/') and mdl.count('/') == 2:
            return 'player', names.get(mdl, base)
        if '/items/taunts/' in mdl or base.startswith('taunt_') or '_prop' in base:
            return 'other', base            # реквизит насмешек — не косметика
        if '/items/' in mdl:
            name = names.get(mdl)
            # Стили шапки лежат отдельными моделями (`_style2`), а в каталоге
            # только первый: имя берём у него, номер стиля дописываем.
            style = re.search(r'_style(\d+)$', base)
            if not name and style:
                first = re.sub(r'_style\d+', '_style1', mdl)
                name = names.get(first)
                if name:
                    word = 'style' if lang == 'en' else 'стиль'
                    name = f"{name} ({word} {style.group(1)})"
            return 'hat', name or base
        if base.endswith('_arms'):
            cls = base[2:-5] if base.startswith('c_') else base[:-5]
            who = names.get(f'models/player/{cls}.mdl', cls)
            hands = 'hands' if lang == 'en' else 'руки'
            return 'arms', f"{who} ({hands})"
        if mdl.startswith('models/weapons/') or base.startswith('c_'):
            return 'weapon', names.get('c:' + base, base)
        return 'other', base

    def particle_model_load(self, mode: str, key: str = '',
                            lang: str = 'ru') -> Dict[str, Any]:
        """
        Модель для точек по предмету каталога: класс, шапка, оружие.

        Кэш декомпиляции — тот же, что у вкладок оружия и шапок
        (`ensure_decompiled`): что уже открывали, придёт сразу, остальное
        разберёт Crowbar. Это секунды-минуты, поэтому фоном: ответ — только
        «начали», сцена приезжает событием `cp_model`, ход — `progress`.

        Args:
            mode: режим каталога (`scout_c_scattergun`, `scout_body`,
                  `scout_hands`, `hat`).
            key:  у шапки — путь MDL (у мультиклассовой — уже выбранного
                  класса), у остальных не нужен.
        """
        from src.services import model_decompile_service
        from src.services.model_decompile_service import DecompileError

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        try:
            weapon_key, candidates = self._cp_model_candidates(mode, key, paths['root'])
        except ValueError as exc:
            return {'error': str(exc)}
        if not candidates:
            return {'error': f'Для «{mode}» модель не найти'}

        seq = self._cp_model_seq = getattr(self, '_cp_model_seq', 0) + 1
        misc_vpk = paths['misc_vpk']
        # Подписи стадий — те же, что у 3D-превью: одна и та же работа.
        from src.services.preview_3d_worker import Preview3DWorker
        t = Preview3DWorker._PROGRESS.get(lang, Preview3DWorker._PROGRESS['en'])

        def run() -> None:
            try:
                found = model_decompile_service.ensure_decompiled(
                    weapon_key, misc_vpk, candidates,
                    cancelled=lambda: self._cp_model_seq != seq,
                    on_progress=lambda stage: self._host._put(
                        'progress', text=t.get(stage.value, stage.value)))
            except DecompileError as exc:
                self._host._put('cp_model', error=str(exc))
                return
            if self._cp_model_seq != seq:
                return                       # выбрали другую — эта не нужна
            if found is None:
                self._host._put('cp_model', error=t['not_found'])
                return
            qc = self._qc_in(found.directory)
            if not qc:
                self._host._put('cp_model', error='QC после разбора не найден')
                return
            scene = self.particle_model_scene(qc)
            if 'error' in scene:
                self._host._put('cp_model', error=scene['error'])
                return
            self._host._put('cp_model', scene=scene, qc=qc)

        threading.Thread(target=run, daemon=True, name=f'cp-model-{seq}').start()
        return {'started': True}

    @staticmethod
    def _cp_model_candidates(mode: str, key: str, root: str):
        """(ключ кэша, пути MDL в VPK) — тем же правилом, что у 3D-превью
        (`Preview3DWorker._mdl_candidates`), чтобы кэш был общий."""
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS
        from src.data.player_hands import HAND_MODE_KEYS
        from src.domain.preview.model_key import model_key_for
        from src.services.extract_model_service import ExtractModelService
        from src.services.tf2_paths import build_hat_mdl_candidates

        if mode == 'hat':
            if not key:
                raise ValueError('У шапки нужен путь модели')
            return key, build_hat_mdl_candidates(key)
        if mode in PLAYER_BODY_MODE_KEYS:
            mdl = model_key_for(mode)
            return mdl, [mdl]
        if mode in HAND_MODE_KEYS:
            arm = model_key_for(mode)
            return arm, ExtractModelService._build_paths_to_try(mode, arm, root)
        weapon_key = model_key_for(mode)
        if not weapon_key:
            raise ValueError(f'У «{mode}» нет модели')
        return weapon_key, ExtractModelService._build_paths_to_try(mode, weapon_key, root)

    @staticmethod
    def _qc_in(directory: str) -> Optional[str]:
        """QC разобранной модели: по мете кэша, иначе единственный *.qc."""
        import glob
        import json

        meta = os.path.join(directory, '_cache_meta.json')
        try:
            with open(meta, encoding='utf-8') as f:
                name = json.load(f).get('qc_filename')
            if name and os.path.isfile(os.path.join(directory, name)):
                return os.path.join(directory, name)
        except (OSError, ValueError):
            pass
        found = sorted(glob.glob(os.path.join(directory, '*.qc')))
        return found[0] if found else None

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
            attachments_from_qc, reference_smd_for_qc, root_bone_from_qc,
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

        paths = self._host.tf2_paths()
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
        # Персонажи собраны с `$upaxis Y`: их SMD лежит осью Y вверх, а сцена
        # частиц — Source, Z вверх. Без поворота разведчик лежал на полу и
        # свечение «на игроке» садилось на лежачего. Поворот тот же, что
        # делает studiomdl: (x, y, z) → (x, −z, y). Точки крепления — так же.
        # Косметика собрана против того же скелета и тоже лежит Y вверх, хотя
        # `$upaxis` Crowbar ей не пишет (bip_head у harmburg — (0, 75.7, −2.9)):
        # верх шапки смотрел вбок.
        y_up = qc_is_y_up(qc) or qc_is_player_item(qc)
        if y_up:
            obj = obj_y_up_to_z_up(obj)

        def point(a):
            return {'name': a.name, 'bone': a.bone,
                    'pos': ([a.pos[0], -a.pos[2], a.pos[1]] if y_up else list(a.pos)),
                    'angles': angles_y_up_to_z_up(a.angles) if y_up else list(a.angles)}

        # Корневая кость — куда игра вешает анюжуал косметики
        # (`attach_to_rootbone 1`): у шапки это bip_head на высоте головы, и
        # точка 0 в нуле сцены стояла бы у ног.
        root = root_bone_from_qc(qc)
        points = [point(a) for a in order]
        root_pt = point(root) if root else None

        # Косметику ставим точкой подвеса в ноль сцены: новые шапки собраны на
        # высоте головы (bip_head на ~75), старые — вокруг нуля, и без сдвига
        # шапка висела под потолком, а камера смотрела в пустой пол. Игрока и
        # оружие не трогаем: игрок стоит на сетке, оружие и так у нуля.
        if qc_is_player_item(qc):
            anchor = next((p for p in points
                           if p['name'].lower() in ('unusual', 'unusual_0')),
                          root_pt)
            if anchor:
                delta = list(anchor['pos'])
                obj = obj_shift(obj, delta)
                for p in points + ([root_pt] if root_pt else []):
                    p['pos'] = [a - b for a, b in zip(p['pos'], delta)]
        return {
            'obj': obj,
            'textures': textures,
            'attachments': points,
            'root': root_pt,
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
        systems = self.pcf.systems_json()
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
        paths = self._host.tf2_paths()
        if self.pcf is None or 'error' in paths:
            return []
        found = self.pcf.materials_json(paths['root'])
        names = (self._effect_materials(system) if system
                 else self.pcf.material_names())
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
                'custom': self.pcf.is_custom_material(name),
            })
        return out

    def _materials_result(self) -> Dict[str, Any]:
        """Материалы и системы после правки — движку нужно и то, и другое."""
        self._history_commit()
        paths = self._host.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        return {
            'systems': self.pcf.systems_json(),
            'materials': self.pcf.materials_json(root),
        }

    def set_particle_texture(self, material: str, path: str,
                             max_size: int = 512) -> Dict[str, Any]:
        """Заменяет текстуру материала своей картинкой."""
        if (err := self._need_pcf()):
            return err
        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        try:
            res = self.pcf.set_material_texture(
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
        if self.pcf.reset_material_texture(material) is None:
            return {'error': 'у этого материала нет своей текстуры'}
        return self._materials_result()

    def game_particle_materials(self) -> List[str]:
        """Материалы всех эффектов игры — выбор вместо своей картинки."""
        from src.services.particle_editor_service import ParticleEditorService

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return []
        return ParticleEditorService.game_effect_materials(paths['root'])

    def set_particle_material_to_game(self, material: str,
                                      game_material: str) -> Dict[str, Any]:
        """Переводит эффект на существующий материал игры."""
        if (err := self._need_pcf()):
            return err
        if not self.pcf.set_material_to_game(material, game_material):
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
        if not self.pcf.rename_material(material, new_material):
            return {'error': 'не удалось переименовать — возможно, путь занят'}
        return self._materials_result()

    def use_particle_texture_colors(self, system: str) -> Dict[str, Any]:
        """Снимает подкраску: эффект показывает родные цвета текстур."""
        if (err := self._need_pcf()):
            return err
        removed = self.pcf.use_texture_colors(system)
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
        systems = self.pcf.systems_json()
        found = particle_lint.check_systems(systems, system or '')
        paths = self._host.tf2_paths()
        if 'error' not in paths:
            found += particle_lint.check_game_conflicts(
                paths['root'], self.pcf.pcf_vpk_path())
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
        found = particle_lint.check_systems(self.pcf.systems_json(),
                                            system or '')
        fixed = particle_lint.apply_fixes(self.pcf, found)
        return self._particles_state(fixed=fixed)

    def save_particles(self, path: str) -> Dict[str, Any]:
        """Сохраняет правленый PCF отдельным файлом."""
        if (err := self._need_pcf()):
            return err
        try:
            self.pcf.save(path)
        except Exception as exc:                     # noqa: BLE001 — граница
            return {'error': str(exc)}
        return {'path': path, 'size': self.pcf.serialized_size()}

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
            out = self.pcf.export_vpk(str(dest), language=lang)
        except Exception as exc:                     # noqa: BLE001 — граница
            logger.warning(f"сборка VPK частиц не удалась: {exc}")
            return {'error': str(exc)}
        return {
            'path': str(out),
            'textures_vpk': getattr(self.pcf, 'last_textures_vpk', None),
            'overflow': self.pcf.casual_size_overflow(),
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

        paths = self._host.tf2_paths()
        root = '' if 'error' in paths else paths['root']
        materials = (self.pcf.material_names()
                     if self.pcf is not None else None)
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
