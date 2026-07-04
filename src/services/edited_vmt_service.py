"""
Сервис для работы с отредактированными VMT файлами
"""

import os
from typing import Optional


class EditedVMTService:
    """Сервис для сохранения и загрузки отредактированных VMT файлов.

    Ключ (``edit_key``) — имя МАТЕРИАЛА/текстуры: у каждой текстуры
    свой кастомный VMT (правило пер-текстурного редактирования). Рядом с правкой
    хранится ``{key}.orig`` — «чистый» игровой оригинал, снятый при первом
    сохранении, чтобы «Reset to game original» восстанавливал именно его, а не
    ранее сохранённую правку.
    """

    EDITED_VMT_DIR = os.path.join("tools", "edited_vmt")
    
    @staticmethod
    def get_edited_vmt_path(edit_key: str) -> str:
        """
        Возвращает путь к отредактированному VMT файлу для оружия
        
        Args:
            edit_key: Ключ материала/текстуры (имя, напр. c_scattergun)
            
        Returns:
            Путь к файлу отредактированного VMT
        """
        os.makedirs(EditedVMTService.EDITED_VMT_DIR, exist_ok=True)
        return os.path.join(EditedVMTService.EDITED_VMT_DIR, f"{edit_key}.vmt")
    
    @staticmethod
    def has_edited_vmt(edit_key: str) -> bool:
        """
        Проверяет, существует ли отредактированный VMT файл для оружия
        
        Args:
            edit_key: Ключ материала/текстуры
            
        Returns:
            True если файл существует
        """
        vmt_path = EditedVMTService.get_edited_vmt_path(edit_key)
        return os.path.exists(vmt_path)
    
    @staticmethod
    def get_edited_vmt(edit_key: str) -> Optional[str]:
        """
        Возвращает путь к отредактированному VMT файлу, если он существует
        
        Args:
            edit_key: Ключ материала/текстуры
            
        Returns:
            Путь к файлу или None если не существует
        """
        if EditedVMTService.has_edited_vmt(edit_key):
            return EditedVMTService.get_edited_vmt_path(edit_key)
        return None
    
    @staticmethod
    def save_edited_vmt(edit_key: str, vmt_content: str) -> str:
        """
        Сохраняет отредактированный VMT файл
        
        Args:
            edit_key: Ключ материала/текстуры
            vmt_content: Содержимое VMT файла
            
        Returns:
            Путь к сохраненному файлу
        """
        vmt_path = EditedVMTService.get_edited_vmt_path(edit_key)
        os.makedirs(os.path.dirname(vmt_path), exist_ok=True)
        with open(vmt_path, 'w', encoding='utf-8') as f:
            f.write(vmt_content)
        return vmt_path
    
    @staticmethod
    def delete_edited_vmt(edit_key: str) -> bool:
        """
        Удаляет отредактированный VMT файл (и бэкап оригинала).

        Args:
            edit_key: Ключ материала/текстуры

        Returns:
            True если файл был удален, False если не существовал
        """
        # Бэкап оригинала больше не нужен, если правки нет — убираем вместе с ней.
        EditedVMTService._remove_original_backup(edit_key)
        vmt_path = EditedVMTService.get_edited_vmt_path(edit_key)
        if os.path.exists(vmt_path):
            os.remove(vmt_path)
            return True
        return False

    # ── Бэкап игрового оригинала (для «Reset to game original») ───────────── #

    @staticmethod
    def _original_backup_path(edit_key: str) -> str:
        """Путь к бэкапу игрового оригинала. Расширение ``.orig`` (не ``.vmt``),
        чтобы бэкап нельзя было принять за отдельный отредактированный VMT."""
        os.makedirs(EditedVMTService.EDITED_VMT_DIR, exist_ok=True)
        return os.path.join(EditedVMTService.EDITED_VMT_DIR, f"{edit_key}.orig")

    @staticmethod
    def has_original_backup(edit_key: str) -> bool:
        return os.path.exists(EditedVMTService._original_backup_path(edit_key))

    @staticmethod
    def save_original_backup(edit_key: str, content: str) -> None:
        """Сохраняет «чистый» игровой оригинал (один раз, при первой правке)."""
        path = EditedVMTService._original_backup_path(edit_key)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def read_original_backup(edit_key: str) -> Optional[str]:
        """Возвращает содержимое бэкапа оригинала или None, если его нет."""
        path = EditedVMTService._original_backup_path(edit_key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def _remove_original_backup(edit_key: str) -> None:
        path = EditedVMTService._original_backup_path(edit_key)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

