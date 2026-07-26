"""Пер-режимный фильтр списка VTF-форматов (src/ui/format_choices.py).

Чистая логика без Qt: резолвер допустимого набора (источник истины — сервис
режима) + план перезаполнения комбобокса, включая edge-case «crit после skybox»
(полный список должен вернуться, иначе DXT5 недоступен).
"""
import unittest

from src.ui.format_choices import (
    VTF_FORMATS, CRIT_ALLOWED_FORMATS, SKYBOX_ALLOWED_FLAGS,
    allowed_flags_for_mode, allowed_formats_for_mode, plan_format_choices,
)
from src.services.skybox_service import SKYBOX_ALLOWED_FORMATS
from src.data.skyboxes import SKYBOX_MODE


class AllowedFormatsForModeTests(unittest.TestCase):
    def test_skybox_uses_service_source_of_truth(self):
        self.assertEqual(
            allowed_formats_for_mode(SKYBOX_MODE), list(SKYBOX_ALLOWED_FORMATS)
        )

    def test_crithit_alpha_capable_set_dxt5_default(self):
        allowed = allowed_formats_for_mode("critHIT")
        self.assertEqual(allowed, list(CRIT_ALLOWED_FORMATS))
        self.assertEqual(allowed[0], "DXT5")  # первый = дефолт
        # только форматы с альфа-каналом (без DXT1/RGB888)
        self.assertNotIn("DXT1", allowed)
        self.assertNotIn("RGB888", allowed)

    def test_other_modes_unrestricted(self):
        self.assertIsNone(allowed_formats_for_mode("scout_c_scattergun"))


class AllowedFlagsForModeTests(unittest.TestCase):
    def test_skybox_shows_only_pointsample(self):
        """Остальные флаги/опции к граням неба не относятся: CLAMP и мипы
        сервис ставит сам, normal/reflectivity/gamma не про шейдер sky."""
        allowed = allowed_flags_for_mode(SKYBOX_MODE)
        self.assertEqual(allowed, ["POINTSAMPLE"])
        self.assertEqual(allowed, list(SKYBOX_ALLOWED_FLAGS))
        for irrelevant in ("CLAMPS", "NOMIP", "NOMINMIP", "NORMAL"):
            self.assertNotIn(irrelevant, allowed)

    def test_other_modes_unrestricted(self):
        self.assertIsNone(allowed_flags_for_mode("scout_c_scattergun"))
        self.assertIsNone(allowed_flags_for_mode("critHIT"))


class PlanFormatChoicesTests(unittest.TestCase):
    def test_skybox_narrows_list(self):
        plan = plan_format_choices(VTF_FORMATS, "DXT5", list(SKYBOX_ALLOWED_FORMATS))
        target, idx = plan
        self.assertEqual(target, list(SKYBOX_ALLOWED_FORMATS))
        # DXT5 не входит в skybox-набор → первый элемент
        self.assertEqual(idx, 0)

    def test_preserves_valid_selection(self):
        plan = plan_format_choices(VTF_FORMATS, "BGR888", list(SKYBOX_ALLOWED_FORMATS))
        target, idx = plan
        self.assertEqual(target[idx], "BGR888")

    def test_none_returns_full_list(self):
        plan = plan_format_choices(list(SKYBOX_ALLOWED_FORMATS), "DXT1", None)
        target, idx = plan
        self.assertEqual(target, VTF_FORMATS)
        # crit после skybox: DXT5 снова в списке
        self.assertIn("DXT5", target)

    def test_noop_when_already_matching(self):
        self.assertIsNone(plan_format_choices(VTF_FORMATS, "DXT1", None))
        self.assertIsNone(plan_format_choices(
            list(SKYBOX_ALLOWED_FORMATS), "DXT1", list(SKYBOX_ALLOWED_FORMATS)))


if __name__ == "__main__":
    unittest.main()
