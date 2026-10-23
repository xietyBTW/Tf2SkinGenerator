"""Конструктор узора блеска (src/services/sheen_builder.py): слои -> кадры,
библиотека своих узоров и сборка маски по имени из VMT"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from src.services import sheen_builder as sb
from src.services import sheen_library as sl
from src.services import sheen_patterns as sp
from src.services import vmt_effects as fx

STOCK = '''"VertexLitGeneric"
{
	"$basetexture" "models/w/gun"
	"$sheenPassEnabled" "1"
	"$sheenmapmask" "Effects/AnimatedSheen/animatedsheen0"
	"Proxies"
	{
		"AnimatedWeaponSheen"
		{
			"animatedtexturevar" "$sheenmapmask"
			"animatedtextureframenumvar" "$sheenmapmaskframe"
		}
	}
}
'''


class SpecTests(unittest.TestCase):
    def test_clean_spec_drops_junk_and_clamps(self):
        spec = sb.clean_spec({"layers": [
            {"type": "stripe", "width": 99, "dir": "sideways", "start": 0.5, "end": 0.5},
            {"type": "laser"}, "junk",
        ] + [{"type": "flash"}] * 20})
        self.assertEqual(len(spec["layers"]), sb.MAX_LAYERS)
        stripe = spec["layers"][0]
        self.assertEqual(stripe["width"], 1.5)
        self.assertEqual(stripe["angle"], 0)             # мусорное направление - вперёд
        self.assertGreater(stripe["end"], stripe["start"])
        self.assertEqual(sb.clean_spec(None), {"layers": [], "quality": "medium"})

    def test_old_patterns_migrate_to_angles(self):
        old = sb.clean_spec({"layers": [
            {"type": "stripe", "dir": "down"}, {"type": "clouds", "dir": "left"},
            {"type": "flash", "fill": "across"}, {"type": "stripe", "angle": 400},
        ]})["layers"]
        self.assertEqual([old[0]["angle"], old[1]["angle"], old[3]["angle"]], [90, 180, 40])
        self.assertEqual((old[2]["fill"], old[2]["gangle"]), ("space", 90))

    def test_angled_stripe_and_drifting_clouds_render(self):
        for kind in ("stripe", "clouds", "image"):
            layer = sb.new_layer(kind) | {"angle": 135}
            frames = sb.render({"layers": [layer]}, 30, 3.0)
            if kind != "image":
                self.assertGreater(max(f[..., 0].max() for f in frames), 100, kind)
        # Полоса под 90° идёт сверху вниз: в начале прохода горит верх
        layer = sb.new_layer("stripe") | {"angle": 90, "wave": 0, "fade": 0, "width": 0.3}
        early = sb.render({"layers": [layer]}, 41, 3.0)[16][..., 0].astype(int)
        self.assertGreater(early[:40].sum(), early[-40:].sum())

    def test_every_preset_renders_with_blank_first_frame(self):
        for key, preset in sb.PRESETS.items():
            frames = sb.render(preset["spec"], 40, 3.0)
            self.assertEqual(len(frames), 40, key)
            self.assertEqual(frames[0][..., :3].max(), 0, key)
            self.assertGreater(max(f[..., 0].max() for f in frames), 150, key)

    def test_sparkle_brightness_follows_power(self):
        def peak(power):
            layer = sb.new_layer("sparkle") | {"power": power, "count": 200, "life": 1}
            return max(f[..., 0].max() for f in sb.render({"layers": [layer]}, 30, 3.0))
        self.assertLess(peak(0.4), peak(1.0) * 0.6)

    def test_quality_shapes_the_mask_like_the_weapon(self):
        self.assertEqual(sb.mask_shape(3.0, "medium"), (128, 512))
        self.assertEqual(sb.mask_shape(3.0, "high"), (256, 1024))
        self.assertEqual(sb.mask_shape(1.0, "low"), (64, 64))
        spec = {"layers": [sb.new_layer("stripe")], "quality": "high"}
        self.assertEqual(sb.render(spec, 26, 3.0)[1].shape[:2], (256, 1024))
        self.assertEqual(sb.clean_spec({"layers": [], "quality": "ultra"})["quality"], "medium")
        self.assertEqual(sb.mod_bytes(61, 3.0, "medium"), 61 * 128 * 512 // 2)

    def test_layer_time_window(self):
        spec = {"layers": [sb.new_layer("flash") | {"start": 0.5, "end": 1.0, "grain": 0}]}
        frames = sb.render(spec, 51, 3.0)
        self.assertEqual(max(f[..., 0].max() for f in frames[1:20]), 0)   # до начала пусто
        self.assertGreater(max(f[..., 0].max() for f in frames[30:]), 100)

    def test_sparkles_round_on_the_weapon(self):
        # В маске искра сжата по X в A раз - на оружии игра растянет её обратно
        spec = sb.clean_spec({"layers": [sb.new_layer("sparkle") | {"size": 0.2, "star": 0, "life": 1}]})
        layer = sb._Layer(spec["layers"][0], 128, 512, 4.0)
        layer.pos, layer.birth = np.array([[2.0, 0.5]]), np.array([0.0])
        ys, xs = np.nonzero(layer._sparkles(0.5) > 0.25)
        width, height = np.ptp(xs) + 1, np.ptp(ys) + 1
        # Маска 128×512 на оружии 4:1 - точка маски квадратная, искра тоже
        self.assertAlmostEqual(width / height, 1.0, delta=0.35)

    def test_image_layer_reveals_picture(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            pic = Path(tmp) / "logo.png"
            img = np.zeros((40, 40, 4), np.uint8)
            img[10:30, 10:30] = (255, 255, 255, 255)
            Image.fromarray(img).save(pic)
            layer = sb.new_layer("image") | {"image": str(pic), "mode": "still", "fade": 0}
            frames = sb.render({"layers": [layer]}, 30, 1.0)
            self.assertEqual(frames[1].shape[:2], sb.mask_shape(1.0, "medium"))
            middle = frames[10][..., 0]
            self.assertGreater(middle[64, 64], 150)                       # квадрат в центре
            self.assertEqual(middle[5, 5], 0)


def _picture(tmp: str, name: str = "logo.png", rgb=(255, 255, 255)) -> str:
    """Квадрат 20×20 цвета rgb в центре прозрачной картинки 40×40"""
    from PIL import Image
    img = np.zeros((40, 40, 4), np.uint8)
    img[10:30, 10:30] = (*rgb, 255)
    path = Path(tmp) / name
    Image.fromarray(img).save(path)
    return str(path)


class LayerOptionsTests(unittest.TestCase):
    """Смешивание, повторы и настройки картинки"""

    @staticmethod
    def flash(**kw) -> dict:
        return sb.new_layer("flash") | {"grain": 0, "fade": 0, "sharp": 0, "start": 0, "end": 1} | kw

    def still(self, tmp, **kw) -> dict:
        return sb.new_layer("image") | {"image": _picture(tmp), "mode": "still", "fade": 0,
                                        "start": 0, "end": 1} | kw

    def test_mask_shows_layers_below_only_through_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Список сверху вниз: маска над вспышкой
            spec = {"layers": [self.still(tmp, blend="mask"), self.flash()]}
            mid = sb.render(spec, 30, 1.0)[15][..., 0]
            self.assertGreater(mid[64, 64], 150)                 # сквозь квадрат видно
            self.assertEqual(mid[5, 5], 0)                       # вне квадрата - нет
            cut = sb.render({"layers": [self.still(tmp, blend="cut"), self.flash()]}, 30, 1.0)[15][..., 0]
            self.assertEqual(cut[64, 64], 0)
            self.assertGreater(cut[5, 5], 150)

    def test_mask_below_does_nothing_to_layers_above(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = {"layers": [self.flash(), self.still(tmp, blend="cut")]}
            self.assertGreater(sb.render(spec, 30, 1.0)[15][64, 64, 0], 150)

    def test_add_sums_and_lighten_takes_brightest(self):
        half = self.flash(power=0.5)
        lighten = sb.render({"layers": [half, half]}, 30, 1.0)[15][64, 64, 0]
        added = sb.render({"layers": [half | {"blend": "add"}, half]}, 30, 1.0)[15][64, 64, 0]
        self.assertAlmostEqual(int(added), 2 * int(lighten), delta=2)

    def test_repeat_and_bounce(self):
        layer = sb.clean_spec({"layers": [sb.new_layer("stripe") | {"repeat": 3}]})["layers"][0]
        lay = sb._Layer(layer, 16, 32, 2.0)
        self.assertAlmostEqual(lay.phase(0.5), 0.5)          # середина второго прохода
        self.assertAlmostEqual(lay.phase(0.2), 0.6)
        lay.bounce = True
        self.assertAlmostEqual(lay.phase(0.5), 0.5)
        self.assertAlmostEqual(lay.phase(0.4), 0.8)          # второй проход - назад
        self.assertEqual(sb.clean_spec({"layers": [{"type": "flash", "repeat": 3.7}]})
                         ["layers"][0]["repeat"], 4)

    def test_image_size_position_and_invert(self):
        with tempfile.TemporaryDirectory() as tmp:
            def frame(**kw):
                return sb.render({"layers": [self.still(tmp, **kw)]}, 30, 1.0)[15][..., 0].astype(int)
            small = frame(scale=0.5)
            self.assertGreater(small[64, 64], 150)
            self.assertEqual(small[64, 40], 0)                   # квадрат стал вдвое меньше
            left = frame(pos_x=0.25)
            self.assertGreater(left[64, 32], 150)
            self.assertEqual(left[64, 96], 0)
            # Негатив: белый квадрат гаснет, прозрачное остаётся тёмным
            inv = frame(invert="yes")
            self.assertEqual((inv[64, 64], inv[5, 5]), (0, 0))

    def test_picture_colours(self):
        with tempfile.TemporaryDirectory() as tmp:
            layer = self.still(tmp, fill="image") | {"image": _picture(tmp, "red.png", (255, 0, 0))}
            mid = sb.render({"layers": [layer]}, 30, 1.0)[15]
            self.assertGreater(mid[64, 64, 0], 150)
            self.assertEqual(int(mid[64, 64, 2]), 0)
        # Цвета картинки - только у слоя-картинки
        self.assertEqual(sb.clean_spec({"layers": [{"type": "flash", "fill": "image"}]})
                         ["layers"][0]["fill"], "solid")


class PreviewTests(unittest.TestCase):
    """Превью конструктора: отмена устаревшего расчёта, кэш листа и картинок"""

    def test_cancel_stops_rendering(self):
        asked = []
        def cancelled():
            asked.append(1)
            return len(asked) > 3
        with self.assertRaises(sb.Cancelled):
            list(sb.iter_frames(sb.PRESETS["classic"]["spec"], 60, 3.0, cancelled=cancelled))
        self.assertEqual(len(asked), 4)

    def test_same_pattern_reuses_the_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = sb.PRESETS["double"]["spec"]
            first = sb.preview(spec, 30, 3.0, Path(tmp))
            with mock.patch.object(sb, "preview_sheet") as again:
                second = sb.preview(spec, 30, 3.0, Path(tmp))
            again.assert_not_called()
            self.assertEqual(first, second)
            sb.preview(sb.PRESETS["pulse"]["spec"], 30, 3.0, Path(tmp))
            self.assertEqual(len(list(Path(tmp).glob("*.png"))), 2)

    def test_changed_picture_file_is_read_again(self):
        import os
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path = _picture(tmp)
            layer = sb.new_layer("image") | {"image": path, "mode": "still", "fade": 0}
            self.assertGreater(sb.render({"layers": [layer]}, 30, 1.0)[15][64, 64, 0], 150)
            Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(path)     # тот же путь, другое
            st = os.stat(path)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
            self.assertEqual(sb.render({"layers": [layer]}, 30, 1.0)[15][..., 0].max(), 0)

    def test_huge_picture_is_kept_small(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.png"
            Image.new("RGBA", (3000, 2000), (255, 255, 255, 255)).save(path)
            st = path.stat()
            src = sb._source(str(path), st.st_mtime_ns, st.st_size)
            self.assertLessEqual(src.width * src.height, sb._SOURCE_PIXELS * 1.01)
            self.assertAlmostEqual(src.width / src.height, 1.5, delta=0.01)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patch = mock.patch("src.services.work_store.WORK_DIR", Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_save_load_list_delete_and_image_copy(self):
        from PIL import Image
        pic = Path(self.tmp.name) / "upload.png"
        Image.new("RGB", (8, 8), "white").save(pic)
        spec = {"layers": [sb.new_layer("image") | {"image": str(pic)}]}
        pid = sl.save("", "Логотип", spec, 3.0)
        self.assertRegex(pid, sl.ID_RE)
        data = sl.load(pid)
        self.assertEqual((data["name"], data["length"]), ("Логотип", 3.0))
        # Странице - абсолютный путь (миниатюра), на диске - относительный
        stored = Path(data["spec"]["layers"][0]["image"])
        self.assertEqual(stored.parent, sb.library_dir() / "images")
        self.assertIn('"images/', (sb.library_dir() / f"{pid}.json").read_text(encoding="utf-8"))
        pic.unlink()                                       # временный файл пропал
        self.assertTrue(stored.is_file())                  # копия в библиотеке цела
        self.assertEqual([p["id"] for p in sl.list_patterns()], [pid])
        self.assertEqual(sl.save(pid, "Новое имя", data["spec"], 2.0), pid)
        self.assertEqual(sl.load(pid)["name"], "Новое имя")
        self.assertTrue(sl.delete(pid))
        self.assertIsNone(sl.load(pid))
        self.assertFalse(sl.delete("../evil"))

    def test_effect_and_build_use_the_pattern(self):
        pid = sl.save("", "Две", sb.PRESETS["double"]["spec"], 2.0)
        bounds = {"scale_x": 30.0, "scale_y": 10.0, "offset_x": 0, "offset_y": 0, "direction": 0}
        out = fx.apply(fx.SHEEN, {"color": "#ffffff", "pattern": pid, "length": 2}, STOCK, "",
                       bounds)["text"]
        self.assertIn(f'"$sheenmapmask" "tf2sg/sheen/{pid}_a30_51"', out)
        self.assertEqual(fx.values(fx.SHEEN, out)["pattern"], pid)
        root = Path(self.tmp.name) / "vpkroot"
        mat = root / "materials" / "models" / "w"
        mat.mkdir(parents=True)
        (mat / "gun.vmt").write_text(out, encoding="utf-8")
        self.assertEqual(sp.materialize(root, "console"), 2)
        # В моде - с отпечатком содержимого узора
        digest = sl.content_hash(pid)
        vtf = root / "materials" / "console" / "tf2sg" / "sheen" / f"{pid}_h{digest}_a30_51.vtf"
        self.assertTrue(vtf.is_file())
        self.assertIn(f"console/tf2sg/sheen/{pid}_h{digest}_a30_51", (mat / "gun.vmt").read_text())
        # Правка узора - другой отпечаток, другой путь
        sl.save(pid, "Две", sb.PRESETS["running"]["spec"], 2.0)
        self.assertNotEqual(sl.content_hash(pid), digest)
        from src.services.vtflib_wrapper import VTFLib
        frames, w, h = VTFLib.read_vtf_all_frames(str(vtf))
        self.assertEqual((len(frames), h, w), (51, *sb.mask_shape(3.0, "medium")))

    def test_image_survives_relative_work_dir(self):
        # В приложении папка работ относительная ("work"),
        # путь картинки уходил странице относительным и при следующем превью
        # искался внутри библиотеки - картинка пропадала из превью и игры
        import os
        from PIL import Image
        pic = Path(self.tmp.name) / "photo.png"
        Image.new("RGB", (16, 16), "white").save(pic)
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)
        with mock.patch("src.services.work_store.WORK_DIR", Path("work")):
            layer = sb.new_layer("image") | {"image": str(pic), "mode": "still", "fade": 0}
            pid = sl.save("", "Фото", {"layers": [layer]}, 2.0)
            again = sl.load(pid)["spec"]                 # как страница получит узор
            self.assertTrue(Path(again["layers"][0]["image"]).is_absolute())
            frames = sb.render(again, 30, 2.0)           # и пришлёт обратно в превью
            self.assertGreater(max(f[..., :3].max() for f in frames), 150)

    def test_layer_colour_lives_in_the_mask(self):
        layer = sb.new_layer("flash") | {"color": "#0000ff", "grain": 0, "fade": 0}
        frames = sb.render({"layers": [layer]}, 30, 3.0)
        mid = frames[15]
        self.assertEqual(int(mid[..., 0].max()), 0)
        self.assertGreater(int(mid[..., 2].max()), 150)

    def test_gradient_fills(self):
        stops = [[0, "#ff0000"], [1, "#0000ff"]]
        def frame(fill, i=15):
            layer = sb.new_layer("flash") | {"fill": fill, "stops": stops, "grain": 0, "fade": 0,
                                              "sharp": 0}
            return sb.render({"layers": [layer]}, 30, 3.0)[i][..., :3].astype(int)
        along = frame("along")
        self.assertGreater(along[64, 2, 0], along[64, 2, 2])       # начало оружия красное
        self.assertGreater(along[64, -3, 2], along[64, -3, 0])     # конец синий
        across = frame("across")
        self.assertGreater(across[2, 64, 0], across[125, 64, 0])   # верх красный, низ нет
        early, late = frame("time", 8), frame("time", 22)
        self.assertGreater(early[64, 64, 0], early[64, 64, 2])     # во времени: сначала красный
        self.assertGreater(late[64, 64, 2], late[64, 64, 0])       # потом синий
        self.assertEqual(sb.clean_spec({"layers": [{"type": "flash", "stops": [[0, "bad"]]}]})
                         ["layers"][0]["stops"], sb.DEFAULT_STOPS)

    def test_vertical_weapon_gets_rotated_side_stencil(self):
        # Кунай: длина по Z. Своя маска - трафарет сбоку (направление 0, X и Z),
        # повёрнутый, раскладка закреплена своими прокси после игрового
        import struct
        mdl = bytearray(300)
        mdl[:4] = b'IDST'
        struct.pack_into('<3f', mdl, 104, -1.4, -1.0, -5.8)
        struct.pack_into('<3f', mdl, 116, 2.1, 1.3, 13.6)
        bounds = fx.sheen_mask_params(bytes(mdl))
        st = bounds["stencil"]
        self.assertEqual((st["direction"], st["rotate"]), (0, True))
        self.assertAlmostEqual(st["scale_x"], 3.5, places=4)      # ширина X
        self.assertAlmostEqual(st["scale_y"], 19.4, places=4)     # длина Z
        self.assertAlmostEqual(st["aspect"], 19.4 / 3.5, places=3)
        pid = sl.save("", "Поворот", sb.PRESETS["double"]["spec"], 2.0)
        out = fx.apply(fx.SHEEN, {"pattern": pid, "length": 2}, STOCK, "", bounds)["text"]
        self.assertIn(f'tf2sg/sheen/{pid}_a55r_51', out)
        self.assertIn('"$sheenmapmaskdirection" "0"', out)
        self.assertIn('"resultVar" "$sheenmapmaskscaleY"', out)   # закреплено прокси
        self.assertEqual(fx.values(fx.SHEEN, out)["pattern"], pid)
        root = Path(self.tmp.name) / "vpkroot"
        mat = root / "materials" / "models" / "w"
        mat.mkdir(parents=True)
        (mat / "kunai.vmt").write_text(out, encoding="utf-8")
        self.assertEqual(sp.materialize(root, ""), 2)          # маска + ровная кубмапа
        vtf = next((root / "materials" / "tf2sg" / "sheen").glob("*_51.vtf"))
        self.assertIn("r_51", vtf.name)
        from src.services.vtflib_wrapper import VTFLib
        _frames, w, h = VTFLib.read_vtf_all_frames(str(vtf))
        mh, mw = sb.mask_shape(19.4 / 3.5, "medium")
        self.assertEqual((w, h), (mh, mw))                        # повёрнута: длина по высоте

    def test_deleted_pattern_still_builds(self):
        pid = sl.save("", "Старый", sb.PRESETS["pulse"]["spec"], 2.0)
        self.assertTrue(sl.delete(pid))
        self.assertEqual(sl.list_patterns(), [])               # из списка ушёл
        self.assertIsNone(sl.load(pid))
        root = Path(self.tmp.name) / "vpkroot"
        mat = root / "materials" / "models"
        mat.mkdir(parents=True)
        (mat / "a.vmt").write_text(STOCK.replace(
            "Effects/AnimatedSheen/animatedsheen0", f"tf2sg/sheen/{pid}_a30_51"), encoding="utf-8")
        self.assertEqual(sp.materialize(root, ""), 1)          # другая работа собирается

    def test_unreadable_image_is_rejected_on_save(self):
        bad = Path(self.tmp.name) / "vector.png"
        bad.write_text("<svg></svg>")
        with self.assertRaises(ValueError):
            sl.save("", "x", {"layers": [sb.new_layer("image") | {"image": str(bad)}]}, 2.0)
        # В отрисовке - пустой слой, а не упавшая сборка
        frames = sb.render({"layers": [sb.new_layer("image") | {"image": str(bad)}]}, 30, 3.0)
        self.assertEqual(max(f[..., 0].max() for f in frames), 0)

    def test_missing_pattern_fails_the_build_loudly(self):
        root = Path(self.tmp.name) / "vpkroot"
        mat = root / "materials" / "models"
        mat.mkdir(parents=True)
        (mat / "a.vmt").write_text(STOCK.replace(
            "Effects/AnimatedSheen/animatedsheen0", "tf2sg/sheen/u00000000_a30_51"), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            sp.materialize(root, "console")

    def test_deleted_pattern_is_an_error_in_the_effect(self):
        res = fx.apply(fx.SHEEN, {"pattern": "u00000000"}, STOCK, "", None)
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
