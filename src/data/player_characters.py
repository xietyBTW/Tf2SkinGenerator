"""
Данные о моделях персонажей TF2.

Мод строится через полный pipeline (как шапки и оружия):
  MDL извлекается из VPK → Crowbar декомпилирует → QC сам отдаёт список текстур.

Хардкодится только mdl_path — реальный путь к MDL в tf2_misc_dir.vpk.
Все текстурные слоты обнаруживаются динамически из QC (skinfamilies).
"""

from typing import Dict, List, Tuple

#: Портрет класса из экрана выбора — картинка, по которой класс узнают с
#: одного взгляда. Формат ключа общий с `api.icon_png`: `mat/…` означает
#: игровой материал, а не предмет рюкзака.
#:
#: Один на всех, кто показывает классы: страница звуков и каталог персонажей.
#: Классовая медаль (тоже вариант) выглядит одинаково у всех девяти.
CLASS_ICON: str = 'mat/vgui/class_portraits/{}'

PLAYER_CHARACTERS: Dict[str, dict] = {
    "scout_body": {
        "en": "Scout",
        "ru": "Разведчик",
        "mdl_path": "models/player/scout.mdl",
        "folder": "scout",          # папка в materials/models/player/
    },
    "soldier_body": {
        "en": "Soldier",
        "ru": "Солдат",
        "mdl_path": "models/player/soldier.mdl",
        "folder": "soldier",
    },
    "pyro_body": {
        "en": "Pyro",
        "ru": "Поджигатель",
        "mdl_path": "models/player/pyro.mdl",
        "folder": "pyro",
    },
    "demoman_body": {
        "en": "Demoman",
        "ru": "Подрывник",
        "mdl_path": "models/player/demo.mdl",
        "folder": "demo",
    },
    "heavy_body": {
        "en": "Heavy",
        "ru": "Пулемётчик",
        "mdl_path": "models/player/heavy.mdl",
        "folder": "hvyweapon",      # Valve назвала папку hvyweapon, не heavy
    },
    "engineer_body": {
        "en": "Engineer",
        "ru": "Инженер",
        "mdl_path": "models/player/engineer.mdl",
        "folder": "engineer",
    },
    "medic_body": {
        "en": "Medic",
        "ru": "Медик",
        "mdl_path": "models/player/medic.mdl",
        "folder": "medic",
    },
    "sniper_body": {
        "en": "Sniper",
        "ru": "Снайпер",
        "mdl_path": "models/player/sniper.mdl",
        "folder": "sniper",
    },
    "spy_body": {
        "en": "Spy",
        "ru": "Шпион",
        "mdl_path": "models/player/spy.mdl",
        "folder": "spy",
    },
}

# Быстрый lookup: is_player_body_mode = mode in PLAYER_BODY_MODE_KEYS
PLAYER_BODY_MODE_KEYS: frozenset = frozenset(PLAYER_CHARACTERS.keys())


# ──────────────────────────────────────────────────────────────────────────────
# Маски маскировки шпиона
# ──────────────────────────────────────────────────────────────────────────────

#: Ключ режима маскировки шпиона (формируется как «spy_masks»)
SPY_MASK_MODE_KEY: str = "spy_masks"

#: MDL шпиона (используется и для скина и для масок)
SPY_MDL_PATH: str = "models/player/spy.mdl"

#: Маски маскировки: (class_key, vtf_name, name_en, name_ru, btn_label)
#: vtf_name — имя файла текстуры в materials/models/player/spy/
#: btn_label — короткая подпись на кнопке переключателя (2-3 символа)
SPY_DISGUISE_MASKS: List[Tuple[str, str, str, str, str]] = [
    ("scout",   "mask_scout",   "Scout",    "Разведчик",  "Sc"),
    ("soldier", "mask_soldier", "Soldier",  "Солдат",     "So"),
    ("pyro",    "mask_pyro",    "Pyro",     "Поджигатель","Py"),
    ("demo",    "mask_demo",    "Demo",     "Подрывник",  "De"),
    ("heavy",   "mask_heavy",   "Heavy",    "Пулемётчик", "Hv"),
    ("engi",    "mask_engi",    "Engi",     "Инженер",    "En"),
    ("medic",   "mask_medic",   "Medic",    "Медик",      "Me"),
    ("sniper",  "mask_sniper",  "Sniper",   "Снайпер",    "Sn"),
    ("spy",     "mask_spy",     "Spy",      "Шпион",      "Sp"),
]

#: Только имена VTF-файлов масок (для быстрой проверки)
SPY_MASK_VTF_NAMES: List[str] = [m[1] for m in SPY_DISGUISE_MASKS]

#: Обложка карточки масок: значок маскировки — тот, что игра рисует над
#: переодетым шпионом. Маска на верёвочке, и объяснять её не надо.
#:
#: Своей маской из девяти карточку не подписать: `mask_spy` — это лицо
#: шпиона, и рядом с его же портретом карточка выглядела бы копией «Скина»,
#: а любая другая обещала бы один класс из девяти.
DISGUISE_ICON: str = 'mat/effects/disguise_icon'
