"""Тесты ядра изоляции плеч вьюмодели (определение + переименование $texturegroup)."""

import os
import tempfile
import unittest

from src.services.qc_skin_parser import (
    detect_shoulder_materials, team_reference, neutral_materials,
    apply_team_promotions,
)
from src.services.model_build_service import ModelBuildService
from src.services.smd_service import SMDService


# Реальная структура $texturegroup рук инженера (упрощённо: 1 RED + 1 BLU скин,
# те же столбцы). col0 — командное тело, col1/col2 — нейтральные руки.
_ENG_ROWS = [
    ["engineer_red",  "engineer_handL", "engineer_handR_red"],   # RED
    ["engineer_blue", "engineer_handL", "engineer_handR_red"],   # BLU
]


_SMD = """version 1
nodes
0 "root" -1
end
skeleton
time 0
0 0 0 0 0 0 0
end
triangles
engineer_red
0 0 0 0 0 0 1 0.1 0.2
0 1 0 0 0 0 1 0.5 0.6
0 0 1 0 0 0 1 0.9 0.1
engineer_handL
0 0 0 0 0 0 1 0.1 0.2
0 1 0 0 0 0 1 0.5 0.6
0 0 1 0 0 0 1 0.9 0.1
end
"""


class DetectShoulderMaterialsTests(unittest.TestCase):
    def test_engineer_arms_have_body_material(self):
        red_row = ["engineer_red", "engineer_handl", "engineer_handr_red"]
        whitelist = ["engineer_handl", "engineer_handr_red"]
        self.assertEqual(detect_shoulder_materials(red_row, whitelist), ["engineer_red"])

    def test_clean_arms_have_nothing(self):
        # Руки без мирового тела — все материалы в whitelist → изолировать нечего.
        red_row = ["scout_handl", "scout_handr"]
        whitelist = ["scout_handl", "scout_handr"]
        self.assertEqual(detect_shoulder_materials(red_row, whitelist), [])

    def test_case_insensitive_and_dedup(self):
        red_row = ["Engineer_Red", "engineer_handl", "ENGINEER_RED"]
        whitelist = ["engineer_handl"]
        self.assertEqual(detect_shoulder_materials(red_row, whitelist), ["Engineer_Red"])

    def test_empty_inputs(self):
        self.assertEqual(detect_shoulder_materials([], ["x"]), [])


class GenerateRenamedTexturegroupTests(unittest.TestCase):
    def test_renames_body_keeps_hands(self):
        rows = [["engineer_red", "engineer_handl", "engineer_handr_red"]]
        block = ModelBuildService.generate_renamed_texturegroup(
            rows, {"engineer_red": "vm_engineer_red"}
        )
        self.assertIn('$texturegroup "skinfamilies"', block)
        self.assertIn('"vm_engineer_red"', block)
        self.assertIn('"engineer_handl"', block)
        self.assertNotIn('"engineer_red"', block)  # старое имя ушло

    def test_lowercased(self):
        rows = [["Engineer_Red"]]
        block = ModelBuildService.generate_renamed_texturegroup(
            rows, {"engineer_red": "VM_Engineer"}
        )
        self.assertIn('"vm_engineer"', block)

    def test_applies_to_all_rows(self):
        rows = [["engineer_red", "h"], ["engineer_red", "h"]]
        block = ModelBuildService.generate_renamed_texturegroup(
            rows, {"engineer_red": "vm_engineer"}
        )
        self.assertEqual(block.count('"vm_engineer"'), 2)

    def test_empty_rows_returns_empty(self):
        self.assertEqual(
            ModelBuildService.generate_renamed_texturegroup([], {"a": "b"}), ""
        )

    def test_empty_rename_builds_unchanged(self):
        # Пустой rename + строки → блок строится без переименования (нужно для
        # промоушена нейтральных, где строки уже изменены отдельно).
        block = ModelBuildService.generate_renamed_texturegroup([["a", "b"]], {})
        self.assertIn('"a"', block)
        self.assertIn('"b"', block)


class TeamPromotionTests(unittest.TestCase):
    def test_team_reference_finds_body_column(self):
        ref = team_reference(_ENG_ROWS)
        self.assertEqual(ref, (0, "engineer_blue"))

    def test_team_reference_none_when_all_neutral(self):
        rows = [["a", "b"], ["a", "b"]]
        self.assertIsNone(team_reference(rows))

    def test_neutral_materials(self):
        self.assertEqual(
            neutral_materials(_ENG_ROWS), ["engineer_handL", "engineer_handR_red"]
        )

    def test_promote_neutral_only_in_blue_row(self):
        out = apply_team_promotions(_ENG_ROWS, {"engineer_handl": "engineer_handL_blue"})
        # RED-строка не тронута
        self.assertEqual(out[0], ["engineer_red", "engineer_handL", "engineer_handR_red"])
        # BLU-строка: handL заменён на синий вариант
        self.assertEqual(out[1], ["engineer_blue", "engineer_handL_blue", "engineer_handR_red"])

    def test_promote_empty_returns_copy(self):
        out = apply_team_promotions(_ENG_ROWS, {})
        self.assertEqual(out, [list(r) for r in _ENG_ROWS])


class RenameMaterialsInSmdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.smd = os.path.join(self.tmp, "ref.smd")
        with open(self.smd, "w", encoding="utf-8") as f:
            f.write(_SMD)

    def test_renames_only_target_material(self):
        n = SMDService.rename_materials_in_smd(self.smd, {"engineer_red": "vm_engineer_red"})
        self.assertEqual(n, 1)
        mats = SMDService.ordered_unique_materials(self.smd)
        self.assertIn("vm_engineer_red", mats)
        self.assertIn("engineer_handL", mats)
        self.assertNotIn("engineer_red", mats)

    def test_case_insensitive(self):
        n = SMDService.rename_materials_in_smd(self.smd, {"ENGINEER_RED": "vm_x"})
        self.assertEqual(n, 1)
        self.assertIn("vm_x", SMDService.ordered_unique_materials(self.smd))

    def test_no_match_no_change(self):
        n = SMDService.rename_materials_in_smd(self.smd, {"nope": "x"})
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
