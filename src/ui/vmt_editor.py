import os
import shutil
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit
)
from PySide6.QtGui import QCloseEvent
from src.data.translations import TRANSLATIONS
from src.services.edited_vmt_service import EditedVMTService


class VMTEditorDialog(QDialog):
    def __init__(self, parent=None, vmt_path="", weapon_key="", t=None):
        super().__init__(parent)
        self.t = t or TRANSLATIONS['ru']
        self.setWindowTitle("VMT Editor")
        self.setGeometry(500, 150, 700, 600)
        self.vmt_path = vmt_path
        self.weapon_key = weapon_key

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
        if os.path.exists(self.vmt_path):
            with open(self.vmt_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.text_edit.setPlainText(content)
            
            if os.path.exists(self.vmt_path):
                shutil.copy2(self.vmt_path, self.backup_path)

    def save_changes(self):
        content = self.text_edit.toPlainText()
        watermark = "\n// made on Tf2SkinGenerator https://steamcommunity.com/id/sosatihackeri - Developer(xiety)"
        if watermark.strip() not in content:
            content += watermark
        
        with open(self.vmt_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        if self.weapon_key:
            EditedVMTService.save_edited_vmt(self.weapon_key, content)
        
        self.accept()

    def restore_backup(self):
        if os.path.exists(self.backup_path):
            with open(self.backup_path, "r", encoding="utf-8") as f:
                self.text_edit.setPlainText(f.read())
    
    def closeEvent(self, event: QCloseEvent) -> None:
        if self.vmt_path:
            normalized_path = os.path.normpath(self.vmt_path)
            temp_dir = os.path.normpath(os.path.join("tools", "temp_vmt_extract"))
            
            if normalized_path.startswith(temp_dir + os.sep) or normalized_path.startswith(temp_dir + "/"):
                try:
                    if os.path.exists(self.vmt_path):
                        os.remove(self.vmt_path)
                except Exception:
                    pass
        
        super().closeEvent(event)

