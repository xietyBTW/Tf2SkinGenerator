"""Правка структуры: модули, системы, слои и дочерние ссылки"""

from typing import Dict, Optional

from src.services.particle_editor.pcf_format import (
    MODULE_GROUPS, Attribute, Element, ValueType, copy_module, make_module,
    module_fn)


#: Кэш шаблонов модулей из стоковых PCF: {(group, fn_lower): Element}
_module_templates: Dict[tuple, "Element"] = {}


def _find_module_template(
    pcf, group: str, function_name: str, tf2_root_dir: str,
) -> Optional["Element"]:
    """
    Шаблон модуля с реалистичными атрибутами: ищем модуль с таким
    functionName в текущем PCF, затем по стоковым PCF игры (первое
    совпадение кэшируется на весь запуск)
    """
    key = (group, function_name.lower())
    if key in _module_templates:
        cached = _module_templates[key]
        # None - закэшированный промах (не сканировать 134 PCF повторно)
        return copy_module(cached) if cached is not None else None

    def _scan(svc) -> Optional["Element"]:
        for d in svc._all_definition_elements():
            if group not in d:
                continue
            try:
                for mod in d[group].iter_elem():
                    if module_fn(mod) == key[1]:
                        return mod
            except Exception:
                continue
        return None

    found = _scan(pcf)
    if found is None and tf2_root_dir:
        for path in pcf.list_game_pcfs(tf2_root_dir):
            try:
                other = type(pcf)()
                other.load_from_game(tf2_root_dir, path)
            except Exception:
                continue
            found = _scan(other)
            if found is not None:
                break
    if found is None:
        _module_templates[key] = None
        return None
    template = copy_module(found)
    _module_templates[key] = template
    return copy_module(template)


def add_module(
    pcf, system_name: str, group: str, function_name: str,
    tf2_root_dir: str = "",
) -> bool:
    """
    Добавляет модуль в группу системы. Атрибуты берутся из шаблона
    (первый такой же модуль в текущем/стоковых PCF), если шаблона нет -
    создаётся элемент с одним functionName (движок игры и превью
    подставляют дефолты)
    """
    d = pcf._find_definition(system_name)
    if d is None or group not in MODULE_GROUPS:
        return False
    mod = _find_module_template(pcf, group, function_name, tf2_root_dir)
    if mod is None:
        mod = Element(function_name, "DmeParticleOperator")
        mod["functionName"] = Attribute.string("functionName", function_name)
    seed_spawn_area(d, mod)
    if group in d:
        d[group].append(mod)
    else:
        arr = Attribute.array(group, ValueType.ELEMENT)
        arr.append(mod)
        d[group] = arr
    return True


def apply_gizmo_edits(pcf, system_name: str, edits: list,
                      tf2_root_dir: str = "") -> Optional[str]:
    """
    Итог перетаскивания ручек гизмо: [{group, index, fn, attr, type, value}]

    Модуль ищется по номеру, а если там другой - по имени функции. Модуля
    может не быть вовсе: превью само дописывает Position Modify Offset Random
    в начале перетаскивания сферы, и здесь он создаётся так же. У правки может
    быть своя system: гизмо двигает весь эффект, корень вместе с дочерними.
    Возвращает текст ошибки или None
    """
    names = list(dict.fromkeys(e.get("system") or system_name for e in edits))
    own = own_effect_children(pcf, system_name, names)
    for edit in edits:
        group, fn = edit.get("group"), str(edit.get("fn") or "")
        name = edit.get("system") or system_name
        name = own.get(name, name)
        d = pcf._find_definition(name)
        if d is None:
            return f"система не найдена: {name}"
        mods = list(d[group].iter_elem()) if group in d else []
        index = int(edit.get("index", -1))
        if not (0 <= index < len(mods) and module_fn(mods[index]) == fn.lower()):
            index = next((i for i, m in enumerate(mods)
                          if module_fn(m) == fn.lower()), -1)
        if index < 0:
            if not pcf.add_module(name, group, fn, tf2_root_dir):
                return f"не удалось добавить {fn}"
            index = len(mods)
        if not pcf.ensure_attr(name, group, index, edit.get("attr"),
                               edit.get("type"), edit.get("value")):
            return f"не удалось записать {edit.get('attr')}"
    return None


def _kid_refs(el) -> list:
    """Ссылки системы на детей: [(элемент-ссылка, дочерняя система)]"""
    out = []
    if "children" not in el:
        return out
    try:
        for ch in el["children"].iter_elem():
            if "child" in ch:
                try:
                    out.append((ch, ch["child"].val_elem))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _subtree(root) -> Dict[int, "Element"]:
    """Система и все её потомки, по id элемента"""
    out, stack = {}, [root]
    while stack:
        el = stack.pop()
        if el is None or id(el) in out:
            continue
        out[id(el)] = el
        stack.extend(kid for _, kid in _kid_refs(el))
    return out


def own_effect_children(pcf, root_name: str, names: list) -> Dict[str, str]:
    """
    Свои копии общих дочерних систем эффекта: {старое имя: новое}

    Система бывает дочерней у нескольких эффектов (gas_can_impact_red и
    _blue делят троих детей). Гизмо двигает эффект целиком, и правка общей
    уехала бы и у соседа - копируем при записи, как общие модули. Имена
    идут от родителей к детям: внук скопированной системы становится общим
    с оригиналом, и копируется следом
    """
    root = pcf._find_definition(root_name)
    if root is None:
        return {}
    own: Dict[str, str] = {}
    for name in names:
        target = pcf._find_definition(name)
        if target is None or target is root:
            continue
        tree = _subtree(root)
        parents = [el for el in tree.values()
                   if any(kid is target for _, kid in _kid_refs(el))]
        outside = any(kid is target
                      for el in pcf._all_definition_elements()
                      if id(el) not in tree for _, kid in _kid_refs(el))
        if not parents or not outside:
            continue
        new_name, n = f"{name}_{root_name}", 2
        while pcf._find_definition(new_name) is not None:
            new_name, n = f"{name}_{root_name}_{n}", n + 1
        if not duplicate_system(pcf, name, new_name):
            continue
        copy = pcf._find_definition(new_name)
        for el in parents:
            _relink_child(el, target, copy)
        own[name] = new_name
    return own


def _relink_child(parent, target, copy) -> None:
    """Ссылки parent на target ведут теперь на copy

    Ссылку не правим на месте, а ставим новую: у Valve общими бывают и
    сами элементы-ссылки (gas_can_impact_red и _blue держат одни и те же),
    и правка на месте перевела бы на копию и соседа
    """
    attr = parent["children"]
    arr = Attribute.array(attr.name, ValueType.ELEMENT)
    for ref, kid in [(r, r["child"].val_elem if "child" in r else None)
                     for r in attr.iter_elem()]:
        if kid is target:
            fresh = Element(copy.name, ref.type)
            for a in ref.values():
                if a.name.casefold() not in ("child", "name"):
                    fresh[a.name] = a.copy()
            fresh["child"] = Attribute("child", ValueType.ELEMENT, copy)
            ref = fresh
        arr.append(ref)
    parent[attr.name] = arr


def seed_spawn_area(definition, mod) -> bool:
    """
    Даёт вырожденной области спавна видимый размер, соразмерный эффекту

    Шаблоны стоковых PCF часто приходят с нулевой областью (у бокса
    min == max) - добавленный модуль спавнит всё в одну точку, каркас
    в превью не рисуется и тянуть нечего. Размер берём от радиуса
    частиц системы, чтобы область была соразмерна тому, что видно.
    Осмысленные значения из шаблона не трогаем
    """
    fn = module_fn(mod)
    if fn not in ("position within box random",
                  "position within sphere random"):
        return False
    radius = 5.0
    if "radius" in definition:
        try:
            radius = abs(definition["radius"].val_float) or 5.0
        except Exception:
            radius = 5.0
    extent = max(4.0, radius * 4.0)

    def _vec(el, name):
        try:
            return list(el[name].val_vec3) if name in el else None
        except Exception:
            return None

    if fn == "position within box random":
        lo, hi = _vec(mod, "min"), _vec(mod, "max")
        if lo is not None and hi is not None and \
                any(abs(hi[i] - lo[i]) > 1e-6 for i in range(3)):
            return False        # у шаблона нормальный бокс
        mod["min"] = Attribute.vec3(
            mod["min"].name if "min" in mod else "min",
            -extent, -extent, -extent)
        mod["max"] = Attribute.vec3(
            mod["max"].name if "max" in mod else "max",
            extent, extent, extent)
        return True

    try:
        d_max = mod["distance_max"].val_float if "distance_max" in mod else 0.0
    except Exception:
        d_max = 0.0
    if abs(d_max) > 1e-6:
        return False            # у шаблона нормальная сфера
    mod["distance_max"] = Attribute.float(
        mod["distance_max"].name if "distance_max" in mod else "distance_max",
        extent * 1.5)
    return True


def remove_module(pcf, system_name: str, group: str, index: int) -> bool:
    """Удаляет модуль по индексу из группы системы"""
    d = pcf._find_definition(system_name)
    if d is None or group not in d:
        return False
    try:
        mods = list(d[group].iter_elem())
        mods.pop(index)
    except (IndexError, Exception):
        return False
    if mods:
        d[group] = mods
    else:
        d[group] = Attribute.array(d[group].name, ValueType.ELEMENT)
    return True


def duplicate_system(pcf, system_name: str, new_name: str) -> bool:
    """
    Дублирует систему под новым именем (в корневой список определений)

    Модули копируются по значению (правки копии не трогают оригинал);
    ссылки children остаются на те же дочерние системы
    """
    d = pcf._find_definition(system_name)
    if d is None or pcf._find_definition(new_name) is not None:
        return False
    new = Element(new_name, d.type)
    for attr in d.values():
        key = attr.name          # оригинальный регистр - уходит в файл
        kl = key.casefold()
        if kl in MODULE_GROUPS:
            mods = [copy_module(m) for m in attr.iter_elem()]
            if mods:
                new[key] = mods
            else:
                new[key] = Attribute.array(key, ValueType.ELEMENT)
        elif kl == "children":
            # Копируем элементы-ссылки, сами дочерние системы - общие
            refs = [copy_module(ch) for ch in attr.iter_elem()]
            if refs:
                new[key] = refs
            else:
                new[key] = Attribute.array(key, ValueType.ELEMENT)
        else:
            new[key] = attr.copy()
    if "name" in new:
        new["name"] = Attribute.string(new["name"].name, new_name)
    pcf.root["particleSystemDefinitions"].append(new)
    return True


def rename_system(pcf, old_name: str, new_name: str) -> bool:
    """
    Переименовывает систему вместе со всеми ссылками на неё

    Дети ссылаются на объект-определение, а не на имя, поэтому связь
    не рвётся, но у элемента-ссылки (DmeParticleChild) собственное имя
    совпадает с именем ребёнка - приводим и его, иначе файл выглядит
    рассогласованным
    """
    new_name = (new_name or "").strip()
    target = pcf._find_definition(old_name)
    if target is None or not new_name or new_name == old_name:
        return False
    if pcf._find_definition(new_name) is not None:
        return False        # имя занято

    target.name = new_name
    if "name" in target:
        target["name"] = Attribute.string(target["name"].name, new_name)

    for el in pcf._all_definition_elements():
        if "children" not in el:
            continue
        try:
            for ch in el["children"].iter_elem():
                if "child" not in ch:
                    continue
                try:
                    if ch["child"].val_elem is target:
                        ch.name = new_name
                except Exception:
                    continue
        except Exception:
            continue
    return True


def remove_system(pcf, system_name: str) -> bool:
    """Удаляет систему совсем: из корневого списка И из children всех
    родителей (иначе она оставалась «призраком» - играла у родителя и
    держала имя занятым)"""
    target = pcf._find_definition(system_name)
    if target is None:
        return False

    # Отцепить все ссылки на target по всему дереву (до удаления из корня)
    for el in pcf._all_definition_elements():
        if "children" not in el:
            continue
        try:
            refs = list(el["children"].iter_elem())
        except Exception:
            continue
        kept_refs = []
        for ch in refs:
            is_target = False
            if "child" in ch:
                try:
                    is_target = ch["child"].val_elem is target
                except Exception:
                    is_target = False
            if not is_target:
                kept_refs.append(ch)
        if len(kept_refs) != len(refs):
            if kept_refs:
                el["children"] = kept_refs
            else:
                el["children"] = Attribute.array(
                    "children", ValueType.ELEMENT)

    defs = pcf._definitions()
    kept = [d for d in defs if d is not target]
    if kept:
        pcf.root["particleSystemDefinitions"] = kept
    else:
        pcf.root["particleSystemDefinitions"] = Attribute.array(
            "particleSystemDefinitions", ValueType.ELEMENT)
    return True


def add_layer(pcf, parent_name: str,
              layer_name: Optional[str] = None) -> Optional[str]:
    """
    Создаёт новый слой-подэффект и цепляет его ребёнком к parent_name

    Слой - готовый «залп спрайтов» с разумными настройками (50 частиц
    разлетаются из центра, крутятся, гаснут и падают): пользователю
    остаётся дать текстуру и крутить параметры. Возвращает имя слоя
    """
    parent = pcf._find_definition(parent_name)
    if parent is None:
        return None
    layer_name = _free_layer_name(pcf, parent_name, layer_name)
    if layer_name is None:
        return None
    pcf.root["particleSystemDefinitions"].append(_layer_definition(layer_name))
    if not add_child(pcf, parent_name, layer_name):
        return None
    return layer_name


def _free_layer_name(pcf, parent_name: str,
                     layer_name: Optional[str]) -> Optional[str]:
    """Имя нового слоя: заданное (None - занято) или <родитель>_layer[N]"""
    if not layer_name:
        base, n = f"{parent_name}_layer", 2
        layer_name = base
        while pcf._find_definition(layer_name) is not None:
            layer_name = f"{base}{n}"
            n += 1
    elif pcf._find_definition(layer_name) is not None:
        return None
    return layer_name


def _layer_definition(layer_name: str) -> "Element":
    """Определение слоя-заготовки: 50 спрайтов разлетаются из центра,
    крутятся, гаснут и падают"""
    d = Element(layer_name, "DmeParticleSystemDefinition")
    d["max_particles"] = Attribute.int("max_particles", 300)
    d["material"] = Attribute.string("material", "effects\\yellowflare.vmt")
    d["radius"] = Attribute.float("radius", 5.0)
    d["color"] = Attribute.color("color", 255, 255, 255, 255)

    op = "DmeParticleOperator"
    d["renderers"] = [make_module("render_animated_sprites", op, [
        Attribute.float("animation rate", 1.0),
        Attribute.int("orientation_type", 0),
    ])]
    d["emitters"] = [make_module("emit_instantaneously", op, [
        Attribute.int("num_to_emit", 50),
        Attribute.float("emission_start_time", 0.0),
    ])]
    d["initializers"] = [
        make_module("Position Within Sphere Random", op, [
            Attribute.float("distance_min", 0.0),
            Attribute.float("distance_max", 4.0),
            Attribute.float("speed_min", 150.0),
            Attribute.float("speed_max", 300.0),
            Attribute.float("speed_random_exponent", 1.0),
        ]),
        make_module("Lifetime Random", op, [
            Attribute.float("lifetime_min", 0.4),
            Attribute.float("lifetime_max", 0.8),
        ]),
        make_module("Radius Random", op, [
            Attribute.float("radius_min", 3.0),
            Attribute.float("radius_max", 6.0),
        ]),
        make_module("Rotation Random", op, []),
    ]
    d["operators"] = [
        make_module("Lifespan Decay", op, []),
        make_module("Movement Basic", op, [
            Attribute.vec3("gravity", 0.0, 0.0, -200.0),
            Attribute.float("drag", 0.0),
        ]),
        make_module("Alpha Fade Out Simple", op, [
            Attribute.float("proportional fade out time", 0.25),
        ]),
        make_module("Rotation Spin Roll", op, [
            Attribute.int("spin_rate_degrees", 240),
            Attribute.int("spin_stop_time", 0),
        ]),
    ]
    return d


def add_child(pcf, parent_name: str, child_name: str,
              delay: float = 0.0) -> bool:
    """Подцепляет существующую систему ребёнком к parent_name"""
    parent = pcf._find_definition(parent_name)
    child = pcf._find_definition(child_name)
    if parent is None or child is None or parent is child:
        return False
    # Гард от цикла: если parent достижим из child по children - в игре
    # это бесконечная рекурсия инстанцирования (крэш клиента)
    pending, seen = [child], set()
    while pending:
        cur = pending.pop()
        if cur is parent:
            return False
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        if "children" in cur:
            try:
                for ch in cur["children"].iter_elem():
                    if "child" in ch:
                        try:
                            pending.append(ch["child"].val_elem)
                        except Exception:
                            pass
            except Exception:
                pass
    ref = Element(child_name, "DmeParticleChild")
    ref["delay"] = Attribute.float("delay", float(delay))
    ref["child"] = Attribute("child", ValueType.ELEMENT, child)
    if "children" in parent:
        parent["children"].append(ref)
    else:
        arr = Attribute.array("children", ValueType.ELEMENT)
        arr.append(ref)
        parent["children"] = arr
    return True


def remove_child(pcf, parent_name: str, index: int) -> bool:
    """Отцепляет ребёнка по индексу (сама дочерняя система остаётся)"""
    parent = pcf._find_definition(parent_name)
    if parent is None or "children" not in parent:
        return False
    try:
        refs = list(parent["children"].iter_elem())
        # UI нумерует только валидные ссылки (systems_json пропускает
        # битые) - маппим индекс на сырой массив
        valid = [i for i, ch in enumerate(refs) if "child" in ch]
        refs.pop(valid[index])
    except (IndexError, Exception):
        return False
    if refs:
        parent["children"] = refs
    else:
        parent["children"] = Attribute.array("children", ValueType.ELEMENT)
    return True
