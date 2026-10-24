"""Краска из игры на шапке, надетой на персонажа"""

import os
import tempfile
import unittest

from PIL import Image

from src.app.session import AppSession
from src.domain.preview.session import PreviewSession
from src.domain.preview.texture_state import SINGLE_TEX_KEY
from src.services import vmt_tint


class PaintInSceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        stock = os.path.join(self.tmp.name, "hat.png")
        Image.new("RGBA", (4, 4), (10, 10, 10, 255)).save(stock)
        # Как при извлечении: маска краски в альфе, рядом исходник
        vmt_tint.apply_to_png(stock, vmt_tint.TintSpec((189, 59, 59), 0.99))
        self.stock = stock

        ps = PreviewSession()
        ps.textures.material_names = [SINGLE_TEX_KEY]
        ps.textures.vpk_red_tex_map = {SINGLE_TEX_KEY: stock}
        # Сцена «На персонаже»: у шапки настоящее имя меша, рядом тело класса
        ps.scene_item_materials = ["xms_scout_elf_hat"]
        ps.scene_extra_textures = {"xms_scout_elf_hat": stock, "scout_red": stock}

        s = AppSession.__new__(AppSession)
        s.preview = ps
        s._paint = "pink"
        s.paints = lambda lang="ru": [{"key": "pink", "red": "#ff69b4", "blu": "#ff69b4"}]
        s._work_dir = lambda: self.tmp.name
        self.session = s

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_material_hat_is_painted_on_the_character(self):
        scene = self.session._painted(self.session.preview.scene_textures())
        self.assertNotEqual(scene["xms_scout_elf_hat"], self.stock)
        # Тело класса - не шапка: его краска шапки не касается
        self.assertEqual(scene["scout_red"], self.stock)
