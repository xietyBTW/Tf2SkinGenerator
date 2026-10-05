"""
«Скопировать главную» у материалов «Прочего» (убер и зомби тела класса).

Вариант стоит в строке скина на месте тела, головы или глаз, и «главная» для
него — материал этого места: голове убера нужна голова, синему — синий.
Текстура тела на всём подряд давала кашу на голове и глазах.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import qc_skin_parser
from src.services.vpk_texture_builder import VpkTextureBuilder
from src.shared.constants import EXTRA_TEX_USE_MAIN

# Строки $texturegroup тела скаута (столбцы тела, головы и двух глаз).
ROWS = [
    ["scout_red", "scout_head_red", "eyeball_l", "eyeball_r"],
    ["scout_blue", "scout_head_blue", "eyeball_l", "eyeball_r"],
    ["scout_red_invun", "scout_head_red_invun", "eyeball_invun", "eyeball_invun"],
    ["scout_blue_invun", "scout_head_blue_invun", "eyeball_invun", "eyeball_invun"],
    ["scout_red_zombie_alphatest", "scout_head_zombie", "eyeball_zombie", "eyeball_zombie"],
]


VMT = '"VertexLitGeneric"\n{{\n\t"$basetexture" "models/{}"\n}}\n'


class VariantBaseTests(unittest.TestCase):
    def test_variant_takes_the_material_of_its_place(self):
        cases = {
            "scout_red_invun": "scout_red",
            "scout_head_red_invun": "scout_head_red",
            "scout_blue_invun": "scout_blue",
            "scout_head_blue_invun": "scout_head_blue",
            "scout_head_zombie": "scout_head_red",
            "eyeball_invun": None,       # на месте глаз: копировать нечего
            "missing": None,
        }
        for name, base in cases.items():
            self.assertEqual(qc_skin_parser.variant_base(ROWS, name), base, name)

    def test_mask_is_not_a_pair(self):
        # Убер-эффект шпиона стоит на месте маски, а маски сборка тела не
        # собирает (своя страница): копировать для него нечего.
        rows = [["spy_head_red", "mask_spy"], ["spy_head_blue", "mask_spy"],
                ["spy_head_red_invun", "invulnfx_red"]]
        self.assertIsNone(qc_skin_parser.variant_base(rows, "invulnfx_red"))

    def test_team_decides_when_names_differ(self):
        # У хэви тело hvyweapon_*, а зомби heavy_*: общего начала нет, и
        # синему зомби досталось бы красное тело.
        rows = [["heavy_head_red", "hvyweapon_red"], ["heavy_head_blue", "hvyweapon_blue"],
                ["heavy_head_zombie", "heavy_red_zombie_alphatest"],
                ["heavy_head_zombie", "heavy_blue_zombie_alphatest"]]
        self.assertEqual(qc_skin_parser.variant_base(rows, "heavy_blue_zombie_alphatest"),
                         "hvyweapon_blue")
        self.assertEqual(qc_skin_parser.variant_base(rows, "heavy_red_zombie_alphatest"),
                         "hvyweapon_red")
        self.assertEqual(qc_skin_parser.variant_base(rows, "heavy_head_zombie"), "heavy_head_red")


def _Slots(folder):
    from src.services.build_context import MaterialSlots
    return MaterialSlots(
        vtf_output_path=Path(folder), vmt_path=Path(folder) / "scout_red.vmt",
        patched_cdmaterials_path="console/models/player/scout",
        original_cdmaterials_paths=["models/player/scout"])


class CopyMainTests(unittest.TestCase):
    def test_variants_copy_their_own_pair(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as game:
            slots = _Slots(d)
            slots.vmt_path.write_text(VMT.format("scout_red"))
            slots.vtf("scout_red").write_bytes(b"body")
            slots.vtf("scout_head_red").write_bytes(b"head")
            originals = {}
            for name in ("scout_head_red_invun", "eyeball_invun", "scout_blue_invun"):
                originals[name] = Path(game) / f"{name}.vmt"
                originals[name].write_text(VMT.format(name))
            deferred = []
            with patch.object(VpkTextureBuilder, "_find_original_vmt",
                              side_effect=lambda name, ctx, s: str(originals.get(name, "")) or None):
                VpkTextureBuilder._build_extra_material_textures(
                    ["scout_head_red_invun", "eyeball_invun", "scout_blue_invun"], "scout",
                    None, slots, None, lambda *_: EXTRA_TEX_USE_MAIN, None,
                    tg_rows=ROWS, deferred=deferred)
                self.assertEqual(slots.vtf("scout_head_red_invun").read_bytes(), b"head")
                # Глазам копировать нечего: игровой VMT, без своей текстуры.
                self.assertFalse(slots.vtf("eyeball_invun").exists())
                self.assertIn("models/eyeball_invun", slots.vmt("eyeball_invun").read_text())
                # Синюю пару пишет BLU-цикл позже — вариант ждёт его.
                self.assertEqual(deferred, [("scout_blue_invun", "scout_blue")])
                slots.vtf("scout_blue").write_bytes(b"blue")
                VpkTextureBuilder._finish_variant_copies(deferred, None, slots)
            self.assertEqual(slots.vtf("scout_blue_invun").read_bytes(), b"blue")
            self.assertIn("console/models/player/scout/scout_blue_invun",
                          slots.vmt("scout_blue_invun").read_text())


ANIMATED = ('"VertexLitGeneric"\n{{\n\t"$basetexture" "models/{}"\n\t"Proxies"\n\t{{\n'
            '\t\t"AnimatedTexture"\n\t\t{{\n\t\t\t"animatedtexturevar" "$basetexture"\n'
            '\t\t\t"animatedtextureframenumvar" "$frame"\n'
            '\t\t\t"animatedtextureframerate" "12"\n\t\t}}\n\t}}\n}}\n')


class PairRulesTests(unittest.TestCase):
    def _build(self, d, game, names, prepare):
        slots = _Slots(d)
        slots.vmt_path.write_text(VMT.format("scout_red"))
        originals = {}
        for name in names:
            originals[name] = Path(game) / f"{name}.vmt"
            originals[name].write_text(VMT.format(name))
        prepare(slots)
        deferred = []
        with patch.object(VpkTextureBuilder, "_find_original_vmt",
                          side_effect=lambda name, ctx, s: str(originals.get(name, "")) or None):
            VpkTextureBuilder._build_extra_material_textures(
                names, "scout", None, slots, None, lambda *_: EXTRA_TEX_USE_MAIN, None,
                tg_rows=ROWS, deferred=deferred)
            VpkTextureBuilder._finish_variant_copies(deferred, None, slots)
        return slots

    def test_game_pair_keeps_the_variant_game(self):
        # Голова осталась игровой (ответ «из игры» дал копию её VTF): у
        # убер-головы «главная» — тоже игровая, а не копия игровой головы
        # под убер-шейдером. Так же, как у синего тела со ссылкой на игру.
        def prepare(slots):
            slots.vtf("scout_head_red").write_bytes(b"game head")
            slots.game_copies.add("scout_head_red")
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as game:
            slots = self._build(d, game, ["scout_head_red_invun", "scout_blue_invun"], prepare)
            self.assertFalse(slots.vtf("scout_head_red_invun").exists())
            self.assertFalse(slots.vtf("scout_blue_invun").exists())   # синей пары нет вовсе
            self.assertIn("models/scout_head_red_invun", slots.vmt("scout_head_red_invun").read_text())

    def test_animated_pair_animates_the_variant(self):
        def prepare(slots):
            slots.vtf("scout_red").write_bytes(b"gif")
            slots.vmt_path.write_text(ANIMATED.format("scout_red"))
            slots.vtf("scout_blue").write_bytes(b"gif blue")
            slots.vmt("scout_blue").write_text(ANIMATED.format("scout_blue"))
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as game:
            slots = self._build(d, game, ["scout_red_invun", "scout_head_red_invun"], prepare)
            self.assertEqual(VpkTextureBuilder._basetexture_fps(slots.vmt("scout_red_invun")), 12)
            self.assertFalse(slots.vtf("scout_head_red_invun").exists())   # головы своей нет

    def test_deferred_blue_variant_animates_too(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as game:
            slots = _Slots(d)
            slots.vtf("scout_blue").write_bytes(b"gif blue")
            slots.vmt("scout_blue").write_text(ANIMATED.format("scout_blue"))
            orig = Path(game) / "scout_blue_invun.vmt"
            orig.write_text(VMT.format("scout_blue_invun"))
            with patch.object(VpkTextureBuilder, "_find_original_vmt", return_value=str(orig)):
                VpkTextureBuilder._finish_variant_copies(
                    [("scout_blue_invun", "scout_blue")], None, slots)
            self.assertEqual(slots.vtf("scout_blue_invun").read_bytes(), b"gif blue")
            self.assertEqual(VpkTextureBuilder._basetexture_fps(slots.vmt("scout_blue_invun")), 12)


class SharedTextureTests(unittest.TestCase):
    def test_heavy_hands_follow_the_body(self):
        # Руки хэви (hvyweapon_red_sheen) в игре смотрят на текстуру тела:
        # со своей текстурой тела они оставались стоковыми. Материал части
        # (редактируемое имя) со своей логикой игровой строки не трогается.
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as game:
            slots = _Slots(d)
            body_game = Path(game) / "hvyweapon_red.vmt"
            body_game.write_text(VMT.format("player/hvyweapon/hvyweapon_red"))
            slots.vtf("hvyweapon_red").write_bytes(b"custom body")
            slots.vmt("hvyweapon_red").write_text(VMT.format("x"))
            for name in ("hvyweapon_red_sheen", "hvyweapon_red_part1_blue"):
                slots.vmt(name).write_text(VMT.format("player/hvyweapon/hvyweapon_red"))
            with patch.object(VpkTextureBuilder, "_find_original_vmt",
                              side_effect=lambda name, ctx, s: str(body_game)
                              if name == "hvyweapon_red" else None):
                VpkTextureBuilder._follow_shared_textures(None, slots)
            self.assertIn("console/models/player/scout/hvyweapon_red",
                          slots.vmt("hvyweapon_red_sheen").read_text())
            self.assertIn("models/player/hvyweapon/hvyweapon_red",
                          slots.vmt("hvyweapon_red_part1_blue").read_text())
            self.assertNotIn("console", slots.vmt("hvyweapon_red_part1_blue").read_text())

    def test_game_copy_is_not_followed(self):
        # Тело осталось игровым (копия игровой VTF) — рукам следовать не за чем.
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as game:
            slots = _Slots(d)
            body_game = Path(game) / "hvyweapon_red.vmt"
            body_game.write_text(VMT.format("player/hvyweapon/hvyweapon_red"))
            slots.vtf("hvyweapon_red").write_bytes(b"game body")
            slots.game_copies.add("hvyweapon_red")
            slots.vmt("hvyweapon_red_sheen").write_text(VMT.format("player/hvyweapon/hvyweapon_red"))
            with patch.object(VpkTextureBuilder, "_find_original_vmt", return_value=str(body_game)):
                VpkTextureBuilder._follow_shared_textures(None, slots)
            self.assertNotIn("console", slots.vmt("hvyweapon_red_sheen").read_text())


class EditedVmtTests(unittest.TestCase):
    """Правка VMT из редактора у доп. материалов: раньше сборка брала только
    правку главного, а голова и «Прочее» уходили в мод игровыми."""

    def test_edits_reach_extra_materials(self):
        from src.services.edited_vmt_service import EditedVMTService
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as game, \
                tempfile.TemporaryDirectory() as edits:
            slots = _Slots(d)
            slots.vmt_path.write_text(VMT.format("scout_red"))
            slots.vtf("scout_head_red").write_bytes(b"head")
            originals = {}
            for name in ("scout_head_red_invun", "scout_head_zombie"):
                originals[name] = Path(game) / f"{name}.vmt"
                originals[name].write_text(VMT.format(name))
            answers = {"scout_head_red_invun": EXTRA_TEX_USE_MAIN,
                       "scout_head_zombie": EXTRA_TEX_USE_GAME_ORIGINAL}
            with patch.object(EditedVMTService, "EDITED_VMT_DIR", edits), \
                    patch.object(VpkTextureBuilder, "_find_original_vmt",
                                 side_effect=lambda name, ctx, s: str(originals.get(name, "")) or None):
                for name in answers:
                    EditedVMTService.save_edited_vmt(
                        name, VMT.format(name).replace("}", '\t"$selfillum" "1"\n}'))
                VpkTextureBuilder._build_extra_material_textures(
                    list(answers), "scout", None, slots, None,
                    lambda name, *_: answers[name], None, tg_rows=ROWS, deferred=[])
            invun = slots.vmt("scout_head_red_invun").read_text()
            zombie = slots.vmt("scout_head_zombie").read_text()
        # Своя текстура (копия головы): $basetexture правки ведёт на неё.
        self.assertIn("$selfillum", invun)
        self.assertIn("console/models/player/scout/scout_head_red_invun", invun)
        # Игровой: правка как есть, текстура игровая.
        self.assertIn("$selfillum", zombie)
        self.assertIn("models/scout_head_zombie", zombie)

    def test_hat_without_game_paints_strips_the_edit(self):
        # Второй материал шапки: правка начинается с игрового VMT с краской.
        # Без «Красок из игры» главный её теряет, и второй должен тоже.
        from src.services.edited_vmt_service import EditedVMTService

        painted = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/x"\n'
                   '\t"$colortint_base" "{ 255 255 255 }"\n\t"Proxies"\n\t{\n'
                   '\t\t"ItemTintColor"\n\t\t{\n\t\t\t"resultVar" "$colortint_tmp"\n\t\t}\n\t}\n}\n')
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as edits:
            slots = _Slots(d)
            target = slots.vmt("c_energydrink")
            target.write_text(VMT.format("x"))
            with patch.object(EditedVMTService, "EDITED_VMT_DIR", edits):
                EditedVMTService.save_edited_vmt("c_energydrink", painted)
                VpkTextureBuilder._apply_edited_vmt(
                    "c_energydrink", target, None, slots, True, strip_paints=True)
            text = target.read_text()
        self.assertNotIn("ItemTintColor", text)
        self.assertNotIn("$colortint_base", text)


if __name__ == "__main__":
    unittest.main()
