"""Инструменты: библиотека модов, извлечение, экспорт, объединение VPK"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, endpoint


@endpoint
def mod_library() -> List[dict]:
    """Что лежит в библиотеке модов (новые сверху)"""
    from src.services import mod_library_service
    return mod_library_service.items()


@endpoint
def mod_icon(name: str = '') -> Dict[str, object]:
    """
    Обложка мода - его основная текстура, при первом запросе строится

    Отдельным вызовом, а не в списке: декодировать VTF всей библиотеки ради
    открытия каталога незачем, а карточки и без обложек показываются сразу
    """
    from src.services import mod_library_service

    path = mod_library_service.icon(name)
    return {'name': name, 'icon': str(path) if path else ''}


@endpoint
def add_mod(path: str = '') -> Dict[str, object]:
    """Кладёт открытый мод в библиотеку и отдаёт его постоянный путь"""
    from src.services import mod_library_service

    saved = mod_library_service.add(path)
    if saved is None:
        return {'error': 'VPK-файл не найден'}
    return {'name': saved.name, 'path': str(saved)}


@endpoint
def remove_mod(name: str = '') -> Dict[str, object]:
    """Удаляет мод из библиотеки. Принимается только ИМЯ файла в ней"""
    from src.services import mod_library_service

    if not mod_library_service.remove(name):
        return {'error': f'«{name}» в библиотеке нет'}
    return {'removed': name}


@endpoint
def load_vpk_mod(path: str = '', lang: str = '') -> Dict[str, object]:
    """Показывает чужой мод из VPK: его модель и его текстуры"""
    from src.app.session import session

    lang = _lang(lang)
    return session().load_vpk_mod(path, lang=lang)


@endpoint
def extract_model(lang: str = '') -> Dict[str, object]:
    """Декомпилирует модель, список файлов приходит событием extract_files"""
    from src.app.session import session

    lang = _lang(lang)
    return session().tools.extract_model(lang=lang)


@endpoint
def export_model_files(files: Optional[List[str]] = None,
                       lang: str = '') -> Dict[str, object]:
    """Сохраняет выбранные файлы модели (пустой список - отказ и уборка)"""
    from src.app.session import session

    lang = _lang(lang)
    return session().tools.export_model_files(files, lang=lang)


@endpoint
def extract_texture(textures: Optional[List[str]] = None,
                    lang: str = '') -> Dict[str, object]:
    """Извлекает оригинальные текстуры предмета в папку экспорта"""
    from src.app.session import session

    lang = _lang(lang)
    return session().tools.extract_texture(textures, lang=lang)


@endpoint
def export_vpks() -> List[str]:
    """Собранные моды в папке экспорта"""
    from src.app.session import session
    return session().tools.export_vpks()


@endpoint
def merge_vpk(files: Optional[List[str]] = None, name: str = '',
              confirmed: bool = False, lang: str = '') -> Dict[str, object]:
    """Сливает выбранные моды в один VPK"""
    from src.app.session import session

    lang = _lang(lang)
    return session().tools.merge_vpk(files, name, confirmed=confirmed, lang=lang)


@endpoint
def export_uv(size: int = 1024) -> Dict[str, object]:
    """Рисует UV-шаблон модели в папку экспорта. Путь придёт событием"""
    from src.app.session import session
    return session().export_uv(size)
