"""
Стадия «текстуры 2D-панели»: вторичные текстуры после главной и BLU -
свои картинки материалов из альбома, карты, варианты стилей, части
"""

import os
from pathlib import Path
from typing import List, Tuple

from src.services import qc_skin_parser
from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.file_utils import copy_file_safe, ensure_directory_exists
from src.shared.logging_config import get_logger

from . import fixed_extras
from . import game_source
from . import material_maps as mat_maps
from . import part_textures

logger = get_logger(__name__)


def build_secondary_textures(
    weapon_key, panel_extra_textures, ctx, slots, tex,
    material_maps, texture_filename, image_path, is_normal_map,
    has_skins, skin_build_data, _eff,
    part_variants=None, part_specs=None, blu_of=None, strip_paints=False,
) -> None:
    """
    Вторичные текстуры после главной+BLU: фиксированные доп. текстуры/файлы,
    текстуры из 2D-панели (материалы SMD вне skinfamilies), пер-текстурные
    файловые карты (detail/selfillum/phong) и VTF/VMT вариантов стилей. Порядок
    важен: карты ложатся в VMT после того, как все VMT материалов созданы

    Материалы частей (`part_variants`, src/services/part_materials.py) -
    последними: их VMT (с игровых VMT строк скина), затем их свои картинки
    по командам и их карты (`blu_of` - синий материал для исходного,
    `strip_paints` - снять краски шапки, как у главного VMT)
    """
    fixed_handled = fixed_extras.build_fixed_extra_textures(
        weapon_key, panel_extra_textures, ctx, tex.size,
        tex.format_type, tex.flags, tex.vtf_options,
    )

    # Экран часов (.res и info.vdf) - только если циферблат меняли
    fixed_extras.write_watch_screen(weapon_key, ctx, fixed_handled)

    # Картинки и карты частей, чей материал сборка пропустила (модель не
    # та), в мод не идут вовсе: их VMT некому показать. Родной материал,
    # получивший части (`existing`), - не материал части: его карты свои
    parts = {str(s['name']).lower() for s in part_specs or () if not s.get('existing')}

    def split(store):
        store = store or {}
        return ({k: v for k, v in store.items() if k.lower() not in parts},
                {k: v for k, v in store.items() if k.lower() in parts})

    # Картинки частей сюда не приходят (едут в спеках частей), карты -
    # приходят: им нужен VMT части, а он пишется ниже
    extras, _ = split(panel_extra_textures)
    maps, part_maps = split(material_maps)

    render_panel_extras(extras, fixed_handled, ctx, slots, _eff)

    # Пер-текстурные файловые карты (detail/selfillum/phong/warp)
    # Теперь VMT всех материалов (главный + доп. + BLU) созданы, поэтому
    # карты каждого материала ложатся в его собственный VMT.
    # Родные нормали - из мода (что уже собрано) и из игры
    read_texture = game_source.texture_reader(
        ctx.vpkroot_dir, [slots.tf2_textures_vpk, slots.tf2_misc_vpk])

    def build_maps(store, bases):
        mat_maps.build_material_maps(
            store, slots.vtf_output_path, texture_filename, slots.vmt_path,
            slots.patched_cdmaterials_path, tex.size,
            base_image_path=image_path, is_normal_map=is_normal_map,
            panel_extra_textures=bases, read_texture=read_texture,
        )

    build_maps(maps, extras)
    if has_skins:
        _style_variants(skin_build_data, slots, tex)
    if part_variants:
        _part_textures(part_variants, part_specs, part_maps, fixed_handled,
                       ctx, slots, _eff, blu_of, strip_paints, build_maps)


def _style_variants(skin_build_data, slots, tex) -> None:
    """
    VTF/VMT вариантов стилей (skinfamilies): для каждой переопределённой
    текстуры доп-стиля (напр. lefteye_bloody) - VTF + VMT рядом с базовыми.
    Имена совпадают с теми, что выписаны в инъектированный $texturegroup.
    Варианты независимы между собой -> рендер параллельный
    """
    jobs = [
        (name, img, tex.size, tex.format_type, tex.flags, tex.vtf_options)
        for name, img in skin_build_data.get('variant_files', {}).items()
    ]
    run_extra_render_jobs(
        jobs, slots.vtf_output_path, slots.vmt_path, slots.patched_cdmaterials_path,
        "[SKIN BUILD] вариант",
    )


def _part_textures(part_variants, part_specs, part_maps, fixed_handled,
                   ctx, slots, _eff, blu_of, strip_paints, build_maps) -> None:
    """Материалы частей: VMT, свои картинки по командам, затем их карты"""
    applied = {str(n).lower() for n in part_variants}
    part_maps = {k: v for k, v in part_maps.items() if k.lower() in applied}
    renders = part_textures.write_part_materials(
        part_variants, part_specs, ctx, slots, blu_of, strip_paints)
    # Настройки VTF - материала части, а не имени строки (`_blue`)
    owner = {row: who for row, (_, who) in renders.items()}
    render_panel_extras(
        {row: image for row, (image, _) in renders.items()}, fixed_handled,
        ctx, slots, lambda name: _eff(owner.get(name, name)))
    # VMT уже смотрит на эту VTF: не вышла (длинный путь, битая картинка) -
    # в игре материал фиолетовый, молчать нельзя
    for row in renders:
        if not slots.vtf(row).exists():
            ctx.warn(f"Текстура материала части «{row}» не создана: в игре он будет без неё")
    # Основа карт «из текстуры» - своя картинка части или игровая
    # текстура исходного (`map_base`)
    build_maps(part_maps, {str(s['name']).lower(): s['map_base']
                           for s in part_specs if s.get('map_base')})


def render_panel_extras(extras: dict, fixed_handled, ctx, slots, _eff) -> None:
    """Свои картинки материалов из альбома: {имя}.vtf и, если VMT ещё
    нет, {имя}.vmt рядом с главным"""
    if not extras:
        return
    # Собираем уже созданные имена (extra_materials + BLU)
    _processed = {_f.stem for _f in slots.vtf_output_path.glob("*.vtf")}

    # Своя текстура австралия: VMT - игровой VMT золота, а не главного,
    # иначе пропадают кубмапа и блеск. Кладём его заранее: рендер ниже
    # VMT не перезаписывает, а $basetexture уже смотрит на наш VTF.
    # Правленый в редакторе VMT важнее - его рендер возьмёт сам
    from src.services.edited_vmt_service import EditedVMTService
    for _pet_name in extras:
        if not qc_skin_parser.is_australium(_pet_name or ''):
            continue
        _edited = EditedVMTService.get_edited_vmt(_pet_name.lower())
        if _edited and os.path.exists(_edited):
            continue
        _v_vmt = slots.vmt(_pet_name.lower())   # как у рендера ниже
        _orig = game_source.find_original_vmt(_pet_name, ctx, slots)
        if _orig and not _v_vmt.exists():
            copy_file_safe(_orig, _v_vmt)
            VMTService.update_vmt_basetexture_path(
                str(_v_vmt), slots.patched_cdmaterials_path, _pet_name.lower())
            logger.info(f"Вариант '{_pet_name}': игровой VMT со своей текстурой")

    # Каждый panel-extra независим (своё имя -> свои файлы, без callback и
    # без чтения игрового VPK) -> рендерим параллельно. Скип-логику и
    # пер-текстурные настройки (_eff) считаем серийно при сборе задач
    from src.services.part_materials import model_name
    _pet_jobs = []
    for _pet_name, _pet_img in extras.items():
        if _pet_name in fixed_handled:
            continue   # уже записан по фиксированному пути
        # Защита от UI-sentinel: '__single__' - главная текстура,
        # а не имя материала. Если протёк - пропускаем, иначе
        # в VPK появятся мусорные __single__.vmt / __single__.vtf
        if not _pet_name or _pet_name.startswith('__'):
            continue
        # Имя - как в модели: studiomdl собирает материал в нижнем
        # регистре и без точек («Material.001» из Blender -> material_001).
        # Под сырым именем файлы ложились мимо модели: у главного -
        # лишним дублем текстуры, у второго материала - фиолетовой шашкой
        _file = model_name(_pet_name)
        if _file in _processed:
            continue   # уже создан через skinfamilies
        _processed.add(_file)
        # Настройки VTF - по карточке, как их задали
        _es, _ef, _efl, _eo = _eff(_pet_name)
        _pet_jobs.append((_file, _pet_img, _es, _ef, _efl, _eo))

    run_extra_render_jobs(
        _pet_jobs, slots.vtf_output_path, slots.vmt_path, slots.patched_cdmaterials_path,
        "Panel extra texture",
    )


def run_extra_render_jobs(
    jobs, vtf_output_path, vmt_path, patched_cdmaterials_path, log_prefix,
) -> None:
    """Параллельно рендерит независимые доп. текстуры (panel-extra / варианты стилей)

    jobs: список ``(name, img, size, format_type, flags, vtf_options)``. Каждая
    задача пишет свои ``{name}.vtf/.vmt`` - без shared-файлов, без чтения игрового
    VPK и без UI-callback, поэтому безопасна в пуле потоков. Сжатие VTF
    отпускает GIL, так что параллелизм реально ускоряет многоматериальные и
    многостилевые сборки. Результаты логируются, функция ничего не возвращает
    """
    if not jobs:
        return
    import concurrent.futures as _cf

    def _one(job):
        name, img, _size, _fmt, _flags, _opts = job
        try:
            ok = render_extra_texture(
                name, img, vtf_output_path, vmt_path,
                patched_cdmaterials_path, _size, _fmt, _flags, _opts,
            )
            return name, ok, None
        except Exception as exc:
            return name, False, exc

    max_workers = min(len(jobs), (os.cpu_count() or 4))
    with _cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vtf") as ex:
        results = list(ex.map(_one, jobs))

    for name, ok, err in results:
        if err is not None:
            logger.warning(f"{log_prefix} '{name}' - ошибка: {err}", exc_info=False)
        elif ok:
            logger.info(f"{log_prefix}: {name}.vtf/vmt")
        else:
            logger.warning(f"{log_prefix} нет файла '{name}'")


def render_extra_texture(
    name: str,
    img: str,
    vtf_output_path: Path,
    vmt_path: Path,
    patched_cdmaterials_path: str,
    size: Tuple[int, int],
    format_type: str,
    flags: List[str],
    vtf_options: dict,
) -> bool:
    """
    Универсальный рендер доп. текстуры в VPK: {name}.vtf + {name}.vmt
    рядом с базовой текстурой

    Источник:
      • .vtf      -> копируется как есть (без переконвертации);
      • анимация  -> анимированный VTF (+ AnimatedTexture-прокси в VMT);
      • картинка  -> ресайз + обычный VTF.
    VMT строится на основе главного (vmt_path) с $basetexture -> name

    Возвращает True, если текстура создана; False - если img пуст/не файл.
    Единая точка для panel_extra_textures и вариантов стилей (skinfamilies)
    """
    if not img or not os.path.isfile(img):
        return False

    # Имя в нижний регистр: Source ищет материалы/текстуры в lowercase,
    # а лукап в VPK регистрозависим - иначе текстура не находится (фиолетовая)
    name = name.lower()

    ensure_directory_exists(vtf_output_path)
    out_vtf = vtf_output_path / f"{name}.vtf"
    out_vmt = vtf_output_path / f"{name}.vmt"

    fps = None
    if str(img).lower().endswith('.vtf'):
        copy_file_safe(img, out_vtf)
    else:
        # Доп. материалы не бывают normal-map -> снимаем 'normal'; единый рендер
        # (анимация / обычная картинка) через TextureService.render_image_to_vtf
        opts = dict(vtf_options) if vtf_options else {}
        opts.pop("normal", None)
        fps, _ = TextureService.render_image_to_vtf(
            img,
            vtf_output_path=vtf_output_path,
            out_vtf_path=out_vtf,
            temp_png_path=vtf_output_path / f"{name}.png",
            normal_base="",
            size=size,
            format_type=format_type,
            flags=flags,
            vtf_options=opts,
        )

    if not out_vmt.exists():
        # Пер-материальный отредактированный VMT (если пользователь правил его
        # для этого материала) - копируем его, затем чиним путь $basetexture
        # под наш VTF/пропатченный cdmaterials. Иначе - обычная генерация
        from src.services.edited_vmt_service import EditedVMTService
        _edited = EditedVMTService.get_edited_vmt(name)
        if _edited and os.path.exists(_edited):
            copy_file_safe(_edited, out_vmt)
            VMTService.update_vmt_basetexture_path(
                str(out_vmt), patched_cdmaterials_path, name)
            logger.info(f"Доп.материал '{name}': использован отредактированный VMT")
        else:
            game_source.write_material_vmt(out_vmt, vmt_path, patched_cdmaterials_path, name)
    if fps:
        VMTService.enable_animated_basetexture(str(out_vmt), fps)
    return True
