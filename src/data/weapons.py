from typing import Optional

TF2_WEAPONS = {
    "Scout": {
        "PlayerSkin": {
            "body": {"ru": "Скин персонажа", "en": "Player Skin"},
        },
        "Primary": {
            "c_scattergun": {"ru": "Обрез", "en": "Scattergun"},
            "c_double_barrel": {"ru": "Неумолимая сила", "en": "Force-A-Nature"},
            "c_shortstop": {"ru": "Прерыватель", "en": "Shortstop"},
            "c_soda_popper": {"ru": "Газировщик", "en": "Soda Popper"},
            "c_pep_scattergun": {"ru": "Обрез Малыша", "en": "Baby Face's Blaster"},
            "c_scatterdrum": {"ru": "Спинобрез", "en": "Back Scatter"},
            "c_scattergun_xmas": {"ru": "Праздничный обрез", "en": "Festive Scattergun"},
            "c_xms_double_barrel": {"ru": "Праздничная Неумолимая сила", "en": "Festive Force-a-Nature"}
        },
        "Secondary": {
            "c_pistol": {"ru": "Пистолет", "en": "Pistol"},
            "c_ttg_max_gun": {"ru": "Люгерморф", "en": "Lugermorph"},
            "c_invasion_pistol": {"ru": "З.А.Х.В.А.Т.Ч.И.К.", "en": "C.A.P.P.E.R"},
            "c_sd_cleaver": {"ru": "Летающая гильотина", "en": "Flying Guillotine"},
            "c_energy_drink": {"ru": "Бонк! Атомный залп", "en": "Bonk! Atomic Punch"},
            "c_madmilk": {"ru": "Зломолоко", "en": "Mad Milk"},
            "c_winger_pistol": {"ru": "Окрыленный", "en": "Winger"},
            "c_pep_pistol": {"ru": "Дамский пистолет Красавчика", "en": "Pretty Boy's Pocket Pistol"},
            "c_breadmonster_milk": {"ru": "Мутировавшее молоко", "en": "Mutated Milk"},
            "c_xms_energy_drink": {"ru": "Праздничный Бонк! Атомный залп", "en": "Festive Bonk! Atomic Punch"}
        },
        "Melee": {
            "c_bat": {"ru": "Бита", "en": "Bat"},
            "c_wooden_bat": {"ru": "Дрёма", "en": "Sandman"},
            "c_holymackerel": {"ru": "Поддай леща", "en": "Holy Mackerel"},
            "c_bonk_bat": {"ru": "Расщепитель", "en": "Atomizer"},
            "c_candy_cane": {"ru": "Карамельная трость", "en": "Candy Cane"},
            "c_boston_basher": {"ru": "Бостонский раздолбай", "en": "Boston Basher"},
            "c_scout_sword": {"ru": "Трехрунный меч", "en": "Three-Rune Blade"},
            "c_rift_fire_mace": {"ru": "Солнце на палочке", "en": "Sun-On-A-Stick"},
            "c_xms_giftwrap": {"ru": "Обёрточный убийца", "en": "Wrap Assassin"},
            "c_invasion_bat": {"ru": "Световая бита", "en": "Batsaber"},
            "c_shogun_warfan": {"ru": "Веер войны", "en": "Fan O'War"},
            "c_crossing_guard": {"ru": "Регулировщик", "en": "Crossing Guard"},
            "c_bat_xmas": {"ru": "Праздничная бита", "en": "Festive Bat"},
            "c_holymackerel_xmas": {"ru": "Праздничный Поддай леща", "en": "Festive Holy Mackerel"}
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
            "c_rocketlauncher": {"ru": "Ракетомёт", "en": "Rocket Launcher"},
            "c_bet_rocketlauncher": {"ru": "Прародитель", "en": "Original"},
            "c_directhit": {"ru": "Прямое попадание", "en": "Direct Hit"},
            "c_blackbox": {"ru": "Чёрный ящик", "en": "Black Box"},
            "c_blackbox_xmas": {"ru": "Праздничный Чёрный ящик", "en": "Festive Black Box"},
            "c_dumpster_device": {"ru": "Базука бродяги", "en": "Beggar's Bazooka"},
            "c_liberty_launcher": {"ru": "Освободитель", "en": "Liberty Launcher"},
            "c_drg_cowmangler": {"ru": "Линчеватель скота 5000", "en": "Cow Mangler 5000"},
            "c_atom_launcher": {"ru": "Авиаудар", "en": "Air Strike"},
            "c_rocketjumper": {"ru": "Тренировочный ракетомёт", "en": "Rocket Jumper"},
            "c_rocketlauncher_xmas": {"ru": "Праздничный ракетомёт", "en": "Festive Rocket Launcher"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Дробовик", "en": "Shotgun"},
            "c_reserve_shooter": {"ru": "Офицер запаса", "en": "Reserve Shooter"},
            "c_buffpack": {"ru": "Вдохновляющее знамя", "en": "Buff Banner"},
            "c_bugle": {"ru": "Вдохновляющее знамя (горн)", "en": "Buff Banner (bugle)"},
            "c_rocketboots_soldier": {"ru": "Штурмботинки", "en": "Gunboats"},
            "c_battalion_buffpack": {"ru": "Поддержка батальона", "en": "Battalion's Backup"},
            "c_battalion_bugle": {"ru": "Поддержка батальона (горн)", "en": "Battalion's Backup (bugle)"},
            "c_shogun_warpack": {"ru": "Завоеватель", "en": "Concheror"},
            "c_shogun_warhorn": {"ru": "Завоеватель (горн)", "en": "Concheror (horn)"},
            "c_drg_righteousbison": {"ru": "Благочестивый бизон", "en": "Righteous Bison"},
            "tankerboots": {"ru": "Людодавы", "en": "Mantreads"},
            "c_paratrooper_pack": {"ru": "Парашютист", "en": "B.A.S.E. Jumper"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"},
            "c_buffpack_xmas": {"ru": "Праздничное Вдохновляющее знамя", "en": "Festive Buff Banner"}
        },
        "Melee": {
            "c_shovel": {"ru": "Лопата", "en": "Shovel"},
            "c_pickaxe_s2": {"ru": "Уравнитель", "en": "Equalizer"},
            "c_shogun_katana_soldier": {"ru": "Полудзатоити", "en": "Half-Zatoichi"},
            "c_riding_crop": {"ru": "Дисциплинарное взыскание", "en": "Disciplinary Action"},
            "c_market_gardener": {"ru": "Землекоп", "en": "Market Gardener"},
            "c_pickaxe": {"ru": "План эвакуации", "en": "Escape Plan"},
            "c_ham": {"ru": "Свиной окорок", "en": "Ham Shank"},
            "c_paintrain": {"ru": "Костыль", "en": "Pain Train"}
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
            "c_flamethrower": {"ru": "Огнемёт", "en": "Flame Thrower"},
            "c_rainblower": {"ru": "Радужигатель", "en": "Rainblower"},
            "c_ai_flamethrower": {"ru": "Ностромский пламемет", "en": "Nostromo Napalmer"},
            "c_backburner": {"ru": "Дожигатель", "en": "Backburner"},
            "c_degreaser": {"ru": "Чистильщик", "en": "Degreaser"},
            "c_drg_phlogistinator": {"ru": "Флогистонатор", "en": "Phlogistinator"},
            "c_flameball": {"ru": "Ярость дракона", "en": "Dragon's Fury"},
            "c_flamethrower_xmas": {"ru": "Праздничный огнемёт", "en": "Festive Flame Thrower"},
            "c_backburner_xmas": {"ru": "Праздничный дожигатель", "en": "Festive Backburner"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Дробовик", "en": "Shotgun"},
            "c_reserve_shooter": {"ru": "Офицер запаса", "en": "Reserve Shooter"},
            "c_flaregun_pyro": {"ru": "Ракетница", "en": "Flare Gun"},
            "c_detonator": {"ru": "Детонатор", "en": "Detonator"},
            "c_scorch_shot": {"ru": "Обжигающий выстрел", "en": "Scorch Shot"},
            "c_rocketpack": {"ru": "Термическая тяга", "en": "Thermal Thruster"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"},
            "c_drg_manmelter": {"ru": "Людоплав", "en": "Manmelter"},
            "c_gascan": {"ru": "Запасной бак", "en": "Gas Passer"},
            "c_xms_flaregun": {"ru": "Праздничная Ракетница", "en": "Festive Flare Gun"}
        },
        "Melee": {
            "c_fireaxe": {"ru": "Пожарный топор", "en": "Fire Axe"},
            "c_axtinguisher_pyro": {"ru": "Огнетопор", "en": "Axtinguisher"},
            "c_mailbox": {"ru": "Почтовый дебошир", "en": "Postal Pummeler"},
            "c_powerjack": {"ru": "Разъединитель", "en": "Powerjack"},
            "c_sledgehammer": {"ru": "Крушитель", "en": "Homewrecker"},
            "c_back_scratcher": {"ru": "Спиночёс", "en": "Back Scratcher"},
            "c_drg_thirddegree": {"ru": "Третья степень", "en": "Third Degree"},
            "c_sd_neonsign": {"ru": "Неоновый аннигилятор", "en": "Neon Annihilator"},
            "c_slapping_glove": {"ru": "Горячая рука", "en": "Hot Hand"},
            "c_lollichop": {"ru": "Кледенец", "en": "Lollichop"},
            "c_rift_fire_axe": {"ru": "Заостренный осколок вулкана", "en": "Sharpened Volcano Fragment"},
            "c_fireaxe_pyro_xmas": {"ru": "Праздничный огнетопор", "en": "Festive Axtinguisher"},
            "c_rfa_hammer": {"ru": "Молот", "en": "Maul"}
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
            "c_grenadelauncher": {"ru": "Гранатомёт", "en": "Grenade Launcher"},
            "c_lochnload": {"ru": "Подкидыш", "en": "Loch-N-Load"},
            "demo_booties": {"ru": "Ботиночки Али-Бабы", "en": "Ali Baba's Wee Booties"},
            "pegleg": {"ru": "Бутлегер", "en": "Bootlegger"},
            "c_demo_cannon": {"ru": "Пушка без лафета", "en": "Loose Cannon"},
            "c_quadball": {"ru": "Железный бомбардир", "en": "Iron Bomber"},
            "c_grenadelauncher_xmas": {"ru": "Праздничный гранатомёт", "en": "Festive Grenade Launcher"}
        },
        "Secondary": {
            "c_stickybomb_launcher": {"ru": "Липучкомёт", "en": "Stickybomb Launcher"},
            "c_scottish_resistance": {"ru": "Шотландское сопротивление", "en": "Scottish Resistance"},
            "c_sticky_jumper": {"ru": "Тренировочный липучкомёт", "en": "Sticky Jumper"},
            "c_targe": {"ru": "Штурмовой щит", "en": "Chargin' Targe"},
            "c_persian_shield": {"ru": "Роскошное прикрытие", "en": "Splendid Screen"},
            "c_kingmaker_sticky": {"ru": "Быстромёт", "en": "Quickiebomb Launcher"},
            "c_wheel_shield": {"ru": "Верный штурвал", "en": "Tide Turner"},
            "c_stickybomb_launcher_xmas": {"ru": "Праздничный липучкомёт", "en": "Festive Stickybomb Launcher"},
            "c_targe_xmas": {"ru": "Праздничный Штурмовой щит", "en": "Festive Chargin' Targe"}
        },
        "Melee": {
            "c_bottle": {"ru": "Бутылка", "en": "Bottle"},
            "c_claymore": {"ru": "Одноглазый горец", "en": "Eyelander"},
            "c_battleaxe": {"ru": "Шотландский головорез", "en": "Scotsman's Skullcutter"},
            "c_headtaker": {"ru": "Секира Пешего всадника без головы", "en": "Horseless Headless Horsemann's Headtaker"},
            "c_caber": {"ru": "Аллапульское бревно", "en": "Ullapool Caber"},
            "c_claidheamohmor": {"ru": "Клеймор", "en": "Claidheamh Mòr"},
            "c_shogun_katana": {"ru": "Полудзатоити", "en": "Half-Zatoichi"},
            "c_demo_sultan_sword": {"ru": "Персидский заклинатель", "en": "Persian Persuader"},
            "c_scotland_shard": {"ru": "Шотландское рукобитие", "en": "Scottish Handshake"},
            "c_golfclub": {"ru": "Железная девятка Несси", "en": "Nessie's Nine Iron"},
            "c_paintrain": {"ru": "Костыль", "en": "Pain Train"},
            "c_claymore_xmas": {"ru": "Праздничный одноглазый горец", "en": "Festive Eyelander"}
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
            "c_minigun": {"ru": "Пулемёт", "en": "Minigun"},
            "c_iron_curtain": {"ru": "Железный занавес", "en": "Iron Curtain"},
            "c_minigun_natascha": {"ru": "Наташа", "en": "Natascha"},
            "c_gatling_gun": {"ru": "Латунный монстр", "en": "Brass Beast"},
            "c_tomislav": {"ru": "Томислав", "en": "Tomislav"},
            "c_canton": {"ru": "Огненный дракон", "en": "Huo-Long Heater"},
            "c_minigun_xmas": {"ru": "Праздничный пулемёт", "en": "Festive Minigun"}
        },
        "Secondary": {
            "c_shotgun": {"ru": "Дробовик", "en": "Shotgun"},
            "c_sandwich": {"ru": "Бутерброд", "en": "Sandvich"},
            "c_chocolate": {"ru": "Плитка \"Далокош\"", "en": "Dalokohs Bar"},
            "c_fishcake": {"ru": "Рыбный батончик", "en": "Fishcake"},
            "c_buffalo_steak": {"ru": "Бутерброд из мяса буйвола", "en": "Buffalo Steak Sandvich"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"},
            "c_banana": {"ru": "Утешительный банан", "en": "Second Banana"},
            "c_robo_sandwich": {"ru": "Робо-бутерброд", "en": "Robo-Sandvich"},
            "c_russian_riot": {"ru": "Семейное дело", "en": "Family Business"},
            "c_sandwich_xmas": {"ru": "Праздничный бутерброд", "en": "Festive Sandvich"}
        },
        "Melee": {
            "c_sr3_punch": {"ru": "Кулакопокалипсис", "en": "Apoco-Fists"},
            "c_fists_of_steel": {"ru": "Стальные кулаки", "en": "Fists Of Steel"},
            "c_boxing_gloves": {"ru": "Кулаки грозного боксёра", "en": "Killing Gloves Of Boxing"},
            "c_breadmonster_gloves": {"ru": "Кусай-хлеб", "en": "Bread Bite"},
            "c_bear_claw": {"ru": "Воинский дух", "en": "Warrior's Spirit"},
            "c_eviction_notice": {"ru": "Уведомление о выселении", "en": "Eviction Notice"},
            "c_xms_gloves": {"ru": "Праздничный удар", "en": "Holiday Punch"},
            "c_boxing_gloves_xmas": {"ru": "Праздничные Горящие Рукавицы Ускорения", "en": "Festive Gloves of Running Urgently"}
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
            "c_shotgun": {"ru": "Дробовик", "en": "Shotgun"},
            "c_drg_pomson": {"ru": "Помсон 6000", "en": "Pomson 6000"},
            "c_dex_shotgun": {"ru": "Овдовитель", "en": "Widowmaker"},
            "c_tele_shotgun": {"ru": "Спасатель", "en": "Rescue Ranger"},
            "c_trenchgun": {"ru": "Паническая атака", "en": "Panic Attack"},
            "c_frontierjustice": {"ru": "Самосуд", "en": "Frontier Justice"},
            "c_frontierjustice_xmas": {"ru": "Праздничный Самосуд", "en": "Festive Frontier Justice"}
        },
        "Secondary": {
            "c_pistol": {"ru": "Пистолет", "en": "Pistol"},
            "c_ttg_max_gun": {"ru": "Люгерморф", "en": "Lugermorph"},
            "c_invasion_pistol": {"ru": "З.А.Х.В.А.Т.Ч.И.К.", "en": "C.A.P.P.E.R"},
            "c_wrangler": {"ru": "Поводырь", "en": "Wrangler"},
            "c_invasion_wrangler": {"ru": "Счётчик Гигера", "en": "Giger Counter"},
            "c_dex_arm": {"ru": "Короткое замыкание", "en": "Short Circuit"},
            "c_wrangler_xmas": {"ru": "Праздничный поводырь", "en": "Festive Wrangler"}
        },
        "Melee": {
            "c_wrench": {"ru": "Гаечный ключ", "en": "Wrench"},
            "c_spikewrench": {"ru": "Южное гостеприимство", "en": "Southern Hospitality"},
            "c_jag": {"ru": "Острозуб", "en": "Jag"},
            "c_drg_wrenchmotron": {"ru": "Озарение", "en": "Eureka Effect"},
            "c_wrench_xmas": {"ru": "Праздничный гаечный ключ", "en": "Festive Wrench"}
        },
        "PDA": {
            "c_builder": {"ru": "КПК постройки", "en": "Construction PDA"},
            "c_pda_engineer": {"ru": "КПК разрушения", "en": "Destruction PDA"},
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
            "c_syringegun": {"ru": "Шприцемёт", "en": "Syringe Gun"},
            "c_leechgun": {"ru": "Кровопийца", "en": "Blutsauger"},
            "c_crusaders_crossbow": {"ru": "Арбалет крестоносца", "en": "Crusader's Crossbow"},
            "c_crusaders_crossbow_xmas": {"ru": "Праздничный Арбалет крестоносца", "en": "Festive Crusader's Crossbow"},
            "c_proto_syringegun": {"ru": "Передоз", "en": "Overdose"}
        },
        "Secondary": {
            "c_medigun": {"ru": "Лечебная пушка", "en": "Medi Gun"},
            "c_proto_medigun": {"ru": "Быстроправ", "en": "Quick-Fix"},
            "c_medigun_defence": {"ru": "Вакцинатор", "en": "Vaccinator"},
            "c_medigun_xmas": {"ru": "Праздничная лечебная пушка", "en": "Festive Medi Gun"}
        },
        "Melee": {
            "c_bonesaw": {"ru": "Медицинская пила", "en": "Bonesaw"},
            "c_ubersaw": {"ru": "Убер-пила", "en": "Übersaw"},
            "c_uberneedle": {"ru": "Вита-пила", "en": "Vita-Saw"},
            "c_amputator": {"ru": "Ампутатор", "en": "Amputator"},
            "c_hippocrates_bust": {"ru": "Священная клятва", "en": "Solemn Vow"},
            "c_bonesaw_xmas": {"ru": "Праздничная медицинская пила", "en": "Festive Bonesaw"},
            "c_ubersaw_xmas": {"ru": "Праздничная убер-пила", "en": "Festive Übersaw"}
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
            "c_sniperrifle": {"ru": "Снайперская винтовка", "en": "Sniper Rifle"},
            "c_csgo_awp": {"ru": "Слонобой", "en": "AWPer Hand"},
            "c_bow": {"ru": "Охотник", "en": "Huntsman"},
            "c_bow_thief": {"ru": "Укрепленный составной лук", "en": "Fortified Compound"},
            "c_dartgun": {"ru": "Сиднейский соня", "en": "Sydney Sleeper"},
            "c_bazaar_sniper": {"ru": "Базарная безделушка", "en": "Bazaar Bargain"},
            "c_dex_sniperrifle": {"ru": "Махина", "en": "Machina"},
            "c_invasion_sniperrifle": {"ru": "Падающая звезда", "en": "Shooting Star"},
            "c_pro_rifle": {"ru": "Разжигатель разбойника", "en": "Hitman's Heatmaker"},
            "c_tfc_sniperrifle": {"ru": "Классика", "en": "Classic"},
            "c_sniperrifle_xmas": {"ru": "Праздничная снайперская винтовка", "en": "Festive Sniper Rifle"},
            "c_bow_xmas": {"ru": "Праздничный охотник", "en": "Festive Huntsman"}
        },
        "Secondary": {
            "c_smg": {"ru": "Пистолет-пулемёт", "en": "SMG"},
            "c_pro_smg": {"ru": "Карабин Чистильщика", "en": "Cleaner's Carbine"},
            "urinejar": {"ru": "Банкате", "en": "Jarate"},
            "c_breadmonster": {"ru": "Родинка с самосознанием", "en": "Self-Aware Beauty Mark"},
            "knife_shield": {"ru": "Бронепанцирь", "en": "Razorback"},
            "croc_shield": {"ru": "Дарвинистский щит", "en": "Darwin's Danger Shield"},
            "xms_sniper_commandobackpack": {"ru": "Набор для кемпинга", "en": "Cozy Camper"},
            "c_smg_xmas": {"ru": "Праздничный пистолет-пулемёт", "en": "Festive SMG"},
            "c_xms_urinejar": {"ru": "Праздничное Банкате", "en": "Festive Jarate"}
        },
        "Melee": {
            "c_machete": {"ru": "Кукри", "en": "Kukri"},
            "c_wood_machete": {"ru": "Заточка дикаря", "en": "Tribalman's Shiv"},
            "c_croc_knife": {"ru": "Кустолом", "en": "Bushwacka"},
            "c_scimitar": {"ru": "Шаханшах", "en": "Shahanshah"},
            "c_prinny_knife": {"ru": "Мачете Принни", "en": "Prinny Machete"}
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
            "c_revolver": {"ru": "Револьвер", "en": "Revolver"},
            "c_snub_nose": {"ru": "Принудитель", "en": "Enforcer"},
            "c_ambassador": {"ru": "Амбассадор", "en": "Ambassador"},
            "c_letranger": {"ru": "Незнакомец", "en": "L'Étranger"},
            "c_dex_revolver": {"ru": "Алмазный змей", "en": "Diamondback"},
            "c_revolver_xmas": {"ru": "Праздничный револьвер", "en": "Festive Revolver"},
            "c_ambassador_xmas": {"ru": "Праздничный амбассадор", "en": "Festive Ambassador"}
        },
        "Secondary": {
            "c_sapper": {"ru": "Жучок", "en": "Sapper"},
            "c_p2rec": {"ru": "Жучок-Уитличок", "en": "Ap-Sap"},
            "c_breadmonster_sapper": {"ru": "Закусочная атака", "en": "Snack Attack"},
            "w_sd_sapper": {"ru": "Откатофон", "en": "Red-Tape Recorder"},
            "c_ttg_sam_gun": {"ru": "Грандиозный убийца", "en": "Big Kill"},
            "c_sapper_xmas": {"ru": "Праздничный жучок", "en": "Festive Sapper"}
        },
        "Melee": {
            "c_knife": {"ru": "Нож", "en": "Knife"},
            "c_acr_hookblade": {"ru": "Одетый с иголочки", "en": "Sharp Dresser"},
            "c_ava_roseknife": {"ru": "Чёрная роза", "en": "Black Rose"},
            "c_eternal_reward": {"ru": "Вечный покой", "en": "Your Eternal Reward"},
            "c_voodoo_pin": {"ru": "Иголка вуду", "en": "Wanga Prick"},
            "c_shogun_kunai": {"ru": "Кунай заговорщика", "en": "Conniver's Kunai"},
            "c_switchblade": {"ru": "Главный делец", "en": "Big Earner"},
            "c_xms_cold_shoulder": {"ru": "Сосулька", "en": "Spy-Cicle"},
            "c_unarmed_combat": {"ru": "Голая рука", "en": "Unarmed Combat"},
            "c_knife_xmas": {"ru": "Праздничный нож", "en": "Festive Knife"}
        },
        "Watch": {
            "c_spy_watch": {"ru": "Часы невидимости", "en": "Invis Watch"},
            "c_leather_watch": {"ru": "Плащ и кинжал", "en": "Cloak and Dagger"},
            "c_pocket_watch": {"ru": "Звон смерти", "en": "Dead Ringer"},
            "v_hm_watch": {"ru": "Крякенптиц", "en": "Quäckenbirdt"},
            "v_ttg_watch_spy": {"ru": "Часы ярого поклонника", "en": "Enthusiast's Timepiece"},
        },
        "Hands": {
            "hands": {"ru": "Руки", "en": "Hands"},
        },
    },
    "All-Class": {
        "Secondary": {
            "c_shotgun_xmas": {"ru": "Праздничный дробовик", "en": "Festive Shotgun"}
        },
        "Melee": {
            "c_frying_pan": {"ru": "Сковорода", "en": "Frying Pan"},
            "c_saxxy": {"ru": "Сакси", "en": "Saxxy"},
            "c_picket": {"ru": "Идейный уклонист", "en": "Conscientious Objector"},
            "c_carnival_mallet": {"ru": "Трупоколотушка", "en": "Necro Smasher"},
            "c_skullbat": {"ru": "Дубина из ада", "en": "Bat Outta Hell"},
            "c_tw_eagle": {"ru": "Посох свободы", "en": "Freedom Staff"},
            "c_8mm_camera": {"ru": "Создатель воспоминаний", "en": "Memory Maker"}
        },
    }
}

# Специальные режимы (эффекты). Только значения нужны везде (mode in SPECIAL_MODES)
SPECIAL_MODES = (
    "critHIT",
    "spray",
    # Скины эффектов смерти (override игровых материалов рагдолла, client-side):
    "death_ice",    # лёд (как от Sky-cicle)    -> models/player/shared/ice_player
    "death_gold",   # золото (Golden Pan/Saxxy) -> models/player/shared/gold_player
    "death_fire",   # огонь горящего игрока     -> effects/tiledfire/fireLayeredSlowTiled512
)

# Спец-режимы, где пишем ТОЛЬКО VTF (без VMT): эти материалы используют особый
# игровой шейдер/прокси (cloak/цвет/scroll), поэтому собственный VMT их сломает -
# игровой VMT сам подхватит нашу текстуру по тому же пути
VTF_ONLY_SPECIAL_MODES = {"death_ice", "death_gold", "death_fire"}

TF2_CLASSES = (
    "Scout", "Soldier", "Pyro", "Demoman", "Heavy",
    "Engineer", "Medic", "Sniper", "Spy", "All-Class",
)

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

# Слоты оружия - то, что показывается в списке «Тип оружия» под категорией «Оружие».
# PlayerSkin/Hands/Custom сюда НЕ входят: они в других категориях.
# Watch (часы шпиона) и PDA (КПК инженера) показываются только у тех классов,
# где они есть (по TF2_WEAPONS)
WEAPON_SLOT_TYPES = ["Primary", "Secondary", "Melee", "Watch", "PDA"]

#: Оружие, которое в игре - другая строка скина модели из таблицы, а не своя
#: модель: «Критокола» - строка 2 модели Бонка (`"visuals" { "skin" "2" }`,
#: см. item_skin_styles). В каталоге - своей строкой, открывается сразу на
#: этом стиле. Из items_game список не вывести: строку-копию (у огнемёта
#: «Ботоубийц») от настоящей отличает только QC модели.
#: {класс: {слот: [(ключ модели, строка скина, имена, иконка)]}}
WEAPON_SKIN_ITEMS = {
    "Scout": {
        "Secondary": [
            ("c_energy_drink", 2, {"ru": "Критокола", "en": "Crit-a-Cola"},
             "backpack/weapons/c_models/c_energy_drink/c_critcola"),
        ],
    },
}

# Типы оружия, которые относятся к категории «Персонаж» (тело + руки)
CHARACTER_PART_TYPES = ["PlayerSkin", "Hands"]


def get_character_parts(class_name: str, language: str = "ru") -> list:
    """
    Возвращает части персонажа (тело + руки) для категории «Персонаж»
    как список (key, display_name)

    Объединяет записи PlayerSkin и Hands выбранного класса. mode для каждой
    части строится как f"{class.lower()}_{key}" (scout_body, scout_hands,
    engineer_mech_hands, spy_masks и т.д.)
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
    """Обратный lookup: ключ типа оружия по его переведённому названию (или None)"""
    for key in WEAPON_TYPES:
        if get_weapon_type_name(key, language) == type_name:
            return key
    return None


def weapon_key_from_mode(mode: str) -> str:
    """
    Извлекает ключ оружия из mode-строки обычного оружия

    mode имеет вид "<class>_<weaponkey>" (например "scout_c_scattergun"),
    поэтому берём часть после первого '_'. Если '_' нет - возвращаем mode как есть
    """
    return mode.split('_', 1)[1] if '_' in mode else mode

WEAPON_MDL_PATHS = {}
for class_name, class_weapons in TF2_WEAPONS.items():
    for weapon_type, weapons in class_weapons.items():
        if weapon_type in ("Hands", "PlayerSkin"):
            continue  # Hands and PlayerSkin have no MDL in the build pipeline
        for weapon_key in weapons.keys():
            WEAPON_MDL_PATHS[weapon_key] = f"models/weapons/c_models/{weapon_key}/{weapon_key}.mdl"

# Нестандартные пути MDL (папка или имя файла не совпадают с ключом оружия)

# Праздничные Неумолимая сила и Банкате: файл прямо в c_models/, без папки
WEAPON_MDL_PATHS["c_xms_double_barrel"] = "models/weapons/c_models/c_xms_double_barrel.mdl"
WEAPON_MDL_PATHS["c_xms_urinejar"] = "models/weapons/c_models/c_xms_urinejar.mdl"

# Молот (Maul): workshop/
WEAPON_MDL_PATHS["c_rfa_hammer"] = (
    "models/workshop/weapons/c_models/c_rfa_hammer/c_rfa_hammer.mdl"
)

# Mutated Milk: общая папка c_breadmonster/, файл c_breadmonster_milk.mdl
WEAPON_MDL_PATHS["c_breadmonster_milk"] = (
    "models/weapons/c_models/c_breadmonster/c_breadmonster_milk.mdl"
)

# Axtinguisher: папка c_axtinguisher/, файл c_axtinguisher_pyro.mdl
WEAPON_MDL_PATHS["c_axtinguisher_pyro"] = (
    "models/weapons/c_models/c_axtinguisher/c_axtinguisher_pyro.mdl"
)

# Знамёна в каталоге - рюкзаки (extra_wearable в items_game), в руке у них
# своя модель-горн, её вид от первого лица берёт по WeaponAnimInfo.held.
# Battalion's Backup: игра берёт workshop-модель (c_batt_buffpack в
# c_models - её старая копия, не «Вдохновляющее знамя»)
WEAPON_MDL_PATHS["c_battalion_buffpack"] = (
    "models/workshop/weapons/c_models/c_battalion_buffpack/c_battalion_buffpack.mdl"
)

# Горн Поддержки батальона: игра берёт workshop-модель (как и рюкзак).
# Горны знамён - отдельные предметы: в игре это своя модель (model_player),
# у рюкзака её не перекрасить
WEAPON_MDL_PATHS["c_battalion_bugle"] = (
    "models/workshop/weapons/c_models/c_battalion_bugle/c_battalion_bugle.mdl"
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

# Mantreads (Людодавы): player-item, не c_models
WEAPON_MDL_PATHS["tankerboots"] = (
    "models/player/items/soldier/tankerboots.mdl"
)

# Darwin's Danger Shield (Дарвинистский щит): player-item, не c_models
WEAPON_MDL_PATHS["croc_shield"] = (
    "models/player/items/sniper/croc_shield.mdl"
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

# Часы шпиона: Invis Watch лежит плоским файлом, Dead Ringer и Cloak and Dagger -
# в подпапке parts/. КПК инженера (c_builder, c_pda_engineer) совпадают с дефолтом
WEAPON_MDL_PATHS["c_spy_watch"] = (
    "models/weapons/c_models/c_spy_watch.mdl"
)
WEAPON_MDL_PATHS["c_pocket_watch"] = (
    "models/weapons/c_models/c_pocket_watch/parts/c_pocket_watch.mdl"
)
WEAPON_MDL_PATHS["c_leather_watch"] = (
    "models/weapons/c_models/c_leather_watch/parts/c_leather_watch.mdl"
)
# Крякенптиц и Часы ярого поклонника: мировой модели у них нет, в игре только
# вьюмодели (items_game: model_player = v_*). Крякенптиц - из workshop_partner
WEAPON_MDL_PATHS["v_hm_watch"] = (
    "models/workshop_partner/weapons/v_models/v_hm_watch/v_hm_watch.mdl"
)
WEAPON_MDL_PATHS["v_ttg_watch_spy"] = "models/weapons/v_models/v_ttg_watch_spy.mdl"

# Праздничные (xmas) модели
# Festive-модель лежит в папке БАЗОВОГО оружия (c_rocketlauncher/c_rocketlauncher_xmas),
# а не в собственной. Точный путь всё равно берётся из items_game.txt первым, это -
# фолбэк, когда items_game недоступен. Папка = ключ без суффикса _xmas, кроме особых
_FESTIVE_BASE_FOLDER = {
    "c_backburner_xmas": "c_flamethrower",  # дожигатель - в папке огнемёта
}
for _k in [k for k in WEAPON_MDL_PATHS if k.endswith("_xmas")]:
    _folder = _FESTIVE_BASE_FOLDER.get(_k, _k[:-len("_xmas")])
    WEAPON_MDL_PATHS[_k] = f"models/weapons/c_models/{_folder}/{_k}.mdl"
# Праздничный поводырь лежит прямо в c_models/ без подпапки
WEAPON_MDL_PATHS["c_wrangler_xmas"] = "models/weapons/c_models/c_wrangler_xmas.mdl"
# Цельные праздничные версии оружия из мастерской лежат в models/workshop/
for _k in ("c_blackbox_xmas", "c_holymackerel_xmas", "c_crusaders_crossbow_xmas"):
    WEAPON_MDL_PATHS[_k] = f"models/workshop/weapons/c_models/{_k[:-len('_xmas')]}/{_k}.mdl"

# Модели рук (c_class_arms)
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
    # Это обеспечивает совпадение ключа кэша при повторных запусках
    WEAPON_MDL_PATHS[_arm] = f"models/weapons/c_models/{_arm}.mdl"

# Модели тел персонажей (models/player/)
# Используются для 3D Preview; в pipeline сборки VPK не задействованы
WEAPON_MDL_PATHS["player_scout"]    = "models/player/scout.mdl"
WEAPON_MDL_PATHS["player_soldier"]  = "models/player/soldier.mdl"
WEAPON_MDL_PATHS["player_pyro"]     = "models/player/pyro.mdl"
WEAPON_MDL_PATHS["player_demo"]     = "models/player/demo.mdl"
WEAPON_MDL_PATHS["player_heavy"]    = "models/player/heavy.mdl"
WEAPON_MDL_PATHS["player_engineer"] = "models/player/engineer.mdl"
WEAPON_MDL_PATHS["player_medic"]    = "models/player/medic.mdl"
WEAPON_MDL_PATHS["player_sniper"]   = "models/player/sniper.mdl"
WEAPON_MDL_PATHS["player_spy"]      = "models/player/spy.mdl"

# Снаряды (w_models): mode = projectile_<key>, weapon_key = <key>
# Трактуются как обычное оружие, поэтому путь к MDL должен быть в WEAPON_MDL_PATHS
from src.data.projectiles import PROJECTILE_MDL_PATHS as _PROJECTILE_MDL_PATHS
WEAPON_MDL_PATHS.update(_PROJECTILE_MDL_PATHS)

# Пикапы (аптечки/патроны, models/items/): mode = pickup_<key>
from src.data.pickups import PICKUP_MDL_PATHS as _PICKUP_MDL_PATHS
WEAPON_MDL_PATHS.update(_PICKUP_MDL_PATHS)

# Реквизит насмешек (taunt props): mode = taunt_<key>
from src.data.taunt_props import TAUNT_PROP_MDL_PATHS as _TAUNT_PROP_MDL_PATHS
WEAPON_MDL_PATHS.update(_TAUNT_PROP_MDL_PATHS)
