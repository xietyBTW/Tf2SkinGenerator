"""
Именованный мьютекс: один экземпляр приложения и признак «я запущено».

Две задачи, одна и та же строчка Windows API.

1. Установщик. В installer/*.iss стоит ``AppMutex=Tf2SkinGenerator``. По
   документации Inno это работает только если САМО приложение создаёт мьютекс
   с таким именем; раньше его никто не создавал, и установка (в том числе
   тихая — та, на которой держится автообновление) молча пыталась заменить
   занятые файлы.

2. Второй экземпляр. Config, work и кэш общие и лежат на диске без блокировок:
   два процесса затирали бы правки друг друга.

Имя мьютекса ДОЛЖНО совпадать с AppMutex в installer/*.iss — сравнение в
Windows регистрозависимое. Мьютекс не освобождаем вручную: система закрывает
хэндл при завершении процесса, а хранение ссылки в модуле держит его живым всё
время работы.

Не Windows или недоступный API — считаем, что мы единственные: на других
системах приложение и так не собирается, а падать из-за проверки незачем.
"""

from __future__ import annotations

import sys
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: То же имя, что AppMutex в installer/*.iss.
MUTEX_NAME = "Tf2SkinGenerator"

_ERROR_ALREADY_EXISTS = 183

#: Держим хэндл до конца процесса — иначе сборщик мусора снимет мьютекс.
_handle: Optional[int] = None


def acquire_single_instance(name: str = MUTEX_NAME) -> bool:
    """
    True — мы единственный экземпляр (мьютекс наш). False — уже запущено.
    """
    global _handle
    if _handle is not None:
        return True
    if sys.platform != "win32":
        return True

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPCVOID, wintypes.BOOL,
                                          wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        handle = kernel32.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
    except Exception as exc:                              # noqa: BLE001
        logger.warning(f"Проверка единственного экземпляра недоступна: {exc}")
        return True

    if not handle:
        logger.warning(f"Мьютекс {name} не создан (код {error})")
        return True

    if error == _ERROR_ALREADY_EXISTS:
        # Хэндл всё равно свой и его надо закрыть, но выходим мы всё равно.
        return False

    _handle = handle
    return True
