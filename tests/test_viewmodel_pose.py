"""
Посадка оружия в руку класса через bonemerge (src/services/viewmodel_pose.py).

Проверяется то, что нельзя увидеть на глаз в превью, но что ломает картинку
целиком:

  * кость оружия встаёт РОВНО туда, где стоит одноимённая кость руки;
  * кость, которой у руки нет (`c_weapon_stattrack`), едет за своим родителем,
    сохраняя смещение;
  * скелеты сопоставляются по ИМЕНИ — номера костей у трёх разных моделей свои,
    и в тестах ниже они намеренно перемешаны;
  * когда цепляться не за что, возвращается None, а не модель в начале координат.

Скелеты синтетические: поворот ровно на 90° вокруг Z даёт числа, которые
считаются в уме, и любой сбой в конвенции углов или в порядке умножения матриц
сразу виден.
"""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services import smd_pose, viewmodel_pose

HALF_PI = math.pi / 2


def _smd(bones, frames=None) -> str:
    """SMD из (имя, родитель) и кадров [{имя: (позиция, углы)}, …]."""
    ids = {name: i for i, (name, _p) in enumerate(bones)}
    lines = ["version 1", "nodes"]
    for name, parent in bones:
        lines.append(f'{ids[name]} "{name}" {ids[parent] if parent else -1}')
    lines += ["end", "skeleton"]
    for n, frame in enumerate(frames or [{}]):
        lines.append(f"time {n}")
        for name, _parent in bones:
            pos, rot = frame.get(name, ((0, 0, 0), (0, 0, 0)))
            lines.append(f"{ids[name]} {pos[0]} {pos[1]} {pos[2]} "
                         f"{rot[0]} {rot[1]} {rot[2]}")
    lines += ["end", "triangles", "end", ""]
    return "\n".join(lines)


def _at(mats, bone_id, point):
    """Куда уедет точка `point`, привязанная к кости `bone_id`."""
    return tuple(round(v, 6) for v in smd_pose.transform_point(mats[bone_id], point))


class BonemergeTests(unittest.TestCase):
    """Оружие ведомое: одноимённая кость забирает мировую матрицу руки."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

        # Рука в bind-позе: кисть в 10 единицах по +Y, ствол ещё в 2 дальше.
        self.arms = self.dir / "c_test_arms.smd"
        self.arms.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"), ("weapon_bone", "bip_hand_R"),
        ], [{
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
        }]), encoding="utf-8")

        # Та же рука в анимации: корень повёрнут на 90° вокруг Z. Порядок костей
        # ОБРАТНЫЙ — совпадение обязано идти по именам, а не по номерам.
        self.anim = self.dir / "anim.smd"
        self.anim.write_text(_smd([
            ("weapon_bone", "bip_hand_R"), ("bip_hand_R", "root"), ("root", None),
        ], [{
            "root": ((0, 0, 0), (0, 0, HALF_PI)),
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
        }]), encoding="utf-8")

        # Оружие: корень в начале координат + своя кость в 3 единицах по +X.
        self.weapon = self.dir / "c_test_reference.smd"
        self.weapon.write_text(_smd([
            ("weapon_bone", None), ("c_weapon_stattrack", "weapon_bone"),
        ], [{"c_weapon_stattrack": ((3, 0, 0), (0, 0, 0))}]), encoding="utf-8")

        self.pose = viewmodel_pose.load_rig(str(self.anim))

    def tearDown(self):
        self._tmp.cleanup()

    def test_arms_rig_is_where_the_animation_puts_it(self):
        """Поворот корня на 90°: кисть с (0,10,0) уезжает в (-10,0,0)."""
        self.assertEqual(
            tuple(round(self.pose.by_name["bip_hand_R"][i], 6) for i in (3, 7, 11)),
            (-10.0, 0.0, 0.0),
        )
        self.assertEqual(
            tuple(round(self.pose.by_name["weapon_bone"][i], 6) for i in (3, 7, 11)),
            (-12.0, 0.0, 0.0),
        )

    def test_weapon_root_lands_exactly_in_the_hand(self):
        mats = viewmodel_pose.bonemerge_skinning(str(self.weapon), self.pose)
        # Вершина в начале координат оружия обязана оказаться там же, где
        # weapon_bone руки — иначе ствол висит рядом с кистью, а не в ней.
        self.assertEqual(_at(mats, 0, (0, 0, 0)), (-12.0, 0.0, 0.0))

    def test_bone_absent_from_the_arms_rides_along(self):
        """`c_weapon_stattrack` у рук нет: смещение 3 по +X едет за родителем."""
        mats = viewmodel_pose.bonemerge_skinning(str(self.weapon), self.pose)
        # +X после поворота на 90° вокруг Z смотрит в +Y.
        self.assertEqual(_at(mats, 1, (3, 0, 0)), (-12.0, 3.0, 0.0))

    def test_matching_is_by_name_not_by_index(self):
        """Номера костей в анимации перемешаны — результат не меняется."""
        shuffled = self.dir / "anim_shuffled.smd"
        shuffled.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"), ("weapon_bone", "bip_hand_R"),
        ], [{
            "root": ((0, 0, 0), (0, 0, HALF_PI)),
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
        }]), encoding="utf-8")
        other = viewmodel_pose.load_rig(str(shuffled))
        self.assertEqual(
            viewmodel_pose.bonemerge_skinning(str(self.weapon), self.pose),
            viewmodel_pose.bonemerge_skinning(str(self.weapon), other),
        )

    def test_only_bones_listed_in_bonemerge_take_the_hand_position(self):
        """Совпадение имён — не повод сливать кость.

        У руки `weapon_bone_1..4` — лесенка точек крепления под разную длину
        оружия, а у револьвера так зовутся его собственные курок и барабан.
        Слияние по имени разносило модель на 73 единицы вместо её двадцати.
        """
        weapon = self.dir / "c_revolver_reference.smd"
        weapon.write_text(_smd([
            ("weapon_bone", None), ("weapon_bone_1", "weapon_bone"),
        ], [{"weapon_bone_1": ((0, 0, 5), (0, 0, 0))}]), encoding="utf-8")

        # В анимации weapon_bone_1 стоит СОВСЕМ не там, где у оружия.
        anim = self.dir / "anim_ladder.smd"
        anim.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"),
            ("weapon_bone", "bip_hand_R"), ("weapon_bone_1", "bip_hand_R"),
        ], [{
            "root": ((0, 0, 0), (0, 0, HALF_PI)),
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
            "weapon_bone_1": ((0, 40, 0), (0, 0, 0)),   # лесенка руки
        }]), encoding="utf-8")
        pose = viewmodel_pose.load_rig(str(anim))

        mats = viewmodel_pose.bonemerge_skinning(
            str(weapon), pose, merge_bones=["weapon_bone"])
        # Своя кость сохраняет собственное смещение 5 по +Z от weapon_bone.
        self.assertEqual(_at(mats, 1, (0, 0, 5)), (-12.0, 0.0, 5.0))

        # А слияние по имени утащило бы её в точку крепления руки — на 38
        # единиц от того места, где деталь оружия должна быть.
        naive = viewmodel_pose.bonemerge_skinning(
            str(weapon), pose, merge_bones=["weapon_bone", "weapon_bone_1"])
        self.assertEqual(_at(naive, 1, (0, 0, 5)), (-50.0, 0.0, 0.0))

    def test_without_a_list_a_bone_that_kept_its_place_merges(self):
        """Так подвижные части оружия и оживают.

        Своих кадров у моделей оружия нет — одна bind-поза. Крышку флергана
        открывает кость `weapon_bone_2` из анимации ПИРО, и без слияния по
        имени она осталась бы неподвижной. `$bonemerge` в декомпилированном QC
        флергана нет вовсе, так что кость отбирается по признаку твёрдого тела:
        расстояние до родителя вращение не меняет — 5 в bind, 5 в позе.
        """
        flap = self.dir / "c_flaregun_reference.smd"
        flap.write_text(_smd([
            ("weapon_bone", None), ("weapon_bone_2", "weapon_bone"),
        ], [{"weapon_bone_2": ((0, 0, 5), (0, 0, 0))}]), encoding="utf-8")
        anim = self.dir / "anim_flap.smd"
        anim.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"),
            ("weapon_bone", "bip_hand_R"), ("weapon_bone_2", "bip_hand_R"),
        ], [{
            "root": ((0, 0, 0), (0, 0, HALF_PI)),
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
            "weapon_bone_2": ((0, 7, 0), (0, 0, 0)),   # крышка откинута
        }]), encoding="utf-8")
        pose = viewmodel_pose.load_rig(str(anim))

        mats = viewmodel_pose.bonemerge_skinning(str(flap), pose)
        self.assertEqual(_at(mats, 0, (0, 0, 0)), (-12.0, 0.0, 0.0))
        # Крышка уехала туда, куда её увела анимация класса, а не осталась
        # висеть на своём bind-смещении от корня.
        self.assertEqual(_at(mats, 1, (0, 0, 5)), (-17.0, 0.0, 0.0))

    def test_without_a_list_a_bone_that_flew_away_is_left_alone(self):
        """Обратный случай: одноимённая кость принадлежит ДРУГОМУ оружию.

        Скелет модели анимаций один на весь класс, и в кадре `idle` шпиона
        `weapon_bone_4` уезжает на 58 единиц от `weapon_bone` при собственных
        3.9 — это кость не револьвера. Пока сливалось всё подряд, Карающий и
        праздничный револьвер разлетались по всему кадру.
        """
        weapon = self.dir / "c_snub_nose_reference.smd"
        weapon.write_text(_smd([
            ("weapon_bone", None), ("weapon_bone_4", "weapon_bone"),
        ], [{"weapon_bone_4": ((0, 0, 5), (0, 0, 0))}]), encoding="utf-8")
        anim = self.dir / "anim_stray.smd"
        anim.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"),
            ("weapon_bone", "bip_hand_R"), ("weapon_bone_4", "bip_hand_R"),
        ], [{
            "root": ((0, 0, 0), (0, 0, HALF_PI)),
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
            "weapon_bone_4": ((0, 40, 0), (0, 0, 0)),   # чужая кость
        }]), encoding="utf-8")
        pose = viewmodel_pose.load_rig(str(anim))

        mats = viewmodel_pose.bonemerge_skinning(str(weapon), pose)
        self.assertEqual(_at(mats, 0, (0, 0, 0)), (-12.0, 0.0, 0.0))
        # Деталь осталась на своём смещении от корня оружия, а не улетела.
        self.assertEqual(_at(mats, 1, (0, 0, 5)), (-12.0, 0.0, 5.0))

    def test_bone_is_judged_on_every_frame_it_is_shown(self):
        """Кость может стоять на месте в первом кадре и улететь в середине.

        У Ответного удара патрон в `reload_loop` именно так себя и вёл, и
        отбор по одному кадру растягивал модель с 39 единиц до 206.
        """
        weapon = self.dir / "c_reserve_shooter_reference.smd"
        weapon.write_text(_smd([
            ("weapon_bone", None), ("weapon_bone_1", "weapon_bone"),
        ], [{"weapon_bone_1": ((0, 0, 5), (0, 0, 0))}]), encoding="utf-8")
        anim = self.dir / "anim_late_flight.smd"
        anim.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"),
            ("weapon_bone", "bip_hand_R"), ("weapon_bone_1", "bip_hand_R"),
        ], [
            {"bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "weapon_bone": ((0, 2, 0), (0, 0, 0)),
             "weapon_bone_1": ((0, 7, 0), (0, 0, 0))},     # на месте
            {"bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "weapon_bone": ((0, 2, 0), (0, 0, 0)),
             "weapon_bone_1": ((0, 60, 0), (0, 0, 0))},    # улетела
        ]), encoding="utf-8")

        first = viewmodel_pose.load_rig(str(anim), 0)
        second = viewmodel_pose.load_rig(str(anim), 1)
        self.assertIn("weapon_bone_1",
                      viewmodel_pose.merged_bone_names(str(weapon), first))
        self.assertEqual(
            viewmodel_pose.merged_bone_names(str(weapon), [first, second]),
            ["weapon_bone"])

    def test_a_second_grip_above_the_anchor_still_merges(self):
        """У медигана `weapon_bone_L` — левая рука, и он КОРЕНЬ скелета.

        На нём висит почти весь меш (16968 вершин из 19116). Пока «всё выше
        weapon_bone» отбрасывалось целиком, медиган не следовал за левой рукой
        и стоял со смещением 5.5 единиц. Отличается второй хват от мирового
        нуля именем: у Valve хваты зовутся `weapon_bone*`.
        """
        weapon = self.dir / "c_medigun_reference.smd"
        weapon.write_text(_smd([
            ("weapon_bone_L", None), ("weapon_bone", "weapon_bone_L"),
        ], [{"weapon_bone": ((0, 0, 0), (0, 0, 0))}]), encoding="utf-8")
        anim = self.dir / "anim_two_grips.smd"
        anim.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"), ("bip_hand_L", "root"),
            ("weapon_bone", "bip_hand_R"), ("weapon_bone_L", "bip_hand_L"),
        ], [{
            "root": ((0, 0, 0), (0, 0, HALF_PI)),
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "bip_hand_L": ((0, 4, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
            "weapon_bone_L": ((0, 2, 0), (0, 0, 0)),
        }]), encoding="utf-8")
        pose = viewmodel_pose.load_rig(str(anim))

        self.assertEqual(viewmodel_pose.merged_bone_names(str(weapon), pose),
                         ["weapon_bone", "weapon_bone_L"])
        mats = viewmodel_pose.bonemerge_skinning(str(weapon), pose)
        # Левый хват стоит там, где его держит ЛЕВАЯ рука, а не в 6 единицах
        # от правой, куда его утащило бы наследование от weapon_bone.
        self.assertEqual(_at(mats, 0, (0, 0, 0)), (-6.0, 0.0, 0.0))

    def test_a_shared_world_root_above_the_grip_is_not_merged(self):
        """Корень скелета оружия может называться так же, как мировой ноль.

        У Хлебной атаки он зовётся `root`, и в модели анимаций шпиона такой
        тоже есть — но это начало координат. Слияние с ним оставляло сапёр
        висеть перед камерой: держат оружие за `weapon_bone`, а всё, что выше
        него, не сливается вовсе.
        """
        weapon = self.dir / "c_breadmonster_sapper_reference.smd"
        weapon.write_text(_smd([
            ("root", None), ("weapon_bone", "root"),
        ], [{"weapon_bone": ((0, 0, 0), (0, 0, 0))}]), encoding="utf-8")
        anim = self.dir / "anim_with_root.smd"
        anim.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"),
            ("weapon_bone", "bip_hand_R"),
        ], [{
            "root": ((0, 0, 0), (0, 0, HALF_PI)),
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "weapon_bone": ((0, 2, 0), (0, 0, 0)),
        }]), encoding="utf-8")
        pose = viewmodel_pose.load_rig(str(anim))

        mats = viewmodel_pose.bonemerge_skinning(str(weapon), pose)
        self.assertEqual(_at(mats, 1, (0, 0, 0)), (-12.0, 0.0, 0.0))

    def test_list_that_misses_the_rig_falls_back_to_everything_shared(self):
        """Список из чужого QC не должен оставлять предмет без крепления."""
        mats = viewmodel_pose.bonemerge_skinning(
            str(self.weapon), self.pose, merge_bones=["совсем_другая_кость"])
        self.assertEqual(_at(mats, 0, (0, 0, 0)), (-12.0, 0.0, 0.0))

    def test_merge_point_is_found_below_a_foreign_root(self):
        """Корень скелета оружия к руке не крепится — крепится его потомок.

        У Фалломорфера корень зовётся по имени модели, а в руку садится
        `weapon_bone` под ним. По корню такие модели отказывались собираться.
        """
        weapon = self.dir / "c_drg_reference.smd"
        weapon.write_text(_smd([
            ("c_drg_phlogistinator", None),
            ("weapon_bone", "c_drg_phlogistinator"),
        ], [{"weapon_bone": ((0, 0, 2), (0, 0, 0))}]), encoding="utf-8")

        mats = viewmodel_pose.bonemerge_skinning(str(weapon), self.pose)
        self.assertIsNotNone(mats)
        self.assertEqual(_at(mats, 1, (0, 0, 2)), (-12.0, 0.0, 0.0))

    def test_two_merge_points_are_both_used(self):
        """Стальные кулаки крепятся сразу к двум кистям, по одной на руку."""
        arms = self.dir / "c_two_hands_arms.smd"
        arms.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"), ("bip_hand_L", "root"),
        ], [{"bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "bip_hand_L": ((0, -10, 0), (0, 0, 0))}]), encoding="utf-8")
        anim = self.dir / "anim_two_hands.smd"
        anim.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"), ("bip_hand_L", "root"),
        ], [{"root": ((0, 0, 0), (0, 0, HALF_PI)),
             "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "bip_hand_L": ((0, -10, 0), (0, 0, 0))}]), encoding="utf-8")
        pose = viewmodel_pose.load_rig(str(anim))

        fists = self.dir / "c_fists_reference.smd"
        fists.write_text(_smd([
            ("steelfists_reference", None),
            ("bip_hand_R", "steelfists_reference"),
            ("bip_hand_L", "steelfists_reference"),
        ], [{"bip_hand_R": ((0, 10, 0), (0, 0, 0)),
             "bip_hand_L": ((0, -10, 0), (0, 0, 0))}]), encoding="utf-8")

        mats = viewmodel_pose.bonemerge_skinning(str(fists), pose)
        self.assertEqual(_at(mats, 1, (0, 10, 0)), (-10.0, 0.0, 0.0))
        self.assertEqual(_at(mats, 2, (0, -10, 0)), (10.0, 0.0, 0.0))

    def test_nothing_to_merge_onto_gives_none(self):
        """Ни одного общего имени — оружие вешать не на что."""
        alien = self.dir / "alien.smd"
        alien.write_text(_smd([("some_other_bone", None)]), encoding="utf-8")
        self.assertIsNone(
            viewmodel_pose.bonemerge_skinning(str(alien), self.pose)
        )

    def test_missing_files_are_survivable(self):
        self.assertIsNone(viewmodel_pose.load_rig(str(self.dir / "nope.smd")))
        self.assertIsNone(viewmodel_pose.bonemerge_skinning("", self.pose))
        self.assertIsNone(viewmodel_pose.arms_skinning(str(self.arms), None))


class ArmsSkinningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.arms = self.dir / "c_test_arms.smd"
        self.arms.write_text(_smd([
            ("root", None), ("bip_hand_R", "root"), ("bip_thumb_R", "bip_hand_R"),
        ], [{
            "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
            "bip_thumb_R": ((0, 1, 0), (0, 0, 0)),
        }]), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _pose(self, bones, frames):
        path = self.dir / "pose.smd"
        path.write_text(_smd(bones, frames), encoding="utf-8")
        return viewmodel_pose.load_rig(str(path))

    def test_mesh_follows_the_animated_skeleton(self):
        pose = self._pose(
            [("root", None), ("bip_hand_R", "root"), ("bip_thumb_R", "bip_hand_R")],
            [{
                "root": ((0, 0, 0), (0, 0, HALF_PI)),
                "bip_hand_R": ((0, 10, 0), (0, 0, 0)),
                "bip_thumb_R": ((0, 1, 0), (0, 0, 0)),
            }],
        )
        mats = viewmodel_pose.arms_skinning(str(self.arms), pose)
        self.assertEqual(_at(mats, 1, (0, 10, 0)), (-10.0, 0.0, 0.0))

    def test_bone_missing_from_the_animation_stays_in_bind(self):
        """У неанимированной кости матрица единичная, а не отброшенная.

        Отброшенная означала бы вершину, посчитанную по части своих весов —
        то есть шов ровно там, где меш переходит с одной кости на другую.
        """
        pose = self._pose(
            [("root", None), ("bip_hand_R", "root")],
            [{"root": ((0, 0, 0), (0, 0, HALF_PI)),
              "bip_hand_R": ((0, 10, 0), (0, 0, 0))}],
        )
        mats = viewmodel_pose.arms_skinning(str(self.arms), pose)
        self.assertEqual(mats[2], smd_pose.IDENTITY)
        self.assertEqual(_at(mats, 2, (0, 11, 0)), (0.0, 11.0, 0.0))

    def test_foreign_skeleton_is_refused(self):
        """Меньше половины костей совпало — это не та модель анимаций."""
        pose = self._pose([("nothing_alike", None)], [{}])
        self.assertIsNone(viewmodel_pose.arms_skinning(str(self.arms), pose))


class FrameSelectionTests(unittest.TestCase):
    """Кадр выбирается в load_rig — единственном месте, где есть время."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "anim.smd"
        self.path.write_text(_smd(
            [("root", None)],
            [{"root": ((0, 0, 0), (0, 0, 0))},
             {"root": ((5, 0, 0), (0, 0, 0))},
             {"root": ((9, 0, 0), (0, 0, 0))}],
        ), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_each_frame_is_reachable(self):
        for index, expected in enumerate((0.0, 5.0, 9.0)):
            rig = viewmodel_pose.load_rig(str(self.path), index)
            self.assertEqual(rig.by_name["root"][3], expected)

    def test_frame_past_the_end_is_none(self):
        self.assertIsNone(viewmodel_pose.load_rig(str(self.path), 99))


class NodeParsingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_names_with_spaces_survive(self):
        path = self.dir / "spaced.smd"
        path.write_text(
            'version 1\nnodes\n0 "bone with space" -1\nend\n'
            'skeleton\ntime 0\n0 0 0 0 0 0 0\nend\n', encoding="utf-8")
        self.assertEqual(smd_pose.parse_node_names(str(path)),
                         {0: "bone with space"})
        self.assertEqual(smd_pose.parse_nodes(str(path)), {0: -1})

    def test_unquoted_names_are_still_read(self):
        """Не все экспортёры ставят кавычки — иерархию терять из-за этого нельзя."""
        path = self.dir / "bare.smd"
        path.write_text(
            "version 1\nnodes\n0 root -1\n1 child 0\nend\n"
            "skeleton\ntime 0\n0 0 0 0 0 0 0\n1 0 0 0 0 0 0\nend\n",
            encoding="utf-8")
        self.assertEqual(smd_pose.parse_node_names(str(path)),
                         {0: "root", 1: "child"})
        self.assertEqual(smd_pose.parse_nodes(str(path)), {0: -1, 1: 0})


if __name__ == "__main__":
    unittest.main()
