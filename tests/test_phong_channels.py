"""Phong-карта по каналам (skin_ps20b.fxc): R - размер блика, G - цвет блика
от текстуры ($phongalbedotint), A - маска обводки ($rimmask), и конструктор
градиента блика (phongwarp)

Настоящее сжатие VTF не зовём: create_vtf кладёт PNG под именем .vtf, rgba_from_vtf его читает
"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from src.data.material_maps import detect_maps, normalize_maps
from src.services import phongwarp, vmt_parse
from src.services.texture_build import map_textures
from src.services.vpk_texture_builder import VpkTextureBuilder


def fake_create_vtf(png, out_dir, fmt, flags, opts=None):
    Path(out_dir, Path(png).stem + '.vtf').write_bytes(Path(png).read_bytes())


def fake_rgba(data):
    if data == b'STOCK_EXP':
        arr = np.zeros((8, 8, 4), np.uint8)
        arr[..., 0] = 200                 # родной размер блика
        arr[:, :4, 1] = 255               # маска окраски Valve: левая половина
        arr[..., 3] = 255
        return arr
    with Image.open(io.BytesIO(data)) as img:
        return np.asarray(img.convert('RGBA')).copy()


BASE_VMT = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
            '\t"$phong" "1"\n\t"$phongexponent" "25"\n%s}\n')


class PhongChannelsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = self.tmp / 'base.png'
        img = Image.new('RGB', (16, 16), (30, 30, 30))
        img.paste((240, 240, 240), (0, 0, 8, 16))
        img.save(self.base)
        self.vmt = self.tmp / 'm9.vmt'

    def build(self, extra_lines, maps, read=None):
        self.vmt.write_text(BASE_VMT % extra_lines, encoding='utf-8')
        with mock.patch('src.services.texture_service.TextureService.create_vtf',
                        side_effect=fake_create_vtf), \
             mock.patch('src.services.normal_map.rgba_from_vtf', side_effect=fake_rgba):
            result = VpkTextureBuilder._apply_maps_for_material(
                normalize_maps(maps), 'm9', self.vmt, str(self.base), self.tmp,
                'models/w', (16, 16), read_texture=read)
        return vmt_parse.parse(self.vmt.read_text(encoding='utf-8')), result

    def exp(self):
        return fake_rgba((self.tmp / 'm9_exp.vtf').read_bytes())

    def test_own_phong_map_drops_phongexponent(self):
        # $phongexponent > 0 перекрывает красный канал (skin_dx9_helper.cpp)
        doc, _ = self.build('', {'phongexp': {'image': str(self.base)}})
        self.assertIsNone(doc.get('$phongexponent'))
        self.assertEqual(doc.path('$phongexponenttexture'), 'models/w/m9_exp')

    def test_albedo_tint_writes_green_channel(self):
        doc, result = self.build('\t"$phongtint" "[1 0 0]"\n',
                                 {'phongcolor': {'enabled': True, 'tint': 'albedo',
                                                 'tint_amount': '60'}})
        self.assertTrue(doc.flag('$phongalbedotint'))
        self.assertIsNone(doc.get('$phongtint'))               # он отключил бы окраску
        self.assertEqual(doc.path('$phongexponenttexture'), 'models/w/m9_exp')
        self.assertEqual(doc.get('$phongexponent'), '25')      # размер блика прежний
        self.assertEqual(int(self.exp()[0, 0, 1]), 153)        # 60 % в зелёном
        self.assertTrue(result['exp_extra'])

    def test_own_colour_is_phongtint(self):
        doc, _ = self.build('\t"$phongalbedotint" "1"\n',
                            {'phongcolor': {'enabled': True, 'tint': 'color',
                                            'tint_color': '#ff8000'}})
        self.assertEqual(doc.get('$phongtint'), '[1.000 0.502 0.000]')
        self.assertIsNone(doc.get('$phongalbedotint'))
        self.assertFalse((self.tmp / 'm9_exp.vtf').exists())   # текстура не нужна

    def test_rim_mask_goes_into_alpha_of_stock_phong_map(self):
        doc, _ = self.build('\t"$phongexponenttexture" "models/w/m9_stock_exp"\n',
                            {'rimlight': {'enabled': True, 'rim_mask': 'auto',
                                          'rim_threshold': '128'}},
                            read=lambda p: b'STOCK_EXP' if p == 'models/w/m9_stock_exp' else None)
        self.assertTrue(doc.flag('$rimmask'))
        self.assertEqual(doc.path('$phongexponenttexture'), 'models/w/m9_exp')
        exp = self.exp()
        self.assertEqual(int(exp[0, 0, 0]), 200)               # родной R цел
        self.assertEqual((int(exp[0, 0, 3]), int(exp[0, -1, 3])), (255, 0))

    def test_rim_everywhere_drops_stock_mask_but_old_entry_keeps_it(self):
        doc, _ = self.build('\t"$rimmask" "1"\n',
                            {'rimlight': {'enabled': True, 'rim_mask': 'all'}})
        self.assertIsNone(doc.get('$rimmask'))
        doc, _ = self.build('\t"$rimmask" "1"\n', {'rimlight': {'enabled': True}})
        self.assertTrue(doc.flag('$rimmask'))                  # работа до маски

    def test_new_phong_map_from_exponent(self):
        # Ни своей, ни родной Phong-карты: R из $phongexponent (1 + 149·R)
        self.build('', {'phongcolor': {'enabled': True, 'tint': 'albedo'}})
        self.assertEqual(int(self.exp()[0, 0, 0]), round((25 - 1) / 149 * 255))

    def test_blue_follows_red_phong_map(self):
        _, red = self.build('', {'phongcolor': {'enabled': True, 'tint': 'albedo'}})
        blue = self.tmp / 'm9_blue.vmt'
        blue.write_text(BASE_VMT % '', encoding='utf-8')
        VpkTextureBuilder._apply_maps_for_material(
            normalize_maps({'phongcolor': {'enabled': True, 'tint': 'albedo'}}), 'm9', blue,
            str(self.base), self.tmp, 'models/w', (16, 16), params_only=True, red=red)
        doc = vmt_parse.parse(blue.read_text(encoding='utf-8'))
        self.assertEqual(doc.path('$phongexponenttexture'), 'models/w/m9_exp')
        self.assertTrue(doc.flag('$phongalbedotint'))


class ReviewFixesTests(PhongChannelsTests):
    """Случаи, что нашло ревью: каждый ломал материал молча"""

    def test_removing_mod_highlight_colour_leaves_rim_alone(self):
        from src.services.vmt_service import VMTService
        self.vmt.write_text(BASE_VMT % '\t"$phongtint" "[1 .5 0]"\n\t"$rimlight" "1"\n',
                            encoding='utf-8')
        VMTService.remove_material_map(str(self.vmt), 'phongcolor')
        doc = vmt_parse.parse(self.vmt.read_text(encoding='utf-8'))
        self.assertIsNone(doc.get('$phongtint'))
        self.assertTrue(doc.flag('$rimlight'))

    def test_blue_gets_colour_when_red_has_own_phong_map(self):
        maps = {'phongexp': {'image': str(self.base)},
                'phongcolor': {'enabled': True, 'tint': 'albedo'}}
        _, red = self.build('', maps)
        blue = self.tmp / 'm9_blue.vmt'
        blue.write_text(BASE_VMT % '', encoding='utf-8')
        with mock.patch('src.services.texture_service.TextureService.create_vtf',
                        side_effect=fake_create_vtf):
            VpkTextureBuilder._apply_maps_for_material(
                normalize_maps(maps), 'm9', blue, str(self.base), self.tmp, 'models/w',
                (16, 16), params_only=True, red=red)
        doc = vmt_parse.parse(blue.read_text(encoding='utf-8'))
        self.assertTrue(doc.flag('$phongalbedotint'))
        self.assertEqual(doc.path('$phongexponenttexture'), 'models/w/m9_exp')

    def test_missing_rim_file_keeps_colour_and_stock_mask(self):
        doc, _ = self.build('\t"$rimmask" "1"\n',
                            {'phongcolor': {'enabled': True, 'tint': 'albedo'},
                             'rimlight': {'enabled': True, 'rim_mask': 'file'}})
        self.assertTrue(doc.flag('$phongalbedotint'))
        self.assertTrue(doc.flag('$rimmask'))                 # родная маска цела

    def test_failed_phong_map_keeps_stock_tint(self):
        with mock.patch.object(map_textures, 'compose_exponent', return_value=False):
            doc, _ = self.build('\t"$phongtint" "[1 0 0]"\n',
                                {'phongcolor': {'enabled': True, 'tint': 'albedo'}})
        self.assertEqual(doc.get('$phongtint'), '[1 0 0]')
        self.assertIsNone(doc.get('$phongalbedotint'))

    def test_stock_albedo_mask_is_scaled_not_flooded(self):
        self.build('\t"$phongexponenttexture" "models/w/m9_stock_exp"\n'
                   '\t"$phongalbedotint" "1"\n',
                   {'phongcolor': {'enabled': True, 'tint': 'albedo', 'tint_amount': '50'}},
                   read=lambda p: b'STOCK_EXP' if p == 'models/w/m9_stock_exp' else None)
        exp = self.exp()
        self.assertEqual((int(exp[0, 0, 1]), int(exp[0, -1, 1])), (128, 0))

    def test_foreign_phong_file_is_not_revived(self):
        # {mat}_exp из мода, с которого карту сняли, - не основа
        (self.tmp / 'm9_exp.vtf').write_bytes(b'STOCK_EXP')
        self.build('', {'phongcolor': {'enabled': True, 'tint': 'albedo'}})
        self.assertEqual(int(self.exp()[0, 0, 0]), round((25 - 1) / 149 * 255))


class DetectAndNormalizeTests(unittest.TestCase):
    def test_mod_highlight_colour_is_detected(self):
        found = detect_maps('"VertexLitGeneric" { "$phongtint" "[1 .5 0]" }')
        self.assertEqual(found['phongcolor']['tint'], 'color')
        self.assertEqual(found['phongcolor']['tint_color'], '#ff8000')
        found = detect_maps('"VertexLitGeneric" { "$phongalbedotint" "1" }')
        self.assertEqual(found['phongcolor']['tint'], 'albedo')

    def test_settings_are_validated(self):
        got = normalize_maps({'rimlight': {'enabled': True, 'rim_mask': 'nope',
                                           'rim_threshold': '999', 'rim_image': 'C:/нет.png'},
                              'phongcolor': {'enabled': True, 'tint_color': 'red',
                                             'tint_amount': '-5'}})
        self.assertEqual(got['rimlight'], {'enabled': True, 'rim_threshold': '255'})
        self.assertEqual(got['phongcolor'], {'enabled': True, 'tint_amount': '0'})


class PhongwarpTests(unittest.TestCase):
    def test_png_and_generate_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = phongwarp.write_png({'preset': 'oil'}, str(Path(tmp) / 'w.png'))
            with Image.open(png) as img:
                self.assertEqual((img.size, img.mode), ((256, 256), 'RGB'))
            got = normalize_maps({'phongwarp': {'image': png,
                                                'generate': {'preset': 'gold', 'x': 1}}})
        self.assertEqual(got['phongwarp']['generate']['preset'], 'gold')
        self.assertNotIn('x', got['phongwarp']['generate'])

    def test_strength_zero_keeps_highlight_white(self):
        self.assertEqual(int(phongwarp.image({'preset': 'rainbow', 'strength': 0}).min()), 255)

    def test_angle_and_edge_row(self):
        red_blue = [[0, '#ff0000'], [1, '#0000ff']]
        down = phongwarp.image({'preset': 'custom', 'stops': red_blue, 'angle': 90})
        self.assertEqual(tuple(down[0, 10]), (255, 0, 0))     # 90° - сверху вниз
        self.assertEqual(tuple(down[-1, 10]), (0, 0, 255))
        two = phongwarp.image({'preset': 'custom', 'stops': [[0, '#ffffff'], [1, '#ffffff']],
                               'edge_row': True,
                               'edge_stops': [[0, '#00ff00'], [1, '#00ff00']]})
        self.assertEqual(tuple(two[0, 5]), (255, 255, 255))   # верх - первый ряд
        self.assertEqual(tuple(two[-1, 5]), (0, 255, 0))      # низ - край модели
        self.assertEqual(phongwarp.clean_params({'angle': -90})['angle'], 270)

    def test_rows_are_fresnel(self):
        # Строка - френель: цвет края модели внизу, у зрителя вверху его нет
        img = phongwarp.image({'preset': 'custom', 'stops': [[0, '#ffffff'], [1, '#ffffff']],
                               'edge': 100, 'edge_color': '#00ff00'})
        self.assertEqual(tuple(img[-1, 200]), (0, 255, 0))
        self.assertEqual(tuple(img[0, 200]), (255, 255, 255))


if __name__ == '__main__':
    unittest.main()
