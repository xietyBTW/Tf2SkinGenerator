"""
Панель настроек - Минималистичный дизайн
"""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QLineEdit, QRadioButton, QCheckBox, QButtonGroup,
    QWidget, QSizePolicy, QFileDialog, QFrame, QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QPoint, QRect
from PySide6.QtGui import QDoubleValidator, QMouseEvent
from src.data.translations import TRANSLATIONS
from src.utils.themes import get_modern_styles
from src.config.app_config import AppConfig


class UVLayoutCheckBox(QCheckBox):
    """Чекбокс UV разметки, который блокирует включение при активном CritHIT режиме"""
    
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.parent_panel = None
        self._force_disable = False  # Флаг для принудительного отключения
    
    def set_parent_panel(self, panel) -> None:
        """Устанавливает ссылку на панель настроек для проверки состояния CritHIT"""
        self.parent_panel = panel
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Перехватывает клик мыши и проверяет, можно ли изменить состояние чекбокса"""
        if event.button() == Qt.LeftButton:
            # Проверяем состояние CritHIT через панель настроек
            is_crit_hit = False
            if self.parent_panel and self.parent_panel.parent:
                if hasattr(self.parent_panel.parent, 'crit_hit_checkbox'):
                    is_crit_hit = self.parent_panel.parent.crit_hit_checkbox.isChecked()
            
            # Если CritHIT включен, блокируем любое изменение состояния
            if is_crit_hit:
                # Не вызываем super(), чтобы предотвратить изменение состояния
                return
            
            # Если CritHIT не включен, разрешаем обычное поведение
            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)
    
    def setChecked(self, checked: bool) -> None:
        """Переопределяем setChecked, чтобы блокировать включение при CritHIT"""
        # Если установлен флаг принудительного изменения, пропускаем все проверки
        if self._force_disable:
            self._force_disable = False
            super().setChecked(checked)
            return
        
        # Если пытаются включить чекбокс, проверяем CritHIT
        if checked:
            is_crit_hit = False
            if self.parent_panel and self.parent_panel.parent:
                if hasattr(self.parent_panel.parent, 'crit_hit_checkbox'):
                    is_crit_hit = self.parent_panel.parent.crit_hit_checkbox.isChecked()
            
            # Если CritHIT включен, не позволяем включить чекбокс
            if is_crit_hit:
                return
        
        # Разрешаем изменение состояния (включая отключение)
        super().setChecked(checked)
    
    def force_set_checked(self, checked: bool) -> None:
        """Принудительно устанавливает состояние чекбокса, игнорируя проверки CritHIT"""
        # Напрямую вызываем setChecked базового класса, минуя наш переопределенный метод
        QCheckBox.setChecked(self, checked)


class CollapsibleGroup(QWidget):
    """Collapsible group для accordion"""
    toggled = Signal(bool)  # Сигнал при сворачивании/разворачивании
    
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setup_ui(title)
        self.is_expanded = False
        
    def setup_ui(self, title):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Кнопка заголовка
        self.toggle_button = QPushButton(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        self.toggle_button.setMinimumWidth(0)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 12px 16px;
                font-size: 13px;
                font-weight: 500;
                color: #ccc;
                background-color: transparent;
                border: none;
                border-bottom: 1px solid #333;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.03);
            }
            QPushButton::indicator {
                width: 0px;
            }
        """)
        self.toggle_button.clicked.connect(self.toggle)
        layout.addWidget(self.toggle_button)
        
        # Контент
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(16, 12, 16, 12)
        self.content_layout.setSpacing(12)
        # Устанавливаем размерную политику для контента, чтобы он не растягивался
        self.content_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # При инициализации контент скрыт - устанавливаем максимальную высоту в 0
        # Это гарантирует, что виджет не займет места в layout
        self.content_widget.setMaximumHeight(0)
        self.content_widget.setMinimumHeight(0)
        layout.addWidget(self.content_widget)
        
    def toggle(self):
        self.is_expanded = not self.is_expanded
        
        # Обновляем текст кнопки
        text = self.toggle_button.text()
        if self.is_expanded:
            self.toggle_button.setText(text.replace("▶", "▼"))
        else:
            self.toggle_button.setText(text.replace("▼", "▶"))
        
        # Обновляем видимость контента
        if not self.is_expanded:
            self.content_widget.setMaximumHeight(0)
            self.content_widget.setMinimumHeight(0)
        else:
            self.content_widget.setMaximumHeight(999999)
            self.content_widget.setMinimumHeight(0)
            self.content_widget.adjustSize()
        
        # Обновляем размер самого accordion
        self.adjustSize()
        self.updateGeometry()
        
        # Испускаем сигнал об изменении состояния
        self.toggled.emit(self.is_expanded)
    
    def addWidget(self, widget):
        self.content_layout.addWidget(widget)
    
    def addLayout(self, layout):
        self.content_layout.addLayout(layout)

_BUILD_OPTS_BTN_IDLE = """
    QPushButton {
        background-color: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 3px;
        padding: 0px;
        min-width: 0px;
    }
    QPushButton:hover {
        background-color: rgba(255, 255, 255, 0.14);
        border-color: rgba(255, 255, 255, 0.28);
    }
    QPushButton:pressed {
        background-color: rgba(0, 0, 0, 0.20);
    }
"""

_BUILD_OPTS_BTN_ACTIVE = """
    QPushButton {
        background-color: rgba(255, 255, 255, 0.22);
        border: 1px solid rgba(255, 255, 255, 0.60);
        border-radius: 3px;
        padding: 0px;
        min-width: 0px;
    }
    QPushButton:hover {
        background-color: rgba(255, 255, 255, 0.35);
        border-color: rgba(255, 255, 255, 0.90);
    }
    QPushButton:pressed {
        background-color: rgba(255, 255, 255, 0.12);
    }
"""


def _make_build_opts_icon(color: str = "#c0c0c0", size: int = 11):
    """Рисует шестерёнку для кнопки опций сборки (аналог _make_gear_icon из main_window)."""
    import math
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPainterPath
    from PySide6.QtCore import Qt, QRectF

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))

    s = float(size)
    cx = cy = s / 2.0
    n_teeth = 6
    r_outer = s * 0.455
    r_base  = s * 0.305
    r_hole  = s * 0.150
    half_tw = 0.285
    step    = 2.0 * math.pi / n_teeth

    path  = QPainterPath()
    first = True
    for i in range(n_teeth):
        center = i * step - math.pi / 2.0
        for r, da in [
            (r_base,  -(half_tw + 0.18)),
            (r_outer, -half_tw * 0.52),
            (r_outer,  half_tw * 0.52),
            (r_base,   (half_tw + 0.18)),
        ]:
            x = cx + r * math.cos(center + da)
            y = cy + r * math.sin(center + da)
            if first:
                path.moveTo(x, y); first = False
            else:
                path.lineTo(x, y)
    path.closeSubpath()

    hole = QPainterPath()
    hole.addEllipse(QRectF(cx - r_hole, cy - r_hole, r_hole * 2, r_hole * 2))
    p.drawPath(path.subtracted(hole))
    p.end()
    return QIcon(pix)


class _BuildOptsPopup(QFrame):
    """
    Всплывающий виджет с опциями сборки.
    Закрывается по клику в любое место ВНЕ виджета через eventFilter на QApplication.
    Остаётся открытым при взаимодействии с чекбоксами внутри.
    Создаётся ОДИН РАЗ и переиспользуется (toggle show/hide).
    """

    def __init__(self, panel: "SettingsPanel") -> None:
        # Qt.Tool | Qt.FramelessWindowHint — без рамки, без taskbar
        super().__init__(panel.window(), Qt.Tool | Qt.FramelessWindowHint)
        self._panel = panel
        self.setObjectName("buildOptsFrame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QFrame#buildOptsFrame {
                background-color: #161616;
                border: 1px solid #2e2e2e;
                border-radius: 6px;
            }
            QCheckBox {
                color: #ccc;
                font-size: 13px;
                spacing: 8px;
                padding: 3px 0px;
                background: transparent;
            }
            QCheckBox:hover { color: #fff; }
            QCheckBox::indicator {
                width: 15px; height: 15px;
                border: 1px solid #444;
                border-radius: 3px;
                background: #1e1e1e;
            }
            QCheckBox::indicator:checked {
                background: #ff6b35;
                border-color: #ff6b35;
            }
            QCheckBox::indicator:hover { border-color: #666; }
            QLabel#optsTitle {
                color: #555;
                font-size: 11px;
                font-weight: 600;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Заголовок
        lbl = QLabel(panel.t.get('build_options_title', 'Build options'))
        lbl.setObjectName("optsTitle")
        layout.addWidget(lbl)

        # Разделитель
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { color: #2a2a2a; margin: 2px 0px 4px 0px; }")
        layout.addWidget(sep)

        # Чекбокс: замена модели
        self._cb_replace = QCheckBox(
            panel.t.get('enable_replace_model', 'Enable model replacement')
        )
        self._cb_replace.stateChanged.connect(self._on_replace)
        layout.addWidget(self._cb_replace)

        # Чекбокс: модель уже готова
        self._cb_ready = QCheckBox(
            panel.t.get('model_already_ready', 'Model is already ready')
        )
        self._cb_ready.stateChanged.connect(self._on_ready)
        layout.addWidget(self._cb_ready)

        self.adjustSize()

    def sync_from_panel(self) -> None:
        """Синхронизирует состояние чекбоксов из панели (без эмиссии сигналов)."""
        self._cb_replace.blockSignals(True)
        self._cb_ready.blockSignals(True)
        self._cb_replace.setChecked(self._panel._replace_model_checked)
        self._cb_ready.setChecked(self._panel._model_ready_checked)
        self._cb_replace.blockSignals(False)
        self._cb_ready.blockSignals(False)

    def showEvent(self, event) -> None:
        # Устанавливаем eventFilter чтобы ловить клики вне попапа
        QApplication.instance().installEventFilter(self)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        # Синхронизируем фактическое состояние чекбоксов в панель перед закрытием
        self._panel._replace_model_checked = self._cb_replace.isChecked()
        self._panel._model_ready_checked   = self._cb_ready.isChecked()
        self._panel._refresh_build_opts_btn()
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched, event) -> bool:
        t = event.type()
        # Фильтруем MouseButtonRelease (а не Press), чтобы чекбокс внутри попапа
        # успел обработать полный цикл нажатие→отпускание и эмитировать stateChanged
        # до того, как попап скроется.  Скрытие делаем отложенным (singleShot 0)
        # по той же причине: событие должно дойти до чекбокса раньше hide().
        if t == QEvent.MouseButtonRelease:
            try:
                gpos = event.globalPosition().toPoint()
            except AttributeError:
                gpos = event.globalPos()
            widget_under = QApplication.widgetAt(gpos)
            inside_popup = (
                widget_under is not None and
                (widget_under is self or self.isAncestorOf(widget_under))
            )
            if not inside_popup:
                btn = self._panel.build_opts_btn
                btn_global = btn.mapToGlobal(QPoint(0, 0))
                btn_rect = QRect(btn_global, btn.size())
                if not btn_rect.contains(gpos):
                    # Отложенное скрытие — даём чекбоксу завершить обработку события
                    QTimer.singleShot(0, self.hide)
        elif t == QEvent.Wheel:
            # Скролл страницы сдвигает кнопку, а попап остаётся — закрываем
            self.hide()
        elif t == QEvent.Move and watched is self._panel.window():
            # Окно приложения переместили — попап остался бы висеть на старом месте
            self.hide()
        return False  # не перехватываем событие

    def _on_replace(self, state: int) -> None:
        val = (state == Qt.Checked)
        self._panel._replace_model_checked = val
        self._panel._refresh_build_opts_btn()
        self._panel.replace_model_toggled.emit(val)

    def _on_ready(self, state: int) -> None:
        val = (state == Qt.Checked)
        self._panel._model_ready_checked = val
        self._panel._refresh_build_opts_btn()
        self._panel.model_ready_toggled.emit(val)


class _BuildButtonContainer(QWidget):
    """Контейнер кнопки 'Build VPK' с маленькой кнопкой настроек в правом верхнем углу."""

    _BTN_W = 26
    _BTN_H = 18
    _MARGIN = 5

    def __init__(self, main_btn: "QPushButton", opts_btn: "QPushButton", parent=None):
        super().__init__(parent)
        self._main = main_btn
        self._opts = opts_btn
        main_btn.setParent(self)
        opts_btn.setParent(self)
        opts_btn.raise_()
        self.setSizePolicy(main_btn.sizePolicy())
        self.setMinimumHeight(main_btn.minimumHeight())
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        self._main.setGeometry(0, 0, self.width(), self.height())
        self._opts.setGeometry(self.width() - self._BTN_W, 0, self._BTN_W, self._BTN_H)
        super().resizeEvent(event)

    def sizeHint(self):
        return self._main.sizeHint()


class SettingsPanel(QWidget):
    replace_model_toggled = Signal(bool)
    model_ready_toggled   = Signal(bool)

    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.styles = get_modern_styles()
        # Получаем язык из родителя, если он есть, иначе из конфига
        if parent and hasattr(parent, 't'):
            self.t = parent.t
        else:
            config = AppConfig.load_config()
            current_lang = config.get('language') or 'en'
            self.t = TRANSLATIONS[current_lang]

        # Состояние опций сборки (перенесено из левой панели в меню шестерёнки)
        self._replace_model_checked: bool = False
        self._model_ready_checked: bool   = False
        
        # Пресеты
        self.presets = {
            "Обычный": {
                "resolution": 512,
                "format": "DXT1",
                "flags": []
            },
            "HQ": {
                "resolution": 1024,
                "format": "DXT5",
                "flags": []
            },
            "HUD/иконки": {
                "resolution": 512,
                "format": "RGBA8888",
                "flags": ["NOMIP", "NOLOD"]
            },
            "Neon": {
                "resolution": 1024,
                "format": "DXT5",
                "flags": ["CLAMPS", "CLAMPT", "NOMIP", "NOLOD"]
            }
        }
        
        self.init_ui()
        self.load_config()
        self.setup_connections()
        self.validate_vpk_name()
    
    def init_ui(self):
        """Инициализация UI"""
        # Главный layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Заголовок "Шаг 2: Экспорт"
        # Заголовок "Шаг 2: Экспорт"
        self.step_label = QLabel(self.t['step_2_export'])
        self.step_label.setStyleSheet("""
            font-size: 12px;
            font-weight: 600;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            padding-bottom: 4px;
        """)
        self.step_label.setWordWrap(True)
        self.step_label.setMinimumWidth(0)
        self.step_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_layout.addWidget(self.step_label)
        
        # ПЕРВЫЙ КОНТЕЙНЕР - Основные настройки
        # Minimum по вертикали: не сжимать блок (Maximum давал сжатие в QScrollArea)
        main_settings_container = QWidget()
        main_settings_container.setMinimumWidth(0)
        main_settings_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        main_settings_layout = QVBoxLayout(main_settings_container)
        main_settings_layout.setSpacing(12)
        main_settings_layout.setContentsMargins(0, 0, 0, 0)
        
        # Разрешение
        self.res_label = QLabel(self.t['resolution'])
        self.res_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.res_label.setWordWrap(True)
        self.res_label.setMinimumWidth(0)
        self.res_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.res_label)
        
        self.radio_group = QButtonGroup()
        self.radio_256  = QRadioButton(self.t.get('res_256', '256x256 (Spray)'))
        self.radio_512  = QRadioButton(self.t['res_normal'])
        self.radio_512.setChecked(True)
        self.radio_1024 = QRadioButton(self.t['res_high'])
        self.radio_2048 = QRadioButton(self.t.get('res_ultra', '2048x2048 (Ultra)'))

        self.radio_group.addButton(self.radio_256)
        self.radio_group.addButton(self.radio_512)
        self.radio_group.addButton(self.radio_1024)
        self.radio_group.addButton(self.radio_2048)

        # 2×2 сетка: 256/512 в первой строке, 1024/2048 во второй
        res_layout = QGridLayout()
        res_layout.setHorizontalSpacing(8)
        res_layout.setVerticalSpacing(6)
        res_layout.addWidget(self.radio_256,  0, 0)
        res_layout.addWidget(self.radio_512,  0, 1)
        res_layout.addWidget(self.radio_1024, 1, 0)
        res_layout.addWidget(self.radio_2048, 1, 1)
        main_settings_layout.addLayout(res_layout)
        
        # Формат VTF
        self.format_label = QLabel(self.t['format_vtf'])
        self.format_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.format_label.setWordWrap(True)
        self.format_label.setMinimumWidth(0)
        self.format_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.format_label)
        
        self.format_combo = QComboBox()
        # Добавляем все поддерживаемые форматы VTF (кроме P8, который не поддерживается)
        self.format_combo.addItems([
            "DXT1",
            "DXT3",
            "DXT5",
            "RGBA8888",
            "ABGR8888",
            "RGB888",
            "BGR888",
            "RGB565",
            "BGR565",
            "I8",
            "IA88",
            "A8",
            "RGB888 Bluescreen",
            "BGR888 Bluescreen",
            "ARGB8888",
            "BGRA8888",
            "BGRX8888",
            "BGRX5551",
            "BGRA4444",
            "DXT1 With One Bit Alpha",
            "BGRA5551",
            "UV88",
            "UVWQ8888",
            "RGBA16161616F",
            "RGBA16161616",
            "UVLX8888"
        ])
        self.format_combo.setStyleSheet(self.styles['combo'])
        self.format_combo.setMinimumWidth(0)
        self.format_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.format_combo)
        
        # Имя VPK
        self.filename_label = QLabel(self.t['filename_vpk'])
        self.filename_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.filename_label.setWordWrap(True)
        self.filename_label.setMinimumWidth(0)
        self.filename_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.filename_label)
        
        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText(self.t['placeholder'])
        self.filename_input.setStyleSheet(self.styles['line_edit'])
        self.filename_input.setMinimumHeight(40)
        self.filename_input.setMinimumWidth(0)
        self.filename_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.filename_input)
        
        # Сообщение об ошибке валидации
        self.filename_error = QLabel("")
        self.filename_error.setStyleSheet("color: #ff4757; font-size: 11px; padding-top: 4px;")
        self.filename_error.hide()
        self.filename_error.setWordWrap(True)
        self.filename_error.setMinimumWidth(0)
        self.filename_error.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.filename_error)
        
        # Primary CTA - Собрать VPK с маленькой кнопкой настроек в правом верхнем углу
        self.button = QPushButton(self.t['build'])
        self.button.setStyleSheet(self.styles['button_primary'])
        self.button.setMinimumHeight(48)
        self.button.setMinimumWidth(0)
        self.button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.build_opts_btn = QPushButton()
        self.build_opts_btn.setIcon(_make_build_opts_icon("#d0d0d0", 11))
        from PySide6.QtCore import QSize as _QSize
        self.build_opts_btn.setIconSize(_QSize(11, 11))
        self.build_opts_btn.setStyleSheet(_BUILD_OPTS_BTN_IDLE)
        self.build_opts_btn.setToolTip(
            self.t.get('build_options_tooltip', 'Build options')
        )
        self.build_opts_btn.clicked.connect(self._show_build_options_menu)

        self._btn_container = _BuildButtonContainer(self.button, self.build_opts_btn)
        main_settings_layout.addWidget(self._btn_container)

        self.extract_model_button = QPushButton(
            self.t.get('extract_model', 'Extract Original Model (SMD)')
        )
        self.extract_model_button.setStyleSheet(self.styles['button_secondary'])
        self.extract_model_button.setMinimumHeight(40)
        self.extract_model_button.setMinimumWidth(0)
        self.extract_model_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.extract_model_button)
        
        # Кнопка извлечения оригинальной текстуры
        self.extract_texture_button = QPushButton(self.t.get('extract_texture', 'Extract Original Texture'))
        self.extract_texture_button.setStyleSheet(self.styles['button_secondary'])
        self.extract_texture_button.setMinimumHeight(40)
        self.extract_texture_button.setMinimumWidth(0)
        self.extract_texture_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.extract_texture_button)
        
        # Кнопка объединения VPK
        self.merge_vpk_button = QPushButton(self.t.get('merge_vpk', 'Сборка в один'))
        self.merge_vpk_button.setStyleSheet(self.styles['button_secondary'])
        self.merge_vpk_button.setMinimumHeight(40)
        self.merge_vpk_button.setMinimumWidth(0)
        self.merge_vpk_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.merge_vpk_button)
        
        # Добавляем первый контейнер в главный layout
        main_layout.addWidget(main_settings_container, 0)
        
        # ВТОРОЙ КОНТЕЙНЕР - Секция "Дополнительно"
        # Уменьшаем отступ сверху, чтобы секция была ближе к кнопке "Собрать VPK"
        advanced_container = QWidget()
        advanced_container.setMinimumWidth(0)
        advanced_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        advanced_container_layout = QVBoxLayout(advanced_container)
        # Устанавливаем отрицательный верхний margin для уменьшения отступа от кнопки
        advanced_container_layout.setContentsMargins(0, -4, 0, 0)
        advanced_container_layout.setSpacing(0)
        
        # Accordion "Дополнительно" в отдельном контейнере
        self.advanced_group = CollapsibleGroup("▶ " + self.t['advanced_title'])
        self.advanced_group.toggle_button.setText("▶ " + self.t['advanced_title'])
        self.advanced_group.setMinimumWidth(0)
        self.advanced_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Устанавливаем минимальную высоту в 0, чтобы при скрытии контента не было проблем
        self.advanced_group.setMinimumHeight(0)
        
        # Флаги VTF - размещаем в два столбца для компактности
        self.flags_label = QLabel(self.t['flags_vtf'])
        self.flags_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.advanced_group.addWidget(self.flags_label)
        
        # Создаем layout для флагов в два столбца
        flags_container = QWidget()
        flags_layout = QVBoxLayout(flags_container)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.setSpacing(8)  # Расстояние между сеткой флагов и строкой гаммы
        
        # Стиль чекбоксов флагов: бордер-индикатор, оранжевая заливка (акцент),
        # подсветка-«чип» при наведении — в едином стиле приложения.
        compact_checkbox_style = """
            QCheckBox {
                color: #bbb;
                font-size: 12px;
                spacing: 8px;
                padding: 6px 8px;
                border-radius: 5px;
                background: transparent;
            }
            QCheckBox:hover {
                color: #fff;
                background: rgba(255, 255, 255, 0.05);
            }
            QCheckBox::indicator {
                width: 15px; height: 15px;
                border: 1px solid #444;
                border-radius: 4px;
                background: #1e1e1e;
            }
            QCheckBox::indicator:hover { border-color: #ff6b35; }
            QCheckBox::indicator:checked {
                background: #ff6b35;
                border-color: #ff6b35;
            }
        """

        # Флаги — аккуратная сетка 2 столбца (выровненные колонки, «воздух»)
        flags_grid = QGridLayout()
        flags_grid.setHorizontalSpacing(10)
        flags_grid.setVerticalSpacing(4)
        flags_grid.setColumnStretch(0, 1)
        flags_grid.setColumnStretch(1, 1)

        self.flag_clamps           = QCheckBox(self.t['clamp_s'])
        self.flag_clampt           = QCheckBox(self.t['clamp_t'])
        self.flag_nomipmaps        = QCheckBox(self.t['no_mipmap'])
        self.flag_nolod            = QCheckBox(self.t['no_lod'])
        self.flag_nominmipmaps     = QCheckBox(self.t.get('no_minimum_mipmap', 'No minimum Mipmap'))
        self.option_normal         = QCheckBox(self.t.get('normal_map', 'Normal Map'))
        self.option_nothumbnail    = QCheckBox(self.t.get('no_thumbnail', 'No Thumbnail'))
        self.option_noreflectivity = QCheckBox(self.t.get('no_reflectivity', 'No Reflectivity'))

        for _i, _cb in enumerate([
            self.flag_clamps, self.flag_clampt,
            self.flag_nomipmaps, self.flag_nolod,
            self.flag_nominmipmaps, self.option_normal,
            self.option_nothumbnail, self.option_noreflectivity,
        ]):
            _cb.setStyleSheet(compact_checkbox_style)
            flags_grid.addWidget(_cb, _i // 2, _i % 2)

        flags_layout.addLayout(flags_grid)
        
        # Gamma Correction - добавляем в тот же контейнер с флагами
        gamma_row = QHBoxLayout()
        gamma_row.setSpacing(6)
        gamma_row.setContentsMargins(0, 0, 0, 0)
        self.option_gamma = QCheckBox(self.t.get('gamma_correction', 'Gamma Correction'))
        self.option_gamma.setStyleSheet(compact_checkbox_style)
        self.gamma_value_input = QLineEdit()
        self.gamma_value_input.setPlaceholderText("2.2")
        self.gamma_value_input.setStyleSheet(self.styles['line_edit'] + " padding: 1px 4px; font-size: 11px;")
        self.gamma_value_input.setMinimumWidth(50)
        self.gamma_value_input.setMaximumWidth(50)
        self.gamma_value_input.setMinimumHeight(20)
        self.gamma_value_input.setMaximumHeight(20)
        # Валидатор для разрешения только цифр и точки (десятичные числа)
        validator = QDoubleValidator(0.1, 10.0, 2, self.gamma_value_input)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.gamma_value_input.setValidator(validator)
        self.gamma_value_input.setEnabled(False)
        self.option_gamma.toggled.connect(lambda checked: self.gamma_value_input.setEnabled(checked))
        gamma_row.addWidget(self.option_gamma)
        gamma_row.addWidget(self.gamma_value_input, alignment=Qt.AlignVCenter)
        gamma_row.addStretch()
        flags_layout.addLayout(gamma_row)
        
        self.advanced_group.addWidget(flags_container)
        
        # UV разметка
        uv_layout_row = QHBoxLayout()
        uv_layout_row.setSpacing(6)
        uv_layout_row.setContentsMargins(0, 0, 0, 0)
        self.uv_layout_checkbox = UVLayoutCheckBox(self.t.get('draw_uv_layout', 'Нарисовать UV разметку'))
        self.uv_layout_checkbox.set_parent_panel(self)
        self.uv_layout_checkbox.setStyleSheet(compact_checkbox_style)
        self.uv_resolution_label = QLabel("(512x512)")
        self.uv_resolution_label.setStyleSheet("font-size: 11px; color: #999; padding: 0px;")
        uv_layout_row.addWidget(self.uv_layout_checkbox)
        uv_layout_row.addWidget(self.uv_resolution_label)
        uv_layout_row.addStretch()
        self.uv_layout_widget = QWidget()  # Сохраняем ссылку для скрытия/показа
        self.uv_layout_widget.setLayout(uv_layout_row)
        self.advanced_group.addWidget(self.uv_layout_widget)
        
        # Обновляем разрешение UV при изменении разрешения текстуры
        self.radio_256.toggled.connect(self._update_uv_resolution_label)
        self.radio_512.toggled.connect(self._update_uv_resolution_label)
        self.radio_1024.toggled.connect(self._update_uv_resolution_label)
        self.radio_2048.toggled.connect(self._update_uv_resolution_label)
        
        # Инструменты
        self.tools_label = QLabel(self.t['tools'])
        self.tools_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 12px;")
        self.advanced_group.addWidget(self.tools_label)
        
        # Кнопка редактора VMT
        self.expert_button = QPushButton(self.t['open_editor'])
        self.expert_button.setStyleSheet(self.styles['button_secondary'])
        self.expert_button.setMinimumHeight(36)
        self.expert_button.setMinimumWidth(0)
        self.expert_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.advanced_group.addWidget(self.expert_button)
        
        # Кнопка очистки кэша декомпилированных моделей
        self.clear_cache_button = QPushButton(self.t.get('clear_decompile_cache', 'Clear Model Cache'))
        self.clear_cache_button.setStyleSheet(self.styles['button_secondary'])
        self.clear_cache_button.setMinimumHeight(36)
        self.clear_cache_button.setMinimumWidth(0)
        self.clear_cache_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.clear_cache_button.setToolTip(
            self.t.get(
                'clear_decompile_cache_tooltip',
                'Deletes cached decompiled models (~/.tf2skingen_cache).\n'
                'Use if models stopped building correctly after a TF2 update.'
            )
        )
        self.advanced_group.addWidget(self.clear_cache_button)
        
        # Настройки сборки моделей - УДАЛЕНО: перенесено в диалог настроек
        # build_label = QLabel("Настройки сборки")
        # build_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 12px;")
        # self.advanced_group.addWidget(build_label)
        
        # self.keep_temp_checkbox = QCheckBox("Сохранить временные файлы при ошибке")
        # self.keep_temp_checkbox.stateChanged.connect(self.save_build_settings)
        # self.advanced_group.addWidget(self.keep_temp_checkbox)
        
        # self.debug_mode_checkbox = QCheckBox("Режим отладки")
        # self.debug_mode_checkbox.stateChanged.connect(self.save_build_settings)
        # self.advanced_group.addWidget(self.debug_mode_checkbox)
        
        # Добавляем accordion во второй контейнер
        advanced_container_layout.addWidget(self.advanced_group)
        
        # Добавляем второй контейнер в главный layout с минимальным отступом
        # Используем stretch factor 0, чтобы контейнер не растягивался
        # Устанавливаем отрицательный верхний margin для уменьшения отступа от кнопки
        main_layout.addWidget(advanced_container, 0)
        
        # Уменьшаем spacing между элементами в главном layout после добавления контейнеров
        # Это делается через установку spacing для конкретных элементов
        main_layout.setSpacing(8)
        
        # Ширина следует за viewport скролла; по вертикали не ниже содержимого
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        self._apply_step2_responsive_radios()

        # Добавляем растяжку, чтобы элементы были сверху и не растягивались
        main_layout.addStretch(1)

    def _apply_step2_responsive_radios(self) -> None:
        """Радиокнопки разрешения: не тянуть лишнюю минимальную ширину из одной длинной строки."""
        for rb in (self.radio_256, self.radio_512, self.radio_1024, self.radio_2048):
            rb.setMinimumWidth(0)
            rb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    # ── Build-options gear menu ──────────────────────────────────────────────── #

    def _show_build_options_menu(self) -> None:
        """Открывает/скрывает всплывающий виджет с опциями сборки."""
        # Создаём попап один раз и переиспользуем
        if not hasattr(self, '_build_popup') or self._build_popup is None:
            self._build_popup = _BuildOptsPopup(self)

        if self._build_popup.isVisible():
            self._build_popup.hide()
            return

        # Позиционируем: правый край попапа совпадает с правым краем кнопки шестерёнки
        btn_global_br = self.build_opts_btn.mapToGlobal(
            QPoint(self.build_opts_btn.width(), self.build_opts_btn.height())
        )
        popup_w = self._build_popup.sizeHint().width()
        popup_x = btn_global_br.x() - popup_w
        popup_y = btn_global_br.y() + 4
        self._build_popup.move(popup_x, popup_y)
        self._build_popup.show()

    def _refresh_build_opts_btn(self) -> None:
        """Обновляет стиль и иконку: акцент — если хотя бы одна опция активна."""
        active = self._replace_model_checked or self._model_ready_checked
        self.build_opts_btn.setStyleSheet(
            _BUILD_OPTS_BTN_ACTIVE if active else _BUILD_OPTS_BTN_IDLE
        )
        icon_color = "#ffffff" if active else "#d0d0d0"
        self.build_opts_btn.setIcon(_make_build_opts_icon(icon_color, 11))

    # ── Публичный API для чтения/установки состояния ──────────────────────── #

    def is_replace_model_checked(self) -> bool:
        # Читаем напрямую из чекбокса попапа — это надёжнее кэшированного флага,
        # который мог не обновиться если stateChanged не успел сработать.
        if hasattr(self, '_build_popup') and self._build_popup is not None:
            return self._build_popup._cb_replace.isChecked()
        return self._replace_model_checked

    def is_model_ready_checked(self) -> bool:
        if hasattr(self, '_build_popup') and self._build_popup is not None:
            return self._build_popup._cb_ready.isChecked()
        return self._model_ready_checked

    def reset_build_options(self, *, emit: bool = False) -> None:
        changed_replace = self._replace_model_checked
        changed_ready   = self._model_ready_checked
        self._replace_model_checked = False
        self._model_ready_checked   = False
        self._refresh_build_opts_btn()
        # Синхронизируем чекбоксы в попапе, если он уже создан
        if hasattr(self, '_build_popup') and self._build_popup is not None:
            self._build_popup.sync_from_panel()
        if emit:
            if changed_replace:
                self.replace_model_toggled.emit(False)
            if changed_ready:
                self.model_ready_toggled.emit(False)

    # ── Единый контроллер ограничений UI по режиму ─────────────────────────── #

    def apply_mode_restrictions(self, mode) -> None:
        """
        Применяет ограничения UI в зависимости от текущего режима сборки.

        Это единственный метод, управляющий доступностью виджетов по режиму.
        Вызывается из MainWindow.apply_selection_auto() при каждой смене режима.

        Матрица ограничений:
          Оружие — всё доступно
          CritHIT — формат/флаги/UV/Normal заблокированы (on_crit_hit_selected);
                    кнопки инструментов недоступны
          Spray   — только 256×256; только форматы с альфа; флаги недоступны;
                    UV/Normal скрыты; кнопки инструментов недоступны
          Hands   — UV/Normal скрыты; VMT недоступен; Извлечь модель — доступно
        """
        try:
            from src.data.player_hands import HAND_MODE_KEYS
        except ImportError:
            HAND_MODE_KEYS = frozenset()
        try:
            from src.data.player_characters import PLAYER_BODY_MODE_KEYS
        except ImportError:
            PLAYER_BODY_MODE_KEYS = frozenset()

        is_spray       = (mode == "spray")
        is_crit        = (mode == "critHIT")
        is_hands       = bool(mode and mode in HAND_MODE_KEYS)
        is_player_body = bool(mode and mode in PLAYER_BODY_MODE_KEYS)
        is_normal = bool(mode and not is_spray and not is_crit and not is_hands and not is_player_body)

        lang = 'ru'
        if self.parent and hasattr(self.parent, 'language'):
            lang = self.parent.language

        # ── 1. Разрешение ────────────────────────────────────────────────── #
        if is_spray:
            self.radio_256.setChecked(True)
        for rb in (self.radio_512, self.radio_1024, self.radio_2048):
            rb.setEnabled(not is_spray)
        self.radio_256.setEnabled(True)  # 256 всегда кликабельна

        # ── 2. Формат VTF ────────────────────────────────────────────────── #
        _ALPHA_FORMATS = {
            "DXT3", "DXT5", "RGBA8888", "BGRA8888", "ABGR8888", "ARGB8888",
            "DXT1 With One Bit Alpha", "BGRA5551", "BGRA4444", "IA88", "A8",
            "RGBA16161616F", "RGBA16161616",
        }
        if is_spray:
            if self.format_combo.currentText() not in _ALPHA_FORMATS:
                self.format_combo.setCurrentText("DXT5")
            self.format_combo.setEnabled(False)
            self.format_combo.setToolTip(
                "Спрей требует формат с альфа-каналом (DXT5)"
                if lang == 'ru' else
                "Spray requires an alpha-capable format (DXT5)"
            )
        elif not is_crit:
            # CritHIT управляется через on_crit_hit_selected — не трогаем
            self.format_combo.setEnabled(True)
            self.format_combo.setToolTip("")

        # ── 3. Флаги VTF ─────────────────────────────────────────────────── #
        # Spray: флаги бессмысленны → отключаем
        # CritHIT: on_crit_hit_selected уже управляет → не трогаем
        _flag_widgets = [
            self.flag_clamps, self.flag_clampt,
            self.flag_nomipmaps, self.flag_nolod, self.flag_nominmipmaps,
        ]
        _opt_attrs = ('option_nothumbnail', 'option_noreflectivity', 'option_gamma')
        if is_spray:
            for w in _flag_widgets:
                w.setEnabled(False)
            for attr in _opt_attrs:
                if hasattr(self, attr):
                    getattr(self, attr).setEnabled(False)
            if hasattr(self, 'gamma_value_input'):
                self.gamma_value_input.setEnabled(False)
        elif not is_crit:
            for w in _flag_widgets:
                w.setEnabled(True)
            for attr in _opt_attrs:
                if hasattr(self, attr):
                    getattr(self, attr).setEnabled(True)
            if hasattr(self, 'gamma_value_input'):
                self.gamma_value_input.setEnabled(
                    hasattr(self, 'option_gamma') and self.option_gamma.isChecked()
                )

        # ── 4. UV Layout ─────────────────────────────────────────────────── #
        # Видима только для обычного оружия; CritHIT, руки и скины персонажей скрывают
        if not is_crit:
            uv_visible = is_normal
            if hasattr(self, 'uv_layout_widget'):
                self.uv_layout_widget.setVisible(uv_visible)
            if hasattr(self, 'uv_layout_checkbox'):
                self.uv_layout_checkbox.setVisible(uv_visible)
                if not uv_visible and self.uv_layout_checkbox.isChecked():
                    self.uv_layout_checkbox.blockSignals(True)
                    self.uv_layout_checkbox.force_set_checked(False)
                    self.uv_layout_checkbox.blockSignals(False)
            if hasattr(self, 'uv_resolution_label'):
                self.uv_resolution_label.setVisible(uv_visible)
            if hasattr(self, 'advanced_group'):
                self.advanced_group.content_widget.updateGeometry()

        # ── 5. Normal Map ─────────────────────────────────────────────────── #
        # Только для обычного оружия; CritHIT управляет сам
        if hasattr(self, 'option_normal') and not is_crit:
            self.option_normal.setEnabled(is_normal)
            if not is_normal and self.option_normal.isChecked():
                self.option_normal.blockSignals(True)
                self.option_normal.setChecked(False)
                self.option_normal.blockSignals(False)

        # ── 6. Кнопки инструментов ────────────────────────────────────────── #

        def _tip(spray_ru, spray_en, crit_ru, crit_en, hands_ru, hands_en):
            if is_spray:
                return spray_ru if lang == 'ru' else spray_en
            if is_crit:
                return crit_ru if lang == 'ru' else crit_en
            if is_hands or is_player_body:
                return hands_ru if lang == 'ru' else hands_en
            return ""

        # Извлечь модель — для обычного оружия, рук и скинов персонажей (MDL существует)
        self.extract_model_button.setEnabled(is_normal or is_hands or is_player_body)
        self.extract_model_button.setToolTip(_tip(
            "Режим спрея: модели нет",   "Spray mode: no model",
            "Режим CritHIT: модели нет", "CritHIT mode: no model",
            "", "",  # для рук и скинов — доступно, подсказка не нужна
        ))

        # Извлечь текстуру — для обычного оружия, рук и скинов персонажей
        self.extract_texture_button.setEnabled(is_normal or is_hands or is_player_body)
        self.extract_texture_button.setToolTip(_tip(
            "Режим спрея: оригинальной текстуры нет", "Spray mode: no original texture",
            "Режим CritHIT: оригинальной текстуры нет", "CritHIT mode: no original texture",
            "", "",  # для рук и скинов — доступно, подсказка не нужна
        ))

        # VMT редактор — только для обычного оружия
        self.expert_button.setEnabled(is_normal)
        self.expert_button.setToolTip(_tip(
            "VMT спрея создаётся автоматически", "Spray VMT is auto-generated",
            "VMT CritHIT создаётся автоматически", "CritHIT VMT is auto-generated",
            "VMT рук управляется игрой",          "Hands VMT is controlled by the game",
        ))

    def on_crit_hit_selected(self, is_crit_hit):
        """Обработка выбора CritHIT режима"""
        # Отключаем/включаем контролы в зависимости от режима
        self.format_combo.setEnabled(not is_crit_hit)
        self.flag_clamps.setEnabled(not is_crit_hit)
        self.flag_clampt.setEnabled(not is_crit_hit)
        self.flag_nomipmaps.setEnabled(not is_crit_hit)
        self.flag_nolod.setEnabled(not is_crit_hit)
        # Отключаем новые опции VTFCmd для CritHIT режима
        if hasattr(self, 'option_nothumbnail'):
            self.option_nothumbnail.setEnabled(not is_crit_hit)
        if hasattr(self, 'option_noreflectivity'):
            self.option_noreflectivity.setEnabled(not is_crit_hit)
        if hasattr(self, 'flag_nominmipmaps'):
            self.flag_nominmipmaps.setEnabled(not is_crit_hit)
        if hasattr(self, 'option_gamma'):
            self.option_gamma.setEnabled(not is_crit_hit)
        if hasattr(self, 'gamma_value_input'):
            self.gamma_value_input.setEnabled(not is_crit_hit and 
                                               (hasattr(self, 'option_gamma') and self.option_gamma.isChecked()))
        self._sync_crit_hit_dependent_controls(is_crit_hit)
        
        # Для CritHIT устанавливаем формат DXT5
        if is_crit_hit:
            self.format_combo.setCurrentText("DXT5")

    def _sync_crit_hit_dependent_controls(self, is_crit_hit=None) -> None:
        if is_crit_hit is None:
            is_crit_hit = self._get_crit_hit_state()

        def apply_state():
            if hasattr(self, 'option_normal'):
                self.option_normal.blockSignals(True)
                if is_crit_hit:
                    self.option_normal.setCheckState(Qt.Unchecked)
                self.option_normal.blockSignals(False)
                self.option_normal.setEnabled(not is_crit_hit)

            if hasattr(self, 'uv_layout_checkbox'):
                self.uv_layout_checkbox.blockSignals(True)
                if is_crit_hit:
                    self.uv_layout_checkbox.force_set_checked(False)
                self.uv_layout_checkbox.blockSignals(False)
                self.uv_layout_checkbox.setEnabled(not is_crit_hit)

            if hasattr(self, 'uv_resolution_label'):
                self.uv_resolution_label.setEnabled(not is_crit_hit)

            if hasattr(self, 'uv_layout_widget'):
                self.uv_layout_widget.setEnabled(not is_crit_hit)
                self.uv_layout_widget.setVisible(not is_crit_hit)
                if hasattr(self, 'uv_layout_checkbox'):
                    self.uv_layout_checkbox.setVisible(not is_crit_hit)
                if hasattr(self, 'uv_resolution_label'):
                    self.uv_resolution_label.setVisible(not is_crit_hit)
                self.uv_layout_widget.updateGeometry()
                if hasattr(self, 'advanced_group'):
                    self.advanced_group.content_widget.updateGeometry()

        QTimer.singleShot(0, apply_state)
    
    def setup_connections(self):
        """Настраивает соединения сигналов"""
        self.expert_button.clicked.connect(self.expert_mode_triggered)
        self.button.clicked.connect(self.build_vpk)
        self.extract_model_button.clicked.connect(self.extract_model_triggered)
        self.extract_texture_button.clicked.connect(self.extract_texture_triggered)
        self.merge_vpk_button.clicked.connect(self.merge_vpk_triggered)
        self.filename_input.textChanged.connect(self.validate_vpk_name)
        # Подключаем сигнал сворачивания/разворачивания секции "Дополнительно"
        self.advanced_group.toggled.connect(self.on_advanced_toggled)
        # Подключаем обработчик для чекбокса UV разметки
        if hasattr(self, 'uv_layout_checkbox'):
            self.uv_layout_checkbox.stateChanged.connect(self._on_uv_layout_state_changed)
        if hasattr(self, 'option_normal'):
            self.option_normal.stateChanged.connect(self._on_normal_map_state_changed)
        if self.parent and hasattr(self.parent, 'crit_hit_checkbox'):
            self.parent.crit_hit_checkbox.stateChanged.connect(
                lambda state: self.on_crit_hit_selected(state == Qt.Checked)
            )
            self.on_crit_hit_selected(self.parent.crit_hit_checkbox.isChecked())
        if hasattr(self, 'clear_cache_button'):
            self.clear_cache_button.clicked.connect(self._on_clear_cache_clicked)
    
    def _on_uv_layout_state_changed(self, state: int) -> None:
        """Обработчик изменения состояния чекбокса UV разметки"""
        is_checked = (state == Qt.Checked)
        
        # Если пытаются включить UV разметку, проверяем, не включен ли CritHIT
        if is_checked:
            is_crit_hit = self._get_crit_hit_state()
            if is_crit_hit:
                def reset_uv():
                    self.uv_layout_checkbox.blockSignals(True)
                    self.uv_layout_checkbox.force_set_checked(False)
                    self.uv_layout_checkbox.blockSignals(False)
                QTimer.singleShot(0, reset_uv)

    def _on_normal_map_state_changed(self, state: int) -> None:
        """Обработчик изменения состояния Normal Map"""
        is_checked = (state == Qt.Checked)
        if is_checked:
            is_crit_hit = self._get_crit_hit_state()
            if is_crit_hit and hasattr(self, 'option_normal'):
                def reset_normal():
                    self.option_normal.blockSignals(True)
                    self.option_normal.setCheckState(Qt.Unchecked)
                    self.option_normal.blockSignals(False)
                QTimer.singleShot(0, reset_normal)
    
    def on_advanced_toggled(self, is_expanded):
        """Обработка сворачивания/разворачивания секции Дополнительно"""
        # Уведомляем главное окно об изменении для пересчета размера
        if hasattr(self.parent, 'on_advanced_section_toggled'):
            self.parent.on_advanced_section_toggled(is_expanded)
        self._sync_crit_hit_dependent_controls()
    
    def _get_crit_hit_state(self) -> bool:
        if self.parent and hasattr(self.parent, 'crit_hit_checkbox'):
            return self.parent.crit_hit_checkbox.isChecked()
        return False
    
    def validate_vpk_name(self):
        """Валидация имени VPK файла"""
        filename = self.filename_input.text().strip()
        
        if not filename:
            self.filename_error.setText(self.t['enter_vpk_filename'])
            self.filename_error.show()
            self.button.setEnabled(False)
            return False
        
        # Проверяем на недопустимые символы
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in invalid_chars:
            if char in filename:
                self.filename_error.setText(self.t.get('invalid_char_error', 'Invalid character: {char}').format(char=char))
                self.filename_error.show()
                self.button.setEnabled(False)
                return False
        
        # Проверяем длину
        if len(filename) > 50:
            self.filename_error.setText(self.t.get('filename_too_long_error', 'Filename is too long (max 50 characters)'))
            self.filename_error.show()
            self.button.setEnabled(False)
            return False
        
        self.filename_error.hide()
        self.button.setEnabled(True)
        return True
    
    def get_settings(self):
        """Возвращает текущие настройки"""
        if self.radio_256.isChecked():
            size = (256, 256)
        elif self.radio_2048.isChecked():
            size = (2048, 2048)
        elif self.radio_1024.isChecked():
            size = (1024, 1024)
        else:
            size = (512, 512)
        format_type = self.format_combo.currentText()
        
        flags = []
        if self.flag_clamps.isChecked():
            flags.append("CLAMPS")
        if self.flag_clampt.isChecked():
            flags.append("CLAMPT")
        if self.flag_nomipmaps.isChecked():
            flags.append("NOMIP")
        if self.flag_nolod.isChecked():
            flags.append("NOLOD")
        if hasattr(self, 'flag_nominmipmaps') and self.flag_nominmipmaps.isChecked():
            flags.append("NOMINMIP")
        
        # Опции VTFCmd
        options = {}
        if hasattr(self, 'option_nothumbnail') and self.option_nothumbnail.isChecked():
            options['nothumbnail'] = True
        if hasattr(self, 'option_noreflectivity') and self.option_noreflectivity.isChecked():
            options['noreflectivity'] = True
        if hasattr(self, 'option_normal') and self.option_normal.isChecked():
            options['normal'] = True
        if hasattr(self, 'option_gamma') and self.option_gamma.isChecked():
            options['gamma'] = True
            if hasattr(self, 'gamma_value_input'):
                gamma_value = self.gamma_value_input.text().strip()
                if gamma_value:
                    try:
                        options['gcorrection'] = float(gamma_value)
                    except ValueError:
                        options['gcorrection'] = 2.2  # Значение по умолчанию
        
        # UV разметка
        draw_uv_layout = False
        if hasattr(self, 'uv_layout_checkbox') and self.uv_layout_checkbox.isChecked():
            draw_uv_layout = True
        
        filename = self.filename_input.text().strip()
        if filename and not filename.lower().endswith(".vpk"):
            filename += ".vpk"
        
        # Получаем путь к TF2 и export folder из конфига
        from src.config.app_config import AppConfig
        config = AppConfig.load_config()
        tf2_path = config.get("tf2_game_folder", "")
        export_folder = config.get("export_folder", "export")
        
        return {
            'size': size,
            'format': format_type,
            'flags': flags,
            'vtf_options': options,  # Новое поле для опций VTFCmd
            'draw_uv_layout': draw_uv_layout,  # Флаг для рисования UV разметки
            'filename': filename,
            'tf2_game_folder': tf2_path,
            'export_folder': export_folder,
            'keep_temp_on_error': config.get('keep_temp_files', False),
            'debug_mode': config.get('debug_mode', False)
        }
    
    def load_config(self):
        """Загружает настройки из конфига"""
        config = AppConfig.load_config()
        
        # Загружаем настройки отладки и временных файлов - УДАЛЕНО: теперь загружаются в SettingsDialog
        pass
    
    def save_build_settings(self):
        """Сохраняет настройки сборки в конфиг"""
        # Сохранение настроек бигда больше не производится здесь для чекбоксов отладки
        pass
    
    def expert_mode_triggered(self):
        """Обработка нажатия кнопки экспертного режима"""
        if hasattr(self.parent, 'expert_mode_triggered'):
            self.parent.expert_mode_triggered()
    
    def build_vpk(self):
        """Обработка нажатия кнопки сборки VPK"""
        if not self.validate_vpk_name():
            return
        if hasattr(self.parent, 'build_vpk'):
            self.parent.build_vpk()

    def extract_model_triggered(self):
        if hasattr(self.parent, 'extract_original_model'):
            self.parent.extract_original_model()
    
    def extract_texture_triggered(self):
        """Обработка нажатия кнопки извлечения текстуры"""
        if hasattr(self.parent, 'extract_original_texture'):
            self.parent.extract_original_texture()
    
    def merge_vpk_triggered(self):
        """Обработка нажатия кнопки объединения VPK"""
        if hasattr(self.parent, 'merge_vpk_files'):
            self.parent.merge_vpk_files()
    
    def _on_clear_cache_clicked(self):
        """Очищает кэш декомпилированных моделей с подтверждением"""
        from src.services.decompile_cache import clear_cache, get_cache_size_mb
        from PySide6.QtWidgets import QMessageBox
        
        size_mb = get_cache_size_mb()
        size_str = f"{size_mb:.1f} MB" if size_mb >= 0.1 else "< 0.1 MB"
        
        msg = self.t.get(
            'clear_cache_confirm',
            'Clear the model decompile cache?\n\nCache size: {size}\n\n'
            'The cache speeds up repeated builds of the same weapon.\n'
            'After clearing, the first build of each weapon will be slower.'
        ).format(size=size_str)
        
        reply = QMessageBox.question(
            self,
            self.t.get('clear_decompile_cache', 'Clear Model Cache'),
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            count = clear_cache()
            ok_msg = self.t.get(
                'clear_cache_done',
                'Cache cleared. {count} entries removed.'
            ).format(count=count)
            QMessageBox.information(
                self,
                self.t.get('clear_decompile_cache', 'Clear Model Cache'),
                ok_msg
            )
    
    def open_support_link(self):
        """Открывает ссылку поддержки"""
        if hasattr(self.parent, 'open_support_link'):
            self.parent.open_support_link()
    
    def change_language_from_combo(self, index):
        """Обработка изменения языка"""
        if hasattr(self.parent, 'change_language_from_combo'):
            self.parent.change_language_from_combo(index)
    
    def update_language(self, t):
        """Обновляет язык интерфейса"""
        self.t = t
        
        # Обновляем тексты
        self.expert_button.setText(self.t.get('open_editor', 'Открыть редактор'))
        self.button.setText(self.t.get('build', 'Собрать VPK'))
        if hasattr(self, 'build_opts_btn'):
            self.build_opts_btn.setToolTip(
                self.t.get('build_options_tooltip', 'Build options')
            )
        if hasattr(self, 'extract_model_button'):
            self.extract_model_button.setText(self.t.get('extract_model', 'Extract Original Model (SMD)'))
        self.filename_input.setPlaceholderText(self.t.get('placeholder', 'Имя VPK'))
        
        # Обновляем метки
        self.step_label.setText(self.t['step_2_export'])
        self.res_label.setText(self.t['resolution'])
        self.format_label.setText(self.t['format_vtf'])
        self.filename_label.setText(self.t['filename_vpk'])
        self.flags_label.setText(self.t['flags_vtf'])
        self.tools_label.setText(self.t['tools'])
        
        # Обновляем радио кнопки
        if hasattr(self, 'radio_256'):
            self.radio_256.setText(self.t.get('res_256', '256x256 (Spray)'))
        self.radio_512.setText(self.t['res_normal'])
        self.radio_1024.setText(self.t['res_high'])
        if hasattr(self, 'radio_2048'):
            self.radio_2048.setText(self.t.get('res_ultra', '2048x2048 (Ultra)'))
        
        # Обновляем чекбоксы
        self.flag_clamps.setText(self.t['clamp_s'])
        self.flag_clampt.setText(self.t['clamp_t'])
        self.flag_nomipmaps.setText(self.t['no_mipmap'])
        self.flag_nolod.setText(self.t['no_lod'])
        # Обновляем новые опции VTFCmd
        if hasattr(self, 'option_nothumbnail'):
            self.option_nothumbnail.setText(self.t.get('no_thumbnail', 'No Thumbnail'))
        if hasattr(self, 'option_noreflectivity'):
            self.option_noreflectivity.setText(self.t.get('no_reflectivity', 'No Reflectivity'))
        if hasattr(self, 'flag_nominmipmaps'):
            self.flag_nominmipmaps.setText(self.t.get('no_minimum_mipmap', 'No minimum Mipmap'))
        if hasattr(self, 'option_normal'):
            self.option_normal.setText(self.t.get('normal_map', 'Normal Map'))
        if hasattr(self, 'option_gamma'):
            self.option_gamma.setText(self.t.get('gamma_correction', 'Gamma Correction'))
        # Обновляем чекбокс UV разметки
        if hasattr(self, 'uv_layout_checkbox'):
            self.uv_layout_checkbox.setText(self.t.get('draw_uv_layout', 'Нарисовать UV разметку'))
        # Обновляем метку разрешения UV
        self._update_uv_resolution_label()
        
        # Обновляем заголовок Advanced
        prefix = "▼ " if self.advanced_group.is_expanded else "▶ "
        self.advanced_group.toggle_button.setText(prefix + self.t['advanced_title'])
        
        # Обновляем кнопку извлечения текстуры
        if hasattr(self, 'extract_texture_button'):
            self.extract_texture_button.setText(self.t.get('extract_texture', 'Extract Original Texture'))
        
        # Обновляем кнопку объединения VPK
        if hasattr(self, 'merge_vpk_button'):
            self.merge_vpk_button.setText(self.t.get('merge_vpk', 'Сборка в один'))
        
        # Обновляем кнопку очистки кэша
        if hasattr(self, 'clear_cache_button'):
            self.clear_cache_button.setText(self.t.get('clear_decompile_cache', 'Clear Model Cache'))
        
        # Перезапускаем валидацию имени файла, если ошибка уже отображается
        if hasattr(self, 'filename_error') and self.filename_error.isVisible():
            self.validate_vpk_name()

    def _update_uv_resolution_label(self):
        """Обновляет метку разрешения UV разметки в зависимости от выбранного разрешения текстуры"""
        if hasattr(self, 'uv_resolution_label'):
            if self.radio_2048.isChecked():
                self.uv_resolution_label.setText("(2048x2048)")
            elif self.radio_1024.isChecked():
                self.uv_resolution_label.setText("(1024x1024)")
            elif self.radio_256.isChecked():
                self.uv_resolution_label.setText("(256x256)")
            else:
                self.uv_resolution_label.setText("(512x512)")
