"""Обновление приложения из самого приложения"""

from __future__ import annotations

import threading
from typing import Dict

from src.app.api._common import endpoint, logger


# Обновление приложения

#: Ответ последней проверки. Спрашивать GitHub на каждое открытие настроек
#: незачем: релизы выходят не чаще, чем человек перезапускает приложение
_update_cache: Dict[str, object] = {}


@endpoint
def update_status(force: bool = False) -> Dict[str, object]:
    """
    Есть ли новая версия и можно ли поставить её отсюда

    Ходит в сеть (одна ссылка на GitHub API), поэтому страница зовёт это уже
    после отрисовки, а не на старте. Ответ запоминается на сеанс; `force`
    заставляет спросить заново - это кнопка «проверить» в настройках
    """
    from src.services.update_checker import check_for_update

    if force or not _update_cache:
        _update_cache.clear()
        _update_cache.update(check_for_update())
    return dict(_update_cache)


#: Ход обновления. Читается страницей опросом (`update_progress`), пишется
#: фоновым потоком. Ключи: state (idle|downloading|launching|done|error),
#: done, total, error, version
_update_run: Dict[str, object] = {'state': 'idle'}
_update_lock = threading.Lock()

#: Состояния, в которых второй запуск обновления не нужен
_UPDATE_BUSY = ('downloading', 'launching', 'done')


@endpoint
def install_update() -> Dict[str, object]:
    """
    Запускает обновление и СРАЗУ возвращается

    Установщик носит приложение внутри себя (installer/*-bundle.iss), это
    десятки мегабайт - качать их молча, пока страница ждёт ответа, нельзя.
    Поэтому работа уходит в фоновый поток, а страница спрашивает ход дела
    через `update_progress`

    После запуска установщика приложение обязано закрыться: Windows не даст
    заменить его .exe и .dll, пока процесс жив
    """
    with _update_lock:
        if _update_run.get('state') in _UPDATE_BUSY:
            return {'started': True}          # уже идёт, второй раз не надо

        info = update_status()
        if not info.get("can_install"):
            return {'error': 'нечего устанавливать'}

        _update_run.clear()
        _update_run.update({
            'state': 'downloading', 'done': 0,
            'total': int(info.get('asset_size') or 0),
            'version': info.get('version'),
        })

    threading.Thread(target=_run_update, args=(info,), daemon=True).start()
    return {'started': True, 'version': info.get('version')}


@endpoint
def update_progress() -> Dict[str, object]:
    """Ход обновления для страницы. Опрос дешёвый - это чтение словаря"""
    with _update_lock:
        return dict(_update_run)


def _run_update(info: Dict[str, object]) -> None:
    """Скачивает, проверяет и запускает установщик. Работает в своём потоке"""
    from src.services.update_checker import download_update, install_update as launch

    def tick(done: int, total: int) -> None:
        with _update_lock:
            _update_run['done'] = done
            # Content-Length надёжнее того, что записано в релизе
            if total:
                _update_run['total'] = total

    try:
        setup = download_update(
            str(info.get('asset_url') or ''),
            expected_digest=str(info.get('asset_digest') or ''),
            expected_size=int(info.get('asset_size') or 0),
            progress=tick,
        )
        with _update_lock:
            _update_run['state'] = 'launching'
        launch(str(setup))
    except Exception as exc:                                  # noqa: BLE001
        logger.error(f"Обновление не установлено: {exc}", exc_info=True)
        with _update_lock:
            _update_run['state'] = 'error'
            _update_run['error'] = str(exc)
        return

    with _update_lock:
        _update_run['state'] = 'done'
    _quit_soon()


def _quit_soon(delay: float = 2.0) -> None:
    """
    Закрывает приложение через пару секунд

    Пауза - чтобы страница успела опросить `update_progress`, увидеть 'done' и
    показать «закрываюсь». Опрос идёт раз в полсекунды, поэтому две.
    Выходим через os._exit: обычный выход ждёт потоки воркеров, а установщик
    ждать не будет, и любой задержавшийся поток означал бы занятый .exe
    """
    import logging
    import os
    import threading

    def bye() -> None:
        logging.shutdown()
        os._exit(0)

    threading.Timer(delay, bye).start()
