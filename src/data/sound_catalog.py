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
сводят в группы (выстрел, перезарядка, удар…): человеку нужен «звук выстрела»,
а не выбор между `Single`, `Fire` и `FireStart`. Словарь групп у каждого
раздела свой — у оружия не бывает боли, у реплик перезарядки.

У трети реплик имя без точки вовсе (`engineer_dominationdemoman03`,
`cm_sniper_pregamelostlast_02`): субъект там — приставка класса, а когда и её
нет, говорящего выдаёт папка файла (`vo/taunts/spy/`).

Кого именно звук озвучивает, точно знает items_game: у предмета в `visuals`
стоит `sound_single_shot` с именем записи. Это единственный надёжный источник
класса — из имени `Weapon_Shotgun` класс не выводится, дробовик носят четверо.
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
#: Valve зовёт оружие в звуках своими рабочими именами: «Латунный монстр» —
#: `Gatling`, «Мачина» — `SniperRailgun`, «Наташа» — `Minifun` (так её и
#: называет items_game у `TF_Unique_Achievement_Minigun`). Ни каталог, ни
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
    'Weapon_AWP': 'AWPer Hand',
    'Weapon_Arrow': 'Huntsman',
    'Weapon_Assassin_Knife': 'Sharp Dresser',
    'Weapon_BarretsArm': 'Short Circuit',
    'Weapon_Ball': 'Sandman',
    'Weapon_BaseballBat': 'Sandman',
    'Weapon_Bison': 'Righteous Bison',
    'Weapon_BuffBanner': 'Buff Banner',
    'Weapon_Club': 'Kukri',
    'Weapon_CompoundBow': 'Huntsman',
    'Weapon_Fist': 'Fists',
    'Weapon_Gatling': 'Brass Beast',
    'Weapon_Katana': 'Half-Zatoichi',
    'Weapon_LooseCannon': 'Loose Cannon',
    'Weapon_MetalGloves': 'Fists of Steel',
    'Weapon_Minifun': 'Natascha',
    'Weapon_QuakeRPG': 'Original',
    'Weapon_RPG': 'Rocket Launcher',
    'Weapon_RescueRanger': 'Rescue Ranger',
    'Weapon_Slap': 'Hot Hand',
    'Weapon_SniperRailgun': 'Machina',
    'Weapon_Sword': 'Eyelander',
    'Weapon_bm_throwable': 'Mutated Milk',
    'Weapon_mittens': 'Holiday Punch',
}

#: Слово субъекта → токен локализации постройки. У построек нет предмета в
#: каталоге оружия, а имя в игре есть: «Турель», а не «Building Sentrygun».
BUILDING_TOKENS: Dict[str, str] = {
    'sentry': 'TF_Object_Sentry', 'sentrygun': 'TF_Object_Sentry',
    'minisentrygun': 'TF_Object_Sentry', 'dispenser': 'TF_Object_Dispenser',
    'teleporter': 'TF_Object_Tele', 'sapper': 'TF_Object_Sapper',
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


def icon_for(subject: str, section: str = '', who: str = '') -> str:
    """Картинка по субъекту записи, иначе по говорящему, иначе по разделу.

    Субъект раньше говорящего: у `Building_Sentrygun` говорящий — инженер,
    а картинка нужна турели. Класс в субъекте проверяется по полному
    совпадению: `Scout` — это класс, а `scout_taunt_dosido_intro` — имя
    файла, и чей это голос, решает `speaker_of`, а не подстрока.
    """
    low = (subject or '').lower()
    if low in CLASSES:
        return CLASS_ICON.format(low)
    for word, icon in SUBJECT_ICONS:
        if word in low and icon != ALL_CLASS_ICON:
            return icon
    if who in CLASSES:
        return CLASS_ICON.format(who)
    # Значок «все классы» — последняя догадка по субъекту: у `taunt_yeti_spy`
    # говорящий известен, и портрет шпиона точнее.
    for word, icon in SUBJECT_ICONS:
        if word in low:
            return icon
    return SECTION_ICONS.get(section, '')


#: Папка, файлы которой считаем оружейными.
WEAPON_SOUND_DIR = 'sound/weapons/'

#: Начало записи: имя в кавычках и скобка на следующей строке.
_ENTRY = re.compile(r'^"([^"]+)"\s*\r?\n\s*\{', re.M)
_PAIR = re.compile(r'"(\w+)"\s+"([^"]*)"')
_BRACE = re.compile(r'[{}]')

#: Служебные приставки пути в Source: пространственный звук, поток, без потерь.
#: К файлу они не относятся — на диске его зовут без них.
_PREFIXES = ')(}$!?@#^*<>'

#: Как Valve сокращает классы в именах файлов и записей: `cm_engie_…`,
#: `demo_taunt_…`, `snipes_taunt_…`.
CLASS_ALIASES: Dict[str, str] = {
    'demo': 'demoman', 'engie': 'engineer', 'engy': 'engineer',
    'eng': 'engineer', 'snipes': 'sniper', 'heavyweapons': 'heavy',
}

#: Говорящие, которые не классы. Ключ — то, что уходит в фильтр «кто».
#: `other` — всё, чьего голоса мы не узнали: строке нужен хоть какой-то ключ,
#: иначе под фильтром до неё не добраться.
WHO_NAMES: Dict[str, str] = {
    'announcer': 'Диктор', 'pauling': 'Мисс Полинг',
    'halloween': 'Хэллоуин', 'wheatley': 'Ап-Сап', 'other': 'Прочие',
}

#: Субъект записи (в нижнем регистре) → говорящий, когда это не класс.
#: `AttackDefend.EnemyStolen` и `CaptureFlag.*` — объявления диктора о
#: разведданных, `sf14` — Мерасмус на карте 2014 года, `PSap` — жучок-болтун.
_SUBJECT_WHO: Dict[str, str] = {
    'announcer': 'announcer', 'attackdefend': 'announcer',
    'captureflag': 'announcer', 'controlpoint': 'announcer',
    'invade': 'announcer', 'resource': 'announcer', 'rd': 'announcer',
    'halloween': 'halloween', 'merasmus': 'halloween', 'sf14': 'halloween',
    'sf15': 'halloween', 'bcon': 'halloween',
    'psap': 'wheatley',
    'plng': 'pauling', 'toughbreak': 'pauling',
}

#: Папка файла → говорящий. Имя записи о голосе молчит у трети реплик
#: (`taunt_yeti_spy`, `true_scotsmans_music`), а путь к файлу Valve кладёт
#: последовательно: `vo/taunts/spy/`, `vo/pauling/`, `vo/halloween_merasmus/`.
_WAVE_WHO: Tuple[Tuple[str, str], ...] = (
    ('vo/announcer', 'announcer'), ('vo/intel_', 'announcer'),
    ('vo/invade_', 'announcer'), ('vo/mvm_', 'announcer'),
    ('vo/pauling/', 'pauling'), ('vo/toughbreak/', 'pauling'),
    ('vo/halloween', 'halloween'), ('vo/items/wheatley', 'wheatley'),
)

#: Группы событий — свой словарь у каждого раздела. Общий список не работал:
#: у оружия «charge» — раскрутка щита, у медика — убер, у диктора — захват.
#:
#: Проверяется ПО СЛОВАМ, а не по вхождению: «GoLoop» — это не команда «Go»,
#: «NoTarget» — не «No», «Removed» — не «Move». Слово короче пяти букв
#: совпадает только целиком; длиннее — и как часть имени, потому что у
#: трети реплик оно записано без разделителей (`engineer_dominationdemoman03`).
#: Порядок важен: первое совпадение побеждает.
_GROUPS: Dict[str, Tuple[Tuple[str, Tuple[str, ...]], ...]] = {
    'weapon': (
        # Хитсаунд — раньше удара: «HitSoundNotes» иначе уходил в «Удар».
        ('hitsound', ('hitsound', 'killsound')),
        ('build', ('build', 'built', 'building', 'sentry', 'dispenser',
                   'teleporter', 'sapper')),
        ('crit', ('crit',)),
        ('explode', ('explode', 'explosion', 'blast', 'detonate', 'dud',
                     'timer', 'fizzle')),
        ('reload', ('reload', 'bolt', 'clip', 'empty', 'cock', 'load',
                    'pump', 'shells', 'tube', 'drum')),
        ('hit', ('hit', 'flesh', 'impact', 'swing', 'miss', 'smash',
                 'backstab', 'slap', 'punch', 'nearmiss', 'bounce',
                 'ricochet', 'break', 'ouch', 'damage', 'push')),
        ('fire', ('single', 'fire', 'shoot', 'shot', 'burst', 'launch',
                  'throw', 'altfire', 'attack', 'zap', 'pull', 'strum',
                  'scoped')),
        # Лечение раньше раскрутки: «Charged» у медигана — это убер.
        ('heal', ('heal', 'healing', 'healer', 'medigun', 'protection',
                  'invulnerable', 'uber', 'buff', 'buffed', 'horn', 'flag',
                  'power', 'resist', 'drain', 'charged')),
        ('spin', ('windup', 'winddown', 'wind', 'spin', 'charg', 'boosters',
                  'pressure', 'reel', 'idle', 'pilot', 'accelerate',
                  'decelerate')),
        ('draw', ('draw', 'deploy', 'holster', 'raise', 'lower', 'switch',
                  'inspect', 'open', 'ready', 'grab', 'catch')),
    ),
    'voice': (
        # Хэллоуин первым: боль босса — это реплика босса, а не «Боль».
        # `sf12_badmagic` — цифры не слово, от приставки остаётся `sf`.
        ('halloween', ('sf', 'hall', 'halloween', 'helltower', 'merasmus',
                       'spell', 'magic', 'skeleton', 'monoculus',
                       'headless', 'eyeball', 'ghost', 'haunted',
                       'bombinomicon', 'bcon', 'wheel', 'hell', 'wolf',
                       'bumper', 'kart', 'plumes', 'scream', 'boo',
                       'pumpkin')),
        ('mvm', ('mvm', 'robot', 'spybot', 'giant', 'sentrybuster')),
        ('comp', ('cm', 'comp', 'rankup', 'pregame', 'gamewon',
                  'gamelost', 'gametie', 'matchmaking')),
        ('contract', ('contract', 'plng', 'toughbreak')),
        ('death', ('death', 'dying', 'die')),
        ('pain', ('pain', 'painsharp', 'painsevere', 'hurt', 'onfire',
                  'beingshot')),
        ('domination', ('domination', 'revenge', 'nemesis')),
        ('laugh', ('laugh', 'giggle')),
        ('order', ('medic', 'helpme', 'incoming', 'headleft', 'headright',
                   'moveup', 'goodjob', 'niceshot', 'thanks', 'cheers',
                   'jeers', 'positive', 'negative', 'battlecry',
                   'activatecharge', 'sentryahead', 'needdispenser',
                   'needsentry', 'needteleporter', 'cloakedspy',
                   'spyidentify', '=yes', '=no', '=go', 'help')),
        ('taunt', ('taunt', 'sandwich', 'eyelander', 'highfive', 'conga',
                   'kazotsky', 'rps', 'flip', 'dosido', 'aerobic', 'yeti',
                   'headbutt', 'nuke', 'burp', 'lollichop', 'singing',
                   'music', 'fanfare')),
    ),
    'player': (
        ('holiday', ('halloween', 'bomb', 'crocs', 'geiger', 'fundraiser',
                     'summer', 'xmas', 'christmas', 'souls', 'isnowit',
                     'youareit', 'taggedotherit', 'samurai', 'banshee')),
        ('taunt', ('taunt', 'guitar', 'boombox', 'vuvezela', 'jingle',
                   'broomfly', 'disco', 'hawk', 'bell', 'music')),
        ('pda', ('pda',)),
        ('selection', ('selection', 'ready')),
        ('damage', ('pain', 'death', 'hit', 'crit', 'damage', 'drown',
                    'fall', 'gib', 'burn', 'fire', 'flame', 'impact',
                    'decapitated', 'dissolve', 'stun', 'resistance',
                    'donk')),
        ('status', ('invulnerable', 'megaheal', 'quickfix', 'recharged',
                    'saveme', 'cloak', 'disguise', 'shield', 'spawn',
                    'freezecam', 'highfive', 'dodge', 'shove', 'swim',
                    'wade', 'underwater', 'jump', 'whistle')),
        ('ui', ('weaponselection', 'weaponselected', 'deny', 'pickup',
                'autocaller', 'hud')),
    ),
    'world': (
        ('mvm', ('mvm', 'robot', 'grinder', 'tank')),
        ('holiday', ('halloween', 'merasmus', 'skeleton', 'spell', 'yeti',
                     'christmas', 'gift', 'summer', 'fireworks', 'hell',
                     'wheel', 'pumpkin', 'medieval', 'eyeball')),
        ('music', ('music',)),
        ('ui', ('hud', 'hudchat', 'ui', 'vote', 'chat', 'matchmaking', 'quest',
                'cyoa', 'achievement', 'replay', 'camera', 'demosupport',
                'panel', 'credits', 'projector', 'training', 'warpaint')),
        ('ambient', ('ambient', 'ambience', 'sawmill', 'nucleus', 'harbor',
                     'hugedoor', 'door', 'portcullis', 'belltower', 'tv',
                     'duck', 'train', 'siren', 'lair')),
        ('steps', ('step', 'cleats', 'ladder')),
        ('physics', ('impact', 'scrape', 'roll', 'strain', 'break',
                     'breakable', 'bounce', 'shatter', 'splash', 'water',
                     'burning', 'engulf', 'shell', 'shrapnel', 'spark',
                     'stick', 'wade', 'swim')),
        ('match', ('game', 'cart', 'powerup', 'mannpower', 'passtime',
                   'doomsday', 'tournament', 'healthkit', 'ammopack',
                   'grenadepack', 'regenerate', 'changeclass', 'item',
                   'equipment', 'upgrade', 'hologram', 'materialize',
                   'weapondrop', 'domination', 'revenge', 'killstreak',
                   'nemesis', 'overtime', 'stalemate', 'suddendeath',
                   'teamwon', 'teamlost', 'death', 'civilian')),
    ),
}

#: Подписи групп. Ключ уходит в фильтр, подпись видит человек. Ключи общие
#: на все разделы: «taunt» в реплике и в звуках игрока — одно и то же слово.
GROUP_NAMES: Dict[str, str] = {
    # Оружие
    'fire': 'Выстрел', 'crit': 'Крит', 'reload': 'Перезарядка',
    'hit': 'Удар', 'draw': 'Достать', 'explode': 'Взрыв',
    'spin': 'Раскрутка', 'heal': 'Лечение', 'build': 'Постройки',
    'hitsound': 'Хитсаунд',
    # Реплики
    'order': 'Команды', 'auto': 'Автореплики', 'death': 'Смерть',
    'pain': 'Боль', 'domination': 'Доминация', 'laugh': 'Смех',
    'taunt': 'Насмешки', 'comp': 'Соревновательный', 'mvm': 'MvM',
    'halloween': 'Хэллоуин', 'match': 'Ход матча', 'contract': 'Контракты',
    # Игрок и мир
    'holiday': 'Праздники', 'pda': 'КПК', 'selection': 'Выбор класса',
    'damage': 'Урон', 'status': 'Состояние', 'ui': 'Интерфейс',
    'music': 'Музыка', 'ambient': 'Окружение', 'steps': 'Шаги',
    'physics': 'Физика',
    'other': 'Прочее',
}

#: Чем считать не подошедшую ни под одно слово запись — зависит от того, кто
#: говорит. У класса всё, что не команда и не боль, — реакция на событие
#: («захватил точку», «убер готов»); у диктора — ход матча.
_FALLBACK_WHO: Dict[str, str] = {'announcer': 'match'}

#: Варианты записи: обычная и роботизированный дубль для MvM. Ключ уходит в
#: фильтр.
VARIANT_NAMES: Dict[str, str] = {'normal': 'Обычные', 'mvm': 'Роботы MvM'}

#: Формат файлов записи: по нему игра выбирает читалку, и свой файл обязан
#: совпасть (см. сборку). Смешанные записи — где вперемешку — подходят под
#: любой из двух фильтров.
FORMAT_NAMES: Dict[str, str] = {'wav': 'WAV', 'mp3': 'MP3'}


@dataclass(frozen=True)
class SoundEntry:
    """Одна запись звукового скрипта."""

    #: Имя записи целиком: `Weapon_Shotgun.Single`.
    name: str
    #: До точки — чей звук.
    subject: str
    #: После точки — какое событие. У реплик там же номер дубля
    #: (`PainSharp01`): по группе он не считается, но в имени остаётся.
    event: str
    #: Группа события: по ней фильтруют.
    group: str
    #: Файлы без служебных приставок, от корня `sound/`. Их бывает несколько:
    #: игра выбирает случайный, и заменять надо все.
    waves: Tuple[str, ...]
    #: Раздел каталога: оружие, реплики, игрок, мир.
    section: str = 'weapon'
    #: Кто звучит: классы или говорящий из `WHO_NAMES`. Из имени записи, из
    #: приставки файла или из пути к нему. Пусто — не узнали.
    who: Tuple[str, ...] = ()
    #: Роботизированный дубль реплики для MvM (`Scout.MVM_Go01`).
    mvm: bool = False
    #: Предметы, у которых этот звук прописан в items_game.
    items: Tuple[str, ...] = ()
    #: Классы этих предметов. Пусто — звук общий или стоковый.
    classes: Tuple[str, ...] = ()
    #: Дубли одной реплики, свёрнутые в эту запись (`Scout.Go01`…`Go08` →
    #: `Scout.Go`): имя записи игры для КАЖДОГО файла, по порядку `waves`
    #: (у дубля бывает и несколько файлов). Пусто — запись настоящая.
    takes: Tuple[str, ...] = ()
    #: Как игра играет запись: канал, громкость, уровень, высота — как в
    #: скрипте. Свой файл зазвучит с теми же значениями, и знать их полезно.
    channel: str = ''
    volume: str = ''
    level: str = ''
    pitch: str = ''


def words_of(text: str) -> List[str]:
    """Слова имени: `CartMovingForward_01` → cart, moving, forward.

    Границей служит и смена регистра, и разделитель, и цифра. Регулярка «а
    потом Б» ловит обычный CamelCase, вторая — стык аббревиатуры со словом
    (`RPGDraw` → rpg, draw).
    """
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text or '')
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)
    return [w for w in re.split(r'[^A-Za-z]+', text.lower()) if w]


def _compile(rules) -> List[Tuple[str, frozenset, Tuple[str, ...], Tuple[str, ...]]]:
    """Словарь раздела → (группа, целые слова, части имени, единственные).

    Слово совпадает целиком; от пяти букв — и как часть склеенного имени:
    короче нельзя, «comp» иначе находился в «completed», «hell» — в «shell».
    С `=` — событие состоит из этого слова и только из него: команда «No» —
    это `No01`, а не `NoTarget`.
    """
    out = []
    for group, keywords in rules:
        whole = frozenset(k for k in keywords if not k.startswith('='))
        parts = tuple(k for k in whole if len(k) >= 5)
        only = tuple(k[1:] for k in keywords if k.startswith('='))
        out.append((group, whole, parts, only))
    return out


_COMPILED = {section: _compile(rules) for section, rules in _GROUPS.items()}


def _group_by_words(section: str, words: List[str]) -> str:
    bag = frozenset(words)
    joined = ''.join(words)
    for group, whole, parts, only in _COMPILED.get(section, ()):
        if (bag & whole or any(p in joined for p in parts)
                or (len(words) == 1 and words[0] in only)):
            return group
    return ''


#: Разделы, где о группе говорит субъект, а не событие: `Taunt.SoldierShotgunFire`
#: — реквизит насмешки, а не выстрел; `MVM.GiantHeavyStep` — MvM, а не шаги.
_SUBJECT_FIRST = frozenset(('player', 'world'))


def group_of(section: str, subject: str, event: str,
             who: Tuple[str, ...] = ()) -> str:
    """Группа записи: `SingleCrit` — крит, `PainSharp01` — боль.

    У оружия и реплик событие важнее субъекта: `Weapon_BuffBanner.Draw` — это
    «достать», а не «лечение». Субъект-класс (`Medic.AutoChargeReady`) о
    группе не говорит вовсе — иначе всё у медика было бы командой «Medic!».
    """
    low = (subject or '').lower()
    if section == 'weapon' and low.startswith('building'):
        return 'build'
    by_event = _group_by_words(section, words_of(event))
    by_subject = ('' if low in CLASSES
                  else _group_by_words(section, words_of(subject)))
    found = ((by_subject or by_event) if section in _SUBJECT_FIRST
             else (by_event or by_subject))
    if found:
        return found
    for one in who:
        if one in CLASSES and section == 'voice':
            return 'auto'
        if one in _FALLBACK_WHO:
            return _FALLBACK_WHO[one]
    return 'other'


def _class_in(words: List[str]) -> str:
    """Класс среди слов, с учётом сокращений Valve. Пусто — нет."""
    for w in words:
        w = CLASS_ALIASES.get(w, w)
        if w in CLASSES:
            return w
    return ''


#: Слова субъекта, за которыми стоит инженер: постройки — его.
_ENGINEER_WORDS = frozenset(('building', 'sentry', 'sentrygun',
                             'minisentrygun', 'dispenser', 'teleporter'))


def speaker_of(subject: str, name: str,
               waves: Tuple[str, ...]) -> Tuple[str, ...]:
    """Кто звучит: класс или говорящий из `WHO_NAMES`. Пусто — не узнали.

    От точного к догадке: субъект записи, слова её имени, путь к файлу.
    `Spy.DominationScout01` — шпион, хотя в имени есть и разведчик: субъект
    проверяется первым и целиком.
    """
    low = (subject or '').lower()
    if low in CLASSES:
        return (low,)
    if low in _SUBJECT_WHO:
        return (_SUBJECT_WHO[low],)
    if _ENGINEER_WORDS & set(words_of(subject)):
        return ('engineer',)
    words = words_of(name)
    # Приставка говорящего раньше класса в словах: `plng_give_contract_demo`
    # говорит Полинг, а подрывник в имени — кому она даёт контракт.
    for w in words[:2]:
        if w in _SUBJECT_WHO:
            return (_SUBJECT_WHO[w],)
    found = _class_in(words)
    if found:
        return (found,)
    for wave in waves[:1]:
        path = wave.lower().lstrip('/')
        for prefix, who in _WAVE_WHO:
            if path.startswith(prefix):
                return (who,)
        # `vo/scout_go01.mp3`, `vo/taunts/scout/…`, `vo/mvm/norm/heavy_…`,
        # `vo/compmode/cm_engie_…` — класс стоит в имени папки или файла.
        if path.startswith('vo/'):
            found = _class_in(words_of(path[3:])[:4])
            if found:
                return (found,)
    return ()


def split_name(name: str) -> Tuple[str, str]:
    """(субъект, событие). У имени без точки субъект — приставка класса.

    `Weapon_Shotgun.Single` → (Weapon_Shotgun, Single);
    `cm_scout_gamewon_01` → (cm_scout, gamewon_01);
    `taunt_yeti_spy` → (taunt_yeti_spy, '') — приставки класса нет.
    """
    if '.' in name:
        subject, _, event = name.partition('.')
        return subject, event
    m = re.match(r'^((?:cm_)?[a-z]+)_(.+)$', name, re.I)
    if m and _class_in(words_of(m.group(1))):
        return m.group(1), m.group(2)
    return name, ''


#: Папка роботизированных дублей реплик. Имя записи признаком не годится:
#: `heavy_mvm_ask_ready01` — обычная реплика пулемётчика «вы готовы?» в MvM,
#: а `Heavy.MVM_Go01` — тот же «Go!», но голосом робота, и лежит он здесь.
MVM_VOICE_DIR = 'vo/mvm/'


def is_mvm_take(waves: Tuple[str, ...]) -> bool:
    """Роботизированный дубль реплики для MvM."""
    return bool(waves) and all(
        w.lower().lstrip('/').startswith(MVM_VOICE_DIR) for w in waves)


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
        depth = 0
        for brace in _BRACE.finditer(text, start):
            depth += 1 if brace.group() == '{' else -1
            if not depth:
                out.append((head.group(1), text[start + 1:brace.start()]))
                break
    return out


def parse_script(text: str, section: str = 'weapon') -> List[SoundEntry]:
    """Записи одного звукового скрипта."""
    out: List[SoundEntry] = []
    for name, body in _blocks(text):
        pairs = _PAIR.findall(body)
        waves = tuple(dict.fromkeys(
            wave_path(value) for key, value in pairs
            if key.lower() == 'wave' and wave_path(value)))
        # Заглушки тишины (`misc/null.wav`) — не звук, а «ничего»: одна на
        # полтора десятка записей, и подменив её у одной, подменишь у всех.
        if not waves or all(is_silence(w) for w in waves):
            continue
        props = {key.lower(): value.strip() for key, value in pairs}
        out.append(make_entry(name, waves, section, props))
    return out


def is_silence(wave: str) -> bool:
    """Файл-заглушка: `misc/null.wav`, `common/null.wav`, `vo/null.mp3`."""
    return os.path.basename(wave).lower().split('.')[0] == 'null'


def make_entry(name: str, waves: Tuple[str, ...], section: str = 'weapon',
               props: Optional[Dict[str, str]] = None) -> SoundEntry:
    """Запись со всем, что выводится из её имени и файлов."""
    props = props or {}
    subject, event = split_name(name)
    # У звуков мира говорящего нет: `MVM.GiantHeavyStep` — шаги робота, а не
    # реплика диктора, и фильтр «кто» в этом разделе только путал бы.
    who = () if section == 'world' else speaker_of(subject, name, waves)
    # У дубля приставка `MVM_` в группе не участвует: `Scout.MVM_Go01` — та
    # же команда «Go!», только голосом робота.
    mvm = is_mvm_take(waves)
    bare = event[4:] if mvm and event[:4].upper() == 'MVM_' else event
    return SoundEntry(
        name=name, subject=subject, event=event,
        group=group_of(section, subject, bare, who), waves=waves,
        section=section, who=who, mvm=mvm,
        # У реплики класс стоит прямо в имени — точнее источника нет.
        classes=tuple(w for w in who if w in CLASSES),
        channel=props.get('channel', ''), volume=props.get('volume', ''),
        level=props.get('soundlevel', ''), pitch=props.get('pitch', ''),
    )


#: Имя с номером дубля на конце: `Scout.Go01`, `taunt_demo_rps_win_08`.
_TAKE = re.compile(r'^(.*\D)(\d+)$')


def fold_takes(entries: List[SoundEntry]) -> List[SoundEntry]:
    """Сворачивает пронумерованные дубли в одну запись с их файлами.

    `Scout.Go01`…`Go08` — восемь записей по одному файлу, и это одна реплика
    «Go!»: игра берёт любой из дублей. Заменять их по одному — восемь раз
    выбрать файл; в одной записи это один клик, а по одному по-прежнему
    можно через файлы записи. Реплик так вчетверо меньше.

    Не сворачиваем, если стебель уже занят настоящей записью
    (`Building_Sentrygun.Fire` рядом с `Fire2`): подменять её собой нельзя.
    """
    names = {e.name for e in entries}
    groups: Dict[Tuple[str, str], List[SoundEntry]] = {}
    for entry in entries:
        m = _TAKE.match(entry.name)
        if not m or entry.name.lower().endswith(('.wav', '.mp3')):
            continue
        stem = m.group(1).rstrip('_')
        if stem in names or not stem:
            continue
        groups.setdefault((entry.section, stem), []).append(entry)

    folded: Dict[str, SoundEntry] = {}
    member: Dict[str, str] = {}
    for (section, stem), takes in groups.items():
        if len(takes) < 2:
            continue
        first = takes[0]
        subject, event = split_name(stem)
        by_wave = {}
        for take in takes:
            for w in take.waves:
                by_wave.setdefault(w, take.name)
        folded[stem] = SoundEntry(
            name=stem, subject=subject, event=event, group=first.group,
            waves=tuple(by_wave), section=section, who=first.who,
            mvm=all(t.mvm for t in takes),
            items=tuple(sorted({i for t in takes for i in t.items})),
            classes=tuple(sorted({c for t in takes for c in t.classes})),
            takes=tuple(by_wave.values()),
            channel=first.channel, volume=first.volume, level=first.level,
            pitch=first.pitch)
        member.update({t.name: stem for t in takes})

    out: List[SoundEntry] = []
    seen: set = set()
    for entry in entries:
        stem = member.get(entry.name)
        if stem is None:
            out.append(entry)
        elif stem not in seen:
            seen.add(stem)
            out.append(folded[stem])
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
                name=wave, subject=stem, event='',
                group=group_of('weapon', stem, ''), waves=(wave,)))
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
            # оружейные): первая побеждает, чтобы раздел не двоился. Внутри
            # одного скрипта тоже бывают повторы (`Weapon_BoneSaw.Miss`
            # дважды) — там побеждает последняя, как у движка.
            fresh = list({e.name: e for e in parse_script(body, section)
                          if e.name not in known}.values())
            entries += fresh
            known.update(e.name for e in fresh)

    entries = [
        SoundEntry(**{**entry.__dict__,
                      'items': tuple(sorted(bound[entry.name][0])),
                      'classes': tuple(sorted(bound[entry.name][1]))})
        if entry.name in bound else entry
        for entry in entries]
    entries = fold_takes(entries)
    entries += _orphan_files(paks, {w for e in entries for w in e.waves})

    by_section: Dict[str, int] = {}
    for entry in entries:
        by_section[entry.section] = by_section.get(entry.section, 0) + 1
    logger.info(f"[звук] записей: {len(entries)} {by_section}, "
                f"с предметом: {sum(1 for e in entries if e.items)}")
    return entries
