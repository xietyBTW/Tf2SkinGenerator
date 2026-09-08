"""
Сохранённые работы — отдельный список, а не наложение на каталог.

Раньше открытие «Обреза» из списка оружия молча возвращало ПРОШЛУЮ работу над
ним: человек выбирал игровой предмет, а получал свой, и вернуться к игровому
мог только через «Забыть правки». Теперь список оружия показывает игру, а
работы живут в разделе «Кастомный мод» — сюда и приходит `restore`.

И попадают туда не все: автосохранение пишет черновик на каждое движение, так
что «просто потыкал» становилось модом. В библиотеке видно только то, что
человек сохранил сам — метка `kept`.
"""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.services import work_keeper, work_store


class ListSavedTests(unittest.TestCase):
    def _folder(self, root: Path, name: str, when: float,
                edits: bool = True, kept: bool = True):
        folder = root / name
        folder.mkdir()
        if edits:
            path = folder / 'edits.json'
            path.write_text(json.dumps({'edits': {}}), encoding='utf-8')
            import os
            os.utime(path, (when, when))
        if kept:
            (folder / work_store.KEPT).write_bytes(b'')

    def test_lists_only_folders_with_edits_newest_first(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._folder(root, 'hat__demo', 1000.0)
            self._folder(root, 'c_scattergun__c_scattergun', 2000.0)
            # Остаток прерванной записи: папка есть, работы нет.
            self._folder(root, 'c_knife__c_knife', 0.0, edits=False)
            with mock.patch.object(work_store, 'WORK_DIR', root):
                keys = [w['key'] for w in work_store.list_saved()]
            self.assertEqual(keys, ['c_scattergun__c_scattergun', 'hat__demo'])

    def test_draft_nobody_saved_stays_out_of_the_library(self):
        """Открыл предмет, что-то тронул — это ещё не мод."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._folder(root, 'c_knife__c_knife', 3000.0, kept=False)
            self._folder(root, 'hat__demo', 1000.0)
            with mock.patch.object(work_store, 'WORK_DIR', root):
                keys = [w['key'] for w in work_store.list_saved()]
                self.assertFalse(work_store.is_kept('c_knife__c_knife'))
            self.assertEqual(keys, ['hat__demo'])

    def test_keep_marks_an_existing_draft_and_forget_unmarks_it(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._folder(root, 'hat__demo', 1000.0, kept=False)
            with mock.patch.object(work_store, 'WORK_DIR', root):
                self.assertTrue(work_store.keep('hat__demo'))
                self.assertTrue(work_store.is_kept('hat__demo'))
                self.assertEqual([w['key'] for w in work_store.list_saved()],
                                 ['hat__demo'])
                work_store.forget('hat__demo')
                self.assertFalse(work_store.is_kept('hat__demo'))
                self.assertEqual(work_store.list_saved(), [])

    def test_keep_without_a_draft_saves_nothing(self):
        """Метка при пустой папке сделала бы работу-призрак в библиотеке."""
        with TemporaryDirectory() as tmp:
            with mock.patch.object(work_store, 'WORK_DIR', Path(tmp)):
                self.assertFalse(work_store.keep('hat__demo'))
                self.assertEqual(work_store.list_saved(), [])

    def test_missing_folder_is_not_an_error(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.object(work_store, 'WORK_DIR', Path(tmp) / 'нет'):
                self.assertEqual(work_store.list_saved(), [])


class WorksApiTests(unittest.TestCase):
    def test_card_carries_human_name_and_how_to_open_it(self):
        from src.app import api

        saved = [{'key': 'c_scattergun__c_scattergun', 'saved_at': 2000.0}]
        with mock.patch.object(work_store, 'list_saved', return_value=saved):
            card, = api.works('ru')
        self.assertEqual(card['name'], 'Обрез')
        self.assertEqual(card['mode'], 'c_scattergun')
        self.assertEqual(card['type'], 'work')
        self.assertEqual(card['icon'], 'c_scattergun')

    def test_unknown_key_shows_the_key_instead_of_hiding_the_work(self):
        from src.app import api

        saved = [{'key': 'c_ничего__c_ничего', 'saved_at': 1.0}]
        with mock.patch.object(work_store, 'list_saved', return_value=saved):
            card, = api.works('ru')
        self.assertEqual(card['name'], 'c_ничего')


class _Preview:
    """Ровно то, что keeper спрашивает у превью."""

    def __init__(self, edits):
        self.edits = edits
        self.applied = None

    def has_user_edits(self):
        return bool(self.edits)

    def user_edits(self):
        return self.edits

    def apply_user_edits(self, edits):
        self.applied = edits


class KeeperTests(unittest.TestCase):
    """Выключатель молчаливой записи не должен запрещать нажатую кнопку."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(work_store, 'WORK_DIR', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        off = mock.patch.object(work_keeper, 'is_enabled', return_value=False)
        off.start()
        self.addCleanup(off.stop)

    def test_keep_writes_and_marks_even_with_autosave_off(self):
        preview = _Preview({'part_tint': 0.5})
        self.assertTrue(work_keeper.keep(preview, 'hat__demo'))
        self.assertEqual([w['key'] for w in work_store.list_saved()], ['hat__demo'])

    def test_keep_refuses_when_there_are_no_edits(self):
        self.assertFalse(work_keeper.keep(_Preview({}), 'hat__demo'))
        self.assertEqual(work_store.list_saved(), [])

    def test_asked_restore_ignores_the_switch_silent_one_obeys_it(self):
        work_keeper.keep(_Preview({'part_colors': {'m': {'0': '#ffffff'}}}),
                         'hat__demo')
        empty = _Preview({})
        self.assertFalse(work_keeper.restore(empty, 'hat__demo'))
        self.assertIsNone(empty.applied)
        self.assertTrue(work_keeper.restore(empty, 'hat__demo', asked=True))
        self.assertEqual(empty.applied.get('part_colors'),
                         {'m': {'0': '#ffffff'}})


class ForgetDraftsTests(unittest.TestCase):
    """Уборка черновиков: до неё добраться было нечем.

    Черновик пишется молча на каждое движение, в библиотеке его нет намеренно,
    и удалить его можно было только заново открыв тот же предмет.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(work_store, 'WORK_DIR', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _work(self, key: str, kept: bool = False) -> None:
        work_store.save(key, {'part_colors': {'m': {'0': '#ffffff'}}})
        if kept:
            work_store.keep(key)

    def _session(self, key: str = ''):
        from src.app.session import AppSession

        app = AppSession()
        app._work_key = lambda: key
        return app

    def test_all_drafts_go_saved_works_stay(self):
        self._work('scout_c_scattergun__c_scattergun')
        self._work('hat__demo', kept=True)

        res = self._session().forget_drafts()
        self.assertEqual(res['removed'], 1)
        self.assertFalse(res['reset'])
        self.assertEqual(work_store.list_drafts(), [])
        self.assertEqual([w['key'] for w in work_store.list_saved()], ['hat__demo'])

    def test_only_the_named_drafts_go(self):
        self._work('a__a')
        self._work('b__b')

        res = self._session().forget_drafts(['a__a'])
        self.assertEqual(res['removed'], 1)
        self.assertEqual([w['key'] for w in work_store.list_drafts()], ['b__b'])

    def test_a_saved_work_cannot_be_deleted_as_a_draft(self):
        """Список присылает страница — опечатка в нём не должна стоить работы."""
        self._work('hat__demo', kept=True)
        res = self._session().forget_drafts(['hat__demo'])
        self.assertEqual(res['removed'], 0)
        self.assertTrue(work_store.has('hat__demo'))

    def test_empty_selection_deletes_nothing(self):
        """«Снял все отметки» — это не «удали всё»."""
        self._work('a__a')
        self.assertEqual(self._session().forget_drafts([])['removed'], 0)
        self.assertTrue(work_store.has('a__a'))

    def test_the_open_item_loses_its_edits_too(self):
        """Иначе автосохранение перепишет черновик на следующей же правке."""
        key = 'scout_c_scattergun__c_scattergun'
        self._work(key)
        app = self._session(key)
        app.preview.textures.set_texture('mat', __file__)

        res = app.forget_drafts()
        self.assertEqual(res['removed'], 1)
        self.assertTrue(res['reset'])
        self.assertFalse(app.preview.has_user_edits())
        self.assertFalse(work_store.has(key))


class RealEditsTests(unittest.TestCase):
    """Что именно делает предмет «правленым».

    Признак один на сеанс и на диск: пока их было два, приложение предлагало
    вернуть правки предмету, в котором человек ничего не менял.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.patch = mock.patch.object(work_store, 'WORK_DIR',
                                       Path(self.tmp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_empty_wrappers_are_not_edits(self):
        """Словари команд заводятся сами и пустыми доезжают до диска."""
        from src.domain.preview.session import has_real_edits
        self.assertFalse(has_real_edits({'textures': {'red': {}, 'blu': {}},
                                         'part_colors': {'weapon': {}}}))

    def test_build_settings_alone_are_not_edits(self):
        """Размер и формат VTF текстуру не меняют — «вернуть» там нечего."""
        from src.domain.preview.session import has_real_edits
        self.assertFalse(has_real_edits(
            {'texture_overrides': {'scattergun': {'size': [1024, 1024]}}}))

    def test_a_painted_part_is_an_edit(self):
        from src.domain.preview.session import has_real_edits
        self.assertTrue(has_real_edits({'part_colors': {'w': {'0': '#fff'}}}))

    def test_the_disk_answers_by_content_not_by_the_file(self):
        work_store.save('hat__demo',
                        {'texture_overrides': {'m': {'size': [512, 512]}}})
        self.assertTrue(work_store.has('hat__demo'))       # файл есть
        self.assertFalse(work_store.holds_edits('hat__demo'))  # работы нет


class WorkNamesTests(unittest.TestCase):
    """Как работа подписана в библиотеке и чем открывается."""

    def _rows(self, item: dict) -> dict:
        from src.app import api

        rows = [{'key': 'hat__models_player_items_scout_hat.mdl',
                 'saved_at': 1.0, 'item': item}]
        with mock.patch.object(
                api, '_hat_index',
                lambda lang: {'models/player/items/scout/hat.mdl': ('Шапка', 'backpack/hat')}):
            return api._named(rows, 'ru')[0]

    def test_hat_work_is_named_by_the_catalogue(self):
        """Раньше карточка была подписана слагом пути к модели."""
        row = self._rows({'mode': 'hat',
                          'key': 'models/player/items/scout/hat.mdl',
                          'per_class': {'scout': 'a.mdl'}})
        self.assertEqual(row['name'], 'Шапка')
        # Иконка объявлена в items_game: по имени модели её не найти.
        self.assertEqual(row['item_icon'], 'backpack/hat')
        self.assertEqual(row['item_key'], 'models/player/items/scout/hat.mdl')
        self.assertEqual(row['per_class'], {'scout': 'a.mdl'})
        self.assertEqual(row['work_mode'], 'hat')

    def test_unknown_hat_falls_back_to_the_model_file(self):
        """Предмета в игре нет — имя файла честнее полного пути."""
        row = self._rows({'mode': 'hat', 'key': 'models/player/items/x/lost.mdl'})
        self.assertEqual(row['name'], 'lost')

    def test_old_work_without_identity_still_reads_by_folder(self):
        from src.app import api

        rows = [{'key': 'scout_c_scattergun__c_scattergun', 'saved_at': 1.0}]
        row = api._named(rows, 'ru')[0]
        self.assertEqual(row['work_mode'], 'scout_c_scattergun')
        self.assertEqual(row['work_item'], 'c_scattergun')
        self.assertNotIn('__', row['name'])


class RestoreIsAskedForTests(unittest.TestCase):
    """Умолчание здесь и есть поведение каталога — оно обязано быть «нет»."""

    def test_load_preview_does_not_restore_by_default(self):
        from src.app.session import AppSession

        for name in ('load_preview', '_load_texture_only'):
            got = inspect.signature(getattr(AppSession, name)).parameters
            self.assertIn('restore', got, name)
            self.assertIs(got['restore'].default, False, name)


if __name__ == '__main__':
    unittest.main()
