"""Стоковое снаряжение класса для сцены «На модели» — из items_game."""

from src.data import stock_loadout

ITEMS_GAME = """"items_game"
{
	"prefabs"
	{
		"weapon_launcher"
		{
			"item_slot"	"primary"
			"model_player"	"models/weapons/c_models/c_grenadelauncher/c_grenadelauncher.mdl"
		}
	}
	"items"
	{
		"19"
		{
			"name"	"TF_WEAPON_GRENADELAUNCHER"
			"prefab"	"weapon_launcher"
			"baseitem"	"1"
			"anim_slot"	"secondary"
			"used_by_classes" { "demoman" "1" }
		}
		"5"
		{
			"name"	"TF_WEAPON_FISTS"
			"baseitem"	"1"
			"item_slot"	"melee"
			"used_by_classes" { "heavy" "1" }
		}
		"28"
		{
			"name"	"TF_WEAPON_BUILDER"
			"baseitem"	"1"
			"item_slot"	"building"
			"model_player"	"models/weapons/c_models/c_toolbox/c_toolbox.mdl"
			"used_by_classes" { "engineer" "1" }
		}
		"735"
		{
			"name"	"TF_WEAPON_BUILDER_SPY"
			"baseitem"	"1"
			"item_slot"	"building"
			"model_player"	"models/weapons/c_models/c_sapper/c_sapper.mdl"
			"used_by_classes" { "spy" "1" }
		}
		"24"
		{
			"name"	"TF_WEAPON_REVOLVER"
			"baseitem"	"1"
			"item_slot"	"secondary"
			"model_player"	"models/weapons/c_models/c_revolver/c_revolver.mdl"
			"used_by_classes" { "spy" "1" }
		}
		"200"
		{
			"name"	"Upgradeable TF_WEAPON_REVOLVER"
			"item_slot"	"secondary"
			"model_player"	"models/weapons/c_models/c_revolver/c_revolver.mdl"
			"used_by_classes" { "spy" "1" }
		}
	}
}
"""


def _root(tmp_path):
    items = tmp_path / "tf" / "scripts" / "items"
    items.mkdir(parents=True)
    (items / "items_game.txt").write_text(ITEMS_GAME, encoding="utf-8")
    stock_loadout._cache.clear()
    return str(tmp_path)


def test_anim_slot_and_prefab_model(tmp_path):
    # Гранатомёт демомана — основное оружие, но стойка вспомогательного;
    # модель — из prefab.
    [w] = stock_loadout.loadout("demoman", _root(tmp_path))
    assert (w.slot, w.anim) == ("primary", "SECONDARY")
    assert w.model.endswith("c_grenadelauncher.mdl")


def test_empty_hands_and_building_only_for_spy(tmp_path):
    root = _root(tmp_path)
    [fists] = stock_loadout.loadout("heavy", root)
    assert fists.slot == "melee" and fists.model is None
    # Ящик инженера — не слот раскладки; сапёр шпиона — второй слот.
    assert stock_loadout.loadout("engineer", root) == []
    assert [w.slot for w in stock_loadout.loadout("spy", root)] == ["secondary", "building"]
