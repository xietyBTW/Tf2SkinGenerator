"""
Тесты прикладного API (src/app/api.py) — того, что вызывает представление.

Смысл: правила «что показывать» должны жить в Python и не переписываться
заново при замене интерфейса. Условия сверены с
settings_panel.apply_mode_restrictions и preview_panel._update_*_visibility,
матрица — во frontend/CONTROLS.md.
"""

import unittest

from src.app import api


class CatalogueTests(unittest.TestCase):
    def test_categories_match_the_app(self):
        keys = [c['key'] for c in api.categories('ru')]
        self.assertEqual(keys, list(api.CATEGORY_KEYS))
        # Названия берутся из переводов, а не из ключей.
        names = {c['key']: c['name'] for c in api.categories('ru')}
        self.assertEqual(names['weapon'], 'Оружие')

    def test_weapon_types_are_per_class(self):
        """Часы есть у шпиона и нет у скаута — список строится по данным класса."""
        scout = {t['key'] for t in api.weapon_types('Scout')}
        spy = {t['key'] for t in api.weapon_types('Spy')}
        self.assertNotIn('Watch', scout)
        self.assertIn('Watch', spy)

    def test_types_without_a_class_cover_every_slot(self):
        """Фильтр по типу должен работать сам по себе, не требуя сперва класс."""
        keys = [t['key'] for t in api.weapon_types()]
        self.assertEqual(keys, ['Primary', 'Secondary', 'Melee', 'Watch', 'PDA'])

    def test_type_filter_works_across_classes(self):
        melee = api.items('weapon', None, 'Melee')
        self.assertGreater(len(melee), len(api.items('weapon', 'Scout', 'Melee')))
        self.assertTrue(all(i['type'] == 'Melee' for i in melee))

    def test_type_absent_in_a_class_gives_empty_list(self):
        """У скаута часов нет — фильтр обязан вернуть пусто, а не всё подряд."""
        self.assertEqual(api.items('weapon', 'Scout', 'Watch'), [])

    def test_weapon_items_carry_class_and_mode(self):
        items = api.items('weapon', 'Scout', 'Primary')
        keys = {i['key'] for i in items}
        self.assertIn('c_scattergun', keys)
        one = next(i for i in items if i['key'] == 'c_scattergun')
        self.assertEqual(one['cls'], 'Scout')
        # Режим — «класс_ключ», как его строит MainWindow. Просто ключ не
        # годится: weapon_key_from_mode отрезал бы первый сегмент и модель
        # искалась бы по «scattergun».
        self.assertEqual(one['mode'], 'scout_c_scattergun')
        from src.data.weapons import weapon_key_from_mode
        self.assertEqual(weapon_key_from_mode(one['mode']), 'c_scattergun')

    def test_empty_filters_mean_everything(self):
        self.assertGreater(len(api.items('weapon')),
                           len(api.items('weapon', 'Scout')))

    def test_character_parts_build_app_mode_keys(self):
        """Ключ режима собирается как в приложении: класс_часть."""
        modes = {i['mode'] for i in api.items('character', 'Engineer')}
        self.assertIn('engineer_body', modes)
        self.assertIn('engineer_hands', modes)

    def test_unknown_category_is_empty_not_an_error(self):
        self.assertEqual(api.items('такой-категории-нет'), [])

    def test_simple_categories_are_listed(self):
        """Снаряды, пикапы и реквизит — те же таблицы, что у приложения."""
        from src.data.simple_models import SIMPLE_MODEL_CATEGORIES
        for category, simple in SIMPLE_MODEL_CATEGORIES.items():
            items = api.items(category)
            self.assertEqual(len(items), len(simple.table), category)
            # Режим — «префикс + ключ»: по нему находится MDL, просто ключ
            # не годится (weapon_key_from_mode отрезает первый сегмент).
            self.assertTrue(all(i['mode'].startswith(simple.mode_prefix)
                                for i in items), category)

    def test_custom_category_has_no_list(self):
        """У кастомного мода предмет — файл на диске, а не строка каталога."""
        self.assertEqual(api.items('custom'), [])


class ModeTests(unittest.TestCase):
    def test_category_gives_the_default_mode(self):
        self.assertEqual(api.mode_for('weapon'), 'normal')
        self.assertEqual(api.mode_for('skybox'), 'skybox')

    def test_subtype_wins_over_category(self):
        """Персонаж — это тело, руки или маски: решает подтип."""
        self.assertEqual(api.mode_for('character', 'engineer_hands'), 'engineer_hands')


class ControlsTests(unittest.TestCase):
    """Каждый пункт сверен с apply_mode_restrictions."""

    def test_shoulders_only_for_hands(self):
        self.assertTrue(api.controls_for('engineer_hands')['shoulders'])
        for mode in ('c_scattergun', 'scout_body', 'hat', 'spray', 'skybox'):
            self.assertFalse(api.controls_for(mode)['shoulders'], mode)

    def test_first_person_only_for_weapons(self):
        """У шапки вида от первого лица нет, хотя режим у неё обычный."""
        self.assertTrue(api.controls_for('c_scattergun')['first_person'])
        self.assertFalse(api.controls_for('hat')['first_person'])
        self.assertFalse(api.controls_for('engineer_hands')['first_person'])

    def test_spray_pins_resolution_and_locks_format(self):
        c = api.controls_for('spray')
        self.assertEqual(c['resolutions'], ['256'])
        self.assertTrue(c['format_locked'])
        self.assertFalse(c['flags_enabled'])

    def test_crit_narrows_formats_to_alpha_capable(self):
        self.assertEqual(api.controls_for('critHIT')['formats'],
                         ['DXT5', 'RGBA8888', 'DXT3'])

    def test_skybox_formats_have_no_alpha(self):
        self.assertEqual(api.controls_for('skybox')['formats'], ['DXT1', 'BGR888'])

    def test_normal_map_needs_a_model(self):
        """Spray и CritHIT — UnlitGeneric, бамп там бессмыслен."""
        for mode in ('c_scattergun', 'engineer_hands', 'scout_body'):
            self.assertTrue(api.controls_for(mode)['normal_map'], mode)
        for mode in ('spray', 'critHIT'):
            self.assertFalse(api.controls_for(mode)['normal_map'], mode)

    def test_material_maps_follow_normal_map(self):
        for mode in ('c_scattergun', 'spray', 'critHIT', 'engineer_hands'):
            c = api.controls_for(mode)
            self.assertEqual(c['material_maps'], c['normal_map'], mode)

    def test_tools_need_a_model(self):
        self.assertTrue(api.controls_for('c_scattergun')['extract_model'])
        self.assertFalse(api.controls_for('spray')['extract_model'])
        self.assertFalse(api.controls_for('skybox')['extract_texture'])

    def test_replace_model_not_offered_for_player_body(self):
        """Сложный скелет и bodygroups — подмена почти всегда даёт битый результат."""
        self.assertTrue(api.controls_for('c_scattergun')['replace_model'])
        self.assertFalse(api.controls_for('scout_body')['replace_model'])

    def test_gamma_hidden_where_flags_are_restricted(self):
        """Гамма видна только в режимах без ограничений на набор флагов."""
        self.assertTrue(api.controls_for('c_scattergun')['gamma'])
        self.assertFalse(api.controls_for('skybox')['gamma'])

    def test_spy_masks_hide_teams(self):
        self.assertFalse(api.controls_for('spy_masks')['teams'])
        self.assertTrue(api.controls_for('c_scattergun')['teams'])

    def test_every_mode_answers_the_same_questions(self):
        """Набор ключей не должен зависеть от режима — иначе фронт ловит undefined."""
        base = set(api.controls_for('c_scattergun'))
        for mode in ('hat', 'engineer_hands', 'scout_body', 'spray',
                     'critHIT', 'skybox', 'spy_masks', ''):
            self.assertEqual(set(api.controls_for(mode)), base, mode)


class SpecialCategoryTests(unittest.TestCase):
    """Спец-режимы: спрей, крит и эффекты смерти."""

    def test_special_items_have_human_names(self):
        """Ключ режима человеку ничего не говорит: «death_ice» — не название."""
        names = {i['key']: i['name'] for i in api.items('special', lang='ru')}
        self.assertEqual(names['spray'], 'Спрей')
        self.assertEqual(names['critHIT'], 'Крит')
        self.assertTrue(names['death_ice'].startswith('Эффект смерти'))

    def test_special_mode_is_the_key_itself(self):
        for item in api.items('special'):
            self.assertEqual(item['mode'], item['key'])


if __name__ == '__main__':
    unittest.main()
