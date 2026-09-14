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

    def test_first_person_hidden_for_world_models(self):
        """Снаряд, пикап и реквизит насмешки в руках не держат — вьюмодели нет.

        `kind_of` зовёт их оружием (pipeline тот же), и вкладка «От первого
        лица» открывалась, но собрать было нечего.
        """
        for mode in ('projectile_rocket', 'pickup_medkit_small', 'taunt_conga'):
            self.assertFalse(api.controls_for(mode)['first_person'], mode)
        self.assertTrue(api.controls_for('taunt_conga')['taunt'])

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

    def test_flag_checks_carry_names_not_captions(self):
        """Галки флагов приезжают с ИМЕНЕМ флага, а не с подписью.

        В сборку уходит имя (`-flag clamps`): на подпись («Clamp S») VTFCmd
        падает, то есть отмеченный флаг ломал сборку целиком. Плюс каждое имя
        обязано быть тем, которое сборка умеет применить.
        """
        from src.services.texture_service import TextureService

        flags = api.controls_for('c_scattergun')['flags']
        self.assertTrue(flags)
        for row in flags:
            self.assertIn(row['key'], TextureService._VTFLIB_FLAG_BITS, row)
            self.assertTrue(row['label'], row)
            self.assertTrue(row['on'], row)          # режим ничего не запрещает
        # NOMIP гасится опцией `nomipmaps`, а не флагом: в VTFCmd-пути имя
        # пропускается нарочно, и галка была бы пустышкой.
        self.assertNotIn('NOMIP', [row['key'] for row in flags])

    def test_settings_says_whether_the_game_path_works(self):
        """`tf2_ok` — по нему окно настроек прячет кнопку автопоиска.

        Проверку делает Python (`TF2Paths.is_valid`), а не страница: искать
        нечего, когда путь уже рабочий, и второй копии этого правила в
        разметке быть не должно.
        """
        from src.services.tf2_paths import TF2Paths

        cfg = api.settings()
        self.assertIsInstance(cfg['tf2_ok'], bool)
        self.assertEqual(cfg['tf2_ok'],
                         TF2Paths.is_valid(cfg['values']['tf2_game_folder']))

    def test_find_tf2_returns_only_working_folders(self):
        """Автопоиск отдаёт список папок, а не «похоже на игру».

        Каждая проверена тем же `is_valid`, по которому работает приложение:
        предложить путь, на котором сборка упадёт, хуже, чем не найти ничего.
        """
        from src.services.tf2_paths import TF2Paths

        found = api.find_tf2()['found']
        self.assertIsInstance(found, list)
        for path in found:
            self.assertTrue(TF2Paths.is_valid(path), path)

    def test_vpk_name_follows_the_item(self):
        """Имя мода предлагается по предмету, а не одно на всех.

        В разметке стояло «scattergun_mod.vpk», и топор собирался под именем
        скаттергана. Правило считает Python: имя обязано пройти
        validate_vpk_filename, и второй копии этих лимитов быть не должно.
        """
        self.assertEqual(api.controls_for('c_axtinguisher')['vpk_name'],
                         'axtinguisher_mod.vpk')
        # У косметики режим один на весь раздел — предмет называет ключ.
        self.assertEqual(
            api.controls_for('hat', 'models/player/items/pyro/hood.mdl')['vpk_name'],
            'hood_mod.vpk')
        # До выбора предмета подсказки нет: иначе щелчок по фильтру каталога
        # затирал бы уже набранное имя.
        self.assertEqual(api.controls_for('hat')['vpk_name'], '')

    def test_risky_flags_are_marked_advanced(self):
        """Обычных флагов пять — только они что-то меняют у цветного скина.

        Остальные скину либо безразличны (фильтрацию решает клиент, Single Copy
        — про память), либо относятся к другому виду текстур, либо вредны:
        SSBump объявляет текстуру самозатеняющимся бампмапом. Такая галка не
        должна стоять в одном ряду с «Point Sample», поэтому она особая и
        показывается только по настройке.
        """
        flags = api.controls_for('c_scattergun')['flags']
        plain = [row['key'] for row in flags if not row['adv']]
        self.assertEqual(plain, ['CLAMPS', 'CLAMPT', 'NOLOD',
                                 'NOMINMIP', 'POINTSAMPLE'])
        adv = {row['key'] for row in flags if row['adv']}
        self.assertIn('SSBUMP', adv)
        self.assertIn('VERTEXTEXTURE', adv)

    def test_advanced_flags_are_off_until_asked_for(self):
        """Настройка есть и по умолчанию не включена: особые флаги спрятаны.

        Значение читается из конфига человека, поэтому проверяем сам ключ и его
        тип — а не то, что стоит у разработчика в config.
        """
        values = api.settings()['values']
        self.assertIn('advanced_vtf_flags', values)
        self.assertIsInstance(values['advanced_vtf_flags'], bool)

    def test_skybox_enables_only_the_flag_it_needs(self):
        """У скайбокса осмысленный флаг один — Point Sample.

        Раньше доступность считалась сравнением ПОДПИСИ с именем
        («point sample».includes('pointsample') — ложь), и у неба гасились все
        галки, включая нужную.
        """
        flags = api.controls_for('skybox')['flags']
        self.assertEqual([row['key'] for row in flags if row['on']],
                         ['POINTSAMPLE'])

    def test_unrestricted_mode_gets_the_whole_format_list(self):
        """Список форматов всегда конкретный, а не «None — сам знаешь».

        `allowed_formats_for_mode` отвечает None там, где режим ничего не
        запрещает, и это значило «покажи полный список». Окно приложения его
        знало, а страница держала свою копию в разметке — из 26 форматов было
        видно 4. Второй копии списка быть не должно.
        """
        from src.shared.constants import VTF_FORMATS

        for mode in ('c_scattergun', 'hat', 'spray', 'scout_body'):
            self.assertEqual(api.controls_for(mode)['formats'],
                             list(VTF_FORMATS), mode)

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

    def test_parts_offered_wherever_there_is_geometry(self):
        """Деление на части — про геометрию, а не про подмену модели.

        Кнопка ходила за `replace_model` и вместе с ним пропадала у тел
        классов, хотя куски у них есть и красить их по одному хочется даже
        чаще, чем у оружия."""
        for mode in ('c_scattergun', 'hat', 'scout_body', 'scout_hands'):
            self.assertTrue(api.controls_for(mode)['split_parts'], mode)
        for mode in ('spray', 'skybox', 'critHIT'):
            self.assertFalse(api.controls_for(mode)['split_parts'], mode)

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


class SearchTests(unittest.TestCase):
    """Поиск в каталоге. Поле над списком одно, а искало только у косметики."""

    def test_weapons_are_searchable_by_name(self):
        found = api.items('weapon', query='scattergun')
        self.assertTrue(found)
        self.assertLess(len(found), len(api.items('weapon')))
        self.assertTrue(all('scattergun' in i['key'] for i in found))

    def test_all_words_must_match_in_any_order(self):
        """«обрез мал» обязано находить «Обрез Малыша»."""
        found = api.items('weapon', lang='ru', query='обрез мал')
        self.assertTrue(found)
        self.assertTrue(all('Обрез' in i['name'] for i in found))
        self.assertEqual(api.items('weapon', query='обрез мал зелёный'), [])

    def test_search_narrows_the_other_categories_too(self):
        pickups = api.items('pickup', lang='en')
        self.assertTrue(pickups)
        self.assertTrue(api.items('pickup', lang='en', query='ammo'))
        self.assertLess(len(api.items('pickup', lang='en', query='ammo')),
                        len(pickups))

    def test_empty_query_changes_nothing(self):
        self.assertEqual(len(api.items('weapon', query='   ')),
                         len(api.items('weapon')))


class CoverTests(unittest.TestCase):
    """Обложка карточки: у чего нет иконки в рюкзаке — своя модель или небо."""

    def test_world_models_point_at_their_mdl(self):
        """Аптечек, патронов и снарядов в рюкзаке нет вовсе.

        Реквизит насмешек — исключение: сама насмешка лежит в инвентаре, и
        иконка у неё есть (см. [taunt_catalog]). Тогда берётся она.
        """
        from src.data.simple_models import SIMPLE_MODEL_CATEGORIES

        for category, simple in SIMPLE_MODEL_CATEGORIES.items():
            for item in api.items(category):
                row = simple.table[item['key']]
                self.assertEqual(item['icon'],
                                 row.get('icon') or row['mdl_path'])
                if not row.get('icon'):
                    self.assertTrue(item['icon'].endswith('.mdl'),
                                    f"{category}/{item['key']}: {item['icon']!r}")

    def test_sky_points_at_itself(self):
        for item in api.items('skybox'):
            self.assertEqual(item['icon'], f"skybox/{item['key']}")

    def test_sky_list_comes_from_the_installed_game(self):
        """Небеса спрашиваем у игры, а не у копии списка в данных.

        `STOCK_SKY_NAMES` — фолбэк без настроенной папки; с обновлениями Valve
        он стареет, и страница показывала бы список короче настоящего. Скан
        (SkyboxService.enumerate_sky_names) объединяет фолбэк с содержимым
        tf2_misc_dir.vpk, поэтому короче он стать не может.
        """
        from unittest.mock import patch

        from src.data.skyboxes import STOCK_SKY_NAMES

        fake = list(STOCK_SKY_NAMES) + ['sky_from_update_99']
        with patch('src.services.skybox_service.SkyboxService'
                   '.enumerate_sky_names', return_value=fake) as scan:
            keys = [row['key'] for row in api.items('skybox')]
        self.assertTrue(scan.called)
        self.assertIn('sky_from_update_99', keys)
        self.assertEqual(len(keys), len(fake))

    def test_character_parts_have_their_own_covers(self):
        """У каждой части свой ответ: тело — чьё, руки — руки, маски — маски.

        Раньше все три брали текстуру своей модели: у половины классов
        предплечья лежат на общем листе с телом, и «Руки» показывали ровно то
        же, что «Скин», а маски — модель шпиона, то есть опять его же.
        """
        from src.data.player_characters import CLASS_ICON, DISGUISE_ICON

        icons = {(i['cls'], i['key']): i['icon']
                 for cls in ('Scout', 'Engineer', 'Spy')
                 for i in api.items('character', cls)}

        self.assertEqual(icons[('Spy', 'masks')], DISGUISE_ICON)
        for cls in ('Scout', 'Engineer', 'Spy'):
            self.assertEqual(icons[(cls, 'body')], CLASS_ICON.format(cls.lower()))
            # Руки — своя текстура рук, и она не повторяет обложку тела.
            self.assertIn('hands' if cls != 'Engineer' else 'hand',
                          icons[(cls, 'hands')])
            self.assertNotEqual(icons[(cls, 'hands')], icons[(cls, 'body')])


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
