"""
Командная строка $texturegroup распознаётся ПО ВСЕМ СТОЛБЦАМ.

Команда в Source меняет материалы поколоночно и не обязательно первый: у
Quick-Fix стекло общее, синеет корпус во втором столбце. Проверка только по
col0 объявляла такие предметы некомандными — селектор RED/BLU не появлялся,
и синюю сторону было не покрасить. На стоке это 14 пушек (Quick-Fix,
Overdose, Manmelter, C.A.P.P.E.R, Регулировщик, праздничные) и 15 моделей
шапок (Conspiracy Cap, Public Accessor, Doublecross-Comm, That '70s Chapeau).

Таблицы ниже сняты с настоящих моделей игры.
"""

import unittest
from unittest.mock import patch

from src.services.qc_skin_parser import (
    classify_rows, is_team_row_pair, team_material_map,
)
from src.services.vpk_texture_builder import VpkTextureBuilder


class TeamRowPairTests(unittest.TestCase):
    def test_team_in_column_zero(self):
        self.assertTrue(is_team_row_pair(["c_scattergun"], ["c_scattergun_blue"]))

    def test_team_in_a_later_column(self):
        """Quick-Fix: col0 (стекло) общий, синеет col1."""
        self.assertTrue(is_team_row_pair(
            ["c_proto_medigun_glass", "c_proto_medigun", "c_proto_medigun_blue"],
            ["c_proto_medigun_glass", "c_proto_medigun_blue", "c_proto_medigun_blue"]))

    def test_red_stem_counts_as_base(self):
        """Праздничный щит: festive_lights_red → festive_lights_blue."""
        self.assertTrue(is_team_row_pair(
            ["c_targe_ice", "c_targe_xmas", "festive_lights_red"],
            ["c_targe_ice", "c_targe_xmas_blue", "festive_lights_blue"]))

    def test_team_suffix_before_variant_suffix(self):
        """Праздничный Посол: '_blue' стоит ПЕРЕД '_xmas'."""
        self.assertTrue(is_team_row_pair(
            ["c_ambassador_opt_xmas", "xms_colored_lights"],
            ["c_ambassador_opt_blue_xmas", "xms_colored_lights_blu"]))

    def test_short_blu_suffix(self):
        self.assertTrue(is_team_row_pair(["xms_lights"], ["xms_lights_blu"]))

    def test_style_row_is_not_a_team(self):
        """Bloody/Clean — стиль, а не команда."""
        self.assertFalse(is_team_row_pair(["c_machete"], ["c_machete_bloody"]))

    def test_australium_row_is_not_a_team(self):
        self.assertFalse(is_team_row_pair(["c_scattergun"], ["c_scattergun_gold"]))

    def test_identical_rows_are_not_a_team(self):
        """Padding-строки (strange/killstreak) командой не считаются."""
        self.assertFalse(is_team_row_pair(["c_bat", "c_bat_lens"],
                                          ["c_bat", "c_bat_lens"]))

    def test_one_team_column_plus_unrelated_change_is_not_a_team(self):
        """Посторонняя разница = это не чистая смена команды."""
        self.assertFalse(is_team_row_pair(
            ["c_hat", "c_hat_lights"],
            ["c_hat_bloody", "c_hat_lights_blue"]))

    def test_empty_rows(self):
        self.assertFalse(is_team_row_pair([], ["c_hat_blue"]))
        self.assertFalse(is_team_row_pair(["c_hat"], []))

    def test_rows_of_different_width_compare_by_overlap(self):
        self.assertTrue(is_team_row_pair(["a", "b"], ["a", "b_blue", "c"]))


class LayoutTeamFlagTests(unittest.TestCase):
    """Флаг раскладки и карта материалов — то, чем пользуются UI и сборка."""

    QUICK_FIX = [
        ["c_proto_medigun_glass", "c_proto_medigun", "c_proto_medigun_blue"],
        ["c_proto_medigun_glass", "c_proto_medigun_blue", "c_proto_medigun_blue"],
    ]

    def test_quick_fix_is_a_team_item(self):
        layout = classify_rows(self.QUICK_FIX)
        self.assertTrue(layout.blu_is_team)
        self.assertEqual(layout.roles[:2], ["RED", "BLU"])

    def test_team_map_keeps_the_shared_column_neutral(self):
        """Стекло отображается само в себя — сборке его трогать не нужно."""
        tmap = team_material_map(classify_rows(self.QUICK_FIX))
        self.assertEqual(tmap["c_proto_medigun_glass"], "c_proto_medigun_glass")
        self.assertEqual(tmap["c_proto_medigun"], "c_proto_medigun_blue")

    def test_skin_roles_mark_the_blu_row(self):
        """Игра выбирает скин по индексу — подпись BLU должна быть у skin 1."""
        skins = classify_rows(self.QUICK_FIX).skins
        self.assertEqual([s["role"] for s in skins], ["RED", "BLU"])

    def test_style_pair_still_reads_as_style(self):
        layout = classify_rows([["c_machete"], ["c_machete_bloody"]])
        self.assertFalse(layout.blu_is_team)
        self.assertNotIn("BLU", layout.roles)


class BluMainTextureGuardTests(unittest.TestCase):
    """
    Синяя главная текстура пишется под именем blu_row[0]. Когда команда живёт
    не в нулевом столбце, это имя РАВНО красному — и запись положила бы синюю
    картинку поверх красной текстуры. Командные столбцы пишет поколоночная
    ветка, а главную здесь трогать нельзя.
    """

    def _call(self, blu_row, main="c_proto_medigun_glass", red_row=None):
        with patch.object(VpkTextureBuilder, "_build_blu_team_texture") as spy:
            VpkTextureBuilder._maybe_build_blu_team_texture(
                weapon_key="c_proto_medigun", blu_row=blu_row, blu_is_team=True,
                blu_mode="upload", blu_image_path="blu.png",
                vtf_filename=f"{main}.vtf", texture_filename=main,
                slots=None, tex=None, red_row=red_row,
            )
        return spy

    def test_shared_main_material_is_not_overwritten(self):
        self.assertEqual(self._call(["c_proto_medigun_glass",
                                     "c_proto_medigun_blue"]).call_count, 0)

    def test_case_difference_still_counts_as_shared(self):
        """Регистр в $texturegroup у Valve гуляет от файла к файлу."""
        self.assertEqual(self._call(["C_Proto_Medigun_Glass"]).call_count, 0)

    def test_real_blu_main_material_is_written(self):
        self.assertEqual(
            self._call(["c_scattergun_blue"], main="c_scattergun").call_count, 1)

    def test_blu_name_comes_from_the_main_column(self):
        """Главная — второй столбец, значит и синяя пара берётся оттуда:
        blu_row[0] дал бы общее стекло вместо синего корпуса."""
        spy = self._call(
            ["c_proto_medigun_glass", "c_proto_medigun_blue", "c_proto_medigun_blue"],
            main="c_proto_medigun",
            red_row=["c_proto_medigun_glass", "c_proto_medigun",
                     "c_proto_medigun_blue"])
        self.assertEqual(spy.call_args.kwargs["blu_texture_filename"],
                         "c_proto_medigun_blue")


if __name__ == "__main__":
    unittest.main()
