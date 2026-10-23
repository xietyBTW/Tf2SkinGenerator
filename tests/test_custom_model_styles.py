"""
Стили своей модели «со своими материалами» (и её Australium)

Игровая таблица скинов к такой модели не подходит, и сборка собирает свою из
того, что положено в стили «плюсиком». Без неё стили своей модели молча
пропадали бы из мода
"""

import os
import tempfile
import unittest

from src.app.build_editor import BuildEditor
from src.app.session import AppSession
from src.domain.preview.session import PreviewSession

#: Снайперка: строки 8 и 9 - Australium (RED и BLU одинаковые)
SNIPER = [["c_sniperrifle", "c_sniperrifle_gold"]] * 8 + [
    ["c_sniperrifle_gold", "c_sniperrifle_gold"]] * 2
#: Гильотина: стиль Bloody - строка 1
CLEAVER = [["c_sd_cleaver", "c_sd_cleaver_bloody"],
           ["c_sd_cleaver_bloody", "c_sd_cleaver_bloody"]]


def _preview(rows, styles=(), custom=True):
    ps = PreviewSession()
    ps.textures.skin_info = {"rows": rows, "styles": [list(s) for s in styles]}
    if custom:
        ps.custom_smd_path, ps.custom_keep_materials = "mine.smd", True
    ps.textures.material_names = ["body", "scope"]
    return ps


class StylesTests(unittest.TestCase):
    def test_own_model_gets_australium_as_a_style(self):
        ps = _preview(SNIPER)
        self.assertEqual(ps.styles(), [["Australium", 8]])
        self.assertEqual((ps.style_rows(8), ps.style_suffix(8)), ([8, 9], "gold"))

    def test_game_model_keeps_its_australium_switch(self):
        self.assertEqual(_preview(SNIPER, custom=False).styles(), [])

    def test_weapon_style_is_named_after_its_label(self):
        ps = _preview(CLEAVER, styles=[("Bloody", 1)])
        self.assertEqual(ps.styles(), [["Bloody", 1]])
        self.assertEqual((ps.style_rows(1), ps.style_suffix(1)), ([1], "bloody"))


class BuildDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.png = os.path.join(self.tmp.name, "gold.png")
        open(self.png, "wb").close()

    def tearDown(self):
        self.tmp.cleanup()

    def _session(self, ps):
        s = AppSession.__new__(AppSession)
        s.preview = ps
        s.building = BuildEditor(s)
        return s

    def test_australium_goes_into_both_gold_rows(self):
        ps = _preview(SNIPER)
        ps.textures.skin_overrides = {8: {"body": self.png}}
        data = self._session(ps).building._own_style_data()
        self.assertEqual(data["tg_overrides"], {8: {"body": "body_gold"}, 9: {"body": "body_gold"}})
        self.assertEqual(data["variant_files"], {"body_gold": self.png})
        self.assertEqual(data["mesh_materials"], ["body", "scope"])

    def test_game_model_builds_styles_by_itself(self):
        ps = _preview(CLEAVER, styles=[("Bloody", 1)], custom=False)
        ps.textures.skin_overrides = {1: {"body": self.png}}
        self.assertIsNone(self._session(ps).building._own_style_data())

    def test_nothing_in_styles_means_one_skin(self):
        self.assertIsNone(self._session(_preview(CLEAVER, styles=[("Bloody", 1)])).building._own_style_data())


if __name__ == "__main__":
    unittest.main()
