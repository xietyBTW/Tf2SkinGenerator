"""
Какие SMD декомпилированной модели показывать в 3D-превью

Вынесено из Preview3DWorker: чистые функции над папкой декомпиляции и
разобранным QC (QcModel или любой объект с `qc_path`), без потока и сигналов
"""

import glob
import os
import re
from typing import Optional

from src.data.item_kinds import kind_of
from src.data.weapons import WEAPON_MDL_PATHS
from src.services import qc_skin_parser, smd_service
from src.services.smd_service import NON_REFERENCE_SMD_KEYWORDS, triangle_count
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Куски тела персонажа, которые не бывают самим телом (medipack.smd и т.п.)
_BODYGROUP_WORDS = ("pack", "backpack", "helmet", "hat", "glasses",
                    "mask", "coat", "vest", "arm", "hand")


# Путь MDL в VPK

def mdl_rel_path(mode: str, weapon_key: str) -> str:
    """Путь MDL предмета внутри VPK (подсказка для mdl_candidates)"""
    from src.data.weapon_quirks import PREVIEW_MDL_OVERRIDE
    kind = kind_of(mode)
    _override = PREVIEW_MDL_OVERRIDE.get(weapon_key)
    # У шапок, персонажей и масок weapon_key - это уже полный путь MDL
    if kind.is_hat or kind.is_character or kind.is_spy_mask:
        return weapon_key
    if _override:
        # Превью-подмена модели (напр. Dead Ringer -> viewmodel v_watch_pocket_spy)
        return _override
    return WEAPON_MDL_PATHS.get(
        weapon_key,
        f"models/weapons/c_models/{weapon_key}/{weapon_key}.mdl",
    )


def mdl_candidates(mode: str, weapon_key: str, misc_vpk_path: str,
                   mdl_rel_hint: str) -> list:
    """Пути MDL внутри VPK в порядке приоритета

    Шапка лежит не там, где записано в предмете (workshop/, суффикс класса),
    поэтому её путь раскрывается в список кандидатов. У персонажей, масок и
    превью-подмен путь известен точно
    """
    from src.data.weapon_quirks import PREVIEW_MDL_OVERRIDE
    kind = kind_of(mode)
    if kind.is_hat:
        from src.services.tf2_paths import build_hat_mdl_candidates
        return build_hat_mdl_candidates(mdl_rel_hint)
    if (kind.is_character or kind.is_spy_mask
            or weapon_key in PREVIEW_MDL_OVERRIDE):
        return [mdl_rel_hint]

    from src.data.weapon_model_index import tf2_root_from_misc_vpk
    from src.services.extract_model_service import ExtractModelService
    return ExtractModelService._build_paths_to_try(
        mode, weapon_key, tf2_root_from_misc_vpk(misc_vpk_path)
    )


# Основной меш

def _skip(path: str) -> bool:
    return any(kw in os.path.basename(path).lower() for kw in NON_REFERENCE_SMD_KEYWORDS)


def find_reference_smd(directory: str, mode: str, weapon_key: str,
                       load_model=qc_skin_parser.load_model) -> Optional[str]:
    """Находит reference SMD (исключая physics/anim) в директории

    ``load_model`` - разбор QC папки (у воркера - с кэшем на прогон): у
    персонажей тело называет QC
    """
    # Режим масок шпиона: загружаем spy_mask.smd (bodygroup)
    if kind_of(mode).is_spy_mask:
        mask = _spy_mask_smd(directory)
        if mask:
            return mask

    # Персонажи TF2: проверяем ДО *_reference.smd. У них bodygroup'ы (рюкзак
    # медика medipack_reference.smd, шапка и т.п.) тоже имеют _reference в
    # имени и алфавитно могут идти раньше основного тела
    from src.data.player_characters import PLAYER_BODY_MODE_KEYS
    if mode in PLAYER_BODY_MODE_KEYS:
        body = _character_smd(directory, weapon_key, load_model)
        if body:
            return body

    return smd_service.find_reference_smd(directory, weapon_key)


def _spy_mask_smd(directory: str) -> Optional[str]:
    mask_smd = os.path.join(directory, "spy_mask.smd")
    if os.path.exists(mask_smd):
        logger.debug("[3D] spy_mask.smd найден")
        return mask_smd
    # Fallback: ищем любой *mask*.smd
    mask_smds = [p for p in glob.glob(os.path.join(directory, "*mask*.smd"))
                 if not _skip(p) and "lod" not in os.path.basename(p).lower()]
    return mask_smds[0] if mask_smds else None


def _character_smd(directory: str, weapon_key: str, load_model) -> Optional[str]:
    """Тело персонажа: по QC, затем по имени класса

    weapon_key персонажа - полный путь MDL ("models/player/medic.mdl"), его
    стем - короткое имя класса, так Crowbar называет SMD. У демомена MDL
    называется demo.mdl, а не demoman.mdl
    """
    # Тело называет САМ QC. Имя файла - ненадёжный признак: у пиромана
    # нет морфов лица (он в маске), файла *_morphs_low.smd не бывает, и
    # поиск по имени класса выбирал `pyro_head_bodygroup.smd` - первый
    # по алфавиту. В превью тогда висели голова, баллон, гранаты и рука
    # без тела
    model = load_model(directory)
    qc_path = getattr(model, 'qc_path', None) if model is not None else None
    body = character_body_smd(directory, qc_path)
    if body:
        return body

    class_short = os.path.splitext(os.path.basename(weapon_key))[0]

    # Приоритет 1: *{class}_morphs_low.smd - именно так Crowbar называет тело
    morphs_smds = [
        p for p in glob.glob(os.path.join(directory, f"*{class_short}*_morphs_low.smd"))
        if not _skip(p)
    ]
    if morphs_smds:
        logger.debug(f"[3D] Персонаж SMD (morphs_low): {os.path.basename(morphs_smds[0])}")
        return morphs_smds[0]

    # Приоритет 2: любой *{class}*.smd (не physics/anim), кроме бодигрупп:
    # они не должны содержать класс как основу (medipack.smd, backpack.smd)
    class_smds = [
        p for p in glob.glob(os.path.join(directory, f"*{class_short}*.smd"))
        if not _skip(p)
    ]
    main_smds = [
        p for p in class_smds
        if not any(w in os.path.basename(p).lower() for w in _BODYGROUP_WORDS)
    ]
    chosen = main_smds if main_smds else class_smds
    if chosen:
        logger.debug(f"[3D] Персонаж SMD (class fallback): {os.path.basename(chosen[0])}")
        return chosen[0]
    return None


def character_body_smd(directory: str, qc_path: Optional[str]) -> Optional[str]:
    """
    Тело персонажа: тот меш, к которому пристёгнуты бодигруппы

    Называет его QC - первый `$body`/`$model`, - а не имя файла: у разных
    классов Crowbar зовёт тело по-разному (`heavy_morphs_low.smd`,
    `pyro_reference.smd`), и подбор по имени класса уже промахивался

    Дальше - оговорка, без которой у пиромана тела всё равно нет. Crowbar
    разложил его меш по уровням детализации так, что нулевой уровень пуст
    (`pyro_reference.smd` - 4 треугольника), а вся геометрия лежит в
    `pyro_reference_lod6.smd` (482). Поэтому из семьи «сам файл плюс его
    _lodN» берём самый ПОДРОБНЫЙ: там, где нулевой уровень настоящий (у
    остальных восьми классов), он и побеждает - LOD по определению беднее
    """
    if not qc_path or not os.path.isfile(qc_path):
        return None
    try:
        with open(qc_path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return None
    named = re.search(r'(?im)^\s*\$(?:body|model)\b.*?"([^"]+\.smd)"', text)
    if not named:
        return None
    main = os.path.join(directory, os.path.basename(named.group(1)))
    if not os.path.isfile(main):
        return None

    stem = os.path.splitext(os.path.basename(main))[0]
    family = [main] + glob.glob(os.path.join(directory, f"{stem}_lod*.smd"))
    best = max(family, key=triangle_count)
    if os.path.abspath(best) != os.path.abspath(main):
        logger.info(
            f"[3D] Тело персонажа: у {os.path.basename(main)} нулевой уровень "
            f"пуст, беру {os.path.basename(best)} "
            f"({triangle_count(best)} треугольников)")
    else:
        logger.debug(f"[3D] Тело персонажа из QC: {os.path.basename(best)}")
    return best


# Бодигруппы

def bodygroup_smds(reference_smd_path: str, bodygroups: dict, mode: str,
                   load_model=qc_skin_parser.load_model) -> tuple:
    """
    Доп. SMD рядом с reference: *_bodygroup.smd и части модели из QC

    Source Engine хранит опциональную геометрию (бодигруппы) в отдельных
    SMD файлах рядом с reference SMD. Пример: c_righthand_bodygroup.smd
    внутри c_pyro_arms - правая рука, которая включается при нужном оружии

    Дополнительно подбирает ВСЕ part-SMD, на которые ссылается QC через
    $body/$bodygroup (studio "...smd") - например центральную вставку
    Dead Ringer (pocket_watch_fg), которая лежит отдельным part-SMD и иначе
    не попала бы в превью (её материала не было бы среди mat_names)

    Returns:
        (все доп. SMD, «поздние» из них) - поздние уже в конце первого списка
    """
    directory = os.path.dirname(reference_smd_path)
    found = set(glob.glob(os.path.join(directory, "*_bodygroup.smd")))
    #: Снаряд в оружии - в конце, «поздней» деталью (см. SmdToObjService
    #: LATE_PREFIX): его куски нумеруются после кусков самой модели
    late: list = []

    # Части модели из QC. Берём вариант ПО УМОЛЧАНИЮ каждой бодигруппы
    # (либо выбранный переключателем): переключаемая группа (broken у
    # бутылки, bites у сэндвича, reload у гранатомёта, класс у id_badge)
    # показывает в игре ровно один вариант, и складывать их все в одну
    # модель значит показать бутылку целой и разбитой разом. Файлы
    # НЕвыбранных вариантов убираем и из найденного по маске: у кабера оба
    # набалдашника зовутся *_bodygroup.smd. Материалы скрытых вариантов
    # не теряются - они приходят карточками из $texturegroup
    try:
        model = load_model(directory)
        if model is not None:
            found, late = _chosen_parts(model.qc_path, found, bodygroups)
    except Exception as exc:
        logger.debug(f"[3D] Не удалось собрать part-SMD из QC: {exc}")

    # Экран модели (циферблат Звона смерти) - vgui-панель, которой в меше
    # нет: превращаем её в геометрию, привязанную к своей кости
    from src.services import control_panel
    found.update(control_panel.screen_smds(directory, reference_smd_path))

    # Не включаем сам reference (он уже основной)
    found.discard(os.path.abspath(reference_smd_path))
    found.discard(reference_smd_path)

    # Тело шпиона: маска маскировки объявлена в QC как $bodygroup и иначе
    # попала бы в превью тела. Но у маски своя секция (режим spy_masks /
    # SPY_MASK_MODE_KEY), поэтому из тела её исключаем
    return sorted(strip_spy_disguise_mask(found, mode)) + late, late


def _chosen_parts(qc_path: str, found: set, bodygroups: dict) -> tuple:
    """Выбранные варианты бодигрупп вместо всех найденных по маске"""
    from src.services.model_build_service import ModelBuildService
    late: list = []
    groups = ModelBuildService.extract_bodygroups(qc_path)
    every = {os.path.normcase(os.path.abspath(v))
             for _, variants in groups for v in variants if v}
    found = {p for p in found
             if os.path.normcase(os.path.abspath(p)) not in every}
    choice = ModelBuildService.preview_choice(groups, bodygroups)
    found.update(ModelBuildService.chosen_body_smds(groups, choice))
    for name, variants in groups:
        shown = ModelBuildService.projectile_variant(name, variants)
        if shown is not None and choice.get(name) == shown and variants[shown] in found:
            found.discard(variants[shown])
            late.append(variants[shown])
    return found, late


def swap_reference_for_choice(smd_path: str, bodygroup_smds: list, bodygroups: dict,
                              load_model=qc_skin_parser.load_model) -> str:
    """
    Основной SMD, если переключатель выбрал другой вариант его группы

    У бутылки reference - это `c_bottle.smd`, нулевой вариант группы
    `broken`; выбрали разбитую - рисовать надо `c_bottle_broken.smd`, а
    целую не рисовать вовсе. Вариант забирается из списка частей (список
    правится на месте): он становится основным, а не дополнительным мешем
    """
    if not bodygroups:
        return smd_path
    try:
        from src.services.model_build_service import ModelBuildService
        model = load_model(os.path.dirname(smd_path))
        if model is None:
            return smd_path
        same = lambda a, b: os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
        for name, variants in ModelBuildService.extract_bodygroups(model.qc_path):
            if not any(v and same(v, smd_path) for v in variants):
                continue
            index = bodygroups.get(name, 0)
            picked = variants[index] if 0 <= index < len(variants) else None
            if not picked or same(picked, smd_path) or not os.path.exists(picked):
                return smd_path
            bodygroup_smds[:] = [p for p in bodygroup_smds if not same(p, picked)]
            logger.info(f"[3D] Бодигруппа {name!r}: основной меш → {os.path.basename(picked)}")
            return picked
    except Exception as exc:
        logger.debug(f"[3D] Переключатель бодигрупп не применён: {exc}")
    return smd_path


def strip_spy_disguise_mask(smd_paths, mode: str) -> list:
    """Убирает SMD маски маскировки из bodygroup'ов ТЕЛА шпиона

    Маска шпиона (``spy_mask.smd`` / ``*mask*.smd``) - отдельная секция
    (SPY_MASK_MODE_KEY), в превью тела (mode == "spy_body") её быть не должно.
    Для остальных режимов список не меняется
    """
    paths = list(smd_paths)
    if mode != "spy_body":
        return paths
    kept = [p for p in paths if "mask" not in os.path.basename(p).lower()]
    removed = [p for p in paths if p not in kept]
    if removed:
        logger.info(
            "[3D] Тело шпиона: маска исключена из bodygroup'ов "
            f"({[os.path.basename(p) for p in removed]}) - у неё своя секция"
        )
    return kept
