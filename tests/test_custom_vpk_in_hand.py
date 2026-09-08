"""
Чужой мод из VPK в руках класса.

Мод — это замена ИГРОВОГО оружия, и приложение может понять какого: путь
внутри VPK называет предмет (`models/weapons/c_models/c_sniperrifle/…`).
Дальше вид от первого лица собирается как обычно — скелет и анимации игровые,
меш из мода, — и мод видно в движении, а не одной статичной моделью.

Здесь проверяется сама связка: что опознанное оружие доезжает до сцены и что
оно не переживает уход к другому предмету.
"""

from __future__ import annotations

import unittest

from src.domain.preview.session import PreviewSession
from src.services.preview_vpk_mod_worker import _weapon_key_from_path


class DetectTests(unittest.TestCase):
    """Что мод заменяет — видно по пути внутри него."""

    def test_game_model_path_names_the_weapon(self):
        self.assertEqual(
            _weapon_key_from_path(
                'models/weapons/c_models/c_sniperrifle/c_sniperrifle.mdl'),
            'c_sniperrifle')

    def test_workshop_path_works_too(self):
        self.assertEqual(
            _weapon_key_from_path(
                'models/workshop_partner/weapons/c_models/c_shogun_kunai/'
                'c_shogun_kunai.mdl'),
            'c_shogun_kunai')

    def test_own_folder_names_nothing(self):
        """Мод со своей моделью (`models/psl/weapons/…`) ничего не заменяет."""
        self.assertIsNone(
            _weapon_key_from_path('models/psl/weapons/sword/sword.mdl'))


class SessionTests(unittest.TestCase):
    """Опознанное оружие живёт ровно до следующего предмета."""

    def setUp(self):
        self.s = PreviewSession()
        self.s.custom_vpk_mode = True
        self.s.custom_vpk_weapon = 'c_sniperrifle'
        self.s.custom_vpk_smd = 'C:/tmp/c_sniperrifle.smd'

    def test_reset_forgets_both(self):
        self.s.reset_custom_vpk()
        self.assertIsNone(self.s.custom_vpk_weapon)
        self.assertIsNone(self.s.custom_vpk_smd)

    def test_going_to_a_game_item_forgets_the_mod(self):
        """Иначе вид от первого лица показал бы предмет прошлого мода."""
        self.s.begin_game_model()
        self.assertIsNone(self.s.custom_vpk_weapon)
        self.assertIsNone(self.s.custom_vpk_smd)


if __name__ == '__main__':
    unittest.main()
