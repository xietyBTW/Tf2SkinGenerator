"""
Проверки эффекта перед сборкой мода.

Ловит случаи, из-за которых мод молча не работает в игре: невидимые
системы, эффект, скрытый от камеры, оборванные ссылки, конфликтующие
файлы в tf/custom. Часть находок чинится автоматически.

Правила откалиброваны по 10427 системам стоковых PCF: то, что у Valve
встречается массово (например, родитель без рендерера, но с детьми),
нарушением НЕ считается — иначе предупреждения превращаются в шум.

Модуль без Qt: логика тестируется напрямую.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class Finding:
    """Одна находка проверки."""
    rule: str                      # идентификатор правила
    system: str                    # система эффекта ("" — общее)
    message_key: str               # ключ перевода particles_lint_<...>
    params: dict = field(default_factory=dict)   # подстановки в сообщение
    #: Адрес атрибута для автопочинки: (группа|None, индекс модуля, имя, тип)
    fix: Optional[tuple] = None
    fix_value: Any = None

    @property
    def fixable(self) -> bool:
        return self.fix is not None


#: Атрибуты, значения которых делают эффект невидимым/странным.
#: Используется и для пометки в дереве свойств (знак вопроса у значения).
def attr_warning(attr_name: str, value: Any) -> Optional[str]:
    """Ключ перевода с пояснением, если значение атрибута проблемное."""
    name = (attr_name or "").lower()
    if name == "control point to disable rendering if it is the camera":
        try:
            if int(value) >= 0:
                return "particles_lint_cp_camera"
        except (TypeError, ValueError):
            return None
    elif name == "max_particles":
        try:
            if int(value) <= 0:
                return "particles_lint_no_particles"
        except (TypeError, ValueError):
            return None
    elif name == "radius":
        try:
            if float(value) == 0:
                return "particles_lint_zero_radius"
        except (TypeError, ValueError):
            return None
    elif name == "color":
        if isinstance(value, (list, tuple)) and len(value) > 3 and value[3] == 0:
            return "particles_lint_zero_alpha"
    elif name == "view model effect":
        if value is True:
            return "particles_lint_viewmodel"
    return None


def _has(mods, *names) -> bool:
    wanted = {n.lower() for n in names}
    return any((m.get("functionName") or "").strip().lower() in wanted
               for m in mods or [])


def check_systems(systems: dict, root_name: str = "",
                  materials: Optional[dict] = None,
                  baseline: Optional[dict] = None) -> List[Finding]:
    """
    Проверяет эффект: систему root_name и всё, что из неё достижимо
    (пустое имя — проверяются все системы файла).

    baseline — состояние на момент загрузки PCF. Если передан, проверяются
    ТОЛЬКО добавленные и изменённые системы: приёмы Valve вроде «скрыть
    эффект от камеры» встречаются в стоке массово и в чужом файле не наша
    забота, а вот принесённые правкой — ровно то, что стоит показать.
    """
    out: List[Finding] = []
    if root_name and root_name in systems:
        names, pending, seen = [], [root_name], set()
        while pending:
            n = pending.pop(0)
            if n in seen or n not in systems:
                continue
            seen.add(n)
            names.append(n)
            pending.extend(c["childName"] for c in systems[n].get("children") or [])
    else:
        names = list(systems)

    if baseline is not None:
        import json
        def _key(d):
            return json.dumps(d, sort_keys=True, ensure_ascii=False)
        names = [n for n in names
                 if n not in baseline or _key(baseline[n]) != _key(systems[n])]

    for name in names:
        s = systems[name]
        attrs = s.get("attrs") or {}
        children = s.get("children") or []
        renderers = s.get("renderers") or []
        emitters = s.get("emitters") or []

        def val(key, default=None):
            return attrs.get(key, {}).get("v", default)

        # Эффект скрыт, если на контрольной точке камера. Родная механика
        # Valve для эффектов от первого лица, но в чужом контексте
        # (перенос эффекта в другой PCF) она молча гасит частицы.
        cp_cam = val("control point to disable rendering if it is the camera")
        if cp_cam is not None and int(cp_cam) >= 0:
            out.append(Finding(
                "cp_camera", name, "particles_lint_cp_camera",
                fix=(None, 0,
                     "control point to disable rendering if it is the camera",
                     "integer"),
                fix_value=-1))

        # Частицы некому рисовать. У Valve системы без рендерера — обычно
        # контейнеры с детьми, это норма; сообщаем, только если система
        # реально спавнит свои частицы.
        if not renderers and emitters:
            out.append(Finding("no_renderer", name, "particles_lint_no_renderer"))

        # Система ничего не делает: ни своих частиц, ни детей
        if not emitters and not children:
            out.append(Finding("no_emitter", name, "particles_lint_no_emitter"))

        if emitters and int(val("max_particles", 1000) or 0) <= 0:
            out.append(Finding(
                "no_particles", name, "particles_lint_no_particles",
                fix=(None, 0, "max_particles", "integer"), fix_value=100))

        radius = val("radius")
        if radius is not None and float(radius) == 0 and not _has(
                s.get("initializers"), "radius random") and not _has(
                s.get("operators"), "radius scale"):
            out.append(Finding(
                "zero_radius", name, "particles_lint_zero_radius",
                fix=(None, 0, "radius", "float"), fix_value=5.0))

        color = val("color")
        if isinstance(color, (list, tuple)) and len(color) > 3 and color[3] == 0:
            out.append(Finding(
                "zero_alpha", name, "particles_lint_zero_alpha",
                fix=(None, 0, "color", "color"),
                fix_value=[color[0], color[1], color[2], 255]))

        # Оборванная ссылка: ребёнка нет в файле — в игре просто ничего
        for ch in children:
            if ch["childName"] not in systems:
                out.append(Finding(
                    "missing_child", name, "particles_lint_missing_child",
                    params={"child": ch["childName"]}))

        # Материал не удалось прочитать: в игре текстуры не будет.
        # Пустой словарь = резолв материалов не выполнялся (нет пути к TF2) —
        # тогда молчим, иначе получим предупреждение на каждую систему.
        if materials:
            mat = val("material")
            if mat and mat not in materials:
                out.append(Finding(
                    "material_missing", name, "particles_lint_material",
                    params={"material": mat}))
    return out


def check_game_conflicts(tf2_root: str, pcf_vpk_path: str) -> List[Finding]:
    """
    Ищет в tf/custom файлы, перекрывающие собираемый PCF.

    Рассыпные файлы из custom монтируются ПОВЕРХ VPK игры, поэтому чужой
    particles/<имя>.pcf делает мод невидимым — и это выглядит как «мод не
    работает», хотя собран он верно.
    """
    out: List[Finding] = []
    if not tf2_root or not pcf_vpk_path:
        return out
    rel = pcf_vpk_path.replace("\\", "/").lstrip("/")
    custom = Path(tf2_root) / "tf" / "custom"
    if not custom.is_dir():
        return out
    try:
        for entry in custom.iterdir():
            if entry.is_dir():
                loose = entry / Path(rel)
                if loose.is_file():
                    out.append(Finding(
                        "custom_override", "", "particles_lint_custom_override",
                        params={"path": str(loose)}))
    except OSError:
        pass
    return out


def apply_fixes(service, findings: List[Finding]) -> int:
    """Применяет автопочинку к дереву PCF. Возвращает число исправлений."""
    fixed = 0
    for f in findings:
        if not f.fixable or not f.system:
            continue
        group, idx, attr, attr_type = f.fix
        if service.ensure_attr(f.system, group, idx, attr, attr_type,
                               f.fix_value):
            fixed += 1
    return fixed
