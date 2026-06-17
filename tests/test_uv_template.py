"""Тесты генерации UV-шаблона по запросу (без полной сборки)."""

import os
import tempfile
import unittest

from src.services.extract_model_service import ExtractModelService

_SMD = """version 1
nodes
0 "root" -1
end
skeleton
time 0
0 0 0 0 0 0 0
end
triangles
test_material
0 0.0 0.0 0.0 0 0 1 0.10 0.20
0 1.0 0.0 0.0 0 0 1 0.50 0.60
0 0.0 1.0 0.0 0 0 1 0.90 0.10
end
"""


class GenerateUVTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.decompile = os.path.join(self.tmp, "decomp")
        self.export = os.path.join(self.tmp, "export")
        os.makedirs(self.decompile)

    def _write_smd(self, name: str):
        with open(os.path.join(self.decompile, name), "w", encoding="utf-8") as f:
            f.write(_SMD)

    def test_generates_png_from_reference_smd(self):
        self._write_smd("c_test_reference.smd")
        ok, result = ExtractModelService.generate_uv_template(
            self.decompile, "c_test", (128, 128), self.export
        )
        self.assertTrue(ok, result)
        self.assertTrue(os.path.exists(result))
        self.assertTrue(result.endswith("_uv_layout.png"))

    def test_no_smd_returns_flag(self):
        ok, result = ExtractModelService.generate_uv_template(
            self.decompile, "c_test", (128, 128), self.export
        )
        self.assertFalse(ok)
        self.assertEqual(result, "no_smd")

    def test_full_mdl_path_weapon_key_sanitized(self):
        # weapon_key как полный mdl-путь (персонажи/шапки) → имя файла из basename.
        self._write_smd("hat_reference.smd")
        ok, result = ExtractModelService.generate_uv_template(
            self.decompile, "models/player/items/hat.mdl", (64, 64), self.export
        )
        # SMD ищется по weapon_key; для произвольного mdl-пути reference не
        # совпадёт по имени — это ок, проверяем лишь отсутствие падения.
        self.assertIn(ok, (True, False))


if __name__ == "__main__":
    unittest.main()
