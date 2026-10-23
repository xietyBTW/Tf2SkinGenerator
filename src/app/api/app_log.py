"""Журнал приложения и папки, которые открывает страница"""

from __future__ import annotations

from typing import Dict

from src.app.api._common import endpoint, logger


# Журнал приложения


@endpoint
def log_tail(since: int = 0, limit: int = 500) -> Dict[str, object]:
    """
    Записи журнала Python новее `since`

    Страница спрашивает это раз в секунду и ТОЛЬКО пока консоль открыта -
    закрыта она почти всегда, так что в обычной работе стоит ноль. Через поток
    событий воркеров лог пускать нельзя: очередь держит 500 штук и при
    переполнении выбрасывает старые, а лог одной сборки - это сотни строк, он
    вытеснил бы `progress` и `model_ready`, и превью бы залипло

    `dropped` в ответе - сколько записей вытеснено из кольца, пока их не
    забирали. Молча отдать дырку нельзя: человек решит, что в этот момент
    ничего не происходило
    """
    from src.shared import log_bridge

    return log_bridge.tail(int(since or 0), int(limit or 500))


@endpoint
def clear_log() -> Dict[str, object]:
    """Забывает накопленные записи. Файл журнала при этом не трогается"""
    from src.shared import log_bridge

    log_bridge.clear()
    return {'cleared': True}


@endpoint
def log_folder() -> Dict[str, object]:
    """
    Открывает папку с файлом журнала в проводнике

    Именно папку, а не сам .log: чем его откроет система - вопрос открытый, а
    вот показать файл в проводнике предсказуемо. Полная история лежит там, в
    кольце - только последние записи
    """
    from src.shared.paths import ensure_data_dir

    return _open_folder(ensure_data_dir())


@endpoint
def export_folder() -> Dict[str, object]:
    """
    Открывает папку экспорта: там собранные моды и извлечённое

    Без этой кнопки человек искал мод наугад - путь из настроек («export»)
    ничего не говорит о том, где эта папка на диске
    """
    from src.shared.paths import export_dir

    folder = export_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return _open_folder(folder)


def _open_folder(folder) -> Dict[str, object]:
    """Показывает папку в проводнике"""
    import os
    import sys

    if sys.platform != 'win32':
        return {'error': 'только Windows', 'path': str(folder)}
    try:
        os.startfile(str(folder))                     # noqa: S606
    except OSError as exc:
        logger.warning(f"не открыть папку {folder}: {exc}")
        return {'error': str(exc), 'path': str(folder)}
    return {'opened': True, 'path': str(folder)}
