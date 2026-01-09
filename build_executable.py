#!/usr/bin/env python3
"""
Скрипт для создания исполняемого файла приложения с помощью PyInstaller
"""

import os
import sys
import subprocess
import shutil

def main():
    """Создает исполняемый файл приложения"""
    
    print("=" * 60)
    print("TF2 Skin Generator - Сборка исполняемого файла")
    print("=" * 60)
    print()
    
    # Проверяем наличие PyInstaller
    try:
        import PyInstaller
        print(f"PyInstaller найден: версия {PyInstaller.__version__}")
    except ImportError:
        print("ОШИБКА: PyInstaller не установлен!")
        print("Установите его командой: pip install pyinstaller")
        sys.exit(1)
    
    # Путь к главному файлу
    main_file = "main.py"
    if not os.path.exists(main_file):
        print(f"ОШИБКА: Файл {main_file} не найден!")
        sys.exit(1)
    
    # Имя исполняемого файла
    app_name = "TF2SkinGenerator"
    
    # Очищаем предыдущие сборки
    build_dirs = ["build", "dist", "__pycache__"]
    for dir_name in build_dirs:
        if os.path.exists(dir_name):
            print(f"Удаление старой папки {dir_name}...")
            shutil.rmtree(dir_name)
    
    if os.path.exists(f"{app_name}.spec"):
        os.remove(f"{app_name}.spec")
    
    print()
    print("Запуск PyInstaller...")
    print()
    
    # Команда PyInstaller
    # ВАЖНО: --onefile создает один EXE файл со всем кодом внутри
    # Исходные .py файлы НЕ нужны - весь код встроен в EXE
    cmd = [
        "pyinstaller",
        "--name", app_name,
        "--onefile",  # Один исполняемый файл (весь код внутри)
        "--windowed",  # Без консоли (GUI приложение)
        "--icon=NONE",  # Можно указать путь к иконке: --icon=icon.ico
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtOpenGL",
        "--hidden-import", "cv2",
        "--hidden-import", "cv2.cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "qdarkstyle",
        "--hidden-import", "vpk",
        "--collect-all", "qdarkstyle",  # Собираем все файлы qdarkstyle
        "--collect-all", "PIL",  # Собираем все файлы Pillow
        main_file
    ]
    
    # Запускаем PyInstaller
    try:
        result = subprocess.run(cmd, check=True)
        print()
        print("=" * 60)
        print("Сборка завершена успешно!")
        print("=" * 60)
        print(f"Исполняемый файл находится в папке: dist\\{app_name}.exe")
        print()
        print("ВАЖНО: Весь код приложения встроен в EXE файл.")
        print("Исходные .py файлы НЕ нужны для работы приложения.")
        print()
        print("Для работы приложения необходимо только:")
        print("  - EXE файл (dist\\TF2SkinGenerator.exe)")
        print("  - Папка tools (VTF, VPK, Crowbar)")
        print()
        print("Теперь можно собрать установщик:")
        print("  - Откройте setup_exe_only.iss в Inno Setup")
        print("  - Или запустите build_installer_exe.bat")
        
    except subprocess.CalledProcessError as e:
        print()
        print("=" * 60)
        print("ОШИБКА при сборке!")
        print("=" * 60)
        print(f"Код ошибки: {e.returncode}")
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 60)
        print("ОШИБКА при сборке!")
        print("=" * 60)
        print(f"Ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

