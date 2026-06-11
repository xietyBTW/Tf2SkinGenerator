import unittest

from src.data.texture_overrides import effective_settings, override_badge


class EffectiveSettingsTests(unittest.TestCase):
    GLOBAL = {'size': (512, 512), 'format': 'DXT1', 'flags': [], 'options': {}}

    def test_no_override_returns_global_copy(self):
        eff = effective_settings(self.GLOBAL, None)
        self.assertEqual(eff, self.GLOBAL)
        self.assertIsNot(eff, self.GLOBAL)   # копия, не тот же объект

    def test_empty_override_returns_global(self):
        self.assertEqual(effective_settings(self.GLOBAL, {}), self.GLOBAL)

    def test_full_override_applied(self):
        ov = {'size': (1024, 1024), 'format': 'DXT5',
              'flags': ['CLAMPS'], 'options': {'normal': True}}
        eff = effective_settings(self.GLOBAL, ov)
        self.assertEqual(eff['size'], (1024, 1024))
        self.assertEqual(eff['format'], 'DXT5')
        self.assertEqual(eff['flags'], ['CLAMPS'])
        self.assertEqual(eff['options'], {'normal': True})

    def test_partial_override_inherits_global(self):
        eff = effective_settings(self.GLOBAL, {'size': (256, 256)})
        self.assertEqual(eff['size'], (256, 256))
        self.assertEqual(eff['format'], 'DXT1')   # формат — глобальный

    def test_none_value_in_override_ignored(self):
        eff = effective_settings(self.GLOBAL, {'format': None})
        self.assertEqual(eff['format'], 'DXT1')

    def test_global_not_mutated(self):
        effective_settings(self.GLOBAL, {'format': 'DXT5'})
        self.assertEqual(self.GLOBAL['format'], 'DXT1')


class OverrideBadgeTests(unittest.TestCase):
    GLOBAL = {'size': (512, 512), 'format': 'DXT1', 'flags': [], 'options': {}}

    def test_empty_when_no_override(self):
        self.assertEqual(override_badge(None, self.GLOBAL), '')
        self.assertEqual(override_badge({}, self.GLOBAL), '')

    def test_shows_size_and_format(self):
        ov = {'size': (1024, 1024), 'format': 'DXT5'}
        self.assertEqual(override_badge(ov, self.GLOBAL), '1024 · DXT5')


if __name__ == "__main__":
    unittest.main()
