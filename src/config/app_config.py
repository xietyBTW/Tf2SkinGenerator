"""
Конфигурация приложения
"""

import os
import json
from typing import Optional, Dict, Any


class AppConfig:
    """Класс для работы с конфигурацией приложения"""
    
    CONFIG_DIR = "config"
    CONFIG_FILE = os.path.join(CONFIG_DIR, "app_config.json")
    
    # Значения по умолчанию
    DEFAULT_CONFIG = {
        "tf2_game_folder": "",
        "language": "ru",
        "last_size": "512",
        "last_format": "DXT1",
        "last_flags": [],
        "keep_temp_on_error": False,
        "debug_mode": False
    }
    
    @staticmethod
    def _ensure_config_dir():
        """Создает директорию для конфига, если её нет"""
        if not os.path.exists(AppConfig.CONFIG_DIR):
            os.makedirs(AppConfig.CONFIG_DIR, exist_ok=True)
    
    @staticmethod
    def load_config() -> Dict[str, Any]:
        """
        Загружает конфигурацию из файла
        
        Returns:
            Словарь с настройками
        """
        AppConfig._ensure_config_dir()
        
        if not os.path.exists(AppConfig.CONFIG_FILE):
            # Если файл не существует, создаем с настройками по умолчанию
            AppConfig.save_config(AppConfig.DEFAULT_CONFIG)
            return AppConfig.DEFAULT_CONFIG.copy()
        
        try:
            with open(AppConfig.CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Объединяем с настройками по умолчанию (на случай, если в файле нет каких-то ключей)
            merged_config = AppConfig.DEFAULT_CONFIG.copy()
            merged_config.update(config)
            return merged_config
        except (json.JSONDecodeError, IOError) as e:
            print(f"Ошибка при загрузке конфига: {e}. Используются настройки по умолчанию.")
            return AppConfig.DEFAULT_CONFIG.copy()
    
    @staticmethod
    def save_config(config: Dict[str, Any]) -> bool:
        """
        Сохраняет конфигурацию в файл
        
        Args:
            config: Словарь с настройками
            
        Returns:
            True если успешно, False если ошибка
        """
        AppConfig._ensure_config_dir()
        
        try:
            with open(AppConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"Ошибка при сохранении конфига: {e}")
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
        return AppConfig.set("tf2_game_folder", path)
