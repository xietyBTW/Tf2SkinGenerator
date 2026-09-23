"""Сравнение строк для поиска: без знаков, регистра и различия «ё/е»."""

import re

_YO = str.maketrans('ё', 'е')


def plain(text: str) -> str:
    """Только буквы и цифры, в нижнем регистре, «ё» как «е»."""
    return (re.sub(r'[^0-9a-zA-Zа-яёА-ЯЁ]+', '', text or '')
            .lower().translate(_YO))
