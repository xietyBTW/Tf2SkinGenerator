"""
Сколько займёт готовый VTF — до того, как его собрали.

Оценка, а не измерение: считать по-настоящему значит прогнать кодировщик, а
ответ нужен на каждое движение ползунка разрешения. Формула точна для сторон,
кратных четырём (у блочных DXT это и есть условие), и завышает на несколько
процентов у нечётных.

Жила в панели превью, пока панель была одна. Переехала сюда, когда интерфейс
стал вторым: число одинаковое для окна и для страницы, и считать его дважды
разными формулами — верный способ показать два разных числа.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

#: Бит на пиксель для форматов VTF. Чего нет в таблице — считаем 32.
#: Таблица жила константой в панели превью и уехала бы вместе с ней; она про
#: форматы VTF, а не про панель.
VTF_BPP = {
    'DXT1': 4, 'DXT1 With One Bit Alpha': 4,
    'DXT3': 8, 'DXT5': 8, 'I8': 8, 'A8': 8,
    'IA88': 16, 'UV88': 16, 'RGB565': 16, 'BGR565': 16,
    'BGRX5551': 16, 'BGRA5551': 16, 'BGRA4444': 16,
    'RGB888': 24, 'BGR888': 24,
    'RGB888 Bluescreen': 24, 'BGR888 Bluescreen': 24,
    'RGBA16161616F': 64, 'RGBA16161616': 64,
}


def vtf_bytes(width: int, height: int, fmt: str,
              flags: Optional[Iterable[str]] = None,
              bpp_table: Optional[Mapping[str, int]] = None) -> int:
    """Примерный размер VTF в байтах.

    Мип-уровни добавляют примерно треть: 1 + 1/4 + 1/16 + … = 4/3. Флаг
    NOMIP их отключает. Блочные форматы (DXT) считаются по битам на пиксель.
    """
    bits = (bpp_table if bpp_table is not None else VTF_BPP).get(fmt, 32)
    base = width * height * bits // 8
    return base if 'NOMIP' in (flags or ()) else base * 4 // 3


def human_size(num_bytes: int) -> str:
    """Байты человеку: КБ до мегабайта, дальше МБ с одним знаком."""
    kb = num_bytes / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    return f"{kb / 1024:.1f} MB"
