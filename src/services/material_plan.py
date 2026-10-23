"""
План материалов сборки модели: что и под какими именами строить

Разбор $texturegroup, сужение до текстур рук, изоляция плеч вьюмодели,
промоушен нейтральных материалов в командные, «сделать командным»,
подавление игровой группы для своей модели. Все функции МУТИРУЮТ QC
(и SMD при изоляции плеч) до компиляции - VPKService только зовёт их
"""

import os
from dataclasses import dataclass

from .model_build_service import ModelBuildService
from .smd_service import SMDService
from .vpk_model_pipeline import VpkModelPipeline
from .texture_build import styles
from src.data.player_hands import HAND_MODE_KEYS
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class MaterialPlan:
    """План материалов сборки: что и под какими именами строить (результат
    анализа $texturegroup + изоляции плеч + подавления для кастомных моделей).
    QC к этому моменту уже пропатчен/синхронизирован (side effect plan_materials)"""
    tg_structure: dict
    blu_row: list
    extra_materials: list
    blu_is_team: bool
    blacklisted_extra: list
    texture_filename: str
    blu_mode: str
    has_skins: bool
    shoulder_iso: list
    image_path: object
    skin_build_data: object
    game_vmt_name: str



def apply_shoulder_isolation(
    ctx, mode, qc_path, weapon_key, tg_structure,
    orig_main_pre_restrict, image_path, blu_image_path,
    panel_extra_textures, panel_blu_textures, isolate_shoulders,
):
    """
    Изоляция плеч/тела вьюмодели рук + команд-промоушен нейтральных
    материалов. Переименовывает общий с миром материал плеч в vm_* в
    $texturegroup и в самих SMD (reference + bodygroup) ДО компиляции,
    плюс синтезирует командные варианты. Только для режимов рук

    Returns:
        (shoulder_iso, image_path) - список [(new_name, orig_name,
        source_path|None)] для записи материалов ниже и (возможно
        перенаправленный) image_path главной текстуры
    """
    if mode not in HAND_MODE_KEYS:
        return [], image_path
    ref_smd, shoulders = _shoulder_candidates(ctx, mode, qc_path, weapon_key, tg_structure)
    srcs = {s: _shoulder_source(s, panel_extra_textures or {}, orig_main_pre_restrict, image_path)
            for s in shoulders}
    do_iso = bool(shoulders) and (isolate_shoulders or any(srcs.values()))
    logger.info(
        f"[SHOULDER ISO] флаг={isolate_shoulders}, плечи={shoulders}, "
        f"источники={ {s: bool(p) for s, p in srcs.items()} }, изолируем={do_iso}"
    )
    if not do_iso:
        shoulders = []
    promo, variant_entries = _team_promotions(qc_path, panel_blu_textures, shoulders)
    if not (shoulders or promo):
        return [], image_path

    rename = {s: SMDService._sanitize_material_name(f"vm_{s}") for s in shoulders}
    blue_iso = _blue_shoulders(shoulders, tg_structure, rename, orig_main_pre_restrict)
    _rename_in_qc_and_smds(qc_path, weapon_key, ref_smd, tg_structure, promo, rename, shoulders)

    shoulder_iso = [(rename[s], s, srcs[s]) for s in shoulders]
    # Синие плечи: источник - пользовательская BLU-картинка
    # (если плечи были главной) либо оригинал {orig_blue} из игры
    blue_main_src = (
        blu_image_path
        if (blu_image_path and blu_image_path != EXTRA_TEX_USE_GAME_ORIGINAL
            and os.path.isfile(str(blu_image_path)))
        else None
    )
    for vm_blue, orig_blue, is_main in blue_iso:
        shoulder_iso.append((vm_blue, orig_blue, blue_main_src if is_main else None))
    if blue_iso:
        logger.info(f"[SHOULDER ISO] синие плечи: {[b[0] for b in blue_iso]}")
    # Командные варианты нейтральных (из «+») - пишем их VTF/VMT
    shoulder_iso.extend(variant_entries)
    if variant_entries:
        logger.info(f"[TEAM PROMO] варианты записаны: {[v[0] for v in variant_entries]}")
    logger.info(f"[SHOULDER ISO] переименованы плечи: {rename}")
    # Если текстура плеч пришла как image_path (главная) -
    # НЕ даём записать её на руку: главная уйдёт на оригинал
    if any(p is not None and p == image_path for p in srcs.values()):
        image_path = EXTRA_TEX_USE_GAME_ORIGINAL
        logger.info("[SHOULDER ISO] главная текстура (плечи) перенаправлена в vm_*; руке - оригинал")
    return shoulder_iso, image_path


def _shoulder_candidates(ctx, mode, qc_path, weapon_key, tg_structure):
    """(reference-SMD, плечи): редактируемые материалы меша рук, которых нет
    среди текстур самих рук"""
    from src.data.player_hands import get_hand_textures
    from src.services.qc_skin_parser import detect_shoulder_materials
    from src.data.material_filter import is_editable_material
    whitelist = [n for _, n in get_hand_textures(mode)]
    # Материалы РЕАЛЬНОГО меша (из reference SMD), а не полная
    # skin-таблица red_row (там варианты/ганслингер/blue)
    ref_smd = VpkModelPipeline._find_decompiled_reference_smd(
        qc_path, weapon_key, ctx.decompile_dir
    )
    mesh_mats = SMDService.ordered_unique_materials(ref_smd) if ref_smd else []
    shoulders = detect_shoulder_materials(
        mesh_mats or tg_structure.get('red_row', []), whitelist
    )
    return ref_smd, [s for s in shoulders if is_editable_material(s)]


def _shoulder_source(s, panel_extra, orig_main, image_path):
    """Источник текстуры плеча: карточка из panel_extra ИЛИ image_path (если
    плечи были col0/«главной» - тогда их текстура ушла в from_path и была
    выкинута из panel_extra)"""
    v = panel_extra.get(s)
    if not v:
        sl = s.lower()
        v = next((vv for kk, vv in panel_extra.items() if kk.lower() == sl), None)
    if v and os.path.isfile(v):
        return v
    if (s.lower() == str(orig_main).lower()
            and image_path and image_path != EXTRA_TEX_USE_GAME_ORIGINAL
            and os.path.isfile(str(image_path))):
        return image_path
    return None


def _team_promotions(qc_path, panel_blu_textures, shoulders):
    """
    Промоушен: НЕЙТРАЛЬНЫЙ материал (нет своего blue-варианта в blu_row) с
    загруженной СИНЕЙ текстурой -> делаем командным. Уже-командные
    (medic_hands_red->medic_hands_blue в blu_row) и плечи - НЕ трогаем (их
    ведёт нативный BLU-блок / изоляция)

    Returns:
        ({mat_lower: variant_name}, [(variant, orig_mat, src_path)])
    """
    promo, variant_entries = {}, []
    if not panel_blu_textures:
        return promo, variant_entries
    from src.services import qc_skin_parser as _qsp
    rows_now = ModelBuildService._parse_texturegroup_rows(qc_path) or []
    neutral = {m.lower() for m in _qsp.neutral_materials(rows_now)}
    sh_set = {s.lower() for s in shoulders}
    for m, bp in panel_blu_textures.items():
        ml = m.lower()
        if ml in neutral and ml not in sh_set and bp and os.path.isfile(str(bp)):
            var = (m[:-4] + '_blue') if ml.endswith('_red') else (m + '_blue')
            var = SMDService._sanitize_material_name(var)
            promo[ml] = var
            variant_entries.append((var, m, bp))
    if promo:
        logger.info(f"[TEAM PROMO] нейтральные → командные: {promo}")
    return promo, variant_entries


def _blue_shoulders(shoulders, tg_structure, rename, orig_main):
    """
    Синяя команда: BLU-вариант плеча по соглашению имён (engineer_red ->
    engineer_blue), фолбэк - та же колонка blu-строки texturegroup. Тоже
    изолируем (vm_engineer_blue), иначе синий игрок увидит оригинал/фиолет.
    Дописывает переименования в rename

    Returns:
        [(vm_blue, orig_blue, плечи_были_главной)]
    """
    red_row = tg_structure.get('red_row', []) or []
    blu_row = tg_structure.get('blu_row', []) or []
    blue_iso = []
    for s in shoulders:
        sl = s.lower()
        bv = None
        if sl.endswith('_red'):
            bv = s[:-4] + '_blue'
        else:
            col = next((i for i, m in enumerate(red_row) if m.lower() == sl), None)
            if col is not None and col < len(blu_row):
                cand = blu_row[col]
                if cand and cand.lower() != sl:
                    bv = cand
        if not bv or bv.lower() == sl:
            continue   # команд-нейтральный материал
        rename[bv] = SMDService._sanitize_material_name(f"vm_{bv}")
        blue_iso.append((rename[bv], bv, sl == str(orig_main).lower()))
    return blue_iso


def _rename_in_qc_and_smds(qc_path, weapon_key, ref_smd, tg_structure, promo, rename, shoulders):
    """Промоушен нейтральных в командные (синие строки -> варианты), затем
    переименование плеч на vm_* - в $texturegroup и в самих SMD"""
    rows = (ModelBuildService._parse_texturegroup_rows(qc_path)
            or [tg_structure.get('red_row', [])])
    if promo:
        from src.services.qc_skin_parser import apply_team_promotions
        rows = apply_team_promotions(rows, promo)
    tg = ModelBuildService.generate_renamed_texturegroup(rows, rename)
    if tg:
        ModelBuildService.replace_texturegroup_in_qc(qc_path, tg)
    # ГЛАВНОЕ: studiomdl берёт имя материала skin 0 из SMD,
    # поэтому переименовываем материал в самих SMD (reference
    # + bodygroup), иначе модель ссылается на старое имя и
    # текстура становится фиолетовой
    smds = [ref_smd] if ref_smd else []
    try:
        smds += ModelBuildService.extract_extra_body_smds(qc_path, weapon_key) or []
    except Exception as e:
        logger.debug(f"[SHOULDER ISO] не удалось собрать доп. body-SMD: {e}")
    rmap_smd = {s.lower(): rename[s] for s in shoulders}
    for sp in smds:
        try:
            n = SMDService.rename_materials_in_smd(sp, rmap_smd)
            if n:
                logger.info(f"[SHOULDER ISO] SMD {os.path.basename(sp)}: заменено {n} материалов")
        except Exception as e:
            logger.warning(f"[SHOULDER ISO] не удалось переименовать в {sp}: {e}")


def apply_force_team(force_team, mode, qc_path, weapon_key, ctx) -> None:
    """
    «Сделать командным»: для оружия БЕЗ нативной команды делает синей BLU-строку
    каждой пары скинов $texturegroup ({material}_blue по материалам
    reference-SMD), чтобы дальше весь командный путь отработал как у
    нативно-командного. Остальные строки (австралий, ботокиллеры) остаются:
    замена всей группы двумя строками потеряла бы золото. Мутирует QC
    """
    if force_team and mode not in HAND_MODE_KEYS:
        try:
            from src.services import qc_skin_parser as _qsp
            if ModelBuildService.extract_skin_info(qc_path).get('is_team'):
                logger.info("[FORCE TEAM] оружие уже командное - пропуск")
                return
            from src.services import smd_service
            from src.data.item_kinds import kind_of
            from src.data.material_filter import is_editable_material as _ed
            # У шапок и персонажей командность в игре ещё не проверена:
            # без меша строки не дописываются, QC остаётся как был
            _kind = kind_of(mode)
            _ref = (None if _kind.is_hat or _kind.is_character or _kind.is_spy_mask
                    else smd_service.find_reference_smd(str(ctx.decompile_dir), weapon_key))
            _mesh = SMDService.ordered_unique_materials(_ref) if _ref else []
            _rows = _qsp.parse_texturegroup_rows(qc_path)
            _new = _qsp.force_team_rows(_rows, [m for m in _mesh if _ed(m)])
            if _new is None:
                why = ("вторая строка скинов - стиль, а не пара команды"
                       if not _qsp.team_pairs_free(_rows)
                       else f"нет материалов меша для команды (меш={_mesh})")
                logger.warning(f"[FORCE TEAM] команду не дописать: {why} "
                               f"(строки={_rows}) - пропуск")
                return
            ModelBuildService.replace_texturegroup_in_qc(
                qc_path, ModelBuildService.generate_renamed_texturegroup(_new, {}))
            logger.info(f"[FORCE TEAM] синие строки пар: {_new[1::2]}")
        except Exception as _fte:
            logger.warning(f"[FORCE TEAM] не удалось синтезировать команду: {_fte}")


def plan_materials(
    qc_path, mode, weapon_key, ctx, texture_filename, image_path, blu_image_path,
    panel_extra_textures, panel_blu_textures, isolate_shoulders, blu_mode,
    skin_build_data, replace_keep_materials, custom_qc_text, original_cdmaterials_path,
    bypass_prefix: str = "console", misc_materials=None,
) -> MaterialPlan:
    """
    Анализирует $texturegroup и решает, какие материалы строить: BLU-строка,
    доп. материалы, служебные/ЧС (пишутся оригиналом), фильтр для рук, изоляция
    плеч, подавление игровой группы для кастомных моделей. Финализирует QC
    (patch_qc_file, инъекция/удаление $texturegroup, пользовательский QC-текст).
    Мутирует файл qc_path. Возвращает MaterialPlan со всеми выходными именами
    """
    tg_structure = ModelBuildService.extract_texturegroup_structure(qc_path)
    blu_row = tg_structure.get('blu_row', [])
    extra_materials = tg_structure.get('extra_materials', [])
    # Настоящая ли команда вторая строка (c_xxx_blue), а не вариант
    # (австралий/gold/festive). У вариант-онли оружия команды нет -
    # значит {texture}_blue не нужен
    blu_is_team = bool(tg_structure.get('blu_is_team', False))

    # Оружие с одной общей текстурой (напр. часы шпиона) - BLU не нужен.
    # Иначе в мод попадёт лишняя _blue текстура
    from src.data.weapon_quirks import NO_BLU_WEAPON_KEYS
    if weapon_key in NO_BLU_WEAPON_KEYS:
        if blu_row:
            logger.info(f"[{weapon_key}] BLU-row подавлен (одиночная текстура)")
        blu_row = []

    orig_main_pre_restrict = texture_filename  # col0 (может быть плечи)
    if mode in HAND_MODE_KEYS:
        texture_filename, extra_materials, blu_row = _restrict_to_hands(
            mode, texture_filename, tg_structure)
    else:
        texture_filename, extra_materials, blu_row = _restrict_to_own(
            weapon_key, texture_filename, extra_materials, blu_row, tg_structure)

    # Изоляция плеч вьюмодели (опционально)
    # Материал плеч/тела arms-модели общий с мировым персонажем.
    # Переименовываем его на уникальный (engineer_red -> vm_engineer_red)
    # в $texturegroup ДО компиляции: перекомпилированная модель станет
    # ссылаться на новый материал, а мир останется на старом. Позже
    # запишем переименованный материал отдельным блоком
    shoulder_iso, image_path = apply_shoulder_isolation(
        ctx, mode, qc_path, weapon_key, tg_structure,
        orig_main_pre_restrict, image_path, blu_image_path,
        panel_extra_textures, panel_blu_textures, isolate_shoulders,
    )

    # Делаем ПОСЛЕ hands-блока, т.к. он переназначает extra_materials/blu_row
    extra_materials, blacklisted_extra = _split_asked_and_silent(
        tg_structure, extra_materials, texture_filename, misc_materials)
    # Чужие материалы модели (руки шпиона во вьюмодели часов) - ни карточкой,
    # ни «оригиналом»: игра и так берёт их из своих файлов
    from src.data.weapon_quirks import is_own_material
    blacklisted_extra = [m for m in blacklisted_extra if is_own_material(weapon_key, m)]
    # blu_row НЕ фильтруем удалением - он индексируется по колонкам
    # вместе с red_row. Служебные blu-материалы пропускаются ВНУТРИ
    # цикла (по col_idx), чтобы не сместить выравнивание

    # Стили (skinfamilies) кастомной модели
    # Если пользователь определил доп-стили, ИГРОВОЙ $texturegroup
    # неприменим: его имена (c_sd_cleaver_bloody, _blue …) относятся
    # к игровой модели, а не к мешу пользователя. Подавляем
    # производные из него BLU/extra-материалы и команду - мы
    # сгенерируем свою группу и варианты ниже. Меш-материалы базы
    # приходят отдельно через panel_extra_textures.
    # Для рук $texturegroup уже сгенерирован выше (изоляция плеч +
    # промоушен): vm_* для плеч + _blu варианты в синих строках.
    # Старый «кастомный» SKIN BUILD путь его перезатёр бы - отключаем
    has_skins = (bool(skin_build_data and skin_build_data.get('tg_overrides'))
                 and mode not in HAND_MODE_KEYS)
    # Для «готовой» кастомной модели (keep_materials) ИГРОВОЙ
    # $texturegroup неприменим ВСЕГДА - у меша свои материалы
    # (c_sd_cleaver/mouth/lefteye…), а игровые имена (c_scattergun,
    # c_scattergun_gold) к нему отношения не имеют. Иначе сборка
    # начнёт спрашивать текстуры для игровых слотов, которых нет
    # в карточках. Базовые меш-материалы идут через panel_extra_textures
    if has_skins or replace_keep_materials:
        logger.info(
            "[SKIN BUILD] кастомная модель → подавляем игровой "
            f"texturegroup (blu_row={blu_row}, extra={extra_materials})"
        )
        blu_row = []
        extra_materials = []
        blacklisted_extra = []  # у кастомного меша свои материалы - не пишем
        blu_mode = 'none'   # не плодим {texture}_blue

    if blu_row:
        logger.info(f"Найдена BLU команда: {blu_row}")
    if extra_materials:
        logger.info(f"Найдены дополнительные материалы модели: {extra_materials}")

    # Пропатчиваем QC файл: перенаправляем $cdmaterials в whitelisted-папку
    # обхода sv_pure (console\ или vgui\replay\thumbnails\), удаляем $lod
    ModelBuildService.patch_qc_file(qc_path, bypass_prefix)

    # Игровое имя текстуры/VMT (источник ОРИГИНАЛЬНОГО кода VMT из игры).
    # Для кастомной модели texture_filename станет именем материала SMD,
    # но оригинальный VMT тащим по игровому имени (c_sd_cleaver),
    # затем лишь переставим $basetexture на материал модели
    game_vmt_name = texture_filename

    if replace_keep_materials:
        texture_filename, skin_build_data = _align_to_smd_materials(
            ctx, qc_path, weapon_key, texture_filename, skin_build_data, has_skins)
    tg_block = _write_custom_texturegroup(
        qc_path, has_skins, replace_keep_materials, skin_build_data)
    if replace_keep_materials and custom_qc_text and custom_qc_text.strip():
        _apply_custom_qc_text(ctx, qc_path, weapon_key, custom_qc_text, tg_block)
    return MaterialPlan(
        tg_structure=tg_structure, blu_row=blu_row, extra_materials=extra_materials,
        blu_is_team=blu_is_team, blacklisted_extra=blacklisted_extra,
        texture_filename=texture_filename, blu_mode=blu_mode, has_skins=has_skins,
        shoulder_iso=shoulder_iso, image_path=image_path,
        skin_build_data=skin_build_data, game_vmt_name=game_vmt_name,
    )


def _restrict_to_own(weapon_key, texture_filename, extra_materials, blu_row, tg_structure):
    """
    Оставляет только свои материалы модели (MODEL_MATERIAL_WHITELIST). Часы
    Крякенптиц - вьюмодель, где первым материалом стоят руки шпиона: без
    этого главной текстурой стали бы руки, и своя картинка легла бы на
    общую текстуру рук всего оружия шпиона

    Returns:
        (texture_filename, extra_materials, blu_row)
    """
    from src.data.weapon_quirks import is_own_material
    from src.services.qc_skin_parser import restrict_to_materials
    red_row = tg_structure.get('red_row', [])
    allowed = [m for m in red_row if is_own_material(weapon_key, m)]
    if not allowed or len(allowed) == len(red_row):
        return texture_filename, extra_materials, blu_row
    texture_filename, extra_materials, blu_row = restrict_to_materials(
        main_texture=texture_filename, red_row=red_row, blu_row=blu_row,
        allowed_names=allowed)
    logger.info(f"[{weapon_key}] только свои материалы: {texture_filename!r} + {extra_materials}")
    return texture_filename, extra_materials, blu_row


def _restrict_to_hands(mode, texture_filename, tg_structure):
    """
    Для режимов рук: фильтруем $texturegroup до актуальных текстур рук.
    QC руки инженера (c_engineer_arms) в column 0 содержит "engineer_red"
    (текстуру ТЕЛА), а не текстуру руки - без фильтрации картинка
    пользователя заменила бы всё тело персонажа

    Returns:
        (texture_filename, extra_materials, blu_row)
    """
    from src.data.player_hands import get_hand_textures
    from src.services.qc_skin_parser import restrict_to_materials
    texture_filename, extra_materials, blu_row = restrict_to_materials(
        main_texture=texture_filename,
        red_row=tg_structure.get('red_row', []),
        blu_row=tg_structure.get('blu_row', []),
        allowed_names=[n for _, n in get_hand_textures(mode)],
    )
    logger.info(
        f"[HANDS] texture_filename={texture_filename!r}, "
        f"extra_materials={extra_materials}, blu_row={blu_row}"
    )
    return texture_filename, extra_materials, blu_row


def _split_asked_and_silent(tg_structure, extra_materials, texture_filename, misc_materials):
    """
    Спрашиваем ровно то, что человек видит карточкой: основные материалы
    геометрии и «Прочее» со страницы (убер/зомби-варианты, у которых
    превью нашло текстуру - сами они в геометрии не встречаются, модель
    ссылается на них из других скинов). Молча, игровым оригиналом, пишем
    остальное: пользовательский ЧС, маски шпиона (у них своя страница) и
    служебное без карточки (глаза без $basetexture, оверлеи) - без
    записи под console\\-cdmaterials оно фиолетовое

    Returns:
        (extra_materials, blacklisted_extra) - спросить / записать оригиналом
    """
    from src.data.material_filter import is_editable_material, is_hidden_at_build
    from src.services.qc_skin_parser import is_australium
    # Источник - ВЕСЬ $texturegroup (все строки/колонки), а не
    # extra_materials: служебные варианты обычно не в геометрии
    all_tg_mats: list = []
    seen_tg: set = set()
    for row in (tg_structure.get('all_rows') or []):
        for m in row:
            ml = (m or '').lower()
            if ml and ml not in seen_tg:
                seen_tg.add(ml)
                all_tg_mats.append(m)
    extra_materials = [m for m in extra_materials
                       if is_editable_material(m) and not is_hidden_at_build(m)]
    asked = {m.lower() for m in extra_materials} | {texture_filename.lower()}
    tg_names = {m.lower(): m for m in all_tg_mats}
    for m in (misc_materials or []):
        ml = (m or '').lower()
        if ml in tg_names and ml not in asked and not is_hidden_at_build(m):
            asked.add(ml)
            extra_materials.append(tg_names[ml])
    # Австралий (_gold) тоже пишем оригиналом, если человек его не правил:
    # у золота свой VMT (кубмапа, блеск, sheen), а производный от главного
    # делал австралий матовым. Спрашивать о нём незачем - своя текстура
    # приходит карточкой (panel-extra). Праздничные имена сюда НЕ входят:
    # у праздничного оружия это родные материалы (см. is_australium)
    blacklisted_extra = [m for m in all_tg_mats
                         if m.lower() not in asked
                         and (is_hidden_at_build(m) or not is_editable_material(m)
                              or is_australium(m))]
    if blacklisted_extra:
        logger.info(f"Служебные/ЧС материалы (без карточек, пишем оригиналом): {blacklisted_extra}")
    return extra_materials, blacklisted_extra


def _align_to_smd_materials(ctx, qc_path, weapon_key, texture_filename, skin_build_data, has_skins):
    """
    Кастомная модель: имена ведём от ФАКТИЧЕСКИХ материалов SMD. Имена
    VTF/VMT, $texturegroup и $basetexture обязаны совпадать с материалом,
    с которым реально компилируется модель (из reference-SMD). UI-имена
    могли разойтись с SMD (другой экспорт/регистр) -> текстура не находилась
    (фиолетовая). Картинки скинов мапим по индексу

    Returns:
        (texture_filename, skin_build_data)
    """
    ref_smd = VpkModelPipeline._find_decompiled_reference_smd(
        qc_path, weapon_key, ctx.decompile_dir
    )
    smd_mats = SMDService.ordered_unique_materials(ref_smd) if ref_smd else []
    if not smd_mats:
        return texture_filename, skin_build_data
    logger.info(f"[SKIN BUILD] материалы SMD (истина): {smd_mats}")
    if has_skins:
        skin_build_data = styles.remap_skin_data_to_smd(skin_build_data, smd_mats)
    if texture_filename != smd_mats[0]:
        logger.info(
            f"[SKIN BUILD] main texture_filename: "
            f"{texture_filename!r} → {smd_mats[0]!r} (материал SMD)"
        )
        texture_filename = smd_mats[0]
    return texture_filename, skin_build_data


def _write_custom_texturegroup(qc_path, has_skins, replace_keep_materials, skin_build_data) -> str:
    """$texturegroup кастомной модели. Возвращает вписанный блок ('' - нет)"""
    if has_skins:
        # Свои стили: генерируем группу (имена выровнены по SMD)
        tg_block = ModelBuildService.generate_texturegroup_block(
            skin_build_data.get('mesh_materials', []),
            skin_build_data.get('tg_overrides', {}),
        )
        ModelBuildService.replace_texturegroup_in_qc(qc_path, tg_block)
        logger.info(f"[SKIN BUILD] $texturegroup инъектирован в QC:\n{tg_block}")
        return tg_block
    if replace_keep_materials:
        # Одно-скиновая кастомная модель: убираем игровую группу - её
        # имена относятся к игровой модели, не к мешу (иначе пустые
        # skin-строки ремапят материал в пустоту -> фиолет)
        ModelBuildService.replace_texturegroup_in_qc(qc_path, '')
        logger.info("[SKIN BUILD] игровой $texturegroup удалён (одно-скиновая кастомная модель)")
    return ''


def _apply_custom_qc_text(ctx, qc_path, weapon_key, custom_qc_text, tg_block) -> None:
    """
    Отредактированный пользователем QC: заменяем QC текстом пользователя,
    синхронизировав $texturegroup с актуальными стилями (правки человека не
    теряются). Делается ДО извлечения cdmaterials - дальше всё читается из
    этого QC
    """
    final_qc = ModelBuildService.replace_texturegroup_in_text(custom_qc_text, tg_block)
    with open(qc_path, 'w', encoding='utf-8') as qf:
        qf.write(final_qc)
    logger.info("[QC EDIT] QC заменён пользовательским (texturegroup синхронизирован)")
    # Описания своих костей модели писались в прежний QC
    # (_apply_model_replacement) - правленый их стёр, и studiomdl
    # снова свернул бы кости в родителя
    ref = VpkModelPipeline._find_decompiled_reference_smd(qc_path, weapon_key, ctx.decompile_dir)
    if ref:
        ModelBuildService.define_missing_bones(qc_path, ref)
