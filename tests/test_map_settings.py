"""Свои настройки карт (MATERIAL_MAPS[…]["settings"]): отражение, свечение,
края блика. Пустое - как у материала, в VMT не пишется

Факты: вики Valve ($envmap, $selfillum, $phong) и материалы TF2
"""
import tempfile
import unittest
from pathlib import Path

from src.data.material_maps import normalize_maps
from src.services import vmt_parse
from src.services.vpk_texture_builder import VpkTextureBuilder

GOLD_VMT = ('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
            '\t"$envmap" "cubemaps/cubemap_gold001"\n\t"$envmaptint" "[.1 .1 .1]"\n'
            '\t"$phongfresnelranges" "[.3 1 8]"\n'
            '\t"proxies"\n\t{\n\t\t"Equals"\n\t\t{\n\t\t\t"srcVar1" "$glowcolor"\n'
            '\t\t\t"resultVar" "$selfillumtint"\n\t\t}\n\t}\n}\n')


class MapSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vmt = self.tmp / 'm9.vmt'
        self.vmt.write_text(GOLD_VMT, encoding='utf-8')

    def apply(self, maps):
        VpkTextureBuilder._apply_settings(normalize_maps(maps), 'm9', self.vmt, self.tmp,
                                          'models/w', (16, 16), None, False, False)
        return self.vmt.read_text(encoding='utf-8')

    def test_untouched_settings_keep_material(self):
        text = self.apply({'envmapmask': {'derive': True}, 'selfillum': {'derive': True}})
        self.assertEqual(text, GOLD_VMT)

    def test_reflection_colour_strength_and_environment(self):
        doc = vmt_parse.parse(self.apply({'envmapmask': {
            'derive': True, 'env_cubemap': 'specular', 'env_tint': '#ff8000',
            'env_strength': '50'}}))
        self.assertEqual(doc.path('$envmap'), 'cubemaps/cubemap_specular001')
        # Игра возведёт в 2.2: 0.5^(1/2.2) ≈ 0.73 - в итоге половина отражения
        self.assertEqual(doc.get('$envmaptint'), '[0.730 0.366 0.000]')

    def test_reflection_tint_is_linear_on_phong(self):
        # Phong-материал берёт $envmaptint как есть (skin_dx9_helper.cpp):
        # цвет палитры в линейный, сила без степени
        self.vmt.write_text(GOLD_VMT.replace('"$envmap"', '"$phong" "1"\n\t"$envmap"'),
                            encoding='utf-8')
        doc = vmt_parse.parse(self.apply({'envmapmask': {
            'derive': True, 'env_tint': '#ff8000', 'env_strength': '50'}}))
        self.assertEqual(doc.get('$envmaptint'), '[0.500 0.108 0.000]')

    def test_tint_follows_phong_turned_on_later(self):
        # Контур свечения при $detail включает phong уже после отражения:
        # цвет всё равно в линейном виде
        self.vmt.write_text(GOLD_VMT.replace('"$envmap"', '"$bumpmap" "models/w/m9_n"\n'
                                             '\t"$detail" "models/w/d"\n\t"$envmap"'),
                            encoding='utf-8')
        doc = vmt_parse.parse(self.apply({
            'envmapmask': {'derive': True, 'env_tint': '#808080'},
            'selfillum': {'derive': True, 'glow_edge': 'on'}}))
        self.assertTrue(doc.flag('$phong'))
        self.assertEqual(doc.get('$envmaptint'), '[0.216 0.216 0.216]')

    def test_native_tint_linearised_when_build_turns_phong_on(self):
        # [.1 .1 .1] без phong движок возводил в 2.2; с phong берёт как есть
        doc = vmt_parse.parse(self.apply({'envmapmask': {'derive': True, 'env_fresnel': '60'}}))
        self.assertEqual(doc.get('$envmaptint'), '[0.006 0.006 0.006]')

    def test_reflection_fresnel_turns_phong_on_silently(self):
        doc = vmt_parse.parse(self.apply({'envmapmask': {'derive': True, 'env_fresnel': '60'}}))
        self.assertEqual(doc.get('$envmapfresnel'), '0.6')
        self.assertTrue(doc.flag('$phong'))
        self.assertEqual(doc.get('$phongboost'), '0')            # блика не будет
        self.assertEqual(doc.get('$phongfresnelranges'), '[.3 1 8]')

    def test_glow_colour_beats_native_proxy_and_pulses(self):
        text = self.apply({'selfillum': {'derive': True, 'glow_color': '#00ff00',
                                         'glow_power': '200', 'glow_pulse': 'fast',
                                         'glow_pulse_min': '20'}})
        doc = vmt_parse.parse(text)
        self.assertEqual(doc.get('$tf2sg_glow'), '[0.000 2.000 0.000]')
        proxies = doc.block('proxies')
        self.assertIsNotNone(proxies.block('Equals'))            # родной цел
        self.assertEqual(proxies.block('Sine').get('sineperiod'), '0.6')
        self.assertEqual(proxies.block('Sine').get('sinemin'), '0.2')
        # Наш Multiply - последним: он и решает итог каждый кадр
        self.assertLess(text.index('"Equals"'), text.index('"Multiply"'))
        # Повторная сборка не копит прокси
        text = self.apply({'selfillum': {'derive': True, 'glow_color': '#00ff00',
                                         'glow_pulse': 'fast'}})
        self.assertEqual(text.count('"Multiply"'), 1)

    def test_glow_edge(self):
        self.vmt.write_text(GOLD_VMT.replace('"$envmap"', '"$bumpmap" "models/w/m9_n"\n\t"$envmap"'),
                            encoding='utf-8')
        doc = vmt_parse.parse(self.apply({'selfillum': {'derive': True, 'glow_edge': 'on',
                                                        'edge_bright': '4', 'edge_sharp': '12'}}))
        self.assertTrue(doc.flag('$selfillumfresnel'))
        self.assertEqual(doc.get('$selfillumfresnelminmaxexp'), '[0 4 12]')

    def test_highlight_edges_fill_untouched_from_material(self):
        VpkTextureBuilder._fresnel_ranges({'fres_edge': '3'}, self.vmt, 'models/w')
        doc = vmt_parse.parse(self.vmt.read_text(encoding='utf-8'))
        self.assertEqual(doc.get('$phongfresnelranges'), '[0.3 1 3]')

    def write(self, text):
        self.vmt.write_text(text, encoding='utf-8')

    def test_pulse_without_colour_keeps_native_glow(self):
        self.write('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
                   '\t"$selfillumtint" "[2 0.5 0.1]"\n}\n')
        doc = vmt_parse.parse(self.apply({'selfillum': {'derive': True, 'glow_pulse': 'slow'}}))
        self.assertEqual(doc.get('$tf2sg_glow'), '[2.000 0.500 0.100]')   # не белый

    def test_brightness_only_adds_no_proxy(self):
        text = self.apply({'selfillum': {'derive': True, 'glow_power': '50'}})
        self.assertNotIn('tf2sg glow', text)                  # родные прокси решают

    def test_strength_without_colour_keeps_gold_hue(self):
        doc = vmt_parse.parse(self.apply({'envmapmask': {'derive': True,
                                                         'env_strength': '200'}}))
        # [.1 .1 .1] материала × 2^(1/2.2): оттенок свой, только сильнее
        self.assertEqual(doc.get('$envmaptint'), '[0.137 0.137 0.137]')

    def test_fresnel_skipped_with_separate_mask(self):
        self.write('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n'
                   '\t"$envmap" "env_cubemap"\n\t"$envmapmask" "models/w/m9_mask"\n}\n')
        doc = vmt_parse.parse(self.apply({'envmapmask': {'mod': True, 'env_fresnel': '50'}}))
        self.assertIsNone(doc.get('$envmapfresnel'))
        self.assertFalse(doc.flag('$phong'))                  # маску мода не ломаем

    def test_glow_edge_needs_normal(self):
        self.write('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9"\n}\n')
        doc = vmt_parse.parse(self.apply({'selfillum': {'derive': True, 'glow_edge': 'on'}}))
        self.assertIsNone(doc.get('$selfillumfresnel'))       # нет нормали - не пишем впустую

    def test_glow_edge_on_blue_follows_red_normal(self):
        self.write('"VertexLitGeneric"\n{\n\t"$basetexture" "models/w/m9_blue"\n}\n')
        (self.tmp / 'm9_normal.vtf').write_bytes(b'n')
        VpkTextureBuilder._apply_settings(
            normalize_maps({'selfillum': {'derive': True, 'glow_edge': 'on'}}), 'm9', self.vmt,
            self.tmp, 'models/w', (16, 16), None, False, True)
        doc = vmt_parse.parse(self.vmt.read_text(encoding='utf-8'))
        self.assertEqual(doc.path('$bumpmap'), 'models/w/m9_normal')
        self.assertTrue(doc.flag('$selfillumfresnel'))

    def test_editor_strip_keeps_glow_proxies(self):
        from src.services import vmt_effects
        text = self.apply({'selfillum': {'derive': True, 'glow_color': '#ff0000'}})
        self.assertIn('tf2sg glow', vmt_effects._strip_marked_proxies(text))

    def test_glow_colour_is_linear(self):
        # $selfillumtint движок берёт без перевода из гаммы - серый из палитры
        # (128) пишется линейным 0.216, иначе свечение выходило светлее
        doc = vmt_parse.parse(self.apply({'selfillum': {'derive': True,
                                                        'glow_color': '#808080'}}))
        self.assertEqual(doc.get('$selfillumtint'), '[0.216 0.216 0.216]')

    def test_settings_are_validated(self):
        got = normalize_maps({'envmapmask': {'derive': True, 'env_cubemap': 'moon',
                                             'env_strength': '999', 'env_tint': 'red'},
                              'phongcolor': {'enabled': True, 'fres_edge': '2.5'}})
        self.assertEqual(got['envmapmask'], {'derive': True, 'env_strength': '300'})
        self.assertEqual(got['phongcolor']['fres_edge'], '2.5')


if __name__ == '__main__':
    unittest.main()
