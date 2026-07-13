"""Тесты _collect_build_request — чистого сбора BuildRequest из состояния UI.

Метод не показывает диалогов и не имеет side-effect'ов, поэтому тестируется
заглушками панелей без QApplication. Фиксирует контракт «что уходит в сборку»:
исключение главной текстуры из доп. слотов, автовыбор blu_mode, прокидывание
пер-текстурных настроек/карт и флагов.
"""

import sys
import unittest


def _import_main_window_with_real_pyside6():
    """Импортирует MainWindow с настоящим PySide6, не ломая соседние тесты.

    Worker-тесты (test_base_worker и др.) подменяют PySide6 заглушкой в
    sys.modules и не восстанавливают её; main_window требует настоящий
    QtWidgets. Снимаем заглушку ТОЛЬКО на время импорта, затем возвращаем
    sys.modules как было — уже импортированный модуль main_window сохраняет
    ссылки на реальные классы и дальше от sys.modules не зависит.
    """
    saved = {k: v for k, v in sys.modules.items()
             if k == 'PySide6' or k.startswith('PySide6.')}
    fake_active = saved and not hasattr(saved.get('PySide6'), '__path__')
    if fake_active:
        for k in saved:
            del sys.modules[k]
    try:
        from src.ui.main_window import MainWindow
        return MainWindow
    finally:
        if fake_active:
            for k in [k for k in sys.modules
                      if k == 'PySide6' or k.startswith('PySide6.')]:
                del sys.modules[k]
            sys.modules.update(saved)


MainWindow = _import_main_window_with_real_pyside6()


class _StubPanel:
    def __init__(self, blu_image=None, slots=None, main_mat='main_mat',
                 skin_data=None, keep_materials=False, qc_text=None):
        self._blu_image = blu_image
        self._slots = dict(slots or {})
        self._main_mat = main_mat
        self._skin_data = skin_data
        self._keep = keep_materials
        self._qc = qc_text

    def get_blu_image_path(self): return self._blu_image
    def get_slot_image_paths(self): return dict(self._slots)
    def get_main_material(self): return self._main_mat
    def get_skin_build_data(self): return self._skin_data
    def get_custom_keep_materials(self): return self._keep
    def get_custom_qc_text(self): return self._qc
    def get_texture_maps(self): return {'main_mat': {'phongexp': {}}}
    def get_texture_overrides(self): return {'main_mat': {'size': (1024, 1024)}}
    def get_blu_slot_image_paths(self): return {'blu_slot': 'blu.png'}
    def get_force_team(self): return True


class _StubSettingsPanel:
    def is_isolate_shoulders_checked(self): return True


class _StubWindow:
    """Минимальное состояние MainWindow, которое читает _collect_build_request."""
    mode = 'scout_scattergun'
    language = 'ru'
    _custom_vpk_path = None

    def __init__(self, panel: _StubPanel):
        self.preview_panel = panel
        self.settings_panel = _StubSettingsPanel()


def _collect(window, **overrides):
    kwargs = dict(
        name='my_mod.vpk',
        size=(512, 512),
        format_type='DXT5',
        flags=['CLAMPS'],
        vtf_options={'srgb': True},
        settings={'tf2_game_folder': 'C:/TF2', 'export_folder': 'exp',
                  'keep_temp_on_error': True, 'debug_mode': False},
        from_path='red.png',
        custom_vtf_path=None,
        replace_model_enabled=False,
        replace_model_smd_path=None,
        model_ready_path=None,
        draw_uv_layout=False,
        hat_apply_game_paints=True,
        hat_mdl_path=None,
        hat_class_models=None,
        hat_style_builds=None,
    )
    kwargs.update(overrides)
    return MainWindow._collect_build_request(window, **kwargs)


class CollectBuildRequestTests(unittest.TestCase):
    def test_basic_fields_passthrough(self):
        w = _StubWindow(_StubPanel())
        r = _collect(w)
        self.assertEqual(r.image_path, 'red.png')
        self.assertEqual(r.mode, 'scout_scattergun')
        self.assertEqual(r.filename, 'my_mod.vpk')
        self.assertEqual(r.size, (512, 512))
        self.assertEqual(r.format_type, 'DXT5')
        self.assertEqual(r.flags, ['CLAMPS'])
        self.assertEqual(r.tf2_root_dir, 'C:/TF2')
        self.assertEqual(r.export_folder, 'exp')
        self.assertTrue(r.keep_temp_on_error)
        self.assertEqual(r.language, 'ru')
        self.assertTrue(r.isolate_shoulders)
        self.assertTrue(r.force_team)
        self.assertEqual(r.material_maps, {'main_mat': {'phongexp': {}}})
        self.assertEqual(r.material_settings, {'main_mat': {'size': (1024, 1024)}})
        self.assertEqual(r.panel_blu_textures, {'blu_slot': 'blu.png'})

    def test_main_texture_excluded_from_panel_extras(self):
        w = _StubWindow(_StubPanel(
            slots={'main_mat': 'main.png', 'scope': 'scope.png'}))
        r = _collect(w)
        self.assertEqual(r.panel_extra_textures, {'scope': 'scope.png'})

    def test_blu_mode_upload_when_blu_image_loaded(self):
        w = _StubWindow(_StubPanel(blu_image='blu.png'))
        r = _collect(w)
        self.assertEqual(r.blu_mode, 'upload')
        self.assertEqual(r.blu_image_path, 'blu.png')

    def test_blu_mode_none_without_blu_image(self):
        w = _StubWindow(_StubPanel())
        r = _collect(w)
        self.assertEqual(r.blu_mode, 'none')
        self.assertIsNone(r.blu_image_path)

    def test_skin_data_only_when_replace_model_enabled(self):
        skin = {'tg_overrides': {1: {'m': 'm_bloody'}},
                'mesh_materials': ['m'], 'variant_files': {}}
        w = _StubWindow(_StubPanel(skin_data=skin))
        self.assertIsNone(_collect(w).skin_build_data)
        self.assertEqual(
            _collect(w, replace_model_enabled=True).skin_build_data, skin)

    def test_custom_qc_only_for_keep_materials(self):
        w = _StubWindow(_StubPanel(keep_materials=True, qc_text='$body ...'))
        r = _collect(w, replace_model_enabled=True)
        self.assertTrue(r.replace_keep_materials)
        self.assertEqual(r.custom_qc_text, '$body ...')
        # Без replace_model — keep_materials не читается, QC не прокидывается.
        r2 = _collect(w)
        self.assertFalse(r2.replace_keep_materials)
        self.assertIsNone(r2.custom_qc_text)

    def test_non_skybox_mode_has_no_skybox_fields(self):
        w = _StubWindow(_StubPanel())
        r = _collect(w)
        self.assertIsNone(r.skybox_sky_names)
        self.assertIsNone(r.skybox_face_overrides)

    def test_bypass_method_defaults_to_console(self):
        w = _StubWindow(_StubPanel())
        self.assertEqual(_collect(w).bypass_method, 'console')

    def test_bypass_method_from_settings(self):
        w = _StubWindow(_StubPanel())
        r = _collect(w, settings={'tf2_game_folder': 'C:/TF2',
                                  'export_folder': 'exp',
                                  'bypass_method': 'vgui'})
        self.assertEqual(r.bypass_method, 'vgui')


class _SkyboxStubPanel(_StubPanel):
    def get_skybox_build_data(self):
        return {'equirect': 'pano.png', 'face_overrides': {'up': 'up.png'}}


class CollectSkyboxRequestTests(unittest.TestCase):
    def _window(self, sky_sel):
        w = _StubWindow(_SkyboxStubPanel(
            slots={'__pano__': 'pano.png', 'up': 'up.png'}))
        w.mode = 'skybox'
        w._skybox_sky_name = sky_sel
        return w

    def test_specific_sky_and_overrides(self):
        r = _collect(self._window('sky_upward'), from_path='pano.png')
        self.assertEqual(r.skybox_sky_names, ['sky_upward'])
        self.assertEqual(r.skybox_face_overrides, {'up': 'up.png'})
        # Карточки панорамы/граней не утекают в модельные доп. слоты.
        self.assertEqual(r.panel_extra_textures, {})

    def test_all_maps_expands_via_enumerate(self):
        from unittest.mock import patch
        from src.data.skyboxes import SKY_ALL_MAPS_KEY
        with patch('src.services.skybox_service.SkyboxService.enumerate_sky_names',
                   return_value=['sky_a', 'sky_b']) as m:
            r = _collect(self._window(SKY_ALL_MAPS_KEY), from_path='pano.png')
        self.assertEqual(r.skybox_sky_names, ['sky_a', 'sky_b'])
        m.assert_called_once_with('C:/TF2')


if __name__ == "__main__":
    unittest.main()
