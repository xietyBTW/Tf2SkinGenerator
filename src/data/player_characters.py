"""
Данные о моделях персонажей TF2.

Мод строится через полный pipeline (как шапки и оружия):
  MDL извлекается из VPK → Crowbar декомпилирует → QC сам отдаёт список текстур.

Хардкодится только mdl_path — реальный путь к MDL в tf2_misc_dir.vpk.
Все текстурные слоты обнаруживаются динамически из QC (skinfamilies).
"""

from typing import Dict, List, Tuple

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


def get_player_body_extra_label(mode_key: str, vtf_name: str, language: str = "en") -> str:
    """
    Возвращает читаемое название текстурного слота персонажа.
    Теперь текстуры обнаруживаются из QC динамически, поэтому
    просто возвращаем vtf_name как есть.
    """
    return vtf_name


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
