"""Снятие покраски игры с материалов мода перед упаковкой."""

from src.services import vmt_parse, vmt_tint
from src.services.vpk_service import VPKService

# Как у Коровьего Мангла в игре: цвет в VMT, маска — альфа текстуры.
MANGLER = """"VertexlitGeneric"
{
	"$basetexture"	"console/models/c_test/c_test"
	"$blendtintbybasealpha" "1"
	"$blendtintcoloroverbase" "0"
	"$colortint_base" "{183 56 61}"
	"$colortint_tmp" "[0 0 0]"
	"$yellow" "0"
	"Proxies"
	{
		"ItemTintColor"
		{
			"resultVar" "$colortint_tmp"
		}
		"SelectFirstIfNonZero"
		{
			"srcVar1" "$colortint_tmp"
			"srcVar2" "$colortint_base"
			"resultVar" "$color2"
		}
		"YellowLevel"
		{
			"resultVar" "$yellow"
		}
		"Multiply"
		{
			"srcVar1" "$color2"
			"srcVar2" "$yellow"
			"resultVar" "$color2"
		}
	}
}
"""


def _put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_strips_tint_where_texture_is_in_the_mod(tmp_path):
    vmt = _put(tmp_path, "materials/console/models/c_test/c_test.vmt", MANGLER)
    _put(tmp_path, "materials/console/models/c_test/c_test.vtf", "vtf")

    VPKService._strip_game_tint(tmp_path)

    text = vmt.read_text(encoding="utf-8")
    assert vmt_tint.parse_tint(text) is None
    assert "ItemTintColor" not in text and "colortint_base" not in text
    # Банкате остаётся: жёлтый теперь идёт в $color2 напрямую.
    assert "YellowLevel" in text and "$yellow" in text
    assert vmt_parse.parse(text).path("basetexture") == "console/models/c_test/c_test"


def test_keeps_tint_on_game_texture(tmp_path):
    # Служебный материал пишется оригиналом: текстура — игровым путём, её в
    # моде нет, и покраску трогать нельзя.
    vmt = _put(tmp_path, "materials/console/models/c_test/c_test.vmt",
               MANGLER.replace("console/models/c_test/c_test", "models/c_test/c_test"))

    VPKService._strip_game_tint(tmp_path)

    assert vmt_tint.parse_tint(vmt.read_text(encoding="utf-8")) is not None
