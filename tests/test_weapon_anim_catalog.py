"""
Каталог анимаций класса: поиск последовательности для оружия и действия

Имена последовательностей наружу не выводятся (`sg_idle`, `db_idle`, `ss_idle`),
зато у каждой в QC стоит активность. Какую активность играть, решает тот же
путь, что в движке, и проверяется именно он - там, где легко ошибиться:

  * какую БАЗОВУЮ активность шлёт оружие (кулаки - HITLEFT, ближний бой -
    HITCENTER, стрелковое - PRIMARYATTACK);
  * подмена из items_game - окончательный ответ, запасных наборов нет;
  * таблица ролей движка (`s_viewmodelacttable`) с её исключениями
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services import weapon_anim_catalog as cat
from src.services.weapon_anim_catalog import Action

# Активности взяты из настоящих QC моделей анимаций TF2
QC = '''
$modelname "weapons/c_models/c_test_animations.mdl"

$sequence "sg_idle" {
	"anims\\sg_idle.smd"
	activity "ACT_PRIMARY_VM_IDLE" 1
	fps 30
	loop
}

$sequence "sg_reload_start" {
	"anims\\sg_reload_start.smd"
	activity "ACT_PRIMARY_RELOAD_START" 1
	fps 30
}

$sequence "db_idle" {
	"anims\\db_idle.smd"
	activity "ACT_ITEM2_VM_IDLE" 1
	fps 30
}

$sequence "ss_idle" {
	"anims\\ss_idle.smd"
	activity "ACT_SECONDARY_VM_IDLE_2" 1
	fps 35
	loop
}

$sequence "melee_allclass_idle" {
	"anims\\melee_allclass_idle.smd"
	activity "ACT_MELEE_ALLCLASS_VM_IDLE" 1
	fps 30
}

$sequence "box_idle" {
	"anims\\box_idle.smd"
	activity "ACT_ENGINEER_BLD_VM_IDLE" 1
	fps 30
}

$sequence "eternal_idle" {
	"anims\\eternal_idle.smd"
	activity "ACT_ITEM2_VM_IDLE" 1
	fps 30
}

$sequence "knife_stab_a" {
	"anims\\knife_stab_a.smd"
	activity "ACT_MELEE_VM_HITCENTER" 1
	fps 30
}

$sequence "offhand_idle" {
	"anims\\offhand_idle.smd"
	activity "ACT_OFFHAND_VM_IDLE" 1
	fps 30
}

$sequence "c_sapper_idle" {
	"anims\\c_sapper_idle.smd"
	activity "ACT_VM_IDLE" 1
	fps 30
}

$sequence "lost_anim" {
	"anims\\not_on_disk.smd"
	activity "ACT_SECONDARY_VM_IDLE" 1
	fps 30
}

$sequence "primary_inspect_idle" {
	"anims\\primary_inspect_idle.smd"
	activity "ACT_PRIMARY_VM_INSPECT_IDLE" 1
	fps 24
	loop
}

$sequence "secondary_inspect_idle" {
	"anims\\secondary_inspect_idle.smd"
	activity "ACT_SECONDARY_VM_INSPECT_IDLE" 1
	fps 30
	loop
}

$sequence "r_handposes" {
	"anims\\r_handposes.smd"
	fps 30
}
'''

ON_DISK = ["sg_idle", "sg_reload_start", "db_idle", "ss_idle",
           "melee_allclass_idle", "box_idle", "r_handposes",
           "eternal_idle", "knife_stab_a", "offhand_idle", "c_sapper_idle",
           "primary_inspect_idle", "secondary_inspect_idle"]


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "c_test_animations.qc").write_text(QC, encoding="utf-8")
        anims = self.dir / "anims"
        anims.mkdir()
        for name in ON_DISK:
            (anims / f"{name}.smd").write_text("version 1\n", encoding="utf-8")
        self.catalog = cat.load(str(self.dir))

    def tearDown(self):
        self._tmp.cleanup()

    # Разбор

    def test_sequence_fields_are_read(self):
        seq = self.catalog.by_name["ss_idle"]
        self.assertEqual(seq.activity, "ACT_SECONDARY_VM_IDLE_2")
        self.assertEqual(seq.fps, 35.0)
        self.assertTrue(seq.loop)
        self.assertTrue(seq.smd_path.endswith("ss_idle.smd"))
        self.assertTrue(seq.exists)

    def test_sequence_without_activity_is_kept_but_not_indexed(self):
        """`r_handposes` есть у всех классов и не является действием оружия"""
        self.assertIn("r_handposes", self.catalog.by_name)
        self.assertEqual(self.catalog.by_name["r_handposes"].activity, "")
        self.assertNotIn("", self.catalog.by_activity)

    def test_loop_is_not_guessed(self):
        self.assertFalse(self.catalog.by_name["db_idle"].loop)

    def test_missing_qc_gives_none(self):
        with TemporaryDirectory() as empty:
            self.assertIsNone(cat.load(empty))
        self.assertIsNone(cat.load(""))

    # Поиск: путь движка

    def _find(self, action, slot, **kw):
        found = self.catalog.find(cat.WeaponProfile(slot=slot, **kw), action)
        return found.name if found else None

    def test_plain_slot(self):
        self.assertEqual(self._find(Action.IDLE, "primary"), "sg_idle")

    def test_numbered_role_is_taken_literally(self):
        """item2 - самостоятельная роль (Неумолимая сила)"""
        self.assertEqual(self._find(Action.IDLE, "item2"), "db_idle")

    def test_reload_activity_has_no_vm_part(self):
        self.assertEqual(self._find(Action.RELOAD_START, "primary"),
                         "sg_reload_start")

    def test_melee_does_not_borrow_the_all_class_set(self):
        """Чего у роли нет, того нет: всеклассовый набор - чужое оружие

        Так Кусай-хлеб получал на удар замах сковородой
        """
        self.assertIsNone(self._find(Action.IDLE, "melee"))
        self.assertEqual(self._find(Action.IDLE, "melee_allclass"),
                         "melee_allclass_idle")

    def test_building_plays_the_base_activity(self):
        """У роли building строк в таблице нет: саппер шпиона - ACT_VM_IDLE"""
        self.assertEqual(self._find(Action.IDLE, "building"), "c_sapper_idle")

    def test_engineer_toolbox_comes_from_the_replacement(self):
        box = {"ACT_VM_IDLE": "ACT_ENGINEER_BLD_VM_IDLE"}
        self.assertEqual(self._find(Action.IDLE, "building", replacement=box),
                         "box_idle")

    def test_sequence_whose_smd_is_gone_is_not_offered(self):
        """Иначе поза бы «нашлась», а файла под ней не оказалось"""
        self.assertIsNone(self._find(Action.IDLE, "secondary"))

    def test_slot_that_is_not_held_in_hands_resolves_to_nothing(self):
        """Щиты, ботинки, тело шпиона: базовая ACT_VM_IDLE нашлась бы - саппер"""
        for slot in ("force_not_used", "playerskin", ""):
            self.assertIsNone(self._find(Action.IDLE, slot), slot)

    def test_unknown_action_for_this_weapon_is_none(self):
        self.assertIsNone(self._find(Action.RELOAD, "item2"))

    def test_actions_for_lists_what_the_weapon_can_do(self):
        """Из этого списка интерфейс потом строит выбор анимации"""
        primary = cat.WeaponProfile(slot="primary", loadout_slot="primary")
        self.assertEqual(set(self.catalog.actions_for(primary)),
                         {Action.IDLE, Action.RELOAD_START, Action.INSPECT_IDLE})
        self.assertEqual(set(self.catalog.actions_for(cat.WeaponProfile(slot="item2"))),
                         {Action.IDLE})

    # Осмотр: по слоту снаряжения

    def test_inspect_follows_the_loadout_slot(self):
        """Гранатомёт: роль secondary, слот снаряжения primary

        Игра берёт осмотр по слоту СНАРЯЖЕНИЯ (GetInspectActivity), и по роли
        гранатомёт получал осмотр липучкомёта - модель разваливалась
        """
        self.assertEqual(self._find(Action.INSPECT_IDLE, "secondary",
                                    loadout_slot="primary"),
                         "primary_inspect_idle")

    def test_inspect_slot_does_not_touch_other_actions(self):
        self.assertEqual(self._find(Action.IDLE, "primary", loadout_slot="secondary"),
                         "sg_idle")

    def test_no_inspect_outside_the_games_table(self):
        """ПДА осматривать нельзя (`CanInspect`)"""
        self.assertIsNone(cat.activity_for(
            cat.WeaponProfile(slot="pda", loadout_slot="pda"), Action.INSPECT_IDLE))

    # Подмена активностей из items_game

    def test_replacement_wins_over_the_role(self):
        """У куная роль melee, а играет он набор ITEM2"""
        kunai = {"ACT_VM_IDLE": "ACT_ITEM2_VM_IDLE"}
        self.assertEqual(self._find(Action.IDLE, "melee", replacement=kunai),
                         "db_idle")   # первая последовательность ACT_ITEM2_VM_IDLE

    def test_replacement_that_points_at_nothing_gives_nothing(self):
        """Подмена - окончательный ответ игры: запасного набора она не ищет"""
        nowhere = {"ACT_VM_IDLE": "ACT_NOSUCH_VM_IDLE"}
        self.assertIsNone(self._find(Action.IDLE, "primary", replacement=nowhere))

    def test_replacement_key_may_carry_the_slot(self):
        """Осмотр подменяется ключом СО слотом: ACT_MELEE_VM_INSPECT_IDLE"""
        kunai = {"ACT_MELEE_VM_INSPECT_IDLE": "ACT_ITEM2_VM_INSPECT_IDLE"}
        self.assertEqual(cat.activity_for(
            cat.WeaponProfile(slot="melee", loadout_slot="melee", replacement=kunai),
            Action.INSPECT_IDLE), "ACT_ITEM2_VM_INSPECT_IDLE")

    # Удары: какую активность шлёт само оружие

    def test_melee_attack_is_hitcenter_and_crit_is_swinghard(self):
        knife = cat.WeaponProfile(slot="melee", loadout_slot="melee")
        self.assertEqual(self.catalog.find(knife, Action.FIRE).name, "knife_stab_a")
        self.assertEqual(cat.activity_for(knife, Action.CRIT),
                         "ACT_MELEE_VM_SWINGHARD")
        self.assertIsNone(cat.activity_for(knife, Action.ALT_FIRE))

    def test_fists_punch_left_and_right(self):
        """Кусай-хлеб: левый удар, правый, крит - и всё через подмену"""
        bread = cat.WeaponProfile(
            slot="melee", loadout_slot="melee", item_class="tf_weapon_fists",
            replacement={"ACT_VM_HITLEFT": "ACT_BREADGLOVES_VM_HITLEFT",
                         "ACT_VM_HITRIGHT": "ACT_BREADGLOVES_VM_HITRIGHT",
                         "ACT_VM_SWINGHARD": "ACT_BREADGLOVES_VM_SWINGHARD"})
        self.assertEqual(cat.activity_for(bread, Action.FIRE),
                         "ACT_BREADGLOVES_VM_HITLEFT")
        self.assertEqual(cat.activity_for(bread, Action.ALT_FIRE),
                         "ACT_BREADGLOVES_VM_HITRIGHT")
        self.assertEqual(cat.activity_for(bread, Action.CRIT),
                         "ACT_BREADGLOVES_VM_SWINGHARD")

    def test_stock_fists_keep_the_untranslated_hit(self):
        """HITLEFT в таблице ролей нет - у стоковых кулаков он так и остаётся"""
        fists = cat.WeaponProfile(slot="melee", loadout_slot="melee",
                                  item_class="tf_weapon_fists")
        self.assertEqual(cat.activity_for(fists, Action.FIRE), "ACT_VM_HITLEFT")

    def test_gun_fires_primaryattack(self):
        gun = cat.WeaponProfile(slot="secondary", loadout_slot="secondary")
        self.assertEqual(cat.activity_for(gun, Action.FIRE),
                         "ACT_SECONDARY_VM_PRIMARYATTACK")
        self.assertIsNone(cat.activity_for(gun, Action.CRIT))

    def test_drink_has_no_throw(self):
        """Бонк и Безумное молоко - один набор ITEM1, но бросает только молоко"""
        drink = cat.WeaponProfile(slot="item1", loadout_slot="secondary",
                                  item_class="tf_weapon_lunchbox_drink")
        milk = cat.WeaponProfile(slot="item1", loadout_slot="secondary",
                                 item_class="tf_weapon_jar_milk")
        self.assertIsNone(cat.activity_for(drink, Action.FIRE))
        self.assertEqual(cat.activity_for(drink, Action.IDLE), "ACT_ITEM1_VM_IDLE")
        self.assertEqual(cat.activity_for(milk, Action.FIRE),
                         "ACT_ITEM1_VM_PRIMARYATTACK")

    def test_buff_banner_translates_itself_to_item1(self):
        """Горн с ролью melee играет ITEM1, а не лопату"""
        horn = cat.WeaponProfile(slot="melee", loadout_slot="secondary",
                                 item_class="tf_weapon_buff_item")
        self.assertEqual(cat.activity_for(horn, Action.IDLE), "ACT_ITEM1_VM_IDLE")

    def test_demoman_sword_uses_the_special_set(self):
        sword = cat.WeaponProfile(slot="melee", loadout_slot="melee",
                                  item_class="tf_weapon_sword", tf2_class="demoman")
        self.assertEqual(cat.activity_for(sword, Action.IDLE), "ACT_VM_IDLE_SPECIAL")
        self.assertEqual(cat.activity_for(sword, Action.FIRE),
                         "ACT_VM_HITCENTER_SPECIAL")
        katana = cat.WeaponProfile(slot="melee", loadout_slot="melee",
                                   item_class="tf_weapon_katana", tf2_class="soldier")
        self.assertEqual(cat.activity_for(katana, Action.IDLE), "ACT_MELEE_VM_IDLE")

    def test_spy_watch_uses_the_offhand_set(self):
        """Часы невидимости - «вторая рука» шпиона"""
        self.assertEqual(self._find(Action.IDLE, "watch"), "offhand_idle")

    # Таблица ролей

    def test_role_table_rows(self):
        """Строки `s_viewmodelacttable`, где легко ошибиться"""
        rows = [
            ("melee", "ACT_VM_HITCENTER", "ACT_MELEE_VM_HITCENTER"),
            ("item2", "ACT_VM_HITCENTER", "ACT_VM_HITCENTER"),
            ("melee", "ACT_VM_HITLEFT", "ACT_VM_HITLEFT"),
            ("secondary2", "ACT_VM_IDLE", "ACT_SECONDARY2_VM_IDLE"),
            ("secondary2", "ACT_VM_SECONDARYATTACK", "ACT_VM_SECONDARYATTACK"),
            ("primary2", "ACT_VM_IDLE", "ACT_PRIMARY_VM_IDLE"),
            ("primary2", "ACT_VM_RELOAD", "ACT_PRIMARY_VM_RELOAD_3"),
            ("primary2", "ACT_RELOAD_START", "ACT_PRIMARY_RELOAD_START_3"),
            ("item2", "ACT_RELOAD_START", "ACT_RELOAD_START"),
            ("building", "ACT_VM_IDLE", "ACT_VM_IDLE"),
        ]
        for slot, base, expected in rows:
            self.assertEqual(cat.translate(slot, base), expected, (slot, base))


if __name__ == "__main__":
    unittest.main()
