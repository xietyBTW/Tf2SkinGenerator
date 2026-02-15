import unittest

from src.domain.models.build_config import BuildConfig


class BuildConfigTests(unittest.TestCase):
    def test_to_dict_and_from_dict(self):
        config = BuildConfig(
            image_path="img.png",
            mode="scout_c_scattergun",
            filename="out.vpk",
            size=(512, 512),
            format_type="DXT1",
            flags=["flag"],
            vtf_options={"a": 1},
            tf2_root_dir="C:/TF2",
            export_folder="export",
            keep_temp_on_error=True,
            debug_mode=True,
            replace_model_enabled=True,
            draw_uv_layout=True,
            language="ru",
            custom_vtf_path="custom.vtf",
        )
        data = config.to_dict()
        restored = BuildConfig.from_dict(data)
        self.assertEqual(restored, config)


if __name__ == "__main__":
    unittest.main()
