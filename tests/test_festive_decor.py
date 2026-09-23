"""
Праздничная версия оружия: гирлянда поверх модели, её правки и сборка.

Гирлянда — отдельная модель, которую игра рисует костями оружия. У одной
модели их бывает две: праздничная (`attached_models` праздничного предмета)
и фестивайзер (`attached_models_festive`). Формат блоков — из настоящего
items_game.txt.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.data import viewmodel_anims as VA
from src.services import vmt_parse

ITEMS_GAME = '''"items_game"
{
	"prefabs"
	{
		"weapon_scattergun"
		{
			"item_class" "tf_weapon_scattergun"
			"model_player" "models/weapons/c_models/c_scattergun.mdl"
			"visuals"
			{
				"attached_models_festive"
				{
					"0"
					{
						"model" "models/weapons/c_models/c_scattergun/c_scattergun_festivizer.mdl"
					}
				}
			}
		}
	}
	"items"
	{
		"13"
		{
			"name" "TF_WEAPON_SCATTERGUN"
			"prefab" "weapon_scattergun"
		}
		"669"
		{
			"name" "Festive Scattergun"
			"prefab" "weapon_scattergun"
			"visuals"
			{
				"attached_models"
				{
					"0"
					{
						"model" "models/weapons/c_models/c_scattergun/c_scattergun_xmas.mdl"
					}
				}
			}
		}
		"29"
		{
			"name" "TF_WEAPON_MEDIGUN"
			"model_player" "models/weapons/c_models/c_medigun/c_medigun.mdl"
			"visuals"
			{
				"attached_models_festive"
				{
					"0" { "model" "models/weapons/c_models/c_overhealer/c_overhealer_festivizer.mdl" }
				}
			}
		}
		"15008"
		{
			"name" "concealedkiller_medigun"
			"model_player" "models/weapons/c_models/c_medigun/c_medigun.mdl"
			"visuals"
			{
				"attached_models_festive"
				{
					"0" { "model" "models/weapons/c_models/c_medigun/c_medigun_festivizer.mdl" }
				}
			}
		}
		"208"
		{
			"name" "TF_WEAPON_FLAMETHROWER"
			"model_player" "models/weapons/c_models/c_flamethrower/c_flamethrower.mdl"
			"visuals"
			{
				"attached_models"
				{
					"0" { "model" "models/weapons/c_models/c_flamethrower/c_flamethrower_pilotlight.mdl" }
				}
			}
		}
		"1006"
		{
			"name" "Festive Ambassador"
			"model_player" "models/weapons/c_models/c_ambassador/c_ambassador_xmas.mdl"
			"visuals"
			{
				"attached_models_festive"
				{
					"0" { "model" "models/weapons/c_models/c_ambassador/c_ambassador_festivizer.mdl" }
				}
			}
		}
	}
}
'''


class DecorIndexTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        scripts = root / "tf" / "scripts" / "items"
        scripts.mkdir(parents=True)
        (scripts / "items_game.txt").write_text(ITEMS_GAME, encoding="utf-8")
        self.root = str(root)
        VA._MEM.pop(self.root, None)
        # Настоящий кэш пользователя тест трогать не должен.
        self._cache = patch.object(VA, "_CACHE_FILE", root / "cache.json")
        self._cache.start()

    def tearDown(self):
        self._cache.stop()
        VA._MEM.pop(self.root, None)
        self._tmp.cleanup()

    def test_both_kinds_are_collected_from_different_items(self):
        # Праздничную даёт один предмет, фестивайзер — префаб другого.
        self.assertEqual(VA.decor_models("c_scattergun", self.root), {
            "xmas": "models/weapons/c_models/c_scattergun/c_scattergun_xmas.mdl",
            "festivizer": "models/weapons/c_models/c_scattergun/c_scattergun_festivizer.mdl",
        })

    def test_own_garland_wins_over_the_first_one(self):
        self.assertEqual(VA.decor_models("c_medigun", self.root)["festivizer"],
                         "models/weapons/c_models/c_medigun/c_medigun_festivizer.mdl")

    def test_not_every_attached_model_is_a_garland(self):
        # Запальник огнемёта тоже висит в attached_models.
        self.assertEqual(VA.decor_models("c_flamethrower", self.root), {})

    def test_whole_festive_model_gets_no_garland(self):
        # Свой скелет с огоньками внутри: гирлянда базы легла бы не туда.
        self.assertEqual(VA.decor_models("c_ambassador_xmas", self.root), {})

    def test_garland_itself_offers_nothing(self):
        # anim_info отдал бы данные базы — decor_models ищет только точно.
        self.assertEqual(VA.decor_models("c_scattergun_xmas", self.root), {})
        self.assertEqual(VA.anim_info("c_scattergun_xmas", self.root).carried_on,
                         "c_scattergun")

    def test_cache_keeps_decor(self):
        VA.anim_index(self.root)
        VA._MEM.pop(self.root, None)
        again = VA.anim_index(self.root)["c_scattergun"]
        self.assertEqual(dict(again.decor)["xmas"],
                         "models/weapons/c_models/c_scattergun/c_scattergun_xmas.mdl")


GARLAND_VMT = '''"VertexlitGeneric"
{
	"$baseTexture" "models/weapons/c_items/festive_lights_red"
	"$detail" "effects/tiledfire/fireLayeredSlowTiled512.vtf"
	"Proxies"
	{
		"AnimatedTexture"
		{
			"animatedtexturevar" "$detail"
			"animatedtextureframenumvar" "$detailframe"
			"animatedtextureframerate" 30
		}
		"AnimatedTexture"
		{
			"animatedtexturevar" "$basetexture"
			"animatedtextureframenumvar" "$frame"
			"animatedtextureframerate" 1
		}
	}
}'''


class FramerateTests(unittest.TestCase):
    def test_base_texture_proxy_wins_over_the_first_one(self):
        # Первым идёт прокси огня: его 30 кадров мигали бы лампочками.
        self.assertEqual(vmt_parse.animated_framerate(GARLAND_VMT), 1.0)

    def test_proxies_inside_quality_branch_are_found(self):
        text = GARLAND_VMT.replace('"Proxies"', '">=DX90" { "Proxies"') + "}"
        self.assertEqual(vmt_parse.animated_framerate(text), 1.0)

    def test_single_proxy_without_var_still_works(self):
        text = '"LightmappedGeneric" { "Proxies" { "AnimatedTexture" ' \
               '{ "animatedtextureframerate" 12 } } }'
        self.assertEqual(vmt_parse.animated_framerate(text), 12.0)


class FirstPersonPrefixTests(unittest.TestCase):
    def test_garland_materials_are_marked_in_the_hand(self):
        from src.services import viewmodel_animation as VMA

        garland = {"positions": [0.0] * 9, "normals": [0.0] * 9, "uvs": [0.0] * 6,
                   "skinIndex": [0] * 12, "skinWeight": [1.0] * 12,
                   "groups": [{"material": "lights", "start": 0, "count": 3}],
                   "materials": ["lights"]}
        part = {"positions": [0.0] * 9, "normals": [0.0] * 9, "uvs": [0.0] * 6,
                "skinIndex": [0] * 12, "skinWeight": [1.0] * 12,
                "groups": [{"material": "gun", "start": 0, "count": 3}],
                "materials": ["gun"]}
        with patch.object(VMA, "_weapon_part", return_value=garland), \
                patch.object(VMA, "_merge_names", return_value=[]):
            VMA._add_carrier(part, "decor.smd", None, {}, "anim.smd", prefix="deco:")
        self.assertEqual(part["materials"], ["gun", "deco:lights"])
        self.assertEqual(part["groups"][1], {"material": "deco:lights",
                                             "start": 3, "count": 3})



class DecorStateTests(unittest.TestCase):
    """Карточки гирлянды в состоянии текстур: нейтральны, без стилей, мимо сборки оружия."""

    CARD = "deco:festivizer/festive_lights_red"

    def setUp(self):
        from src.domain.preview.session import PreviewSession
        self._tmp = TemporaryDirectory()
        self.png = str(Path(self._tmp.name) / "a.png")
        Path(self.png).write_bytes(b"x")
        self.s = PreviewSession()
        self.s.textures.material_names = ["__single__"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_style_does_not_capture_garland_texture(self):
        t = self.s.textures
        t.skin_info = {"num_skins": 3}
        t.active_skin = 2
        t.set_texture(self.CARD, self.png)
        self.assertEqual(t.skin_overrides, {})
        self.assertEqual(t.resolve_card(self.CARD), self.png)

    def test_garland_is_neutral_and_out_of_weapon_build(self):
        t = self.s.textures
        t.set_texture(self.CARD, self.png)
        self.assertEqual(t.textures["blu"][self.CARD], self.png)
        self.assertNotIn(self.CARD, t.uploaded_slot_paths())
        self.assertNotIn(self.CARD, t.blu_uploaded_paths())
        self.assertEqual(t.decor_uploads(), {self.CARD: {"red": self.png, "blu": self.png}})

    def test_team_lights_are_edited_per_team(self):
        # У огоньков фестивайзера синие кадры свои: правка на RED синих не
        # трогает, и в сборку синяя пара уходит игровой.
        t = self.s.textures
        red_png, blu_png = self.png, str(Path(self._tmp.name) / "b.png")
        Path(blu_png).write_bytes(b"y")
        t.decor_stock = {"red": {self.CARD: red_png}, "blu": {self.CARD: blu_png}}
        self.assertTrue(t.is_team_material(self.CARD))
        t.set_texture(self.CARD, red_png)
        self.assertNotIn(self.CARD, t.textures["blu"])
        self.assertEqual(t.decor_uploads()[self.CARD], {"red": red_png, "blu": ""})

    def test_stock_frame_lives_apart_from_weapon_maps(self):
        t = self.s.textures
        t.decor_stock = {"red": {self.CARD: self.png}}
        t.vpk_red_tex_map = {}          # перезагрузка модели оружия его не стирает
        self.assertEqual(t.game_base(self.CARD), self.png)

    def test_cards_and_edits(self):
        from src.domain.preview.session import has_real_edits
        self.s.decor_cards = [self.CARD]
        self.assertEqual(self.s.card_materials(), ["__single__", self.CARD])
        self.s.decor_fit = {"festivizer": {"scale": 1.5, "rotate": [0, 0, 0], "offset": [0, 0, 0]}}
        edits = self.s.user_edits()
        self.assertTrue(has_real_edits(edits))
        self.s.begin_item("c_bat", "scout_c_bat")
        self.assertEqual((self.s.decor_fit, self.s.decor_cards), ({}, []))
        self.s.apply_user_edits(edits)
        self.assertEqual(self.s.decor_fit["festivizer"]["scale"], 1.5)


class DecorBuildTests(unittest.TestCase):
    def test_card_names_round_trip(self):
        from src.services import festive_decor as fd
        self.assertEqual(fd.parse_card(fd.card("xmas", "xms_colored_lights")),
                         ("xmas", "xms_colored_lights"))
        self.assertEqual(fd.parse_card("c_scattergun"), ("", ""))

    def test_blue_image_goes_to_team_pair(self):
        from src.services.decor_build import _images_by_material
        out = _images_by_material(
            {"festive_lights_red": {"red": "r.png", "blu": "b.png"},
             "festivizer_battery": {"red": "k.png", "blu": "k.png"}},
            {"festive_lights_red": "festive_lights_blue",
             "festivizer_battery": "festivizer_battery"})
        self.assertEqual(out, {"festive_lights_red": "r.png",
                               "festive_lights_blue": "b.png",
                               "festivizer_battery": "k.png"})

    def test_cdmaterials_collapse_into_own_folder(self):
        from src.services.decor_build import _set_cdmaterials
        with TemporaryDirectory() as tmp:
            qc = Path(tmp) / "g.qc"
            qc.write_text('$modelname "a.mdl"\n$cdmaterials "models/weapons/c_items/"\n'
                          '$cdmaterials ""\n$texturegroup "skinfamilies"\n', encoding="utf-8")
            _set_cdmaterials(str(qc), "models/tf2sg_decor/g")
            text = qc.read_text(encoding="utf-8")
        self.assertEqual(text.count("$cdmaterials"), 1)
        self.assertIn('$cdmaterials "models/tf2sg_decor/g', text)
        self.assertNotIn("c_items", text)

    def test_only_garland_means_no_weapon_build(self):
        from src.services.build_request import BuildRequest
        from src.services.vpk_service import VPKService
        decor = [{"kind": "festivizer", "mdl": "m.mdl", "fit": None, "textures": {}}]
        self.assertTrue(VPKService._is_decor_only(BuildRequest(decor_builds=decor)))
        self.assertFalse(VPKService._is_decor_only(
            BuildRequest(decor_builds=decor, image_path="x.png")))
        self.assertFalse(VPKService._is_decor_only(BuildRequest()))


SMD = """version 1
nodes
  0 "weapon_bone" -1
end
skeleton
time 0
  0 0 0 0 0 0 0
end
triangles
wire
  0 0 0 0 0 0 1 0 0
  0 10 0 0 0 0 1 1 0
  0 20 0 0 0 0 1 1 1
bulb
  0 10 5 0 0 0 1 0 0
  0 10.5 5 0 0 0 1 1 0
  0 10 5.5 0 0 0 1 1 1
wire
  0 20 0 0 0 0 1 0 0
  0 30 0 0 0 0 1 1 0
  0 20 3 0 0 0 1 1 1
end
"""


class DecorBendTests(unittest.TestCase):
    """Изгиб гирлянды: лампочки целиком, провод гнётся, порядок как у разбора."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.smd = str(Path(self._tmp.name) / "g.smd")
        Path(self.smd).write_text(SMD, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_small_piece_is_rigid_wire_is_not(self):
        from src.services import festive_decor as fd
        groups = fd.bend_groups(self.smd, "deco:k/")
        self.assertEqual(list(groups), ["deco:k/wire", "deco:k/bulb"])
        self.assertEqual(set(groups["deco:k/wire"]), {-1})
        self.assertEqual(len(set(groups["deco:k/bulb"])), 1)
        self.assertGreaterEqual(groups["deco:k/bulb"][0], 0)

    def test_order_matches_the_obj_parser(self):
        from src.services import festive_decor as fd
        from src.services.smd_to_obj_service import SmdToObjService
        _lines, tris = fd._smd_triangles(SMD)
        ours = [pt for tri in tris for pt in tri[2]]
        theirs = [tuple(v["pos"]) for tris_ in
                  SmdToObjService._parse_triangles_by_mat(self.smd).values()
                  for tri in tris_ for v in tri]
        self.assertEqual(ours, theirs)

    def test_bend_moves_near_vertices_and_bulb_as_a_whole(self):
        from src.services import festive_decor as fd
        from src.services.smd_to_obj_service import SmdToObjService
        out = str(Path(self._tmp.name) / "b.smd")
        fd.bend_smd(self.smd, out, [{"c": [10, 5, 0], "r": 3, "d": [0, 0, 2]}])
        tris = SmdToObjService._parse_triangles_by_mat(out)
        bulb = [v["pos"] for tri in tris["bulb"] for v in tri]
        shifts = {round(p[2] - z, 6) for p, z in zip(bulb, (0, 0, 0))}
        self.assertEqual(len(shifts), 1)             # целиком, не смята
        self.assertGreater(shifts.pop(), 0)
        far = tris["wire"][1][1]["pos"]              # (30, 0, 0) — вне радиуса
        self.assertEqual(far, (30.0, 0.0, 0.0))

    def test_shaped_smd_without_edits_is_the_source(self):
        from src.services import festive_decor as fd
        self.assertEqual(fd.shaped_smd(self.smd, None, []), self.smd)

    def test_bend_made_in_the_preview_pose_lands_there_in_the_build(self):
        # Превью показывает гирлянду в позе оружия и гнут её там; сборка
        # гнёт SMD в исходной позе. Поставленный обратно в позу результат
        # сборки обязан совпасть с тем, что видели в превью.
        from src.services import festive_decor as fd, smd_pose
        from src.services.smd_to_obj_service import SmdToObjService
        pose = {0: (0.0, -1.0, 0.0, 1.0,     # поворот на 90° вокруг Z и сдвиг
                    1.0, 0.0, 0.0, 2.0,
                    0.0, 0.0, 1.0, 0.0)}
        bend = [{"c": [0, 10, 0], "r": 6, "d": [1, 2, 3]}]
        out = str(Path(self._tmp.name) / "p.smd")
        fd.bend_smd(self.smd, out, bend, pose)

        src = SmdToObjService._parse_triangles_by_mat(self.smd)
        got = SmdToObjService._parse_triangles_by_mat(out)
        seen = [list(smd_pose.apply_to_vertex(pose, v["links"], v["pos"], v["nrm"])[0])
                for tris in src.values() for tri in tris for v in tri]
        groups = [g for gs in fd.bend_groups(self.smd, "").values() for g in gs]
        fd.apply_bends(seen, groups, bend)
        built = [smd_pose.apply_to_vertex(pose, v["links"], v["pos"], v["nrm"])[0]
                 for tris in got.values() for tri in tris for v in tri]
        for a, b in zip(seen, built):
            for k in range(3):
                self.assertAlmostEqual(a[k], b[k], places=4)


class BlinkTests(unittest.TestCase):
    """Своя текстура лампочек мигает кадрами игровой: цвет свой, ритм и
    свечение — игровые."""

    def setUp(self):
        from PIL import Image
        self._tmp = TemporaryDirectory()
        d = Path(self._tmp.name)
        # Две «лампочки» по пикселю: в кадре 0 горит левая, в кадре 1 — правая.
        self.stock = []
        for k, (left, right) in enumerate([((200, 0, 0, 255), (0, 20, 0, 0)),
                                           ((20, 0, 0, 0), (0, 200, 0, 255))]):
            im = Image.new("RGBA", (2, 1))
            im.putpixel((0, 0), left)
            im.putpixel((1, 0), right)
            path = str(d / f"s{k}.png")
            im.save(path)
            self.stock.append(path)
        self.d = d

    def tearDown(self):
        self._tmp.cleanup()

    def test_lit_frame_has_every_bulb_on(self):
        from PIL import Image
        from src.services import festive_decor as fd
        lit = Image.open(fd.lit_frame(self.stock, str(self.d / "lit.png")))
        self.assertEqual(lit.getpixel((0, 0)), (200, 0, 0, 255))
        self.assertEqual(lit.getpixel((1, 0)), (0, 200, 0, 255))

    def test_own_colour_blinks_like_the_game(self):
        from PIL import Image
        from src.services import festive_decor as fd
        own = Image.new("RGB", (2, 1), (0, 0, 250))       # обе перекрасили в синий
        own_path = str(self.d / "own.png")
        own.save(own_path)
        frames = [Image.open(p) for p in fd.blink_like(own_path, self.stock,
                                                        str(self.d / "out"), "b")]
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].getpixel((0, 0)), (0, 0, 250, 255))   # горит
        self.assertEqual(frames[0].getpixel((1, 0))[3], 0)               # не светится
        self.assertLess(frames[0].getpixel((1, 0))[2], 30)               # погашена
        self.assertEqual(frames[1].getpixel((1, 0)), (0, 0, 250, 255))

    def test_single_frame_texture_is_left_alone(self):
        from src.services import festive_decor as fd
        self.assertEqual(fd.blink_like("own.png", self.stock[:1], str(self.d), "b"),
                         ["own.png"])


if __name__ == "__main__":
    unittest.main()
