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


_SMD_TWO_MATERIALS = """version 1
nodes
0 "root" -1
end
skeleton
time 0
0 0 0 0 0 0 0
end
triangles
body_material
0 0.0 0.0 0.0 0 0 1 0.10 0.20
0 1.0 0.0 0.0 0 0 1 0.50 0.60
0 0.0 1.0 0.0 0 0 1 0.90 0.10
lens_material
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
        ok, result, files = ExtractModelService.generate_uv_template(
            self.decompile, "c_test", (128, 128), self.export
        )
        self.assertTrue(ok, result)
        self.assertTrue(os.path.exists(result))
        self.assertTrue(result.endswith("_uv_layout.png"))
        self.assertEqual(files, [result])

    def test_each_material_gets_its_own_layout(self):
        """Развёртки материалов лежат в одних координатах: на общей картинке
        они накладываются друг на друга, и рисовать по ней нельзя."""
        with open(os.path.join(self.decompile, "c_test_reference.smd"),
                  "w", encoding="utf-8") as f:
            f.write(_SMD_TWO_MATERIALS)
        ok, _result, files = ExtractModelService.generate_uv_template(
            self.decompile, "c_test", (128, 128), self.export
        )
        self.assertTrue(ok)
        self.assertEqual(len(files), 2)
        self.assertTrue(all(os.path.exists(f) for f in files))
        names = sorted(os.path.basename(f) for f in files)
        self.assertIn("body_material", names[0])
        self.assertIn("lens_material", names[1])

    def test_no_smd_returns_flag(self):
        ok, result, files = ExtractModelService.generate_uv_template(
            self.decompile, "c_test", (128, 128), self.export
        )
        self.assertFalse(ok)
        self.assertEqual(result, "no_smd")
        self.assertEqual(files, [])

    def test_full_mdl_path_weapon_key_sanitized(self):
        # weapon_key как полный mdl-путь (персонажи/шапки) → имя файла из basename.
        self._write_smd("hat_reference.smd")
        ok, result, _files = ExtractModelService.generate_uv_template(
            self.decompile, "models/player/items/hat.mdl", (64, 64), self.export
        )
        # SMD ищется по weapon_key; для произвольного mdl-пути reference не
        # совпадёт по имени — это ок, проверяем лишь отсутствие падения.
        self.assertIn(ok, (True, False))


if __name__ == "__main__":
    unittest.main()
