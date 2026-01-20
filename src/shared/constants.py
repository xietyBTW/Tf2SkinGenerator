"""
Константы приложения
"""

from pathlib import Path
from typing import Dict, Tuple

# ============================================================================
# Пути к инструментам
# ============================================================================

class ToolPaths:
    """Пути к внешним инструментам"""
    VTF_TOOL = Path("tools/VTF/VTFCmd.exe")
    VPK_TOOL = Path("tools/VPK/vpk.exe")
    CROWBAR = Path("tools/crowbar/CrowbarCommandLineDecomp.exe")
    
    @classmethod
    def get_vtf_tool(cls) -> Path:
        """Возвращает абсолютный путь к VTF инструменту"""
        return cls.VTF_TOOL.resolve() if cls.VTF_TOOL.exists() else cls.VTF_TOOL
    
    @classmethod
    def get_vpk_tool(cls) -> Path:
        """Возвращает абсолютный путь к VPK инструменту"""
        return cls.VPK_TOOL.resolve() if cls.VPK_TOOL.exists() else cls.VPK_TOOL
    
    @classmethod
    def get_crowbar(cls) -> Path:
        """Возвращает абсолютный путь к Crowbar"""
        return cls.CROWBAR.resolve() if cls.CROWBAR.exists() else cls.CROWBAR


# ============================================================================
# UI Константы
# ============================================================================

class UIConstants:
    """Константы для пользовательского интерфейса"""
    DEFAULT_WINDOW_X = 100
    DEFAULT_WINDOW_Y = 100
    DEFAULT_WINDOW_WIDTH = 1600
    DEFAULT_WINDOW_HEIGHT = 800
    
    MIN_WINDOW_WIDTH = 1200
    MIN_WINDOW_HEIGHT = 600
    
    PREVIEW_IMAGE_HEIGHT = 500
    PREVIEW_IMAGE_MIN_WIDTH = 800
    
    INFO_SUMMARY_HEIGHT = 220
    INFO_SUMMARY_MIN_WIDTH = 600


# ============================================================================
# Разрешения и форматы
# ============================================================================

class Resolution:
    """Стандартные разрешения"""
    NORMAL = (512, 512)
    HIGH = (1024, 1024)
    ULTRA = (2048, 2048)
    
    RESOLUTION_MAP: Dict[str, Tuple[int, int]] = {
        "512": NORMAL,
        "1024": HIGH,
        "2048": ULTRA
    }
    
    @classmethod
    def from_string(cls, size_str: str) -> Tuple[int, int]:
        """Преобразует строку в кортеж разрешения"""
        return cls.RESOLUTION_MAP.get(size_str, cls.NORMAL)


class VTFFormat:
    """Форматы VTF"""
    DXT1 = "DXT1"
    DXT5 = "DXT5"
    RGBA8888 = "RGBA8888"
    I8 = "I8"
    A8 = "A8"
    
    VALID_FORMATS = [DXT1, DXT5, RGBA8888, I8, A8]
    
    @classmethod
    def is_valid(cls, format_str: str) -> bool:
        """Проверяет валидность формата"""
        return format_str in cls.VALID_FORMATS


# ============================================================================
# VTF Флаги
# ============================================================================

class VTFFlags:
    """Флаги VTF"""
    CLAMPS = "CLAMPS"
    CLAMPT = "CLAMPT"
    CLAMPU = "CLAMPU"
    NOMIP = "NOMIP"
    NOLOD = "NOLOD"
    POINTSAMPLE = "POINTSAMPLE"
    TRILINEAR = "TRILINEAR"
    ANISOTROPIC = "ANISOTROPIC"
    SRGB = "SRGB"
    NOCOMPRESS = "NOCOMPRESS"
    NODEBUGOVERRIDE = "NODEBUGOVERRIDE"
    SINGLECOPY = "SINGLECOPY"
    NODEPTHBUFFER = "NODEPTHBUFFER"
    VERTEXTEXTURE = "VERTEXTEXTURE"
    SSBUMP = "SSBUMP"
    BORDER = "BORDER"
    
    # Маппинг флагов UI -> VTFCmd
    FLAG_MAPPING: Dict[str, str] = {
        CLAMPS: "clamps",
        CLAMPT: "clampt",
        CLAMPU: "clampu",
        NOLOD: "nolod",
        POINTSAMPLE: "pointsample",
        TRILINEAR: "trilinear",
        ANISOTROPIC: "anisotropic",
        SRGB: "srgb",
        NOCOMPRESS: "nocompress",
        NODEBUGOVERRIDE: "nodebugoverride",
        SINGLECOPY: "singlecopy",
        NODEPTHBUFFER: "nodepthbuffer",
        VERTEXTEXTURE: "vertextexture",
        SSBUMP: "ssbump",
        BORDER: "border"
    }


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
    
    # Размеры изображений
    MIN_IMAGE_SIZE = 1
    MAX_IMAGE_SIZE = 4096


# ============================================================================
# Имена файлов
# ============================================================================

class DefaultFilenames:
    """Имена файлов по умолчанию"""
    CONFIG_FILE = "app_config.json"
    LOG_FILE = "tf2_skin_generator.log"

