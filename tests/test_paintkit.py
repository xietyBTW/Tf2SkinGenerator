"""War Paint: чтение рецептов proto_defs.vpd и компоновщик (без установленной игры)."""

import struct
import unittest

import numpy as np

from src.data.paintkit_defs import PaintKitDefs
from src.services.paintkit_compositor import (
    PaintkitCompositor, UniformRandomStream, adjust_levels,
)


# ── Мини-кодировщик protobuf: ровно то, что нужно рецепту ─────────────── #

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def fld(num, value):
    if isinstance(value, int):
        return _varint(num << 3) + _varint(value)
    if isinstance(value, str):
        value = value.encode()
    return _varint(num << 3 | 2) + _varint(len(value)) + value


def header(defindex, name, variables=()):
    body = fld(1, defindex) + fld(2, name)
    for var_name, value, inherit in variables:
        body += fld(6, fld(1, var_name) + fld(2, int(inherit)) + fld(3, value))
    return fld(1, body)


def var_field(num, name, default=''):
    return fld(num, fld(1, name) + fld(9, default))


def def_id(num, defindex, kind):
    return fld(num, fld(1, defindex) + fld(2, kind))


def vpd(blocks):
    """{тип: [сообщения]} → proto_defs.vpd."""
    out = b''
    for kind, msgs in blocks.items():
        out += struct.pack('<II', kind, len(msgs))
        for m in msgs:
            out += struct.pack('<I', len(m)) + m
    return out


def texture_stage(tex_var):
    return fld(1, var_field(1, tex_var))        # texture_lookup.texture


def make_defs():
    # Шаблон: multiply( texture($pattern), texture($albedo) ).
    combine = (fld(11, fld(1, texture_stage('pattern')))
               + fld(11, fld(1, texture_stage('albedo'))))
    operation = header(900, 'tmpl', [('pattern', 'patterns/a', True),
                                     ('albedo', 'models/x/albedo', True),
                                     ('locked', 'keep', False)])
    operation += fld(2, fld(1, fld(4, combine)))            # combine_multiply
    item_def = (header(50, 'gun', [('albedo', 'models/gun/p_gun_albedo', True)])
                + fld(2, 13)                                  # предмет 13
                + fld(4, var_field(2, 'pattern', 'patterns/wear1'))
                + fld(4, var_field(2, 'pattern', 'patterns/wear2')))
    kit_item = def_id(1, 50, 8) + fld(5, var_field(4, 'locked', 'changed'))
    kit = (header(7, 'kit', [('pattern', 'patterns/a', True),
                             ('albedo', 'models/x/albedo', True),
                             ('locked', 'keep', False)])
           + fld(2, 'kit_token') + def_id(3, 900, 7) + fld(15, kit_item))
    return PaintKitDefs(vpd({7: [operation], 8: [item_def], 9: [kit]}))


class RecipeTests(unittest.TestCase):

    def test_variables_resolved_like_game(self):
        """Шаблон → War Paint → пушка → износ; запертая переменная не меняется."""
        defs = make_defs()
        kit = defs.kits[7]
        self.assertEqual(kit.loc_token, 'kit_token')
        recipe = defs.recipe(kit, kit.items[0], wear=2)
        self.assertEqual(recipe['type'], 'combine_multiply')
        textures = [n['fields']['texture'] for n in recipe['nodes']]
        self.assertEqual(textures, ['patterns/wear2', 'models/gun/p_gun_albedo'])

    def test_wear_clamped_to_available(self):
        defs = make_defs()
        kit = defs.kits[7]
        recipe = defs.recipe(kit, kit.items[0], wear=5)
        self.assertEqual(recipe['nodes'][0]['fields']['texture'], 'patterns/wear2')


def solid(color, size=4):
    return np.full((size, size, 4), color, np.uint8)


class CompositorTests(unittest.TestCase):

    def compose(self, recipe, textures, size=8, team='red'):
        comp = PaintkitCompositor(lambda p, raw=False: textures.get(p), size=size, team=team)
        return comp.compose(recipe, seed=1), comp

    def test_multiply_in_linear_space(self):
        """Умножение идёт в линейном пространстве, как у sRGB-чтения игры."""
        half = solid((188, 188, 188, 255))          # ≈ 0.5 в линейном
        recipe = {'type': 'combine_multiply', 'fields': {}, 'nodes': [
            {'type': 'texture_lookup', 'fields': {'texture': 'a'}, 'nodes': []},
            {'type': 'texture_lookup', 'fields': {'texture': 'b'}, 'nodes': []}]}
        img, _ = self.compose(recipe, {'a': half, 'b': half})
        # 0.5 · 0.5 = 0.25 линейных → ≈ 137 в sRGB (а не 188·188/255 = 139 и не 64).
        self.assertTrue(abs(int(img[0, 0, 0]) - 137) <= 2, img[0, 0])

    def test_select_mask_by_group(self):
        groups = np.zeros((8, 8, 4), np.uint8)
        groups[:, :4, 0] = 32          # группа 2 слева
        groups[:, 4:, 0] = 48          # группа 3 справа
        recipe = {'type': 'combine_lerp', 'fields': {}, 'nodes': [
            {'type': 'texture_lookup', 'fields': {'texture': 'black'}, 'nodes': []},
            {'type': 'texture_lookup', 'fields': {'texture': 'white'}, 'nodes': []},
            {'type': 'select', 'fields': {'groups': 'g'}, 'select': ['32', '0'], 'nodes': []}]}
        img, _ = self.compose(recipe, {'black': solid((0, 0, 0, 255)),
                                       'white': solid((255, 255, 255, 255)),
                                       'g': groups})
        self.assertEqual(int(img[4, 1, 0]), 255)     # группа выбрана — белое
        self.assertEqual(int(img[4, 6, 0]), 0)       # не выбрана — чёрное

    def test_team_texture(self):
        node = {'type': 'texture_lookup', 'nodes': [],
                'fields': {'texture_red': 'r', 'texture_blue': 'b'}}
        tex = {'r': solid((255, 0, 0, 255)), 'b': solid((0, 0, 255, 255))}
        red, _ = self.compose(node, tex, team='red')
        blu, _ = self.compose(node, tex, team='blue')
        self.assertGreater(int(red[0, 0, 0]), 200)
        self.assertGreater(int(blu[0, 0, 2]), 200)

    def test_missing_texture_reported(self):
        node = {'type': 'texture_lookup', 'fields': {'texture': 'nope'}, 'nodes': []}
        img, comp = self.compose(node, {})
        self.assertEqual(comp.missing, ['nope'])
        self.assertEqual(img.shape, (8, 8, 4))

    def test_levels_zero_range_is_threshold(self):
        """adjust_offset 0: белая точка = чёрной — порог, а не деление на ноль."""
        rgba = np.full((2, 2, 4), 0.5, np.float32)
        out = adjust_levels(rgba, 0.2, 0.2, 1.0)
        self.assertTrue(np.isfinite(out).all())
        self.assertTrue((out[..., 0] == 1).all())

    def test_seed_is_deterministic(self):
        node = {'type': 'texture_lookup', 'nodes': [],
                'fields': {'texture': 'n', 'rotation': '0 360', 'translate_u': '0 1'}}
        noise = np.random.default_rng(0).integers(0, 255, (16, 16, 4), dtype=np.uint8)
        a, _ = self.compose(node, {'n': noise}, size=16)
        b, _ = self.compose(node, {'n': noise}, size=16)
        self.assertTrue((a == b).all())


class RandomStreamTests(unittest.TestCase):

    def test_matches_numerical_recipes_ran1(self):
        """CUniformRandomStream — это ran1: при idum = -1 первое значение 0.415999."""
        self.assertAlmostEqual(UniformRandomStream(1).random_float(), 0.415999, places=5)


if __name__ == '__main__':
    unittest.main()


class GroupSeamTests(unittest.TestCase):

    def test_seam_between_groups_is_not_a_third_group(self):
        """Маска вдвое крупнее результата: шов 48|80 не должен дать группу 64."""
        groups = np.zeros((16, 16, 4), np.uint8)
        groups[:, :8, 0] = 48
        groups[:, 8:, 0] = 80
        recipe = {'type': 'select', 'fields': {'groups': 'g'}, 'select': ['64'], 'nodes': []}
        comp = PaintkitCompositor(lambda p, raw=False: groups if p == 'g' else None, size=8)
        self.assertEqual(int(comp.compose(recipe)[..., 0].max()), 0)


class FakeReader:
    def __init__(self, files):
        self.files = {k.lower(): v for k, v in files.items()}
        self.paks = [self.files]

    def read(self, path):
        return self.files.get(path.lower())


class PaintableMaterialsTests(unittest.TestCase):

    def test_weaponskin_materials_found(self):
        from unittest.mock import patch
        from src.services import paintkit_worker as pw
        reader = FakeReader({
            'models/w/c_det.mdl': b'mdl',
            'materials/models/w/c_det.vmt': b'"VertexLitGeneric" { "Proxies" { "WeaponSkin" {} } }',
            'materials/models/w/c_det_shell.vmt': b'{ "Proxies" { "weaponskin" {} } }',
            'materials/models/w/c_det_lens.vmt': b'{ }',
        })
        with patch('src.services.mdl_mesh.materials',
                   return_value=(['c_det', 'c_det_shell', 'c_det_lens'], ['models/w/'])):
            got = pw.paintable_materials(reader, 'models/w/c_det.mdl')
        self.assertEqual(got, ['c_det', 'c_det_shell'])


class TargetsTests(unittest.TestCase):

    def targets(self, cards, paintable, main):
        from src.app.session import AppSession
        s = AppSession.__new__(AppSession)
        from src.domain.preview.session import PreviewSession
        s.preview = PreviewSession()
        s.preview.textures.material_names = cards
        return s._paintkit_targets(paintable, main)

    def test_single_material_goes_to_main_card(self):
        self.assertEqual(self.targets(['__single__'], ['c_sniperrifle'], '__single__'),
                         ['__single__'])

    def test_detonator_gets_shell_too(self):
        self.assertEqual(self.targets(['c_detonator', 'c_detonator_shell'],
                                      ['c_detonator', 'c_detonator_shell', 'c_detonator_blue'],
                                      'c_detonator'),
                         ['c_detonator', 'c_detonator_shell'])

    def test_unknown_materials_fall_back_to_main(self):
        self.assertEqual(self.targets(['a', 'b'], [], 'a'), ['a'])


class GenericModeTests(unittest.TestCase):

    def test_largest_part_gets_base_layer(self):
        from src.services.paintkit_generic import assign_layers
        got = assign_layers([0.5, 0.2, 0.1, 0.05, 0.01], [1, 2, 3, 4], False, 0)
        self.assertEqual(got[0], 0)                    # основа (слой 1) — без выбора
        self.assertEqual(got[1:4], [2, 3, 4])          # следующие — по разным слоям

    def test_over_albedo_paints_every_part(self):
        from src.services.paintkit_generic import assign_layers
        got = assign_layers([0.5, 0.2, 0.1], [2, 3], True, 0)
        self.assertNotIn(0, got)
        self.assertNotEqual(got[0], got[1])            # две крупные — разные узоры

    def test_shuffle_changes_layout(self):
        from src.services.paintkit_generic import assign_layers
        areas = [0.4, 0.2, 0.1, 0.1, 0.05, 0.05]
        layouts = {tuple(assign_layers(areas, [1, 2, 3, 4], False, s)) for s in range(1, 20)}
        self.assertGreater(len(layouts), 1)

    def test_single_part_model_splits_by_islands(self):
        """Цельная модель (бита) делится по островам развёртки, иначе узор один."""
        from types import SimpleNamespace
        from src.services.paintkit_generic import _units
        tri = lambda x: ((x, 0.0), (x + 0.2, 0.0), (x, 0.2))  # noqa: E731
        part = SimpleNamespace(index=0, uv_area=0.06, paintable=True)
        model = SimpleNamespace(
            parts_of=lambda m: [part],
            polygons=lambda m, i: [tri(0.0), tri(0.3), tri(0.6)],
            tri_island={'bat': [0, 1, 2]},
            uv={'bat': [tri(0.0), tri(0.3), tri(0.6)]})
        self.assertEqual(len(_units(model, 'bat', 4)), 3)

    def test_recipe_forced_values_and_stickers_removed(self):
        defs = make_defs()
        kit = defs.kits[7]
        recipe = defs.recipe(kit, kit.items[0], 1, forced={'albedo': '__generated__/albedo'})
        self.assertEqual(recipe['nodes'][1]['fields']['texture'], '__generated__/albedo')
        from src.data.paintkit_defs import _without_stickers
        node = {'type': 'combine_lerp', 'fields': {}, 'nodes': [
            {'type': 'apply_sticker', 'fields': {}, 'stickers': [], 'nodes': [
                {'type': 'texture_lookup', 'fields': {'texture': 'a'}, 'nodes': []}]}]}
        self.assertEqual(_without_stickers(node)['nodes'][0]['type'], 'texture_lookup')
