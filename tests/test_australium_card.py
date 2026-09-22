"""
Австралий — своя карточка, а не переключатель показа поверх главной.

Раньше вариант только подменял картинку главной карточки игровым gold-кадром:
положить свою текстуру австралия было некуда, а части красили главную. Теперь
у варианта своя карточка с той же геометрией, и всё, что умеет карточка, —
текстура, части, настройки — у него своё.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.domain.preview.session import PreviewSession
from src.domain.preview.texture_state import SINGLE_TEX_KEY


class VariantCardTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.gold = str(root / 'gold.png')
        self.base = str(root / 'base.png')
        self.mine = str(root / 'mine.png')
        for p in (self.gold, self.base, self.mine):
            Image.new('RGBA', (4, 4), (255, 255, 255, 255)).save(p)
        s = PreviewSession()
        s.weapon_key = 'c_scattergun'
        t = s.textures
        t.material_names = [SINGLE_TEX_KEY]
        t.vpk_red_tex_map = {SINGLE_TEX_KEY: self.base}
        t.australium_frame = self.gold
        t.australium_mat_name = 'c_scattergun_gold'
        self.s, self.t = s, t

    def tearDown(self):
        self._dir.cleanup()

    def test_the_variant_card_stands_in_for_the_main_one_while_toggled(self):
        """Как RED/BLU: карточка одна, что на ней — решает переключатель."""
        self.assertEqual(self.s.card_materials(), [SINGLE_TEX_KEY])
        self.assertEqual(self.s.visible_textures(), {SINGLE_TEX_KEY: self.base})
        self.t.australium_active = True
        self.assertEqual(self.s.card_materials(), ['c_scattergun_gold'])
        self.assertEqual(self.s.visible_textures(), {'c_scattergun_gold': self.gold})

    def test_own_texture_on_the_variant_shows_on_the_model_when_toggled(self):
        self.t.set_texture('c_scattergun_gold', self.mine)
        # Главная не тронута ни в альбоме, ни на модели, пока вариант выключен.
        self.assertEqual(self.s.visible_textures()[SINGLE_TEX_KEY], self.base)
        self.assertEqual(self.s.scene_textures()[SINGLE_TEX_KEY], self.base)
        self.t.australium_active = True
        self.assertEqual(self.s.visible_textures()['c_scattergun_gold'], self.mine)
        self.assertEqual(self.t.variant_display_texture(), self.mine)
        self.assertEqual(self.s.scene_textures()[SINGLE_TEX_KEY], self.mine)

    def test_no_stand_in_for_a_vpk_mod(self):
        self.t.australium_active = True
        self.s.custom_vpk_mode = True
        self.assertEqual(self.s.card_materials(), [SINGLE_TEX_KEY])

    def test_variant_texture_goes_to_the_build_as_its_own_material(self):
        self.t.set_texture('c_scattergun_gold', self.mine)
        self.assertEqual(self.t.uploaded_slot_paths(), {'c_scattergun_gold': self.mine})
        self.assertEqual(self.t.uploaded_for_mat('c_scattergun_gold'), self.mine)


if __name__ == '__main__':
    unittest.main()
