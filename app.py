import sys
import os
import shutil
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPushButton, QFileDialog,
    QMessageBox, QLineEdit, QRadioButton, QCheckBox, QComboBox,
    QButtonGroup, QTextEdit, QWidget, QVBoxLayout, QDialog, QHBoxLayout
)
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QPalette, QPixmap
from PyQt5.QtCore import QUrl, Qt
from PIL import Image

TRANSLATIONS = {
    'ru': {
        'error': 'Ошибка',
        'file_not_found': 'Файл не найден по пути:',
        'load_image': 'Сначала загрузите изображение.',
        'enter_name': 'Введите имя VPK-файла.',
        'vpk_success': 'VPK успешно собран:',
        'vpk_failed': 'VPK не создан.\nSTDERR: {stderr}\nSTDOUT: {stdout}',
        'vpk_missing': 'Файл root.vpk не найден после сборки.',
        'build_error': 'Ошибка при сборке VPK',
        'support': '💖 Поддержать автора',
        'open_editor': 'Открыть редактор VMT',
        'build': 'Собрать VPK',
        'save': 'Сохранить',
        'restore': 'Восстановить из backup',
        'placeholder': 'Введите имя VPK-файла (без .vpk)',
        'drag_image': 'Перетащи сюда изображение',
        'language': 'Язык',
        'image_format': 'Формат изображения:',
        'res_high': '1024x1024 (Высокое)',
        'res_normal': '512x512 (Обычное)'
    },
    'en': {
        'error': 'Error',
        'file_not_found': 'File not found at path:',
        'load_image': 'Please load an image first.',
        'enter_name': 'Please enter the VPK file name.',
        'vpk_success': 'VPK successfully created:',
        'vpk_failed': 'VPK was not created.\nSTDERR: {stderr}\nSTDOUT: {stdout}',
        'vpk_missing': 'File root.vpk not found after build.',
        'build_error': 'Build error',
        'support': '💖 Support the author',
        'open_editor': 'Open VMT Editor',
        'build': 'Build VPK',
        'save': 'Save',
        'restore': 'Restore from backup',
        'placeholder': 'Enter VPK file name (without .vpk)',
        'drag_image': 'Drag your image here',
        'language': 'Language',
        'image_format': 'Image format:',
        'res_high': '1024x1024 (High)',
        'res_normal': '512x512 (Normal)'
    }
}

MODES = {
    "Kunai": "kunai",
    "CritHIT": "critHIT"
}

def apply_dark_theme(app):
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1e1e2f"))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor("#252836"))
    palette.setColor(QPalette.AlternateBase, QColor("#2c2f48"))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor("#2c2f48"))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor("#6c9ee3"))
    palette.setColor(QPalette.Highlight, QColor("#6c9ee3"))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    app.setStyleSheet("""
        
        QWidget {
            background-color: #1e1e2f;
            color: #ffffff;
        }
        QLabel {
            font-size: 13px;
        }
        QComboBox, QLineEdit, QTextEdit {
            background-color: #2c2f48;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 4px;
        }
        QComboBox QAbstractItemView {
            background-color: #2c2f48;
            color: #ffffff;
            selection-background-color: #3e4459;
        }
        QPushButton {
            background-color: #3d3f5c;
            color: white;
            padding: 6px;
            border-radius: 5px;
            border: 1px solid #5e5e80;
        }
        QPushButton:hover {
            background-color: #4e5175;
        }
        QRadioButton {
            spacing: 6px;
        }
        QRadioButton::indicator {;
            width: 15px;
            height: 15px;
            border-radius: 7px;
            border: 1px solid #aaa;
            background-color: #2c2f48;
        }
        QRadioButton::indicator:checked {
            background-color: #6c9ee3;
            border: 1px solid #6c9ee3;
        }

    """)

class VMTEditorDialog(QDialog):
    def __init__(self, parent=None, vmt_path="", t=None):
        super().__init__(parent)
        self.t = t or TRANSLATIONS['ru']
        self.setWindowTitle("VMT Editor")
        self.setGeometry(500, 150, 700, 600)
        self.vmt_path = vmt_path

        self.backup_dir = os.path.join("tools", "backupVMT")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.backup_path = os.path.join(self.backup_dir, os.path.basename(vmt_path))

        self.text_edit = QTextEdit(self)
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
                self.text_edit.setPlainText(f.read())
        if not os.path.exists(self.backup_path):
            shutil.copy2(self.vmt_path, self.backup_path)

    def save_changes(self):
        content = self.text_edit.toPlainText()
        watermark = "\n// made on Tf2SkinGenerator https://steamcommunity.com/id/sosatihackeri - Developer(xiety)"
        if watermark.strip() not in content:
            content += watermark
        with open(self.vmt_path, "w", encoding="utf-8") as f:
            f.write(content)
        self.accept()

    def restore_backup(self):
        if os.path.exists(self.backup_path):
            with open(self.backup_path, "r", encoding="utf-8") as f:
                self.text_edit.setPlainText(f.read())

class VTFGenerator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.language = 'ru'
        self.t = TRANSLATIONS[self.language]
        self.setWindowTitle("TF2 Skin Generator")
        self.setGeometry(300, 300, 960, 600)

        self.mode_select = QComboBox(self)
        self.mode_select.setGeometry(30, 20, 200, 25)
        self.mode_select.addItems(MODES.keys())
        self.mode_select.currentTextChanged.connect(self.update_mode)

        self.label = QLabel(self.t['drag_image'], self)
        self.label.setGeometry(250, 20, 440, 80)
        self.label.setStyleSheet("QLabel { border: 2px dashed #aaa; font-size: 14px; }")
        self.label.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)

        self.preview = QLabel(self)
        self.preview.setGeometry(370, 120, 328, 328)
        self.preview.setStyleSheet("QLabel { border: 1px solid #ccc; background-color: white; }")
        self.preview.setAlignment(Qt.AlignCenter)

        self.radio_group = QButtonGroup(self)
        self.radio_512 = QRadioButton(self.t['res_normal'], self)
        self.radio_512.setGeometry(30, 120, 200, 25)
        self.radio_512.setChecked(True)
        self.radio_1024 = QRadioButton(self.t['res_high'], self)
        self.radio_1024.setGeometry(30, 150, 200, 25)
        self.radio_group.addButton(self.radio_512)
        self.radio_group.addButton(self.radio_1024)

        self.support_button = QPushButton(self.t['support'], self)
        self.support_button.setGeometry(770, 20, 160, 30)
        self.support_button.clicked.connect(self.open_support_link)

        self.language_select = QComboBox(self)
        self.language_select.setGeometry(10, 570, 170, 30)
        self.language_select.addItems(["Русский", "English"])
        self.language_select.currentIndexChanged.connect(self.change_language_from_combo)

        self.format_label = QLabel(self.t['image_format'], self)
        self.format_label.setGeometry(30, 190, 200, 20)
        self.format_combo = QComboBox(self)
        self.format_combo.setGeometry(30, 210, 200, 25)
        self.format_combo.addItems(["DXT1", "DXT5", "RGBA8888", "I8", "A8"])

        self.flag_clamps = QCheckBox("Clamp S", self)
        self.flag_clamps.setGeometry(30, 245, 200, 20)
        self.flag_clampt = QCheckBox("Clamp T", self)
        self.flag_clampt.setGeometry(30, 270, 200, 20)
        self.flag_nomipmaps = QCheckBox("No Mipmap", self)
        self.flag_nomipmaps.setGeometry(30, 295, 200, 20)
        self.flag_nolod = QCheckBox("No level of detail", self)
        self.flag_nolod.setGeometry(30, 320, 200, 20)

        self.expert_button = QPushButton(self.t['open_editor'], self)
        self.expert_button.setGeometry(30, 355, 200, 30)
        self.expert_button.clicked.connect(self.expert_mode_triggered)

        self.filename_input = QLineEdit(self)
        self.filename_input.setGeometry(50, 470, 400, 40)
        self.filename_input.setPlaceholderText(self.t['placeholder'])

        self.button = QPushButton(self.t['build'], self)
        self.button.setGeometry(470, 470, 180, 40)
        self.button.clicked.connect(self.build_vpk)

        self.image_path = None
        self.mode = "kunai"
        self.update_mode("Kunai")

    def set_language(self, lang):
        self.language = lang
        self.t = TRANSLATIONS[lang]
        self.support_button.setText(self.t['support'])
        self.expert_button.setText(self.t['open_editor'])
        self.button.setText(self.t['build'])
        self.filename_input.setPlaceholderText(self.t['placeholder'])
        self.label.setText(self.t['drag_image'])
        self.format_label.setText(self.t['image_format'])
        self.radio_512.setText(self.t['res_normal'])
        self.radio_1024.setText(self.t['res_high'])

    def update_mode(self, mode_text):
        self.mode = MODES[mode_text]
        crit_mode = self.mode == "critHIT"

        self.flag_clamps.setChecked(False)
        self.flag_clampt.setChecked(False)
        self.flag_nomipmaps.setChecked(False)
        self.flag_nolod.setChecked(False)

        for widget in [self.flag_clamps, self.flag_clampt, self.flag_nomipmaps, self.flag_nolod]:
            widget.setDisabled(crit_mode)

        self.format_combo.setDisabled(crit_mode)
        if crit_mode:
            self.format_combo.setCurrentText("DXT5")

    def change_language_from_combo(self, index):
        lang = 'ru' if index == 0 else 'en'
        self.set_language(lang)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.load_image(path)

    def load_image(self, path):
        self.image_path = path
        pixmap = QPixmap(path).scaled(328, 328, Qt.KeepAspectRatio)
        self.preview.setPixmap(pixmap)

    def open_support_link(self):
        QDesktopServices.openUrl(QUrl("https://steamcommunity.com/tradeoffer/new/?partner=394814324&token=GNGCagXk"))

    def expert_mode_triggered(self):
        if self.mode == "kunai":
            base_path = os.path.join("tools", "mod_data", "kunai")
            rel_path = os.path.join("materials", "vgui", "replay", "thumbnails", "models", "workshop_partner", "weapons", "c_models", "c_shogun_kunai")
            vmt_filename = "c_shogun_kunai.vmt"
        else:
            base_path = os.path.join("tools", "mod_data", "critHIT")
            rel_path = os.path.join("materials", "effects")
            vmt_filename = "crit.vmt"

        vmt_full_path = os.path.join(base_path, "root", rel_path, vmt_filename)

        if not os.path.isfile(vmt_full_path):
            QMessageBox.warning(self, self.t['error'], f"{self.t['file_not_found']}\n{vmt_full_path}")
            return

        self.open_vmt_editor(vmt_full_path)

    def open_vmt_editor(self, path):
        dialog = VMTEditorDialog(self, path, self.t)
        dialog.exec_()

    def build_vpk(self):
        try:
            from_path = self.image_path
            if not from_path:
                QMessageBox.warning(self, self.t['error'], self.t['load_image'])
                return

            name = self.filename_input.text().strip()
            if not name:
                QMessageBox.warning(self, self.t['error'], self.t['enter_name'])
                return
            if not name.lower().endswith(".vpk"):
                name += ".vpk"

            size = (1024, 1024) if self.radio_1024.isChecked() else (512, 512)

            if self.mode == "kunai":
                base_path = os.path.join("tools", "mod_data", "kunai")
                rel_path = os.path.join("materials", "vgui", "replay", "thumbnails", "models", "workshop_partner", "weapons", "c_models", "c_shogun_kunai")
                vtf_filename = "c_shogun_kunai.vtf"
            else:
                base_path = os.path.join("tools", "mod_data", "critHIT")
                rel_path = os.path.join("materials", "effects")
                vtf_filename = "crit.vtf"

            vtf_output_path = os.path.join(base_path, "root", rel_path)
            vmt_path = os.path.join(vtf_output_path, vtf_filename.replace(".vtf", ".vmt"))
            vtf_temp_png = os.path.join(vtf_output_path, vtf_filename.replace(".vtf", ".png"))

            os.makedirs(vtf_output_path, exist_ok=True)
            img = Image.open(from_path).convert("RGBA").resize(size)
            img.save(vtf_temp_png)

            selected_format = self.format_combo.currentText() if self.mode == "kunai" else "DXT5"
            flags = []
            if self.mode == "kunai":
                if self.flag_clamps.isChecked(): flags.append("CLAMPS")
                if self.flag_clampt.isChecked(): flags.append("CLAMPT")
                if self.flag_nomipmaps.isChecked(): flags.append("NOMIP")
                if self.flag_nolod.isChecked(): flags.append("NOLOD")

            vtf_args = [
                os.path.abspath("tools/VTF/VTFCmd.exe"),
                "-file", vtf_temp_png,
                "-output", vtf_output_path,
                "-format", selected_format
            ] + ["-flag" if i % 2 == 0 else f for i, f in enumerate(flags*2)]

            subprocess.run(vtf_args, check=True)
            if os.path.exists(vtf_temp_png): os.remove(vtf_temp_png)

            vpk_dir = os.path.join(base_path, "root")
            temp_vpk_path = os.path.join(base_path, "root.vpk")
            if os.path.exists(temp_vpk_path): os.remove(temp_vpk_path)

            result = subprocess.run([
                os.path.abspath("tools/VPK/vpk.exe"),
                "-v", os.path.abspath(vpk_dir)
            ], cwd=base_path, capture_output=True, text=True)

            if result.returncode != 0:
                raise RuntimeError(self.t['vpk_failed'].format(stderr=result.stderr, stdout=result.stdout))

            if not os.path.exists(temp_vpk_path):
                raise FileNotFoundError(self.t['vpk_missing'])

            os.makedirs("export", exist_ok=True)
            final_output = os.path.join("export", name)
            shutil.move(temp_vpk_path, final_output)
            QMessageBox.information(self, "OK", f"{self.t['vpk_success']} {final_output}")

        except Exception as e:
            QMessageBox.critical(self, self.t['build_error'], str(e))

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(__file__))

    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = VTFGenerator()
    window.show()
    sys.exit(app.exec_())