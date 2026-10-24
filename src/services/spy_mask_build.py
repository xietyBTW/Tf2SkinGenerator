"""
Мод с масками маскировки шпиона: только VTF+VMT по игровому пути
materials/models/player/spy/, без декомпиляции и компиляции модели
"""

import os

from src.data.player_characters import SPY_DISGUISE_MASKS
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.logging_config import get_logger
from .packaging_service import PackagingService
from .texture_service import TextureService
from .tf2_paths import TF2Paths
from .texture_build import game_source

logger = get_logger(__name__)


def build_spy_masks_vpk(
    ctx,
    image_path,
    size,
    format_type,
    flags,
    vtf_options,
    filename,
    export_folder,
    language,
    extra_texture_callback,
    tf2_root_dir,
    keep_temp_on_error,
    debug_mode,
    t,
):
    """
    Строит VPK-мод с кастомными масками маскировки шпиона

    В отличие от player skin, здесь НЕТ деcompile/patch/compile - только
    VTF+VMT файлы по оригинальному пути materials/models/player/spy/.
    Это гарантирует что body-текстуры шпиона остаются из игры
    """
    try:
        # Папка для текстур масок внутри vpkroot
        masks_dir = ctx.vpkroot_dir / "materials" / "models" / "player" / "spy"
        ensure_directory_exists(masks_dir)

        tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
        try:
            _, tf2_misc_vpk_path, _ = TF2Paths.resolve(tf2_root_dir)
        except Exception:
            tf2_misc_vpk_path = None

        # Оригинальный cdmaterials - нужен для VMT $basetexture
        spy_cdmat = "models/player/spy"

        any_created = False

        for cls_key, vtf_name, name_en, name_ru, btn in SPY_DISGUISE_MASKS:
            mask_vtf_path = masks_dir / f"{vtf_name}.vtf"
            mask_vmt_path = masks_dir / f"{vtf_name}.vmt"

            # Спрашиваем пользователя через стандартный callback
            mask_img = extra_texture_callback(vtf_name, "spy") if extra_texture_callback else None

            if mask_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                # Берём оригинал из VPK
                orig = game_source.get_original_vtf_bytes(
                    vtf_name, [spy_cdmat],
                    tf2_textures_vpk, tf2_misc_vpk_path, log_not_found=False
                )
                if orig:
                    with open(mask_vtf_path, "wb") as f:
                        f.write(orig)
                    logger.info(f"Маска из VPK: {vtf_name}.vtf")
                else:
                    logger.debug(f"Маска не найдена в VPK, пропускаем: {vtf_name}")
                    continue
            elif mask_img and str(mask_img).lower().endswith('.vtf'):
                # В карточку маски загрузили готовый VTF - копируем как есть
                copy_file_safe(mask_img, mask_vtf_path)
                logger.info(f"Маска: готовый VTF скопирован → {vtf_name}.vtf")
            elif mask_img and os.path.isfile(mask_img):
                # Конвертируем изображение пользователя.
                # ВАЖНО: имя PNG должно совпадать с именем VTF (без _tmp),
                # иначе create_vtf создаст файл с неправильным именем
                tmp_png = masks_dir / f"{vtf_name}.png"
                TextureService.process_image(mask_img, tmp_png, size)
                vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                TextureService.create_vtf(str(tmp_png), str(masks_dir), format_type, vtf_flags, merged)
                if tmp_png.exists():
                    tmp_png.unlink()
                logger.info(f"Создан VTF маски: {vtf_name}.vtf")
            else:
                # Пользователь пропустил - не включаем
                logger.debug(f"Маска пропущена: {vtf_name}")
                continue

            # VMT - простой VertexLitGeneric по оригинальному пути
            if mask_vtf_path.exists():
                vmt_content = (
                    '"VertexLitGeneric"\n'
                    '{\n'
                    f'\t"$basetexture" "{spy_cdmat}/{vtf_name}"\n'
                    '}\n'
                )
                with open(mask_vmt_path, 'w', encoding='utf-8') as f:
                    f.write(vmt_content)
                logger.info(f"Создан VMT маски: {vtf_name}.vmt")
                any_created = True

        if not any_created:
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, t.get('error_no_textures', 'No mask textures were provided.')

        # Пакуем VPK
        vpk_path = PackagingService.create_vpk_file(ctx, filename, export_folder, language)
        ctx.cleanup(on_error=False, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
        logger.info(f"VPK масок шпиона готов: {vpk_path}")
        return True, vpk_path

    except Exception as exc:
        logger.error(f"build_spy_masks_vpk: {exc}", exc_info=True)
        if ctx:
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
        return False, str(exc)
