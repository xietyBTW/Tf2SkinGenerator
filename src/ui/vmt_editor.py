import os
import re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLabel, QMessageBox, QToolButton, QMenu, QCompleter, QToolTip,
)
from PySide6.QtGui import (
    QCloseEvent, QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QAction,
    QTextCursor,
)
from PySide6.QtCore import QRegularExpression, Qt, QEvent, QStringListModel
from src.data.translations import TRANSLATIONS
from src.data.vmt_snippets import VMT_SNIPPETS, VMT_FULL_TEMPLATES, VMT_PARAM_DOCS, all_param_names
from src.services.edited_vmt_service import EditedVMTService
from src.services.vmt_service import VMTService


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


class VMTTextEdit(QTextEdit):
    """
    QTextEdit с автодополнением $-параметров и тултипами при наведении.

    - Автодополнение: при наборе "$ba" всплывает список совпадающих параметров
      (из VMT_PARAM_DOCS), Enter/Tab подставляет.
    - Тултипы: наведение на "$param" показывает краткое описание параметра.
    """

    _TOKEN_RE = re.compile(r'\$\w+')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self._completer = QCompleter(self)
        self._completer.setModel(QStringListModel(all_param_names(), self._completer))
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert_completion)

        # Подсветка парных { } при перемещении курсора
        self.cursorPositionChanged.connect(self._highlight_brackets)

    # ── Подсветка парных скобок ─────────────────────────────────────────── #

    @staticmethod
    def _structural_mask(text: str) -> list:
        """Маска: True там, где символ структурный (вне строк и // комментариев)."""
        n = len(text)
        mask = [True] * n
        in_quote = False
        i = 0
        while i < n:
            c = text[i]
            if c == '"':
                mask[i] = False
                in_quote = not in_quote
                i += 1
                continue
            if in_quote:
                mask[i] = False
                i += 1
                continue
            if c == '/' and i + 1 < n and text[i + 1] == '/':
                while i < n and text[i] != '\n':
                    mask[i] = False
                    i += 1
                continue
            i += 1
        return mask

    @staticmethod
    def _match_brace(text: str, mask: list, pos: int) -> int:
        """Возвращает индекс парной скобки для скобки в позиции pos, или -1."""
        ch = text[pos]
        if ch == '{':
            step, opener, closer = 1, '{', '}'
        elif ch == '}':
            step, opener, closer = -1, '}', '{'
        else:
            return -1
        depth = 0
        i = pos
        n = len(text)
        while 0 <= i < n:
            if mask[i]:
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        return i
            i += step
        return -1

    def _highlight_brackets(self) -> None:
        text = self.toPlainText()
        if not text:
            self.setExtraSelections([])
            return
        mask = self._structural_mask(text)
        pos = self.textCursor().position()

        pair = []
        # Скобка под курсором или сразу перед ним
        for p in (pos, pos - 1):
            if 0 <= p < len(text) and text[p] in '{}' and mask[p]:
                m = self._match_brace(text, mask, p)
                if m != -1:
                    pair = [p, m]
                break

        selections = []
        for p in pair:
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor('#3a5a3a'))
            fmt.setForeground(QColor('#ffffff'))
            sel.format = fmt
            c = self.textCursor()
            c.setPosition(p)
            c.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            selections.append(sel)
        self.setExtraSelections(selections)

    # ── Автодополнение ──────────────────────────────────────────────────── #

    def _token_prefix(self) -> str:
        """$-токен от начала до позиции курсора (например, '$ba')."""
        tc = self.textCursor()
        block = tc.block().text()
        col = tc.positionInBlock()
        start = col
        while start > 0 and (block[start - 1].isalnum() or block[start - 1] == '_'):
            start -= 1
        if start > 0 and block[start - 1] == '$':
            return block[start - 1:col]
        return ''

    def _insert_completion(self, completion: str) -> None:
        prefix = self._token_prefix()
        tc = self.textCursor()
        for _ in range(len(prefix)):
            tc.deletePreviousChar()
        tc.insertText(completion)
        self.setTextCursor(tc)

    def keyPressEvent(self, e) -> None:
        popup = self._completer.popup()
        if popup.isVisible() and e.key() in (
            Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape,
        ):
            # Отдаём управление попапу (Enter/Tab подставит, Esc закроет)
            e.ignore()
            return

        super().keyPressEvent(e)

        prefix = self._token_prefix()
        if prefix.startswith('$') and len(prefix) >= 2:
            if prefix != self._completer.completionPrefix():
                self._completer.setCompletionPrefix(prefix)
                self._completer.popup().setCurrentIndex(
                    self._completer.completionModel().index(0, 0)
                )
            if self._completer.completionCount() > 0:
                cr = self.cursorRect()
                cr.setWidth(
                    self._completer.popup().sizeHintForColumn(0)
                    + self._completer.popup().verticalScrollBar().sizeHint().width()
                )
                self._completer.complete(cr)
            else:
                popup.hide()
        else:
            popup.hide()

    # ── Тултипы при наведении ───────────────────────────────────────────── #

    def event(self, e) -> bool:
        if e.type() == QEvent.ToolTip:
            tc = self.cursorForPosition(e.pos())
            token = self._token_at(tc.block().text(), tc.positionInBlock())
            doc = VMT_PARAM_DOCS.get(token)
            if doc:
                QToolTip.showText(e.globalPos(), f'{token} — {doc}', self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    @classmethod
    def _token_at(cls, text: str, col: int) -> str:
        """Возвращает $-токен, в пределах которого находится позиция col."""
        for m in cls._TOKEN_RE.finditer(text or ''):
            if m.start() <= col <= m.end():
                return m.group(0)
        return ''


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
        self._is_valid   = True       # результат последней проверки синтаксиса
        self._error_line = 0
        self._error_msg  = ""

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
        self.text_edit = VMTTextEdit(self)
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

        # ── Кнопка «Вставить» с меню сниппетов ───────────────────────────── #
        self.insert_btn = QToolButton()
        self.insert_btn.setText(self.t.get('vmt_insert', 'Insert') + "  ▾")
        self.insert_btn.setStyleSheet(_btn_style + """
            QToolButton::menu-indicator { image: none; width: 0px; }
        """)
        self.insert_btn.setPopupMode(QToolButton.InstantPopup)
        self.insert_btn.setToolTip(
            self.t.get('vmt_insert_tooltip', 'Insert a parameter / proxy / template')
        )
        self._build_insert_menu()

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

        btn_row.addWidget(self.insert_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    # ── Меню вставки сниппетов ─────────────────────────────────────────────── #

    def _build_insert_menu(self) -> None:
        """Строит меню «Вставить» из VMT_SNIPPETS (категории → пункты)."""
        menu = QMenu(self)
        for category, items in VMT_SNIPPETS.items():
            submenu = menu.addMenu(category)
            for label, snippet, tooltip in items:
                act = QAction(label, self)
                if tooltip:
                    act.setToolTip(tooltip)
                # snippet is None → полный шаблон (замена документа)
                act.triggered.connect(
                    lambda _checked=False, lbl=label, snip=snippet: self._insert_snippet(lbl, snip)
                )
                submenu.addAction(act)
            submenu.setToolTipsVisible(True)
        self.insert_btn.setMenu(menu)

    def _insert_snippet(self, label: str, snippet) -> None:
        """Вставляет сниппет в позицию курсора, либо заменяет весь документ (шаблон)."""
        if snippet is None:
            # Полный шаблон — заменяем весь документ (с подтверждением если есть текст)
            template = VMT_FULL_TEMPLATES.get(label, "")
            if not template:
                return
            if self.text_edit.toPlainText().strip():
                reply = QMessageBox.question(
                    self,
                    self.t.get('vmt_template_title', 'Apply template'),
                    self.t.get('vmt_template_confirm',
                               'Replace the entire VMT with this template?'),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return
            self.text_edit.setPlainText(template)
            return

        # Обычный сниппет — вставляем в позицию курсора отдельной строкой
        cursor = self.text_edit.textCursor()
        text = snippet
        # Если курсор не в начале строки — переносим вставку на новую строку
        cursor.insertText("\n\t" + text if cursor.columnNumber() > 0 else "\t" + text)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()

    # ── Загрузка контента ─────────────────────────────────────────────────── #

    def _load_content(self) -> None:
        """Загружает контент в редактор."""
        # Временно отключаем трекинг изменений при первоначальной загрузке
        self.text_edit.document().contentsChanged.disconnect(self._on_content_changed)
        self.text_edit.setPlainText(self._orig_content)
        self.text_edit.document().contentsChanged.connect(self._on_content_changed)

        self._modified = False
        self._validate()
        self._update_title()
        self._update_status()

    # ── Обработчики ───────────────────────────────────────────────────────── #

    def _on_content_changed(self) -> None:
        self._modified = True
        self._validate()
        self._update_title()
        self._update_status()

    def _validate(self) -> None:
        """Проверяет синтаксис и блокирует Save при ошибке."""
        content = self.text_edit.toPlainText()
        self._is_valid, self._error_msg, self._error_line = VMTService.validate_vmt_syntax(content)
        self.save_btn.setEnabled(self._is_valid)

    def _update_title(self) -> None:
        marker = " *" if self._modified else ""
        self.setWindowTitle(f"VMT Editor — {self._display}{marker}")

    def _update_status(self) -> None:
        # Ошибка синтаксиса имеет приоритет — это защита от «невидимого материала»
        if not self._is_valid:
            loc = f' ({self.t.get("vmt_line", "line")} {self._error_line})' if self._error_line else ''
            self._status_label.setText(f'✗ {self._error_msg}{loc}')
            self._status_label.setStyleSheet("color: #d05050; font-size: 11px; font-weight: 600;")
            return

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
        # Защита: не сохраняем синтаксически сломанный VMT (иначе материал
        # станет невидимым в игре). Кнопка и так задизейблена, но Ctrl+S и
        # прочие пути обходим этой проверкой.
        if not self._is_valid:
            loc = f' ({self.t.get("vmt_line", "line")} {self._error_line})' if self._error_line else ''
            QMessageBox.warning(
                self,
                self.t.get('vmt_invalid_title', 'Invalid VMT'),
                self.t.get('vmt_invalid_msg',
                           'The VMT has a syntax error and cannot be saved:')
                + f'\n\n✗ {self._error_msg}{loc}',
            )
            return False

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
        return True

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
                # Если VMT невалиден, _save вернёт False → не закрываем окно,
                # чтобы пользователь не потерял правки.
                if not self._save():
                    event.ignore()
                    return
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
