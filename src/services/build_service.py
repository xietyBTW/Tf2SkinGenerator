import os
from typing import List, Optional, Tuple
from src.services.vmt_service import VMTService
from src.services.texture_service import TextureService
from src.shared.constants import DirectoryPaths
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class BuildService:
    @staticmethod
    def build_special_mode_vpk(
        ctx,
        mode: str,
        image_path: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict = None,
        keep_temp_on_error: bool = False,
        debug_mode: bool = False,
        language: str = "en",
        custom_vtf_path: str = None
    ) -> Tuple[bool, str, Optional[str]]:
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        try:
            rel_path, vmt_filename, vtf_filename = VMTService.get_weapon_relpaths(mode)
            vtf_output_path = ctx.vpkroot_dir / rel_path
            vmt_path = vtf_output_path / vmt_filename
            vtf_temp_png = vtf_output_path / vtf_filename.replace(".vtf", ".png")
            vtf_filename_for_mode = vmt_filename.replace('.vmt', '.vtf')
            is_normal_map = False
            animated_fps = None
            try:
                ensure_directory_exists(vtf_output_path)
            except OSError as e:
                if "path too long" in str(e).lower():
                    logger.error(f"Путь слишком длинный для режима {mode}")
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_path_too_long'].format(mode=mode), None
                raise
            if custom_vtf_path:
                vtf_file_path = vtf_output_path / vtf_filename_for_mode
                ensure_directory_exists(vtf_output_path)
                copy_file_safe(custom_vtf_path, vtf_file_path)
                logger.info(f"Использован пользовательский VTF файл для специального режима: {custom_vtf_path} -> {vtf_file_path}")
            else:
                animated_fps, is_normal_map = TextureService.render_image_to_vtf(
                    image_path,
                    vtf_output_path=vtf_output_path,
                    out_vtf_path=vtf_output_path / vtf_filename_for_mode,
                    temp_png_path=vtf_temp_png,
                    normal_base=vmt_filename.replace('.vmt', ''),
                    size=size,
                    format_type=format_type,
                    flags=flags,
                    vtf_options=vtf_options,
                )
            from src.services.edited_vmt_service import EditedVMTService
            vmt_filename_without_ext = os.path.splitext(vmt_filename)[0]
            edited_vmt_path = EditedVMTService.get_edited_vmt(vmt_filename_without_ext)
            vmt_to_delete = None
            if mode == "critHIT":
                mod_data_base = DirectoryPaths.MOD_DATA_DIR
            else:
                mod_data_base = DirectoryPaths.MOD_DATA_DIR / mode
            mod_data_vmt_path = mod_data_base / vmt_filename
            if edited_vmt_path and os.path.exists(edited_vmt_path):
                copy_file_safe(edited_vmt_path, vmt_path)
                logger.info(f"Использован отредактированный VMT файл для специального режима: {edited_vmt_path} -> {vmt_path}")
                vmt_to_delete = vmt_filename_without_ext
            elif mod_data_vmt_path.exists():
                copy_file_safe(mod_data_vmt_path, vmt_path)
                logger.info(f"Использован VMT файл из mod_data: {mod_data_vmt_path} -> {vmt_path}")
            else:
                class_name = mode.split('_')[0].capitalize() if '_' in mode else "Unknown"
                weapon_type = "Primary"
                VMTService.create_vmt_template(str(vmt_path), mode, class_name, weapon_type)
                logger.info(f"Создан VMT файл из шаблона: {vmt_path}")
            if animated_fps:
                VMTService.enable_animated_basetexture(str(vmt_path), animated_fps)
            if is_normal_map:
                normal_texture_filename = vmt_filename.replace('.vmt', '_normal')
                normal_cdmaterials_path = rel_path.replace('materials/', '').rstrip('/')
                VMTService.update_vmt_bumpmap_path(str(vmt_path), normal_cdmaterials_path, normal_texture_filename)
                logger.info(f"Обновлен VMT файл для добавления $bumpmap: {normal_texture_filename}")
            if mode == "critHIT":
                pcf_filename = "crit.pcf"
                mod_data_pcf_path = mod_data_base / pcf_filename
                if mod_data_pcf_path.exists():
                    pcf_output_path = ctx.vpkroot_dir / "particles"
                    ensure_directory_exists(pcf_output_path)
                    pcf_dest_path = pcf_output_path / pcf_filename
                    copy_file_safe(mod_data_pcf_path, pcf_dest_path)
                    logger.info(f"Скопирован PCF файл: {mod_data_pcf_path} -> {pcf_dest_path}")
                else:
                    logger.warning(f"PCF файл не найден: {mod_data_pcf_path}")
            success_msg = t.get('special_mode_success', 'Special mode textures created successfully')
            return True, success_msg, vmt_to_delete
        except Exception as e:
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, t['error_special_mode_vpk'].format(error=str(e)), None
