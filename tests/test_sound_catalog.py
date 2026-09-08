"""
Каталог игровых звуков и сборка мода из них.

Звук в Source зовут именем записи, а не файлом, и правил тут ровно три:
как разобрать запись, к какому событию её отнести и чей это звук. Ими и
держится страница — фильтровать восемь сотен записей больше нечем.
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


class FamilyTests(unittest.TestCase):
    """Событий в одном скрипте 345 — фильтровать по ним нельзя, только по семьям."""

    def test_crit_wins_over_the_shot(self):
        """`SingleCrit` — это крит, хотя и содержит `Single`."""
        self.assertEqual(sc.family_of('SingleCrit'), 'crit')

    def test_known_events_land_where_expected(self):
        for event, family in (('Single', 'fire'), ('WorldReload', 'reload'),
                              ('HitFlesh', 'hit'), ('Draw', 'draw'),
                              ('Explode', 'explode'), ('WindUp', 'spin')):
            self.assertEqual(sc.family_of(event), family, event)

    def test_unknown_event_is_not_an_error(self):
        self.assertEqual(sc.family_of('TubeOpen'), 'other')


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

    def test_take_number_does_not_make_a_new_family(self):
        """Реплик каждого повода по полсотни, и семья у них одна."""
        self.assertEqual(sc.family_of('PainSharp07'), 'pain')
        self.assertEqual(sc.family_of('PainSharp'), 'pain')

    def test_death_wins_over_crit(self):
        """`CritDeath` — это смерть. У оружия событий со словом death нет
        вовсе, так что спора с критом не выходит."""
        self.assertEqual(sc.family_of('CritDeath'), 'death')
        self.assertEqual(sc.family_of('SingleCrit'), 'crit')

    def test_section_is_remembered(self):
        self.assertEqual(self.rows['Heavy.CritDeath'].section, 'voice')

    def test_weapon_subject_gets_no_class(self):
        """У оружия класс из имени не выводится: дробовик носят трое."""
        weapon = {e.name: e for e in sc.parse_script(SCRIPT)}
        self.assertEqual(weapon['Weapon_Shotgun.Single'].classes, ())


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
        """`scout_taunt_dosido_intro` — насмешка мастерской, а не разведчик:
        портрет ей ни к чему."""
        self.assertNotIn('class_portraits/scout',
                         sc.icon_for('scout_taunt_dosido_intro', 'voice'))

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
