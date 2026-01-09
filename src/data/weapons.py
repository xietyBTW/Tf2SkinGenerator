"""
Данные оружия Team Fortress 2 с поддержкой двух языков
"""

# Полный список оружия TF2 по классам с русскими и английскими названиями
TF2_WEAPONS = {
    "Scout": {
        "Primary": {
            "c_scattergun": {"ru": "Стандартное Обрез", "en": "Stock Scattergun"},
            "c_double_barrel": {"ru": "Неумолимая сила", "en": "Force-A-Nature"},
            "c_shortstop": {"ru": "Прерыватель", "en": "Shortstop"},
            "c_soda_popper": {"ru": "Газировщик", "en": "Soda Popper"},
            "c_pep_scattergun": {"ru": "Обрез Малыша", "en": "Baby Face's Blaster"},
            "c_scatterdrum": {"ru": "Спинобрез", "en": "Backscatter"}
        },
        "Secondary": {
            "c_pistol": {"ru": "Стандартный Пистолет", "en": "Stock Pistol"},
            "c_ttg_max_gun": {"ru": "Люгерморф", "en": "Lugermorph"},
            "c_invasion_pistol": {"ru": "З.А.Х.В.А.Т.Ч.И.К.", "en": "C.A.P.P.E.R"},
            "c_sd_cleaver": {"ru": "Окрыленный", "en": "Flying Guillotine"},
            "c_energy_drink": {"ru": "Дамский пистолет Красавчика", "en": "Bonk! Atomic Punch"},
            "c_madmilk": {"ru": "Зломолоко", "en": "Mad Milk"},
            "c_winger_pistol": {"ru": "Дрёма", "en": "Winger"},
            "c_pep_pistol": {"ru": "Критокола", "en": "Crit-a-Cola"}
        },
        "Melee": {
            "c_bat": {"ru": "Стандартная Бита", "en": "Stock Bat"},
            "c_wooden_bat": {"ru": "Поддай леща", "en": "Sandman"},
            "c_holymackerel": {"ru": "Голая рука", "en": "Holy Mackerel"},
            "c_bonk_bat": {"ru": "Световая бита", "en": "Atomizer"},
            "c_candy_cane": {"ru": "Карамельная трость", "en": "Candy Cane"},
            "c_boston_basher": {"ru": "Бостонский раздолбай", "en": "Boston Basher"},
            "c_scout_sword": {"ru": "Трехрунный меч", "en": "Three-Rune Sword"},
            "c_rift_fire_mace": {"ru": "Солнце на палочке", "en": "Sun-on-a-Stick"},
            "c_xms_giftwrap": {"ru": "Обёрточный убийца", "en": "Wrap Assassin"},
            "c_invasion_bat": {"ru": "Веер войны", "en": "Fan O'War"}
        }
    },
    "Soldier": {
        "Primary": {
            "c_rocketlauncher": {"ru": "Стандартное Ракетомёт", "en": "Stock Rocket Launcher"},
            "c_bet_rocketlauncher": {"ru": "Прародитель", "en": "Original"},
            "c_directhit": {"ru": "Прямое попадание", "en": "Direct Hit"},
            "c_blackbox": {"ru": "Чёрный ящик", "en": "Black Box"},
            "c_dumpster_device": {"ru": "Тренировочный ракетомёт", "en": "Beggar's Bazooka"},
            "c_liberty_launcher": {"ru": "Освободитель", "en": "Liberty Launcher"},
            "c_drg_cowmangler": {"ru": "Линчеватель скота 5000", "en": "Cattle Bruiser"},
            "c_atom_launcher": {"ru": "Авиаудар", "en": "Air Strike"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Stock Shotgun"},
            "c_reserve_shooter": {"ru": "Офицер запаса", "en": "Reserve Shooter"},
            "c_batt_buffpack": {"ru": "Вдохновляющее знамя", "en": "Buff Banner"},
            "c_rocketboots_soldier": {"ru": "Штурмботинки", "en": "Gunboats"},
            "c_shogun_warpack": {"ru": "Поддержка батальона", "en": "Battalion's Backup"},
            "c_drg_righteousbison": {"ru": "Благочестивый бизон", "en": "Righteous Bison"},
            "tankerboots": {"ru": "Людодавы", "en": "Mantreads"},
            "c_paratrooper_pack": {"ru": "Парашютист", "en": "Parachute"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"}
        },
        "Melee": {
            "c_shovel": {"ru": "Стандартная Лопата", "en": "Stock Shovel"},
            "c_pickaxe_s2": {"ru": "Уравнитель", "en": "Equalizer"},
            "c_shogun_katana_soldier": {"ru": "Полудзатоити", "en": "Half-Zatoichi"},
            "c_riding_crop": {"ru": "Дисциплинарное взыскание", "en": "Disciplinary Action"},
            "c_market_gardener": {"ru": "Землекоп", "en": "Pickaxe"},
            "c_pickaxe": {"ru": "План эвакуации", "en": "Escape Plan"}
        }
    },
    "Pyro": {
        "Primary": {
            "c_flamethrower": {"ru": "Стандартное Огнемёт", "en": "Stock Flamethrower"},
            "c_rainblower": {"ru": "Радужигатель", "en": "Rainbow Flamethrower"},
            "c_ai_flamethrower": {"ru": "Ностромский пламемет", "en": "Nostromo Flamethrower"},
            "c_backburner": {"ru": "Дожигатель", "en": "Backburner"},
            "c_degreaser": {"ru": "Чистильщик", "en": "Degreaser"},
            "c_drg_phlogistinator": {"ru": "Флогистонатор", "en": "Phlogiston"},
            "c_flameball": {"ru": "Ярость дракона", "en": "Dragon's Fury"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Stock Shotgun"},
            "c_reserve_shooter": {"ru": "Офицер запаса", "en": "Reserve Shooter"},
            "c_flaregun_pyro": {"ru": "Ракетница", "en": "Flare Gun"},
            "c_detonator": {"ru": "Детонатор", "en": "Detonator"},
            "c_scorch_shot": {"ru": "Людоплав", "en": "Scorch Shot"},
            "c_rocketpack": {"ru": "Обжигающий выстрел", "en": "Thermal Thruster"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"}
        },
        "Melee": {
            "c_fireaxe": {"ru": "Стандартный Пожарный топор", "en": "Stock Fire Axe"},
            "c_axtinguisher_pyro": {"ru": "Огнетопор", "en": "Axtinguisher"},
            "c_mailbox": {"ru": "Почтовый дебошир", "en": "Mailman's Mail"},
            "c_powerjack": {"ru": "Крушитель", "en": "Powerjack"},
            "c_sledgehammer": {"ru": "Молот", "en": "Sledgehammer"},
            "c_back_scratcher": {"ru": "Спиночёс", "en": "Sharpened Volcano Fragment"},
            "c_drg_thirddegree": {"ru": "Третья степень", "en": "Third Degree"},
            "c_sd_neonsign": {"ru": "Неоновый аннигилятор", "en": "Neon Annihilator"},
            "c_slapping_glove": {"ru": "Горячая рука", "en": "Hot Hand"},
            "c_lollichop": {"ru": "Заостренный осколок вулкана", "en": "Sharpened Volcano Fragment"}
        }
    },
    "Demoman": {
        "Primary": {
            "c_grenadelauncher": {"ru": "Стандартное Гранатомёт", "en": "Stock Grenade Launcher"},
            "c_lochnload": {"ru": "Подкидыш", "en": "Loch-n-Load"},
            "demo_booties": {"ru": "Ботиночки Али-Бабы", "en": "Ali Baba's Wee Booties"},
            "pegleg": {"ru": "Бутлегер", "en": "Bootlegger"},
            "c_demo_cannon": {"ru": "Пушка без лафета", "en": "Cannondary"},
            "c_quadball": {"ru": "Железный бомбардир", "en": "Iron Bomber"}
        },
        "Secondary": {
            "c_stickybomb_launcher": {"ru": "Стандартное Липучкомёт", "en": "Stock Sticky Launcher"},
            "c_scottish_resistance": {"ru": "Шотландское сопротивление", "en": "Scottish Resistance"},
            "c_sticky_jumper": {"ru": "Штурмовой щит", "en": "Sticky Jumper"},
            "c_targe": {"ru": "Роскошное прикрытие", "en": "Luxurious Lunchbox"},
            "c_persian_shield": {"ru": "Верный штурвал", "en": "Mighty Helm"},
            "c_kingmaker_sticky": {"ru": "Быстромёт", "en": "Quickfire Launcher"}
        },
        "Melee": {
            "c_bottle": {"ru": "Стандартная Бутылка", "en": "Stock Bottle"},
            "c_claymore": {"ru": "Одноглазый горец", "en": "Eyelander"},
            "c_battleaxe": {"ru": "Секира Пешего всадника без головы", "en": "Headless Headman's Cleaver"},
            "c_headtaker": {"ru": "Шотландский головорез", "en": "Scottish Guillotine"},
            "c_caber": {"ru": "Аллапульское бревно", "en": "Alepurian Log"},
            "c_claidheamohmor": {"ru": "Клеймор", "en": "Claymore"},
            "c_shogun_katana": {"ru": "Полудзатоити", "en": "Half-Zatoichi"},
            "c_demo_sultan_sword": {"ru": "Персидский заклинатель", "en": "Persian Persuader"}
        }
    },
    "Heavy": {
        "Primary": {
            "c_minigun": {"ru": "Стандартное Пулемёт", "en": "Stock Minigun"},
            "c_iron_curtain": {"ru": "Железный занавес", "en": "Iron Curtain"},
            "c_minigun_natascha": {"ru": "Наташа", "en": "Natascha"},
            "c_gatling_gun": {"ru": "Латунный монстр", "en": "Brass Beast"},
            "c_tomislav": {"ru": "Томислав", "en": "Tomislav"},
            "c_canton": {"ru": "Огненный дракон", "en": "Dragon's Breath"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Stock Shotgun"},
            "c_sandwich": {"ru": "Бутерброд", "en": "Sandvich"},
            "c_chocolate": {"ru": "Плитка «Далокош»", "en": "Dalokosh Bar"},
            "c_fishcake": {"ru": "Рыбный батончик", "en": "Fish Stick"},
            "c_buffalo_steak": {"ru": "Бутерброд из мяса буйвола", "en": "Buffalo Steak Sandwich"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"},
            "c_banana": {"ru": "Утешительный банан", "en": "Banana"},
            "c_robo_sandwich": {"ru": "Робо-бутерброд", "en": "Robo-Sandwich"}
        },
        "Melee": {
            "c_sr3_punch": {"ru": "Стандартные Кулаки", "en": "Stock Fists"},
            "c_fists_of_steel": {"ru": "Кулакопокалипсис", "en": "Fists of Steel"},
            "c_boxing_gloves": {"ru": "Кулаки грозного боксёра", "en": "GRU"},
            "c_breadmonster_gloves": {"ru": "Кусай-хлеб", "en": "Bread Knuckles"},
            "c_bear_claw": {"ru": "Воинский дух", "en": "Warrior's Spirit"},
            "c_eviction_notice": {"ru": "Уведомление о выселении", "en": "Eviction Notice"},
            "c_xms_gloves": {"ru": "Праздничный удар", "en": "Holiday Punch"}
        }
    },
    "Engineer": {
        "Primary": {
            "c_shotgun": {"ru": "Стандартный Дробовик", "en": "Stock Shotgun"},
            "c_drg_pomson": {"ru": "Самосуд", "en": "Pomson 6000"},
            "c_dex_shotgun": {"ru": "Овдовитель", "en": "Widowmaker"},
            "c_tele_shotgun": {"ru": "Спасатель", "en": "Rescue Ranger"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"}
        },
        "Secondary": {
            "c_pistol": {"ru": "Стандартный Пистолет", "en": "Stock Pistol"},
            "c_ttg_max_gun": {"ru": "Люгерморф", "en": "Lugermorph"},
            "c_invasion_pistol": {"ru": "З.А.Х.В.А.Т.Ч.И.К.", "en": "C.A.P.P.E.R"},
            "c_wrangler": {"ru": "Поводырь", "en": "Wrangler"},
            "c_invasion_wrangler": {"ru": "Счётчик Гигера", "en": "Jag"},
            "c_dex_arm": {"ru": "Короткое замыкание", "en": "Short Circuit"}
        },
        "Melee": {
            "c_wrench": {"ru": "Стандартный Гаечный ключ", "en": "Stock Wrench"},
            "c_spikewrench": {"ru": "Южное гостеприимство", "en": "Southern Hospitality"},
            "c_jag": {"ru": "Острозуб", "en": "Jag"},
            "c_drg_wrenchmotron": {"ru": "Озарение", "en": "Eureka Effect"}
        }
    },
    "Medic": {
        "Primary": {
            "c_syringegun": {"ru": "Стандартное Шприцемёт", "en": "Stock Syringe Gun"},
            "c_leechgun": {"ru": "Кровопийца", "en": "Blutsauger"},
            "c_crusaders_crossbow": {"ru": "Арбалет крестоносца", "en": "Crossbow"},
            "c_proto_syringegun": {"ru": "Передоз", "en": "Overdose"}
        },
        "Secondary": {
            "c_medigun": {"ru": "Стандартная Лечебная пушка", "en": "Stock Medigun"},
            "c_proto_medigun": {"ru": "Быстроправ", "en": "Quick-Fix"},
            "c_medigun_defence": {"ru": "Вакцинатор", "en": "Vaccinator"}
        },
        "Melee": {
            "c_bonesaw": {"ru": "Стандартная Медицинская пила", "en": "Stock Bone Saw"},
            "c_ubersaw": {"ru": "Убер-пила", "en": "Übersaw"},
            "c_uberneedle": {"ru": "Вита-пила", "en": "Vita-Saw"},
            "c_amputator": {"ru": "Ампутатор", "en": "Amputator"},
            "c_hippocrates_bust": {"ru": "Священная клятва", "en": "Holy Mackerel"}
        }
    },
    "Sniper": {
        "Primary": {
            "c_sniperrifle": {"ru": "Стандартная Снайперская винтовка", "en": "Stock Sniper Rifle"},
            "c_csgo_awp": {"ru": "Слонобой", "en": "AWPer Hand"},
            "c_bow": {"ru": "Охотник", "en": "Huntsman"},
            "c_bow_thief": {"ru": "Укрепленный составной лук", "en": "Compound Bow"},
            "c_dartgun": {"ru": "Сиднейский соня", "en": "Sydney Sleeper"},
            "c_bazaar_sniper": {"ru": "Базарная безделушка", "en": "Bazaar Bargain"},
            "c_dex_sniperrifle": {"ru": "Махина", "en": "Machina"},
            "c_invasion_sniperrifle": {"ru": "Падающая звезда", "en": "Falling Star"},
            "c_pro_rifle": {"ru": "Разжигатель разбойника", "en": "Hitman's Heatmaker"},
            "c_tfc_sniperrifle": {"ru": "Классика", "en": "Classic"}
        },
        "Secondary": {
            "c_smg": {"ru": "Стандартный Пистолет-пулемёт", "en": "Stock SMG"},
            "c_pro_smg": {"ru": "Карабин Чистильщика", "en": "Cleaner's Carbine"},
            "urinejar": {"ru": "Банкате", "en": "Jarate"},
            "c_breadmonster": {"ru": "Родинка с самосознанием", "en": "Self-Aware Beauty Mark"},
            "knife_shield": {"ru": "Бронепанцирь", "en": "Razorback"},
            "croc_shield": {"ru": "Дарвинистский щит", "en": "Darwin's Danger Shield"},
            "xms_sniper_commandobackpack": {"ru": "Набор для кемпинга", "en": "Camping Kit"}
        },
        "Melee": {
            "c_machete": {"ru": "Стандартный Кукри", "en": "Stock Kukri"},
            "c_wood_machete": {"ru": "Заточка дикаря", "en": "Bushman's Bristleback"},
            "c_croc_knife": {"ru": "Кустолом", "en": "Machete"},
            "c_scimitar": {"ru": "Шаханшах", "en": "Shahanshah"}
        }
    },
    "Spy": {
        "Primary": {
            "c_revolver": {"ru": "Стандартный Револьвер", "en": "Stock Revolver"},
            "c_snub_nose": {"ru": "Грандиозный убийца", "en": "Enforcer"},
            "c_ambassador": {"ru": "Амбассадор", "en": "Ambassador"},
            "c_letranger": {"ru": "Незнакомец", "en": "Stranger"},
            "c_dex_revolver": {"ru": "Алмазный змей", "en": "Diamond Back"}
        },
        "Secondary": {
            "c_sapper": {"ru": "Жучок", "en": "Sapper"},
            "c_p2rec": {"ru": "Жучок-Уитличок", "en": "Witchling Exterminator"},
            "c_breadmonster_sapper": {"ru": "Закусочная атака", "en": "Snack Attack"},
            "w_sd_sapper": {"ru": "Откатофон", "en": "Rewind-o-Matic"}
        },
        "Melee": {
            "c_knife": {"ru": "Стандартный Нож", "en": "Stock Knife"},
            "c_acr_hookblade": {"ru": "Одетый с иголочки", "en": "Classy Dapper"},
            "c_ava_roseknife": {"ru": "Чёрная роза", "en": "Black Rose"},
            "c_eternal_reward": {"ru": "Вечный покой", "en": "Eternal Rest"},
            "c_voodoo_pin": {"ru": "Иголка вуду", "en": "Voodoo Pin"},
            "c_shogun_kunai": {"ru": "Кунай заговорщика", "en": "Conspiracy Knife"},
            "c_switchblade": {"ru": "Главный делец", "en": "Big Cheese"},
            "c_xms_cold_shoulder": {"ru": "Сосулька", "en": "Icicle"}
        }
    }
}

# Специальные режимы (эффекты)
SPECIAL_MODES = {
    "CritHIT": "critHIT"
}

# Классы TF2 с иконками и цветами
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

# Типы оружия
WEAPON_TYPES = {
    "Primary": {"ru": "Основное", "en": "Primary"},
    "Secondary": {"ru": "Дополнительное", "en": "Secondary"},
    "Melee": {"ru": "Ближний бой", "en": "Melee"}
}

# Функция для получения названия оружия по языку
def get_weapon_name(class_name: str, weapon_type: str, weapon_key: str, language: str = "ru") -> str:
    """
    Получает название оружия на указанном языке
    
    Args:
        class_name: Имя класса (Scout, Soldier, etc.)
        weapon_type: Тип оружия (Primary, Secondary, Melee)
        weapon_key: Ключ оружия (c_scattergun, etc.)
        language: Язык ('ru' или 'en')
    
    Returns:
        Название оружия на указанном языке или weapon_key, если не найдено
    """
    if class_name not in TF2_WEAPONS:
        return weapon_key
    
    if weapon_type not in TF2_WEAPONS[class_name]:
        return weapon_key
    
    if weapon_key not in TF2_WEAPONS[class_name][weapon_type]:
        return weapon_key
    
    weapon_data = TF2_WEAPONS[class_name][weapon_type][weapon_key]
    
    # Если это словарь с языками
    if isinstance(weapon_data, dict):
        return weapon_data.get(language, weapon_data.get("ru", weapon_key))
    
    # Если это строка (старый формат для обратной совместимости)
    return weapon_data

# Функция для получения типа оружия по языку
def get_weapon_type_name(weapon_type: str, language: str = "ru") -> str:
    """
    Получает название типа оружия на указанном языке
    
    Args:
        weapon_type: Тип оружия (Primary, Secondary, Melee)
        language: Язык ('ru' или 'en')
    
    Returns:
        Название типа оружия на указанном языке
    """
    return WEAPON_TYPES.get(weapon_type, {}).get(language, weapon_type)

# Маппинг weaponkey на пути моделей внутри TF2 VPK
# Формат: models/weapons/c_models/<weapon_key>/<weapon_key>.mdl
# Структура: каждая модель находится в своей папке
WEAPON_MDL_PATHS = {}
for class_name, class_weapons in TF2_WEAPONS.items():
    for weapon_type, weapons in class_weapons.items():
        for weapon_key in weapons.keys():
            # Путь включает папку с именем оружия: models/weapons/c_models/<weapon_key>/<weapon_key>.mdl
            if weapon_key.startswith("c_") or weapon_key.startswith("w_"):
                WEAPON_MDL_PATHS[weapon_key] = f"models/weapons/c_models/{weapon_key}/{weapon_key}.mdl"
            else:
                # Для некоторых оружий путь может отличаться (например, demo_booties, pegleg)
                # По умолчанию используем стандартный путь с папкой
                WEAPON_MDL_PATHS[weapon_key] = f"models/weapons/c_models/{weapon_key}/{weapon_key}.mdl"
