import tempfile
import unittest
from pathlib import Path

from src.services.tf2_paths import TF2Paths, build_hat_mdl_candidates


class BuildHatMdlCandidatesTests(unittest.TestCase):
    def test_expands_percent_s_to_all_classes(self):
        out = build_hat_mdl_candidates("models/player/items/all_class/foo_%s.mdl")
        self.assertIn("models/player/items/all_class/foo_heavy.mdl", out)
        self.assertIn("models/player/items/all_class/foo_spy.mdl", out)
        self.assertIn("models/workshop/player/items/all_class/foo_heavy.mdl", out)
        self.assertIn("models/workshop_partner/player/items/all_class/foo_scout.mdl", out)

    def test_workshop_variants_for_plain_path(self):
        out = build_hat_mdl_candidates("models/player/items/engineer/hat.mdl")
        self.assertEqual(out[0], "models/player/items/engineer/hat.mdl")
        self.assertIn("models/workshop_partner/player/items/engineer/hat.mdl", out)
        self.assertIn("models/workshop/player/items/engineer/hat.mdl", out)

    def test_class_suffix_expansion(self):
        out = build_hat_mdl_candidates("models/player/items/engineer/hat_heavy.mdl")
        self.assertTrue(any(p.endswith("hat_scout.mdl") for p in out))
        self.assertTrue(any(p.endswith("hat_demoman.mdl") for p in out))

    def test_lowercased_and_backslashes_normalized(self):
        out = build_hat_mdl_candidates("Models\\Player\\Items\\X\\Hat.mdl")
        self.assertEqual(out[0], "models/player/items/x/hat.mdl")

    def test_no_duplicates(self):
        out = build_hat_mdl_candidates("models/player/items/all_class/foo_%s.mdl")
        self.assertEqual(len(out), len(set(out)))


class TF2PathsTests(unittest.TestCase):
    def test_resolve_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "missing"
            with self.assertRaises(FileNotFoundError):
                TF2Paths.resolve(str(base))

    def test_resolve_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "bin").mkdir()
            (base / "tf").mkdir()
            (base / "bin" / "studiomdl.exe").write_text("x", encoding="utf-8")
            (base / "tf" / "tf2_misc_dir.vpk").write_text("x", encoding="utf-8")
            studiomdl, misc_vpk, tf_dir = TF2Paths.resolve(str(base))
            self.assertTrue(studiomdl.endswith("studiomdl.exe"))
            self.assertTrue(misc_vpk.endswith("tf2_misc_dir.vpk"))
            self.assertTrue(tf_dir.endswith("tf"))

    def test_resolve_textures_vpk(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "tf").mkdir()
            (base / "tf" / "tf2_textures_dir.vpk").write_text("x", encoding="utf-8")
            result = TF2Paths.resolve_textures_vpk(str(base))
            self.assertTrue(result.endswith("tf2_textures_dir.vpk"))

    def test_check_crowbar(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            crowbar = base / "CrowbarCommandLineDecomp.exe"
            crowbar.write_text("x", encoding="utf-8")
            TF2Paths.CROWBAR_PATH = str(crowbar)
            exists, error = TF2Paths.check_crowbar()
            self.assertTrue(exists)
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
