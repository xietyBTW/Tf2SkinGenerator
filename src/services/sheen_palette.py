"""
Гамма своего узора блеска: какие цвета слоёв игра вообще покажет

Проверено в игре (обрез, «чёрный блеск»): у прохода блеска
непрозрачность = яркость оттенка эффекта x КРАСНЫЙ канал маски, а цвет =
оттенок x маска по каналам (weapon_sheen_pass). Отсюда правило: у всех
полностью видимых слоёв одного материала доля красного одна и та же, её
задаёт оттенок. Поэтому узор живёт в одной из двух гамм:

  тёплая    оттенок белый             белый, жёлтый, оранжевый, красный,
            маска = цвет слоя          розовый, фиолетовый
  холодная  оттенок (0, 1, 1)         чёрный, синий, голубой, зелёный,
            красный канал маски =      бирюзовый
            форма слоя, зелёный и
            синий = его цвет

Гамму выбирают цвета слоёв, человеку думать о ней не нужно. Слой не из
своей гаммы в игре не виден (`classify` называет такие слои)
"""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

WARM, COLD = "warm", "cold"

#: Цвет «без красного» (0…1 sRGB): красного почти нет или он меньше половины
#: зелёного и синего. В тёплой гамме такой слой почти не виден (его
#: непрозрачность - его красный), в холодной - виден своим цветом
_NO_RED = 0.15


def _rgb(hexc: str) -> Tuple[float, float, float]:
    text = str(hexc or "").lstrip("#")
    try:
        return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (1.0, 1.0, 1.0)


def is_cold(hexc: str) -> bool:
    """Цвет показывает только холодная гамма"""
    r, g, b = _rgb(hexc)
    return r <= _NO_RED or r < 0.5 * max(g, b)


def _needs(layer: dict) -> Set[str]:
    """Каким гаммам нужны цвета слоя, пусто - слой цвета не несёт"""
    if not layer.get("on", True) or layer.get("blend") in ("mask", "cut"):
        return set()
    fill = layer.get("fill", "solid")
    if fill == "image":
        return {WARM}                      # цвета картинки - как есть
    colours = ([c for _pos, c in layer.get("stops") or []]
               if fill in ("space", "time") else [layer.get("color", "#ffffff")])
    return {COLD if is_cold(c) else WARM for c in colours}


def classify(spec: dict) -> Dict[str, object]:
    """Гамма узора и слои, которые в ней не видны

    Холодная - если слоёв с чёрным/синим/зелёным больше, чем со светлыми и
    тёплыми цветами, поровну - тёплая (так узоры работали всегда)

    Returns:
        {"palette": WARM|COLD, "lost": [номера слоёв, невидимых в игре]}
    """
    needs = [_needs(layer) for layer in spec.get("layers") or []]
    cold = sum(1 for n in needs if COLD in n and WARM not in n)
    warm = sum(1 for n in needs if WARM in n and COLD not in n)
    palette = COLD if cold > warm else WARM
    other = WARM if palette == COLD else COLD
    return {"palette": palette, "lost": [i for i, n in enumerate(needs) if other in n]}


def tint(palette: str, bright: float) -> Tuple[float, float, float]:
    """Оттенок эффекта для гаммы (линейный, как пишет vmt_effects)"""
    return (0.0, bright, bright) if palette == COLD else (bright, bright, bright)


def palette_of(pattern_id: str) -> Optional[str]:
    """Гамма своего узора по id; None - узора нет"""
    from src.services import sheen_library
    data = sheen_library.load(pattern_id, deleted=True)
    return classify(data["spec"])["palette"] if data else None

