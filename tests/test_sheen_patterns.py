"""Свои узоры блеска Killstreak (src/services/sheen_patterns.py) и их связь
с эффектом «Цвет блеска киллстрика»."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.services import sheen_patterns as sp
from src.services import vmt_effects as fx

STOCK = '''"VertexLitGeneric"
{
	"$basetexture" "models/w/kunai"
	"$sheenPassEnabled" "1"
	"$sheenmapmask" "Effects/AnimatedSheen/animatedsheen0"
	"$sheenmapmaskframe" "0"
	"Proxies"
	{
		"AnimatedWeaponSheen"
		{
			"animatedtexturevar" "$sheenmapmask"
			"animatedtextureframenumvar" "$sheenmapmaskframe"
			"animatedtextureframerate" "40"
		}
	}
}
'''
BOUNDS = {"scale_x": 19.4, "scale_y": 3.5, "offset_x": -5.8, "offset_y": -1.4, "direction": 2}


class PatternTests(unittest.TestCase):
    def test_name_round_trip(self):
        name = sp.texture_name("double", sp.frames_for(2.4))
        self.assertEqual(name, "tf2sg/sheen/double_61")
        self.assertEqual(sp.parse(name), ("double", 61))
        self.assertEqual(sp.parse("TF2SG\\sheen\\double_61"), ("double", 61))
        self.assertIsNone(sp.parse("tf2sg/sheen/nope_61"))
        self.assertIsNone(sp.parse("tf2sg/sheen/double_5000"))
        self.assertIsNone(sp.parse("effects/animatedsheen/animatedsheen0"))

    def test_frames_start_blank_and_light_up(self):
        for name in (p for p in sp.PATTERNS if p != "calib"):
            pics = sp.frames(name, 31)
            self.assertEqual(len(pics), 31)
            self.assertEqual(pics[0][..., :3].max(), 0, name)          # кадр 0 не рисуется
            self.assertGreater(max(p[..., 0].max() for p in pics), 120, name)
            self.assertEqual(pics[-1][..., :3].max(), 0, name)         # пауза в конце прохода

    def test_calibration_stays_for_the_whole_pass(self):
        pics = sp.frames("calib", 26)
        self.assertEqual(pics[0][..., :3].max(), 0)
        self.assertTrue(all(np.array_equal(pics[1], p) for p in pics[1:]))
        self.assertEqual(pics[1].shape[:2], (sp.CALIB_SIZE, sp.CALIB_SIZE))
        lum = pics[1][..., 0]
        # Несимметрична: зеркало и поворот дают другую картинку.
        self.assertFalse(np.array_equal(lum, lum[:, ::-1]))
        self.assertFalse(np.array_equal(lum, lum[::-1, :]))

    def test_frames_are_deterministic(self):
        a, b = sp.frames("sparkle", 30), sp.frames("sparkle", 30)
        self.assertTrue(all(np.array_equal(x, y) for x, y in zip(a, b)))

    def test_materialize_builds_referenced_masks_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mat = root / "materials" / "models" / "w"
            mat.mkdir(parents=True)
            (mat / "a.vmt").write_text(STOCK.replace(
                "Effects/AnimatedSheen/animatedsheen0", "tf2sg/sheen/stripes_31"), encoding="utf-8")
            (mat / "b.vmt").write_text(STOCK, encoding="utf-8")
            # Ручная запись: обратные слэши, без пробела, с .vtf.
            (mat / "c.vmt").write_text(STOCK.replace(
                '"$sheenmapmask" "Effects/AnimatedSheen/animatedsheen0"',
                '"$sheenmapmask""TF2SG\\sheen\\stripes_31.vtf"'), encoding="utf-8")
            self.assertEqual(sp.materialize(root, "vgui\\replay\\thumbnails"), 1)
            # Маска — в папке-обходе sv_pure, ссылки VMT туда же.
            vtf = root / "materials" / "vgui" / "replay" / "thumbnails" / "tf2sg" / "sheen" / "stripes_31.vtf"
            self.assertTrue(vtf.is_file())
            for name in ("a.vmt", "c.vmt"):
                self.assertIn('vgui/replay/thumbnails/tf2sg/sheen/stripes_31"',
                              (mat / name).read_text(encoding="utf-8"))
            from src.services.vtflib_wrapper import VTFLib
            frames, w, h = VTFLib.read_vtf_all_frames(str(vtf))
            self.assertEqual((len(frames), w, h), (31, sp.SIZE, sp.SIZE))
            # Повторная упаковка: ссылка уже с папкой, файл есть.
            self.assertEqual(sp.materialize(root, "vgui\\replay\\thumbnails"), 0)
            self.assertNotIn('thumbnails/vgui', (mat / "a.vmt").read_text(encoding="utf-8"))

    def test_materialize_without_bypass_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mat = root / "materials" / "models"
            mat.mkdir(parents=True)
            (mat / "a.vmt").write_text(STOCK.replace(
                "Effects/AnimatedSheen/animatedsheen0", "tf2sg/sheen/pulse_26"), encoding="utf-8")
            self.assertEqual(sp.materialize(root, ""), 1)
            self.assertTrue((root / "materials" / "tf2sg" / "sheen" / "pulse_26.vtf").is_file())


class EffectPatternTests(unittest.TestCase):
    def sheen(self, text=STOCK, **vals):
        vals = {"color": "#00ff00", "bright": 1, "look": "normal", "when": "game", **vals}
        return fx.apply(fx.SHEEN, vals, text, "", BOUNDS)["text"]

    def test_pattern_sets_own_mask_and_reopens(self):
        out = self.sheen(pattern="pulse2", length=4)
        self.assertIn('"$sheenmapmask" "tf2sg/sheen/pulse2_101"', out)
        got = fx.values(fx.SHEEN, out)
        self.assertEqual((got["pattern"], got["length"]), ("pulse2", 4.0))
        # Кадры по-прежнему крутит прокси игры — он в материале остался.
        self.assertIn("AnimatedWeaponSheen", out)

    def test_back_to_game_pattern_restores_stock_mask(self):
        out = self.sheen(self.sheen(pattern="mist"), pattern="game")
        self.assertIn('"$sheenmapmask" "effects/animatedsheen/animatedsheen0"', out)
        self.assertEqual(fx.values(fx.SHEEN, out)["pattern"], "game")

    def test_back_to_game_restores_own_mod_mask(self):
        mod = STOCK.replace("Effects/AnimatedSheen/animatedsheen0", "mods/my_mask")
        own = fx.apply(fx.SHEEN, {"color": "#00ff00", "pattern": "mist"}, mod, mod, BOUNDS)["text"]
        back = fx.apply(fx.SHEEN, {"color": "#00ff00", "pattern": "game"}, own, mod, BOUNDS)["text"]
        self.assertIn('"$sheenmapmask" "mods/my_mask"', back)

    def test_always_counts_pattern_frames(self):
        out = self.sheen(pattern="double", length=2, when="always")
        self.assertIn('"$tf2sg_sheenlast" "50.0"', out)               # 51 кадр
        keys = [l for l in out.lower().splitlines() if l.startswith('	"$sheenmapmask" ')]
        self.assertEqual(keys, ['	"$sheenmapmask" "tf2sg/sheen/double_51"'])


if __name__ == "__main__":
    unittest.main()
