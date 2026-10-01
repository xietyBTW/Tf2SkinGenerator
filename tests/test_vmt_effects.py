"""
Особые материалы редактора VMT (src/services/vmt_effects.py).

Главное, что ломалось бы молча: повторная настройка плодила бы прокси,
невидимость шпиона перестала бы прятать оружие, а текст не проходил бы
проверку синтаксиса и не сохранялся.
"""

from __future__ import annotations

import re
import unittest

from src.services import vmt_effects as fx
from src.services.vmt_service import VMTService

#: Кусок стокового VMT оружия (обрез): невидимость и перекраска уже в прокси.
STOCK = '''"VertexLitGeneric"
{
	"$basetexture"	"models/weapons/c_models/c_scattergun/c_scattergun"
	"$phong" "1"
	// Cloaking
	"$cloakPassEnabled" "1"
	"Proxies"
	{
		"invis"
		{
		}
		"Equals"
		{
			"srcVar1"  "$glowcolor"
			"resultVar" "$color2"
		}
	}
}
'''


def proxies(text: str) -> list:
    """Имена прокси по порядку."""
    block = text[text.lower().index('"proxies"'):]
    return re.findall(r'^\t\t"(\w+)"\s*$', block, re.MULTILINE)


class GlassTests(unittest.TestCase):

    def glass(self, text=STOCK, **vals):
        vals = {'color': '#3fd8ff', 'look': 'edge', 'refract': 1.5, **vals}
        return fx.apply(fx.GLASS, vals, text)['text']

    def test_keeps_the_material_and_orders_proxies(self):
        out = self.glass()
        self.assertIn('c_scattergun"', out)                  # текстура осталась
        # Обнулить → невидимость шпиона → прибавить стекло → обрезать до 1.
        self.assertEqual(proxies(out), ['Equals', 'invis', 'Equals', 'Add', 'Clamp'])
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])

    def test_reconfigure_replaces_own_proxies_and_keys(self):
        out = self.glass(self.glass(), color='#ff0000', look='full', refract=3)
        self.assertEqual(proxies(out), ['Equals', 'invis', 'Equals', 'Add', 'Clamp'])
        self.assertEqual(len(re.findall(r'cloakpassenabled', out, re.I)), 1)
        self.assertEqual(fx.values(fx.GLASS, out),
                         {'color_mode': 'solid', 'color': '#ff0000', 'speed': 3,
                          'look': 'full', 'refract': 3.0})

    def test_adds_invis_when_material_has_none(self):
        bare = '"VertexLitGeneric"\n{\n\t"$basetexture" "a/b"\n}\n'
        out = self.glass(bare)
        self.assertEqual(proxies(out), ['Equals', 'invis', 'Add', 'Clamp'])
        self.assertEqual(proxies(self.glass(out)), ['Equals', 'invis', 'Add', 'Clamp'])
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])


class GlassEdgeCases(unittest.TestCase):
    """Нашло ревью: разбор съезжал на скобках в комментариях."""

    glass = GlassTests.glass

    def test_brace_in_comment_inside_proxies(self):
        text = STOCK.replace('\t\t"invis"', '\t\t// TODO: add Sine {\n\t\t"invis"')
        once = self.glass(text)
        self.assertEqual(self.glass(once).count('// tf2sg'), once.count('// tf2sg'))

    def test_header_comment_with_brace(self):
        text = '// by me {v2}\n"VertexLitGeneric"\n{\n\t"$basetexture" "a/b"\n}\n'
        out = self.glass(text)
        self.assertTrue(out.startswith('// by me {v2}\n'))
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])

    def test_one_line_proxies_and_legacy_invis(self):
        for proxy in ('"invis" { }', '"weapon_invis" { }'):
            text = '"VertexLitGeneric"\n{\n\t"$basetexture" "a/b"\n\t"Proxies" { %s }\n}\n' % proxy
            out = self.glass(text)
            self.assertEqual(len(re.findall(r'"(?:\w+_)?invis"', out)), 1, proxy)
            self.assertEqual(self.glass(out), out)


class GhostTests(unittest.TestCase):

    def test_glowing_edges_with_cloak(self):
        res = fx.apply(fx.GHOST, {'color': '#3fd8ff', 'source': 'color',
                                  'cubemap': 'gold', 'bright': 2}, STOCK)
        out = res['text']
        self.assertTrue(res['replace'])
        # Рецепт мода, который видно в игре: без самосвета с френелем оружие
        # выходило полностью прозрачным (сборка человека).
        for line in ('"$additive" "1"', '"$color2" "[0 0 0]"', '"$selfillum" "1"',
                     '"$selfillumfresnel" "1"', '"$cloakpassenabled" "1"'):
            self.assertIn(line, out)
        self.assertIn(f'"$basetexture" "{fx.WHITE}"', out)
        self.assertEqual(proxies(out), ['invis'])
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        self.assertEqual(fx.values(fx.GHOST, out),
                         {'color_mode': 'solid', 'color': '#3fd8ff', 'speed': 3,
                          'source': 'color', 'cubemap': 'gold', 'bright': 2.0})

    def test_texture_source_finds_the_own_texture_again(self):
        """Своя текстура из игрового оригинала, когда в тексте уже белая основа."""
        white = fx.apply(fx.GHOST, {'source': 'color'}, STOCK)['text']
        out = fx.apply(fx.GHOST, {'source': 'texture'}, white, STOCK)['text']
        self.assertIn('"$basetexture" "models/weapons/c_models/c_scattergun/c_scattergun"', out)
        self.assertEqual(fx.values(fx.GHOST, out)['source'], 'texture')

    def test_defaults_on_a_plain_material(self):
        self.assertEqual(fx.values(fx.GHOST, STOCK),
                         {'color_mode': 'solid', 'color': '#ffffff', 'speed': 3,
                          'source': 'color', 'cubemap': 'sheen', 'bright': 1})


class RainbowTests(unittest.TestCase):
    """Цвет по кругу: три Sine на каналы, со сдвигом на треть периода."""

    def sines(self, text, var):
        return re.findall(r'"resultVar" "' + re.escape(var) + r'\[(\d)\]"', text)

    def test_glass_rainbow_and_back_to_one_color(self):
        out = fx.apply(fx.GLASS, {'color_mode': 'rainbow', 'speed': 2}, STOCK)['text']
        # Каналы — в свою переменную, в параметр плаща — целиком: запись по
        # каналам прямо в $cloakcolortint в игре гасила стекло.
        self.assertEqual(self.sines(out, '$cloakcolortint'), [])
        self.assertEqual(self.sines(out, '$tf2sg_rgb'), ['0', '1', '2'])
        self.assertIn('"srcVar1" "$tf2sg_rgb"', out)
        self.assertIn('"timeOffset" "0.667"', out)
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        vals = fx.values(fx.GLASS, out)
        self.assertEqual((vals['color_mode'], vals['speed']), ('rainbow', 2.0))
        # Перенастройка на один цвет убирает радугу целиком.
        solid = fx.apply(fx.GLASS, {'color_mode': 'solid', 'color': '#ff0000'}, out)['text']
        self.assertEqual(self.sines(solid, '$tf2sg_rgb'), [])
        self.assertNotIn('"srcVar1" "$tf2sg_rgb"', solid)
        self.assertEqual(fx.values(fx.GLASS, solid)['color_mode'], 'solid')

    def test_ghost_rainbow_drives_glow_and_reflection(self):
        out = fx.apply(fx.GHOST, {'color_mode': 'rainbow', 'speed': 4, 'bright': 1.5},
                       STOCK)['text']
        self.assertEqual(self.sines(out, '$selfillumtint'), ['0', '1', '2'])
        self.assertIn('"resultVar" "$envmaptint"', out)      # отражение — копия
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        vals = fx.values(fx.GHOST, out)
        self.assertEqual((vals['color_mode'], vals['speed'], vals['bright']),
                         ('rainbow', 4.0, 1.5))


class BuildKeepsChosenBaseTests(unittest.TestCase):
    """Сборка не переписывает $basetexture, выбранный в правке сознательно."""

    def _chosen(self, edited_base):
        import os
        import tempfile
        from src.services.vpk_texture_builder import VpkTextureBuilder
        with tempfile.TemporaryDirectory() as d:
            game, edited = os.path.join(d, 'g.vmt'), os.path.join(d, 'e.vmt')
            for path, base in ((game, 'models/weapons/c_models/c_pistol/c_pistol'),
                               (edited, edited_base)):
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('"VertexLitGeneric"\n{\n\t"$basetexture" "%s"\n}\n' % base)
            return VpkTextureBuilder._basetexture_chosen(edited, game)

    def test_effect_white_base_is_kept(self):
        self.assertTrue(self._chosen(fx.WHITE))

    def test_same_game_path_is_rewritten(self):
        self.assertFalse(self._chosen(r'Models\Weapons\c_models\c_pistol\c_pistol'))


if __name__ == '__main__':
    unittest.main()
