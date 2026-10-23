"""Карты материала у мода из VPK: что служебное, что распознано, что снимается,
и конструктор полоски lightwarp"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from src.data.material_maps import detect_maps, normalize_maps
from src.services import lightwarp
from src.services.mod_textures import is_base_vtf, is_service_name, vmt_references
from src.services.vmt_service import VMTService

VMT = '''"VertexLitGeneric"
{
\t"$basetexture" "models/w/m9"
\t"$phongexponenttexture" "models/w/m9_exp"
\t"$detail" "models/w/grain"
\t"$detailscale" "4"
\t"$lightwarptexture" "models/lightwarps/weapon_lightwarp"
\t"$rimlight" "1"
\t"$rimlightboost" "3"
//\t"$selfillummask" "models/w/m9_illum"
\t"$envmap" "env_cubemap"
}
'''


class ServiceTextureTests(unittest.TestCase):
    def test_our_generated_maps_are_service(self):
        for stem in ('m9_exp', 'm9_illum', 'm9_envmask', 'm9_normal', 'm9_detail',
                     'm9_lightwarp', 'm9_phongwarp', 'm9_exp_blue'):
            self.assertTrue(is_service_name(f'materials/x/{stem}.vtf'), stem)

    def test_mask_word_inside_name_is_not_service(self):
        # Старый фильтр искал «mask» где угодно и прятал маску шпиона
        self.assertFalse(is_service_name('materials/models/player/spy/mask_scout.vtf'))
        self.assertFalse(is_service_name('materials/models/x/spectre_gun.vtf'))

    def test_vmt_decides_before_name(self):
        refs = vmt_references([VMT])
        self.assertTrue(is_base_vtf('materials/models/w/m9.vtf', refs))
        # «grain» по имени основная, но VMT кладёт её в $detail
        self.assertFalse(is_base_vtf('materials/models/w/grain.vtf', refs))
        self.assertFalse(is_base_vtf('materials/models/w/m9_exp.vtf', refs))

    def test_basetexture_wins_over_service_reference(self):
        other = '"VertexLitGeneric" { "$basetexture" "models/w/grain" }'
        refs = vmt_references([VMT, other])
        self.assertTrue(is_base_vtf('materials/models/w/grain.vtf', refs))


class DetectMapsTests(unittest.TestCase):
    def test_detects_live_maps_with_numbers(self):
        found = detect_maps(VMT)
        self.assertEqual(found['phongexp'], {'mod': True, 'texture': 'models/w/m9_exp'})
        self.assertEqual(found['detail']['$detailscale'], '4')
        self.assertEqual(found['lightwarp']['texture'], 'models/lightwarps/weapon_lightwarp')
        self.assertEqual(found['rimlight'], {'enabled': True, 'mod': True,
                                             '$rimlightboost': '3'})
        self.assertNotIn('selfillum', found)        # только в комментарии
        self.assertNotIn('envmapmask', found)

    def test_normalize_keeps_mod_entry(self):
        self.assertEqual(normalize_maps({'detail': {'mod': True, 'preview': 'x',
                                                    '$detailscale': '6'}}),
                         {'detail': {'mod': True, '$detailscale': '6'}})

    def test_normalize_keeps_off_marker(self):
        self.assertEqual(normalize_maps({'rimlight': {'off': True, 'enabled': True}}),
                         {'rimlight': {'off': True}})

    def test_normalize_keeps_generator_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / 'lw.png'
            png.write_bytes(b'x')
            got = normalize_maps({'lightwarp': {'image': str(png),
                                                'generate': {'steps': 3, 'junk': 1}}})
        self.assertEqual(got['lightwarp']['generate']['steps'], 3)
        self.assertNotIn('junk', got['lightwarp']['generate'])


class RemoveMapTests(unittest.TestCase):
    def test_removes_path_line_and_disables_rim(self):
        with tempfile.TemporaryDirectory() as tmp:
            vmt = Path(tmp) / 'm9.vmt'
            vmt.write_text(VMT, encoding='utf-8')
            self.assertTrue(VMTService.remove_material_map(str(vmt), 'lightwarp'))
            self.assertTrue(VMTService.remove_material_map(str(vmt), 'rimlight'))
            found = detect_maps(vmt.read_text(encoding='utf-8'))
        self.assertNotIn('lightwarp', found)
        self.assertNotIn('rimlight', found)
        self.assertIn('phongexp', found)


class ModBuildMapsTests(unittest.TestCase):
    """Сборка мода: запись карт против карт, что уже стоят в VMT"""

    BLUE = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9_blue"\n'
            '\t"$detail" "models/w/grain"\n\t"$selfillummask" "models/w/blue_glow"\n}\n')

    def run_build(self, record, other_vmt=None):
        from src.services.custom_vpk_service import CustomVPKService
        tmp = tempfile.mkdtemp()
        root = Path(tmp) / 'vpkroot'
        folder = root / 'materials' / 'models' / 'w'
        folder.mkdir(parents=True)
        (folder / 'm9.vtf').write_bytes(b'v')
        (folder / 'grain.vtf').write_bytes(b'd')          # текстура $detail
        (folder / 'm9.vmt').write_text(VMT, encoding='utf-8')
        if other_vmt:
            (folder / 'other.vmt').write_text(other_vmt, encoding='utf-8')
        self.folder = folder
        textures = [{'name': 'm9', 'vtf_name': 'm9', 'vtf_path': str(folder / 'm9.vtf'),
                     'vmt_path': str(folder / 'm9.vmt'), 'vmt_dir': str(folder)}]
        if self.with_blue:
            (folder / 'm9_blue.vtf').write_bytes(b'v')
            (folder / 'm9_blue.vmt').write_text(self.BLUE, encoding='utf-8')
            textures.append({'name': 'm9_blue', 'vtf_name': 'm9_blue',
                             'vtf_path': str(folder / 'm9_blue.vtf'),
                             'vmt_path': str(folder / 'm9_blue.vmt'), 'vmt_dir': str(folder)})
        maps = {} if record is None else {'m9': record}
        with mock.patch('src.services.normal_map.rgba_from_vtf',
                        return_value=np.zeros((4, 4, 4), np.uint8)):
            CustomVPKService._apply_material_extras(
                textures, {}, maps, lambda t: ((64, 64), 'DXT5', [], {}),
                root, Path(tmp), 'ru')
        return (folder / 'm9.vmt').read_text(encoding='utf-8')

    with_blue = False

    def test_untouched_material_keeps_mod_vmt(self):
        self.assertEqual(self.run_build(None), VMT)

    def test_kept_and_dropped_maps(self):
        text = self.run_build({'phongexp': {'mod': True},
                               'detail': {'mod': True, '$detailscale': '9'},
                               'rimlight': {'off': True}})
        found = detect_maps(text)
        # Без записи (lightwarp) - как в моде; off - снят
        self.assertEqual(set(found), {'phongexp', 'detail', 'lightwarp'})
        self.assertEqual(found['detail']['$detailscale'], '9')
        self.assertTrue((self.folder / 'grain.vtf').exists())

    def test_dropped_map_texture_leaves_the_mod(self):
        text = self.run_build({'detail': {'off': True}})
        self.assertNotIn('detail', detect_maps(text))
        self.assertFalse((self.folder / 'grain.vtf').exists())

    def test_texture_still_used_in_quality_block_stays(self):
        other = '"VertexLitGeneric"\n{\n\t">=dx90"\n\t{\n\t\t"$detail" "models/w/grain"\n\t}\n}\n'
        self.run_build({'detail': {'off': True}}, other_vmt=other)
        self.assertTrue((self.folder / 'grain.vtf').exists())

    def test_blue_loses_only_what_was_turned_off(self):
        self.with_blue = True
        self.run_build({'detail': {'off': True}})
        blue = detect_maps((self.folder / 'm9_blue.vmt').read_text(encoding='utf-8'))
        self.assertEqual(set(blue), {'selfillum'})      # своё у синего осталось


class VmtEditTests(unittest.TestCase):
    def write(self, text, encoding='utf-8'):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / 'a.vmt'
        path.write_bytes(text.encode(encoding))
        return path

    def test_unquoted_value_is_replaced_not_duplicated(self):
        path = self.write('"VertexLitGeneric"\n{\n\t$rimlight 1\n\t$rimlightboost 3\n}\n')
        VMTService.add_material_map_params(str(path), '', None, None, {'$rimlightboost': '5'})
        VMTService.remove_material_map(str(path), 'rimlight')
        text = path.read_text(encoding='utf-8')
        self.assertEqual(text.lower().count('$rimlightboost'), 1)
        self.assertIn('"5"', text)
        self.assertNotIn('rimlight', detect_maps(text))

    def test_cp1251_comment_and_bom_survive(self):
        body = '﻿// мод\n"VertexLitGeneric"\n{\n\t"$detail" "a/b"\n}\n'
        path = self.write(body)
        self.assertTrue(VMTService.add_material_map_params(
            str(path), '', None, None, {'$detailscale': '2'}))
        raw = '// \xe9\xee\xe4\n"VertexLitGeneric"\n{\n\t"$detail" "a/b"\n}\n'
        path = self.write(raw, 'latin-1')                # байты cp1251
        self.assertTrue(VMTService.remove_material_map(str(path), 'detail'))
        self.assertTrue(path.read_bytes().startswith(b'// \xe9\xee\xe4\n'))


class LightwarpTests(unittest.TestCase):
    def test_steps_and_tint_without_game(self):
        flat = lightwarp.ramp({'preset': 'neutral', 'steps': 4})
        self.assertEqual(flat.shape, (lightwarp.WIDTH, 3))
        self.assertEqual(len({tuple(px) for px in flat}), 4)
        warm = lightwarp.ramp({'preset': 'neutral', 'light': 100, 'light_color': '#ff8000'})
        self.assertGreater(warm[230, 0], warm[230, 2])

    def test_neutral_fallback_is_half_brightness(self):
        # Игра: результат = 2 · полоска, значит «как без lightwarp» на свету - 128
        self.assertEqual(int(lightwarp.ramp({'preset': 'neutral'})[-1, 0]), 128)

    def test_custom_stops_and_round_trip(self):
        own = lightwarp.ramp({'preset': 'custom', 'stops': [[0, '#ff0000'], [1, '#0000ff']]})
        self.assertEqual(tuple(own[0]), (255, 0, 0))
        self.assertEqual(tuple(own[-1]), (0, 0, 255))
        # Резкая ступень, как у weapon_lightwarp, переживает «Сделать точками»
        step = lightwarp.ramp({'preset': 'custom', 'stops': [
            [0, '#1f1f1f'], [0.6, '#1f1f1f'], [0.6, '#808080'], [1, '#808080']]})
        again = lightwarp.ramp({'preset': 'custom', 'stops': lightwarp.to_stops(step)})
        self.assertLessEqual(int(np.abs(again.astype(int) - step.astype(int)).max()), 3)

    def test_tints_do_not_apply_to_own_gradient(self):
        stops = [[0, '#202020'], [1, '#808080']]
        plain = lightwarp.ramp({'preset': 'custom', 'stops': stops})
        tinted = lightwarp.ramp({'preset': 'custom', 'stops': stops, 'shadow': 100,
                                 'shadow_color': '#0000ff', 'light': 100})
        self.assertTrue((plain == tinted).all())

    def test_bad_stops_fall_back(self):
        got = lightwarp.clean_params({'preset': 'custom', 'stops': [[0.5, 'red'], 'x']})
        self.assertEqual(got['stops'], lightwarp.DEFAULT_STOPS)

    def test_png_is_one_pixel_high(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            out = lightwarp.write_png({'steps': 2}, str(Path(tmp) / 'lw.png'))
            with Image.open(out) as img:
                self.assertEqual(img.size, (256, 1))
                self.assertEqual(img.mode, 'RGB')


if __name__ == '__main__':
    unittest.main()
