import unittest
from unittest import mock

from src.data import material_filter as mf


def _with_user_patterns(patterns):
    """Контекст-менеджер: подменяет пользовательские паттерны блэклиста в конфиге."""
    cfg = {"material_blacklist": patterns}
    return mock.patch(
        "src.config.app_config.AppConfig.load_config",
        staticmethod(lambda: cfg),
    )


class DefaultBlacklistTests(unittest.TestCase):
    def setUp(self):
        self._p = _with_user_patterns([])
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_anatomy_not_editable(self):
        for n in ("eyeball_l", "eyeball_r", "spy_teeth", "heavy_tongue"):
            self.assertFalse(mf.is_editable_material(n), n)

    def test_system_not_editable(self):
        # консолидировано из vpk_service inline-списка
        for n in ("sniper_lens_invulnfx", "sniper_red_invun", "x_invuln", "y_zombie"):
            self.assertFalse(mf.is_editable_material(n), n)

    def test_overlays_not_editable(self):
        for n in ("hvyweapon_hands_sheen", "weapon_overlay", "lens_fresnel"):
            self.assertFalse(mf.is_editable_material(n), n)

    def test_normal_material_editable(self):
        for n in ("c_scattergun", "sniper_lens", "c_arrow", "pocket_watch_fg"):
            self.assertTrue(mf.is_editable_material(n), n)

    def test_filter_editable(self):
        self.assertEqual(
            mf.filter_editable(["c_scattergun", "eyeball_l", "c_arrow"]),
            ["c_scattergun", "c_arrow"],
        )


class UserBlacklistTests(unittest.TestCase):
    """Пользовательский ЧС теперь отдельная роль: is_user_blacklisted скрывает
    карточку, но НЕ меняет класс материала (is_editable_material — только дефолты)."""

    def test_substring_user_pattern(self):
        with _with_user_patterns(["myglow"]):
            self.assertTrue(mf.is_user_blacklisted("hat_myglow"))
            self.assertFalse(mf.is_user_blacklisted("c_scattergun"))
            # Класс «основная/служебная» от пользовательского ЧС не зависит.
            self.assertTrue(mf.is_editable_material("hat_myglow"))

    def test_exact_user_pattern(self):
        # '=' → точное имя, без ложных подстрок
        with _with_user_patterns(["=sniper_lens"]):
            self.assertTrue(mf.is_user_blacklisted("sniper_lens"))
            self.assertFalse(mf.is_user_blacklisted("sniper_lens_red"))

    def test_case_insensitive(self):
        with _with_user_patterns(["FooBar"]):
            self.assertTrue(mf.is_user_blacklisted("xx_foobar_yy"))

    def test_defaults_still_apply_with_user(self):
        with _with_user_patterns(["custom"]):
            # Дефолтный классификатор: служебные остаются служебными.
            self.assertFalse(mf.is_editable_material("eyeball_l"))
            # Пользовательский ЧС: скрывает по своему паттерну.
            self.assertTrue(mf.is_user_blacklisted("a_custom_b"))

    def test_missing_config_key_safe(self):
        with mock.patch(
            "src.config.app_config.AppConfig.load_config",
            staticmethod(lambda: {}),
        ):
            self.assertTrue(mf.is_editable_material("c_scattergun"))
            self.assertFalse(mf.is_editable_material("eyeball_l"))
            self.assertFalse(mf.is_user_blacklisted("anything"))


class PatternsArgumentTests(unittest.TestCase):
    def test_explicit_patterns_skip_config(self):
        """С готовым списком паттернов конфиг читаться не должен."""
        with mock.patch.object(mf, "get_blacklist_patterns") as m_patterns:
            self.assertFalse(mf.is_editable_material("anything", patterns=["anything"]))
            self.assertTrue(mf.is_editable_material("anything", patterns=["other"]))
        m_patterns.assert_not_called()

    def test_filter_editable_defaults_only(self):
        """filter_editable классифицирует ТОЛЬКО по дефолтам; пользовательский ЧС
        не влияет на класс (c_scattergun в ЧС остаётся редактируемым)."""
        with _with_user_patterns(["c_scattergun"]):
            result = mf.filter_editable(["c_scattergun", "eyeball_l", "c_arrow"])
        # eyeball_l — служебный (дефолт) → убран; c_scattergun остаётся.
        self.assertEqual(result, ["c_scattergun", "c_arrow"])


if __name__ == "__main__":
    unittest.main()
