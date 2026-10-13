"""Мод из VPK: рельеф и карты материала доходят до VMT мода.

Раньше build_custom_mod выкидывал галку Normal Map и не знал про карты —
в мод шла только заменённая текстура.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from src.services.custom_vpk_service import CustomVPKService

VMT = '"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n}\n'


class ApplyMaterialExtrasTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.vpkroot = root / 'vpkroot'
        self.temp = root
        folder = self.vpkroot / 'materials' / 'models' / 'w'
        folder.mkdir(parents=True)
        self.textures = []
        for name in ('m9', 'm9_blue'):
            (folder / f'{name}.vtf').write_bytes(b'vtf')
            (folder / f'{name}.vmt').write_text(VMT, encoding='utf-8')
            self.textures.append({'name': name, 'vtf_name': name,
                                  'vtf_path': str(folder / f'{name}.vtf'),
                                  'vmt_path': str(folder / f'{name}.vmt'),
                                  'vmt_dir': str(folder)})
        self.folder = folder

    def tearDown(self):
        self._tmp.cleanup()

    def run_extras(self, maps, opts):
        def fake_normal(image, vtf_dir, mat, *_a, **_k):
            out = Path(vtf_dir) / f'{mat}_normal.vtf'
            out.write_bytes(b'n')
            return out

        settings = lambda tex: ((64, 64), 'DXT5', [], dict(opts))
        with mock.patch('src.services.normal_map.rgba_from_vtf',
                        return_value=np.zeros((4, 4, 4), np.uint8)), \
             mock.patch('src.services.texture_service.TextureService.write_normal_vtf',
                        side_effect=fake_normal), \
             mock.patch('src.services.vpk_texture_builder.VpkTextureBuilder'
                        '._apply_maps_for_material') as apply_maps:
            problems = CustomVPKService._apply_material_extras(
                self.textures, {}, maps, settings, self.vpkroot, self.temp, 'ru')
        return problems, apply_maps

    def test_normal_from_mod_texture_goes_into_vmt(self):
        problems, _ = self.run_extras({}, {'normal': True})
        self.assertEqual(problems, [])
        text = (self.folder / 'm9.vmt').read_text(encoding='utf-8')
        self.assertIn('"$bumpmap" "models/w/m9_normal"', text)
        self.assertTrue((self.folder / 'm9_normal.vtf').exists())

    def test_maps_go_to_own_vmt_and_blue_inherits(self):
        maps = {'m9': {'rimlight': {'enabled': True}}}
        problems, apply_maps = self.run_extras(maps, {})
        self.assertEqual(problems, [])
        red, blue = apply_maps.call_args_list
        self.assertEqual(red.args[1:3], ('m9', self.folder / 'm9.vmt'))
        self.assertEqual(red.args[5], 'models/w')
        self.assertEqual(blue.args[2], self.folder / 'm9_blue.vmt')
        self.assertTrue(blue.kwargs.get('params_only'))

    def test_no_vmt_is_reported(self):
        self.textures[0]['vmt_path'] = None
        problems, apply_maps = self.run_extras({'m9': {'rimlight': {'enabled': True}}}, {})
        self.assertEqual(len(problems), 1)


if __name__ == '__main__':
    unittest.main()
