"""Тесты обнаружения текстур и подготовки 2D-карточек для custom-VPK мода.

Обнаружение идёт по самим VTF-файлам (discover_textures) — чтобы показать ВСЕ
текстуры мода (включая стили), не завися от полноты VMT.
"""

import os
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
        self.preview = os.path.join(self.tmp, "preview")
        self.mat = os.path.join(self.extract, "materials", "models", "w")
        os.makedirs(self.mat)

    def test_card_per_vtf_red_before_blue(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        _touch(os.path.join(self.mat, "c_w_blue.vtf"))
        cards = CustomVPKService.build_texture_cards(self.extract, self.preview)
        names = [c['name'] for c in cards]
        self.assertEqual(names, ["c_w", "c_w_blue"])
        self.assertFalse(cards[0]['is_blue'])
        self.assertTrue(cards[1]['is_blue'])

    def test_two_textures_same_folder_both_shown(self):
        # Реальный кейс: 2 текстуры + 2 VMT в одной папке → 2 карточки.
        _touch(os.path.join(self.mat, "skin1.vtf"))
        _touch(os.path.join(self.mat, "skin2.vtf"))
        cards = CustomVPKService.build_texture_cards(self.extract, self.preview)
        self.assertEqual(len(cards), 2)
        self.assertEqual(len({c['name'] for c in cards}), 2)

    def test_multistyle_same_name_different_folders_kept(self):
        _touch(os.path.join(self.extract, "materials", "a", "c_w.vtf"))
        _touch(os.path.join(self.extract, "materials", "b", "c_w.vtf"))
        cards = CustomVPKService.build_texture_cards(self.extract, self.preview)
        self.assertEqual(len(cards), 2)
        self.assertEqual(len({c['name'] for c in cards}), 2)  # ключи уникальны

    def test_service_vtf_excluded(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        _touch(os.path.join(self.mat, "c_w_normal.vtf"))
        _touch(os.path.join(self.mat, "lightwarp.vtf"))
        cards = CustomVPKService.build_texture_cards(self.extract, self.preview)
        self.assertEqual([c['name'] for c in cards], ["c_w"])

    def test_vmt_path_linked_when_present(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        _touch(os.path.join(self.mat, "c_w.vmt"))
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual(len(textures), 1)
        self.assertTrue(textures[0]['vmt_path'].endswith("c_w.vmt"))

    def test_no_vtf_no_cards(self):
        cards = CustomVPKService.build_texture_cards(self.extract, self.preview)
        self.assertEqual(cards, [])

    def test_single_name_not_disambiguated(self):
        _touch(os.path.join(self.mat, "c_w.vtf"))
        textures = CustomVPKService.discover_textures(self.extract)
        self.assertEqual(textures[0]['name'], 'c_w')
        self.assertEqual(textures[0]['vtf_name'], 'c_w')


if __name__ == "__main__":
    unittest.main()
