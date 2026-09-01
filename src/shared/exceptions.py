"""
Кастомные исключения для приложения.

Здесь остались только реально используемые типы. RequiredFileMissingError
наследуется и от встроенного FileNotFoundError, чтобы существующие
`except FileNotFoundError` продолжали его ловить.
"""

from typing import Optional


class TF2SkinGeneratorError(Exception):
    """Базовое исключение приложения"""
    pass


class RequiredFileMissingError(TF2SkinGeneratorError, FileNotFoundError):
    """
    Необходимый для работы файл не найден.

    Наследует встроенный FileNotFoundError: обработчики, ловящие встроенный
    тип, поймают и этот.
    """
    def __init__(self, file_path: str, message: Optional[str] = None):
        self.file_path = file_path
        if message is None:
            message = f"Файл не найден: {file_path}"
        super().__init__(message)


class VTFCreationError(TF2SkinGeneratorError):
    """Ошибка создания VTF файла"""
    def __init__(self, command: str, stdout: str = "", stderr: str = ""):
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        message = f"Ошибка создания VTF файла\nКоманда: {command}"
        if stdout:
            message += f"\nSTDOUT: {stdout}"
        if stderr:
            message += f"\nSTDERR: {stderr}"
        super().__init__(message)


class FileLockedError(TF2SkinGeneratorError):
    """Файл занят другим процессом (Windows не даёт его перезаписать).

    Отдельно от прочих ошибок сборки: причина всегда одна и чинится не
    настройками, а закрытием того, кто держит файл (запущенная TF2 с
    примонтированным модом, GCFScape, проводник с превью). Сообщение уже
    готово к показу пользователю — сырой WinError 32 ему ничего не говорит.
    """
    def __init__(self, file_path: str, message: Optional[str] = None):
        self.file_path = file_path
        super().__init__(message or f"Файл занят другим процессом: {file_path}")


class VPKCreationError(TF2SkinGeneratorError):
    """Ошибка создания VPK файла"""
    def __init__(self, stdout: str = "", stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr
        message = "Ошибка создания VPK файла"
        if stdout:
            message += f"\nSTDOUT: {stdout}"
        if stderr:
            message += f"\nSTDERR: {stderr}"
        super().__init__(message)
