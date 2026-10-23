"""
Стадия «доп. материалы»: столбцы $texturegroup кроме главного, «Прочее»
(убер/зомби-варианты), служебные/ЧС материалы оригиналом, изолированные
плечи рук и материалы, следующие за общей текстурой
"""

import os
from pathlib import Path
from typing import Optional

from src.services import qc_skin_parser
from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL, EXTRA_TEX_USE_MAIN
from src.shared.file_utils import copy_file_safe
from src.shared.logging_config import get_logger

from . import game_source

logger = get_logger(__name__)


def build_extra_material_textures(
    extra_materials, weapon_key, ctx, slots, tex,
    extra_texture_callback, animated_fps,
    tg_rows=None, deferred: Optional[list] = None, strip_paints: bool = False,
) -> dict:
    """
    Создаёт VTF+VMT для доп. материалов модели (столбцы 1+ RED-строки
    $texturegroup: shell, scope и т.п.). На каждый материал спрашивает
    текстуру через callback, либо берёт оригинал из игры, либо пропускает

    tg_rows - строки $texturegroup: по ним «Скопировать главную» у
    варианта из «Прочего» находит его пару (qc_skin_parser.variant_base).
    Пару, которой ещё нет, вариант ждёт в `deferred` (finish_variant_copies).
    strip_paints - шапка без «Красок из игры» (см. game_source.apply_edited_vmt)

    Returns:
        {material_name: vtf_path} - для последующего копирования в BLU
    """
    from src.data.material_filter import is_editable_material
    vtf_paths = {}

    # Сколько ещё спросим после этого. Число едет в вопрос: предлагать
    # «и так для остальных», когда остальных нет, - врать человеку.
    # Считается только здесь: остальные вызовы callback условные (BLU,
    # главный материал), и обещать по ним нечего
    for asked, name in enumerate(extra_materials):
        logger.info(f"Создаем текстуры для дополнительного материала: {name}")
        # Спрашиваем пользователя - нужна ли отдельная текстура для этого материала
        img = extra_texture_callback(
            name, weapon_key, len(extra_materials) - asked - 1) if extra_texture_callback else None
        # Родной VMT материала: у «из игры» из него берётся $basetexture,
        # у служебного (убер/зомби) - ещё и шейдер с $alphatest/прокси,
        # которых в главном VMT нет
        orig_vmt = game_source.find_original_vmt(name, ctx, slots)
        editable = is_editable_material(name)
        # Частота анимации VMT: своей картинки, иначе пары варианта, иначе главной
        fps = animated_fps
        if img == EXTRA_TEX_USE_GAME_ORIGINAL:
            if _from_game(name, orig_vmt, editable, slots, ctx, strip_paints, vtf_paths):
                continue
            # Совсем ничего - НЕ подменяем текстурой тела
            img = None
        elif img == EXTRA_TEX_USE_MAIN:
            if tex is not None:
                tex.wait_vtfs()
            handled, fps = _copy_main(name, orig_vmt, editable, tg_rows, deferred,
                                      slots, ctx, strip_paints, animated_fps)
            if handled:
                continue
            img = None

        if img and not os.path.isfile(img):
            logger.warning(f"Файл не найден: {img}")
            img = None
        if img:
            # Пользователь предоставил отдельное изображение для этого материала
            logger.info(f"Используем отдельное изображение для {name}: {img}")
            fps = _render_own_image(name, img, slots, tex)
        elif not slots.vtf(name).exists():
            # В мод попадает ТОЛЬКО то, что пользователь явно загрузил
            # или выбрал «использовать из игры». Всё остальное движок
            # найдёт через другие $cdmaterials пути - не добавляем
            logger.debug(f"Доп. материал пропускается (нет изображения): {name}")
            continue

        vtf_paths[name] = slots.vtf(name)
        # VMT для дополнительного материала: у обычных (гильза, прицел) -
        # по образцу главного, у служебных из «Прочего» - родной, иначе
        # зомби-кожа потеряет $alphatest и дыры зальются текстурой
        base = Path(orig_vmt) if (orig_vmt and not editable) else slots.vmt_path
        game_source.write_material_vmt(slots.vmt(name), base, slots.patched_cdmaterials_path, name)
        game_source.apply_edited_vmt(name, slots.vmt(name), orig_vmt, slots, True, strip_paints)
        if fps:
            VMTService.enable_animated_basetexture(str(slots.vmt(name)), fps)
    return vtf_paths


def _from_game(name, orig_vmt, editable, slots, ctx, strip_paints, vtf_paths) -> bool:
    """
    «Использовать из игры». Поиск VTF по ИМЕНИ МАТЕРИАЛА ненадёжен: у головы/
    варианта имя VTF ≠ имя материала (demoman_head_red -> $basetexture
    "models/player/demo/demoman_head"), и старый fallback подставлял текстуру
    ТЕЛА (главную) - отсюда «голова с текстурой тела». Поэтому VTF ищется по
    $basetexture родного VMT

    Returns:
        True - материал записан (VTF+VMT или один VMT); False - в игре ничего
    """
    vmt_path = slots.vmt(name)
    if orig_vmt and not editable:
        # Служебный из «Прочего» оставили игровым: родного VMT
        # достаточно - его $basetexture смотрит в игру, а копия VTF
        # была бы мёртвым весом (у зомби-кожи это по 700 КБ на штуку).
        # Обычным доп. материалам VTF нужен: с него BLU-цикл снимает
        # RED-вариант, когда синего в игре нет
        write_variant_original(vmt_path, orig_vmt, name, slots, ctx, strip_paints)
        return True
    logger.info(f"Извлекаем оригинал из игры для: {name}")
    game_vtf = None
    bt = game_source.read_vmt_basetexture(orig_vmt) if orig_vmt else None
    if bt:
        bt_dir, bt_name = os.path.split(bt.replace('\\', '/').strip().strip('/'))
        game_vtf = game_source.get_original_vtf_bytes(
            bt_name,
            ([bt_dir] if bt_dir else []) + list(slots.original_cdmaterials_paths or []),
            slots.tf2_textures_vpk, slots.tf2_misc_vpk,
            log_not_found=False,
        )
    if game_vtf is None:
        game_vtf = game_source.get_original_vtf_bytes(
            name, slots.original_cdmaterials_paths,
            slots.tf2_textures_vpk, slots.tf2_misc_vpk,
            log_not_found=False,
        )
    if game_vtf:
        # Пишем самодостаточно (VTF + VMT) - тогда и BLU-цикл скопирует
        # RED-вариант
        with open(slots.vtf(name), "wb") as f:
            f.write(game_vtf)
        slots.game_copies.add(name.lower())
        # VMT: родной (сохраняет шейдер/детейл) с $basetexture,
        # перенаправленным на наш console-VTF
        base = Path(orig_vmt) if orig_vmt else slots.vmt_path
        game_source.write_material_vmt(vmt_path, base, slots.patched_cdmaterials_path, name)
        game_source.apply_edited_vmt(name, vmt_path, orig_vmt, slots, True, strip_paints)
        vtf_paths[name] = slots.vtf(name)
        logger.info(f"Оригинал из игры: {name} (VTF+VMT)")
        return True
    if orig_vmt:
        # Текстуру не нашли (глаза/зомби - абсолютные shared
        # пути): копируем VMT как есть, ссылки сами найдут
        write_variant_original(vmt_path, orig_vmt, name, slots, ctx, strip_paints)
        return True
    return False


def _copy_main(name, orig_vmt, editable, tg_rows, deferred, slots, ctx,
               strip_paints, animated_fps):
    """
    «Скопировать главную»: тот же VTF, что у основного материала

    Returns:
        (записан ли материал целиком, частота анимации его VMT)
    """
    main_vtf = slots.vmt_path.with_suffix('.vtf')
    fps = animated_fps
    if not editable:
        # Убер/зомби из «Прочего»: «главная» для него - материал,
        # чьё место он занимает в скине (у головы - голова, у
        # синего - синий). Текстура тела на голове в убере была
        # кашей, а глазам копировать нечего: они игровые. Пара
        # осталась игровой - вариант тоже игровой
        pair = qc_skin_parser.variant_base(tg_rows or [], name)
        if pair and deferred is not None and not slots.vtf(pair).exists():
            # Пару ещё не собрали (синюю пишет BLU-цикл позже)
            deferred.append((name, pair))
            return True, None
        main_vtf = slots.own_vtf(pair) if pair else None
        if main_vtf is None:
            write_variant_original(slots.vmt(name), orig_vmt, name, slots, ctx, strip_paints)
            return True, None
        # Анимированная пара листается и в варианте - со своей частотой
        fps = game_source.basetexture_fps(slots.vmt(pair))
    if main_vtf.exists():
        copy_file_safe(main_vtf, slots.vtf(name))
        logger.info(f"Копия главной текстуры: {name}.vtf ← {main_vtf.name}")
    return False, fps


def _render_own_image(name, img, slots, tex):
    """Своя картинка доп. материала -> его VTF с настройками его карточки
    (разрешение, формат, флаги). Возвращает частоту анимации или None"""
    mtex = tex.for_material(name)
    out_vtf = slots.vtf(name)
    if mtex.custom_vtf_path or img.lower().endswith('.vtf'):
        # Пользователь загрузил готовый VTF (глобально или в эту
        # карточку) - копируем как есть, без переконвертации
        copy_file_safe(img, out_vtf)
        return None
    # drop_normal: доп. материалы normal map не получают (иначе бамп уехал
    # бы в базовую текстуру)
    flags, merged = TextureService.resolve_vtf_flags_and_options(
        mtex.flags, mtex.vtf_options, drop_normal=True)
    if TextureService.is_animated_image(img):
        return TextureService.create_animated_vtf(
            img, str(out_vtf), mtex.size, mtex.format_type, flags, merged)
    mtex.image_to_vtf(img, f"{name}.png", flags, merged)
    return None


def write_variant_original(vmt_path, orig_vmt, name, slots=None, ctx=None,
                            strip_paints: bool = False) -> None:
    """Служебный вариант (убер/зомби) игровым: его родной VMT смотрит на
    игровую текстуру, и своей копии VTF не нужно. Родного VMT нет -
    пишем, как служебные без карточек (write_blacklisted_materials):
    материал под console-путём обязан быть, иначе он фиолетовый"""
    if orig_vmt:
        copy_file_safe(orig_vmt, vmt_path)
        logger.info(f"Оригинал из игры (только VMT): {name}")
    elif slots is not None and ctx is not None:
        write_blacklisted_materials([name], {}, ctx, slots)
    if slots is not None:
        game_source.apply_edited_vmt(
            name, vmt_path, orig_vmt, slots, False, strip_paints)


def finish_variant_copies(deferred, ctx, slots, strip_paints: bool = False) -> None:
    """«Скопировать главную» у вариантов, чья пара собирается позже их
    (синяя - в BLU-цикле): копия её VTF под родным VMT варианта. Пара
    осталась игровой (нет своей картинки) - вариант тоже игровой"""
    for name, pair in deferred or ():
        orig = game_source.find_original_vmt(name, ctx, slots)
        source = slots.own_vtf(pair)
        if source is None:
            write_variant_original(
                slots.vmt(name), orig, name, slots, ctx, strip_paints)
            continue
        copy_file_safe(source, slots.vtf(name))
        game_source.write_material_vmt(
            slots.vmt(name), Path(orig) if orig else slots.vmt_path,
            slots.patched_cdmaterials_path, name)
        game_source.apply_edited_vmt(
            name, slots.vmt(name), orig, slots, True, strip_paints)
        # Анимированная пара (гифка) листается и в убере
        fps = game_source.basetexture_fps(slots.vmt(pair))
        if fps:
            VMTService.enable_animated_basetexture(str(slots.vmt(name)), fps)
        logger.info(f"Копия текстуры пары: {name}.vtf ← {source.name}")


def follow_shared_textures(ctx, slots) -> None:
    """
    Служебный материал, который в игре рисуется ТОЙ ЖЕ текстурой, что и
    собранный материал мода, следует за ней

    У хэви руки (hvyweapon_red_sheen) в игре смотрят на текстуру тела
    (hvyweapon_red). Служебный материал уходил в мод игровым VMT, и со
    своей текстурой тела руки оставались стоковыми. Сравниваем $basetexture
    родных VMT: смотрящий в игру VMT служебного материала переводим на VTF
    материала, собранного из картинки человека. Только служебные: у
    материала части синяя строка без своей картинки игровая нарочно
    """
    from src.data.material_filter import is_editable_material

    def norm(path):
        path = (path or '').replace('\\', '/').strip().strip('/').lower()
        path = path[len('materials/'):] if path.startswith('materials/') else path
        return path[:-4] if path.endswith('.vtf') else path

    own = {}
    for vtf in sorted(slots.vtf_output_path.glob('*.vtf')):
        if slots.own_vtf(vtf.stem) is None:
            continue
        orig = game_source.find_original_vmt(vtf.stem, ctx, slots)
        game = norm(game_source.read_vmt_basetexture(orig)) if orig else ''
        if game:
            own.setdefault(game, vtf.stem)
    if not own:
        return
    for vmt in sorted(slots.vtf_output_path.glob('*.vmt')):
        if is_editable_material(vmt.stem) or slots.vtf(vmt.stem).exists():
            continue
        target = own.get(norm(game_source.read_vmt_basetexture(str(vmt))))
        if target:
            VMTService.update_vmt_basetexture_path(
                str(vmt), slots.patched_cdmaterials_path, target)
            logger.info(f"{vmt.stem}: общая с {target} текстура - своя из мода")


def write_blacklisted_materials(
    blacklisted_extra, panel_extra_textures, ctx, slots,
) -> None:
    """
    Пишет ОРИГИНАЛЬНЫЙ VMT (и VTF при наличии) для служебных/ЧС материалов
    (глаза/убер/зомби и т.п.). Из-за console-cdmaterials модель ищет их VMT
    по новому пути - без него материал стал бы фиолетовым. Текстурные ссылки
    у таких VMT абсолютные, поэтому отдельный VTF чаще не нужен
    """
    # Регистр: имена группы после правки QC в нижнем регистре, а ключи
    # панели - как в превью
    _pet_keys = {k.lower() for k in (panel_extra_textures or {})}
    for _bl_mat in blacklisted_extra:
        # Пользователь заменил служебную текстуру через «Прочее» -
        # её запишет блок panel_extra_textures ниже (его правка важнее)
        if _bl_mat.lower() in _pet_keys:
            continue
        _bl_vmt = slots.vmt(_bl_mat)
        if _bl_vmt.exists():
            continue
        try:
            _src_vmt = game_source.find_original_vmt(_bl_mat, ctx, slots)
            if _src_vmt:
                # Родной VMT ссылается на текстуру ИГРОВЫМ путём, и он в
                # игре есть - своя копия VTF была бы мёртвым весом в моде
                # (у тела персонажа это мегабайты на голову и зомби-скины)
                copy_file_safe(_src_vmt, _bl_vmt)
            else:
                # Нет родного VMT - производный от главного.
                # Он смотрит в console-путь, значит текстуру надо положить
                _bl_orig = game_source.get_original_vtf_bytes(
                    _bl_mat, slots.original_cdmaterials_paths,
                    slots.tf2_textures_vpk, slots.tf2_misc_vpk,
                )
                if not _bl_orig:
                    continue   # ни VMT, ни VTF - движковый эффект, пропуск
                game_source.write_material_vmt(
                    _bl_vmt, slots.vmt_path, slots.patched_cdmaterials_path,
                    _bl_mat)
                with open(slots.vtf(_bl_mat), "wb") as _f:
                    _f.write(_bl_orig)
            logger.info(f"Служебный материал записан оригиналом: {_bl_mat}")
        except Exception as _e:
            logger.warning(f"Не удалось записать служебный материал {_bl_mat}: {_e}")


def write_shoulder_iso_materials(shoulder_iso, ctx, slots, tex) -> None:
    """
    Пишет VTF+VMT для изолированных материалов плеч/тела вьюмодели (vm_<orig>)
    под главным console-путём. Источник каждого: пользовательская текстура
    (разрешена при детекте) либо оригинал тела из игры (чтобы плечи не стали
    фиолетовыми). Список готовит material_plan.apply_shoulder_isolation
    """
    for _new_name, _orig_name, _sh_src in shoulder_iso:
        _sh_vtf = slots.vtf(_new_name)
        _sh_vmt = slots.vmt(_new_name)
        # Источник уже разрешён при детекте (карточка/image_path/BLU);
        # без источника - берём оригинал из игры (без лишних диалогов)
        try:
            if _sh_src and os.path.isfile(_sh_src):
                if str(_sh_src).lower().endswith('.vtf'):
                    copy_file_safe(_sh_src, _sh_vtf)
                else:
                    _sh_png = slots.vtf_output_path / f"{_new_name}.png"
                    _mt = tex.for_material(_orig_name)   # настройки карточки плеч
                    TextureService.process_image(_sh_src, _sh_png, _mt.size)
                    _vf, _vo = TextureService.resolve_vtf_flags_and_options(_mt.flags, _mt.vtf_options, drop_normal=True)
                    TextureService.create_vtf(str(_sh_png), str(slots.vtf_output_path), _mt.format_type, _vf, _vo)
                    if _sh_png.exists():
                        _sh_png.unlink()
            else:
                # По умолчанию - оригинальная текстура тела из игры
                # (по ОРИГИНАЛЬНОМУ имени), чтобы плечи не стали фиолетовыми
                _orig_vtf = game_source.get_original_vtf_bytes(
                    _orig_name, slots.original_cdmaterials_paths,
                    slots.tf2_textures_vpk, slots.tf2_misc_vpk
                )
                if _orig_vtf:
                    with open(_sh_vtf, "wb") as _f:
                        _f.write(_orig_vtf)
                else:
                    ctx.warn(
                        f"Не найдена оригинальная текстура плеч '{_orig_name}' - "
                        f"плечи вьюмодели могут быть фиолетовыми."
                    )
                    continue
            game_source.write_material_vmt(
                _sh_vmt, slots.vmt_path, slots.patched_cdmaterials_path, _new_name)
            logger.info(f"[SHOULDER ISO] записан материал плеч: {_new_name}")
        except Exception as _e:
            logger.error(f"[SHOULDER ISO] ошибка записи {_new_name}: {_e}", exc_info=True)
