"""
Данные о текстурах тел персонажей TF2.

Текстуры тел находятся в tf2_textures_dir.vpk по пути:
  materials/models/player/{folder}/{texture_name}.vtf

Мод заменяет VTF файлы напрямую — MDL не нужен.
Основная текстура (index 0) берётся из изображения пользователя.
Дополнительные текстуры (index 1+) запрашиваются через extra_texture_callback.
"""

from typing import Dict, List, Tuple

PLAYER_CHARACTERS: Dict[str, dict] = {
    # Голова Scout — scout_head.vtf (единая для RED и BLU, без командных суффиксов)
    "scout_body": {
        "en": "Scout",
        "ru": "Разведчик",
        "folder": "scout",
        "mdl_key": "player_scout",
        "textures": [
            ("scout", "scout_red"),
            ("scout", "scout_blue"),
            ("scout", "scout_head"),
        ],
        "extra_labels": {
            "scout_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
            "scout_head": {"ru": "Голова",     "en": "Head"},
        },
    },
    # Голова Soldier — soldier_head.vtf (единая)
    "soldier_body": {
        "en": "Soldier",
        "ru": "Солдат",
        "folder": "soldier",
        "mdl_key": "player_soldier",
        "textures": [
            ("soldier", "soldier_red"),
            ("soldier", "soldier_blue"),
            ("soldier", "soldier_head"),
        ],
        "extra_labels": {
            "soldier_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
            "soldier_head": {"ru": "Голова",     "en": "Head"},
        },
    },
    # Pyro — голова закрыта маской, отдельной head-текстуры нет
    "pyro_body": {
        "en": "Pyro",
        "ru": "Поджигатель",
        "folder": "pyro",
        "mdl_key": "player_pyro",
        "textures": [
            ("pyro", "pyro_red"),
            ("pyro", "pyro_blue"),
        ],
        "extra_labels": {
            "pyro_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
        },
    },
    # Demoman — папка "demo", но файлы называются demoman_*.vtf; голова — demoman_head.vtf
    "demoman_body": {
        "en": "Demoman",
        "ru": "Подрывник",
        "folder": "demo",
        "mdl_key": "player_demo",
        "textures": [
            ("demo", "demoman_red"),
            ("demo", "demoman_blue"),
            ("demo", "demoman_head"),
        ],
        "extra_labels": {
            "demoman_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
            "demoman_head": {"ru": "Голова",     "en": "Head"},
        },
    },
    # Heavy — папка "hvyweapon", тело hvyweapon_*.vtf, голова heavy_head.vtf
    "heavy_body": {
        "en": "Heavy",
        "ru": "Пулемётчик",
        "folder": "hvyweapon",
        "mdl_key": "player_heavy",
        "textures": [
            ("hvyweapon", "hvyweapon_red"),
            ("hvyweapon", "hvyweapon_blue"),
            ("hvyweapon", "heavy_head"),
        ],
        "extra_labels": {
            "hvyweapon_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
            "heavy_head":     {"ru": "Голова",     "en": "Head"},
        },
    },
    # Голова Engineer — engineer_head.vtf (единая)
    "engineer_body": {
        "en": "Engineer",
        "ru": "Инженер",
        "folder": "engineer",
        "mdl_key": "player_engineer",
        "textures": [
            ("engineer", "engineer_red"),
            ("engineer", "engineer_blue"),
            ("engineer", "engineer_head"),
        ],
        "extra_labels": {
            "engineer_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
            "engineer_head": {"ru": "Голова",     "en": "Head"},
        },
    },
    # Голова Medic — medic_head.vtf (единая)
    "medic_body": {
        "en": "Medic",
        "ru": "Медик",
        "folder": "medic",
        "mdl_key": "player_medic",
        "textures": [
            ("medic", "medic_red"),
            ("medic", "medic_blue"),
            ("medic", "medic_head"),
        ],
        "extra_labels": {
            "medic_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
            "medic_head": {"ru": "Голова",     "en": "Head"},
        },
    },
    # Голова Sniper — sniper_head.vtf (единая)
    "sniper_body": {
        "en": "Sniper",
        "ru": "Снайпер",
        "folder": "sniper",
        "mdl_key": "player_sniper",
        "textures": [
            ("sniper", "sniper_red"),
            ("sniper", "sniper_blue"),
            ("sniper", "sniper_head"),
        ],
        "extra_labels": {
            "sniper_blue": {"ru": "Тело (BLU)", "en": "Body (BLU)"},
            "sniper_head": {"ru": "Голова",     "en": "Head"},
        },
    },
    # Spy — ЕДИНСТВЕННЫЙ класс с командными head-текстурами: spy_head_red.vtf / spy_head_blue.vtf
    "spy_body": {
        "en": "Spy",
        "ru": "Шпион",
        "folder": "spy",
        "mdl_key": "player_spy",
        "textures": [
            ("spy", "spy_red"),
            ("spy", "spy_head_red"),
            ("spy", "spy_blue"),
            ("spy", "spy_head_blue"),
        ],
        "extra_labels": {
            "spy_head_red":  {"ru": "Голова (RED)", "en": "Head (RED)"},
            "spy_blue":      {"ru": "Тело (BLU)",   "en": "Body (BLU)"},
            "spy_head_blue": {"ru": "Голова (BLU)", "en": "Head (BLU)"},
        },
    },
}

# Быстрый lookup: is_player_body_mode = mode in PLAYER_BODY_MODE_KEYS
PLAYER_BODY_MODE_KEYS: frozenset = frozenset(PLAYER_CHARACTERS.keys())


def get_player_body_textures(mode_key: str) -> List[Tuple[str, str]]:
    """Возвращает список (folder, vtf_name) текстур для режима."""
    char = PLAYER_CHARACTERS.get(mode_key)
    if not char:
        return []
    return char.get("textures", [])


def get_player_body_extra_textures(mode_key: str) -> List[Tuple[str, str]]:
    """Возвращает только дополнительные текстуры (index 1+)."""
    return get_player_body_textures(mode_key)[1:]


def get_player_body_extra_label(mode_key: str, vtf_name: str, language: str = "en") -> str:
    """Возвращает человекочитаемое название дополнительной текстуры."""
    char = PLAYER_CHARACTERS.get(mode_key, {})
    labels = char.get("extra_labels", {})
    entry = labels.get(vtf_name, {})
    return entry.get(language) or entry.get("en") or vtf_name
