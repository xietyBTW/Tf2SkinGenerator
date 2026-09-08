"""
Где лежит код и где лежат данные человека.

Раньше и то, и другое считалось от текущей папки процесса: ``Path("work")``,
``Path("config")``, ``Path("tools/temp")``. Пока приложение запускали из его
собственной папки, это совпадало с истиной. Но `chdir` в проекте не осталось
(он был в Qt-обвязке), а ярлык — не единственный способ запуска: из «Выполнить»,
из консоли, по ассоциации файла cwd будет чужой, и приложение молча заведёт
пустые ``config/`` и ``work/`` где попало.

Вторая, более важная причина — обновления. Любой апдейтер (хоть тихая
переустановка через Inno, хоть Velopack) ЗАМЕНЯЕТ папку установки. Пока работы
человека лежат внутри неё, обновление либо стирает их, либо наслаивается на
старые файлы.

Отсюда два корня:

    install_dir()   код и бандл: .exe, frontend, tools/crowbar, tools/VTF.
                    Только чтение. Обновление заменяет его целиком.

    data_dir()      всё, что написал человек или насчитало приложение: config,
                    work, mods, export, cache, лог, временные папки сборки.
                    Обновление его не трогает.

В разработке (не frozen) оба корня — точка, то есть текущая папка, ровно как
было: ``data_dir() / 'cache'`` даёт тот же ``Path('cache')``. Так запуск из
репозитория, тесты и содержимое репозитория не меняются вообще; корни
расходятся только в собранном приложении.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Имя папки в %LOCALAPPDATA%. Совпадает с AppName в installer/*.iss — по нему
#: же человек найдёт свои работы руками, если понадобится.
APP_DIR_NAME = "Tf2SkinGenerator"

#: Что переносим из папки установки при первом запуске новой версии. Только
#: данные человека и кэш; tools/ и код остаются на месте.
_LEGACY_DIRS = ("config", "work", "mods", "export", "cache")


def is_frozen() -> bool:
    """True — приложение собрано PyInstaller'ом."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """
    Папка с кодом и бандлом. Только чтение.

    В собранном приложении это папка рядом с .exe (не ``_internal``: туда
    PyInstaller кладёт свои файлы, а tools/ и frontend/ лежат в корне вывода —
    см. build.ps1). В разработке — текущая папка, как раньше.
    """
    return Path(sys.executable).parent if is_frozen() else Path(".")


def data_dir() -> Path:
    """
    Папка данных человека. Пишем только сюда.

    В собранном приложении — ``%LOCALAPPDATA%\\Tf2SkinGenerator``. Если
    LOCALAPPDATA почему-то не задан (запуск из-под службы, урезанное
    окружение), падать нельзя: возвращаемся к папке рядом с .exe, то есть к
    прежнему поведению.
    """
    if not is_frozen():
        return Path(".")
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return install_dir()
    return Path(base) / APP_DIR_NAME


def ensure_data_dir() -> Path:
    """Папка данных, созданная на диске."""
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_data() -> None:
    """
    Переносит данные из папки установки в папку данных — один раз.

    Нужно ровно для тех, кто ставил прежние версии: их config/, work/ и mods/
    лежат рядом с .exe и первое же обновление их потеряет. Переносим только то,
    чего ещё нет в новом месте: повторный запуск ничего не перетирает, а сбой
    на одной папке не мешает остальным.
    """
    if not is_frozen():
        return
    source_root = install_dir()
    target_root = data_dir()
    if source_root.resolve() == target_root.resolve():
        return

    for name in _LEGACY_DIRS:
        source, target = source_root / name, target_root / name
        if not source.is_dir() or target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            logger.info(f"Данные перенесены: {name} -> {target}")
        except OSError as exc:                       # занято, нет прав — не фатально
            logger.warning(f"Не удалось перенести {name}: {exc}")
