"""
Косметика в позе игрока.

В MDL шапка лежит как автору было удобно: у одной верх по +Y, у другой по −Z
(bak_teufort_knight: `bip_head` на z = −73 с поворотом на 96°). Игра этого не
видит — она сливает кость шапки с костью игрока, и шапка встаёт на голову.
Перенос повторяет это: где бы ни лежала bind-поза, вершина, заданная
относительно `bip_head`, оказывается в одном и том же месте.
"""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.data.player_skeleton import BONES
from src.services import cosmetic_pose, smd_pose
from src.services.smd_to_obj_service import SmdToObjService


def _hat(bone: str, pos, rot, local_vertex) -> str:
    """SMD с одной костью и одним треугольником из одной точки (в мире)."""
    w = smd_pose.local_matrix(pos, rot)
    x, y, z = smd_pose.transform_point(w, local_vertex)
    v = f"0 {x:.6f} {y:.6f} {z:.6f} 0 0 1 0 0"
    return "\n".join([
        "version 1", "nodes", f'0 "{bone}" -1', "end",
        "skeleton", "time 0", f"0 {pos[0]} {pos[1]} {pos[2]} {rot[0]} {rot[1]} {rot[2]}",
        "end", "triangles", "hat", v, v, v, "end", "",
    ])


def _obj_vertex(obj_path: Path):
    for line in obj_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            return tuple(float(t) for t in line.split()[1:4])
    return None


class CosmeticPoseTests(unittest.TestCase):
    #: Точка «над головой» в локальных осях bip_head (у рига TF2 верх — −Y).
    LOCAL = (0.0, -8.0, 0.0)

    def _placed(self, tmp: Path, name: str, bone: str, pos, rot):
        smd = tmp / f"{name}.smd"
        smd.write_text(_hat(bone, pos, rot, self.LOCAL), encoding="utf-8")
        obj = tmp / f"{name}.obj"
        ok, _ = SmdToObjService.convert(str(smd), str(obj), on_player=True)
        self.assertTrue(ok)
        return _obj_vertex(obj)

    def test_bind_frame_does_not_matter(self):
        """Y-up, «лёжа» и любой другой bind дают одну и ту же точку."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            a = self._placed(tmp, "yup", "bip_head", (0, 75.2, -1.1), (math.pi, 0, 0))
            b = self._placed(tmp, "knight", "bip_head", (0, -1.4, -73.5), (1.685, 0, 0))
            c = self._placed(tmp, "odd", "bip_head", (12, -3, 40), (0.3, -1.1, 2.0))
        for p, q in ((a, b), (a, c)):
            for u, v in zip(p, q):
                self.assertAlmostEqual(u, v, places=3)

    def test_up_is_up_and_above_the_head(self):
        """Точка над головой — выше bip_head игрока по вертикали сцены."""
        with TemporaryDirectory() as d:
            v = self._placed(Path(d), "h", "bip_head", (0, -1.4, -73.5), (1.685, 0, 0))
        head_z = BONES["bip_head"][11]                # высота головы в движке
        # Сцена: (x, y, z) движка → (x, z, −y); вертикаль сцены — y.
        self.assertGreater(v[1], head_z + 7.0)
        self.assertLess(abs(v[0]), 0.5)

    def test_unknown_skeleton_is_left_alone(self):
        with TemporaryDirectory() as d:
            smd = Path(d) / "x.smd"
            smd.write_text(_hat("static_prop", (0, 0, 0), (0, 0, 0), self.LOCAL),
                           encoding="utf-8")
            self.assertIsNone(cosmetic_pose.anchor_transform(str(smd)))
            self.assertIsNone(cosmetic_pose.on_player(str(smd), None))

    def test_head_preferred_over_root(self):
        """У косметики с позвоночником якорь — голова, а не таз."""
        with TemporaryDirectory() as d:
            smd = Path(d) / "chain.smd"
            smd.write_text("\n".join([
                "version 1", "nodes", '0 "bip_pelvis" -1', '1 "bip_head" 0', "end",
                "skeleton", "time 0", "0 0 0 0 0 0 0", "1 0 0 30 0 0 0", "end",
                "triangles", "end", "",
            ]), encoding="utf-8")
            t = cosmetic_pose.anchor_transform(str(smd))
        # Голова после переноса стоит ровно на голове игрока.
        moved = smd_pose.transform_point(t, (0, 0, 30))
        canon = smd_pose.mul(cosmetic_pose._FACE_CAMERA, BONES["bip_head"])
        for u, v in zip(moved, (canon[3], canon[7], canon[11])):
            self.assertAlmostEqual(u, v, places=4)


if __name__ == "__main__":
    unittest.main()
