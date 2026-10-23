"""Свои узоры блеска Killstreak (src/services/sheen_patterns.py) и их связь
с эффектом «Цвет блеска киллстрика»"""
import tempfile
import unittest
from unittest import mock
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
        for name in sp.PATTERNS:
            pics = sp.frames(name, 31)
            self.assertEqual(len(pics), 31)
            self.assertEqual(pics[0][..., :3].max(), 0, name)          # кадр 0 не рисуется
            self.assertGreater(max(p[..., 0].max() for p in pics), 120, name)
            self.assertEqual(pics[-1][..., :3].max(), 0, name)         # пауза в конце прохода

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
            # Ручная запись: обратные слэши, без пробела, с .vtf
            (mat / "c.vmt").write_text(STOCK.replace(
                '"$sheenmapmask" "Effects/AnimatedSheen/animatedsheen0"',
                '"$sheenmapmask""TF2SG\\sheen\\stripes_31.vtf"'), encoding="utf-8")
            self.assertEqual(sp.materialize(root, "vgui\\replay\\thumbnails"), 1)
            # Маска - в папке-обходе sv_pure, ссылки VMT туда же
            vtf = root / "materials" / "vgui" / "replay" / "thumbnails" / "tf2sg" / "sheen" / "stripes_31.vtf"
            self.assertTrue(vtf.is_file())
            for name in ("a.vmt", "c.vmt"):
                self.assertIn('vgui/replay/thumbnails/tf2sg/sheen/stripes_31"',
                              (mat / name).read_text(encoding="utf-8"))
            from src.services.vtflib_wrapper import VTFLib
            frames, w, h = VTFLib.read_vtf_all_frames(str(vtf))
            self.assertEqual((len(frames), w, h), (31, sp.SIZE, sp.SIZE))
            # Повторная упаковка: ссылка уже с папкой, файл есть
            self.assertEqual(sp.materialize(root, "vgui\\replay\\thumbnails"), 0)
            self.assertNotIn('thumbnails/vgui', (mat / "a.vmt").read_text(encoding="utf-8"))

    def test_each_mod_gets_its_own_sheen_folder(self):
        """Два мода с одинаковыми именами масок и ровной кубмапой не должны
        делить путь: прелоадер видел конфликт, а при разном содержимом один
        мод ломал бы блеск другого"""
        out = fx.apply(fx.SHEEN, {"color": "#00ff00", "pattern": "p_mist"}, STOCK, STOCK,
                       BOUNDS)["text"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "materials" / "models").mkdir(parents=True)
            vmt = root / "materials" / "models" / "a.vmt"
            vmt.write_text(out, encoding="utf-8")
            self.assertEqual(sp.materialize(root, "console", namespace="My Kunai-mod"), 2)
            text = vmt.read_text(encoding="utf-8")
            self.assertIn('"$sheenmap" "console/my_kunai_mod/tf2sg/sheen/flat"', text)
            self.assertIn('"$sheenmapmask" "console/my_kunai_mod/tf2sg/sheen/p_mist_h', text)
            self.assertTrue((root / "materials" / "console" / "my_kunai_mod" / "tf2sg"
                             / "sheen" / "flat.vtf").is_file())
            # Повторная упаковка не плодит вложенных папок
            self.assertEqual(sp.materialize(root, "console", namespace="My Kunai-mod"), 0)
            self.assertEqual(vmt.read_text(encoding="utf-8"), text)

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
        vals = {"color": "#00ff00", "bright": 1, "when": "game", **vals}
        return fx.apply(fx.SHEEN, vals, text, "", BOUNDS)["text"]

    def test_pattern_sets_own_mask_and_reopens(self):
        """Готовый узор - шаблон конструктора, маска в пропорции оружия"""
        out = self.sheen(pattern="p_pulse", length=4)
        self.assertRegex(out, r'"\$sheenmapmask" "tf2sg/sheen/p_pulse_a\d+r?_101"')
        got = fx.values(fx.SHEEN, out)
        self.assertEqual((got["pattern"], got["length"]), ("p_pulse", 4.0))
        # Кадры по-прежнему крутит прокси игры - он в материале остался
        self.assertIn("AnimatedWeaponSheen", out)

    def test_old_pattern_reopens_as_its_template(self):
        """VMT старой работы со старым узором открывается тем же видом"""
        old = STOCK.replace("Effects/AnimatedSheen/animatedsheen0", "tf2sg/sheen/stripes_101")
        old = old.replace('"$sheenPassEnabled"', '"$tf2sg_sheen" "[1 1 1]"\n\t"$sheenPassEnabled"')
        got = fx.values(fx.SHEEN, old)
        self.assertEqual((got["pattern"], got["length"]), ("p_running", 4.0))

    def test_own_pattern_ignores_effect_colour(self):
        """Свой узор красят слои: цвет эффекта белый, радуга не включается"""
        from src.services import sheen_library
        with mock.patch.object(sheen_library, "load",
                               lambda pid, deleted=False: {"id": pid, "length": 3.0,
                                                           "spec": {"layers": []}}):
            out = self.sheen(pattern="u0123abcd", color="#00ff00", bright=2,
                             color_mode="rainbow", length=8)
        self.assertIn('"$tf2sg_sheen" "[2 2 2]"', out)
        self.assertNotIn("Sine", out)
        self.assertIn("_76", out)            # длина из конструктора, 3 с

    def test_back_to_game_pattern_restores_stock_mask(self):
        out = self.sheen(self.sheen(pattern="p_mist"), pattern="game")
        self.assertIn('"$sheenmapmask" "effects/animatedsheen/animatedsheen0"', out)
        self.assertEqual(fx.values(fx.SHEEN, out)["pattern"], "game")

    def test_back_to_game_restores_own_mod_mask(self):
        mod = STOCK.replace("Effects/AnimatedSheen/animatedsheen0", "mods/my_mask")
        own = fx.apply(fx.SHEEN, {"color": "#00ff00", "pattern": "p_mist"}, mod, mod, BOUNDS)["text"]
        back = fx.apply(fx.SHEEN, {"color": "#00ff00", "pattern": "game"}, own, mod, BOUNDS)["text"]
        self.assertIn('"$sheenmapmask" "mods/my_mask"', back)

    def test_flat_cube_for_own_pattern_and_back(self):
        out = self.sheen(pattern="p_mist")
        self.assertIn('"$sheenmap" "tf2sg/sheen/flat"', out)
        self.assertEqual(fx.values(fx.SHEEN, out)["shine"], "flat")
        live = self.sheen(out, pattern="p_mist", shine="live")
        self.assertIn('"$sheenmap" "cubemaps/cubemap_sheen001"', live)
        self.assertEqual(fx.values(fx.SHEEN, live)["shine"], "live")
        back = fx.apply(fx.SHEEN, {"color": "#00ff00", "pattern": "game"}, out, STOCK, BOUNDS)["text"]
        self.assertIn('"$sheenmap" "cubemaps/cubemap_sheen001"', back)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mat = root / "materials" / "models"
            mat.mkdir(parents=True)
            (mat / "a.vmt").write_text(out, encoding="utf-8")
            self.assertEqual(sp.materialize(root, "console"), 2)   # маска + кубмапа
            text = (mat / "a.vmt").read_text(encoding="utf-8")
            self.assertIn('"$sheenmap" "console/tf2sg/sheen/flat"', text)
            self.assertIn('"$sheenmapmask" "console/tf2sg/sheen/p_mist_h', text)
            from src.services.vtflib_wrapper import VTFLib
            cube = str(root / "materials" / "console" / "tf2sg" / "sheen" / "flat.vtf")
            for face in range(7):
                self.assertEqual(VTFLib.read_vtf_as_rgba(cube, face)[0][:3], bytes([sp.FLAT_GREY] * 3))
            # Как у игровой кубмапы: 7 граней (со сферической), startFrame 0 -
            # TF2 не знает соглашения VTFLib «6 граней при 0xFFFF»
            raw = Path(cube).read_bytes()
            header = int.from_bytes(raw[12:16], "little")
            self.assertEqual(int.from_bytes(raw[26:28], "little"), 0)
            self.assertEqual(len(raw) - header, 7 * 4 * 4 * 4)
            self.assertEqual(sp.materialize(root, "console"), 0)

    def test_black_sheen_green_tint_on_red_only_mask(self):
        """Чёрный блеск (проверен в игре): непрозрачность берётся из красного
        канала маски, цвет - оттенок x маска. Зелёный оттенок на красной маске
        = полная непрозрачность при цвете 0"""
        out = self.sheen(pattern="p_classic", dark="on", color="#ff00ff", bright=2)
        self.assertIn('"$tf2sg_sheen" "[0 2 2]"', out)          # без красного
        self.assertRegex(out, r'"\$sheenmapmask" "tf2sg/sheen/p_classic_a\d+k_\d+"')
        got = fx.values(fx.SHEEN, out)
        self.assertEqual((got["dark"], got["color"]), ("on", "#ffffff"))
        # У игрового узора маска серая - чёрный там не получится, и поля нет
        game = self.sheen(pattern="game", dark="on", color="#ff0000")
        self.assertIn('"$tf2sg_sheen" "[1 0 0]"', game)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "materials" / "models").mkdir(parents=True)
            (root / "materials" / "models" / "a.vmt").write_text(out, encoding="utf-8")
            sp.materialize(root, "console")
            vtf = next(root.rglob("p_classic_*k_*.vtf"))
            from src.services.vtflib_wrapper import VTFLib
            frames, w, h = VTFLib.read_vtf_all_frames(str(vtf))
            px = np.stack([np.frombuffer(f, np.uint8).reshape(h, w, 4) for f in frames])
            self.assertGreater(px[..., 0].max(), 120)
            self.assertEqual(px[..., 1:3].max(), 0)

    def test_black_hides_the_colour_fields(self):
        fields = {f["key"]: f for f in fx.fields(fx.SHEEN, False)}
        # Только у шаблонов: у своего узора гамму выбирают цвета слоёв
        self.assertIn("p_classic", fields["dark"]["show_if"]["pattern"])
        self.assertNotIn("game", fields["dark"]["show_if"]["pattern"])
        self.assertEqual(fields["color_mode"]["show_if"]["dark!"], "on")

    def test_always_counts_pattern_frames(self):
        out = self.sheen(pattern="p_double", length=2, when="always")
        self.assertIn('"$tf2sg_sheenlast" "50.0"', out)               # 51 кадр
        keys = [l for l in out.lower().splitlines() if l.startswith('	"$sheenmapmask" ')]
        self.assertEqual(len(keys), 1)
        self.assertRegex(keys[0], r'"tf2sg/sheen/p_double_a\d+r?_51"$')


if __name__ == "__main__":
    unittest.main()
