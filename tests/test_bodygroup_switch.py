"""
Переключатель состояния модели в превью (бодигруппы).

`$bodygroup` — переключатель, который игра дёргает сама: бутылка после крита
разбитая, у кабера отлетает набалдашник. Превью показывало только нулевой
вариант; теперь можно посмотреть каждый — только показ, в мод уходят все.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.app.session import AppSession, _variant_label
from src.services.preview_3d_worker import Preview3DWorker

BOTTLE_QC = ('$bodygroup "broken"\n{\n\tstudio "c_bottle.smd"\n'
             '\tstudio "c_bottle_broken.smd"\n}\n')
CABER_QC = ('$bodygroup "body"\n{\n\tstudio "c_caber_reference.smd"\n}\n'
            '$bodygroup "broken"\n{\n\tstudio "caber_top_bodygroup.smd"\n'
            '\tstudio "caber_exploded_bodygroup.smd"\n}\n')


class _Model:
    def __init__(self, qc_path):
        self.qc_path = qc_path


def _decompiled(tmp: str, name: str, qc: str, smds) -> str:
    folder = os.path.join(tmp, name)
    os.makedirs(folder)
    for smd in smds:
        with open(os.path.join(folder, smd), 'w', encoding='utf-8') as f:
            f.write('version 1\n')
    qc_path = os.path.join(folder, name + '.qc')
    with open(qc_path, 'w', encoding='utf-8') as f:
        f.write(qc)
    return qc_path


def _worker(bodygroups=None) -> Preview3DWorker:
    return Preview3DWorker(weapon_key='c_bottle', mode='demoman_c_bottle',
                           misc_vpk_path='m.vpk', textures_vpk_path='t.vpk',
                           bodygroups=bodygroups)


class WorkerChoiceTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name

    def tearDown(self):
        self._dir.cleanup()

    def _names(self, paths):
        return sorted(os.path.basename(p) for p in paths)

    def test_bottle_by_default_is_whole_and_broken_replaces_the_reference(self):
        qc = _decompiled(self.tmp, 'c_bottle', BOTTLE_QC,
                         ['c_bottle.smd', 'c_bottle_broken.smd'])
        ref = os.path.join(os.path.dirname(qc), 'c_bottle.smd')

        w = _worker()
        w._models[os.path.dirname(qc)] = _Model(qc)
        extra = w._find_bodygroup_smds(ref)
        self.assertEqual(self._names(extra), [])          # целая — сам reference
        self.assertEqual(w._swap_reference_for_choice(ref, extra), ref)

        w = _worker({'broken': 1})
        w._models[os.path.dirname(qc)] = _Model(qc)
        extra = w._find_bodygroup_smds(ref)
        self.assertEqual(self._names(extra), ['c_bottle_broken.smd'])
        main = w._swap_reference_for_choice(ref, extra)
        self.assertEqual(os.path.basename(main), 'c_bottle_broken.smd')
        self.assertEqual(extra, [])                       # стала основным мешем

    def test_caber_shows_one_head_at_a_time_even_though_both_are_bodygroup_files(self):
        """По маске *_bodygroup.smd находились ОБА набалдашника — и кабер
        стоял целым и взорванным разом."""
        qc = _decompiled(self.tmp, 'c_caber', CABER_QC,
                         ['c_caber_reference.smd', 'caber_top_bodygroup.smd',
                          'caber_exploded_bodygroup.smd'])
        ref = os.path.join(os.path.dirname(qc), 'c_caber_reference.smd')

        w = _worker()
        w._models[os.path.dirname(qc)] = _Model(qc)
        self.assertEqual(self._names(w._find_bodygroup_smds(ref)),
                         ['caber_top_bodygroup.smd'])

        w = _worker({'broken': 1})
        w._models[os.path.dirname(qc)] = _Model(qc)
        extra = w._find_bodygroup_smds(ref)
        self.assertEqual(self._names(extra), ['caber_exploded_bodygroup.smd'])
        self.assertEqual(w._swap_reference_for_choice(ref, extra), ref)


class SessionSwitchTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.qc = _decompiled(self._dir.name, 'c_bottle', BOTTLE_QC,
                              ['c_bottle.smd', 'c_bottle_broken.smd'])
        self.s = AppSession()
        self.s._mode = 'demoman_c_bottle'
        self.s.preview.weapon_key = 'c_bottle'
        patches = [
            patch('src.services.decompile_cache.find_cached_qc_for_weapon',
                  lambda key: self.qc if key == 'c_bottle' else None),
            patch.object(self.s.controller, 'load_game_model'),
            patch.object(type(self.s), 'tf2_paths', staticmethod(
                lambda: {'root': 'r', 'misc_vpk': 'm', 'textures_vpk': 't'})),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._dir.cleanup()

    def test_states_are_listed_with_readable_labels(self):
        self.assertEqual(self.s.bodygroups(), [
            {'name': 'broken', 'chosen': 0, 'variants': ['основной', 'разбитая']}])

    def test_switching_reloads_the_model_with_the_choice(self):
        res = self.s.set_bodygroup('broken', 1)
        self.assertNotIn('error', res)
        self.assertEqual(res['bodygroups'][0]['chosen'], 1)
        kw = self.s.controller.load_game_model.call_args.kwargs
        self.assertEqual(kw['bodygroups'], {'broken': 1})
        # Назад к основному — выбор снимается, а не хранится нулём.
        self.s.set_bodygroup('broken', 0)
        self.assertEqual(self.s._bodygroups, {})
        self.assertIn('error', self.s.set_bodygroup('broken', 5))
        self.assertIn('error', self.s.set_bodygroup('nope', 0))

    def test_parts_wait_for_the_main_state(self):
        self.s._bodygroups = {'broken': 1}
        self.s._obj_path = __file__            # хоть какой-то файл: до разбора не дойдёт
        with patch('src.services.mesh_parts_service.load', return_value=MagicMock()):
            self.assertIn('error', self.s._parts_model(''))

    def test_no_switch_for_own_model_or_other_kinds(self):
        self.s.preview.custom_smd_path = self.qc
        self.assertEqual(self.s.bodygroups(), [])
        self.s.preview.custom_smd_path = None
        self.s._mode = 'scout_body'
        self.assertEqual(self.s.bodygroups(), [])


class LabelTests(unittest.TestCase):
    def test_known_words_and_fallbacks(self):
        self.assertEqual(_variant_label('C:/x/c_bottle.smd', 'c_bottle'), 'основной')
        self.assertEqual(_variant_label('C:/x/c_bottle_broken.smd', 'c_bottle'), 'разбитая')
        self.assertEqual(_variant_label('C:/x/caber_exploded_bodygroup.smd', 'c_caber'),
                         'после взрыва')
        self.assertEqual(_variant_label('C:/x/caber_top_bodygroup.smd', 'c_caber'), 'caber_top')
        self.assertEqual(_variant_label(None, 'c_caber'), 'без части')


if __name__ == '__main__':
    unittest.main()
