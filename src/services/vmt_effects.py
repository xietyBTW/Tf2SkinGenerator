"""
Особые материалы редактора VMT: эффекты с настройками (цвет, сила).

Обычные сниппеты (`src/data/vmt_snippets.py`) вставляются как есть. Эти —
собираются из выбранных значений, а форма открывается уже заполненной тем,
что стоит в материале: эффект можно перенастроить, а не только поставить.

- «Призрачная оболочка» — рецепт мода, который видно в игре: `$additive` +
  `$color2 [0 0 0]` + самосвечение с френелем (`$selfillumfresnel`,
  `[0.1 0.2 1]`) + отражение кубмапы. Контур светится цветом ОСНОВЫ, умноженным
  на `$selfillumtint`: основа — `effects/white` («свой цвет») или текстура
  оружия («из текстуры», как радуга в образце).
  ВНИМАНИЕ: по коду SDK 2013 френель самосвета есть только в bump/skin
  шейдерах, а самосвет умножается на обнулённый `$color2` — то есть в SDK этот
  рецепт дал бы одно отражение. В TF2 шейдеры свои: без самосвета оружие в
  игре выходило ПОЛНОСТЬЮ прозрачным (отражение `cubemap_sheen001` почти
  чёрное) — проверено сборкой человека. Верить SDK тут нельзя, только игре.

По коду шейдеров Valve (source-sdk-2013, stdshaders):

- «Стекло» — проход плаща шпиона (cloak_blended_pass): `$cloakfactor` ~0.26–0.44
  делает стеклом середину, края остаются текстурой; от 0.44 — стекло целиком.
  Тон — `$cloakcolortint` (действует при факторе < 0.75), искажение —
  `$refractamount`. Шейдер Refract не годится: прокси `invis` пишет только
  `$cloakfactor` (tf_proxyentity.cpp), а оружие рисуется при любой
  невидимости (CTFWeaponBase::ShouldDraw) — невидимого шпиона с таким оружием
  было бы видно. Здесь своё значение ПРИБАВЛЯЕТСЯ к невидимости шпиона, и
  при настоящей невидимости сумма доходит до 1: оружие исчезает, как в игре.

Модуль без Qt.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

#: Метка наших служебных переменных: по ней эффект находит и заменяет свои
#: прокси при повторной настройке, не трогая прокси материала.
MARK = "$tf2sg_"

GHOST = "Призрачная оболочка"
GLASS = "Стекло"

#: Белая основа для «своего цвета» (220/224/220, альфа 255 — маска свечения
#: полная). `patterns/solid_white` не годится: серая и почти прозрачная.
WHITE = "effects/white"

_CUBEMAPS = {
    "sheen": "cubemaps/cubemap_sheen001",
    "gold": "cubemaps/cubemap_gold001",
    "map": "env_cubemap",
}
#: Сколько стекла: середина (края — текстура) или вся модель. Границы — из
#: формулы маски плаща (см. docstring модуля): 0.26 и 0.44.
_GLASS_LOOK = {"edge": 0.34, "full": 0.6}

#: Готовые цвета: белый (как в моде-образце), голубой, зелёный, фиолетовый,
#: красный, золотой. Свой цвет — выбором рядом.
PRESETS = ["#ffffff", "#3fd8ff", "#4dff88", "#b366ff", "#ff4d4d", "#ffc93c"]

#: Цвет во времени: один цвет или радуга. Общие поля для всех эффектов с
#: цветом: `show_if` прячет поле, пока другое поле не примет нужное значение.
#: Радуга — три прокси Sine на каналы R/G/B со сдвигом на треть круга
#: (resultVar "$var[0]" пишет один канал: CResultProxy, functionproxy.cpp).
def _color_fields(label: Tuple[str, str]) -> List[dict]:
    return [
        {"key": "color_mode", "type": "choice", "label": label, "default": "solid",
         "choices": [("solid", "Один цвет", "One color"),
                     ("rainbow", "Радуга", "Rainbow")]},
        # Без подписи: стоит сразу под переключателем, заголовок у них общий.
        {"key": "color", "type": "color", "label": ("", ""),
         "default": "#ffffff", "show_if": {"color_mode": "solid"}},
        {"key": "speed", "type": "range",
         "label": ("Круг цветов, сек", "Color cycle, s"),
         "min": 0.5, "max": 10, "step": 0.5, "default": 3,
         "show_if": {"color_mode": "rainbow"}},
    ]


# Поля форм. Подписи парами (ru, en): переводит Python, как и сами сниппеты.
EFFECTS: Dict[str, dict] = {
    GHOST: {
        "replace": True,
        "fields": [
            *_color_fields(("Цвет", "Color")),
            {"key": "source", "type": "choice",
             "label": ("Цвет контура", "Outline color"), "default": "color",
             "choices": [("color", "Выбранный цвет", "The picked color"),
                         ("texture", "Из текстуры × цвет", "From the texture × color")]},
            {"key": "cubemap", "type": "choice", "label": ("Отражение", "Reflection"),
             "default": "sheen",
             "choices": [("sheen", "Неон", "Neon"), ("gold", "Золото", "Gold"),
                         ("map", "Карта", "Map")]},
            {"key": "bright", "type": "range", "label": ("Яркость", "Brightness"),
             "min": 0.3, "max": 3, "step": 0.1, "default": 1},
        ],
    },
    GLASS: {
        "replace": False,
        "fields": [
            *_color_fields(("Оттенок", "Tint")),
            {"key": "look", "type": "choice", "label": ("Вид", "Look"),
             "default": "edge",
             "choices": [("edge", "Стекло с контуром", "Glass with an outline"),
                         ("full", "Целиком стекло", "All glass")]},
            {"key": "refract", "type": "range", "label": ("Искажение", "Distortion"),
             "min": 0, "max": 4, "step": 0.1, "default": 2},
        ],
    },
}


def fields(key: str, en: bool) -> List[dict]:
    """Поля формы эффекта на языке интерфейса; у простого сниппета — пусто."""
    out = []
    for f in EFFECTS.get(key, {}).get("fields", []):
        item = {k: v for k, v in f.items() if k not in ("label", "choices")}
        item["label"] = f["label"][1 if en else 0]
        if "choices" in f:
            item["choices"] = [{"value": v, "label": en_l if en else ru}
                               for v, ru, en_l in f["choices"]]
        if f["type"] == "color":
            item["presets"] = list(PRESETS)
        out.append(item)
    return out


# ── Разбор и запись значений ──────────────────────────────────────────── #

def _key_re(key: str) -> "re.Pattern[str]":
    """Строка «"$ключ" значение» (кавычки у ключа необязательны, регистр любой)."""
    return re.compile(r'^([ \t]*)"?' + re.escape(key) + r'"?[ \t]+([^\n]*)$',
                      re.IGNORECASE | re.MULTILINE)


def _value(text: str, key: str) -> Optional[str]:
    """Значение ключа без кавычек и комментария; последний одноимённый."""
    found = _key_re(key).findall(text)
    if not found:
        return None
    raw = re.sub(r'\s*//.*$', '', found[-1][1]).strip()
    return raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] == '"' else raw


def _vec(text: Optional[str]) -> Optional[Tuple[float, float, float]]:
    """«[r g b]» (0…1) или «{r g b}» (0…255) → тройка 0…1+."""
    if not text:
        return None
    nums = re.findall(r'-?\d*\.?\d+', text)
    if len(nums) < 3:
        return None
    v = tuple(float(n) for n in nums[:3])
    return tuple(c / 255 for c in v) if text.strip().startswith('{') else v


def _to_hex(rgb) -> str:
    return '#' + ''.join('%02x' % max(0, min(255, round(c * 255))) for c in rgb)


def _from_hex(value: str) -> Tuple[float, float, float]:
    m = re.fullmatch(r'#?([0-9a-fA-F]{6})', str(value or '').strip())
    h = m.group(1) if m else 'ffffff'
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _fmt_vec(rgb) -> str:
    return '[' + ' '.join(f'{c:.3f}'.rstrip('0').rstrip('.') or '0' for c in rgb) + ']'


def _num(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v))


def values(key: str, text: str) -> Dict[str, object]:
    """Значения формы: из материала, если эффект уже стоит, иначе по умолчанию."""
    out = {f["key"]: f["default"] for f in EFFECTS.get(key, {}).get("fields", [])}
    if key == GHOST and _value(text, "$additive") == "1":
        tint = _vec(_value(text, "$selfillumtint") or _value(text, "$envmaptint"))
        if tint:
            peak = max(tint)
            bright = peak if peak > 1 else 1.0
            out["color"] = _to_hex(c / bright for c in tint)
            out["bright"] = round(_num(bright, 0.3, 3, 1), 1)
        rainbow = _rainbow_info(text, "$selfillumtint")
        if rainbow:
            out["color_mode"] = "rainbow"
            out["speed"] = _num(rainbow[0], 0.5, 10, 3)
            out["bright"] = round(_num(rainbow[1], 0.3, 3, 1), 1)
        base = (_value(text, "$basetexture") or "").lower()
        out["source"] = "color" if base == WHITE else "texture"
        cube = (_value(text, "$envmap") or "").lower()
        out["cubemap"] = next((k for k, v in _CUBEMAPS.items() if v == cube), out["cubemap"])
    elif key == GLASS and _value(text, MARK + "glass") is not None:
        tint = _vec(_value(text, "$cloakcolortint"))
        if tint:
            out["color"] = _to_hex(tint)
        factor = _num(_value(text, MARK + "glass"), 0, 1, _GLASS_LOOK["edge"])
        out["look"] = "full" if factor >= 0.44 else "edge"
        out["refract"] = round(_num(_value(text, "$refractamount"), 0, 4, 2), 1)
        # Старая запись (по каналам прямо в $cloakcolortint) тоже узнаётся:
        # перенастройка заменит её рабочей.
        rainbow = (_rainbow_info(text, MARK + "rgb")
                   or _rainbow_info(text, "$cloakcolortint"))
        if rainbow:
            out["color_mode"] = "rainbow"
            out["speed"] = _num(rainbow[0], 0.5, 10, 3)
    return out


# ── Сборка ────────────────────────────────────────────────────────────── #

def apply(key: str, vals: Dict[str, object], text: str,
          game: str = '') -> Dict[str, object]:
    """Текст материала с эффектом: {'text', 'replace'} или {'error'}.

    `game` — игровой оригинал материала: из него берётся родная текстура,
    когда в тексте её уже заменила белая основа прошлой настройки.
    """
    if key == GHOST:
        return {"text": _ghost(vals, text, game), "replace": True}
    if key == GLASS:
        return {"text": _glass(vals, text), "replace": False}
    return {"error": "Такого эффекта нет"}


def _ghost(vals: Dict[str, object], text: str, game: str = '') -> str:
    """Весь материал заново. Основа — белая («свой цвет») или родная текстура:
    её сборка потом заменит на текстуру человека, если он её положил."""
    rgb = _from_hex(vals.get("color"))
    bright = _num(vals.get("bright"), 0.3, 3, 1)
    cube = _CUBEMAPS.get(str(vals.get("cubemap")), _CUBEMAPS["sheen"])
    if vals.get("source") == "texture":
        own = [b for b in (_value(text, "$basetexture"), _value(game, "$basetexture"))
               if b and b.lower() != WHITE]
        base = own[0] if own else WHITE
    else:
        base = WHITE
    glow = _fmt_vec(c * bright for c in rgb)
    proxies = _proxy("invis", [])
    if vals.get("color_mode") == "rainbow":
        # Контур и отражение одного цвета: радуга на самосвет, отражение —
        # его копия (Equals копирует и вектор: CEqualsProxy, mathproxy.cpp).
        glow = _fmt_vec((bright, bright, bright))
        proxies += (_rainbow("$selfillumtint", _num(vals.get("speed"), 0.5, 10, 3), bright)
                    + _proxy("Equals", [("srcVar1", "$selfillumtint"),
                                        ("resultVar", "$envmaptint")]))
    return (
        '"VertexLitGeneric"\n'
        '{\n'
        f'\t"$basetexture" "{base}"\n'
        # Комментарии в самом VMT — по-английски: файл уходит в мод, и его
        # открывают люди с любым языком.
        '\t// Ghost shell: the body is see-through (additive, $color2 black),\n'
        '\t// the edges glow with the base texture times $selfillumtint\n'
        '\t"$additive" "1"\n'
        '\t"$color2" "[0 0 0]"\n'
        '\t"$selfillum" "1"\n'
        f'\t"$selfillumtint" "{glow}"\n'
        '\t"$selfillumfresnel" "1"\n'
        '\t"$selfillumfresnelminmaxexp" "[0.1 0.2 1]"\n'
        f'\t"$envmap" "{cube}"\n'
        f'\t"$envmaptint" "{glow}"\n'
        "\t// Spy cloak still hides the weapon, as with a stock material\n"
        '\t"$cloakpassenabled" "1"\n'
        '\t"Proxies"\n'
        '\t{\n'
        f'{proxies}'
        '\t}\n'
        '}\n'
    )


def _glass(vals: Dict[str, object], text: str) -> str:
    """Вливается в материал: ключи — на место одноимённых, прокси — свои."""
    factor = _GLASS_LOOK.get(str(vals.get("look")), _GLASS_LOOK["edge"])
    keys = [
        ("$cloakpassenabled", "1"),
        ("$cloakcolortint", _fmt_vec(_from_hex(vals.get("color")))),
        ("$refractamount", f'{_num(vals.get("refract"), 0, 4, 2):g}'),
        (MARK + "glass", f"{factor:g}"),
        (MARK + "zero", "0"),
        # Цвет радуги до копирования в $cloakcolortint (объявлен вектором,
        # иначе прокси его не найдут).
        (MARK + "rgb", "[1 1 1]"),
    ]
    out = _strip_marked_proxies(text)
    for key, value in keys:
        out = _set_key(out, key, value)
    # Порядок важен: обнулить → невидимость шпиона → прибавить стекло →
    # обрезать до 1. Обнуление само по себе: прокси невидимости ставит
    # значение не в каждом кадре (без сущности OnBind не зовётся), и без него
    # «прибавить» копило бы фактор до полной невидимости.
    has_invis = _has_invis(out)
    head = _proxy("Equals", [("srcVar1", MARK + "zero"), ("resultVar", "$cloakfactor")])
    if not has_invis:
        head += _proxy("invis", [])
    tail = (_proxy("Add", [("srcVar1", "$cloakfactor"), ("srcVar2", MARK + "glass"),
                           ("resultVar", "$cloakfactor")])
            + _proxy("Clamp", [("min", "0"), ("max", "1"), ("srcVar1", "$cloakfactor"),
                               ("resultVar", "$cloakfactor")]))
    if vals.get("color_mode") == "rainbow":
        # Тон стекла по кругу; действует, пока фактор плаща < 0.75 — то есть
        # всегда, кроме настоящей невидимости шпиона. Синусоиды пишут СВОЮ
        # переменную, а в $cloakcolortint она копируется целиком: запись по
        # каналам прямо в параметр плаща в игре гасила стекло совсем (сборка
        # человека), а у Valve ни один материал прокси плаща по каналам не
        # пишет — только целиком, как Equals $glowcolor → $color2.
        tail += (_rainbow(MARK + "rgb", _num(vals.get("speed"), 0.5, 10, 3))
                 + _proxy("Equals", [("srcVar1", MARK + "rgb"),
                                     ("resultVar", "$cloakcolortint")]))
    return _add_proxies(out, head, tail)


def _rainbow(var: str, period: float, peak: float = 1.0) -> str:
    """Три прокси Sine на каналы `var`: цвет идёт по кругу за `period` секунд.

    Каналы сдвинуты на треть круга (timeOffset), поэтому оттенок меняется, а
    яркость почти нет: сумма трёх синусоид со сдвигом 120° постоянна.
    """
    return ''.join(
        _proxy("Sine", [("resultVar", f"{var}[{i}]"), ("sinePeriod", f"{period:g}"),
                        ("timeOffset", f"{period * i / 3:.3g}"),
                        ("sineMin", "0"), ("sineMax", f"{peak:g}")])
        for i in range(3))


def _rainbow_info(text: str, var: str) -> Optional[Tuple[float, float]]:
    """(период, пик) радуги на `var`, если она стоит; иначе None."""
    for block in re.findall(r'"?sine"?\s*\{([^}]*)\}', text, re.IGNORECASE):
        if f'{var.lower()}[0]' not in block.lower():
            continue
        def num(name, default):
            m = re.search(r'"?' + name + r'"?\s+"?([-\d.]+)', block, re.IGNORECASE)
            return float(m.group(1)) if m else default
        return num('sineperiod', 3.0), num('sinemax', 1.0)
    return None


def _has_invis(text: str) -> bool:
    """Есть ли в блоке "Proxies" прокси невидимости — «invis» или старые
    weapon_invis / vm_invis / spy_invis: все пишут $cloakfactor."""
    m = _PROXIES_RE.search(text)
    close = _match_brace(text, m.end() - 1) if m else -1
    if close < 0:
        return False
    inner = re.sub(r'//[^\n]*', '', text[m.end():close])
    return bool(re.search(r'"?\b(?:\w+_)?invis"?\s*\{', inner, re.IGNORECASE))


def _set_key(text: str, key: str, value: str) -> str:
    """Меняет значение ключа на месте; нет ключа — строка за первой «{»."""
    line = f'"{key}" "{value}"'
    rx = _key_re(key)
    if rx.search(text):
        # Все одноимённые строки: в VMT действует последняя, и оставленная
        # старая могла бы перекрыть новую.
        return rx.sub(lambda m: m.group(1) + line, text)
    at = _first_brace(text)
    at = len(text) if at < 0 else at + 1
    return text[:at] + '\n\t' + line + text[at:]


def _first_brace(text: str) -> int:
    """Первая «{» вне комментариев и строк (шапка `// by me {v2}` — не она)."""
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            end = text.find('"', i + 1)
            i = len(text) if end < 0 else end
        elif c == '/' and text[i + 1:i + 2] == '/':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif c == '{':
            return i
        i += 1
    return -1


#: Комментарий в наших прокси: по нему их узнаёт повторная настройка. Не
#: все они ссылаются на помеченную переменную (Clamp — только на $cloakfactor).
_PROXY_MARK = "// tf2sg"


def _proxy(name: str, pairs: List[Tuple[str, str]]) -> str:
    body = ''.join(f'\t\t\t"{k}" "{v}"\n' for k, v in pairs)
    return f'\t\t"{name}"\n\t\t{{\n\t\t\t{_PROXY_MARK}\n{body}\t\t}}\n'


_PROXIES_RE = re.compile(r'^[ \t]*"?proxies"?(?:\s|//[^\n]*)*\{', re.IGNORECASE | re.MULTILINE)


def _match_brace(text: str, open_at: int) -> int:
    """Парная «}»; скобки в строках и комментариях не в счёт. -1 — не закрыта."""
    depth, i = 0, open_at
    while i < len(text):
        c = text[i]
        if c == '"':
            end = text.find('"', i + 1)
            if end < 0:
                return -1
            i = end
        elif c == '/' and text[i + 1:i + 2] == '/':
            end = text.find('\n', i)
            if end < 0:
                return -1
            i = end
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _add_proxies(text: str, head: str, tail: str) -> str:
    """`head` — в начало блока "Proxies", `tail` — в конец; нет блока — свой.

    Блок один: материал читает только первый "Proxies" (KeyValues::FindKey).
    """
    m = _PROXIES_RE.search(text)
    close = _match_brace(text, m.end() - 1) if m else -1
    if close < 0:
        root_close = text.rfind('}')
        block = '\t"Proxies"\n\t{\n' + head + tail + '\t}\n'
        if root_close < 0:
            return text + '\n' + block
        return text[:root_close].rstrip() + '\n' + block + text[root_close:]
    open_at = m.end()
    end = close
    while end > open_at and text[end - 1] in ' \t':
        end -= 1
    inner = text[open_at:end].rstrip() + '\n'
    return text[:open_at] + '\n' + head + inner.lstrip('\n') + tail + '\t' + text[close:]


def _strip_marked_proxies(text: str) -> str:
    """Убирает из "Proxies" наши прошлые прокси (с метками `$tf2sg_`)."""
    m = _PROXIES_RE.search(text)
    close = _match_brace(text, m.end() - 1) if m else -1
    if close < 0:
        return text
    inner = text[m.end():close]
    kept, i = [], 0
    # С начала строки: иначе «имя {» ловилось бы и в комментарии
    # (`// TODO Sine {`), разбор уезжал, и свои прокси копились бы.
    entry = re.compile(r'^[ \t]*"?[\w]+"?\s*\{', re.MULTILINE)
    while True:
        e = entry.search(inner, i)
        if not e:
            kept.append(inner[i:])
            break
        e_close = _match_brace(inner, e.end() - 1)
        if e_close < 0:
            kept.append(inner[i:])
            break
        chunk_end = e_close + 1
        if inner[chunk_end:chunk_end + 1] == '\n':
            chunk_end += 1
        chunk = inner[e.start():chunk_end]
        kept.append(inner[i:e.start()])
        # Свой «invis» (добавлен, когда родного не было) тоже помечен и уходит:
        # следующая сборка добавит его снова, раз родного нет.
        if _PROXY_MARK not in chunk:
            kept.append(chunk)
        i = chunk_end
    return text[:m.end()] + ''.join(kept) + text[close:]
