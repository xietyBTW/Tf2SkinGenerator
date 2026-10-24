"""Карты материала так, как их читает движок (вики Valve + материалы TF2)

Настоящее сжатие VTF в тестах не зовём: create_vtf кладёт PNG под именем .vtf, а
rgba_from_vtf его читает - так видно, что именно ушло бы в текстуру
"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from src.data.material_maps import detect_maps, normalize_maps
from src.services import vmt_parse
from src.services.vpk_texture_builder import VpkTextureBuilder

STOCK_RGB = (10, 200, 250)          # «родная» нормаль игры


def fake_create_vtf(png, out_dir, fmt, flags, opts=None):
    Path(out_dir, Path(png).stem + '.vtf').write_bytes(Path(png).read_bytes())


def fake_rgba(data):
    if data == b'STOCK':
        arr = np.zeros((8, 8, 4), np.uint8)
        arr[..., :3] = STOCK_RGB
        arr[..., 3] = 77
        return arr
    with Image.open(io.BytesIO(data)) as img:
        return np.asarray(img.convert('RGBA')).copy()


class EngineMapsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = self.tmp / 'base.png'
        img = Image.new('RGB', (16, 16), (40, 40, 40))
        img.paste((230, 230, 230), (0, 0, 8, 16))          # левая половина светлая
        img.save(self.base)
        self.vmt = self.tmp / 'm9.vmt'

    def build(self, vmt_text, maps, read=None, params_only=False):
        self.vmt.write_text(vmt_text, encoding='utf-8')
        with mock.patch('src.services.texture_service.TextureService.create_vtf',
                        side_effect=fake_create_vtf), \
             mock.patch('src.services.normal_map.rgba_from_vtf', side_effect=fake_rgba):
            VpkTextureBuilder._apply_maps_for_material(
                normalize_maps(maps), 'm9', self.vmt, str(self.base), self.tmp,
                'models/w', (16, 16), params_only=params_only, read_texture=read)
        return self.vmt.read_text(encoding='utf-8')

    def normal(self):
        return fake_rgba((self.tmp / 'm9_normal.vtf').read_bytes())

    def test_envmask_goes_into_alpha_of_stock_normal(self):
        text = self.build(
            '"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
            '\t"$bumpmap" "models/w/m9_stock"\n\t"$phong" "1"\n'
            '\t"$basemapalphaphongmask" "1"\n}\n',
            {'envmapmask': {'derive': True, 'threshold': '128'}},
            read=lambda path: b'STOCK' if path == 'models/w/m9_stock' else None)
        doc = vmt_parse.parse(text)
        self.assertEqual(doc.path('$bumpmap'), 'models/w/m9_normal')
        self.assertTrue(doc.flag('$normalmapalphaenvmapmask'))
        self.assertIsNone(doc.get('$envmapmask'))            # нерабочий не пишем
        self.assertIsNone(doc.get('$basemapalphaphongmask'))
        n = self.normal()
        self.assertEqual(tuple(n[0, 0, :3]), STOCK_RGB)       # рельеф игры цел
        self.assertEqual(int(n[0, 0, 3]), 255)                # светлое - блестит
        self.assertEqual(int(n[0, -1, 3]), 0)            # размер - как у родной

    def test_auto_gloss_mask_lives_in_normal_alpha(self):
        text = self.build('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n}\n',
                          {'phongexp': {'derive': True, 'threshold': '128'}})
        doc = vmt_parse.parse(text)
        self.assertEqual(doc.path('$bumpmap'), 'models/w/m9_normal')
        self.assertEqual(doc.get('$phongfresnelranges'), '[0 0.5 1]')
        n = self.normal()
        self.assertEqual((int(n[0, 0, 3]), int(n[0, 15, 3])), (255, 0))
        exp = fake_rgba((self.tmp / 'm9_exp.vtf').read_bytes())
        self.assertEqual(int(exp[..., 3].min()), 255)         # альфа exp - rim, не блеск

    def test_material_fresnel_ranges_are_kept(self):
        text = self.build('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
                          '\t"$phongfresnelranges" "[1.5 .5 3]"\n}\n',
                          {'rimlight': {'enabled': True}})
        self.assertEqual(vmt_parse.parse(text).get('$phongfresnelranges'), '[1.5 .5 3]')

    def test_detail_releases_burning_proxies(self):
        vmt = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
               '\t"$detail" "effects/tiledfire/fireLayeredSlowTiled512"\n'
               '\t"$detailblendmode" "6"\n\t"proxies"\n\t{\n'
               '\t\t"AnimatedTexture"\n\t\t{\n\t\t\t"animatedtexturevar" "$basetexture"\n'
               '\t\t\t"animatedtextureframerate" "10"\n\t\t}\n'
               '\t\t"AnimatedTexture"\n\t\t{\n\t\t\t"animatedtexturevar" "$detail"\n'
               '\t\t\t"animatedtextureframenumvar" "$detailframe"\n\t\t}\n'
               '\t\t"BurnLevel"\n\t\t{\n\t\t\t"resultVar" "$detailblendfactor"\n\t\t}\n'
               '\t}\n}\n')
        img = self.tmp / 'grain.png'
        Image.new('RGB', (8, 8), (128, 128, 128)).save(img)
        text = self.build(vmt, {'detail': {'image': str(img)}})
        doc = vmt_parse.parse(text)
        self.assertEqual(doc.path('$detail'), 'models/w/m9_detail')
        self.assertEqual(doc.get('$detailblendmode'), '0')
        proxies = doc.block('proxies')
        self.assertIsNone(proxies.block('BurnLevel'))
        self.assertEqual(len(proxies.blocks['animatedtexture']), 1)
        self.assertEqual(proxies.block('AnimatedTexture').get('animatedtexturevar'),
                         '$basetexture')

    def test_animated_normal_is_left_alone(self):
        # Гифка + Normal Map: многокадровый рельеф. Маска заморозила бы его
        animated = bytearray(b'VTF\0' + bytes(22))
        animated[24:26] = (12).to_bytes(2, 'little')
        (self.tmp / 'm9_normal.vtf').write_bytes(bytes(animated))
        text = self.build('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
                          '\t"$phong" "1"\n}\n', {'envmapmask': {'derive': True}})
        self.assertEqual((self.tmp / 'm9_normal.vtf').read_bytes(), bytes(animated))
        self.assertIsNone(vmt_parse.parse(text).get('$normalmapalphaenvmapmask'))

    def test_blue_keeps_its_own_normal(self):
        red = {'mask': True, 'bump': 'models/w/m9_stock'}
        blue = self.tmp / 'm9_blue.vmt'
        blue.write_text('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9_blue"\n'
                        '\t"$bumpmap" "models/w/m9_blue_normal"\n\t"$phong" "1"\n}\n',
                        encoding='utf-8')
        (self.tmp / 'm9_normal.vtf').write_bytes(b'x')
        VpkTextureBuilder._apply_maps_for_material(
            normalize_maps({'envmapmask': {'derive': True}}), 'm9', blue, str(self.base),
            self.tmp, 'models/w', (16, 16), params_only=True, red=red)
        doc = vmt_parse.parse(blue.read_text(encoding='utf-8'))
        self.assertEqual(doc.path('$bumpmap'), 'models/w/m9_blue_normal')
        self.assertIsNone(doc.get('$envmapmask'))

    def test_blue_follows_only_successful_red(self):
        blue = self.tmp / 'm9_blue.vmt'
        blue.write_text('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9_blue"\n'
                        '\t"$phong" "1"\n\t"$basemapalphaphongmask" "1"\n}\n',
                        encoding='utf-8')
        (self.tmp / 'm9_normal.vtf').write_bytes(b'x')
        VpkTextureBuilder._apply_maps_for_material(
            normalize_maps({'envmapmask': {'derive': True}}), 'm9', blue, str(self.base),
            self.tmp, 'models/w', (16, 16), params_only=True, red={'mask': False, 'bump': None})
        doc = vmt_parse.parse(blue.read_text(encoding='utf-8'))
        self.assertIsNone(doc.get('$normalmapalphaenvmapmask'))
        self.assertTrue(doc.flag('$basemapalphaphongmask'))

    def test_one_line_burn_proxy_and_glow_without_phong(self):
        vmt = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
               '\t"$bumpmap" "models/w/m9_n"\n\t"proxies"\n\t{\n'
               '\t\t"BurnLevel" { "resultVar" "$detailblendfactor" }\n\t}\n}\n')
        img = self.tmp / 'grain.png'
        Image.new('RGB', (8, 8), (128, 128, 128)).save(img)
        text = self.build(vmt, {'detail': {'image': str(img), '$detailblendmode': '5'}})
        doc = vmt_parse.parse(text)
        self.assertIsNone(doc.block('proxies').block('BurnLevel'))
        self.assertEqual(doc.get('$detailblendmode'), '1')     # 5 без $phong не рисуется

    def test_fire_stays_when_detail_texture_failed(self):
        vmt = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n\t"proxies"\n\t{\n'
               '\t\t"BurnLevel"\n\t\t{\n\t\t\t"resultVar" "$detailblendfactor"\n\t\t}\n\t}\n}\n')
        img = self.tmp / 'grain.png'
        Image.new('RGB', (8, 8), (128, 128, 128)).save(img)
        self.vmt.write_text(vmt, encoding='utf-8')
        with mock.patch('src.services.texture_service.TextureService.create_vtf'):
            VpkTextureBuilder._apply_maps_for_material(
                normalize_maps({'detail': {'image': str(img)}}), 'm9', self.vmt,
                str(self.base), self.tmp, 'models/w', (16, 16))
        doc = vmt_parse.parse(self.vmt.read_text(encoding='utf-8'))
        self.assertIsNotNone(doc.block('proxies').block('BurnLevel'))
        self.assertIsNone(doc.get('$detail'))

    def test_unsupported_blend_mode_falls_back(self):
        # 7 с $bumpmap не рисуется вовсе
        got = normalize_maps({'detail': {'derive': False, 'image': str(self.base),
                                         '$detailblendmode': '7'}})
        self.assertNotIn('$detailblendmode', got['detail'])

    def test_rimlight_zero_point_zero_is_off(self):
        self.assertNotIn('rimlight', detect_maps('"VertexLitGeneric" { "$rimlight" "0.0" }'))


if __name__ == '__main__':
    unittest.main()
