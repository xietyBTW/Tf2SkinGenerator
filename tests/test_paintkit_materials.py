"""
War Paint на оружии из нескольких материалов

У каждого отмеченного материала своя сборка по его деталям и развёртке, а не
один узор под главный материал: иначе остальные материалы своей модели (и все
материалы оружия без War Paint в игре, кроме первого) остались бы некрашеными
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.app.paintkit_editor import PaintkitEditor
from src.app.session import AppSession
from src.domain.preview.session import PreviewSession
from src.services.paintkit_worker import PaintkitBatch

LAYERED = {'id': 7, 'item': 15, 'by_parts': True}
HAND_MADE = {'id': 8, 'item': 15, 'by_parts': False}


def _meshes(model, card):
    """Меш назван как карточка, только регистр другой (как бывает в OBJ)"""
    return card.upper(), card


def _session(cards, own=(), game=(), layout=None):
    """Редактор War Paint на сеансе без __init__: поля сеанса - по месту"""
    s = PaintkitEditor(AppSession.__new__(AppSession))
    s._host.preview = PreviewSession()
    s._host.preview.textures.material_names = list(cards)
    s._host.preview.custom_vpk_mode, s._host.preview.custom_vpk_weapon = True, 'c_detonator'
    if layout:
        s._host.preview.paintkit_layouts['7'] = layout
    s._host.tf2_paths = lambda: {'root': 'C:/tf2', 'textures_vpk': '', 'misc_vpk': ''}
    s._own_paintkits = lambda root, lang='ru': list(own)
    s._game_cards = lambda paths, item: list(game)
    s._host._obj_path = ''
    s._host.parts = SimpleNamespace(_mesh_of=_meshes)
    return s


def _plans(s, kit=7, materials=None):
    with patch('src.services.mesh_parts_service.load', return_value=object()):
        plans = s._paintkit_plans(kit, 15, 0, materials)
    if isinstance(plans, dict):
        return plans
    return [(cards, generic and generic['obj_material'], generic and generic['assign'])
            for cards, generic, _forced, _tag in plans]


class GamePaintTests(unittest.TestCase):
    def test_default_is_like_in_game(self):
        s = _session(['c_det', 'c_det_shell', 'c_det_lens'], own=[LAYERED],
                     game=['c_det', 'c_det_shell'])
        self.assertEqual(_plans(s), [(['c_det', 'c_det_shell'], None, None)])

    def test_other_material_gets_its_own_parts(self):
        s = _session(['c_det', 'c_det_lens'], own=[LAYERED], game=['c_det'],
                     layout={'p1': 2})
        self.assertEqual(_plans(s, materials=['c_det', 'c_det_lens']),
                         [(['c_det'], None, None), (['c_det_lens'], 'C_DET_LENS', None)])

    def test_hand_made_recipe_stays_where_the_game_puts_it(self):
        s = _session(['c_det', 'c_det_lens'], own=[HAND_MADE], game=['c_det'])
        self.assertEqual(_plans(s, kit=8, materials=['c_det', 'c_det_lens']),
                         [(['c_det'], None, None)])
        self.assertIn('error', _plans(s, kit=8, materials=['c_det_lens']))


class UniversalTests(unittest.TestCase):
    def test_every_material_by_default(self):
        s = _session(['body', 'scope'], layout={'p1': 2})
        self.assertEqual(_plans(s), [(['body'], 'BODY', {'p1': 2}),
                                     (['scope'], 'SCOPE', None)])

    def test_unchecked_material_is_left_alone(self):
        s = _session(['body', 'glass'])
        self.assertEqual(_plans(s, materials=['body']), [(['body'], 'BODY', None)])

    def test_nothing_checked(self):
        self.assertIn('error', _plans(_session(['body', 'glass']), materials=[]))

    def test_card_without_its_own_mesh_is_not_offered(self):
        """Вставка HUD или материал $texturegroup вне модели: меша нет"""
        s = _session(['body', 'smiley'])
        s._host.parts = SimpleNamespace(_mesh_of=lambda model, card: (
            ('BODY', 'body') if card == 'body' else {'error': 'нет геометрии'}))
        self.assertEqual(_plans(s), [(['body'], 'BODY', None)])

    def test_single_mesh_mod_does_not_paint_its_garland_lights(self):
        """У одноматериальной модели любая карточка находит единственный меш"""
        s = _session(['c_ambassador', 'festive_lights_red'])
        s._host.parts = SimpleNamespace(_mesh_of=lambda model, card: ('C_Ambassador', 'c_ambassador'))
        self.assertEqual(_plans(s), [(['c_ambassador'], 'C_Ambassador', None)])

    def test_part_material_takes_its_source_picture(self):
        s = _session(['body', 'scope'])
        s._host.preview.textures.part_cards = {'body_part1': 'body'}
        self.assertEqual(_plans(s), [(['body', 'body_part1'], 'BODY', None),
                                     (['scope'], 'SCOPE', None)])
        self.assertEqual(_plans(s, materials=['body_part1']),
                         [(['body_part1'], 'BODY', None)])

    def test_part_of_a_game_material_gets_the_recipe(self):
        s = _session(['c_det', 'c_det_lens'], own=[LAYERED], game=['c_det'])
        s._host.preview.textures.part_cards = {'c_det_part1': 'c_det'}
        self.assertEqual(_plans(s), [(['c_det', 'c_det_part1'], None, None)])

    def test_materials_list_for_panel(self):
        s = _session(['c_det', 'c_det_lens'], own=[LAYERED], game=['c_det'])
        s._host.preview.textures.part_cards = {'c_det_part1': 'c_det'}
        with patch('src.services.mesh_parts_service.load', return_value=object()):
            got = s.paintkit_materials(15)['materials']
        self.assertEqual(got, [{'card': 'c_det', 'game': True, 'parts': True},
                               {'card': 'c_det_part1', 'game': True, 'parts': True},
                               {'card': 'c_det_lens', 'game': False, 'parts': True}])

    def test_game_card_without_mesh_is_not_laid_by_parts(self):
        """Скин с другой пушки ложится по деталям: карточке игры без меша - нет"""
        s = _session(['c_det', 'c_det_shell'], own=[LAYERED], game=['c_det', 'c_det_shell'])
        s._host.parts = SimpleNamespace(_mesh_of=lambda model, card: (
            ('C_DET', card) if card == 'c_det' else {'error': 'нет геометрии'}))
        with patch('src.services.mesh_parts_service.load', return_value=object()):
            got = s.paintkit_materials(15)['materials']
        self.assertEqual([m['parts'] for m in got], [True, False])
        # Чужой скин (не из своих War Paint) - по деталям, гильзы в плане нет
        self.assertEqual(_plans(s, kit=53, materials=['c_det', 'c_det_shell']),
                         [(['c_det'], 'C_DET', None)])


class TiledUvTests(unittest.TestCase):
    """Развёртка в соседней плитке (линза Базарной безделушки: u от 1 до 2)"""

    def test_other_tile_lands_on_canvas(self):
        from src.services.paintkit_generic import _rasterize
        img = _rasterize([(9, [[(1.1, 0.1), (1.9, 0.1), (1.5, 0.9)]])], 16)
        self.assertGreater(int((img == 9).sum()), 20)

    def test_triangle_over_the_edge_wraps(self):
        from src.services.paintkit_generic import _rasterize
        img = _rasterize([(9, [[(0.8, 0.2), (1.2, 0.2), (1.0, 0.8)]])], 20)
        self.assertTrue(img[:, :2].any() and img[:, -2:].any())


class _Job:
    def __init__(self, ok, out, missing=()):
        self.result, self.missing = (ok, out), list(missing)
        self.progress = SimpleNamespace(connect=lambda slot: None)

    def work(self):
        return self.result


class BatchTests(unittest.TestCase):
    def test_collects_every_material(self):
        b = PaintkitBatch([(['a'], _Job(True, 'a.png', ['x'])),
                           (['b'], _Job(True, 'b.png', ['x', 'y']))])
        self.assertEqual(b.work(), (True, ''))
        self.assertEqual((b.done, b.missing), ([(['a'], 'a.png'), (['b'], 'b.png')], ['x', 'y']))

    def test_one_failure_stops_the_rest(self):
        b = PaintkitBatch([(['a'], _Job(False, 'нет развёртки')), (['b'], _Job(True, 'b.png'))])
        self.assertEqual(b.work(), (False, 'нет развёртки'))
        self.assertEqual(b.done, [])


class ApplyTests(unittest.TestCase):
    """Нанесение: всё одним шагом отмены, а не легло на одну - ни на какую"""

    def _apply(self, refuse=()):
        s = _session(['body', 'scope'])
        s._host._work_dir = lambda: 'C:/tmp'
        s._paintkit_job_for = lambda *args: None
        events, undo, steps, set_cards = [], [], [], []
        s._host._put = lambda event, **kw: events.append((event, kw))
        s._host.undo_edits = lambda delta=-1, lang='ru': undo.append(delta)
        s._host._autosave = lambda step=True: steps.append(step)

        def set_texture(card, png):
            set_cards.append(card)
            return {'error': 'нельзя'} if card in refuse else {}
        s._host.set_texture = set_texture

        class Batch:
            def __init__(self, jobs):
                self.done = [(cards, cards[0] + '.png') for cards, _ in jobs]
                self.missing, self._done = [], None
                self.progress = SimpleNamespace(connect=lambda slot: None)
                self.finished = SimpleNamespace(connect=self._keep)

            def _keep(self, slot):
                self._done = slot

            def isRunning(self):
                return False

            def start(self):
                self._done(True, '')

        with patch('src.services.mesh_parts_service.load', return_value=object()), \
             patch('src.services.paintkit_worker.PaintkitBatch', Batch):
            s.apply_paintkit(7, 15)
        return events[-1][1]['ok'], set_cards, steps, undo

    def test_every_card_one_step(self):
        self.assertEqual(self._apply(), (True, ['body', 'scope'], [True], []))

    def test_refused_card_rolls_back_the_rest(self):
        self.assertEqual(self._apply(refuse=('scope',)), (False, ['body', 'scope'], [], [0]))


class UndoTests(unittest.TestCase):
    def test_held_edits_make_one_step(self):
        s = AppSession.__new__(AppSession)
        s.preview = PreviewSession()
        commits = []
        s._edits_commit = lambda: commits.append(1)
        s._work_key, s._style_snapshots, s._item_id = (lambda: None,) * 3
        from unittest.mock import patch
        with patch('src.services.work_keeper.save'):
            s._edits_held = True
            s._autosave()
            s._autosave()
            s._edits_held = False
            s._autosave()
        self.assertEqual(commits, [1])


if __name__ == '__main__':
    unittest.main()
