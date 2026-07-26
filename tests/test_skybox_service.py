"""Тесты SkyboxService: нарезка панорамы, сборка VPK, роутинг сборки.

Нарезка фиксируется цветовой панорамой (центры граней = ожидаемые сектора
долготы/полюса) — это защищает калиброванные FACE_BASES от регрессий.
Сборка — паттерн test_vpk_service: реальный BuildContext во временной папке,
патчи TextureService/PackagingService, ассерты по файлам vpkroot.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.data.skyboxes import SKY_FACES
from src.services.build_context import BuildContext
from src.services.build_request import BuildRequest
from src.services.skybox_service import SkyboxService


def _make_banded_pano(path: str, w: int = 256, h: int = 128) -> dict:
    """Панорама с секторами долготы + полюсами. Возвращает ожидаемые цвета.

    Раскладка по x (формула нарезки: x = (0.5 - lon/2pi)*W):
      центр (x=W/2)  → ft;  x=W/4 → rt;  x=3W/4 → lf;  края → bk.
    Верхние/нижние 15% строк — полюса (up/dn).
    """
    colors = {
        "ft": (220, 200, 40), "lf": (200, 40, 40),
        "bk": (150, 60, 200), "rt": (40, 180, 80),
        "up": (255, 255, 255), "dn": (10, 10, 10),
    }
    im = Image.new("RGB", (w, h))
    px = im.load()
    for x in range(w):
        if x < w * 0.125 or x >= w * 0.875:
            band = colors["bk"]
        elif x < w * 0.375:
            band = colors["rt"]
        elif x < w * 0.625:
            band = colors["ft"]
        else:
            band = colors["lf"]
        for y in range(h):
            if y < h * 0.15:
                px[x, y] = colors["up"]
            elif y >= h * 0.85:
                px[x, y] = colors["dn"]
            else:
                px[x, y] = band
    im.save(path)
    return colors


def _center_color(png_path: str):
    with Image.open(png_path) as im:
        w, h = im.size
        return im.getpixel((w // 2, h // 2))


class SplitEquirectTests(unittest.TestCase):
    def test_face_centers_match_expected_directions(self):
        # Фиксирует FACE_BASES: центр каждой грани смотрит в свой сектор.
        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "pano.png")
            colors = _make_banded_pano(pano)
            faces = SkyboxService.split_equirect_to_faces(pano, 64, tmp)
            self.assertEqual(set(faces), set(SKY_FACES))
            for face in SKY_FACES:
                got = _center_color(faces[face])
                want = colors[face]
                for g, wnt in zip(got, want):
                    self.assertLessEqual(
                        abs(g - wnt), 12,
                        f"{face}: центр {got}, ожидалось ~{want}")

    def test_output_files_square_of_requested_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "pano.png")
            _make_banded_pano(pano)
            faces = SkyboxService.split_equirect_to_faces(pano, 48, tmp)
            for face, path in faces.items():
                with Image.open(path) as im:
                    self.assertEqual(im.size, (48, 48), face)

    def test_bk_center_spans_pano_seam_without_artifacts(self):
        # Центр bk — ровно на шве панорамы (x=0/W): билинейная выборка обязана
        # заворачиваться, иначе цвет центра исказится.
        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "pano.png")
            colors = _make_banded_pano(pano)
            faces = SkyboxService.split_equirect_to_faces(pano, 64, tmp)
            got = _center_color(faces["bk"])
            for g, wnt in zip(got, colors["bk"]):
                self.assertLessEqual(abs(g - wnt), 12)

    def test_fine_detail_survives_in_linear_light(self):
        """Мелкие яркие детали (звёзды) не должны гаснуть при нарезке.

        Шахматка 1 px из 255 и 4: физически верное среднее — 0.5 в линейном
        свете, то есть ~186 в sRGB. Усреднение самих sRGB-значений дало бы ~130
        (именно так звёзды и «пропадали»).

        Заодно фиксируется суперсэмплинг: без него значение пикселя зависит от
        того, куда случайно попал единственный отсчёт (разброс в сотню единиц —
        это и есть «шипение» мелких деталей), с ним грань ровная.
        """
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "chk.png")
            h, w = 256, 512
            yy, xx = np.mgrid[0:h, 0:w]
            chk = np.where((xx + yy) % 2 == 0, 255, 4).astype(np.uint8)
            Image.fromarray(np.dstack([chk] * 3)).save(pano)

            spans = {}
            for ss in (1, 2):
                faces = SkyboxService.split_equirect_to_faces(
                    pano, 64, os.path.join(tmp, f"o{ss}"), supersample=ss)
                arr = np.asarray(Image.open(faces["ft"]).convert("L"),
                                 dtype=np.float32)[16:48, 16:48]
                self.assertGreater(arr.mean(), 165, f"ss={ss}: детали погасли")
                self.assertLess(arr.mean(), 205, f"ss={ss}: пересвет")
                spans[ss] = float(arr.max() - arr.min())

            # Суперсэмплинг убирает разброс от случайной попадания отсчёта
            self.assertLess(spans[2], spans[1] / 4,
                            f"суперсэмплинг не сгладил алиасинг: {spans}")

    def test_upscaled_panorama_is_sharpened(self):
        """Панорама меньше граней: суперсэмплинг бессмыслен (деталей нет),
        зато контраст на границах должен подрасти от нерезкой маски."""
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "small.png")
            h, w = 64, 128
            half = np.zeros((h, w, 3), np.uint8)
            half[:, w // 2:] = 200          # резкая вертикальная граница
            Image.fromarray(half).save(pano)

            faces = SkyboxService.split_equirect_to_faces(
                pano, 128, os.path.join(tmp, "o"))   # 128 > 128/4 → апскейл
            arr = np.asarray(Image.open(faces["ft"]).convert("L"),
                             dtype=np.float32)
            # Нерезкая маска даёт «выброс» ярче исходных 200 у самой границы
            self.assertGreater(arr.max(), 205, "нерезкая маска не применилась")

    def test_cancel_stops_between_faces(self):
        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "pano.png")
            _make_banded_pano(pano)
            calls = {"n": 0}

            def cancel():
                calls["n"] += 1
                return calls["n"] > 2   # отменяем после двух граней

            faces = SkyboxService.split_equirect_to_faces(
                pano, 32, tmp, cancel_callback=cancel)
            self.assertLess(len(faces), len(SKY_FACES))


class NormalizeFaceTests(unittest.TestCase):
    def test_half_height_goes_to_top_half_with_clamped_bottom(self):
        # 2:1 (боковые грани стоковых небес): верхняя половина квадрата —
        # картинка, нижняя — растянутая нижняя строка (как рендерит движок).
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "side.png")
            im = Image.new("RGB", (64, 32), (0, 200, 0))
            for x in range(64):
                im.putpixel((x, 31), (200, 0, 0))   # нижняя строка — красная
            im.save(src)
            out = os.path.join(tmp, "sq.png")
            SkyboxService._normalize_face_to_square(src, out, 64)
            with Image.open(out) as sq:
                self.assertEqual(sq.size, (64, 64))
                self.assertEqual(sq.getpixel((32, 10)), (0, 200, 0))
                self.assertEqual(sq.getpixel((32, 50)), (200, 0, 0))

    def test_square_resizes_full_face(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "sq_src.png")
            Image.new("RGB", (32, 32), (10, 20, 30)).save(src)
            out = os.path.join(tmp, "sq.png")
            SkyboxService._normalize_face_to_square(src, out, 64)
            with Image.open(out) as sq:
                self.assertEqual(sq.size, (64, 64))
                self.assertEqual(sq.getpixel((5, 60)), (10, 20, 30))

    def test_up_face_2to1_stretches_full_face(self):
        # Правило «верхняя половина» — только для боковых; up/dn растягиваются.
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "up_src.png")
            im = Image.new("RGB", (64, 32), (0, 200, 0))
            for x in range(64):
                im.putpixel((x, 31), (200, 0, 0))
            im.save(src)
            out = os.path.join(tmp, "up_sq.png")
            SkyboxService._normalize_face_to_square(src, out, 64, face="up")
            with Image.open(out) as sq:
                # Низ квадрата — из нижних строк картинки, а не клампа одной
                # строки на всю половину: середина низа зелёная.
                self.assertEqual(sq.getpixel((32, 50)), (0, 200, 0))


class VtfStemTests(unittest.TestCase):
    def test_sanitizes_filename(self):
        self.assertEqual(SkyboxService._vtf_stem("My Sky Mod.vpk"), "my_sky_mod")

    def test_fallback_for_empty_stem(self):
        self.assertEqual(SkyboxService._vtf_stem("Небо.vpk"), "customsky")


def _build_request(tmp: str, **overrides) -> BuildRequest:
    pano = os.path.join(tmp, "pano.png")
    if not os.path.exists(pano):
        _make_banded_pano(pano)
    kwargs = dict(
        image_path=pano,
        mode="skybox",
        filename="Test Sky.vpk",
        size=(32, 32),
        format_type="DXT1",
        export_folder=os.path.join(tmp, "export"),
        language="en",
        skybox_sky_names=["sky_a_01", "sky_b_01"],
        skybox_face_overrides={},
    )
    kwargs.update(overrides)
    return BuildRequest(**kwargs)


class BuildSkyboxVpkTests(unittest.TestCase):
    def _run_build(self, request, tmp):
        """Запускает сборку с патчами; возвращает (ok, msg, снимок vpkroot)."""
        captured = {}
        vtf_calls = []

        def fake_create_vtf(png_path, out_dir, fmt, flags, options=None):
            stem = Path(png_path).stem
            # Центр PNG — для проверки «оверрайд бьёт панораму».
            center = _center_color(png_path)
            vtf_calls.append(
                {"stem": stem, "format": fmt, "flags": list(flags),
                 "options": dict(options or {}), "center": center})
            (Path(out_dir) / f"{stem}.vtf").write_bytes(b"VTF0")

        def fake_pack(ctx, filename, export_folder, language="en"):
            root = ctx.vpkroot_dir
            captured["files"] = sorted(
                str(p.relative_to(root)).replace("\\", "/")
                for p in root.rglob("*") if p.is_file())
            captured["vmt_texts"] = {
                p.name: p.read_text(encoding="utf-8")
                for p in root.rglob("*.vmt")}
            return os.path.join(export_folder, filename)

        def fake_ctx_create(mode, weapon_key, base_temp_dir=None, debug_mode=False):
            ctx = BuildContext("test_id", mode, weapon_key,
                               Path(tmp) / "ctx")
            ctx.create_directories()
            return ctx

        with patch("src.services.texture_service.TextureService.create_vtf",
                   side_effect=fake_create_vtf), \
             patch("src.services.packaging_service.PackagingService.create_vpk_file",
                   side_effect=fake_pack), \
             patch("src.services.build_context.BuildContext.create",
                   side_effect=fake_ctx_create):
            ok, msg = SkyboxService.build_skybox_vpk(request)
        return ok, msg, captured, vtf_calls

    def test_writes_shared_vtfs_and_per_sky_vmts(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = _build_request(tmp)
            ok, msg, cap, calls = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            vtfs = [f for f in cap["files"] if f.endswith(".vtf")]
            vmts = [f for f in cap["files"] if f.endswith(".vmt")]
            self.assertEqual(
                sorted(vtfs),
                sorted(f"materials/skybox/test_sky{face}.vtf"
                       for face in SKY_FACES))
            # 2 неба × 6 граней × (LDR + HDR) = 24
            self.assertEqual(len(vmts), 24)
            for sky in req.skybox_sky_names:
                for face in SKY_FACES:
                    self.assertIn(f"materials/skybox/{sky}{face}.vmt", vmts)
                    self.assertIn(f"materials/skybox/{sky}_hdr{face}.vmt", vmts)
            content = cap["vmt_texts"]["sky_a_01up.vmt"]
            self.assertIn('"sky"', content)
            self.assertIn('"$basetexture" "skybox/test_skyup"', content)
            self.assertIn('"$nofog" "1"', content)
            # HDR-клон ссылается на те же общие VTF.
            self.assertEqual(content, cap["vmt_texts"]["sky_a_01_hdrup.vmt"])

    def test_face_override_beats_panorama(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = os.path.join(tmp, "up_override.png")
            Image.new("RGB", (32, 32), (250, 5, 5)).save(override)
            req = _build_request(tmp, skybox_face_overrides={"up": override})
            ok, msg, _cap, calls = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            up_call = next(c for c in calls if c["stem"] == "test_skyup")
            self.assertEqual(up_call["center"], (250, 5, 5))

    def test_forces_clamp_flags_and_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Формат вне SKYBOX_ALLOWED_FORMATS и посторонние флаги игнорируются:
            # CLAMPS/CLAMPT/NOLOD и отсутствие мипов у скайбокса свои.
            req = _build_request(tmp, format_type="DXT5",
                                 flags=["NOMINMIP", "TRILINEAR"])
            ok, msg, _cap, calls = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            self.assertEqual(len(calls), 6)
            for c in calls:
                self.assertEqual(c["flags"], ["CLAMPS", "CLAMPT", "NOLOD"])
                self.assertTrue(c["options"].get("nomipmaps"))
                self.assertEqual(c["format"], "DXT1")

    def test_pointsample_flag_passes_through(self):
        """POINTSAMPLE — единственный пользовательский флаг, доезжающий до граней
        (без него звёзды размываются билинейной фильтрацией при увеличении)."""
        with tempfile.TemporaryDirectory() as tmp:
            req = _build_request(tmp, flags=["POINTSAMPLE"])
            ok, msg, _cap, calls = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            self.assertEqual(len(calls), 6)
            for c in calls:
                self.assertEqual(c["flags"],
                                 ["CLAMPS", "CLAMPT", "NOLOD", "POINTSAMPLE"])

    def test_ready_vtf_override_copied_as_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            vtf = os.path.join(tmp, "custom_up.vtf")
            with open(vtf, "wb") as f:
                f.write(b"VTF\x00custom")
            req = _build_request(tmp, skybox_face_overrides={"up": vtf})
            ok, msg, cap, calls = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            # up не конвертируется (5 вызовов create_vtf вместо 6)
            self.assertEqual(len(calls), 5)
            self.assertIn("materials/skybox/test_skyup.vtf", cap["files"])

    def test_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Нет небес
            req = _build_request(tmp, skybox_sky_names=[])
            ok, msg = SkyboxService.build_skybox_vpk(req)
            self.assertFalse(ok)
            # Нет ни панорамы, ни полного набора граней
            req = _build_request(tmp, image_path=None,
                                 skybox_face_overrides={"up": "nope.png"})
            ok, msg = SkyboxService.build_skybox_vpk(req)
            self.assertFalse(ok)
            # Имя без .vpk
            req = _build_request(tmp, filename="sky.zip")
            ok, msg = SkyboxService.build_skybox_vpk(req)
            self.assertFalse(ok)

    def test_cancel_returns_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = _build_request(tmp)
            captured = {}

            def fake_ctx_create(mode, weapon_key, base_temp_dir=None,
                                debug_mode=False):
                ctx = BuildContext("test_id", mode, weapon_key,
                                   Path(tmp) / "ctx")
                ctx.create_directories()
                captured["ctx"] = ctx
                return ctx

            with patch("src.services.build_context.BuildContext.create",
                       side_effect=fake_ctx_create):
                ok, msg = SkyboxService.build_skybox_vpk(
                    req, cancel_callback=lambda: True)
            self.assertFalse(ok)


class BuildRoutingTests(unittest.TestCase):
    def test_build_with_progress_routes_skybox_without_tf2(self):
        # Скайбокс идёт своей веткой ДО _validate_build_params:
        # ни image_path, ни tf2_root_dir не обязательны.
        from src.services.vpk_service import VPKService
        req = BuildRequest(mode="skybox", filename="s.vpk",
                           skybox_sky_names=["sky_a_01"])
        with patch("src.services.skybox_service.SkyboxService.build_skybox_vpk",
                   return_value=(True, "out/s.vpk")) as m:
            ok, msg, cancelled = VPKService.build_with_progress(req)
        self.assertTrue(ok)
        self.assertEqual(msg, "out/s.vpk")
        self.assertFalse(cancelled)
        m.assert_called_once()


if __name__ == "__main__":
    unittest.main()


def _make_animated_pano(path: str, frames: int = 3, w: int = 64, h: int = 32) -> None:
    """Простая анимированная equirect-панорама (GIF, кадры разного цвета)."""
    imgs = [Image.new("RGB", (w, h), (40 + i * 30, 60, 90)) for i in range(frames)]
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=100, loop=0)


class AnimatedSkyboxTests(unittest.TestCase):
    """Анимированные грани: нарезка анимированной панорамы + умный VMT
    (UnlitGeneric+AnimatedTexture только для анимированных граней)."""

    def _run_build(self, request, tmp):
        captured = {}

        def fake_create_vtf(png_path, out_dir, fmt, flags, options=None):
            (Path(out_dir) / f"{Path(png_path).stem}.vtf").write_bytes(b"VTF0")

        def fake_create_animated_vtf(input_path, output_file, size, fmt,
                                     flags, options=None):
            Path(output_file).write_bytes(b"VTF0")
            return 24  # fps

        def fake_pack(ctx, filename, export_folder, language="en"):
            root = ctx.vpkroot_dir
            captured["vmt_texts"] = {
                p.name: p.read_text(encoding="utf-8")
                for p in root.rglob("*.vmt")}
            captured["files"] = sorted(
                str(p.relative_to(root)).replace("\\", "/")
                for p in root.rglob("*") if p.is_file())
            return os.path.join(export_folder, filename)

        def fake_ctx_create(mode, weapon_key, base_temp_dir=None, debug_mode=False):
            ctx = BuildContext("test_id", mode, weapon_key, Path(tmp) / "ctx")
            ctx.create_directories()
            return ctx

        with patch("src.services.texture_service.TextureService.create_vtf",
                   side_effect=fake_create_vtf), \
             patch("src.services.texture_service.TextureService.create_animated_vtf",
                   side_effect=fake_create_animated_vtf), \
             patch("src.services.packaging_service.PackagingService.create_vpk_file",
                   side_effect=fake_pack), \
             patch("src.services.build_context.BuildContext.create",
                   side_effect=fake_ctx_create):
            ok, msg = SkyboxService.build_skybox_vpk(request)
        return ok, msg, captured

    def test_animated_split_produces_apng_faces(self):
        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "p.gif")
            _make_animated_pano(pano, frames=4)
            out = os.path.join(tmp, "faces")
            faces = SkyboxService.split_equirect_animated_to_faces(pano, 32, out)
            self.assertEqual(set(faces), set(SKY_FACES))
            for path in faces.values():
                with Image.open(path) as im:
                    self.assertEqual(im.n_frames, 4)     # все кадры сохранены
                    self.assertEqual(im.size, (32, 32))  # квадрат face_size

    def test_animated_panorama_writes_proxy_vmts(self):
        with tempfile.TemporaryDirectory() as tmp:
            pano = os.path.join(tmp, "anim_pano.gif")
            _make_animated_pano(pano, frames=3)
            req = _build_request(tmp, image_path=pano)
            ok, msg, cap = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            self.assertEqual(
                len([f for f in cap["files"] if f.endswith(".vtf")]), 6)
            up = cap["vmt_texts"]["sky_a_01up.vmt"]
            self.assertIn('"UnlitGeneric"', up)
            self.assertIn('"AnimatedTexture"', up)
            self.assertIn('"animatedTextureFrameRate" "24"', up)
            self.assertIn('"$hdrbasetexture" "skybox/test_skyup"', up)
            # HDR-клон идентичен
            self.assertEqual(up, cap["vmt_texts"]["sky_a_01_hdrup.vmt"])

    def test_mixed_uses_uniform_unlit_shader(self):
        """Смешанный скайбокс: анимирована одна грань → ВСЕ грани на UnlitGeneric
        (единый шейдер, без стыка sky/UnlitGeneric). Статичная грань — БЕЗ
        анимационных параметров (требование «ничего лишнего не добавляем»)."""
        with tempfile.TemporaryDirectory() as tmp:
            anim = os.path.join(tmp, "anim_up.gif")
            _make_animated_pano(anim, frames=3)
            # Статичная панорама (по умолчанию) + анимированный оверрайд только up.
            req = _build_request(tmp, skybox_face_overrides={"up": anim})
            ok, msg, cap = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            up = cap["vmt_texts"]["sky_a_01up.vmt"]
            self.assertIn('"UnlitGeneric"', up)
            self.assertIn('"AnimatedTexture"', up)       # анимированная грань
            ft = cap["vmt_texts"]["sky_a_01ft.vmt"]
            self.assertIn('"UnlitGeneric"', ft)          # единый шейдер
            self.assertNotIn('"sky"', ft)                # не разнородный
            self.assertNotIn("AnimatedTexture", ft)      # без анимац. параметров
            self.assertNotIn("$frame", ft)

    def test_fully_static_stays_sky_shader(self):
        """Без анимации — нативный шейдер sky на всех гранях (UnlitGeneric не навязываем)."""
        with tempfile.TemporaryDirectory() as tmp:
            req = _build_request(tmp)   # статичная панорама
            ok, msg, cap = self._run_build(req, tmp)
            self.assertTrue(ok, msg)
            for face in SKY_FACES:
                vmt = cap["vmt_texts"][f"sky_a_01{face}.vmt"]
                self.assertTrue(vmt.startswith('"sky"'))
                self.assertNotIn("UnlitGeneric", vmt)
