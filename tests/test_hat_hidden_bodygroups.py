"""Что шапка прячет у персонажа — из items_game (каска солдата под шапкой)."""

from src.data import hats_parser

ITEMS_GAME = """"items_game"
{
	"prefabs"
	{
		"hat"
		{
			"item_slot"	"head"
			"equip_region"	"hat"
		}
	}
	"items"
	{
		"30338"
		{
			"name"		"Ground Control"
			"prefab"		"hat"
			"visuals"
			{
				"player_bodygroups"
				{
					"hat"		"1"
				}
			}
			"model_player"		"models/workshop/player/items/soldier/sbox2014_soldier_major/sbox2014_soldier_major.mdl"
			"used_by_classes"
			{
				"soldier"		"1"
			}
		}
		"30339"
		{
			"name"		"Styled Cap"
			"prefab"		"hat"
			"model_player"		"models/workshop/player/items/soldier/styled_cap/styled_cap.mdl"
			"used_by_classes"
			{
				"soldier"		"1"
			}
			"visuals"
			{
				"styles"
				{
					"0"
					{
						"model_player"		"models/workshop/player/items/soldier/styled_cap/styled_cap.mdl"
					}
					"1"
					{
						"model_player"		"models/workshop/player/items/soldier/styled_cap/styled_cap_nohp.mdl"
						"additional_hidden_bodygroups"
						{
							"headphones"		"1"
						}
					}
				}
			}
		}
	}
}
"""


def _parse(tmp_path):
    path = tmp_path / "items_game.txt"
    path.write_text(ITEMS_GAME, encoding="utf-8")
    return {h.internal_name: h for h in hats_parser._parse_items_game(str(path), {})}


def test_item_hides_player_bodygroup(tmp_path):
    hats = _parse(tmp_path)
    assert hats["Ground Control"].hidden_bodygroups == {"hat": 1}
    assert hats["Styled Cap"].hidden_bodygroups == {}


def test_style_hides_its_own_bodygroups(tmp_path):
    styles = _parse(tmp_path)["Styled Cap"].styles
    assert [s["hidden_bodygroups"] for s in styles] == [{}, {"headphones": 1}]
