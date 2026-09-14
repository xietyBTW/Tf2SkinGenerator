"""
Косметические стили стоковой модели (Летающая гильотина).

QC гильотины:
    { "c_sd_cleaver"        "c_sd_cleaver_bloody" }
    { "c_sd_cleaver_bloody" "c_sd_cleaver_bloody" }

Строка стиля выровнена по колонкам с базовой, поэтому её материал — ЗАМЕНА
базового, а не ещё один материал модели. Раньше он уезжал карточкой в базовый
альбом (две текстуры в «Базовом»), а вкладка Bloody оставалась пустой.
"""

import unittest

from src.domain.preview.session import PreviewSession

ROWS = [['c_sd_cleaver', 'c_sd_cleaver_bloody'],
        ['c_sd_cleaver_bloody', 'c_sd_cleaver_bloody']]


def _session():
    s = PreviewSession()
    s.textures.material_names = ['c_sd_cleaver']
    s.textures.main_material = 'c_sd_cleaver'
    s.textures.skin_info = {'rows': ROWS, 'styles': [('Bloody', 1)]}
    return s


class StyleTextureTests(unittest.TestCase):
    def test_style_shows_its_own_game_texture(self):
        s = _session()
        s.adopt_style_textures({1: {'c_sd_cleaver': __file__}})
        s.textures.active_skin = 1
        self.assertEqual(s.card_materials(), ['c_sd_cleaver'])
        self.assertEqual(s.visible_textures(), {'c_sd_cleaver': __file__})
        # Оригинал стиля — не правка человека: в сохранённую работу и в сборку
        # уехали бы временные PNG вместо его выбора.
        self.assertEqual(s.textures.skin_overrides, {})

    def test_user_texture_wins_over_the_game_one(self):
        s = _session()
        s.adopt_style_textures({1: {'c_sd_cleaver': __file__}})
        s.textures.active_skin = 1
        mine = __file__.replace('.py', '_mine.py')
        open(mine, 'w').close()
        try:
            s.textures.set_texture('c_sd_cleaver', mine)
            self.assertEqual(s.visible_textures(), {'c_sd_cleaver': mine})
            # Сборка спрашивает материал строки стиля по ЕГО имени.
            self.assertEqual(
                s.textures.style_upload_for('c_sd_cleaver_bloody'), mine)
        finally:
            import os
            os.unlink(mine)

    def test_game_original_is_not_offered_to_the_build(self):
        s = _session()
        s.adopt_style_textures({1: {'c_sd_cleaver': __file__}})
        self.assertIsNone(s.textures.style_upload_for('c_sd_cleaver_bloody'))


class SingleMaterialModelTests(unittest.TestCase):
    """У гильотины ОДИН материал: превью держит её текстуру под служебным
    ключом, а не под именем из QC. Под именем карточка стиля была пустой."""

    def _session(self):
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        s = PreviewSession()
        s.textures.material_names = [SINGLE_TEX_KEY]
        s.textures.skin_info = {'rows': ROWS, 'styles': [('Bloody', 1)]}
        s.adopt_style_textures({1: {'c_sd_cleaver': __file__}})
        s.textures.active_skin = 1
        return s, SINGLE_TEX_KEY

    def test_style_card_is_not_empty(self):
        s, key = self._session()
        self.assertEqual(s.card_materials(), [key])
        self.assertEqual(s.visible_textures(), {key: __file__})

    def test_build_finds_the_users_style_texture(self):
        s, key = self._session()
        mine = __file__.replace('.py', '_single.py')
        open(mine, 'w').close()
        try:
            s.textures.set_texture(key, mine)
            self.assertEqual(
                s.textures.style_upload_for('c_sd_cleaver_bloody'), mine)
        finally:
            import os
            os.unlink(mine)


class WorkerPairingTests(unittest.TestCase):
    """Пары «базовый материал → материал стиля» строит воркер по строкам QC."""

    def _worker(self, rows):
        from src.services import qc_skin_parser
        from src.services.preview_3d_worker import Preview3DWorker

        w = object.__new__(Preview3DWorker)
        w._decomp_dir = 'x'
        layout = qc_skin_parser.classify_rows(rows)
        w._model = lambda _d: type('M', (), {'layout': layout})()
        w._extract_multi_textures = lambda names: {n: f'{n}.png' for n in names}
        return w

    def test_guillotine(self):
        w = self._worker(ROWS)
        self.assertEqual(w._extract_style_textures(),
                         {1: {'c_sd_cleaver': 'c_sd_cleaver_bloody.png'}})

    def test_team_rows_are_not_styles(self):
        """RED/BLU — свой тумблер, а не стиль."""
        w = self._worker([['c_scattergun'], ['c_scattergun_blue']])
        self.assertEqual(w._extract_style_textures(), {})
