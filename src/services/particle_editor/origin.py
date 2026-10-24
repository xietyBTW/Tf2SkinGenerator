"""
Точка «начало эффекта»: весь эффект едет одним смещением

Двигать эффект местами рождения нельзя: вращение вокруг оси, притяжение,
ограничение расстояния, привязка и точки, которые эффект ставит сам, опираются
на точку 0 - место крепления. Так устроена примерно треть эффектов
(item_fx, invasion_unusuals, halloween: 93 из 265). Поэтому корень получает
оператор Valve Set Control Point Positions: точка N = точка 0 + смещение в
осях точки 0, и ссылки эффекта на место точки 0 переводятся на N.

Не переводится то, что берёт у точки 0 оси (скорость в локальных осях,
lock rotation): новая точка у Valve поворот точки 0 не получает (оракул,
--forward), и в игре такой модуль перестал бы поворачиваться с головой. Если
такой модуль задаёт место рождения, системе добавляется смещение в осях
точки 0 на ту же величину. Не переводится и система, чью точку 0 ставит
предок по своим частицам: там 0 - это не место крепления.
"""

import re
from typing import Dict, List, Optional, Tuple

from src.services.particle_editor.attr_edit import module_for_edit
from src.services.particle_editor.pcf_format import Attribute, ValueType, module_fn
from src.services.particle_editor.structure import (
    _kid_refs, add_module, own_effect_children)

#: Имена своих модулей: по ним превью узнаёт их при следующем перетаскивании
ORIGIN_OP = "Effect origin"
ORIGIN_OFFSET = "Effect origin offset"

#: Атрибуты, которыми модуль берёт у точки МЕСТО
_PLACE_ATTRS = {
    "control_point_number", "control point number", "control point",
    "start control point number", "end control point number",
    "control point to offset positions from",
}
#: Модули, которые читают у точки значение, скорость или модель на ней, а не
#: место: у новой точки нет ни скорости игрока, ни хитбоксов шапки
_VALUE_FNS = {
    "lifetime from control point life time", "velocity inherit from control point",
    "remap cp speed to cp", "color light from control point",
    "set control point to player", "assign target cp",
    "position on model random", "movement lock to bone", "cull relative to model",
}
#: Модули, которые берут у точки поворот по самой своей работе
_AXES_FNS = {"normal lock to control point", "remap control point direction to vector"}
#: Флаги поворота без слова «local» в имени
_AXES_FLAGS = {"lock rotation"}
#: Инициализаторы, задающие место рождения (первый из них и действует)
_PLACE_SETTERS = {
    "position within sphere random", "position within box random",
    "position along path sequential", "position along path random",
    "move particles between 2 control points",
}
#: Модули, которые считают точки эффекта: новая точка изменила бы у них
#: число частиц или разброс
_COUNTS_POINTS = ("scale emission to used control points",
                  "randomly distribute to highest supplied control point")
#: Точек у системы Source не больше 64
_MAX_CP = 63
_GROUPS = ("initializers", "operators", "forces", "constraints")
_SLOTS = ("first", "second", "third", "fourth")


def find_origin(root) -> Optional[int]:
    """Номер оператора «начало эффекта» у корня"""
    if "operators" not in root:
        return None
    for i, mod in enumerate(root["operators"].iter_elem()):
        if mod.name == ORIGIN_OP:
            return i
    return None


def _int(el, name: str, default: int = 0) -> int:
    try:
        return int(el[name].val_int) if name in el else default
    except Exception:
        return default


def _uses_axes(mod) -> bool:
    """Берёт ли модуль у точки оси: флаг «local» или поворота включён, вектор
    в локальных осях не ноль, или модуль поворотом и работает"""
    if module_fn(mod) in _AXES_FNS:
        return True
    for attr in mod.values():
        name = attr.name.casefold()
        if "local" not in name and name not in _AXES_FLAGS:
            continue
        try:
            if attr.type.name.lower() == "vec3":
                if any(abs(x) > 1e-6 for x in attr.val_vec3):
                    return True
            elif attr.val_bool:
                return True
        except Exception:
            continue
    return False


def _effect(root) -> List[Tuple["Element", set]]:
    """Системы эффекта от корня вниз и точки, которые им ставят предки по
    своим частицам (Set child control points from particle positions)"""
    out, seen, queue = [], {id(root)}, [(root, set())]
    while queue:
        el, driven = queue.pop(0)
        out.append((el, driven))
        passed = set(driven)
        if "operators" in el:
            for op in el["operators"].iter_elem():
                if module_fn(op) == "set child control points from particle positions":
                    first = _int(op, "first control point to set")
                    count = _int(op, "# of control points to set", 1)
                    passed.update(range(first, first + count))
        for _, kid in _kid_refs(el):
            if kid is not None and id(kid) not in seen:
                seen.add(id(kid))
                queue.append((kid, passed))
    return out


def _free_point(systems) -> Optional[int]:
    """Точка, которой эффект не касается: на одну больше старшей упомянутой"""
    top = 0
    for el, _ in systems:
        for group in _GROUPS + ("emitters", "renderers"):
            if group not in el:
                continue
            for mod in el[group].iter_elem():
                count = _int(mod, "# of control points to set", 1)
                for attr in mod.values():
                    name = attr.name.casefold()
                    if ("control point" not in name and "control_point" not in name
                            and not re.search(r"\bcp\b", name)):
                        continue
                    if name.startswith("#"):
                        continue
                    value = _int(mod, attr.name, 0)
                    if name == "first control point to set":
                        value += count - 1
                    top = max(top, value)
    n = top + 1
    return n if n <= _MAX_CP else None


def _counts_points(systems) -> bool:
    for el, _ in systems:
        for group in _GROUPS + ("emitters",):
            if group not in el:
                continue
            for mod in el[group].iter_elem():
                for attr in mod.values():
                    if attr.name.casefold() not in _COUNTS_POINTS:
                        continue
                    try:
                        if attr.val_float:
                            return True
                    except Exception:
                        continue
    return False


def _set(el, name: str, attr) -> None:
    """Пишет атрибут под тем написанием имени, что уже есть в шаблоне:
    srctools берёт имя у ключа"""
    same = next((a.name for a in el.values() if a.name.casefold() == name.casefold()), name)
    el[same] = attr


def _add_origin_op(pcf, root_name: str, root, cp: int, tf2_root_dir: str) -> bool:
    """Оператор первым в списке: точку N должны видеть все операторы кадра"""
    if not add_module(pcf, root_name, "operators", "Set Control Point Positions",
                      tf2_root_dir):
        return False
    mods = list(root["operators"].iter_elem())
    op = mods.pop()
    op.name = ORIGIN_OP
    # Окна включения из шаблона: точка должна стоять всё время жизни эффекта
    for a in list(op.values()):
        if a.name.casefold().startswith("operator ") and "fade" in a.name.casefold():
            op[a.name] = Attribute.float(a.name, 0.0)
    _set(op, "control point to offset positions from", Attribute.int("x", 0))
    _set(op, "set positions in world space", Attribute.bool("x", False))
    # Все четыре слота - на одну точку: незаданный слот у Valve ставит
    # точки 2-4 в свои места и сломал бы эффект, который ими пользуется
    for slot in _SLOTS:
        _set(op, f"{slot} control point number", Attribute.int("x", cp))
        _set(op, f"{slot} control point parent", Attribute.int("x", 0))
        _set(op, f"{slot} control point location", Attribute.vec3("x", [0.0, 0.0, 0.0]))
    arr = Attribute.array(root["operators"].name, ValueType.ELEMENT)
    for m in [op] + mods:
        arr.append(m)
    root[root["operators"].name] = arr
    return True


def _retarget(pcf, el, driven: set, cp: int) -> bool:
    """Переводит ссылки системы на место точки 0 на точку cp. True - место
    рождения осталось у точки 0 (модуль берёт оси) и нужно смещение"""
    if 0 in driven:
        return False
    keeps_place = False
    first_setter = True
    for group in _GROUPS:
        if group not in el:
            continue
        for i, mod in enumerate(list(el[group].iter_elem())):
            fn = module_fn(mod)
            if mod.name == ORIGIN_OP or fn in _VALUE_FNS:
                continue
            setter = group == "initializers" and fn in _PLACE_SETTERS
            names = [a.name for a in mod.values()
                     if a.name.casefold() in _PLACE_ATTRS and _int(mod, a.name, -1) == 0]
            if setter and first_setter:
                first_setter = False
                if names and _uses_axes(mod):
                    keeps_place = True
            if not names or _uses_axes(mod):
                continue
            own = module_for_edit(pcf, el, group, i)
            if own is None:
                continue
            for name in names:
                own[name] = Attribute.int(name, cp)
    return keeps_place


def ensure_effect_origin(pcf, root_name: str, tf2_root_dir: str = "") -> Dict:
    """
    Ставит эффекту точку «начало эффекта», если её ещё нет

    Возвращает {"cp": N} или {"error": текст}; noOrigin - точку ставить
    нельзя, гизмо двигает места рождения. Общие с чужим эффектом
    системы сначала получают свои копии: перевод ссылок задел бы соседа
    """
    root = pcf._find_definition(root_name)
    if root is None:
        return {"error": f"система не найдена: {root_name}"}
    found = find_origin(root)
    if found is not None:
        op = list(root["operators"].iter_elem())[found]
        return {"cp": _int(op, "first control point number")}

    if _counts_points(_effect(root)):
        return {"error": "эффект считает свои точки", "noOrigin": True}
    systems = _effect(root)
    # Точку ищем до копий: копии номеров не меняют, а ошибка не должна
    # оставлять их в файле
    cp = _free_point(systems)
    if cp is None:
        return {"error": "у эффекта заняты все точки"}
    own_effect_children(pcf, root_name, [el.name for el, _ in systems])
    systems = _effect(root)
    if not _add_origin_op(pcf, root_name, root, cp, tf2_root_dir):
        return {"error": "не удалось добавить Set Control Point Positions"}
    for el, driven in systems:
        if not _retarget(pcf, el, driven, cp):
            continue
        if not add_module(pcf, el.name, "initializers",
                          "Position Modify Offset Random", tf2_root_dir):
            continue
        off = list(el["initializers"].iter_elem())[-1]
        off.name = ORIGIN_OFFSET
        _set(off, "control_point_number", Attribute.int("control_point_number", 0))
        _set(off, "offset in local space 0/1", Attribute.bool("offset in local space 0/1", True))
        _set(off, "offset proportional to radius 0/1",
             Attribute.bool("offset proportional to radius 0/1", False))
        _set(off, "offset min", Attribute.vec3("offset min", [0.0, 0.0, 0.0]))
        _set(off, "offset max", Attribute.vec3("offset max", [0.0, 0.0, 0.0]))
    return {"cp": cp}
