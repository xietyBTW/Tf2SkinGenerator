"""Родные цвета текстуры: снять с эффекта модули тинта"""

from typing import Optional

from src.services.particle_editor.pcf_format import Attribute, ValueType


#: Модули, красящие частицы (тинт умножается на текстуру)
_COLOR_MODULE_NAMES = {"color random", "color fade", "color lit per particle"}


def use_texture_colors(pcf, system_name: str) -> int:
    """
    Заставляет эффект использовать родные цвета текстур: у системы и всех
    её дочерних удаляются модули тинта (Color Random, Color Fade,
    Color Lit Per Particle, ремапы CP/осцилляция в поле цвета), базовый
    цвет ставится белым. Тот же приём, что colored-crit в CritPcfService

    Returns:
        Количество удалённых модулей (0 - красящих модулей не было)
    """
    root_def = pcf._find_definition(system_name)
    if root_def is None:
        return 0

    # Система + все дочерние (эффект целиком)
    targets, seen, pending = [], set(), [root_def]
    while pending:
        d = pending.pop(0)
        if id(d) in seen:
            continue
        seen.add(id(d))
        targets.append(d)
        if "children" in d:
            try:
                for ch in d["children"].iter_elem():
                    if "child" in ch:
                        try:
                            pending.append(ch["child"].val_elem)
                        except Exception:
                            pass
            except Exception:
                pass

    removed = 0
    for d in targets:
        for group in ("initializers", "operators"):
            if group not in d:
                continue
            kept = []
            for mod in d[group].iter_elem():
                if _is_color_module(mod):
                    removed += 1
                else:
                    kept.append(mod)
            if len(kept) != len(d[group]):
                if kept:
                    d[group] = kept
                else:
                    # Пустому списку srctools не выводит тип - явный массив
                    d[group] = Attribute.array(
                        d[group].name, ValueType.ELEMENT)
        if "color" in d:
            d["color"] = Attribute.color(d["color"].name, 255, 255, 255, 255)
    return removed


def _is_color_module(mod) -> bool:
    """True для модулей, задающих/меняющих цвет частиц"""
    fn = ""
    if "functionname" in mod:
        try:
            fn = mod["functionname"].val_str
        except Exception:
            fn = ""
    fn = (fn or mod.name or "").strip().lower()
    if fn in _COLOR_MODULE_NAMES:
        return True

    def _field(attr_name: str) -> Optional[int]:
        if attr_name not in mod:
            return None
        try:
            return mod[attr_name].val_int
        except Exception:
            return None

    # 6 = TINT_RGB (цвет частицы) в индексации полей Source
    if fn == "remap control point to vector" and _field("output field") == 6:
        return True
    if fn == "oscillate vector" and _field("oscillation field") == 6:
        return True
    return False
