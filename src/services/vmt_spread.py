"""
Правка VMT во все материалы предмета

Без шестерёнки на карточке правка общая: то, что человек сделал в VMT одного
материала, уходит и в остальные. Копировать текст целиком нельзя - у каждого
материала свои текстуры, и копия сломала бы их. Поэтому правка разбирается на
две части:

  * готовые эффекты (блеск, крит, стекло, оболочка) - собираются заново для
    каждого материала из ЕГО текста теми же значениями формы (vmt_effects);
  * остальное - изменённые, добавленные и удалённые ключи корня материала.
    Пути текстур не переносятся: они у каждого материала свои

Ручные правки внутри "Proxies" и снятие эффекта не переносятся - о них
сообщается, чтобы человек поправил остальные материалы сам
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.services import vmt_effects

#: Ключи с путём к текстуре, своей у каждого материала
TEXTURE_KEYS = frozenset({
    "$basetexture", "$basetexture2", "$bumpmap", "$bumpmap2", "$normalmap",
    "$detail", "$envmapmask", "$selfillummask", "$phongexponenttexture",
    "$phongwarptexture", "$lightwarptexture", "$blendmodulatetexture",
    "$ambientoccltexture", "$tintmasktexture", "$iris", "$corneatexture",
})

_KEY_RE = re.compile(r'^\s*"?([$%][\w]+)"?\s+(.*?)\s*$')


@dataclass
class Plan:
    """Что из правки одного материала уходит в остальные"""

    #: (эффект, значения формы) - собрать заново в каждом материале
    effects: List[Tuple[str, dict]] = field(default_factory=list)
    #: {ключ: строка значения как в тексте} - поставить
    keys: Dict[str, str] = field(default_factory=dict)
    #: Ключи, которые убрали
    removed: List[str] = field(default_factory=list)
    #: Что перенести нельзя: "effect_removed" (сняли эффект), "proxies"
    #: (ручная правка прокси). Текст для человека - на странице
    notes: List[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.effects or self.keys or self.removed)


def plan(before: str, after: str, game: str = "",
         bounds: Optional[dict] = None) -> Plan:
    """Разбирает правку `before` -> `after` одного материала"""
    out = Plan()
    staged = before
    for key in vmt_effects.EFFECTS:
        if not vmt_effects.present(key, after):
            if vmt_effects.present(key, before) and "effect_removed" not in out.notes:
                out.notes.append("effect_removed")
            continue
        vals = vmt_effects.values(key, after)
        if vmt_effects.present(key, before) and vals == vmt_effects.values(key, before):
            continue
        res = vmt_effects.apply(key, vals, staged, game, bounds)
        if "text" in res:
            staged = res["text"]
        out.effects.append((key, vals))

    # Ручная часть - то, чего эффекты сами не дали
    old, new = top_keys(staged), top_keys(after)
    for name, (_shown, value) in new.items():
        if name not in TEXTURE_KEYS and old.get(name, (None, None))[1] != value:
            out.keys[new[name][0]] = value
    out.removed = [shown for name, (shown, _v) in old.items()
                   if name not in new and name not in TEXTURE_KEYS]
    if _proxies(staged) != _proxies(after):
        out.notes.append("proxies")
    return out


def apply_plan(p: Plan, text: str, game: str = "",
               bounds: Optional[dict] = None) -> Tuple[str, List[str]]:
    """Текст другого материала с правкой, второе - что не легло и почему"""
    problems = []
    for key, vals in p.effects:
        res = vmt_effects.apply(key, vals, text, game, bounds)
        if "text" in res:
            text = res["text"]
        else:
            problems.append(f"{key}: {res.get('error', '')}")
    for key, value in p.keys.items():
        text = set_key(text, key, value)
    for key in p.removed:
        text = drop_key(text, key)
    return text, problems


# Ключи корня материала

def _lines(text: str) -> List[Tuple[str, int, Optional[str]]]:
    """(строка, глубина в её начале, ключ в нижнем регистре или None)"""
    out, depth = [], 0
    for line in text.split("\n"):
        code = _code(line)
        m = _KEY_RE.match(code)
        out.append((line, depth, m.group(1).lower() if m else None))
        depth += code.count("{") - code.count("}")
    return out


def _code(line: str) -> str:
    """Строка без комментария и без скобок внутри кавычек"""
    out, quoted = [], False
    i = 0
    while i < len(line):
        c = line[i]
        if c == '"':
            quoted = not quoted
        elif not quoted and line.startswith("//", i):
            break
        if not (quoted and c in "{}"):
            out.append(c)
        i += 1
    return "".join(out)


def top_keys(text: str) -> Dict[str, Tuple[str, str]]:
    """{ключ: (как написан, значение)} корня материала, последний выигрывает,
    как в игре. Ключи вложенных блоков (Proxies, >=DX90) не в счёт"""
    found = {}
    for line, depth, key in _lines(text):
        if depth == 1 and key:
            m = _KEY_RE.match(_code(line))
            found[key] = (m.group(1), m.group(2))
    return found


def set_key(text: str, key: str, value: str) -> str:
    """Ставит ключ корня: меняет его строки на месте, нет - за первой «{»"""
    rows = _lines(text)
    name = key.lower()
    hits = [i for i, (_l, depth, k) in enumerate(rows) if depth == 1 and k == name]
    lines = [r[0] for r in rows]
    new = f'"{key}" {value}'
    if hits:
        for i in hits:
            indent = re.match(r"\s*", lines[i]).group(0)
            lines[i] = indent + new
        return "\n".join(lines)
    for i, (line, depth, _k) in enumerate(rows):
        if depth == 0 and "{" in _code(line):
            lines.insert(i + 1, "\t" + new)
            return "\n".join(lines)
    return text


def drop_key(text: str, key: str) -> str:
    """Убирает строки ключа из корня материала"""
    name = key.lower()
    return "\n".join(line for line, depth, k in _lines(text)
                     if not (depth == 1 and k == name))


def _proxies(text: str) -> str:
    """Содержимое "Proxies" без наших помеченных прокси и пробелов"""
    clean = vmt_effects.strip_marked_proxies(text)
    m = re.search(r'"?proxies"?\s*\{', clean, re.IGNORECASE)
    if not m:
        return ""
    depth, start = 0, m.end() - 1
    for i in range(start, len(clean)):
        if clean[i] == "{":
            depth += 1
        elif clean[i] == "}":
            depth -= 1
            if depth == 0:
                return re.sub(r"\s+", "", clean[start:i])
    return re.sub(r"\s+", "", clean[start:])
