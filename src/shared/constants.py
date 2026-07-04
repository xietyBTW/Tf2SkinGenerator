"""
Константы приложения
"""

from pathlib import Path
from typing import Optional


# ============================================================================
# Команды TF2
# ============================================================================

class Team:
    """Команды TF2. Значения СТРОКОВЫЕ намеренно: служат и dict-ключами
    (``_textures['red']``), и сериализуются в edit-state как есть — поэтому
    ``Team.RED == 'red'`` и замена литералов на константы поведение не меняет,
    лишь убирает magic-строки и защищает от опечаток."""
    RED = "red"
    BLU = "blu"

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
        """Абсолютный путь к vpk.exe. Приоритет:

          1. Бандл ``tools/VPK/vpk.exe`` (если положили рядом).
          2. ``vpk.exe`` из ``bin`` установленной у пользователя TF2 — это тот же
             официальный инструмент Valve, причём его DLL (tier0/vstdlib/
             FileSystem_Stdio) лежат рядом в bin, поэтому он запускается без
             бандла. Так проприетарные бинарники Valve не нужно носить в репо.
          3. Иначе — бандл-путь (вызов упадёт с понятной ошибкой; у распаковки
             есть резервный путь через python-библиотеку vpk).
        """
        if cls.VPK_TOOL.exists():
            return cls.VPK_TOOL.resolve()
        bin_vpk = cls._tf2_bin_tool("vpk.exe")
        if bin_vpk is not None:
            return bin_vpk
        return cls.VPK_TOOL

    @staticmethod
    def _tf2_bin_tool(exe_name: str) -> Optional[Path]:
        """Путь к инструменту из ``<TF2>/bin`` или None. Папку TF2 берём из
        настроек приложения. Пригодно и для других инструментов Valve из bin
        (vtex.exe, vtf2tga.exe, studiomdl.exe …)."""
        try:
            from src.config.app_config import AppConfig
            tf2_root = AppConfig.get_tf2_game_folder()
        except Exception:
            return None
        if not tf2_root:
            return None
        p = Path(tf2_root) / "bin" / exe_name
        return p.resolve() if p.exists() else None


# ============================================================================
# Таймауты внешних процессов (секунды)
# ============================================================================

class ToolTimeouts:
    """
    Лимиты времени для внешних инструментов (Crowbar, studiomdl, VTFCmd, vpk.exe).

    Без таймаута зависший процесс (битая модель, баг Crowbar) заблокировал бы
    воркер навсегда: прогресс-бар висит, отмена не убивает заблокированный
    subprocess. По истечении лимита поднимаем понятную ошибку.
    """
    DECOMPILE = 300   # Crowbar: декомпиляция MDL → QC/SMD
    COMPILE = 300     # studiomdl: компиляция QC → MDL
    VTF = 120         # VTFCmd: конвертация изображения в VTF
    VPK = 180         # vpk.exe: упаковка папки в VPK


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
