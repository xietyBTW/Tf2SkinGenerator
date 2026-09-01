"""
Сборка одной текстуры из того, что положили на РАЗНЫЕ части модели.

Материал у оружия один, значит и текстура в моде одна. «Своя картинка на
ствол» или «синий приклад» — это не второй материал, а вклейка в общую
текстуру: берём место части на развёртке и рисуем там.

Дальше по конвейеру эта склейка ничем не отличается от обычной
пользовательской текстуры — её же и подставляем. Поэтому ни сборка, ни
автосохранение, ни превью про части ничего не знают.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

UvTri = Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]

#: Насколько расширить маску части, в пикселях. Ровно по краю остаются швы:
#: при уменьшении текстуры (мипмапы) в край подмешивается соседний пиксель. У
#: развёрток TF2 между островами есть зазор, поэтому один пиксель безопасен.
_BLEED = 1


@dataclass(frozen=True)
class Layer:
    """Что положили на одну часть: картинка ИЛИ цвет."""

    polygons: Sequence[UvTri]
    #: Файл картинки. Растягивается на место части.
    image: Optional[str] = None
    #: Тонировка «#rrggbb». Яркость оригинала сохраняется — иначе от модели
    #: остаётся цветное пятно без единой детали.
    color: Optional[str] = None
    #: Второй цвет: тонировка становится градиентом от color к color2 по месту
    #: части на развёртке. Так делают настоящие скины — одним цветом деталь
    #: выглядит плоской.
    color2: Optional[str] = None
    #: Направление градиента: True — поперёк (слева направо), иначе сверху вниз.
    horizontal: bool = False
    #: Сила тонировки: 1.0 — полностью в цвет, 0.3 — лёгкий оттенок.
    strength: float = 1.0


def _mask(polygons: Iterable[UvTri], size: Tuple[int, int]) -> Image.Image:
    """Маска части: её треугольники развёртки, закрашенные на холсте текстуры.

    v развёртки растёт СНИЗУ (OpenGL), строки картинки — сверху: без
    переворота картинка легла бы зеркально по вертикали.
    """
    width, height = size
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    for tri in polygons:
        draw.polygon([(u * width, (1.0 - v) * height) for u, v in tri], fill=255)
    if _BLEED:
        mask = mask.filter(ImageFilter.MaxFilter(2 * _BLEED + 1))
    return mask


def _rgb(color: str) -> Optional[Tuple[int, int, int]]:
    """«#rrggbb» → (r, g, b). Мусор превращать в чёрный нельзя: это была бы
    молча закрашенная деталь."""
    text = (color or '').strip().lstrip('#')
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _paint_layer(size: Tuple[int, int], box: Tuple[int, int, int, int],
                 first: Tuple[int, int, int],
                 second: Optional[Tuple[int, int, int]],
                 horizontal: bool) -> Image.Image:
    """
    Слой краски: сплошной цвет или градиент по месту части на развёртке.

    Градиент строится в границах ЧАСТИ, а не всей текстуры: иначе на мелкой
    детали виден один цвет из двух, и переход пропадает.
    """
    canvas = Image.new('RGB', size, first)
    if not second:
        return canvas

    width = max(1, box[2] - box[0])
    height = max(1, box[3] - box[1])
    steps = width if horizontal else height
    ramp = Image.new('RGB', (steps, 1) if horizontal else (1, steps))
    pixels = ramp.load()
    for i in range(steps):
        k = i / (steps - 1) if steps > 1 else 0.0
        shade = tuple(int(round(first[c] + (second[c] - first[c]) * k))
                      for c in range(3))
        pixels[(i, 0) if horizontal else (0, i)] = shade
    canvas.paste(ramp.resize((width, height)), (box[0], box[1]))
    return canvas


def _tinted(base: Image.Image, paint: Image.Image,
            strength: float) -> Image.Image:
    """
    Тонировка: цвет ложится как краска, детали остаются.

    Взято overlay, а не умножение: умножение гасит тёмную текстуру в чёрное
    («красный ствол» выходит угольным), а раскраска по яркости — мутной.
    Overlay держит и тени, и блики, поэтому дерево остаётся деревом, просто
    красным. Проверено на стоковой текстуре обреза.
    """
    lit = ImageChops.overlay(base.convert('RGB'), paint).convert('RGBA')
    lit.putalpha(base.getchannel('A'))
    amount = min(1.0, max(0.0, float(strength)))
    return Image.blend(base, lit, amount) if amount < 1.0 else lit


def compose(base_path: str,
            layers: Sequence[Layer],
            out_path: str) -> Optional[str]:
    """
    Вклеивает в базовую текстуру всё, что назначено частям.

    Args:
        base_path: текстура, поверх которой рисуем (игровая или своя).
        layers:    слои по порядку; у каждого своя маска-часть.
        out_path:  куда записать склейку.

    Returns:
        Путь к склейке или None, если рисовать оказалось нечего.
    """
    if not (base_path and os.path.isfile(base_path)):
        logger.warning(f"склейка частей: нет базовой текстуры {base_path!r}")
        return None

    try:
        base = Image.open(base_path).convert('RGBA')
    except OSError as exc:
        logger.warning(f"склейка частей: {base_path} не читается: {exc}")
        return None

    size = base.size
    drawn = 0
    for layer in layers:
        if not layer.polygons:
            continue
        mask = _mask(layer.polygons, size)
        box = mask.getbbox()
        if not box:
            continue                      # часть не попала на холст развёртки

        if layer.image:
            if not os.path.isfile(layer.image):
                continue
            try:
                patch = Image.open(layer.image).convert('RGBA')
            except OSError as exc:
                logger.warning(f"склейка частей: {layer.image} не читается: {exc}")
                continue
            # Картинка растягивается на место части: человек кладёт её «на
            # ствол», а не в угол развёртки.
            patch = patch.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
            canvas = Image.new('RGBA', size, (0, 0, 0, 0))
            canvas.paste(patch, (box[0], box[1]))
            # Прозрачность картинки уважаем: иначе PNG с альфой затирал бы
            # часть чёрным вместо того, чтобы показать текстуру под собой.
            mask = ImageChops.multiply(mask, canvas.getchannel('A'))
        elif layer.color:
            rgb = _rgb(layer.color)
            if not rgb:
                continue
            canvas = _tinted(
                base,
                _paint_layer(size, box, rgb, _rgb(layer.color2 or ''),
                             layer.horizontal),
                layer.strength)
        else:
            continue

        base = Image.composite(canvas, base, mask)
        drawn += 1

    if not drawn:
        return None

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    base.save(out_path)
    logger.info(f"склейка частей: {drawn} шт. → {os.path.basename(out_path)}")
    return out_path
