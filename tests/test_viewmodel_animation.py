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


class LayerTests(BuildSceneTests):
    """Разностный слой поверх кадров: вздрагивание горящего игрока.

    В SMD у такого слоя нули вместо поз — это добавка, а не поза. Складывается
    он в местных осях кости, а КОРЕНЬ пропускается: там лежит не движение, а
    поправка осей, и вместе с базой она кладёт персонажа набок.
    """

    def _layer(self, frame):
        path = self.dir / "layer.smd"
        path.write_text(_smd(
            [("root", None), ("bip_hand_R", "root"),
             ("weapon_bone", "bip_hand_R")], frame), encoding="utf-8")
        return str(path)

    def _hand(self, **kwargs):
        clip = self._build(**kwargs)["clip"]
        return next(t for t in clip["tracks"] if t["name"] == "bip_hand_R")

    def test_offset_is_added_to_the_bone(self):
        was = self._hand()
        now = self._hand(anim_layer_smd=self._layer(
            {"bip_hand_R": ((0, 3, 0), (0, 0, 0))}))
        self.assertEqual(now["positions"][1] - was["positions"][1], 3)

    def test_root_of_the_layer_is_ignored(self):
        """У вздрагивания солдата в корне ровно -90 градусов — оси, не поза."""
        clip = self._build(anim_layer_smd=self._layer(
            {"root": ((0, 0, 0), (0, 0, -HALF_PI))}))["clip"]
        plain = self._build()["clip"]
        root = next(t for t in clip["tracks"] if t["name"] == "root")
        before = next(t for t in plain["tracks"] if t["name"] == "root")
        self.assertEqual(root["quaternions"], before["quaternions"])

    def test_scene_without_a_layer_is_unchanged(self):
        self.assertEqual(self._hand(anim_layer_smd=""), self._hand())


class CutTests(BuildSceneTests):
    """Обрыв движения: замороженная смерть застывает посреди падения."""

    def _times(self, **kwargs):
        scene = viewmodel_animation.build_scene(
            arms_ref_smd=str(self.arms), weapon_ref_smd=str(self.weapon),
            **kwargs)
        return scene["clip"]["times"]

    def _long_anim(self, frames=10):
        """Анимация на несколько кадров: поза одна, важны их номера."""
        lines = ["version 1", "nodes",
                 '0 "root" -1', '1 "bip_hand_R" 0', '2 "weapon_bone" 1',
                 "end", "skeleton"]
        for i in range(frames):
            lines.append(f"time {i}")
            lines += [f"{b} 0 0 0 0 0 0" for b in range(3)]
        lines += ["end", ""]
        path = self.dir / "long.smd"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def test_frames_past_the_cut_are_dropped(self):
        anim = self._long_anim()
        whole = self._times(anim_smd=anim, fps=10.0)
        cut = self._times(anim_smd=anim, fps=10.0, clip_cut=0.5)
        self.assertEqual(len(whole), 10)
        self.assertEqual(len(cut), 6)          # 0.0…0.5 включительно

    def test_cut_never_leaves_a_single_frame(self):
        """Из одного кадра дорожки не выйдет, и «замереть сразу» — не то."""
        self.assertGreaterEqual(
            len(self._times(anim_smd=self._long_anim(), fps=10.0,
                            clip_cut=0.0001)), 2)


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
