from typing import Optional

TF2_WEAPONS = {
    "Scout": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_scattergun": {"ru": "Стандартное Обрез", "en": "Scattergun"},
            "c_double_barrel": {"ru": "Неумолимая сила", "en": "Force-A-Nature"},
            "c_shortstop": {"ru": "Прерыватель", "en": "Shortstop"},
            "c_soda_popper": {"ru": "Газировщик", "en": "Soda Popper"},
            "c_pep_scattergun": {"ru": "Обрез Малыша", "en": "Baby Face's Blaster"},
            "c_scatterdrum": {"ru": "Спинобрез", "en": "Back Scatter"}
        },
        "Secondary": {
            "c_pistol": {"ru": "Стандартный Пистолет", "en": "Pistol"},
            "c_ttg_max_gun": {"ru": "Люгерморф", "en": "Lugermorph"},
            "c_invasion_pistol": {"ru": "З.А.Х.В.А.Т.Ч.И.К.", "en": "C.A.P.P.E.R"},
            "c_sd_cleaver": {"ru": "Окрыленный", "en": "Flying Guillotine"},
            "c_energy_drink": {"ru": "Дамский пистолет Красавчика", "en": "Bonk! Atomic Punch"},
            "c_madmilk": {"ru": "Зломолоко", "en": "Mad Milk"},
            "c_winger_pistol": {"ru": "Дрёма", "en": "Winger"},
            "c_pep_pistol": {"ru": "Критокола", "en": "Crit-A-Cola"}
        },
        "Melee": {
            "c_bat": {"ru": "Стандартная Бита", "en": "Bat"},
            "c_wooden_bat": {"ru": "Поддай леща", "en": "Sandman"},
            "c_holymackerel": {"ru": "Голая рука", "en": "Holy Mackerel"},
            "c_bonk_bat": {"ru": "Световая бита", "en": "Atomizer"},
            "c_candy_cane": {"ru": "Карамельная трость", "en": "Candy Cane"},
            "c_boston_basher": {"ru": "Бостонский раздолбай", "en": "Boston Basher"},
            "c_scout_sword": {"ru": "Трехрунный меч", "en": "Three-Rune Blade"},
            "c_rift_fire_mace": {"ru": "Солнце на палочке", "en": "Sun-On-A-Stick"},
            "c_xms_giftwrap": {"ru": "Обёрточный убийца", "en": "Wrap Assassin"},
            "c_invasion_bat": {"ru": "Веер войны", "en": "The Batsaber"}
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "Soldier": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_rocketlauncher": {"ru": "Стандартное Ракетомёт", "en": "Rocket Launcher"},
            "c_bet_rocketlauncher": {"ru": "Прародитель", "en": "Original"},
            "c_directhit": {"ru": "Прямое попадание", "en": "Direct Hit"},
            "c_blackbox": {"ru": "Чёрный ящик", "en": "Black Box"},
            "c_dumpster_device": {"ru": "Тренировочный ракетомёт", "en": "Beggar's Bazooka"},
            "c_liberty_launcher": {"ru": "Освободитель", "en": "Liberty Launcher"},
            "c_drg_cowmangler": {"ru": "Линчеватель скота 5000", "en": "Cow Mangler 5000"},
            "c_atom_launcher": {"ru": "Авиаудар", "en": "Air Strike"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Shotgun"},
            "c_reserve_shooter": {"ru": "Офицер запаса", "en": "Reserve Shooter"},
            "c_batt_buffpack": {"ru": "Вдохновляющее знамя", "en": "Buff Banner"},
            "c_rocketboots_soldier": {"ru": "Штурмботинки", "en": "Gunboats"},
            "c_shogun_warpack": {"ru": "Поддержка батальона", "en": "Battalion's Backup"},
            "c_drg_righteousbison": {"ru": "Благочестивый бизон", "en": "Righteous Bison"},
            "tankerboots": {"ru": "Людодавы", "en": "Mantreads"},
            "c_paratrooper_pack": {"ru": "Парашютист", "en": "B.A.S.E Jumper"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"}
        },
        "Melee": {
            "c_shovel": {"ru": "Стандартная Лопата", "en": "Shovel"},
            "c_pickaxe_s2": {"ru": "Уравнитель", "en": "Equalizer"},
            "c_shogun_katana_soldier": {"ru": "Полудзатоити", "en": "Half-Zatoichi"},
            "c_riding_crop": {"ru": "Дисциплинарное взыскание", "en": "Disciplinary Action"},
            "c_market_gardener": {"ru": "Землекоп", "en": "Market Gardener"},
            "c_pickaxe": {"ru": "План эвакуации", "en": "Escape Plan"}
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "Pyro": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_flamethrower": {"ru": "Стандартное Огнемёт", "en": "Flamethrower"},
            "c_rainblower": {"ru": "Радужигатель", "en": "Rainblower"},
            "c_ai_flamethrower": {"ru": "Ностромский пламемет", "en": "Nostromo Napalmer"},
            "c_backburner": {"ru": "Дожигатель", "en": "Backburner"},
            "c_degreaser": {"ru": "Чистильщик", "en": "Degreaser"},
            "c_drg_phlogistinator": {"ru": "Флогистонатор", "en": "Phlogistinator"},
            "c_flameball": {"ru": "Ярость дракона", "en": "Dragon's Fury"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Shotgun"},
            "c_reserve_shooter": {"ru": "Офицер запаса", "en": "Reserve Shooter"},
            "c_flaregun_pyro": {"ru": "Ракетница", "en": "Flare Gun"},
            "c_detonator": {"ru": "Детонатор", "en": "Detonator"},
            "c_scorch_shot": {"ru": "Людоплав", "en": "Scorch Shot"},
            "c_rocketpack": {"ru": "Обжигающий выстрел", "en": "Thermal Thruster"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"}
        },
        "Melee": {
            "c_fireaxe": {"ru": "Стандартный Пожарный топор", "en": "Fire Axe"},
            "c_axtinguisher_pyro": {"ru": "Огнетопор", "en": "Axtinguisher"},
            "c_mailbox": {"ru": "Почтовый дебошир", "en": "Postal Pummeler"},
            "c_powerjack": {"ru": "Крушитель", "en": "Powerjack"},
            "c_sledgehammer": {"ru": "Молот", "en": "Homewrecker"},
            "c_back_scratcher": {"ru": "Спиночёс", "en": "Back Scratcher"},
            "c_drg_thirddegree": {"ru": "Третья степень", "en": "Third Degree"},
            "c_sd_neonsign": {"ru": "Неоновый аннигилятор", "en": "Neon Annihilator"},
            "c_slapping_glove": {"ru": "Горячая рука", "en": "Hot Hand"},
            "c_lollichop": {"ru": "Заостренный осколок вулкана", "en": "Lollichop"}
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "Demoman": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_grenadelauncher": {"ru": "Стандартное Гранатомёт", "en": "Grenade Launcher"},
            "c_lochnload": {"ru": "Подкидыш", "en": "Loch-N-Load"},
            "demo_booties": {"ru": "Ботиночки Али-Бабы", "en": "Ali Baba's Wee Booties"},
            "pegleg": {"ru": "Бутлегер", "en": "Bootlegger"},
            "c_demo_cannon": {"ru": "Пушка без лафета", "en": "Loose Cannon"},
            "c_quadball": {"ru": "Железный бомбардир", "en": "Iron Bomber"}
        },
        "Secondary": {
            "c_stickybomb_launcher": {"ru": "Стандартное Липучкомёт", "en": "Stickybomb Launcher"},
            "c_scottish_resistance": {"ru": "Шотландское сопротивление", "en": "Scottish Resistance"},
            "c_sticky_jumper": {"ru": "Штурмовой щит", "en": "Sticky Jumper"},
            "c_targe": {"ru": "Роскошное прикрытие", "en": "Chargin' Targe"},
            "c_persian_shield": {"ru": "Верный штурвал", "en": "Splendid Screen"},
            "c_kingmaker_sticky": {"ru": "Быстромёт", "en": "Quickiebomb Launcher"}
        },
        "Melee": {
            "c_bottle": {"ru": "Стандартная Бутылка", "en": "Bottle"},
            "c_claymore": {"ru": "Одноглазый горец", "en": "Eyelander"},
            "c_battleaxe": {"ru": "Секира Пешего всадника без головы", "en": "Scotsman's Skullcutter"},
            "c_headtaker": {"ru": "Шотландский головорез", "en": "Horseless Headless Horsemann's Headtaker"},
            "c_caber": {"ru": "Аллапульское бревно", "en": "Ullapool Caber"},
            "c_claidheamohmor": {"ru": "Клеймор", "en": "Claidheamh Mòr"},
            "c_shogun_katana": {"ru": "Полудзатоити", "en": "Half-Zatoichi"},
            "c_demo_sultan_sword": {"ru": "Персидский заклинатель", "en": "Persian Persuader"}
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "Heavy": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_minigun": {"ru": "Стандартное Пулемёт", "en": "Minigun"},
            "c_iron_curtain": {"ru": "Железный занавес", "en": "Iron Curtain"},
            "c_minigun_natascha": {"ru": "Наташа", "en": "Natascha"},
            "c_gatling_gun": {"ru": "Латунный монстр", "en": "Brass Beast"},
            "c_tomislav": {"ru": "Томислав", "en": "Tomislav"},
            "c_canton": {"ru": "Огненный дракон", "en": "Huo-Long Heater"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Shotgun"},
            "c_sandwich": {"ru": "Бутерброд", "en": "Sandvich"},
            "c_chocolate": {"ru": "Плитка «Далокош»", "en": "Dalokohs Bar"},
            "c_fishcake": {"ru": "Рыбный батончик", "en": "Fishcake"},
            "c_buffalo_steak": {"ru": "Бутерброд из мяса буйвола", "en": "Buffalo Steak Sandvich"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"},
            "c_banana": {"ru": "Утешительный банан", "en": "Second Banana"},
            "c_robo_sandwich": {"ru": "Робо-бутерброд", "en": "Robo-Sandvich"}
        },
        "Melee": {
            "c_sr3_punch": {"ru": "Стандартные Кулаки", "en": "Apoco-Fists"},
            "c_fists_of_steel": {"ru": "Кулакопокалипсис", "en": "Fists Of Steel"},
            "c_boxing_gloves": {"ru": "Кулаки грозного боксёра", "en": "Killing Gloves Of Boxing"},
            "c_breadmonster_gloves": {"ru": "Кусай-хлеб", "en": "Bread Bite"},
            "c_bear_claw": {"ru": "Воинский дух", "en": "Warrior's Spirit"},
            "c_eviction_notice": {"ru": "Уведомление о выселении", "en": "Eviction Notice"},
            "c_xms_gloves": {"ru": "Праздничный удар", "en": "Holiday Punch"}
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "Engineer": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Shotgun"},
            "c_drg_pomson": {"ru": "Самосуд", "en": "Pomson 6000"},
            "c_dex_shotgun": {"ru": "Овдовитель", "en": "Widowmaker"},
            "c_tele_shotgun": {"ru": "Спасатель", "en": "Rescue Ranger"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"}
        },
        "Secondary": {
            "c_pistol": {"ru": "Стандартный Пистолет", "en": "Pistol"},
            "c_ttg_max_gun": {"ru": "Люгерморф", "en": "Lugermorph"},
            "c_invasion_pistol": {"ru": "З.А.Х.В.А.Т.Ч.И.К.", "en": "C.A.P.P.E.R"},
            "c_wrangler": {"ru": "Поводырь", "en": "Wrangler"},
            "c_invasion_wrangler": {"ru": "Счётчик Гигера", "en": "Giger Counter"},
            "c_dex_arm": {"ru": "Короткое замыкание", "en": "Short Curcuit"}
        },
        "Melee": {
            "c_wrench": {"ru": "Стандартный Гаечный ключ", "en": "Wrench"},
            "c_spikewrench": {"ru": "Южное гостеприимство", "en": "Southern Hospitality"},
            "c_jag": {"ru": "Острозуб", "en": "Jag"},
            "c_drg_wrenchmotron": {"ru": "Озарение", "en": "Eureka Effect"}
        },
        "PDA": {
            "c_builder": {"ru": "КПК строительства", "en": "Construction PDA"},
            "c_pda_engineer": {"ru": "КПК сноса", "en": "Destruction PDA"},
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
            "mech_hands": {"ru": "Рука робота (МвМ)", "en": "Robot Hand (MvM)"},
        },
    },
    "Medic": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_syringegun": {"ru": "Стандартное Шприцемёт", "en": "Syringe Gun"},
            "c_leechgun": {"ru": "Кровопийца", "en": "Blutsauger"},
            "c_crusaders_crossbow": {"ru": "Арбалет крестоносца", "en": "Crusader's Crossbow"},
            "c_proto_syringegun": {"ru": "Передоз", "en": "Overdose"}
        },
        "Secondary": {
            "c_medigun": {"ru": "Стандартная Лечебная пушка", "en": "Medigun"},
            "c_proto_medigun": {"ru": "Быстроправ", "en": "Quickfix"},
            "c_medigun_defence": {"ru": "Вакцинатор", "en": "Vaccinator"}
        },
        "Melee": {
            "c_bonesaw": {"ru": "Стандартная Медицинская пила", "en": "Bonesaw"},
            "c_ubersaw": {"ru": "Убер-пила", "en": "Übersaw"},
            "c_uberneedle": {"ru": "Вита-пила", "en": "Vita-Saw"},
            "c_amputator": {"ru": "Ампутатор", "en": "Amputator"},
            "c_hippocrates_bust": {"ru": "Священная клятва", "en": "Solemn Vow"}
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "Sniper": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_sniperrifle": {"ru": "Стандартная Снайперская винтовка", "en": "Sniper Rifle"},
            "c_csgo_awp": {"ru": "Слонобой", "en": "AWPer Hand"},
            "c_bow": {"ru": "Охотник", "en": "Huntsman"},
            "c_bow_thief": {"ru": "Укрепленный составной лук", "en": "Fortified Compound"},
            "c_dartgun": {"ru": "Сиднейский соня", "en": "Sydney Sleeper"},
            "c_bazaar_sniper": {"ru": "Базарная безделушка", "en": "Bazaar Bargain"},
            "c_dex_sniperrifle": {"ru": "Махина", "en": "Machina"},
            "c_invasion_sniperrifle": {"ru": "Падающая звезда", "en": "The Shooting Star"},
            "c_pro_rifle": {"ru": "Разжигатель разбойника", "en": "Hitman's Heatmaker"},
            "c_tfc_sniperrifle": {"ru": "Классика", "en": "Classic"}
        },
        "Secondary": {
            "c_smg": {"ru": "Стандартный Пистолет-пулемёт", "en": "Submachine Gun"},
            "c_pro_smg": {"ru": "Карабин Чистильщика", "en": "Cleaner's Carbine"},
            "urinejar": {"ru": "Банкате", "en": "Jarate"},
            "c_breadmonster": {"ru": "Родинка с самосознанием", "en": "Self-Aware Beauty Mark"},
            "knife_shield": {"ru": "Бронепанцирь", "en": "Razorback"},
            "croc_shield": {"ru": "Дарвинистский щит", "en": "Darwin's Danger Shield"},
            "xms_sniper_commandobackpack": {"ru": "Набор для кемпинга", "en": "Cozy Camper"}
        },
        "Melee": {
            "c_machete": {"ru": "Стандартный Кукри", "en": "Kukri"},
            "c_wood_machete": {"ru": "Заточка дикаря", "en": "Tribalman's Shiv"},
            "c_croc_knife": {"ru": "Кустолом", "en": "Bushwacka"},
            "c_scimitar": {"ru": "Шаханшах", "en": "Shahanshah"}
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "Spy": {
        "PlayerSkin": {
            "body":  {"ru": "Скин персонажа",    "en": "Player Skin"},
            "masks": {"ru": "Маски маскировки", "en": "Disguise Masks"},
        },
        "Primary": {
            "c_revolver": {"ru": "Стандартный Револьвер", "en": "Revolver"},
            "c_snub_nose": {"ru": "Грандиозный убийца", "en": "Enforcer"},
            "c_ambassador": {"ru": "Амбассадор", "en": "Ambassador"},
            "c_letranger": {"ru": "Незнакомец", "en": "L'Etranger"},
            "c_dex_revolver": {"ru": "Алмазный змей", "en": "Diamondback"}
        },
        "Secondary": {
            "c_sapper": {"ru": "Жучок", "en": "Sapper"},
            "c_p2rec": {"ru": "Жучок-Уитличок", "en": "Ap-Sap"},
            "c_breadmonster_sapper": {"ru": "Закусочная атака", "en": "Snack Attack"},
            "w_sd_sapper": {"ru": "Откатофон", "en": "Red-Tape Recorder"}
        },
        "Melee": {
            "c_knife": {"ru": "Стандартный Нож", "en": "Knife"},
            "c_acr_hookblade": {"ru": "Одетый с иголочки", "en": "Sharp Dresser"},
            "c_ava_roseknife": {"ru": "Чёрная роза", "en": "Black Rose"},
            "c_eternal_reward": {"ru": "Вечный покой", "en": "Your Eternal Reward"},
            "c_voodoo_pin": {"ru": "Иголка вуду", "en": "Wanga Voodoo Knife"},
            "c_shogun_kunai": {"ru": "Кунай заговорщика", "en": "Conniver's Kunai"},
            "c_switchblade": {"ru": "Главный делец", "en": "Big Earner"},
            "c_xms_cold_shoulder": {"ru": "Сосулька", "en": "Spy-Cicle"}
        },
        "Watch": {
            "c_spy_watch": {"ru": "Часы невидимости", "en": "Invis Watch"},
            "c_leather_watch": {"ru": "Плащ и кинжал", "en": "Cloak and Dagger"},
            "c_pocket_watch": {"ru": "Запасной выход", "en": "Dead Ringer"},
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    }
}

# Специальные режимы (эффекты)
SPECIAL_MODES = {
    "CritHIT": "critHIT",
    "Spray": "spray",
}

TF2_CLASSES = {
    "Scout": {"color": "#87CEEB", "icon": ""},
    "Soldier": {"color": "#8B4513", "icon": ""},
    "Pyro": {"color": "#FF4500", "icon": ""},
    "Demoman": {"color": "#800080", "icon": ""},
    "Heavy": {"color": "#FFD700", "icon": ""},
    "Engineer": {"color": "#DAA520", "icon": ""},
    "Medic": {"color": "#FF0000", "icon": ""},
    "Sniper": {"color": "#228B22", "icon": ""},
    "Spy": {"color": "#4B0082", "icon": ""}
}

WEAPON_TYPES = {
    "PlayerSkin": {"ru": "Скин персонажа", "en": "Player Skin"},
    "Primary": {"ru": "Основное", "en": "Primary"},
    "Secondary": {"ru": "Дополнительное", "en": "Secondary"},
    "Melee": {"ru": "Ближний бой", "en": "Melee"},
    "Watch": {"ru": "Часы", "en": "Watch"},
    "PDA": {"ru": "КПК", "en": "PDA"},
    "Hands": {"ru": "Руки", "en": "Hands"},
    "Custom": {"ru": "Кастомный мод", "en": "Custom Mod"},
}

# Слоты оружия — то, что показывается в списке «Тип оружия» под категорией «Оружие».
# PlayerSkin/Hands/Custom сюда НЕ входят: они теперь в других категориях.
# Watch (часы шпиона) и PDA (КПК инженера) показываются только у тех классов,
# где они есть (фильтр по TF2_WEAPONS в main_window).
WEAPON_SLOT_TYPES = ["Primary", "Secondary", "Melee", "Watch", "PDA"]

# Типы оружия, которые относятся к категории «Персонаж» (тело + руки).
CHARACTER_PART_TYPES = ["PlayerSkin", "Hands"]


def get_character_parts(class_name: str, language: str = "ru") -> list:
    """
    Возвращает части персонажа (тело + руки) для категории «Персонаж»
    как список (key, display_name).

    Объединяет записи PlayerSkin и Hands выбранного класса. mode для каждой
    части строится как f"{class.lower()}_{key}" — те же ключи, что и раньше
    (scout_body, scout_hands, engineer_mech_hands, spy_masks и т.д.).
    """
    parts: list = []
    cls = TF2_WEAPONS.get(class_name, {})
    for ptype in CHARACTER_PART_TYPES:
        for key, val in cls.get(ptype, {}).items():
            if isinstance(val, dict):
                name = val.get(language, val.get("ru", key))
            else:
                name = val
            parts.append((key, name))
    return parts

def get_weapon_name(class_name: str, weapon_type: str, weapon_key: str, language: str = "ru") -> str:
    if class_name not in TF2_WEAPONS:
        return weapon_key

    if weapon_type not in TF2_WEAPONS[class_name]:
        return weapon_key

    if weapon_key not in TF2_WEAPONS[class_name][weapon_type]:
        return weapon_key

    weapon_data = TF2_WEAPONS[class_name][weapon_type][weapon_key]

    if isinstance(weapon_data, dict):
        return weapon_data.get(language, weapon_data.get("ru", weapon_key))

    return weapon_data

def get_weapon_type_name(weapon_type: str, language: str = "ru") -> str:
    return WEAPON_TYPES.get(weapon_type, {}).get(language, weapon_type)


def get_weapon_type_key(type_name: str, language: str = "ru") -> Optional[str]:
    """Обратный lookup: ключ типа оружия по его переведённому названию (или None)."""
    for key in WEAPON_TYPES:
        if get_weapon_type_name(key, language) == type_name:
            return key
    return None


def weapon_key_from_mode(mode: str) -> str:
    """
    Извлекает ключ оружия из mode-строки обычного оружия.

    mode имеет вид "<class>_<weaponkey>" (например "scout_c_scattergun"),
    поэтому берём часть после первого '_'. Если '_' нет — возвращаем mode как есть.
    """
    return mode.split('_', 1)[1] if '_' in mode else mode

WEAPON_MDL_PATHS = {}
for class_name, class_weapons in TF2_WEAPONS.items():
    for weapon_type, weapons in class_weapons.items():
        if weapon_type in ("Hands", "PlayerSkin"):
            continue  # Hands and PlayerSkin have no MDL in the build pipeline
        for weapon_key in weapons.keys():
            WEAPON_MDL_PATHS[weapon_key] = f"models/weapons/c_models/{weapon_key}/{weapon_key}.mdl"

# ── Нестандартные пути MDL (папка или имя файла не совпадают с ключом оружия) ──

# Axtinguisher: папка c_axtinguisher/, файл c_axtinguisher_pyro.mdl
WEAPON_MDL_PATHS["c_axtinguisher_pyro"] = (
    "models/weapons/c_models/c_axtinguisher/c_axtinguisher_pyro.mdl"
)

# Buff Banner: папка c_battalion_buffpack/, файл c_batt_buffpack.mdl
WEAPON_MDL_PATHS["c_batt_buffpack"] = (
    "models/weapons/c_models/c_battalion_buffpack/c_batt_buffpack.mdl"
)

# B.A.S.E Jumper: workshop/, папка с опечаткой c_paratooper_pack
WEAPON_MDL_PATHS["c_paratrooper_pack"] = (
    "models/workshop/weapons/c_models/c_paratooper_pack/c_paratrooper_pack.mdl"
)

# Equalizer / Escape Plan share the c_pickaxe/ folder
WEAPON_MDL_PATHS["c_pickaxe_s2"] = (
    "models/weapons/c_models/c_pickaxe/c_pickaxe_s2.mdl"
)

# Half-Zatoichi (Soldier): workshop_partner/, общая папка c_shogun_katana/
WEAPON_MDL_PATHS["c_shogun_katana_soldier"] = (
    "models/workshop_partner/weapons/c_models/c_shogun_katana/c_shogun_katana_soldier.mdl"
)

# Fire Axe (Pyro): папка c_fireaxe_pyro/, файл c_fireaxe_pyro.mdl
WEAPON_MDL_PATHS["c_fireaxe"] = (
    "models/weapons/c_models/c_fireaxe_pyro/c_fireaxe_pyro.mdl"
)

# Ali Baba's Wee Booties / Bootlegger: workshop player items, не weapons
WEAPON_MDL_PATHS["demo_booties"] = (
    "models/workshop/player/items/demo/demo_booties/demo_booties.mdl"
)
WEAPON_MDL_PATHS["pegleg"] = (
    "models/workshop/player/items/demo/pegleg/pegleg.mdl"
)

# Robo-Sandvich: папка c_sandwich/, файл c_robo_sandwich.mdl
WEAPON_MDL_PATHS["c_robo_sandwich"] = (
    "models/weapons/c_models/c_sandwich/c_robo_sandwich.mdl"
)

# Natascha: папка c_minigun/, файл c_minigun_natascha.mdl
WEAPON_MDL_PATHS["c_minigun_natascha"] = (
    "models/weapons/c_models/c_minigun/c_minigun_natascha.mdl"
)

# Vaccinator: workshop/, папка c_medigun_defense (американская орфография)
WEAPON_MDL_PATHS["c_medigun_defence"] = (
    "models/workshop/weapons/c_models/c_medigun_defense/c_medigun_defense.mdl"
)

# Red-Tape Recorder: w_models, не c_models
WEAPON_MDL_PATHS["w_sd_sapper"] = (
    "models/weapons/w_models/w_sd_sapper.mdl"
)

# Часы шпиона: Invis Watch лежит плоским файлом, Dead Ringer и Cloak and Dagger —
# в подпапке parts/. КПК инженера (c_builder, c_pda_engineer) совпадают с дефолтом.
WEAPON_MDL_PATHS["c_spy_watch"] = (
    "models/weapons/c_models/c_spy_watch.mdl"
)
WEAPON_MDL_PATHS["c_pocket_watch"] = (
    "models/weapons/c_models/c_pocket_watch/parts/c_pocket_watch.mdl"
)
WEAPON_MDL_PATHS["c_leather_watch"] = (
    "models/weapons/c_models/c_leather_watch/parts/c_leather_watch.mdl"
)

# ── Модели рук (c_class_arms) ─────────────────────────────────────────────────
_ARM_CLASSES = [
    "c_scout_arms",
    "c_soldier_arms",
    "c_pyro_arms",
    "c_demo_arms",
    "c_heavy_arms",
    "c_engineer_arms",
    "c_engineer_gunslinger",   # робо-рука инженера (MvM / Gunslinger)
    "c_medic_arms",
    "c_sniper_arms",
    "c_spy_arms",
]
for _arm in _ARM_CLASSES:
    # Руки хранятся по плоскому пути (без подпапки), а не c_models/{arm}/{arm}.mdl.
    # Это обеспечивает совпадение ключа кэша при повторных запусках.
    WEAPON_MDL_PATHS[_arm] = f"models/weapons/c_models/{_arm}.mdl"

# ── Модели тел персонажей (models/player/) ────────────────────────────────────
# Используются для 3D Preview; в pipeline сборки VPK не задействованы.
WEAPON_MDL_PATHS["player_scout"]    = "models/player/scout.mdl"
WEAPON_MDL_PATHS["player_soldier"]  = "models/player/soldier.mdl"
WEAPON_MDL_PATHS["player_pyro"]     = "models/player/pyro.mdl"
WEAPON_MDL_PATHS["player_demo"]     = "models/player/demo.mdl"
WEAPON_MDL_PATHS["player_heavy"]    = "models/player/heavy.mdl"
WEAPON_MDL_PATHS["player_engineer"] = "models/player/engineer.mdl"
WEAPON_MDL_PATHS["player_medic"]    = "models/player/medic.mdl"
WEAPON_MDL_PATHS["player_sniper"]   = "models/player/sniper.mdl"
WEAPON_MDL_PATHS["player_spy"]      = "models/player/spy.mdl"

# ── Доп. текстуры по фиксированному пути (вне QC/модели) ──────────────────────
# Некоторые предметы используют текстуры, которых НЕТ ни в $texturegroup, ни в
# геометрии модели (например HUD-вставки Dead Ringer). Их нельзя найти через
# материалы модели — путь зашит в игре. Здесь задаём такие текстуры явно:
#   {weapon_key: [{"name", "vpk" (путь в VPK с materials/...vtf), "ru", "en"}]}
# Превью покажет для них слот, сборка запишет картинку ровно по этому пути.
WEAPON_EXTRA_TEXTURES: dict[str, list[dict]] = {
    "c_pocket_watch": [
        {
            "name": "pocket_watch_fg",
            "vpk":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_fg.vtf",
            # VMT кладём В ТУ ЖЕ папку, что и VTF (так требует игра, без дублей vgui)
            "vmt":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_fg.vmt",
            "ru": "Центральная вставка", "en": "Center insert",
        },
        {
            "name": "pocket_watch_bg",
            "vpk":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_bg.vtf",
            "vmt":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_bg.vmt",
            "ru": "Фон циферблата", "en": "Watch background",
        },
    ],
}

# ── Оружие без BLU-команды ───────────────────────────────────────────────────
# У некоторых предметов модель использует ОДНУ текстуру для обеих команд
# (напр. часы шпиона). Для них не нужно создавать BLU-вариант — игнорируем
# blu_row из $texturegroup, иначе в мод попадёт лишняя _blue текстура.
NO_BLU_WEAPON_KEYS: frozenset = frozenset({"c_pocket_watch"})

# ── Оружие, которому нужен зеркальный VMT по оригинальному пути ───────────────
# Некоторые предметы отображаются в игре ДРУГОЙ моделью, чем та, что собирает
# инструмент, и ссылаются на текстуру по ОРИГИНАЛЬНОМУ пути материала, а не по
# пропатченному console\. Для них создаём зеркальный VMT по оригинальному
# $cdmaterials-пути — тогда «чужая» модель найдёт скин.
# Dead Ringer виден через РОДНОЙ viewmodel (v_watch_pocket_spy), который смотрит
# на материал по ОРИГИНАЛЬНОМУ пути. Зеркальный VMT по этому пути ссылается на
# console-VTF (текстура + все карты), поэтому папку console оставляем как есть.
MIRROR_VMT_WEAPON_KEYS: frozenset = frozenset({"c_pocket_watch"})

# ── Оружие «только материалы» (без модели в моде) ────────────────────────────
# Эти предметы отображаются РОДНОЙ игровой моделью (напр. Dead Ringer виден
# через viewmodel v_watch_pocket_spy). Своя перекомпилированная модель в моде
# не нужна и вредна (игра подхватит «чужую»). Собираем только материалы (VTF/VMT
# по console-пути) + зеркальный VMT по оригинальному пути — родная модель найдёт
# скин и карты материала. Модель .mdl в мод НЕ кладём.
MATERIAL_ONLY_WEAPON_KEYS: frozenset = frozenset({"c_pocket_watch"})

# ── 3D-превью: подмена модели и фильтр материалов ────────────────────────────
# Для некоторых предметов в 3D надо показывать ДРУГУЮ модель, чем собирает
# инструмент. Dead Ringer: собираем c_pocket_watch, но в игре от первого лица
# видно viewmodel v_watch_pocket_spy (руки + часы в одном меше). Показываем его,
# оставляя только меши часов (материалы по whitelist), руки скрываем.
PREVIEW_MDL_OVERRIDE: dict[str, str] = {
    "c_pocket_watch": "models/weapons/v_models/v_watch_pocket_spy.mdl",
}
# Подстроки имён материалов, которые ОСТАВЛЯЕМ в превью (остальные меши скрыты).
PREVIEW_MAT_WHITELIST: dict[str, tuple] = {
    "c_pocket_watch": ("watch",),   # c_pocket_watch / pocket_watch_fg / pocket_watch_bg
}

# ── Доп. статические файлы мода (скрипты/метаданные) ─────────────────────────
# Некоторым предметам нужны не-материальные файлы в моде: HUD-скрипты (.res),
# метаданные мода (info.vdf) и т.п. Кладутся в корень VPK по указанному пути
# ровно с заданным содержимым. {weapon_key: [{"path", "content"}]}.
WEAPON_EXTRA_FILES: dict[str, list[dict]] = {
    "c_pocket_watch": [
        {
            "path": "scripts/screens/pda_spy_invis_pocket.res",
            "content": (
                '"pda_spy_invis.res"\n'
                '{\n'
                '\t"InvisProgress"\n'
                '\t{\n'
                '\t\t"ControlName"\t"CircularProgressBar"\t"fieldName"\t"InvisProgress"\n'
                '\t\t"xpos"\t"10"\t"ypos"\t"10"\t"zpos"\t"1"\t"wide"\t"260"\t"tall"\t"80"\n'
                '\t\t"visible"\t"1"\t"enabled"\t"1"\n'
                '\n'
                '\t\t"fg_image"\t"replay/thumbnails/deadringer/pocket_watch_fg"\t\n'
                '\t\t"bg_image"\t"replay/thumbnails/deadringer/pocket_watch_bg"\n'
                '\t}\t\n'
                '}\n'
            ),
        },
        {
            "path": "info.vdf",
            "content": '"stan-deadringer" { "ui_version" "3" }\n',
        },
    ],
}

# ── Нестандартные пути VTF (дополнительные пути для поиска текстур) ───────────
# Используются как приоритетный список ПЕРЕД стандартными путями.
# Нужны когда имя/папка текстуры не совпадает с weapon_key.

WEAPON_TEXTURE_PATHS: dict[str, list[str]] = {
    # Fire Axe: текстура в c_fireaxe_pyro/
    "c_fireaxe": [
        "materials/models/weapons/c_models/c_fireaxe_pyro/c_fireaxe_pyro.vtf",
    ],
    # Axtinguisher: папка c_axtinguisher/, не c_axtinguisher_pyro/
    "c_axtinguisher_pyro": [
        "materials/backpack/weapons/c_models/c_axtinguisher/c_axtinguisher_pyro.vtf",
    ],
    # Backburner: backpack path
    "c_backburner": [
        "materials/backpack/weapons/c_models/c_backburner/c_backburner.vtf",
    ],
    # Buff Banner: имя файла c_buffpack, не c_batt_buffpack
    "c_batt_buffpack": [
        "materials/models/weapons/c_items/c_buffpack.vtf",
    ],
    # Bread Bite: имя файла c_breadmonster, не c_breadmonster_gloves
    "c_breadmonster_gloves": [
        "materials/models/weapons/c_items/c_breadmonster.vtf",
    ],
    # AWPer Hand: папка csgo_awp/, файл w_csgo_awp
    "c_csgo_awp": [
        "materials/models/weapons/csgo_awp/w_csgo_awp.vtf",
    ],
    # Bonk! Atomic Punch: имя файла c_energydrink (без подчёркивания)
    "c_energy_drink": [
        "materials/models/weapons/c_items/c_energydrink.vtf",
    ],
    # Flare Gun: имя файла c_flaregun, не c_flaregun_pyro
    "c_flaregun_pyro": [
        "materials/models/weapons/c_items/c_flaregun.vtf",
    ],
    # Vaccinator: workshop, американская орфография (defense), не defence
    "c_medigun_defence": [
        "materials/models/workshop/weapons/c_models/c_medigun_defense/c_medigun_defense.vtf",
    ],
    # Gunboats: имя файла c_rocketboots_demo, не c_rocketboots_soldier
    "c_rocketboots_soldier": [
        "materials/models/weapons/c_items/c_rocketboots_demo.vtf",
    ],
    # Half-Zatoichi (Soldier): workshop_partner, папка c_shogun_katana/
    "c_shogun_katana_soldier": [
        "materials/models/workshop_partner/weapons/c_models/c_shogun_katana/c_shogun_katana.vtf",
    ],
    # Sandman: папка v_bat/, файл v_wooden_bat
    "c_wooden_bat": [
        "materials/models/weapons/v_bat/v_wooden_bat.vtf",
    ],
    # Horseless Headless Horsemann's Headtaker: имя файла pumpkin_axe
    "c_headtaker": [
        "materials/models/weapons/c_items/pumpkin_axe.vtf",
    ],
    # Scottish Resistance: папка v_stickybomb_defender/
    "c_scottish_resistance": [
        "materials/models/weapons/v_stickybomb_defender/v_stickybomb_defender.vtf",
    ],
    # Darwin's Danger Shield: workshop player items
    "croc_shield": [
        "materials/models/workshop/player/items/sniper/croc_shield/croc_shield.vtf",
    ],
    # Jarate: workshop player items (xmas variant folder)
    "urinejar": [
        "materials/models/workshop/player/items/sniper/xms_sniper_commandobackpack/xms_sniper_commandobackpack.vtf",
    ],
    # Razorback: player/items/sniper
    "knife_shield": [
        "materials/models/player/items/sniper/knife_shield.vtf",
    ],
    # Mantreads: player/items/soldier
    "tankerboots": [
        "materials/models/player/items/soldier/tankerboots.vtf",
    ],
    # Ali Baba's Wee Booties: workshop player items
    "demo_booties": [
        "materials/models/workshop/player/items/demo/demo_booties/demo_booties.vtf",
    ],
    # Bootlegger: workshop player items
    "pegleg": [
        "materials/models/workshop/player/items/demo/pegleg/pegleg.vtf",
    ],
    # Red-Tape Recorder: w_models
    "w_sd_sapper": [
        "materials/models/weapons/w_models/w_sd_sapper/w_sd_sapper.vtf",
    ],
    # ── Текстуры тела персонажа (materials/models/player/…) ─────────────────────
    "player_scout":    ["materials/models/player/scout/scout_red.vtf"],
    "player_soldier":  ["materials/models/player/soldier/soldier_red.vtf"],
    "player_pyro":     ["materials/models/player/pyro/pyro_red.vtf"],
    "player_demo":     ["materials/models/player/demo/demoman_red.vtf"],
    "player_heavy":    ["materials/models/player/hvyweapon/hvyweapon_red.vtf"],
    "player_engineer": ["materials/models/player/engineer/engineer_red.vtf"],
    "player_medic":    ["materials/models/player/medic/medic_red.vtf"],
    "player_sniper":   ["materials/models/player/sniper/sniper_red.vtf"],
    "player_spy":      ["materials/models/player/spy/spy_red.vtf"],
    # ── Текстуры рук (materials/models/player/…) ──────────────────────────────
    "c_scout_arms": [
        "materials/models/player/scout/scout_hands.vtf",
    ],
    "c_soldier_arms": [
        "materials/models/player/soldier/soldier_hands.vtf",
    ],
    "c_pyro_arms": [
        "materials/models/player/pyro/pyro_hands_red.vtf",
    ],
    "c_demo_arms": [
        "materials/models/player/demo/demoman_hands.vtf",
    ],
    "c_heavy_arms": [
        "materials/models/player/hvyweapon/hvyweapon_hands.vtf",
    ],
    "c_engineer_arms": [
        "materials/models/player/engineer/engineer_handl.vtf",
        "materials/models/player/engineer/engineer_handr_red.vtf",
    ],
    "c_medic_arms": [
        "materials/models/player/medic/medic_hands_red.vtf",
    ],
    "c_sniper_arms": [
        "materials/models/player/sniper/sniper_handl_red.vtf",
    ],
    "c_spy_arms": [
        "materials/models/player/spy/spy_hands_red.vtf",
    ],
}
