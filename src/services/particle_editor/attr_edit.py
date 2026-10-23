"""Правка значений: атрибуты системы и модулей, отвязка общих модулей"""

from typing import Any, Optional

from src.services.particle_editor.pcf_format import (
    MODULE_GROUPS, SERVICE_ATTRS, Attribute, ValueType, attr_from_json,
    copy_module, module_fn)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def set_attr(
    pcf,
    system_name: str,
    group: Optional[str],
    module_index: int,
    attr_name: str,
    value: Any,
) -> bool:
    """
    Меняет значение существующего атрибута

    Args:
        system_name:  имя системы частиц
        group:        группа модулей (из MODULE_GROUPS) либо None -
                      атрибут самой системы
        module_index: индекс модуля в группе (игнорируется при group=None)
        attr_name:    имя атрибута
        value:        новое значение из GUI: число, bool, строка,
                      [x,y,z] для vec3, [r,g,b,a] 0-255 для color

    Returns:
        True если атрибут найден и обновлён
    """
    d = pcf._find_definition(system_name)
    if d is None:
        return False
    el = d
    if group is not None:
        el = module_for_edit(pcf, d, group, module_index)
        if el is None:
            return False
    if attr_name not in el:
        return False

    # Пересоздаём атрибут с ИСХОДНЫМ именем (ключи srctools casefold-ятся,
    # а в файле имя должно остаться как было) и исходным типом
    orig_name = el[attr_name].name
    vt = el[attr_name].type
    try:
        if vt is ValueType.COLOR:
            r, g, b, a = [max(0, min(255, int(x))) for x in value]
            el[attr_name] = Attribute.color(orig_name, r, g, b, a)
        elif vt is ValueType.VEC3:
            x, y, z = [float(v) for v in value]
            el[attr_name] = Attribute.vec3(orig_name, x, y, z)
        elif vt is ValueType.BOOL:
            el[attr_name] = Attribute.bool(orig_name, bool(value))
        elif vt is ValueType.INTEGER:
            el[attr_name] = Attribute.int(orig_name, int(value))
        elif vt is ValueType.TIME:
            el[attr_name] = Attribute.time(orig_name, float(value))
        elif vt is ValueType.FLOAT:
            el[attr_name] = Attribute.float(orig_name, float(value))
        elif vt is ValueType.STRING:
            el[attr_name] = Attribute.string(orig_name, str(value))
        else:
            return False
    except (TypeError, ValueError) as exc:
        logger.warning(f"set_attr({system_name}.{attr_name}={value!r}): {exc}")
        return False
    return True


def ensure_attr(
    pcf, system_name: str, group: Optional[str], module_index: int,
    attr_name: str, attr_type: str, value: Any,
) -> bool:
    """
    set_attr; если атрибута нет - создаёт его с заданным DMX-типом.
    Нужно простому режиму: крутилка должна работать и на модуле,
    у которого этот атрибут ещё не записан (игра держит его в дефолте)
    """
    if set_attr(pcf, system_name, group, module_index, attr_name, value):
        return True
    d = pcf._find_definition(system_name)
    if d is None:
        return False
    el = d
    if group is not None:
        el = module_for_edit(pcf, d, group, module_index)
        if el is None:
            return False
    if attr_name in el:
        return False   # атрибут есть, но set_attr отверг значение
    # Новый атрибут - в написании игры, иначе Source его не прочитает
    canon = pcf.canonical_attr_name(
        group, module_fn(el) if group else "", attr_name)
    attr = attr_from_json(canon, {"t": attr_type, "v": value})
    if attr is None:
        return False
    el[canon] = attr
    return True


def remove_attr(pcf, system_name: str, group: Optional[str],
                module_index: int, attr_name: str) -> bool:
    """
    Удаляет параметр - значение возвращается к умолчанию движка

    Полезно вдвойне: убирает лишнее и уменьшает PCF (для казуала файл
    не должен превышать оригинальный)
    """
    if (attr_name or "").lower() in SERVICE_ATTRS:
        return False
    d = pcf._find_definition(system_name)
    if d is None:
        return False
    el = d
    if group is not None:
        el = module_for_edit(pcf, d, group, module_index)
        if el is None:
            return False
    if attr_name not in el:
        return False
    del el[attr_name]
    return True


def module_owners(pcf, mod) -> int:
    """Сколько раз модуль встречается по группам всех систем

    Valve делит элементы модулей между системами: в crit.pcf один
    «Alpha Fade and Decay» стоит у десяти определений сразу
    """
    count = 0
    for d in pcf._all_definition_elements():
        for group in MODULE_GROUPS:
            if group not in d:
                continue
            try:
                count += sum(1 for m in d[group].iter_elem() if m is mod)
            except Exception:
                continue
    return count


def module_for_edit(pcf, d, group: str, index: int):
    """Модуль системы под правку - свой, а не общий с другими

    Общий элемент подменяется в ЭТОЙ системе отвязанной копией: иначе
    правка end_alpha у crit_text молча меняла hit_text, miss_text и ещё
    семь систем, делящих с ней тот же оператор. None - модуля нет
    """
    if group not in d:
        return None
    try:
        mods = list(d[group].iter_elem())
        mod = mods[index]
    except (IndexError, Exception):
        return None
    if module_owners(pcf, mod) <= 1:
        return mod
    mods[index] = copy_module(mod)
    arr = Attribute.array(d[group].name, ValueType.ELEMENT)
    for m in mods:
        arr.append(m)
    d[d[group].name] = arr
    return mods[index]
