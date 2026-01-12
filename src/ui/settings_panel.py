"""
Панель настроек - Минималистичный дизайн
"""

import os
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QPushButton, QLineEdit, QRadioButton, QCheckBox, QButtonGroup,
    QWidget, QSizePolicy, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
from src.data.translations import TRANSLATIONS
from src.utils.themes import get_modern_styles
from src.config.app_config import AppConfig

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

class SettingsPanel(QWidget):
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
        self.step_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_layout.addWidget(self.step_label)
        
        # ПЕРВЫЙ КОНТЕЙНЕР - Основные настройки
        main_settings_container = QWidget()
        main_settings_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        main_settings_layout = QVBoxLayout(main_settings_container)
        main_settings_layout.setSpacing(12)
        main_settings_layout.setContentsMargins(0, 0, 0, 0)
        
        # Пресет
        self.preset_label = QLabel(self.t['profile_preset'])
        self.preset_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.preset_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.preset_label)
        
        self.preset_combo = QComboBox()
        # Обновляем ключи пресетов, чтобы они брались из translations
        self.update_preset_items()
        
        self.preset_combo.setStyleSheet(self.styles['combo'])
        self.preset_combo.setMinimumHeight(40)
        self.preset_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.preset_combo)
        
        # Разрешение
        self.res_label = QLabel(self.t['resolution'])
        self.res_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.res_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.res_label)
        
        self.radio_group = QButtonGroup()
        self.radio_512 = QRadioButton(self.t['res_normal'])
        self.radio_512.setChecked(True)
        self.radio_1024 = QRadioButton(self.t['res_high'])
        self.radio_2048 = QRadioButton(self.t.get('res_ultra', '2048x2048 (Ultra)'))
        
        self.radio_group.addButton(self.radio_512)
        self.radio_group.addButton(self.radio_1024)
        self.radio_group.addButton(self.radio_2048)
        
        res_layout = QHBoxLayout()
        res_layout.setSpacing(8)
        res_layout.addWidget(self.radio_512)
        res_layout.addWidget(self.radio_1024)
        res_layout.addWidget(self.radio_2048)
        main_settings_layout.addLayout(res_layout)
        
        # Формат VTF
        self.format_label = QLabel(self.t['format_vtf'])
        self.format_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.format_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.format_label)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["DXT1", "DXT5", "RGBA8888", "I8", "A8"])
        self.format_combo.setStyleSheet(self.styles['combo'])
        self.format_combo.setMinimumHeight(40)
        self.format_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.format_combo)
        
        # Имя VPK
        self.filename_label = QLabel(self.t['filename_vpk'])
        self.filename_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc;")
        self.filename_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.filename_label)
        
        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText(self.t['placeholder'])
        self.filename_input.setStyleSheet(self.styles['line_edit'])
        self.filename_input.setMinimumHeight(40)
        self.filename_input.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.filename_input)
        
        # Сообщение об ошибке валидации
        self.filename_error = QLabel("")
        self.filename_error.setStyleSheet("color: #ff4757; font-size: 11px; padding-top: 4px;")
        self.filename_error.hide()
        self.filename_error.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.filename_error)
        
        # Primary CTA - Собрать VPK
        self.button = QPushButton(self.t['build'])
        self.button.setStyleSheet(self.styles['button_primary'])
        self.button.setMinimumHeight(48)
        self.button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.button)
        
        # Кнопка извлечения оригинальной текстуры
        self.extract_texture_button = QPushButton(self.t.get('extract_texture', 'Extract Original Texture'))
        self.extract_texture_button.setStyleSheet(self.styles['button_secondary'])
        self.extract_texture_button.setMinimumHeight(40)
        self.extract_texture_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_settings_layout.addWidget(self.extract_texture_button)
        
        # Добавляем первый контейнер в главный layout
        main_layout.addWidget(main_settings_container, 0)
        
        # ВТОРОЙ КОНТЕЙНЕР - Секция "Дополнительно"
        # Уменьшаем отступ сверху, чтобы секция была ближе к кнопке "Собрать VPK"
        advanced_container = QWidget()
        advanced_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        advanced_container_layout = QVBoxLayout(advanced_container)
        # Устанавливаем отрицательный верхний margin для уменьшения отступа от кнопки
        advanced_container_layout.setContentsMargins(0, -4, 0, 0)
        advanced_container_layout.setSpacing(0)
        
        # Accordion "Дополнительно" в отдельном контейнере
        self.advanced_group = CollapsibleGroup("▶ " + self.t['advanced_title'])
        self.advanced_group.toggle_button.setText("▶ " + self.t['advanced_title'])
        # Устанавливаем размерную политику, чтобы accordion не растягивался
        self.advanced_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
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
        flags_layout.setSpacing(4)  # Уменьшенное расстояние между флагами
        
        # Компактный стиль для чекбоксов флагов
        compact_checkbox_style = """
            QCheckBox {
                padding: 2px 0px;
                spacing: 6px;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
        """
        
        # Первый ряд флагов (два столбца)
        flags_row1 = QHBoxLayout()
        flags_row1.setSpacing(8)
        flags_row1.setContentsMargins(0, 0, 0, 0)
        self.flag_clamps = QCheckBox(self.t['clamp_s'])
        self.flag_clamps.setStyleSheet(compact_checkbox_style)
        self.flag_clampt = QCheckBox(self.t['clamp_t'])
        self.flag_clampt.setStyleSheet(compact_checkbox_style)
        flags_row1.addWidget(self.flag_clamps)
        flags_row1.addWidget(self.flag_clampt)
        flags_row1.addStretch()
        flags_layout.addLayout(flags_row1)
        
        # Второй ряд флагов (два столбца)
        flags_row2 = QHBoxLayout()
        flags_row2.setSpacing(8)
        flags_row2.setContentsMargins(0, 0, 0, 0)
        self.flag_nomipmaps = QCheckBox(self.t['no_mipmap'])
        self.flag_nomipmaps.setStyleSheet(compact_checkbox_style)
        self.flag_nolod = QCheckBox(self.t['no_lod'])
        self.flag_nolod.setStyleSheet(compact_checkbox_style)
        flags_row2.addWidget(self.flag_nomipmaps)
        flags_row2.addWidget(self.flag_nolod)
        flags_row2.addStretch()
        flags_layout.addLayout(flags_row2)
        
        # Третий ряд - новые опции VTFCmd (два столбца)
        flags_row3 = QHBoxLayout()
        flags_row3.setSpacing(8)
        flags_row3.setContentsMargins(0, 0, 0, 0)
        self.option_nothumbnail = QCheckBox(self.t.get('no_thumbnail', 'No Thumbnail'))
        self.option_nothumbnail.setStyleSheet(compact_checkbox_style)
        self.option_noreflectivity = QCheckBox(self.t.get('no_reflectivity', 'No Reflectivity'))
        self.option_noreflectivity.setStyleSheet(compact_checkbox_style)
        flags_row3.addWidget(self.option_nothumbnail)
        flags_row3.addWidget(self.option_noreflectivity)
        flags_row3.addStretch()
        flags_layout.addLayout(flags_row3)
        
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
        self.uv_layout_checkbox = QCheckBox(self.t.get('draw_uv_layout', 'Нарисовать UV разметку'))
        self.uv_layout_checkbox.setStyleSheet(compact_checkbox_style)
        self.uv_resolution_label = QLabel("(512x512)")
        self.uv_resolution_label.setStyleSheet("font-size: 11px; color: #999; padding: 0px;")
        uv_layout_row.addWidget(self.uv_layout_checkbox)
        uv_layout_row.addWidget(self.uv_resolution_label)
        uv_layout_row.addStretch()
        uv_layout_widget = QWidget()
        uv_layout_widget.setLayout(uv_layout_row)
        self.advanced_group.addWidget(uv_layout_widget)
        
        # Обновляем разрешение UV при изменении разрешения текстуры
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
        self.advanced_group.addWidget(self.expert_button)
        
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
        
        # Добавляем растяжку, чтобы элементы были сверху и не растягивались
        main_layout.addStretch(1)
    
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
        if hasattr(self, 'option_gamma'):
            self.option_gamma.setEnabled(not is_crit_hit)
        if hasattr(self, 'gamma_value_input'):
            self.gamma_value_input.setEnabled(not is_crit_hit and 
                                               (hasattr(self, 'option_gamma') and self.option_gamma.isChecked()))
        # Отключаем UV разметку для CritHIT режима
        if hasattr(self, 'uv_layout_checkbox'):
            self.uv_layout_checkbox.setEnabled(not is_crit_hit)
        
        # Для CritHIT устанавливаем формат DXT5
        if is_crit_hit:
            self.format_combo.setCurrentText("DXT5")
    
    def setup_connections(self):
        """Настраивает соединения сигналов"""
        self.expert_button.clicked.connect(self.expert_mode_triggered)
        self.button.clicked.connect(self.build_vpk)
        self.extract_texture_button.clicked.connect(self.extract_texture_triggered)
        self.preset_combo.currentTextChanged.connect(self.apply_preset)
        self.filename_input.textChanged.connect(self.validate_vpk_name)
        # Подключаем сигнал сворачивания/разворачивания секции "Дополнительно"
        self.advanced_group.toggled.connect(self.on_advanced_toggled)
    
    def on_advanced_toggled(self, is_expanded):
        """Обработка сворачивания/разворачивания секции Дополнительно"""
        # Уведомляем главное окно об изменении для пересчета размера
        if hasattr(self.parent, 'on_advanced_section_toggled'):
            self.parent.on_advanced_section_toggled(is_expanded)
    
    def apply_preset(self, preset_name):
        """Применяет выбранный пресет"""
        if preset_name in self.presets:
            preset = self.presets[preset_name]
            
            # Устанавливаем разрешение
            if preset["resolution"] == 512:
                self.radio_512.setChecked(True)
            elif preset["resolution"] == 1024:
                self.radio_1024.setChecked(True)
            elif preset["resolution"] == 2048:
                self.radio_2048.setChecked(True)
            else:
                self.radio_512.setChecked(True)
            
            # Устанавливаем формат
            self.format_combo.setCurrentText(preset["format"])
            
            # Устанавливаем флаги
            self.flag_clamps.setChecked("CLAMPS" in preset["flags"])
            self.flag_clampt.setChecked("CLAMPT" in preset["flags"])
            self.flag_nomipmaps.setChecked("NOMIP" in preset["flags"])
            self.flag_nolod.setChecked("NOLOD" in preset["flags"])
    
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
        if self.radio_2048.isChecked():
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
        
        # Опции VTFCmd
        options = {}
        if hasattr(self, 'option_nothumbnail') and self.option_nothumbnail.isChecked():
            options['nothumbnail'] = True
        if hasattr(self, 'option_noreflectivity') and self.option_noreflectivity.isChecked():
            options['noreflectivity'] = True
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
    
    def extract_texture_triggered(self):
        """Обработка нажатия кнопки извлечения текстуры"""
        if hasattr(self.parent, 'extract_original_texture'):
            self.parent.extract_original_texture()
    
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
        self.filename_input.setPlaceholderText(self.t.get('placeholder', 'Имя VPK'))
        
        # Обновляем метки
        self.step_label.setText(self.t['step_2_export'])
        self.preset_label.setText(self.t['profile_preset'])
        self.res_label.setText(self.t['resolution'])
        self.format_label.setText(self.t['format_vtf'])
        self.filename_label.setText(self.t['filename_vpk'])
        self.flags_label.setText(self.t['flags_vtf'])
        self.tools_label.setText(self.t['tools'])
        
        # Обновляем радио кнопки
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
        
        # Обновляем список пресетов (сохраняя текущий выбор по индексу)
        current_idx = self.preset_combo.currentIndex()
        self.update_preset_items()
        if current_idx >= 0 and current_idx < self.preset_combo.count():
            self.preset_combo.setCurrentIndex(current_idx)
        
        # Обновляем кнопку извлечения текстуры
        if hasattr(self, 'extract_texture_button'):
            self.extract_texture_button.setText(self.t.get('extract_texture', 'Extract Original Texture'))
        
        # Перезапускаем валидацию имени файла, если ошибка уже отображается
        if hasattr(self, 'filename_error') and self.filename_error.isVisible():
            self.validate_vpk_name()

    def update_preset_items(self):
        """Обновляет список пресетов на текущем языке"""
        self.preset_combo.clear()
        
        # Маппинг отображения
        display_names = [
            self.t['preset_normal'],
            self.t['preset_hq'], 
            self.t['preset_hud'],
            self.t['preset_neon']
        ]
        
        # Поскольку ключи в self.presets сейчас русские, а мы переводим отображение,
        # нам нужно просто пересоздать элементы комбобокса с новыми именами, но в том же порядке.
        # Порядок ключей в self.presets['Обычный', 'HQ', 'HUD/иконки', 'Neon'] (Python 3.7+ сохраняет порядок вставки)
        
        # Просто добавляем переведенные имена
        self.preset_combo.addItems(display_names)
    
    def _update_uv_resolution_label(self):
        """Обновляет метку разрешения UV разметки в зависимости от выбранного разрешения текстуры"""
        if hasattr(self, 'uv_resolution_label'):
            if self.radio_2048.isChecked():
                self.uv_resolution_label.setText("(2048x2048)")
            elif self.radio_1024.isChecked():
                self.uv_resolution_label.setText("(1024x1024)")
            else:
                self.uv_resolution_label.setText("(512x512)")
