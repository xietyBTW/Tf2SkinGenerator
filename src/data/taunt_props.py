"""
Данные о моделях реквизита насмешек TF2 (taunt props — пропсы, которые
появляются во время насмешек: танк, йети, скутер, гитара и т.п.).

Мод строится через тот же pipeline, что у оружия/снарядов/пикапов:
  MDL из VPK → Crowbar декомпилирует → QC отдаёт текстуры/skinfamilies.

mode формируется как f"taunt_{key}" → _resolve_3d_weapon_key/сборка трактуют
его как обычное оружие (weapon_key = key), путь берётся из TAUNT_PROP_MDL_PATHS
(подмешан в WEAPON_MDL_PATHS).

Пути выверены по tf2_misc_dir.vpk (папки .../items/taunts/). Только одиночные
пропсы; по-классовые анимационные модели насмешек сюда не входят.
"""

from typing import Dict

# key → {ru, en, mdl_path}. key совпадает с weapon_key (basename без расширения).
TAUNT_PROPS: Dict[str, dict] = {
    "tank": {
        "ru": "Танк", "en": "Tank",
        "mdl_path": "models/player/items/taunts/tank/tank.mdl",
    },
    "yeti": {
        "ru": "Йети", "en": "Yeti",
        "mdl_path": "models/player/items/taunts/yeti/yeti.mdl",
    },
    "yeti_standee": {
        "ru": "Картонный йети", "en": "Yeti Standee",
        "mdl_path": "models/player/items/taunts/yeti_standee/yeti_standee.mdl",
    },
    "scooter": {
        "ru": "Скутер", "en": "Scooter",
        "mdl_path": "models/player/items/taunts/scooter/scooter.mdl",
    },
    "bumpercar": {
        "ru": "Машинка автодрома", "en": "Bumper Car",
        "mdl_path": "models/player/items/taunts/bumpercar/parts/bumpercar.mdl",
    },
    "brutal_guitar": {
        "ru": "Гитара", "en": "Guitar",
        "mdl_path": "models/workshop_partner/player/items/taunts/brutal_guitar/brutal_guitar.mdl",
    },
    "beer_crate": {
        "ru": "Ящик пива", "en": "Beer Crate",
        "mdl_path": "models/player/items/taunts/beer_crate/beer_crate.mdl",
    },
    "chicken_bucket": {
        "ru": "Ведро с курицей", "en": "Chicken Bucket",
        "mdl_path": "models/player/items/taunts/chicken_bucket/chicken_bucket.mdl",
    },
    "cash_wad": {
        "ru": "Пачка денег", "en": "Cash Wad",
        "mdl_path": "models/player/items/taunts/cash_wad.mdl",
    },
    "matchbox": {
        "ru": "Спичечный коробок", "en": "Matchbox",
        "mdl_path": "models/player/items/taunts/matchbox/matchbox.mdl",
    },
    "demo_nuke_bottle": {
        "ru": "Ядерная бутылка", "en": "Nuke Bottle",
        "mdl_path": "models/player/items/taunts/demo_nuke_bottle/demo_nuke_bottle.mdl",
    },
    "dizzy_bottle1": {
        "ru": "Хмельная бутылка", "en": "Dizzy Bottle",
        "mdl_path": "models/player/items/taunts/dizzy_bottle1/dizzy_bottle1.mdl",
    },
    "victory_mug": {
        "ru": "Кружка победы", "en": "Victory Mug",
        "mdl_path": "models/player/items/taunts/victory_mug.mdl",
    },
    "wupass_mug": {
        "ru": "Кружка «Открой банку»", "en": "Can of Wupass Mug",
        "mdl_path": "models/player/items/taunts/wupass_mug/wupass_mug.mdl",
    },
    "medic_xray_taunt": {
        "ru": "Рентген медика", "en": "Medic X-Ray",
        "mdl_path": "models/player/items/taunts/medic_xray_taunt.mdl",
    },
    "engys_new_chair_articlulated": {
        "ru": "Кресло инженера", "en": "Engineer's Chair",
        "mdl_path": "models/player/items/taunts/engys_new_chair/engys_new_chair_articlulated.mdl",
    },
    "pyro_poolparty": {
        "ru": "Бассейн Пиро", "en": "Pyro Pool Party",
        "mdl_path": "models/workshop/player/items/taunts/pyro_poolparty/pyro_poolparty.mdl",
    },
    "balloon_animal_pyro": {
        "ru": "Шарик-зверушка", "en": "Balloon Animal",
        "mdl_path": "models/player/items/taunts/balloon_animal_pyro/balloon_animal_pyro.mdl",
    },
    # Эти насмешки имеют по модели на класс, НО все классы ссылаются на одни и те
    # же материалы (taunt_<name>) — пропс общий, отличается лишь скелет привязки.
    # Поэтому селектор класса не нужен: берём одну модель-представителя (scout),
    # правка даёт единый мод для всех классов.
    "taunt_burstchester_scout": {
        "ru": "Burstchester", "en": "Burstchester",
        "mdl_path": "models/workshop/player/items/all_class/taunt_burstchester/taunt_burstchester_scout.mdl",
    },
    "taunt_cheers_scout": {
        "ru": "Cheers", "en": "Cheers",
        "mdl_path": "models/workshop/player/items/all_class/taunt_cheers/taunt_cheers_scout.mdl",
    },
    "taunt_killer_joke_scout": {
        "ru": "Killer Joke", "en": "Killer Joke",
        "mdl_path": "models/workshop/player/items/all_class/taunt_killer_joke/taunt_killer_joke_scout.mdl",
    },
    "taunt_the_final_score_scout": {
        "ru": "The Final Score", "en": "The Final Score",
        "mdl_path": "models/workshop/player/items/all_class/taunt_the_final_score/taunt_the_final_score_scout.mdl",
    },
}

#: Префикс mode для реквизита насмешек (mode = f"{TAUNT_PROP_MODE_PREFIX}{key}").
TAUNT_PROP_MODE_PREFIX = "taunt_"

#: key → путь MDL (для подмешивания в WEAPON_MDL_PATHS).
TAUNT_PROP_MDL_PATHS: Dict[str, str] = {
    key: data["mdl_path"] for key, data in TAUNT_PROPS.items()
}


def get_taunt_prop_name(key: str, language: str = "ru") -> str:
    data = TAUNT_PROPS.get(key, {})
    return data.get(language, data.get("ru", key))
