"""Лёгкий парсер заголовка VTF — только то, что нужно диагностике (размеры).

Полноценная декодировка не нужна: читаем сигнатуру и width/height из заголовка.
Формат VTF: сигнатура "VTF\\0" (4 байта), version[2] (2×uint32), headerSize
(uint32), затем width (uint16) и height (uint16). Всё little-endian.
"""

from __future__ import annotations

import struct
from typing import Optional, Tuple


def read_vtf_size(path: str) -> Optional[Tuple[int, int]]:
    """Возвращает (width, height) из заголовка VTF или None, если файл не VTF
    либо повреждён/слишком короткий."""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
    except OSError:
        return None
    return parse_vtf_size(head)


def parse_vtf_size(head: bytes) -> Optional[Tuple[int, int]]:
    """Разбирает первые байты VTF-заголовка. Вынесено отдельно для тестов."""
    if len(head) < 20 or head[:4] != b"VTF\x00":
        return None
    try:
        width, height = struct.unpack_from("<HH", head, 16)
    except struct.error:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0
