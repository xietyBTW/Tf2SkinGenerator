"""Единый разбор VMT.

Каждый случай здесь — из настоящих файлов игры или из бага, который старые
регулярки на этом файле давали. До этого модуля разбор жил шестью
независимыми наборами регулярок, и они расходились между собой.
"""

import unittest

from src.services import vmt_parse

CR = chr(13)
BS = chr(92)


class ParseBasicsTests(unittest.TestCase):
    def test_shader_and_params(self):
        doc = vmt_parse.parse(
            '"VertexLitGeneric"\n{\n\t"$basetexture" "models/a/b"\n'
            '\t"$phong" "1"\n}\n')
        self.assertEqual(doc.shader, "vertexlitgeneric")
        self.assertEqual(doc.get("basetexture"), "models/a/b")
        self.assertEqual(doc.get("$basetexture"), "models/a/b", "имя с $")
        self.assertEqual(doc.get("$BaseTexture"), "models/a/b", "регистр")
        self.assertTrue(doc.flag("phong"))

    def test_crlf(self):
        text = ('"VertexLitGeneric"' + CR + "\n{" + CR + "\n"
                '\t"$basetexture" "models/a/b"' + CR + "\n}" + CR + "\n")
        self.assertEqual(vmt_parse.parse(text).get("basetexture"), "models/a/b")

    def test_unquoted_key_and_value(self):
        self.assertEqual(
            vmt_parse.parse("{\n\t$basetexture models/a/b\n}").get("basetexture"),
            "models/a/b")

    def test_commented_out_param_is_ignored(self):
        """Старые регулярки возвращали именно закомментированное значение."""
        doc = vmt_parse.parse(
            "{\n"
            '\t// "$basetexture" "models/WRONG/x"\n'
            '\t"$basetexture" "models/a/b"\n'
            "}\n")
        self.assertEqual(doc.get("basetexture"), "models/a/b")

    def test_trailing_comment(self):
        doc = vmt_parse.parse(
            '{\n\t"$basetexture" "models/a/b"   // хвост\n}\n')
        self.assertEqual(doc.get("basetexture"), "models/a/b")

    def test_slashes_in_comment_inside_quotes_are_not_a_comment(self):
        doc = vmt_parse.parse('{\n\t"$basetexture" "models/a//b"\n}\n')
        self.assertEqual(doc.get("basetexture"), "models/a//b")

    def test_first_value_wins_on_duplicate(self):
        """Движок читает первое совпадение — повтор ниже его не отменяет."""
        doc = vmt_parse.parse(
            '{\n\t"$basetexture" "first"\n\t"$basetexture" "second"\n}\n')
        self.assertEqual(doc.get("basetexture"), "first")

    def test_broken_input_gives_empty_doc(self):
        for text in ("", "   ", "{{{", '"VertexLitGeneric"', "}"):
            doc = vmt_parse.parse(text)
            self.assertIsNone(doc.get("basetexture"), repr(text))


class NestedBlockTests(unittest.TestCase):
    VMT = (
        '"VertexLitGeneric"\n'
        "{\n"
        '\t"$basetexture" "models/a/b"\n'
        '\t">=DX90"\n'
        "\t{\n"
        '\t\t"$selfillum" "1"\n'
        "\t}\n"
        "\tproxies\n"
        "\t{\n"
        "\t\tAnimatedTexture\n"
        "\t\t{\n"
        '\t\t\t"animatedtexturevar" "$basetexture"\n'
        '\t\t\t"animatedtextureframerate" "30"\n'
        "\t\t}\n"
        "\t}\n"
        "}\n")

    def test_nested_param_not_visible_at_root(self):
        doc = vmt_parse.parse(self.VMT)
        self.assertIsNone(doc.get("selfillum"))
        self.assertIsNone(doc.get("animatedtextureframerate"))

    def test_find_searches_the_whole_tree(self):
        doc = vmt_parse.parse(self.VMT)
        self.assertEqual(doc.find("selfillum"), "1")
        self.assertEqual(doc.find("animatedtextureframerate"), "30")

    def test_proxy_mention_does_not_override_real_param(self):
        """В прокси $basetexture упоминается как ИМЯ переменной, а не значение."""
        self.assertEqual(vmt_parse.parse(self.VMT).get("basetexture"),
                         "models/a/b")

    def test_block_access(self):
        doc = vmt_parse.parse(self.VMT)
        proxies = doc.block("proxies")
        self.assertIsNotNone(proxies)
        self.assertIsNotNone(proxies.block("animatedtexture"))
        self.assertEqual(proxies.find("animatedtextureframerate"), "30")

    def test_animated_framerate_helper(self):
        self.assertEqual(vmt_parse.animated_framerate(self.VMT), 30.0)
        self.assertIsNone(vmt_parse.animated_framerate('{\n"$a" "1"\n}'))
        # Нулевой fps бессмысленен — поднимаем до минимума, как раньше
        self.assertEqual(
            vmt_parse.animated_framerate(
                '{\nproxies\n{\nAnimatedTexture\n{\n'
                '"animatedtextureframerate" "0"\n}\n}\n}'), 0.1)


class TypedAccessTests(unittest.TestCase):
    def test_path_normalises_slashes_and_case(self):
        doc = vmt_parse.parse(
            '{\n\t"$basetexture" "Models' + BS + 'Weapons' + BS + 'C_Item"\n}\n')
        self.assertEqual(doc.path("basetexture"), "models/weapons/c_item")
        self.assertEqual(vmt_parse.basetexture(
            '{\n\t"$basetexture" "/models/a/"\n}\n'), "models/a")

    def test_flag(self):
        doc = vmt_parse.parse(
            '{\n\t"$additive" "1"\n\t"$translucent" "0"\n\t"$junk" "nope"\n}\n')
        self.assertTrue(doc.flag("additive"))
        self.assertFalse(doc.flag("translucent"))
        self.assertFalse(doc.flag("junk"))
        self.assertTrue(doc.flag("junk", default=True), "непонятное → default")
        self.assertFalse(doc.flag("missing"))

    def test_number(self):
        doc = vmt_parse.parse('{\n\t"$phongboost" "0.800000"\n}\n')
        self.assertAlmostEqual(doc.number("phongboost"), 0.8)
        self.assertIsNone(doc.number("missing"))
        self.assertEqual(doc.number("missing", 5.0), 5.0)

    def test_color(self):
        doc = vmt_parse.parse(
            '{\n\t"$colortint_base" "{ 189 59 59 }"\n'
            '\t"$color2" "[.5 .25 0]"\n}\n')
        self.assertEqual(doc.color("colortint_base"), (189, 59, 59))
        self.assertEqual(doc.color("color2"), (128, 64, 0))
        self.assertIsNone(doc.color("missing"))
        self.assertEqual(vmt_parse.parse_color("{194 45 48}"), (194, 45, 48))
        self.assertEqual(vmt_parse.parse_color("[1 1 1]"), (255, 255, 255))
        self.assertIsNone(vmt_parse.parse_color("не цвет"))


class RealFileTests(unittest.TestCase):
    """Кусок настоящего VMT шапки со всеми особенностями Valve сразу."""

    VMT = (
        '"VertexLitGeneric"' + CR + "\n"
        "{" + CR + "\n"
        '\t"$basetexture"\t\t"models/workshop/player/items/scout/xms/xms_color"' + CR + "\n"
        '\t"$bumpmap"\t\t"models/workshop/player/items/scout/xms/xms_normal"' + CR + "\n"
        '\t"$blendtintbybasealpha"\t\t"1"' + CR + "\n"
        '\t"$blendtintcoloroverbase"\t\t"0.990000"' + CR + "\n"
        '\t"$colortint_base"\t\t"{ 189 59 59 }"' + CR + "\n"
        '\t">=DX90"' + CR + "\n"
        "\t{" + CR + "\n"
        '\t\t"$selfillum"\t\t"0"' + CR + "\n"
        "\t}" + CR + "\n"
        '\t"proxies"' + CR + "\n"
        "\t{" + CR + "\n"
        '\t\t"invis"' + CR + "\n"
        "\t\t{" + CR + "\n"
        "\t\t}" + CR + "\n"
        '\t\t"ItemTintColor"' + CR + "\n"
        "\t\t{" + CR + "\n"
        '\t\t\t"resultVar"\t\t"$colortint_tmp"' + CR + "\n"
        "\t\t}" + CR + "\n"
        "\t}" + CR + "\n"
        "}" + CR + "\n")

    def test_everything_reads(self):
        doc = vmt_parse.parse(self.VMT)
        self.assertEqual(doc.shader, "vertexlitgeneric")
        self.assertEqual(doc.path("basetexture"),
                         "models/workshop/player/items/scout/xms/xms_color")
        self.assertTrue(doc.flag("blendtintbybasealpha"))
        self.assertAlmostEqual(doc.number("blendtintcoloroverbase"), 0.99)
        self.assertEqual(doc.color("colortint_base"), (189, 59, 59))
        self.assertIsNotNone(doc.block("proxies").block("itemtintcolor"))
        self.assertIsNotNone(doc.block("proxies").block("invis"),
                             "пустой блок прокси не должен ломать разбор")


if __name__ == "__main__":
    unittest.main()
