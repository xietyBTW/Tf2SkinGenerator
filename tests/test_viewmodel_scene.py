"""
Сцена вида от первого лица: руки и оружие в одном OBJ.

Проверяется склейка: две модели с РАЗНЫМИ скелетами и разными позами попадают
в один файл, каждая по своей матрице, а материалы остаются разведены по частям
— по ним панель потом решает, что пользователю можно править (оружие), а что
показывается как есть (руки).
"""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services import viewmodel_scene
from src.services.smd_to_obj_service import MeshPart, SmdToObjService

HALF_PI = math.pi / 2


def _smd(bones, frame=None, triangles=()) -> str:
    """SMD из (имя, родитель), позы кадра и треугольников (материал, вершины)."""
    ids = {name: i for i, (name, _p) in enumerate(bones)}
    lines = ["version 1", "nodes"]
    for name, parent in bones:
        lines.append(f'{ids[name]} "{name}" {ids[parent] if parent else -1}')
    lines += ["end", "skeleton", "time 0"]
    for name, _parent in bones:
        pos, rot = (frame or {}).get(name, ((0, 0, 0), (0, 0, 0)))
        lines.append(f"{ids[name]} {pos[0]} {pos[1]} {pos[2]} "
                     f"{rot[0]} {rot[1]} {rot[2]}")
    lines += ["end", "triangles"]
    for material, verts in triangles:
        lines.append(material)
        for pos, bone in verts:
            lines.append(f"{ids[bone]} {pos[0]} {pos[1]} {pos[2]} "
                         f"0 0 1 0.5 0.5 1 {ids[bone]} 1.0")
    lines += ["end", ""]
    return "\n".join(lines)


def _obj_vertices(obj_path: Path):
    return [tuple(round(float(x), 4) for x in ln.split()[1:4])
            for ln in obj_path.read_text(encoding="utf-8").splitlines()
            if ln.startswith("v ")]


def _obj_groups(obj_path: Path):
    return [ln.split(None, 1)[1].strip()
            for ln in obj_path.read_text(encoding="utf-8").splitlines()
            if ln.startswith("g ")]


class SceneTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.obj = self.dir / "scene.obj"

        # Руки: кисть в 10 по +Y, точка крепления оружия ещё в 2 дальше.
        self.arms = self.dir / "c_test_arms.smd"
        self.arms.write_text(_smd(
            [("root", None), ("bip_hand_R", "root"), ("weapon_bone", "bip_hand_R")],
            {"bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "weapon_bone": ((0, 2, 0), (0, 0, 0))},
            [("test_hands", [((0, 10, 0), "bip_hand_R"),
                             ((1, 10, 0), "bip_hand_R"),
                             ((0, 11, 0), "bip_hand_R")])],
        ), encoding="utf-8")

        # Та же рука в анимации: корень повёрнут на 90° вокруг Z.
        self.anim = self.dir / "anim.smd"
        self.anim.write_text(_smd(
            [("root", None), ("bip_hand_R", "root"), ("weapon_bone", "bip_hand_R")],
            {"root": ((0, 0, 0), (0, 0, HALF_PI)),
             "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "weapon_bone": ((0, 2, 0), (0, 0, 0))},
        ), encoding="utf-8")

        # Оружие: своя кость weapon_bone в начале координат.
        self.weapon = self.dir / "c_test_reference.smd"
        self.weapon.write_text(_smd(
            [("weapon_bone", None)],
            {},
            [("c_test", [((0, 0, 0), "weapon_bone"),
                         ((1, 0, 0), "weapon_bone"),
                         ((0, 0, 1), "weapon_bone")])],
        ), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _build(self, **kwargs):
        return viewmodel_scene.build(
            str(self.obj),
            weapon_ref_smd=str(self.weapon),
            arms_ref_smd=str(self.arms),
            anim_smd=str(self.anim),
            **kwargs,
        )

    def test_both_models_land_in_one_file(self):
        scene = self._build()
        self.assertIsNotNone(scene)
        self.assertTrue(self.obj.exists())
        self.assertTrue((self.dir / "scene.mtl").exists())
        self.assertEqual(sorted(_obj_groups(self.obj)), ["c_test", "test_hands"])

    def test_materials_are_split_by_part(self):
        """Панель редактирует оружие; руки показываются, но не правятся."""
        scene = self._build()
        self.assertEqual(scene.weapon_materials, ["c_test"])
        self.assertEqual(scene.arms_materials, ["test_hands"])
        self.assertEqual(scene.materials, ["c_test", "test_hands"])

    def test_weapon_is_placed_into_the_animated_hand(self):
        """Вершина в начале координат оружия обязана оказаться в weapon_bone руки.

        В OBJ оси уже конвертированы (x,y,z)→(x,z,-y), поэтому (-12,0,0)
        остаётся (-12,0,0) — но проверяем именно значение из файла.
        """
        self._build()
        self.assertIn((-12.0, 0.0, 0.0), _obj_vertices(self.obj))

    def test_arms_follow_the_animation_too(self):
        """Кисть с (0,10,0) уезжает в (-10,0,0) — руки тоже в позе, не в bind."""
        self._build()
        self.assertIn((-10.0, 0.0, 0.0), _obj_vertices(self.obj))

    def test_include_mats_drops_unwanted_meshes(self):
        """У рук солдата в том же SMD лежит ракета для перезарядки — её убираем."""
        scene = self._build(arms_include_mats=set())
        self.assertEqual(scene.arms_materials, [])
        self.assertEqual(scene.weapon_materials, ["c_test"])

    def test_item_that_is_worn_not_held_says_so(self):
        """У ранцев и знамён вида от первого лица нет в самой игре.

        Отдельная ошибка, а не общий отказ: «не удалось собрать сцену» соврало
        бы про причину, и пользователь пошёл бы искать поломку.
        """
        alien = self.dir / "alien.smd"
        alien.write_text(_smd(
            [("bip_spine_3", None)], {},
            [("alien_mat", [((0, 0, 0), "bip_spine_3"),
                            ((1, 0, 0), "bip_spine_3"),
                            ((0, 0, 1), "bip_spine_3")])],
        ), encoding="utf-8")
        with self.assertRaises(viewmodel_scene.NotHeldInHands):
            viewmodel_scene.build(
                str(self.obj), weapon_ref_smd=str(alien),
                arms_ref_smd=str(self.arms), anim_smd=str(self.anim))

    def test_missing_animation_refuses_the_scene(self):
        self.assertIsNone(viewmodel_scene.build(
            str(self.obj), weapon_ref_smd=str(self.weapon),
            arms_ref_smd=str(self.arms), anim_smd=str(self.dir / "nope.smd")))


class ConvertPartsTests(unittest.TestCase):
    """Сам конвертер: несколько мешей, каждый со своей матрицей."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.obj = self.dir / "out.obj"

    def tearDown(self):
        self._tmp.cleanup()

    def _part_file(self, name, material):
        path = self.dir / f"{name}.smd"
        path.write_text(_smd(
            [("bone", None)], {},
            [(material, [((1, 0, 0), "bone"), ((2, 0, 0), "bone"),
                         ((1, 1, 0), "bone")])],
        ), encoding="utf-8")
        return path

    def test_parts_keep_their_own_pose(self):
        """Сдвиг задан только второй части — первая обязана остаться на месте."""
        shift = (1, 0, 0, 0,  0, 1, 0, 100,  0, 0, 1, 0)   # +100 по Y
        ok, mats = SmdToObjService.convert_parts(
            [MeshPart(smd_path=str(self._part_file("a", "mat_a"))),
             MeshPart(smd_path=str(self._part_file("b", "mat_b")),
                      skinning={0: shift})],
            str(self.obj),
        )
        self.assertTrue(ok)
        self.assertEqual(mats, ["mat_a", "mat_b"])
        verts = _obj_vertices(self.obj)
        # Оси в OBJ: (x,y,z) → (x, z, -y). Сдвиг +100 по Y стал -100 по Z.
        self.assertIn((1.0, 0.0, 0.0), verts)
        self.assertIn((1.0, 0.0, -100.0), verts)

    def test_shared_material_name_merges_into_one_group(self):
        ok, mats = SmdToObjService.convert_parts(
            [MeshPart(smd_path=str(self._part_file("a", "same"))),
             MeshPart(smd_path=str(self._part_file("b", "same")))],
            str(self.obj),
        )
        self.assertTrue(ok)
        self.assertEqual(mats, ["same"])
        self.assertEqual(_obj_groups(self.obj), ["same"])

    def test_empty_scene_is_a_failure_not_a_crash(self):
        empty = self.dir / "empty.smd"
        empty.write_text(_smd([("bone", None)]), encoding="utf-8")
        ok, mats = SmdToObjService.convert_parts(
            [MeshPart(smd_path=str(empty))], str(self.obj))
        self.assertFalse(ok)
        self.assertEqual(mats, [])


if __name__ == "__main__":
    unittest.main()
