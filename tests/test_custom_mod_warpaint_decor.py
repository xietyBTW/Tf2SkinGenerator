"""
War Paint и гирлянды на моде из VPK («Кастомный мод») и своей модели.

- War Paint ищутся по оружию, которое мод заменяет, а не по прошлому
  предмету каталога;
- на своей геометрии War Paint игры не предлагаются: рецепт Valve кладёт
  узор по развёртке стоковой модели — работает универсальный режим;
- правленые гирлянды доходят до сборки кастомного мода.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.app.session import AppSession
from src.domain.preview.session import PreviewSession
from src.services.custom_vpk_service import CustomVPKService


def _session(**preview) -> AppSession:
    s = AppSession.__new__(AppSession)       # без воркеров и конфига
    s.preview = PreviewSession()
    s._mode = 'custom'
    for k, v in preview.items():
        setattr(s.preview, k, v)
    s.tf2_paths = lambda: {'root': 'C:/tf2'}
    return s


class WarpaintOnModTests(unittest.TestCase):

    def test_mod_weapon_is_the_shown_weapon(self):
        s = _session(custom_vpk_mode=True, custom_vpk_weapon='c_scattergun',
                     weapon_key='c_minigun')   # остался от прошлого предмета
        self.assertEqual(s._shown_weapon(), 'c_scattergun')
        self.assertTrue(s._paintkit_model().endswith('c_scattergun.mdl'))

    def test_mod_with_own_model_gets_generic_kits(self):
        s = _session(custom_vpk_mode=True, custom_vpk_weapon='c_scattergun',
                     custom_vpk_own_model=True)
        with patch('src.data.paintkit_defs.for_model', return_value=[{'id': 1}]), \
             patch('src.data.paintkit_defs.generic_kits', return_value=[{'id': 2}]):
            self.assertEqual(s.paintkits(), {'items': [{'id': 2}], 'generic': True})

    def test_texture_only_mod_keeps_game_kits(self):
        """Мод без MDL лежит на стоковой модели — её War Paint ложатся верно."""
        s = _session(custom_vpk_mode=True, custom_vpk_weapon='c_scattergun',
                     custom_vpk_own_model=False)
        with patch('src.data.paintkit_defs.for_model', return_value=[{'id': 1}]):
            self.assertEqual(s.paintkits(), {'items': [{'id': 1}], 'generic': False})

    def test_own_smd_is_custom_geometry_too(self):
        s = _session(custom_smd_path='C:/tmp/my.smd')
        self.assertTrue(s._custom_geometry())
        self.assertEqual(s._own_paintkits('C:/tf2'), [])

    def test_reset_forgets_own_model(self):
        p = PreviewSession(custom_vpk_own_model=True)
        p.reset_custom_vpk()
        self.assertFalse(p.custom_vpk_own_model)


class BypassSettingTests(unittest.TestCase):
    """Способ обхода sv_pure из настроек доходит до сборки."""

    def _method(self, value):
        with patch('src.config.app_config.AppConfig.load_config',
                   return_value={'sv_pure_bypass': value}):
            return AppSession._bypass_method()

    def test_vgui_is_taken_from_settings(self):
        self.assertEqual(self._method('vgui'), 'vgui')

    def test_build_request_carries_the_setting(self):
        import tempfile
        from unittest.mock import MagicMock
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            png = f.name
        s = _session()
        s._mode = 'normal'
        s._build = None
        s.preview.textures.material_names = ['c_pistol']
        s.preview.textures.set_texture('c_pistol', png)
        s.parts = MagicMock(bake_plan=lambda paths: None, baked_path=lambda p: p)
        s._tint_risks = lambda paths: {}
        s._decor_builds = lambda root: []
        s._put = lambda *a, **k: None
        captured = {}

        def Worker(request=None, prepare=None):                # noqa: N802
            captured['request'] = request
            return MagicMock()

        with patch('src.config.app_config.AppConfig.load_config',
                   return_value={'sv_pure_bypass': 'vgui'}), \
             patch('src.services.build_worker.BuildWorker', Worker):
            res = s.build({'filename': 'x.vpk'})
        self.assertTrue(res.get('started'), res)
        self.assertEqual(captured['request'].bypass_method, 'vgui')

    def test_unknown_or_missing_falls_back_to_console(self):
        self.assertEqual(self._method('garbage'), 'console')
        self.assertEqual(self._method(None), 'console')


class SceneNamesTests(unittest.TestCase):
    """Куда в показанной сцене ложится карточка (предпросмотр War Paint)."""

    def test_single_material_in_hands_is_the_weapon_mesh(self):
        from src.domain.preview.texture_state import SINGLE_TEX_KEY
        p = PreviewSession(scene_item_materials=['c_pistol'])
        self.assertEqual(p.scene_names(SINGLE_TEX_KEY), ['c_pistol'])

    def test_single_material_on_its_own_keeps_the_key(self):
        from src.domain.preview.texture_state import SINGLE_TEX_KEY
        self.assertEqual(PreviewSession().scene_names(SINGLE_TEX_KEY), [SINGLE_TEX_KEY])

    def test_mod_card_maps_to_model_material(self):
        p = PreviewSession(custom_vpk_mode=True, custom_model_materials=['C_Ambassador'])
        self.assertEqual(p.scene_names('c_ambassador'), ['C_Ambassador'])


class WeaponMdlTests(unittest.TestCase):
    """Гирлянда в той же папке, что пушка, не должна стать «оружием» мода."""

    def test_weapon_wins_over_its_garland(self):
        from src.services.preview_vpk_mod_worker import _weapon_mdl
        files = ['models/weapons/c_models/c_ambassador/c_ambassador_festivizer.mdl',
                 'models/weapons/c_models/c_ambassador/c_ambassador.mdl']
        self.assertEqual(_weapon_mdl(files, 'c_ambassador'), files[1])

    def test_unknown_weapon_takes_the_first(self):
        from src.services.preview_vpk_mod_worker import _weapon_mdl
        self.assertEqual(_weapon_mdl(['models/psl/a.mdl'], None), 'models/psl/a.mdl')


class ModMainCardTests(unittest.TestCase):
    """Главная карточка мода — материал модели, а не первый VTF архива."""

    def test_model_material_becomes_main(self):
        from src.app.preview_controller import VpkModController
        p = PreviewSession()
        p.textures.material_names = ['festive_lights_red', 'c_ambassador',
                                     'c_ambassador_blue']
        p.textures.main_material = 'festive_lights_red'
        VpkModController(p)._on_materials(['C_Ambassador'])
        self.assertEqual(p.textures.main_material, 'c_ambassador')
        self.assertEqual(p.textures.material_names,
                         ['c_ambassador', 'festive_lights_red', 'c_ambassador_blue'])

    def test_no_match_keeps_order(self):
        from src.app.preview_controller import VpkModController
        p = PreviewSession()
        p.textures.material_names = ['a', 'b']
        p.textures.main_material = 'a'
        VpkModController(p)._on_materials(['zzz'])
        self.assertEqual((p.textures.main_material, p.textures.material_names),
                         ('a', ['a', 'b']))


class DecorInCustomBuildTests(unittest.TestCase):

    def _run(self, built: int):
        entries = [{'kind': 'xmas', 'mdl': 'models/a_xmas.mdl'}]
        with patch('src.services.tf2_paths.TF2Paths.resolve',
                   return_value=('studiomdl.exe', 'misc.vpk', 'tf')), \
             patch('src.services.tf2_paths.TF2Paths.resolve_textures_vpk',
                   return_value='tex.vpk'), \
             patch('src.services.decor_build.build_decor_models',
                   return_value=built) as build:
            note = CustomVPKService._build_decor(
                entries, Path('tmp'), Path('tmp/vpkroot'), 'C:/tf2', (512, 512),
                'DXT5', [], {}, 'console', lambda *_: None, 'ru')
        return note, build

    def test_lights_go_into_the_mod_root(self):
        note, build = self._run(built=1)
        self.assertEqual(note, '')
        ctx = build.call_args.args[0]
        self.assertEqual(ctx.vpkroot_dir, Path('tmp/vpkroot'))
        self.assertEqual(build.call_args.kwargs['bypass_prefix'], 'console')

    def test_mods_own_lights_replacement_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            mdl = Path(root, 'models/a_xmas.mdl')
            mdl.parent.mkdir(parents=True)
            mdl.write_bytes(b'x')
            with patch('src.services.tf2_paths.TF2Paths.resolve',
                       return_value=('s', 'm', 't')), \
                 patch('src.services.tf2_paths.TF2Paths.resolve_textures_vpk',
                       return_value='tex.vpk'), \
                 patch('src.services.decor_build.build_decor_models', return_value=1):
                note = CustomVPKService._build_decor(
                    [{'kind': 'xmas', 'mdl': 'models/a_xmas.mdl'}], Path(root),
                    Path(root), 'C:/tf2', (512, 512), 'DXT5', [], {}, 'console',
                    lambda *_: None, 'ru')
        self.assertIn('a_xmas', note)

    def test_failed_lights_are_reported(self):
        note, _build = self._run(built=0)
        self.assertIn('гирлянды', note)


if __name__ == '__main__':
    unittest.main()
