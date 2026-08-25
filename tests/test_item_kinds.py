"""Классификация вида предмета — единый ответ вместо проверок по строке."""

import unittest

from src.data.item_kinds import kind_of
from src.data.player_characters import PLAYER_BODY_MODE_KEYS, SPY_MASK_MODE_KEY
from src.data.player_hands import HAND_MODE_KEYS


class KindOfTests(unittest.TestCase):
    def test_hat(self):
        kind = kind_of("hat")
        self.assertTrue(kind.is_hat)
        self.assertTrue(kind.asks_game_paints, "у шапок спрашиваем про краски")
        self.assertFalse(kind.multi_material)

    def test_hands(self):
        for mode in list(HAND_MODE_KEYS)[:3]:
            kind = kind_of(mode)
            self.assertTrue(kind.is_hands, mode)
            self.assertTrue(kind.multi_material, mode)
            self.assertFalse(kind.is_weapon, mode)

    def test_character_body(self):
        for mode in list(PLAYER_BODY_MODE_KEYS)[:3]:
            kind = kind_of(mode)
            self.assertTrue(kind.is_character, mode)
            self.assertTrue(kind.multi_material, mode)
            self.assertFalse(kind.model_is_z_up, mode)

    def test_spy_mask(self):
        kind = kind_of(SPY_MASK_MODE_KEY)
        self.assertTrue(kind.is_spy_mask)
        self.assertFalse(kind.is_character, "маски — не тело, у них своя панель")

    def test_weapon_is_the_default(self):
        for mode in ("scout_c_scattergun", "", None, "что-то новое"):
            self.assertTrue(kind_of(mode).is_weapon, mode)

    def test_kinds_are_mutually_exclusive(self):
        modes = ["hat", SPY_MASK_MODE_KEY, "scout_c_scattergun"]
        modes += list(HAND_MODE_KEYS)[:2] + list(PLAYER_BODY_MODE_KEYS)[:2]
        for mode in modes:
            kind = kind_of(mode)
            flags = [kind.is_hat, kind.is_hands, kind.is_character,
                     kind.is_spy_mask, kind.is_weapon]
            self.assertEqual(sum(flags), 1, f"{mode}: {flags}")

    def test_same_object_for_same_mode(self):
        """Вид — значение, а не состояние: можно сравнивать и кэшировать."""
        self.assertIs(kind_of("hat"), kind_of("hat"))
        self.assertEqual(kind_of("hat"), kind_of("hat"))


if __name__ == "__main__":
    unittest.main()
