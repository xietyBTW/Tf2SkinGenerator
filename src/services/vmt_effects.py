"""
Особые материалы редактора VMT: эффекты с настройками (цвет, сила)

Обычные сниппеты (`src/data/vmt_snippets.py`) вставляются как есть. Эти -
собираются из выбранных значений, а форма открывается уже заполненной тем,
что стоит в материале: эффект можно перенастроить, а не только поставить

- «Призрачная оболочка» - рецепт мода, который видно в игре: `$additive` +
  `$color2 [0 0 0]` + самосвечение с френелем (`$selfillumfresnel`,
  `[0.1 0.2 1]`) + отражение кубмапы. Контур светится цветом ОСНОВЫ, умноженным
  на `$selfillumtint`: основа - `effects/white` («свой цвет») или текстура
  оружия («из текстуры», как радуга в образце).
  ВНИМАНИЕ: по коду SDK 2013 френель самосвета есть только в bump/skin
  шейдерах, а самосвет умножается на обнулённый `$color2` - то есть в SDK этот
  рецепт дал бы одно отражение. В TF2 шейдеры свои: без самосвета оружие в
  игре выходило ПОЛНОСТЬЮ прозрачным (отражение `cubemap_sheen001` почти
  чёрное) - проверено сборкой человека. Верить SDK тут нельзя, только игре

По коду шейдеров Valve (source-sdk-2013, stdshaders):

- «Стекло» - проход плаща шпиона (cloak_blended_pass): `$cloakfactor` ~0.26-0.44
  делает стеклом середину, края остаются текстурой, от 0.44 - стекло целиком.
  Тон - `$cloakcolortint` (действует при факторе < 0.75), искажение -
  `$refractamount`. Шейдер Refract не годится: прокси `invis` пишет только
  `$cloakfactor` (tf_proxyentity.cpp), а оружие рисуется при любой
  невидимости (CTFWeaponBase::ShouldDraw) - невидимого шпиона с таким оружием
  было бы видно. Здесь своё значение ПРИБАВЛЯЕТСЯ к невидимости шпиона, и
  при настоящей невидимости сумма доходит до 1: оружие исчезает, как в игре

По клиентскому коду TF2 (source-sdk-2013, game/client/tf/c_tf_player.cpp) и
вики Valve («Proxies are executed in the order in which they appear»):

- «Цвет блеска киллстрика» - прокси AnimatedWeaponSheen каждый кадр пишет в
  `$sheenmaptint` цвет из таблицы киллстрика, а наш Equals ниже него
  перезаписывает его своим (так сделан мод white sheen). Шейдер блеска
  (weapon_sheen_pass_ps2x.fxc) берёт цвет линейным и умножает на 10;
  `$sheenindex 1` (так у австралия) - ещё ×1.8. «Всегда»: без киллстрика
  прокси ставит кадр маски 0, а при кадре 0 проход не рисуется
  (ShouldDrawMaterialSheen) - кадры крутят свои LinearRamp -> WrapMinMax ->
  Int -> LessOrEqual, а положение полосы - `$sheenmapmaskscale/offset/
  direction`, посчитанные из габаритов модели так же, как InitParams игры.
- «Цвет свечения крита» - ModelGlowColor пишет в `$glowcolor` [80 8 5] у
  RED и [5 20 80] у BLU под критами, иначе [1 1 1]; материал копирует его в
  `$color2`. Сразу за ним наши прокси смешивают свой цвет по доле «красноты»
  (R − B) / 75. Каналы вектора читаются приёмом Clamp с min = max =
  "$var[i]" (вики Valve), пишутся в «$var[i]» своего вектора, умножение
  вектора на число не используется - его поведение в SDK не видно
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

#: Метка наших служебных переменных: по ней эффект находит и заменяет свои
#: прокси при повторной настройке, не трогая прокси материала
MARK = "$tf2sg_"

GHOST = "Призрачная оболочка"
GLASS = "Стекло"
SHEEN = "Цвет блеска киллстрика"
CRIT = "Цвет свечения крита"

#: Белая основа для «своего цвета» (220/224/220, альфа 255 - маска свечения
#: полная). `patterns/solid_white` не годится: серая и почти прозрачная
WHITE = "effects/white"

_CUBEMAPS = {
    "sheen": "cubemaps/cubemap_sheen001",
    "gold": "cubemaps/cubemap_gold001",
    "map": "env_cubemap",
}
#: Сколько стекла: середина (края - текстура) или вся модель. Границы - из
#: формулы маски плаща (см. docstring модуля): 0.26 и 0.44
_GLASS_LOOK = {"edge": 0.34, "full": 0.6}

#: Готовые цвета: белый (как в моде-образце), голубой, зелёный, фиолетовый,
#: красный, золотой. Свой цвет - выбором рядом
PRESETS = ["#ffffff", "#3fd8ff", "#4dff88", "#b366ff", "#ff4d4d", "#ffc93c"]

#: Цвет во времени: один цвет или радуга. Общие поля для всех эффектов с
#: цветом: `show_if` прячет поле, пока другое поле не примет нужное значение.
#: Радуга - три прокси Sine на каналы R/G/B со сдвигом на треть круга
#: (resultVar "$var[0]" пишет один канал: CResultProxy, functionproxy.cpp)
def _color_fields(label: Tuple[str, str]) -> List[dict]:
    return [
        {"key": "color_mode", "type": "choice", "label": label, "default": "solid",
         "choices": [("solid", "Один цвет", "One color"),
                     ("rainbow", "Радуга", "Rainbow")]},
        # Без подписи: стоит сразу под переключателем, заголовок у них общий
        {"key": "color", "type": "color", "label": ("", ""),
         "default": "#ffffff", "show_if": {"color_mode": "solid"}},
        {"key": "speed", "type": "range",
         "label": ("Круг цветов, сек", "Color cycle, s"),
         "min": 0.5, "max": 10, "step": 0.5, "default": 3,
         "show_if": {"color_mode": "rainbow"}},
    ]


def _sheen_presets() -> List[Tuple[str, str, str]]:
    """Готовые узоры блеска = шаблоны конструктора: (значение, ru, en)"""
    from src.services.sheen_builder import PRESETS
    from src.services.sheen_library import PRESET_PREFIX
    return [(PRESET_PREFIX + k, *p["label"]) for k, p in PRESETS.items()]


#: Значения «Узора», при которых цвет задаёт эффект: игра и готовые узоры.
#: Свой узор красят его слои, и цвет эффекта ему не нужен (он белый)
_SHEEN_TINTED = ["game", *[v for v, _ru, _en in _sheen_presets()]]


def _tinted(field: dict) -> dict:
    """Поле цвета блеска видно, пока узор не свой и блеск не чёрный"""
    return {**field, "show_if": {**field.get("show_if", {}), "pattern": _SHEEN_TINTED,
                                 "dark!": "on"}}


# Поля форм. Подписи парами (ru, en): переводит Python, как и сами сниппеты
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
    SHEEN: {
        "replace": False,
        "fields": [
            # `builder`: страница добавляет свои узоры из конструктора и
            # кнопку самого конструктора (sheen-builder.js)
            {"key": "pattern", "type": "choice", "label": ("Узор", "Pattern"),
             "default": "game", "builder": True,
             "choices": [("game", "Как в игре", "As in game"), *_sheen_presets()]},
            # Чёрный блеск готового узора: узор уходит в красный канал, оттенок
            # без красного (sheen_palette). У своего узора гамму выбирают
            # цвета его слоёв, поле ему не нужно
            {"key": "dark", "type": "choice", "label": ("Вид", "Look"),
             "default": "off", "show_if": {"pattern": _SHEEN_TINTED[1:]},
             "choices": [("off", "Светится", "Glows"),
                         ("on", "Чёрный, затемняет", "Black, darkens")]},
            *[_tinted(f) for f in _color_fields(("Цвет", "Color"))],
            {"key": "bright", "type": "range", "label": ("Яркость", "Brightness"),
             "min": 0.3, "max": 3, "step": 0.1, "default": 1},
            # Длина своего узора задана в конструкторе
            {"key": "length", "type": "range",
             "label": ("Длина прохода, сек", "Sweep length, s"),
             "min": 1, "max": 8, "step": 0.5, "default": 2.5,
             "show_if": {"pattern": _SHEEN_TINTED[1:]}},
            {"key": "shine", "type": "choice", "label": ("Отблеск", "Shine"),
             "default": "flat", "show_if": {"pattern!": "game"},
             "choices": [("flat", "Ровный, узор виден целиком", "Even, the whole pattern shows"),
                         ("live", "Живой, как в игре", "Live, as in game")]},
            {"key": "when", "type": "choice", "label": ("Когда", "When"),
             "default": "game",
             "choices": [("game", "С киллстриком, как в игре", "With a killstreak, as in game"),
                         ("always", "Всегда, на любом оружии", "Always, on any weapon")]},
            {"key": "pause", "type": "range",
             "label": ("Пауза между бликами, сек", "Pause between sweeps, s"),
             "min": 0, "max": 10, "step": 0.5, "default": 5,
             "show_if": {"when": "always"}},
        ],
    },
    CRIT: {
        "replace": False,
        "fields": [
            {"key": "red", "type": "color", "label": ("Крит RED", "RED crit"),
             "default": "#ff5947"},
            {"key": "blue", "type": "color", "label": ("Крит BLU", "BLU crit"),
             "default": "#4789ff"},
            {"key": "bright", "type": "range", "label": ("Яркость", "Brightness"),
             "min": 0.3, "max": 3, "step": 0.1, "default": 1},
        ],
    },
}


def fields(key: str, en: bool) -> List[dict]:
    """Поля формы эффекта на языке интерфейса, у простого сниппета - пусто"""
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


# Разбор и запись значений

def _key_re(key: str) -> "re.Pattern[str]":
    """Строка «"$ключ" значение» (кавычки у ключа необязательны, регистр любой)"""
    return re.compile(r'^([ \t]*)"?' + re.escape(key) + r'"?[ \t]+([^\n]*)$',
                      re.IGNORECASE | re.MULTILINE)


def _value(text: str, key: str) -> Optional[str]:
    """Значение ключа без кавычек и комментария, последний одноимённый"""
    found = _key_re(key).findall(text)
    if not found:
        return None
    raw = re.sub(r'\s*//.*$', '', found[-1][1]).strip()
    return raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] == '"' else raw


def _vec(text: Optional[str]) -> Optional[Tuple[float, float, float]]:
    """«[r g b]» (0…1) или «{r g b}» (0…255) -> тройка 0…1+"""
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


def _fmt_vec(rgb, digits: int = 3) -> str:
    return '[' + ' '.join(f'{c:.{digits}f}'.rstrip('0').rstrip('.') or '0' for c in rgb) + ']'


def _num(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v))


def present(key: str, text: str) -> bool:
    """Эффект уже стоит в материале (те же признаки, что у `values`)"""
    marks = {GHOST: ("$additive", "1"), GLASS: (MARK + "glass", None),
             SHEEN: (MARK + "sheen", None), CRIT: (MARK + "critred", None)}
    var, want = marks.get(key, ("", None))
    got = _value(text, var) if var else None
    return got is not None and (want is None or got == want)


def values(key: str, text: str) -> Dict[str, object]:
    """Значения формы: из материала, если эффект уже стоит, иначе по умолчанию"""
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
        # перенастройка заменит её рабочей
        rainbow = (_rainbow_info(text, MARK + "rgb")
                   or _rainbow_info(text, "$cloakcolortint"))
        if rainbow:
            out["color_mode"] = "rainbow"
            out["speed"] = _num(rainbow[0], 0.5, 10, 3)
    elif key == SHEEN and _value(text, MARK + "sheen") is not None:
        bright = _num(_value(text, MARK + "sheenbright"), 0.3, 3, 1)
        # Старое «Ярче, как у австралия» ($sheenindex 1) - это x1.8 к яркости
        boost = 1.8 if _value(text, MARK + "sheenidx") is not None else 1
        out["bright"] = round(min(3, bright * boost), 1)
        tint = _vec(_value(text, MARK + "sheen"))
        if tint:
            out["color"] = _to_hex(_to_srgb(c / bright) for c in tint)
        rainbow = _rainbow_info(text, MARK + "sheen")
        if rainbow:
            out["color_mode"] = "rainbow"
            out["speed"] = _num(rainbow[0], 0.5, 10, 3)
        from src.services import sheen_library, sheen_patterns
        mask = _value(text, "$sheenmapmask") or ""
        own = sheen_patterns.parse(mask)
        custom = sheen_patterns.parse_custom(mask)
        if own:
            # Старый готовый узор - тот же вид из шаблонов конструктора
            out["pattern"] = sheen_library.PRESET_PREFIX + sheen_patterns.LEGACY_PRESETS[own[0]]
            out["length"] = round((own[1] - 1) / sheen_patterns.FPS * 2) / 2
        elif custom:
            out["pattern"] = custom[0]
            if sheen_library.ID_RE.match(custom[0]):
                out["color"] = "#ffffff"        # оттенок своего узора - служебный
            elif sheen_patterns.darkened(mask):
                out["dark"] = "on"
                out["color"] = "#ffffff"
            out["length"] = round((custom[2] - 1) / sheen_patterns.FPS * 2) / 2
        if own or custom:
            out["shine"] = ("flat" if sheen_patterns.is_flat_cube(_value(text, "$sheenmap"))
                            else "live")
        pause = _value(text, MARK + "sheenpause")
        if pause is not None:
            out["when"] = "always"
            out["pause"] = _num(pause, 0, 10, 5)
    elif key == CRIT and _value(text, MARK + "critred") is not None:
        bright = _num(_value(text, MARK + "critbright"), 0.3, 3, 1)
        out["bright"] = round(bright, 1)
        for field, var in (("red", "critred"), ("blue", "critblue")):
            tint = _vec(_value(text, MARK + var))
            if tint:
                out[field] = _to_hex(_to_srgb(c / (_CRIT_SCALE * bright)) for c in tint)
    return out


# Сборка

def apply(key: str, vals: Dict[str, object], text: str,
          game: str = '', bounds: Optional[dict] = None) -> Dict[str, object]:
    """Текст материала с эффектом: {'text', 'replace'} или {'error'}

    `game` - игровой оригинал материала: из него берётся родная текстура,
    когда в тексте её уже заменила белая основа прошлой настройки.
    `bounds` - положение полосы блеска для модели (`sheen_mask_params`),
    нужно блеску «всегда»
    """
    if key == GHOST:
        return {"text": _ghost(vals, text, game), "replace": True}
    if key == GLASS:
        return {"text": _glass(vals, text), "replace": False}
    if key == SHEEN:
        return _sheen(vals, text, bounds, game)
    if key == CRIT:
        return _crit(vals, text)
    return {"error": "Такого эффекта нет"}


# Блеск киллстрика и свечение крита

#: Свои метки: повторная настройка одного эффекта не трогает прокси другого
_SHEEN_MARK = "// tf2sg sheen"
_CRIT_MARK = "// tf2sg crit"
#: Крит у игры - [80 8 5] и [5 20 80]: такой силы и наш цвет
_CRIT_SCALE = 80.0
#: Кадров в маске Valve effects/animatedsheen/animatedsheen0 и скорость, с
#: которой их крутит игра (tf_sheen_framerate 25)
_SHEEN_FRAMES = 60
_SHEEN_FPS = 25
_STOCK_MASK = "effects/animatedsheen/animatedsheen0"


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _proxy_name_re(name: str) -> "re.Pattern[str]":
    """Начало прокси `name`: «"Имя" {», и в одну строку, и с комментарием
    перед «{»"""
    return re.compile(r'(?<![\w$])"?' + re.escape(name) + r'"?(?:\s|//[^\n]*)*\{',
                      re.IGNORECASE)


def _has_proxy(text: str, name: str) -> bool:
    """Есть ли в блоке "Proxies" прокси `name` (без комментариев)"""
    m = _PROXIES_RE.search(text)
    close = _match_brace(text, m.end() - 1) if m else -1
    if close < 0:
        return False
    inner = re.sub(r'//[^\n]*', '', text[m.end():close])
    return bool(_proxy_name_re(name).search(inner))


def _drop_keys(text: str, prefix: str) -> str:
    """Убирает строки наших ключей с этим началом (прошлая настройка)"""
    return re.sub(r'^[ \t]*"?' + re.escape(prefix) + r'\w*"?[ \t]+[^\n]*\n?', '', text,
                  flags=re.IGNORECASE | re.MULTILINE)


def _insert_after_proxy(text: str, name: str, chunk: str) -> Optional[str]:
    """`chunk` сразу за прокси `name` в блоке "Proxies"; None - его нет"""
    m = _PROXIES_RE.search(text)
    close = _match_brace(text, m.end() - 1) if m else -1
    if close < 0:
        return None
    rx = _proxy_name_re(name)
    i = m.end()
    while True:
        p = rx.search(text, i, close)
        if not p:
            return None
        line_start = text.rfind('\n', 0, p.start()) + 1
        if '//' not in text[line_start:p.start()]:
            break
        i = p.end()
    end = _match_brace(text, p.end() - 1)
    if end < 0:
        return None
    end += 1
    if text[end:end + 1] == '\n':
        end += 1
    else:
        chunk = '\n' + chunk
    return text[:end] + chunk + text[end:]


def sheen_mask_params(mdl: bytes) -> Optional[dict]:
    """Положение полосы блеска для модели - как его считает игра

    CProxyAnimatedWeaponSheen::InitParams берёт GetRenderBounds сущности, а
    C_BaseAnimating::GetRenderBounds - view_bbmin/max заголовка MDL (если не
    нули, иначе hull_min/max), расширенные рамкой текущей анимации (у
    оружия - нулевой). Ось полосы - самая длинная сторона
    """
    import struct

    if len(mdl) < 200 or mdl[:4] != b'IDST':
        return None
    vec = lambda at: struct.unpack_from('<3f', mdl, at)
    lo, hi = vec(128), vec(140)
    if not any(lo) and not any(hi):
        lo, hi = vec(104), vec(116)
    numseq, seqindex = struct.unpack_from('<ii', mdl, 188)
    if numseq > 0 and 0 < seqindex <= len(mdl) - 56:
        s_lo, s_hi = vec(seqindex + 32), vec(seqindex + 44)
        lo = tuple(min(a, b) for a, b in zip(lo, s_lo))
        hi = tuple(max(a, b) for a, b in zip(hi, s_hi))
    size = [h - l for l, h in zip(lo, hi)]
    # Тот же порядок проверок, что в InitParams: X, потом Y, потом Z
    sx, ox, sy, oy, d = size[0], lo[0], size[2], lo[2], 0
    if size[1] > sx:
        sx, ox, sy, oy, d = size[1], lo[1], size[0], lo[0], 1
    if size[2] > sx:
        sx, ox, sy, oy, d = size[2], lo[2], size[1], lo[1], 2
    if sx <= 0 or sy <= 0 or size[0] <= 0 or size[2] <= 0:
        return None
    # Для своих узоров - трафарет сбоку: направление 0, маска по X и Z,
    # проекция сквозь толщину Y. Только оно проверено калибровкой в игре
    # (Scattergun). Направление игры у оружия, длинного по Z (кунай: Z 19.4,
    # Y 2.3), кладёт по вертикали маски ТОЛЩИНУ клинка, и плоская сторона
    # видела одну строку маски - тонкую линию.
    # Длинное по Z оружие - маска повёрнута: в конструкторе длина всё
    # равно идёт слева направо
    rotate = size[2] > size[0]
    stencil = {"scale_x": size[0], "offset_x": lo[0], "scale_y": size[2], "offset_y": lo[2],
               "direction": 0, "rotate": rotate,
               "aspect": max(size[0], size[2]) / min(size[0], size[2])}
    return {"scale_x": sx, "scale_y": sy, "offset_x": ox, "offset_y": oy, "direction": d,
            "stencil": stencil}


def _stencil(bounds: Optional[dict]) -> Optional[dict]:
    """Раскладка своей маски по оружию (sheen_mask_params["stencil"])"""
    if not bounds:
        return None
    if "stencil" in bounds:
        return bounds["stencil"]
    return {**bounds, "rotate": False,
            "aspect": bounds["scale_x"] / bounds["scale_y"] if bounds.get("scale_y") else 3.0}


def _sheen(vals: Dict[str, object], text: str, bounds: Optional[dict],
           game: str = '') -> Dict[str, object]:
    """Свой цвет блеска: наш Equals ниже AnimatedWeaponSheen перезаписывает
    цвет, который игра ставит каждый кадр"""
    always = vals.get("when") == "always"
    has_game_sheen = _has_proxy(text, "AnimatedWeaponSheen")
    if not always and not has_game_sheen:
        return {"error": "У материала нет блеска киллстрика (прокси AnimatedWeaponSheen). "
                         "Выберите «Всегда, на любом оружии»."}
    if always and not bounds:
        return {"error": "Не удалось прочитать размеры модели для полосы блеска."}
    from src.services import sheen_builder, sheen_library, sheen_palette, sheen_patterns

    pattern = str(vals.get("pattern") or "game")
    # Свой узор красят его слои: гамму (тёплая с белым или холодная с
    # чёрным) выбирают их цвета, оттенок эффекта - по ней, радуги нет
    painted = bool(sheen_library.ID_RE.match(pattern))
    palette = sheen_palette.palette_of(pattern) if painted else None
    # Чёрный: оттенок без красного на маске в красном канале (darkened)
    dark = (palette == sheen_palette.COLD if painted
            else vals.get("dark") == "on" and sheen_library.is_pattern(pattern))
    bright = _num(vals.get("bright"), 0.3, 3, 1)
    rainbow = vals.get("color_mode") == "rainbow" and not painted and not dark
    # Шейдер берёт цвет линейным: цвет палитры переводим, иначе он бледнее
    tint = (sheen_palette.tint(sheen_palette.COLD if dark else sheen_palette.WARM, bright)
            if dark or rainbow or painted
            else tuple(_to_linear(c) * bright for c in _from_hex(vals.get("color"))))

    out = _drop_keys(_strip_marked_proxies(text, _SHEEN_MARK), MARK + "sheen")
    keys = [(MARK + "sheen", _fmt_vec(tint, 6)), (MARK + "sheenbright", f"{bright:g}")]
    # Свой узор - своя маска у ЭТОГО материала (моды подменяют общую маску
    # всего оружия). Кадры крутит тот же прокси игры: пауза между проходами
    # по-прежнему сокращается с серией убийств. Файл маски достроит сборка
    # по имени (sheen_patterns.materialize)
    frames = _SHEEN_FRAMES
    stencil = _stencil(bounds)
    rotate = bool(stencil and stencil["rotate"])
    own = False
    if sheen_library.is_pattern(pattern):
        # Узор конструктора (свой или готовый шаблон): в имени пропорция
        # ЭТОГО оружия - сборка нарисует маску так, чтобы искры на нём были
        # круглыми
        data = sheen_library.load(pattern)
        if data is None:
            return {"error": "Такого своего узора больше нет. Выберите другой."}
        own = True
        # Длина своего узора - из конструктора, у готового - из формы
        length = data["length"] if painted else vals.get("length")
        frames = sheen_patterns.frames_for(_num(length, 1, 8, 2.5))
        aspect = stencil["aspect"] if stencil else sheen_builder.DEFAULT_ASPECT
        keys.append(("$sheenmapmask",
                     sheen_patterns.custom_name(pattern, aspect, frames, rotate, dark)))
    elif (sheen_patterns.parse(_value(out, "$sheenmapmask") or "")
          or sheen_patterns.parse_custom(_value(out, "$sheenmapmask") or "")):
        # Назад к маске материала (у мода она могла быть своя), иначе стоковая
        native = _value(game, "$sheenmapmask") or ""
        own_mask = sheen_patterns.parse(native) or sheen_patterns.parse_custom(native)
        keys.append(("$sheenmapmask", native if native and not own_mask else _STOCK_MASK))
    # Ровная кубмапа - узор виден целиком (sheen_patterns.FLAT_CUBE), у
    # маски игры остаётся игровая, как и при «Живой»
    if own and vals.get("shine") != "live":
        keys.append(("$sheenmap", sheen_patterns.FLAT_CUBE))
    elif sheen_patterns.is_flat_cube(_value(out, "$sheenmap")):
        native = _value(game, "$sheenmap") or ""
        keys.append(("$sheenmap", native if native and not sheen_patterns.is_flat_cube(native)
                     else sheen_patterns.STOCK_CUBE))
    tail = ""
    if rainbow:
        tail += _rainbow(MARK + "sheen", _num(vals.get("speed"), 0.5, 10, 3), bright,
                         _SHEEN_MARK)
    tail += _proxy("Equals", [("srcVar1", MARK + "sheen"), ("resultVar", "$sheenmaptint")],
                   _SHEEN_MARK)
    if own and stencil:
        # Раскладка своей маски закреплена: игра у киллстрик-оружия каждый
        # кадр ставит свою (InitParams), наши Equals ниже её перебивают
        for name, key, value in (
                ("sheenmx", "$sheenmapmaskscaleX", stencil["scale_x"]),
                ("sheenmy", "$sheenmapmaskscaleY", stencil["scale_y"]),
                ("sheenox", "$sheenmapmaskoffsetX", stencil["offset_x"]),
                ("sheenoy", "$sheenmapmaskoffsetY", stencil["offset_y"])):
            keys += [(MARK + name, f"{value:.4g}"), (key, f"{value:.4g}")]
            tail += _proxy("Equals", [("srcVar1", MARK + name), ("resultVar", key)], _SHEEN_MARK)
        keys += [(MARK + "sheendir", "0"), ("$sheenmapmaskdirection", "0")]
        tail += _proxy("Equals", [("srcVar1", MARK + "sheendir"),
                                  ("resultVar", "$sheenmapmaskdirection")], _SHEEN_MARK)
    if always:
        pause = _num(vals.get("pause"), 0, 10, 5)
        # Блеск без киллстрика: параметры прохода, если материала их нет
        for key, value in (("$sheenpassenabled", "1"),
                           ("$sheenmap", sheen_patterns.STOCK_CUBE),
                           ("$sheenmapmask", _STOCK_MASK),
                           ("$sheenmaptint", "[1 1 1]"),
                           ("$sheenmapmaskframe", "0"),
                           ("$sheenindex", "0")):
            if _value(out, key) is None and key not in dict(keys):
                keys.append((key, value))
        if not own:
            # Стоковая маска - раскладка, как её ставит игра (InitParams)
            keys += [("$sheenmapmaskscaleX", f'{bounds["scale_x"]:.4g}'),
                     ("$sheenmapmaskscaleY", f'{bounds["scale_y"]:.4g}'),
                     ("$sheenmapmaskoffsetX", f'{bounds["offset_x"]:.4g}'),
                     ("$sheenmapmaskoffsetY", f'{bounds["offset_y"]:.4g}'),
                     ("$sheenmapmaskdirection", str(bounds["direction"]))]
        keys += [(MARK + "sheenpause", f"{pause:g}"),
                 (MARK + "sheent", "0.0"),
                 (MARK + "sheenlast", f"{frames - 1}.0"),
                 (MARK + "sheenzero", "0.0")]
        # Кадр маски: 1…59 - полоса идёт, 0 - проход не рисуется (пауза)
        cycle = frames + pause * _SHEEN_FPS
        t = MARK + "sheent"
        tail += (_proxy("LinearRamp", [("rate", str(_SHEEN_FPS)), ("initialValue", "0"),
                                       ("resultVar", t)], _SHEEN_MARK)
                 + _proxy("WrapMinMax", [("srcVar1", t), ("minVal", "0"),
                                         ("maxVal", f"{cycle:g}"), ("resultVar", t)],
                          _SHEEN_MARK)
                 + _proxy("Int", [("srcVar1", t), ("resultVar", t)], _SHEEN_MARK)
                 + _proxy("LessOrEqual", [("srcVar1", t), ("srcVar2", MARK + "sheenlast"),
                                          ("lessEqualVar", t),
                                          ("greaterVar", MARK + "sheenzero"),
                                          ("resultVar", "$sheenmapmaskframe")], _SHEEN_MARK))
    for key, value in keys:
        out = _set_key(out, key, value)
    return {"text": _add_proxies(out, "", tail), "replace": False}


def _crit(vals: Dict[str, object], text: str) -> Dict[str, object]:
    """Свой цвет свечения крита: сразу за ModelGlowColor переписываем
    `$glowcolor`, и родные Equals материала несут его в `$color2`"""
    if not _has_proxy(text, "ModelGlowColor"):
        return {"error": "У материала нет свечения крита (прокси ModelGlowColor)."}
    bright = _num(vals.get("bright"), 0.3, 3, 1)
    scale = _CRIT_SCALE * bright
    red = tuple(_to_linear(c) * scale for c in _from_hex(vals.get("red") or "#ff5947"))
    blue = tuple(_to_linear(c) * scale for c in _from_hex(vals.get("blue") or "#4789ff"))

    out = _drop_keys(_strip_marked_proxies(text, _CRIT_MARK), MARK + "crit")
    v = lambda name: MARK + "crit" + name
    keys = [(v("red"), _fmt_vec(red, 6)), (v("blue"), _fmt_vec(blue, 6)),
            (v("bright"), f"{bright:g}"), (v("out"), "[1 1 1]"), (v("zero"), "0.0"),
            (v("one"), "1.0"), (v("k"), "75.0"), (v("k04"), "0.4"), (v("k10"), "10.0")]
    keys += [(v(n), "0.0") for n in ("r", "b", "gn", "fr", "fb", "gate", "w", "g", "t", "c")]

    def p(name, pairs):
        return _proxy(name, pairs, _CRIT_MARK)

    def split(src, dst):
        # Канал вектора в число: Clamp с min = max = "$var[i]" (вики Valve)
        return p("Clamp", [("srcVar1", v("zero")), ("min", src), ("max", src),
                           ("resultVar", dst)])

    def team_share(main, other, share):
        """(main − other) / 75 в 0…1, и только если зелёный мал: у крита RED
        [80 8 5] и BLU [5 20 80] он не больше 0.25 главного канала, а у
        свечения баффов (знамя, Crit-a-Cola: [226 150 62], [29 202 135])
        большой - их цвет остаётся родным. Ворота: (0.4·главный − G) / 10"""
        return (p("Subtract", [("srcVar1", main), ("srcVar2", other), ("resultVar", share)])
                + p("Divide", [("srcVar1", share), ("srcVar2", v("k")), ("resultVar", share)])
                + p("Clamp", [("srcVar1", share), ("min", "0"), ("max", "1"),
                              ("resultVar", share)])
                + p("Multiply", [("srcVar1", main), ("srcVar2", v("k04")),
                                 ("resultVar", v("gate"))])
                + p("Subtract", [("srcVar1", v("gate")), ("srcVar2", v("gn")),
                                 ("resultVar", v("gate"))])
                + p("Divide", [("srcVar1", v("gate")), ("srcVar2", v("k10")),
                               ("resultVar", v("gate"))])
                + p("Clamp", [("srcVar1", v("gate")), ("min", "0"), ("max", "1"),
                              ("resultVar", v("gate"))])
                + p("Multiply", [("srcVar1", share), ("srcVar2", v("gate")),
                                 ("resultVar", share)]))

    # Доля RED и BLU: крит RED даёт 1 и 0, BLU - 0 и 1, обычное [1 1 1] -
    # 0 и 0; заряд щита демо растёт плавно
    chain = (split("$glowcolor[0]", v("r")) + split("$glowcolor[1]", v("gn"))
             + split("$glowcolor[2]", v("b"))
             + team_share(v("r"), v("b"), v("fr")) + team_share(v("b"), v("r"), v("fb"))
             + p("Subtract", [("srcVar1", v("one")), ("srcVar2", v("fr")), ("resultVar", v("w"))])
             + p("Subtract", [("srcVar1", v("w")), ("srcVar2", v("fb")), ("resultVar", v("w"))]))
    # Канал i: игра × w + RED × fr + BLU × fb - в свой вектор по каналу
    for i in range(3):
        chain += (split(f"$glowcolor[{i}]", v("g"))
                  + p("Multiply", [("srcVar1", v("g")), ("srcVar2", v("w")), ("resultVar", v("t"))])
                  + split(f'{v("red")}[{i}]', v("c"))
                  + p("Multiply", [("srcVar1", v("c")), ("srcVar2", v("fr")), ("resultVar", v("c"))])
                  + p("Add", [("srcVar1", v("t")), ("srcVar2", v("c")), ("resultVar", v("t"))])
                  + split(f'{v("blue")}[{i}]', v("c"))
                  + p("Multiply", [("srcVar1", v("c")), ("srcVar2", v("fb")), ("resultVar", v("c"))])
                  + p("Add", [("srcVar1", v("t")), ("srcVar2", v("c")),
                              ("resultVar", f'{v("out")}[{i}]')]))
    # Целиком, а не по каналам: так пишут Valve (Equals $glowcolor -> $color2)
    chain += p("Equals", [("srcVar1", v("out")), ("resultVar", "$glowcolor")])
    for key, value in keys:
        out = _set_key(out, key, value)
    done = _insert_after_proxy(out, "ModelGlowColor", chain)
    if done is None:
        return {"error": "У материала нет свечения крита (прокси ModelGlowColor)."}
    return {"text": done, "replace": False}


def _ghost(vals: Dict[str, object], text: str, game: str = '') -> str:
    """Весь материал заново. Основа - белая («свой цвет») или родная текстура:
    её сборка потом заменит на текстуру человека, если он её положил"""
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
        # Контур и отражение одного цвета: радуга на самосвет, отражение -
        # его копия (Equals копирует и вектор: CEqualsProxy, mathproxy.cpp)
        glow = _fmt_vec((bright, bright, bright))
        proxies += (_rainbow("$selfillumtint", _num(vals.get("speed"), 0.5, 10, 3), bright)
                    + _proxy("Equals", [("srcVar1", "$selfillumtint"),
                                        ("resultVar", "$envmaptint")]))
    return (
        '"VertexLitGeneric"\n'
        '{\n'
        f'\t"$basetexture" "{base}"\n'
        # Комментарии в самом VMT - по-английски: файл уходит в мод, и его
        # открывают люди с любым языком
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
    """Вливается в материал: ключи - на место одноимённых, прокси - свои"""
    factor = _GLASS_LOOK.get(str(vals.get("look")), _GLASS_LOOK["edge"])
    keys = [
        ("$cloakpassenabled", "1"),
        ("$cloakcolortint", _fmt_vec(_from_hex(vals.get("color")))),
        ("$refractamount", f'{_num(vals.get("refract"), 0, 4, 2):g}'),
        (MARK + "glass", f"{factor:g}"),
        (MARK + "zero", "0"),
        # Цвет радуги до копирования в $cloakcolortint (объявлен вектором,
        # иначе прокси его не найдут)
        (MARK + "rgb", "[1 1 1]"),
    ]
    out = _strip_marked_proxies(text)
    for key, value in keys:
        out = _set_key(out, key, value)
    # Порядок важен: обнулить -> невидимость шпиона -> прибавить стекло ->
    # обрезать до 1. Обнуление само по себе: прокси невидимости ставит
    # значение не в каждом кадре (без сущности OnBind не зовётся), и без него
    # «прибавить» копило бы фактор до полной невидимости
    has_invis = _has_invis(out)
    head = _proxy("Equals", [("srcVar1", MARK + "zero"), ("resultVar", "$cloakfactor")])
    if not has_invis:
        head += _proxy("invis", [])
    tail = (_proxy("Add", [("srcVar1", "$cloakfactor"), ("srcVar2", MARK + "glass"),
                           ("resultVar", "$cloakfactor")])
            + _proxy("Clamp", [("min", "0"), ("max", "1"), ("srcVar1", "$cloakfactor"),
                               ("resultVar", "$cloakfactor")]))
    if vals.get("color_mode") == "rainbow":
        # Тон стекла по кругу, действует, пока фактор плаща < 0.75 - то есть
        # всегда, кроме настоящей невидимости шпиона. Синусоиды пишут СВОЮ
        # переменную, а в $cloakcolortint она копируется целиком: запись по
        # каналам прямо в параметр плаща в игре гасила стекло совсем (сборка
        # человека), а у Valve ни один материал прокси плаща по каналам не
        # пишет - только целиком, как Equals $glowcolor -> $color2
        tail += (_rainbow(MARK + "rgb", _num(vals.get("speed"), 0.5, 10, 3))
                 + _proxy("Equals", [("srcVar1", MARK + "rgb"),
                                     ("resultVar", "$cloakcolortint")]))
    return _add_proxies(out, head, tail)


def _rainbow(var: str, period: float, peak: float = 1.0, mark: str = None) -> str:
    """Три прокси Sine на каналы `var`: цвет идёт по кругу за `period` секунд

    Каналы сдвинуты на треть круга (timeOffset), поэтому оттенок меняется, а
    яркость почти нет: сумма трёх синусоид со сдвигом 120° постоянна
    """
    return ''.join(
        _proxy("Sine", [("resultVar", f"{var}[{i}]"), ("sinePeriod", f"{period:g}"),
                        ("timeOffset", f"{period * i / 3:.3g}"),
                        ("sineMin", "0"), ("sineMax", f"{peak:g}")],
               mark or _PROXY_MARK)
        for i in range(3))


def _rainbow_info(text: str, var: str) -> Optional[Tuple[float, float]]:
    """(период, пик) радуги на `var`, если она стоит, иначе None"""
    for block in re.findall(r'"?sine"?\s*\{([^}]*)\}', text, re.IGNORECASE):
        if f'{var.lower()}[0]' not in block.lower():
            continue
        def num(name, default):
            m = re.search(r'"?' + name + r'"?\s+"?([-\d.]+)', block, re.IGNORECASE)
            return float(m.group(1)) if m else default
        return num('sineperiod', 3.0), num('sinemax', 1.0)
    return None


def _has_invis(text: str) -> bool:
    """Есть ли в блоке "Proxies" прокси невидимости - «invis» или старые
    weapon_invis / vm_invis / spy_invis: все пишут $cloakfactor"""
    m = _PROXIES_RE.search(text)
    close = _match_brace(text, m.end() - 1) if m else -1
    if close < 0:
        return False
    inner = re.sub(r'//[^\n]*', '', text[m.end():close])
    return bool(re.search(r'"?\b(?:\w+_)?invis"?\s*\{', inner, re.IGNORECASE))


def _set_key(text: str, key: str, value: str) -> str:
    """Меняет значение ключа на месте, нет ключа - строка за первой «{»"""
    line = f'"{key}" "{value}"'
    rx = _key_re(key)
    if rx.search(text):
        # Все одноимённые строки: в VMT действует последняя, и оставленная
        # старая могла бы перекрыть новую
        return rx.sub(lambda m: m.group(1) + line, text)
    at = _first_brace(text)
    at = len(text) if at < 0 else at + 1
    return text[:at] + '\n\t' + line + text[at:]


def _first_brace(text: str) -> int:
    """Первая «{» вне комментариев и строк (шапка `// by me {v2}` - не она)"""
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
#: все они ссылаются на помеченную переменную (Clamp - только на $cloakfactor)
_PROXY_MARK = "// tf2sg"


def _proxy(name: str, pairs: List[Tuple[str, str]], mark: str = _PROXY_MARK) -> str:
    body = ''.join(f'\t\t\t"{k}" "{v}"\n' for k, v in pairs)
    return f'\t\t"{name}"\n\t\t{{\n\t\t\t{mark}\n{body}\t\t}}\n'


_PROXIES_RE = re.compile(r'^[ \t]*"?proxies"?(?:\s|//[^\n]*)*\{', re.IGNORECASE | re.MULTILINE)


def _match_brace(text: str, open_at: int) -> int:
    """Парная «}», скобки в строках и комментариях не в счёт. -1 - не закрыта"""
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
    """`head` - в начало блока "Proxies", `tail` - в конец, нет блока - свой

    Блок один: материал читает только первый "Proxies" (KeyValues::FindKey)
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


def _strip_marked_proxies(text: str, mark: str = _PROXY_MARK) -> str:
    """Убирает из "Proxies" наши прошлые прокси (с меткой `mark`)"""
    m = _PROXIES_RE.search(text)
    close = _match_brace(text, m.end() - 1) if m else -1
    if close < 0:
        return text
    inner = text[m.end():close]
    kept, i = [], 0
    # С начала строки: иначе «имя {» ловилось бы и в комментарии
    # (`// TODO Sine {`), разбор уезжал, и свои прокси копились бы
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
        # следующая сборка добавит его снова, раз родного нет
        if not re.search(r'^[ \t]*' + re.escape(mark) + r'[ \t]*$', chunk, re.MULTILINE):
            kept.append(chunk)
        i = chunk_end
    return text[:m.end()] + ''.join(kept) + text[close:]


#: Для переноса правки во все материалы (vmt_spread): наши прокси не в счёт
strip_marked_proxies = _strip_marked_proxies
