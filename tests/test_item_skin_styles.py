"""
Строки скина, которые в игре - отдельный предмет (Критокола у модели Бонка),
становятся стилями с его именем, строки-копии - нет
"""

import unittest
from unittest import mock

from src.services.skin_detect_worker import SkinDetectWorker


def _styles(weapon_key, rows, named):
    worker = SkinDetectWorker(weapon_key, f"scout_{weapon_key}", "C:/tf2/tf/tf2_misc_dir.vpk", "ru")
    info = {'rows': rows, 'styles': [],
            'skins': [{'index': i, 'role': f'Skin {i}'} for i in range(len(rows))]}
    with mock.patch('src.data.weapon_model_index.tf2_root_from_misc_vpk', return_value='C:/tf2'), \
         mock.patch('src.data.item_skin_styles.styled_skins', return_value=named):
        return worker._with_item_styles(info)


class ItemSkinStylesTests(unittest.TestCase):
    def test_crit_a_cola_is_a_named_style_of_the_bonk_model(self):
        rows = [['c_energydrink'], ['c_energydrink_blu'], ['c_energydrink_purp']]
        info = _styles('c_energy_drink', rows, [('Критокола', 2)])
        self.assertEqual(info['styles'], [('Критокола', 2)])
        self.assertEqual(info['skins'][2]['role'], 'Критокола')

    def test_copy_of_an_earlier_row_is_not_a_style(self):
        # Ботоубийцы огнемёта: строки 3/5 - та же синяя, править нечего
        rows = [['c_flamethrower'], ['c_flamethrower_blue']] * 3
        info = _styles('c_flamethrower', rows, [('Ботоубийца', 3), ('Ржавый', 5)])
        self.assertEqual(info['styles'], [])


if __name__ == '__main__':
    unittest.main()
