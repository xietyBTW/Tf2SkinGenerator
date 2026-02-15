import os
import shutil
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
                TextureService.process_image(image_path, vtf_temp_png, size)
                vtf_flags, flags_parsed_options = TextureService.parse_vtf_flags_and_options(flags)
                merged_options = {}
                if vtf_options:
                    merged_options.update(vtf_options)
                merged_options.update(flags_parsed_options)
                is_normal_map = merged_options.get("normal", False)
                if is_normal_map:
                    normal_options = merged_options.copy()
                    normal_options.pop("normal", None)
                    TextureService.create_vtf(str(vtf_temp_png), str(vtf_output_path), format_type, vtf_flags, normal_options)
                    logger.info(f"Создана обычная VTF текстура для специального режима: {vtf_filename_for_mode}")
                    normal_vtf_filename = f"{vmt_filename.replace('.vmt', '')}_normal.vtf"
                    normal_temp_png = vtf_output_path / f"{vmt_filename.replace('.vmt', '')}_normal.png"
                    shutil.copy2(vtf_temp_png, normal_temp_png)
                    normal_options_normal = {"normal": True}
                    TextureService.create_vtf(str(normal_temp_png), str(vtf_output_path), format_type, [], normal_options_normal)
                    normal_png_name = normal_temp_png.stem
                    created_normal_vtf = vtf_output_path / f"{normal_png_name}.vtf"
                    normal_vtf_path = vtf_output_path / normal_vtf_filename
                    if created_normal_vtf.exists():
                        created_normal_vtf.rename(normal_vtf_path)
                        logger.info(f"Создана normal VTF текстура для специального режима: {normal_vtf_filename}")
                    else:
                        logger.warning(f"Normal VTF файл не был создан: {created_normal_vtf}")
                    if normal_temp_png.exists():
                        normal_temp_png.unlink()
                else:
                    TextureService.create_vtf(str(vtf_temp_png), str(vtf_output_path), format_type, vtf_flags, merged_options)
                if vtf_temp_png.exists():
                    vtf_temp_png.unlink()
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
