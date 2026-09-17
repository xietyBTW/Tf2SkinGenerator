"""
Каталог косметики: «куда надевается» и ранжированный поиск.

Раньше поиск был подстрокой где угодно без порядка («очки» находило
«Ботиночки» наравне с очками), а 1822 предмета шли одной алфавитной стеной.
"""

import unittest

from src.app.api import _hat_rank, _hat_suggest
from src.data.hats_parser import HatItem, region_group


def _hat(name, regions=(), internal='', prefab=''):
    return HatItem(defindex='1', name=name, internal_name=internal or name,
                   mdl_path=f'models/player/items/{name}.mdl',
                   classes=['scout'], slot='head', regions=list(regions),
                   prefab=prefab)


class RegionTests(unittest.TestCase):
    def test_game_regions_fold_into_groups(self):
        self.assertEqual(region_group('hat'), 'head')
        self.assertEqual(region_group('pyro_head_replacement'), 'head')
        self.assertEqual(region_group('glasses'), 'face')
        self.assertEqual(region_group('sniper_vest'), 'body')
        self.assertEqual(region_group('disconnected_floating_item'), 'other')

    def test_item_takes_the_first_group_in_facet_order(self):
        """Шлем с очками — голова, а не лицо; без областей — прочее."""
        self.assertEqual(_hat('Helm', ['glasses', 'hat']).region, 'head')
        self.assertEqual(_hat('Beard', ['beard']).region, 'face')
        self.assertEqual(_hat('Old', []).region, 'other')
        self.assertEqual(_hat('Medal', [], prefab='tournament_medal').region, 'medal')


class RankTests(unittest.TestCase):
    def test_whole_then_prefix_then_word_start_then_substring(self):
        self.assertEqual(_hat_rank(_hat('Очки Гейба'), ['очки', 'гейба'], ''), 0)
        self.assertEqual(_hat_rank(_hat('Очки Гейба'), ['очки'], ''), 1)
        self.assertEqual(_hat_rank(_hat('Антарктические очки'), ['очки'], ''), 2)
        self.assertEqual(_hat_rank(_hat('Ботиночки'), ['очки'], ''), 3)
        self.assertIsNone(_hat_rank(_hat('Шапка'), ['очки'], ''))

    def test_english_name_counts_in_russian_ui(self):
        self.assertEqual(_hat_rank(_hat('Очки Гейба'), ['glasses'], "Gabe's Glasses"), 2)

    def test_yo_and_case_do_not_matter(self):
        self.assertEqual(_hat_rank(_hat('Ёлочная шляпа'), ['елочная'], ''), 1)

    def test_suggestions_for_a_typo(self):
        got = _hat_suggest(['fedra'], ['Fancy Fedora', 'Bonk Helm'], {})
        self.assertEqual(got, ['Fancy Fedora'])


if __name__ == '__main__':
    unittest.main()
