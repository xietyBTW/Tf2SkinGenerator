"""
Габариты модели для вписывания в кадр.

Считается в Python намеренно: bounding box у Three.js сразу после загрузки
ненадёжен, а от центра и масштаба зависит, попадёт модель в кадр или уедет
за него. Правило не зависит ни от Qt, ни от того, чем сцену рисуют, поэтому
живёт в домене — им пользуются и виджет превью, и веб-фронт.
"""

from __future__ import annotations

from typing import Tuple

#: Во столько единиц вписываем наибольшую сторону модели.
TARGET_EXTENT = 2.0


def compute_obj_bounds(obj_content: str) -> Tuple[float, float, float, float]:
    """
    Разбирает вершины OBJ и возвращает ``(cx, cy, cz, scale)``:

      * ``cx, cy, cz`` — центр ограничивающего параллелепипеда;
      * ``scale`` — во сколько раз сжать, чтобы наибольшая сторона стала
        TARGET_EXTENT.

    У модели без вершин (пустой или битый файл) центр нулевой, масштаб 1:
    показать её всё равно нечем, и падать здесь незачем.
    """
    xs, ys, zs = [], [], []
    for line in obj_content.splitlines():
        if not line.startswith("v "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            xs.append(float(parts[1]))
            ys.append(float(parts[2]))
            zs.append(float(parts[3]))
        except ValueError:
            continue

    if not xs:
        return 0.0, 0.0, 0.0, 1.0

    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    cz = (min(zs) + max(zs)) / 2

    extent = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    scale = (TARGET_EXTENT / extent) if extent > 0 else 1.0
    return cx, cy, cz, scale
