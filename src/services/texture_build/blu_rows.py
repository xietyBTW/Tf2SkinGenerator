"""
Стадия «строки BLU»: VTF+VMT синей строки $texturegroup поколоночно

Столбец бывает трёх видов: вариант без RED-пары (австралий-строка длиннее
обычной), общий столбец (одно имя в обеих командах) и командный (своё синее
имя). У каждого вида свой шаг
"""

import os

from src.services import qc_skin_parser
from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL, EXTRA_TEX_USE_MAIN
from src.shared.file_utils import copy_file_safe
from src.shared.logging_config import get_logger

from . import game_source

logger = get_logger(__name__)


def build_blu_row_textures(
    blu_row, tg_structure, texture_filename, vtf_filename, ctx, slots, tex,
    extra_texture_callback, weapon_key, animated_fps, is_normal_map,
    extra_materials_vtf_paths,
) -> None:
    """
    Создаёт VTF+VMT для BLU-строки $texturegroup (row 1). На каждый столбец:
    спрашивает отдельное изображение, копирует соответствующую RED-текстуру,
    тянет оригинал из игры или пропускает (служебные/нейтральные shared,
    скин-варианты без RED-аналога). Выравнивание по col_idx с red_row
    """
    from src.data.material_filter import is_editable_material, is_hidden_at_build
    if not blu_row:
        return
    red_row = tg_structure.get('red_row', [])
    main_vtf = slots.vtf_output_path / vtf_filename

    def ask(name):
        return extra_texture_callback(name, weapon_key) if extra_texture_callback else None

    for col_idx, blu_tex_name in enumerate(blu_row):
        # Служебные материалы (sheen-оверлеи, глаза и т.п.) и скрытые
        # (ЧС, маски шпиона) не спрашиваем: их пишет оригиналом
        # write_blacklisted_materials. Пропускаем по col_idx, не удаляя
        # из списка, чтобы сохранить выравнивание с red_row
        if not is_editable_material(blu_tex_name) or is_hidden_at_build(blu_tex_name):
            continue
        # Австралий командой не меняется: его пишет оригиналом
        # write_blacklisted_materials, а свою текстуру - panel-extra. Здесь
        # он шёл «общим столбцом» с вопросом и VMT от главного, и терял
        # золотой блеск. Праздничные имена (c_wrangler_xmas_blue) - родные
        # командные материалы, их этот цикл и пишет
        if qc_skin_parser.is_australium(blu_tex_name):
            continue
        # Находим соответствующее RED имя для этого столбца
        red_tex_name = red_row[col_idx] if col_idx < len(red_row) else None

        if not red_tex_name:
            _variant_column(blu_tex_name, col_idx, ask, main_vtf, texture_filename,
                            slots, tex, animated_fps)
        elif qc_skin_parser.is_shared_column(red_tex_name, blu_tex_name):
            if blu_tex_name.lower() != (texture_filename or "").lower():
                _shared_column(blu_tex_name, ask, main_vtf, slots, tex, animated_fps)
        else:
            _team_column(blu_tex_name, red_tex_name, col_idx, ask, ctx, slots, tex,
                         animated_fps, is_normal_map, extra_materials_vtf_paths)


def _put_game_copy(slots, name, data) -> None:
    """VTF материала - байтами игровой текстуры, помечается копией игры"""
    with open(slots.vtf(name), "wb") as f:
        f.write(data)
    slots.game_copies.add(name.lower())


def _variant_column(blu_tex_name, col_idx, ask, main_vtf, texture_filename,
                    slots, tex, animated_fps) -> None:
    """
    Скин-вариант (австралий, gold) имеет БОЛЬШЕ материалов, чем обычный.
    Например: normal { c_scattergun }, australian { c_scattergun, c_scattergun_gold }.
    c_scattergun_gold нет в RED-строке, но нам всё равно нужно его включить в мод.
    Спрашиваем пользователя и создаём текстуру (или копируем основную)
    """
    logger.info(
        f"Дополнительный материал варианта (нет RED аналога): {blu_tex_name} (col {col_idx})"
    )
    variant_vtf_path = slots.vtf(blu_tex_name)
    variant_vmt_path = slots.vmt(blu_tex_name)
    tex.wait_vtfs()   # копия главной читает её готовый VTF

    if not variant_vtf_path.exists():
        img = ask(blu_tex_name)
        if img == EXTRA_TEX_USE_GAME_ORIGINAL:
            logger.info(f"Извлекаем оригинал варианта из игры: {blu_tex_name}")
            game_vtf = game_source.get_original_vtf_bytes(
                blu_tex_name, slots.original_cdmaterials_paths,
                slots.tf2_textures_vpk, slots.tf2_misc_vpk
            )
            if game_vtf:
                _put_game_copy(slots, blu_tex_name, game_vtf)
            elif main_vtf.exists():
                copy_file_safe(main_vtf, variant_vtf_path)
                if texture_filename.lower() in slots.game_copies:
                    slots.game_copies.add(blu_tex_name.lower())
            img = None  # VTF на месте, пропускаем блок ниже
        if img == EXTRA_TEX_USE_MAIN or (img and not os.path.isfile(img)):
            img = None   # ниже - копия основной
        if img:
            tex.for_material(blu_tex_name).render_user_image_vtf(
                img, variant_vtf_path, f"{blu_tex_name}.png")
            logger.info(f"Создан VTF варианта (отд. изображение): {blu_tex_name}.vtf")
        elif not variant_vtf_path.exists():
            # Пользователь отказался или нет callback - копируем основную
            if main_vtf.exists():
                copy_file_safe(main_vtf, variant_vtf_path)
                logger.info(f"Создан VTF варианта (копия основной): {blu_tex_name}.vtf")
            else:
                logger.warning(f"Основной VTF не найден для варианта: {main_vtf}")

    if not variant_vmt_path.exists():
        game_source.write_material_vmt(variant_vmt_path, slots.vmt_path,
                                       slots.patched_cdmaterials_path, blu_tex_name)
        if animated_fps:
            VMTService.enable_animated_basetexture(str(variant_vmt_path), animated_fps)


def _shared_column(blu_tex_name, ask, main_vtf, slots, tex, animated_fps) -> None:
    """
    BLU имя совпадает с RED - общая (нейтральная) скиновая текстура (sniper_lens,
    c_arrow и т.п.): спрашиваем пользователя, как для extra_materials.
    Служебные общие сюда не доходят - их отсекает проверка в начале цикла
    """
    shared_vtf_path = slots.vtf(blu_tex_name)
    shared_vmt_path = slots.vmt(blu_tex_name)
    # VMT уже записан (тем же именем в соседнем столбце, у синего
    # «из игры» - ссылкой без VTF): второй раз не спрашиваем
    if not shared_vtf_path.exists() and not shared_vmt_path.exists():
        img = ask(blu_tex_name)
        if img == EXTRA_TEX_USE_GAME_ORIGINAL:
            game_vtf = game_source.get_original_vtf_bytes(
                blu_tex_name, slots.original_cdmaterials_paths,
                slots.tf2_textures_vpk, slots.tf2_misc_vpk, log_not_found=False
            )
            if not game_vtf:
                logger.debug(f"Shared VTF не найден в игре, пропуск: {blu_tex_name}")
                return
            _put_game_copy(slots, blu_tex_name, game_vtf)
            logger.info(f"Shared VTF из игры: {blu_tex_name}.vtf")
        elif img == EXTRA_TEX_USE_MAIN:
            tex.wait_vtfs()
            if not main_vtf.exists():
                logger.debug(f"Shared: главной VTF нет, пропуск: {blu_tex_name}")
                return
            copy_file_safe(main_vtf, shared_vtf_path)
            logger.info(f"Shared: копия главной → {blu_tex_name}.vtf")
        elif img and str(img).lower().endswith('.vtf'):
            copy_file_safe(img, shared_vtf_path)
            logger.info(f"Shared: готовый VTF скопирован → {blu_tex_name}.vtf")
        elif img and os.path.isfile(img):
            mt = tex.for_material(blu_tex_name)
            flags, merged = TextureService.resolve_vtf_flags_and_options(
                mt.flags, mt.vtf_options, drop_normal=True)
            mt.image_to_vtf(img, f"{blu_tex_name}.png", flags, merged)
            logger.info(f"Создан shared VTF: {blu_tex_name}.vtf")
        else:
            # Пользователь пропустил - не включаем
            logger.debug(f"Shared texture пропущена пользователем: {blu_tex_name}")
            return

    # VTF существует -> создаём VMT если нет
    if not shared_vmt_path.exists():
        game_source.write_material_vmt(shared_vmt_path, slots.vmt_path,
                                       slots.patched_cdmaterials_path, blu_tex_name)
    if animated_fps:
        VMTService.enable_animated_basetexture(str(shared_vmt_path), animated_fps)


def _team_column(blu_tex_name, red_tex_name, col_idx, ask, ctx, slots, tex,
                 animated_fps, is_normal_map, extra_materials_vtf_paths) -> None:
    """Командный столбец: своё синее имя у RED-материала"""
    logger.info(f"Создаем текстуры для BLU команды: {blu_tex_name} (RED: {red_tex_name})")
    blu_vtf_path = slots.vtf(blu_tex_name)
    blu_vmt_path = slots.vmt(blu_tex_name)

    # Спрашиваем у пользователя отдельное изображение для BLU материала
    img = ask(blu_tex_name)
    # «Из игры»: синяя текстура и так лежит в игре, и VMT смотрит на
    # неё её путём, как у золота. Копия VTF в моде - мёртвый вес
    # (у медигана 5,5 МБ при своей текстуре в 87 КБ). Только когда
    # родной VMT смотрит на текстуру с именем материала, иначе (синий
    # цвет задан в VMT, а текстура общая с красным) VTF копируется
    game_tex = (game_source.game_texture(blu_tex_name, ctx, slots)
                if img == EXTRA_TEX_USE_GAME_ORIGINAL else None)
    if game_tex and game_tex.rsplit('/', 1)[-1].lower() != blu_tex_name.lower():
        game_tex = None
    if game_tex:
        logger.info(f"BLU {blu_tex_name}: текстура из игры по ссылке {game_tex}")
        img = None
    if img in (EXTRA_TEX_USE_GAME_ORIGINAL, EXTRA_TEX_USE_MAIN):
        game_vtf = (game_source.get_original_vtf_bytes(
            blu_tex_name, slots.original_cdmaterials_paths,
            slots.tf2_textures_vpk, slots.tf2_misc_vpk
        ) if img == EXTRA_TEX_USE_GAME_ORIGINAL else None)
        if game_vtf:
            _put_game_copy(slots, blu_tex_name, game_vtf)
            logger.info(f"Извлечён VTF из игры для BLU текстуры: {blu_tex_name}.vtf")
        else:
            # «Скопировать главную» у BLU - это его RED-пара, сюда же
            # падает «из игры», когда синей текстуры в игре нет
            tex.wait_vtfs()
            red_src = (slots.vtf(red_tex_name) if col_idx == 0
                       else extra_materials_vtf_paths.get(red_tex_name, slots.vtf(red_tex_name)))
            if red_src.exists():
                copy_file_safe(red_src, blu_vtf_path)
                if red_tex_name.lower() in slots.game_copies:
                    slots.game_copies.add(blu_tex_name.lower())
        img = None

    if img and os.path.isfile(img):
        # Пользователь дал отдельное изображение для этого BLU материала
        logger.info(f"Используем отдельное изображение для BLU {blu_tex_name}: {img}")
        # Синий - та же карточка, что и красная пара: её настройки
        tex.for_material(red_tex_name).render_user_image_vtf(
            img, blu_vtf_path, f"{blu_tex_name}.png")
    elif not blu_vtf_path.exists() and not game_tex:
        # Пользователь не предоставил изображение для BLU -
        # не включаем в мод, движок найдёт оригинал сам
        logger.debug(f"BLU текстура пропускается (нет изображения): {blu_tex_name}")
        return

    # Создаем VMT для BLU (копируем RED VMT и обновляем $basetexture)
    game_source.write_material_vmt(blu_vmt_path, slots.vmt(red_tex_name),
                                   slots.patched_cdmaterials_path, blu_tex_name)
    if game_tex:
        dir_, _, file_ = game_tex.rpartition('/')
        VMTService.update_vmt_basetexture_path(str(blu_vmt_path), dir_, file_)
    if animated_fps:
        VMTService.enable_animated_basetexture(str(blu_vmt_path), animated_fps)

    # Normal map для BLU
    if is_normal_map:
        tex.wait_vtfs()
        red_normal_vtf = slots.vtf(f"{red_tex_name}_normal")
        if red_normal_vtf.exists():
            copy_file_safe(red_normal_vtf, slots.vtf(f"{blu_tex_name}_normal"))
            logger.info(f"Скопирован normal VTF для BLU: {blu_tex_name}_normal.vtf")
        blu_normal_key = f"{blu_tex_name}_normal"
        VMTService.update_vmt_bumpmap_path(str(blu_vmt_path), slots.patched_cdmaterials_path,
                                           blu_normal_key)
        logger.info(f"Обновлен VMT $bumpmap для BLU: {blu_normal_key}")
