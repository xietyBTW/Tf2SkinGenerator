"""
Инструменты прикладного слоя: что проверяется ДО запуска воркера.

Сами воркеры (декомпиляция, извлечение, объединение) тут не гоняются — им
нужна установленная игра. Проверяются решения, которые принимает сеанс:
какие файлы предлагать по умолчанию и что считать негодным запросом.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app import api
from src.app.session import AppSession
from src.services import mod_library_service, work_keeper, work_store
from src.services.extract_model_service import ExtractModelService
from src.shared.constants import Team


class DefaultExportSelectionTests(unittest.TestCase):
    """Что отметить в списке подготовленных файлов модели."""

    def test_reference_smd_wins(self):
        files = ["c_scattergun.qc", "c_scattergun_physics.smd",
                 "c_scattergun_reference.smd", "c_scattergun_reference_lod1.smd"]
        self.assertEqual(ExtractModelService.default_export_selection(files),
                         ["c_scattergun_reference.smd"])

    def test_any_smd_when_reference_is_missing(self):
        files = ["model.qc", "model_physics.smd"]
        self.assertEqual(ExtractModelService.default_export_selection(files),
                         ["model_physics.smd"])

    def test_nothing_to_offer_without_smd(self):
        self.assertEqual(ExtractModelService.default_export_selection(["a.qc"]), [])


class MergeVpkGuardTests(unittest.TestCase):
    """Объединение модов: негодный запрос не должен доходить до воркера."""

    def _session(self, folder: str) -> AppSession:
        """Сеанс с подменённой папкой экспорта и без реального запуска воркера."""
        s = AppSession()
        s._export_settings = staticmethod(lambda: (folder, 'PNG'))
        s.started = []
        s._run_tool = lambda worker, done='tool_done': (
            s.started.append(worker) or {'started': True})
        return s

    def test_one_mod_is_not_a_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._session(tmp).merge_vpk(['a.vpk'], 'out.vpk')
            self.assertIn('error', res)

    def test_name_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._session(tmp).merge_vpk(['a.vpk', 'b.vpk'], '  ')
            self.assertIn('error', res)

    def test_missing_files_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.vpk').write_bytes(b'')
            res = self._session(tmp).merge_vpk(['a.vpk', 'b.vpk'], 'out.vpk')
            self.assertIn('b.vpk', res.get('error', ''))

    def test_path_from_the_page_cannot_leave_the_export_folder(self):
        """Страница присылает ИМЯ; путь собирает Python, иначе «..» увёл бы
        объединение к любому файлу на диске."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.vpk').write_bytes(b'')
            (Path(tmp) / 'b.vpk').write_bytes(b'')
            session = self._session(tmp)
            res = session.merge_vpk(['../../secret/a.vpk', 'b.vpk'], 'out.vpk')
            # '../../secret/a.vpk' сведён к 'a.vpk' — файл внутри папки экспорта.
            self.assertNotIn('error', res)
            self.assertEqual([p.parent for p in session.started[0].vpk_files],
                             [Path(tmp), Path(tmp)])

    def test_files_listed_are_only_vpk(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'mod.vpk').write_bytes(b'')
            (Path(tmp) / 'notes.txt').write_text('x')
            self.assertEqual(self._session(tmp).export_vpks(), ['mod.vpk'])


class CardKeyTests(unittest.TestCase):
    """К какому материалу относится правка карточки."""

    def test_single_texture_key_never_becomes_an_edit_key(self):
        """`__single__` — служебный ключ показа. Правка под ним легла бы в
        хранилище именем, которого сборка не ищет, то есть пропала бы."""
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        s = AppSession()
        s.preview.textures.material_names = [SINGLE_TEX_KEY]
        self.assertEqual(s._card_key(), '')
        self.assertEqual(s._card_key(SINGLE_TEX_KEY), '')

    def test_named_material_is_kept(self):
        s = AppSession()
        s.preview.textures.material_names = ['medic_red', 'medic_head_red']
        self.assertEqual(s._card_key(), 'medic_red')
        self.assertEqual(s._card_key('medic_head_red'), 'medic_head_red')

    def test_maps_need_an_item(self):
        s = AppSession()
        self.assertIn('error', s.set_texture_maps('', {'rimlight': {'enabled': True}}))


class TextureSettingsTests(unittest.TestCase):
    """Свои настройки материала: разреженная запись поверх глобальных."""

    def _session(self) -> AppSession:
        s = AppSession()
        s._mode = 'scout_c_scattergun'
        s.preview.textures.material_names = ['scattergun', 'scattergun_extra']
        return s

    def test_settings_are_stored_per_material(self):
        s = self._session()
        s.set_texture_settings('scattergun_extra',
                               {'size': [1024, 1024], 'format': 'DXT5'})
        self.assertEqual(s.texture_settings('scattergun_extra')['settings'],
                         {'size': [1024, 1024], 'format': 'DXT5'})
        # Соседний материал остаётся на глобальных.
        self.assertEqual(s.texture_settings('scattergun')['settings'], {})

    def test_empty_settings_return_the_material_to_global(self):
        s = self._session()
        s.set_texture_settings('scattergun', {'size': [1024, 1024]})
        s.set_texture_settings('scattergun', None)
        self.assertEqual(s.preview.texture_overrides, {})

    def test_unknown_keys_do_not_reach_the_build(self):
        """В запись попадают только те ключи, которые сборка умеет наложить."""
        s = self._session()
        res = s.set_texture_settings('scattergun',
                                     {'size': [512, 512], 'filename': 'взлом.vpk'})
        self.assertEqual(res['settings'], {'size': [512, 512]})

    def test_badge_shows_resolution_and_format(self):
        s = self._session()
        res = s.set_texture_settings('scattergun',
                                     {'size': [1024, 1024], 'format': 'DXT5'})
        self.assertEqual(res['badge'], '1024 · DXT5')

    def test_switching_item_forgets_settings_and_maps(self):
        """Имена материалов принадлежат предмету: у следующего они чужие."""
        s = self._session()
        s.preview.begin_item('c_scattergun', 'scout_c_scattergun')
        s.set_texture_settings('scattergun', {'size': [1024, 1024]})
        s.preview.texture_maps['scattergun'] = {'rimlight': {'enabled': True}}
        s.preview.begin_item('c_shortstop', 'scout_c_shortstop')
        self.assertEqual(s.preview.texture_overrides, {})
        self.assertEqual(s.preview.texture_maps, {})


class CustomModelTests(unittest.TestCase):
    """Своя модель: что можно, пока она не загружена."""

    def test_missing_file_is_an_error_not_a_crash(self):
        s = AppSession()
        self.assertIn('error', s.load_custom_model('нет-такого.smd'))

    def test_qc_is_only_for_a_ready_model(self):
        """У замены геометрии QC собирает сборка — править нечего."""
        s = AppSession()
        s.preview.custom_smd_path = 'C:/models/my.smd'
        s.preview.custom_keep_materials = False
        self.assertIn('error', s.qc_text())

    def test_saving_and_clearing_the_qc(self):
        s = AppSession()
        self.assertTrue(s.save_qc('$modelname "a.mdl"')['edited'])
        self.assertEqual(s.preview.custom_qc_text, '$modelname "a.mdl"')
        self.assertFalse(s.save_qc('   ')['edited'])
        self.assertIsNone(s.preview.custom_qc_text)

    def test_dropping_the_model_forgets_its_qc(self):
        s = AppSession()
        s.preview.custom_smd_path = 'C:/models/my.smd'
        s.save_qc('$modelname "a.mdl"')
        s.drop_custom_model()
        self.assertIsNone(s.preview.custom_smd_path)
        self.assertIsNone(s.preview.custom_qc_text)


class DiagnosticsReportTests(unittest.TestCase):
    """Отчёт диагностики отдаётся простыми значениями."""

    def _report(self):
        from src.services.diagnostics.models import (
            DiagnosticReport, Finding, Severity,
        )
        report = DiagnosticReport()
        report.add(Finding(Severity.INFO, 'scan.ok', 'Осмотрено'))
        report.add(Finding(Severity.ERROR, 'vmt.missing', 'Нет VMT',
                           detail='почему', fix_hint='что делать',
                           location='materials/a.vmt'))
        report.add(Finding(Severity.WARNING, 'vtf.format', 'Формат'))
        return report

    def test_enums_do_not_leak_out(self):
        """Транспорт сериализует только простые значения."""
        data = AppSession._report_to_dict(self._report())
        self.assertTrue(all(isinstance(f['severity'], str)
                            for f in data['findings']))

    def test_errors_come_first(self):
        data = AppSession._report_to_dict(self._report())
        self.assertEqual([f['severity'] for f in data['findings']],
                         ['error', 'warning', 'info'])

    def test_counts_and_health(self):
        data = AppSession._report_to_dict(self._report())
        self.assertEqual((data['errors'], data['warnings']), (1, 1))
        self.assertFalse(data['healthy'])

    def test_missing_file_is_refused(self):
        self.assertIn('error', AppSession().diagnose('нет-такого.vpk'))


class ModLibraryTests(unittest.TestCase):
    """Библиотека модов: папка и есть список."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(mod_library_service, 'LIBRARY_DIR',
                                   Path(self._tmp.name) / 'mods')
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _vpk(self, name: str) -> str:
        path = Path(self._tmp.name) / name
        path.write_bytes(b'vpk')
        return str(path)

    def test_added_mod_shows_up_in_the_list(self):
        mod_library_service.add(self._vpk('weapon.vpk'))
        self.assertEqual([m['name'] for m in mod_library_service.items()],
                         ['weapon.vpk'])

    def test_same_name_does_not_overwrite(self):
        """Два разных мода с одинаковым именем — обычное дело."""
        mod_library_service.add(self._vpk('weapon.vpk'))
        other = Path(self._tmp.name) / 'other'
        other.mkdir()
        (other / 'weapon.vpk').write_bytes(b'another')
        mod_library_service.add(str(other / 'weapon.vpk'))
        self.assertEqual(sorted(m['name'] for m in mod_library_service.items()),
                         ['weapon.vpk', 'weapon_1.vpk'])

    def test_reopening_a_library_mod_does_not_copy_it_again(self):
        first = mod_library_service.add(self._vpk('weapon.vpk'))
        again = mod_library_service.add(str(first))
        self.assertEqual(first, again)
        self.assertEqual(len(mod_library_service.items()), 1)

    def test_removal_takes_a_name_not_a_path(self):
        """Иначе «../../» увело бы удаление к любому файлу на диске."""
        mod_library_service.add(self._vpk('weapon.vpk'))
        outsider = Path(self._tmp.name) / 'secret.vpk'
        outsider.write_bytes(b'x')
        self.assertFalse(mod_library_service.remove(str(outsider)))
        self.assertTrue(outsider.exists())
        self.assertTrue(mod_library_service.remove('weapon.vpk'))
        self.assertEqual(mod_library_service.items(), [])

    def test_unknown_name_is_an_error_not_a_crash(self):
        self.assertIn('error', api.remove_mod('нет-такого.vpk'))


class ModIconTests(unittest.TestCase):
    """Обложки модов: кэш на диске, а не пересборка на каждый показ."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(mod_library_service, 'LIBRARY_DIR',
                                   Path(self._tmp.name) / 'mods')
        self._patch.start()
        self.mod = mod_library_service.add(self._vpk('weapon.vpk'))

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _vpk(self, name: str) -> str:
        path = Path(self._tmp.name) / name
        path.write_bytes(b'vpk')
        return str(path)

    def _fake_icon(self) -> Path:
        icon = mod_library_service._icon_path(self.mod.name)
        icon.write_bytes(b'png')
        return icon

    def test_list_shows_a_ready_icon(self):
        self._fake_icon()
        self.assertTrue(mod_library_service.items()[0]['icon'])

    def test_list_does_not_build_icons(self):
        """Открытие каталога не должно декодировать текстуры всей библиотеки."""
        self.assertIsNone(mod_library_service.items()[0]['icon'])

    def test_icon_older_than_the_mod_is_not_reused(self):
        icon = self._fake_icon()
        os.utime(icon, (0, 0))                 # обложка от прошлой версии мода
        self.assertIsNone(mod_library_service.items()[0]['icon'])

    def test_removing_a_mod_takes_its_icon(self):
        """Иначе одноимённый мод получил бы чужую обложку."""
        icon = self._fake_icon()
        mod_library_service.remove(self.mod.name)
        self.assertFalse(icon.exists())

    def test_icon_of_an_unknown_mod_is_none(self):
        self.assertIsNone(mod_library_service.icon('нет-такого.vpk'))


class AutosaveTests(unittest.TestCase):
    """Когда сеанс вообще берётся сохранять работу."""

    def _session(self, tmp) -> AppSession:
        s = AppSession()
        self._patch = patch.object(work_store, 'WORK_DIR', Path(tmp) / 'work')
        self._patch.start()
        self.addCleanup(self._patch.stop)
        return s

    def test_no_item_no_work_key(self):
        """Без опознанного предмета работа легла бы в папку, которую потом
        никто не найдёт: тот же предмет с ключом получил бы вторую."""
        s = AppSession()
        self.assertEqual(s._work_key(), '')
        s._mode = 'scout_c_scattergun'
        self.assertEqual(s._work_key(), '')          # ключа предмета ещё нет
        s.preview.weapon_key = 'c_scattergun'
        self.assertTrue(s._work_key())

    def test_mod_is_identified_by_its_file(self):
        s = AppSession()
        s._mode = 'custom'
        self.assertEqual(s._work_key(), '')
        s._vpk_mod_path = 'mods/weapon.vpk'
        self.assertIn('weapon.vpk'.replace('.', '.'), s._work_key())

    def test_switch_off_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self._session(tmp)
            s._mode = 'scout_c_scattergun'
            s.preview.weapon_key = 'c_scattergun'
            s.preview.textures.set_texture('mat', __file__)
            with patch.object(work_keeper, 'is_enabled', lambda: False):
                s._autosave()
            self.assertFalse((Path(tmp) / 'work').exists())

    def test_emptying_the_work_removes_the_file(self):
        """«Сбросил всё» не должно возвращаться при следующем открытии."""
        with tempfile.TemporaryDirectory() as tmp:
            s = self._session(tmp)
            s._mode = 'scout_c_scattergun'
            s.preview.weapon_key = 'c_scattergun'
            s.preview.textures.set_texture('mat', __file__)
            with patch.object(work_keeper, 'is_enabled', lambda: True):
                s._autosave()
                self.assertTrue(work_store.has(s._work_key()))
                s.preview.forget_user_edits()
                s._autosave()
            self.assertFalse(work_store.has(s._work_key()))


class MissingTextureAnswerTests(unittest.TestCase):
    """Ответ сборке про недостающую текстуру."""

    def _session(self) -> AppSession:
        s = AppSession()
        s._mode = 'hat'
        s.preview.weapon_key = 'models/player/items/medic/medic_gatsby.mdl'
        s.answers = []
        s._answer_texture_request = s.answers.append
        return s

    def test_apply_all_main_is_remembered(self):
        """«Взять главную» — это None, и его легко спутать с «ответа не было».
        На этом сборка спрашивала про один и тот же материал по кругу."""
        s = self._session()
        s.answer_texture('main', apply_all=True)
        s._on_build_needs_texture('medic_gatsby_blue', 'medic_gatsby')
        self.assertEqual(s.answers, [None, None])   # ответ и авто-ответ

    def test_without_apply_all_the_question_reaches_the_page(self):
        s = self._session()
        s.answer_texture('game')
        events = []
        s._put = lambda name, **payload: events.append(name)
        s._on_build_needs_texture('medic_gatsby_blue', 'medic_gatsby')
        self.assertEqual(events, ['need_texture'])

    def test_uploaded_texture_answers_itself(self):
        """Уже положенная текстура не должна ничего спрашивать."""
        s = self._session()
        s.preview.textures.set_texture('mat', __file__)
        s._on_build_needs_texture('mat', 'key')
        self.assertEqual(s.answers, [__file__])


class HatClassSelectionTests(unittest.TestCase):
    """Какие модели мультиклассовой шапки уходят в сборку."""

    def _session(self) -> AppSession:
        s = AppSession()
        s._hat_models = {'scout': 'a_scout.mdl', 'demoman': 'a_demo.mdl',
                         'spy': 'a_spy.mdl'}
        return s

    def test_selected_classes_only(self):
        """Мод под все девять классов весит вдевятеро против нужного одного."""
        models = self._session()._hat_models_for(['scout'])
        self.assertEqual(models, {'scout': 'a_scout.mdl'})

    def test_empty_selection_means_all(self):
        """Пустой выбор — «все»: собрать пустую шапку хуже, чем лишнее."""
        models = self._session()._hat_models_for([])
        self.assertEqual(len(models), 3)

    def test_unknown_classes_do_not_empty_the_build(self):
        models = self._session()._hat_models_for(['pyro'])
        self.assertEqual(len(models), 3)

    def test_ordinary_hat_has_no_class_models(self):
        s = AppSession()
        self.assertIsNone(s._hat_models_for(['scout']))


class HatStyleMemoryTests(unittest.TestCase):
    """Правки соседних стилей шапки доезжают до сборки — в тот же мод."""

    def _edited(self, tmp: str, name: str) -> str:
        """Стиль с одной положенной текстурой."""
        path = os.path.join(tmp, name)
        Path(path).write_bytes(b'png')
        return path

    def _session(self, tmp: str) -> AppSession:
        s = AppSession()
        s._hat_models = {'scout': 'style0.mdl'}
        t = s.preview.textures
        t.material_names = ['hat_red']
        t.textures[Team.RED]['hat_red'] = self._edited(tmp, 'a.png')
        return s

    def test_switching_style_remembers_the_previous_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self._session(tmp)
            s._remember_hat_style(1)
            self.assertEqual(s._hat_style, 1)
            self.assertIn(0, s._hat_styles)
            self.assertEqual(s._hat_styles[0]['models'], {'scout': 'style0.mdl'})

    def test_new_hat_forgets_previous_styles(self):
        """Стили — у КАЖДОЙ шапки свои: правки прошлой к новой не относятся."""
        with tempfile.TemporaryDirectory() as tmp:
            s = self._session(tmp)
            s._remember_hat_style(1)
            s._remember_hat_style(None)
            self.assertEqual(s._hat_styles, {})
            self.assertEqual(s._hat_style, 0)

    def test_untouched_style_is_not_remembered(self):
        s = AppSession()
        s._hat_models = {'scout': 'style0.mdl'}
        s._remember_hat_style(1)
        self.assertEqual(s._hat_styles, {})

    def test_build_takes_other_styles_but_not_the_active_one(self):
        """Активный стиль собирается основным путём — второй раз он лишний."""
        with tempfile.TemporaryDirectory() as tmp:
            s = self._session(tmp)
            s._remember_hat_style(1)
            s._hat_models = {'scout': 'style1.mdl'}
            s.preview.textures.textures[Team.RED]['hat_red'] =                 self._edited(tmp, 'b.png')
            s._remember_hat_style(0)

            builds = s._hat_style_builds()
            self.assertEqual([b['mdl_paths'] for b in builds], [['style1.mdl']])
            self.assertTrue(builds[0]['image_path'].endswith('b.png'))
            self.assertIn('hat_red', builds[0]['textures'][Team.RED])

    def test_forgetting_the_work_forgets_other_styles_too(self):
        """«Забыть правки» и правки соседних стилей — иначе они всё равно
        уедут в мод, хотя человек просил их забыть."""
        with tempfile.TemporaryDirectory() as tmp:
            s = self._session(tmp)
            s._remember_hat_style(1)
            with patch.object(work_keeper, 'forget'):
                s.forget_work()
            self.assertEqual(s._hat_styles, {})

    def test_nothing_to_add_means_no_extra_styles(self):
        self.assertIsNone(AppSession()._hat_style_builds())


if __name__ == "__main__":
    unittest.main()
