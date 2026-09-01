"""Тесты чистой модели режима превью (взаимоисключение + переходы)."""

import unittest

from src.domain.preview.mode import PreviewMode, PreviewState


class PreviewStateTests(unittest.TestCase):
    def test_default_is_weapon(self):
        s = PreviewState()
        self.assertEqual(s.mode, PreviewMode.WEAPON)
        self.assertFalse(s.is_custom)

    def test_enter_is_mutually_exclusive(self):
        s = PreviewState()
        s.enter(PreviewMode.CUSTOM)
        self.assertTrue(s.is_custom)
        # все остальные — погашены автоматически
        self.assertNotEqual(s.mode, PreviewMode.WEAPON)
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
        self.assertEqual(s.mode, PreviewMode.WEAPON)
        self.assertFalse(s.is_custom)

    def test_enter_rejects_non_mode(self):
        s = PreviewState()
        with self.assertRaises(TypeError):
            s.enter("custom")

    def test_skybox_mode_mutually_exclusive(self):
        s = PreviewState()
        s.enter(PreviewMode.SKYBOX)
        self.assertTrue(s.is_skybox)
        self.assertNotEqual(s.mode, PreviewMode.WEAPON)
        self.assertFalse(s.is_crithit)
        s.enter(PreviewMode.CRITHIT)
        self.assertFalse(s.is_skybox)    # не «залип»
        s.enter(PreviewMode.SKYBOX)
        s.reset()
        self.assertEqual(s.mode, PreviewMode.WEAPON)
        self.assertFalse(s.is_skybox)


if __name__ == "__main__":
    unittest.main()
