"""Краски игры для превью: банки из items_game и покраска по маске."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from src.data import paints
from src.services import vmt_tint

ITEMS = '''
"items_game"
{
	"prefabs"
	{
		"paint_can"
		{
			"item_class"	"tool"
			"attributes"
			{
				"set item tint RGB"	{ "attribute_class" "set_item_tint_rgb" "value" "0" }
			}
		}
	}
	"items"
	{
		"5027"
		{
			"name"	"Paint Can 1"
			"prefab"	"valve paint_can"
			"item_name"	"#TF_Tool_PaintCan_1"
			"attributes"
			{
				"set item tint RGB"	{ "attribute_class" "set_item_tint_rgb" "value" "7511618" }
			}
		}
		"5046"
		{
			"name"	"Paint Can Team Color"
			"prefab"	"valve paint_can_team_color"
			"item_name"	"#TF_Tool_PaintCan_TeamColor"
			"attributes"
			{
				"set item tint RGB"	{ "attribute_class" "set_item_tint_rgb" "value" "12073019" }
				"set item tint RGB 2"	{ "attribute_class" "set_item_tint_rgb_override" "value" "5801378" }
			}
		}
		"1"
		{
			"name"	"Not a paint"
			"prefab"	"hat"
		}
	}
}
'''


class PaintsTests(unittest.TestCase):
    def test_cans_come_with_localized_names_and_team_colours(self):
        got = paints.parse(ITEMS, {'TF_Tool_PaintCan_1': 'Истинно зелёный'})
        self.assertEqual(got, [
            {'key': '5027', 'name': 'Истинно зелёный', 'red': (114, 158, 66), 'blu': (114, 158, 66)},
            {'key': '5046', 'name': 'Paint Can Team Color', 'red': (184, 56, 59), 'blu': (88, 133, 162)},
        ])


class PaintedTests(unittest.TestCase):
    def test_tinting_keeps_the_mask_beside_and_paints_by_it(self):
        with TemporaryDirectory() as tmp:
            png = str(Path(tmp) / 'hat.png')
            img = Image.new('RGBA', (2, 1))
            img.putpixel((0, 0), (200, 200, 200, 255))   # красится
            img.putpixel((1, 0), (10, 20, 30, 0))        # маска пуста — не трогать
            img.save(png)
            self.assertTrue(vmt_tint.apply_to_png(png, vmt_tint.TintSpec((255, 0, 0), 0.0)))
            self.assertEqual(vmt_tint.paintable(png), vmt_tint.TintSpec((255, 0, 0), 0.0))
            self.assertTrue(Path(vmt_tint.raw_of(png)).is_file())
            self.assertIsNone(vmt_tint.paintable(str(Path(tmp) / 'nope.png')))

            out = vmt_tint.painted(vmt_tint.raw_of(png), vmt_tint.TintSpec((0, 255, 0), 1.0), tmp)
            with Image.open(out) as res:
                self.assertEqual(res.getpixel((0, 0)), (0, 255, 0, 255))
                self.assertEqual(res.getpixel((1, 0)), (10, 20, 30, 255))
            # Тот же цвет и исходник — тот же файл, без пересчёта.
            self.assertEqual(vmt_tint.painted(vmt_tint.raw_of(png), vmt_tint.TintSpec((0, 255, 0), 1.0), tmp), out)


if __name__ == '__main__':
    unittest.main()
