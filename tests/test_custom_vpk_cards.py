"""Тесты обнаружения текстур custom-VPK мода (CustomVPKService.discover_textures).

Обнаружение идёт по самим VTF-файлам — чтобы показать ВСЕ текстуры мода
(включая стили), не завися от полноты VMT. Порядок RED-перед-BLU и отрисовка
превью — это слой 2D-карточек UI (preview_vpk_mod_worker), здесь не проверяется.
"""

import os
import shutil
import tempfile
import unittest

from src.services.custom_vpk_service import CustomVPKService


def _touch(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00")  # содержимое неважно — discovery по факту наличия файла


class DiscoverTexturesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.extract = os.path.join(self.tmp, "vpkroot")
        self.mat = os.path.join(self.extract, "materials", "models", "w")
        os.makedirs(self.mat)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_discovers_red_and_blue_with_flags(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        _touch(os.path.join(self.mat, "c_w_blue.vtf"))
        textures = CustomVPKService.discover_textures(self.extract)
        by_name = {t['name']: t for t in textures}
        self.assertEqual(set(by_name), {"c_w", "c_w_blue"})
        self.assertFalse(by_name["c_w"]['is_blue'])
        self.assertTrue(by_name["c_w_blue"]['is_blue'])

    def test_two_textures_same_folder_both_shown(self):
        _touch(os.path.join(self.mat, "skin1.vtf"))
        _touch(os.path.join(self.mat, "skin2.vtf"))
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual(len(textures), 2)
        self.assertEqual(len({t['name'] for t in textures}), 2)

    def test_multistyle_same_name_different_folders_kept(self):
        _touch(os.path.join(self.extract, "materials", "a", "c_w.vtf"))
        _touch(os.path.join(self.extract, "materials", "b", "c_w.vtf"))
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual(len(textures), 2)
        self.assertEqual(len({t['name'] for t in textures}), 2)  # ключи уникальны

    def test_service_vtf_excluded(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        _touch(os.path.join(self.mat, "c_w_normal.vtf"))
        _touch(os.path.join(self.mat, "lightwarp.vtf"))
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual([t['name'] for t in textures], ["c_w"])

    def test_vmt_path_linked_when_present(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        _touch(os.path.join(self.mat, "c_w.vmt"))
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual(len(textures), 1)
        self.assertTrue(textures[0]['vmt_path'].endswith("c_w.vmt"))

    def test_no_vtf_no_textures(self):
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual(textures, [])

    def test_single_name_not_disambiguated(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual(textures[0]['name'], 'c_w')
        self.assertEqual(textures[0]['vtf_name'], 'c_w')


if __name__ == "__main__":
    unittest.main()
