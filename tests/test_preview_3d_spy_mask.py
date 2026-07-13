"""Тест: маска маскировки шпиона не попадает в bodygroup'ы превью ТЕЛА.

Маска — отдельная секция (SPY_MASK_MODE_KEY); в превью тела (mode="spy_body")
её быть не должно, хотя в QC она объявлена как $bodygroup.
"""

import unittest

from src.services.preview_3d_worker import Preview3DWorker


class StripSpyDisguiseMaskTests(unittest.TestCase):
    _SMDS = [
        "/decomp/spy_reference.smd",
        "/decomp/spy_mask.smd",
        "/decomp/spy_head_bodygroup.smd",
    ]

    def test_spy_body_removes_mask(self):
        kept = Preview3DWorker._strip_spy_disguise_mask(self._SMDS, "spy_body")
        self.assertNotIn("/decomp/spy_mask.smd", kept)
        self.assertIn("/decomp/spy_reference.smd", kept)
        self.assertIn("/decomp/spy_head_bodygroup.smd", kept)

    def test_other_modes_keep_everything(self):
        # Для оружия/рук/прочих режимов список не меняется.
        for mode in ("scout_c_scattergun", "spy_masks", "hat", "engineer_arms"):
            kept = Preview3DWorker._strip_spy_disguise_mask(self._SMDS, mode)
            self.assertEqual(kept, self._SMDS, f"mode={mode} не должен фильтровать")

    def test_case_insensitive(self):
        kept = Preview3DWorker._strip_spy_disguise_mask(
            ["/d/Spy_MASK.smd", "/d/body.smd"], "spy_body")
        self.assertEqual(kept, ["/d/body.smd"])

    def test_no_mask_present_is_noop(self):
        smds = ["/d/spy_reference.smd", "/d/spy_head_bodygroup.smd"]
        self.assertEqual(
            Preview3DWorker._strip_spy_disguise_mask(smds, "spy_body"), smds)


if __name__ == "__main__":
    unittest.main()
