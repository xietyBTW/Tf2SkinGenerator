"""
Гамма своего узора блеска: цвета слоёв сами выбирают, как узор ляжет в игру

Правило проверено в игре (чёрный блеск на обрезе): непрозрачность прохода -
КРАСНЫЙ канал маски x яркость оттенка, цвет - оттенок x маска. Поэтому у всех
видимых слоёв одного материала одна доля красного: белое с чёрным вместе не
бывает, чёрное с голубым - бывает
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from src.services import sheen_builder as sb
from src.services import sheen_library as sl
from src.services import sheen_palette as pal
from src.services import sheen_patterns as sp
from src.services import vmt_effects as fx
from tests.test_sheen_patterns import BOUNDS, STOCK


def layer(kind="stripe", **kw):
    return sb.new_layer(kind) | kw


class ClassifyTests(unittest.TestCase):
    def test_light_colours_are_warm(self):
        spec = {"layers": [layer(color="#ffffff"), layer(color="#ffc93c")]}
        self.assertEqual(pal.classify(spec), {"palette": pal.WARM, "lost": []})

    def test_black_and_blue_are_cold_together(self):
        spec = {"layers": [layer(color="#000000"), layer("sparkle", color="#3fa0ff")]}
        self.assertEqual(pal.classify(spec), {"palette": pal.COLD, "lost": []})

    def test_black_with_white_names_the_layer_that_will_vanish(self):
        spec = {"layers": [layer(color="#000000"), layer(color="#ffffff"),
                           layer(color="#ffe000")]}
        self.assertEqual(pal.classify(spec), {"palette": pal.WARM, "lost": [0]})

    def test_mask_layers_and_hidden_layers_do_not_vote(self):
        spec = {"layers": [layer(color="#000000"), layer(color="#ffffff", on=False),
                           layer(color="#ffffff", blend="mask")]}
        self.assertEqual(pal.classify(spec)["palette"], pal.COLD)

    def test_gradient_counts_every_stop(self):
        mixed = layer(fill="space", stops=[[0, "#ff0000"], [1, "#00ffff"]])
        self.assertEqual(pal.classify({"layers": [mixed]}), {"palette": pal.WARM, "lost": [0]})


class FramesTests(unittest.TestCase):
    def test_cold_frames_keep_a_black_layer_in_the_red_channel(self):
        spec = {"layers": [layer(color="#000000"), layer("sparkle", color="#0080ff", count=40)]}
        warm = np.stack(sb.render(spec, 30, 3.0))
        cold = np.stack(sb.render(spec, 30, 3.0, palette=pal.COLD))
        self.assertEqual(warm[..., 0].max(), 0)          # в тёплой чёрный пропал бы
        self.assertGreater(cold[..., 0].max(), 200)      # форма полосы - в красном
        self.assertGreater(cold[..., 2].max(), 150)      # синие искры - своим цветом
        self.assertTrue((cold[..., 3] == 255).all())     # DXT1 без прозрачности


class EffectAndBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch("src.services.work_store.WORK_DIR", Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)

    def _apply(self, pid):
        return fx.apply(fx.SHEEN, {"pattern": pid, "bright": 2, "when": "game"},
                        STOCK, STOCK, BOUNDS)["text"]

    def test_own_cold_pattern_gets_tint_without_red(self):
        pid = sl.save("", "Тень", {"layers": [layer(color="#000000")]}, 2.0)
        out = self._apply(pid)
        self.assertIn('"$tf2sg_sheen" "[0 2 2]"', out)
        self.assertRegex(out, r'tf2sg/sheen/' + pid + r'_a\d+k_\d+"')
        got = fx.values(fx.SHEEN, out)
        # «Вид» - поле шаблонов, служебный оттенок своего узора не цвет формы
        self.assertEqual((got["dark"], got["color"]), ("off", "#ffffff"))

    def test_build_follows_the_pattern_repainted_after_the_effect(self):
        pid = sl.save("", "Тень", {"layers": [layer(color="#000000")]}, 2.0)
        out = self._apply(pid)
        sl.save(pid, "Тень", {"layers": [layer(color="#ffffff")]}, 2.0)   # перекрасили
        root = Path(self.tmp.name) / "mod"
        (root / "materials" / "models").mkdir(parents=True)
        vmt = root / "materials" / "models" / "a.vmt"
        vmt.write_text(out, encoding="utf-8")
        sp.materialize(root, "console")
        text = vmt.read_text(encoding="utf-8")
        self.assertIn('"$tf2sg_sheen" "[2 2 2]"', text)
        self.assertNotRegex(text, r'_a\d+k_\d+"')


if __name__ == "__main__":
    unittest.main()
