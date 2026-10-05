"""
Синяя строка скинов с ответом «из игры».

Синяя текстура и так лежит в игре: VMT мода смотрит на неё её путём (как у
золота), а копия VTF в моде была мёртвым весом. Если родной VMT смотрит на
текстуру с другим именем (синий цвет задан в самом VMT), всё по-старому.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import vmt_parse
from src.services.vpk_texture_builder import VpkTextureBuilder
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

MAIN_VMT = '"VertexLitGeneric"\n{\n\t"$basetexture" "console/models/x/c_gun"\n}\n'


def _Slots(folder):
    from src.services.build_context import MaterialSlots
    return MaterialSlots(
        vtf_output_path=Path(folder), vmt_path=Path(folder) / "c_gun.vmt",
        patched_cdmaterials_path="console/models/x", original_cdmaterials_paths=["models/x"])


def build(folder, game_texture, red_row=("c_gun",), blu_row=("c_gun_blue",), asked=None):
    slots = _Slots(folder)
    slots.vmt_path.write_text(MAIN_VMT)

    def answer(material, *_):
        if asked is not None:
            asked.append(material)
        return EXTRA_TEX_USE_GAME_ORIGINAL

    with patch.object(VpkTextureBuilder, "_game_texture", return_value=game_texture), \
            patch.object(VpkTextureBuilder, "_get_original_vtf_bytes", return_value=b"VTF-copy"):
        VpkTextureBuilder._build_blu_row_textures(
            list(blu_row), {"red_row": list(red_row)}, "c_gun", "c_gun.vtf", None, slots, None,
            answer, "c_gun", None, False, {})
    vmt = vmt_parse.parse(slots.vmt("c_gun_blue").read_text()).get("basetexture")
    return vmt, slots.vtf("c_gun_blue").exists()


class BluGameTextureTests(unittest.TestCase):
    def test_game_blue_is_linked_not_copied(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build(d, "models/x/c_gun_blue"), ("models/x/c_gun_blue", False))

    def test_same_blue_in_a_shared_column_is_asked_once(self):
        # Медиган: синий материал стоит и во втором столбце обеих строк.
        asked = []
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                build(d, "models/x/c_gun_blue", red_row=("c_gun", "c_gun_blue"),
                      blu_row=("c_gun_blue", "c_gun_blue"), asked=asked),
                ("models/x/c_gun_blue", False))
        self.assertEqual(asked, ["c_gun_blue"])

    def test_other_texture_keeps_the_old_copy(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build(d, "models/x/c_gun"), ("console/models/x/c_gun_blue", True))


if __name__ == "__main__":
    unittest.main()
