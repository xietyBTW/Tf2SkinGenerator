"""Тесты мультиклассовых шапок в hats_parser: поле HatItem.per_class_models."""

import unittest
import unittest.mock
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


_ITEMS_GAME_CASES = '''
"items_game"
{
    "items"
    {
        "900"
        {
            "name" "real_hat"
            "item_name" "#real_hat"
            "item_slot" "head"
            "model_player" "models/player/items/all_class/real_hat.mdl"
        }
        "901"
        {
            "name" "abominable_cosmetic_case"
            "item_name" "#TF_CosmeticCase"
            "prefab" "base_cosmetic_case"
            "tool" { "type" "supply_crate" }
            "model_player" "models/player/items/crafting/cosmetic_case.mdl"
        }
        "902"
        {
            "name" "some_weapon_crate"
            "item_name" "#TF_Crate"
            "prefab" "eventcratebase"
            "model_player" "models/player/items/crafting/eventcrate.mdl"
        }
    }
}
'''


class ParseHatsCaseExclusionTests(unittest.TestCase):
    """Кейсы/ящики/крафт-инструменты не должны попадать в список шапок."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        items_dir = root / "tf" / "scripts" / "items"
        items_dir.mkdir(parents=True)
        (items_dir / "items_game.txt").write_text(_ITEMS_GAME_CASES, encoding="utf-8")
        self.root = str(root)
        self._cache_backup = hats_parser._CACHE_FILE
        hats_parser._CACHE_FILE = root / "cache.json"

    def tearDown(self):
        hats_parser._CACHE_FILE = self._cache_backup
        self._tmp.cleanup()

    def test_cases_excluded_hats_kept(self):
        items = parse_hats(self.root, language="en", force_reparse=True)
        names = {h.internal_name for h in items}
        self.assertIn("real_hat", names)
        self.assertNotIn("abominable_cosmetic_case", names)   # prefab + tool + crafting
        self.assertNotIn("some_weapon_crate", names)          # prefab crate


class HatItemFlagTests(unittest.TestCase):
    """Флаги для фильтра списка шапок (медали / сезонное)."""

    def _hat(self, **kw):
        from src.data.hats_parser import HatItem
        base = dict(defindex="1", name="x", internal_name="x", mdl_path="m",
                    classes=[], slot="head")
        base.update(kw)
        return HatItem(**base)

    def test_is_medal_from_item_type(self):
        self.assertTrue(self._hat(item_type="#TF_Wearable_CommunityMedal").is_medal)
        self.assertTrue(self._hat(item_type="#TF_Wearable_TournamentMedal").is_medal)
        self.assertTrue(self._hat(item_type="#TF_Wearable_Medallion").is_medal)
        self.assertFalse(self._hat(item_type="#TF_Wearable_Hat").is_medal)
        self.assertFalse(self._hat().is_medal)

    def test_is_medal_from_prefab_and_item_name(self):
        # Турнирные медали: item_type_name наследуется через prefab и в блоке
        # отсутствует — детекция должна ловить их по prefab и по item_name.
        self.assertTrue(self._hat(prefab="tournament_medal").is_medal)
        self.assertTrue(self._hat(prefab="etf2l_participation_styles tournament_medal").is_medal)
        self.assertTrue(self._hat(item_name_token="#TF_TournamentMedal_AFC_Div1_1st").is_medal)
        self.assertFalse(self._hat(prefab="hat", item_name_token="#Some_Cool_Hat").is_medal)

    def test_halloween_and_holiday(self):
        h = self._hat(holiday="halloween_or_fullmoon")
        self.assertTrue(h.is_halloween)
        self.assertTrue(h.is_holiday)
        x = self._hat(holiday="christmas")
        self.assertFalse(x.is_halloween)
        self.assertTrue(x.is_holiday)
        n = self._hat()
        self.assertFalse(n.is_halloween)
        self.assertFalse(n.is_holiday)


class DemomanModelTokenTests(unittest.TestCase):
    """У подрывника файлы моделей называются `_demo`, а не `_demoman`."""

    ITEMS = """
"items_game"
{
    "items"
    {
        "200"
        {
            "name" "all_class_template_hat"
            "item_name" "#template_hat"
            "item_slot" "head"
            "model_player" "models/player/items/all_class/template_%s.mdl"
        }
    }
}
"""

    def test_template_expands_with_the_path_token(self):
        """Раскрывая %s именем класса, мод оставался без модели подрывника —
        такого файла в игре нет (там 910 моделей `_demo` и ни одной `_demoman`)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "tf" / "scripts" / "items"
            items.mkdir(parents=True)
            (items / "items_game.txt").write_text(self.ITEMS, encoding="utf-8")
            (root / "tf" / "resource").mkdir(parents=True)
            with unittest.mock.patch.object(
                    hats_parser, "_CACHE_FILE", root / "cache.json"):
                hats = parse_hats(str(root), "en", force_reparse=True)

        hat = next(h for h in hats if h.internal_name == "all_class_template_hat")
        self.assertEqual(len(hat.per_class_models), 9)
        self.assertTrue(hat.per_class_models["demoman"].endswith("template_demo.mdl"))
        self.assertTrue(hat.per_class_models["scout"].endswith("template_scout.mdl"))


if __name__ == "__main__":
    unittest.main()
