import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLabel, QMessageBox,
)
from PySide6.QtGui import (
    QCloseEvent, QSyntaxHighlighter, QTextCharFormat, QColor, QFont,
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
        self._rules.append((QRegularExpression(r'//[^\n]*'), fmt('#555555', italic=True)))
        # 2. $параметры шейдера
        self._rules.append((QRegularExpression(r'\$\w+'), fmt('#ff6b35', bold=True)))
        # 3. Имена шейдеров/секций в кавычках без $ (первый токен строки)
        self._rules.append((
            QRegularExpression(r'^\s*"[A-Za-z][A-Za-z0-9_]*"\s*$'),
            fmt('#7aa8d0', bold=True),
        ))
        # 4. Значения в кавычках
        self._rules.append((QRegularExpression(r'"[^"]*"'), fmt('#a8c4a2')))
        # 5. Скобки
        self._rules.append((QRegularExpression(r'[{}]'), fmt('#888888')))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class VMTEditorDialog(QDialog):
    def __init__(
        self,
        parent=None,
        vmt_path: str = "",
        weapon_key: str = "",
        t=None,
        display_name: str = "",
    ):
        super().__init__(parent)
        self.t           = t or TRANSLATIONS['en']
        self.vmt_path    = vmt_path
        self.weapon_key  = weapon_key
        self._display    = display_name or weapon_key or os.path.basename(vmt_path)
        self._modified   = False

        # ── Бэкап игрового оригинала ─────────────────────────────────────── #
        # Сохраняем «чистую» игровую копию ОДИН РАЗ — только если ещё нет
        # сохранённого отредактированного VMT для этого ключа.
        # Это позволяет кнопке «Reset to original» восстановить именно
        # оригинал из игры, а не случайно закешированную правку.
        self._orig_content: str = ""
        if vmt_path and os.path.exists(vmt_path):
            with open(vmt_path, "r", encoding="utf-8", errors="replace") as f:
                self._orig_content = f.read()

        self._setup_ui()
        self._load_content()

    # ── UI ────────────────────────────────────────────────────────────────── #

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"VMT Editor — {self._display}")
        self.setMinimumSize(700, 580)
        self.resize(760, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── Статусная строка ─────────────────────────────────────────────── #
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._status_label)

        # ── Редактор ─────────────────────────────────────────────────────── #
        self.text_edit = QTextEdit(self)
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
        self._highlighter = VMTHighlighter(self.text_edit.document())
        self.text_edit.document().contentsChanged.connect(self._on_content_changed)
        layout.addWidget(self.text_edit)

        # ── Кнопки ───────────────────────────────────────────────────────── #
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        _btn_style = """
            QPushButton {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                color: #ccc;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover  { background-color: #333; border-color: #555; }
            QPushButton:pressed { background-color: #222; }
            QPushButton:disabled { color: #555; border-color: #2a2a2a; }
        """
        _save_style = """
            QPushButton {
                background-color: #c05020;
                border: 1px solid #d06030;
                border-radius: 4px;
                color: #fff;
                padding: 6px 18px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover  { background-color: #d06030; }
            QPushButton:pressed { background-color: #a04010; }
        """

        self.save_btn = QPushButton(self.t.get('save', 'Save'))
        self.save_btn.setStyleSheet(_save_style)
        self.save_btn.setToolTip(self.t.get('vmt_save_tooltip', 'Save changes (Ctrl+S)'))
        self.save_btn.setShortcut("Ctrl+S")
        self.save_btn.clicked.connect(self._save)

        self.reset_btn = QPushButton(self.t.get('vmt_reset_original', 'Reset to game original'))
        self.reset_btn.setStyleSheet(_btn_style)
        self.reset_btn.setToolTip(
            self.t.get('vmt_reset_tooltip', 'Discard all edits and restore the game\'s original VMT')
        )
        self.reset_btn.clicked.connect(self._reset_to_original)
        # Кнопка активна только если есть сохранённый вариант (т.е. было что сбрасывать)
        self.reset_btn.setEnabled(EditedVMTService.has_edited_vmt(self.weapon_key))

        self.close_btn = QPushButton(self.t.get('close', 'Close'))
        self.close_btn.setStyleSheet(_btn_style)
        self.close_btn.clicked.connect(self.close)

        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    # ── Загрузка контента ─────────────────────────────────────────────────── #

    def _load_content(self) -> None:
        """Загружает контент в редактор."""
        # Временно отключаем трекинг изменений при первоначальной загрузке
        self.text_edit.document().contentsChanged.disconnect(self._on_content_changed)
        self.text_edit.setPlainText(self._orig_content)
        self.text_edit.document().contentsChanged.connect(self._on_content_changed)

        self._modified = False
        self._update_title()
        self._update_status()

    # ── Обработчики ───────────────────────────────────────────────────────── #

    def _on_content_changed(self) -> None:
        if not self._modified:
            self._modified = True
            self._update_title()
            self._update_status()

    def _update_title(self) -> None:
        marker = " *" if self._modified else ""
        self.setWindowTitle(f"VMT Editor — {self._display}{marker}")

    def _update_status(self) -> None:
        if self._modified:
            self._status_label.setText(
                self.t.get('vmt_unsaved_changes', '● Unsaved changes')
            )
            self._status_label.setStyleSheet("color: #d08030; font-size: 11px;")
        elif EditedVMTService.has_edited_vmt(self.weapon_key):
            self._status_label.setText(
                self.t.get('vmt_custom_active', '✓ Custom VMT active')
            )
            self._status_label.setStyleSheet("color: #70a870; font-size: 11px;")
        else:
            self._status_label.setText(
                self.t.get('vmt_showing_original', 'Showing game original')
            )
            self._status_label.setStyleSheet("color: #888; font-size: 11px;")

    def _save(self) -> None:
        """Сохраняет изменения без закрытия диалога."""
        content = self.text_edit.toPlainText()

        # Дописываем ватермарк только если его ещё нет
        watermark = "// made on Tf2SkinGenerator https://steamcommunity.com/id/sosatihackeri - Developer(xiety)"
        if watermark.strip() not in content:
            content = content.rstrip() + "\n" + watermark + "\n"
            # Обновляем редактор тоже (чтобы не было расхождения)
            self.text_edit.document().contentsChanged.disconnect(self._on_content_changed)
            self.text_edit.setPlainText(content)
            self.text_edit.document().contentsChanged.connect(self._on_content_changed)

        # Сохраняем во временный файл (для текущего сеанса)
        if self.vmt_path:
            try:
                with open(self.vmt_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                pass

        # Сохраняем в постоянный кэш (tools/edited_vmt/)
        if self.weapon_key:
            EditedVMTService.save_edited_vmt(self.weapon_key, content)

        self._modified = False
        self._update_title()
        self._update_status()
        self.reset_btn.setEnabled(True)

    def _reset_to_original(self) -> None:
        """Сбрасывает к оригинальному VMT из игры, удаляет сохранённую правку."""
        reply = QMessageBox.question(
            self,
            self.t.get('vmt_reset_original', 'Reset to game original'),
            self.t.get(
                'vmt_reset_confirm',
                'This will discard all your edits and restore the game\'s original VMT.\n\nContinue?',
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Удаляем сохранённый VMT
        if self.weapon_key:
            EditedVMTService.delete_edited_vmt(self.weapon_key)

        # Загружаем оригинальный контент обратно
        self.text_edit.document().contentsChanged.disconnect(self._on_content_changed)
        self.text_edit.setPlainText(self._orig_content)
        self.text_edit.document().contentsChanged.connect(self._on_content_changed)

        self._modified = False
        self.reset_btn.setEnabled(False)
        self._update_title()
        self._update_status()

    # ── Закрытие ──────────────────────────────────────────────────────────── #

    def closeEvent(self, event: QCloseEvent) -> None:
        # Предупреждаем о несохранённых изменениях
        if self._modified:
            reply = QMessageBox.question(
                self,
                self.t.get('vmt_unsaved_title', 'Unsaved changes'),
                self.t.get(
                    'vmt_unsaved_confirm',
                    'You have unsaved changes. Close without saving?',
                ),
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply == QMessageBox.Save:
                self._save()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
                return

        # Удаляем временный файл (только если он в temp_vmt_extract)
        if self.vmt_path:
            normalized = os.path.normpath(self.vmt_path)
            temp_dir   = os.path.normpath(os.path.join("tools", "temp_vmt_extract"))
            if normalized.startswith(temp_dir + os.sep) or normalized == temp_dir:
                try:
                    if os.path.exists(self.vmt_path):
                        os.remove(self.vmt_path)
                except Exception:
                    pass

        super().closeEvent(event)
