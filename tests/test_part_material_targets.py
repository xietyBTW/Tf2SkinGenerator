"""
Куда уходят части, ставшие своими материалами (src/app/parts_editor.py)

- Материал части в стиле оружия (Bloody у гильотины): в стиле он виден, его
  правка стиля - его, и сборка ставит её в строку стиля, а не в базовую.
- Родной материал модели как цель: треугольники берут его имя, своей
  карточки и столбца в $texturegroup у такой записи нет, а его картинки и
  карты остаются его
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import part_materials as pm

from tests.test_part_materials import SQUARES, names_in, smd, tri
from types import SimpleNamespace


#: SQUARES плюс второй родной материал c_y - квадрат на той же развёртке
TWO = SQUARES + "usemtl c_y\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"


def _png(folder, name, color):
    from PIL import Image
    path = os.path.join(folder, name + ".png")
    Image.new("RGB", (64, 64), color).save(path)
    return path


def _has(path, color):
    from PIL import Image
    with Image.open(path) as im:
        return any(all(abs(a - b) < 40 for a, b in zip(px, color))
                   for _, px in im.convert("RGB").getcolors(64 * 64))


def _editor(folder, obj_text, names):
    from src.app.parts_editor import PartsEditor
    from src.app.session import AppSession
    from src.domain.preview.session import PreviewSession
    from src.services import mesh_parts_service

    obj = os.path.join(folder, "model.obj")
    with open(obj, "w", encoding="utf-8") as f:
        f.write(obj_text)
    mesh_parts_service._CACHE.clear()

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

        decor = SimpleNamespace(for_card=lambda card: None)

        def _shape_changed(host):
            return False

        def _put(host, *args, **kwargs):
            pass

        materials = SimpleNamespace(vmt_target=lambda material='': {'error': 'нет'})

        def _work_dir(host):
            return folder

        def view_state(host):
            return {}

    host = Host()
    host.preview.textures.material_names = list(names)
    return PartsEditor(host), host.preview


class StyleTests(unittest.TestCase):
    """Гильотина: одна модель, стиль Bloody меняет c_x на c_x_bloody"""

    def setUp(self):
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.single = SINGLE_TEX_KEY
        self.editor, self.ps = _editor(d, SQUARES, [SINGLE_TEX_KEY])
        t = self.t = self.ps.textures
        t.vpk_red_tex_map = {SINGLE_TEX_KEY: _png(d, "game", (128, 128, 128))}
        t.skin_info = {"rows": [["c_x"], ["c_x_bloody"]]}
        self.blood = _png(d, "blood", (120, 0, 0))
        self.ps.adopt_style_textures({1: {"c_x": self.blood}})
        t.active_skin = 1
        self.parts = [p['id'] for p in self.editor.describe('')['parts']]

    def tearDown(self):
        self.tmp.cleanup()

    def test_part_made_in_a_style_stays_in_it(self):
        # Жалоба: выбрал Bloody, дал части свой материал - а он ушёл в базовый
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.assertEqual(self.ps.card_materials(), [self.single, name])
        # Без своей правки - оригинал стиля исходного, как и в игре
        self.assertEqual(self.ps.visible_textures()[name], self.blood)
        own = _png(self.tmp.name, "own", (0, 0, 255))
        self.t.set_texture(name, own)
        self.assertEqual(self.t.skin_overrides[1][name], own)
        self.assertEqual(self.ps.scene_textures()[name], own)
        # Базовый стиль своей правкой стиля часть не трогает
        self.t.active_skin = 0
        self.assertNotEqual(self.ps.visible_textures()[name], own)

    def test_leaving_the_style_takes_the_part_along(self):
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.t.set_texture(name, _png(self.tmp.name, "own", (0, 0, 255)))
        self.assertTrue(self.ps.drop_from_style(self.single))
        self.assertNotIn(name, self.t.skin_overrides[1])
        self.assertEqual(self.ps.card_materials(), [])

    def test_strokes_in_a_style_do_not_pile_up(self):
        # Основой склейки в стиле была прошлая склейка: снятый мазок оставался
        name = self.editor.set_part_material('', [self.parts[0], self.parts[1]], '')['created']
        self.editor.set_part_colors('', {self.parts[0]: '#00ff00', self.parts[1]: '#ff00ff'})
        self.editor.set_part_colors('', {self.parts[0]: None})
        mine = self.t.skin_overrides[1][name]
        self.assertTrue(_has(mine, (255, 0, 255)) and not _has(mine, (0, 255, 0)))

    def test_leaving_the_style_drops_its_strokes(self):
        self.editor.set_part_material('', [self.parts[0]], '')
        self.editor.set_part_colors('', {self.parts[1]: '#ff00ff'})
        self.assertTrue(self.ps.drop_from_style(self.single))
        self.assertNotIn(f"{self.single}@style1", self.ps.part_colors)

    def test_part_card_leaves_the_style_alone(self):
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.t.set_texture(name, _png(self.tmp.name, "own", (0, 0, 255)))
        self.assertTrue(self.ps.drop_from_style(name))
        self.assertEqual(self.ps.visible_textures()[name], self.blood)

    def test_style_that_keeps_the_source_has_no_part_card(self):
        # Строка стиля оставила исходный: у части там та же базовая, и правке
        # стиля некуда - карточки в этом стиле нет
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.t.skin_info = {"rows": [["c_x"], ["c_x"]]}
        self.assertNotIn(name, self.ps.card_materials())

    def test_style_image_of_the_source_is_copied(self):
        red = _png(self.tmp.name, "red", (255, 0, 0))
        self.t.set_texture(self.single, red)                  # правка Bloody исходного
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.assertEqual(self.t.skin_overrides[1].get(name), red)

    def test_strokes_in_a_style_reach_the_part_material(self):
        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        self.editor.set_part_colors('', {self.parts[0]: '#00ff00', self.parts[1]: '#ff00ff'})
        mine, main = self.t.skin_overrides[1][name], self.t.skin_overrides[1][self.single]
        self.assertTrue(_has(mine, (0, 255, 0)) and not _has(mine, (255, 0, 255)))
        self.assertTrue(_has(main, (255, 0, 255)) and not _has(main, (0, 255, 0)))

    def test_build_spec_names_the_style_row(self):
        from src.app.build_editor import BuildEditor
        from src.app.session import AppSession

        name = self.editor.set_part_material('', [self.parts[0]], '')['created']
        own = _png(self.tmp.name, "own", (0, 0, 255))
        self.t.set_texture(name, own)
        s = AppSession.__new__(AppSession)
        s.preview = self.ps
        spec = BuildEditor(s)._part_material_specs()[0]
        self.assertEqual(spec['style_images'], {"c_x_bloody": own})
        self.assertIsNone(spec['image'])


class WriterTests(unittest.TestCase):
    def test_style_row_takes_the_style_image_of_the_part(self):
        from src.services.texture_build import game_source
        from src.services.vpk_texture_builder import VpkTextureBuilder

        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            game = out / "game.vmt"
            game.write_text('"VertexLitGeneric"\n{\n\t"$basetexture" "models/c_x"\n}\n')

            class Slots:
                vtf_output_path = out
                patched_cdmaterials_path = "models/mod/"

                @staticmethod
                def vmt(name):
                    return out / f"{name}.vmt"

            class Ctx:
                @staticmethod
                def warn(message):
                    pass

            spec = {"name": "c_x_part1", "base": "c_x", "image": "base.png",
                    "image_blu": None, "style_images": {"c_x_bloody": "blood.png"}}
            with patch.object(game_source, "find_original_vmt", return_value=str(game)), \
                 patch("src.services.edited_vmt_service.EditedVMTService.get_edited_vmt",
                       return_value=None):
                renders = VpkTextureBuilder._write_part_materials(
                    {"c_x_part1": "c_x", "c_x_part1_bloody": "c_x_bloody"}, [spec],
                    Ctx(), Slots())
        self.assertEqual(renders, {"c_x_part1": ("base.png", "c_x_part1"),
                                   "c_x_part1_bloody": ("blood.png", "c_x_part1")})


class NativeTargetTests(unittest.TestCase):
    """У модели два родных материала: части c_x можно отдать c_y"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.editor, self.ps = _editor(self.tmp.name, TWO, ["c_x", "c_y"])
        self.t = self.ps.textures
        self.parts = [p['id'] for p in self.editor.describe('c_x')['parts']]

    def tearDown(self):
        self.tmp.cleanup()

    def test_model_materials_are_offered(self):
        self.assertEqual(self.editor.describe('c_x')['targets'], ["c_y"])

    def test_parts_take_the_model_material_without_a_card(self):
        mine = _png(self.tmp.name, "mine", (0, 0, 255))
        self.t.set_texture("c_y", mine)
        self.editor.set_part_material('c_x', [self.parts[0]], 'c_y')
        entry = self.ps.part_materials["c_x"][0]
        self.assertEqual((entry['name'], entry.get('existing')), ("c_y", True))
        self.assertNotIn("c_y", self.t.part_cards)
        self.assertEqual(self.ps.part_material_names(), [])
        self.assertEqual(self.ps.card_materials(), ["c_x", "c_y"])
        # Вьювер делит меш c_x так же, как для материала части
        view = self.editor.part_material_view()
        self.assertEqual([p['name'] for p in view["c_x"]['parts']], ["c_y"])
        # Вернули в общий - картинка c_y осталась его
        self.editor.drop_part_material("c_y", "c_x")
        self.assertEqual(self.ps.part_materials, {})
        self.assertEqual(self.t.resolve_card("c_y"), mine)

    def test_reset_keeps_the_model_material(self):
        mine = _png(self.tmp.name, "mine", (0, 0, 255))
        self.t.set_texture("c_y", mine)
        self.editor.set_part_material('c_x', [self.parts[0]], 'c_y')
        self.ps.forget_parts_layout()
        self.assertEqual(self.t.resolve_card("c_y"), mine)

    def test_flag_survives_the_work(self):
        from src.domain.preview.session import PreviewSession

        self.editor.set_part_material('c_x', [self.parts[0]], 'c_y')
        back = PreviewSession()
        back.apply_user_edits(self.ps.user_edits())
        self.assertTrue(back.part_materials["c_x"][0].get('existing'))

    def test_given_part_is_not_painted(self):
        self.editor.set_part_material('c_x', [self.parts[0]], 'c_y')
        res = self.editor.set_part_colors('c_x', {self.parts[0]: '#00ff00'})
        self.assertIn("c_y", res.get('error', ''))
        # Соседняя часть того же материала красится как прежде
        self.assertNotIn('error', self.editor.set_part_colors('c_x', {self.parts[1]: '#00ff00'}))

    def test_build_spec_only_renames(self):
        from src.app.build_editor import BuildEditor
        from src.app.session import AppSession

        self.editor.set_part_material('c_x', [self.parts[0]], 'c_y')
        s = AppSession.__new__(AppSession)
        s.preview = self.ps
        spec = BuildEditor(s)._part_material_specs()[0]
        self.assertEqual((spec['name'], spec['existing'], spec['image']), ("c_y", True, None))


class NativeBuildTests(unittest.TestCase):
    def test_triangles_take_the_name_without_a_new_column(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ref.smd"), "w") as f:
                f.write(smd(tri("c_x"), tri("c_x"), tri("C_Y")))
            qc = os.path.join(d, "m.qc")
            group = '$texturegroup "skinfamilies"\n{\n\t{ "c_x" "C_Y" }\n\t{ "c_x_blue" "C_Y_blue" }\n}\n'
            with open(qc, "w") as f:
                f.write('$modelname "x.mdl"\n' + group)
            variants = pm.apply_to_model(qc, [{
                "name": "C_Y", "base": "c_x", "tris": [1], "total": 2,
                "sources": ["ref.smd"], "existing": True}])
            self.assertEqual(variants, {})
            with open(os.path.join(d, "ref.smd")) as f:
                self.assertEqual(names_in(f.read()), ["c_x", "C_Y", "C_Y", "end"])
            with open(qc) as f:
                self.assertNotIn("part", f.read())

    def test_native_target_that_has_its_own_part_material(self):
        # c_x отдаёт кусок родному c_y, у c_y свой материал части. Считай c_y
        # после переименования c_x - номера съехали бы, и его часть пропала
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ref.smd"), "w") as f:
                f.write(smd(tri("c_x"), tri("c_x"), tri("c_y"), tri("c_y")))
            qc = os.path.join(d, "m.qc")
            with open(qc, "w") as f:
                f.write('$modelname "x.mdl"\n')
            warned = []
            variants = pm.apply_to_model(qc, [
                {"name": "c_y", "base": "c_x", "tris": [1], "total": 2,
                 "sources": ["ref.smd"], "existing": True},
                {"name": "c_y_part1", "base": "c_y", "tris": [0], "total": 2,
                 "sources": ["ref.smd"]}], warned.append)
            self.assertEqual((variants, warned), ({"c_y_part1": "c_y"}, []))
            with open(os.path.join(d, "ref.smd")) as f:
                self.assertEqual(names_in(f.read()), ["c_x", "c_y", "c_y_part1", "c_y", "end"])

    def test_custom_model_names_the_target_like_the_build(self):
        spec = {"name": "Glass.001", "base": "Material.001", "tris": [0], "total": 1,
                "sources": ["mine.smd"], "existing": True}
        with tempfile.TemporaryDirectory() as d:
            ref = os.path.join(d, "c_x_reference.smd")
            with open(ref, "w") as f:
                f.write(smd(tri("c_x")))
            kept = pm.specs_for_custom_model([spec], ref, keep_materials=True)
            self.assertEqual(kept[0]["name"], "glass_001")
            # «Только форма»: её материалы в сборке - один, отдавать нечему
            self.assertEqual(pm.specs_for_custom_model([spec], ref, keep_materials=False), [])

    def test_other_class_model_skips_the_whole_source(self):
        specs = [{"name": "hat_part1", "base": "hat", "tris": [0], "total": 2,
                  "sources": ["a_ref.smd"]},
                 {"name": "hat_b", "base": "hat", "tris": [1], "total": 2,
                  "sources": ["a_ref.smd"], "existing": True}]
        with tempfile.TemporaryDirectory() as d:
            qc = os.path.join(d, "b.qc")
            with open(qc, "w") as f:
                f.write('$modelname "b.mdl"\n')
            out, missed = pm.specs_for_other_model(specs, d, qc)
        self.assertEqual((out, sorted(missed)), ([], ["hat_b", "hat_part1"]))

    def test_other_class_model_does_not_take_them(self):
        spec = {"name": "hat_b", "base": "hat", "tris": [0], "total": 2,
                "sources": ["a_ref.smd"], "existing": True}
        with tempfile.TemporaryDirectory() as d:
            qc = os.path.join(d, "b.qc")
            with open(qc, "w") as f:
                f.write('$modelname "b.mdl"\n')
            out, missed = pm.specs_for_other_model([spec], d, qc)
        self.assertEqual((out, missed), ([], ["hat_b"]))


if __name__ == "__main__":
    unittest.main()
