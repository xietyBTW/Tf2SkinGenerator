"""
Каталог игровых звуков: что звучит, когда и у кого.

Звук в Source зовут не файлом, а ИМЕНЕМ ЗАПИСИ — `Weapon_Shotgun.Single`.
Запись лежит в звуковом скрипте (`scripts/game_sounds_*.txt`) и говорит, какой
файл играть, по какому каналу и с какой громкостью::

    "Weapon_Shotgun.Single"
    {
        "channel"       "CHAN_WEAPON"
        "soundlevel"    "SNDLVL_94dB"
        "volume"        "1.0"
        "wave"          ")weapons/shotgun_shoot.wav"
    }

Имя записи само себя объясняет: до точки — чей звук, после — какое событие.
Событий в одном оружейном скрипте 345 штук, поэтому по ним не фильтруют, а
сводят в семьи (выстрел, перезарядка, удар…): человеку нужен «звук выстрела»,
а не выбор между `Single`, `Fire` и `FireStart`.

Кого именно звук озвучивает, точно знает items_game: у предмета в `visuals`
стоит `sound_single_shot` с именем записи. Это единственный надёжный источник
класса — из имени `Weapon_Shotgun` класс не выводится, дробовик носят трое.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from src.data.player_characters import CLASS_ICON
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Скрипт оружейных звуков: в нём 610 записей `Weapon_*` из 624 во всей игре.
WEAPON_SCRIPT = 'scripts/game_sounds_weapons.txt'

#: Разделы каталога: ключ → скрипты, из которых он собирается.
#:
#: Делить надо: в игре звуков под семь тысяч, и одним списком их не смотрят.
#: Реплики устроены удобнее оружия — `Scout.PainSharp01` называет и КЛАСС, и
#: положение, в котором эта реплика звучит, так что фильтры по ним работают
#: точнее, чем по оружию.
SECTIONS: Dict[str, Tuple[str, ...]] = {
    'weapon': (WEAPON_SCRIPT,),
    'voice': ('scripts/game_sounds_vo.txt',
              'scripts/game_sounds_vo_handmade.txt',
              'scripts/game_sounds_vo_taunts.txt',
              'scripts/game_sounds_vo_tough_break.txt',
              'scripts/game_sounds_vo_pauling.txt',
              'scripts/game_sounds_vo_merasmus.txt',
              'scripts/game_sounds_vo_rd_robots.txt',
              'scripts/game_sounds_vo_mvm.txt',
              'scripts/game_sounds_vo_mvm_handmade.txt'),
    'player': ('scripts/game_sounds_player.txt',),
    'world': ('scripts/game_sounds.txt',
              'scripts/game_sounds_physics.txt',
              'scripts/game_sounds_mvm.txt',
              'scripts/game_sounds_music.txt',
              'scripts/game_sounds_passtime.txt'),
}

#: Подписи разделов. По-русски: английские берёт словарь страницы
#: (frontend/mockup/strings.js), как у всех остальных подписей.
SECTION_NAMES: Dict[str, str] = {
    'weapon': 'Оружие', 'voice': 'Реплики', 'player': 'Игрок', 'world': 'Мир',
}

#: Классы игры. У реплики класс стоит прямо в имени записи — это самый точный
#: источник из всех, что есть: у оружия его приходится угадывать.
CLASSES = ('scout', 'soldier', 'pyro', 'demoman', 'heavy',
           'engineer', 'medic', 'sniper', 'spy')

#: Картинка для того, чей это звук. Ключ `mat/…` уходит в общий `icon_png`,
#: который достаёт её прямо из игрового архива.
#:
#: Портрет класса (`CLASS_ICON`) живёт в данных о классах: те же портреты
#: стоят на карточках каталога персонажей. У построек — их значки из
#: интерфейса инженера, у диктора — значок голоса с миникарты: собственной
#: картинки у Администратора в игре нет.
ALL_CLASS_ICON = 'mat/vgui/class_portraits/all_class'
VOICE_ICON = 'mat/sprites/minimap_icons/voiceicon'

#: Субъект звука → предмет игры, когда имя записи с ним не сходится.
#:
#: Valve зовёт оружие в звуках своими рабочими именами: миниган — `Gatling`,
#: «Мачина» — `SniperRailgun`, «Латунный зверь» — `Minifun`. Ни каталог, ни
#: локализация, ни items_game такой связки не знают, а картинка предмета от
#: этого есть. Значение — ИМЯ предмета в игре: по нему картинка и находится,
#: и в отличие от пути её не надо править, когда Valve переложит файл.
SUBJECT_ITEMS: Dict[str, str] = {
    'BallBuster': 'Wrap Assassin',
    'BumperCar': 'Taunt: The Victory Lap',
    'Cleaver': 'Flying Guillotine',
    'DemoCharge': "Chargin' Targe",
    'DisciplineDevice': 'Disciplinary Action',
    'Dragon_Minigun': 'Huo-Long Heater',
    'Icicle': 'Spy-Cicle',
    'MeleeInspect': 'Bat',
    'WeaponMedi_Shield': 'Medi Gun',
    'WeaponMedigun_Vaccinator': 'Vaccinator',
    'Weapon_Arrow': 'Huntsman',
    'Weapon_Assassin_Knife': 'Black Rose',
    'Weapon_BarretsArm': 'Bat',
    'Weapon_BaseballBat': 'Bat',
    'Weapon_Bison': 'Righteous Bison',
    'Weapon_BuffBanner': 'Buff Banner',
    'Weapon_Club': 'Kukri',
    'Weapon_CompoundBow': 'Huntsman',
    'Weapon_Fist': 'Fists',
    'Weapon_Gatling': 'Minigun',
    'Weapon_Katana': 'Half-Zatoichi',
    'Weapon_LooseCannon': 'Loose Cannon',
    'Weapon_MetalGloves': 'Fists of Steel',
    'Weapon_Minifun': 'Brass Beast',
    'Weapon_QuakeRPG': 'Original',
    'Weapon_RPG': 'Rocket Launcher',
    'Weapon_RescueRanger': 'Rescue Ranger',
    'Weapon_Slap': 'Holiday Punch',
    'Weapon_SniperRailgun': 'Machina',
    'Weapon_Sword': 'Eyelander',
    'Weapon_bm_throwable': 'Mutated Milk',
    'Weapon_mittens': 'Boxing Gloves',
}

#: Субъект (в нижнем регистре, по вхождению) → картинка.
SUBJECT_ICONS: Tuple[Tuple[str, str], ...] = (
    ('sentry', 'mat/hud/hud_obj_status_sentry_3'),
    ('dispenser', 'mat/hud/hud_obj_status_dispenser'),
    ('teleporter', 'mat/hud/leaderboard_class_teleporter'),
    ('tank', 'mat/hud/leaderboard_class_tank'),
    ('announcer', VOICE_ICON),
    ('pauling', VOICE_ICON),
    ('merasmus', VOICE_ICON),
    ('robot', 'mat/hud/leaderboard_class_tank'),
    ('mvm', 'mat/hud/leaderboard_class_tank'),
    ('player', ALL_CLASS_ICON),
    ('taunt', ALL_CLASS_ICON),
)


#: Запасная картинка раздела. Своей у записи может не быть вовсе: под сотню
#: субъектов — это остатки Half-Life 2 (`357_fire2`) и служебные эффекты, у
#: которых предмета в игре нет. Пустая ячейка выглядит поломкой, поэтому
#: показываем хотя бы то, о чём этот раздел.
SECTION_ICONS: Dict[str, str] = {
    'weapon': 'mat/hud/hud_obj_status_ammo_64',
    'voice': VOICE_ICON,
    'player': ALL_CLASS_ICON,
    'world': 'mat/vgui/gfx/vgui/tf_logo',
}


def icon_for(subject: str, section: str = '') -> str:
    """Картинка по субъекту записи, иначе — по разделу.

    Класс проверяется первым и по полному совпадению: `Scout` — это класс, а
    `scout_taunt_dosido_intro` — насмешка мастерской, и портрет ей ни к чему.
    """
    low = (subject or '').lower()
    if low in CLASSES:
        return CLASS_ICON.format(low)
    for word, icon in SUBJECT_ICONS:
        if word in low:
            return icon
    return SECTION_ICONS.get(section, '')


#: Папка, файлы которой считаем оружейными.
WEAPON_SOUND_DIR = 'sound/weapons/'

#: Начало записи: имя в кавычках и скобка на следующей строке.
_ENTRY = re.compile(r'^"([^"]+)"\s*\r?\n\s*\{', re.M)
_PAIR = re.compile(r'"(\w+)"\s+"([^"]*)"')

#: Служебные приставки пути в Source: пространственный звук, поток, без потерь.
#: К файлу они не относятся — на диске его зовут без них.
_PREFIXES = ')(}$!?@#^*<>'

#: Событие → семья. Проверяется по вхождению, порядок важен: «SingleCrit» это
#: крит, а не выстрел, и попасться первым должен крит.
_FAMILIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # Смерть проверяется ПЕРВОЙ: `CritDeath` — это смерть, а не крит, и у
    # оружия событий со словом «death» нет вовсе, так что спора не выходит.
    ('death', ('death', 'dying')),
    ('pain', ('pain', 'hurt', 'onfire', 'beingshot')),
    ('order', ('medic', 'helpme', 'incoming', 'go', 'move', 'activate',
               'stand', 'cart', 'thanks', 'niceshot', 'goodjob', 'yes', 'no',
               'headleft', 'headright', 'sentry', 'dispenser', 'teleporter')),
    ('mood', ('cheer', 'jeer', 'laugh', 'vocalization', 'award', 'domination',
              'revenge', 'battlecry', 'dare', 'robot', 'dejected')),
    ('spy', ('cloakedspy', 'spyidentify', 'disguise')),
    ('crit', ('crit',)),
    ('reload', ('reload', 'boltback', 'boltforward', 'clipempty', 'empty',
                'cock', 'load')),
    ('hit', ('hitflesh', 'hitworld', 'impact', 'swing', 'miss', 'hit')),
    ('draw', ('draw', 'deploy', 'holster', 'raise', 'lower')),
    ('explode', ('explode', 'explosion', 'blast')),
    ('spin', ('windup', 'winddown', 'spin', 'charge')),
    ('taunt', ('taunt',)),
    ('fire', ('single', 'fire', 'shoot', 'shot', 'burst', 'launch')),
)

#: Подписи семей. Ключ — то, что уходит в фильтр, значение — что видит человек.
FAMILY_NAMES: Dict[str, str] = {
    'fire': 'Выстрел', 'crit': 'Крит', 'reload': 'Перезарядка',
    'hit': 'Удар', 'draw': 'Достать', 'explode': 'Взрыв',
    'spin': 'Раскрутка', 'taunt': 'Насмешка',
    'death': 'Смерть', 'pain': 'Боль', 'order': 'Команда',
    'mood': 'Настроение', 'spy': 'Шпион', 'other': 'Прочее',
}

@dataclass(frozen=True)
class SoundEntry:
    """Одна запись звукового скрипта."""

    #: Имя записи целиком: `Weapon_Shotgun.Single`.
    name: str
    #: До точки — чей звук.
    subject: str
    #: После точки — какое событие. У реплик там же номер дубля
    #: (`PainSharp01`): по семье он не считается, но в имени остаётся.
    event: str
    #: Семья события: по ней фильтруют.
    family: str
    #: Файлы без служебных приставок, от корня `sound/`. Их бывает несколько:
    #: игра выбирает случайный, и заменять надо все.
    waves: Tuple[str, ...]
    #: Раздел каталога: оружие, реплики, игрок, мир.
    section: str = 'weapon'
    #: Предметы, у которых этот звук прописан в items_game.
    items: Tuple[str, ...] = ()
    #: Классы этих предметов. Пусто — звук общий или стоковый.
    classes: Tuple[str, ...] = ()


def family_of(event: str) -> str:
    """Семья события. `SingleCrit` — крит, `PainSharp01` — боль.

    Номер дубля отбрасываем: реплик каждого положения по полсотни, и семья у
    них одна.
    """
    low = re.sub(r'\d+$', '', event).lower()
    for family, words in _FAMILIES:
        if any(word in low for word in words):
            return family
    return 'other'


def wave_path(raw: str) -> str:
    """Путь файла без служебных приставок Source."""
    return raw.strip().lstrip(_PREFIXES).replace('\\', '/').strip()


def _blocks(text: str) -> List[Tuple[str, str]]:
    """(имя записи, тело) по балансу скобок.

    Регуляркой «до закрывающей» такой блок не взять: внутри лежит `rndwave`
    со своим списком файлов, и первая же скобка оборвала бы запись на нём.
    """
    out: List[Tuple[str, str]] = []
    for head in _ENTRY.finditer(text):
        start = text.index('{', head.start())
        depth, i = 0, start
        while i < len(text):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if not depth:
                    break
            i += 1
        out.append((head.group(1), text[start + 1:i]))
    return out


def parse_script(text: str, section: str = 'weapon') -> List[SoundEntry]:
    """Записи одного звукового скрипта."""
    out: List[SoundEntry] = []
    for name, body in _blocks(text):
        waves = tuple(dict.fromkeys(
            wave_path(value) for key, value in _PAIR.findall(body)
            if key.lower() == 'wave' and wave_path(value)))
        if not waves:
            continue
        subject, _, event = name.partition('.')
        out.append(SoundEntry(
            name=name, subject=subject, event=event,
            family=family_of(event), waves=waves, section=section,
            # У реплики класс стоит прямо в имени — точнее источника нет.
            classes=((subject.lower(),) if subject.lower() in CLASSES else ()),
        ))
    return out


def item_bindings(items_game_text: str) -> Dict[str, Tuple[set, set]]:
    """{имя записи: (предметы, классы)} — из блоков `visuals` в items_game.

    Единственное место, где сказано, ЧЕЙ это звук: имя записи о классе молчит,
    дробовик носят трое.
    """
    from src.data.taunt_catalog import _item_bodies

    out: Dict[str, Tuple[set, set]] = {}
    for body in _item_bodies(items_game_text):
        sounds = re.findall(r'"(sound_[a-z0-9_]+)"\s+"([^"]+)"', body)
        if not sounds:
            continue
        name = re.search(r'"item_name"\s+"([^"]+)"', body)
        title = (name.group(1) if name else '').lstrip('#')
        classes = set(re.findall(
            r'"(scout|soldier|pyro|demoman|heavy|engineer|medic|sniper|spy)"'
            r'\s+"1"', body))
        for _event, entry in sounds:
            items, known = out.setdefault(entry, (set(), set()))
            if title:
                items.add(title)
            known.update(classes)
    return out


def _orphan_files(paks, known: set) -> List[SoundEntry]:
    """Файлы `sound/weapons/`, которых не называет ни одна запись.

    Их полсотни: связку «событие — файл» для части оружия Valve держит в
    зашифрованных `scripts/tf_weapon_*.ctx`, и через записи до этих звуков не
    добраться. Заменяются они всё равно по пути, поэтому показываем их сами по
    себе — иначе часть звуков оружия просто недоступна.
    """
    out: List[SoundEntry] = []
    seen = set()
    for pak in paks:
        for path in pak:
            low = path.lower()
            if not low.startswith(WEAPON_SOUND_DIR):
                continue
            if not low.endswith(('.wav', '.mp3')):
                continue
            wave = path[len('sound/'):]
            if wave in known or wave in seen:
                continue
            seen.add(wave)
            stem = os.path.splitext(os.path.basename(wave))[0]
            out.append(SoundEntry(
                name=wave, subject=stem, event='', family='other',
                waves=(wave,)))
    return out


def load(vpk_paths: Sequence[Optional[str]],
         items_game_path: str = '') -> List[SoundEntry]:
    """Оружейные звуки игры, уже связанные с предметами.

    Returns:
        Пустой список, если скрипт не достался: игры может не быть на месте.
    """
    from src.services import vtf_preview_service as vps

    paks = vps.open_vpks(list(vpk_paths))

    def text(name: str) -> str:
        for pak in paks:
            try:
                return pak[name].read().decode('utf-8', 'replace')
            except KeyError:
                continue
        return ''

    if not text(WEAPON_SCRIPT):
        logger.warning(f"[звук] не достали {WEAPON_SCRIPT}")
        return []

    bound: Dict[str, Tuple[set, set]] = {}
    if items_game_path and os.path.isfile(items_game_path):
        bound = item_bindings(open(items_game_path, encoding='utf-8',
                                   errors='replace').read())

    entries: List[SoundEntry] = []
    known: set = set()
    for section, scripts in SECTIONS.items():
        for script in scripts:
            body = text(script)
            if not body:
                continue
            # Одна и та же запись встречается в двух скриптах (MvM повторяет
            # оружейные): первая побеждает, чтобы раздел не двоился.
            fresh = [e for e in parse_script(body, section)
                     if e.name not in known]
            entries += fresh
            known.update(e.name for e in fresh)

    entries = [
        SoundEntry(**{**entry.__dict__,
                      'items': tuple(sorted(bound[entry.name][0])),
                      'classes': tuple(sorted(bound[entry.name][1]))})
        if entry.name in bound else entry
        for entry in entries]
    entries += _orphan_files(paks, {w for e in entries for w in e.waves})

    by_section: Dict[str, int] = {}
    for entry in entries:
        by_section[entry.section] = by_section.get(entry.section, 0) + 1
    logger.info(f"[звук] записей: {len(entries)} {by_section}, "
                f"с предметом: {sum(1 for e in entries if e.items)}")
    return entries
