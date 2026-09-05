import unittest

from src.data.skyboxes import (
    SKY_ALL_MAPS_KEY,
    SKY_FACE_LABELS,
    SKY_FACES,
    SKY_PANO_KEY,
    SKY_PREVIEW_DEFAULT,
    SKY_SIDE_FACES,
    STOCK_SKY_NAMES,
    stock_face_stems,
)
from src.services.skybox_service import SkyboxService


class SkyboxesDataTests(unittest.TestCase):
    def test_stock_list_sane(self):
        self.assertTrue(STOCK_SKY_NAMES)
        self.assertEqual(len(STOCK_SKY_NAMES), len(set(STOCK_SKY_NAMES)))
        self.assertEqual(STOCK_SKY_NAMES, sorted(STOCK_SKY_NAMES))
        for name in STOCK_SKY_NAMES:
            self.assertTrue(name.startswith("sky_"), name)
            self.assertFalse(name.endswith("_hdr"), name)

    def test_faces_and_labels_consistent(self):
        self.assertEqual(set(SKY_FACES), set(SKY_FACE_LABELS))
        for face, labels in SKY_FACE_LABELS.items():
            self.assertIn("ru", labels, face)
            self.assertIn("en", labels, face)

    def test_service_keys_do_not_collide_with_faces(self):
        # Служебные ключи карточек не должны совпадать с гранями/именами небес.
        self.assertNotIn(SKY_PANO_KEY, SKY_FACES)
        self.assertNotIn(SKY_ALL_MAPS_KEY, STOCK_SKY_NAMES)

    def test_preview_default_is_stock(self):
        # На SKY_PREVIEW_DEFAULT держится превью пункта «Все карты».
        self.assertIn(SKY_PREVIEW_DEFAULT, STOCK_SKY_NAMES)


class StockFaceNamesTests(unittest.TestCase):
    """Как в игре зовутся текстуры стоковых небес.

    Пока грань искали одним именем `<небо><грань>`, у любого стокового неба
    находились только верх и низ: боковые грани у всех четыре, а текстура одна
    и зовётся `side`.
    """

    def test_side_faces_fall_back_to_the_shared_texture(self):
        for face in SKY_SIDE_FACES:
            stems = stock_face_stems('sky_dustbowl_01', face)
            self.assertIn('sky_dustbowl_01side', stems, face)
            self.assertIn('sky_dustbowl_01_side', stems, face)
            # Своё имя грани идёт первым: у неба с настоящими шестью
            # текстурами общая `side` не должна их перебивать.
            self.assertEqual(stems[0], f'sky_dustbowl_01{face}')

    def test_top_and_bottom_have_no_side_fallback(self):
        for face in ('up', 'dn'):
            stems = stock_face_stems('sky_harvest_01', face)
            self.assertEqual(stems, ['sky_harvest_01' + face,
                                     'sky_harvest_01_' + face])

    def test_every_face_is_covered(self):
        for face in SKY_FACES:
            self.assertTrue(stock_face_stems('sky_tf2_04', face), face)


class EnumerateSkyNamesTests(unittest.TestCase):
    def setUp(self):
        # Кэш enumerate_sky_names живёт на модуле — изолируем тесты.
        import src.services.skybox_service as m
        m._sky_names_cache.clear()

    def test_scan_result_merges_with_fallback_sorted(self):
        from unittest.mock import patch
        pak = ["materials/skybox/sky_extra_01up.vmt"]
        with patch("os.path.exists", return_value=True), \
             patch("src.services.skybox_service.open_vpk_cached", return_value=pak):
            names = SkyboxService.enumerate_sky_names(r"C:\fake_tf2")
        self.assertIn("sky_extra_01", names)
        self.assertTrue(set(STOCK_SKY_NAMES) <= set(names))
        self.assertEqual(names, sorted(names))

    def test_scan_error_falls_back(self):
        from unittest.mock import patch
        with patch("os.path.exists", return_value=True), \
             patch("src.services.skybox_service.open_vpk_cached",
                   side_effect=RuntimeError("boom")):
            names = SkyboxService.enumerate_sky_names(r"C:\fake_tf2")
        self.assertEqual(names, sorted(STOCK_SKY_NAMES))

    def test_result_is_cached_per_root(self):
        from unittest.mock import patch
        pak = ["materials/skybox/sky_extra_01up.vmt"]
        with patch("os.path.exists", return_value=True), \
             patch("src.services.skybox_service.open_vpk_cached",
                   return_value=pak) as opener:
            SkyboxService.enumerate_sky_names(r"C:\fake_tf2")
            SkyboxService.enumerate_sky_names(r"C:\fake_tf2")
        self.assertEqual(opener.call_count, 1)

    def test_no_root_returns_fallback(self):
        self.assertEqual(
            SkyboxService.enumerate_sky_names(""), sorted(STOCK_SKY_NAMES)
        )

    def test_missing_root_returns_fallback(self):
        self.assertEqual(
            SkyboxService.enumerate_sky_names(r"Z:\no\such\dir"),
            sorted(STOCK_SKY_NAMES),
        )

    def test_scan_parses_names_and_skips_hdr(self):
        pak = iter([
            "materials/skybox/sky_upwardup.vmt",
            "materials/skybox/sky_upwarddn.vmt",           # не up-грань — мимо
            "materials/skybox/sky_upward_hdrup.vmt",       # HDR-вариант — мимо
            "materials/skybox/sky_newmap_01up.vmt",
            "materials/skybox/nested/sky_xup.vmt",         # вложенная папка — мимо
            "materials/other/sky_fakeup.vmt",              # не skybox — мимо
            "materials/skybox/up.vmt",                     # пустое имя — мимо
        ])
        self.assertEqual(
            SkyboxService._scan_sky_names(pak),
            {"sky_upward", "sky_newmap_01"},
        )

    def test_scan_normalizes_case_and_slashes(self):
        pak = iter([r"materials\skybox\SKY_Upwardup.vmt"])
        self.assertEqual(SkyboxService._scan_sky_names(pak), {"sky_upward"})


if __name__ == "__main__":
    unittest.main()
