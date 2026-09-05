"""
Список насмешек с реквизитом из items_game.

Руками таких таблиц не держат: в игре их девяносто с лишним, и каждое
обновление приносит новые. Здесь проверяются правила разбора, на которых
список стоит: какой блок читать, какую модель считать главной и откуда брать
имя с иконкой.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.data import taunt_catalog

#: Два предмета: всеклассовая насмешка с моделью на каждый класс и одноклассовая.
#: В первом нарочно лежит `model_player_per_class` — блок с такими же строками
#: `"класс" "модель"`, но не про реквизит.
ITEMS_GAME = '''
"items_game"
{
\t"items"
\t{
\t\t"1"
\t\t{
\t\t\t"name"\t"The Test Riff"
\t\t\t"item_name"\t"#TF_TestRiff"
\t\t\t"image_inventory"\t"backpack\\workshop\\taunts\\riff"
\t\t\t"model_player_per_class"
\t\t\t{
\t\t\t\t"scout"\t"models/player/items/scout/НЕ_РЕКВИЗИТ.mdl"
\t\t\t}
\t\t\t"taunt"
\t\t\t{
\t\t\t\t"custom_taunt_prop_per_class"
\t\t\t\t{
\t\t\t\t\t"scout"\t"models/workshop/taunts/riff/riff.mdl"
\t\t\t\t\t"heavy"\t"models/workshop/taunts/riff/riff_xl.mdl"
\t\t\t\t}
\t\t\t}
\t\t}
\t\t"2"
\t\t{
\t\t\t"item_name"\t"#TF_TestSolo"
\t\t\t"image_inventory"\t"backpack/workshop/taunts/solo"
\t\t\t"taunt"
\t\t\t{
\t\t\t\t"custom_taunt_prop_per_class"
\t\t\t\t{
\t\t\t\t\t"medic"\t"models/workshop/taunts/solo/solo.mdl"
\t\t\t\t}
\t\t\t}
\t\t}
\t\t"3"
\t\t{
\t\t\t"item_name"\t"#TF_JustAHat"
\t\t}
\t}
}
'''

LOCALIZATION = {
    'TF_TestRiff': 'Насмешка: Тестовый рифф',
    'TF_TestSolo': 'Соло без приставки',
}


class LoadTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        path = Path(self.root) / 'tf' / 'scripts' / 'items'
        path.mkdir(parents=True)
        (path / 'items_game.txt').write_text(ITEMS_GAME, encoding='utf-8')

    def _load(self):
        import src.data.hats_parser as hats

        was = hats.parse_localization
        hats.parse_localization = lambda root, lang: dict(LOCALIZATION)
        try:
            return taunt_catalog.load(self.root)
        finally:
            hats.parse_localization = was

    def test_only_items_with_a_prop_get_in(self):
        """У шапки блока насмешки нет — ей в этом списке не место."""
        self.assertEqual(sorted(self._load()), ['riff', 'solo'])

    def test_key_and_path_come_from_the_scouts_model(self):
        """У всеклассовой насмешки девять моделей, разница только в размере.

        Разведчик есть у каждой такой, и ключ выходит тот же, что был выверен
        руками (`taunt_cheers_scout`, `brutal_guitar`).
        """
        self.assertEqual(self._load()['riff']['mdl_path'],
                         'models/workshop/taunts/riff/riff.mdl')

    def test_model_outside_the_prop_block_is_not_taken(self):
        """`model_player_per_class` — это косметика предмета, а не реквизит."""
        paths = {row['mdl_path'] for row in self._load().values()}
        self.assertTrue(all('НЕ_РЕКВИЗИТ' not in p for p in paths))

    def test_name_loses_the_taunt_prefix(self):
        """«Насмешка: Тестовый рифф» — приставка занимает пол-карточки."""
        self.assertEqual(self._load()['riff']['ru'], 'Тестовый рифф')

    def test_name_without_a_prefix_is_left_alone(self):
        self.assertEqual(self._load()['solo']['ru'], 'Соло без приставки')

    def test_icon_path_is_normalized(self):
        self.assertEqual(self._load()['riff']['icon'],
                         'backpack/workshop/taunts/riff')


class MergeTests(unittest.TestCase):
    """Влитие в общие таблицы: своё имя не терять, чужое добавить."""

    FOUND = {
        'riff': {'ru': 'Тестовый рифф', 'en': 'Test Riff',
                 'mdl_path': 'models/новый/путь.mdl', 'icon': 'backpack/riff'},
        'solo': {'ru': 'Соло', 'en': 'Solo',
                 'mdl_path': 'models/solo.mdl', 'icon': 'backpack/solo'},
    }

    def tearDown(self):
        from src.data import taunt_props, weapons

        for key in self.FOUND:
            taunt_props.TAUNT_PROPS.pop(key, None)
            taunt_props.TAUNT_PROP_MDL_PATHS.pop(key, None)
            weapons.WEAPON_MDL_PATHS.pop(key, None)

    def _merge(self):
        from src.data import taunt_props, weapons

        was_load, was_root = taunt_catalog.load, taunt_catalog._merged_root
        taunt_catalog.load = lambda root: {k: dict(v)
                                           for k, v in self.FOUND.items()}
        taunt_catalog._merged_root = ''
        try:
            added = taunt_catalog.merge('D:/игра')
        finally:
            taunt_catalog.load, taunt_catalog._merged_root = was_load, was_root
        return added, taunt_props.TAUNT_PROPS, weapons.WEAPON_MDL_PATHS

    def test_hand_written_name_survives_but_the_icon_is_taken(self):
        """Свои имена переведены руками и короче официальных.

        А иконки у ручной таблицы не было вовсе: карточкам рисовали обложку из
        текстуры модели, и у пачки денег выходило зелёное пятно.
        """
        from src.data.taunt_props import TAUNT_PROPS

        TAUNT_PROPS['riff'] = {'ru': 'Гитара', 'en': 'Guitar',
                               'mdl_path': 'models/старый/путь.mdl'}
        added, table, _ = self._merge()
        self.assertEqual(added, 1)                      # только solo
        self.assertEqual(table['riff']['ru'], 'Гитара')
        self.assertEqual(table['riff']['mdl_path'], 'models/старый/путь.mdl')
        self.assertEqual(table['riff']['icon'], 'backpack/riff')

    def test_new_prop_reaches_the_table_of_models(self):
        """Без этого сборка не найдёт MDL: путь ищут по общей таблице оружия."""
        _, _, mdl_paths = self._merge()
        self.assertEqual(mdl_paths['solo'], 'models/solo.mdl')


if __name__ == '__main__':
    unittest.main()
