"""Сток: игровая версия открытого файла, сравнение с ней и откат"""

import os
from typing import Any, Dict, List, Optional

from src.services.particle_editor.pcf_format import (
    MODULE_GROUPS, SERVICE_ATTRS, Attribute, Element, ValueType, copy_module,
    element_attrs_to_json)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _same_value(a: Any, b: Any) -> bool:
    """Значения атрибутов равны. Числа - с допуском: float32 из файла и
    число из поля отличаются в седьмом знаке"""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same_value(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-5 * max(1.0, abs(a), abs(b))
    return a == b


def _diff_attrs(cur: Dict[str, dict], ref: Dict[str, dict]) -> List[str]:
    """Имена атрибутов, где текущее отличается от стокового (или его нет)"""
    out = []
    for name, tv in cur.items():
        if name.lower() in SERVICE_ATTRS:
            continue
        other = ref.get(name)
        if other is None or not _same_value(tv.get("v"), other.get("v")):
            out.append(name)
    return out


def diff_systems(current: Dict[str, dict],
                 stock: Dict[str, dict]) -> Dict[str, dict]:
    """Чем открытый файл отличается от игрового, по системам

    Модули сопоставляются по functionName и порядковому номеру среди
    одноимённых: два Remap в одной группе - это два разных модуля

    Returns:
        {имя: {"status": added|changed|same, "attrs": [имена],
               "modules": {группа: {индекс: {"status": added|changed,
                                             "attrs": [имена]}}},
               "removed": {группа: [functionName, ...]},
               "children": bool}}
    """
    out: Dict[str, dict] = {}
    for name, cur in current.items():
        ref = stock.get(name)
        if ref is None:
            out[name] = {"status": "added", "attrs": [], "modules": {},
                         "removed": {}, "children": False}
            continue
        entry = {"attrs": _diff_attrs(cur.get("attrs") or {},
                                      ref.get("attrs") or {}),
                 "modules": {}, "removed": {}}
        for group in MODULE_GROUPS:
            ref_mods = ref.get(group) or []
            used: set = set()
            for idx, mod in enumerate(cur.get(group) or []):
                fn = (mod.get("functionName") or "").lower()
                match = next((j for j, m in enumerate(ref_mods)
                              if j not in used
                              and (m.get("functionName") or "").lower() == fn),
                             None)
                if match is None:
                    entry["modules"].setdefault(group, {})[idx] = {
                        "status": "added", "attrs": []}
                    continue
                used.add(match)
                changed = _diff_attrs(mod.get("attrs") or {},
                                      ref_mods[match].get("attrs") or {})
                if changed:
                    entry["modules"].setdefault(group, {})[idx] = {
                        "status": "changed", "attrs": changed}
            gone = [m.get("functionName") or m.get("name") or "?"
                    for j, m in enumerate(ref_mods) if j not in used]
            if gone:
                entry["removed"][group] = gone
        kids = [c.get("childName") for c in cur.get("children") or []]
        ref_kids = [c.get("childName") for c in ref.get("children") or []]
        entry["children"] = kids != ref_kids
        entry["status"] = ("changed" if entry["attrs"] or entry["modules"]
                           or entry["removed"] or entry["children"]
                           else "same")
        out[name] = entry
    return out


def stock_path(pcf) -> str:
    """Путь игрового PCF, с которым сравнивать. Пусто - стока нет

    Файл из игры - он сам, файл с диска - игровой с тем же именем, если
    такой есть (чужой crit.pcf сравниваем с crit.pcf Valve)
    """
    src = pcf.source_path or ""
    if src.startswith("vpk:"):
        return src[4:]
    base = os.path.basename(src).lower()
    return f"particles/{base}" if base.endswith(".pcf") else ""


def stock(pcf, tf2_root_dir: str):
    """Игровая версия открытого файла. None - её нет или не читается"""
    path = pcf.stock_path()
    if not path:
        return None
    cached = pcf._stock
    if cached is not None and cached[0] == path:
        return cached[1]
    svc = None
    try:
        svc = type(pcf)()
        svc.load_from_game(tf2_root_dir, path)
    except Exception as exc:                          # noqa: BLE001
        logger.info(f"стока для {path} нет: {exc}")
        svc = None
    pcf._stock = (path, svc)
    return svc


def stock_diff(pcf, tf2_root_dir: str) -> Dict[str, dict]:
    """Отличия от игры по системам (см. diff_systems). Пусто - стока нет"""
    stock = pcf.stock(tf2_root_dir)
    if stock is None:
        return {}
    cached = pcf._stock_systems
    if cached is None:
        cached = pcf._stock_systems = stock.systems_json()
    return diff_systems(pcf.systems_json(), cached)


def revert_system(pcf, tf2_root_dir: str, system_name: str) -> bool:
    """Возвращает систему в игровой вид: атрибуты, модули, дочерние

    Дочерние - ссылки на другие системы этого же файла, берём их по
    имени, и если такой системы у нас больше нет, ссылку пропускаем
    """
    stock = pcf.stock(tf2_root_dir)
    d = pcf._find_definition(system_name)
    ref = stock._find_definition(system_name) if stock else None
    if d is None or ref is None:
        return False
    for key in list(d.keys()):
        if key not in MODULE_GROUPS and key != "children":
            del d[key]
    for attr in ref.values():
        if attr.name in MODULE_GROUPS or attr.name == "children":
            continue
        d[attr.name] = attr.copy()
    # Пустой список srctools не типизирует (ловушка: `el[group] = []`
    # падает) - массив заводим явно и наполняем.
    # Модули у Valve общие между системами: берём наш же элемент с тем
    # же uuid, если он ещё жив у соседей, - иначе файл раздувался бы
    # копиями и переставал влезать в потолок казуала
    mine_by_uuid = {}
    for other in pcf._all_definition_elements():
        for group in MODULE_GROUPS:
            if group in other:
                for m in other[group].iter_elem():
                    mine_by_uuid.setdefault(m.uuid, m)
    for group in MODULE_GROUPS:
        if group in d:
            del d[group]
        if group in ref:
            arr = Attribute.array(ref[group].name, ValueType.ELEMENT)
            for m in ref[group].iter_elem():
                same = mine_by_uuid.get(m.uuid)
                if same is not None and not _diff_attrs(
                        element_attrs_to_json(same),
                        element_attrs_to_json(m)):
                    arr.append(same)
                else:
                    copy = copy_module(m)
                    copy.uuid = m.uuid
                    arr.append(copy)
            d[ref[group].name] = arr
    if "children" in d:
        del d["children"]
    if "children" in ref:
        d[ref["children"].name] = _copy_children(pcf, ref, mine_by_uuid, {})
    return True


def _copy_children(pcf, ref, mine_by_uuid: dict, done: dict):
    """Ссылки на дочерние из стока - на НАШИ системы с теми же именами

    Дочерняя, которой у нас больше нет (отцепили единственную ссылку -
    и определение ушло из дерева), копируется из стока целиком, вместе
    со своими модулями и детьми. `done` - уже скопированные, от циклов
    """
    arr = Attribute.array(ref["children"].name, ValueType.ELEMENT)
    for ch in ref["children"].iter_elem():
        try:
            child = ch["child"].val_elem
        except Exception:
            continue
        mine = pcf._find_definition(child.name)
        if mine is None:
            mine = _copy_definition(pcf, child, mine_by_uuid, done)
        new = Element(ch.name, ch.type, ch.uuid)
        for attr in ch.values():
            new[attr.name] = (Attribute(attr.name, ValueType.ELEMENT, mine)
                              if attr.name.lower() == "child"
                              else attr.copy())
        arr.append(new)
    return arr


def _copy_definition(pcf, ref, mine_by_uuid: dict, done: dict):
    """Отвязанная копия определения системы из стока (с модулями и детьми)"""
    if ref.uuid in done:
        return done[ref.uuid]
    new = Element(ref.name, ref.type, ref.uuid)
    done[ref.uuid] = new
    for attr in ref.values():
        if attr.name in MODULE_GROUPS or attr.name == "children":
            continue
        new[attr.name] = attr.copy()
    for group in MODULE_GROUPS:
        if group not in ref:
            continue
        arr = Attribute.array(ref[group].name, ValueType.ELEMENT)
        for m in ref[group].iter_elem():
            same = mine_by_uuid.get(m.uuid)
            if same is None:
                same = copy_module(m)
                same.uuid = m.uuid
            arr.append(same)
        new[ref[group].name] = arr
    if "children" in ref:
        new[ref["children"].name] = _copy_children(pcf, ref, mine_by_uuid, done)
    return new


def revert_attr(pcf, tf2_root_dir: str, system_name: str,
                group: Optional[str], module_index: int,
                attr_name: str) -> bool:
    """Значение атрибута как в игре, в игре его нет - убираем"""
    stock = pcf.stock(tf2_root_dir)
    if stock is None:
        return False
    stock_json = stock.systems_json().get(system_name)
    if stock_json is None:
        return False
    cur = pcf.systems_json().get(system_name) or {}
    if group is None:
        ref_attrs = stock_json.get("attrs") or {}
    else:
        mods = cur.get(group) or []
        if module_index >= len(mods):
            return False
        fn = (mods[module_index].get("functionName") or "").lower()
        nth = sum(1 for m in mods[:module_index]
                  if (m.get("functionName") or "").lower() == fn)
        same = [m for m in stock_json.get(group) or []
                if (m.get("functionName") or "").lower() == fn]
        if nth >= len(same):
            return False
        ref_attrs = same[nth].get("attrs") or {}
    tv = ref_attrs.get(attr_name)
    if tv is None:
        return pcf.remove_attr(system_name, group, module_index, attr_name)
    return pcf.ensure_attr(system_name, group, module_index, attr_name,
                            tv["t"], tv["v"])
