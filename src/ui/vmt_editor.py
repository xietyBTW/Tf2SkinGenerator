"""
VMT редактор
"""

import os
import shutil
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit
)
from src.data.translations import TRANSLATIONS
from src.services.edited_vmt_service import EditedVMTService


class VMTEditorDialog(QDialog):
    def __init__(self, parent=None, vmt_path="", weapon_key="", t=None):
        super().__init__(parent)
        self.t = t or TRANSLATIONS['ru']
        self.setWindowTitle("VMT Editor")
        self.setGeometry(500, 150, 700, 600)
        self.vmt_path = vmt_path
        self.weapon_key = weapon_key  # Ключ оружия для сохранения отредактированного VMT

        self.backup_dir = os.path.join("tools", "backupVMT")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.backup_path = os.path.join(self.backup_dir, os.path.basename(vmt_path))

        self.text_edit = QTextEdit(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text_edit)

        button_layout = QHBoxLayout()

        self.save_button = QPushButton(self.t['save'], self)
        self.save_button.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_button)

        self.restore_button = QPushButton(self.t['restore'], self)
        self.restore_button.clicked.connect(self.restore_backup)
        button_layout.addWidget(self.restore_button)

        layout.addLayout(button_layout)
        self.load_vmt()

    def load_vmt(self):
        """Загружает VMT файл в редактор"""
        if os.path.exists(self.vmt_path):
            with open(self.vmt_path, "r", encoding="utf-8") as f:
                self.text_edit.setPlainText(f.read())
        if not os.path.exists(self.backup_path):
            shutil.copy2(self.vmt_path, self.backup_path)

    def save_changes(self):
        """Сохраняет изменения в VMT файл и в папку отредактированных VMT"""
        content = self.text_edit.toPlainText()
        watermark = "\n// made on Tf2SkinGenerator https://steamcommunity.com/id/sosatihackeri - Developer(xiety)"
        if watermark.strip() not in content:
            content += watermark
        
        # Сохраняем в исходный файл
        with open(self.vmt_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Сохраняем в папку отредактированных VMT для использования при сборке VPK
        if self.weapon_key:
            EditedVMTService.save_edited_vmt(self.weapon_key, content)
        
        self.accept()

    def restore_backup(self):
        """Восстанавливает VMT из бэкапа"""
        if os.path.exists(self.backup_path):
            with open(self.backup_path, "r", encoding="utf-8") as f:
                self.text_edit.setPlainText(f.read())

