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

import math
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

UvTri = Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]

#: Запас маски в долях стороны текстуры. Ровно по краю части в игре остаётся
#: полоска исходного цвета: остров растеризуется по центрам пикселей (до
#: полпикселя теряется сразу), потом движок фильтрует текстуру билинейно и
#: строит мипмапы — на дальних уровнях в край подмешивается то, что снаружи.
#: Одного пикселя на это не хватало, и края частей было видно на модели.
#:
#: 0.4% стороны — это 8 px на 2048 и 2 px на 512, примерно столько же кладут
#: запекатели развёрток. Замерено на моделях TF2: расширение даже на 8 px не
#: задевает НИ ОДНОГО пикселя соседних частей — между островами есть зазор.
_BLEED_SHARE = 0.004
_BLEED_MIN = 2
_BLEED_MAX = 8


def _bleed_for(size: Tuple[int, int]) -> int:
    """Запас маски для текстуры такого размера."""
    side = max(1, min(size))
    return max(_BLEED_MIN, min(_BLEED_MAX, round(side * _BLEED_SHARE)))


@dataclass(frozen=True)
class Layer:
    """Что положили на одну часть: картинка ИЛИ цвет."""

    polygons: Sequence[UvTri]
    #: Файл картинки. Кладётся на место части по правилам ниже.
    image: Optional[str] = None
    #: Как вписать картинку в место части:
    #: 'contain' — целиком, с сохранением пропорций (умолчание: растяжение по
    #: прямоугольнику корёжило логотипы, а заметно это только в игре);
    #: 'cover' — заполнить место, лишнее обрезать;
    #: 'stretch' — растянуть по прямоугольнику, пропорции побоку.
    fit: str = 'contain'
    #: Поворот картинки в градусах по часовой стрелке. Остров развёртки нередко
    #: лежит боком, и без поворота надпись на детали читается вбок.
    image_angle: float = 0.0
    #: Множитель поверх вписывания: 1.0 — как вписалось, 2.0 — вдвое крупнее.
    image_scale: float = 1.0
    #: Сдвиг центра в долях места части: (0.5, 0) — на пол-ширины вправо.
    image_offset: Tuple[float, float] = (0.0, 0.0)
    #: Тонировка «#rrggbb». Яркость оригинала сохраняется — иначе от модели
    #: остаётся цветное пятно без единой детали.
    color: Optional[str] = None
    #: Второй цвет: тонировка становится градиентом от color к color2 по месту
    #: части на развёртке. Так делают настоящие скины — одним цветом деталь
    #: выглядит плоской.
    color2: Optional[str] = None
    #: Направление градиента в градусах: 0 — сверху вниз, дальше по часовой
    #: стрелке (90 — слева направо). Углом, а не флагом «поперёк»: наклонный
    #: переход на детали читается как объём, а двух вариантов на это не хватает.
    angle: float = 0.0
    #: Сила тонировки: 1.0 — полностью в цвет, 0.3 — лёгкий оттенок.
    strength: float = 1.0
    #: Окантовка: ширина полосы по краю части в долях стороны текстуры.
    #: 0 — без окантовки. В долях, а не в пикселях: одна и та же работа
    #: собирается и в 512, и в 2048, и полоса должна выглядеть одинаково.
    edge: float = 0.0
    #: Цвет окантовки «#rrggbb». Пусто — берётся цвет самой части.
    edge_color: Optional[str] = None


def place_image(patch: Image.Image, box: Tuple[int, int, int, int],
                fit: str = 'contain', angle: float = 0.0, scale: float = 1.0,
                offset: Tuple[float, float] = (0.0, 0.0)):
    """
    Готовит картинку к вклейке: размер, поворот, положение.

    Возвращает (картинка, куда её положить). Порядок — размер, потом поворот:
    поворот увеличивает холст под углы, и вписывать после него значило бы
    вписывать пустоту вместе с картинкой.

    Публичная: тем же расчётом страница рисует предпросмотр, и разойтись им
    нельзя — человек настраивает по одному изображению, а в мод уходит другое.
    """
    width = max(1, box[2] - box[0])
    height = max(1, box[3] - box[1])
    source = max(1, patch.width), max(1, patch.height)

    if fit == 'stretch':
        target = (width, height)
    else:
        pick = max if fit == 'cover' else min
        k = pick(width / source[0], height / source[1])
        target = (source[0] * k, source[1] * k)

    k = max(0.01, float(scale))
    target = (max(1, round(target[0] * k)), max(1, round(target[1] * k)))
    patch = patch.resize(target, Image.LANCZOS)
    if angle:
        # PIL крутит против часовой, а угол задаём по часовой — как у ручки
        # направления градиента, чтобы два поворота в одном окне не спорили.
        patch = patch.rotate(-float(angle), resample=Image.BICUBIC, expand=True)

    cx = box[0] + width / 2 + float(offset[0]) * width
    cy = box[1] + height / 2 + float(offset[1]) * height
    return patch, (round(cx - patch.width / 2), round(cy - patch.height / 2))


def _spread(mask: Image.Image, radius: int, grow: bool) -> Image.Image:
    """
    Расширяет (`grow`) или ужимает маску на `radius` пикселей.

    Не `MaxFilter`/`MinFilter`: PIL считает их наивно, по всему ядру, и на
    текстуре 2048x2048 запас в 8 пикселей стоил 1.2 с НА КАЖДУЮ часть, а
    окантовка в 41 пиксель — 17 секунд. Покраска из-за этого встала колом.

    Квадратное ядро раскладывается: расширение на a, потом на b, равно
    расширению на a+b. Поэтому идём степенями двойки (1, 2, 4, …) — вместо
    ядра radius получается log2(radius) проходов. Каждый проход — по осям
    отдельно, тоже свойство квадрата.
    """
    if radius < 1:
        return mask
    data = np.asarray(mask)
    fill = 0 if grow else 255
    pick = np.maximum if grow else np.minimum

    left = radius
    step = 1
    while left > 0:
        move = min(step, left)
        for axis in (0, 1):
            shifted_up = np.roll(data, move, axis=axis)
            shifted_down = np.roll(data, -move, axis=axis)
            # roll заворачивает край на противоположный — обрубаем, иначе
            # деталь у левого края «расширилась» бы у правого.
            if axis == 0:
                shifted_up[:move, :] = fill
                shifted_down[-move:, :] = fill
            else:
                shifted_up[:, :move] = fill
                shifted_down[:, -move:] = fill
            data = pick(pick(data, shifted_up), shifted_down)
        left -= move
        step *= 2
    return Image.fromarray(data, 'L')


def _mask(polygons: Iterable[UvTri], size: Tuple[int, int],
          bleed: Optional[int] = None) -> Image.Image:
    """Маска части: её треугольники развёртки, закрашенные на холсте текстуры.

    v развёртки растёт СНИЗУ (OpenGL), строки картинки — сверху: без
    переворота картинка легла бы зеркально по вертикали.
    """
    width, height = size
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    for tri in polygons:
        draw.polygon([(u * width, (1.0 - v) * height) for u, v in tri], fill=255)
    grow = _bleed_for(size) if bleed is None else bleed
    return _spread(mask, grow, True) if grow > 0 else mask


#: Размер картинки-подсветки. Её показывают поверх кадра текстуры (около
#: 250 px на экране), поэтому больше половины тысячи не нужно, а меньше —
#: заметны ступеньки на тонких деталях.
_SPOT_SIZE = 512


def dense_bbox(polygons: Sequence[UvTri], cut: float = 0.04):
    """
    Габарит ПЛОТНОЙ части детали: без редких дальних островков.

    Обычный габарит для приближения не годится: у половины частей острова
    разбросаны по всей развёртке, и прямоугольник вокруг них — почти вся
    текстура. У обреза это давало окну масштаб x0.87, то есть оно не
    приближало, а отдаляло.

    Отбрасываем по `cut` доли ПЛОЩАДИ с каждого края по каждой оси: площадь, а
    не число точек, — иначе один крупный остров перевесила бы россыпь мелких.
    """
    items = []
    for tri in polygons:
        (u1, v1), (u2, v2), (u3, v3) = tri
        area = abs((u2 - u1) * (v3 - v1) - (u3 - u1) * (v2 - v1)) / 2
        items.append((area, [p[0] for p in tri], [p[1] for p in tri]))
    if not items:
        return (0.0, 0.0, 1.0, 1.0)
    total = sum(a for a, _, _ in items) or 1e-9

    def edge(axis: int):
        pts = []
        for area, us, vs in items:
            for value in (us if axis == 0 else vs):
                pts.append((value, area / 3))
        pts.sort()
        low = pts[0][0]
        high = pts[-1][0]
        acc = 0.0
        for value, weight in pts:
            acc += weight
            if acc >= total * cut:
                low = value
                break
        acc = 0.0
        for value, weight in reversed(pts):
            acc += weight
            if acc >= total * cut:
                high = value
                break
        return (low, high) if high > low else (pts[0][0], pts[-1][0])

    u0, u1 = edge(0)
    v0, v1 = edge(1)
    return (u0, v0, u1, v1)


def outline_png(polygons: Sequence[UvTri], out_path: str,
                rgb: Tuple[int, int, int] = (204, 85, 34)) -> str:
    """
    Форма части на развёртке — картинкой: заливка плюс обводка по краю.

    Картинкой, а не списком координат: у крупного куска их полторы тысячи, и
    возить их на страницу ради КАЖДОГО наведения дороже, чем отдать PNG в
    несколько килобайт, который браузер к тому же закэширует.

    Обводку берём как разницу расширенной маски и исходной — рисовать рёбра
    треугольников нельзя, получилась бы сетка, а не контур детали.
    """
    size = (_SPOT_SIZE, _SPOT_SIZE)
    # Без запаса: здесь показывают форму части, а не красят её. Расширенный
    # контур врал бы о том, где деталь кончается.
    mask = _mask(polygons, size, bleed=0)
    edge = ImageChops.subtract(_spread(mask, 2, True), mask)

    spot = Image.new('RGBA', size, (0, 0, 0, 0))
    spot.paste(Image.new('RGBA', size, (*rgb, 70)), mask=mask)
    spot.paste(Image.new('RGBA', size, (*rgb, 255)), mask=edge)

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    spot.save(out_path)
    return out_path


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
                 angle: float = 0.0) -> Image.Image:
    """
    Слой краски: сплошной цвет или градиент по месту части на развёртке.

    Градиент строится в границах ЧАСТИ, а не всей текстуры: иначе на мелкой
    детали виден один цвет из двух, и переход пропадает.

    Ось задаётся углом: 0 — сверху вниз, дальше по часовой стрелке. Считается
    проекцией каждого пикселя на ось, а не поворотом готовой картинки —
    поворот пришлось бы строить с запасом и обрезать, и на краях части
    оставались бы пустые углы.
    """
    canvas = Image.new('RGB', size, first)
    if not second:
        return canvas

    width = max(1, box[2] - box[0])
    height = max(1, box[3] - box[1])
    rad = math.radians(float(angle))
    dx, dy = math.sin(rad), math.cos(rad)

    xs = (np.arange(width) + 0.5) / width - 0.5
    ys = (np.arange(height) + 0.5) / height - 0.5
    projection = xs[None, :] * dx + ys[:, None] * dy
    # Нормируем по РАЗМАХУ проекции прямоугольника, а не по его стороне: иначе
    # на наклонной оси крайние цвета не доходят до углов части.
    span = abs(dx) + abs(dy) or 1.0
    k = np.clip(projection / span + 0.5, 0.0, 1.0)[..., None]

    a = np.array(first, dtype=float)
    b = np.array(second, dtype=float)
    ramp = np.rint(a + (b - a) * k).astype(np.uint8)
    canvas.paste(Image.fromarray(ramp, 'RGB'), (box[0], box[1]))
    return canvas


def edge_band(mask: Image.Image, width: int) -> Image.Image:
    """
    Полоса по краю маски: сама маска минус её же, ужатая внутрь.

    Ужимаем (MinFilter), а не расширяем: окантовка должна лечь ВНУТРЬ части,
    иначе она вылезет на соседнюю деталь и покрасит чужое.
    """
    if width < 1:
        return Image.new('L', mask.size, 0)
    return ImageChops.subtract(mask, _spread(mask, width, False))


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


#: Больше кадров в VTF не влезает по-хорошему: анимация в Source живёт на весь
#: материал, и каждый кадр — ещё одна полноразмерная картинка в моде. Гифка на
#: 200 кадров раздула бы текстуру предмета в двести раз.
_MAX_FRAMES = 64

#: Сколько памяти готовы отдать под кадры склейки. Все кадры APNG живут в
#: списке одновременно (Pillow иначе его не запишет), а кадр текстуры 2048×2048
#: — это 16 МБ: шестьдесят четыре таких кадра положили бы приложение на ровном
#: месте. Потолок по площади важнее потолка по числу.
_FRAME_BUDGET = 320 * 1024 * 1024


def _frame_budget(size: Tuple[int, int], wanted: int) -> int:
    """Сколько кадров осилим при таком размере текстуры (минимум один)."""
    per_frame = max(1, size[0] * size[1] * 4)
    return max(1, min(wanted, _FRAME_BUDGET // per_frame))


def _frames_of(path: str) -> int:
    """Сколько кадров в картинке; 1 — обычная."""
    try:
        with Image.open(path) as img:
            return max(1, int(getattr(img, 'n_frames', 1)))
    except (OSError, ValueError):
        return 1


def _frame(path: str, index: int) -> Optional[Image.Image]:
    """Кадр анимации (или сама картинка). Короткая анимация зацикливается."""
    try:
        img = Image.open(path)
        count = max(1, int(getattr(img, 'n_frames', 1)))
        if count > 1:
            img.seek(index % count)
        return img.convert('RGBA')
    except (OSError, ValueError, EOFError) as exc:
        logger.warning(f"склейка частей: {path} не читается: {exc}")
        return None


def _durations(path: str, count: int) -> List[int]:
    """Длительности кадров в мс. Без метки — 100 мс, как принято у GIF."""
    out: List[int] = []
    try:
        with Image.open(path) as img:
            for i in range(count):
                img.seek(i % max(1, int(getattr(img, 'n_frames', 1))))
                out.append(int(img.info.get('duration') or 100))
    except (OSError, ValueError, EOFError):
        out = [100] * count
    return out or [100] * count


def frame_count(path: str) -> int:
    """Сколько кадров в картинке; 1 — обычная. Публичная: тем же числом окно
    посадки решает, крутить ли предпросмотр."""
    return _frames_of(path)


def export_frames(path: str, out_dir: str, prefix: str,
                  limit: int = _MAX_FRAMES) -> Tuple[List[str], List[int]]:
    """
    Раскладывает анимацию по PNG-кадрам и отдаёт (файлы, длительности в мс).

    Нужна окну посадки: браузер из гифки кадры не достаёт — отсоединённый
    `<img>` её не крутит, а `drawImage` берёт всегда первый. Разбираем тем же
    PIL, что и склейка, поэтому предпросмотр показывает ровно то, что уйдёт в
    мод.
    """
    count = min(limit, _frames_of(path))
    if count < 2:
        return [], []
    os.makedirs(out_dir, exist_ok=True)
    made: List[str] = []
    for index in range(count):
        frame = _frame(path, index)
        if frame is None:
            break
        out = os.path.join(out_dir, f"{prefix}_{index:03d}.png")
        frame.save(out)
        made.append(out)
    return made, _durations(path, len(made))


def _masks_for(layers: Sequence[Layer], size: Tuple[int, int]):
    """
    Маска и место каждого слоя — ОДИН раз на всю анимацию.

    Маска чисто геометрическая: от кадра она не зависит, а стоит дорого (0.08 с
    на полутора тысячах треугольников при 2048×2048). Считать её в цикле кадров
    значило подарить пять секунд на каждую перекраску шестидесяти четырёх
    кадров — при том что результат каждый раз один и тот же.
    """
    out = []
    for layer in layers:
        if not layer.polygons:
            out.append(None)
            continue
        mask = _mask(layer.polygons, size)
        box = mask.getbbox()
        out.append((mask, box) if box else None)   # None — часть вне холста
    return out


def _compose_frame(base: Image.Image, layers: Sequence[Layer],
                   ready, frame: int) -> Tuple[Image.Image, int]:
    """Один кадр склейки: база плюс все слои. Возвращает (картинка, сколько легло)."""
    size = base.size
    drawn = 0
    for layer, prepared in zip(layers, ready):
        if prepared is None:
            continue
        mask, box = prepared

        if layer.image:
            if not os.path.isfile(layer.image):
                continue
            patch = _frame(layer.image, frame)
            if patch is None:
                continue
            # Картинка ложится на место части: человек кладёт её «на ствол», а
            # не в угол развёртки. Как именно — решает настройка слоя.
            patch, at = place_image(patch, box, layer.fit, layer.image_angle,
                                    layer.image_scale, layer.image_offset)
            canvas = Image.new('RGBA', size, (0, 0, 0, 0))
            canvas.paste(patch, at)
            # Прозрачность картинки уважаем: иначе PNG с альфой затирал бы
            # часть чёрным вместо того, чтобы показать текстуру под собой.
            # Не портим общую маску: она одна на все кадры.
            mask = ImageChops.multiply(mask, canvas.getchannel('A'))
        elif layer.color:
            rgb = _rgb(layer.color)
            if not rgb:
                continue
            canvas = _tinted(
                base,
                _paint_layer(size, box, rgb, _rgb(layer.color2 or ''),
                             layer.angle),
                layer.strength)
        else:
            continue

        base = Image.composite(canvas, base, mask)

        # Окантовка — поверх слоя: она обводит саму часть, и картинка её
        # перекрывать не должна. Ширина в долях стороны, чтобы одна и та же
        # работа одинаково выглядела и в 512, и в 2048.
        if layer.edge > 0:
            rim = _rgb(layer.edge_color or layer.color or '')
            width = round(max(size) * layer.edge)
            if rim and width >= 1:
                band = ImageChops.multiply(edge_band(mask, width), mask)
                base = Image.composite(
                    Image.new('RGBA', size, (*rim, 255)), base, band)

        drawn += 1
    return base, drawn


def compose(base_path: str,
            layers: Sequence[Layer],
            out_path: str) -> Optional[str]:
    """
    Вклеивает в базовую текстуру всё, что назначено частям.

    Анимированная картинка на части делает склейку многокадровой (APNG): дальше
    сборка сама увидит анимацию (`TextureService.is_animated_image`) и соберёт
    анимированный VTF с прокси AnimatedTexture. APNG, а не GIF: у GIF 256
    цветов на кадр, и игровая текстура под наклейкой становится грязью.

    Anim в Source — свойство ВСЕГО материала: анимируется вся текстура, просто
    в остальных местах кадры одинаковые. Отсюда и потолок на число кадров.

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

    # Кадров столько, сколько у самой длинной анимации: короткие зациклятся.
    moving = [l.image for l in layers
              if l.image and os.path.isfile(l.image) and _frames_of(l.image) > 1]
    count = min(_MAX_FRAMES, max((_frames_of(p) for p in moving), default=1))
    allowed = _frame_budget(base.size, count)
    if allowed < count:
        logger.info("склейка частей: кадров %s → %s, текстура %sx%s не даёт больше",
                    count, allowed, base.size[0], base.size[1])
        count = allowed

    ready = _masks_for(layers, base.size)
    made = []
    drawn = 0
    for index in range(count):
        frame, hits = _compose_frame(base, layers, ready, index)
        drawn = max(drawn, hits)
        made.append(frame)

    if not drawn:
        return None

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    if len(made) > 1:
        made[0].save(out_path, save_all=True, append_images=made[1:],
                     duration=_durations(moving[0], count), loop=0)
    else:
        made[0].save(out_path)
    logger.info("склейка частей: %s шт., кадров %s → %s",
                drawn, len(made), os.path.basename(out_path))
    return out_path
