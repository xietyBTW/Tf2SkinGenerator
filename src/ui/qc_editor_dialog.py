"""
Редактор QC для «готовой» кастомной модели.

Показывает ИСПРАВЛЕННЫЙ QC (как его получит компилятор: пути под console\\, без
$lod, с актуальным $texturegroup). Важные для сборки блоки изначально ЗАКРЫТЫ
(нарисованный замок, read-only). Нажав на замок, пользователь открывает блок для
правки. Жёсткого разделения «можно/нельзя» нет — всё под ответственностью юзера.
"""

from typing import List, Dict, Tuple, Set

from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QSize
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QTextFormat
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QWidget, QTextEdit,
)

# Директивы, чьи блоки важны для сборки → по умолчанию заблокированы.
LOCK_DIRECTIVES = (
    '$modelname', '$cdmaterials', '$texturegroup', '$body', '$model',
    '$bodygroup', '$sequence', '$definebone', '$collisionmodel',
    '$collisionjoints', '$lod', '$shadowlod',
)

# Модифицирующие текст клавиши (для проверки защиты).
_EDIT_KEYS = None  # заполняется лениво из Qt


class _LockGutter(QWidget):
    """Полоса слева с замочками напротив защищённых блоков."""

    def __init__(self, editor: 'QCLockEdit'):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.lock_area_width(), 0)

    def paintEvent(self, event):
        self._editor.lock_area_paint(event)

    def mousePressEvent(self, event):
        self._editor.lock_area_click(event.position().toPoint().y())


class QCLockEdit(QPlainTextEdit):
    """QPlainTextEdit с защитой строк по блокам директив и замочками в желобе."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gutter = _LockGutter(self)
        # Разблокированные блоки: ключ (директива, порядковый номер вхождения).
        self._unlocked: Set[Tuple[str, int]] = set()
        self._blocks: List[Dict] = []   # кэш разбора защищённых блоков

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._on_update_request)
        self.textChanged.connect(self._reparse_and_highlight)
        self._update_gutter_width()
        self._reparse_and_highlight()

    # ── Разбор защищённых блоков ─────────────────────────────────────────── #

    def _scan_blocks(self) -> List[Dict]:
        """Находит защищённые блоки: (директива, occ, first_line, last_line)."""
        lines = self.toPlainText().split('\n')
        n = len(lines)
        blocks: List[Dict] = []
        occ: Dict[str, int] = {}
        i = 0
        while i < n:
            stripped = lines[i].strip()
            token = stripped.split(None, 1)[0].lower() if stripped else ''
            if token in LOCK_DIRECTIVES:
                first = i
                # Есть ли скобочный блок?
                has_block = '{' in lines[i]
                k = i + 1
                while not has_block and k < n:
                    nxt = lines[k].strip()
                    if not nxt:
                        k += 1
                        continue
                    if nxt.startswith('{'):
                        has_block = True
                    break
                if has_block:
                    depth = 0
                    seen_open = False
                    j = i
                    while j < n:
                        depth += lines[j].count('{') - lines[j].count('}')
                        if '{' in lines[j]:
                            seen_open = True
                        if seen_open and depth <= 0:
                            break
                        j += 1
                    last = min(j, n - 1)
                else:
                    last = i
                o = occ.get(token, 0)
                occ[token] = o + 1
                blocks.append({'dir': token, 'occ': o, 'first': first, 'last': last})
                i = last + 1
            else:
                i += 1
        return blocks

    def _reparse_and_highlight(self) -> None:
        self._blocks = self._scan_blocks()
        self._apply_highlight()
        self._gutter.update()

    def locked_line_numbers(self) -> Set[int]:
        result: Set[int] = set()
        for b in self._blocks:
            if (b['dir'], b['occ']) in self._unlocked:
                continue
            result.update(range(b['first'], b['last'] + 1))
        return result

    def _apply_highlight(self) -> None:
        """Подсветка: закрытые блоки — приглушённый фон, открытые — зеленоватый."""
        extra = []
        doc = self.document()
        for b in self._blocks:
            opened = (b['dir'], b['occ']) in self._unlocked
            color = QColor(40, 70, 40) if opened else QColor(35, 35, 35)
            for ln in range(b['first'], b['last'] + 1):
                blk = doc.findBlockByNumber(ln)
                if not blk.isValid():
                    continue
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(color)
                sel.format.setProperty(QTextFormat.FullWidthSelection, True)
                cur = self.textCursor()
                cur.setPosition(blk.position())
                sel.cursor = cur
                extra.append(sel)
        self.setExtraSelections(extra)

    # ── Желоб с замочками ────────────────────────────────────────────────── #

    def lock_area_width(self) -> int:
        return 22

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.lock_area_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.lock_area_width(), cr.height()))

    def lock_area_paint(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(24, 24, 24))
        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        first_lines = {b['first']: ((b['dir'], b['occ']) in self._unlocked) for b in self._blocks}
        line_h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and block_num in first_lines:
                opened = first_lines[block_num]
                color = QColor(120, 200, 120) if opened else QColor(150, 150, 150)
                cx = self.lock_area_width() / 2.0
                cy = top + line_h / 2.0
                self._paint_lock(painter, cx, cy, opened, color)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_num += 1

    @staticmethod
    def _paint_lock(painter: QPainter, cx: float, cy: float,
                    opened: bool, color: QColor) -> None:
        """Рисует аккуратный замок (закрытый/открытый) ~11px в точке (cx, cy)."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(color)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.RoundCap)

        bw, bh = 9.0, 6.5
        bx = cx - bw / 2.0
        by = cy - 0.5          # верх корпуса
        r = 2.6                # радиус дужки
        # ── дужка ──
        painter.setBrush(Qt.NoBrush)
        painter.setPen(pen)
        if opened:
            # открыто: дужка приподнята, правая ножка отстёгнута
            top_cy = by - r - 2.0
            painter.drawArc(QRectF(cx - r - 1.0, top_cy - r, 2 * r, 2 * r), 30 * 16, 200 * 16)
            painter.drawLine(QPointF(cx - r - 1.0, top_cy), QPointF(cx - r - 1.0, by))
        else:
            # закрыто: подкова сверху, обе ножки к корпусу
            top_cy = by - r - 1.0
            painter.drawArc(QRectF(cx - r, top_cy - r, 2 * r, 2 * r), 0, 180 * 16)
            painter.drawLine(QPointF(cx - r, top_cy), QPointF(cx - r, by))
            painter.drawLine(QPointF(cx + r, top_cy), QPointF(cx + r, by))
        # ── корпус ──
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 1.6, 1.6)
        painter.restore()

    def lock_area_click(self, y: int) -> None:
        """Клик по желобу: переключаем замок ближайшего блока на этой строке."""
        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        while block.isValid():
            if block.isVisible() and top <= y <= bottom:
                for b in self._blocks:
                    if b['first'] == block_num:
                        key = (b['dir'], b['occ'])
                        if key in self._unlocked:
                            self._unlocked.discard(key)
                        else:
                            self._unlocked.add(key)
                        self._reparse_and_highlight()
                        return
                return
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_num += 1

    # ── Защита от правки закрытых блоков ─────────────────────────────────── #

    def _edit_blocked(self, is_backspace: bool, is_delete: bool) -> bool:
        locked = self.locked_line_numbers()
        if not locked:
            return False
        cur = self.textCursor()
        if cur.hasSelection():
            a = self.document().findBlock(cur.selectionStart()).blockNumber()
            b = self.document().findBlock(cur.selectionEnd()).blockNumber()
            return any(ln in locked for ln in range(a, b + 1))
        line = cur.blockNumber()
        if line in locked:
            return True
        # Backspace в начале строки сливает с предыдущей; Delete в конце — со следующей.
        if is_backspace and cur.positionInBlock() == 0 and (line - 1) in locked:
            return True
        if is_delete and cur.atBlockEnd() and (line + 1) in locked:
            return True
        return False

    def keyPressEvent(self, event):
        from PySide6.QtGui import QKeySequence
        key = event.key()
        is_backspace = key == Qt.Key_Backspace
        is_delete = key == Qt.Key_Delete
        # Модифицирующие действия: ввод текста, удаление, вставка, вырезание.
        modifies = (
            is_backspace or is_delete
            or event.matches(QKeySequence.Paste)
            or event.matches(QKeySequence.Cut)
            or (event.text() and event.text().isprintable())
            or key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab)
        )
        if modifies and self._edit_blocked(is_backspace, is_delete):
            return  # блок закрыт — игнорируем правку
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        if self._edit_blocked(False, False):
            return
        super().insertFromMimeData(source)


class QCEditorDialog(QDialog):
    """Диалог редактирования исправленного QC с замочками на важных блоках."""

    def __init__(self, qc_text: str, lang: str = 'en', parent=None):
        super().__init__(parent)
        ru = (lang == 'ru')
        self.setWindowTitle('Редактор QC' if ru else 'QC Editor')
        self.resize(760, 680)
        self.setStyleSheet("QDialog { background:#1b1b1b; } QLabel { color:#ccc; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        hint = QLabel(
            'Важные для сборки блоки закрыты (значок замка слева). Нажми на замок, '
            'чтобы открыть блок для правки. $texturegroup управляется стилями и '
            'пересобирается автоматически.'
            if ru else
            'Build-critical blocks are locked (lock icon on the left). Click a lock '
            'to open a block for editing. $texturegroup is style-managed and '
            'auto-synced.'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#999; font-size:11px;")
        lay.addWidget(hint)

        self._edit = QCLockEdit()
        mono = QFont('Consolas')
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)
        self._edit.setFont(mono)
        self._edit.setStyleSheet(
            "QPlainTextEdit { background:#141414; color:#ddd; border:1px solid #333;"
            " border-radius:4px; }"
        )
        self._edit.setPlainText(qc_text or '')
        lay.addWidget(self._edit, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        reset = QPushButton('Сбросить к исходному' if ru else 'Reset to default')
        reset.clicked.connect(lambda: self.done(2))   # код 2 = сброс
        cancel = QPushButton('Отмена' if ru else 'Cancel')
        cancel.clicked.connect(self.reject)
        save = QPushButton('Сохранить' if ru else 'Save')
        save.setDefault(True)
        save.clicked.connect(self.accept)
        for b in (reset, cancel):
            b.setStyleSheet(
                "QPushButton { background:#2a2a2a; color:#ccc; border:1px solid #444;"
                " border-radius:4px; padding:6px 16px; } QPushButton:hover { border-color:#666; }"
            )
        save.setStyleSheet(
            "QPushButton { background:#2d4a2d; color:#dfe; border:1px solid #3a6a3a;"
            " border-radius:4px; padding:6px 18px; } QPushButton:hover { border-color:#4a8a4a; }"
        )
        btns.addWidget(reset)
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)

    def get_text(self) -> str:
        return self._edit.toPlainText()
