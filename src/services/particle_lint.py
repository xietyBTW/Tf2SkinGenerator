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


#: Операторы, которые убивают частицу по истечении её жизни. Без любого из
#: них частицы бессмертны: поток встаёт, как только наберётся max_particles.
_DEATH_OPERATORS = ("lifespan decay", "lifespan_decay",
                    "alpha fade and decay", "alpha_fade",
                    "cull random", "cull when crossing plane")

#: Рендереры, которые крутят спрайт-лист материала.
_SHEET_RENDERERS = ("render_animated_sprites", "render_sprite_trail")


def _sheet_frames(sheet: Optional[dict], sequence: Any) -> int:
    """Сколько кадров в последовательности спрайт-листа материала.

    sequence — sequence_number системы; если такой последовательности нет,
    берётся самая длинная (частица всё равно может попасть в неё через
    Sequence Random).
    """
    sequences = (sheet or {}).get("sequences") or {}
    if not sequences:
        return 0
    chosen = sequences.get(str(sequence)) or sequences.get(sequence)
    if chosen is not None:
        return len(chosen.get("frames") or [])
    return max((len(s.get("frames") or []) for s in sequences.values()),
               default=0)


def _frames_played(renderer_attrs: dict, frames: int, lifetime: float) -> float:
    """Сколько кадров спрайт-листа частица успевает показать за свою жизнь.

    Смысл «animation rate» зависит от флага: при «use animation rate as fps»
    это кадры в секунду, иначе — ЦИКЛЫ в секунду (весь лист за цикл).
    """
    def val(name, default):
        return (renderer_attrs.get(name) or {}).get("v", default)

    if val("animation_fit_lifetime", False):
        return float(frames)            # лист растянут ровно на жизнь
    try:
        rate = float(val("animation rate", 1.0) or 0.0)
    except (TypeError, ValueError):
        return float(frames)            # не число — не наше дело
    if val("use animation rate as fps", False):
        return rate * lifetime
    return rate * lifetime * frames


def _animation_is_frozen(renderer_attrs: dict, frames: int,
                         lifetime: float) -> bool:
    """Стоит ли частица одним кадром всю свою жизнь.

    Порог — два кадра: если за жизнь не успевает смениться даже один, лист
    в игре читается как обычная статичная картинка.

    Медленная прокрутка длинного листа сюда НЕ входит, хотя соблазн есть:
    у Valve 15-кадровые листы на 0.1-0.2 цикла/сек встречаются массово
    (кровь, дым) — там разнообразие даёт Sequence Random, раздающий частицам
    разные стартовые кадры, а не сама анимация.
    """
    return _frames_played(renderer_attrs, frames, lifetime) < 2.0


def _reachable(systems: dict, root_name: str) -> list:
    """Система root_name и всё, что достижимо через детей (пусто — все)."""
    if not root_name or root_name not in systems:
        return list(systems)
    names, pending, seen = [], [root_name], set()
    while pending:
        n = pending.pop(0)
        if n in seen or n not in systems:
            continue
        seen.add(n)
        names.append(n)
        pending.extend(c["childName"] for c in systems[n].get("children") or [])
    return names


def check_preview_support(systems: dict, supported: dict, aliases: dict,
                          root_name: str = "") -> List[Finding]:
    """Модули, которые движок превью не исполняет.

    Такой модуль движок молча выбрасывает, и эффект в превью ведёт себя
    иначе, чем в игре, — причём заметить это можно только по результату.
    Особенно больно с операторами размещения (`Position on Model Random`,
    `Movement Lock to Bone`): без них частицы-держатели сваливаются в одну
    точку, и всё дерево детей, висящее на их позициях, съезжает следом.

    supported/aliases приходят из самого движка (implementedModules), поэтому
    список не разъезжается с реализацией. Пустой supported — страница ещё не
    отчиталась, молчим.
    """
    out: List[Finding] = []
    if not supported:
        return out

    for name in _reachable(systems, root_name):
        s = systems[name]
        missing = []
        for group, known in supported.items():
            for mod in s.get(group) or []:
                fn = (mod.get("functionName") or "").strip()
                key = aliases.get(fn.lower(), fn.lower())
                if fn and key not in known:
                    missing.append(fn)
        if missing:
            # Порядок и повторы не нужны: важен сам список
            out.append(Finding(
                "not_previewed", name, "particles_lint_not_previewed",
                params={"modules": ", ".join(sorted(set(missing)))}))
    return out


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

        # Частицы бессмертны: непрерывный поток встанет, как только наберётся
        # max_particles, и эффект замрёт навсегда. У Valve так сделаны 3.4%
        # систем (застывшие арки, лучи) — намеренно, поэтому не ошибка, а
        # предупреждение; при сравнении с baseline оно и вовсе всплывёт
        # только на том, что правил пользователь.
        if _has(emitters, "emit_continuously") and renderers and \
                not _has(s.get("operators"), *_DEATH_OPERATORS):
            out.append(Finding("immortal", name, "particles_lint_immortal"))

        # Материал не удалось прочитать: в игре текстуры не будет.
        # Пустой словарь = резолв материалов не выполнялся (нет пути к TF2) —
        # тогда молчим, иначе получим предупреждение на каждую систему.
        if materials:
            mat = val("material")
            info = materials.get(mat) if mat else None
            if mat and info is None:
                out.append(Finding(
                    "material_missing", name, "particles_lint_material",
                    params={"material": mat}))
            elif info:
                out.extend(_check_animation(name, s, attrs, info))
    return out


def _check_animation(name: str, s: dict, attrs: dict,
                     material: dict) -> List[Finding]:
    """Анимированная текстура, которая в игре стоит кадром.

    Спрайт-лист крутится либо флагом animation_fit_lifetime, либо заметной
    скоростью анимации. Дефолтные 0.1 ЦИКЛА в секунду на листе из 30 кадров
    при жизни частицы в секунду покажут треть кадра — пользователь видит
    статичную картинку и не понимает, почему «гифка не анимируется». В
    стоке такое сочетание встречается у 2 систем из 57 с многокадровыми
    листами, так что это действительно исключение, а не приём.
    """
    frames = _sheet_frames(material.get("sheet"),
                           (attrs.get("sequence_number") or {}).get("v", 0))
    if frames < 2:
        return []
    # Sequence Random раздаёт частицам разные стартовые кадры: даже стоящий
    # лист выглядит разнообразно, и это приём Valve, а не оплошность
    if _has(s.get("initializers"), "sequence random", "sequence two random",
            "lifetime from sequence"):
        return []
    lifetime = _max_lifetime(s)
    out: List[Finding] = []
    for idx, r in enumerate(s.get("renderers") or []):
        if (r.get("functionName") or "").strip().lower() not in _SHEET_RENDERERS:
            continue
        if not _animation_is_frozen(r.get("attrs") or {}, frames, lifetime):
            continue
        out.append(Finding(
            "frozen_animation", name, "particles_lint_frozen_anim",
            params={"frames": frames},
            fix=("renderers", idx, "animation_fit_lifetime", "bool"),
            fix_value=True))
    return out


def _max_lifetime(s: dict, default: float = 1.0) -> float:
    """Верхняя граница жизни частицы по инициализатору Lifetime Random."""
    for mod in s.get("initializers") or []:
        if (mod.get("functionName") or "").strip().lower() in (
                "lifetime random", "lifetime_random"):
            v = (mod.get("attrs") or {}).get("lifetime_max")
            if v is not None:
                try:
                    return max(float(v["v"]), 1e-6)
                except (TypeError, ValueError, KeyError):
                    break
    return default


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
