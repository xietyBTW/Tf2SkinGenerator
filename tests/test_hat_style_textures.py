"""
Текстуры дополнительных стилей шапки при сборке.

Стиль, который пользователь правил, но не оставил активным, собирается
отдельной веткой (`_build_extra_style_models`). Раньше она писала РОВНО одну
текстуру — главный материал, — а пер-материальные и командные правки молча
терялись: панель их запоминает, метка «изменён» горит, сборка проходит без
ошибок, и только в игре видно, что заменена лишь часть шапки.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.vpk_model_pipeline import VpkModelPipeline, texture_slot_key
from src.services.vpk_texture_builder import VpkTextureBuilder
from src.shared.constants import Team

BS = chr(92)

QC_MULTI = """
$modelname "hat_style2.mdl"
$cdmaterials "models{bs}workshop{bs}player{bs}items{bs}heavy{bs}hat_style2{bs}"

$texturegroup "skinfamilies"
{{
	{{ "hat_style2"      "hat_style2_1"      "hat_style2_blue" "hat_style2_1_blue" }}
	{{ "hat_style2_blue" "hat_style2_1_blue" "hat_style2_blue" "hat_style2_1_blue" }}
}}
""".format(bs=BS)

QC_SINGLE = """
$modelname "hat_style2.mdl"
$cdmaterials "models{bs}workshop{bs}player{bs}items{bs}heavy{bs}hat_style2{bs}"

$texturegroup "skinfamilies"
{{
	{{ "hat_style2" }}
}}
""".format(bs=BS)


class StyleTexturesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.calls = []
        self._orig = VpkTextureBuilder._render_extra_texture

        def spy(name, img, *a, **kw):
            self.calls.append((name, os.path.basename(img)))
            return True

        VpkTextureBuilder._render_extra_texture = staticmethod(spy)

    def tearDown(self):
        VpkTextureBuilder._render_extra_texture = self._orig
        self._tmp.cleanup()

    def _qc(self, text: str) -> str:
        path = self.dir / "hat_style2.qc"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _img(self, name: str) -> str:
        path = self.dir / name
        path.write_bytes(b"x")
        return str(path)

    def _write(self, qc: str, entry: dict, main_img=None,
               main_tex="hat_style2", **kw) -> int:
        return VpkModelPipeline._write_style_textures(
            qc, entry, main_img, main_tex, self.dir, self.dir / "base.vmt",
            "console/models/hat", (512, 512), "DXT5", [], {}, **kw)

    def test_every_material_and_team_variant_is_written(self):
        """Правки по материалам и по командам доходят до мода целиком."""
        entry = {"textures": {
            Team.RED: {"hat_style2": self._img("body.png"),
                       "hat_style2_1": self._img("lens.png")},
            Team.BLU: {"hat_style2": self._img("body_blu.png")},
        }}
        written = self._write(self._qc(QC_MULTI), entry)

        self.assertEqual(written, 3, self.calls)
        self.assertIn(("hat_style2", "body.png"), self.calls)
        self.assertIn(("hat_style2_1", "lens.png"), self.calls)
        # Синяя картинка пишется под ИМЕНЕМ КОМАНДНОЙ ПАРЫ материала
        self.assertIn(("hat_style2_blue", "body_blu.png"), self.calls)

    def test_shared_columns_do_not_get_a_blu_copy(self):
        """Столбцы, одинаковые в обеих строках, командной пары не имеют."""
        entry = {"textures": {
            Team.RED: {"hat_style2_blue": self._img("always_blue.png")},
        }}
        self._write(self._qc(QC_MULTI), entry)
        names = [n for n, _ in self.calls]
        self.assertEqual(names.count("hat_style2_blue"), 1, self.calls)

    def test_single_image_goes_to_the_main_material(self):
        """Общая картинка стиля (старое поведение) достаётся главному материалу."""
        written = self._write(self._qc(QC_MULTI), {}, main_img=self._img("one.png"))
        self.assertEqual(written, 1)
        self.assertEqual(self.calls, [("hat_style2", "one.png")])

    def test_per_material_edit_wins_over_the_common_image(self):
        entry = {"textures": {Team.RED: {"hat_style2": self._img("card.png")}}}
        self._write(self._qc(QC_MULTI), entry, main_img=self._img("common.png"))
        self.assertEqual(self.calls, [("hat_style2", "card.png")])

    def test_nothing_to_write(self):
        self.assertEqual(self._write(self._qc(QC_MULTI), {}), 0)
        self.assertEqual(self.calls, [])

    def test_missing_files_are_skipped(self):
        entry = {"textures": {Team.RED: {"hat_style2": str(self.dir / "нет.png")}}}
        self.assertEqual(self._write(self._qc(QC_MULTI), entry), 0)

    def test_single_material_style(self):
        entry = {"textures": {Team.RED: {"hat_style2": self._img("body.png")}}}
        self.assertEqual(self._write(self._qc(QC_SINGLE), entry), 1)

    def test_material_names_are_matched_case_insensitively(self):
        """Панель отдаёт имена в нижнем регистре, QC — как автор написал."""
        entry = {"textures": {Team.RED: {"HAT_STYLE2_1": self._img("lens.png")}}}
        self._write(self._qc(QC_MULTI), entry)
        self.assertIn(("hat_style2_1", "lens.png"), self.calls)

    def test_broken_qc_still_writes_the_main_texture(self):
        """QC не читается — хотя бы главный материал должен уехать в мод."""
        qc = str(self.dir / "нет-такого.qc")
        written = self._write(qc, {}, main_img=self._img("one.png"))
        self.assertEqual(written, 1)
        self.assertEqual(self.calls, [("hat_style2", "one.png")])


class SharedMaterialWarningTests(StyleTexturesTests):
    """
    63 шапки в стоке (Barnstormer, «Gem Only»-серия) держат все стили на ОДНОМ
    материале: стили различаются только геометрией. Разные текстуры для них
    физически невозможны — в мод уедет записанная последней. Молча это делать
    нельзя, иначе выглядит как баг приложения.
    """

    def setUp(self):
        super().setUp()
        self.warnings = []
        self.ctx = type("Ctx", (), {"warn": lambda _s, m: self.warnings.append(m)})()

    def test_second_style_on_the_same_material_warns(self):
        seen = {}
        self._write(self._qc(QC_SINGLE),
                    {"textures": {Team.RED: {"hat_style2": self._img("up.png")}}},
                    written_textures=seen, ctx=self.ctx)
        self.assertEqual(self.warnings, [])

        self._write(self._qc(QC_SINGLE),
                    {"textures": {Team.RED: {"hat_style2": self._img("down.png")}}},
                    written_textures=seen, ctx=self.ctx)
        self.assertEqual(len(self.warnings), 1, self.warnings)
        self.assertIn("hat_style2", self.warnings[0])

    def test_same_image_twice_is_not_a_conflict(self):
        """Один стиль пишется для каждого класса — это не конфликт."""
        seen, img = {}, self._img("up.png")
        for _ in range(3):
            self._write(self._qc(QC_SINGLE),
                        {"textures": {Team.RED: {"hat_style2": img}}},
                        written_textures=seen, ctx=self.ctx)
        self.assertEqual(self.warnings, [])

    def test_slot_key_ignores_slash_style_and_case(self):
        """Основная сборка отдаёт путь с обратными слэшами, стиль — с прямыми."""
        self.assertEqual(texture_slot_key(chr(92).join(("console", "models", "hat")), "Hat"),
                         texture_slot_key("console/models/hat/", "hat"))

    def test_styles_in_different_material_folders_do_not_clash(self):
        """211 из 273 шапок держат стили в разных папках — им конфликта нет."""
        seen = {}
        for folder, img in (("console/models/a", "up.png"),
                            ("console/models/b", "down.png")):
            VpkModelPipeline._write_style_textures(
                self._qc(QC_SINGLE),
                {"textures": {Team.RED: {"hat_style2": self._img(img)}}},
                None, "hat_style2", self.dir, self.dir / "base.vmt",
                folder, (512, 512), "DXT5", [], {},
                written_textures=seen, ctx=self.ctx)
        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main()
