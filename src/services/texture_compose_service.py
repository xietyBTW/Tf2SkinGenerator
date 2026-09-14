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

import io
import math
import os
import struct
import zlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw

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
    #: Множитель ПО ВЫСОТЕ. None — такой же, как по ширине: наклейку чаще
    #: растят целиком, а разные множители нужны, когда деталь длинная и
    #: картинку под неё вытягивают.
    image_scale_y: Optional[float] = None
    #: Сдвиг центра в долях места части: (0.5, 0) — на пол-ширины вправо.
    image_offset: Tuple[float, float] = (0.0, 0.0)
    #: Куда вписывать картинку, если не в габарит самой части: габарит развёртки
    #: (u0, v0, u1, v1) той части, на которую её клали. Нужен после РЕЗКИ:
    #: разрезанная деталь становится двумя частями, у каждой свой габарит, и
    #: без якоря наклейка перерисовывалась заново в каждой половине — на модели
    #: это выглядело как две уменьшенные копии вместо одной картинки.
    anchor: Optional[Tuple[float, float, float, float]] = None
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
    #: Где переход начинается и заканчивается вдоль своей оси, в долях места
    #: части: 0 и 1 — от края до края. Сдвигая их, человек говорит, сколько
    #: детали занимает чистый цвет, а сколько — сам перелив.
    start: float = 0.0
    end: float = 1.0
    #: Где цвета смешаны поровну: 0.5 — ровно посередине перехода, меньше —
    #: ближе к первому цвету (он перетягивает). Это и есть «сила» перелива:
    #: краями задаётся его ширина, серединой — перевес.
    mid: float = 0.5
    #: Сила тонировки: 1.0 — полностью в цвет, 0.3 — лёгкий оттенок.
    strength: float = 1.0
    #: Красить ИМЕННО выбранным цветом, а не смешивать его с оригиналом
    #: (см. `_tinted`). Свойство работы, а не отдельной части: вид у покраски
    #: должен быть один на весь предмет.
    exact: bool = False
    #: Окантовка: ширина полосы по краю части в долях стороны текстуры.
    #: 0 — без окантовки. В долях, а не в пикселях: одна и та же работа
    #: собирается и в 512, и в 2048, и полоса должна выглядеть одинаково.
    edge: float = 0.0
    #: Цвет окантовки «#rrggbb». Пусто — берётся цвет самой части.
    edge_color: Optional[str] = None


def place_image(patch: Image.Image, box: Tuple[int, int, int, int],
                fit: str = 'contain', angle: float = 0.0, scale: float = 1.0,
                offset: Tuple[float, float] = (0.0, 0.0),
                scale_y: Optional[float] = None):
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

    # Ширина и высота тянутся по отдельности: за угол рамки — вместе, за
    # сторону — только своя ось. Без второго множителя картинку было не
    # вытянуть под длинную деталь.
    kx = max(0.01, float(scale))
    ky = max(0.01, float(scale if scale_y is None else scale_y))
    target = (max(1, round(target[0] * kx)), max(1, round(target[1] * ky)))
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


def _spot_size(shape: Optional[Tuple[int, int]]) -> Tuple[int, int]:
    """Размер подсветки в ПРОПОРЦИЯХ текстуры: длинная сторона — _SPOT_SIZE."""
    try:
        width, height = int(shape[0]), int(shape[1])
    except (TypeError, ValueError, IndexError):
        return (_SPOT_SIZE, _SPOT_SIZE)
    if width < 1 or height < 1:
        return (_SPOT_SIZE, _SPOT_SIZE)
    longest = max(width, height)
    return (max(1, round(_SPOT_SIZE * width / longest)),
            max(1, round(_SPOT_SIZE * height / longest)))


def outline_png(polygons: Sequence[UvTri], out_path: str,
                rgb: Tuple[int, int, int] = (204, 85, 34),
                shape: Optional[Tuple[int, int]] = None) -> str:
    """
    Форма части на развёртке — картинкой: заливка плюс обводка по краю.

    Картинкой, а не списком координат: у крупного куска их полторы тысячи, и
    возить их на страницу ради КАЖДОГО наведения дороже, чем отдать PNG в
    несколько килобайт, который браузер к тому же закэширует.

    Обводку берём как разницу расширенной маски и исходной — рисовать рёбра
    треугольников нельзя, получилась бы сетка, а не контур детали.

    `shape` — размер САМОЙ текстуры. Квадратными они бывают не всегда: у тела
    шпиона 1024×512, и подсветка, нарисованная в квадрат, ложилась на кадр
    растянутой по вертикали — разметка съезжала с деталей.
    """
    size = _spot_size(shape)
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
                 angle: float = 0.0, start: float = 0.0, end: float = 1.0,
                 mid: float = 0.5) -> Image.Image:
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
    k = np.clip(projection / span + 0.5, 0.0, 1.0)

    # Края перехода: за ними лежит чистый цвет. Сдвинутые к середине, они
    # делают перелив резче, сдвинутые к одному краю — отдают деталь одному
    # цвету. Схлопнуться в точку не даём: это деление на ноль, а на экране —
    # граница вместо перехода.
    low, high = sorted((float(start), float(end)))
    high = max(high, low + 1e-3)
    k = np.clip((k - low) / (high - low), 0.0, 1.0)

    # Середина: где цвета смешаны поровну. Степень, а не сдвиг, — так переход
    # остаётся гладким на всей длине; ровно так же считает Photoshop.
    middle = min(0.95, max(0.05, float(mid)))
    if abs(middle - 0.5) > 1e-3:
        k = k ** (math.log(0.5) / math.log(middle))
    k = k[..., None]

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
            strength: float, mask: Optional[Image.Image] = None,
            exact: bool = False) -> Image.Image:
    """
    Тонировка: цвет ложится как краска, детали остаются.

    Взято overlay, а не умножение: умножение гасит тёмную текстуру в чёрное
    («красный ствол» выходит угольным), а раскраска по яркости — мутной.
    Overlay держит и тени, и блики, поэтому дерево остаётся деревом, просто
    красным. Проверено на стоковой текстуре обреза.

    `exact` — второй способ, для тех случаев, когда нужен ИМЕННО выбранный
    цвет. Overlay считает от яркости оригинала: на тёмном металле #cc5522
    выходит бурым, и человек видит в палитре одно, а на модели другое. Здесь
    цвет берётся как есть, а фактура возвращается ОТНОСИТЕЛЬНОЙ яркостью:
    пиксель темнее среднего по детали — цвет темнее во столько же раз, светлее
    — светлее. Среднее совпадает с выбранным цветом, тени и блики на месте.
    """
    if exact:
        lit = _repainted(base, paint, mask)
    else:
        lit = ImageChops.overlay(base.convert('RGB'), paint).convert('RGBA')
    lit.putalpha(base.getchannel('A'))
    amount = min(1.0, max(0.0, float(strength)))
    return Image.blend(base, lit, amount) if amount < 1.0 else lit


def _repainted(base: Image.Image, paint: Image.Image,
               mask: Optional[Image.Image]) -> Image.Image:
    """
    Цвет как в палитре, фактура — относительной яркостью оригинала.

    Среднее берём ПО МАСКЕ ЧАСТИ, а не по всей текстуре: детали лежат на
    развёртке вперемешку, и среднее по картинке целиком сделало бы светлую
    деталь тёмной за компанию с соседями.
    """
    gray = np.asarray(base.convert('L'), dtype=np.float32)
    if mask is not None:
        weights = np.asarray(mask, dtype=np.float32)
        total = float(weights.sum())
        mean = float((gray * weights).sum() / total) if total > 0 else 0.0
    else:
        mean = float(gray.mean())
    # Совсем чёрная деталь среднего не даёт: относительная яркость там
    # бессмысленна, и красим ровно выбранным цветом.
    if mean < 1.0:
        return paint.convert('RGBA')

    rel = (gray / mean)[..., None]
    rgb = np.asarray(paint.convert('RGB'), dtype=np.float32) * rel
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8),
                           'RGB').convert('RGBA')


#: Больше кадров в VTF не влезает по-хорошему: анимация в Source живёт на весь
#: материал, и каждый кадр — ещё одна полноразмерная картинка в моде. Гифка на
#: 200 кадров раздула бы текстуру предмета в двести раз.
_MAX_FRAMES = 64


def _frames_of(path: str) -> int:
    """Сколько кадров в картинке; 1 — обычная."""
    try:
        with Image.open(path) as img:
            return max(1, int(getattr(img, 'n_frames', 1)))
    except (OSError, ValueError):
        return 1


def _read_frames(path: str):
    """
    Кадры анимации по порядку и по кругу: (картинка RGBA, задержка в мс).

    Файл открывается ОДИН раз. Раньше каждый кадр открывал гифку заново и
    мотал с начала, а GIF мотается только через все предыдущие кадры — на
    шестидесяти кадрах это в тридцать раз дороже, чем прочитать их подряд.
    Обычная картинка отдаётся бесконечно одна и та же.
    """
    try:
        with Image.open(path) as img:
            count = max(1, int(getattr(img, 'n_frames', 1)))
            if count == 1:
                still = img.convert('RGBA')
                while True:
                    yield still, 100
            while True:
                for index in range(count):
                    img.seek(index)
                    # Без метки — 100 мс, как принято у GIF.
                    yield img.convert('RGBA'), int(img.info.get('duration') or 100)
    except (OSError, ValueError, EOFError) as exc:
        logger.warning(f"склейка частей: {path} не читается: {exc}")
        while True:
            yield None, 100


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
    delays: List[int] = []
    reader = _read_frames(path)
    try:
        for index in range(count):
            frame, delay = next(reader)
            if frame is None:
                break
            out = os.path.join(out_dir, f"{prefix}_{index:03d}.png")
            frame.save(out)
            made.append(out)
            delays.append(delay)
    finally:
        reader.close()
    return made, delays


class _ApngWriter:
    """
    Пишет APNG кадр за кадром, не держа их в памяти.

    Pillow умеет записать APNG только целиком: копирует ВСЕ кадры в список,
    чтобы считать разницу между соседними. Кадр текстуры 2048×2048 — это
    16 МБ, и шестьдесят кадров сборки положили бы приложение на ровном месте
    (раньше от этого спасал потолок в 20 кадров — и гифка обрезалась).

    Кадр кодируется тем же Pillow как одиночный PNG (фильтры и deflate — его
    родной код на C), а отсюда берутся только сжатые данные: первый кадр идёт
    в IDAT, остальные — в fdAT. Все кадры целые, одного размера, без разницы с
    соседом: читателю (Pillow в сборке) так даже проще.
    """

    _SIG = b'\x89PNG\r\n\x1a\n'

    def __init__(self, fp, size: Tuple[int, int], count: int, loop: int = 0):
        self._fp = fp
        self._size = size
        self._seq = 0
        self._written = 0
        fp.write(self._SIG)
        self._chunk(b'IHDR', struct.pack('>IIBBBBB', size[0], size[1],
                                         8, 6, 0, 0, 0))      # RGBA, 8 бит
        self._chunk(b'acTL', struct.pack('>II', count, loop))

    def _chunk(self, kind: bytes, data: bytes) -> None:
        self._fp.write(struct.pack('>I', len(data)) + kind + data
                       + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))

    def _next_seq(self) -> bytes:
        seq = self._seq
        self._seq += 1
        return struct.pack('>I', seq)

    @staticmethod
    def _idat(frame: Image.Image) -> bytes:
        """Сжатые данные кадра — всё, что Pillow положил бы в IDAT."""
        buf = io.BytesIO()
        # Уровень 1: файл временный и его тут же читает сборка, а на 2048×2048
        # умолчание Pillow вдвое медленнее ради нескольких мегабайт.
        frame.save(buf, 'PNG', compress_level=1)
        raw = buf.getvalue()
        out = []
        pos = len(_ApngWriter._SIG)
        while pos + 8 <= len(raw):
            length, kind = struct.unpack('>I4s', raw[pos:pos + 8])
            if kind == b'IDAT':
                out.append(raw[pos + 8:pos + 8 + length])
            pos += 12 + length
        return b''.join(out)

    def add(self, frame: Image.Image, delay_ms: int) -> None:
        if frame.size != self._size:
            raise ValueError('кадр APNG не того размера')
        self._chunk(b'fcTL', self._next_seq() + struct.pack(
            '>IIIIHHBB', self._size[0], self._size[1], 0, 0,
            max(1, int(delay_ms)), 1000, 0, 0))
        data = self._idat(frame.convert('RGBA'))
        if self._written == 0:
            self._chunk(b'IDAT', data)
        else:
            self._chunk(b'fdAT', self._next_seq() + data)
        self._written += 1

    def close(self) -> None:
        self._chunk(b'IEND', b'')


def _masks_for(layers: Sequence[Layer], size: Tuple[int, int]):
    """
    Маска и место каждого слоя — ОДИН раз на всю анимацию.

    Маска чисто геометрическая: от кадра она не зависит, а стоит дорого (0.08 с
    на полутора тысячах треугольников при 2048×2048). Считать её в цикле кадров
    значило подарить пять секунд на каждую перекраску шестидесяти четырёх
    кадров — при том что результат каждый раз один и тот же.
    """
    out = []
    width, height = size
    for layer in layers:
        if not layer.polygons:
            out.append(None)
            continue
        mask = _mask(layer.polygons, size)
        box = mask.getbbox()
        if box and layer.anchor:
            # Якорь задан в координатах развёртки, а v там растёт снизу — как и
            # в самой маске.
            u0, v0, u1, v1 = layer.anchor
            box = (int(u0 * width), int((1.0 - v1) * height),
                   int(u1 * width), int((1.0 - v0) * height))
        out.append((mask, box) if box else None)   # None — часть вне холста
    return out


def _compose_frame(base: Image.Image, layers: Sequence[Layer],
                   ready, patches: Dict[str, Optional[Image.Image]]
                   ) -> Tuple[Image.Image, int]:
    """Один кадр склейки: база плюс все слои. Возвращает (картинка, сколько легло).

    ``patches`` — картинка каждого слоя НА ЭТОТ КАДР, по пути файла: одна
    гифка на двух частях декодируется один раз, а не дважды.
    """
    size = base.size
    drawn = 0
    for layer, prepared in zip(layers, ready):
        if prepared is None:
            continue
        mask, box = prepared

        if layer.image:
            patch = patches.get(layer.image)
            if patch is None:
                continue
            # Картинка ложится на место части: человек кладёт её «на ствол», а
            # не в угол развёртки. Как именно — решает настройка слоя.
            patch, at = place_image(patch, box, layer.fit, layer.image_angle,
                                    layer.image_scale, layer.image_offset,
                                    layer.image_scale_y)
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
                             layer.angle, layer.start, layer.end, layer.mid),
                layer.strength, mask, layer.exact)
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


def _plan(layers: Sequence[Layer], frames: Optional[int]):
    """(пути картинок, сколько кадров, самая длинная анимация)."""
    paths = sorted({l.image for l in layers
                    if l.image and os.path.isfile(l.image)})
    # Кадров столько, сколько у самой длинной анимации: короткие зациклятся.
    count = min(frames or _MAX_FRAMES, _MAX_FRAMES,
                max((_frames_of(p) for p in paths), default=1))
    return paths, count, max(paths, key=_frames_of, default=None)


def is_moving(layers: Sequence[Layer]) -> bool:
    """Есть ли среди слоёв анимация — то есть будет ли склейка многокадровой."""
    return _plan(layers, None)[1] > 1


def iter_frames(base_path: str, layers: Sequence[Layer],
                frames: Optional[int] = None,
                size: Optional[int] = None,
                alive=None):
    """
    Кадры склейки по одному: (картинка, задержка в мс).

    Пусто — рисовать нечего (нет основы или ни один слой не лёг). Кадры не
    копятся: кто читает, тот и решает, куда их деть — в APNG для сборки или в
    файлы для вьювера.

    Args:
        frames: потолок кадров; 1 — только первый.
        size:   ужать основу так, чтобы длинная сторона не превышала это.
                Маски считаются в долях развёртки, и склейка при любом размере
                та же — только мельче.
        alive:  функция; вернула False — читатель передумал, обрываемся.
    """
    if not (base_path and os.path.isfile(base_path)):
        logger.warning(f"склейка частей: нет базовой текстуры {base_path!r}")
        return
    try:
        base = Image.open(base_path).convert('RGBA')
    except OSError as exc:
        logger.warning(f"склейка частей: {base_path} не читается: {exc}")
        return
    if size and max(base.size) > size:
        k = size / max(base.size)
        base = base.resize((max(1, round(base.size[0] * k)),
                            max(1, round(base.size[1] * k))), Image.LANCZOS)

    paths, count, longest = _plan(layers, frames)
    ready = _masks_for(layers, base.size)
    readers = {p: _read_frames(p) for p in paths}
    try:
        for index in range(count):
            if alive is not None and not alive():
                return
            patches = {}
            delay = 100
            for path, reader in readers.items():
                patches[path], took = next(reader)
                if path == longest:
                    delay = took
            frame, hits = _compose_frame(base, layers, ready, patches)
            if not hits:
                return                    # первый кадр пуст — пусты и остальные
            yield frame, delay
    finally:
        for reader in readers.values():
            reader.close()


def compose(base_path: str,
            layers: Sequence[Layer],
            out_path: str,
            frames: Optional[int] = None) -> Optional[str]:
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
        frames:    потолок кадров. 1 — только первый, обычный PNG: столько
                   видит превью (3D крутить APNG не умеет), и ради него не
                   стоит на каждый мазок собирать шестьдесят кадров по 16 МБ.
                   None — все, сколько есть (до `_MAX_FRAMES`): так печёт
                   сборка, кадр за кадром, память от их числа не зависит.

    Returns:
        Путь к склейке или None, если рисовать оказалось нечего.
    """
    count = _plan(layers, frames)[1]
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    writer = None
    drawn = 0
    with open(out_path, 'wb') as fp:
        for frame, delay in iter_frames(base_path, layers, frames):
            drawn += 1
            if count == 1:
                frame.save(fp, 'PNG')
                break
            if writer is None:
                writer = _ApngWriter(fp, frame.size, count)
            writer.add(frame, delay)
        if writer is not None:
            writer.close()

    if not drawn:
        try:
            os.remove(out_path)
        except OSError:
            pass
        return None
    logger.info("склейка частей: кадров %s → %s", drawn,
                os.path.basename(out_path))
    return out_path


def export_composite_frames(base_path: str, layers: Sequence[Layer],
                            out_dir: str, size: Optional[int] = None,
                            alive=None) -> Tuple[List[str], int]:
    """
    Кадры склейки файлами для вьювера: (файлы, кадров в секунду).

    Вьювер APNG не крутит, а список PNG — умеет (`loadAnimatedTexture`).
    Частота одна на всю анимацию — как и в VTF.
    """
    os.makedirs(out_dir, exist_ok=True)
    made: List[str] = []
    delays: List[int] = []
    for frame, delay in iter_frames(base_path, layers, None, size, alive):
        out = os.path.join(out_dir, f"frame_{len(made):03d}.png")
        # Уровень 1: файл живёт до следующего мазка, а читает его один браузер.
        frame.save(out, 'PNG', compress_level=1)
        made.append(out)
        delays.append(delay)
    if alive is not None and not alive():
        return [], 0
    # Задержка короче 20 мс у гифок означает «как получится» — браузеры и
    # сборка (TextureService._fps_from_durations) читают её как 100.
    vals = [d if d >= 20 else 100 for d in delays] or [100]
    return made, max(1, min(60, round(1000 * len(vals) / sum(vals))))
