#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                QHBoxLayout, QLabel, QComboBox, QPushButton,
                                QFileDialog, QLineEdit, QTextEdit, QCheckBox,
                                QMessageBox, QGroupBox, QTabWidget)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from src.data.weapons import TF2_WEAPONS, SPECIAL_MODES, WEAPON_TEXTURE_PATHS
from src.config.app_config import AppConfig
from src.services.vpk_service import VPKService
from src.services.tf2_paths import TF2Paths
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


# ── Воркер проверки текстур ───────────────────────────────────────────────────

# Корневые папки глубокого поиска (в порядке приоритета — как у MDL моделей)
_DEEP_SEARCH_ROOTS = [
    "materials/models/workshop_partner/",
    "materials/models/workshop/",
    "materials/models/weapons/",
]

# Шаблоны обычного (быстрого) поиска — те же корни, конкретные подпапки
# {weapon_key}, {base_key} (без c_), {parent_key} (c_base без суффикса)
_TEXTURE_SEARCH_TEMPLATES = [
    # workshop_partner — наивысший приоритет
    "materials/models/workshop_partner/weapons/c_models/{weapon_key}",
    "materials/models/workshop_partner/weapons/c_models/{parent_key}",
    # workshop
    "materials/models/workshop/weapons/c_models/{weapon_key}",
    "materials/models/workshop/weapons/c_models/{parent_key}",
    # weapons — базовые пути
    "materials/models/weapons/c_models/{weapon_key}",
    "materials/models/weapons/c_models/{parent_key}",
    "materials/models/weapons/c_items/{weapon_key}",
    "materials/models/weapons/c_items",          # плоский (без подпапки)
    "materials/models/weapons/v_{base_key}",     # старый v_-viewmodel
    "materials/models/weapons/{weapon_key}",     # w_-world-model и прочие
]


class TextureCheckWorker(QThread):
    progress = Signal(str)
    finished = Signal(dict)
    # dict: {"found": [...], "missing": [...], "deep": {weapon_key: [actual_paths]}}

    def __init__(self, textures_vpk: str, class_filter: str, deep_search: bool = False):
        super().__init__()
        self.textures_vpk = textures_vpk
        self.class_filter = class_filter
        self.deep_search = deep_search

    def run(self):
        try:
            import vpk as _vpk
        except ImportError:
            self.progress.emit("ОШИБКА: библиотека vpk не установлена")
            self.finished.emit({"found": [], "missing": [], "deep": {}})
            return

        if not os.path.isfile(self.textures_vpk):
            self.progress.emit(f"ОШИБКА: файл не найден: {self.textures_vpk}")
            self.finished.emit({"found": [], "missing": [], "deep": {}})
            return

        self.progress.emit(f"Открываем VPK: {self.textures_vpk}")
        try:
            vpk_file = _vpk.open(self.textures_vpk)
        except Exception as e:
            self.progress.emit(f"ОШИБКА открытия VPK: {e}")
            self.finished.emit({"found": [], "missing": [], "deep": {}})
            return

        # Собираем список оружий
        special_keys = set(SPECIAL_MODES.values())
        weapons = []
        for class_name, categories in TF2_WEAPONS.items():
            if self.class_filter and class_name != self.class_filter:
                continue
            for category, weapon_dict in categories.items():
                if category == "Hands":
                    continue
                for weapon_key, names in weapon_dict.items():
                    if weapon_key in special_keys or weapon_key == "hands":
                        continue
                    weapons.append((class_name, category, weapon_key, names.get("en", weapon_key)))

        seen = set()
        unique_weapons = []
        for item in weapons:
            if item[2] not in seen:
                seen.add(item[2])
                unique_weapons.append(item)

        found = []
        missing = []
        total = len(unique_weapons)
        self.progress.emit(f"Проверяем {total} оружий...\n")

        for idx, (class_name, category, weapon_key, name_en) in enumerate(unique_weapons, 1):
            if self.isInterruptionRequested():
                break

            base_key  = weapon_key[2:] if weapon_key.startswith("c_") else weapon_key
            _p        = base_key.rsplit("_", 1)
            parent_key = ("c_" + _p[0]) if len(_p) == 2 else weapon_key

            vtf_names = list(dict.fromkeys([
                f"{weapon_key}.vtf",
                f"{weapon_key}_red.vtf",
                f"{weapon_key}_blue.vtf",
                f"v_{base_key}.vtf",
            ] + ([f"c_{weapon_key}.vtf"] if not weapon_key.startswith("c_") else [])))

            found_path = None

            # Сначала проверяем явные переопределения
            if weapon_key in WEAPON_TEXTURE_PATHS:
                for override_path in WEAPON_TEXTURE_PATHS[weapon_key]:
                    if override_path in vpk_file:
                        found_path = override_path
                        break

            # Затем стандартный поиск по шаблонам
            if not found_path:
                for tpl in _TEXTURE_SEARCH_TEMPLATES:
                    try:
                        folder = tpl.format(
                            weapon_key=weapon_key,
                            base_key=base_key,
                            parent_key=parent_key,
                        )
                    except KeyError:
                        continue
                    for vtf_name in vtf_names:
                        rel = f"{folder}/{vtf_name}"
                        if rel in vpk_file:
                            found_path = rel
                            break
                    if found_path:
                        break

            if found_path:
                found.append((weapon_key, name_en, class_name, category, found_path))
                self.progress.emit(f"[{idx}/{total}] ✔  {weapon_key} ({name_en})")
            else:
                missing.append((weapon_key, name_en, class_name, category))
                self.progress.emit(f"[{idx}/{total}] ✘  {weapon_key} ({name_en}) — не найдено")

        if hasattr(vpk_file, "close"):
            try:
                vpk_file.close()
            except Exception:
                pass

        # ── Глубокий поиск для ненайденных ──────────────────────────────── #
        deep_results: dict[str, list[str]] = {}
        if self.deep_search and missing:
            self.progress.emit(
                f"\nГлубокий поиск: строю индекс VPK ({len(missing)} ненайденных)..."
            )
            try:
                vpk_file2 = _vpk.open(self.textures_vpk)

                # Собираем только VTF внутри разрешённых корней (однократный обход)
                scoped_vtf: list[str] = []
                for path in vpk_file2:
                    if not path.endswith(".vtf"):
                        continue
                    for root in _DEEP_SEARCH_ROOTS:
                        if path.startswith(root):
                            scoped_vtf.append(path)
                            break

                if hasattr(vpk_file2, "close"):
                    try:
                        vpk_file2.close()
                    except Exception:
                        pass

                self.progress.emit(
                    f"Индекс построен: {len(scoped_vtf)} VTF-файлов в разрешённых путях\n"
                )

                def _priority(path: str) -> int:
                    """Сортировка по приоритету: workshop_partner=0, workshop=1, weapons=2."""
                    for i, root in enumerate(_DEEP_SEARCH_ROOTS):
                        if path.startswith(root):
                            return i
                    return 99

                for weapon_key, name_en, class_name, category in missing:
                    if self.isInterruptionRequested():
                        break

                    base_key = weapon_key[2:] if weapon_key.startswith("c_") else weapon_key

                    # Ищем VTF, имя файла (без расширения) содержит weapon_key
                    matches = [
                        p for p in scoped_vtf
                        if weapon_key in p.split("/")[-1]
                           or base_key == p.split("/")[-1].replace(".vtf", "")
                    ]
                    # Сортируем по приоритету корня
                    matches.sort(key=_priority)
                    deep_results[weapon_key] = matches

                    if matches:
                        self.progress.emit(f"  🔍 {weapon_key} → {len(matches)} совпадений:")
                        for m in matches:
                            self.progress.emit(f"       {m}")
                    else:
                        self.progress.emit(f"  🔍 {weapon_key} → ОТСУТСТВУЕТ в разрешённых путях")

            except Exception as e:
                self.progress.emit(f"ОШИБКА глубокого поиска: {e}")

        self.finished.emit({"found": found, "missing": missing, "deep": deep_results})


# ── Главное окно ──────────────────────────────────────────────────────────────

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.test_worker = None
        self.texture_check_worker = None

        from src.core.app_factory import AppFactory
        icon_path = AppFactory.get_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        self.init_ui()
        self.load_config()

    def init_ui(self):
        self.setWindowTitle("TF2 Skin Generator - Тестовое приложение")
        self.setMinimumSize(640, 720)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_vpk_tab(), "Сборка VPK")
        self.tabs.addTab(self._build_texture_check_tab(), "Проверка текстур")

    # ── Вкладка 1: сборка VPK (существующий функционал) ─────────────────── #

    def _build_vpk_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

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
        self.replace_model_checkbox.toggled.connect(
            lambda checked: self.model_path_edit.setEnabled(checked)
        )

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

        layout.addWidget(QLabel("Лог теста:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(180)
        layout.addWidget(self.log_text)

        layout.addWidget(QLabel("Результаты:"))
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMinimumHeight(130)
        layout.addWidget(self.results_text)

        return tab

    # ── Вкладка 2: проверка текстур ──────────────────────────────────────── #

    def _build_texture_check_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        cfg_group = QGroupBox("Параметры проверки")
        cfg_layout = QVBoxLayout()

        tf2_row = QHBoxLayout()
        tf2_row.addWidget(QLabel("Папка TF2:"))
        self.tc_tf2_edit = QLineEdit()
        self.tc_tf2_edit.setPlaceholderText("Путь к корневой папке TF2...")
        tf2_browse_btn = QPushButton("Обзор...")
        tf2_browse_btn.clicked.connect(self._tc_browse_tf2)
        tf2_row.addWidget(self.tc_tf2_edit)
        tf2_row.addWidget(tf2_browse_btn)
        cfg_layout.addLayout(tf2_row)

        class_row = QHBoxLayout()
        class_row.addWidget(QLabel("Класс:"))
        self.tc_class_combo = QComboBox()
        self.tc_class_combo.addItem("Все классы", "")
        for cls in TF2_WEAPONS.keys():
            self.tc_class_combo.addItem(cls, cls)
        class_row.addWidget(self.tc_class_combo)
        class_row.addStretch()
        cfg_layout.addLayout(class_row)

        # Опция глубокого поиска
        self.tc_deep_checkbox = QCheckBox(
            "Глубокий поиск для ненайденных  "
            "(сканирует весь VPK — медленно, но показывает реальный путь)"
        )
        cfg_layout.addWidget(self.tc_deep_checkbox)

        cfg_group.setLayout(cfg_layout)
        layout.addWidget(cfg_group)

        btn_row = QHBoxLayout()
        self.tc_start_btn = QPushButton("Начать проверку")
        self.tc_start_btn.clicked.connect(self._tc_start)
        self.tc_cancel_btn = QPushButton("Отменить")
        self.tc_cancel_btn.clicked.connect(self._tc_cancel)
        self.tc_cancel_btn.setEnabled(False)
        btn_row.addWidget(self.tc_start_btn)
        btn_row.addWidget(self.tc_cancel_btn)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Лог проверки:"))
        self.tc_log = QTextEdit()
        self.tc_log.setReadOnly(True)
        self.tc_log.setMinimumHeight(220)
        layout.addWidget(self.tc_log)

        layout.addWidget(QLabel("Итог:"))
        self.tc_results = QTextEdit()
        self.tc_results.setReadOnly(True)
        self.tc_results.setMinimumHeight(160)
        layout.addWidget(self.tc_results)

        return tab

    def _tc_browse_tf2(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите корневую папку TF2")
        if folder:
            self.tc_tf2_edit.setText(folder)

    def _tc_start(self):
        tf2_root = self.tc_tf2_edit.text().strip()
        if not tf2_root:
            QMessageBox.warning(self, "Ошибка", "Укажите путь к папке TF2!")
            return

        textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root)
        if not textures_vpk:
            QMessageBox.warning(
                self, "Ошибка",
                f"tf2_textures_dir.vpk не найден в:\n{tf2_root}\n\n"
                "Ожидаемый путь: <TF2>\\tf\\tf2_textures_dir.vpk"
            )
            return

        self.tc_log.clear()
        self.tc_results.clear()
        self.tc_start_btn.setEnabled(False)
        self.tc_cancel_btn.setEnabled(True)

        class_filter = self.tc_class_combo.currentData()
        deep = self.tc_deep_checkbox.isChecked()
        self.texture_check_worker = TextureCheckWorker(textures_vpk, class_filter, deep)
        self.texture_check_worker.progress.connect(self._tc_on_progress)
        self.texture_check_worker.finished.connect(self._tc_on_finished)
        self.texture_check_worker.start()

    def _tc_cancel(self):
        if self.texture_check_worker and self.texture_check_worker.isRunning():
            self.texture_check_worker.requestInterruption()
            self.texture_check_worker.wait(3000)
        self.tc_log.append("\nПроверка отменена.")
        self.tc_start_btn.setEnabled(True)
        self.tc_cancel_btn.setEnabled(False)

    def _tc_on_progress(self, msg: str):
        self.tc_log.append(msg)
        self.tc_log.verticalScrollBar().setValue(self.tc_log.verticalScrollBar().maximum())

    def _tc_on_finished(self, results: dict):
        self.tc_start_btn.setEnabled(True)
        self.tc_cancel_btn.setEnabled(False)

        found = results["found"]
        missing = results["missing"]
        deep: dict = results.get("deep", {})
        total = len(found) + len(missing)

        lines = [
            "=== РЕЗУЛЬТАТЫ ПРОВЕРКИ ТЕКСТУР ===\n",
            f"Всего оружий: {total}",
            f"Найдено:      {len(found)}",
            f"Не найдено:   {len(missing)}\n",
        ]

        if missing:
            if deep:
                # Разбиваем на три группы: найдено глубоко, отсутствует в VPK
                found_deep = [(k, n, c, cat) for k, n, c, cat in missing if deep.get(k)]
                absent = [(k, n, c, cat) for k, n, c, cat in missing if not deep.get(k)]

                if found_deep:
                    lines.append("🔍 НАЙДЕНО ГЛУБОКИМ ПОИСКОМ (нужно добавить пути):")
                    for weapon_key, name_en, class_name, category in sorted(found_deep, key=lambda x: x[0]):
                        lines.append(f"  • {weapon_key} ({name_en}, {class_name}/{category})")
                        for real_path in deep[weapon_key]:
                            lines.append(f"      → {real_path}")
                    lines.append("")

                if absent:
                    lines.append("✘ ОТСУТСТВУЮТ В VPK ПОЛНОСТЬЮ:")
                    for weapon_key, name_en, class_name, category in sorted(absent, key=lambda x: x[0]):
                        lines.append(f"  • {weapon_key:<35} {name_en}  ({class_name}/{category})")
            else:
                lines.append("✘ НЕ НАЙДЕНО (включите глубокий поиск чтобы узнать реальный путь):")
                for weapon_key, name_en, class_name, category in sorted(missing, key=lambda x: x[0]):
                    lines.append(f"  • {weapon_key:<35} {name_en}  ({class_name}/{category})")

            lines.append("")
            lines.append("Проверялись пути:")
            for p in _TEXTURE_SEARCH_TEMPLATES:
                lines.append(f"  {p}")

        self.tc_results.setPlainText("\n".join(lines))
    
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
        tf2_folder = config.get('tf2_game_folder', '')
        if tf2_folder:
            self.tc_tf2_edit.setText(tf2_folder)
    
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

