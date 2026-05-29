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


# Маппинг mode_key → (player_key для WEAPON_TEXTURE_PATHS)
_BODY_MODE_TO_PLAYER_KEY: Dict[str, str] = {
    "scout_body":    "player_scout",
    "soldier_body":  "player_soldier",
    "pyro_body":     "player_pyro",
    "demoman_body":  "player_demo",
    "heavy_body":    "player_heavy",
    "engineer_body": "player_engineer",
    "medic_body":    "player_medic",
    "sniper_body":   "player_sniper",
    "spy_body":      "player_spy",
}


def get_player_body_textures(mode_key: str) -> List[Tuple[str, str]]:
    """
    Возвращает список (folder, vtf_name) основных текстур тела персонажа.

    Используется в PlayerTextureBuildService как texture_getter.
    Путь к VTF: materials/models/player/{folder}/{vtf_name}.vtf

    Пример:
        get_player_body_textures("spy_body")
        → [("spy", "spy_red")]
    """
    from src.data.weapons import WEAPON_TEXTURE_PATHS

    player_key = _BODY_MODE_TO_PLAYER_KEY.get(mode_key)
    if not player_key:
        return []

    vtf_paths = WEAPON_TEXTURE_PATHS.get(player_key, [])
    result: List[Tuple[str, str]] = []
    for vtf_path in vtf_paths:
        # Формат: "materials/models/player/{folder}/{vtf_name}.vtf"
        # Нам нужны folder и vtf_name
        parts = vtf_path.replace("\\", "/").split("/")
        if len(parts) >= 2:
            vtf_name = parts[-1].replace(".vtf", "")
            folder = parts[-2]
            result.append((folder, vtf_name))

    return result


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
