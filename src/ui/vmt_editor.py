import os
import re
import shutil
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit
)
from PySide6.QtGui import (
    QCloseEvent, QSyntaxHighlighter, QTextCharFormat, QColor, QFont
)
from PySide6.QtCore import QRegularExpression
from src.data.translations import TRANSLATIONS
from src.services.edited_vmt_service import EditedVMTService


class VMTHighlighter(QSyntaxHighlighter):
    """Подсветка синтаксиса VMT файлов."""

    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        # 1. Комментарии  //...
        self._rules.append((
            QRegularExpression(r'//[^\n]*'),
            fmt('#555555', italic=True),
        ))

        # 2. Параметры шейдера: $basetexture, $translucent и т.д.
        self._rules.append((
            QRegularExpression(r'\$\w+'),
            fmt('#ff6b35', bold=True),
        ))

        # 3. Имена шейдеров/секций в кавычках без $ (первый токен строки)
        #    «"UnlitGeneric"», «"Proxies"», «"animatedtexture"» и т.п.
        self._rules.append((
            QRegularExpression(r'^\s*"[A-Za-z][A-Za-z0-9_]*"\s*$'),
            fmt('#7aa8d0', bold=True),
        ))

        # 4. Значения в кавычках (строки)
        self._rules.append((
            QRegularExpression(r'"[^"]*"'),
            fmt('#a8c4a2'),
        ))

        # 5. Скобки { }
        self._rules.append((
            QRegularExpression(r'[{}]'),
            fmt('#888888'),
        ))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


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
        # Моноширинный шрифт для кода
        mono_font = QFont("Consolas", 11)
        mono_font.setStyleHint(QFont.Monospace)
        self.text_edit.setFont(mono_font)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #111;
                color: #ddd;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 8px;
                selection-background-color: rgba(255,107,53,0.3);
            }
        """)

        # Подключаем подсветку синтаксиса
        self._highlighter = VMTHighlighter(self.text_edit.document())

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
