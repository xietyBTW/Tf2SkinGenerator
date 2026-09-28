"""«Сделать командным»: синяя строка каждой пары скинов, остальное как в игре.

Раскладки — настоящие таблицы скинов моделей TF2 (прочитаны из MDL игры).
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services import qc_skin_parser as q
from src.services.vpk_service import VPKService

SNIPER = ([['c_sniperrifle', 'c_sniperrifle_gold']] * 8
          + [['c_sniperrifle_gold', 'c_sniperrifle_gold']] * 2)


class ForceTeamRowsTests(unittest.TestCase):

    def test_australium_rows_survive(self):
        """Снайперка: BLU-строки 1/3/5/7 синие, золото 8/9 не тронуто."""
        rows = q.force_team_rows(SNIPER, ['c_sniperrifle'])
        self.assertEqual(len(rows), 10)
        for i in (0, 2, 4, 6):
            self.assertEqual(rows[i], ['c_sniperrifle', 'c_sniperrifle_gold'])
        for i in (1, 3, 5, 7):
            self.assertEqual(rows[i], ['c_sniperrifle_blue', 'c_sniperrifle_gold'])
        self.assertEqual(rows[8], SNIPER[8])
        self.assertEqual(rows[9], SNIPER[9])

    def test_result_is_native_team(self):
        """После синтеза раскладка читается командной, как у медигана."""
        lay = q.classify_rows(q.force_team_rows(SNIPER, ['c_sniperrifle']))
        self.assertTrue(q.selector_spec(lay).team)
        self.assertIn('australium', lay.variants)
        self.assertEqual(lay.second_row[0], 'c_sniperrifle_blue')

    def test_four_row_grenade_launcher(self):
        rows = q.force_team_rows(
            [['c_grenadelauncher', 'c_grenadelauncher_gold']] * 2
            + [['c_grenadelauncher_gold', 'c_grenadelauncher_gold']] * 2,
            ['c_grenadelauncher'])
        self.assertEqual(rows[1][0], 'c_grenadelauncher_blue')
        self.assertEqual(rows[2:], [['c_grenadelauncher_gold'] * 2] * 2)

    def test_single_row_gets_blue_pair(self):
        self.assertEqual(q.force_team_rows([['c_shotgun']], ['c_shotgun']),
                         [['c_shotgun'], ['c_shotgun_blue']])

    def test_no_group_uses_mesh_materials(self):
        self.assertEqual(q.force_team_rows([], ['c_pistol']),
                         [['c_pistol'], ['c_pistol_blue']])

    def test_mesh_material_outside_group_becomes_column(self):
        rows = q.force_team_rows([['c_gun'], ['c_gun']], ['c_gun', 'c_gun_scope'])
        self.assertEqual(rows, [['c_gun', 'c_gun_scope'],
                                ['c_gun_blue', 'c_gun_scope_blue']])

    def test_gold_and_blue_names_never_team(self):
        rows = q.force_team_rows(SNIPER, ['c_sniperrifle', 'c_sniperrifle_gold',
                                          'c_sniperrifle_blue'])
        self.assertEqual(rows[1], ['c_sniperrifle_blue', 'c_sniperrifle_gold'])

    def test_native_festive_model_can_be_team(self):
        """Праздничное имя — родной материал модели, а не вариант."""
        self.assertEqual(
            q.force_team_rows([['c_holymackerel_xmas']], ['c_holymackerel_xmas']),
            [['c_holymackerel_xmas'], ['c_holymackerel_xmas_blue']])

    def test_only_australium_counts_as_variant(self):
        self.assertTrue(q.is_australium('c_sniperrifle_gold'))
        self.assertTrue(q.is_australium('c_ambassador_blue_gold'))
        self.assertFalse(q.is_australium('c_wrangler_xmas_blue'))
        self.assertFalse(q.is_australium('c_sniperrifle'))

    def test_style_second_row_refused(self):
        """Кровь тесака — стиль: команду не дописать, не стерев его."""
        cleaver = [['c_sd_cleaver', 'c_sd_cleaver_bloody'],
                   ['c_sd_cleaver_bloody', 'c_sd_cleaver_bloody']]
        self.assertFalse(q.team_pairs_free(cleaver))
        self.assertIsNone(q.force_team_rows(cleaver, ['c_sd_cleaver']))


class ApplyForceTeamQcTests(unittest.TestCase):
    """Сборка правит QC снайперки, не выкидывая золото."""

    def test_qc_keeps_australium(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            rows = '\n'.join('\t{ ' + ' '.join(f'"{m}"' for m in r) + ' }' for r in SNIPER)
            qc = d / 'c_sniperrifle.qc'
            qc.write_text('$modelname "weapons/c_models/c_sniperrifle.mdl"\n'
                          '$texturegroup "skinfamilies"\n{\n' + rows + '\n}\n',
                          encoding='utf-8')
            (d / 'c_sniperrifle.smd').write_text('// smd', encoding='utf-8')
            ctx = SimpleNamespace(decompile_dir=d)
            with patch('src.services.smd_service.SMDService.find_reference_smd',
                       return_value=str(d / 'c_sniperrifle.smd')), \
                 patch('src.services.smd_service.SMDService.ordered_unique_materials',
                       return_value=['c_sniperrifle']):
                VPKService._apply_force_team(True, 'sniper_c_sniperrifle', str(qc),
                                             'c_sniperrifle', ctx)
            out = q.parse_texturegroup_rows(str(qc))
        self.assertEqual(len(out), 10)
        self.assertEqual(out[1], ['c_sniperrifle_blue', 'c_sniperrifle_gold'])
        self.assertEqual(out[9], ['c_sniperrifle_gold', 'c_sniperrifle_gold'])


if __name__ == '__main__':
    unittest.main()
