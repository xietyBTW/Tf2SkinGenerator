"""
Сервис для работы с отредактированными VMT файлами
"""

import os
from typing import Optional


class EditedVMTService:
    """Сервис для сохранения и загрузки отредактированных VMT файлов"""
    
    EDITED_VMT_DIR = os.path.join("tools", "edited_vmt")
    
    @staticmethod
    def get_edited_vmt_path(weapon_key: str) -> str:
        """
        Возвращает путь к отредактированному VMT файлу для оружия
        
        Args:
            weapon_key: Ключ оружия (например, c_scattergun)
            
        Returns:
            Путь к файлу отредактированного VMT
        """
        os.makedirs(EditedVMTService.EDITED_VMT_DIR, exist_ok=True)
        return os.path.join(EditedVMTService.EDITED_VMT_DIR, f"{weapon_key}.vmt")
    
    @staticmethod
    def has_edited_vmt(weapon_key: str) -> bool:
        """
        Проверяет, существует ли отредактированный VMT файл для оружия
        
        Args:
            weapon_key: Ключ оружия
            
        Returns:
            True если файл существует
        """
        vmt_path = EditedVMTService.get_edited_vmt_path(weapon_key)
        return os.path.exists(vmt_path)
    
    @staticmethod
    def get_edited_vmt(weapon_key: str) -> Optional[str]:
        """
        Возвращает путь к отредактированному VMT файлу, если он существует
        
        Args:
            weapon_key: Ключ оружия
            
        Returns:
            Путь к файлу или None если не существует
        """
        if EditedVMTService.has_edited_vmt(weapon_key):
            return EditedVMTService.get_edited_vmt_path(weapon_key)
        return None
    
    @staticmethod
    def save_edited_vmt(weapon_key: str, vmt_content: str) -> str:
        """
        Сохраняет отредактированный VMT файл
        
        Args:
            weapon_key: Ключ оружия
            vmt_content: Содержимое VMT файла
            
        Returns:
            Путь к сохраненному файлу
        """
        vmt_path = EditedVMTService.get_edited_vmt_path(weapon_key)
        os.makedirs(os.path.dirname(vmt_path), exist_ok=True)
        with open(vmt_path, 'w', encoding='utf-8') as f:
            f.write(vmt_content)
        return vmt_path
    
    @staticmethod
    def delete_edited_vmt(weapon_key: str) -> bool:
        """
        Удаляет отредактированный VMT файл
        
        Args:
            weapon_key: Ключ оружия
            
        Returns:
            True если файл был удален, False если не существовал
        """
        vmt_path = EditedVMTService.get_edited_vmt_path(weapon_key)
        if os.path.exists(vmt_path):
            os.remove(vmt_path)
            return True
        return False

