"""Тесты PreviewSession: правила перехода между моделями превью.

Раньше эти правила лежали в теле PreviewPanel._start_3d_worker и проверить их
можно было только через живой Qt-виджет. Теперь они в домене — тесты идут
без Qt.
"""

import unittest

from src.domain.preview.mode import PreviewMode
from src.domain.preview.session import PreviewSession
from src.shared.constants import Team


def _loaded_session() -> PreviewSession:
    """Сеанс, как после полной загрузки кастомной модели с командами и стилями."""
    s = PreviewSession()
    s.custom_smd_path = "C:/models/my.smd"
    s.custom_obj_path = "C:/models/my.obj"
    s.custom_keep_materials = True
    s.custom_vpk_mode = True
    s.custom_model_materials = ["mat_a", "mat_b"]
    s.misc_materials = ["eyeball_r"]
    s.misc_mode = True
    s.skin_chosen = {1: {"mat_a"}}
    s.applied_3d_tex = {"mat_a": "C:/tex/a.png"}
    s.team_framerate = 12.0
    s.blu_matches_red = True
    s.pending_2d_refresh = True

    t = s.textures
    t.skin_info = {"num_skins": 3}
    t.active_skin = 2
    t.skin_overrides = {2: {"mat_a": "C:/tex/style.png"}}
    t.red_frames = ["r0.png"]
    t.blu_frames = ["b0.png"]
    t.blu_name_map = {"mat_a": "mat_a_blue"}
    t.vpk_red_tex_map = {"mat_a": "r.png"}
    t.vpk_blu_tex_map = {"mat_a": "b.png"}
    t.active_team = Team.BLU
    t.force_team = True
    t.main_material = "mat_a"
    t.material_names = ["mat_a", "mat_b"]
    t.australium_frame = "gold.png"
    t.australium_active = True
    t.australium_user_tex = "C:/tex/gold_user.png"
    t.australium_mat_name = "mat_a_gold"
    return s


class HasCustomModelTests(unittest.TestCase):
    """Кастомность определяется по четырём независимым признакам."""

    def test_clean_session_is_not_custom(self):
        self.assertFalse(PreviewSession().has_custom_model)

    def test_smd_path_alone_is_enough(self):
        s = PreviewSession()
        s.custom_smd_path = "C:/m.smd"
        self.assertTrue(s.has_custom_model)

    def test_keep_materials_alone_is_enough(self):
        s = PreviewSession()
        s.custom_keep_materials = True
        self.assertTrue(s.has_custom_model)

    def test_skin_info_alone_is_enough(self):
        """Определённые стили оригинала — тоже след кастомной модели."""
        s = PreviewSession()
        s.textures.skin_info = {"num_skins": 2}
        self.assertTrue(s.has_custom_model)

    def test_custom_mode_alone_is_enough(self):
        s = PreviewSession()
        s.mode.enter(PreviewMode.CUSTOM)
        self.assertTrue(s.has_custom_model)


class BeginGameModelTests(unittest.TestCase):
    def test_reports_previous_show_was_custom(self):
        """Признак снимается ДО сбросов — иначе он всегда был бы False."""
        self.assertTrue(_loaded_session().begin_game_model())

    def test_reports_false_when_previous_was_stock(self):
        s = PreviewSession()
        s.textures.red_frames = ["r0.png"]     # обычное игровое оружие
        self.assertFalse(s.begin_game_model())

    def test_forgets_custom_model(self):
        s = _loaded_session()
        s.begin_game_model()
        self.assertIsNone(s.custom_smd_path)
        self.assertIsNone(s.custom_obj_path)
        self.assertFalse(s.custom_keep_materials)
        self.assertFalse(s.custom_vpk_mode)

    def test_forgets_styles(self):
        s = _loaded_session()
        s.begin_game_model()
        self.assertIsNone(s.textures.skin_info)
        self.assertEqual(s.textures.active_skin, 0)
        self.assertEqual(s.textures.skin_overrides, {})
        self.assertEqual(s.skin_chosen, {})

    def test_forgets_team_data_and_variant(self):
        s = _loaded_session()
        s.begin_game_model()
        t = s.textures
        self.assertEqual(t.red_frames, [])
        self.assertEqual(t.blu_frames, [])
        self.assertEqual(t.blu_name_map, {})
        self.assertEqual(t.active_team, Team.RED)
        self.assertFalse(t.force_team)
        self.assertFalse(t.australium_active)
        self.assertIsNone(t.australium_frame)
        self.assertEqual(s.team_framerate, 0.0)
        self.assertFalse(s.blu_matches_red)
        self.assertEqual(s.applied_3d_tex, {})

    def test_forgets_misc_and_main_material(self):
        """Имя главного материала обязано уйти вместе с «Прочее».

        Иначе у одно-текстурной игровой модели команда и вариант привязались бы
        к карточке предыдущей модели.
        """
        s = _loaded_session()
        s.begin_game_model()
        self.assertEqual(s.misc_materials, [])
        self.assertFalse(s.misc_mode)
        self.assertIsNone(s.textures.main_material)

    def test_forgets_material_names(self):
        """Имена материалов принадлежат модели: пережив переход, они заставили
        бы разрешать текстуры для чужих материалов."""
        s = _loaded_session()
        s.begin_game_model()
        self.assertEqual(s.textures.material_names, [])

    def test_clears_pending_2d_refresh(self):
        s = _loaded_session()
        s.begin_game_model()
        self.assertFalse(s.pending_2d_refresh)

    def test_keeps_mode(self):
        """Режим переключают явные переходы, а не загрузка модели."""
        s = PreviewSession()
        s.mode.enter(PreviewMode.SPY_MASKS)
        s.begin_game_model()
        self.assertEqual(s.mode.mode, PreviewMode.SPY_MASKS)

    def test_is_idempotent(self):
        """Повторный вызов ничего не ломает: панель зовёт сбросы и порознь."""
        s = _loaded_session()
        s.begin_game_model()
        self.assertFalse(s.begin_game_model())


class BeginItemTests(unittest.TestCase):
    """Смена ПРЕДМЕТА забывает пользовательское; перезагрузка того же — нет."""

    def test_same_item_keeps_uploaded_textures(self):
        s = PreviewSession()
        s.begin_item("c_scattergun", "scout_c_scattergun")
        s.textures.set_texture("mat_a", "C:/tex/user.png")

        self.assertFalse(s.begin_item("c_scattergun", "scout_c_scattergun"))
        self.assertTrue(s.textures.textures[Team.RED])

    def test_other_item_forgets_uploaded_textures(self):
        """Иначе скин одного оружия переезжает на следующее выбранное."""
        s = PreviewSession()
        s.begin_item("c_scattergun", "scout_c_scattergun")
        s.textures.set_texture("mat_a", "C:/tex/user.png")

        self.assertTrue(s.begin_item("c_minigun", "heavy_c_minigun"))
        self.assertEqual(s.textures.textures[Team.RED], {})
        self.assertEqual(s.textures.material_names, [])
        self.assertIsNone(s.current_object)

    def test_other_item_forgets_styles_and_custom_model(self):
        s = _loaded_session()
        s.begin_item("c_minigun", "heavy_c_minigun")
        self.assertIsNone(s.textures.skin_info)
        self.assertIsNone(s.custom_smd_path)


class PartialResetTests(unittest.TestCase):
    """Половинки сбросов не должны задевать чужое состояние."""

    def test_reset_skins_keeps_team_data(self):
        s = _loaded_session()
        s.reset_skins()
        self.assertIsNone(s.textures.skin_info)
        self.assertEqual(s.textures.red_frames, ["r0.png"])

    def test_reset_team_frames_keeps_styles(self):
        s = _loaded_session()
        s.reset_team_frames()
        self.assertEqual(s.textures.red_frames, [])
        self.assertEqual(s.textures.skin_info, {"num_skins": 3})

    def test_reset_custom_model_keeps_loaded_textures(self):
        """Забыть подставленную геометрию — не то же самое, что забыть текстуры.

        Текстура здесь уезжает в skin_overrides активного стиля (так работает
        маршрутизация set_texture при skin > 0), и сброс модели её не трогает.
        """
        s = _loaded_session()
        s.textures.set_texture("mat_a", "C:/tex/user.png")
        s.reset_custom_model()
        self.assertIsNone(s.custom_smd_path)
        self.assertEqual(s.textures.skin_overrides[2]["mat_a"], "C:/tex/user.png")

    def test_reset_custom_model_keeps_team_textures(self):
        """Тот же сброс без активного стиля: текстура лежит по командам."""
        s = PreviewSession()
        s.custom_smd_path = "C:/m.smd"
        s.textures.set_texture("mat_a", "C:/tex/user.png")
        s.reset_custom_model()
        self.assertEqual(s.textures.textures[Team.RED]["mat_a"], "C:/tex/user.png")


class MiscAndForceTeamTests(unittest.TestCase):
    """«Прочее» и «сделать командным» — правила, которые держала панель."""

    def _model(self, tmp) -> PreviewSession:
        """Сеанс с двумя карточками и одним служебным материалом на диске."""
        import os
        s = PreviewSession()
        s.weapon_key = "c_scattergun"
        s.weapon_mode = "scout_c_scattergun"
        paths = {}
        for mat in ("scattergun", "scattergun_extra", "eyeball_r"):
            path = os.path.join(tmp, mat + ".png")
            with open(path, "wb") as f:
                f.write(b"x")
            paths[mat] = path
        s.textures.material_names = ["scattergun", "scattergun_extra"]
        s.textures.main_material = "scattergun"
        s.textures.vpk_red_tex_map = dict(paths)
        s.misc_materials = ["eyeball_r"]
        return s

    def test_misc_mode_swaps_only_cards(self):
        """«Прочее» меняет карточки, но не состав модели: главный материал —
        основа ключа хранения и командных кадров, подменять его нельзя."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            s = self._model(tmp)
            self.assertTrue(s.toggle_misc())
            self.assertEqual(s.card_materials(), ["eyeball_r"])
            self.assertEqual(s.textures.material_names,
                             ["scattergun", "scattergun_extra"])
            self.assertEqual(s.textures.stable_main(), "scattergun")
            self.assertEqual(list(s.visible_textures()), ["eyeball_r"])
            self.assertFalse(s.toggle_misc())
            self.assertEqual(s.card_materials(),
                             ["scattergun", "scattergun_extra"])

    def test_scene_textures_include_service_materials(self):
        """В 3D едут ВСЕ материалы: без служебных глаза и зубы серые."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            s = self._model(tmp)
            self.assertEqual(sorted(s.scene_textures()),
                             ["eyeball_r", "scattergun", "scattergun_extra"])

    def test_misc_toggle_drops_variant(self):
        """Активный австралий гасится: он перекрыл бы главный материал."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            s = self._model(tmp)
            s.textures.australium_active = True
            s.toggle_misc()
            self.assertFalse(s.textures.australium_active)

    def test_force_team_offered_only_without_native_variant(self):
        """Есть свой BLU — предлагать синтез незачем."""
        s = PreviewSession()
        s.weapon_key = "c_scattergun"
        s.weapon_mode = "scout_c_scattergun"
        self.assertTrue(s.can_force_team())
        s.textures.blu_frames = ["b0.png"]
        self.assertFalse(s.can_force_team())

    def test_force_team_not_offered_twice(self):
        """После включения кнопка уходит — её место занимают RED/BLU."""
        s = PreviewSession()
        s.weapon_key = "c_scattergun"
        s.weapon_mode = "scout_c_scattergun"
        s.enable_force_team()
        self.assertTrue(s.textures.force_team)
        self.assertEqual(s.textures.active_team, Team.RED)
        self.assertFalse(s.can_force_team())

    def test_force_team_not_offered_for_hats_and_hands(self):
        """Шапки, руки и тела персонажей синтез команды не получают."""
        from src.data.player_hands import HAND_MODE_KEYS
        s = PreviewSession()
        s.weapon_key = "c_scattergun"
        for mode in ("hat", "custom", next(iter(HAND_MODE_KEYS))):
            s.weapon_mode = mode
            self.assertFalse(s.can_force_team(), mode)


class VpkModStylesTests(unittest.TestCase):
    """Стили чужого мода: его текстуры должны лечь переопределениями."""

    def test_mod_style_textures_become_overrides(self):
        """Иначе переключение стиля показывало бы пустые карточки вместо того,
        что лежит в файле мода."""
        import os
        from src.app.preview_controller import VpkModController

        session = PreviewSession()
        controller = VpkModController(session)
        controller._on_skins({
            'skins': [{'index': 0}, {'index': 1}],
            # Базовый стиль карточки показывают сами — его пропускаем.
            'skin_textures': {0: {'mat': __file__}, 1: {'mat': __file__}},
        })
        self.assertEqual(session.textures.skin_overrides.get(1, {}).get('mat'),
                         __file__)
        self.assertIn('mat', session.skin_chosen.get(1, set()))
        self.assertNotIn(0, session.textures.skin_overrides)

    def test_missing_files_are_skipped(self):
        from src.app.preview_controller import VpkModController

        session = PreviewSession()
        VpkModController(session)._on_skins({
            'skins': [{'index': 1}],
            'skin_textures': {1: {'mat': 'C:/нет-такого.png'}},
        })
        self.assertEqual(session.textures.skin_overrides.get(1, {}), {})


if __name__ == "__main__":
    unittest.main()
