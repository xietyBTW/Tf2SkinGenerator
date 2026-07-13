"""
Данные о моделях пикапов TF2: аптечки и патроны (models/items/).

Это мир-объекты (без команды RED/BLU и без skinfamilies), но мод строится
через тот же pipeline, что у оружия/снарядов:
  MDL из VPK → Crowbar декомпилирует → QC отдаёт текстуры.

mode пикапа формируется как f"pickup_{key}" — _resolve_3d_weapon_key/сборка
трактуют его как обычное оружие (weapon_key = key), путь берётся из
PICKUP_MDL_PATHS (подмешан в WEAPON_MDL_PATHS).

Пути выверены по tf2_misc_dir.vpk (папка models/items/).
"""

from typing import Dict

# key → {ru, en, mdl_path}. key совпадает с weapon_key (basename без расширения).
PICKUPS: Dict[str, dict] = {
    "medkit_small": {
        "ru": "Аптечка (малая)", "en": "Health Kit (Small)",
        "mdl_path": "models/items/medkit_small.mdl",
    },
    "medkit_medium": {
        "ru": "Аптечка (средняя)", "en": "Health Kit (Medium)",
        "mdl_path": "models/items/medkit_medium.mdl",
    },
    "medkit_large": {
        "ru": "Аптечка (большая)", "en": "Health Kit (Large)",
        "mdl_path": "models/items/medkit_large.mdl",
    },
    "halloween_medkit_small": {
        "ru": "Аптечка Хэллоуин (малая)", "en": "Halloween Health Kit (Small)",
        "mdl_path": "models/props_halloween/halloween_medkit_small.mdl",
    },
    "halloween_medkit_medium": {
        "ru": "Аптечка Хэллоуин (средняя)", "en": "Halloween Health Kit (Medium)",
        "mdl_path": "models/props_halloween/halloween_medkit_medium.mdl",
    },
    "halloween_medkit_large": {
        "ru": "Аптечка Хэллоуин (большая)", "en": "Halloween Health Kit (Large)",
        "mdl_path": "models/props_halloween/halloween_medkit_large.mdl",
    },
    "medkit_small_bday": {
        "ru": "Аптечка День рождения (малая)", "en": "Birthday Health Kit (Small)",
        "mdl_path": "models/items/medkit_small_bday.mdl",
    },
    "medkit_medium_bday": {
        "ru": "Аптечка День рождения (средняя)", "en": "Birthday Health Kit (Medium)",
        "mdl_path": "models/items/medkit_medium_bday.mdl",
    },
    "medkit_large_bday": {
        "ru": "Аптечка День рождения (большая)", "en": "Birthday Health Kit (Large)",
        "mdl_path": "models/items/medkit_large_bday.mdl",
    },
    "ammopack_small": {
        "ru": "Патроны (малые)", "en": "Ammo Pack (Small)",
        "mdl_path": "models/items/ammopack_small.mdl",
    },
    "ammopack_medium": {
        "ru": "Патроны (средние)", "en": "Ammo Pack (Medium)",
        "mdl_path": "models/items/ammopack_medium.mdl",
    },
    "ammopack_large": {
        "ru": "Патроны (большие)", "en": "Ammo Pack (Large)",
        "mdl_path": "models/items/ammopack_large.mdl",
    },
    "ammopack_small_bday": {
        "ru": "Патроны День рождения (малые)", "en": "Birthday Ammo Pack (Small)",
        "mdl_path": "models/items/ammopack_small_bday.mdl",
    },
    "ammopack_medium_bday": {
        "ru": "Патроны День рождения (средние)", "en": "Birthday Ammo Pack (Medium)",
        "mdl_path": "models/items/ammopack_medium_bday.mdl",
    },
    "ammopack_large_bday": {
        "ru": "Патроны День рождения (большие)", "en": "Birthday Ammo Pack (Large)",
        "mdl_path": "models/items/ammopack_large_bday.mdl",
    },
    "currencypack_small": {
        "ru": "Деньги MvM (малые)", "en": "MvM Money (Small)",
        "mdl_path": "models/items/currencypack_small.mdl",
    },
    "currencypack_medium": {
        "ru": "Деньги MvM (средние)", "en": "MvM Money (Medium)",
        "mdl_path": "models/items/currencypack_medium.mdl",
    },
    "currencypack_large": {
        "ru": "Деньги MvM (большие)", "en": "MvM Money (Large)",
        "mdl_path": "models/items/currencypack_large.mdl",
    },
}

#: Префикс mode для пикапов (mode = f"{PICKUP_MODE_PREFIX}{key}").
PICKUP_MODE_PREFIX = "pickup_"

#: key → путь MDL (для подмешивания в WEAPON_MDL_PATHS).
PICKUP_MDL_PATHS: Dict[str, str] = {
    key: data["mdl_path"] for key, data in PICKUPS.items()
}
