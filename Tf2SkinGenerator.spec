# -*- mode: python ; coding: utf-8 -*-
"""
Сборка Tf2SkinGenerator.

Интерфейс — веб-страница в окне WebView2 (pywebview). Раньше здесь была
длинная чистка PySide6: из 424 МБ дистрибутива 349 МБ занимал Qt, из них
196 МБ — Qt6WebEngineCore.dll, то есть встроенный Chromium ради превью на
three.js. Движок Edge уже стоит в Windows, поэтому весь этот раздел исчез
вместе с Qt — вырезать больше нечего.

Что ОБЯЗАНО попасть в сборку, кроме кода:
    frontend/  — сама страница (HTML, CSS, модули JS);
    src/static — вьювер моделей и движок частиц, они грузятся в iframe.
Без любого из двух приложение запустится и покажет пустое окно.

Чего в сборке БЫТЬ НЕ ДОЛЖНО: папки config. Там лежит не «значения по
умолчанию», а рабочий конфиг того, кто собирал: путь к его копии игры и, если
он что-то пробовал, его ключи от сторонних сервисов. Значения по умолчанию
живут в коде (AppConfig.DEFAULT_CONFIG), конфиг создаётся сам при первом
запуске, и создаётся он в папке данных, а не рядом с .exe — см.
src/shared/paths.py.
"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend\\mockup', 'frontend\\mockup'),
        ('src\\static', 'src\\static'),
    ],
    # pywebview выбирает бэкенд в рантайме, и PyInstaller этого не видит:
    # на Windows это WinForms поверх WebView2, он тянет pythonnet (clr).
    hiddenimports=[
        'webview.platforms.winforms',
        'clr_loader',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Тянутся транзитивно и никем не импортируются.
        'tkinter', 'unittest', 'pydoc_data', 'test', 'lib2to3',
        # Qt в проекте больше нет; исключение оставлено сторожем на случай,
        # если пакет доедет транзитивной зависимостью.
        'PySide6', 'PyQt5', 'PyQt6', 'shiboken6',
    ],
    noarchive=False,
    optimize=0,
)


def _drop(entry) -> bool:
    """True — файл в сборку не попадает."""
    dest = entry[0].replace('\\', '/').lower()
    name = dest.rsplit('/', 1)[-1]
    # Кодек AVIF в Pillow: изображения читаются как png/jpg/tga/bmp/webp/gif.
    if name.startswith('_avif.') or name == 'libavif.dll':
        return True
    return False


a.binaries = [e for e in a.binaries if not _drop(e)]
a.datas = [e for e in a.datas if not _drop(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Tf2SkinGenerator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['installer\\assets\\icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Tf2SkinGenerator',
)
