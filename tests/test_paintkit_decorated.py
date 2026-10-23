"""
Украшенное оружие коллекций (Current Event, Night Owl…) на любой модели

В игре такой скин есть только у своих пушек: шаблона у него нет, рецепт каждого
износа нарисован под маски пушки (``p_<пушка>_groups`` и др.) и номера её групп.
Приложение раскладывает «виды» рецепта по деталям модели в долях оригинала и
подменяет маски оригинала масками модели
"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.services import paintkit_generic as pg

GROUPS = 'models/weapons/c_models/c_scattergun/p_scattergun_groups'


def _lookup(texture, **fields):
    return {'type': 'texture_lookup', 'nodes': [], 'fields': {'texture': texture, **fields}}


def _select(*values):
    return {'type': 'select', 'nodes': [], 'fields': {'groups': GROUPS},
            'select': [str(v) for v in values]}


#: Как у Current Event: молнии на группах 3/11/15, лаванда на 2/4/8/9, чёрный - остальное
CURRENT_EVENT = {'type': 'combine_lerp', 'fields': {}, 'nodes': [
    {'type': 'combine_lerp', 'fields': {}, 'nodes': [
        _lookup('patterns/solid_black_02'), _lookup('patterns/powerhouse/electric_purple'),
        _select(48, 176, 240)]},
    _lookup('patterns/solid_bright_lavender'),
    _select(32, 64, 128, 144)]}


def _mask(counts):
    """Маска групп: {номер группы: сколько пикселей}"""
    ids = [g for g, n in counts.items() for _ in range(n)]
    mask = np.zeros((1, len(ids), 4), np.uint8)
    mask[0, :, 0] = [min(g * 16, 255) for g in ids]     # группа 16 в маске - 255
    return mask


class LooksTests(unittest.TestCase):
    def test_current_event_has_three_looks_with_original_shares(self):
        loader = lambda path, raw=False: _mask({0: 50, 3: 30, 2: 10, 5: 10})  # noqa: E731
        looks = pg.recipe_looks(CURRENT_EVENT, loader)
        self.assertEqual(looks.groups, GROUPS)
        self.assertEqual(looks.values, [0, 32, 48])        # ни один / лаванда / молнии
        self.assertEqual([round(s, 2) for s in looks.shares], [0.2, 0.2, 0.6])

    def test_group_sixteen_is_a_look_too(self):
        """255 и 248 - группа 16: у Stabbed to Hell на ней трещины, у ножа это пятая часть"""
        recipe = {'type': 'combine_lerp', 'fields': {}, 'nodes': [
            _lookup('patterns/solid_black_02'), _lookup('patterns/mtp/pyr_crackles'),
            _select(255)]}
        looks = pg.recipe_looks(recipe, lambda path, raw=False: _mask({3: 4, 16: 1}))
        self.assertEqual(looks.values, [0, 255])
        self.assertEqual(looks.shares, [0.8, 0.2])

    def test_same_groups_in_two_selects_are_one_look(self):
        recipe = {'type': 'combine_multiply', 'fields': {}, 'nodes': [
            _select(48), _select(48), _select(64)]}
        looks = pg.recipe_looks(recipe, lambda path, raw=False: None)
        self.assertEqual(looks.values, [0, 48, 64])
        self.assertEqual(looks.shares, [1 / 3] * 3)        # маски нет - поровну

    def test_parts_follow_original_shares(self):
        got = pg.assign_shares([0.5, 0.3, 0.1, 0.1], [0.2, 0.5, 0.3])
        self.assertEqual(got, [1, 2, 0, 0])

    def test_shuffle_changes_layout(self):
        areas = [0.3, 0.2, 0.2, 0.1, 0.1, 0.1]
        layouts = {tuple(pg.assign_shares(areas, [0.3, 0.4, 0.3], s)) for s in range(1, 20)}
        self.assertGreater(len(layouts), 1)


class SwapTests(unittest.TestCase):
    def test_original_weapon_masks_become_the_models(self):
        recipe = {'type': 'combine_multiply', 'fields': {}, 'nodes': [
            _lookup('models/weapons/c_models/c_scattergun/p_scattergun_ao'),
            _lookup('models/weapons/c_models/c_revolver/c_revolver'),
            _lookup('patterns/gunmettle/c_smg/p_smg_wearblend_gunmettle'),
            _lookup('patterns/paint_dirt'),
            _select(48)]}
        nodes = pg.swap_weapon_textures(recipe)['nodes']
        self.assertEqual([n['fields'].get('texture') for n in nodes[:4]],
                         [pg.GEN + 'ao', pg.GEN + 'albedo', pg.GEN + 'wearblend',
                          'patterns/paint_dirt'])
        self.assertEqual(nodes[4]['fields']['groups'], pg.GEN + 'groups')
        self.assertEqual(recipe['nodes'][0]['fields']['texture'][:6], 'models')  # копия

    def test_picture_drawn_for_the_original_is_dropped(self):
        """У Killer Bee поверх узора - рисунок под развёртку обреза (умножением)"""
        recipe = {'type': 'combine_multiply', 'fields': {}, 'nodes': [
            _select(48), _lookup('patterns/combat/c_scattergun_killerbee_multiply')]}
        self.assertEqual(pg.swap_weapon_textures(recipe)['nodes'][1]['fields']['texture'],
                         'patterns/blank_white')

    def test_skin_drawn_whole_stays_with_its_weapon(self):
        """Warhawk - одна картинка под развёртку ракетомёта, групп нет"""
        from src.data.paintkit_defs import _drawn_whole
        warhawk = {'type': 'combine_lerp', 'fields': {}, 'nodes': [
            _lookup('models/weapons/c_models/c_rocketlauncher/p_rocketlauncher_albedo'),
            _lookup('patterns/combat/c_rocketlauncher_flyingtigers'),
            _lookup('patterns/paint_scratches')]}
        self.assertTrue(_drawn_whole(warhawk))
        self.assertFalse(_drawn_whole(CURRENT_EVENT))


class CatalogTests(unittest.TestCase):
    def _session(self, own):
        from src.app.session import AppSession
        from src.domain.preview.session import PreviewSession
        from src.app.paintkit_editor import PaintkitEditor
        s = PaintkitEditor(AppSession.__new__(AppSession))
        s._host.preview = PreviewSession(custom_vpk_mode=True, custom_vpk_weapon='c_rocketlauncher')
        s._host.tf2_paths = lambda: {'root': 'C:/tf2'}
        s._own_paintkits = lambda root, lang='ru': list(own)
        return s

    def test_other_weapons_skins_follow_own_paints(self):
        deco = [{'id': 53, 'decorated': True}, {'id': 9, 'decorated': True}]
        with patch('src.data.paintkit_defs.decorated_kits', return_value=deco):
            got = self._session([{'id': 9}, {'id': 1}]).paintkits()
        self.assertEqual(got, {'items': [{'id': 9}, {'id': 1}, deco[0]], 'generic': False})

    def test_universal_mode_gets_them_all(self):
        deco = [{'id': 53, 'decorated': True}]
        with patch('src.data.paintkit_defs.decorated_kits', return_value=deco), \
             patch('src.data.paintkit_defs.generic_kits', return_value=[{'id': 2}]):
            got = self._session([]).paintkits()
        self.assertEqual(got, {'items': [{'id': 2}, deco[0]], 'generic': True})


class LayoutTests(unittest.TestCase):
    def test_looks_are_layers_with_their_own_swatches(self):
        from src.services.paintkit_layout import describe
        colors = {'patterns/solid_black_02': 0, 'patterns/powerhouse/electric_purple': 200,
                  'patterns/solid_bright_lavender': 120}

        def loader(path, raw=False):
            if path == GROUPS:
                return _mask({3: 6, 2: 3, 5: 1})
            v = colors.get(path, 255)
            return np.full((8, 8, 4), (v, v, v, 255), np.uint8)

        tri = lambda x: ((x, 0.0), (x + 0.2, 0.0), (x, 0.2))  # noqa: E731
        parts = [SimpleNamespace(index=i, uv_area=a, paintable=True, triangles=[i])
                 for i, a in enumerate([0.6, 0.3, 0.1])]
        model = SimpleNamespace(parts_of=lambda m: parts,
                                polygons=lambda m, i: [tri(0.3 * i)],
                                tri_island={}, uv={'m': [tri(0.0), tri(0.3), tri(0.6)]})
        kit = SimpleNamespace(operation=None, header=SimpleNamespace(defindex=53))
        defs = SimpleNamespace(recipe=lambda k, i, w, strip_stickers=False: CURRENT_EVENT)
        with tempfile.TemporaryDirectory() as tmp:
            res = describe(defs, kit, SimpleNamespace(item_def=53), model, 'm', False,
                           loader, loader, tmp)
            self.assertEqual([l['n'] for l in res['layers']], [0, 1, 2])
            self.assertTrue(all(os.path.isfile(l['swatch']) for l in res['layers']))
            self.assertEqual(len({l['color'] for l in res['layers']}), 3)
        # Крупная деталь - самому частому виду оригинала (молнии, 60 %)
        self.assertEqual([u['layer'] for u in res['units']], [2, 1, 0])


if __name__ == '__main__':
    unittest.main()
