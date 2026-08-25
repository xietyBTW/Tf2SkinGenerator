"""
Главная текстура предмета — та, что покрывает модель, а не первая в QC.

Порядок столбцов $texturegroup ничего не обещает: у Quick-Fix первым идёт
стекло (4% модели), у C.A.P.P.E.R — экранчик (0.1%). Основная картинка
пользователя уезжала на них, а корпус оставался «доп. материалом». Веса
берём из мешей (треугольники в SMD) и переносим главную только при явном
перевесе — спорные 54/46 остаются на порядке автора.

По стоку правило срабатывает на 7 пушках и 247 моделях шапок; c_tw_eagle
остаётся на месте, хотя 82% модели покрывает столбец с '_gold'.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.qc_skin_parser import (
    choose_main_column, classify_rows, mesh_material_weights,
)
from src.services.smd_service import SMDService

QUICK_FIX = ["c_proto_medigun_glass", "c_proto_medigun", "c_proto_medigun_blue"]
WRANGLER = ["c_invasion_wrangler_screen", "c_invasion_wrangler_laser",
            "c_invasion_wrangler", "c_invasion_wrangler_blue",
            "c_invasion_wrangler_laser_blue"]


class ChooseMainColumnTests(unittest.TestCase):
    def test_dominant_column_wins(self):
        weights = {"c_proto_medigun_glass": 247, "c_proto_medigun": 5281}
        self.assertEqual(choose_main_column(QUICK_FIX, weights), 1)

    def test_tiny_screen_loses_to_the_body(self):
        weights = {"c_invasion_wrangler_screen": 4,
                   "c_invasion_wrangler_laser": 31,
                   "c_invasion_wrangler": 4252}
        self.assertEqual(choose_main_column(WRANGLER, weights), 2)

    def test_close_call_keeps_the_author_order(self):
        """Карамельная трость, 60/40 — не повод переезжать."""
        row = ["c_candy_cane_red", "c_candy_cane_bow_red"]
        self.assertEqual(choose_main_column(row, {row[0]: 40, row[1]: 60}), 0)

    def test_column_zero_stays_when_it_is_big_enough(self):
        """Mad Milk: стекла больше, но жидкость — треть модели, не мелочь."""
        row = ["c_madmilk_liquid", "c_madmilk_glass"]
        self.assertEqual(
            choose_main_column(row, {"c_madmilk_liquid": 32,
                                     "c_madmilk_glass": 67}), 0)

    def test_moves_on_ratio_even_below_two_thirds(self):
        """Праздничный револьвер: 58% против 13% у гирлянды — перевес вчетверо."""
        row = ["festive_lights_red", "festive_battery", "c_revolver_xmas"]
        self.assertEqual(
            choose_main_column(row, {"festive_lights_red": 13,
                                     "festive_battery": 28,
                                     "c_revolver_xmas": 58}), 2)

    def test_australium_column_is_never_main(self):
        """c_tw_eagle: 82% модели покрывает '_gold', красить надо базу."""
        row = ["c_tw_eagle", "c_tw_eagle_gold"]
        self.assertEqual(
            choose_main_column(row, {"c_tw_eagle": 18, "c_tw_eagle_gold": 82}), 0)

    def test_own_festive_material_can_be_main(self):
        """У праздничного револьвера '_xmas' — его собственный материал."""
        row = ["festive_lights_red", "c_revolver_xmas"]
        self.assertEqual(
            choose_main_column(row, {"festive_lights_red": 9,
                                     "c_revolver_xmas": 62}), 1)

    def test_blue_column_is_never_main(self):
        row = ["glass", "body_blue"]
        self.assertEqual(choose_main_column(row, {"glass": 1, "body_blue": 99}), 0)

    def test_without_weights_nothing_moves(self):
        self.assertEqual(choose_main_column(QUICK_FIX, None), 0)
        self.assertEqual(choose_main_column(QUICK_FIX, {}), 0)

    def test_weights_that_do_not_match_the_row_are_ignored(self):
        """Имена мешей разошлись со столбцами — доверять весам нельзя."""
        self.assertEqual(choose_main_column(QUICK_FIX, {"совсем_другое": 999}), 0)

    def test_empty_row(self):
        self.assertEqual(choose_main_column([], {"a": 1}), 0)


class LayoutWithWeightsTests(unittest.TestCase):
    ROWS = [QUICK_FIX,
            ["c_proto_medigun_glass", "c_proto_medigun_blue",
             "c_proto_medigun_blue"]]
    WEIGHTS = {"c_proto_medigun_glass": 247, "c_proto_medigun": 5281}

    def test_main_texture_and_index(self):
        layout = classify_rows(self.ROWS, self.WEIGHTS)
        self.assertEqual(layout.main_texture, "c_proto_medigun")
        self.assertEqual(layout.main_index, 1)

    def test_previous_main_becomes_a_card(self):
        """Стекло не должно пропасть: раньше его выбрасывало правило
        «минус имена из второй строки», хотя общий материал там есть всегда."""
        layout = classify_rows(self.ROWS, self.WEIGHTS)
        self.assertEqual(layout.extra_materials, ["c_proto_medigun_glass"])

    def test_blue_columns_never_become_cards(self):
        layout = classify_rows(self.ROWS, self.WEIGHTS)
        self.assertNotIn("c_proto_medigun_blue", layout.extra_materials)

    def test_australium_column_is_not_a_card(self):
        layout = classify_rows([["c_scattergun", "c_scattergun_gold"]],
                               {"c_scattergun": 100})
        self.assertEqual(layout.extra_materials, [])

    def test_column_absent_from_every_mesh_is_not_a_card(self):
        """У праздничного сапёра в строке лежит материал обычного сапёра."""
        layout = classify_rows([["c_sapper_xmas", "c_sapper"]],
                               {"c_sapper_xmas": 500})
        self.assertEqual(layout.extra_materials, [])

    def test_without_weights_cards_are_kept_as_written(self):
        layout = classify_rows([["body", "trim"]])
        self.assertEqual(layout.main_texture, "body")
        self.assertEqual(layout.extra_materials, ["trim"])


class SmdWeightTests(unittest.TestCase):
    SMD = """version 1
nodes
0 "root" -1
end
skeleton
time 0
0 0 0 0 0 0 0
end
triangles
body
0 1 2 3 0 0 1 0 0 0
0 1 2 3 0 0 1 0 0 0
0 1 2 3 0 0 1 0 0 0
body
0 1 2 3 0 0 1 0 0 0
0 1 2 3 0 0 1 0 0 0
0 1 2 3 0 0 1 0 0 0
glass.vtf
0 1 2 3 0 0 1 0 0 0
0 1 2 3 0 0 1 0 0 0
0 1 2 3 0 0 1 0 0 0
end
"""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _smd(self, name: str, text: str) -> str:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_counts_triangles_per_material(self):
        counts = SMDService.material_triangle_counts([self._smd("a.smd", self.SMD)])
        self.assertEqual(counts, {"body": 2, "glass": 1})

    def test_counts_add_up_across_files(self):
        counts = SMDService.material_triangle_counts(
            [self._smd("a.smd", self.SMD), self._smd("b.smd", self.SMD)])
        self.assertEqual(counts["body"], 4)

    def test_missing_file_is_skipped(self):
        self.assertEqual(SMDService.material_triangle_counts(
            [str(self.dir / "нет.smd")]), {})

    def test_no_triangles_section(self):
        self.assertEqual(SMDService.material_triangle_counts(
            [self._smd("c.smd", "version 1\nnodes\nend\n")]), {})

    def test_weights_without_qc(self):
        self.assertEqual(mesh_material_weights(str(self.dir / "нет.qc")), {})
        self.assertEqual(mesh_material_weights(""), {})

    def test_weights_read_the_bodygroups_of_a_qc(self):
        """Скрытые варианты бодигрупп тоже считаются: парашют — материал."""
        self._smd("pack.smd", self.SMD)
        self._smd("chute.smd", self.SMD.replace("body", "chute"))
        qc = self.dir / "pack.qc"
        qc.write_text('$bodygroup "body"\n{\n\tstudio "pack.smd"\n}\n'
                      '$bodygroup "chute"\n{\n\tblank\n\tstudio "chute.smd"\n}\n',
                      encoding="utf-8")
        weights = mesh_material_weights(str(qc))
        self.assertEqual(weights.get("body"), 2)
        self.assertEqual(weights.get("chute"), 2)


if __name__ == "__main__":
    unittest.main()
