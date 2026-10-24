"""Слияние вложенных блоков с префабами - в порядке MergeDefinitionPrefab"""

import re

from src.data.items_game_kv import ItemsGame

TEXT = """"items_game"
{
	"prefabs"
	{
		"noun"	{ "player_bodygroups" { "hat" "1" "hands" "1" } }
		"adj"	{ "player_bodygroups" { "hands" "0" } }
	}
	"items"
	{
		"1"
		{
			"prefab"	"adj noun"
			"player_bodygroups" { "headphones" "1" "hat" "0" }
		}
	}
}
"""


def _pairs(text):
    return dict(re.findall(r'"([^"]+)"\s*"(\d+)"', text))


def test_prefabs_merge_back_to_front_and_item_wins():
    """«adj noun»: сначала noun, поверх adj, поверх сам предмет"""
    game = ItemsGame.parse(TEXT)
    merged = game.merged_block(game.items[0][1], "player_bodygroups")
    assert _pairs(merged) == {"hat": "0", "hands": "0", "headphones": "1"}


def test_missing_block_is_empty():
    game = ItemsGame.parse(TEXT)
    assert game.merged_block(game.items[0][1], "equip_regions") == ""
