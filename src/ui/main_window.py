"""
Главное окно приложения TF2 Skin Generator
"""

import sys
import os
from typing import Optional, Dict, Any, Tuple, List
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMessageBox, QFileDialog, QCheckBox, QProgressDialog, QPushButton, QDialog
)
from PySide6.QtCore import QUrl, Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QDesktopServices, QMouseEvent, QIcon
from PIL import Image

from src.ui.preview_panel import PreviewPanel
from src.ui.settings_panel import SettingsPanel
from src.ui.vmt_editor import VMTEditorDialog
from src.ui.settings_dialog import SettingsDialog
from src.data.translations import TRANSLATIONS
from src.data.weapons import (
    TF2_WEAPONS, TF2_CLASSES, WEAPON_TYPES, SPECIAL_MODES,
    get_weapon_name, get_weapon_type_name
)
from src.utils.themes import apply_dark_theme
from src.shared.logging_config import get_logger
from src.ui.error_handler import ErrorHandler
from src.shared.validators import validate_vpk_filename

logger = get_logger(__name__)


class ExclusiveCheckBox(QCheckBox):
    """Чекбокс с взаимоисключающим поведением - предотвращает включение, если другой чекбокс уже включен"""
    
    def __init__(self, text: str, exclusive_with: 'ExclusiveCheckBox' = None, parent=None):
        super().__init__(text, parent)
        self.exclusive_with = exclusive_with
    
    def set_exclusive_with(self, other: 'ExclusiveCheckBox') -> None:
        """Устанавливает другой чекбокс, с которым этот взаимоисключающий"""
        self.exclusive_with = other
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Перехватывает клик мыши и проверяет, можно ли включить чекбокс"""
        if event.button() == Qt.LeftButton:
            # Если чекбокс уже включен, разрешаем отключение
            if self.isChecked():
                super().mousePressEvent(event)
                return
            
            # Если чекбокс выключен и мы пытаемся его включить
            # Проверяем, не включен ли взаимоисключающий чекбокс
            if self.exclusive_with and self.exclusive_with.isChecked():
                # Блокируем сигналы взаимоисключающего чекбокса
                self.exclusive_with.blockSignals(True)
                # Отключаем его
                self.exclusive_with.setChecked(False)
                # Разблокируем сигналы
                self.exclusive_with.blockSignals(False)
                # Теперь разрешаем включение текущего чекбокса
                super().mousePressEvent(event)
            else:
                # Если взаимоисключающий чекбокс не включен, разрешаем обычное поведение
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        from src.config.app_config import AppConfig
        from src.core.app_factory import AppFactory
        self.config = AppConfig.load_config()
        self.language = self.config.get('language') or 'en'
        self.t = TRANSLATIONS[self.language]
        self.setWindowTitle("TF2 Skin Generator")
        self.setGeometry(100, 100, 1600, 800)
        
        icon_path = AppFactory.get_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))
        
        self.current_class = None
        self.current_weapon_type = None
        self.current_weapon = None
        self.mode = None
        
        self.setAcceptDrops(True)
        
        self.init_ui()
        self.setup_connections()
        
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._adjust_window_size)
    
    def init_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_vertical_layout = QVBoxLayout(central_widget)
        main_vertical_layout.setContentsMargins(0, 0, 0, 0)
        main_vertical_layout.setSpacing(0)
        
        top_bar = QWidget()
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 8, 16, 0)
        top_bar_layout.setSpacing(0)
        top_bar_layout.addStretch()
        
        self.settings_button = QPushButton("⚙")
        self.settings_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #666;
                border: none;
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 14px;
                min-width: 24px;
                min-height: 24px;
                max-width: 24px;
                max-height: 24px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
                color: #888;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        self.settings_button.setToolTip("Настройки")
        self.settings_button.clicked.connect(self.open_settings_dialog)
        top_bar_layout.addWidget(self.settings_button)
        
        main_vertical_layout.addWidget(top_bar)
        
        main_layout = QHBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 16, 20, 20)
        
        left_panel = self.create_weapon_selection_panel()
        main_layout.addWidget(left_panel, 1)
        
        self.preview_panel = PreviewPanel(self)
        main_layout.addWidget(self.preview_panel, 2)
        
        self.settings_panel = SettingsPanel(self)
        self.settings_panel.update_language(self.t)
        main_layout.addWidget(self.settings_panel, 1)
        
        main_vertical_layout.addLayout(main_layout)
        
        self.settings_panel.preset_combo.currentTextChanged.connect(self.update_preview_info)
        self.settings_panel.radio_512.toggled.connect(self.update_preview_info)
        self.settings_panel.radio_1024.toggled.connect(self.update_preview_info)
        self.settings_panel.format_combo.currentTextChanged.connect(self.update_preview_info)
        self.settings_panel.filename_input.textChanged.connect(self.update_preview_info)
        self.settings_panel.flag_clamps.stateChanged.connect(self.update_preview_info)
        self.settings_panel.flag_clampt.stateChanged.connect(self.update_preview_info)
        self.settings_panel.flag_nomipmaps.stateChanged.connect(self.update_preview_info)
        self.settings_panel.flag_nolod.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'option_nothumbnail'):
            self.settings_panel.option_nothumbnail.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'option_noreflectivity'):
            self.settings_panel.option_noreflectivity.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'option_gamma'):
            self.settings_panel.option_gamma.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'gamma_value_input'):
            self.settings_panel.gamma_value_input.textChanged.connect(self.update_preview_info)
    
    def create_weapon_selection_panel(self) -> None:
        from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QComboBox, QPushButton, QWidget
        from src.utils.themes import get_modern_styles
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.step_1_label = QLabel(self.t['step_1_selection'])
        self.step_1_label.setStyleSheet("""
            font-size: 12px;
            font-weight: 600;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            padding-bottom: 8px;
        """)
        layout.addWidget(self.step_1_label)
        
        self.weapon_selection_group = QGroupBox(self.t['weapon_selection'])
        styles = get_modern_styles()
        self.weapon_selection_group.setStyleSheet(styles['groupbox'])
        
        group_layout = QVBoxLayout(self.weapon_selection_group)
        group_layout.setSpacing(12)
        
        self.class_label = QLabel(self.t['class'])
        self.class_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 4px;")
        group_layout.addWidget(self.class_label)
        
        self.class_combo = QComboBox()
        self.class_combo.setStyleSheet(styles['combo'])
        self.class_combo.setMinimumHeight(40)
        
        for class_name, class_info in TF2_CLASSES.items():
            self.class_combo.addItem(f"{class_info['icon']} {class_name}")
        
        group_layout.addWidget(self.class_combo)
        
        self.type_label = QLabel(self.t['weapon_type'])
        self.type_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 8px;")
        group_layout.addWidget(self.type_label)
        
        self.weapon_type_combo = QComboBox()
        self.weapon_type_combo.setStyleSheet(styles['combo'])
        self.weapon_type_combo.setMinimumHeight(40)
        group_layout.addWidget(self.weapon_type_combo)
        
        self.weapon_label = QLabel(self.t['weapon'])
        self.weapon_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 8px;")
        group_layout.addWidget(self.weapon_label)
        
        self.weapon_combo = QComboBox()
        self.weapon_combo.setStyleSheet(styles['combo'])
        self.weapon_combo.setMinimumHeight(40)
        group_layout.addWidget(self.weapon_combo)
        
        self.crit_hit_label = QLabel(self.t['crit_hit_mode'])
        self.crit_hit_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 16px;")
        group_layout.addWidget(self.crit_hit_label)
        
        self.crit_hit_checkbox = ExclusiveCheckBox(self.t['enable_crit_hit'])
        group_layout.addWidget(self.crit_hit_checkbox)
        
        self.replace_model_label = QLabel(self.t['replace_model'])
        self.replace_model_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 16px;")
        group_layout.addWidget(self.replace_model_label)
        
        self.replace_model_checkbox = ExclusiveCheckBox(self.t['enable_replace_model'])
        self.replace_model_checkbox.setStyleSheet("color: #ccc;")
        group_layout.addWidget(self.replace_model_checkbox)
        
        self.crit_hit_checkbox.set_exclusive_with(self.replace_model_checkbox)
        self.replace_model_checkbox.set_exclusive_with(self.crit_hit_checkbox)
        
        self.selected_smd_path = None
        
        group_layout.addStretch()
        
        layout.addWidget(self.weapon_selection_group)
        layout.addStretch()
        
        return container
    
    def setup_connections(self) -> None:
        """Настраивает соединения сигналов"""
        self.class_combo.currentTextChanged.connect(self.on_class_changed)
        self.weapon_type_combo.currentTextChanged.connect(self.on_weapon_type_changed)
        self.weapon_combo.currentTextChanged.connect(self.on_weapon_changed)
        self.crit_hit_checkbox.stateChanged.connect(self._on_crit_hit_state_changed)
        self.replace_model_checkbox.stateChanged.connect(self._on_replace_model_state_changed)
        
        # Инициализируем первый класс
        self.on_class_changed(self.class_combo.currentText())
    
    def update_ui_text(self) -> None:
        """Обновляет текст интерфейса при смене языка"""
        # Обновляем заголовки
        if hasattr(self, 'step_1_label'):
            self.step_1_label.setText(self.t['step_1_selection'])
        if hasattr(self, 'weapon_selection_group'):
            self.weapon_selection_group.setTitle(self.t['weapon_selection'])
        if hasattr(self, 'class_label'):
            self.class_label.setText(self.t['class'])
        if hasattr(self, 'type_label'):
            self.type_label.setText(self.t['weapon_type'])
        if hasattr(self, 'weapon_label'):
            self.weapon_label.setText(self.t['weapon'])
        
        # Обновляем дочерние панели
        if hasattr(self, 'settings_panel'):
            self.settings_panel.update_language(self.t)
            
        if hasattr(self, 'preview_panel'):
            self.preview_panel.update_language(self.t)
            
        if hasattr(self, 'crit_hit_checkbox'):
            self.crit_hit_checkbox.setText(self.t['enable_crit_hit'])
            
        if hasattr(self, 'crit_hit_label'):
            self.crit_hit_label.setText(self.t['crit_hit_mode'])
        
        if hasattr(self, 'replace_model_checkbox'):
            self.replace_model_checkbox.setText(self.t['enable_replace_model'])
        
        if hasattr(self, 'replace_model_label'):
            self.replace_model_label.setText(self.t['replace_model'])
        
        # Обновляем списки оружий с учетом нового языка
        if hasattr(self, 'weapon_type_combo') and self.current_class:
            # Сохраняем текущий выбор
            current_type_text = self.weapon_type_combo.currentText()
            
            # Обновляем типы оружия
            self.weapon_type_combo.clear()
            if self.current_class in TF2_WEAPONS:
                for weapon_type in TF2_WEAPONS[self.current_class].keys():
                    type_name = get_weapon_type_name(weapon_type, self.language)
                    self.weapon_type_combo.addItem(type_name)
            
            # Восстанавливаем выбор и обновляем список оружий
            if self.weapon_type_combo.count() > 0:
                # Пытаемся найти соответствующий тип
                for i in range(self.weapon_type_combo.count()):
                    if self.weapon_type_combo.itemText(i) == current_type_text or i == 0:
                        self.weapon_type_combo.setCurrentIndex(i)
                        self.on_weapon_type_changed(self.weapon_type_combo.currentText())
                        break
    
    def on_class_changed(self, class_text: str) -> None:
        """Обработка изменения класса"""
        # Извлекаем имя класса из текста с иконкой
        class_name = class_text.split(' ', 1)[1] if ' ' in class_text else class_text
        self.current_class = class_name
        
        # Обновляем типы оружия
        self.weapon_type_combo.clear()
        if class_name in TF2_WEAPONS:
            for weapon_type in TF2_WEAPONS[class_name].keys():
                type_name = get_weapon_type_name(weapon_type, self.language)
                self.weapon_type_combo.addItem(type_name)
        
        # Обновляем оружие для первого типа
        if self.weapon_type_combo.count() > 0:
            self.on_weapon_type_changed(self.weapon_type_combo.currentText())
    
    def on_weapon_type_changed(self, type_text: str) -> None:
        """Обработка изменения типа оружия"""
        # Находим ключ типа оружия
        weapon_type = None
        for key in WEAPON_TYPES.keys():
            type_name = get_weapon_type_name(key, self.language)
            if type_name == type_text:
                weapon_type = key
                break
        
        if weapon_type and self.current_class:
            self.current_weapon_type = weapon_type
            
            # Обновляем список оружия
            self.weapon_combo.clear()
            if self.current_class in TF2_WEAPONS and weapon_type in TF2_WEAPONS[self.current_class]:
                for weapon_key in TF2_WEAPONS[self.current_class][weapon_type].keys():
                    weapon_name = get_weapon_name(self.current_class, weapon_type, weapon_key, self.language)
                    self.weapon_combo.addItem(f"{weapon_name} ({weapon_key})")
    
    def on_weapon_changed(self, weapon_text: str) -> None:
        """Обработка изменения оружия"""
        if weapon_text and '(' in weapon_text:
            # Извлекаем ключ оружия из скобок
            weapon_key = weapon_text.split('(')[1].rstrip(')')
            self.current_weapon = weapon_key
            # Автоматически применяем выбор
            self.apply_selection_auto()
    
    def _on_crit_hit_state_changed(self, state: int) -> None:
        """Обработчик изменения состояния чекбокса CritHIT"""
        is_checked = (state == Qt.Checked)
        
        # Если CritHIT включается, всегда отключаем замену модели (взаимоисключающие режимы)
        if is_checked:
            # Блокируем сигналы, чтобы избежать рекурсии
            self.replace_model_checkbox.blockSignals(True)
            self.replace_model_checkbox.setChecked(False)
            self.replace_model_checkbox.blockSignals(False)
        
        # Вызываем основной обработчик
        self.on_crit_hit_changed(is_checked)
    
    def _on_replace_model_state_changed(self, state: int) -> None:
        """Обработчик изменения состояния чекбокса замены модели"""
        is_checked = (state == Qt.Checked)
        
        # Если замена модели включается, всегда отключаем CritHIT (взаимоисключающие режимы)
        if is_checked:
            # Блокируем сигналы, чтобы избежать рекурсии
            self.crit_hit_checkbox.blockSignals(True)
            self.crit_hit_checkbox.setChecked(False)
            self.crit_hit_checkbox.blockSignals(False)
            # Восстанавливаем доступность элементов управления оружием
            self.class_combo.setEnabled(True)
            self.weapon_type_combo.setEnabled(True)
            self.weapon_combo.setEnabled(True)
        
        # Вызываем основной обработчик
        self.on_replace_model_changed(is_checked)
    
    def on_crit_hit_changed(self, is_crit_hit: bool) -> None:
        """Обработка изменения состояния CritHIT режима"""
        # Отключаем/включаем элементы управления
        self.class_combo.setEnabled(not is_crit_hit)
        self.weapon_type_combo.setEnabled(not is_crit_hit)
        self.weapon_combo.setEnabled(not is_crit_hit)
        
        # Уведомляем панель настроек для обновления её UI (включая скрытие UV разметки)
        if hasattr(self, 'settings_panel'):
            self.settings_panel.on_crit_hit_selected(is_crit_hit)
        
        # Автоматически применяем выбор
        self.apply_selection_auto()
    
    def on_replace_model_changed(self, is_enabled: bool) -> None:
        """Обработка изменения состояния замены модели"""
        # Просто сохраняем состояние чекбокса, диалог будет показан при сборке
        if not is_enabled:
            self.selected_smd_path = None
            self.replace_model_checkbox.setText(self.t['enable_replace_model'])
    
    def apply_selection_auto(self) -> None:
        """Автоматически применяет выбранное оружие"""
        # Проверяем CritHIT режим из локального чекбокса
        is_crit_hit = self.crit_hit_checkbox.isChecked()
        
        if is_crit_hit:
            self.mode = "critHIT"
            logger.info("Выбран CritHIT режим")
        elif self.current_class and self.current_weapon:
            self.mode = f"{self.current_class.lower()}_{self.current_weapon}"
            logger.debug(f"Выбрано оружие: {self.current_class} - {self.current_weapon}")
        else:
            self.mode = None
        
        # Обновляем резюме в превью
        self.update_preview_info()
    
    def update_preview_info(self) -> None:
        """Обновляет резюме информации в превью"""
        if hasattr(self, 'preview_panel'):
            self.preview_panel.update_info_summary()
    
    def create_weapon_folders(self) -> None:
        """Создает папки для всех оружий TF2, если они не существуют"""
        base_path = os.path.join("tools", "mod_data")
        
        for class_name, weapons in TF2_WEAPONS.items():
            for weapon_type, weapon_dict in weapons.items():
                for weapon_key, weapon_name in weapon_dict.items():
                    mode_key = f"{class_name.lower()}_{weapon_key}"
                    weapon_path = os.path.join(base_path, mode_key, "root")
                    
                    try:
                        # Создаем правильную структуру vgui/replay/thumbnails
                        vgui_path = os.path.join(weapon_path, "materials", "vgui", "replay", "thumbnails", "models", "workshop_partner", "weapons", "c_models", weapon_key)
                        
                        # Создаем папки по частям
                        path_parts = ["materials", "vgui", "replay", "thumbnails", "models", "workshop_partner", "weapons", "c_models", weapon_key]
                        current_path = weapon_path
                        
                        for part in path_parts:
                            current_path = os.path.join(current_path, part)
                            os.makedirs(current_path, exist_ok=True)
                        
                        # Создаем VMT файл если его нет
                        vmt_path = os.path.join(vgui_path, f"{weapon_key}.vmt")
                        if not os.path.exists(vmt_path):
                            try:
                                mode_key = f"{class_name.lower()}_{weapon_key}"
                                self.create_vmt_template(vmt_path, mode_key, class_name, weapon_type)
                            except (OSError, IOError) as e:
                                # Игнорируем ошибки создания файлов для оружия с очень длинными именами
                                if "No such file or directory" in str(e) or "path too long" in str(e).lower():
                                    logger.warning(f"Пропуск создания VMT для {weapon_key} (слишком длинный путь)")
                                else:
                                    logger.error(f"Ошибка создания VMT для {weapon_key}: {e}", exc_info=True)
                        
                        # Создаем VTF файл если его нет
                        vtf_path = os.path.join(vgui_path, f"c_{weapon_key}.vtf")
                        if not os.path.exists(vtf_path):
                            try:
                                # Создаем пустой VTF файл (будет заменен при генерации)
                                with open(vtf_path, 'wb') as f:
                                    f.write(b'')
                            except (OSError, IOError) as e:
                                # Игнорируем ошибки создания файлов для оружия с очень длинными именами
                                if "No such file or directory" in str(e) or "path too long" in str(e).lower():
                                    logger.warning(f"Пропуск создания VTF для {weapon_key} (слишком длинный путь)")
                                else:
                                    logger.error(f"Ошибка создания VTF для {weapon_key}: {e}", exc_info=True)
                                
                    except Exception as e:
                        logger.error(f"Ошибка создания папок для {weapon_key}: {e}", exc_info=True)
                        continue
    

    def create_vmt_template(self, vmt_path: str, weapon: str, class_name: str, weapon_type: str) -> None:
        """Создает VMT шаблон для оружия"""
        try:
            # Проверяем, является ли это специальным режимом
            if weapon in SPECIAL_MODES.values():
                if weapon == "critHIT":
                    # Для CritHIT используем простой шаблон
                    vmt_content = f'''"UnlitGeneric"
{{
\t"$basetexture" "effects/{weapon}"
\t"$additive" "1"
\t"$translucent" "1"
}}'''
                else:
                    # Для других специальных режимов
                    vmt_content = f'''"UnlitGeneric"
{{
\t"$basetexture" "effects/{weapon}"
\t"$additive" "1"
\t"$translucent" "1"
}}'''
            else:
                # Для обычного оружия - всегда используем VGUI структуру
                # Извлекаем имя оружия из режима (убираем префикс класса)
                weapon_name = weapon.split('_', 1)[1] if '_' in weapon else weapon
                texture_path = f"vgui/replay/thumbnails/models/workshop_partner/weapons/c_models/{weapon_name}"
                
                # Полный шаблон VMT с Proxies
                vmt_content = f'''"VertexLitGeneric"
{{
\t"$basetexture" "{texture_path}"
\t
\t"$phong" "1"
\t"$phongexponent" "25"
\t"$phongboost" "2.5"\t
\t
\t"$phongfresnelranges"\t"[.25 .5 20]"
\t"$halflambert" "1"

\t"$basemapalphaphongmask" "1"
\t
\t// Rim lighting parameters
\t"$rimlight" "1"\t\t\t\t\t\t
\t"$rimlightexponent" "4"\t\t
\t"$rimlightboost" "2"

\t"$glowcolor" "1"

\t// Cloaking
\t"$cloakPassEnabled" "1"
\t"$sheenPassEnabled" "1"

\t"$sheenmap" \t\t"cubemaps/cubemap_sheen001"
\t"$sheenmapmask" \t\t"Effects/AnimatedSheen/animatedsheen0"
\t"$sheenmaptint" \t\t"[ 1 1 1 ]"
\t"$sheenmapmaskframe" \t"0"
\t"$sheenindex" \t\t"0"

\t"$yellow" "0"

\t"Proxies"
\t{{
\t\t"AnimatedWeaponSheen"
\t\t{{
\t\t\t"animatedtexturevar" \t\t"$sheenmapmask"
\t\t\t"animatedtextureframenumvar" \t"$sheenmapmaskframe"
\t\t\t"animatedtextureframerate" \t\t"40"
\t\t}}
\t\t"invis"
\t\t{{
\t\t}}
\t\t"ModelGlowColor"
\t\t{{
\t\t\t"resultVar" "$glowcolor"
\t\t}}
\t\t"Equals"
\t\t{{
\t\t\t"srcVar1"  "$glowcolor"
\t\t\t"resultVar" "$selfillumtint"
\t\t}}
\t\t"Equals"
\t\t{{
\t\t\t"srcVar1"  "$glowcolor"
\t\t\t"resultVar" "$color2"
\t\t}}
\t\t"YellowLevel"
\t\t{{
\t\t\t"resultVar" "$yellow"
\t\t}}
\t\t"Multiply"
\t\t{{
\t\t\t"srcVar1" "$color2"
\t\t\t"srcVar2" "$yellow"
\t\t\t"resultVar" "$color2"
\t\t}}
\t}}
}}

// made on Tf2SkinGenerator https://steamcommunity.com/id/sosatihackeri - Developer(xiety)'''
            
            # Записываем VMT файл
            with open(vmt_path, 'w', encoding='utf-8') as f:
                f.write(vmt_content)
                
        except Exception as e:
            logger.error(f"Ошибка при создании VMT файла: {e}", exc_info=True)
    
    def get_weapon_paths(self, mode: str) -> Tuple[str, str, str, str]:
        """Возвращает пути для конкретного оружия"""
        if mode in SPECIAL_MODES.values():
            if mode == "critHIT":
                base_path = os.path.join("tools", "mod_data", "critHIT")
                rel_path = os.path.join("materials", "effects")
                vmt_filename = "crit.vmt"
                vtf_filename = "crit.vtf"
            else:
                # Для других специальных режимов
                base_path = os.path.join("tools", "mod_data", mode)
                rel_path = os.path.join("materials", "effects")
                vmt_filename = f"{mode}.vmt"
                vtf_filename = f"{mode}.vtf"
        else:
            # Для обычного оружия - всегда используем VGUI структуру
            base_path = os.path.join("tools", "mod_data", mode)
            weapon_name = mode.split('_', 1)[1] if '_' in mode else mode
            
            rel_path = os.path.join("materials", "vgui", "replay", "thumbnails", "models", "workshop_partner", "weapons", "c_models", f"c_{weapon_name}")
            vmt_filename = f"c_{weapon_name}.vmt"
            vtf_filename = f"c_{weapon_name}.vtf"
        
        return base_path, rel_path, vmt_filename, vtf_filename
    
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def change_language_from_combo(self, index: int) -> None:
        """Обработка изменения языка из настроек"""
        lang_code = 'ru' if index == 0 else 'en'
        
        # Сохраняем в конфиг
        from src.config.app_config import AppConfig
        AppConfig.set("language", lang_code)
        
        # Используем единый метод для установки языка
        self.set_language(lang_code)

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.preview_panel.load_image(path)

    def expert_mode_triggered(self) -> None:
        """Открывает редактор VMT для выбранного оружия"""
        if not hasattr(self, 'mode') or not self.mode:
            ErrorHandler.show_warning(self, "Сначала выберите оружие!", self.t['error'])
            return
        
        # Получаем weapon_key из mode
        weapon_key = self.mode.split('_', 1)[1] if '_' in self.mode else self.mode
        
        # Извлекаем оригинальный VMT из игры
        settings = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')
        
        if not tf2_root_dir:
            ErrorHandler.show_warning(self, "Не указан путь к игре TF2 в настройках!", self.t['error'])
            return
        
        # Извлекаем оригинальный VMT из игры
        vmt_path = self.extract_original_vmt_from_game(weapon_key, tf2_root_dir)
        
        if not vmt_path:
            error_msg = f"Не удалось извлечь оригинальный VMT файл для оружия {weapon_key}.\nПроверьте путь к игре TF2 в настройках."
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return
        
        # Открываем редактор с извлеченным VMT
        self.open_vmt_editor(vmt_path, weapon_key)
    
    def extract_original_vmt_from_game(self, weapon_key: str, tf2_root_dir: str) -> Optional[str]:
        """
        Извлекает оригинальный VMT файл из игры для оружия
        
        Пути поиска (в VPK без префикса materials/):
        - models/workshop_partner/weapons/c_models/{weapon_key}/ (с папкой)
        - models/workshop_partner/weapons/c_models/ (без папки, файл напрямую)
        - models/weapons/c_items/{weapon_key}/ (с папкой)
        - models/weapons/c_items/ (без папки, файл напрямую)
        
        Args:
            weapon_key: Ключ оружия (например, c_scattergun)
            tf2_root_dir: Корневая директория TF2
            
        Returns:
            Путь к извлеченному VMT файлу или None если не удалось извлечь
        """
        from src.services.tf2_vpk_extract_service import TF2VPKExtractService
        from src.services.tf2_paths import TF2Paths
        
        # Создаем временную директорию для извлечения
        temp_dir = os.path.join("tools", "temp_vmt_extract")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Получаем пути к VPK файлам
        tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
        try:
            _, tf2_misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        except FileNotFoundError:
            tf2_misc_vpk = None
        
        # Список путей для поиска VMT файла (в порядке приоритета)
        # В VPK файлах VMT находятся в materials/ директории
        search_paths = []
        
        if weapon_key.startswith('v_'):
            # Для v_ оружия
            search_paths = [
                f"materials/models/weapons/{weapon_key}",  # materials/models/weapons/v_weapon
                f"materials/models/workshop_partner/weapons/{weapon_key}",  # materials/models/workshop_partner/weapons/v_weapon
                f"models/weapons/{weapon_key}",  # Fallback без materials/
                f"models/workshop_partner/weapons/{weapon_key}",  # Fallback без materials/
            ]
        else:
            # Для c_ оружия пробуем несколько путей в порядке приоритета
            # Сначала с materials/, затем без (fallback)
            search_paths = [
                f"materials/models/workshop_partner/weapons/c_models/{weapon_key}",  # С папкой и materials/
                f"materials/models/workshop_partner/weapons/c_models/{weapon_key}/{weapon_key}",  # С полным путем
                f"materials/models/workshop/weapons/c_models/{weapon_key}",  # Альтернативный путь
                f"materials/models/weapons/c_models/{weapon_key}",  # Стандартный путь
                f"materials/models/weapons/c_items/{weapon_key}",  # c_items путь
                "materials/models/workshop_partner/weapons/c_models",  # Без папки (файл напрямую)
                "materials/models/weapons/c_items",  # Без папки в c_items
                # Fallback пути без materials/
                f"models/workshop_partner/weapons/c_models/{weapon_key}",  # С папкой
                "models/workshop_partner/weapons/c_models",  # Без папки (файл напрямую)
                f"models/weapons/c_items/{weapon_key}",  # С папкой в c_items
                "models/weapons/c_items",  # Без папки в c_items (файл напрямую)
            ]
        
        # Пробуем извлечь VMT по каждому пути
        vpk_files = []
        if tf2_textures_vpk:
            vpk_files.append(tf2_textures_vpk)
        if tf2_misc_vpk:
            vpk_files.append(tf2_misc_vpk)
        
        for cdmaterials_path in search_paths:
            for vpk_file in vpk_files:
                vmt_file = TF2VPKExtractService.extract_vmt_file(
                    vpk_file,
                    cdmaterials_path,
                    weapon_key,
                    temp_dir
                )
                if vmt_file and os.path.exists(vmt_file):
                    return vmt_file
        
        return None

    def open_vmt_editor(self, path: str, weapon_key: str = "") -> None:
        """Открывает редактор VMT файла"""
        dialog = VMTEditorDialog(self, path, weapon_key, self.t)
        dialog.exec()

    def build_vpk(self):
        """Запускает асинхронную сборку VPK"""
        try:
            if not hasattr(self, 'mode') or not self.mode:
                ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
                return
                
            settings = self.settings_panel.get_settings()
            name = settings['filename']
            if not name:
                ErrorHandler.show_warning(self, self.t['enter_name'], self.t['error'])
                return
            
            # Валидация имени файла
            is_valid, error_msg = validate_vpk_filename(name)
            if not is_valid:
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return

            size = settings['size']
            is_special_mode = self.mode in SPECIAL_MODES.values()
            # Для critHIT используем настройки пользователя (формат, флаги, опции)
            selected_format = settings['format']
            flags = settings['flags']
            vtf_options = settings.get('vtf_options', {})
            # UV разметка недоступна для CritHIT режима
            is_crit_hit = (hasattr(self, 'crit_hit_checkbox') and 
                          self.crit_hit_checkbox.isChecked())
            draw_uv_layout = settings.get('draw_uv_layout', False) and not is_special_mode and not is_crit_hit
            
            # Проверяем, используется ли VTF файл из preview_panel
            custom_vtf_path = self.preview_panel.get_vtf_path()
            from_path = None
            if not custom_vtf_path:
                from_path = self.preview_panel.get_image_path()
                if not from_path:
                    ErrorHandler.show_warning(self, self.t['load_image_error'], self.t['error'])
                    return
            
            # Получаем флаг замены модели (True если включен, диалог будет показан при сборке)
            replace_model_enabled = False
            if (hasattr(self, 'replace_model_checkbox') and 
                self.replace_model_checkbox.isChecked()):
                replace_model_enabled = True
            
            # Проверяем взаимоисключение режимов (на случай, если что-то пошло не так)
            is_crit_hit = (hasattr(self, 'crit_hit_checkbox') and 
                          self.crit_hit_checkbox.isChecked())
            if is_crit_hit and replace_model_enabled:
                # Если оба режима включены, отключаем замену модели
                logger.warning("Обнаружено одновременное включение CritHIT и замены модели. Отключаем замену модели.")
                self.replace_model_checkbox.blockSignals(True)
                self.replace_model_checkbox.setChecked(False)
                self.replace_model_checkbox.blockSignals(False)
                replace_model_enabled = False
            
            # Проверяем, не запущена ли уже сборка
            if hasattr(self, '_build_worker') and self._build_worker.isRunning():
                ErrorHandler.show_warning(
                    self, 
                    self.t.get('build_already_running', 'Build is already in progress. Please wait.'),
                    self.t['error']
                )
                return
            
            # Создаем и запускаем воркер для асинхронной сборки
            from src.services.build_worker import BuildWorker
            
            self._build_worker = BuildWorker(
                image_path=from_path,
                mode=self.mode,
                filename=name,
                size=size,
                format_type=selected_format,
                flags=flags,
                vtf_options=vtf_options,
                tf2_root_dir=settings.get('tf2_game_folder', ''),
                export_folder=settings.get('export_folder', 'export'),
                keep_temp_on_error=settings.get('keep_temp_on_error', False),
                debug_mode=settings.get('debug_mode', False),
                replace_model_enabled=replace_model_enabled,
                draw_uv_layout=draw_uv_layout,
                language=self.language,
                custom_vtf_path=custom_vtf_path,
                parent=self
            )
            
            # Подключаем сигналы
            self._build_worker.finished.connect(self._on_build_finished)
            self._build_worker.progress.connect(self._on_build_progress)
            self._build_worker.error.connect(self._on_build_error)
            if replace_model_enabled:
                self._build_worker.request_model_file.connect(self._on_request_model_file)
            
            # Создаем и показываем прогресс-диалог
            progress_text = self.t.get('build_progress_text', 'Building VPK...')
            cancel_text = self.t.get('cancel', 'Cancel')
            progress_title = self.t.get('build_progress_title', 'Build VPK')
            
            self._progress_dialog = QProgressDialog(progress_text, cancel_text, 0, 100, self)
            self._progress_dialog.setWindowTitle(progress_title)
            self._progress_dialog.setWindowModality(Qt.WindowModal)
            self._progress_dialog.setAutoClose(False)
            self._progress_dialog.setAutoReset(False)
            self._progress_dialog.canceled.connect(self._cancel_build)
            
            # Запускаем воркер
            self._build_worker.start()
            self._progress_dialog.show()
            
            # Отключаем кнопку сборки во время работы
            if hasattr(self.settings_panel, 'button'):
                self.settings_panel.button.setEnabled(False)

        except Exception as e:
            ErrorHandler.show_error(self, e, "Ошибка при запуске сборки VPK", self.t['build_error'])
    
    def _on_build_finished(self, success: bool, message: str):
        """Обработчик завершения сборки"""
        if hasattr(self, '_progress_dialog'):
            self._progress_dialog.close()
            self._progress_dialog = None
        
        # Включаем кнопку сборки обратно
        if hasattr(self.settings_panel, 'button'):
            self.settings_panel.button.setEnabled(True)
        
        if success:
            success_title = self.t.get('build_success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_error(self, Exception(message), "Ошибка сборки VPK", self.t['build_error'])
    
    def _on_build_progress(self, percentage: int, status: str):
        """Обработчик прогресса сборки"""
        if hasattr(self, '_progress_dialog'):
            self._progress_dialog.setValue(percentage)
            self._progress_dialog.setLabelText(status)
    
    def _on_build_error(self, error_message: str):
        """Обработчик ошибки сборки"""
        if hasattr(self, '_progress_dialog'):
            self._progress_dialog.close()
            self._progress_dialog = None
        
        # Включаем кнопку сборки обратно
        if hasattr(self.settings_panel, 'button'):
            self.settings_panel.button.setEnabled(True)
        
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка сборки VPK", self.t['error'])
    
    def _cancel_build(self) -> None:
        """Отменяет сборку"""
        if hasattr(self, '_build_worker') and self._build_worker.isRunning():
            self._build_worker.terminate()
            self._build_worker.wait()
            
            if hasattr(self, '_progress_dialog'):
                self._progress_dialog.close()
                self._progress_dialog = None
            
            # Включаем кнопку сборки обратно
            if hasattr(self.settings_panel, 'button'):
                self.settings_panel.button.setEnabled(True)
            
            cancelled_msg = self.t.get('build_cancelled', 'Build cancelled by user')
            ErrorHandler.show_info(self, cancelled_msg, self.t.get('cancel', 'Cancel'))
    
    def _on_request_model_file(self) -> None:
        """Обрабатывает запрос выбора файла модели из рабочего потока"""
        if not hasattr(self, '_build_worker'):
            return
        
        # Показываем диалог выбора SMD файла в главном потоке
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите SMD файл модели для замены",
            "",
            "SMD Files (*.smd);;All Files (*)"
        )
        
        # Устанавливаем результат в воркере
        if hasattr(self._build_worker, 'set_model_file_result'):
            self._build_worker.set_model_file_result(file_path if file_path else None)

    def extract_original_texture(self) -> None:
        """Запускает асинхронное извлечение оригинальной текстуры оружия из игры"""
        try:
            if not hasattr(self, 'mode') or not self.mode:
                ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
                return
            
            # Получаем weapon_key из mode
            weapon_key = self.mode.split('_', 1)[1] if '_' in self.mode else self.mode
            
            # Проверяем, что это не специальный режим
            from src.data.weapons import SPECIAL_MODES
            if self.mode in SPECIAL_MODES.values():
                error_msg = self.t.get('extract_texture_special_mode_error', 'Cannot extract texture for special modes')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return
            
            # Получаем путь к TF2
            settings = self.settings_panel.get_settings()
            tf2_root_dir = settings.get('tf2_game_folder', '')
            
            if not tf2_root_dir:
                error_msg = self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return
            
            # Получаем путь к tf2_textures_dir.vpk
            from src.services.tf2_paths import TF2Paths
            textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
            
            if not textures_vpk:
                error_msg = self.t.get('textures_vpk_not_found', 'tf2_textures_dir.vpk not found')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return
            
            # Получаем папку экспорта и формат
            export_folder = settings.get('export_folder', 'export')
            from src.config.app_config import AppConfig
            config = AppConfig.load_config()
            export_format = config.get('export_image_format', 'PNG')
            
            # Проверяем, не запущено ли уже извлечение
            if hasattr(self, '_extract_worker') and self._extract_worker.isRunning():
                error_msg = self.t.get('extract_already_running', 'Extraction is already in progress. Please wait.')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return
            
            # Создаем и запускаем воркер для асинхронного извлечения
            from src.services.extract_texture_worker import ExtractTextureWorker
            
            self._extract_worker = ExtractTextureWorker(
                textures_vpk_path=textures_vpk,
                weapon_key=weapon_key,
                export_folder=export_folder,
                export_format=export_format,
                language=self.language,
                parent=self
            )
            
            # Подключаем сигналы
            self._extract_worker.finished.connect(self._on_extract_finished)
            self._extract_worker.progress.connect(self._on_extract_progress)
            self._extract_worker.error.connect(self._on_extract_error)
            
            # Создаем и показываем прогресс-диалог
            progress_text = self.t.get('extract_progress_text', 'Extracting texture...')
            cancel_text = self.t.get('cancel', 'Cancel')
            progress_title = self.t.get('extract_progress_title', 'Extract Texture')
            
            self._extract_progress_dialog = QProgressDialog(progress_text, cancel_text, 0, 100, self)
            self._extract_progress_dialog.setWindowTitle(progress_title)
            self._extract_progress_dialog.setWindowModality(Qt.WindowModal)
            self._extract_progress_dialog.setAutoClose(False)
            self._extract_progress_dialog.setAutoReset(False)
            self._extract_progress_dialog.canceled.connect(self._cancel_extract)
            
            # Запускаем воркер
            self._extract_worker.start()
            self._extract_progress_dialog.show()
            
            # Отключаем кнопку извлечения во время работы
            if hasattr(self.settings_panel, 'extract_texture_button'):
                self.settings_panel.extract_texture_button.setEnabled(False)
        
        except Exception as e:
            ErrorHandler.show_error(self, e, "Ошибка при запуске извлечения текстуры", self.t['error'])
    
    def _on_extract_finished(self, success: bool, message: str) -> None:
        """Обработчик завершения извлечения текстуры"""
        if hasattr(self, '_extract_progress_dialog'):
            self._extract_progress_dialog.close()
            self._extract_progress_dialog = None
        
        # Включаем кнопку извлечения обратно
        if hasattr(self.settings_panel, 'extract_texture_button'):
            self.settings_panel.extract_texture_button.setEnabled(True)
        
        if success:
            success_title = self.t.get('success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_warning(self, message, self.t['error'])
    
    def _on_extract_progress(self, percentage: int, status: str):
        """Обработчик прогресса извлечения текстуры"""
        if hasattr(self, '_extract_progress_dialog'):
            self._extract_progress_dialog.setValue(percentage)
            self._extract_progress_dialog.setLabelText(status)
    
    def _on_extract_error(self, error_message: str):
        """Обработчик ошибки извлечения текстуры"""
        if hasattr(self, '_extract_progress_dialog'):
            self._extract_progress_dialog.close()
            self._extract_progress_dialog = None
        
        # Включаем кнопку извлечения обратно
        if hasattr(self.settings_panel, 'extract_texture_button'):
            self.settings_panel.extract_texture_button.setEnabled(True)
        
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка извлечения текстуры", self.t['error'])
    
    def _cancel_extract(self) -> None:
        """Отменяет извлечение текстуры"""
        if hasattr(self, '_extract_worker') and self._extract_worker.isRunning():
            self._extract_worker.terminate()
            self._extract_worker.wait()
            
            if hasattr(self, '_extract_progress_dialog'):
                self._extract_progress_dialog.close()
                self._extract_progress_dialog = None
            
            # Включаем кнопку извлечения обратно
            if hasattr(self.settings_panel, 'extract_texture_button'):
                self.settings_panel.extract_texture_button.setEnabled(True)
            
            cancelled_msg = self.t.get('extract_cancelled', 'Extraction cancelled by user')
            ErrorHandler.show_info(self, cancelled_msg, self.t.get('cancel', 'Cancel'))
    
    def merge_vpk_files(self) -> None:
        """Открывает диалог объединения VPK файлов"""
        from src.ui.merge_vpk_dialog import MergeVPKDialog
        from src.services.merge_vpk_service import MergeVPKService
        from src.shared.validators import validate_vpk_filename
        
        # Открываем диалог выбора модов
        dialog = MergeVPKDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Получаем выбранные файлы
        selected_files = dialog.get_selected_files()
        if not selected_files:
            ErrorHandler.show_warning(self, self.t.get('no_vpk_files_selected', 'No VPK files selected'), self.t['error'])
            return
        
        # Запрашиваем имя выходного файла
        from PySide6.QtWidgets import QInputDialog
        filename, ok = QInputDialog.getText(
            self,
            self.t.get('merge_vpk_title', 'Объединить моды'),
            self.t.get('enter_output_filename', 'Введите имя выходного файла:'),
            text="merged_mod.vpk"
        )
        
        if not ok or not filename:
            return
        
        # Валидация имени файла
        if not filename.endswith('.vpk'):
            filename += '.vpk'
        
        is_valid, error_msg = validate_vpk_filename(filename)
        if not is_valid:
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return
        
        # Получаем настройки
        settings = self.settings_panel.get_settings()
        export_folder = settings.get('export_folder', 'export')
        
        # Проверяем наличие дубликатов оружий
        duplicates = MergeVPKService.check_duplicate_weapons(selected_files)
        if duplicates:
            # Формируем сообщение о дубликатах
            duplicate_msg = self.t.get('duplicate_weapons_warning', 
                'Обнаружены дубликаты оружий:\n\n')
            
            for weapon_name, vpk_files in duplicates.items():
                duplicate_msg += f"• {weapon_name}: {', '.join(vpk_files)}\n"
            
            duplicate_msg += "\n" + self.t.get('duplicate_weapons_question', 
                'Вы пытаетесь соединить моды, которые влияют на одно оружие.\nПродолжить?')
            
            # Показываем диалог подтверждения
            reply = QMessageBox.question(
                self,
                self.t.get('duplicate_weapons_title', 'Дубликаты оружий'),
                duplicate_msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return  # Останавливаем процесс
        
        # Проверяем, не запущено ли уже объединение
        if hasattr(self, '_merge_worker') and self._merge_worker.isRunning():
            ErrorHandler.show_warning(
                self,
                self.t.get('merge_already_running', 'Объединение уже выполняется. Пожалуйста, подождите.'),
                self.t['error']
            )
            return
        
        # Создаем и показываем прогресс-диалог
        progress_text = self.t.get('merge_vpk_progress', 'Объединение VPK файлов...')
        cancel_text = self.t.get('cancel', 'Cancel')
        progress_title = self.t.get('merge_vpk_title', 'Объединить моды')
        
        self._merge_progress_dialog = QProgressDialog(progress_text, cancel_text, 0, 100, self)
        self._merge_progress_dialog.setWindowTitle(progress_title)
        self._merge_progress_dialog.setWindowModality(Qt.WindowModal)
        self._merge_progress_dialog.setAutoClose(False)
        self._merge_progress_dialog.setAutoReset(False)
        self._merge_progress_dialog.canceled.connect(self._cancel_merge)
        
        # Выполняем объединение в отдельном потоке
        from PySide6.QtCore import QThread, Signal
        
        class MergeWorker(QThread):
            finished = Signal(bool, str)
            progress = Signal(int, str)
            
            def __init__(self, vpk_files, filename, export_folder, language, translations):
                super().__init__()
                self.vpk_files = vpk_files
                self.filename = filename
                self.export_folder = export_folder
                self.language = language
                self.t = translations
            
            def run(self):
                try:
                    self.progress.emit(10, self.t.get('merge_vpk_extracting', 'Извлечение файлов...'))
                    success, message = MergeVPKService.merge_vpk_files(
                        self.vpk_files,
                        self.filename,
                        self.export_folder,
                        self.language
                    )
                    self.progress.emit(100, self.t.get('merge_vpk_completed', 'Завершено'))
                    self.finished.emit(success, message)
                except Exception as e:
                    # Используем get_logger напрямую, чтобы избежать циклических импортов
                    from src.shared.logging_config import get_logger
                    worker_logger = get_logger(__name__)
                    worker_logger.error(f"Ошибка в MergeWorker: {e}", exc_info=True)
                    self.finished.emit(False, str(e))
        
        # Создаем и сохраняем worker как атрибут класса
        self._merge_worker = MergeWorker(selected_files, filename, export_folder, self.language, self.t)
        
        # Подключаем сигналы
        self._merge_worker.finished.connect(self._on_merge_finished)
        self._merge_worker.progress.connect(self._on_merge_progress)
        
        # Запускаем worker
        self._merge_worker.start()
        self._merge_progress_dialog.show()
        
        # Отключаем кнопку объединения во время работы
        if hasattr(self.settings_panel, 'merge_vpk_button'):
            self.settings_panel.merge_vpk_button.setEnabled(False)
    
    def _on_merge_finished(self, success: bool, message: str):
        """Обработчик завершения объединения VPK"""
        if hasattr(self, '_merge_progress_dialog'):
            self._merge_progress_dialog.close()
            self._merge_progress_dialog = None
        
        # Включаем кнопку объединения обратно
        if hasattr(self.settings_panel, 'merge_vpk_button'):
            self.settings_panel.merge_vpk_button.setEnabled(True)
        
        if success:
            ErrorHandler.show_info(self, message, self.t.get('merge_vpk_title', 'Объединить моды'))
        else:
            ErrorHandler.show_error(self, Exception(message), "Ошибка объединения VPK", self.t['error'])
    
    def _on_merge_progress(self, percentage: int, status: str):
        """Обработчик прогресса объединения VPK"""
        if hasattr(self, '_merge_progress_dialog'):
            self._merge_progress_dialog.setValue(percentage)
            self._merge_progress_dialog.setLabelText(status)
    
    def _cancel_merge(self) -> None:
        """Отменяет объединение VPK"""
        if hasattr(self, '_merge_worker') and self._merge_worker.isRunning():
            self._merge_worker.terminate()
            self._merge_worker.wait()
            
            if hasattr(self, '_merge_progress_dialog'):
                self._merge_progress_dialog.close()
                self._merge_progress_dialog = None
            
            # Включаем кнопку объединения обратно
            if hasattr(self.settings_panel, 'merge_vpk_button'):
                self.settings_panel.merge_vpk_button.setEnabled(True)
            
            cancelled_msg = self.t.get('merge_cancelled', 'Объединение отменено пользователем')
            ErrorHandler.show_info(self, cancelled_msg, self.t.get('cancel', 'Cancel'))
    
    def open_support_link(self) -> None:
        QDesktopServices.openUrl(QUrl("https://steamcommunity.com/tradeoffer/new/?partner=394814324&token=GNGCagXk"))
    
    def open_settings_dialog(self) -> None:
        """Открывает диалог настроек"""
        dialog = SettingsDialog(self)
        dialog.exec()

    def set_language(self, lang):
        self.language = lang
        self.t = TRANSLATIONS[lang]
        self.settings_panel.update_language(self.t)
        self.update_ui_text()
    
    def on_advanced_section_toggled(self, is_expanded):
        """Обработка сворачивания/разворачивания секции Дополнительно"""
        # Даём время на обновление layout
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._adjust_window_size)
    
    def _adjust_window_size(self) -> None:
        """Пересчитывает и применяет оптимальный размер окна"""
        # Обновляем layout
        self.centralWidget().updateGeometry()
        self.centralWidget().layout().activate()
        
        # Получаем минимальный необходимый размер
        hint = self.centralWidget().sizeHint()
        
        # Применяем новый размер с сохранением ширины
        current_width = self.width()
        new_height = max(hint.height() + 20, 600)  # Минимум 600px
        
        self.resize(current_width, new_height)
    