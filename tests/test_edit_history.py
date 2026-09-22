"""
История правок предмета: Ctrl+Z / Ctrl+Y в редакторе.

Одна лента на всё — текстуры, части, свою модель: две ленты (у частей была
своя) разъезжались, и отменённый в одной мазок другая помнила последним шагом.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.app.session import AppSession


class _Session(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.tex = str(self.tmp / 'skin.png')
        Path(self.tex).write_bytes(b'png')
        self.session = AppSession()
        self.session._mode = 'scout_c_scattergun'
        self.session.preview.weapon_key = 'c_scattergun'
        self.session.preview.textures.material_names = ['weapon']
        # Автосохранение на диск — не предмет проверки.
        p = mock.patch('src.services.work_keeper.save', return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.session._edits_reset()

    def tearDown(self):
        self._dir.cleanup()

    def shown(self):
        return self.session.preview.textures.uploaded_for_mat('weapon')


class UndoRedoTests(_Session):
    def test_fresh_item_has_nothing_to_undo(self):
        self.assertIn('error', self.session.undo_edits(-1))
        self.assertEqual(self.session.edit_history(), {'undo': False, 'redo': False})

    def test_undo_takes_the_texture_off_and_redo_puts_it_back(self):
        self.session.set_texture('weapon', self.tex)
        self.assertEqual(self.shown(), self.tex)
        res = self.session.undo_edits(-1)
        self.assertNotIn('error', res)
        self.assertIsNone(self.shown())
        self.assertTrue(res['redo'])
        self.session.undo_edits(1)
        self.assertEqual(self.shown(), self.tex)

    def test_a_new_edit_forgets_the_way_forward(self):
        self.session.set_texture('weapon', self.tex)
        self.session.undo_edits(-1)
        self.session.force_team()
        self.assertIn('error', self.session.undo_edits(1))

    def test_same_state_twice_is_one_step(self):
        """Правка, не изменившая ничего, не должна стоить нажатия Ctrl+Z."""
        self.session.set_texture('weapon', self.tex)
        self.session.set_texture('weapon', self.tex)
        self.session.undo_edits(-1)
        self.assertIsNone(self.shown())

    def test_history_is_bounded(self):
        for n in range(self.session.EDIT_HISTORY_LIMIT + 10):
            path = str(self.tmp / f'{n}.png')
            Path(path).write_bytes(b'x')
            self.session.set_texture('weapon', path)
        self.assertLessEqual(len(self.session._edit_history),
                             self.session.EDIT_HISTORY_LIMIT)

    def test_new_item_starts_a_new_history(self):
        self.session.set_texture('weapon', self.tex)
        self.session._edits_reset()
        self.assertIn('error', self.session.undo_edits(-1))


class GeometryTests(_Session):
    """Своя модель — тоже правка: её приход и уход откатываются, и кадр
    обязан идти за состоянием."""

    def setUp(self):
        super().setUp()
        self.smd = self.tmp / 'own.smd'
        self.smd.write_text('version 1', encoding='utf-8')
        for target, kw in (
            (self.session, {'attribute': '_custom_model_obj',
                            'return_value': (str(self.tmp / 'own.obj'), ['own'])}),
            (self.session, {'attribute': '_on_model_ready'}),
            (self.session.controller, {'attribute': 'load_game_model'}),
            (self.session.skins, {'attribute': 'detect'}),
        ):
            p = mock.patch.object(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(type(self.session), 'tf2_paths', staticmethod(
            lambda: {'root': 'r', 'misc_vpk': 'm', 'textures_vpk': 't'}))
        p.start()
        self.addCleanup(p.stop)

    def _put_own_model(self):
        p = self.session.preview
        p.custom_smd_path = str(self.smd)
        p.custom_keep_materials = True
        p.custom_obj_path = 'obj-of-this-run'
        self.session._autosave()

    def test_undoing_the_own_model_brings_the_game_one_back(self):
        self._put_own_model()
        self.session.undo_edits(-1)
        self.assertIsNone(self.session.preview.custom_smd_path)
        self.session.controller.load_game_model.assert_called_once()

    def test_redoing_the_own_model_rebuilds_its_geometry(self):
        self._put_own_model()
        self.session.undo_edits(-1)
        self.session.undo_edits(1)
        p = self.session.preview
        self.assertEqual(p.custom_smd_path, str(self.smd))
        self.assertEqual(p.custom_obj_path, str(self.tmp / 'own.obj'))
        self.session._on_model_ready.assert_called_once()

    def test_the_obj_survives_an_unrelated_undo(self):
        """OBJ живёт один запуск: терять его на отмене текстуры нельзя."""
        self._put_own_model()
        self.session.set_texture('own', self.tex)
        self.session.undo_edits(-1)
        self.assertEqual(self.session.preview.custom_obj_path, 'obj-of-this-run')
        self.session._on_model_ready.assert_not_called()


class WorkFilesTests(_Session):
    """Автосохранение убирает из папки работы всё, на что правки больше не
    ссылаются, — а Ctrl+Z обязан вернуть снятую текстуру."""

    def test_snapshot_keeps_its_own_copy_of_a_work_file(self):
        from src.services import work_store

        work = self.tmp / 'work'
        files = work / 'item' / 'files'
        files.mkdir(parents=True)
        inside = files / 'skin.png'
        inside.write_bytes(b'png')
        with mock.patch.object(work_store, 'WORK_DIR', work):
            self.session.set_texture('weapon', str(inside))
            os.remove(inside)                       # так делает `_sweep`
            self.session.set_texture('weapon', None)
            self.session.undo_edits(-1)
        shown = self.shown()
        self.assertTrue(shown and os.path.isfile(shown), shown)
        self.assertNotEqual(shown, str(inside))


if __name__ == '__main__':
    unittest.main()
