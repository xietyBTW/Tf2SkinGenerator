import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def setup_fake_pyside6():
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtcore = types.ModuleType("PySide6.QtCore")
    pyside = types.ModuleType("PySide6")

    class DummyApp:
        def __init__(self, *args, **kwargs):
            self.icon = None
            self.palette = None
            self.font = None
            self.stylesheet = None

        def setWindowIcon(self, icon):
            self.icon = icon
        
        def setPalette(self, palette):
            self.palette = palette
        
        def setFont(self, font):
            self.font = font
        
        def setStyleSheet(self, stylesheet):
            self.stylesheet = stylesheet

    class DummyIcon:
        def __init__(self, path):
            self.path = path

    class DummyColor:
        def __init__(self, value):
            self.value = value

    class DummyPalette:
        Window = 1
        WindowText = 2
        Base = 3
        AlternateBase = 4
        ToolTipBase = 5
        ToolTipText = 6
        Text = 7
        Button = 8
        ButtonText = 9
        BrightText = 10
        Link = 11
        Highlight = 12
        HighlightedText = 13

        def __init__(self):
            self.colors = []

        def setColor(self, role, color):
            self.colors.append((role, color))

    class DummyFont:
        Normal = 50

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    qtwidgets.QApplication = DummyApp
    qtgui.QIcon = DummyIcon
    qtgui.QColor = DummyColor
    qtgui.QPalette = DummyPalette
    qtgui.QFont = DummyFont
    qtcore.Qt = type("Qt", (), {})
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtWidgets"] = qtwidgets
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtCore"] = qtcore


#: Модули, которые импортируются ПОД заглушкой и поэтому запоминают фейковый Qt.
#: Их надо выбросить вместе с ней, иначе они утекут в соседние тесты.
_TAINTED = ("src.core.app_factory", "src.utils.themes")


class AppFactoryTests(unittest.TestCase):
    def setUp(self):
        # Заглушку обязательно снимаем в tearDown. Раньше она оставалась в
        # sys.modules до конца прогона, и всё, что импортировалось после,
        # живого Qt уже не видело — три тест-модуля падали на сборе.
        self._saved = {k: sys.modules.get(k) for k in
                       ("PySide6", "PySide6.QtWidgets", "PySide6.QtGui",
                        "PySide6.QtCore") + _TAINTED}
        setup_fake_pyside6()
        for name in _TAINTED:
            sys.modules.pop(name, None)
        self.module = importlib.import_module("src.core.app_factory")
        self.AppFactory = self.module.AppFactory

    def tearDown(self):
        for name in _TAINTED:
            sys.modules.pop(name, None)
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_setup_working_directory_dev(self):
        with patch.object(sys, "frozen", False, create=True):
            with patch.object(self.module, "os") as os_mod:
                os_mod.getcwd.return_value = "cwd"
                self.AppFactory.setup_working_directory()
                os_mod.chdir.assert_called()

    def test_get_icon_path_dev(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            icon_path = base / "installer" / "assets" / "icon.ico"
            icon_path.parent.mkdir(parents=True, exist_ok=True)
            icon_path.write_text("x", encoding="utf-8")
            with patch.object(sys, "frozen", False, create=True):
                with patch.object(self.module, "Path", side_effect=lambda *a, **k: Path(*a, **k)):
                    with patch.object(self.module, "__file__", str(base / "src" / "core" / "app_factory.py")):
                        result = self.AppFactory.get_icon_path()
                        self.assertEqual(result, icon_path)
    
    def test_get_icon_path_frozen_with_meipass(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            meipass = base / "meipass"
            meipass.mkdir()
            icon_path = meipass / "installer" / "assets" / "icon.ico"
            icon_path.parent.mkdir(parents=True, exist_ok=True)
            icon_path.write_text("x", encoding="utf-8")
            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "_MEIPASS", str(meipass), create=True):
                    with patch.object(sys, "executable", str(base / "app.exe"), create=True):
                        result = self.AppFactory.get_icon_path()
                        self.assertEqual(result, icon_path)
    
    def test_get_icon_path_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.object(sys, "frozen", False, create=True):
                with patch.object(self.module, "Path", side_effect=lambda *a, **k: Path(*a, **k)):
                    with patch.object(self.module, "__file__", str(base / "src" / "core" / "app_factory.py")):
                        with patch.object(Path, "exists", return_value=False):
                            result = self.AppFactory.get_icon_path()
                            self.assertIsNone(result)

    def test_create_app_calls_theme(self):
        with patch.object(self.AppFactory, "get_icon_path", return_value=None):
            with patch.object(self.AppFactory, "setup_working_directory"):
                with patch("src.utils.themes.apply_theme") as apply_theme:
                    with patch.object(self.module.AppConfig, "load_config", return_value={"theme": "dark"}):
                        app = self.AppFactory.create_app(apply_theme=True)
        self.assertIsNotNone(app)
        apply_theme.assert_called()
    
    def test_create_app_sets_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            icon_path = base / "icon.ico"
            icon_path.write_text("x", encoding="utf-8")
            with patch.object(self.AppFactory, "get_icon_path", return_value=icon_path):
                with patch.object(self.AppFactory, "setup_working_directory"):
                    app = self.AppFactory.create_app(apply_theme=False)
            self.assertIsNotNone(app.icon)

    def test_core_init_import(self):
        import src.core as core
        self.assertTrue(hasattr(core, "AppFactory"))
    
    def test_apply_theme_dark_and_blue(self):
        themes = importlib.import_module("src.utils.themes")
        app = sys.modules["PySide6.QtWidgets"].QApplication([])
        themes.apply_theme(app, "dark")
        self.assertIsNotNone(app.palette)
        self.assertIsNotNone(app.font)
        self.assertIsNotNone(app.stylesheet)
        themes.apply_theme(app, "blue")
        self.assertIsNotNone(app.stylesheet)
    
    def test_apply_theme_fallback(self):
        themes = importlib.import_module("src.utils.themes")
        app = sys.modules["PySide6.QtWidgets"].QApplication([])
        themes.apply_theme(app, "unknown")
        self.assertIsNotNone(app.palette)
    
    def test_get_modern_styles(self):
        themes = importlib.import_module("src.utils.themes")
        styles = themes.get_modern_styles()
        self.assertIn("groupbox", styles)
        self.assertIn("button_primary", styles)


if __name__ == "__main__":
    unittest.main()
