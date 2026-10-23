"""
Стадия «основная текстура»: главный VTF/VMT материала и синяя пара
главной ({texture}_blue) у предметов с настоящей командой
"""

import os
import shutil
from pathlib import Path
from typing import Optional

from src.services import qc_skin_parser
from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL, EXTRA_TEX_USE_MAIN
from src.shared.file_utils import copy_file_safe, ensure_directory_exists
from src.shared.logging_config import get_logger

from . import game_source

logger = get_logger(__name__)


def build_main_material(
    image_path, texture_filename, vtf_filename, vtf_temp_png,
    original_cdmaterials_path, _game_vmt_name, mode, hat_apply_game_paints,
    ctx, slots, tex, extra_texture_callback, weapon_key, _eff,
):
    """
    Главная текстура материала: резолв RED (пользователь / «из игры»), создание
    главного VTF (готовый custom / .vtf из карточки / рендер из картинки) и запись
    главного VMT (родной игровой код с $basetexture, перенаправленным на материал).
    ``_eff`` - замыкание эффективных пер-текстурных настроек

    Returns:
        (image_path, animated_fps, is_normal_map, vmt_to_delete)
    """
    is_normal_map = False
    animated_fps = None
    # RED не загружен - сначала спрашиваем пользователя
    # через существующий extra_texture_callback (стандартный диалог).
    # Если callback вернул EXTRA_TEX_USE_GAME_ORIGINAL или None -
    # извлекаем оригинал из игрового VPK
    if image_path == EXTRA_TEX_USE_GAME_ORIGINAL:
        # Без своей главной собирают ради другой правки - спрашивать,
        # чем красить главную, незачем: она остаётся игровой
        if extra_texture_callback and not tex.main_from_game:
            image_path = extra_texture_callback(texture_filename, weapon_key)
            logger.info(f"Callback для основной RED текстуры: {image_path!r}")

        if image_path in (EXTRA_TEX_USE_GAME_ORIGINAL, EXTRA_TEX_USE_MAIN) or not image_path:
            # «Из игры», «главную» (это и есть главная) или ничего - оригинал
            _orig_red = game_source.get_original_vtf_bytes(
                texture_filename, slots.original_cdmaterials_paths,
                slots.tf2_textures_vpk, slots.tf2_misc_vpk
            )
            ensure_directory_exists(slots.vtf_output_path)
            vtf_file_path = slots.vtf_output_path / vtf_filename
            if _orig_red:
                with open(vtf_file_path, "wb") as _f:
                    _f.write(_orig_red)
                slots.game_copies.add(texture_filename.lower())
                logger.info(f"Оригинальная RED VTF из игры: {vtf_filename}")
                # Normal Map без своей текстуры - рельеф из игровой: превью
                # его показывает, и мод без него расходился бы с превью
                is_normal_map = _normal_from_game_vtf(
                    _orig_red, texture_filename, original_cdmaterials_path,
                    _game_vmt_name, ctx, slots, tex, _eff)
            else:
                ctx.warn(
                    f"Не найдена игровая текстура '{texture_filename}' - "
                    f"в игре материал может быть фиолетовым. Загрузите свою "
                    f"текстуру в главный слот."
                )
            image_path = None  # VTF уже на месте, не передаём дальше

    if tex.custom_vtf_path:
        # Если юзер сам сделал VTF - просто копируем его, не генерируем из картинки
        vtf_file_path = slots.vtf_output_path / vtf_filename
        ensure_directory_exists(slots.vtf_output_path)
        copy_file_safe(tex.custom_vtf_path, vtf_file_path)
        logger.info(f"Использован пользовательский VTF файл: {tex.custom_vtf_path} -> {vtf_file_path}")
    elif image_path and str(image_path).lower().endswith('.vtf'):
        # В карточку главного материала загрузили готовый VTF -
        # копируем как есть, без PIL-конвертации (иначе «cannot identify image»)
        ensure_directory_exists(slots.vtf_output_path)
        copy_file_safe(image_path, slots.vtf_output_path / vtf_filename)
        logger.info(f"Главная текстура: готовый VTF скопирован → {vtf_filename}")
    # Оригинальный VMT по пути из QC (до патчинга), по ИГРОВОМУ имени
    # (c_sd_cleaver.vmt) - чтобы сохранить родной код материала
    # (phong/прокси); _write_main_vmt переставит $basetexture на
    # texture_filename. Берётся ДО рендера: по нему видно, есть ли у
    # материала родная нормаль, поверх которой ляжет рельеф картинки
    vmt_file = game_source.extract_original_vmt(
        original_cdmaterials_path, _game_vmt_name,
        slots.tf2_textures_vpk, slots.tf2_misc_vpk, ctx.decompile_dir,
    )

    if image_path and not tex.custom_vtf_path \
            and not str(image_path).lower().endswith('.vtf'):
        _ms, _mf, _mfl, _mo = _eff(texture_filename)
        stock = (_stock_normal(texture_filename, vmt_file, slots)
                 if (_mo or {}).get('normal') and tex.stock_normal_ok else None)
        animated_fps, is_normal_map = TextureService.render_image_to_vtf(
            image_path,
            vtf_output_path=slots.vtf_output_path,
            out_vtf_path=slots.vtf_output_path / vtf_filename,
            temp_png_path=vtf_temp_png,
            normal_base=texture_filename,
            size=_ms,
            format_type=_mf,
            flags=_mfl,
            vtf_options=_mo,
            stock_normal=stock,
            jobs=tex.jobs,
        )

    vmt_to_delete = _write_main_vmt(
        vmt_file, slots.vmt_path, texture_filename, slots.patched_cdmaterials_path,
        mode, hat_apply_game_paints, animated_fps, is_normal_map,
    )
    return image_path, animated_fps, is_normal_map, vmt_to_delete


def _write_main_vmt(
    vmt_file: Optional[str],
    vmt_path,
    texture_filename: str,
    patched_cdmaterials_path: str,
    mode: str,
    hat_apply_game_paints: bool,
    animated_fps: Optional[float],
    is_normal_map: bool,
) -> Optional[str]:
    """
    Записывает главный VMT текстуры и возвращает vmt_to_delete
    (имя отредактированного VMT, который надо убрать из tools/edited_vmt
    после сборки), либо None

    Приоритет источника: отредактированный пользователем VMT -> извлечённый
    из игры -> шаблон по $cdmaterials. Затем: снятие красок (шапки),
    анимация ($basetexture) и $bumpmap (normal-map)
    """
    vmt_to_delete = None
    # Проверяем, есть ли отредактированный VMT файл (приоритет 1 - юзер знает лучше)
    from src.services.edited_vmt_service import EditedVMTService
    edited_vmt_path = EditedVMTService.get_edited_vmt(texture_filename)

    if edited_vmt_path and Path(edited_vmt_path).exists():
        # Используем отредактированный VMT файл (юзер его правил через редактор)
        copy_file_safe(edited_vmt_path, vmt_path)
        # Путь $baseTexture переводится на текстуру мода (правили по
        # игровому пути). Но если человек САМ указал другую текстуру
        # (белая основа эффекта, чужая текстура игры), это выбор, а не
        # устаревший путь: переписанный, он молча терялся
        if game_source.basetexture_chosen(edited_vmt_path, vmt_file):
            logger.info(f"[{texture_filename}] $basetexture выбран в правке - оставлен")
        else:
            VMTService.update_vmt_basetexture_path(
                str(vmt_path), patched_cdmaterials_path, texture_filename)
        logger.info(f"Использован отредактированный VMT файл: {edited_vmt_path} -> {vmt_path}")
        vmt_to_delete = texture_filename
    elif vmt_file and Path(vmt_file).exists():
        # Если VMT файл извлечен, копируем его в нужную директорию и обновляем путь $baseTexture
        # (потому что путь в оригинале может быть другим)
        copy_file_safe(vmt_file, vmt_path)
        VMTService.update_vmt_basetexture_path(str(vmt_path), patched_cdmaterials_path, texture_filename)
        logger.info(f"Скопирован и обновлен извлеченный VMT файл: {vmt_file} -> {vmt_path}")
    else:
        # Если VMT файл не извлечен, создаем из шаблона (базовый VMT, ничего особенного)
        VMTService.create_vmt_template_from_cdmaterials(str(vmt_path), patched_cdmaterials_path, texture_filename)
        logger.info(f"Создан VMT файл из шаблона: {vmt_path}")

    # Для шапок: если пользователь не хочет красок из игры - удаляем прокси красок
    if mode == "hat" and not hat_apply_game_paints:
        VMTService.remove_paint_proxies(str(vmt_path))
        logger.info(f"Удалены прокси красок из VMT файла шапки: {vmt_path}")

    if animated_fps:
        VMTService.enable_animated_basetexture(str(vmt_path), animated_fps)

    # Если normal map включена, обновляем VMT файл для добавления $bumpmap
    # (это нужно для бампмаппинга, иначе нормалмап не загрузится)
    if is_normal_map:
        normal_weapon_key = f"{texture_filename}_normal"
        VMTService.update_vmt_bumpmap_path(str(vmt_path), patched_cdmaterials_path, normal_weapon_key)
        logger.info(f"Обновлен VMT файл для добавления $bumpmap: {normal_weapon_key}")
        if animated_fps:
            # Бамп многокадровый (гифка + normal) - тот же fps, что у базы
            VMTService.enable_animated_bumpmap(str(vmt_path), animated_fps)
    return vmt_to_delete


def _normal_from_game_vtf(vtf_bytes: bytes, texture_filename: str,
                          original_cdmaterials_path, game_vmt_name,
                          ctx, slots, tex, _eff) -> bool:
    """Нормаль из игровой текстуры материала, если галка Normal Map стоит"""
    from PIL import Image
    from src.services import normal_map

    size, fmt, _flags, options = _eff(texture_filename)
    if not (options or {}).get('normal'):
        return False
    rgba = normal_map.rgba_from_vtf(vtf_bytes)
    if rgba is None:
        return False
    png = slots.vtf_output_path / f"{texture_filename}_normal_src.png"
    try:
        Image.fromarray(rgba, 'RGBA').convert('RGB').resize(tuple(size), Image.LANCZOS).save(png)
        vmt_file = game_source.extract_original_vmt(
            original_cdmaterials_path, game_vmt_name,
            slots.tf2_textures_vpk, slots.tf2_misc_vpk, ctx.decompile_dir)
        stock = (_stock_normal(texture_filename, vmt_file, slots)
                 if tex.stock_normal_ok else None)
        return TextureService.write_normal_vtf(
            png, slots.vtf_output_path, texture_filename, fmt, options, stock) is not None
    except Exception as exc:                          # noqa: BLE001
        logger.warning(f"[{texture_filename}] нормаль из игровой текстуры не вышла: {exc}")
        return False
    finally:
        if png.exists():
            png.unlink()


def _stock_normal(texture_filename: str, vmt_file, slots):
    """Родная нормаль материала (RGBA) - по VMT, который уйдёт в мод

    VMT - тот же, что выберет _write_main_vmt: правка человека, иначе
    игровой. Нет $bumpmap или файла - None
    """
    from src.services import normal_map
    from src.services.edited_vmt_service import EditedVMTService

    source = EditedVMTService.get_edited_vmt(texture_filename)
    if not (source and Path(source).exists()):
        source = vmt_file
    if not (source and Path(source).exists()):
        return None
    try:
        text = Path(source).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    stock = normal_map.stock_normal(text, [slots.tf2_textures_vpk, slots.tf2_misc_vpk])
    if stock is not None:
        logger.info(f"[{texture_filename}] рельеф ляжет поверх родной нормали")
    return stock


def maybe_build_blu_team_texture(
    weapon_key, blu_row, blu_is_team, blu_mode, blu_image_path,
    vtf_filename, texture_filename, slots, tex, red_row=None,
) -> None:
    """
    Создаёт {texture}_blue (командную раскраску) ТОЛЬКО если у предмета есть
    настоящая команда (blu_is_team) и он не одиночно-текстурный. У вариант-онли
    оружия (обычный+австралий) команды нет - иначе появился бы лишний c_xxx_blue

    Синюю пару главной берём из ЕЁ столбца: главной не обязательно нулевой
    (у Quick-Fix первый столбец - общее стекло, корпус второй), и blu_row[0]
    дал бы имя чужого материала
    """
    from src.data.weapon_quirks import NO_BLU_WEAPON_KEYS as _NO_BLU
    # Создаём {texture}_blue ТОЛЬКО если у предмета есть настоящая
    # команда (blu_is_team). У вариант-онли оружия (скаттерган:
    # обычный+австралий) команды нет - иначе появляется лишний
    # c_xxx_blue, который движок даже не использует
    _main_col = next(
        (i for i, name in enumerate(red_row or [])
         if qc_skin_parser.is_shared_column(name, texture_filename)), 0)
    _blu_col0 = blu_row[_main_col] if len(blu_row or []) > _main_col else None
    if weapon_key in _NO_BLU:
        logger.info(f"[{weapon_key}] BLU team texture пропущена (одиночная текстура)")
    elif not blu_is_team:
        logger.info(f"[{weapon_key}] BLU team texture пропущена (нет командной строки в $texturegroup)")
    elif _blu_col0 and qc_skin_parser.is_shared_column(_blu_col0, texture_filename):
        # Команда есть, но меняется НЕ главный материал (Quick-Fix: стекло
        # общее, синеет корпус). Синее имя тогда совпадает с красным, и
        # запись «синей главной» затёрла бы RED-текстуру этим же файлом.
        # Командные столбцы пишет blu_rows.build_blu_row_textures - поколоночно
        logger.info(
            f"[{weapon_key}] BLU главной текстуры не нужен: '{texture_filename}' "
            f"одинаков в обеих командах, синеют другие материалы"
        )
    else:
        # Реальное имя синего материала - из столбца главной (может быть
        # w_grenade_blue при w_grenade_red), иначе дефолт «{texture}_blue»
        build_blu_team_texture(
            blu_mode, blu_image_path, vtf_filename, texture_filename,
            slots, tex, blu_texture_filename=_blu_col0,
        )


def build_blu_team_texture(
    blu_mode: str,
    blu_image_path: Optional[str],
    vtf_filename: str,
    texture_filename: str,
    slots,
    tex,
    blu_texture_filename: Optional[str] = None,
) -> None:
    """
    Создаёт BLU-командную текстуру (и VMT) рядом с RED

    blu_mode == 'same'        -> копия RED VTF;
    иначе при blu_image_path  -> отдельное изображение -> VTF.
    BLU VMT - копия RED VMT с обновлённым $basetexture. Ошибки не критичны
    (мод соберётся и без BLU-варианта)

    blu_texture_filename - РЕАЛЬНОЕ имя синего материала из $texturegroup
    (та же колонка, что у главной). Нужно, т.к. имя может уже нести суффикс
    _red (w_grenade_red -> w_grenade_blue), и «{texture}_blue» дало бы
    неверное w_grenade_red_blue. По умолчанию - «{texture}_blue»

    Примечание: BLU намеренно использует только UI-опции (tex.vtf_options),
    не подмешивая опции из флагов - поведение сохранено как в оригинале
    """
    if not blu_mode or blu_mode in ('none', ''):
        return
    try:
        blu_name = blu_texture_filename or f"{texture_filename}_blue"
        red_vtf_path = slots.vtf_output_path / vtf_filename
        blu_vtf_name = f"{blu_name}.vtf"
        blu_vtf_path = slots.vtf_output_path / blu_vtf_name
        blu_created = False

        if blu_mode == 'same':
            tex.wait_vtfs()
            if red_vtf_path.exists():
                shutil.copy2(red_vtf_path, blu_vtf_path)
                blu_created = True
                logger.info(f"BLU текстура скопирована из RED: {blu_vtf_name}")
        elif blu_image_path and str(blu_image_path).lower().endswith('.vtf'):
            # В BLU-карточку загрузили готовый VTF - копируем как есть
            copy_file_safe(blu_image_path, blu_vtf_path)
            blu_created = blu_vtf_path.exists()
            if blu_created:
                logger.info(f"BLU текстура: готовый VTF скопирован → {blu_vtf_name}")
        elif blu_image_path and os.path.exists(blu_image_path):
            blu_png_tmp = slots.vtf_output_path / f"{blu_name}.png"
            TextureService.process_image(blu_image_path, str(blu_png_tmp), tex.size)
            blu_vtf_flags, _ = TextureService.parse_vtf_flags_and_options(tex.flags or [])
            blu_opts = dict(tex.vtf_options or {})
            blu_opts.pop('normal', None)   # BLU - не normal map
            TextureService.create_vtf(
                str(blu_png_tmp), str(slots.vtf_output_path), tex.format_type, blu_vtf_flags, blu_opts
            )
            if blu_png_tmp.exists():
                blu_png_tmp.unlink()
            blu_created = blu_vtf_path.exists()
            if blu_created:
                logger.info(f"BLU текстура создана: {blu_vtf_name}")

        # BLU VMT - копия RED с обновлённым $basetexture
        if blu_created and slots.vmt_path.exists():
            blu_vmt_path = slots.vtf_output_path / f"{blu_name}.vmt"
            shutil.copy2(slots.vmt_path, blu_vmt_path)
            VMTService.update_vmt_basetexture_path(
                str(blu_vmt_path), slots.patched_cdmaterials_path, blu_name
            )
            logger.info(f"BLU VMT создан: {blu_vmt_path.name}")
    except Exception as _blu_exc:
        logger.warning(
            f"Не удалось создать BLU текстуру (не критично): {_blu_exc}", exc_info=True
        )
