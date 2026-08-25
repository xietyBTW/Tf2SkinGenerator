"""
Перевод меша из bind-позы в позу анимации.

Превью показывало reference-меш как есть, а игра всегда проигрывает
последовательность. У Мутировавшего молока хлеб в bind-позе торчит из банки на
2.58 единицы, а первый кадр `idle` смещает кости на 2.69 — в игре хлеб внутри,
в превью снаружи.

Порядок эйлеровых углов (Rz·Ry·Rx) не угадан: в MDL кость несёт и углы, и
посчитанный компилятором Valve кватернион, и на 35 костях стоковых моделей
этот порядок воспроизводит кватернион с ошибкой 0.000000 (ближайший другой —
0.78). Тест ниже отличает его от обратного порядка.
"""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services import smd_pose

HALF_PI = math.pi / 2


def _skeleton(bones) -> str:
    lines = ["version 1", "nodes"]
    lines += [f'{i} "bone{i}" {parent}' for i, (parent, _, _) in enumerate(bones)]
    lines += ["end", "skeleton", "time 0"]
    for i, (_, pos, rot) in enumerate(bones):
        lines.append(f"{i} {pos[0]} {pos[1]} {pos[2]} {rot[0]} {rot[1]} {rot[2]}")
    lines += ["end", "triangles", "end", ""]
    return "\n".join(lines)


class MatrixTests(unittest.TestCase):
    def test_z_rotation_turns_x_into_y(self):
        m = smd_pose.local_matrix((0, 0, 0), (0, 0, HALF_PI))
        x, y, z = smd_pose.transform_point(m, (1, 0, 0))
        self.assertAlmostEqual(x, 0, places=6)
        self.assertAlmostEqual(y, 1, places=6)
        self.assertAlmostEqual(z, 0, places=6)

    def test_rotation_order_is_z_y_x(self):
        """Отличает Rz·Ry·Rx от обратного порядка: результаты разные."""
        m = smd_pose.local_matrix((0, 0, 0), (HALF_PI, 0, HALF_PI))
        x, y, z = smd_pose.transform_point(m, (0, 1, 0))
        # Сначала поворот вокруг X: (0,1,0) → (0,0,1); затем вокруг Z: не меняет.
        self.assertAlmostEqual(x, 0, places=6)
        self.assertAlmostEqual(y, 0, places=6)
        self.assertAlmostEqual(z, 1, places=6)

    def test_translation(self):
        m = smd_pose.local_matrix((5, -2, 3), (0, 0, 0))
        self.assertEqual(smd_pose.transform_point(m, (0, 0, 0)), (5, -2, 3))

    def test_direction_ignores_translation(self):
        m = smd_pose.local_matrix((100, 100, 100), (0, 0, 0))
        self.assertEqual(smd_pose.transform_dir(m, (1, 0, 0)), (1, 0, 0))

    def test_inverse_undoes_the_transform(self):
        m = smd_pose.local_matrix((3, -1, 7), (0.3, -1.1, 2.0))
        back = smd_pose.mul(smd_pose.rigid_inverse(m), m)
        for got, want in zip(back, smd_pose.IDENTITY):
            self.assertAlmostEqual(got, want, places=9)

    def test_child_inherits_the_parent(self):
        """Кость-ребёнок стоит на метр вперёд от родителя, повёрнутого на 90°."""
        parents = {0: -1, 1: 0}
        frame = {0: ((0, 0, 0), (0, 0, HALF_PI)), 1: ((1, 0, 0), (0, 0, 0))}
        world = smd_pose.world_matrices(parents, frame)
        x, y, z = smd_pose.transform_point(world[1], (0, 0, 0))
        self.assertAlmostEqual(x, 0, places=6)
        self.assertAlmostEqual(y, 1, places=6)
        self.assertAlmostEqual(z, 0, places=6)

    def test_broken_hierarchy_does_not_hang(self):
        """Кость сама себе родитель — не зацикливаемся."""
        world = smd_pose.world_matrices({0: 0}, {0: ((1, 2, 3), (0, 0, 0))})
        self.assertEqual(len(world), 1)


class SkinningMatrixTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _smd(self, name: str, bones) -> str:
        path = self.dir / name
        path.write_text(_skeleton(bones), encoding="utf-8")
        return str(path)

    def test_identical_poses_need_no_work(self):
        bones = [(-1, (0, 0, 0), (0, 0, 0)), (0, (1, 0, 0), (0, 0, 0))]
        ref = self._smd("ref.smd", bones)
        pose = self._smd("idle.smd", bones)
        self.assertIsNone(smd_pose.skinning_matrices(ref, pose))

    def test_root_only_difference_is_ignored(self):
        """В анимации корень разворачивает предмет «как в руке» — в превью
        предмет стоит в своей позе, крутить всю модель не надо."""
        ref = self._smd("ref.smd", [(-1, (0, 0, 0), (0, 0, 0))])
        pose = self._smd("idle.smd", [(-1, (10, 0, 0), (0, 0, HALF_PI))])
        self.assertIsNone(smd_pose.skinning_matrices(ref, pose))

    def test_child_movement_produces_matrices(self):
        ref = self._smd("ref.smd", [(-1, (0, 0, 0), (0, 0, 0)),
                                    (0, (1, 0, 0), (0, 0, 0))])
        pose = self._smd("idle.smd", [(-1, (0, 0, 0), (0, 0, 0)),
                                      (0, (1, 5, 0), (0, 0, 0))])
        mats = smd_pose.skinning_matrices(ref, pose)
        self.assertIsNotNone(mats)
        moved = smd_pose.transform_point(mats[1], (1, 0, 0))
        self.assertAlmostEqual(moved[1], 5, places=6)

    def test_mismatched_skeletons_are_refused(self):
        ref = self._smd("ref.smd", [(-1, (0, 0, 0), (0, 0, 0)),
                                    (0, (1, 0, 0), (0, 0, 0)),
                                    (0, (2, 0, 0), (0, 0, 0)),
                                    (0, (3, 0, 0), (0, 0, 0))])
        pose = self._smd("other.smd", [(-1, (0, 0, 0), (0, 0, 1.0))])
        self.assertIsNone(smd_pose.skinning_matrices(ref, pose))

    def test_missing_files(self):
        self.assertIsNone(smd_pose.skinning_matrices("", ""))
        self.assertIsNone(smd_pose.skinning_matrices(
            str(self.dir / "нет.smd"), str(self.dir / "тоже нет.smd")))


class VertexSkinningTests(unittest.TestCase):
    SHIFT = smd_pose.local_matrix((0, 10, 0), (0, 0, 0))

    def test_single_bone(self):
        pos, _ = smd_pose.apply_to_vertex({0: self.SHIFT}, [(0, 1.0)],
                                          (1, 2, 3), (0, 0, 1))
        self.assertEqual(pos, (1, 12, 3))

    def test_weights_are_blended(self):
        mats = {0: self.SHIFT, 1: smd_pose.IDENTITY}
        pos, _ = smd_pose.apply_to_vertex(mats, [(0, 0.5), (1, 0.5)],
                                          (0, 0, 0), (0, 0, 1))
        self.assertAlmostEqual(pos[1], 5.0)

    def test_unnormalised_weights_are_normalised(self):
        """В SMD веса не всегда дают в сумме единицу."""
        mats = {0: self.SHIFT, 1: smd_pose.IDENTITY}
        pos, _ = smd_pose.apply_to_vertex(mats, [(0, 1.0), (1, 1.0)],
                                          (0, 0, 0), (0, 0, 1))
        self.assertAlmostEqual(pos[1], 5.0)

    def test_normal_stays_unit_length(self):
        rot = smd_pose.local_matrix((0, 0, 0), (0, 0, HALF_PI))
        _, nrm = smd_pose.apply_to_vertex({0: rot}, [(0, 1.0)],
                                          (0, 0, 0), (1, 0, 0))
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in nrm)), 1.0, places=6)
        self.assertAlmostEqual(nrm[1], 1.0, places=6)

    def test_unknown_bone_leaves_the_vertex_alone(self):
        pos, nrm = smd_pose.apply_to_vertex({0: self.SHIFT}, [(99, 1.0)],
                                            (1, 2, 3), (0, 0, 1))
        self.assertEqual(pos, (1, 2, 3))
        self.assertEqual(nrm, (0, 0, 1))

    def test_no_links_no_change(self):
        self.assertEqual(
            smd_pose.apply_to_vertex({0: self.SHIFT}, [], (1, 2, 3), (0, 0, 1))[0],
            (1, 2, 3))


class SanityGuardTests(unittest.TestCase):
    BOX = [(0, 0, 0), (10, 10, 10)]

    def test_reasonable_pose_passes(self):
        self.assertTrue(smd_pose.looks_sane(self.BOX, [(1, 1, 1), (9, 9, 9)]))

    def test_exploded_mesh_is_rejected(self):
        self.assertFalse(smd_pose.looks_sane(self.BOX, [(0, 0, 0), (500, 0, 0)]))

    def test_nan_is_rejected(self):
        self.assertFalse(smd_pose.looks_sane(self.BOX,
                                             [(0, 0, 0), (float("nan"), 0, 0)]))

    def test_infinity_is_rejected(self):
        self.assertFalse(smd_pose.looks_sane(self.BOX,
                                             [(0, 0, 0), (float("inf"), 0, 0)]))

    def test_empty_input_is_rejected(self):
        self.assertFalse(smd_pose.looks_sane([], []))


class FindPoseSmdTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _qc(self, text: str) -> str:
        path = self.dir / "model.qc"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_block_form(self):
        """Так пишет Crowbar: файл на отдельной строке внутри блока."""
        anims = self.dir / "model_anims"
        anims.mkdir()
        (anims / "idle.smd").write_text("version 1\n", encoding="utf-8")
        qc = self._qc('$sequence "idle" {\n\t"model_anims\\idle.smd"\n\tfps 30\n}\n')
        self.assertEqual(Path(smd_pose.find_pose_smd(qc)).name, "idle.smd")

    def test_inline_form(self):
        (self.dir / "idle.smd").write_text("version 1\n", encoding="utf-8")
        qc = self._qc('$sequence "idle" "idle.smd" fps 30\n')
        self.assertEqual(Path(smd_pose.find_pose_smd(qc)).name, "idle.smd")

    def test_first_sequence_wins(self):
        for name in ("idle.smd", "fire.smd"):
            (self.dir / name).write_text("version 1\n", encoding="utf-8")
        qc = self._qc('$sequence "idle" "idle.smd"\n$sequence "fire" "fire.smd"\n')
        self.assertEqual(Path(smd_pose.find_pose_smd(qc)).name, "idle.smd")

    def test_missing_file_is_not_returned(self):
        qc = self._qc('$sequence "idle" "нет-такого.smd"\n')
        self.assertIsNone(smd_pose.find_pose_smd(qc))

    def test_no_sequences(self):
        self.assertIsNone(smd_pose.find_pose_smd(self._qc('$modelname "x.mdl"\n')))

    def test_absent_qc(self):
        self.assertIsNone(smd_pose.find_pose_smd(str(self.dir / "нет.qc")))
        self.assertIsNone(smd_pose.find_pose_smd(""))


if __name__ == "__main__":
    unittest.main()
