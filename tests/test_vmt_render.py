"""
Разбор VMT в свойства рисования для 3D-превью.

Превью рисовало каждый меш непрозрачным, поэтому стекло банки Мутировавшего
молока выглядело серым бубликом: в его VMT стоит `$additive 1`, а базовая
текстура — пузырьковый шлем пиро, который без смешивания читается как пластик.

Блик и отражения намеренно НЕ разбираются: в Source они ограничены маской из
текстуры, а без неё покрывают модель белёсой плёнкой (см. vmt_render.py).

Фрагменты VMT ниже сняты с настоящих файлов игры. По стоку (2005 уникальных
материалов оружия и шапок): $additive 101, $translucent 98, $alphatest 35,
$alpha<1 2, $nocull 25.
"""

import unittest

from src.services.vmt_render import (
    BLEND_ADD, BLEND_ALPHA, BLEND_CUTOUT, BLEND_OPAQUE, RenderSpec, parse_render,
)

# c_breadmonster_glass.vmt — стекло банки Мутировавшего молока
BREADMONSTER_GLASS = '''"VertexlitGeneric"
{
	"$nocull" 1
	"$baseTexture" "models/player/items/pyro/drg_pyro_bubbleHelmet"
	"$additive" 1
	"$envmap" "env_cubemap"
	"$envmaptint" "[.3 .3 .2]"
	"$phong" "1"
	"$phongexponent" "65"
	"$phongboost" "6"
	"$rimlight" "1"
}
'''

# c_madmilk_glass.vmt — и $translucent, и $additive разом
MADMILK_GLASS = '''"VertexlitGeneric"
{
	"$baseTexture" "models/workshop/weapons/c_models/c_madmilk/c_madmilk_glass"
	"$translucent" "1"
	"$additive" "1"
}
'''

# c_madmilk_liquid.vmt — непрозрачная, но очень блестящая
MADMILK_LIQUID = '''"VertexlitGeneric"
{
	"$baseTexture" "models/workshop/weapons/c_models/c_madmilk/c_madmilk_liquid"
	"$phong" "1"
	"$phongexponent" "60"
	"$phongboost" "20"
	"$rimlight" "1"
}
'''


class BlendModeTests(unittest.TestCase):
    def test_additive_glass(self):
        spec = parse_render(BREADMONSTER_GLASS)
        self.assertEqual(spec.blend, BLEND_ADD)
        self.assertTrue(spec.two_sided)          # $nocull 1
        self.assertTrue(spec.is_transparent)

    def test_additive_wins_over_translucent(self):
        """Оба флага вместе — в игре решает сложение с фоном."""
        self.assertEqual(parse_render(MADMILK_GLASS).blend, BLEND_ADD)

    def test_translucent_alone(self):
        self.assertEqual(
            parse_render('"VertexLitGeneric"{"$translucent" "1"}').blend, BLEND_ALPHA)

    def test_alphatest_is_a_cutout(self):
        spec = parse_render('"VertexLitGeneric"{"$alphatest" "1"}')
        self.assertEqual(spec.blend, BLEND_CUTOUT)
        self.assertEqual(spec.alpha_test, 0.5)
        self.assertFalse(spec.is_transparent)    # вырезание глубину пишет

    def test_alphatest_reference(self):
        spec = parse_render(
            '"VertexLitGeneric"{"$alphatest" "1" "$alphatestreference" "0.8"}')
        self.assertAlmostEqual(spec.alpha_test, 0.8)

    def test_constant_alpha_makes_it_translucent(self):
        spec = parse_render('"VertexLitGeneric"{"$alpha" "0.4"}')
        self.assertEqual(spec.blend, BLEND_ALPHA)
        self.assertAlmostEqual(spec.opacity, 0.4)

    def test_alpha_one_is_not_transparent(self):
        self.assertEqual(parse_render('"VertexLitGeneric"{"$alpha" "1"}').blend,
                         BLEND_OPAQUE)

    def test_zero_flags_are_not_flags(self):
        """«$translucent 0» — это выключено, а не включено."""
        self.assertEqual(
            parse_render('"VertexLitGeneric"{"$translucent" "0"}').blend, BLEND_OPAQUE)

    def test_plain_material(self):
        spec = parse_render('"VertexLitGeneric"{"$basetexture" "x"}')
        self.assertEqual(spec.blend, BLEND_OPAQUE)
        self.assertTrue(spec.is_plain)

    def test_shiny_material_without_blending_is_plain(self):
        """У 1972 материалов стока есть $phong — вьюверу о них знать незачем."""
        self.assertTrue(parse_render(MADMILK_LIQUID).is_plain)

    def test_broken_and_empty_input(self):
        self.assertEqual(parse_render(""), RenderSpec())
        self.assertEqual(parse_render(None), RenderSpec())
        self.assertEqual(parse_render("{{{").blend, BLEND_OPAQUE)


class WireFormatTests(unittest.TestCase):
    """as_dict уходит в JS — лишних полей там быть не должно."""

    def test_plain_material_sends_only_the_blend(self):
        self.assertEqual(parse_render('"VertexLitGeneric"{}').as_dict(),
                         {"blend": "opaque"})

    def test_glass_sends_everything_the_viewer_needs(self):
        data = parse_render(BREADMONSTER_GLASS).as_dict()
        self.assertEqual(data["blend"], "add")
        self.assertTrue(data["twoSided"])
        self.assertNotIn("opacity", data)        # непрозрачность не менялась

    def test_shine_is_not_sent(self):
        """Блик без маски — та самая «серебряная оболочка»; его тут нет."""
        for text in (BREADMONSTER_GLASS, MADMILK_LIQUID):
            data = parse_render(text).as_dict()
            self.assertNotIn("shininess", data)
            self.assertNotIn("specular", data)
            self.assertNotIn("reflectivity", data)

    def test_dict_is_json_safe(self):
        import json
        json.dumps(parse_render(MADMILK_LIQUID).as_dict())


if __name__ == "__main__":
    unittest.main()
