"""
Правило поиска иконки рюкзака: ключ каталога → путь внутри VPK.

Ключи в каталоге разные (путь из items_game, ключ оружия, путь к модели
шапки), а иконка одна и та же. Ошибка здесь не падает, а тихо показывает
чужую картинку, поэтому правило проверяется отдельно от VPK.
"""

import unittest

from src.services import backpack_icons


class IconLookupTests(unittest.TestCase):
    def setUp(self):
        backpack_icons._index = {
            'c_scattergun': 'materials/backpack/weapons/c_models/c_scattergun.vtf',
            'w_minigun': 'materials/backpack/weapons/w_models/w_minigun.vtf',
            'soldier_officer':
                'materials/backpack/player/items/soldier/soldier_officer.vtf',
        }
        self.addCleanup(setattr, backpack_icons, '_index', None)

    def find(self, key):
        return backpack_icons.vpk_path_for(key, 'textures.vpk')

    def test_weapon_key(self):
        self.assertEqual(self.find('c_scattergun'),
                         'materials/backpack/weapons/c_models/c_scattergun.vtf')

    def test_stock_weapon_falls_back_to_world_model_icon(self):
        """У стоковых иконка объявлена под мировой моделью: c_minigun → w_minigun."""
        self.assertEqual(self.find('c_minigun'),
                         'materials/backpack/weapons/w_models/w_minigun.vtf')

    def test_hat_key_is_a_model_path(self):
        self.assertEqual(
            self.find('models/player/items/soldier/soldier_officer.mdl'),
            'materials/backpack/player/items/soldier/soldier_officer.vtf')

    def test_declared_path_is_used_as_is(self):
        """image_inventory из items_game точен — индекс для него не нужен."""
        self.assertEqual(self.find('backpack/workshop/weapons/x/y'),
                         'materials/backpack/workshop/weapons/x/y.vtf')

    def test_backslashes_and_case(self):
        self.assertEqual(
            self.find(r'models\player\items\soldier\Soldier_Officer.mdl'),
            'materials/backpack/player/items/soldier/soldier_officer.vtf')

    def test_unknown_and_empty(self):
        for key in ('', 'c_nothing_like_this', 'models/x/nope.mdl'):
            self.assertIsNone(self.find(key), key)


if __name__ == '__main__':
    unittest.main()
