"""
Каталог анимаций класса: поиск последовательности по слоту и действию.

Имена последовательностей наружу не выводятся (`sg_idle`, `db_idle`, `ss_idle`),
зато у каждой в QC стоит активность, и она называет слот и действие явно.
Проверяется именно разрешение имени активности — там, где легко ошибиться:

  * `item2` — самостоятельный слот (Неумолимая сила), а `secondary2` — второй
    вариант вторичного (Прерыватель). По написанию не отличить, порядок решает;
  * у перезарядки в активности нет `VM_`;
  * инструменты инженера названы через ACT_ENGINEER_*, а не по слоту.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services import weapon_anim_catalog as cat
from src.services.weapon_anim_catalog import Action

# Активности взяты из настоящих QC моделей анимаций TF2.
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

$sequence "r_handposes" {
	"anims\\r_handposes.smd"
	fps 30
}
'''

ON_DISK = ["sg_idle", "sg_reload_start", "db_idle", "ss_idle",
           "melee_allclass_idle", "box_idle", "r_handposes",
           "eternal_idle", "knife_stab_a", "offhand_idle", "c_sapper_idle"]


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

    # ── Разбор ────────────────────────────────────────────────────────────── #

    def test_sequence_fields_are_read(self):
        seq = self.catalog.by_name["ss_idle"]
        self.assertEqual(seq.activity, "ACT_SECONDARY_VM_IDLE_2")
        self.assertEqual(seq.fps, 35.0)
        self.assertTrue(seq.loop)
        self.assertTrue(seq.smd_path.endswith("ss_idle.smd"))
        self.assertTrue(seq.exists)

    def test_sequence_without_activity_is_kept_but_not_indexed(self):
        """`r_handposes` есть у всех классов и не является действием оружия."""
        self.assertIn("r_handposes", self.catalog.by_name)
        self.assertEqual(self.catalog.by_name["r_handposes"].activity, "")
        self.assertNotIn("", self.catalog.by_activity)

    def test_loop_is_not_guessed(self):
        self.assertFalse(self.catalog.by_name["db_idle"].loop)

    def test_missing_qc_gives_none(self):
        with TemporaryDirectory() as empty:
            self.assertIsNone(cat.load(empty))
        self.assertIsNone(cat.load(""))

    # ── Поиск ─────────────────────────────────────────────────────────────── #

    def test_plain_slot(self):
        self.assertEqual(self.catalog.find("primary", Action.IDLE).name, "sg_idle")

    def test_numbered_slot_is_taken_literally_first(self):
        """item2 — слот сам по себе, а не «второй вариант item»."""
        self.assertEqual(self.catalog.find("item2", Action.IDLE).name, "db_idle")

    def test_numbered_slot_falls_back_to_a_variant(self):
        """ACT_SECONDARY2_* нет — значит цифра означает вариант вторичного."""
        self.assertEqual(self.catalog.find("secondary2", Action.IDLE).name,
                         "ss_idle")

    def test_reload_activity_has_no_vm_part(self):
        self.assertEqual(self.catalog.find("primary", Action.RELOAD_START).name,
                         "sg_reload_start")

    def test_melee_falls_back_to_the_all_class_set(self):
        self.assertEqual(self.catalog.find("melee", Action.IDLE).name,
                         "melee_allclass_idle")

    def test_engineer_tools_are_found_through_an_alias(self):
        self.assertEqual(self.catalog.find("building", Action.IDLE).name,
                         "box_idle")

    def test_sequence_whose_smd_is_gone_is_not_offered(self):
        """Иначе поза бы «нашлась», а файла под ней не оказалось."""
        self.assertIsNone(self.catalog.find("secondary", Action.IDLE))

    def test_slot_that_the_game_marks_unused_resolves_to_nothing(self):
        """У щитов и ботинок вьюмодели нет вовсе — items_game так и пишет."""
        self.assertEqual(cat.activity_candidates("force_not_used", Action.IDLE), [])
        self.assertIsNone(self.catalog.find("force_not_used", Action.IDLE))
        self.assertIsNone(self.catalog.find("", Action.IDLE))

    def test_unknown_action_for_this_weapon_is_none(self):
        self.assertIsNone(self.catalog.find("item2", Action.RELOAD))

    def test_actions_for_lists_what_the_weapon_can_do(self):
        """Из этого списка интерфейс потом строит выбор анимации."""
        self.assertEqual(set(self.catalog.actions_for("primary")),
                         {Action.IDLE, Action.RELOAD_START})
        self.assertEqual(set(self.catalog.actions_for("item2")), {Action.IDLE})

    # ── Подмена активностей из items_game ─────────────────────────────────── #

    def test_replacement_wins_over_the_slot(self):
        """У куная слот остаётся melee, а играет он набор ITEM2.

        Пока подмена не читалась, почти все ножи шпиона показывали анимацию
        обычного ножа-бабочки — это и было заметно на экране.
        """
        kunai = {"ACT_VM_IDLE": "ACT_ITEM2_VM_IDLE"}
        self.assertEqual(self.catalog.find("melee", Action.IDLE).name,
                         "melee_allclass_idle")
        self.assertEqual(self.catalog.find("melee", Action.IDLE, kunai).name,
                         "db_idle")   # первая последовательность ACT_ITEM2_VM_IDLE

    def test_replacement_that_points_at_nothing_falls_back_to_the_slot(self):
        """Чужая или устаревшая подмена не должна лишать оружие анимации."""
        nowhere = {"ACT_VM_IDLE": "ACT_NOSUCH_VM_IDLE"}
        self.assertEqual(self.catalog.find("primary", Action.IDLE, nowhere).name,
                         "sg_idle")

    def test_replacement_key_may_carry_the_slot(self):
        """Осмотр в таблице записан ключом СО слотом, а не голым именем.

            ACT_MELEE_VM_INSPECT_IDLE → ACT_ITEM2_VM_INSPECT_IDLE

        Пока разбирались только голые ключи, у куная и Вечной награды осмотр
        так и брался от ножа-бабочки, хотя всё остальное играло из ITEM2.
        """
        kunai = {"ACT_MELEE_VM_INSPECT_IDLE": "ACT_ITEM2_VM_INSPECT_IDLE"}
        names = cat.activity_candidates("melee", Action.INSPECT_IDLE, kunai)
        self.assertEqual(names[0], "ACT_ITEM2_VM_INSPECT_IDLE")
        self.assertIn("ACT_MELEE_VM_INSPECT_IDLE", names)   # запасной остался

    def test_replacement_is_first_among_candidates(self):
        names = cat.activity_candidates(
            "melee", Action.IDLE, {"ACT_VM_IDLE": "ACT_ITEM2_VM_IDLE"})
        self.assertEqual(names[0], "ACT_ITEM2_VM_IDLE")

    # ── Действия, названные не как у стрелкового ───────────────────────────── #

    def test_melee_attack_is_called_hitcenter(self):
        """Удар ближнего боя — не PRIMARYATTACK, и без этого ножи и биты
        оставались без единого действия «Выстрел» в списке."""
        self.assertEqual(self.catalog.find("melee", Action.FIRE).name,
                         "knife_stab_a")

    def test_spy_watch_uses_the_offhand_set(self):
        """Часы невидимости — «вторая рука» шпиона."""
        self.assertEqual(self.catalog.find("watch", Action.IDLE).name,
                         "offhand_idle")

    def test_sapper_activity_has_no_slot_at_all(self):
        """Саппер шпиона назван просто ACT_VM_IDLE.

        Разрешено это только слоту building: общий запасной вариант «активность
        без слота» выдавал бы саппер любому оружию, чью анимацию не нашли.
        """
        self.assertEqual(self.catalog.find("building", Action.IDLE).name,
                         "box_idle")           # у инженера — свой ящик
        catalog = self._catalog_without("box_idle")
        self.assertEqual(catalog.find("building", Action.IDLE).name,
                         "c_sapper_idle")      # у шпиона — саппер
        self.assertIsNone(catalog.find("нет_такого_слота", Action.IDLE))

    def _catalog_without(self, name: str):
        """Тот же каталог, но без одной последовательности на диске."""
        (self.dir / "anims" / f"{name}.smd").unlink()
        return cat.load(str(self.dir))

    # ── Порядок кандидатов ────────────────────────────────────────────────── #

    def test_literal_name_is_tried_before_the_variant_split(self):
        names = cat.activity_candidates("item2", Action.IDLE)
        self.assertEqual(names[0], "ACT_ITEM2_VM_IDLE")
        self.assertLess(names.index("ACT_ITEM2_VM_IDLE"),
                        names.index("ACT_ITEM_VM_IDLE_2"))

    def test_split_slot(self):
        self.assertEqual(cat.split_slot("secondary2"), ("SECONDARY2", "_2"))
        self.assertEqual(cat.split_slot("melee_allclass"), ("MELEE_ALLCLASS", ""))
        self.assertEqual(cat.split_slot("force_not_used"), ("", ""))
        self.assertEqual(cat.split_slot(""), ("", ""))


if __name__ == "__main__":
    unittest.main()
