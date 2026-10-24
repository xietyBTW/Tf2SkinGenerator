"""
Данные вьюмодели: пути моделей классов и разбор items_game.txt

items_game - единственный авторитетный источник того, какую анимацию играет
конкретное оружие. Проверяется то, на чём наивный разбор ломается:
наследование через prefab (у стокового оружия и модель, и класс объявлены в
prefab, а не в предмете) и приоритет anim_slot над слотом инвентаря
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.data import items_game_kv, viewmodel_anims
from src.data.viewmodel_anims import WeaponAnimInfo

ITEMS_GAME = '''
"items_game"
{
    "prefabs"
    {
        "weapon_scattergun"
        {
            "item_class"  "tf_weapon_scattergun"
            "item_slot"   "primary"
            "model_player" "models/weapons/c_models/c_scattergun.mdl"
        }
        "weapon_sword"
        {
            "anim_slot"   "item1"
        }
        "valve_weapon"
        {
            "quality" "unique"
        }
    }
    "items"
    {
        "13"
        {
            "name"   "Scattergun"
            "prefab" "valve_weapon weapon_scattergun"
        }
        "45"
        {
            "name"        "Force-A-Nature"
            "prefab"      "weapon_scattergun"
            "anim_slot"   "item2"
            "model_player" "models/weapons/c_models/c_double_barrel.mdl"
        }
        "356"
        {
            "name"        "Conniver's Kunai"
            "prefab"      "weapon_scattergun"
            "model_player" "models/weapons/c_models/c_shogun_kunai.mdl"
            "visuals"
            {
                "animation_replacement"
                {
                    "ACT_VM_IDLE"       "ACT_ITEM2_VM_IDLE"
                    "ACT_VM_DRAW""ACT_ITEM2_VM_DRAW"
                    "ACT_VM_HITCENTER"  "ACT_ITEM2_VM_HITCENTER"
                }
            }
        }
        "9"
        {
            "name"         "Engineer Shotgun"
            "item_class"   "tf_weapon_shotgun_primary"
            "item_slot"    "primary"
            "model_player" "models/weapons/c_models/c_shotgun/c_shotgun.mdl"
            "used_by_classes" { "engineer" "1" }
        }
        "199"
        {
            "name"         "Upgradeable Shotgun"
            "item_class"   "tf_weapon_shotgun"
            "item_slot"    "secondary"
            "model_player" "models/weapons/c_models/c_shotgun/c_shotgun.mdl"
            "used_by_classes"
            {
                "soldier"  "1"
                "heavy"    "1"
                "engineer" "primary"
            }
        }
        "357"
        {
            "name"         "The Half-Zatoichi"
            "prefab"       "weapon_sword"
            "item_class"   "tf_weapon_katana"
            "anim_slot"    ""
            "item_slot"    "melee"
            "model_player" "models/weapons/c_models/c_shogun_katana.mdl"
        }
        "129"
        {
            "name"           "The Buff Banner"
            "item_class"     "tf_weapon_buff_item"
            "item_slot"      "secondary"
            "anim_slot"      "melee"
            "model_player"   "models/weapons/c_models/c_bugle/c_bugle.mdl"
            "extra_wearable" "models/weapons/c_models/c_buffpack/c_buffpack.mdl"
        }
        "999"
        {
            "name" "Не оружие: без модели"
            "item_class" "tf_wearable"
        }
    }
}
'''


class ClassModelPathTests(unittest.TestCase):
    def test_every_class_resolves_to_both_models(self):
        for tf2_class in viewmodel_anims.CLASS_MODEL_STEM:
            self.assertTrue(viewmodel_anims.arms_mdl(tf2_class))
            self.assertTrue(viewmodel_anims.animations_mdl(tf2_class))

    def test_demoman_models_are_named_demo(self):
        """Склейка по названию класса дала бы c_demoman_arms.mdl, которого нет"""
        self.assertEqual(viewmodel_anims.arms_mdl("demoman"),
                         "models/weapons/c_models/c_demo_arms.mdl")
        self.assertEqual(viewmodel_anims.animations_mdl("demoman"),
                         "models/weapons/c_models/c_demo_animations.mdl")

    def test_unknown_class_is_none_not_a_broken_path(self):
        self.assertIsNone(viewmodel_anims.arms_mdl("engie"))
        self.assertIsNone(viewmodel_anims.animations_mdl(""))


class ItemsGameParsingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self.items = base / "items_game.txt"
        self.items.write_text(ITEMS_GAME, encoding="utf-8")
        self.cache = base / "anim_cache.json"

        viewmodel_anims._MEM.clear()
        self._patches = [
            patch.object(viewmodel_anims, "_CACHE_FILE", self.cache),
            patch.object(viewmodel_anims, "get_items_game_path",
                         lambda _root: self.items),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        viewmodel_anims._MEM.clear()
        self._tmp.cleanup()

    def test_stock_weapon_inherits_model_and_class_from_prefab(self):
        """У стокового оружия в самом предмете нет ни модели, ни item_class"""
        info = viewmodel_anims.anim_info("c_scattergun", "root")
        self.assertEqual(info, WeaponAnimInfo(item_class="tf_weapon_scattergun",
                                              anim_slot="", item_slot="primary"))
        self.assertEqual(info.slot, "primary")

    def test_anim_slot_wins_over_inventory_slot(self):
        """Неумолимая сила лежит в primary, а анимируется как item2"""
        info = viewmodel_anims.anim_info("c_double_barrel", "root")
        self.assertEqual(info.item_slot, "primary")
        self.assertEqual(info.anim_slot, "item2")
        self.assertEqual(info.slot, "item2")

    def test_animation_replacement_is_read(self):
        """Слот не единственный источник: у куная он melee, а набор - ITEM2

        Пока подмена не читалась, почти все ножи шпиона показывали анимацию
        обычного ножа-бабочки
        """
        info = viewmodel_anims.anim_info("c_shogun_kunai", "root")
        # Средняя пара записана слитно, как у Valve в Shortstop: пока разбор
        # требовал пробел, всё ниже неё съезжало на одну позицию
        self.assertEqual(info.replacement, {
            "ACT_VM_IDLE": "ACT_ITEM2_VM_IDLE",
            "ACT_VM_DRAW": "ACT_ITEM2_VM_DRAW",
            "ACT_VM_HITCENTER": "ACT_ITEM2_VM_HITCENTER",
        })
        # У обычного оружия подмены нет - слота достаточно
        self.assertEqual(
            viewmodel_anims.anim_info("c_scattergun", "root").replacement, {})

    def test_replacement_survives_the_cache(self):
        """JSON не знает кортежей - на возврате из кэша легко потерять форму"""
        viewmodel_anims.anim_index("root")
        viewmodel_anims._MEM.clear()
        with patch.object(viewmodel_anims.items_game_kv.ItemsGame, "parse",
                          side_effect=AssertionError("items_game читать не должны")):
            info = viewmodel_anims.anim_info("c_shogun_kunai", "root")
        self.assertEqual(info.replacement["ACT_VM_IDLE"], "ACT_ITEM2_VM_IDLE")

    def test_festive_variant_falls_back_to_the_base_weapon(self):
        """c_scattergun_xmas в items_game нет - анимации те же, что у базы"""
        self.assertEqual(viewmodel_anims.anim_info("c_scattergun_xmas", "root"),
                         viewmodel_anims.anim_info("c_scattergun", "root"))

    def test_items_without_a_model_are_skipped(self):
        self.assertNotIn("", viewmodel_anims.anim_index("root"))
        self.assertEqual(len(viewmodel_anims.anim_index("root")), 7)

    def test_worn_banner_knows_what_is_held(self):
        """Знамя в каталоге - рюкзак (extra_wearable), а в руке - дудка

        Без этого вид от первого лица сажал в руку рюкзак и писал, что
        анимаций нет
        """
        pack = viewmodel_anims.anim_info("c_buffpack", "root")
        self.assertEqual((pack.held, pack.item_class), ("c_bugle", "tf_weapon_buff_item"))
        self.assertEqual(viewmodel_anims.anim_info("c_bugle", "root").held, "")

    def test_loadout_slot_depends_on_the_class(self):
        """Одна модель дробовика - у инженера основной, у остальных вторичный

        Слоты собираются со всех предметов модели, первый предмет не решает
        """
        self.assertEqual(viewmodel_anims.loadout_slot("c_shotgun", "root", "engineer"),
                         "primary")
        for tf2_class in ("soldier", "heavy"):
            self.assertEqual(viewmodel_anims.slot_for("c_shotgun", "root", tf2_class),
                             "secondary", tf2_class)
        # Без класса - общий слот первого предмета, как было
        self.assertEqual(viewmodel_anims.slot_for("c_shotgun", "root"), "primary")

    def test_class_slots_survive_the_cache(self):
        viewmodel_anims.anim_index("root")
        viewmodel_anims._MEM.clear()
        self.assertEqual(viewmodel_anims.loadout_slot("c_shotgun", "root", "heavy"),
                         "secondary")

    def test_own_empty_anim_slot_cancels_the_prefab(self):
        """Полу-Дзатоити: `"anim_slot" ""` при префабе с другим слотом

        По префабу солдат махал катаной анимациями Знамени (item1)
        """
        self.assertEqual(viewmodel_anims.anim_info("c_shogun_katana", "root").anim_slot, "")
        self.assertEqual(viewmodel_anims.slot_for("c_shogun_katana", "root", "soldier"),
                         "melee")

    def test_unknown_weapon_is_none(self):
        self.assertIsNone(viewmodel_anims.anim_info("c_nonexistent", "root"))
        self.assertIsNone(viewmodel_anims.anim_info("", "root"))

    def test_index_is_cached_on_disk_and_reused(self):
        viewmodel_anims.anim_index("root")
        self.assertTrue(self.cache.exists())
        self.assertIn("c_scattergun",
                      json.loads(self.cache.read_text(encoding="utf-8"))["items"])

        # Разбор из кэша обязан дать тот же результат - без чтения items_game
        viewmodel_anims._MEM.clear()
        with patch.object(viewmodel_anims.items_game_kv.ItemsGame, "parse",
                          side_effect=AssertionError("items_game читать не должны")):
            info = viewmodel_anims.anim_info("c_double_barrel", "root")
        self.assertEqual(info.anim_slot, "item2")

    def test_stale_cache_is_ignored(self):
        viewmodel_anims.anim_index("root")
        viewmodel_anims._MEM.clear()
        # items_game новее кэша - данные обязаны перечитаться
        import os
        os.utime(self.items, (self.cache.stat().st_mtime + 100,) * 2)
        self.assertIsNotNone(viewmodel_anims.anim_info("c_scattergun", "root"))

    def test_slot_prefers_items_game_over_our_own_table(self):
        """У шпиона револьвер у нас во вкладке Primary, а в игре - secondary

        Последовательности `primary_*` у шпиона нет вовсе, так что верить надо
        игре, иначе поза не найдётся
        """
        self.assertEqual(viewmodel_anims.slot_for("c_double_barrel", "root"),
                         "item2")
        self.assertEqual(viewmodel_anims.slot_for("c_scattergun", "root"),
                         "primary")

    def test_slot_falls_back_to_our_table_when_the_game_has_no_such_model(self):
        """Ганслингер и ещё десяток моделей items_game зовёт иначе, чем мы"""
        self.assertEqual(viewmodel_anims.slot_for("c_scattergun_xmas", "root"),
                         "primary")               # через базовое оружие
        self.assertEqual(viewmodel_anims.slot_for("c_bat", "root"), "melee")
        self.assertEqual(viewmodel_anims.slot_for("c_nonexistent", "root"), "")

    def test_missing_items_game_is_survivable(self):
        with patch.object(viewmodel_anims, "get_items_game_path", lambda _r: None):
            viewmodel_anims._MEM.clear()
            self.assertEqual(viewmodel_anims.anim_index("root"), {})
            self.assertIsNone(viewmodel_anims.anim_info("c_scattergun", "root"))


class KeyValuesTests(unittest.TestCase):
    """Примитивы разбора: на них же держится парсер шапок"""

    def test_sections_are_found_at_the_top_level_only(self):
        pos = items_game_kv.find_section(ITEMS_GAME, "items")
        self.assertGreater(pos, 0)
        self.assertEqual(ITEMS_GAME[pos], "{")

    def test_nested_section_with_the_same_name_is_not_taken(self):
        nested = '"items_game"\n{\n "prefabs" { "x" { "items" { "trap" "1" } } }\n' \
                 ' "items" { "13" { "name" "real" } }\n}\n'
        pos = items_game_kv.find_section(nested, "items")
        blocks = dict(items_game_kv.iter_blocks(nested, pos))
        self.assertEqual(list(blocks), ["13"])

    def test_prefab_chain_is_followed_but_bounded(self):
        looping = '"items_game"\n{\n "prefabs" {\n' \
                  '  "a" { "prefab" "b" }\n  "b" { "prefab" "a" }\n }\n' \
                  ' "items" { "1" { "prefab" "a" } }\n}\n'
        game = items_game_kv.ItemsGame.parse(looping)
        self.assertIsNone(game.inherited(game.items[0][1], "item_class"))

    def test_missing_section_yields_nothing(self):
        self.assertEqual(items_game_kv.find_section("", "items"), -1)
        self.assertEqual(list(items_game_kv.iter_blocks("", -1)), [])


if __name__ == "__main__":
    unittest.main()


class WornTests(unittest.TestCase):
    """Что смотрят на персонаже, а что в руке"""

    def _worn(self, **info):
        with patch.object(viewmodel_anims, "anim_info",
                          lambda _key, _root: WeaponAnimInfo(**info)):
            return viewmodel_anims.is_worn("key", "root")

    def test_spy_watch_is_held_despite_force_not_used(self):
        """Quäckenbirdt и Enthusiast's Timepiece показывались «На персонаже»"""
        self.assertFalse(self._worn(item_class="tf_weapon_invis",
                                    anim_slot="force_not_used", item_slot="pda2"))

    def test_boots_and_shields_are_worn(self):
        self.assertTrue(self._worn(item_class="tf_wearable", anim_slot="force_not_used"))
        self.assertTrue(self._worn(item_class="tf_wearable_demoshield",
                                   anim_slot="force_not_used"))

    def test_v_model_watches_show_their_own_view_model(self):
        for key in ("v_hm_watch", "v_ttg_watch_spy"):
            self.assertTrue(viewmodel_anims.viewmodel_mdl(key), key)
