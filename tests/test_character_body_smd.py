"""
Тело персонажа: какой из декомпилированных SMD показывать в превью.

Обе ловушки — про пиромана. У него нет морфов лица (он в маске), поэтому
файла `*_morphs_low.smd`, которым Crowbar называет тело у остальных восьми
классов, не существует: подбор по имени класса брал первый по алфавиту
`pyro_head_bodygroup.smd`, и в превью висели голова, баллон, гранаты и рука
без тела. А сам `pyro_reference.smd` пуст — Crowbar положил геометрию тела в
`pyro_reference_lod6.smd` (4 треугольника против 482).
"""

import tempfile
import unittest
from pathlib import Path

from src.services.preview_3d_worker import Preview3DWorker
from src.services.smd_service import triangle_count


def write_smd(path: Path, triangles: int) -> None:
    """SMD с заданным числом треугольников — остальное в нём неважно."""
    lines = ["version 1", "nodes", '0 "root" -1', "end",
             "skeleton", "time 0", "0 0 0 0 0 0 0", "end", "triangles"]
    for _ in range(triangles):
        lines.append("mat")
        lines += ["0 0 0 0 0 0 0 0 0"] * 3
    path.write_text("\n".join(lines), encoding="utf-8")


def body_of(directory: Path):
    """Выбор тела так, как его делает воркер превью."""
    worker = Preview3DWorker.__new__(Preview3DWorker)
    worker._models = {}
    return worker._character_body_smd(str(directory))


class CharacterBodyTests(unittest.TestCase):
    def test_triangle_count_reads_the_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            smd = Path(tmp) / "body.smd"
            write_smd(smd, 7)
            self.assertEqual(triangle_count(str(smd)), 7)

    def test_body_comes_from_qc_not_from_the_file_name(self):
        """Голова крупнее тела, но какой меш основной — говорит QC."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "pyro.qc").write_text(
                '$modelname "player/pyro.mdl"\n'
                '$model "pyro" "pyro_reference.smd" {\n}\n'
                '$bodygroup "head"\n{\nstudio "pyro_head_bodygroup.smd"\nblank\n}\n',
                encoding="utf-8")
            write_smd(base / "pyro_reference.smd", 4)
            write_smd(base / "pyro_reference_lod6.smd", 482)
            write_smd(base / "pyro_head_bodygroup.smd", 1054)

            # Из семьи «сам файл плюс его _lodN» берётся тот, где геометрия есть.
            self.assertTrue(body_of(base).endswith("pyro_reference_lod6.smd"))

    def test_full_zero_level_wins_over_its_own_lods(self):
        """У остальных классов нулевой уровень настоящий — он и берётся."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "heavy.qc").write_text(
                '$body "studio" "heavy_morphs_low.smd"\n', encoding="utf-8")
            write_smd(base / "heavy_morphs_low.smd", 4036)
            write_smd(base / "heavy_morphs_low_lod3.smd", 1413)

            self.assertTrue(body_of(base).endswith("heavy_morphs_low.smd"))

    def test_no_qc_means_no_answer(self):
        """Без QC выбор остаётся прежним — воркер идёт своим старым путём."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_smd(base / "pyro_reference.smd", 4)
            self.assertIsNone(body_of(base))


if __name__ == "__main__":
    unittest.main()
