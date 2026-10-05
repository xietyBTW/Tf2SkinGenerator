"""
Снаряд, заряженный в оружие (граната Loch-n-Load, ракета сигнальной, стрела).

Это бодигруппа «пусто | снаряд»: игра показывает его только в первом лице на
перезарядке, а в кадре предмета он виден — его правят. Своя модель снаряда
садится на кость игрового (её двигает рука), а куски снаряда нумеруются после
кусков самой модели, чтобы покраска по частям старых работ не съехала.
"""

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.services import mesh_import_service, mesh_parts_service
from src.services.model_build_service import ModelBuildService
from src.services.preview_3d_worker import with_part_models
from src.services.smd_to_obj_service import SmdToObjService

NODES = 'nodes\n0 "weapon_bone" -1\n1 "weapon_bone_4" 0\nend\nskeleton\ntime 0\n' \
        '0 0 0 0 0 0 0\n1 0 0 0 0 0 0\nend\n'


def tri(mat, bone, pts, uvs):
    return mat + "\n" + "".join(
        f"  {bone} {x} {y} {z} 0 0 1 {u} {v} 1 {bone} 1\n" for (x, y, z), (u, v) in zip(pts, uvs))


def smd(*tris, nodes=NODES):
    return "version 1\n" + nodes + "triangles\n" + "".join(tris) + "end\n"


QUAD = [((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((1, 0, 0), (1, 1, 0), (0, 1, 0))]


class RuleTests(unittest.TestCase):
    def test_projectile_groups(self):
        pv = ModelBuildService.projectile_variant
        self.assertEqual(pv("reload", [None, "g.smd"]), 1)
        self.assertEqual(pv("Shell", ["s.smd", None]), 0)
        self.assertIsNone(pv("broken", [None, "b.smd"]))          # замена, не снаряд
        self.assertIsNone(pv("reload", ["a.smd", "b.smd"]))       # не «пусто | снаряд»

    def test_preview_shows_projectile_unless_hidden(self):
        groups = [("body", ["gun.smd"]), ("reload", [None, "g.smd"])]
        self.assertEqual(ModelBuildService.preview_choice(groups, {}), {"reload": 1})
        self.assertEqual(ModelBuildService.preview_choice(groups, {"reload": 0}), {"reload": 0})


class PartModelTests(unittest.TestCase):
    def test_own_projectile_sits_on_the_projectile_bone(self):
        # Своя граната без костей (`root`) садится на кость игровой гранаты:
        # её двигает рука при перезарядке. Кэш разборки не трогаем.
        with tempfile.TemporaryDirectory() as d:
            cache, out = os.path.join(d, "cache"), os.path.join(d, "copy")
            os.makedirs(cache)
            part = os.path.join(cache, "c_gun_reload_bodygroup.smd")
            Path(part).write_text(smd(tri("c_gun", 1, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
            Path(cache, "c_gun.smd").write_text(smd(tri("c_gun", 0, QUAD[1], [(0, 0), (1, 0), (0, 1)])))
            mine = os.path.join(d, "mine.smd")
            Path(mine).write_text(smd(tri("Grenade", 0, QUAD[1], [(0, 0), (1, 0), (0, 1)]),
                                      nodes='nodes\n0 "root" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\n'))
            with_part_models(cache, {"C_GUN_RELOAD_BODYGROUP": mine}, out)
            merged = Path(out, "c_gun_reload_bodygroup.smd").read_text()
            verts = [l.split() for l in merged.split("triangles", 1)[1].splitlines()
                     if len(l.split()) >= 9]
            self.assertTrue(verts and all(v[0] == "1" for v in verts))
            self.assertIn("c_gun\n", merged)                       # материал игровой
            self.assertNotIn("Grenade", Path(part).read_text())   # кэш не тронут


class LateNumberingTests(unittest.TestCase):
    def test_projectile_chunks_go_after_the_weapon(self):
        # Снаряд по площади развёртки больше куска ружья, но номера кусков
        # ружья остаются такими, какими были без снаряда.
        with tempfile.TemporaryDirectory() as d:
            gun = os.path.join(d, "c_gun.smd")
            Path(gun).write_text(smd(
                tri("c_gun", 0, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0), (0.5, 0), (0, 0.5)]),
                tri("c_gun", 0, [(5, 0, 0), (6, 0, 0), (5, 1, 0)], [(0.6, 0.6), (0.7, 0.6), (0.6, 0.7)])))
            shell = os.path.join(d, "c_gun_reload_bodygroup.smd")
            Path(shell).write_text(smd(
                tri("c_gun", 1, [(9, 0, 0), (12, 0, 0), (9, 3, 0)], [(0, 0.5), (1, 0.5), (0, 1)])))
            before = os.path.join(d, "before.obj")
            after = os.path.join(d, "after.obj")
            SmdToObjService.convert(gun, before)
            SmdToObjService.convert(gun, after, extra_smd_paths=[shell], late_smd_paths=[shell])
            old = mesh_parts_service.load(before).parts_of("c_gun")
            new = mesh_parts_service.load(after).parts_of("c_gun")
            self.assertEqual([p.triangles for p in new[:len(old)]], [p.triangles for p in old])
            self.assertEqual(tuple(new[-1].triangles), (2,))
            with open(after, encoding="utf-8") as f:
                head = f.read(300)
            self.assertIn("# Sources: c_gun.smd|c_gun_reload_bodygroup.smd", head)


class FitTests(unittest.TestCase):
    def test_mesh_is_laid_into_the_projectile_box(self):
        long_x = np.array([[x, y, z] for x in (-5, 5) for y in (-1, 1) for z in (-1, 1)], float)
        target = np.array([[x, y, z] for x in (-1.4, 1.4) for y in (9.8, 12.6)
                           for z in (-7.4, -1.6)], float)
        fit = mesh_import_service.fit_into(long_x, target)
        moved = long_x @ np.array(fit.matrix()).T * fit.scale + np.array(fit.offset)
        self.assertTrue(np.allclose(moved.min(0)[2], -7.4) and np.allclose(moved.max(0)[2], -1.6))
        self.assertTrue(np.allclose((moved.min(0) + moved.max(0)) / 2, [0, 11.2, -4.5]))


#: Оружие (квадрат слева) и снаряд после него (квадрат справа) одного
#: материала; развёртка снаряда накрывает развёртку оружия, как у своей
#: модели из интернета.
LATE_OBJ = """# Sources: ref.smd|shell.smd
# Late: c_x=2
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 5 0 0
v 6 0 0
v 6 1 0
v 5 1 0
vt 0.0 0.0
vt 0.5 0.0
vt 0.5 0.5
vt 0.0 0.5
vt 0.1 0.1
vt 0.6 0.1
vt 0.6 0.6
vt 0.1 0.6
usemtl c_x
f 1/1 2/2 3/3
f 1/1 3/3 4/4
f 5/5 6/6 7/7
f 5/5 7/7 8/8
"""


class ItemSwitchTests(unittest.TestCase):
    def test_projectile_stays_with_its_weapon(self):
        # Снаряд Подкидыша уезжал в работу и сборку следующего открытого оружия.
        from src.domain.preview.session import PreviewSession
        s = PreviewSession()
        s.begin_item("c_lochnload", "demoman_c_lochnload")
        s.part_models = {"c_lochnload_reload_bodygroup": "mine.smd"}
        s.begin_item("c_lochnload", "demoman_c_lochnload")      # тот же — остаётся
        self.assertTrue(s.part_models)
        s.begin_item("c_demo_cannon", "demoman_c_demo_cannon")
        self.assertEqual(s.part_models, {})


class FitsTests(unittest.TestCase):
    def test_weapon_parts_survive_a_new_projectile(self):
        from src.services import part_materials as pm
        weapon = {'tris': [0, 1], 'total': 4, 'late': 2}
        shell = {'tris': [2, 3], 'total': 4, 'late': 2}
        self.assertTrue(pm.fits(weapon, 4, 2) and pm.fits(shell, 4, 2))   # та же модель
        self.assertTrue(pm.fits(weapon, 30, 2))       # снаряд сменился — оружие то же
        self.assertFalse(pm.fits(shell, 30, 2))       # треугольники прежнего снаряда
        self.assertTrue(pm.fits(weapon, 2, 2))        # снаряд скрыт
        self.assertFalse(pm.fits(weapon, 30, 3))      # само оружие другое
        # Выбрано до того, как снаряд появился в кадре: `late` нет, всё — оружие.
        self.assertTrue(pm.fits({'tris': [0], 'total': 2}, 4, 2))
        self.assertFalse(pm.fits({'tris': [0], 'total': 3}, 4, 2))

    def test_vmt_loses_maps_laid_on_the_game_unwrap(self):
        from src.services import part_materials as pm
        vmt = ('"VertexlitGeneric"\n{\n\t"$basetexture" "models/x/ball"\n'
               '\t"$bumpmap" "models/x/ball_normal"\n\t$normalmapalphaenvmapmask 1\n'
               '\t"$lightwarptexture" "models/lightwarps/weapon_lightwarp"\n}\n')
        out = pm.without_uv_maps(vmt)
        self.assertNotIn("bumpmap", out)
        self.assertNotIn("normalmapalphaenvmapmask", out)
        self.assertIn("$basetexture", out)
        self.assertIn("$lightwarptexture", out)
        self.assertEqual(pm.without_uv_maps(out), out)


class EditorTests(unittest.TestCase):
    """Своя модель снаряда в общем с оружием материале: своя склейка, сброс
    правок прежнего снаряда."""

    def setUp(self):
        import threading

        from src.app.parts_editor import PartsEditor
        from src.app.session import AppSession
        from src.domain.preview.session import PreviewSession
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.obj = os.path.join(d, "model.obj")
        Path(self.obj).write_text(LATE_OBJ, encoding="utf-8")
        self.shell = os.path.join(d, "shell.smd")
        Path(self.shell).write_text(smd(tri("c_x", 1, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
        obj = self.obj

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

            def _shape_changed(host):
                return False

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

    def test_own_projectile_gets_its_material_and_paint_stays_on_it(self):
        mine = self.png("mine", (0, 0, 255))
        name = self.editor.own_projectile(mine)
        entry = self.host.preview.part_materials["c_x"][0]
        self.assertEqual((entry["name"], entry["tris"], entry["total"], entry["late"]),
                         (name, [2, 3], 4, 2))
        self.assertEqual(entry["card"], self.single)
        self.assertEqual(self.t.resolve_card(name), mine)
        # Краска снаряда — на его материале; оружие под той же развёрткой цело.
        self.editor.set_part_colors('', {1: '#00ff00'})
        self.assertTrue(self.has(self.t.resolve_card(name), (0, 255, 0)))
        self.assertFalse(self.has(self.t.resolve_card(self.single), (0, 255, 0)))
        view = self.editor.part_material_view()["c_x"]
        self.assertEqual(view["total"], 4)
        self.assertEqual(view["parts"][0]["runs"], [[2, 2]])

    def test_without_a_picture_the_projectile_is_plain_grey(self):
        name = self.editor.own_projectile(None)
        self.assertTrue(self.has(self.t.resolve_card(name), (150, 150, 150)))

    def test_scissor_area_over_gun_and_shell_keeps_the_gun_paint(self):
        # Область [1, 3] задела и ружьё, и снаряд. Её обрезка до ружья сдвигает
        # номера частей — мазок остатка ружья (треугольник 0) остаётся на нём.
        p = self.host.preview
        p.part_regions = {"c_x": [[1, 3]]}
        from src.services import mesh_parts_service
        model = mesh_parts_service.load(self.obj, p.part_cuts, p.part_regions)
        gun = next(part.index for part in model.parts_of("c_x") if part.triangles == (0,))
        self.editor.set_part_colors('', {gun: '#ff0000'})
        self.editor.forget_projectile(self.shell)
        self.assertEqual(p.part_regions["c_x"], [[1]])
        model = mesh_parts_service.load(self.obj, p.part_cuts, p.part_regions)
        now = next(part.index for part in model.parts_of("c_x") if 0 in part.triangles)
        self.assertEqual(list(p.part_colors[self.editor._slot(self.single)]), [now])
        self.assertTrue(set(model.parts_of("c_x")[now].triangles) <= {0, 1})

    def test_a_material_from_another_model_is_left_alone(self):
        # Выбран на другой версии модели (total не тот): «оживлять» его новым
        # late нельзя — он лёг бы на чужие номера.
        p = self.host.preview
        p.part_materials = {"c_x": [{"name": "c_x_part1", "card": self.single,
                                     "tris": [0, 3], "total": 9,
                                     "sources": ["ref.smd", "shell.smd"]}]}
        p.sync_part_cards()
        self.editor.forget_projectile(self.shell)
        self.assertEqual(p.part_materials["c_x"][0]["tris"], [0, 3])
        self.assertNotIn("late", p.part_materials["c_x"][0])

    def test_new_projectile_forgets_the_paint_of_the_old_one(self):
        # Области ножницами режут каждый квадрат надвое: части 0-1 — оружие,
        # 2-3 — снаряд. Его части, область и материал уходят, оружия — нет.
        p = self.host.preview
        p.part_regions = {"c_x": [[1], [3]]}
        p.part_materials = {"c_x": [
            {"name": "c_x_part1", "card": self.single, "tris": [1], "total": 4, "late": 2,
             "sources": ["ref.smd", "shell.smd"]},
            {"name": "c_x_part2", "card": self.single, "tris": [2, 3], "total": 4,
             "late": 2, "sources": ["ref.smd", "shell.smd"]}]}
        p.sync_part_cards()
        self.editor.set_part_colors('', {0: '#ff0000', 2: '#00ff00'})
        self.editor.forget_projectile(self.shell)
        self.assertEqual([e["tris"] for e in p.part_materials["c_x"]], [[1]])
        self.assertNotIn("c_x_part2", self.t.part_cards)
        self.assertEqual(p.part_regions["c_x"], [[1]])
        slot = self.editor._slot(self.single)
        self.assertEqual(list(p.part_colors[slot]), [0])
        self.assertTrue(self.has(self.t.resolve_card(self.single), (255, 0, 0)))
        self.assertFalse(self.has(self.t.resolve_card(self.single), (0, 255, 0)))


class HiddenOwnShellTests(EditorTests):
    """Скрытый снаряд со своим материалом (ракета Ракетницы): в кадре один
    меш оружия, а мазки на карточке снаряда всё равно его."""

    def setUp(self):
        super().setUp()
        Path(self.obj).write_text(
            "# Sources: ref.smd\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
            "vt 0 0\nvt 0.5 0\nvt 0.5 0.5\nvt 0 0.5\n"
            "usemtl c_gun\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n", encoding="utf-8")
        Path(self.shell).write_text(smd(tri("c_shell", 1, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
        self.t.material_names = ["c_gun", "c_shell"]

    def test_shell_card_strokes_go_even_when_hidden(self):
        from src.domain.preview import part_specs
        p = self.host.preview
        shell_slot = part_specs.slot_key("c_shell", 0, False)
        gun_slot = part_specs.slot_key("c_gun", 0, False)
        p.part_colors = {shell_slot: {0: {"color": "#00ff00"}},
                         gun_slot: {0: {"color": "#ff0000"}}}
        self.editor.forget_projectile(self.shell)
        self.assertFalse(p.part_colors.get(shell_slot))
        self.assertTrue(p.part_colors.get(gun_slot))

    # Остальные проверки EditorTests — про общий материал; здесь не нужны.
    test_own_projectile_gets_its_material_and_paint_stays_on_it = None
    test_without_a_picture_the_projectile_is_plain_grey = None
    test_new_projectile_forgets_the_paint_of_the_old_one = None
    test_scissor_area_over_gun_and_shell_keeps_the_gun_paint = None
    test_a_material_from_another_model_is_left_alone = None


class SessionTests(unittest.TestCase):
    def test_custom_weapon_model_drops_the_projectile(self):
        # Своя модель оружия стирает части и материалы частей — и свой снаряд:
        # его материал ушёл вместе с ними, а снаряд своей модели спросит сборка.
        from src.domain.preview.session import PreviewSession
        s = PreviewSession()
        s.part_models = {"c_lochnload_reload_bodygroup": "mine.smd"}
        s.forget_parts_layout()
        self.assertEqual(s.part_models, {})

    def test_material_waits_while_the_projectile_is_hidden(self):
        from unittest.mock import MagicMock
        from src.app.session import AppSession
        s = AppSession()
        s.parts = MagicMock()
        s.preview.part_models = {"shell": "mine.smd"}
        s._bodygroups = {"reload": 0}
        s._own_projectile("reload", "shell", "mine.smd", None, "ru")
        s.parts.own_projectile.assert_not_called()
        self.assertEqual(len(s._after_model), 1)
        s._bodygroups = {}
        s.parts.own_projectile.return_value = ""
        s._after_model.pop()()
        s.parts.own_projectile.assert_called_once()


class SmdInputTests(unittest.TestCase):
    def test_smd_is_copied_and_obj_brings_its_picture(self):
        from src.app.session import _part_smd
        from src.services.mesh_import_service import MeshImportError

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            os.makedirs(out)
            part = os.path.join(d, "shell.smd")
            Path(part).write_text(smd(tri("c_x", 1, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
            mine = os.path.join(d, "mine.smd")
            Path(mine).write_text(smd(tri("x", 0, QUAD[1], [(0, 0), (1, 0), (0, 1)])))
            got, texture, simplified = _part_smd(mine, part, out)
            self.assertEqual(os.path.dirname(got), out)           # копия, не загрузка
            self.assertEqual(Path(got).read_text(), Path(mine).read_text())
            self.assertIsNone(texture)
            Path(mine).write_text("version 1\n")
            with self.assertRaises(MeshImportError):
                _part_smd(mine, part, out)

            from PIL import Image
            Image.new("RGB", (8, 8), (9, 9, 9)).save(os.path.join(d, "skin.png"))
            Path(d, "ball.mtl").write_text("newmtl skin\nmap_Kd skin.png\n")
            Path(d, "ball.obj").write_text(
                "mtllib ball.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\n"
                "usemtl skin\nf 1/1 2/2 3/3\n")
            got, texture, _ = _part_smd(os.path.join(d, "ball.obj"), part, out)
            self.assertTrue(got.endswith("ball.smd") and os.path.isfile(got))
            self.assertEqual(os.path.basename(texture or ""), "skin.png")


class BuildTests(unittest.TestCase):
    def test_build_takes_the_session_projectile_without_asking(self):
        from types import SimpleNamespace
        from src.services.vpk_model_pipeline import VpkModelPipeline

        with tempfile.TemporaryDirectory() as d:
            decomp = Path(d)
            Path(decomp, "c_gun.qc").write_text(
                '$modelname "c_gun.mdl"\n$bodygroup "body"\n{\n\tstudio "c_gun.smd"\n}\n'
                '$bodygroup "reload"\n{\n\tblank\n\tstudio "c_gun_reload_bodygroup.smd"\n}\n')
            Path(decomp, "c_gun.smd").write_text(smd(tri("c_gun", 0, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
            Path(decomp, "c_gun_reload_bodygroup.smd").write_text(
                smd(tri("c_gun", 1, QUAD[1], [(0, 0), (1, 0), (0, 1)])))
            mine = os.path.join(d, "mine.smd")
            Path(mine).write_text(smd(tri("x", 0, [(7, 7, 7), (8, 7, 7), (7, 8, 7)],
                                          [(0, 0), (1, 0), (0, 1)])))
            ctx = SimpleNamespace(decompile_dir=decomp, warn=lambda m: None)
            VpkModelPipeline._apply_model_replacement(
                ctx, str(decomp / "c_gun.qc"), "c_gun", None, None, "ru", lambda *a: None,
                part_models={"c_gun_reload_bodygroup": mine})
            merged = Path(decomp, "c_gun_reload_bodygroup.smd").read_text()
            self.assertIn(" 7 7 7 ", merged)
            self.assertNotIn("\nx\n", merged)      # материал — игровой детали

    def test_weapon_part_material_survives_a_new_projectile(self):
        # Материалы частей выбирали с игровой гранатой в кадре (1 + 1
        # треугольник), в сборке у снаряда своя модель на 2: материал на
        # самом оружии собирается, а на прежней гранате — нет, с предупреждением.
        from src.services import part_materials as pm

        with tempfile.TemporaryDirectory() as d:
            qc = os.path.join(d, "c_gun.qc")
            Path(qc).write_text('$modelname "c_gun.mdl"\n$bodygroup "body"\n{\n\tstudio "c_gun.smd"\n}\n'
                                '$bodygroup "reload"\n{\n\tblank\n\tstudio "shell.smd"\n}\n')
            Path(d, "c_gun.smd").write_text(smd(tri("c_gun", 0, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
            Path(d, "shell.smd").write_text(smd(
                tri("c_gun", 1, QUAD[1], [(0, 0), (1, 0), (0, 1)]),
                tri("c_gun", 1, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
            warned = []
            spec = {'base': 'c_gun', 'total': 2, 'late': 1,
                    'sources': ['c_gun.smd', 'shell.smd']}
            got = pm.apply_to_model(qc, [{**spec, 'name': 'c_gun_part1', 'tris': [0]},
                                         {**spec, 'name': 'c_gun_part2', 'tris': [1]}],
                                    warned.append)
            self.assertEqual(got, {'c_gun_part1': 'c_gun'})
            self.assertIn("c_gun_part1", Path(d, "c_gun.smd").read_text())
            self.assertNotIn("c_gun_part2", Path(d, "shell.smd").read_text())
            self.assertEqual(len(warned), 1)

    def test_old_material_without_the_shell_file_does_not_hide_the_shell(self):
        # Материал на оружии выбран до того, как граната попала в кадр: его
        # `sources` без SMD гранаты. Первым в группе он не должен отрезать
        # материал своей гранаты (её треугольники — во втором файле).
        from src.services import part_materials as pm

        with tempfile.TemporaryDirectory() as d:
            qc = os.path.join(d, "c_gun.qc")
            Path(qc).write_text('$modelname "c_gun.mdl"\n$bodygroup "body"\n{\n\tstudio "c_gun.smd"\n}\n'
                                '$bodygroup "reload"\n{\n\tblank\n\tstudio "shell.smd"\n}\n')
            Path(d, "c_gun.smd").write_text(smd(tri("c_gun", 0, QUAD[0], [(0, 0), (1, 0), (0, 1)])))
            Path(d, "shell.smd").write_text(smd(tri("c_gun", 1, QUAD[1], [(0, 0), (1, 0), (0, 1)])))
            got = pm.apply_to_model(qc, [
                {'name': 'c_gun_part1', 'base': 'c_gun', 'tris': [0], 'total': 1,
                 'sources': ['c_gun.smd']},
                {'name': 'c_gun_part2', 'base': 'c_gun', 'tris': [1], 'total': 2, 'late': 1,
                 'sources': ['c_gun.smd', 'shell.smd']}], lambda m: None)
            self.assertEqual(got, {'c_gun_part1': 'c_gun', 'c_gun_part2': 'c_gun'})
            self.assertIn("c_gun_part2", Path(d, "shell.smd").read_text())


if __name__ == "__main__":
    unittest.main()
