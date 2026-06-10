"""
Конфигурация приложения
"""

import copy
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from src.shared.logging_config import get_logger
from src.shared.constants import DirectoryPaths, DefaultFilenames

logger = get_logger(__name__)


class AppConfig:
    """
    Класс для работы с конфигурацией приложения.

    Конфиг кэшируется в памяти: get()/load_config() не читают диск, пока
    файл не изменился (проверка по mtime) или не было save_config().
    """

    CONFIG_DIR = Path(DirectoryPaths.CONFIG_DIR)
    CONFIG_FILE = CONFIG_DIR / DefaultFilenames.CONFIG_FILE

    # Значения по умолчанию
    DEFAULT_CONFIG: Dict[str, Any] = {
        "tf2_game_folder": "",
        "export_folder": "export",
        "export_image_format": "VTF",
        "language": "en",
        "last_size": "512",
        "last_format": "DXT1",
        "last_flags": [],
        "keep_temp_on_error": False,
        "debug_mode": False,
        "window_geometry": None,
        # Пользовательские паттерны материалов-исключений (доп. к дефолтным
        # из material_filter): не показываются в 2D и не пишутся в мод.
        "material_blacklist": [],
    }

    # ── Кэш в памяти ───────────────────────────────────────────────────── #
    _cache: Optional[Dict[str, Any]] = None
    # Ключ кэша: (путь файла, mtime) — путь нужен, потому что CONFIG_FILE
    # подменяется в тестах
    _cache_key: Optional[tuple] = None

    @staticmethod
    def _ensure_config_dir() -> None:
        """Создает директорию для конфига, если её нет"""
        AppConfig.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _file_mtime() -> Optional[float]:
        try:
            return os.path.getmtime(AppConfig.CONFIG_FILE)
        except OSError:
            return None

    @staticmethod
    def _current_cache_key() -> tuple:
        return (str(AppConfig.CONFIG_FILE), AppConfig._file_mtime())

    @staticmethod
    def invalidate_cache() -> None:
        """Сбрасывает кэш (для тестов и при внешнем изменении файла)."""
        AppConfig._cache = None
        AppConfig._cache_key = None

    @staticmethod
    def load_config() -> Dict[str, Any]:
        """
        Загружает конфигурацию (из кэша, если файл не менялся).

        Returns:
            Глубокая копия словаря с настройками — мутации результата
            не влияют ни на кэш, ни на DEFAULT_CONFIG.
        """
        current_key = AppConfig._current_cache_key()
        if AppConfig._cache is not None and AppConfig._cache_key == current_key:
            return copy.deepcopy(AppConfig._cache)

        AppConfig._ensure_config_dir()

        if not AppConfig.CONFIG_FILE.exists():
            # Если файл не существует, создаем с настройками по умолчанию
            logger.info("Файл конфигурации не найден, создается с настройками по умолчанию")
            AppConfig.save_config(copy.deepcopy(AppConfig.DEFAULT_CONFIG))
            return copy.deepcopy(AppConfig.DEFAULT_CONFIG)

        try:
            with open(AppConfig.CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Объединяем с настройками по умолчанию (на случай, если в файле нет каких-то ключей)
            merged_config = copy.deepcopy(AppConfig.DEFAULT_CONFIG)
            merged_config.update(config)
            AppConfig._cache = copy.deepcopy(merged_config)
            AppConfig._cache_key = current_key
            logger.debug("Конфигурация успешно загружена")
            return merged_config
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Ошибка при загрузке конфига: {e}. Используются настройки по умолчанию.", exc_info=True)
            return copy.deepcopy(AppConfig.DEFAULT_CONFIG)

    @staticmethod
    def save_config(config: Dict[str, Any]) -> bool:
        """
        Сохраняет конфигурацию в файл (атомарно: temp-файл + os.replace).

        Args:
            config: Словарь с настройками

        Returns:
            True если успешно, False если ошибка
        """
        AppConfig._ensure_config_dir()

        tmp_path = AppConfig.CONFIG_FILE.with_suffix('.json.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, AppConfig.CONFIG_FILE)
            AppConfig._cache = copy.deepcopy(config)
            AppConfig._cache_key = AppConfig._current_cache_key()
            logger.debug("Конфигурация успешно сохранена")
            return True
        except IOError as e:
            logger.error(f"Ошибка при сохранении конфига: {e}", exc_info=True)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return False

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """
        Получает значение настройки по ключу

        Args:
            key: Ключ настройки
            default: Значение по умолчанию, если ключ не найден

        Returns:
            Значение настройки или default
        """
        config = AppConfig.load_config()
        return config.get(key, default)

    @staticmethod
    def set(key: str, value: Any) -> bool:
        """
        Устанавливает значение настройки и сохраняет в файл

        Args:
            key: Ключ настройки
            value: Значение

        Returns:
            True если успешно, False если ошибка
        """
        config = AppConfig.load_config()
        config[key] = value
        logger.debug(f"Установлено значение конфигурации: {key} = {value}")
        return AppConfig.save_config(config)

    @staticmethod
    def get_tf2_game_folder() -> str:
        """
        Получает путь к директории TF2

        Returns:
            Путь к директории TF2 или пустая строка
        """
        return AppConfig.get("tf2_game_folder", "")

    @staticmethod
    def set_tf2_game_folder(path: str) -> bool:
        """
        Устанавливает путь к директории TF2

        Args:
            path: Путь к директории TF2

        Returns:
            True если успешно, False если ошибка
        """
        logger.info(f"Установлен путь к TF2: {path}")
        return AppConfig.set("tf2_game_folder", path)
