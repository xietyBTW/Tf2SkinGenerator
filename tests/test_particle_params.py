"""
Крутилки простого режима на стороне приложения.

Схема и чтение значений живут в services/simple_params и проверены там; здесь
проверяется то, что добавил слой приложения: форма ответа для страницы и
правила записи — в первую очередь запрет создавать модуль там, где схема это
запрещает. Лишний emit_instantaneously задваивает залп, и молча добавить его
хуже, чем отказать.
"""

import unittest

from src.app.session import AppSession


class _StubService:
    """Служба частиц ровно в том объёме, в каком её зовёт сеанс."""

    def __init__(self, systems):
        self._systems = systems
        self.writes = []
        self.added = []

    def systems_json(self):
        return self._systems

    def ensure_attr(self, system, group, index, attr, attr_type, value):
        self.writes.append((system, group, index, attr, value))
        mods = self._systems[system][group] if group else None
        attrs = self._systems[system]['attrs'] if group is None else mods[index]['attrs']
        attrs[attr] = {'t': attr_type, 'v': value}
        return True

    def set_attr(self, system, group, index, attr, value):
        sysj = self._systems.get(system)
        if sysj is None:
            return False
        attrs = sysj['attrs'] if group is None else sysj[group][index]['attrs']
        if attr not in attrs:
            return False
        attrs[attr]['v'] = value
        self.writes.append((system, group, index, attr, value))
        return True

    def add_module(self, system, group, function_name, root=''):
        self.added.append((group, function_name))
        self._systems[system].setdefault(group, []).append(
            {'functionName': function_name, 'name': function_name, 'attrs': {}})
        return True

    def system_names(self):
        return list(self._systems)

    def materials_json(self, root, cancel_check=None):
        return {}

    def material_names(self):
        return []

    def remove_module(self, system, group, index):
        try:
            self._systems[system][group].pop(int(index))
            return True
        except (KeyError, IndexError):
            return False

    def remove_attr(self, system, group, index, attr):
        sysj = self._systems.get(system)
        if sysj is None:
            return False
        attrs = sysj['attrs'] if group is None else sysj[group][index]['attrs']
        return attrs.pop(attr, None) is not None


def _system(**groups):
    base = {'name': 'sys', 'attrs': {}, 'children': []}
    for g in ('renderers', 'operators', 'initializers', 'emitters',
              'forces', 'constraints'):
        base[g] = groups.get(g, [])
    return base


def _mod(fn, attrs=None):
    return {'functionName': fn, 'name': fn,
            'attrs': {k: {'t': 'float', 'v': v} for k, v in (attrs or {}).items()}}


def _session(systems):
    s = AppSession()
    s.particles = _StubService(systems)
    return s


class ParamsListTests(unittest.TestCase):
    def setUp(self):
        self.s = _session({'sys': _system(
            operators=[_mod('Movement Basic', {'drag': 0.25})])})

    def test_every_param_of_the_schema_is_reported(self):
        from src.services.simple_params import SIMPLE_PARAMS
        self.assertEqual(len(self.s.particle_params('sys')), len(SIMPLE_PARAMS))

    def test_value_comes_from_the_module(self):
        drag = next(p for p in self.s.particle_params('sys') if p['key'] == 'drag')
        self.assertEqual(drag['value'], 0.25)

    def test_missing_module_gives_none_and_a_placeholder(self):
        """None — не «нет значения», а «модуля нет»: поле показывают бледным."""
        life = next(p for p in self.s.particle_params('sys')
                    if p['key'] == 'lifetime')
        self.assertIsNone(life['value'])
        self.assertIsNotNone(life['placeholder'])
        self.assertEqual(life['missing'], [['initializers', 'Lifetime Random']])

    def test_unknown_system_is_empty_not_an_error(self):
        self.assertEqual(self.s.particle_params('нет такой'), [])


class SetParamTests(unittest.TestCase):
    def setUp(self):
        self.s = _session({'sys': _system(
            operators=[_mod('Movement Basic', {'drag': 0.25})])})

    def test_write_reaches_the_service_and_returns_systems(self):
        res = self.s.set_particle_param('sys', 'drag', 0.5)
        self.assertIn('systems', res)
        self.assertEqual(self.s.particles.writes,
                         [('sys', 'operators', 0, 'drag', 0.5)])

    def test_missing_module_is_created_when_the_schema_allows(self):
        self.s.set_particle_param('sys', 'lifetime', [1.0, 2.0])
        self.assertEqual(self.s.particles.added,
                         [('initializers', 'Lifetime Random')])

    def test_emitter_module_is_never_created(self):
        """creatable=False у эмиттеров — добавленный залп звучал бы дважды."""
        res = self.s.set_particle_param('sys', 'spawn_burst', 50)
        self.assertIn('error', res)
        self.assertEqual(self.s.particles.added, [])

    def test_unknown_param_and_system(self):
        self.assertIn('error', self.s.set_particle_param('sys', 'нет', 1))
        self.assertIn('error', self.s.set_particle_param('нет', 'drag', 1))

    def test_without_a_loaded_pcf(self):
        self.assertIn('error', AppSession().set_particle_param('sys', 'drag', 1))


class ExpertModeTests(unittest.TestCase):
    """Экспертный режим показывает файл как есть — но без служебных ключей."""

    def setUp(self):
        self.s = _session({'sys': _system(
            operators=[_mod('Movement Basic', {'drag': 0.25})],
            initializers=[_mod('Lifetime Random', {'lifetime_min': 1.0})])})
        # functionName и name адресуют модуль, а не настраивают его.
        mod = self.s.particles.systems_json()['sys']['operators'][0]
        mod['attrs']['functionname'] = {'t': 'string', 'v': 'Movement Basic'}
        mod['attrs']['id'] = {'t': 'string', 'v': 'x'}

    def _groups(self):
        return {g['group']: g for g in self.s.particle_system('sys')['groups']}

    def test_system_attrs_come_first_as_their_own_block(self):
        groups = self.s.particle_system('sys')['groups']
        self.assertIsNone(groups[0]['group'])
        self.assertEqual(groups[0]['modules'][0]['title'], 'sys')

    def test_modules_are_listed_with_their_attributes(self):
        mod = self._groups()['operators']['modules'][0]
        self.assertEqual(mod['title'], 'Movement Basic')
        self.assertEqual([a['name'] for a in mod['attrs']], ['drag'])

    def test_service_keys_are_not_shown(self):
        names = [a['name'] for a in self._groups()['operators']['modules'][0]['attrs']]
        self.assertNotIn('functionname', names)
        self.assertNotIn('id', names)

    def test_empty_forces_and_constraints_are_skipped(self):
        groups = self._groups()
        self.assertNotIn('forces', groups)
        self.assertNotIn('constraints', groups)
        # А основные группы видны и пустыми — иначе в них нечего добавить.
        self.assertIn('renderers', groups)

    def test_attrs_are_sorted(self):
        self.s.particles.systems_json()['sys']['operators'][0]['attrs'].update(
            {'a_last': {'t': 'float', 'v': 1.0}, 'a_first': {'t': 'float', 'v': 2.0}})
        names = [a['name'] for a in self._groups()['operators']['modules'][0]['attrs']]
        self.assertEqual(names, sorted(names))

    def test_unknown_system_is_empty(self):
        self.assertEqual(self.s.particle_system('нет'), {})

    def test_edit_writes_through_the_service(self):
        res = self.s.set_particle_attr('sys', 'operators', 0, 'drag', 0.9)
        self.assertIn('systems', res)
        self.assertEqual(
            self.s.particles.systems_json()['sys']['operators'][0]['attrs']['drag']['v'],
            0.9)

    def test_edit_of_a_missing_attr_is_an_error_not_a_silent_pass(self):
        res = self.s.set_particle_attr('sys', 'operators', 0, 'нет такого', 1)
        self.assertIn('error', res)


class StructureTests(unittest.TestCase):
    """Правка состава эффекта: модули, параметры, дети."""

    def setUp(self):
        self.s = _session({'sys': _system(
            operators=[_mod('Movement Basic', {'drag': 0.25})]),
            'other': _system()})
        self.s.particles._systems['sys']['children'] = [
            {'delay': 0.0, 'childName': 'other'}]

    def test_every_change_returns_systems_and_tree(self):
        """Каталог слева и свойства справа рисуются одним ответом."""
        res = self.s.add_particle_module('sys', 'forces', 'random force')
        self.assertIn('systems', res)
        self.assertIn('tree', res)
        self.assertTrue(all('kids' in n for n in res['tree']))

    def test_remove_module(self):
        self.s.remove_particle_module('sys', 'operators', 0)
        self.assertEqual(self.s.particles.systems_json()['sys']['operators'], [])

    def test_remove_module_out_of_range_is_an_error(self):
        self.assertIn('error', self.s.remove_particle_module('sys', 'operators', 7))

    def test_children_are_listed_with_their_index(self):
        """Отцепляют по индексу: одна и та же система может висеть дважды."""
        self.assertEqual(self.s.particle_children('sys'),
                         [{'index': 0, 'name': 'other', 'delay': 0.0}])

    def test_children_of_unknown_system(self):
        self.assertEqual(self.s.particle_children('нет'), [])

    def test_without_a_loaded_pcf_every_action_says_so(self):
        empty = AppSession()
        for call in (lambda: empty.add_particle_module('s', 'forces', 'f'),
                     lambda: empty.remove_particle_module('s', 'forces', 0),
                     lambda: empty.remove_particle_attr('s', None, 0, 'a'),
                     lambda: empty.duplicate_particle_system('s', 'x'),
                     lambda: empty.add_particle_layer('s')):
            self.assertIn('error', call())


class CopyPayloadTests(unittest.TestCase):
    """Формат буфера обмена — тот же, что у панели приложения."""

    def setUp(self):
        self.s = _session({'sys': _system(
            operators=[_mod('Movement Basic', {'drag': 0.25})],
            initializers=[_mod('Radius Random', {'radius_min': 1.0})])})
        self.s.particles.systems_json()['sys']['attrs']['radius'] = {
            't': 'float', 'v': 5.0}
        # Служебные ключи адресуют модуль, а не настраивают его.
        self.s.particles.systems_json()['sys']['operators'][0]['attrs'].update(
            {'functionname': {'t': 'string', 'v': 'Movement Basic'},
             'id': {'t': 'string', 'v': 'x'}})

    def test_whole_system_is_marked_full(self):
        """Полный набор при вставке спрашивает, заменять ли систему целиком."""
        payload = self.s.copy_particle_params('sys')['payload']
        self.assertTrue(payload['full'])
        self.assertEqual(payload['attrs'], {'radius': {'t': 'float', 'v': 5.0}})
        self.assertEqual([g for g in payload['modules']],
                         ['operators', 'initializers'])

    def test_single_module_is_not_full(self):
        payload = self.s.copy_particle_params('sys', 'operators', 0)['payload']
        self.assertNotIn('full', payload)
        self.assertEqual(list(payload['modules']), ['operators'])
        self.assertEqual(payload['modules']['operators'][0][0], 'Movement Basic')

    def test_service_keys_are_not_copied(self):
        payload = self.s.copy_particle_params('sys', 'operators', 0)['payload']
        attrs = payload['modules']['operators'][0][1]
        self.assertEqual(list(attrs), ['drag'])

    def test_single_attribute_of_a_module(self):
        """Самый частый случай: перенести одну настройку, не трогая остального."""
        payload = self.s.copy_particle_params(
            'sys', 'operators', 0, 'drag')['payload']
        self.assertEqual(payload['modules']['operators'],
                         [['Movement Basic', {'drag': {'t': 'float', 'v': 0.25}}]])
        self.assertEqual(payload['attrs'], {})
        self.assertNotIn('full', payload)

    def test_single_attribute_of_the_system(self):
        payload = self.s.copy_particle_params('sys', None, None, 'radius')['payload']
        self.assertEqual(payload['attrs'], {'radius': {'t': 'float', 'v': 5.0}})
        self.assertEqual(payload['modules'], {})

    def test_whole_group(self):
        self.s.particles.systems_json()['sys']['operators'].append(
            _mod('Radius Scale', {'radius_start_scale': 1.0}))
        payload = self.s.copy_particle_params('sys', 'operators')['payload']
        self.assertEqual([m[0] for m in payload['modules']['operators']],
                         ['Movement Basic', 'Radius Scale'])

    def test_unknown_system_and_module(self):
        self.assertIn('error', self.s.copy_particle_params('нет'))
        self.assertIn('error', self.s.copy_particle_params('sys', 'operators', 9))
        self.assertIn('error',
                      self.s.copy_particle_params('sys', 'operators', 0, 'нет'))
        self.assertIn('error', self.s.copy_particle_params('sys', 'forces'))


class _HistoryService(_StubService):
    """Служба со снимками: снимок — копия систем, восстановление — обратно."""

    def snapshot(self):
        import copy
        return copy.deepcopy(self._systems)

    def restore(self, snap):
        import copy
        self._systems.clear()
        self._systems.update(copy.deepcopy(snap))
        return True


class HistoryTests(unittest.TestCase):
    """
    Отмена правок снимками.

    Снимок покрывает и будущие операции: забыть «откат» для новой правки
    невозможно, чего не даёт набор обратимых команд.
    """

    def setUp(self):
        self.s = AppSession()
        self.s.particles = _HistoryService({'sys': _system(
            operators=[_mod('Movement Basic', {'drag': 0.25})])})
        self.s._history_reset()

    def _drag(self):
        return (self.s.particles.systems_json()['sys']['operators'][0]
                ['attrs']['drag']['v'])

    def test_after_load_there_is_nothing_to_undo(self):
        self.assertEqual(self.s.particle_history(),
                         {'undo': False, 'redo': False})

    def test_edit_then_undo_and_redo(self):
        self.s.set_particle_attr('sys', 'operators', 0, 'drag', 0.9)
        self.assertEqual(self._drag(), 0.9)
        self.assertTrue(self.s.particle_history()['undo'])

        self.s.undo_particles(-1)
        self.assertEqual(self._drag(), 0.25)
        self.assertTrue(self.s.particle_history()['redo'])

        self.s.undo_particles(1)
        self.assertEqual(self._drag(), 0.9)

    def test_a_new_edit_drops_the_redo_branch(self):
        self.s.set_particle_attr('sys', 'operators', 0, 'drag', 0.9)
        self.s.undo_particles(-1)
        self.s.set_particle_attr('sys', 'operators', 0, 'drag', 0.5)
        self.assertFalse(self.s.particle_history()['redo'])

    def test_undo_itself_is_not_an_edit(self):
        """Иначе откат добавлял бы снимок и возврат стал бы недостижим."""
        self.s.set_particle_attr('sys', 'operators', 0, 'drag', 0.9)
        before = len(self.s._particle_history)
        self.s.undo_particles(-1)
        self.assertEqual(len(self.s._particle_history), before)

    def test_beyond_the_edge_is_an_error(self):
        self.assertIn('error', self.s.undo_particles(-1))
        self.assertIn('error', self.s.undo_particles(1))

    def test_history_is_capped(self):
        """Снимок — копия всего дерева; помним ограниченное число шагов."""
        for i in range(self.s.HISTORY_LIMIT + 10):
            self.s.set_particle_attr('sys', 'operators', 0, 'drag', i / 100)
        self.assertEqual(len(self.s._particle_history), self.s.HISTORY_LIMIT)

    def test_without_a_loaded_pcf(self):
        self.assertIn('error', AppSession().undo_particles(-1))


class ControlPointTests(unittest.TestCase):
    """Какие контрольные точки нужны эффекту.

    В игре их выставляет код (где оружие, какого цвета килстрик), в превью —
    человек. Без подсказки узнать, что эффекту важна CP 9, можно только
    вычитав это в дереве свойств.
    """

    def test_points_of_the_effect_and_its_children(self):
        s = _session({'root': _system(operators=[
            _mod('Movement Lock to Control Point')]), 'kid': _system()})
        systems = s.particles.systems_json()
        systems['root']['operators'][0]['attrs']['control_point_number'] = {
            't': 'integer', 'v': 9}
        systems['root']['children'] = [{'delay': 0, 'childName': 'kid'}]
        systems['kid']['initializers'] = [_mod('Position Within Sphere Random')]
        systems['kid']['initializers'][0]['attrs']['control_point_number'] = {
            't': 'integer', 'v': 3}

        used = s.particle_control_points('root')['used']
        self.assertIn(9, used)
        self.assertIn(3, used)

    def test_unknown_system_and_no_pcf(self):
        s = _session({'sys': _system()})
        self.assertEqual(s.particle_control_points('нет')['used'], [])
        self.assertEqual(AppSession().particle_control_points('sys')['used'], [])


class _MaterialService(_StubService):
    """Служба с материалами: их картинки и признак своей текстуры."""

    def __init__(self, systems, materials, custom=()):
        super().__init__(systems)
        self._materials = materials
        self._custom = set(custom)
        self.reset_calls = []

    def material_names(self):
        return list(self._materials)

    def materials_json(self, root, cancel_check=None):
        return self._materials

    def is_custom_material(self, name):
        return name in self._custom

    def reset_material_texture(self, name):
        self.reset_calls.append(name)
        return 'file.vtf' if name in self._custom else None

    def use_texture_colors(self, system):
        return 3


class MaterialTests(unittest.TestCase):
    """Карточки текстур эффекта."""

    def setUp(self):
        self.s = AppSession()
        self.s.particles = _MaterialService(
            {'sys': _system()},
            {'effects/glow.vmt': {'dataUrl': 'data:image/png;base64,x',
                                  'width': 128, 'height': 128, 'sheet': None},
             'particle/smoke.vmt': {'dataUrl': 'data:image/png;base64,y',
                                    'width': 1024, 'height': 256,
                                    'sheet': {'frames': 8}}},
            custom=['effects/glow.vmt'])

    def test_only_the_materials_of_the_chosen_effect(self):
        """В PCF десятки систем; чужая карточка предлагала бы заменить не то."""
        svc = self.s.particles
        svc._systems['root'] = _system()
        svc._systems['root']['attrs']['material'] = {
            't': 'string', 'v': 'effects/glow.vmt'}
        svc._systems['root']['children'] = [{'delay': 0, 'childName': 'kid'}]
        svc._systems['kid'] = _system()
        svc._systems['kid']['attrs']['material'] = {
            't': 'string', 'v': 'particle/smoke.vmt'}
        svc._systems['чужая'] = _system()
        svc._systems['чужая']['attrs']['material'] = {
            't': 'string', 'v': 'effects/other.vmt'}
        svc._materials['effects/other.vmt'] = {'dataUrl': 'z'}

        names = [c['name'] for c in self.s.particle_materials('root')]
        self.assertEqual(names, ['effects/glow.vmt', 'particle/smoke.vmt'])
        # Без системы — весь файл: так материалы смотрят до выбора эффекта.
        self.assertEqual(len(self.s.particle_materials()), 3)

    def test_shared_child_is_not_listed_twice(self):
        svc = self.s.particles
        svc._systems['root'] = _system()
        svc._systems['root']['attrs']['material'] = {
            't': 'string', 'v': 'effects/glow.vmt'}
        svc._systems['root']['children'] = [{'delay': 0, 'childName': 'kid'},
                                            {'delay': 0, 'childName': 'kid'}]
        svc._systems['kid'] = _system()
        svc._systems['kid']['attrs']['material'] = {
            't': 'string', 'v': 'effects/glow.vmt'}
        self.assertEqual([c['name'] for c in self.s.particle_materials('root')],
                         ['effects/glow.vmt'])

    def test_cycle_in_children_does_not_hang(self):
        """Ребёнок может ссылаться назад — обход обязан это пережить."""
        svc = self.s.particles
        svc._systems['a'] = _system()
        svc._systems['a']['children'] = [{'delay': 0, 'childName': 'b'}]
        svc._systems['b'] = _system()
        svc._systems['b']['children'] = [{'delay': 0, 'childName': 'a'}]
        self.assertEqual(self.s.particle_materials('a'), [])

    def test_cards_carry_size_sheet_and_custom_flag(self):
        cards = {c['name']: c for c in self.s.particle_materials()}
        self.assertEqual(cards['effects/glow.vmt']['width'], 128)
        self.assertTrue(cards['effects/glow.vmt']['custom'])
        # Покадровая анимация: об этом предупреждают ДО замены картинки.
        self.assertTrue(cards['particle/smoke.vmt']['sheet'])
        self.assertFalse(cards['effects/glow.vmt']['sheet'])

    def test_material_without_a_picture_still_gets_a_card(self):
        """Текстура могла не найтись — карточка нужна всё равно, её правят."""
        self.s.particles._materials['effects/none.vmt'] = {}
        cards = {c['name']: c for c in self.s.particle_materials()}
        self.assertEqual(cards['effects/none.vmt']['dataUrl'], '')

    def test_reset_of_a_game_texture_is_an_error(self):
        self.assertIn('error',
                      self.s.reset_particle_texture('particle/smoke.vmt'))
        self.assertIn('systems',
                      self.s.reset_particle_texture('effects/glow.vmt'))

    def test_natural_colors_report_how_many_modules_went(self):
        res = self.s.use_particle_texture_colors('sys')
        self.assertEqual(res['removed'], 3)
        self.assertIn('materials', res)

    def test_without_a_loaded_pcf(self):
        empty = AppSession()
        self.assertEqual(empty.particle_materials(), [])
        self.assertIn('error', empty.reset_particle_texture('x'))
        self.assertIn('error', empty.use_particle_texture_colors('sys'))


if __name__ == '__main__':
    unittest.main()
