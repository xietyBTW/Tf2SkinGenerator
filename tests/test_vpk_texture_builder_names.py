"""
Имена материалов своей модели в сборке.

«Material.001» из Blender studiomdl собирает как material_001 (нижний регистр,
точки — в подчёркивания): файлы мода обязаны лечь под тем же именем. Под сырым
именем главный материал получал лишний дубль текстуры, а второй материал —
фиолетовую шашку в игре (VMT лежал мимо модели), и карты с таких карточек
терялись.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.vpk_texture_builder import VpkTextureBuilder


class _Slots:
    def __init__(self, folder):
        self.vtf_output_path = Path(folder)
        self.vmt_path = Path(folder) / "material_001.vmt"
        self.patched_cdmaterials_path = "console/x"

    def vmt(self, name):
        return self.vtf_output_path / f"{name}.vmt"


def _settings(_name):
    return (256, 256), "DXT5", [], {}


class PanelExtrasNamesTests(unittest.TestCase):
    def test_dotted_cards_render_under_the_model_names(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "material_001.vtf").write_bytes(b"x")    # главный уже собран
            with patch.object(VpkTextureBuilder, "_run_extra_render_jobs") as run:
                VpkTextureBuilder._render_panel_extras(
                    {"Material.001": "a.png", "Paint.002": "b.png"}, set(), None,
                    _Slots(d), _settings)
            self.assertEqual([job[0] for job in run.call_args[0][0]], ["paint_002"])


class MaterialMapsNamesTests(unittest.TestCase):
    def test_maps_of_dotted_cards_reach_their_vmt(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "paint_002.vmt").write_text("x")
            derive = {"selfillum": {"derive": True}}
            with patch.object(VpkTextureBuilder, "_apply_maps_for_material") as apply:
                VpkTextureBuilder._build_material_maps(
                    {"Paint.002": derive, "Material.001": derive},
                    out, "material_001", out / "material_001.vmt", "console/x", (256, 256),
                    base_image_path="main.png", panel_extra_textures={"Paint.002": "b.png"})
            seen = {c.args[1]: (c.args[2], c.args[3]) for c in apply.call_args_list}
            self.assertEqual(seen["paint_002"], (out / "paint_002.vmt", "b.png"))
            self.assertEqual(seen["material_001"], (out / "material_001.vmt", "main.png"))


if __name__ == "__main__":
    unittest.main()
