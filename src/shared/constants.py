"""
Константы приложения
"""

from pathlib import Path

# ============================================================================
# Сентинел-значения для extra_texture_callback
# ============================================================================

#: Пользователь выбрал «Использовать обычную» — взять оригинальную текстуру из игры.
#: vpk_service пропускает создание VTF/VMT для этого слота → игра использует свою текстуру.
EXTRA_TEX_USE_GAME_ORIGINAL = "__USE_GAME_ORIGINAL__"

# ============================================================================
# Пути к инструментам
# ============================================================================

class ToolPaths:
    """Пути к внешним инструментам"""
    VTF_TOOL = Path("tools/VTF/VTFCmd.exe")
    VPK_TOOL = Path("tools/VPK/vpk.exe")

    @classmethod
    def get_vtf_tool(cls) -> Path:
        """Возвращает абсолютный путь к VTF инструменту"""
        return cls.VTF_TOOL.resolve() if cls.VTF_TOOL.exists() else cls.VTF_TOOL

    @classmethod
    def get_vpk_tool(cls) -> Path:
        """Возвращает абсолютный путь к VPK инструменту"""
        return cls.VPK_TOOL.resolve() if cls.VPK_TOOL.exists() else cls.VPK_TOOL


# ============================================================================
# Пути и директории
# ============================================================================

class DirectoryPaths:
    """Стандартные пути к директориям"""
    BASE_TEMP_DIR = Path("tools/temp")
    MOD_DATA_DIR = Path("tools/mod_data")
    EXPORT_DIR = Path("export")
    CONFIG_DIR = Path("config")
    EDITED_VMT_DIR = Path("tools/edited_vmt")
    TEMP_VMT_EXTRACT_DIR = Path("tools/temp_vmt_extract")

    @classmethod
    def ensure_exists(cls) -> None:
        """Создает все необходимые директории"""
        for dir_path in [
            cls.BASE_TEMP_DIR,
            cls.MOD_DATA_DIR,
            cls.EXPORT_DIR,
            cls.CONFIG_DIR,
            cls.EDITED_VMT_DIR,
            cls.TEMP_VMT_EXTRACT_DIR
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Валидация
# ============================================================================

class ValidationLimits:
    """Лимиты для валидации"""
    MAX_FILENAME_LENGTH = 50
    MIN_FILENAME_LENGTH = 1

    INVALID_FILENAME_CHARS = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']


# ============================================================================
# Имена файлов
# ============================================================================

class DefaultFilenames:
    """Имена файлов по умолчанию"""
    CONFIG_FILE = "app_config.json"
