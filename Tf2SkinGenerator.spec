# -*- mode: python ; coding: utf-8 -*-
"""
Сборка Tf2SkinGenerator.

Здесь же описано, что в сборку НЕ попадает: раньше эта чистка жила в
build.ps1 постобработкой, теперь всё в одном месте — файлы просто не
копируются, а не удаляются после.

ЧТО ТРОГАТЬ НЕЛЬЗЯ. Зависимости QtWebEngineWidgets прочитаны из таблиц
импорта его DLL; без любой из них превью моделей и частиц не запустится:
    Core, Gui, Network, OpenGL, Positioning, PrintSupport, Qml, QmlMeta,
    QmlModels, QmlWorkerScript, Quick, QuickWidgets, WebChannel,
    WebChannelQuick, WebEngineCore, WebEngineQuick, WebEngineWidgets, Widgets
Отдельно: Qt6Positioning — геолокация, Qt6PrintSupport — печать страницы;
выглядят ненужными, но без них падает импорт QtWebEngineWidgets.
Поэтому списки ниже точечные: маска вида «всё, где есть Quick» вырезала бы
WebEngineQuick вместе с превью.
"""

import re

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('src\\static', 'src\\static'), ('config', 'config')],
    hiddenimports=['PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore', 'PySide6.QtWebChannel'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Python-модули, которые тянутся транзитивно и никем не импортируются
        'tkinter', 'unittest', 'pydoc_data', 'test', 'lib2to3',
        'PySide6.QtQuick3D', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DExtras',
        'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSerialPort',
        'PySide6.QtSensors', 'PySide6.QtSql', 'PySide6.QtTest',
        'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtPdf',
        'PySide6.QtPdfWidgets', 'PySide6.QtWebSockets', 'PySide6.QtWebView',
        'PySide6.QtSpatialAudio', 'PySide6.QtTextToSpeech',
    ],
    noarchive=False,
    optimize=0,
)

# ── Чистка бинарников и данных ───────────────────────────────────────────────
# Отбираем по точным именам файлов и по каталогам: маски вида «всё, где
# встречается Quick» опасны — под них попадает WebEngineQuick, без которого
# превью не работает.

#: DLL, не нужные приложению. WebEngine и его Quick-зависимости НЕ трогаем.
_EXCLUDED_DLLS = {
    'qt6charts', 'qt6chartsqml', 'qt6datavisualization', 'qt6graphs',
    'qt6graphswidgets', 'qt63dcore', 'qt63drender', 'qt63dinput',
    'qt63dlogic', 'qt63dextras', 'qt63danimation', 'qt63dquick',
    'qt63dquickscene2d', 'qt63dquickextras', 'qt63dquickinput',
    'qt63dquickrender', 'qt63dquickanimation',
    'qt6multimedia', 'qt6multimediaquick', 'qt6multimediawidgets',
    'qt6spatialaudio', 'qt6texttospeech', 'qt6bluetooth', 'qt6nfc',
    'qt6serialport', 'qt6serialbus', 'qt6sensors', 'qt6sensorsquick',
    'qt6sql', 'qt6test', 'qt6quicktest', 'qt6designer', 'qt6help',
    'qt6pdf', 'qt6pdfquick', 'qt6pdfwidgets', 'qt6websockets',
    'qt6webview', 'qt6webviewquick', 'qt6statemachine', 'qt6statemachineqml',
    'qt6remoteobjects', 'qt6remoteobjectsqml', 'qt6scxml', 'qt6scxmlqml',
    'qt6virtualkeyboard', 'qt6quick3d', 'qt6quick3dassetimport',
    'qt6quick3dassetutils', 'qt6quick3deffects', 'qt6quick3dhelpers',
    'qt6quick3dhelpersimpl', 'qt6quick3diblbaker', 'qt6quick3dparticles',
    'qt6quick3dparticleeffects', 'qt6quick3druntimerender',
    'qt6quick3dutils', 'qt6quick3dxr', 'qt6quick3dglslparser',
    'qt6quickvectorimage', 'qt6quickvectorimagegenerator',
    'qt6quickvectorimagehelpers', 'qt6quicktimeline',
    'qt6quicktimelineblendtrees',
    # Появились в PySide6 6.11: QML-обвязки к тем же неиспользуемым модулям
    'qt6datavisualizationqml', 'qt6virtualkeyboardqml',
    'qt6virtualkeyboardsettings', 'qt6quick3dspatialaudio',
    'qt63dquickscene3d', 'qt63dquicklogic', 'qt6location',
    'qt6locationquick', 'qt6quickeffects',
}

#: Каталоги QML-модулей, которые не нужны ни приложению, ни WebEngine.
_EXCLUDED_QML_DIRS = (
    'pyside6/qml/qtquick3d', 'pyside6/qml/qt3d', 'pyside6/qml/qtcharts',
    'pyside6/qml/qtgraphs', 'pyside6/qml/qtdatavisualization',
    'pyside6/qml/qtmultimedia', 'pyside6/qml/qtsensors',
    'pyside6/qml/qtpositioning', 'pyside6/qml/qttest',
    'pyside6/qml/qtwebsockets', 'pyside6/qml/qtwebview',
    'pyside6/qml/qtquick/virtualkeyboard', 'pyside6/qml/qtquick/timeline',
    'pyside6/qml/qtquick/particles', 'pyside6/qml/qtquick/scene2d',
    'pyside6/qml/qtquick/scene3d', 'pyside6/qml/qtquick/vectorimage',
    'pyside6/qml/qtremoteobjects', 'pyside6/qml/qtscxml',
    'pyside6/qml/qtlocation', 'pyside6/qml/qtquick/pdf',
    'pyside6/qml/qtquick/effects',
)

#: Локали Chromium: интерфейс приложения только на ru/en.
_KEEP_LOCALES = ('en-us', 'en-gb', 'ru')

#: Плагины Qt, которые не нужны без соответствующих модулей.
_EXCLUDED_PLUGIN_DIRS = (
    'plugins/sqldrivers', 'plugins/multimedia', 'plugins/position',
    'plugins/sensors', 'plugins/texttospeech', 'plugins/virtualkeyboard',
    'plugins/webview', 'plugins/renderers', 'plugins/geometryloaders',
    'plugins/sceneparsers', 'plugins/designer', 'plugins/qmltooling',
)


def _drop(entry) -> bool:
    """True — файл в сборку не попадает."""
    dest = entry[0].replace('\\', '/').lower()
    name = dest.rsplit('/', 1)[-1]

    if name.endswith('.dll') and name[:-4] in _EXCLUDED_DLLS:
        return True
    if any(part in dest for part in _EXCLUDED_QML_DIRS):
        return True
    if any(part in dest for part in _EXCLUDED_PLUGIN_DIRS):
        return True
    # Локали Chromium: оставляем только используемые языки
    if 'qtwebengine_locales/' in dest and name.endswith('.pak'):
        return name[:-4].lower() not in _KEEP_LOCALES
    # Переводы Qt: оставляем английский и русский ЛЮБОГО модуля (включая
    # qtwebengine_ru.qm — это подписи меню и диалогов внутри превью)
    if '/translations/' in dest and name.endswith('.qm'):
        return not re.search(r'_(en|ru)(_|\.qm$)', name)
    # Кодек AVIF в Pillow: изображения читаются как png/jpg/tga/bmp/webp/gif
    if name.startswith('_avif.') or name == 'libavif.dll':
        return True
    # Отладочные ресурсы Chromium: нужны только сборкам Qt с отладкой
    if name.endswith(('.debug.pak', '.debug.bin')):
        return True
    # Инспектор Chromium (DevTools) — 83 МБ ресурсов. Приложение его не
    # открывает: страницы превью свои, а не пользовательские
    if name.startswith('qtwebengine_devtools_resources'):
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
    upx=False,   # UPX ломает Qt6WebEngineCore.dll
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
    upx=False,
    upx_exclude=[],
    name='Tf2SkinGenerator',
)
