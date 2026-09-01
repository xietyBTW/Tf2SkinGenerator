"""
Дерево систем PCF → вид для каталога.

Вложенность в PCF настоящая: система тянет детей по имени. Каталог показывает
её деревом, а не списком — в class_fx.pcf 104 системы при 43 корнях, и плоский
список читается как свалка. Один ребёнок может висеть у нескольких родителей,
и тогда он появляется под каждым: так оно в файле и есть.
"""

import unittest

from src.app.session import _tree_nodes


class TreeNodesTests(unittest.TestCase):
    def test_children_stay_children(self):
        tree = [('root', [('kid', [('grandkid', [])])])]
        self.assertEqual(_tree_nodes(tree), [
            {'key': 'root', 'name': 'root', 'kids': [
                {'key': 'kid', 'name': 'kid', 'kids': [
                    {'key': 'grandkid', 'name': 'grandkid', 'kids': []},
                ]},
            ]},
        ])

    def test_roots_keep_their_order(self):
        tree = [('a', [('a1', [])]), ('b', [])]
        self.assertEqual([n['key'] for n in _tree_nodes(tree)], ['a', 'b'])

    def test_shared_child_appears_under_each_parent(self):
        tree = [('a', [('common', [])]), ('b', [('common', [])])]
        nodes = _tree_nodes(tree)
        self.assertEqual([k['key'] for k in nodes[0]['kids']], ['common'])
        self.assertEqual([k['key'] for k in nodes[1]['kids']], ['common'])

    def test_leaf_has_an_empty_list_not_none(self):
        """Фронт спрашивает kids.length — None уронил бы отрисовку."""
        self.assertEqual(_tree_nodes([('one', [])])[0]['kids'], [])

    def test_empty(self):
        self.assertEqual(_tree_nodes([]), [])


if __name__ == '__main__':
    unittest.main()
