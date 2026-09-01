"""
Настройки приложения через прикладной API.

Конфиг общий с окном, поэтому проверяется главное: страница не должна молча
менять то, чего в файле ещё нет.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app import api
from src.config.app_config import AppConfig
from src.data.material_filter import parse_blacklist


class BlacklistParsingTests(unittest.TestCase):
    """Список исключений человек пишет и строками, и через запятую."""

    def test_both_separators_work(self):
        self.assertEqual(parse_blacklist('a, b\nc'), ['a', 'b', 'c'])

    def test_repeats_and_blanks_are_dropped(self):
        self.assertEqual(parse_blacklist(' a \n\nA\n,,\nb'), ['a', 'b'])

    def test_empty_text_is_an_empty_list(self):
        self.assertEqual(parse_blacklist(''), [])


class SettingsRoundTripTests(unittest.TestCase):
    """Сохранение не должно менять то, чего пользователь не трогал."""

    def setUp(self):
        AppConfig.invalidate_cache()

    def tearDown(self):
        AppConfig.invalidate_cache()

    def _isolated(self, tmp: str) -> Path:
        config_dir = Path(tmp) / 'config'
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / 'settings.json'

    def test_unset_checkbox_keeps_its_app_default(self):
        """`particles_group_tree` в окне включён по умолчанию.

        Если отдать его как «не задан», страница покажет галку снятой и первое
        же сохранение молча выключит группировку дерева частиц.
        """
        with tempfile.TemporaryDirectory() as tmp:
            config_file = self._isolated(tmp)
            config_file.write_text(json.dumps({'language': 'ru'}), encoding='utf-8')
            with patch.object(AppConfig, 'CONFIG_FILE', config_file):
                self.assertIs(api.settings('ru')['values']['particles_group_tree'],
                              True)

    def test_saving_unchanged_values_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = self._isolated(tmp)
            with patch.object(AppConfig, 'CONFIG_FILE', config_file):
                before = api.settings('ru')['values']
                after = api.set_settings(dict(before), 'ru')['values']
                self.assertEqual(before, after)

    def test_unknown_keys_are_ignored(self):
        """Страница правит только свои ключи: геометрия окна ей не принадлежит."""
        with tempfile.TemporaryDirectory() as tmp:
            config_file = self._isolated(tmp)
            with patch.object(AppConfig, 'CONFIG_FILE', config_file):
                api.set_settings({'window_geometry': 'взлом',
                                  'export_folder': 'out'}, 'ru')
                saved = json.loads(config_file.read_text(encoding='utf-8'))
            self.assertEqual(saved['export_folder'], 'out')
            self.assertNotEqual(saved.get('window_geometry'), 'взлом')

    def test_empty_export_folder_falls_back(self):
        """Безымянная папка сломала бы сборку молча, на записи файла."""
        with tempfile.TemporaryDirectory() as tmp:
            config_file = self._isolated(tmp)
            with patch.object(AppConfig, 'CONFIG_FILE', config_file):
                values = api.set_settings({'export_folder': '   '}, 'ru')['values']
            self.assertEqual(values['export_folder'], 'export')

    def test_blacklist_accepts_text_from_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = self._isolated(tmp)
            with patch.object(AppConfig, 'CONFIG_FILE', config_file):
                values = api.set_settings(
                    {'material_blacklist': 'eyeball\nteeth, eyeball'}, 'ru')['values']
            self.assertEqual(values['material_blacklist'], ['eyeball', 'teeth'])


if __name__ == '__main__':
    unittest.main()
