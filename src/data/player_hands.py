"""
Данные о текстурах рук персонажей TF2.

Текстуры рук находятся в tf2_textures_dir.vpk по пути:
  materials/models/player/{folder}/{texture_name}.vtf

VMT файлы не нужны — игра использует собственные из базового VPK.
Мод содержит только VTF файлы.
"""

from typing import Dict, List, Tuple

# Структура записи:
# "mode_key": {
#     "ru": <название на русском>,
#     "en": <название на английском>,
#     "textures": [("folder", "vtf_name"), ...]
#        - первая текстура использует основное изображение пользователя
#        - дополнительные текстуры запрашиваются через extra_texture_callback
# }

HAND_MODES: Dict[str, dict] = {
    "scout_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_scout_arms",   # MDL ключ для 3D Preview
        "textures": [
            ("scout", "scout_hands"),
        ],
    },
    "soldier_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_soldier_arms",
        "textures": [
            ("soldier", "soldier_hands"),
        ],
    },
    "pyro_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_pyro_arms",
        "textures": [
            ("pyro", "pyro_hands_red"),
        ],
    },
    "demoman_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_demo_arms",
        "textures": [
            ("demo", "demoman_hands"),
        ],
    },
    "heavy_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_heavy_arms",
        "textures": [
            ("hvyweapon", "hvyweapon_hands"),
        ],
    },
    "engineer_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_engineer_arms",
        # handl = левая рука, handr_red = правая (красная)
        "textures": [
            ("engineer", "engineer_handl"),
            ("engineer", "engineer_handr_red"),
        ],
    },
    "engineer_mech_hands": {
        "ru": "Рука робота (МвМ)",
        "en": "Robot Hand (MvM)",
        "arm_model": "c_engineer_gunslinger",   # MDL робо-руки (Gunslinger)
        # Механическая рука инженера для режима MvM
        "textures": [
            ("engineer", "engineer_mech_hand"),
            ("engineer", "engineer_mech_hand_blue"),
        ],
    },
    "medic_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_medic_arms",
        "textures": [
            ("medic", "medic_hands_red"),
            ("medic", "medic_hands_blue"),
        ],
    },
    "sniper_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_sniper_arms",
        "textures": [
            ("sniper", "sniper_handl_red"),
        ],
    },
    "spy_hands": {
        "ru": "Руки",
        "en": "Hands",
        "arm_model": "c_spy_arms",
        "textures": [
            ("spy", "spy_hands_red"),
            ("spy", "spy_hands_blue"),
        ],
    },
}

# Быстрый lookup для проверки: is_hand_mode = mode in HAND_MODE_KEYS
HAND_MODE_KEYS: frozenset = frozenset(HAND_MODES.keys())


def get_hand_mode_name(mode_key: str, language: str = "en") -> str:
    """Возвращает локализованное название режима рук."""
    mode = HAND_MODES.get(mode_key)
    if not mode:
        return mode_key
    return mode.get(language, mode.get("en", mode_key))


def get_hand_textures(mode_key: str) -> List[Tuple[str, str]]:
    """Возвращает список (folder, vtf_name) текстур для режима."""
    mode = HAND_MODES.get(mode_key)
    if not mode:
        return []
    return mode.get("textures", [])
