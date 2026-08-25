"""
Праздничные «пушки» из списка — на самом деле навесная гирлянда.

items_game объявляет их через "attached_models": игра рисует базовое оружие,
а сверху вешает отдельную модель. У c_minigun_xmas в модели ровно два
материала, и оба — лампочки. Перекраска такой записи меняет украшение, а не
ствол, и об этом надо сказать вслух: иначе выглядит так, будто мод не работает.

Формат блоков взят из настоящего items_game.txt (12 таких записей в списке
приложения: c_minigun_xmas, c_scattergun_xmas, c_knife_xmas и др.).
"""

import unittest
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory

from src.data import weapon_model_index as WMI

ITEMS_GAME = '''"items_game"
{
	"items"
	{
		"200"
		{
			"name" "TF_WEAPON_MINIGUN"
			"model_player" "models\\\\weapons\\\\c_models\\\\c_minigun\\\\c_minigun.mdl"
		}
		"654"
		{
			"name" "Festive Minigun"
			"visuals"
			{
				"attached_models"
				{
					"0"
					{
						"model" "models\\\\weapons\\\\c_models\\\\c_minigun\\\\c_minigun_xmas.mdl"
					}
				}
			}
		}
		"999"
		{
			"name" "Both ways"
			"model_player" "models\\\\weapons\\\\c_models\\\\c_bow\\\\c_bow.mdl"
			"visuals"
			{
				"attached_models"
				{
					"0"
					{
						"model" "models\\\\weapons\\\\c_models\\\\c_bow\\\\c_bow.mdl"
					}
				}
			}
		}
	}
}
'''


class AttachmentOnlyModelsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        scripts = root / "tf" / "scripts" / "items"
        scripts.mkdir(parents=True)
        (scripts / "items_game.txt").write_text(ITEMS_GAME, encoding="utf-8")
        self.root = str(root)
        WMI._MEM.pop(self.root, None)
        WMI._MEM_ATTACHED.pop(self.root, None)
        # Кэш индекса лежит по ОТНОСИТЕЛЬНОМУ пути cache/weapon_paths_cache.json:
        # без подмены тест затирает настоящий кэш пользователя своими двумя
        # записями, и приложение потом читает их как индекс игры.
        self._cache_patch = patch.object(WMI, "_CACHE_FILE", root / "cache.json")
        self._cache_patch.start()

    def tearDown(self):
        self._cache_patch.stop()
        WMI._MEM.pop(self.root, None)
        WMI._MEM_ATTACHED.pop(self.root, None)
        self._tmp.cleanup()

    def test_garland_is_reported_as_attachment(self):
        self.assertIn("c_minigun_xmas", WMI.attachment_only_models(self.root))

    def test_real_weapon_is_not_an_attachment(self):
        self.assertNotIn("c_minigun", WMI.attachment_only_models(self.root))

    def test_model_used_as_both_is_not_an_attachment(self):
        """Если модель где-то объявлена как model_player — это оружие."""
        self.assertNotIn("c_bow", WMI.attachment_only_models(self.root))

    def test_missing_items_game_is_not_an_error(self):
        self.assertEqual(WMI.attachment_only_models("D:/нет/такого"), set())
        self.assertEqual(WMI.attachment_only_models(""), set())

    def test_result_is_memoized(self):
        first = WMI.attachment_only_models(self.root)
        self.assertIs(first, WMI.attachment_only_models(self.root))


if __name__ == "__main__":
    unittest.main()
