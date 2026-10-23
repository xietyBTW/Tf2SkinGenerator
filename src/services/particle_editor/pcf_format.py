"""Формат PCF: DMX-атрибуты <-> JSON, элементы модулей, ключ материала

Общий слой, на котором стоят все соавторы документа: сами они друг о
друге не знают, а этот модуль знают все"""

import re
from typing import Any, Dict, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

try:
    from srctools.dmx import Attribute, Element, ValueType
    SRCTOOLS_AVAILABLE = True
except ImportError:
    SRCTOOLS_AVAILABLE = False
    Attribute = Element = ValueType = None  # type: ignore


#: Группы модулей внутри определения системы частиц
MODULE_GROUPS = (
    "renderers", "operators", "initializers", "emitters", "forces", "constraints",
)


#: Служебные поля - их не показываем и не даём удалять
SERVICE_ATTRS = ("functionname", "name", "id")


def norm_mat(name: str, ext: str = ".vmt") -> str:
    """Материал -> нормализованный rel-путь под materials/ (effects/crit.vmt)

    Ключ для сопоставления материалов с разным регистром и разделителями.
    Задвоенные разделители схлопываются: в PCF стока встречается
    `effects\\\\crit` (а у эффекта из мастерской - задвоенные во ВСЕХ
    сегментах), и без этого `effects//crit.vmt` считался бы другим материалом,
    которого в архиве нет - крит-эффект оставался без текстуры
    """
    n = re.sub(r"[\\/]+", "/", (name or "").strip()).strip("/").lower()
    if not n:
        return ""
    if not n.endswith(ext):
        n += ext
    if n.startswith("materials/"):
        n = n[len("materials/"):]
    return n


# Конвертация атрибутов DMX -> JSON

def attr_scalar_to_json(attr) -> Any:
    """Значение скалярного атрибута -> JSON-совместимое значение"""
    vt = attr.type
    if vt is ValueType.COLOR:
        c = attr.val_color
        return [c.r, c.g, c.b, c.a]
    if vt is ValueType.BOOL:
        return attr.val_bool
    if vt is ValueType.INTEGER:
        return attr.val_int
    if vt in (ValueType.FLOAT, ValueType.TIME):
        return attr.val_float
    if vt is ValueType.STRING:
        return attr.val_str
    return None


def attr_to_json(attr) -> Optional[dict]:
    """Атрибут DMX -> {"t": тип, "v": значение} либо None для несериализуемых"""
    vt = attr.type
    if vt in (ValueType.ELEMENT, ValueType.BINARY, ValueType.MATRIX,
              ValueType.QUATERNION):
        return None
    type_name = vt.name.lower()
    if attr.is_array:
        if vt is ValueType.FLOAT:
            return {"t": "float_array", "v": list(attr.iter_float())}
        if vt is ValueType.INTEGER:
            return {"t": "int_array", "v": list(attr.iter_int())}
        return None
    if vt is ValueType.VEC3:
        return {"t": "vec3", "v": list(attr.val_vec3)}
    if vt is ValueType.VEC2:
        return {"t": "vec2", "v": list(attr.val_vec2)}
    if vt is ValueType.VEC4:
        return {"t": "vec4", "v": list(attr.val_vec4)}
    val = attr_scalar_to_json(attr)
    if val is None and vt is not ValueType.STRING:
        return None
    return {"t": type_name, "v": val}


def element_attrs_to_json(el) -> Dict[str, dict]:
    """Все скалярные атрибуты элемента -> {имя: {"t","v"}} (модульные группы пропускаются)"""
    out: Dict[str, dict] = {}
    for key in el.keys():
        if key in MODULE_GROUPS or key == "children":
            continue
        j = attr_to_json(el[key])
        if j is not None:
            out[key] = j
    return out


def module_to_json(el) -> dict:
    """Модуль (оператор/инициализатор/...) -> JSON с functionName и атрибутами"""
    attrs = element_attrs_to_json(el)
    # srctools хранит имена атрибутов в нижнем регистре
    fn = attrs.get("functionname", {}).get("v") or el.name
    return {"functionName": fn, "name": el.name, "attrs": attrs}


def attr_from_json(name: str, tv: dict) -> Optional["Attribute"]:
    """{"t","v"} из systems_json -> Attribute (None - неизвестный тип/битое значение)"""
    t, v = tv.get("t"), tv.get("v")
    try:
        if t == "color":
            r, g, b, a = (list(v) + [255])[:4]
            return Attribute.color(name, int(r), int(g), int(b), int(a))
        if t == "vec3":
            return Attribute.vec3(name, [float(x) for x in v])
        if t == "vec2":
            return Attribute.vec2(name, [float(x) for x in v])
        if t == "vec4":
            return Attribute.vec4(name, [float(x) for x in v])
        if t == "bool":
            return Attribute.bool(name, bool(v))
        if t == "integer":
            return Attribute.int(name, int(v))
        if t == "time":
            return Attribute.time(name, float(v))
        if t == "float":
            return Attribute.float(name, float(v))
        if t == "string":
            return Attribute.string(name, str(v))
        if t == "float_array":
            return Attribute.array(name, ValueType.FLOAT,
                                   [float(x) for x in v])
        if t == "int_array":
            return Attribute.array(name, ValueType.INTEGER,
                                   [int(x) for x in v])
    except (TypeError, ValueError) as exc:
        logger.warning(f"Вставка атрибута {name}={v!r}: {exc}")
    return None


def copy_module(el) -> "Element":
    """Отвязанная копия модуля: все атрибуты копируются по значению

    Ключ - ОРИГИНАЛЬНОЕ имя атрибута (el.keys() отдаёт casefold-ключи,
    присваивание по ним затирало бы регистр имён в файле)"""
    new = Element(el.name, el.type)
    for attr in el.values():
        new[attr.name] = attr.copy()
    return new


def module_fn(mod) -> str:
    """functionName модуля (нижний регистр) с фолбэком на имя элемента"""
    fn = ""
    if "functionname" in mod:
        try:
            fn = mod["functionname"].val_str
        except Exception:
            fn = ""
    return (fn or mod.name or "").strip().lower()


def make_module(function_name: str, element_type: str, attrs: list) -> "Element":
    """Модуль из functionName и готовых Attribute"""
    el = Element(function_name, element_type)
    el["functionName"] = Attribute.string("functionName", function_name)
    for attr in attrs:
        el[attr.name] = attr
    return el
