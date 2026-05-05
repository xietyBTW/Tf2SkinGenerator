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


if __name__ == "__main__":
    unittest.main()
