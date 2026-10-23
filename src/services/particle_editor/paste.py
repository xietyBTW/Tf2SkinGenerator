"""Вставка скопированного набора параметров в систему"""

from typing import Dict, Optional

from src.services.particle_editor.pcf_format import (
    MODULE_GROUPS, Attribute, Element, ValueType, attr_from_json, module_fn)


def _paste_attrs(pcf, el, attrs: Dict[str, dict], overwrite: bool = True,
                 report: Optional[list] = None,
                 where: str = "", group: Optional[str] = None) -> bool:
    """Merge-вставка атрибутов в элемент: новые добавляются, совпадающие
    перезаписываются (overwrite=False - существующие не трогаются)

    report - сюда складываются проблемы, чтобы вставка не проваливалась
    молча: битые значения видны пользователю"""
    changed = False
    if not isinstance(attrs, dict):
        if report is not None:
            report.append(("particles_paste_bad_attrs", {"where": where}))
        return False
    for name, tv in attrs.items():
        if str(name).lower() in ("functionname", "name", "id"):
            continue
        if not isinstance(tv, dict) or "v" not in tv:
            if report is not None:
                report.append(("particles_paste_bad_value",
                               {"where": where, "attr": name}))
            continue
        if not overwrite and name in el:
            continue
        # Существующий атрибут сохраняет своё написание; НОВЫЙ создаём
        # в написании игры, иначе Source его не увидит
        orig_name = (el[name].name if name in el
                     else pcf.canonical_attr_name(
                         group, module_fn(el) if group else "", name))
        attr = attr_from_json(orig_name, tv)
        if attr is None:
            if report is not None:
                report.append(("particles_paste_bad_value",
                               {"where": where, "attr": name}))
            continue
        # Кладём ПО КАНОНИЧЕСКОМУ ключу: srctools пишет в файл имя ключа,
        # а Source читает атрибуты с учётом регистра
        el[orig_name] = attr
        changed = True
    return changed


def paste_params(pcf, system_name: str, payload: dict,
                 mode: str = "overwrite",
                 report: Optional[list] = None) -> bool:
    """
    Вставляет скопированный набор параметров в систему

    payload - формат буфера копирования панели:
        {"attrs": {имя: {"t","v"}},
         "modules": {группа: [[functionName, {имя: {"t","v"}}], ...]}}
    (легаси-формат {группа: {functionName: attrs}} тоже принимается -
    старые копии в буфере обмена)

    mode:
        "overwrite" - merge, совпадающие имена перезаписываются молча;
        "keep"      - merge, существующие параметры цели не трогаются,
                      добавляются только недостающие;
        "replace"   - параметры и модули цели удаляются, остаются только
                      вставляемые (children и имя системы сохраняются)

    Модуль ищется по functionName с учётом номера вхождения (у эффектов
    бывает два одинаковых модуля, напр. Remap Noise to Scalar), нет
    такого - создаётся новый
    """
    d = pcf._find_definition(system_name)
    if d is None:
        return False
    overwrite = mode != "keep"
    changed = mode == "replace" and _clear_for_replace(d)
    if _paste_attrs(pcf, d, payload.get("attrs") or {}, overwrite,
                    report, where="attrs", group=None):
        changed = True
    modules = payload.get("modules") or {}
    if not isinstance(modules, dict):
        if report is not None:
            report.append(("particles_paste_bad_modules", {}))
        modules = {}
    for group, mods in modules.items():
        pairs = _module_pairs(group, mods, report)
        if pairs is not None and _paste_group(pcf, d, group, pairs,
                                              overwrite, report):
            changed = True
    return changed


def _clear_for_replace(d) -> bool:
    """Режим "replace": сносим скалярные атрибуты (кроме имени) и все
    группы модулей; children и прочие element-ссылки не трогаем"""
    changed = False
    for key in list(d.keys()):
        if key in ("name", "id"):
            continue
        if key in MODULE_GROUPS:
            d[key] = Attribute.array(d[key].name, ValueType.ELEMENT)
        elif d[key].type is not ValueType.ELEMENT:
            del d[key]
        changed = True
    return changed


def _module_pairs(group, mods, report: Optional[list]) -> Optional[list]:
    """Пары [functionName, attrs] группы из буфера; None - группа негодная"""
    if group not in MODULE_GROUPS:
        if report is not None:
            report.append(("particles_paste_unknown_group",
                           {"group": group,
                            "known": ", ".join(MODULE_GROUPS)}))
        return None
    try:
        return list(mods.items() if isinstance(mods, dict) else mods)
    except TypeError:
        if report is not None:
            report.append(("particles_paste_bad_group",
                           {"group": group}))
        return None


def _paste_group(pcf, d, group: str, pairs: list, overwrite: bool,
                 report: Optional[list]) -> bool:
    """Вставляет модули одной группы; True - система изменилась"""
    changed = False
    occurrence: Dict[str, int] = {}
    for pair in pairs:
        try:
            fn, attrs = pair
        except (TypeError, ValueError):
            if report is not None:
                report.append(("particles_paste_bad_group",
                               {"group": group}))
            continue
        fn = (str(fn) if fn is not None else "").strip()
        if not fn:
            continue
        # n-я копия модуля в буфере метит n-ю копию у цели
        n = occurrence.get(fn.lower(), 0)
        occurrence[fn.lower()] = n + 1
        target = _nth_module(pcf, d, group, fn, n)
        if target is None:
            target = _new_module(pcf, d, group, fn, report)
            changed = True
        if _paste_attrs(pcf, target, attrs or {}, overwrite,
                        report, where=fn, group=group):
            changed = True
    return changed


def _nth_module(pcf, d, group: str, fn: str, n: int):
    """n-й модуль fn в группе системы, отвязанный для правки; None - нет"""
    if group not in d:
        return None
    k = 0
    for i, m in enumerate(d[group].iter_elem()):
        if module_fn(m) == fn.lower():
            if k == n:
                # Общий с другими системами - сперва свой
                return pcf._module_for_edit(d, group, i)
            k += 1
    return None


def _new_module(pcf, d, group: str, fn: str, report: Optional[list]):
    """Новый модуль fn в конце группы"""
    # Модуля с таким именем нет в игре - почти наверняка
    # опечатка: игра его проигнорирует
    if report is not None and pcf._attr_catalog and \
            (group, fn.lower()) not in pcf._attr_catalog:
        report.append(("particles_paste_unknown_module",
                       {"group": group, "module": fn}))
    target = Element(fn, "DmeParticleOperator")
    target["functionName"] = Attribute.string(
        "functionName", fn)
    if group in d:
        d[group].append(target)
    else:
        arr = Attribute.array(group, ValueType.ELEMENT)
        arr.append(target)
        d[group] = arr
    return target
