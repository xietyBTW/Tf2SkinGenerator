"""Таблица необычных эффектов из items_game: имя в игре → система частиц."""

from src.data import unusual_effects as ue

ITEMS_GAME = """
"items_game"
{
	"attribute_controlled_attached_particles"
	{
		"other_particles"
		{
			"1"
			{
				"system"			"burningplayer_red"
			}
		}
		"cosmetic_unusual_effects"
		{
			"13"
			{
				"system"			"superrare_burning1"
				"attach_to_rootbone"	"1"
				"attachment"		"muzzle"
			}
			"14"
			{
				"system"			"superrare_burning2"
			}
		}
		"taunt_unusual_effects"
		{
			"3225"
			{
				"system"			"utaunt_luminousdrift_teamcolor_red"
			}
		}
	}
	"items"
	{
		"1"
		{
			"name"	"not a particle"
		}
	}
}
"""

LOC = {"Attrib_Particle13": "Burning Flames", "Attrib_Particle14": "Scorching Flames",
       "attrib_particle3225": "Luminous Drift"}


def test_effects_come_with_names_and_categories():
    fx = ue.parse(ITEMS_GAME, LOC)
    assert [(f["id"], f["system"], f["name"], f["category"]) for f in fx] == [
        (1, "burningplayer_red", "", "other"),
        (13, "superrare_burning1", "Burning Flames", "cosmetic"),
        (14, "superrare_burning2", "Scorching Flames", "cosmetic"),
        (3225, "utaunt_luminousdrift_teamcolor_red", "Luminous Drift", "taunt"),
    ]


def test_missing_table_is_empty():
    assert ue.parse('"items_game" { "items" { } }', LOC) == []


def test_every_category_has_a_name():
    assert set(ue.CATEGORIES.values()) <= set(ue.CATEGORY_NAMES)
