"""Тесты мультиклассовых шапок в hats_parser: поле HatItem.per_class_models."""

import unittest
import tempfile
from pathlib import Path

from src.data import hats_parser
from src.data.hats_parser import _extract_per_class_models, parse_hats


_ITEMS_GAME = '''
"items_game"
{
    "items"
    {
        "100"
        {
            "name" "multiclass_per_class_hat"
            "item_name" "#multiclass_hat"
            "item_slot" "head"
            "model_player_per_class"
            {
                "scout"   "models/player/items/scout/PerClassHat.mdl"
                "soldier" "models\\player\\items\\soldier\\PerClassHat.mdl"
                "demoman" "models/player/items/demo/PerClassHat.mdl"
            }
            "used_by_classes"
            {
                "scout"   "1"
                "soldier" "1"
                "demoman" "1"
            }
        }
        "200"
        {
            "name" "template_hat"
            "item_name" "#template_hat"
            "item_slot" "head"
            "model_player" "models/player/items/all_class/gibus_%s.mdl"
            "used_by_classes"
            {
                "scout"    "1"
                "soldier"  "1"
                "pyro"     "1"
                "demoman"  "1"
                "heavy"    "1"
                "engineer" "1"
                "medic"    "1"
                "sniper"   "1"
                "spy"      "1"
            }
        }
        "300"
        {
            "name" "single_model_hat"
            "item_name" "#single_hat"
            "item_slot" "head"
            "model_player" "models/player/items/hat/SingleHat.mdl"
            "used_by_classes"
            {
                "scout" "1"
            }
        }
        "400"
        {
            "name" "basename_template_hat"
            "item_name" "#basename_hat"
            "item_slot" "head"
            "model_player_per_class"
            {
                "basename" "models/player/items/all_class/basename_%s.mdl"
            }
        }
    }
}
'''


class ExtractPerClassModelsTests(unittest.TestCase):
    def test_extracts_all_classes_normalized(self):
        block = (
            '"x" { "model_player_per_class" { '
            '"heavy" "models/player/items/heavy/a.mdl" '
            '"scout" "models\\player\\items\\scout\\B.MDL" } }'
        )
        result = _extract_per_class_models(block)
        self.assertEqual(result, {
            "heavy": "models/player/items/heavy/a.mdl",
            "scout": "models/player/items/scout/b.mdl",
        })

    def test_no_block_returns_empty(self):
        self.assertEqual(
            _extract_per_class_models('"x" { "model_player" "a.mdl" }'), {})

    def test_unknown_class_ignored(self):
        block = '"x" { "model_player_per_class" { "alien" "models/a.mdl" } }'
        self.assertEqual(_extract_per_class_models(block), {})


class ParseHatsMulticlassTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        items_dir = root / "tf" / "scripts" / "items"
        items_dir.mkdir(parents=True)
        (items_dir / "items_game.txt").write_text(_ITEMS_GAME, encoding="utf-8")
        self.root = str(root)
        # Изолируем кэш, чтобы не трогать реальный cache/.
        self._cache_backup = hats_parser._CACHE_FILE
        hats_parser._CACHE_FILE = root / "cache.json"

    def tearDown(self):
        hats_parser._CACHE_FILE = self._cache_backup
        self._tmp.cleanup()

    def _by_name(self, items):
        return {h.internal_name: h for h in items}

    def test_per_class_and_template_and_single(self):
        items = parse_hats(self.root, language="en", force_reparse=True)
        by = self._by_name(items)

        # 1) model_player_per_class → все 3 класса, пути нормализованы.
        pc = by["multiclass_per_class_hat"]
        self.assertEqual(pc.per_class_models, {
            "scout":   "models/player/items/scout/perclasshat.mdl",
            "soldier": "models/player/items/soldier/perclasshat.mdl",
            "demoman": "models/player/items/demo/perclasshat.mdl",
        })

        # 2) %s-шаблон → раскрытие по всем 9 классам.
        tmpl = by["template_hat"]
        self.assertEqual(len(tmpl.per_class_models), 9)
        self.assertEqual(tmpl.per_class_models["heavy"],
                         "models/player/items/all_class/gibus_heavy.mdl")

        # 3) одиночная модель → per_class_models пуст.
        single = by["single_model_hat"]
        self.assertEqual(single.per_class_models, {})

        # 4) %s в basename внутри model_player_per_class, без used_by_classes
        #    → раскрытие по всем 9 классам.
        bn = by["basename_template_hat"]
        self.assertEqual(len(bn.per_class_models), 9)
        self.assertEqual(bn.per_class_models["spy"],
                         "models/player/items/all_class/basename_spy.mdl")


if __name__ == "__main__":
    unittest.main()
