"""
Сохранение работы над предметом: что считается правкой и как она переживает
перезапуск.

Главное правило, ради которого всё и делалось: производное (имена материалов,
игровые оригиналы, кадры команд) в работу НЕ попадает — оно приезжает заново с
моделью, а сохранённое замёрзло бы путями во временные папки.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.domain.preview.session import PreviewSession
from src.services import work_keeper, work_store
from src.shared.constants import Team


class UserEditsTests(unittest.TestCase):
    """Граница «моё / производное» в домене."""

    def _session(self) -> PreviewSession:
        s = PreviewSession()
        # Правки человека.
        s.textures.set_texture('scattergun', 'C:/my/skin.png')
        s.texture_maps['scattergun'] = {'rimlight': {'enabled': True}}
        s.texture_overrides['scattergun'] = {'size': [1024, 1024]}
        s.custom_qc_text = '$modelname "a.mdl"'
        # Производное: приедет с моделью заново.
        s.textures.material_names = ['scattergun', 'scattergun_extra']
        s.textures.vpk_red_tex_map = {'scattergun': 'C:/temp/game.png'}
        s.textures.red_frames = ['C:/temp/frame0.png']
        s.misc_materials = ['eyeball_r']
        s.current_object = ('mode', 'C:/temp/model.obj', 'C:/temp/tex.png')
        return s

    def test_derived_data_never_gets_saved(self):
        edits = self._session().user_edits()
        flat = json.dumps(edits, ensure_ascii=False)
        for leaked in ('material_names', 'vpk_red_tex_map', 'red_frames',
                       'misc_materials', 'current_object', 'game.png',
                       'frame0.png', 'model.obj'):
            self.assertNotIn(leaked, flat, leaked)

    def test_edits_survive_a_round_trip(self):
        edits = self._session().user_edits()
        back = PreviewSession()
        back.apply_user_edits(edits)
        self.assertEqual(back.textures.textures[Team.RED]['scattergun'],
                         'C:/my/skin.png')
        self.assertEqual(back.texture_maps['scattergun'],
                         {'rimlight': {'enabled': True}})
        self.assertEqual(back.texture_overrides['scattergun'],
                         {'size': [1024, 1024]})
        self.assertEqual(back.custom_qc_text, '$modelname "a.mdl"')

    def test_style_keys_survive_json(self):
        """Ключи стилей — числа, а в JSON станут строками."""
        s = PreviewSession()
        s.textures.skin_info = {'num_skins': 2}
        s.textures.active_skin = 1
        s.textures.set_texture('mat', 'C:/my/style.png')
        edits = json.loads(json.dumps(s.user_edits()))
        back = PreviewSession()
        back.apply_user_edits(edits)
        self.assertEqual(back.textures.skin_overrides[1]['mat'], 'C:/my/style.png')

    def test_empty_session_has_nothing_to_save(self):
        self.assertFalse(PreviewSession().has_user_edits())
        self.assertTrue(self._session().has_user_edits())

    def test_forgetting_clears_only_the_edits(self):
        s = self._session()
        s.forget_user_edits()
        self.assertFalse(s.has_user_edits())
        # Производное осталось: модель на экране никуда не делась.
        self.assertEqual(s.textures.material_names,
                         ['scattergun', 'scattergun_extra'])


class WorkStoreTests(unittest.TestCase):
    """Хранилище: владение файлами, пропажи, версия формата."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(work_store, 'WORK_DIR',
                                   Path(self._tmp.name) / 'work')
        self._patch.start()
        self.key = work_store.key_for('scout_c_scattergun', 'c_scattergun')

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _texture(self, name: str = 'skin.png') -> str:
        path = Path(self._tmp.name) / name
        path.write_bytes(b'png')
        return str(path)

    def test_key_is_filesystem_safe(self):
        """Ключом бывает путь к MDL — в имя папки его класть нельзя как есть."""
        key = work_store.key_for('hat', 'models/player/items/scout/hat.mdl')
        self.assertNotIn('/', key)
        self.assertNotIn('\\\\', key)

    def test_referenced_files_are_copied_next_to_the_work(self):
        """Текстура пришла через браузер и лежит во временной папке системы:
        оставить ссылку на неё — значит потерять работу при первой чистке."""
        source = self._texture()
        work_store.save(self.key, {'textures': {'red': {'mat': source}}})
        saved = work_store.load(self.key)['textures']['red']['mat']
        self.assertNotEqual(saved, source)
        self.assertTrue(Path(saved).is_file())
        Path(source).unlink()
        self.assertTrue(Path(work_store.load(self.key)['textures']['red']['mat']).is_file())

    def test_part_images_are_copied_too(self):
        """Картинка части лежит там же, где любая другая присланная страницей:
        без копии «покрасил ствол» терялось бы вместе с исходником."""
        source = self._texture()
        work_store.save(self.key, {'part_textures': {'mat': {'1': source}}})
        saved = work_store.load(self.key)['part_textures']['mat']['1']
        self.assertNotEqual(saved, source)
        self.assertTrue(Path(saved).is_file())

    def test_saving_twice_does_not_pile_up_copies(self):
        source = self._texture()
        work_store.save(self.key, {'textures': {'red': {'mat': source}}})
        first = work_store.load(self.key)
        work_store.save(self.key, first)
        files = list((Path(self._tmp.name) / 'work' / self.key / 'files').iterdir())
        self.assertEqual(len(files), 1)

    def test_vanished_files_are_dropped_not_fatal(self):
        source = self._texture()
        work_store.save(self.key, {'textures': {'red': {'mat': source}}})
        for file in (Path(self._tmp.name) / 'work' / self.key / 'files').iterdir():
            file.unlink()
        self.assertEqual(work_store.load(self.key)['textures']['red'], {})

    def test_another_format_version_is_ignored(self):
        """Правила «моё/производное» могли разойтись: молча применённый чужой
        формат хуже отсутствия работы."""
        work_store.save(self.key, {'force_team': True})
        path = Path(self._tmp.name) / 'work' / self.key / 'edits.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['format'] = work_store.FORMAT + 1
        path.write_text(json.dumps(payload), encoding='utf-8')
        self.assertIsNone(work_store.load(self.key))

    def test_forget_takes_the_files_too(self):
        work_store.save(self.key, {'textures': {'red': {'mat': self._texture()}}})
        self.assertTrue(work_store.forget(self.key))
        self.assertFalse(work_store.has(self.key))
        self.assertIsNone(work_store.load(self.key))

    def test_nothing_saved_means_nothing_loaded(self):
        self.assertIsNone(work_store.load('никогда-не-было'))
        self.assertFalse(work_store.has('никогда-не-было'))


class KeeperRulesTests(unittest.TestCase):
    """Правила «когда сохранять» — общие у окна и страницы."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = patch.object(work_store, 'WORK_DIR', Path(self._tmp.name) / 'work')
        self._dir.start()
        self._on = patch.object(work_keeper, 'is_enabled', lambda: True)
        self._on.start()

    def tearDown(self):
        self._on.stop()
        self._dir.stop()
        self._tmp.cleanup()

    def test_unidentified_item_has_no_key(self):
        self.assertEqual(work_keeper.key_for('', ''), '')
        self.assertEqual(work_keeper.key_for('scout_c_scattergun', ''), '')
        # chr(0) — sentinel панели «модель ещё не грузили».
        self.assertEqual(work_keeper.key_for('scout_c_scattergun', chr(0)), '')
        self.assertTrue(work_keeper.key_for('scout_c_scattergun', 'c_scattergun'))

    def test_mod_and_weapon_do_not_share_a_key(self):
        """Мод показан поверх оружия, но работа над ним — своя."""
        weapon = work_keeper.key_for('scout_c_scattergun', 'c_scattergun')
        mod = work_keeper.key_for('custom', 'c_scattergun', 'mods/skin.vpk')
        self.assertNotEqual(weapon, mod)
        self.assertIn('skin.vpk', mod.replace('_vpk', '.vpk'))

    def test_mod_without_a_file_has_no_key(self):
        self.assertEqual(work_keeper.key_for('custom', 'c_scattergun'), '')

    def test_save_and_restore_go_through_the_session(self):
        source = PreviewSession()
        source.textures.set_texture('mat', __file__)
        key = work_keeper.key_for('scout_c_scattergun', 'c_scattergun')
        self.assertTrue(work_keeper.save(source, key))

        target = PreviewSession()
        self.assertTrue(work_keeper.restore(target, key))
        self.assertTrue(target.textures.textures[Team.RED]['mat'])

    def test_switched_off_neither_saves_nor_restores(self):
        """«Я выключил, а оно всё равно подставляет вчерашнее» — не то."""
        session = PreviewSession()
        session.textures.set_texture('mat', __file__)
        key = work_keeper.key_for('scout_c_scattergun', 'c_scattergun')
        work_keeper.save(session, key)

        with patch.object(work_keeper, 'is_enabled', lambda: False):
            self.assertFalse(work_keeper.save(session, key))
            self.assertFalse(work_keeper.restore(PreviewSession(), key))


if __name__ == '__main__':
    unittest.main()
