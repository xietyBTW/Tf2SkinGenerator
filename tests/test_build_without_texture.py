"""
Сборка без своей текстуры (AppSession.build).

- есть другая правка (VMT, карты, модель…) — мод собирается, главная игровая,
  и о ней не спрашивают (main_from_game);
- правок нет — страницу просят переспросить (confirm_empty), с allow_empty
  собирается игровой мод;
- правлена одна гирлянда — оружие в мод не идёт (главная из игры не нужна).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.app.session import AppSession
from src.domain.preview.session import PreviewSession
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL


def _session() -> AppSession:
    s = AppSession.__new__(AppSession)       # без воркеров и конфига
    s.preview = PreviewSession()
    s.preview.weapon_key = 'c_pistol'
    s.preview.textures.material_names = ['c_pistol']
    s._mode = 'normal'
    s._build = None
    s.tf2_paths = lambda: {'root': 'C:/tf2'}
    s.parts = MagicMock(bake_plan=lambda paths: None, baked_path=lambda p: p)
    s._tint_risks = lambda paths: {}
    s._decor_builds = lambda root: []
    s._put = lambda *a, **k: None
    s._vmt_target = lambda card='': ('c_pistol', card or 'c_pistol')
    return s


def _build(s, params=None, edited_vmt=None):
    captured = {}

    def worker(request=None, prepare=None):                    # noqa: N802
        captured['request'] = request
        return MagicMock()

    with patch('src.services.build_worker.BuildWorker', worker), \
         patch('src.config.app_config.AppConfig.load_config', return_value={}), \
         patch('src.services.edited_vmt_service.EditedVMTService.get_edited_vmt',
               return_value=edited_vmt):
        res = s.build({'filename': 'x.vpk', **(params or {})})
    return res, captured.get('request')


class BuildWithoutTextureTests(unittest.TestCase):

    def test_no_changes_asks_first(self):
        res, request = _build(_session())
        self.assertEqual(res, {'confirm_empty': True})
        self.assertIsNone(request)

    def test_build_anyway_uses_game_texture(self):
        res, request = _build(_session(), {'allow_empty': True})
        self.assertTrue(res.get('started'), res)
        self.assertEqual(request.image_path, EXTRA_TEX_USE_GAME_ORIGINAL)
        self.assertTrue(request.main_from_game)

    def test_vmt_edit_alone_is_a_change(self):
        with tempfile.NamedTemporaryFile(suffix='.vmt', delete=False) as f:
            vmt = f.name
        try:
            res, request = _build(_session(), edited_vmt=vmt)
        finally:
            os.unlink(vmt)
        self.assertTrue(res.get('started'), res)
        self.assertTrue(request.main_from_game)

    def test_material_maps_alone_are_a_change(self):
        s = _session()
        s.preview.texture_maps = {'c_pistol': {'selfillum': {}}}
        res, request = _build(s)
        self.assertTrue(res.get('started'), res)

    def test_only_garland_keeps_the_decor_only_build(self):
        s = _session()
        s._decor_builds = lambda root: [{'kind': 'xmas', 'mdl': 'm', 'textures': {}}]
        res, request = _build(s)
        self.assertTrue(res.get('started'), res)
        self.assertIsNone(request.image_path)
        self.assertFalse(request.main_from_game)


if __name__ == '__main__':
    unittest.main()
