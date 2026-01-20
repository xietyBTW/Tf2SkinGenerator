#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                QHBoxLayout, QLabel, QComboBox, QPushButton, 
                                QFileDialog, QLineEdit, QTextEdit, QCheckBox,
                                QMessageBox, QGroupBox)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from src.data.weapons import TF2_WEAPONS
from src.config.app_config import AppConfig
from src.services.vpk_service import VPKService
from PIL import Image


class TestWorker(QThread):
    progress = Signal(str)
    finished = Signal(dict)
    
    def __init__(self, class_name, replace_model_enabled, model_path, 
                 texture_path, texture_name, size, format_type, flags, tf2_root_dir):
        super().__init__()
        self.class_name = class_name
        self.replace_model_enabled = replace_model_enabled
        self.model_path = model_path
        self.texture_path = texture_path
        self.texture_name = texture_name
        self.size = size
        self.format_type = format_type
        self.flags = flags
        self.tf2_root_dir = tf2_root_dir
        self.cancel_requested = False
        
    def run(self):
        results = {"success": [], "failed": []}
        
        export_dir = "exportTest"
        os.makedirs(export_dir, exist_ok=True)
        
        weapons_to_test = []
        if self.class_name in TF2_WEAPONS:
            for weapon_type, weapons in TF2_WEAPONS[self.class_name].items():
                for weapon_key in weapons.keys():
                    mode = f"{self.class_name.lower()}_{weapon_key}"
                    weapons_to_test.append((mode, weapon_key))
        
        total_weapons = len(weapons_to_test)
        self.progress.emit(f"Найдено оружий для теста: {total_weapons}")
        
        test_image_path = self._create_test_image()
        if not test_image_path:
            self.finished.emit({"success": [], "failed": [("Setup", "Не удалось создать тестовое изображение")]})
            return
        
        for index, (mode, weapon_key) in enumerate(weapons_to_test, 1):
            if self.cancel_requested:
                self.progress.emit("Тест отменен пользователем")
                break
                
            self.progress.emit(f"[{index}/{total_weapons}] Тестируем {weapon_key}...")
            
            try:
                temp_filename = f"test_{weapon_key}.vpk"
                filename = f"{index}.vpk"
                
                model_path_for_test = None
                if self.replace_model_enabled:
                    if self.model_path and os.path.exists(self.model_path):
                        model_path_for_test = self.model_path
                    else:
                        results["failed"].append((weapon_key, "Файл модели не найден"))
                        self.progress.emit(f"[{index}/{total_weapons}] ✗ {weapon_key} - Файл модели не найден")
                        continue
                
                success, message = VPKService.build_vpk(
                    image_path=test_image_path,
                    mode=mode,
                    filename=temp_filename,
                    size=self.size,
                    format_type=self.format_type,
                    flags=self.flags,
                    tf2_root_dir=self.tf2_root_dir,
                    keep_temp_on_error=False,
                    debug_mode=False,
                    replace_model_enabled=self.replace_model_enabled,
                    parent_window=None,
                    replace_model_path=model_path_for_test
                )
                
                if success:
                    source_path = os.path.join("export", temp_filename)
                    dest_path = os.path.join("exportTest", filename)
                    try:
                        if os.path.exists(source_path):
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                            os.rename(source_path, dest_path)
                            results["success"].append(weapon_key)
                            self.progress.emit(f"[{index}/{total_weapons}] ✓ {weapon_key} - Успешно")
                        else:
                            results["failed"].append((weapon_key, "Файл не найден после сборки"))
                            self.progress.emit(f"[{index}/{total_weapons}] ✗ {weapon_key} - Файл не найден после сборки")
                    except Exception as e:
                        results["failed"].append((weapon_key, f"Ошибка перемещения файла: {str(e)}"))
                        self.progress.emit(f"[{index}/{total_weapons}] ✗ {weapon_key} - Ошибка перемещения: {str(e)}")
                else:
                    results["failed"].append((weapon_key, message))
                    self.progress.emit(f"[{index}/{total_weapons}] ✗ {weapon_key} - Ошибка: {message}")
                    
            except Exception as e:
                error_msg = str(e)
                results["failed"].append((weapon_key, error_msg))
                self.progress.emit(f"[{index}/{total_weapons}] ✗ {weapon_key} - Исключение: {error_msg}")
        
        if os.path.exists(test_image_path):
            try:
                os.remove(test_image_path)
            except:
                pass
        
        self.finished.emit(results)
    
    def _create_test_image(self):
        if not self.texture_path or not os.path.exists(self.texture_path):
            return None
        
        try:
            img = Image.open(self.texture_path)
            img = img.convert("RGBA").resize(self.size)
            
            temp_path = os.path.join("tools", "temp", "test_texture.png")
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            img.save(temp_path)
            
            return temp_path
        except Exception as e:
            print(f"Ошибка создания тестового изображения: {e}")
            return None
    
    def cancel(self):
        self.cancel_requested = True


class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.test_worker = None
        
        from src.core.app_factory import AppFactory
        icon_path = AppFactory.get_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))
        
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        self.setWindowTitle("TF2 Skin Generator - Тестовое приложение")
        self.setMinimumSize(600, 700)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        settings_group = QGroupBox("Настройки теста")
        settings_layout = QVBoxLayout()
        
        class_layout = QHBoxLayout()
        class_layout.addWidget(QLabel("Класс:"))
        self.class_combo = QComboBox()
        self.class_combo.addItems(TF2_WEAPONS.keys())
        class_layout.addWidget(self.class_combo)
        settings_layout.addLayout(class_layout)
        
        function_layout = QHBoxLayout()
        self.replace_model_checkbox = QCheckBox("Замена модели")
        function_layout.addWidget(self.replace_model_checkbox)
        settings_layout.addLayout(function_layout)
        
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Модель (SMD):"))
        self.model_path_edit = QLineEdit()
        self.model_path_edit.setPlaceholderText("Выберите файл модели...")
        model_browse_btn = QPushButton("Обзор...")
        model_browse_btn.clicked.connect(self.browse_model)
        model_layout.addWidget(self.model_path_edit)
        model_layout.addWidget(model_browse_btn)
        settings_layout.addLayout(model_layout)
        self.model_path_edit.setEnabled(False)
        self.replace_model_checkbox.toggled.connect(lambda checked: self.model_path_edit.setEnabled(checked))
        
        texture_layout = QHBoxLayout()
        texture_layout.addWidget(QLabel("Текстура:"))
        self.texture_path_edit = QLineEdit()
        self.texture_path_edit.setPlaceholderText("Выберите файл текстуры...")
        texture_browse_btn = QPushButton("Обзор...")
        texture_browse_btn.clicked.connect(self.browse_texture)
        texture_layout.addWidget(self.texture_path_edit)
        texture_layout.addWidget(texture_browse_btn)
        settings_layout.addLayout(texture_layout)
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Название (для справки):"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Введите название...")
        name_layout.addWidget(self.name_edit)
        settings_layout.addLayout(name_layout)
        
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Размер текстуры:"))
        self.size_combo = QComboBox()
        self.size_combo.addItems(["256", "512", "1024", "2048"])
        self.size_combo.setCurrentText("512")
        size_layout.addWidget(self.size_combo)
        settings_layout.addLayout(size_layout)
        
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Формат:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["DXT1", "DXT5", "RGBA8888"])
        self.format_combo.setCurrentText("DXT1")
        format_layout.addWidget(self.format_combo)
        settings_layout.addLayout(format_layout)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Начать тест")
        self.start_btn.clicked.connect(self.start_test)
        self.cancel_btn = QPushButton("Отменить")
        self.cancel_btn.clicked.connect(self.cancel_test)
        self.cancel_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)
        
        log_label = QLabel("Лог теста:")
        layout.addWidget(log_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        layout.addWidget(self.log_text)
        
        results_label = QLabel("Результаты:")
        layout.addWidget(results_label)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMinimumHeight(150)
        layout.addWidget(self.results_text)
    
    def browse_model(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл модели (SMD)",
            "",
            "SMD Files (*.smd);;All Files (*)"
        )
        if file_path:
            self.model_path_edit.setText(file_path)
    
    def browse_texture(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл текстуры",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if file_path:
            self.texture_path_edit.setText(file_path)
    
    def load_config(self):
        config = AppConfig.load_config()
    
    def start_test(self):
        if not self.texture_path_edit.text():
            QMessageBox.warning(self, "Ошибка", "Выберите файл текстуры!")
            return
        
        if not os.path.exists(self.texture_path_edit.text()):
            QMessageBox.warning(self, "Ошибка", "Файл текстуры не найден!")
            return
        
        if self.replace_model_checkbox.isChecked():
            if not self.model_path_edit.text():
                QMessageBox.warning(self, "Ошибка", "Выберите файл модели для замены!")
                return
            
            if not os.path.exists(self.model_path_edit.text()):
                QMessageBox.warning(self, "Ошибка", "Файл модели не найден!")
                return
        
        config = AppConfig.load_config()
        tf2_root_dir = config.get('tf2_game_folder', '')
        
        if not tf2_root_dir:
            QMessageBox.warning(self, "Ошибка", 
                              "Не указан путь к TF2 в настройках!\n"
                              "Запустите основное приложение и укажите путь в настройках.")
            return
        
        class_name = self.class_combo.currentText()
        replace_model_enabled = self.replace_model_checkbox.isChecked()
        model_path = self.model_path_edit.text() if replace_model_enabled else None
        texture_path = self.texture_path_edit.text()
        size = (int(self.size_combo.currentText()), int(self.size_combo.currentText()))
        format_type = self.format_combo.currentText()
        flags = []
        
        self.log_text.clear()
        self.results_text.clear()
        
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        
        self.test_worker = TestWorker(
            class_name=class_name,
            replace_model_enabled=replace_model_enabled,
            model_path=model_path,
            texture_path=texture_path,
            texture_name=self.name_edit.text(),
            size=size,
            format_type=format_type,
            flags=flags,
            tf2_root_dir=tf2_root_dir
        )
        
        self.test_worker.progress.connect(self.on_progress)
        self.test_worker.finished.connect(self.on_finished)
        self.test_worker.start()
    
    def cancel_test(self):
        if self.test_worker and self.test_worker.isRunning():
            self.test_worker.cancel()
            self.test_worker.wait()
            self.log_text.append("Тест отменен пользователем")
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
    
    def on_progress(self, message):
        self.log_text.append(message)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def on_finished(self, results):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        success_count = len(results["success"])
        failed_count = len(results["failed"])
        total_count = success_count + failed_count
        
        results_text = f"=== РЕЗУЛЬТАТЫ ТЕСТА ===\n\n"
        results_text += f"Всего протестировано: {total_count}\n"
        results_text += f"Успешно: {success_count}\n"
        results_text += f"Ошибок: {failed_count}\n\n"
        
        if results["success"]:
            results_text += "✓ УСПЕШНО СОЗДАННЫЕ ОРУЖИЯ:\n"
            for weapon in results["success"]:
                results_text += f"  • {weapon}\n"
            results_text += "\n"
        
        if results["failed"]:
            results_text += "✗ ОРУЖИЯ С ОШИБКАМИ:\n"
            for weapon, error in results["failed"]:
                results_text += f"  • {weapon}: {error[:100]}\n"
                if len(error) > 100:
                    results_text += f"    ... ({len(error) - 100} символов еще)\n"
        
        self.results_text.setPlainText(results_text)
        
        QMessageBox.information(
            self,
            "Тест завершен",
            f"Тест завершен!\n\n"
            f"Успешно: {success_count}/{total_count}\n"
            f"Ошибок: {failed_count}/{total_count}"
        )


def main():
    try:
        from src.core.app_factory import AppFactory
        
        app = AppFactory.create_app(apply_theme=True)
        
        window = TestWindow()
        window.show()
        
        sys.exit(app.exec())
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА при запуске приложения: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

