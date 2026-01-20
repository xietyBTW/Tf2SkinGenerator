"""
Кастомные исключения для приложения
"""

from typing import Optional


class TF2SkinGeneratorError(Exception):
    """Базовое исключение приложения"""
    pass


class ConfigurationError(TF2SkinGeneratorError):
    """Ошибка конфигурации"""
    pass


class ValidationError(TF2SkinGeneratorError):
    """Ошибка валидации входных данных"""
    pass


class FileNotFoundError(TF2SkinGeneratorError):
    """Файл не найден"""
    def __init__(self, file_path: str, message: Optional[str] = None):
        self.file_path = file_path
        if message is None:
            message = f"Файл не найден: {file_path}"
        super().__init__(message)


class DirectoryNotFoundError(TF2SkinGeneratorError):
    """Директория не найдена"""
    def __init__(self, dir_path: str, message: Optional[str] = None):
        self.dir_path = dir_path
        if message is None:
            message = f"Директория не найдена: {dir_path}"
        super().__init__(message)


class TF2PathError(TF2SkinGeneratorError):
    """Ошибка связанная с путем к TF2"""
    pass


class TF2PathNotSpecifiedError(TF2PathError):
    """Путь к TF2 не указан"""
    pass


class TF2PathNotFoundError(TF2PathError):
    """Путь к TF2 не найден"""
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Путь к TF2 не найден: {path}")


class ModelNotFoundError(TF2SkinGeneratorError):
    """Модель не найдена"""
    def __init__(self, weapon_key: str, searched_paths: Optional[list] = None):
        self.weapon_key = weapon_key
        self.searched_paths = searched_paths or []
        message = f"Модель не найдена для оружия: {weapon_key}"
        if searched_paths:
            paths_str = "\n".join([f"  - {path}" for path in searched_paths])
            message += f"\nПроверенные пути:\n{paths_str}"
        super().__init__(message)


class ModelExtractionError(TF2SkinGeneratorError):
    """Ошибка извлечения модели"""
    pass


class ModelDecompilationError(TF2SkinGeneratorError):
    """Ошибка декомпиляции модели"""
    def __init__(self, mdl_path: str, error_details: Optional[str] = None):
        self.mdl_path = mdl_path
        message = f"Ошибка декомпиляции модели: {mdl_path}"
        if error_details:
            message += f"\nДетали: {error_details}"
        super().__init__(message)


class ModelCompilationError(TF2SkinGeneratorError):
    """Ошибка компиляции модели"""
    def __init__(self, qc_path: str, error_details: Optional[str] = None):
        self.qc_path = qc_path
        message = f"Ошибка компиляции модели: {qc_path}"
        if error_details:
            message += f"\nДетали: {error_details}"
        super().__init__(message)


class TextureProcessingError(TF2SkinGeneratorError):
    """Ошибка обработки текстуры"""
    pass


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


class BuildError(TF2SkinGeneratorError):
    """Общая ошибка сборки"""
    def __init__(self, message: str, details: Optional[str] = None):
        self.details = details
        full_message = message
        if details:
            full_message += f"\nДетали: {details}"
        super().__init__(full_message)


class PathTooLongError(TF2SkinGeneratorError):
    """Путь слишком длинный"""
    def __init__(self, path: str, max_length: Optional[int] = None):
        self.path = path
        self.max_length = max_length
        message = f"Путь слишком длинный: {path}"
        if max_length:
            message += f" (максимум: {max_length} символов)"
        super().__init__(message)


class InvalidFilenameError(ValidationError):
    """Недопустимое имя файла"""
    def __init__(self, filename: str, reason: str):
        self.filename = filename
        self.reason = reason
        super().__init__(f"Недопустимое имя файла '{filename}': {reason}")


class InvalidImageError(ValidationError):
    """Недопустимое изображение"""
    def __init__(self, image_path: str, reason: str):
        self.image_path = image_path
        self.reason = reason
        super().__init__(f"Недопустимое изображение '{image_path}': {reason}")

