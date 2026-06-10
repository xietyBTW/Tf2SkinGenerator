"""
Корпусные тесты единого парсера $texturegroup.

Фикстуры в tests/fixtures/qc/ — реальные паттерны QC из декомпиляции TF2.
Любое изменение эвристик (BLU/варианты/стили/padding) должно проходить
по всему корпусу — это защита от «починили одно оружие, сломали другое».
"""

import unittest
from pathlib import Path

from src.services.qc_skin_parser import (
    SkinLayout,
    VARIANT_SUFFIXES,
    classify_rows,
    parse_cdmaterials,
    parse_skin_layout,
    parse_texturegroup_rows,
    pick_preview_variant,
    restrict_to_materials,
    variant_kind,
)

FIXTURES = Path(__file__).parent / "fixtures" / "qc"


def _qc(name: str) -> str:
    return str(FIXTURES / name)


class CorpusTests(unittest.TestCase):
    """Сквозная классификация всех фикстур корпуса."""

    def test_flaregun_team_shell(self):
        layout = parse_skin_layout(_qc("flaregun_team_shell.qc"))
        self.assertEqual(layout.main_texture, "c_flaregun")
        self.assertEqual(layout.extra_materials, ["c_flaregun_shell"])
        self.assertEqual(layout.second_row, ["c_flaregun_blue", "c_flaregun_shell_blue"])
        self.assertTrue(layout.blu_is_team)
        self.assertEqual(layout.variants, {})
        self.assertEqual(layout.roles, ["RED", "BLU"])

    def test_rocketlauncher_team_australium(self):
        layout = parse_skin_layout(_qc("rocketlauncher_team_australium.qc"))
        self.assertEqual(layout.main_texture, "c_rocketlauncher")
        self.assertEqual(layout.second_row, ["c_rocketlauncher_blue"])
        self.assertTrue(layout.blu_is_team)
        # gold-строки — варианты, не скины
        self.assertIn("australium", layout.variants)
        self.assertEqual(layout.variants["australium"], ["c_rocketlauncher_gold"])
        self.assertEqual(len(layout.base_rows), 2)
        self.assertEqual(layout.roles, ["RED", "BLU"])

    def test_pocket_watch_single(self):
        """Одна общая текстура: ни BLU, ни стилей — спецсписки не нужны."""
        layout = parse_skin_layout(_qc("pocket_watch_single.qc"))
        self.assertEqual(layout.main_texture, "c_pocket_watch")
        self.assertEqual(layout.second_row, [])
        self.assertFalse(layout.blu_is_team)
        self.assertEqual(layout.roles, ["Skin 0"])

    def test_padded_skinfamilies(self):
        """Padding-дубли не считаются отдельными стилями, но позиционность сохранена."""
        layout = parse_skin_layout(_qc("padded_skinfamilies.qc"))
        # Позиционно (для сборки): 4 базовые строки, second_row = строка 1
        self.assertEqual(len(layout.base_rows), 4)
        self.assertEqual(layout.second_row, ["c_minigun_blue"])
        # Для UI: 2 уникальных скина RED/BLU
        self.assertEqual(len(layout.unique_base_rows), 2)
        self.assertTrue(layout.blu_is_team)
        self.assertEqual(layout.roles, ["RED", "BLU"])

    def test_cleaver_styles(self):
        """Стили (bloody) рендерятся как второй скин, но это НЕ команда."""
        layout = parse_skin_layout(_qc("cleaver_styles.qc"))
        self.assertEqual(layout.main_texture, "c_sd_cleaver")
        self.assertEqual(layout.second_row, ["c_sd_cleaver_bloody"])
        self.assertFalse(layout.blu_is_team)
        self.assertEqual(layout.roles, ["Skin 0", "Bloody"])

    def test_multiline_rows(self):
        """Многострочный блок скина = один скин, а не N."""
        layout = parse_skin_layout(_qc("multiline_rows.qc"))
        self.assertEqual(len(layout.base_rows), 2)
        self.assertEqual(layout.base_rows[0], ["c_bow", "c_bow_arrow"])
        self.assertTrue(layout.blu_is_team)
        self.assertEqual(layout.extra_materials, ["c_bow_arrow"])

    def test_hat_blueprints(self):
        layout = parse_skin_layout(_qc("hat_blueprints.qc"))
        self.assertEqual(layout.main_texture, "fwk_engineer_blueprints")
        self.assertTrue(layout.blu_is_team)

    def test_all_variant_rows_fallback(self):
        """Все строки — варианты → fallback: базовыми считаются все."""
        layout = parse_skin_layout(_qc("all_variant_rows.qc"))
        self.assertEqual(layout.main_texture, "c_weapon_gold")
        self.assertIn("australium", layout.variants)
        self.assertIn("festive", layout.variants)

    def test_no_texturegroup(self):
        layout = parse_skin_layout(_qc("no_texturegroup.qc"))
        self.assertIsNone(layout.main_texture)
        self.assertEqual(layout.roles, [])
        self.assertEqual(layout.second_row, [])

    def test_flat_single_row_blu(self):
        """BLU-имена, записанные столбцами RED-строки, не попадают в extras."""
        layout = parse_skin_layout(_qc("flat_single_row_blu.qc"))
        self.assertEqual(layout.main_texture, "c_flamethrower")
        self.assertEqual(layout.extra_materials, ["c_flamethrower_shell"])

    def test_missing_file(self):
        layout = parse_skin_layout(_qc("does_not_exist.qc"))
        self.assertEqual(layout.all_rows, [])
        self.assertIsNone(layout.main_texture)


class CdmaterialsTests(unittest.TestCase):
    def test_normalization(self):
        cdmats = parse_cdmaterials(_qc("hat_blueprints.qc"))
        # console\ срезан, бэкслеши → /, relative-путь с .. отброшен
        self.assertEqual(cdmats, ["models/player/items/engineer"])

    def test_regular_path(self):
        cdmats = parse_cdmaterials(_qc("flaregun_team_shell.qc"))
        self.assertEqual(cdmats, ["models/weapons/c_items/c_flaregun"])

    def test_missing_file(self):
        self.assertEqual(parse_cdmaterials(_qc("does_not_exist.qc")), [])


class VariantKindTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(variant_kind("c_w_gold"), "australium")
        self.assertEqual(variant_kind("c_w_australium"), "australium")
        self.assertEqual(variant_kind("c_w_festive"), "festive")
        self.assertEqual(variant_kind("c_w_XMAS"), "festive")
        self.assertEqual(variant_kind("c_w_botkiller"), "botkiller")
        self.assertIsNone(variant_kind("c_w"))
        self.assertIsNone(variant_kind("c_w_blue"))
        self.assertIsNone(variant_kind(""))

    def test_team_variant_of_variant(self):
        """BLU-вариант австралиума — вариант, а не фантомный базовый скин."""
        self.assertEqual(variant_kind("c_rocketlauncher_gold_blue"), "australium")
        self.assertEqual(variant_kind("c_w_festive_blu"), "festive")

    def test_all_suffixes_have_kind(self):
        for suffix in VARIANT_SUFFIXES:
            self.assertEqual(variant_kind(f"x{suffix}"), VARIANT_SUFFIXES[suffix])


class PickPreviewVariantTests(unittest.TestCase):
    def test_australium_has_priority(self):
        layout = classify_rows([
            ["c_w"], ["c_w_blue"], ["c_w_festive"], ["c_w_gold"],
        ])
        self.assertEqual(pick_preview_variant(layout), ["c_w_gold"])

    def test_festive_when_no_australium(self):
        layout = classify_rows([["c_w"], ["c_w_festive"]])
        self.assertEqual(pick_preview_variant(layout), ["c_w_festive"])

    def test_none_without_variants(self):
        layout = classify_rows([["c_w"], ["c_w_blue"]])
        self.assertIsNone(pick_preview_variant(layout))

    def test_strange_padding_is_not_preview_variant(self):
        layout = classify_rows([["c_w"], ["c_w_strange"]])
        self.assertIsNone(pick_preview_variant(layout))


class RestrictToMaterialsTests(unittest.TestCase):
    """Фильтрация раскладки для режимов рук (инженер/медик: тело в col0)."""

    def test_body_texture_replaced_by_hand(self):
        main, extras, blu = restrict_to_materials(
            main_texture="engineer_red",
            red_row=["engineer_red", "engineer_arms"],
            blu_row=["engineer_blue", "engineer_arms_blue"],
            allowed_names=["engineer_arms"],
        )
        self.assertEqual(main, "engineer_arms")
        self.assertEqual(extras, [])
        self.assertEqual(blu, ["engineer_arms_blue"])

    def test_neutral_shared_texture_skipped_in_blu(self):
        """BLU == RED на позиции руки → нейтральная текстура, не BLU."""
        main, extras, blu = restrict_to_materials(
            main_texture="spy_red",
            red_row=["spy_red", "spy_gloves"],
            blu_row=["spy_blue", "spy_gloves"],
            allowed_names=["spy_gloves"],
        )
        self.assertEqual(main, "spy_gloves")
        self.assertEqual(blu, [])
        self.assertEqual(extras, [])

    def test_main_already_hand_kept(self):
        main, extras, blu = restrict_to_materials(
            main_texture="scout_arms",
            red_row=["scout_arms", "scout_glove"],
            blu_row=["scout_arms_blue", "scout_glove_blue"],
            allowed_names=["scout_arms", "scout_glove"],
        )
        self.assertEqual(main, "scout_arms")
        self.assertEqual(extras, ["scout_glove"])
        self.assertEqual(blu, ["scout_arms_blue", "scout_glove_blue"])

    def test_no_hands_in_row_falls_back_to_allowed(self):
        main, extras, blu = restrict_to_materials(
            main_texture="medic_red",
            red_row=["medic_red"],
            blu_row=["medic_blue"],
            allowed_names=["medic_arms"],
        )
        self.assertEqual(main, "medic_arms")
        self.assertEqual(extras, [])
        self.assertEqual(blu, [])

    def test_case_insensitive_matching(self):
        main, extras, blu = restrict_to_materials(
            main_texture="Engineer_Red",
            red_row=["Engineer_Red", "Engineer_HandL"],
            blu_row=["Engineer_Blue", "Engineer_HandL_Blue"],
            allowed_names=["engineer_handl"],
        )
        self.assertEqual(main, "Engineer_HandL")
        self.assertEqual(blu, ["Engineer_HandL_Blue"])


class RowParserEdgeCases(unittest.TestCase):
    def test_any_group_name_accepted(self):
        """Имя группы не обязано быть "skinfamilies"."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(
                '$texturegroup "skins"\n{\n{ "a" }\n{ "a_blue" }\n}\n',
                encoding="utf-8",
            )
            rows = parse_texturegroup_rows(str(qc))
        self.assertEqual(rows, [["a"], ["a_blue"]])

    def test_classify_empty(self):
        layout = classify_rows([])
        self.assertIsInstance(layout, SkinLayout)
        self.assertIsNone(layout.main_texture)
        self.assertEqual(layout.roles, [])

    def test_describe_does_not_crash(self):
        for rows in ([], [["a"]], [["a"], ["a_blue"]], [["a"], ["a_bloody"]]):
            self.assertIsInstance(classify_rows(rows).describe(), str)


if __name__ == "__main__":
    unittest.main()
