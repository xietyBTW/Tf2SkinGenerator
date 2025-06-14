import sys
import os
import shutil
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPushButton, QFileDialog,
    QMessageBox, QLineEdit, QRadioButton, QCheckBox, QComboBox,
    QButtonGroup, QTextEdit, QWidget, QVBoxLayout, QDialog, QHBoxLayout
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
from PIL import Image

MODES = {
    "Kunai": "kunai",
    "CritHIT": "critHIT"
}

class VMTEditorDialog(QDialog):
    def __init__(self, parent=None, vmt_path=""):
        super().__init__(parent)
        self.setWindowTitle("Редактор VMT-файла")
        self.setGeometry(500, 150, 700, 600)
        self.vmt_path = vmt_path

        self.backup_dir = os.path.join("tools", "backupVMT")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.backup_path = os.path.join(self.backup_dir, os.path.basename(vmt_path))

        self.text_edit = QTextEdit(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text_edit)

        button_layout = QHBoxLayout()

        self.save_button = QPushButton("Сохранить", self)
        self.save_button.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_button)

        self.restore_button = QPushButton("Восстановить из backup", self)
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
        self.setWindowTitle("TF2 Skin Generator")
        self.setGeometry(300, 300, 960, 800)

        self.mode_select = QComboBox(self)
        self.mode_select.setGeometry(30, 20, 200, 25)
        self.mode_select.addItems(MODES.keys())
        self.mode_select.currentTextChanged.connect(self.update_mode)

        self.label = QLabel("Перетащи сюда изображение", self)
        self.label.setGeometry(250, 20, 440, 80)
        self.label.setStyleSheet("QLabel { border: 2px dashed #aaa; font-size: 14px; }")
        self.label.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)

        self.preview = QLabel(self)
        self.preview.setGeometry(370, 120, 328, 328)
        self.preview.setStyleSheet("QLabel { border: 1px solid #ccc; background-color: white; }")
        self.preview.setAlignment(Qt.AlignCenter)

        self.radio_group = QButtonGroup(self)
        self.radio_512 = QRadioButton("512x512 (Обычное)", self)
        self.radio_512.setGeometry(30, 120, 200, 25)
        self.radio_512.setChecked(True)
        self.radio_1024 = QRadioButton("1024x1024 (Высокое)", self)
        self.radio_1024.setGeometry(30, 150, 200, 25)
        self.radio_group.addButton(self.radio_512)
        self.radio_group.addButton(self.radio_1024)

        self.format_label = QLabel("Формат изображения:", self)
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

        self.expert_button = QPushButton("Открыть редактор VMT", self)
        self.expert_button.setGeometry(30, 355, 200, 30)
        self.expert_button.clicked.connect(self.expert_mode_triggered)

        self.filename_input = QLineEdit(self)
        self.filename_input.setGeometry(50, 470, 400, 40)
        self.filename_input.setPlaceholderText("Введите имя VPK-файла (без .vpk)")

        self.button = QPushButton("Собрать VPK", self)
        self.button.setGeometry(470, 470, 180, 40)
        self.button.clicked.connect(self.build_vpk)

        self.image_path = None
        self.mode = "kunai"
        self.update_mode("Kunai")

    def update_mode(self, mode_text):
        self.mode = MODES[mode_text]

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
            QMessageBox.warning(self, "VMT-файл не найден", f"Файл не найден по пути:\n{vmt_full_path}\n\nСначала соберите VPK, чтобы он появился.")
            return

        self.open_vmt_editor(vmt_full_path)

    def open_vmt_editor(self, path):
        dialog = VMTEditorDialog(self, path)
        dialog.exec_()

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

    def build_vpk(self):
        try:
            from_path = self.image_path
            if not from_path:
                QMessageBox.warning(self, "Ошибка", "Сначала загрузите изображение.")
                return

            name = self.filename_input.text().strip()
            if not name:
                QMessageBox.warning(self, "Ошибка", "Введите имя VPK-файла.")
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
                if self.flag_clamps.isChecked():
                    flags.append("CLAMPS")
                if self.flag_clampt.isChecked():
                    flags.append("CLAMPT")
                if self.flag_nomipmaps.isChecked():
                    flags.append("NOMIP")
                if self.flag_nolod.isChecked():
                    flags.append("NOLOD")

            vtf_args = [
                os.path.abspath("tools/VTF/VTFCmd.exe"),
                "-file", vtf_temp_png,
                "-output", vtf_output_path,
                "-format", selected_format
            ]
            for flag in flags:
                vtf_args.extend(["-flag", flag])

            subprocess.run(vtf_args, check=True)

            if os.path.exists(vtf_temp_png):
                os.remove(vtf_temp_png)

            vpk_dir = os.path.join(base_path, "root")
            temp_vpk_path = os.path.join(base_path, "root.vpk")
            if os.path.exists(temp_vpk_path):
                os.remove(temp_vpk_path)

            result = subprocess.run([
                os.path.abspath("tools/VPK/vpk.exe"),
                "-v", os.path.abspath(vpk_dir)
            ], cwd=base_path, capture_output=True, text=True)

            if result.returncode != 0:
                raise RuntimeError(f"VPK не создан.\nSTDERR: {result.stderr or '—'}\nSTDOUT: {result.stdout or '—'}")

            if not os.path.exists(temp_vpk_path):
                raise FileNotFoundError("Файл root.vpk не найден после сборки.")

            os.makedirs("export", exist_ok=True)
            final_output = os.path.join("export", name)
            shutil.move(temp_vpk_path, final_output)
            QMessageBox.information(self, "Успех", f"VPK успешно собран: {final_output}")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка при сборке VPK", str(e))

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(__file__))

    app = QApplication(sys.argv)
    window = VTFGenerator()
    window.show()
    sys.exit(app.exec_())
