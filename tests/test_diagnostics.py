"""Тесты диагностики модов (чистый бэкенд, без Qt)."""

import struct
import tempfile
import unittest
from pathlib import Path

from src.services.diagnostics import build_inspected_mod, run_all_checks
from src.services.diagnostics.context import InspectedMod, parse_vmt
from src.services.diagnostics.mdl_reader import parse_mdl
from src.services.diagnostics.models import Severity
from src.services.diagnostics.vtf_reader import (
    parse_vtf_size, is_power_of_two,
)
from src.services.diagnostics import checks


def _codes(findings):
    return {f.code for f in findings}


# ── Бинарные читатели ────────────────────────────────────────────────────── #

class VtfReaderTests(unittest.TestCase):
    def test_parse_size(self):
        head = b"VTF\x00" + b"\x00" * 12 + struct.pack("<HH", 512, 256)
        self.assertEqual(parse_vtf_size(head), (512, 256))

    def test_bad_signature(self):
        self.assertIsNone(parse_vtf_size(b"XXXX" + b"\x00" * 16))
        self.assertIsNone(parse_vtf_size(b"VTF\x00short"))

    def test_power_of_two(self):
        for n in (1, 2, 512, 1024, 2048):
            self.assertTrue(is_power_of_two(n))
        for n in (0, 3, 1000, 513):
            self.assertFalse(is_power_of_two(n))


class MdlReaderTests(unittest.TestCase):
    def _synthetic_mdl(self, version=48, material="redgun",
                       cdmaterials="models/weapons/c_models"):
        buf = bytearray(0x200)
        buf[0:4] = b"IDST"
        struct.pack_into("<i", buf, 0x04, version)
        # 1 текстура, структура на 0x100
        struct.pack_into("<i", buf, 0xCC, 1)      # numtextures
        struct.pack_into("<i", buf, 0xD0, 0x100)  # textureindex
        struct.pack_into("<i", buf, 0xD4, 1)      # numcdtextures
        struct.pack_into("<i", buf, 0xD8, 0x150)  # cdtextureindex
        # mstudiotexture_t @0x100: sznameindex → имя на 0x140
        struct.pack_into("<i", buf, 0x100, 0x40)
        name_bytes = material.encode() + b"\x00"
        buf[0x140:0x140 + len(name_bytes)] = name_bytes
        # cd pointer array @0x150: 1 указатель → строка на 0x160
        struct.pack_into("<i", buf, 0x150, 0x160)
        cd_bytes = cdmaterials.encode() + b"\x00"
        buf[0x160:0x160 + len(cd_bytes)] = cd_bytes
        return bytes(buf)

    def test_parse_valid(self):
        hdr = parse_mdl(self._synthetic_mdl())
        self.assertTrue(hdr.valid)
        self.assertEqual(hdr.version, 48)
        self.assertEqual(hdr.material_names, ["redgun"])
        self.assertEqual(hdr.cdmaterials, ["models/weapons/c_models"])

    def test_parse_garbage_no_crash(self):
        hdr = parse_mdl(b"not a model at all")
        self.assertFalse(hdr.valid)
        self.assertEqual(hdr.material_names, [])


# ── Разбор VMT ───────────────────────────────────────────────────────────── #

class VmtParseTests(unittest.TestCase):
    def test_shader_and_texture_refs(self):
        vmt = parse_vmt("materials/x.vmt",
                        '"VertexLitGeneric"\n{\n\t"$baseTexture" "models/w/gun"\n'
                        '\t"$bumpmap" "models/w/gun_normal"\n'
                        '\t"$envmap" "env_cubemap"\n}')
        self.assertEqual(vmt.shader, "vertexlitgeneric")
        refs = vmt.texture_refs()
        self.assertEqual(refs["basetexture"], "materials/models/w/gun")
        self.assertEqual(refs["bumpmap"], "materials/models/w/gun_normal")
        self.assertNotIn("envmap", refs)   # env_cubemap — не файл

    def test_shared_game_textures_not_tracked(self):
        # Рескины ссылаются на общие игровые lightwarp/detail/phong и не везут их —
        # эти параметры не должны попадать в проверку «нет текстуры».
        vmt = parse_vmt("materials/x.vmt",
                        '"VertexLitGeneric"\n{\n'
                        '\t"$basetexture" "models/w/gun"\n'
                        '\t"$detail" "detail/metalwall"\n'
                        '\t"$lightwarptexture" "models/lightwarps/weapon_lightwarp"\n'
                        '\t"$phongexponenttexture" "models/w/gun_exp"\n}')
        refs = vmt.texture_refs()
        self.assertIn("basetexture", refs)
        self.assertNotIn("detail", refs)
        self.assertNotIn("lightwarptexture", refs)
        self.assertNotIn("phongexponenttexture", refs)


# ── Проверки (изолированно) ──────────────────────────────────────────────── #

class ChecksTests(unittest.TestCase):
    def _mod(self, **kw):
        return InspectedMod(root=Path("."), **kw)

    _VMT = '"VertexLitGeneric"\n{\n\t"$basetexture" "m/gun"\n}'

    def test_missing_texture_flagged(self):
        mod = self._mod(vmts=[parse_vmt("materials/m/gun.vmt", self._VMT)])  # нет VTF
        codes = _codes(checks.check_vmt_textures_exist(mod))
        self.assertIn("vmt.missing_texture", codes)

    def test_texture_present_not_flagged(self):
        mod = self._mod(vmts=[parse_vmt("materials/m/gun.vmt", self._VMT)],
                        vtf_rel={"materials/m/gun"})
        self.assertEqual(checks.check_vmt_textures_exist(mod), [])

    def test_missing_texture_deduped(self):
        # Одна и та же недостающая текстура в двух VMT → одна находка.
        a = parse_vmt("materials/a.vmt", self._VMT)
        b = parse_vmt("materials/b.vmt", self._VMT)
        mod = self._mod(vmts=[a, b])
        self.assertEqual(len(checks.check_vmt_textures_exist(mod)), 1)

    def test_vmt_syntax_error(self):
        vmt = parse_vmt("materials/bad.vmt", '"UnlitGeneric" { ')   # незакрытая скобка
        mod = self._mod(vmts=[vmt])
        codes = _codes(checks.check_vmt_syntax(mod))
        self.assertIn("vmt.syntax", codes)

    def test_vtf_not_power_of_two(self):
        mod = self._mod(vtf_sizes={"materials/m/x": (1000, 1000)})
        codes = _codes(checks.check_vtf_dimensions(mod))
        self.assertIn("vtf.not_power_of_two", codes)
        mod_ok = self._mod(vtf_sizes={"materials/m/x": (1024, 1024)})
        self.assertEqual(checks.check_vtf_dimensions(mod_ok), [])

    def test_wrapper_folder(self):
        mod = self._mod(all_rel={"mymod/materials/m/x.vmt", "mymod/models/y.mdl"})
        codes = _codes(checks.check_structure(mod))
        self.assertIn("structure.wrapper_folder", codes)

    def test_structure_ok(self):
        mod = self._mod(all_rel={"materials/m/x.vmt", "models/y.mdl"})
        codes = _codes(checks.check_structure(mod))
        self.assertNotIn("structure.wrapper_folder", codes)
        self.assertNotIn("structure.no_content", codes)

    def test_corrupt_vtf(self):
        mod = self._mod(bad_vtf={"materials/m/broken"})
        self.assertIn("vtf.corrupt", _codes(checks.check_vtf_corrupt(mod)))

    def test_conflicts(self):
        mod = self._mod(all_rel={"materials/m/x.vmt", "models/y.mdl"},
                        external_paths={"materials/m/x.vmt"})
        codes = _codes(checks.check_conflicts(mod))
        self.assertIn("conflict.overlap", codes)
        # нет пересечения → нет находки
        mod2 = self._mod(all_rel={"materials/m/x.vmt"}, external_paths={"models/z.mdl"})
        self.assertEqual(checks.check_conflicts(mod2), [])


# ── Интеграция: сборка из папки + прогон всех проверок ───────────────────── #

class BuildInspectedModTests(unittest.TestCase):
    def test_build_and_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mat = root / "materials" / "models" / "weapons"
            mat.mkdir(parents=True)
            (mat / "gun.vmt").write_text(
                '"VertexLitGeneric"\n{\n\t"$basetexture" "models/weapons/gun"\n}',
                encoding="utf-8")
            # VTF присутствует, размер степень двойки
            (mat / "gun.vtf").write_bytes(
                b"VTF\x00" + b"\x00" * 12 + struct.pack("<HH", 256, 256))

            mod = build_inspected_mod(root)
            self.assertEqual(len(mod.vmts), 1)
            self.assertIn("materials/models/weapons/gun", mod.vtf_rel)
            self.assertEqual(mod.vtf_sizes["materials/models/weapons/gun"], (256, 256))

            findings = run_all_checks(mod)
            # Здоровый мод → нет ошибок и нет предупреждений (только INFO-сводка).
            self.assertFalse([f for f in findings
                              if f.severity in (Severity.ERROR, Severity.WARNING)])
            self.assertIn("summary", _codes(findings))


if __name__ == "__main__":
    unittest.main()
