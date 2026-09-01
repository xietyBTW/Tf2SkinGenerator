"""
Сборка анимированной сцены вьюмодели (src/services/viewmodel_animation.py).

Проверяется то, из чего складывается картинка в руке, а не арифметика поз —
её держит test_viewmodel_pose:

  * пушка-НОСИТЕЛЬ под праздничной гирляндой: в `c_medigun_xmas` лежат одни
    огоньки, и без носителя они висели бы в пустой руке. Показываем, но
    редактировать даём только сам предмет;
  * бодигруппы: правая рука пиро и инженера объявлена отдельной, и без неё в
    сцене оставалась одна левая;
  * белый список материалов рук: у солдата в модели рук лежит РАКЕТА, и вне
    перезарядки её быть не должно.

Скелеты синтетические: поворот на 90° вокруг Z даёт числа, считаемые в уме.
"""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services import viewmodel_animation, viewmodel_pose

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


def _tri(material, bone, base=(0, 0, 0)):
    x, y, z = base
    return (material, [((x, y, z), bone), ((x + 1, y, z), bone),
                       ((x, y, z + 1), bone)])


class BuildSceneTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

        self.arms = self.dir / "c_test_arms.smd"
        self.arms.write_text(_smd(
            [("root", None), ("bip_hand_R", "root"),
             ("weapon_bone", "bip_hand_R")],
            {"bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "weapon_bone": ((0, 2, 0), (0, 0, 0))},
            [_tri("test_hands", "bip_hand_R"),
             _tri("w_rocket01", "bip_hand_R", (5, 0, 0))],
        ), encoding="utf-8")

        self.anim = self.dir / "anim.smd"
        self.anim.write_text(_smd(
            [("root", None), ("bip_hand_R", "root"),
             ("weapon_bone", "bip_hand_R")],
            {"root": ((0, 0, 0), (0, 0, HALF_PI)),
             "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "weapon_bone": ((0, 2, 0), (0, 0, 0))},
        ), encoding="utf-8")

        self.weapon = self.dir / "c_test_reference.smd"
        self.weapon.write_text(_smd(
            [("weapon_bone", None)], {}, [_tri("xms_lights", "weapon_bone")],
        ), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _build(self, **kwargs):
        return viewmodel_animation.build_scene(
            arms_ref_smd=str(self.arms),
            weapon_ref_smd=str(self.weapon),
            anim_smd=str(self.anim),
            **kwargs,
        )

    def _part(self, scene, kind):
        return next(p for p in scene["parts"] if p["kind"] == kind)

    # ── Пушка-носитель ────────────────────────────────────────────────────── #

    def _carrier(self) -> Path:
        path = self.dir / "c_base_reference.smd"
        path.write_text(_smd(
            [("weapon_bone", None)], {}, [_tri("c_base", "weapon_bone", (0, 0, 3))],
        ), encoding="utf-8")
        return path

    def test_carrier_is_shown_but_stays_uneditable(self):
        """Праздничное оружие — гирлянда, а не пушка.

        В `c_medigun_xmas` лежат одни огоньки: показывать их в пустой руке
        неправильно, а перекрашивать медиган под ними пользователь не просил.
        """
        scene = self._build(weapon_carrier_smd=str(self._carrier()))
        weapon = self._part(scene, "weapon")
        self.assertEqual(weapon["materials"], ["xms_lights", "c_base"])
        self.assertEqual(scene["weaponMaterials"], ["xms_lights"])

    def test_carrier_geometry_is_appended_after_the_item(self):
        """Группы носителя должны указывать на СВОИ вершины.

        Смещение старта легко потерять, и тогда материал носителя красил бы
        треугольники гирлянды.
        """
        plain = self._build()
        scene = self._build(weapon_carrier_smd=str(self._carrier()))
        weapon = self._part(scene, "weapon")
        item_verts = len(self._part(plain, "weapon")["positions"]) // 3

        self.assertEqual(len(weapon["positions"]) // 3, item_verts * 2)
        self.assertEqual([g["material"] for g in weapon["groups"]],
                         ["xms_lights", "c_base"])
        self.assertEqual(weapon["groups"][1]["start"], item_verts)
        # Веса и индексы наращены вместе с вершинами, иначе меш развалится.
        self.assertEqual(len(weapon["skinIndex"]),
                         len(weapon["positions"]) // 3 * 4)

    def test_item_that_is_worn_not_held_says_so(self):
        """Ранцы, знамёна и ботинки к руке не крепятся вовсе.

        Отличать это от поломки сборки надо: сообщение пользователю разное.
        """
        worn = self.dir / "c_batt_buffpack_reference.smd"
        worn.write_text(_smd(
            [("static_prop", None)], {}, [_tri("c_pack", "static_prop")],
        ), encoding="utf-8")

        with self.assertRaises(viewmodel_pose.NotHeldInHands):
            viewmodel_animation.build_scene(
                arms_ref_smd=str(self.arms),
                weapon_ref_smd=str(worn),
                anim_smd=str(self.anim),
            )

    def test_carrier_that_does_not_load_is_skipped_quietly(self):
        """Носителя может не оказаться — это не повод остаться без сцены."""
        scene = self._build(weapon_carrier_smd=str(self.dir / "нет.smd"))
        self.assertEqual(self._part(scene, "weapon")["materials"], ["xms_lights"])

    # ── Бодигруппы и белый список ─────────────────────────────────────────── #

    def test_arms_bodygroups_are_added(self):
        """Правая рука пиро и инженера — отдельная бодигруппа.

        Без неё в сцене оставалась одна левая.
        """
        right = self.dir / "c_righthand_bodygroup.smd"
        right.write_text(_smd(
            [("root", None), ("bip_hand_R", "root")], {},
            [_tri("test_handR", "bip_hand_R")],
        ), encoding="utf-8")

        scene = self._build(arms_extra_smds=[str(right)])
        self.assertIn("test_handR", self._part(scene, "arms")["materials"])

    def test_arms_whitelist_hides_the_prop(self):
        """У солдата в модели РУК лежит ракета — в покое её быть не должно."""
        full = self._build()
        self.assertIn("w_rocket01", self._part(full, "arms")["materials"])

        trimmed = self._build(arms_include_mats={"test_hands"})
        self.assertEqual(self._part(trimmed, "arms")["materials"], ["test_hands"])

    def test_weapon_bodygroups_share_the_weapon_skeleton(self):
        """Откидные части оружия едут теми же костями, что и основной меш."""
        extra = self.dir / "c_test_scope.smd"
        extra.write_text(_smd(
            [("weapon_bone", None)], {}, [_tri("c_test_scope", "weapon_bone")],
        ), encoding="utf-8")

        scene = self._build(weapon_extra_smds=[str(extra)])
        weapon = self._part(scene, "weapon")
        self.assertEqual(weapon["materials"], ["xms_lights", "c_test_scope"])
        # Бодигруппа своя часть предмета, а не носитель — её тоже красят.
        self.assertEqual(scene["weaponMaterials"], ["xms_lights", "c_test_scope"])


if __name__ == "__main__":
    unittest.main()


class OwnViewmodelTests(BuildSceneTests):
    """Предмет со СВОЕЙ моделью вида: часы шпиона.

    В `v_watch_*.mdl` уже лежат и руки, и часы, и свои последовательности —
    сажать в руку нечего, и отдельной части с оружием в сцене нет.
    """

    def test_scene_without_a_weapon_part_is_built(self):
        scene = viewmodel_animation.build_scene(
            arms_ref_smd=str(self.arms),
            anim_smd=str(self.anim),
            editable_mats=["test_hands"],
        )
        self.assertEqual([p["kind"] for p in scene["parts"]], ["arms"])
        self.assertEqual(scene["weaponMaterials"], ["test_hands"])
        self.assertTrue(scene["clip"]["times"])

    def test_editable_list_wins_over_the_weapon_materials(self):
        """У модели вида руки и предмет вперемешку — красят только предмет."""
        scene = self._build(editable_mats=["xms_lights"])
        self.assertEqual(scene["weaponMaterials"], ["xms_lights"])
