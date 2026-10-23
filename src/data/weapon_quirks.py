"""
Особые правила моделей оружия для сборки и превью: что у конкретной модели
устроено не как у всех. Каталог (названия по классам и слотам) и пути MDL -
в weapons.py; здесь - исключения, которые читают сборка и 3D-превью:
доп. текстуры по фиксированным путям, оружие без BLU, зеркальные VMT,
«только материалы», подмена модели превью и фильтр своих материалов,
доп. файлы мода, нестандартные пути VTF
"""

# Доп. текстуры по фиксированному пути (вне QC/модели)
# Некоторые предметы используют текстуры, которых НЕТ ни в $texturegroup, ни в
# геометрии модели (например HUD-вставки Dead Ringer). Их нельзя найти через
# материалы модели - путь зашит в игре. Здесь задаём такие текстуры явно:
#   {weapon_key: [{"name", "vpk" (путь в VPK с materials/...vtf), "ru", "en"}]}
# Превью покажет для них слот, сборка запишет картинку ровно по этому пути
WEAPON_EXTRA_TEXTURES: dict[str, list[dict]] = {
    "c_pocket_watch": [
        {
            "name": "pocket_watch_fg",
            "vpk":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_fg.vtf",
            # Оригинал в игре - здесь, мод кладёт свою в папку обхода sv_pure
            "game": "materials/vgui/pocket_watch_fg.vtf",
            # VMT кладём В ТУ ЖЕ папку, что и VTF (так требует игра, без дублей vgui)
            "vmt":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_fg.vmt",
            "ru": "Центральная вставка", "en": "Center insert",
        },
        {
            "name": "pocket_watch_bg",
            "vpk":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_bg.vtf",
            "game": "materials/vgui/pocket_watch_bg.vtf",
            "vmt":  "materials/vgui/replay/thumbnails/deadringer/pocket_watch_bg.vmt",
            "ru": "Фон циферблата", "en": "Watch background",
        },
    ],
}

# Оружие без BLU-команды
# У некоторых предметов модель использует ОДНУ текстуру для обеих команд
# (напр. часы шпиона). Для них не нужно создавать BLU-вариант - игнорируем
# blu_row из $texturegroup, иначе в мод попадёт лишняя _blue текстура
NO_BLU_WEAPON_KEYS: frozenset = frozenset({"c_pocket_watch", "v_hm_watch", "v_ttg_watch_spy"})

# Оружие, которому нужен зеркальный VMT по оригинальному пути
# Некоторые предметы отображаются в игре ДРУГОЙ моделью, чем та, что собирает
# инструмент, и ссылаются на текстуру по ОРИГИНАЛЬНОМУ пути материала, а не по
# пропатченному console\. Для них создаём зеркальный VMT по оригинальному
# $cdmaterials-пути - тогда «чужая» модель найдёт скин.
# Dead Ringer виден через РОДНОЙ viewmodel (v_watch_pocket_spy), который смотрит
# на материал по ОРИГИНАЛЬНОМУ пути. Зеркальный VMT по этому пути ссылается на
# console-VTF (текстура + все карты), поэтому папку console оставляем как есть
MIRROR_VMT_WEAPON_KEYS: frozenset = frozenset({"c_pocket_watch", "v_hm_watch", "v_ttg_watch_spy"})

# Оружие «только материалы» (без модели в моде)
# Эти предметы отображаются РОДНОЙ игровой моделью (напр. Dead Ringer виден
# через viewmodel v_watch_pocket_spy). Своя перекомпилированная модель в моде
# не нужна и вредна (игра подхватит «чужую»). Собираем только материалы (VTF/VMT
# по console-пути) + зеркальный VMT по оригинальному пути - родная модель найдёт
# скин и карты материала. Модель .mdl в мод НЕ кладём
MATERIAL_ONLY_WEAPON_KEYS: frozenset = frozenset({"c_pocket_watch", "v_hm_watch", "v_ttg_watch_spy"})

# 3D-превью: подмена модели и фильтр материалов
# Для некоторых предметов в 3D надо показывать ДРУГУЮ модель, чем собирает
# инструмент. Dead Ringer: собираем c_pocket_watch, но в игре от первого лица
# видно viewmodel v_watch_pocket_spy (руки + часы в одном меше). Показываем его,
# оставляя только меши часов (материалы по whitelist), руки скрываем
PREVIEW_MDL_OVERRIDE: dict[str, str] = {
    "c_pocket_watch": "models/weapons/v_models/v_watch_pocket_spy.mdl",
}
# Подстроки имён материалов, которые у модели ЕДИНСТВЕННО свои: превью
# оставляет только эти меши, сборка правит и пишет только эти материалы.
# Крякенптиц и Часы ярого поклонника в игре - вьюмодели с руками шпиона, а
# spy_hands_red/blue - общая текстура рук всего его оружия: мод их не трогает
MODEL_MATERIAL_WHITELIST: dict[str, tuple] = {
    "c_pocket_watch": ("watch",),   # c_pocket_watch / pocket_watch_fg / pocket_watch_bg
    "v_hm_watch": ("watch",),       # v_hm_watch (+ spy_hands_*)
    "v_ttg_watch_spy": ("watch",),  # ttg_watch (+ spy_hands_*)
}


def is_own_material(weapon_key: str, material: str) -> bool:
    """Свой ли материал модели (MODEL_MATERIAL_WHITELIST), без правила - все свои"""
    keep = MODEL_MATERIAL_WHITELIST.get(weapon_key)
    return not keep or any(s in (material or '').lower() for s in keep)

# Доп. статические файлы мода (скрипты/метаданные)
# Некоторым предметам нужны не-материальные файлы в моде: HUD-скрипты (.res),
# метаданные мода (info.vdf) и т.п. Кладутся в корень VPK по указанному пути
# ровно с заданным содержимым. {weapon_key: [{"path", "content"}]}
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

# Нестандартные пути VTF (дополнительные пути для поиска текстур)
# Используются как приоритетный список ПЕРЕД стандартными путями.
# Нужны когда имя/папка текстуры не совпадает с weapon_key

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
    # Текстуры тела персонажа (materials/models/player/…)
    "player_scout":    ["materials/models/player/scout/scout_red.vtf"],
    "player_soldier":  ["materials/models/player/soldier/soldier_red.vtf"],
    "player_pyro":     ["materials/models/player/pyro/pyro_red.vtf"],
    "player_demo":     ["materials/models/player/demo/demoman_red.vtf"],
    "player_heavy":    ["materials/models/player/hvyweapon/hvyweapon_red.vtf"],
    "player_engineer": ["materials/models/player/engineer/engineer_red.vtf"],
    "player_medic":    ["materials/models/player/medic/medic_red.vtf"],
    "player_sniper":   ["materials/models/player/sniper/sniper_red.vtf"],
    "player_spy":      ["materials/models/player/spy/spy_red.vtf"],
    # Текстуры рук (materials/models/player/…)
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
