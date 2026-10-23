"""Каталог игры: параметры модулей, системы, материалы - один скан всех PCF

Состояние каталога живёт атрибутами класса сервиса (cls): его читают
подсказки UI, тесты и фоновый поток"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.particle_editor.hierarchy import system_hierarchy
from src.services.particle_editor.pcf_format import (
    MODULE_GROUPS, SERVICE_ATTRS, element_attrs_to_json, module_fn,
    module_to_json)
from src.services.tf2_paths import TF2Paths
from src.services.vtf_preview_service import open_vpks
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Каталог модулей для «Добавить модуль…» - ходовые functionName из стоковых
#: PCF TF2 (написание - как в файлах игры). Идут первыми в списке выбора,
#: остальные модули игры добавляются к ним из каталога параметров
#:
#: Правило отбора: сюда попадает всё, что умеет движок превью, плюс то, что
#: массово встречается в эффектах игры (счётчики - по срезу 134 стоковых PCF).
#: Модули, которых превью не понимает, помечаются в диалоге отдельно -
#: скрывать их нельзя: в игре они работают, и без них не собрать половину
#: приёмов Valve (спавн по модели, привязка к кости)
MODULE_CATALOG = {
    "emitters": ["emit_continuously", "emit_instantaneously", "emit noise"],
    "initializers": [
        "Position Within Sphere Random", "Position Within Box Random",
        "Position Modify Offset Random", "Position Modify Warp Random",
        "Position From Parent Particles", "Position on Model Random",
        "Position Along Path Sequential", "Position Along Path Random",
        "Lifetime Random", "Radius Random", "Alpha Random", "Color Random",
        "Rotation Random", "Rotation Speed Random", "Rotation Yaw Random",
        "Rotation Yaw Flip Random", "Sequence Random", "Sequence Two Random",
        "Trail Length Random",
        "Velocity Random", "Velocity Noise",
        "Velocity Inherit from Control Point", "lifetime from sequence",
        "Lifetime From Control Point Life Time", "Lifetime Pre-Age Noise",
        "remap initial scalar", "Remap Initial Distance to Control Point to Scalar",
        "Remap Noise to Scalar", "Remap Control Point to Vector",
        "Remap Control Point to Scalar", "Remap Scalar to Vector",
        "Assign target CP", "move particles between 2 control points",
    ],
    "operators": [
        "Lifespan Decay", "Movement Basic", "Movement Lock to Control Point",
        "Movement Rotate Particle Around Axis", "Movement Max Velocity",
        "Movement Lock to Bone", "Movement Follow CP",
        "Movement Dampen Relative to Control Point",
        "Movement Maintain Position Along Path",
        "Movement Match Particle Velocities",
        "Radius Scale", "Color Fade", "Alpha Fade In Random",
        "Alpha Fade Out Random", "Alpha Fade and Decay",
        "Rotation Basic", "Rotation Spin Roll", "Rotation Spin Yaw",
        "Rotation Orient to 2D Direction", "Rotation Orient Relative to CP",
        "Oscillate Scalar", "Oscillate Vector", "Noise Scalar",
        "Remap Scalar",
        "Remap Distance to Control Point to Scalar",
        "Remap Distance to Control Point to Vector",
        "Remap Dot Product to Scalar",
        "Set child control points from particle positions",
        "Set Control Point Positions", "Set Control Point To Player",
        "Set Control Point To Particles' Center",
        "Cull when crossing plane", "Cull Random",
    ],
    "forces": ["random force", "Pull towards control point", "twist around axis"],
    "constraints": [
        "Collision via traces", "Constrain distance to control point",
        "Constrain distance to path between two control points",
        "Prevent passing through a plane",
    ],
    "renderers": ["render_animated_sprites", "render_rope",
                  "render_sprite_trail", "render_screen_velocity_rotate"],
}


def list_game_pcfs(tf2_root_dir: str) -> List[str]:
    """Список путей particles/*.pcf внутри tf2_misc_dir.vpk (отсортирован)"""
    try:
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
    except FileNotFoundError:
        return []
    paks = open_vpks([misc_vpk])
    if not paks:
        return []
    out = []
    for pak in paks:
        try:
            for path in pak:
                name = str(path)
                if name.startswith("particles/") and name.endswith(".pcf"):
                    out.append(name)
        except Exception as exc:
            logger.warning(f"Не удалось перечислить PCF в VPK: {exc}")
    return sorted(set(out))


def _is_particle_material(name: str) -> bool:
    """Спрайтовая particle-текстура (effects//particle), не служебная"""
    if not name or "custom_" in name.lower():
        return False
    return name.replace("\\", "/").lower().startswith(("effects/", "particle/"))


def game_effect_materials(cls, tf2_root_dir: str) -> List[str]:
    """
    Материалы (текстуры) из ВСЕХ particle-эффектов игры - для выбора
    существующей игровой текстуры вместо своей картинки. Такой материал
    уже есть в игре, поэтому мод работает в казуале (bypass не нужно
    добавлять новый файл)

    Собирается вместе с каталогом параметров одним сканом, результат
    кэшируется на диск и переживает перезапуск
    """
    if cls._game_materials_cache is not None:
        return cls._game_materials_cache
    build_attr_catalog(cls, tf2_root_dir)   # заполнит и материалы
    if cls._game_materials_cache is None:
        cls._game_materials_cache = []
    return cls._game_materials_cache


def canonical_attr_name(cls, group: Optional[str], function_name: str,
                        attr_name: str) -> str:
    """
    Имя атрибута в написании игры

    Source читает атрибуты С УЧЁТОМ РЕГИСТРА: записанный строчными
    'spin strength' игра молча игнорирует и берёт умолчание, ей нужен
    'Spin Strength'. AI-пресеты и ручной ввод часто дают строчные -
    приводим к написанию из стоковых эффектов
    """
    key = (group, (function_name or "").strip().lower())
    canon = cls._attr_canonical.get(key)
    if canon:
        return canon.get(attr_name.lower(), attr_name)
    # Модуля нет в каталоге - поищем это имя у любого другого модуля
    for names in cls._attr_canonical.values():
        hit = names.get(attr_name.lower())
        if hit:
            return hit
    return attr_name


#: Версия формата дискового кэша (растёт, когда меняется его состав)
_CATALOG_FORMAT = 7   # 7: + корни {дочерняя: корневая система}


def attr_catalog_file() -> Path:
    return (Path(os.path.expanduser("~")) / ".tf2skingen_cache"
            / "particle_attr_catalog.json")


def game_stamp(tf2_root_dir: str) -> str:
    """Отпечаток контента игры - чтобы кэш протух после обновления TF2"""
    try:
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        st = Path(misc_vpk).stat()
        return f"{st.st_size}-{int(st.st_mtime)}"
    except Exception:
        return ""


def load_disk_catalog(cls, tf2_root_dir: str) -> bool:
    """Поднимает каталог из файла, если он от той же версии игры"""
    path = cls._attr_catalog_file()
    try:
        if not path.is_file():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("stamp") != cls._game_stamp(tf2_root_dir):
            return False
        if data.get("format") != _CATALOG_FORMAT:
            return False        # старый кэш без канонических имён
        for key_str, attrs in (data.get("catalog") or {}).items():
            group, _, fn = key_str.partition("|")
            cls._attr_catalog[(group or None, fn)] = attrs
        for key_str, disp in (data.get("display") or {}).items():
            group, _, fn = key_str.partition("|")
            cls._module_display[(group or None, fn)] = disp
        for key_str, names in (data.get("canonical") or {}).items():
            group, _, fn = key_str.partition("|")
            cls._attr_canonical[(group or None, fn)] = names
        cls._game_materials_cache = list(data.get("materials") or [])
        cls._system_index = dict(data.get("systems") or {})
        cls._system_roots = dict(data.get("roots") or {})
    except Exception as exc:
        logger.warning(f"Кэш каталога параметров не прочитан: {exc}")
        return False
    return bool(cls._attr_catalog)


def _save_disk_catalog(cls, tf2_root_dir: str) -> None:
    path = cls._attr_catalog_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": _CATALOG_FORMAT,
            "stamp": cls._game_stamp(tf2_root_dir),
            "catalog": {f"{g or ''}|{fn}": attrs
                        for (g, fn), attrs in cls._attr_catalog.items()},
            "display": {f"{g or ''}|{fn}": name
                        for (g, fn), name in cls._module_display.items()},
            "canonical": {f"{g or ''}|{fn}": names
                          for (g, fn), names in cls._attr_canonical.items()},
            "materials": cls._game_materials_cache or [],
            "systems": cls._system_index,
            "roots": cls._system_roots,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Кэш каталога параметров не сохранён: {exc}")


def build_attr_catalog(cls, tf2_root_dir: str) -> None:
    """
    Собирает каталог параметров для ВСЕХ модулей игры за один проход

    Скан под каждый модуль отдельно стоил бы пятисекундной паузы снова и
    снова, поэтому один скан на всё, и он переживает перезапуск приложения
    """
    if cls._attr_catalog or not tf2_root_dir:
        return
    if load_disk_catalog(cls, tf2_root_dir):
        return
    # Собираем в локальные словари и присваиваем целиком: сбор идёт в
    # фоне, а UI не должен видеть наполовину готовый каталог. Материалы
    # копим в том же проходе - PCF уже загружены, это бесплатно
    catalog: Dict[tuple, Dict[str, dict]] = {}
    canon: Dict[tuple, Dict[str, Dict[str, int]]] = {}
    materials: set = set()
    systems: Dict[str, str] = {}
    roots: Dict[str, str] = {}
    for pcf in cls.list_game_pcfs(tf2_root_dir):
        try:
            other = cls()
            other.load_from_game(tf2_root_dir, pcf)
        except Exception:
            continue
        _collect_catalog(cls, other, catalog, canon)
        for m in other.material_names():
            if _is_particle_material(m):
                materials.add(m)
        # Первый файл побеждает: `_dx80`-копии идут следом по алфавиту и
        # несут те же имена
        sys_json = other.systems_json()
        for name in sys_json:
            systems.setdefault(name, pcf)
        # Корень - верхний уровень дерева файла, потомку достаётся
        # первый корень, под которым он встретился: одна система бывает
        # ребёнком у нескольких эффектов
        tree = system_hierarchy(sys_json, order=other.system_names())
        tops = {name for name, _ in tree}

        def walk(kids, top):
            for name, sub in kids:
                if name not in tops:
                    roots.setdefault(name, top)
                walk(sub, top)
        for name, sub in tree:
            walk(sub, name)
    if catalog:
        cls._attr_catalog = catalog
        cls._system_index = systems
        cls._system_roots = roots
        # Побеждает самое частое написание (см. _canon)
        cls._attr_canonical = {
            key: {low: max(variants.items(), key=lambda kv: kv[1])[0]
                  for low, variants in names.items()}
            for key, names in canon.items()}
        cls._game_materials_cache = sorted(materials, key=str.lower)
        _save_disk_catalog(cls, tf2_root_dir)


def system_roots(cls, tf2_root_dir: str) -> Dict[str, str]:
    """{дочерняя система: корневая} - из того же каталога"""
    system_index(cls, tf2_root_dir)
    return cls._system_roots


def system_index(cls, tf2_root_dir: str) -> Dict[str, str]:
    """{имя системы: файл PCF} по всей игре - то, что уже собрано

    Скана не ждёт: с нуля он идёт 13 секунд, и страница за это время
    показывает то, что знает. Нет ничего - запускает сбор в фоне, с
    диска (после первого раза) каталог поднимается мгновенно
    """
    if cls._system_index or not tf2_root_dir:
        return cls._system_index
    if load_disk_catalog(cls, tf2_root_dir) and cls._system_index:
        return cls._system_index
    if cls._catalog_thread is None or not cls._catalog_thread.is_alive():
        cls._catalog_thread = threading.Thread(
            target=cls.build_attr_catalog, args=(tf2_root_dir,),
            name='particle-catalog', daemon=True)
        cls._catalog_thread.start()
    return cls._system_index


def track_range(entry: dict, value: Any) -> None:
    """Копит разброс числового параметра по эффектам игры

    Одного «примера» мало: по нему не понять, 0.1 - это норма или
    экзотика. Границы нужны и подсказке в дереве свойств, и справочнику
    для ИИ. bool считать бессмысленно, вектора и строки - пропускаем
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    entry["n"] = entry.get("n", 0) + 1
    lo, hi = entry.get("lo"), entry.get("hi")
    entry["lo"] = value if lo is None else min(lo, value)
    entry["hi"] = value if hi is None else max(hi, value)


def attr_stats(cls, group: Optional[str], function_name: str,
               attr_name: str) -> Optional[dict]:
    """
    Как этот параметр настроен в эффектах игры: {'lo','hi','n','v'}

    Только по уже собранному каталогу - сканирование не запускает
    (его греет фоновый воркер), поэтому годится для подсказок в UI.
    None - каталога нет, параметр не числовой или встречен один раз
    """
    key = (group, (function_name or "").strip().lower())
    entry = (cls._attr_catalog.get(key) or {}).get(
        (attr_name or "").strip().lower())
    if not entry or entry.get("n", 0) < 2 or entry.get("lo") is None:
        return None
    return entry


def _collect_catalog(cls, svc,
                     catalog: Dict[tuple, Dict[str, dict]],
                     canon: Optional[dict] = None) -> None:
    """Добавляет в каталог параметры всех модулей одного файла"""
    def _canon(key, el):
        """Копит ВАРИАНТЫ написания имён атрибутов со счётчиком

        Считаем, а не берём первое встреченное: собственный мод
        пользователя тоже лежит в VPK игры и может нести неверный
        регистр - побеждает написание, которое чаще у Valve"""
        if canon is None:
            return
        m = canon.setdefault(key, {})
        for a in el.values():
            per_name = m.setdefault(a.name.lower(), {})
            per_name[a.name] = per_name.get(a.name, 0) + 1

    for d in svc._all_definition_elements():
        sys_cat = catalog.setdefault((None, ""), {})
        for name, tv in element_attrs_to_json(d).items():
            if name not in SERVICE_ATTRS:
                track_range(sys_cat.setdefault(name, dict(tv)),
                                 tv["v"])
        _canon((None, ""), d)
        for group in MODULE_GROUPS:
            if group not in d:
                continue
            try:
                for mod in d[group].iter_elem():
                    fn = module_fn(mod)
                    cat = catalog.setdefault((group, fn), {})
                    mod_json = module_to_json(mod)
                    # Каноническое имя нужно для генерации пресетов:
                    # в ключах каталога оно приведено к нижнему регистру
                    cls._module_display.setdefault(
                        (group, fn), mod_json["functionName"])
                    _canon((group, fn), mod)
                    for name, tv in mod_json["attrs"].items():
                        if name not in SERVICE_ATTRS:
                            track_range(
                                cat.setdefault(name, dict(tv)), tv["v"])
            except Exception:
                continue


def module_attr_catalog(
    cls, group: Optional[str], function_name: str,
    tf2_root_dir: str = "", current=None,
) -> Dict[str, dict]:
    """
    Все параметры, которые встречаются у этого модуля в эффектах игры

    Список полей нигде не задекларирован, поэтому собираем его из
    стоковых PCF. Значение берём первое встреченное: оно заведомо
    осмысленное (так настроено у Valve) и годится как значение по
    умолчанию при добавлении. group=None - параметры самого определения
    системы
    """
    build_attr_catalog(cls, tf2_root_dir)
    key = (group, (function_name or "").strip().lower())
    catalog = dict(cls._attr_catalog.get(key) or {})
    # Открытый файл может знать поля, которых нет в стоке (чужой мод)
    if current is not None:
        probe: Dict[tuple, Dict[str, dict]] = {}
        _collect_catalog(cls, current, probe)
        for name, tv in (probe.get(key) or {}).items():
            catalog.setdefault(name, tv)
    return catalog


def group_module_catalog(cls, group: str, tf2_root_dir: str = "") -> List[str]:
    """
    Полный список модулей группы для диалога «Добавить модуль…»

    Ходовые (и понятные превью) идут первыми из MODULE_CATALOG, затем -
    ВСЕ остальные модули этой группы, что реально встречаются в эффектах
    игры (из _module_display, канонический регистр). Так в списке есть
    всё, а частое - под рукой
    """
    curated = list(MODULE_CATALOG.get(group, []))
    seen = {name.lower() for name in curated}
    build_attr_catalog(cls, tf2_root_dir)
    rest = []
    for (g, fn), display in cls._module_display.items():
        if g == group and fn not in seen:
            rest.append(display)
            seen.add(fn)
    return curated + sorted(rest, key=str.lower)


def missing_attrs(
    pcf, system_name: str, group: Optional[str], module_index: int,
    tf2_root_dir: str = "",
) -> Dict[str, dict]:
    """Параметры из каталога, которых у этого модуля/системы ещё нет"""
    d = pcf._find_definition(system_name)
    if d is None:
        return {}
    el = d
    fn = ""
    if group is not None:
        if group not in d:
            return {}
        try:
            el = list(d[group].iter_elem())[module_index]
        except (IndexError, Exception):
            return {}
        fn = module_fn(el)
    catalog = pcf.module_attr_catalog(group, fn, tf2_root_dir, current=pcf)
    return {name: tv for name, tv in catalog.items() if name not in el}
