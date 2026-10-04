"""Часть модели как отдельный материал: SMD, $texturegroup и VMT."""

import os
import tempfile
import unittest

from src.services import part_materials as pm
from src.services import vmt_parse

V = "0 0 0 0 0 0 1 {u} 0 1 0 1"


def tri(mat, u=0.0, bad=False):
    vert = "oops" if bad else V.format(u=u)
    return f"{mat}\n  {vert}\n  {V.format(u=u)}\n  {V.format(u=u)}\n"


def smd(*tris):
    return "version 1\nnodes\n0 \"root\" -1\nend\ntriangles\n" + "".join(tris) + "end\n"


class NamesTests(unittest.TestCase):
    def test_next_name_skips_taken(self):
        self.assertEqual(pm.next_name("C_Gun", []), "c_gun_part1")
        self.assertEqual(pm.next_name("c_gun", ["C_GUN_PART1"]), "c_gun_part2")
        # Под именем лежит правка VMT прежнего материала — новому она чужая.
        self.assertEqual(pm.next_name("c_gun", [], lambda n: n == "c_gun_part1"),
                         "c_gun_part2")

    def test_variant_names(self):
        self.assertEqual(pm.variant_name("c_x_part1", "c_x", "c_x_blue", 1), "c_x_part1_blue")
        self.assertEqual(pm.variant_name("hat_red_part1", "hat_red", "hat_blue", 1),
                         "hat_red_part1_blue")
        self.assertEqual(pm.variant_name("c_x_part1", "c_x", "c_x_gold", 8), "c_x_part1_gold")
        # Вариант — префикс исходного: хвоста нет, имя по номеру строки.
        self.assertEqual(pm.variant_name("c_xy_part1", "c_xy", "c_x", 2), "c_xy_part1_s2")


def names_in(text):
    return [ln.strip() for ln in text.split("triangles", 1)[1].splitlines()
            if ln.strip() and not ln.strip()[0].isdigit()]


class RenameTests(unittest.TestCase):
    def test_renames_picked_triangles_in_preview_order(self):
        text = smd(tri("gun", 0.1), tri("lens"), tri("gun", 0.2), tri("gun", 0.3))
        out, count, renamed = pm.rename_triangles(text, "gun", {0: "gun_part1", 2: "gun_part1"})
        self.assertEqual((count, renamed["gun_part1"]), (3, 2))
        self.assertEqual(names_in(out), ["gun_part1", "lens", "gun", "gun_part1", "end"])

    def test_two_parts_of_one_material_in_one_pass(self):
        # Вторая часть считает номера по исходному материалу, как и превью:
        # переименованная первой треугольник номера не теряет.
        text = smd(tri("gun"), tri("gun"), tri("gun"))
        out, count, renamed = pm.rename_triangles(text, "gun", {0: "gun_part1", 2: "gun_part2"})
        self.assertEqual(count, 3)
        self.assertEqual(names_in(out), ["gun_part1", "gun", "gun_part2", "end"])

    def test_broken_triangle_does_not_shift_numbers(self):
        # Превью пропускает треугольник с битой вершиной — номер его не занимает.
        text = smd(tri("gun", bad=True), tri("gun", 0.5))
        out, count, renamed = pm.rename_triangles(text, "gun", {0: "gun_part1"})
        self.assertEqual((count, renamed["gun_part1"]), (1, 1))
        self.assertEqual(out.count("gun_part1"), 1)
        self.assertLess(out.index("oops"), out.index("gun_part1"))

    def test_offset_continues_numbering_across_files(self):
        out, count, renamed = pm.rename_triangles(smd(tri("gun"), tri("gun")), "gun",
                                                  {3: "gun_part1"}, start=2)
        self.assertEqual((count, renamed["gun_part1"]), (2, 1))
        self.assertEqual(out.count("gun_part1"), 1)

    def test_keeps_text_outside_triangles(self):
        text = smd(tri("gun"))
        out, _, _ = pm.rename_triangles(text, "gun", {0: "gun_part1"})
        self.assertTrue(out.startswith("version 1\nnodes\n"))
        self.assertTrue(out.endswith("end\n"))


class TexturegroupTests(unittest.TestCase):
    def test_team_rows_get_their_own_part_column(self):
        rows = [["c_x", "c_lens"], ["c_x_blue", "c_lens"], ["c_x_gold", "c_lens"]]
        out, variants = pm.add_part_columns(rows, [("c_x_part1", "c_x")])
        self.assertEqual([r[-1] for r in out], ["c_x_part1", "c_x_part1_blue", "c_x_part1_gold"])
        self.assertEqual(variants, {"c_x_part1": "c_x", "c_x_part1_blue": "c_x_blue",
                                    "c_x_part1_gold": "c_x_gold"})
        self.assertEqual(rows[0], ["c_x", "c_lens"])        # вход не тронут

    def test_material_outside_group_stays_out(self):
        out, variants = pm.add_part_columns([["c_lens"]], [("c_x_part1", "c_x")])
        self.assertEqual(out, [["c_lens"]])
        self.assertEqual(variants, {"c_x_part1": "c_x"})


class ApplyToModelTests(unittest.TestCase):
    def test_smd_and_qc_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ref.smd"), "w") as f:
                f.write(smd(tri("c_x"), tri("c_x")))
            with open(os.path.join(d, "bg.smd"), "w") as f:
                f.write(smd(tri("c_x")))
            qc = os.path.join(d, "m.qc")
            with open(qc, "w") as f:
                f.write('$modelname "x.mdl"\n$texturegroup "skinfamilies"\n'
                        '{\n\t{ "c_x" }\n\t{ "c_x_blue" }\n}\n')
            variants = pm.apply_to_model(qc, [{
                "name": "c_x_part1", "base": "c_x", "tris": [1, 2],
                "sources": ["ref.smd", "bg.smd"]}])
            self.assertEqual(variants, {"c_x_part1": "c_x", "c_x_part1_blue": "c_x_blue"})
            with open(os.path.join(d, "ref.smd")) as f:
                self.assertEqual(f.read().count("c_x_part1"), 1)
            with open(os.path.join(d, "bg.smd")) as f:
                self.assertEqual(f.read().count("c_x_part1"), 1)
            with open(qc) as f:
                text = f.read()
            self.assertIn('"c_x" "c_x_part1"', text)
            self.assertIn('"c_x_blue" "c_x_part1_blue"', text)

    def test_no_triangles_found_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ref.smd"), "w") as f:
                f.write(smd(tri("c_x")))
            qc = os.path.join(d, "m.qc")
            with open(qc, "w") as f:
                f.write('$modelname "x.mdl"\n')
            self.assertEqual(pm.apply_to_model(qc, [{
                "name": "c_x_part1", "base": "c_x", "tris": [5], "sources": ["ref.smd"]}]), {})

    def _model(self, d, *files):
        for name, text in files:
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        qc = os.path.join(d, "m.qc")
        with open(qc, "w") as f:
            f.write('$modelname "x.mdl"\n')
        return qc

    def test_two_parts_of_one_material(self):
        with tempfile.TemporaryDirectory() as d:
            qc = self._model(d, ("ref.smd", smd(tri("c_x"), tri("c_x"), tri("c_x"))))
            spec = {"base": "c_x", "total": 3, "sources": ["ref.smd"]}
            variants = pm.apply_to_model(qc, [{**spec, "name": "c_x_part1", "tris": [0]},
                                              {**spec, "name": "c_x_part2", "tris": [2]}])
            self.assertEqual(set(variants), {"c_x_part1", "c_x_part2"})
            with open(os.path.join(d, "ref.smd")) as f:
                self.assertEqual(names_in(f.read()), ["c_x_part1", "c_x", "c_x_part2", "end"])

    def test_other_model_is_left_alone_and_reported(self):
        # Модель не та, на которой выбирали части: не хватает файла или
        # треугольников другое число — по чужим номерам переносить нельзя.
        for files, total in (([("ref.smd", smd(tri("c_x"), tri("c_x")))], 3),
                             ([("ref.smd", smd(tri("c_x")))], 0)):
            with tempfile.TemporaryDirectory() as d:
                qc = self._model(d, *files)
                warned = []
                sources = ["ref.smd", "bg.smd"] if not total else ["ref.smd"]
                self.assertEqual(pm.apply_to_model(qc, [{
                    "name": "c_x_part1", "base": "c_x", "tris": [0], "total": total,
                    "sources": sources}], warned.append), {})
                self.assertEqual(len(warned), 1)
                self.assertIn("c_x_part1", warned[0])
                with open(os.path.join(d, "ref.smd")) as f:
                    self.assertNotIn("c_x_part1", f.read())


class OverlayVmtTests(unittest.TestCase):
    RED = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/hat_red"\n'
           '\t"$phongboost" "2"\n\t"$color2" "[1 0 0]"\n}\n')
    BLU = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/hat_blue"\n'
           '\t"$phongboost" "2"\n\t"$color2" "[0 0 1]"\n}\n')

    def test_edits_land_on_blue_without_losing_its_paint(self):
        edited = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/hat_red"\n'
                  '\t"$phongboost" "6"\n\t"$color2" "[1 0 0]"\n\t"$selfillum" "1"\n'
                  '\t"Proxies"\n\t{\n\t\t"Sine"\n\t\t{\n\t\t\t"resultVar" "$x"\n\t\t}\n\t}\n}\n')
        out = vmt_parse.parse(pm.overlay_vmt(self.BLU, self.RED, edited))
        self.assertEqual(out.get("basetexture"), "models/hat_blue")
        self.assertEqual(out.get("color2"), "[0 0 1]")
        self.assertEqual(out.get("phongboost"), "6")
        self.assertEqual(out.get("selfillum"), "1")
        self.assertIsNotNone(out.block("proxies"))

    def test_removed_param_and_shader_change(self):
        edited = '"UnlitGeneric"\n{\n\t"$basetexture" "models/hat_red"\n\t"$color2" "[1 0 0]"\n}\n'
        out = vmt_parse.parse(pm.overlay_vmt(self.BLU, self.RED, edited))
        self.assertEqual(out.shader, "unlitgeneric")
        self.assertIsNone(out.get("phongboost"))
        self.assertEqual(out.get("color2"), "[0 0 1]")

    def test_untouched_edit_gives_base_back(self):
        self.assertEqual(pm.overlay_vmt(self.BLU, self.RED, self.RED), self.BLU)

    def test_chosen_basetexture_goes_to_every_skin(self):
        # Белая основа под свечение — выбор человека, а не путь для подмены.
        edited = self.RED.replace("models/hat_red", "models/effects/white")
        self.assertTrue(pm.basetexture_changed(self.RED, edited))
        out = vmt_parse.parse(pm.overlay_vmt(self.BLU, self.RED, edited))
        self.assertEqual(out.get("basetexture"), "models/effects/white")
        self.assertFalse(pm.basetexture_changed(self.RED, self.RED.replace("$phongboost", "$x")))


#: Два несвязанных квадрата одного материала — две части; слева и справа на развёртке.
SQUARES = """# Sources: ref.smd
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 5 0 0
v 6 0 0
v 6 1 0
v 5 1 0
vt 0.0 0.0
vt 0.4 0.0
vt 0.4 0.4
vt 0.0 0.4
vt 0.6 0.6
vt 1.0 0.6
vt 1.0 1.0
vt 0.6 1.0
usemtl c_x
f 1/1 2/2 3/3
f 1/1 3/3 4/4
f 5/5 6/6 7/7
f 5/5 7/7 8/8
"""


class EditorTests(unittest.TestCase):
    """Материал части — своя карточка: копия исходного при создании, дальше
    порознь; мазки частей видны в склейке каждого материала."""

    def setUp(self):
        import threading
        from src.app.parts_editor import PartsEditor
        from src.app.session import AppSession
        from src.domain.preview.session import PreviewSession
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        obj = os.path.join(d, "model.obj")
        with open(obj, "w", encoding="utf-8") as f:
            f.write(SQUARES)

        class Host:
            def __init__(host):
                host.preview = PreviewSession()
                host._lock = threading.Lock()
                host._obj_path = obj
                host._bodygroups = {}
                host._hat_styles = {}

            def _autosave(host, step=False):
                pass

            def _card_key(host, material=''):
                return AppSession._card_key(host, material)

            def _decor_for_card(host, card):
                return None

            def _put(host, *args, **kwargs):
                pass

            def _vmt_target(host, material=''):
                return {'error': 'нет'}

            def _work_dir(host):
                return d

            def view_state(host):
                return {}

        self.single = SINGLE_TEX_KEY
        self.host = Host()
        self.t = self.host.preview.textures
        self.t.material_names = [SINGLE_TEX_KEY]
        self.game = self.png("game", (128, 128, 128))
        self.t.vpk_red_tex_map = {SINGLE_TEX_KEY: self.game}
        self.editor = PartsEditor(self.host)
        self.parts = [p['id'] for p in self.editor.describe('')['parts']]

    def tearDown(self):
        self.tmp.cleanup()

    def png(self, name, color):
        from PIL import Image
        path = os.path.join(self.tmp.name, name + ".png")
        Image.new("RGB", (64, 64), color).save(path)
        return path

    @staticmethod
    def has(path, color):
        from PIL import Image
        with Image.open(path) as im:
            return any(all(abs(a - b) < 40 for a, b in zip(px, color))
                       for _, px in im.convert("RGB").getcolors(64 * 64))

    def test_new_material_starts_as_a_copy_then_lives_apart(self):
        red = self.png("red", (255, 0, 0))
        self.t.set_texture(self.single, red)
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.assertEqual(self.t.resolve_card(name), red)
        # Картинка на исходном после создания материала части не касается.
        self.t.set_texture(self.single, self.png("blue", (0, 0, 255)))
        self.assertEqual(self.t.resolve_card(name), red)

    def test_strokes_land_in_every_material_over_its_own_base(self):
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.editor.set_part_colors('', {self.parts[0]: '#00ff00'})
        main, mine = self.t.resolve_card(self.single), self.t.resolve_card(name)
        self.assertNotEqual(main, mine)
        self.assertTrue(self.has(main, (0, 255, 0)) and self.has(mine, (0, 255, 0)))
        # Своя картинка исходного ложится под мазки только у исходного.
        self.editor.set_base(self.single, self.png("blue", (0, 0, 255)))
        self.assertTrue(self.has(self.t.resolve_card(self.single), (0, 0, 255)))
        self.assertFalse(self.has(self.t.resolve_card(name), (0, 0, 255)))
        # Мазки сняли — материал части вернулся к своей основе, игровой.
        self.editor.clear_parts('')
        self.assertEqual(self.t.resolve_card(name), self.game)

    def test_carrier_gun_does_not_hide_the_festive_item(self):
        # Праздничное оружие: в OBJ гирлянда и пушка-носитель под ней. Карточка
        # у гирлянды служебная, и разбор искал материал с именем «__single__».
        with open(self.host._obj_path, "w", encoding="utf-8") as f:
            f.write(SQUARES.replace("usemtl c_x\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n",
                                    "usemtl c_gun\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\nusemtl lights\n"))
        from src.services import mesh_parts_service
        mesh_parts_service._CACHE.clear()        # тот же путь, в ту же секунду
        self.host.preview.scene_item_materials = ["lights"]
        out = self.editor.describe('')
        self.assertNotIn('error', out)
        self.assertEqual(len(out['parts']), 1)
        self.assertEqual(out['parts'][0]['triangles'], 2)

    def test_own_image_of_the_part_goes_under_the_strokes(self):
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.editor.set_part_colors('', {self.parts[0]: '#00ff00'})
        self.assertEqual(self.editor.set_base(name, self.png("red", (255, 0, 0))), {})
        mine = self.t.resolve_card(name)
        self.assertTrue(self.has(mine, (255, 0, 0)) and self.has(mine, (0, 255, 0)))
        self.assertFalse(self.has(self.t.resolve_card(self.single), (255, 0, 0)))


class SourcesTests(unittest.TestCase):
    def test_sources_line_read(self):
        with tempfile.TemporaryDirectory() as d:
            obj = os.path.join(d, "m.obj")
            with open(obj, "w") as f:
                f.write("# Converted from ref.smd\n# Sources: ref.smd|bg.smd\nmtllib m.mtl\n")
            self.assertEqual(pm.sources_of_obj(obj), ["ref.smd", "bg.smd"])
            self.assertEqual(pm.sources_of_obj(os.path.join(d, "none.obj")), [])

    def test_carrier_of_festive_weapon_is_not_a_source(self):
        # Пушка-носитель праздничного оружия — чужая модель из своей папки: в
        # сборку предмета она не входит, и номера его треугольников не сдвигает.
        from src.services.smd_to_obj_service import SmdToObjService
        with tempfile.TemporaryDirectory() as d:
            item, carrier = os.path.join(d, "item"), os.path.join(d, "carrier")
            os.makedirs(item)
            os.makedirs(carrier)
            paths = {}
            for folder, name, mat in ((item, "ref.smd", "lights"), (item, "bg.smd", "lights"),
                                      (carrier, "gun.smd", "c_gun")):
                paths[name] = os.path.join(folder, name)
                with open(paths[name], "w") as f:
                    f.write(smd(tri(mat, 0.1), tri(mat, 0.2)))
            obj = os.path.join(d, "model.obj")
            ok, _ = SmdToObjService.convert(paths["ref.smd"], obj,
                                            extra_smd_paths=[paths["bg.smd"], paths["gun.smd"]])
            self.assertTrue(ok)
            self.assertEqual(pm.sources_of_obj(obj), ["ref.smd", "bg.smd"])


if __name__ == "__main__":
    unittest.main()


class DomainTests(unittest.TestCase):
    """Карточка части в альбоме и её текстура (PreviewSession)."""

    def setUp(self):
        from src.domain.preview.session import PreviewSession
        from src.domain.preview.texture_state import SINGLE_TEX_KEY
        from src.shared.constants import Team
        self.tmp = tempfile.TemporaryDirectory()
        self.single, self.red = SINGLE_TEX_KEY, Team.RED

        def png(name):
            path = os.path.join(self.tmp.name, name)
            open(path, "wb").close()
            return path
        self.png = png
        self.ps = PreviewSession()
        self.ps.textures.material_names = [SINGLE_TEX_KEY]
        self.ps.part_materials = {"c_x": [{"name": "c_x_part1", "card": SINGLE_TEX_KEY,
                                           "tris": [3, 4], "sources": ["ref.smd"],
                                           "total": 6}]}
        self.ps.sync_part_cards()

    def tearDown(self):
        self.tmp.cleanup()

    def test_card_follows_its_base(self):
        self.assertEqual(self.ps.card_materials(), [self.single, "c_x_part1"])

    def _game(self):
        game = self.png("game.png")
        self.ps.textures.vpk_red_tex_map = {self.single: game}
        return game

    def test_main_texture_does_not_reach_the_part(self):
        # Отдельный материал: картинка на исходной карточке его не касается,
        # без своей он показывает игровую текстуру исходного.
        game, main = self._game(), self.png("main.png")
        self.ps.textures.set_texture(self.single, main)
        shown = self.ps.visible_textures()
        self.assertEqual((shown[self.single], shown["c_x_part1"]), (main, game))
        own = self.png("own.png")
        self.ps.textures.set_texture("c_x_part1", own)
        shown = self.ps.visible_textures()
        self.assertEqual((shown[self.single], shown["c_x_part1"]), (main, own))

    def test_scene_names_the_base_mesh(self):
        game, main = self._game(), self.png("main.png")
        self.ps.textures.set_texture(self.single, main)
        scene = self.ps.scene_textures()
        self.assertNotIn(self.single, scene)
        self.assertEqual((scene["c_x"], scene["c_x_part1"]), (main, game))

    def test_variant_shows_game_gold_on_the_part(self):
        # Австралий: строка золота ведёт часть в игровой VMT золота — своя
        # картинка части стоит только в строках её команды.
        t = self.ps.textures
        self._game()
        t.set_texture("c_x_part1", self.png("own.png"))
        gold = self.png("gold.png")
        t.australium_mat_name, t.australium_frame, t.australium_active = "c_x_gold", gold, True
        self.assertEqual(self.ps.scene_textures()["c_x_part1"], gold)
        self.assertEqual(self.ps.visible_textures()["c_x_part1"], gold)

    def test_part_follows_its_base_in_teams(self):
        from src.shared.constants import Team
        t = self.ps.textures
        own = self.png("own.png")
        # Нейтральный исходный: картинка части — обеим командам.
        t.set_texture("c_x_part1", own)
        self.assertEqual({team: t.textures.get(team, {}).get("c_x_part1")
                          for team in (Team.RED, Team.BLU)},
                         {Team.RED: own, Team.BLU: own})
        # Командный исходный (или «сделать командным»): у части команды порознь.
        t.textures = {Team.RED: {}, Team.BLU: {}}
        t.force_team = True
        t.set_texture("c_x_part1", own)
        self.assertEqual(t.textures[Team.BLU].get("c_x_part1"), None)
        t.force_team = False
        t.blu_frames = [self.png("blu.png")]
        self.assertTrue(t.is_team_material("c_x_part1"))
        self.assertFalse(t.is_neutral("c_x_part1"))

    def test_blue_image_of_a_part_is_not_the_weapon_blue(self):
        # Своей синей у главной нет: сборка спросит про неё, а не возьмёт
        # синюю картинку части за синий скин всего оружия.
        from src.shared.constants import Team
        t = self.ps.textures
        t.force_team = True
        t.active_team = Team.BLU
        t.set_texture("c_x_part1", self.png("part_blu.png"))
        self.assertIsNone(t.blu_main())
        self.assertIsNone(t.uploaded_for_mat("c_x_blue"))

    def test_survives_work_round_trip(self):
        from src.domain.preview.session import PreviewSession, has_real_edits
        edits = self.ps.user_edits()
        self.assertTrue(has_real_edits(edits))
        other = PreviewSession()
        other.textures.material_names = [self.single]
        other.apply_user_edits(edits)
        self.assertEqual(other.part_materials, self.ps.part_materials)
        self.assertEqual(other.textures.part_cards, {"c_x_part1": self.single})
        other.forget_user_edits()
        self.assertEqual((other.part_materials, other.textures.part_cards), ({}, {}))

    def test_new_geometry_drops_part_cards(self):
        # Своя модель: материала части больше нет — его картинка в сборку не идёт.
        self.ps.textures.set_texture("c_x_part1", self.png("own.png"))
        self.ps.texture_maps["c_x_part1"] = {"normal": "n.png"}
        self.ps.forget_parts_layout()
        self.assertEqual(self.ps.textures.uploaded_slot_paths(), {})
        self.assertNotIn("c_x_part1", self.ps.texture_maps)
