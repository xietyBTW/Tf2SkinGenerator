import os
import tempfile
import unittest

from src.data.material_maps import MATERIAL_MAPS, MAP_ORDER
from src.services.vmt_service import VMTService
from src.services.texture_service import TextureService
from PIL import Image


class MaterialMapsConfigTests(unittest.TestCase):
    def test_order_matches_keys(self):
        self.assertEqual(set(MAP_ORDER), set(MATERIAL_MAPS.keys()))

    def test_each_map_has_required_fields(self):
        for map_id, cfg in MATERIAL_MAPS.items():
            self.assertIn('format', cfg, map_id)
            self.assertIsInstance(cfg['extra_vmt'], dict, map_id)
            if cfg.get('vmt_only'):
                # Параметрическая карта (rim light) — без своей текстуры.
                self.assertIsNone(cfg.get('path_param'), map_id)
                continue
            self.assertIn('suffix', cfg, map_id)
            self.assertIn('path_param', cfg, map_id)
            self.assertTrue(cfg['path_param'].startswith('$'), map_id)

    def test_phong_uses_alpha_format(self):
        # phong-exp нельзя в DXT1 — альфа критична
        self.assertEqual(MATERIAL_MAPS['phongexp']['format'], 'DXT5')

    def test_detail_no_clamp_flags(self):
        # detail тайлится → без CLAMP
        self.assertNotIn('CLAMPS', MATERIAL_MAPS['detail']['flags'])
        self.assertNotIn('CLAMPT', MATERIAL_MAPS['detail']['flags'])

    def test_envmapmask_derive_and_envmap(self):
        cfg = MATERIAL_MAPS['envmapmask']
        self.assertEqual(cfg.get('derive_kind'), 'envmapmask')
        self.assertEqual(cfg['path_param'], '$envmapmask')
        self.assertIn('$envmap', cfg['extra_vmt'])  # маска без $envmap не работает

    def test_rimlight_is_vmt_only(self):
        cfg = MATERIAL_MAPS['rimlight']
        self.assertTrue(cfg.get('vmt_only'))
        self.assertIsNone(cfg.get('path_param'))
        self.assertEqual(cfg['extra_vmt'].get('$rimlight'), '1')
        self.assertEqual(cfg['extra_vmt'].get('$phong'), '1')  # rim требует phong


class SetVmtParamTests(unittest.TestCase):
    BASE = '"VertexLitGeneric"\n{\n\t"$basetexture" "path/tex"\n}\n'

    def test_insert(self):
        out = VMTService._set_vmt_param(self.BASE, "$detailscale", "8")
        self.assertIn('"$detailscale" "8"', out)
        self.assertLess(out.index("$detailscale"), out.rindex("}"))

    def test_update_idempotent(self):
        once = VMTService._set_vmt_param(self.BASE, "$detailscale", "8")
        twice = VMTService._set_vmt_param(once, "$detailscale", "12")
        self.assertEqual(twice.count("$detailscale"), 1)
        self.assertIn('"$detailscale" "12"', twice)


class AddMaterialMapParamsTests(unittest.TestCase):
    CDMAT = "vgui/replay/thumbnails/models/workshop_partner/weapons/c_models/"

    def _write(self, content):
        fd, path = tempfile.mkstemp(suffix=".vmt")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_writes_path_and_extra(self):
        path = self._write('"VertexLitGeneric"\n{\n\t"$basetexture" "t"\n}\n')
        try:
            changed = VMTService.add_material_map_params(
                path, self.CDMAT, "c_scattergun_detail", "$detail",
                {"$detailscale": "8", "$detailblendmode": "1"},
            )
            self.assertTrue(changed)
            out = self._read(path)
            self.assertIn('"$detail"', out)
            self.assertIn("c_scattergun_detail", out)
            self.assertIn('"$detailscale" "8"', out)
            self.assertIn('"$detailblendmode" "1"', out)
        finally:
            os.remove(path)

    def test_skips_unlit(self):
        original = '"UnlitGeneric"\n{\n\t"$basetexture" "t"\n}\n'
        path = self._write(original)
        try:
            changed = VMTService.add_material_map_params(
                path, self.CDMAT, "spray_detail", "$detail", {})
            self.assertFalse(changed)
            self.assertEqual(self._read(path), original)
        finally:
            os.remove(path)

    def test_idempotent(self):
        path = self._write('"VertexLitGeneric"\n{\n\t"$basetexture" "t"\n}\n')
        try:
            VMTService.add_material_map_params(path, self.CDMAT, "k_exp", "$phongexponenttexture", {"$phong": "1"})
            VMTService.add_material_map_params(path, self.CDMAT, "k_exp", "$phongexponenttexture", {"$phong": "1"})
            out = self._read(path)
            self.assertEqual(out.count('"$phongexponenttexture"'), 1)
            self.assertEqual(out.count('"$phong"'), 1)
        finally:
            os.remove(path)

    def test_missing_file_returns_false(self):
        self.assertFalse(
            VMTService.add_material_map_params("/no/file.vmt", self.CDMAT, "k", "$detail", {})
        )

    def test_path_param_none_writes_params_only(self):
        # rim light: path_param=None → пишем только параметры, без пути к текстуре.
        path = self._write('"VertexLitGeneric"\n{\n\t"$basetexture" "t"\n}\n')
        try:
            changed = VMTService.add_material_map_params(
                path, self.CDMAT, None, None,
                {"$phong": "1", "$rimlight": "1", "$rimlightexponent": "4"},
            )
            self.assertTrue(changed)
            out = self._read(path)
            self.assertIn('"$rimlight" "1"', out)
            self.assertIn('"$rimlightexponent" "4"', out)
            self.assertNotIn('$envmapmask', out)  # путь к текстуре не писался
        finally:
            os.remove(path)

    def test_result_valid(self):
        path = self._write('"VertexLitGeneric"\n{\n\t"$basetexture" "t"\n}\n')
        try:
            VMTService.add_material_map_params(
                path, self.CDMAT, "k_illum", "$selfillummask", {"$selfillum": "1"})
            ok, _, _ = VMTService.validate_vmt_syntax(self._read(path))
            self.assertTrue(ok)
        finally:
            os.remove(path)


class DeriveEffectMapTests(unittest.TestCase):
    def _base(self):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        # простая RGB-картинка с градиентом яркости
        img = Image.new("RGB", (32, 32))
        px = img.load()
        for y in range(32):
            for x in range(32):
                v = int(x / 31 * 255)
                px[x, y] = (v, v, v)
        img.save(path)
        return path

    def test_phong_map_has_alpha(self):
        base = self._base()
        out = base + ".phong.png"
        try:
            TextureService.derive_effect_map(base, out, "phong", (64, 64))
            with Image.open(out) as im:
                self.assertEqual(im.mode, "RGBA")   # альфа = маска блеска
                self.assertEqual(im.size, (64, 64))  # ресайз к нужному размеру
        finally:
            for p in (base, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_selfillum_map_is_grayscale(self):
        base = self._base()
        out = base + ".illum.png"
        try:
            TextureService.derive_effect_map(base, out, "selfillum", (64, 64))
            with Image.open(out) as im:
                self.assertEqual(im.mode, "L")
        finally:
            for p in (base, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_normal_with_alpha_bakes_mask(self):
        base = self._base()
        mask = base + ".mask.png"
        out = base + ".nrm.png"
        try:
            # маска = сплошной серый 200 → ожидаем её в альфе нормали
            Image.new("L", (16, 16), 200).save(mask)
            TextureService.make_normal_with_alpha(base, mask, out, (32, 32))
            with Image.open(out) as im:
                self.assertEqual(im.mode, "RGBA")
                self.assertEqual(im.size, (32, 32))
                alpha = im.getchannel("A")
                self.assertEqual(alpha.getextrema(), (200, 200))  # альфа = маска
        finally:
            for p in (base, mask, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_envmapmask_map_is_grayscale(self):
        base = self._base()
        out = base + ".envmask.png"
        try:
            TextureService.derive_effect_map(base, out, "envmapmask", (64, 64))
            with Image.open(out) as im:
                self.assertEqual(im.mode, "L")
                self.assertEqual(im.size, (64, 64))
        finally:
            for p in (base, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_threshold_binarizes(self):
        base = self._base()
        out = base + ".thr.png"
        try:
            TextureService.derive_effect_map(base, out, "selfillum", (64, 64), threshold=128)
            with Image.open(out) as im:
                colors = {p for p in im.getdata()}
                self.assertTrue(colors <= {0, 255})  # только чёрное/белое
        finally:
            for p in (base, out):
                if os.path.exists(p):
                    os.remove(p)


class DeriveConfigTests(unittest.TestCase):
    def test_phong_supports_derive_with_normal_and_envmap(self):
        cfg = MATERIAL_MAPS['phongexp']
        self.assertEqual(cfg.get('derive_kind'), 'phong')
        self.assertTrue(cfg.get('derive_auto_normal'))
        self.assertIn('$envmap', cfg.get('derive_extra_vmt', {}))

    def test_selfillum_supports_derive(self):
        self.assertEqual(MATERIAL_MAPS['selfillum'].get('derive_kind'), 'selfillum')

    def test_detail_has_no_derive(self):
        self.assertIsNone(MATERIAL_MAPS['detail'].get('derive_kind'))


if __name__ == "__main__":
    unittest.main()
