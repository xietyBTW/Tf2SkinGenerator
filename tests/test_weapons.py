import unittest

from src.data.weapons import (
    WEAPON_TYPES,
    WEAPON_MDL_PATHS,
    get_weapon_type_name,
    get_weapon_type_key,
    weapon_key_from_mode,
)


class WeaponKeyFromModeTests(unittest.TestCase):
    def test_strips_class_prefix(self):
        self.assertEqual(weapon_key_from_mode("scout_c_scattergun"), "c_scattergun")
        self.assertEqual(weapon_key_from_mode("soldier_c_rocketlauncher"), "c_rocketlauncher")

    def test_only_first_underscore_split(self):
        # делим лишь по первому '_': остаток сохраняется целиком
        self.assertEqual(weapon_key_from_mode("a_b_c"), "b_c")

    def test_no_underscore_returns_as_is(self):
        self.assertEqual(weapon_key_from_mode("custom"), "custom")


class GetWeaponTypeKeyTests(unittest.TestCase):
    def test_roundtrip_all_types_en_and_ru(self):
        # Имя → ключ должно вернуть исходный ключ для обоих языков
        for key in WEAPON_TYPES:
            for lang in ("en", "ru"):
                name = get_weapon_type_name(key, lang)
                self.assertEqual(get_weapon_type_key(name, lang), key)

    def test_known_value(self):
        self.assertEqual(get_weapon_type_key("Primary", "en"), "Primary")
        self.assertEqual(get_weapon_type_key("Ближний бой", "ru"), "Melee")

    def test_unknown_name_returns_none(self):
        self.assertIsNone(get_weapon_type_key("not-a-real-type", "en"))


class WeaponMdlPathsTests(unittest.TestCase):
    def test_default_pattern_for_regular_weapon(self):
        # Обычное оружие получает путь по общему шаблону из цикла
        self.assertEqual(
            WEAPON_MDL_PATHS.get("c_scattergun"),
            "models/weapons/c_models/c_scattergun/c_scattergun.mdl",
        )

    def test_special_override_preserved(self):
        # Явный оверрайд (папка ≠ имени ключа) не затирается циклом
        self.assertEqual(
            WEAPON_MDL_PATHS.get("c_batt_buffpack"),
            "models/weapons/c_models/c_battalion_buffpack/c_batt_buffpack.mdl",
        )

    def test_all_paths_under_models_dir(self):
        for key, path in WEAPON_MDL_PATHS.items():
            self.assertTrue(path.startswith("models/"))
            self.assertTrue(path.endswith(".mdl"))

    def test_non_empty(self):
        self.assertTrue(WEAPON_MDL_PATHS)


if __name__ == "__main__":
    unittest.main()
