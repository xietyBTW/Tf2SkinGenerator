"""Тесты чистой логики выбора 2D-карточек материалов."""

import unittest

from src.ui.material_cards import (
    MaterialCardSpec, editable_material_cards, spy_mask_cards,
)


class EditableMaterialCardsTests(unittest.TestCase):
    def test_filters_service_materials(self):
        specs = editable_material_cards(["c_scattergun", "eyeball_l", "c_scattergun_shell"])
        names = [s.name for s in specs]
        self.assertIn("c_scattergun", names)
        self.assertIn("c_scattergun_shell", names)
        self.assertNotIn("eyeball_l", names)   # служебный — отброшен

    def test_name_equals_display(self):
        specs = editable_material_cards(["c_rocketlauncher"])
        self.assertEqual(specs[0], MaterialCardSpec("c_rocketlauncher", "c_rocketlauncher"))

    def test_dedup_preserves_order(self):
        specs = editable_material_cards(["a", "b", "a", "c"])
        self.assertEqual([s.name for s in specs], ["a", "b", "c"])

    def test_all_service_falls_back_to_all(self):
        # Вся модель «служебная» → не оставляем пусто, показываем всё.
        specs = editable_material_cards(["eyeball_l", "eyeball_r"])
        self.assertEqual([s.name for s in specs], ["eyeball_l", "eyeball_r"])

    def test_empty_input(self):
        self.assertEqual(editable_material_cards([]), [])


class SpyMaskCardsTests(unittest.TestCase):
    def test_display_names_localized(self):
        specs_en = spy_mask_cards(["mask_scout", "mask_spy"], lang="en")
        self.assertEqual(specs_en[0].name, "mask_scout")
        self.assertEqual(specs_en[0].display_name, "Scout")
        specs_ru = spy_mask_cards(["mask_scout"], lang="ru")
        self.assertEqual(specs_ru[0].display_name, "Разведчик")

    def test_unknown_mask_falls_back_to_name(self):
        specs = spy_mask_cards(["mask_unknown"])
        self.assertEqual(specs[0].display_name, "mask_unknown")

    def test_dedup(self):
        specs = spy_mask_cards(["mask_scout", "mask_scout"])
        self.assertEqual(len(specs), 1)


if __name__ == "__main__":
    unittest.main()
