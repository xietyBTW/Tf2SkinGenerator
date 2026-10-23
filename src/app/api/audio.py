"""Страница звуков"""

from __future__ import annotations

from typing import Dict, Optional

from src.app.api._common import _lang, endpoint


@endpoint
def sounds(section: str = '', who: str = '', group: str = '',
           variant: str = '', fmt: str = '', own: bool = False,
           query: str = '', offset: int = 0,
           lang: str = '') -> Dict[str, object]:
    """Записи звукового скрипта под фильтрами страницы и сами фильтры"""
    from src.app.session import session

    return session().sounds.sounds(section, who, group, variant, fmt, own, query,
                                   offset, lang=_lang(lang))


@endpoint
def set_sound(name: str = '', path: Optional[str] = None,
              wave: str = '') -> Dict[str, object]:
    """Кладёт свой файл на запись звука или на один её файл (`wave`)"""
    from src.app.session import session

    return session().sounds.set_sound(name, path, wave)


@endpoint
def clear_sounds() -> Dict[str, object]:
    """Снимает все свои звуки разом"""
    from src.app.session import session

    return session().sounds.clear_sounds()


@endpoint
def save_sound(name: str = '', wave: str = '') -> Dict[str, object]:
    """Кладёт игровой звук записи (или один её файл) в папку экспорта"""
    from src.app.session import session

    return session().sounds.save_sound(name, wave)


@endpoint
def build_sounds(filename: str = '') -> Dict[str, object]:
    """Собирает VPK со всеми выбранными звуками"""
    from src.app.session import session

    return session().sounds.build_sounds(filename)


def sound_wave(path: str) -> Optional[bytes]:
    """Игровой звук как есть - отдаётся отдельной ручкой, не через /api/"""
    from src.app.session import session

    return session().sounds.sound_bytes(path)
