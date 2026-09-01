"""
Источник VMT для правки: ключ предмета и политика сохранения.

Извлечение из игровых VPK здесь не гоняется (нужна установленная игра) —
проверяется то, что решает сама служба.
"""

import unittest

from src.services import vmt_source_service as vmt

_VALID = '"VertexLitGeneric"\n{\n\t"$basetexture" "models/x"\n}\n'


class ResolveTargetTests(unittest.TestCase):
    """Ключ правки у каждого вида предмета свой — по нему её потом ищут."""

    def test_weapon_key_comes_from_the_mode(self):
        self.assertEqual(vmt.resolve_target('scout_c_scattergun'),
                         ('c_scattergun', 'c_scattergun'))

    def test_hat_key_is_a_normalized_mdl_path(self):
        key, _name = vmt.resolve_target('hat', hat_mdl='Models/Player/Items/A.mdl')
        self.assertEqual(key, 'models/player/items/a.mdl')

    def test_hat_without_a_model_has_no_target(self):
        self.assertIsNone(vmt.resolve_target('hat'))

    def test_hands_point_at_the_arm_model(self):
        from src.data.player_hands import HAND_MODES, HAND_MODE_KEYS
        mode = next(iter(HAND_MODE_KEYS))
        self.assertEqual(vmt.resolve_target(mode)[0],
                         HAND_MODES[mode]['arm_model'])

    def test_no_mode_no_target(self):
        self.assertIsNone(vmt.resolve_target(''))


class SaveEditTests(unittest.TestCase):
    """Что происходит при сохранении правки."""

    def test_broken_syntax_is_refused(self):
        """Сломанный VMT в игре даёт невидимый материал — не сохраняем."""
        ok, error, _content = vmt.save_edit('', _VALID + '\n{ "oops"')
        self.assertFalse(ok)
        self.assertTrue(error)

    def test_watermark_is_added_once(self):
        ok, _error, once = vmt.save_edit('', _VALID)
        self.assertTrue(ok)
        self.assertEqual(once.count(vmt.WATERMARK), 1)
        _ok, _error, twice = vmt.save_edit('', once)
        self.assertEqual(twice.count(vmt.WATERMARK), 1)

    def test_original_is_backed_up_only_the_first_time(self):
        """Иначе «вернуть как в игре» после второй правки вернуло бы первую."""
        from src.services.edited_vmt_service import EditedVMTService

        key = 'test_vmt_source_service_key'
        try:
            vmt.save_edit(key, _VALID, original=_VALID)
            first = EditedVMTService.read_original_backup(key)
            edited = _VALID.replace('models/x', 'models/y')
            vmt.save_edit(key, edited, original=edited)
            self.assertEqual(EditedVMTService.read_original_backup(key), first)
        finally:
            EditedVMTService.delete_edited_vmt(key)


if __name__ == "__main__":
    unittest.main()
