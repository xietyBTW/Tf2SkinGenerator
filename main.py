#!/usr/bin/env python3

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.shared.logging_config import setup_logging
from src.shared.constants import DirectoryPaths
from src.shared import paths

# Лог — к данным человека, а не в папку установки: обновление её заменяет, а
# лог нужен как раз чтобы разобрать, что сломалось в прошлой версии.
_log_dir = paths.ensure_data_dir()
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
    Удаляет старые папки build_* из папки временных файлов при старте.

    Эти папки остаются после прерванных или упавших сборок.
    Активная сборка создаёт папку только во время работы, поэтому
    при старте все build_* можно безопасно удалять.
    """
    import shutil
    temp_dir = Path(DirectoryPaths.BASE_TEMP_DIR)
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
        # Мьютекс держим до конца процесса: по нему установщик понимает, что
        # приложение запущено (AppMutex в installer/*.iss), и не пытается
        # заменить занятые файлы. Он же не даёт запустить второй экземпляр —
        # два процесса поверх одних config/ и work/ затирали бы друг друга.
        from src.shared.single_instance import acquire_single_instance
        if not acquire_single_instance():
            logger.info("Приложение уже запущено — выходим")
            return

        # Данные прежних версий лежали рядом с .exe. Переносим один раз, до
        # первого обращения к config/ и work/.
        paths.migrate_legacy_data()

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
