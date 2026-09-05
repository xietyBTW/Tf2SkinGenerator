#!/usr/bin/env python3

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.shared.logging_config import setup_logging
from src.shared.constants import DirectoryPaths

# В frozen-режиме __file__ указывает внутрь _internal/ — лог пишем рядом с .exe
if getattr(sys, 'frozen', False):
    _log_dir = Path(sys.executable).parent
else:
    _log_dir = Path(os.path.dirname(os.path.abspath(__file__)))
_log_file = _log_dir / "tf2sg.log"

logger = setup_logging(
    log_level="INFO",
    console_output=True,
    log_file=_log_file,
)

# Нативные падения (access violation в распаковке VPK, в драйвере WebView2)
# не оставляют Python-трейсбека — faulthandler допишет стек прямо в лог
try:
    import faulthandler
    _fault_log = open(_log_dir / "tf2sg_crash.log", "a", buffering=1)
    faulthandler.enable(file=_fault_log)
except Exception:  # диагностика не должна мешать запуску
    pass


def _cleanup_stale_temp() -> None:
    """
    Удаляет старые папки build_* из tools/temp при старте приложения.

    Эти папки остаются после прерванных или упавших сборок.
    Активная сборка создаёт папку только во время работы, поэтому
    при старте все build_* можно безопасно удалять.
    """
    import shutil
    temp_dir = Path("tools/temp")
    if not temp_dir.exists():
        return
    removed = 0
    for entry in temp_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("build_"):
            try:
                shutil.rmtree(entry)
                removed += 1
            except Exception as e:
                logger.warning(f"Не удалось удалить старую temp папку {entry.name}: {e}")
    if removed:
        logger.info(f"Очищено {removed} старых temp папок при старте")


def main():
    logger.info("Запуск TF2 Skin Generator")

    try:
        DirectoryPaths.ensure_exists()
        _cleanup_stale_temp()

        # Интерфейс — веб-страница в окне WebView2 (см. frontend/app.py).
        # Qt здесь больше не участвует: воркеры (src/services) живут на своих
        # сигналах, а страница ходит в тот же src/app/api.py.
        from frontend.app import main as run_ui

        logger.info("Приложение успешно запущено")
        run_ui()

    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
