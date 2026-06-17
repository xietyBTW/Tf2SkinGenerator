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
    def test_substring_user_pattern(self):
        with _with_user_patterns(["myglow"]):
            self.assertFalse(mf.is_editable_material("hat_myglow"))
            self.assertTrue(mf.is_editable_material("c_scattergun"))

    def test_exact_user_pattern(self):
        # '=' → точное имя, без ложных подстрок
        with _with_user_patterns(["=sniper_lens"]):
            self.assertFalse(mf.is_editable_material("sniper_lens"))
            self.assertTrue(mf.is_editable_material("sniper_lens_red"))

    def test_case_insensitive(self):
        with _with_user_patterns(["FooBar"]):
            self.assertFalse(mf.is_editable_material("xx_foobar_yy"))

    def test_defaults_still_apply_with_user(self):
        with _with_user_patterns(["custom"]):
            self.assertFalse(mf.is_editable_material("eyeball_l"))
            self.assertFalse(mf.is_editable_material("a_custom_b"))

    def test_missing_config_key_safe(self):
        with mock.patch(
            "src.config.app_config.AppConfig.load_config",
            staticmethod(lambda: {}),
        ):
            self.assertTrue(mf.is_editable_material("c_scattergun"))
            self.assertFalse(mf.is_editable_material("eyeball_l"))


class PatternsArgumentTests(unittest.TestCase):
    def test_explicit_patterns_skip_config(self):
        """С готовым списком паттернов конфиг читаться не должен."""
        with mock.patch.object(mf, "get_blacklist_patterns") as m_patterns:
            self.assertFalse(mf.is_editable_material("anything", patterns=["anything"]))
            self.assertTrue(mf.is_editable_material("anything", patterns=["other"]))
        m_patterns.assert_not_called()

    def test_filter_editable_loads_patterns_once(self):
        """filter_editable загружает паттерны один раз на проход, не на каждый материал."""
        with mock.patch.object(
            mf, "get_blacklist_patterns",
            return_value=list(mf.DEFAULT_NON_EDITABLE_PATTERNS),
        ) as m_patterns:
            result = mf.filter_editable(["c_scattergun", "eyeball_l", "c_arrow"])
        self.assertEqual(result, ["c_scattergun", "c_arrow"])
        m_patterns.assert_called_once()


if __name__ == "__main__":
    unittest.main()
