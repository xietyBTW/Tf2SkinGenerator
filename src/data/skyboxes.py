"""
Данные для режима «Скайбокс» — замена неба карт TF2.

Скайбокс в Source — 6 материалов materials/skybox/<имя_неба><грань>.{vmt,vtf},
грани: up/dn/lf/rt/ft/bk (суффикс приклеивается к имени БЕЗ разделителя:
sky_tf2_04 + up → sky_tf2_04up.vmt). Каждая карта задаёт имя неба в worldspawn,
поэтому мод перекрывает материалы конкретного имени (или всех имён сразу).
"""

# Режим сборки (аналог значений SPECIAL_MODES, но НЕ в SPECIAL_MODES:
# у скайбокса своя ветка пайплайна, см. VPKService.build_with_progress).
SKYBOX_MODE = "skybox"

# Ключ пункта «Все карты» в списке небес (не имя материала).
SKY_ALL_MAPS_KEY = "__all_maps__"

# Порядок граней — канонический для всей фичи (нарезка/превью/сборка).
SKY_FACES = ("up", "dn", "lf", "rt", "ft", "bk")

# Четыре боковые грани. У стоковых небес TF2 это ОДНА текстура `side`: небо
# нарисовано цилиндром, а не кубом, и по кругу везде одно и то же.
SKY_SIDE_FACES = ("lf", "rt", "ft", "bk")


def stock_face_stems(sky_name: str, face: str):
    """Имена VTF стоковой грани, в порядке проверки.

    Единого правила у Valve нет: у большинства небес это `<имя><грань>`
    (`sky_upwardup`), у части — `<имя>_<грань>` (`sky_harvest_01_up`), а
    боковые грани у всех — общая `side`. VMT-ки граней (`<имя>ft.vmt`) искать
    текстуру не помогают: у стоковых небес они ссылаются на `skybox/cloudft`,
    которого в игре нет вовсе.
    """
    stems = [f"{sky_name}{face}", f"{sky_name}_{face}"]
    if face in SKY_SIDE_FACES:
        stems += [f"{sky_name}side", f"{sky_name}_side"]
    return stems


# Ключ карточки-панорамы в ленте слотов превью (не грань, в сборку не пишется).
SKY_PANO_KEY = "__pano__"

# Подписи граней для карточек превью.
SKY_FACE_LABELS = {
    "up": {"ru": "Верх",  "en": "Up"},
    "dn": {"ru": "Низ",   "en": "Down"},
    "lf": {"ru": "Лево",  "en": "Left"},
    "rt": {"ru": "Право", "en": "Right"},
    "ft": {"ru": "Перед", "en": "Front"},
    "bk": {"ru": "Зад",   "en": "Back"},
}

# Небо, которым превьюится пункт «Все карты» (нужно конкретное имя для
# извлечения стоковых граней из VPK игры).
SKY_PREVIEW_DEFAULT = "sky_tf2_04"

# Фолбэк-список стоковых небес TF2: используется без настроенной папки игры и
# как минимум при скане VPK (реальный список дополняется сканом
# materials/skybox/*up.vmt — Valve добавляет новые неба с обновлениями).
STOCK_SKY_NAMES = [
    "sky_alpinestorm_01",
    "sky_badlands_01",
    "sky_dustbowl_01",
    "sky_goldrush_01",
    "sky_granary_01",
    "sky_gravel_01",
    "sky_halloween",
    "sky_halloween_night2014_01",
    "sky_halloween_night_01",
    "sky_harvest_01",
    "sky_harvest_night_01",
    "sky_hydro_01",
    "sky_island_01",
    "sky_morningsnow_01",
    "sky_night_01",
    "sky_nightfall_01",
    "sky_rainbow_01",
    "sky_stormfront_01",
    "sky_tf2_04",
    "sky_trainyard_01",
    "sky_upward",
    "sky_well_01",
]
