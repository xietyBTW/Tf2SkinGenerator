"""Тесты чистой модели режима превью (взаимоисключение + переходы)."""

import unittest

from src.ui.preview_mode import PreviewMode, PreviewState


class PreviewStateTests(unittest.TestCase):
    def test_default_is_weapon(self):
        s = PreviewState()
        self.assertTrue(s.is_weapon)
        self.assertFalse(s.is_custom)
        self.assertFalse(s.is_special)

    def test_enter_is_mutually_exclusive(self):
        s = PreviewState()
        s.enter(PreviewMode.CUSTOM)
        self.assertTrue(s.is_custom)
        # все остальные — погашены автоматически
        self.assertFalse(s.is_weapon)
        self.assertFalse(s.is_spy_masks)
        self.assertFalse(s.is_crithit)
        self.assertFalse(s.is_death)

    def test_switching_modes_clears_previous(self):
        s = PreviewState()
        s.enter(PreviewMode.CRITHIT)
        self.assertTrue(s.is_crithit)
        s.enter(PreviewMode.SPY_MASKS)
        self.assertTrue(s.is_spy_masks)
        self.assertFalse(s.is_crithit)   # критхит не «залип»

    def test_reset_returns_to_weapon(self):
        s = PreviewState()
        s.enter(PreviewMode.CUSTOM)
        s.reset()
        self.assertTrue(s.is_weapon)
        self.assertFalse(s.is_custom)

    def test_is_special(self):
        s = PreviewState()
        s.enter(PreviewMode.CRITHIT)
        self.assertTrue(s.is_special)
        s.enter(PreviewMode.DEATH)
        self.assertTrue(s.is_special)
        s.enter(PreviewMode.CUSTOM)
        self.assertFalse(s.is_special)

    def test_legacy_flags_match_mode(self):
        s = PreviewState()
        s.enter(PreviewMode.CUSTOM)
        self.assertEqual(s.as_legacy_flags(), {
            "_custom_smd_mode": True,
            "_spy_mask_mode": False,
            "_crithit_mode": False,
            "_death_effect_mode": False,
        })
        # ровно один флаг True в любом режиме (или ноль в WEAPON)
        for mode in PreviewMode:
            s.enter(mode)
            self.assertLessEqual(sum(s.as_legacy_flags().values()), 1)

    def test_enter_rejects_non_mode(self):
        s = PreviewState()
        with self.assertRaises(TypeError):
            s.enter("custom")


if __name__ == "__main__":
    unittest.main()
