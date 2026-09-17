"""
Каталог игровых звуков и сборка мода из них.

Звук в Source зовут именем записи, а не файлом, и правил тут ровно три:
как разобрать запись, к какой группе событий её отнести и чей это звук. Ими и
держится страница — фильтровать десять тысяч записей больше нечем.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import wave

from src.data import sound_catalog as sc
from src.services import sound_build_service as builder

SCRIPT = '''
// Комментарий, который разбору мешать не должен.
"Weapon_Shotgun.Single"
{
	"channel"	"CHAN_WEAPON"
	"soundlevel"	"SNDLVL_94dB"
	"volume"	"1.0"
	"wave"		")weapons/shotgun_shoot.wav"
}

"FX_Ricochet.Ricochet"
{
	"channel"	"CHAN_STATIC"
	"volume"	"1.0"
	"rndwave"
	{
		"wave"	"weapons/fx/rics/ric1.wav"
		"wave"	"^weapons/fx/rics/ric2.wav"
	}
}

"Weapon_Empty.NoFile"
{
	"channel"	"CHAN_STATIC"
}
'''

ITEMS_GAME = '''
"items_game"
{
\t"items"
\t{
\t\t"1"
\t\t{
\t\t\t"item_name"\t"#TF_TestGun"
\t\t\t"used_by_classes"
\t\t\t{
\t\t\t\t"scout"\t"1"
\t\t\t\t"soldier"\t"1"
\t\t\t}
\t\t\t"visuals"
\t\t\t{
\t\t\t\t"sound_single_shot"\t"Weapon_Shotgun.Single"
\t\t\t}
\t\t}
\t}
}
'''


class ParseTests(unittest.TestCase):

    def setUp(self):
        self.rows = {e.name: e for e in sc.parse_script(SCRIPT)}

    def test_entry_without_a_file_is_skipped(self):
        """Заменять в такой записи нечего — в списке ей не место."""
        self.assertNotIn('Weapon_Empty.NoFile', self.rows)

    def test_name_splits_into_subject_and_event(self):
        one = self.rows['Weapon_Shotgun.Single']
        self.assertEqual((one.subject, one.event), ('Weapon_Shotgun', 'Single'))

    def test_random_waves_are_all_collected(self):
        """Игра берёт из `rndwave` случайный: подменив один, свой звук слышно
        через раз."""
        self.assertEqual(self.rows['FX_Ricochet.Ricochet'].waves,
                         ('weapons/fx/rics/ric1.wav',
                          'weapons/fx/rics/ric2.wav'))

    def test_source_prefixes_are_stripped(self):
        """`)` и `^` — это признаки звука в Source, а не часть пути."""
        self.assertEqual(self.rows['Weapon_Shotgun.Single'].waves,
                         ('weapons/shotgun_shoot.wav',))


class GroupTests(unittest.TestCase):
    """Событий в одном скрипте 345 — фильтровать по ним нельзя, только по группам.

    Группа ищется ПО СЛОВАМ имени, а не по вхождению: старый разбор находил
    команду «Go» в «GoLoop» и «No» в «NoTarget», и половина оружия уезжала
    в «Команду».
    """

    def test_crit_wins_over_the_shot(self):
        """`SingleCrit` — это крит, хотя и содержит `Single`."""
        self.assertEqual(sc.group_of('weapon', 'Weapon_Shotgun', 'SingleCrit'),
                         'crit')

    def test_known_events_land_where_expected(self):
        for event, group in (('Single', 'fire'), ('WorldReload', 'reload'),
                             ('HitFlesh', 'hit'), ('Draw', 'draw'),
                             ('Explode', 'explode'), ('WindUp', 'spin'),
                             ('HitSoundNotes', 'hitsound')):
            self.assertEqual(sc.group_of('weapon', 'Weapon_X', event), group,
                             event)

    def test_short_words_match_whole_only(self):
        """«GoLoop» — не команда «Go», «NoTarget» — не «No»."""
        self.assertEqual(sc.group_of('weapon', 'BumperCar', 'GoLoop'), 'other')
        self.assertEqual(sc.group_of('voice', 'Heavy', 'NoTarget',
                                     ('heavy',)), 'auto')
        self.assertEqual(sc.group_of('voice', 'Demoman', 'Go01',
                                     ('demoman',)), 'order')

    def test_subject_speaks_when_event_is_silent(self):
        """У `Building_Sentrygun.Alert` о группе говорит только субъект."""
        self.assertEqual(sc.group_of('weapon', 'Building_Sentrygun', 'Alert'),
                         'build')
        self.assertEqual(sc.group_of('weapon', 'WeaponMedigun', 'NoTarget'),
                         'heal')

    def test_event_beats_subject_for_weapons(self):
        """`Weapon_BuffBanner.Draw` — «достать», а не «лечение»."""
        self.assertEqual(sc.group_of('weapon', 'Weapon_BuffBanner', 'Draw'),
                         'draw')

    def test_class_subject_says_nothing_about_group(self):
        """`Medic.AutoChargeReady` — автореплика, а не команда «Medic!»."""
        self.assertEqual(sc.group_of('voice', 'Medic', 'AutoChargeReady',
                                     ('medic',)), 'auto')

    def test_subject_beats_event_for_player_and_world(self):
        """`Taunt.SoldierShotgunFire` — реквизит насмешки, а не выстрел."""
        self.assertEqual(sc.group_of('player', 'Taunt', 'SoldierShotgunFire'),
                         'taunt')
        self.assertEqual(sc.group_of('world', 'MVM', 'GiantHeavyStep'), 'mvm')
        self.assertEqual(sc.group_of('world', 'Wood', 'StepLeft'), 'steps')

    def test_fallback_depends_on_the_speaker(self):
        """Что не подошло под слова: у класса — реакция, у диктора — матч."""
        self.assertEqual(sc.group_of('voice', 'Scout', 'SpecialCompleted01',
                                     ('scout',)), 'auto')
        self.assertEqual(sc.group_of('voice', 'Announcer', 'TimeAdded',
                                     ('announcer',)), 'match')
        self.assertEqual(sc.group_of('weapon', 'Weapon_X', 'Sparkle'), 'other')

    def test_glued_names_still_match(self):
        """У трети реплик имя без разделителей: `dominationdemoman03`."""
        self.assertEqual(sc.group_of('voice', 'engineer', 'dominationdemoman03',
                                     ('engineer',)), 'domination')
        self.assertEqual(sc.group_of('voice', 'scout', 'sf12_badmagic01',
                                     ('scout',)), 'halloween')

    def test_every_group_has_a_name(self):
        used = {g for rules in sc._GROUPS.values() for g, _ in rules}
        self.assertTrue(used <= set(sc.GROUP_NAMES), used - set(sc.GROUP_NAMES))


class NameTests(unittest.TestCase):
    """Имя без точки: субъект — приставка класса, если она есть."""

    def test_dotted_name_splits_at_the_dot(self):
        self.assertEqual(sc.split_name('Weapon_Shotgun.Single'),
                         ('Weapon_Shotgun', 'Single'))

    def test_class_prefix_becomes_the_subject(self):
        self.assertEqual(sc.split_name('cm_scout_gamewon_01'),
                         ('cm_scout', 'gamewon_01'))
        self.assertEqual(sc.split_name('engineer_dominationdemoman03'),
                         ('engineer', 'dominationdemoman03'))

    def test_name_without_class_stays_whole(self):
        self.assertEqual(sc.split_name('taunt_yeti_spy'), ('taunt_yeti_spy', ''))

    def test_words_split_camel_case_and_separators(self):
        self.assertEqual(sc.words_of('CartMovingForward_01'),
                         ['cart', 'moving', 'forward'])
        self.assertEqual(sc.words_of('RPGDraw'), ['rpg', 'draw'])


class SpeakerTests(unittest.TestCase):
    """Кто звучит — из имени записи, из приставки или из пути к файлу."""

    def test_class_subject_wins_over_class_in_event(self):
        """`Spy.DominationScout01` — шпион, а не разведчик."""
        self.assertEqual(sc.speaker_of('Spy', 'Spy.DominationScout01', ()),
                         ('spy',))

    def test_valve_short_names_are_understood(self):
        self.assertEqual(sc.speaker_of('cm_engie', 'cm_engie_gamewon_01', ()),
                         ('engineer',))
        self.assertEqual(sc.speaker_of('demo', 'demo_taunt_nuke_9_button', ()),
                         ('demoman',))

    def test_file_path_names_the_voice(self):
        """`taunt_yeti_spy` о голосе молчит — говорит папка файла."""
        self.assertEqual(sc.speaker_of('taunt_yeti_spy', 'taunt_yeti_spy',
                                       ('vo/spy_sf12_badmagic03.mp3',)),
                         ('spy',))
        self.assertEqual(sc.speaker_of('x', 'x', ('vo/taunts/engy/eng_1.mp3',)),
                         ('engineer',))
        self.assertEqual(sc.speaker_of('x', 'x', ('vo/pauling/plng_1.mp3',)),
                         ('pauling',))

    def test_prefix_beats_class_in_words(self):
        """`plng_give_contract_demo` говорит Полинг — подрывнику."""
        self.assertEqual(sc.speaker_of('plng_give_contract_demo',
                                       'plng_give_contract_demo', ()),
                         ('pauling',))

    def test_buildings_belong_to_the_engineer(self):
        self.assertEqual(
            sc.speaker_of('Building_Sentrygun', 'Building_Sentrygun.Alert', ()),
            ('engineer',))

    def test_announcer_has_many_subjects(self):
        for subject in ('Announcer', 'AttackDefend', 'CaptureFlag'):
            self.assertEqual(sc.speaker_of(subject, subject + '.X', ()),
                             ('announcer',), subject)

    def test_unknown_voice_is_empty(self):
        self.assertEqual(sc.speaker_of('Sword', 'Sword.Idle',
                                       ('vo/sword_idle01.mp3',)), ())

    def test_every_speaker_has_a_name(self):
        used = set(sc._SUBJECT_WHO.values()) | {w for _, w in sc._WAVE_WHO}
        self.assertTrue(used <= set(sc.WHO_NAMES), used - set(sc.WHO_NAMES))


class MvmTakeTests(unittest.TestCase):
    """Роботизированный дубль узнаётся по папке файла, а не по имени."""

    def test_take_in_the_mvm_folder(self):
        one = sc.make_entry('Scout.MVM_Go01',
                            ('vo/mvm/norm/scout_mvm_go01.mp3',), 'voice')
        self.assertTrue(one.mvm)
        # Приставка `MVM_` в группе не участвует: это та же команда «Go!».
        self.assertEqual(one.group, 'order')

    def test_mvm_in_the_name_is_not_a_take(self):
        """`heavy_mvm_ask_ready01` — обычная реплика в MvM, а не дубль."""
        one = sc.make_entry('heavy_mvm_ask_ready01',
                            ('vo/heavy_mvm_ask_ready01.mp3',), 'voice')
        self.assertFalse(one.mvm)
        self.assertEqual((one.group, one.who), ('mvm', ('heavy',)))

    def test_announcer_mvm_lines_are_not_takes(self):
        one = sc.make_entry('Announcer.MVM_Wave_Start',
                            ('vo/mvm_wave_start01.mp3',), 'voice')
        self.assertFalse(one.mvm)
        self.assertEqual(one.group, 'mvm')


VOICE = '''
"Heavy.CritDeath"
{
	"channel"	"CHAN_VOICE"
	"wave"	"vo/heavy_paincriticaldeath01.wav"
}

"Scout.PainSharp07"
{
	"channel"	"CHAN_VOICE"
	"wave"	"vo/scout_painsharp07.wav"
}
'''


class VoiceTests(unittest.TestCase):
    """Реплики размечены точнее оружия: имя записи называет и класс, и повод."""

    def setUp(self):
        self.rows = {e.name: e for e in sc.parse_script(VOICE, 'voice')}

    def test_class_comes_straight_from_the_name(self):
        """`Scout.PainSharp07` — это разведчик, и гадать тут не о чем."""
        self.assertEqual(self.rows['Scout.PainSharp07'].classes, ('scout',))
        self.assertEqual(self.rows['Heavy.CritDeath'].classes, ('heavy',))

    def test_take_number_does_not_make_a_new_group(self):
        """Реплик каждого повода по полсотни, и группа у них одна."""
        self.assertEqual(self.rows['Scout.PainSharp07'].group, 'pain')

    def test_death_wins_over_crit(self):
        """`CritDeath` — это смерть, а `SingleCrit` у оружия — крит."""
        self.assertEqual(self.rows['Heavy.CritDeath'].group, 'death')
        self.assertEqual(sc.group_of('weapon', 'Weapon_X', 'SingleCrit'), 'crit')

    def test_speaker_is_the_class(self):
        self.assertEqual(self.rows['Scout.PainSharp07'].who, ('scout',))

    def test_section_is_remembered(self):
        self.assertEqual(self.rows['Heavy.CritDeath'].section, 'voice')

    def test_weapon_subject_gets_no_class(self):
        """У оружия класс из имени не выводится: дробовик носят трое."""
        weapon = {e.name: e for e in sc.parse_script(SCRIPT)}
        self.assertEqual(weapon['Weapon_Shotgun.Single'].classes, ())


TAKES = '''
"Scout.Go01"
{
	"channel"	"CHAN_VOICE"
	"volume"	"0.82"
	"soundlevel"	"SNDLVL_95dB"
	"wave"	"vo/scout_go01.mp3"
}
"Scout.Go02"
{
	"channel"	"CHAN_VOICE"
	"wave"	"vo/scout_go02.mp3"
}
"Scout.Go03"
{
	"channel"	"CHAN_VOICE"
	"rndwave"
	{
		"wave"	"vo/scout_go03a.mp3"
		"wave"	"vo/scout_go03b.mp3"
	}
}
"Scout.Death"
{
	"wave"	"vo/scout_death.mp3"
}
"Scout.Death01"
{
	"wave"	"vo/scout_death01.mp3"
}
"Scout.Death02"
{
	"wave"	"vo/scout_death02.mp3"
}
"Scout.Silent"
{
	"wave"	"misc/null.wav"
}
'''


class TakeTests(unittest.TestCase):
    """Дубли одной реплики сворачиваются в запись с их файлами."""

    def setUp(self):
        self.rows = {e.name: e
                     for e in sc.fold_takes(sc.parse_script(TAKES, 'voice'))}

    def test_numbered_takes_fold_into_one(self):
        """`Scout.Go01`…`03` — одна реплика «Go!», игра берёт любой дубль."""
        self.assertIn('Scout.Go', self.rows)
        self.assertNotIn('Scout.Go01', self.rows)
        self.assertEqual(self.rows['Scout.Go'].waves,
                         ('vo/scout_go01.mp3', 'vo/scout_go02.mp3',
                          'vo/scout_go03a.mp3', 'vo/scout_go03b.mp3'))

    def test_take_name_goes_with_each_file(self):
        """У дубля бывает несколько файлов — имя стоит при каждом."""
        self.assertEqual(self.rows['Scout.Go'].takes,
                         ('Scout.Go01', 'Scout.Go02', 'Scout.Go03',
                          'Scout.Go03'))

    def test_folded_entry_keeps_group_and_speaker(self):
        one = self.rows['Scout.Go']
        self.assertEqual((one.group, one.who, one.section),
                         ('order', ('scout',), 'voice'))

    def test_stem_taken_by_a_real_entry_is_left_alone(self):
        """`Scout.Death` уже есть — подменять её дублями нельзя."""
        self.assertIn('Scout.Death', self.rows)
        self.assertIn('Scout.Death01', self.rows)
        self.assertEqual(self.rows['Scout.Death'].takes, ())

    def test_silence_placeholder_is_dropped(self):
        """`misc/null.wav` — «ничего», одно на полтора десятка записей."""
        self.assertNotIn('Scout.Silent', self.rows)
        self.assertTrue(sc.is_silence('misc/null.wav'))
        self.assertTrue(sc.is_silence('vo/null.mp3'))
        self.assertFalse(sc.is_silence('vo/scout_go01.mp3'))

    def test_script_props_are_read(self):
        """Свой файл зазвучит с каналом и громкостью из скрипта."""
        one = self.rows['Scout.Go']
        self.assertEqual((one.channel, one.volume, one.level),
                         ('CHAN_VOICE', '0.82', 'SNDLVL_95dB'))


class BindingTests(unittest.TestCase):
    """Чей звук, знает только items_game: дробовик носят трое."""

    def test_item_and_its_classes_are_found(self):
        bound = sc.item_bindings(ITEMS_GAME)
        items, classes = bound['Weapon_Shotgun.Single']
        self.assertEqual(items, {'TF_TestGun'})
        self.assertEqual(classes, {'scout', 'soldier'})

    def test_item_without_sounds_is_ignored(self):
        self.assertEqual(sc.item_bindings('"items_game" { }'), {})


class OrphanTests(unittest.TestCase):
    """Файлы, которых не называет ни одна запись.

    Их полсотни: связку «событие — файл» для части оружия Valve держит в
    зашифрованных `tf_weapon_*.ctx`. Через записи туда не добраться, а
    заменяются они всё равно по пути — значит, показывать надо.
    """

    PAK = ['sound/weapons/known.wav', 'sound/weapons/lonely.wav',
           'sound/weapons/notes.txt', 'sound/vo/scout_jump.wav',
           'materials/models/gun.vtf']

    def _found(self):
        return sc._orphan_files([self.PAK], {'weapons/known.wav'})

    def test_only_unnamed_weapon_sounds_are_added(self):
        self.assertEqual([e.waves for e in self._found()],
                         [('weapons/lonely.wav',)])

    def test_orphan_is_named_by_its_file(self):
        one = self._found()[0]
        self.assertEqual((one.name, one.subject, one.event),
                         ('weapons/lonely.wav', 'lonely', ''))


class SearchTests(unittest.TestCase):
    """Поиск не должен спотыкаться о разделители в именах Valve."""

    def test_separators_and_case_are_ignored(self):
        """Скаттерган в игре записан `Weapon_Scatter_Gun`, и буквальное
        совпадение подстроки не находило его по слову «scattergun»."""
        from src.app.session import _plain

        self.assertEqual(_plain('Weapon_Scatter_Gun.Single'),
                         'weaponscattergunsingle')
        self.assertIn(_plain('scattergun'), _plain('Weapon_Scatter_Gun.Single'))

    def test_russian_survives(self):
        from src.app.session import _plain

        self.assertEqual(_plain('Обрез Малыша'), 'обрезмалыша')


class RankTests(unittest.TestCase):
    """Поиск ранжирует: имя предмета дороже имени записи, то — дороже файла."""

    @staticmethod
    def _row(name, terms, waves):
        from src.app.session import _plain

        plain = [_plain(t) for t in terms]
        return {'name': name, 'terms': tuple(plain), 'name_plain': _plain(name),
                'blob': ' '.join([*plain, _plain(name),
                                  *(_plain(w) for w in waves)])}

    def test_item_name_beats_file_name(self):
        """«pistol» — сначала пистолет, а не ракетница с пистолетным файлом."""
        from src.app.session import _score

        pistol = self._row('Weapon_Pistol.Single', ['Пистолет', 'Pistol'],
                           ['weapons/pistol_shoot.wav'])
        flare = self._row('Weapon_FlareGun.ClipEmpty', ['Ракетница', 'Flare Gun'],
                          ['weapons/pistol_empty.wav'])
        self.assertGreater(_score(pistol, ['pistol']), _score(flare, ['pistol']))

    def test_whole_term_beats_its_prefix(self):
        from src.app.session import _score

        bat = self._row('Weapon_Bat.Draw', ['Бита', 'Bat'], [])
        saber = self._row('Weapon_BatSaber.Draw', ['Бэт-сабля', 'Batsaber'], [])
        self.assertGreater(_score(bat, ['bat']), _score(saber, ['bat']))

    def test_every_word_must_match(self):
        from src.app.session import _score

        bat = self._row('Weapon_Bat.Draw', ['Бита', 'Bat', 'Scout', 'Melee'], [])
        self.assertGreater(_score(bat, ['scout', 'melee']), 0)
        self.assertLess(_score(bat, ['scout', 'rifle']), 0)


class FormatTests(unittest.TestCase):
    """Расширение своего файла обязано совпасть с игровым.

    Игра зовёт файл по имени из записи, вместе с расширением. Реплики почти
    все в MP3 (12299 против 103), оружие почти всё в WAV — положив WAV под
    именем `.mp3`, получаешь в игре тишину и не понимаешь почему.
    """

    def _check(self, wave_name, own_name):
        from src.app.session import AppSession

        return AppSession._wrong_format([wave_name], own_name)

    def test_same_extension_passes(self):
        self.assertEqual(self._check('vo/heavy.mp3', 'C:/my.mp3'), '')

    def test_wav_into_an_mp3_slot_is_refused(self):
        trouble = self._check('vo/heavy.mp3', 'C:/my.wav')
        self.assertIn('MP3', trouble)
        self.assertIn('WAV', trouble)

    def test_mixed_kinds_accept_either(self):
        """У полусотни записей файлы разных расширений вперемешку: у моторки
        разведчика и wav, и mp3. Годится совпавший хоть с одним."""
        from src.app.session import AppSession

        waves = ['vo/a.wav', 'vo/b.mp3', 'vo/c.mp3']
        self.assertEqual(AppSession._wrong_format(waves, 'C:/my.wav'), '')
        self.assertEqual(AppSession._wrong_format(waves, 'C:/my.mp3'), '')
        self.assertIn('MP3/WAV', AppSession._wrong_format(waves, 'C:/my.ogg'))

    def test_entry_without_files_is_not_judged(self):
        from src.app.session import AppSession

        self.assertEqual(AppSession._wrong_format([], 'C:/my.wav'), '')


class ArchiveNameTests(unittest.TestCase):
    """Имена пронумерованных архивов у библиотеки vpk.

    В `_make_vpkfile_path` она делает `path.replace('english', '')` — хак под
    чужие сборки Source. У TF2 озвучка так и называется, и после замены
    библиотека искала несуществующий `tf2_sound_vo__001.vpk`: реплики молчали.
    """

    def _path(self, vpk_path, index):
        from src.services.vpk_cache import _fix_archive_names

        class FakePak:
            pass

        pak = FakePak()
        pak.vpk_path = vpk_path
        _fix_archive_names(pak)
        return pak._make_vpkfile_path({'archive_index': index})

    def test_language_in_the_name_survives(self):
        self.assertEqual(
            self._path('D:/tf/tf2_sound_vo_english_dir.vpk', 1),
            'D:/tf/tf2_sound_vo_english_001.vpk')

    def test_ordinary_archive_is_numbered_as_before(self):
        self.assertEqual(self._path('D:/tf/tf2_misc_dir.vpk', 12),
                         'D:/tf/tf2_misc_012.vpk')

    def test_file_inside_the_dir_stays_there(self):
        """0x7fff — «лежит в самом каталоге», подменять путь нечем."""
        self.assertEqual(self._path('D:/tf/tf2_misc_dir.vpk', 0x7fff),
                         'D:/tf/tf2_misc_dir.vpk')


class IconTests(unittest.TestCase):
    """Картинка «чей это звук». Пустая ячейка в списке читается как поломка."""

    def test_class_gets_its_portrait(self):
        self.assertEqual(sc.icon_for('Scout', 'voice'),
                         'mat/vgui/class_portraits/scout')
        self.assertEqual(sc.icon_for('Demoman', 'voice'),
                         'mat/vgui/class_portraits/demoman')

    def test_class_matches_whole_name_only(self):
        """`scout_taunt_dosido_intro` — имя файла, а не класс: чей это голос,
        решает `speaker_of`, и портрет приходит через него."""
        self.assertNotIn('class_portraits/scout',
                         sc.icon_for('scout_taunt_dosido_intro', 'voice'))
        self.assertEqual(sc.icon_for('scout_taunt_dosido_intro', 'voice',
                                     'scout'), 'mat/vgui/class_portraits/scout')

    def test_subject_beats_speaker(self):
        """У турели говорящий — инженер, а картинка нужна турели."""
        self.assertIn('sentry', sc.icon_for('Building_Sentrygun', 'weapon',
                                            'engineer'))

    def test_buildings_get_their_own(self):
        for subject, part in (('Building_Sentrygun', 'sentry'),
                              ('Building_Dispenser', 'dispenser'),
                              ('Building_Teleporter', 'teleporter')):
            self.assertIn(part, sc.icon_for(subject, 'weapon'), subject)

    def test_announcer_gets_the_voice_sign(self):
        """Своей картинки у Администратора в игре нет — берём значок голоса."""
        self.assertEqual(sc.icon_for('Announcer', 'voice'), sc.VOICE_ICON)

    def test_unknown_subject_falls_back_to_its_section(self):
        """Под сотню субъектов — остатки Half-Life 2 и служебные эффекты,
        предмета в игре у них нет."""
        self.assertEqual(sc.icon_for('357_fire2', 'weapon'),
                         sc.SECTION_ICONS['weapon'])
        self.assertEqual(sc.icon_for('BaseExplosionEffect', 'world'),
                         sc.SECTION_ICONS['world'])

    def test_every_section_has_a_fallback(self):
        self.assertEqual(sorted(sc.SECTION_ICONS), sorted(sc.SECTIONS))


class SaveTests(unittest.TestCase):
    """Достать игровой звук: переделать его иначе не из чего."""

    def _session(self, waves, folder, data=b'RIFF'):
        from src.app.session import AppSession

        session = AppSession.__new__(AppSession)
        session._rows_any = lambda: [{'name': 'Weapon_Test.Single',
                                      'waves': waves}]
        session._export_settings = lambda: (folder, 'PNG')
        session.sound_bytes = lambda wave: data
        return session

    def test_every_file_of_the_entry_is_saved(self):
        """Игра берёт из записи случайный файл — переделывать надо все."""
        folder = tempfile.mkdtemp()
        got = self._session(['weapons/a.wav', 'weapons/b.wav'],
                            folder).save_sound('Weapon_Test.Single')
        self.assertEqual(got['files'], 2)
        self.assertEqual(sorted(os.listdir(folder)), ['a.wav', 'b.wav'])

    def test_only_the_file_name_is_used(self):
        """Путь внутри игры сюда не переносим: `..` увёл бы запись мимо
        папки экспорта."""
        folder = tempfile.mkdtemp()
        self._session(['../../evil.wav'], folder).save_sound('Weapon_Test.Single')
        self.assertEqual(os.listdir(folder), ['evil.wav'])

    def test_unknown_entry_is_refused(self):
        session = self._session(['weapons/a.wav'], tempfile.mkdtemp())
        self.assertIn('error', session.save_sound('нет такой'))

    def test_entry_without_a_file_says_so(self):
        """На полсотни записей игра ссылается, а файлов не положила."""
        session = self._session(['weapons/a.wav'], tempfile.mkdtemp(), data=b'')
        self.assertIn('error', session.save_sound('Weapon_Test.Single'))


class PickTests(unittest.TestCase):
    """Замены живут по файлам игры, а не по записям.

    Игра подменяет файл, и один файл бывает у девяти записей: заменив
    «промах» у биты, человек заменил его и у бутылки — и обе строки обязаны
    это показать.
    """

    def _session(self):
        from src.app.session import AppSession

        session = AppSession.__new__(AppSession)
        session._wave_picks = {}
        session._rows_any = lambda: [
            {'name': 'Weapon_Bat.Miss', 'waves': ['weapons/miss.wav']},
            {'name': 'Weapon_Bottle.Miss', 'waves': ['weapons/miss.wav']},
            {'name': 'Weapon_Fist.Miss',
             'waves': ['weapons/swoosh1.wav', 'weapons/swoosh2.wav']},
            {'name': 'Weapon_Mixed.Single',
             'waves': ['weapons/a.wav', 'vo/b.mp3']},
        ]
        return session

    def _wav(self):
        path = os.path.join(tempfile.mkdtemp(), 'own.wav')
        with wave.open(path, 'wb') as snd:
            snd.setnchannels(1)
            snd.setsampwidth(2)
            snd.setframerate(44100)
            snd.writeframes(b'\0' * 40)
        return path

    def test_shared_file_marks_every_owner(self):
        session = self._session()
        res = session.set_sound('Weapon_Bat.Miss', self._wav())
        self.assertTrue(res['own'])
        self.assertEqual(sorted(res['affected']),
                         ['Weapon_Bat.Miss', 'Weapon_Bottle.Miss'])
        self.assertTrue(res['affected']['Weapon_Bottle.Miss']['own'])
        # Затронуто две записи, а файл под замену один.
        self.assertEqual((res['total'], res['files']), (2, 1))

    def test_one_file_of_two_is_partial(self):
        session = self._session()
        res = session.set_sound('Weapon_Fist.Miss', self._wav(),
                                'weapons/swoosh1.wav')
        self.assertEqual((res['own'], res['partial']), ('', True))
        self.assertEqual(list(res['own_waves']), ['weapons/swoosh1.wav'])

    def test_whole_entry_then_removed(self):
        session = self._session()
        session.set_sound('Weapon_Fist.Miss', self._wav())
        self.assertEqual(len(session._wave_picks), 2)
        res = session.set_sound('Weapon_Fist.Miss', None)
        self.assertEqual((res['own'], res['partial'], res['files']),
                         ('', False, 0))

    def test_mismatched_format_files_are_skipped(self):
        """WAV ложится только на `.wav`; про `.mp3` говорим сразу."""
        session = self._session()
        res = session.set_sound('Weapon_Mixed.Single', self._wav())
        self.assertEqual(res['skipped'], 1)
        self.assertTrue(res['partial'])

    def test_clear_drops_everything(self):
        session = self._session()
        session.set_sound('Weapon_Bat.Miss', self._wav())
        self.assertEqual(session.clear_sounds(), {'total': 0, 'files': 0})
        self.assertEqual(session._wave_picks, {})

    def test_unknown_entry_is_refused(self):
        self.assertIn('error', self._session().set_sound('Нет такой', 'x.wav'))


class SubjectItemTests(unittest.TestCase):
    """Рабочее имя Valve в звуке против имени предмета в игре."""

    def test_table_is_sane(self):
        self.assertTrue(all(subject and item
                            for subject, item in sc.SUBJECT_ITEMS.items()))

    def test_article_is_tried_too(self):
        """Половина названий в игре с артиклем («The Buff Banner»), а
        называют их без него."""
        from src.app.session import AppSession

        session = AppSession.__new__(AppSession)
        guess = {'theeyelander': ('Eyelander', ('demoman',), 'c_claymore')}
        self.assertEqual(session._by_item(guess, 'Eyelander')[2], 'c_claymore')

    def test_missing_item_is_not_an_error(self):
        from src.app.session import AppSession

        session = AppSession.__new__(AppSession)
        self.assertIsNone(session._by_item({}, 'Такого предмета нет'))

    def test_entry_without_an_icon_does_not_count(self):
        """Имя нашлось, картинки нет — значит, ищем дальше."""
        from src.app.session import AppSession

        session = AppSession.__new__(AppSession)
        self.assertIsNone(session._by_item({'bat': ('Bat', (), '')}, 'Bat'))


class BuildTests(unittest.TestCase):
    """Формат проверяем здесь, а не выясняем в игре: Source молча промолчит."""

    def _wav(self, width=2, rate=44100):
        path = os.path.join(tempfile.mkdtemp(), 'a.wav')
        with wave.open(path, 'wb') as snd:
            snd.setnchannels(1)
            snd.setsampwidth(width)
            snd.setframerate(rate)
            snd.writeframes(struct.pack('<20h', *([0] * 20))[:20 * width])
        return path

    def test_ordinary_pcm_passes(self):
        self.assertEqual(builder.check_wav(self._wav()), '')

    def test_eight_bit_is_refused(self):
        self.assertIn('16-битный', builder.check_wav(self._wav(width=1)))

    def test_odd_rate_is_refused(self):
        self.assertIn('частота', builder.check_wav(self._wav(rate=48000)))

    def _named_mp3(self, data):
        path = os.path.join(tempfile.mkdtemp(), 'a.mp3')
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def test_real_mp3_passes(self):
        self.assertEqual(builder.check_wav(self._named_mp3(b'ID3\x03abc')), '')
        self.assertEqual(builder.check_wav(self._named_mp3(b'\xff\xfbabc')), '')

    def test_wav_renamed_to_mp3_is_refused(self):
        """Движок выбирает читалку по имени: такой файл в игре молчит."""
        self.assertIn('не MP3',
                      builder.check_wav(self._named_mp3(b'RIFF....WAVE')))

    def test_missing_file_is_refused(self):
        self.assertEqual(builder.check_wav('такого-нет.wav'), 'файла нет')

    def test_nothing_to_build_is_an_error(self):
        with self.assertRaises(ValueError):
            builder.build({}, 'empty.vpk')


if __name__ == '__main__':
    unittest.main()
