"""
Особые материалы редактора VMT (src/services/vmt_effects.py)

Главное, что ломалось бы молча: повторная настройка плодила бы прокси,
невидимость шпиона перестала бы прятать оружие, а текст не проходил бы
проверку синтаксиса и не сохранялся
"""

from __future__ import annotations

import re
import unittest

from src.services import vmt_effects as fx
from src.services.vmt_service import VMTService

#: Кусок стокового VMT оружия (обрез): невидимость и перекраска уже в прокси
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
    """Имена прокси по порядку"""
    block = text[text.lower().index('"proxies"'):]
    return re.findall(r'^\t\t"(\w+)"\s*$', block, re.MULTILINE)


class GlassTests(unittest.TestCase):

    def glass(self, text=STOCK, **vals):
        vals = {'color': '#3fd8ff', 'look': 'edge', 'refract': 1.5, **vals}
        return fx.apply(fx.GLASS, vals, text)['text']

    def test_keeps_the_material_and_orders_proxies(self):
        out = self.glass()
        self.assertIn('c_scattergun"', out)                  # текстура осталась
        # Обнулить -> невидимость шпиона -> прибавить стекло -> обрезать до 1
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
    """Нашло ревью: разбор съезжал на скобках в комментариях"""

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
        # выходило полностью прозрачным (сборка человека)
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
        """Своя текстура из игрового оригинала, когда в тексте уже белая основа"""
        white = fx.apply(fx.GHOST, {'source': 'color'}, STOCK)['text']
        out = fx.apply(fx.GHOST, {'source': 'texture'}, white, STOCK)['text']
        self.assertIn('"$basetexture" "models/weapons/c_models/c_scattergun/c_scattergun"', out)
        self.assertEqual(fx.values(fx.GHOST, out)['source'], 'texture')

    def test_defaults_on_a_plain_material(self):
        self.assertEqual(fx.values(fx.GHOST, STOCK),
                         {'color_mode': 'solid', 'color': '#ffffff', 'speed': 3,
                          'source': 'color', 'cubemap': 'sheen', 'bright': 1})


class RainbowTests(unittest.TestCase):
    """Цвет по кругу: три Sine на каналы, со сдвигом на треть периода"""

    def sines(self, text, var):
        return re.findall(r'"resultVar" "' + re.escape(var) + r'\[(\d)\]"', text)

    def test_glass_rainbow_and_back_to_one_color(self):
        out = fx.apply(fx.GLASS, {'color_mode': 'rainbow', 'speed': 2}, STOCK)['text']
        # Каналы - в свою переменную, в параметр плаща - целиком: запись по
        # каналам прямо в $cloakcolortint в игре гасила стекло
        self.assertEqual(self.sines(out, '$cloakcolortint'), [])
        self.assertEqual(self.sines(out, '$tf2sg_rgb'), ['0', '1', '2'])
        self.assertIn('"srcVar1" "$tf2sg_rgb"', out)
        self.assertIn('"timeOffset" "0.667"', out)
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        vals = fx.values(fx.GLASS, out)
        self.assertEqual((vals['color_mode'], vals['speed']), ('rainbow', 2.0))
        # Перенастройка на один цвет убирает радугу целиком
        solid = fx.apply(fx.GLASS, {'color_mode': 'solid', 'color': '#ff0000'}, out)['text']
        self.assertEqual(self.sines(solid, '$tf2sg_rgb'), [])
        self.assertNotIn('"srcVar1" "$tf2sg_rgb"', solid)
        self.assertEqual(fx.values(fx.GLASS, solid)['color_mode'], 'solid')

    def test_ghost_rainbow_drives_glow_and_reflection(self):
        out = fx.apply(fx.GHOST, {'color_mode': 'rainbow', 'speed': 4, 'bright': 1.5},
                       STOCK)['text']
        self.assertEqual(self.sines(out, '$selfillumtint'), ['0', '1', '2'])
        self.assertIn('"resultVar" "$envmaptint"', out)      # отражение - копия
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        vals = fx.values(fx.GHOST, out)
        self.assertEqual((vals['color_mode'], vals['speed'], vals['bright']),
                         ('rainbow', 4.0, 1.5))


#: Стоковое оружие с блеском киллстрика и свечением крита (как c_shogun_kunai)
SHEEN_STOCK = '''"VertexLitGeneric"
{
	"$basetexture" "models/w/kunai"
	"$glowcolor" "1"
	"$sheenPassEnabled" "1"
	"$sheenmap" "cubemaps/cubemap_sheen001"
	"$sheenmapmask" "Effects/AnimatedSheen/animatedsheen0"
	"$sheenmaptint" "[ 1 1 1 ]"
	"$sheenmapmaskframe" "0"
	"$sheenindex" "0"
	"$yellow" "0"
	"Proxies"
	{
		"AnimatedWeaponSheen"
		{
			"animatedtexturevar" "$sheenmapmask"
			"animatedtextureframenumvar" "$sheenmapmaskframe"
			"animatedtextureframerate" "40"
		}
		"invis"
		{
		}
		"ModelGlowColor"
		{
			"resultVar" "$glowcolor"
		}
		"Equals"
		{
			"srcVar1"  "$glowcolor"
			"resultVar" "$color2"
		}
		"YellowLevel"
		{
			"resultVar" "$yellow"
		}
	}
}
'''

BOUNDS = {"scale_x": 19.4, "scale_y": 3.5, "offset_x": -5.8, "offset_y": -1.4, "direction": 2}
GAME = {'AnimatedWeaponSheen': 0, 'ModelGlowColor': [1, 1, 1], 'YellowLevel': [1, 1, 1]}


def run_proxies(text: str, game: dict, curtime: float = 0.0) -> dict:
    """Прогон блока Proxies по семантике mathproxy.cpp / functionproxy.cpp
    (source-sdk-2013): переменные из VMT, игровые прокси пишут `game`"""
    vars_ = {}
    for key, val in re.findall(r'^\t"(\$\w+)"\s+"([^"]*)"', text, re.MULTILINE):
        nums = [float(n) for n in re.findall(r'-?\d*\.?\d+', val)]
        if nums:
            vars_[key.lower()] = nums if val.strip().startswith('[') else nums[0]
    block = text[text.lower().index('"proxies"'):]
    for name, body in re.findall(r'^\t\t"(\w+)"\s*\{([^}]*)\}', block, re.MULTILINE):
        args = {k.lower(): v for k, v in re.findall(r'"(\w+)"\s+"([^"]*)"', body)}

        def get(ref):
            m = re.fullmatch(r'(\$\w+)\[(\d)\]', ref)
            if m:
                return vars_[m.group(1).lower()][int(m.group(2))]
            if ref.startswith('$'):
                return vars_[ref.lower()]
            return float(ref)

        def put(ref, value):
            m = re.fullmatch(r'(\$\w+)\[(\d)\]', ref)
            if m:
                vec = list(vars_[m.group(1).lower()])
                vec[int(m.group(2))] = value
                vars_[m.group(1).lower()] = vec
            else:
                vars_[ref.lower()] = value

        res = args.get('resultvar')
        if name in game:
            put(res or args.get('animatedtextureframenumvar', ''), game[name])
        elif name == 'Equals':
            put(res, get(args['srcvar1']))
        elif name == 'Clamp':
            lo, hi = sorted((get(args['min']), get(args['max'])))
            put(res, min(hi, max(lo, get(args['srcvar1']))))
        elif name in ('Add', 'Subtract', 'Multiply', 'Divide'):
            a, b = get(args['srcvar1']), get(args['srcvar2'])
            put(res, a + b if name == 'Add' else a - b if name == 'Subtract'
                else a * b if name == 'Multiply' else a / b)
        elif name == 'LinearRamp':
            put(res, float(args['rate']) * curtime + float(args['initialvalue']))
        elif name == 'WrapMinMax':
            lo, hi = float(args['minval']), float(args['maxval'])
            f = (get(args['srcvar1']) - lo) / (hi - lo)
            put(res, (f - int(f)) * (hi - lo) + lo)
        elif name == 'Int':
            put(res, float(int(get(args['srcvar1']))))
        elif name == 'LessOrEqual':
            pick = 'lessequalvar' if get(args['srcvar1']) <= get(args['srcvar2']) else 'greatervar'
            put(res, get(args[pick]))
    return vars_


class SheenTests(unittest.TestCase):

    def sheen(self, text=SHEEN_STOCK, **vals):
        vals = {'color': '#00ff00', 'bright': 1, 'when': 'game', **vals}
        return fx.apply(fx.SHEEN, vals, text, '', BOUNDS)

    def test_own_colour_wins_over_game_and_is_linear(self):
        out = self.sheen(color='#808080')['text']
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        # Игра ставит цвет набора, наш Equals ниже его перебивает
        got = run_proxies(out, GAME)
        self.assertEqual([round(c, 3) for c in got['$sheenmaptint']], [0.216, 0.216, 0.216])
        self.assertEqual(proxies(out)[-1], 'Equals')

    def test_dark_colour_round_trips(self):
        for colour, bright in (('#050505', 1), ('#102030', 0.3)):
            out = self.sheen(color=colour, bright=bright)['text']
            self.assertEqual(fx.values(fx.SHEEN, out)['color'], colour)

    def test_reconfigure_and_values(self):
        out = self.sheen(self.sheen(when='always', pause=2)['text'],
                         color='#ff0000')['text']
        self.assertNotIn('LinearRamp', out)                   # «всегда» снято
        self.assertEqual(out.count('// tf2sg sheen'), 1)
        self.assertEqual(fx.values(fx.SHEEN, out)['color'], '#ff0000')
        self.assertEqual(fx.values(fx.SHEEN, out)['when'], 'game')

    def test_old_australium_look_folds_into_brightness(self):
        """«Ярче, как у австралия» ($sheenindex 1) - это x1.8 к яркости

        Поле «Вид» убрано: оно повторяло ползунок «Яркость». Старая настройка
        открывается яркостью, а перенастройка снимает и ключ, и прокси
        """
        old = self.sheen(bright=1.5)['text'].replace(
            '"$tf2sg_sheenbright" "1.5"', '"$tf2sg_sheenbright" "1.5"\n\t"$tf2sg_sheenidx" "1"')
        self.assertEqual(fx.values(fx.SHEEN, old)['bright'], 2.7)
        again = self.sheen(old, bright=2.7)['text']
        self.assertNotIn('sheenidx', again)

    def test_always_drives_frames_with_pause(self):
        out = self.sheen(when='always', pause=2)['text']
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        self.assertIn('"$sheenmapmaskdirection" "2"', out)
        self.assertEqual(fx.values(fx.SHEEN, out)['pause'], 2)
        frame = lambda t: run_proxies(out, GAME, t)['$sheenmapmaskframe']
        # 25 кадров/с: полоса идёт 59 кадров (2.4 с), потом 2 с кадр 0
        self.assertEqual(frame(1.0), 25)
        self.assertEqual(frame(2.3), 57)
        self.assertEqual(frame(3.0), 0)
        self.assertEqual(frame(4.4 + 1.0), 25)                # цикл 110 кадров = 4.4 с

    def test_game_mode_needs_game_sheen(self):
        bare = '"VertexLitGeneric"\n{\n\t"$basetexture" "a/b"\n}\n'
        self.assertIn('error', self.sheen(bare))
        out = self.sheen(bare, when='always')['text']
        self.assertIn('"$sheenpassenabled" "1"', out)        # проход добавлен

    def test_mask_params_like_the_game(self):
        import struct
        mdl = bytearray(300)
        mdl[:4] = b'IDST'
        struct.pack_into('<3f', mdl, 104, -1.4, -1.0, -5.8)   # hull_min
        struct.pack_into('<3f', mdl, 116, 2.1, 1.3, 13.6)     # hull_max
        struct.pack_into('<ii', mdl, 188, 1, 200)             # одна анимация
        struct.pack_into('<3f', mdl, 232, -1.4, -1.0, -5.8)
        struct.pack_into('<3f', mdl, 244, 2.1, 1.3, 13.6)
        got = fx.sheen_mask_params(bytes(mdl))
        self.assertEqual(got['direction'], 2)                 # длинная сторона Z
        self.assertAlmostEqual(got['scale_x'], 19.4, places=4)
        self.assertAlmostEqual(got['offset_y'], -1.0, places=4)


class CritGlowTests(unittest.TestCase):

    def crit(self, text=SHEEN_STOCK, **vals):
        vals = {'red': '#ff00ff', 'blue': '#00ffff', 'bright': 1, **vals}
        return fx.apply(fx.CRIT, vals, text)

    def glow(self, out, game_glow):
        return run_proxies(out, {**GAME, 'ModelGlowColor': game_glow})['$color2']

    def test_recolours_each_team_and_keeps_normal(self):
        out = self.crit()['text']
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])
        # Сразу за ModelGlowColor: родной Equals в $color2 несёт уже наш цвет
        names = proxies(out)
        self.assertEqual(names[names.index('ModelGlowColor') + 1], 'Clamp')
        self.assertEqual([round(c, 3) for c in self.glow(out, [80, 8, 5])], [80, 0, 80])
        self.assertEqual([round(c, 3) for c in self.glow(out, [5, 20, 80])], [0, 80, 80])
        self.assertEqual([round(c, 3) for c in self.glow(out, [1, 1, 1])], [1, 1, 1])
        # Свечение баффов (знамя, Crit-a-Cola) остаётся родным
        self.assertEqual([round(c, 3) for c in self.glow(out, [226, 150, 62])], [226, 150, 62])
        self.assertEqual([round(c, 3) for c in self.glow(out, [29, 202, 135])], [29, 202, 135])
        # Заряд щита демомана: половина пути к своему цвету
        half = self.glow(out, [40, 4, 2.5])
        self.assertAlmostEqual(half[0], 40 * 0.5 + 80 * 0.5, delta=0.5)

    def test_reconfigure_replaces_chain(self):
        once = self.crit()['text']
        twice = self.crit(once, bright=2)['text']
        self.assertEqual(twice.count('// tf2sg crit'), once.count('// tf2sg crit'))
        self.assertEqual(fx.values(fx.CRIT, twice),
                         {'red': '#ff00ff', 'blue': '#00ffff', 'bright': 2.0})

    def test_one_line_proxies(self):
        # Комментарий между именем и «{», тело в одну строку
        flat = SHEEN_STOCK.replace(
            '"ModelGlowColor"\n\t\t{\n\t\t\t"resultVar" "$glowcolor"\n\t\t}',
            '"ModelGlowColor" // crit\n\t\t{ "resultVar" "$glowcolor" }')
        self.assertIn('// crit\n', flat)
        out = self.crit(flat)['text']
        self.assertLess(out.index('"ModelGlowColor"'), out.index('// tf2sg crit'))
        self.assertTrue(VMTService.validate_vmt_syntax(out)[0])

    def test_needs_model_glow_proxy(self):
        self.assertIn('error', self.crit(STOCK))


class BuildKeepsChosenBaseTests(unittest.TestCase):
    """Сборка не переписывает $basetexture, выбранный в правке сознательно"""

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
