"""
Данные о моделях снарядов TF2 (w_models — то, что летит: ракеты, гранаты,
липучки, стрелы и т.п.).

Мод строится через тот же полный pipeline, что у оружия:
  MDL из VPK → Crowbar декомпилирует → QC отдаёт текстуры/skinfamilies →
  команда RED/BLU и варианты работают автоматически.

mode снаряда формируется как f"projectile_{key}" — благодаря этому
_resolve_3d_weapon_key/сборка трактуют его как обычное оружие
(weapon_key = key), а путь к MDL берётся из PROJECTILE_MDL_PATHS.

Пути выверены по tf2_misc_dir.vpk (папка models/weapons/w_models/).
"""

from typing import Dict

# key → {ru, en, mdl_path}. key совпадает с weapon_key (basename без расширения),
# кроме случаев, когда модель лежит в подпапке (тогда путь задан явно).
PROJECTILES: Dict[str, dict] = {
    "w_rocket": {
        "ru": "Ракета", "en": "Rocket",
        "mdl_path": "models/weapons/w_models/w_rocket.mdl",
    },
    "w_rocket_airstrike": {
        "ru": "Ракета (Авиаудар)", "en": "Rocket (Air Strike)",
        "mdl_path": "models/weapons/w_models/w_rocket_airstrike/w_rocket_airstrike.mdl",
    },
    "w_grenade_grenadelauncher": {
        "ru": "Граната", "en": "Grenade",
        "mdl_path": "models/weapons/w_models/w_grenade_grenadelauncher.mdl",
    },
    "w_grenade_pipebomb": {
        "ru": "Пайп-бомба", "en": "Pipebomb",
        "mdl_path": "models/weapons/w_models/w_grenade_pipebomb.mdl",
    },
    "w_stickybomb": {
        "ru": "Липучка", "en": "Stickybomb",
        "mdl_path": "models/weapons/w_models/w_stickybomb.mdl",
    },
    "w_stickybomb_defender": {
        "ru": "Липучка (Защитник)", "en": "Stickybomb (Defender)",
        "mdl_path": "models/weapons/w_models/w_stickybomb_defender.mdl",
    },
    "w_arrow": {
        "ru": "Стрела", "en": "Arrow",
        "mdl_path": "models/weapons/w_models/w_arrow.mdl",
    },
    "w_arrow_xmas": {
        "ru": "Стрела (праздничная)", "en": "Arrow (Festive)",
        "mdl_path": "models/weapons/w_models/w_arrow_xmas.mdl",
    },
    "w_cannonball": {
        "ru": "Ядро", "en": "Cannonball",
        "mdl_path": "models/weapons/w_models/w_cannonball.mdl",
    },
    "w_baseball": {
        "ru": "Бейсбольный мяч", "en": "Baseball",
        "mdl_path": "models/weapons/w_models/w_baseball.mdl",
    },
    "w_flaregun_shell": {
        "ru": "Сигнальный заряд", "en": "Flare",
        "mdl_path": "models/weapons/w_models/w_flaregun_shell.mdl",
    },
    "w_syringe": {
        "ru": "Шприц", "en": "Syringe",
        "mdl_path": "models/weapons/w_models/w_syringe.mdl",
    },
    "w_drg_ball": {
        "ru": "Энергошар", "en": "Energy Ball",
        "mdl_path": "models/weapons/w_models/w_drg_ball.mdl",
    },
    "w_syringe_proj": {
        "ru": "Шприц (снаряд)", "en": "Syringe (projectile)",
        "mdl_path": "models/weapons/w_models/w_syringe_proj.mdl",
    },
    "w_breadmonster": {
        "ru": "Хлебомонстр", "en": "Bread Monster",
        "mdl_path": "models/weapons/w_models/w_breadmonster/w_breadmonster.mdl",
    },
    "w_repair_claw": {
        "ru": "Коготь Спасателя", "en": "Repair Claw",
        "mdl_path": "models/weapons/w_models/w_repair_claw.mdl",
    },
    "w_stickybomb2": {
        "ru": "Липучка (вариант 2)", "en": "Stickybomb (variant 2)",
        "mdl_path": "models/weapons/w_models/w_stickybomb2.mdl",
    },
    "w_stickybomb3": {
        "ru": "Липучка (вариант 3)", "en": "Stickybomb (variant 3)",
        "mdl_path": "models/weapons/w_models/w_stickybomb3.mdl",
    },
    "w_stickybomb_d": {
        "ru": "Липучка (вариант D)", "en": "Stickybomb (variant D)",
        "mdl_path": "models/weapons/w_models/w_stickybomb_d.mdl",
    },
    # Своя летящая модель через атрибут "custom projectile model" в items_game.
    "w_quadball_grenade": {
        "ru": "Граната Железного бомбардира", "en": "Iron Bomber Grenade",
        "mdl_path": "models/workshop/weapons/c_models/c_quadball/w_quadball_grenade.mdl",
    },
    "w_kingmaker_stickybomb": {
        "ru": "Липучка Быстромёта", "en": "Quickiebomb",
        "mdl_path": "models/workshop/weapons/c_models/c_kingmaker_sticky/w_kingmaker_stickybomb.mdl",
    },
}

#: Префикс mode для снарядов (mode = f"{PROJECTILE_MODE_PREFIX}{key}").
PROJECTILE_MODE_PREFIX = "projectile_"

#: key → путь MDL (для подмешивания в WEAPON_MDL_PATHS).
PROJECTILE_MDL_PATHS: Dict[str, str] = {
    key: data["mdl_path"] for key, data in PROJECTILES.items()
}
