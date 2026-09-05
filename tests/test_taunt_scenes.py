"""
Насмешка с реквизитом: какой класс её играет и какой последовательностью.

Связку даёт items_game, но имя сцены (.vcd) не всегда совпадает с именем
последовательности в модели анимаций — у транспорта сцена одна на все классы,
а анимации разные. Тест держит правило поиска: точное имя, затем по словам,
затем выверенный случай из OVERRIDES.
"""

from __future__ import annotations

import unittest

from src.data import taunt_scenes


class SequenceNameTests(unittest.TestCase):
    """Как из имени сцены получается имя последовательности."""

    AVAILABLE = [
        'ref', 'taunt_nuke', 'taunt_yeti', 'taunt_chicken',
        'taunt_vehicle_allclass_start', 'taunt_vehicle_allclass_end',
        'taunt_burstchester_scout', 'taunt_burstchester_soldier',
        'taunt_pyro_pool', 'taunt_pyro_pool_end',
    ]

    def test_exact_scene_name_wins(self):
        self.assertEqual(
            taunt_scenes.sequence_name('demo_nuke_bottle', 'taunt_nuke',
                                       'demoman', self.AVAILABLE),
            'taunt_nuke')

    def test_class_suffix_is_tried(self):
        """У всеклассовой насмешки анимация своя на каждый класс."""
        for cls in ('scout', 'soldier'):
            self.assertEqual(
                taunt_scenes.sequence_name('prop', 'taunt_burstchester', cls,
                                           self.AVAILABLE),
                f'taunt_burstchester_{cls}')

    def test_words_match_when_the_name_differs(self):
        """Сцена «taunt_pool_party_intro», анимация «taunt_pyro_pool»."""
        self.assertEqual(
            taunt_scenes.sequence_name('pyro_poolparty', 'taunt_pool_party_intro',
                                       'pyro', self.AVAILABLE),
            'taunt_pyro_pool')

    def test_ending_pieces_lose_to_the_taunt_itself(self):
        """`_end` — это выход из насмешки, показывать надо её саму."""
        found = taunt_scenes.sequence_name('bumpercar', 'taunt_vehicle_allclass',
                                           'scout', self.AVAILABLE)
        self.assertEqual(found, 'taunt_vehicle_allclass_start')

    def test_override_wins_over_the_scene_name(self):
        self.assertIn('bumpercar', taunt_scenes.OVERRIDES)
        self.assertEqual(taunt_scenes.OVERRIDES['bumpercar'],
                         'taunt_vehicle_allclass_start')

    def test_empty_override_means_the_prop_plays_itself(self):
        """У танка водитель сидит неподвижно, а едет сам танк."""
        self.assertEqual(taunt_scenes.OVERRIDES['tank'], '')
        self.assertIsNone(
            taunt_scenes.sequence_name('tank', 'taunt_vehicle_tank', 'soldier',
                                       self.AVAILABLE))

    def test_nothing_matched_is_not_an_error(self):
        self.assertIsNone(
            taunt_scenes.sequence_name('prop', 'taunt_of_which_nobody_knows',
                                       'spy', self.AVAILABLE))


class MotionTests(unittest.TestCase):
    """Насмешка хранится двумя частями: пустой базой и слоем с движением."""

    def _smd(self, rows):
        import tempfile
        from pathlib import Path

        tmp = tempfile.mkdtemp()
        path = Path(tmp) / 'anim.smd'
        body = ['version 1', 'nodes', '  0 "bip_pelvis" -1', 'end',
                'skeleton', 'time 0'] + rows + ['end']
        path.write_text('\n'.join(body), encoding='utf-8')
        return str(path)

    def test_stub_without_offsets_is_not_an_animation(self):
        """У медика в базе ненулевых строк 185 из 17020 — персонаж от такой
        «анимации» складывался в комок."""
        from src.services.taunt_worker import has_motion

        rows = ['  {} 0.000000 0.000000 0.000000 0.000000 0.000000 0.000000'.format(i)
                for i in range(10)]
        self.assertFalse(has_motion(self._smd(rows)))

    def test_real_pose_has_bone_offsets(self):
        from src.services.taunt_worker import has_motion

        rows = ['  {} 0.000000 -4.279888 0.000000 0.045 0.099 0.025'.format(i)
                for i in range(10)]
        self.assertTrue(has_motion(self._smd(rows)))

    def test_missing_file_is_not_an_animation(self):
        from src.services.taunt_worker import has_motion

        self.assertFalse(has_motion('такого-файла-нет.smd'))


class MergeTests(unittest.TestCase):
    """Реквизит надевается на персонажа по именам костей, как EF_BONEMERGE."""

    def _smd(self, names):
        import tempfile
        from pathlib import Path

        nodes = ['  {} "{}" {}'.format(i, name, i - 1)
                 for i, name in enumerate(names)]
        rows = ['  {} 0 0 0 0 0 0'.format(i) for i in range(len(names))]
        body = (['version 1', 'nodes'] + nodes
                + ['end', 'skeleton', 'time 0'] + rows + ['end'])
        path = Path(tempfile.mkdtemp()) / 'ref.smd'
        path.write_text(chr(10).join(body), encoding='utf-8')
        return str(path)

    def test_every_shared_bone_merges(self):
        """Отбор «по твёрдому телу» оставлял одну кость — хват спрятанного
        оружия. У рентгена медика анимация уводит его на полсотни единиц от
        кисти, и снимок улетал вместе с ним."""
        from src.services import viewmodel_animation, viewmodel_pose

        prop = self._smd(['weapon_bone', 'weapon_bone_1', 'joint_hose01',
                          'своя_кость'])
        player = viewmodel_pose.load_rig(
            self._smd(['bip_hand_R', 'weapon_bone', 'weapon_bone_1',
                       'joint_hose01']))
        self.assertEqual(
            viewmodel_animation._shared_bones(prop, player),
            ['joint_hose01', 'weapon_bone', 'weapon_bone_1'])


class HideEventTests(unittest.TestCase):
    """Реквизит виден не весь клип: игра достаёт его событием."""

    def test_pair_of_events_becomes_hidden_ranges(self):
        """Медик лезет за снимком до 23-го кадра и убирает его на 166-м."""
        from src.services.taunt_worker import hidden_ranges

        self.assertEqual(
            hidden_ranges(((0, True), (23, False), (166, True)), 30.0),
            [[0.0, 23 / 30.0], [166 / 30.0, None]])

    def test_lonely_hide_is_about_the_weapon_not_the_prop(self):
        """У обычных насмешек AE_WPN_HIDE прячет ОРУЖИЕ, которого в сцене нет.
        Приняв его за реквизит, мы спрятали бы реквизит на весь клип."""
        from src.services.taunt_worker import hidden_ranges

        self.assertEqual(hidden_ranges(((0, True),), 30.0), [])
        self.assertEqual(hidden_ranges((), 30.0), [])


class ParseTests(unittest.TestCase):
    """Разбор items_game: одна насмешка описывает сразу все свои классы."""

    ITEMS_GAME = '''
"items_game"
{
    "items"
    {
        "1"
        {
            "name" "Taunt: Test"
            "taunt"
            {
                "custom_taunt_scene_per_class"
                {
                    "scout"   "scenes/workshop/player/scout/low/taunt_test.vcd"
                    "soldier" "scenes/workshop/player/soldier/low/taunt_test.vcd"
                }
                "custom_taunt_prop_per_class"
                {
                    "scout"   "models/workshop/player/items/all_class/test/test_scout.mdl"
                    "soldier" "models\\workshop\\player\\items\\all_class\\test\\test_soldier.mdl"
                }
            }
        }
    }
}
'''

    def _parsed(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'items_game.txt'
            path.write_text(self.ITEMS_GAME, encoding='utf-8')
            return taunt_scenes._parse(str(path))

    def test_any_prop_of_the_taunt_leads_to_the_whole_table(self):
        """Выбрали другой класс — сменились и модель реквизита, и сцена."""
        table = self._parsed()
        scout_mdl = 'models/workshop/player/items/all_class/test/test_scout.mdl'
        self.assertIn(scout_mdl, table)
        by_class = table[scout_mdl]
        self.assertEqual(sorted(by_class), ['scout', 'soldier'])
        self.assertEqual(by_class['soldier'][0],
                         'models/workshop/player/items/all_class/test/test_soldier.mdl')
        self.assertEqual(by_class['soldier'][1], 'taunt_test')
        # И наоборот: модель солдата ведёт на ту же таблицу.
        self.assertEqual(table[by_class['soldier'][0]], by_class)

    def test_windows_slashes_are_normalized(self):
        table = self._parsed()
        self.assertTrue(all('\\' not in mdl for mdl in table))


if __name__ == '__main__':
    unittest.main()
