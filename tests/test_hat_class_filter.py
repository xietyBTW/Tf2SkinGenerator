"""
Фильтр косметики по классу, включая «All-Class».

Мультиклассовая косметика (пустой список классов или все девять) под фильтром
конкретного класса не показывается — иначе список Скаута состоял бы наполовину
из всеклассовых шляп. У неё свой фильтр, и раньше он молча давал пустой список.
"""

import unittest

from src.data.hats_parser import HatItem


def _hat(name, classes):
    return HatItem(defindex='1', name=name, internal_name=name,
                   mdl_path=f'models/player/items/{name}.mdl',
                   classes=classes, slot='head')


ВСЕ_КЛАССЫ = ['scout', 'soldier', 'pyro', 'demoman', 'heavy',
              'engineer', 'medic', 'sniper', 'spy']


class ClassFilterTests(unittest.TestCase):
    def setUp(self):
        self.scout = _hat('Bonk Leadwear', ['scout'])
        self.любой = _hat('Graybanns', [])
        self.девять = _hat('Battery Canteens', ВСЕ_КЛАССЫ)

    def test_all_shows_everything(self):
        for h in (self.scout, self.любой, self.девять):
            self.assertTrue(h.matches([], 'all'), h.name)

    def test_class_filter_excludes_multiclass(self):
        self.assertTrue(self.scout.matches([], 'scout'))
        self.assertFalse(self.любой.matches([], 'scout'))
        self.assertFalse(self.девять.matches([], 'scout'))

    def test_all_class_filter_shows_only_multiclass(self):
        self.assertTrue(self.любой.matches([], 'All-Class'))
        self.assertTrue(self.девять.matches([], 'All-Class'))
        self.assertFalse(self.scout.matches([], 'All-Class'))

    def test_all_class_spelling(self):
        """Ключ приходит из данных оружия («All-Class»); подчёркивание тоже."""
        for написание in ('All-Class', 'all-class', 'all_class'):
            self.assertTrue(self.любой.matches([], написание), написание)

    def test_search_still_applies_inside_all_class(self):
        self.assertTrue(self.любой.matches(['gray'], 'All-Class'))
        self.assertFalse(self.любой.matches(['bonk'], 'All-Class'))

    def test_search_without_class_filter(self):
        self.assertTrue(self.scout.matches(['bonk', 'lead'], None))
        self.assertFalse(self.scout.matches(['bonk', 'нет'], None))


if __name__ == '__main__':
    unittest.main()
