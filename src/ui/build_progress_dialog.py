"""
Кастомное окно прогресса сборки VPK — адаптируется под выбранную тему.
Два прогресс-бара: общий и пошаговый (с pulse-режимом для внешних процессов).
"""

import random
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QLinearGradient
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QSizePolicy, QFrame,
)

from src.config.app_config import AppConfig


# ---------------------------------------------------------------------------
# TF2 фразы (RU / EN)
# ---------------------------------------------------------------------------

_PHRASES_RU = [
    "Ищем шпиона...",
    "Толкаем вагонетку...",
    "Декомпилируем .MDL...",
    "Готовим VTF текстуру...",
    "Строим укрепление...",
    "Обновляем сентри...",
    "Упаковываем VPK...",
    "Ищем разведчика...",
    "Заряжаем убер...",
    "Патчим QC файл...",
    "Собираем разведданные...",
    "Настраиваем прицел...",
    "Копируем SMD файлы...",
    "Компилируем через studiomdl...",
    "Помогаем Инженеру...",
    "Считаем патроны...",
    "Набираем критхиты...",
]

_PHRASES_EN = [
    "Looking for the Spy...",
    "Pushing the cart...",
    "Decompiling .MDL...",
    "Cooking the VTF texture...",
    "Building the sentry...",
    "Upgrading sentry...",
    "Packing the VPK...",
    "Finding the Scout...",
    "Charging the UberCharge...",
    "Patching the QC file...",
    "Gathering intelligence...",
    "Adjusting crosshair...",
    "Copying SMD files...",
    "Compiling with studiomdl...",
    "Helping the Engineer...",
    "Counting bullets...",
    "Stacking crits...",
]


# ---------------------------------------------------------------------------
# Цвета тем
# ---------------------------------------------------------------------------

def _theme_colors(theme: str) -> dict:
    if theme == 'blue':
        return {
            'bg':           '#0d1b2a',
            'bg_track':     '#162233',
            'border':       '#2a3f58',
            'separator':    '#1e3248',
            'text':         '#e0e1dd',
            'dim':          '#6b8099',
            'accent_start': QColor(30, 80, 170),
            'accent_mid':   QColor(50, 120, 210),
            'accent_end':   QColor(74, 144, 226),
            'glow':         QColor(100, 160, 255, 55),
            # Второй бар чуть тусклее
            'sub_start':    QColor(25, 60, 130),
            'sub_mid':      QColor(40, 95, 170),
            'sub_end':      QColor(60, 120, 200),
            'sub_glow':     QColor(80, 130, 220, 40),
        }
    return {
        'bg':           '#0a0a0a',
        'bg_track':     '#141414',
        'border':       '#1e1e1e',
        'separator':    '#181818',
        'text':         '#ffffff',
        'dim':          '#555555',
        'accent_start': QColor(180, 70, 20),
        'accent_mid':   QColor(230, 100, 30),
        'accent_end':   QColor(255, 140, 50),
        'glow':         QColor(255, 255, 255, 50),
        'sub_start':    QColor(130, 50, 15),
        'sub_mid':      QColor(170, 75, 22),
        'sub_end':      QColor(200, 105, 40),
        'sub_glow':     QColor(255, 200, 150, 35),
    }


# ---------------------------------------------------------------------------
# Прогресс-бар с поддержкой pulse-режима
# ---------------------------------------------------------------------------

class _AnimatedBar(QWidget):
    """
    Прогресс-бар с анимацией.

    value = 0..100  → обычный заполненный бар
    value = -1      → indeterminate: скользящий pulse (для внешних процессов)
    """

    def __init__(self, colors: dict, use_sub_colors: bool = False, parent=None):
        super().__init__(parent)
        self._colors = colors
        self._use_sub = use_sub_colors
        self._value = 0
        self._phase = 0.0          # 0..1, для glow на обычном баре
        self._pulse_pos = 0.0      # 0..1, для pulse в indeterminate-режиме
        self.setFixedHeight(3)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)      # ~60 fps

    def setValue(self, v: int) -> None:
        """v = 0..100 или -1 для indeterminate."""
        self._value = v
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.035) % 1.0
        if self._value == -1:
            self._pulse_pos = (self._pulse_pos + 0.018) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._colors

        w, h = self.width(), self.height()
        r = h / 2

        # Трек
        p.setBrush(QColor(c['bg_track']))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)

        if self._value == -1:
            # --- Pulse (indeterminate) ---
            seg_w = int(w * 0.35)
            # Позиция центра сегмента: скользит от -seg_w до w+seg_w
            center = int((self._pulse_pos * (w + seg_w * 2)) - seg_w)
            x0 = max(0, center - seg_w // 2)
            x1 = min(w, center + seg_w // 2)
            if x1 > x0:
                sk = 'sub_start' if self._use_sub else 'accent_start'
                em = 'sub_end'   if self._use_sub else 'accent_end'
                grad = QLinearGradient(x0, 0, x1, 0)
                grad.setColorAt(0.0, QColor(c[sk].red(), c[sk].green(), c[sk].blue(), 0))
                grad.setColorAt(0.5, c['sub_mid' if self._use_sub else 'accent_mid'])
                grad.setColorAt(1.0, QColor(c[em].red(), c[em].green(), c[em].blue(), 0))
                p.setBrush(grad)
                p.drawRoundedRect(x0, 0, x1 - x0, h, r, r)
        else:
            # --- Обычный заполненный бар ---
            filled_w = int(w * max(0, self._value) / 100)
            if filled_w > 0:
                sk = 'sub_start' if self._use_sub else 'accent_start'
                sm = 'sub_mid'   if self._use_sub else 'accent_mid'
                se = 'sub_end'   if self._use_sub else 'accent_end'
                sg = 'sub_glow'  if self._use_sub else 'glow'

                grad = QLinearGradient(0, 0, filled_w, 0)
                grad.setColorAt(0.0, c[sk])
                grad.setColorAt(0.5, c[sm])
                grad.setColorAt(1.0, c[se])
                p.setBrush(grad)
                p.drawRoundedRect(0, 0, filled_w, h, r, r)

                # Скользящий блик
                gx = int(filled_w * self._phase)
                glow = QLinearGradient(gx - 40, 0, gx + 40, 0)
                glow.setColorAt(0.0, QColor(255, 255, 255, 0))
                glow.setColorAt(0.5, c[sg])
                glow.setColorAt(1.0, QColor(255, 255, 255, 0))
                p.setBrush(glow)
                p.drawRoundedRect(0, 0, filled_w, h, r, r)

        p.end()


# ---------------------------------------------------------------------------
# Диалог прогресса
# ---------------------------------------------------------------------------

class BuildProgressDialog(QDialog):
    """
    Диалог прогресса сборки с двумя прогресс-барами:
      - верхний  : общий прогресс (0..100 %)
      - нижний   : пошаговый (0..100 % или -1 = indeterminate pulse)

    Сигналы:
        cancel_requested — пользователь нажал «Отмена»
    """

    cancel_requested = Signal()

    def __init__(self, parent=None, language: str = "en"):
        super().__init__(parent)
        self._language = language
        self._phrases = _PHRASES_RU if language == "ru" else _PHRASES_EN
        self._phrase_pool = list(self._phrases)
        random.shuffle(self._phrase_pool)
        self._phrase_idx = 0
        self._cancelled = False

        config = AppConfig.load_config()
        self._colors = _theme_colors(config.get('theme', 'dark'))

        self._setup_ui()
        self._setup_timers()

    def _setup_ui(self) -> None:
        c = self._colors
        self.setWindowTitle("TF2 Skin Generator")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedSize(460, 256)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
            }}
            QLabel {{
                background-color: transparent;
            }}
            QLabel#title {{
                color: {c['dim']};
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 3px;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            }}
            QLabel#phrase {{
                color: {c['dim']};
                font-size: 11px;
                font-weight: 300;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
                font-style: italic;
            }}
            QLabel#status {{
                color: {c['text']};
                font-size: 13px;
                font-weight: 400;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            }}
            QLabel#percent {{
                color: {c['dim']};
                font-size: 10px;
                font-weight: 400;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            }}
            QLabel#sub_label {{
                color: {c['dim']};
                font-size: 10px;
                font-weight: 400;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            }}
            QLabel#sub_pct {{
                color: {c['dim']};
                font-size: 10px;
                font-weight: 400;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            }}
            QFrame#separator {{
                background-color: {c['separator']};
                border: none;
                max-height: 1px;
            }}
            QPushButton#cancel_btn {{
                background-color: transparent;
                color: {c['dim']};
                border: none;
                padding: 4px 0px;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1px;
                font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            }}
            QPushButton#cancel_btn:hover {{
                color: {c['text']};
            }}
            QPushButton#cancel_btn:disabled {{
                color: {c['border']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 20)
        root.setSpacing(0)

        # -- Заголовок --
        title_text = "СБОРКА VPK" if self._language == "ru" else "BUILD VPK"
        lbl = QLabel(title_text)
        lbl.setObjectName("title")
        root.addWidget(lbl)

        root.addSpacing(12)

        # -- Статус --
        self._status_label = QLabel("...")
        self._status_label.setObjectName("status")
        root.addWidget(self._status_label)

        root.addSpacing(4)

        # -- Весёлая фраза --
        self._phrase_label = QLabel(self._current_phrase())
        self._phrase_label.setObjectName("phrase")
        self._phrase_label.setWordWrap(True)
        root.addWidget(self._phrase_label)

        root.addSpacing(14)

        # -- Общий прогресс-бар --
        overall_row = QHBoxLayout()
        overall_row.setSpacing(10)
        self._bar = _AnimatedBar(self._colors, use_sub_colors=False)
        overall_row.addWidget(self._bar, 1)
        self._percent_label = QLabel("0%")
        self._percent_label.setObjectName("percent")
        self._percent_label.setFixedWidth(28)
        self._percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        overall_row.addWidget(self._percent_label)
        root.addLayout(overall_row)

        root.addSpacing(16)

        # -- Разделитель --
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        root.addSpacing(12)

        # -- Подпись шага + пошаговый прогресс --
        sub_header = QHBoxLayout()
        sub_header.setSpacing(0)
        self._sub_label = QLabel("—")
        self._sub_label.setObjectName("sub_label")
        sub_header.addWidget(self._sub_label, 1)
        self._sub_pct_label = QLabel("")
        self._sub_pct_label.setObjectName("sub_pct")
        self._sub_pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sub_header.addWidget(self._sub_pct_label)
        root.addLayout(sub_header)

        root.addSpacing(6)

        # -- Пошаговый прогресс-бар (pulse по умолчанию) --
        self._sub_bar = _AnimatedBar(self._colors, use_sub_colors=True)
        self._sub_bar.setValue(-1)
        root.addWidget(self._sub_bar)

        root.addSpacing(16)

        # -- Кнопка отмены --
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_text = "ОТМЕНА" if self._language == "ru" else "CANCEL"
        self._cancel_btn = QPushButton(cancel_text)
        self._cancel_btn.setObjectName("cancel_btn")
        self._cancel_btn.setFocusPolicy(Qt.NoFocus)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

    def _setup_timers(self) -> None:
        self._phrase_timer = QTimer(self)
        self._phrase_timer.timeout.connect(self._rotate_phrase)
        self._phrase_timer.start(3000)

    def _current_phrase(self) -> str:
        if not self._phrase_pool:
            self._phrase_pool = list(self._phrases)
            random.shuffle(self._phrase_pool)
            self._phrase_idx = 0
        phrase = self._phrase_pool[self._phrase_idx % len(self._phrase_pool)]
        self._phrase_idx += 1
        return phrase

    def _rotate_phrase(self) -> None:
        if not self._cancelled:
            self._phrase_label.setText(self._current_phrase())

    # --- Публичный API ---

    def setValue(self, value: int) -> None:
        """Обновляет общий прогресс-бар."""
        self._bar.setValue(value)
        self._percent_label.setText(f"{value}%")

    def setLabelText(self, text: str) -> None:
        """Обновляет строку основного статуса."""
        self._status_label.setText(text)

    def set_sub_progress(self, value: int, label: str) -> None:
        """
        Обновляет пошаговый прогресс.

        Args:
            value: 0..100 — реальный прогресс; -1 — indeterminate (pulse)
            label: текст под разделителем (название шага / «X / Y строк»)
        """
        self._sub_bar.setValue(value)
        self._sub_label.setText(label)
        if value < 0:
            self._sub_pct_label.setText("")
        else:
            self._sub_pct_label.setText(f"{value}%")

    def _on_cancel_clicked(self) -> None:
        if not self._cancelled:
            self._cancelled = True
            self._cancel_btn.setEnabled(False)
            cancel_text = "Отменяем..." if self._language == "ru" else "Cancelling..."
            self._status_label.setText(cancel_text)
            self._phrase_label.setText(cancel_text)
            self.cancel_requested.emit()

    def mark_cancelling(self) -> None:
        """Вызывается снаружи когда отмена уже запущена."""
        self._on_cancel_clicked()

    def closeEvent(self, event) -> None:
        self._phrase_timer.stop()
        super().closeEvent(event)
