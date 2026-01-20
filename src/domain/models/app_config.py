"""
Модель конфигурации приложения
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
from pathlib import Path
import json
import os
from src.config.app_config import AppConfig as AppConfigService


@dataclass
class AppConfig:
    """Конфигурация приложения"""
    
    tf2_game_folder: str = ""
    export_folder: str = "export"
    export_image_format: str = "VTF"
    language: str = "en"
    last_size: str = "512"
    last_format: str = "DXT1"
    last_flags: List[str] = field(default_factory=list)
    keep_temp_on_error: bool = False
    debug_mode: bool = False
    keep_temp_files: bool = False
    
    @classmethod
    def load_from_file(cls) -> 'AppConfig':
        """
        Загружает конфигурацию из файла
        
        Returns:
            Загруженная конфигурация
        """
        config_dict = AppConfigService.load_config()
        return cls(**config_dict)
    
    def save_to_file(self) -> bool:
        """
        Сохраняет конфигурацию в файл
        
        Returns:
            True если успешно, False если ошибка
        """
        config_dict = {
            'tf2_game_folder': self.tf2_game_folder,
            'export_folder': self.export_folder,
            'export_image_format': self.export_image_format,
            'language': self.language,
            'last_size': self.last_size,
            'last_format': self.last_format,
            'last_flags': self.last_flags,
            'keep_temp_on_error': self.keep_temp_on_error,
            'debug_mode': self.debug_mode,
            'keep_temp_files': self.keep_temp_files
        }
        return AppConfigService.save_config(config_dict)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Получает значение настройки по ключу
        
        Args:
            key: Ключ настройки
            default: Значение по умолчанию
            
        Returns:
            Значение настройки или default
        """
        return getattr(self, key, default)
    
    def set(self, key: str, value: Any) -> None:
        """
        Устанавливает значение настройки
        
        Args:
            key: Ключ настройки
            value: Значение
        """
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise AttributeError(f"Неизвестный ключ конфигурации: {key}")

