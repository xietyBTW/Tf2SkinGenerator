"""
Синий материал, который в игре выглядит в точности как красный

Переключатель RED/BLU честен, только если смена команды что-то меняет на
модели. Разные имена материалов этого не гарантируют, разные файлы текстур
тоже: у 140 из 2317 таких пар стоковых шапок модель берёт из разных VTF
одну и ту же картинку (сверка 2026-10-24 по всем 5015 командным моделям
шапок, без переключателя остаются 56). Здесь одно правило на это, по факту
картинки под треугольниками модели
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

UvTri = Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]

#: Разница канала больше шага 5-битного канала DXT - уже другой цвет. Порог
#: выше пропускал настоящие команды: у тёмного плаща Criminal Cloak RED
#: коричневый, BLU серо-синий, а разница почти везде от 8 до 16
_NOISE = 8
#: Край острова развёртки, который делят блоки DXT 4x4 с соседним островом:
#: здесь RED и BLU расходятся, даже когда сам остров у них один
_EDGE = 3
#: Пятно крупнее блока DXT - уже деталь, а не шум сжатия. Самые мелкие
#: настоящие детали в сверке - 23 пикселя (Toowoomba Tunic) и 60 (Wingman)
_PATCH = 16
#: Столько отличий шумом не бывает, и искать в них пятна незачем
_PLAIN_DIFF = 2048
#: Средняя разница по всей развёртке вместе с краем. Тонкий остров край
#: съедает почти целиком (Aloha Apparel, Colored Lights): по середине он
#: двойник, а в целом отличается в среднем на 10-75. У настоящих двойников
#: сверки - не больше 2
_MEAN_DIFF = 2.0


def is_twin(red, blu, tris: Optional[Sequence[UvTri]]) -> bool:
    """
    BLU-материал неотличим от RED на этой модели

    red/blu - ResolvedMaterial обеих команд. Весь VMT, кроме $basetexture,
    обязан совпасть: краска команды и любые другие параметры живут там. Если
    совпала и текстура - это один материал под двумя именами (46 стоковых
    шапок вроде professor_photon). Иначе решают пиксели под треугольниками
    модели. Без развёртки сравнивать нечего - считаем разными, лишний
    переключатель безобиднее пропавшего
    """
    if red is None or blu is None or not red.png_path or not blu.png_path:
        return False
    if red.params != blu.params:
        return False
    if red.basetexture == blu.basetexture:
        return True
    return bool(tris) and same_on_mesh(red.png_path, blu.png_path, tris)


def same_on_mesh(red_png: str, blu_png: str, tris: Iterable[UvTri]) -> bool:
    """Картинки совпадают везде, куда смотрит модель

    Отдельные отличающиеся пиксели - шум DXT на стыках блоков (RED и BLU
    сжаты порознь), а деталь команды - всегда сплошное пятно. Только первый
    кадр: анимированная текстура сравнивается по нему
    """
    found = differing_pixels(red_png, blu_png, tris)
    if found is None:
        return False
    stray, mean = found
    if mean > _MEAN_DIFF or len(stray) > _PLAIN_DIFF:
        return False
    return largest_patch(stray) <= _PATCH


def largest_patch(pixels: Iterable[Tuple[int, int]]) -> int:
    """Размер самого крупного сплошного пятна (соседство по 8 направлениям)"""
    left = set(pixels)
    best = 0
    while left:
        stack, size = [left.pop()], 0
        while stack:
            y, x = stack.pop()
            size += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    near = (y + dy, x + dx)
                    if near in left:
                        left.remove(near)
                        stack.append(near)
        best = max(best, size)
    return best


def differing_pixels(red_png: str, blu_png: str, tris: Iterable[UvTri]
                     ) -> Optional[Tuple[List[Tuple[int, int]], float]]:
    """([(строка, столбец)] отличающихся пикселей внутри развёртки без края,
    средняя разница по всей развёртке)

    None - картинки не прочитать, они разного размера или развёртка пустая
    """
    try:
        red = Image.open(red_png).convert('RGBA')
        blu = Image.open(blu_png).convert('RGBA')
    except OSError as exc:
        logger.debug(f"differing_pixels: {exc}")
        return None
    if blu.size != red.size:
        return None
    width, height = red.size
    mask = Image.new('L', red.size, 0)
    draw = ImageDraw.Draw(mask)
    for tri in tris:
        # Развёртка заходит за [0,1], и текстура тогда повторяется: у Front
        # Runner v от -0.66 до -0.01. Треугольник сдвигаем внутрь целым
        # числом повторов и рисуем с соседями - так ляжет и тот, что
        # пересекает шов
        du = math.floor(sum(u for u, _ in tri) / 3)
        dv = math.floor(sum(v for _, v in tri) / 3)
        for ou in (-1, 0, 1):
            for ov in (-1, 0, 1):
                # v развёртки SMD растёт снизу, строки картинки - сверху
                draw.polygon([((u - du + ou) * width, (1.0 - (v - dv + ov)) * height)
                              for u, v in tri], fill=255)
    whole = np.asarray(mask) > 0
    if not whole.any():
        return None
    inner = np.asarray(mask.filter(ImageFilter.MinFilter(2 * _EDGE + 1))) > 0
    if not inner.any():
        inner = whole                       # остров тоньше края - берём целиком
    diff = np.abs(np.asarray(red, dtype=np.int16)
                  - np.asarray(blu, dtype=np.int16)).max(axis=2)
    ys, xs = np.nonzero((diff > _NOISE) & inner)
    return list(zip(ys.tolist(), xs.tolist())), float(diff[whole].mean())


def uv_triangles(smd_paths: Iterable[str]) -> Dict[str, List[UvTri]]:
    """{материал в нижнем регистре: UV его треугольников} по всем SMD модели"""
    from src.services.uv_layout_service import UVLayoutService

    out: Dict[str, List[UvTri]] = {}
    for path in smd_paths:
        try:
            by_material = UVLayoutService.parse_smd_uv_by_material(path)
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(f"uv_triangles({path}): {exc}")
            continue
        for name, verts in by_material.items():
            tris = out.setdefault(name.strip().lower(), [])
            for i in range(0, len(verts) - 2, 3):
                tris.append(tuple((verts[i + k][0], verts[i + k][1]) for k in range(3)))
    return out
