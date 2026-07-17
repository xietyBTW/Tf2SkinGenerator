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
