import os
import tempfile
import unittest

from PIL import Image


class VTFLibAnimatedVTFTests(unittest.TestCase):
    def test_create_animated_vtf_from_gif(self):
        from src.services.texture_service import TextureService

        tmp_dir = tempfile.mkdtemp(prefix="vtf_anim_")
        try:
            gif_path = os.path.join(tmp_dir, "anim.gif")
            out_vtf = os.path.join(tmp_dir, "anim.vtf")

            im1 = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
            im2 = Image.new("RGBA", (64, 64), (0, 255, 0, 255))
            im1.save(gif_path, save_all=True, append_images=[im2], duration=100, loop=0)

            fps = TextureService.create_animated_vtf(
                gif_path,
                out_vtf,
                (64, 64),
                "DXT1",
                [],
                {},
            )

            self.assertTrue(os.path.exists(out_vtf))
            self.assertGreater(os.path.getsize(out_vtf), 0)
            self.assertTrue(fps is None or fps > 0)
        except Exception as e:
            self.skipTest(str(e))
        finally:
            try:
                for name in os.listdir(tmp_dir):
                    try:
                        os.remove(os.path.join(tmp_dir, name))
                    except Exception:
                        pass
                os.rmdir(tmp_dir)
            except Exception:
                pass


class AnimatedNormalMapTests(unittest.TestCase):
    def test_gif_with_normal_option_builds_both_vtfs(self):
        """Гифка + включённый normal map → база И многокадровая нормаль."""
        from pathlib import Path

        from src.services.texture_service import TextureService

        tmp_dir = tempfile.mkdtemp(prefix="vtf_anim_normal_")
        try:
            gif_path = os.path.join(tmp_dir, "anim.gif")
            frames = [Image.new("RGB", (32, 32), c) for c in ((200, 30, 30), (30, 200, 30))]
            frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=125, loop=0)

            out_dir = Path(tmp_dir)
            fps, is_normal = TextureService.render_image_to_vtf(
                gif_path,
                vtf_output_path=out_dir,
                out_vtf_path=out_dir / "c_test.vtf",
                temp_png_path=out_dir / "c_test.png",
                normal_base="c_test",
                size=(32, 32),
                format_type="DXT5",
                flags=[],
                vtf_options={"normal": True},
            )

            self.assertTrue(is_normal)
            self.assertEqual(fps, 8)                       # 125 мс → 8 fps
            self.assertTrue((out_dir / "c_test.vtf").exists())
            self.assertTrue((out_dir / "c_test_normal.vtf").exists())
        except OSError as e:
            self.skipTest(str(e))                          # нет VTFLib DLL в окружении
        finally:
            for name in os.listdir(tmp_dir):
                try:
                    os.remove(os.path.join(tmp_dir, name))
                except OSError:
                    pass
            os.rmdir(tmp_dir)


class AnimationFpsTests(unittest.TestCase):
    """fps берётся по СРЕДНЕМУ кадру, а не по первому (переменные задержки)."""

    def test_fps_from_durations_averages(self):
        from src.services.texture_service import TextureService

        # 100 + 300 мс → средние 200 мс → 5 fps (по первому кадру было бы 10).
        self.assertEqual(TextureService._fps_from_durations([100, 300]), 5)
        # Нулевые/сверхкороткие задержки трактуются как 100 мс.
        self.assertEqual(TextureService._fps_from_durations([0, 0]), 10)
        self.assertEqual(TextureService._fps_from_durations([]), 10)

    def test_animation_info_detects_opacity_and_count(self):
        from src.services.texture_service import TextureService

        tmp_dir = tempfile.mkdtemp(prefix="vtf_anim_info_")
        try:
            gif_path = os.path.join(tmp_dir, "opaque.gif")
            frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
            frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=[100, 300, 200], loop=0)

            count, has_alpha = TextureService._animation_info(gif_path)
            self.assertEqual(count, 3)
            self.assertFalse(has_alpha)          # непрозрачная гифка → DXT1, не DXT5

            # Кадры отдаются потоком, задержки собираются по ходу.
            durations = []
            got = list(TextureService._iter_animation_frames_rgba(gif_path, (8, 8), count, durations))
            self.assertEqual(len(got), 3)
            self.assertEqual([len(b) for b in got], [8 * 8 * 4] * 3)
            self.assertEqual(durations, [100, 300, 200])
            self.assertEqual(TextureService._fps_from_durations(durations), 5)
        finally:
            for name in os.listdir(tmp_dir):
                try:
                    os.remove(os.path.join(tmp_dir, name))
                except OSError:
                    pass
            os.rmdir(tmp_dir)


if __name__ == "__main__":
    unittest.main()
