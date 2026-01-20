"""
Вся хуйня с VPK файлами - распаковка, сборка, конвертация текстур.
Если что-то сломалось - виноват не я, а Valve с их ебанутым форматом.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any
from PIL import Image
from .build_context import BuildContext
from .vmt_service import VMTService
from .tf2_vpk_extract_service import TF2VPKExtractService
from .model_build_service import ModelBuildService
from .tf2_paths import TF2Paths
from .debug_service import DebugService
from .smd_service import SMDService
from src.data.weapons import SPECIAL_MODES, WEAPON_MDL_PATHS
from src.shared.logging_config import get_logger
from src.shared.constants import ToolPaths, DirectoryPaths
from src.shared.exceptions import (
    TF2PathNotSpecifiedError,
    ModelNotFoundError,
    VTFCreationError,
    VPKCreationError,
    BuildError,
    PathTooLongError
)
from src.shared.file_utils import ensure_file_exists, ensure_directory_exists, copy_file_safe

logger = get_logger(__name__)


class VPKService:
    """Тут вся магия сборки VPK файлов. Если что-то не работает - читай логи, я не телепат."""
    
    @staticmethod
    def _get_vtf_tool() -> Path:
        return ToolPaths.get_vtf_tool()
    
    @staticmethod
    def _get_vpk_tool() -> Path:
        return ToolPaths.get_vpk_tool()
    
    @staticmethod
    def _get_crowbar() -> Path:
        return ToolPaths.get_crowbar()
    
    @staticmethod
    def build_vpk(
        image_path: str,
        mode: str,
        filename: str,
        size: Tuple[int, int],
        format_type: str = "DXT1",
        flags: List[str] = None,
        vtf_options: dict = None,
        tf2_root_dir: str = "",
        export_folder: str = "export",
        keep_temp_on_error: bool = False,
        debug_mode: bool = False,
        replace_model_enabled: bool = False,
        draw_uv_layout: bool = False,
        parent_window=None,  # Окно для диалогов (если нужно показать что-то юзеру)
        replace_model_path: str = None,  # Путь к модели для замены (для тестов, обычно None)
        model_file_callback=None,  # Колбэк для запроса файла из UI потока (потому что Qt не любит мультипоточность)
        language: str = "en",  # Язык для ошибок
        custom_vtf_path: str = None  # Если юзер сам сделал VTF - используем его вместо генерации из картинки
    ) -> Tuple[bool, str]:
        """
        Главная функция - делает из картинки VPK файл. 
        Если что-то пойдет не так - вернет False и описание проблемы.
        Вся эта хуйня с моделями, текстурами и VPK - тут.
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        
        ctx = None
        try:
            # Проверяем что все на месте, иначе потом будет больно (валидация параметров)
            validation_error = VPKService._validate_build_params(
                image_path, mode, filename, size, format_type, tf2_root_dir, t, custom_vtf_path
            )
            if validation_error:
                return False, validation_error
            
            if flags is None:
                flags = []
            
            weapon_key = mode.split('_', 1)[1] if '_' in mode else mode
            
            # Запоминаем какой VMT надо будет удалить после сборки (если юзер его редактировал через редактор)
            vmt_to_delete = None
            
            ctx = BuildContext.create(mode, weapon_key, debug_mode=debug_mode)
            
            # Для critHIT и прочих спец режимов - просто текстуры, без всей этой возни с моделями
            if mode in SPECIAL_MODES.values():
                result = VPKService._build_special_mode_vpk(
                    ctx, mode, image_path, size, format_type, flags, vtf_options,
                    keep_temp_on_error, debug_mode, language, custom_vtf_path
                )
                if not result[0]:
                    return result[0], result[1]
                # Если юзер редактировал VMT, запомним чтобы потом удалить
                if len(result) > 2 and result[2]:
                    vmt_to_delete = result[2]
                else:
                    vmt_to_delete = None
            else:
                # Для обычного оружия - сначала распаковываем модель, потом текстуры по пути из QC делаем
                # Без пути к TF2 вообще хуй че получится - нужны VPK файлы игры
                if not tf2_root_dir:
                    logger.error("Путь к TF2 не указан")
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_tf2_not_specified']
                
                # Crowbar нужен для декомпиляции, без него никак
                crowbar_exists, crowbar_error = TF2Paths.check_crowbar()
                if not crowbar_exists:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, crowbar_error
                
                try:
                    studiomdl_exe, tf2_misc_vpk, tf_dir = TF2Paths.resolve(tf2_root_dir)
                except FileNotFoundError as e:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, str(e)
                
                if weapon_key not in WEAPON_MDL_PATHS:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_weapon_not_found'].format(weapon_key=weapon_key)
                
                # Тут начинается веселье - TF2 хранит модели в разных местах, и мы не знаем где именно
                # Поэтому пробуем все возможные варианты, начиная с самых вероятных:
                # workshop_partner -> workshop -> weapons/c_models -> weapons/c_items -> player/items
                # И для каждого пути пробуем с папкой и без (потому что Valve любит делать по-разному, хуй знает почему)
                
                base_path_from_config = WEAPON_MDL_PATHS[weapon_key]
                
                paths_to_try = []
                
                # Сначала пробуем workshop_partner - там обычно все новое лежит
                workshop_partner_path_with_folder = base_path_from_config.replace("models/weapons/", "models/workshop_partner/weapons/")
                paths_to_try.append(workshop_partner_path_with_folder)
                
                # А может без папки? (Valve любит делать по-разному, потому что им похую на консистентность)
                if f"/{weapon_key}/{weapon_key}.mdl" in workshop_partner_path_with_folder:
                    workshop_partner_path_no_folder = workshop_partner_path_with_folder.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(workshop_partner_path_no_folder)
                
                # Потом workshop
                workshop_path_with_folder = base_path_from_config.replace("models/weapons/", "models/workshop/weapons/")
                paths_to_try.append(workshop_path_with_folder)
                
                if f"/{weapon_key}/{weapon_key}.mdl" in workshop_path_with_folder:
                    workshop_path_no_folder = workshop_path_with_folder.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(workshop_path_no_folder)
                
                # Стандартное место
                paths_to_try.append(base_path_from_config)
                
                if f"/{weapon_key}/{weapon_key}.mdl" in base_path_from_config:
                    fallback_path_no_folder = base_path_from_config.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(fallback_path_no_folder)
                
                # Может в c_items? (еще одно место где может лежать хуйня)
                c_items_path_with_folder = base_path_from_config.replace("models/weapons/c_models/", "models/weapons/c_items/")
                paths_to_try.append(c_items_path_with_folder)
                
                if f"/{weapon_key}/{weapon_key}.mdl" in c_items_path_with_folder:
                    c_items_path_no_folder = c_items_path_with_folder.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(c_items_path_no_folder)
                
                # Последний шанс - в папках классов (тут обычно старье валяется, но проверить надо)
                if '_' in mode:
                    class_name_lower = mode.split('_', 1)[0]
                    
                    player_items_path_with_folder = f"models/player/items/{class_name_lower}/{weapon_key}/{weapon_key}.mdl"
                    paths_to_try.append(player_items_path_with_folder)
                    
                    player_items_path_no_folder = f"models/player/items/{class_name_lower}/{weapon_key}.mdl"
                    paths_to_try.append(player_items_path_no_folder)
                
                crowbar_exe = TF2Paths.get_crowbar_path()
                
                try:
                    # Оптимизация: сначала просто проверяем есть ли файл, а не тащим всю папку
                    # Так быстрее, потому что не распаковываем кучу ненужного мусора из VPK
                    found_mdl_path = None
                    last_error = None
                    
                    for mdl_rel_path in paths_to_try:
                        try:
                            logger.debug(f"Проверяем наличие MDL по пути: {mdl_rel_path}")
                            if TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, mdl_rel_path):
                                found_mdl_path = mdl_rel_path
                                logger.info(f"MDL файл найден по пути: {mdl_rel_path}")
                                break
                            else:
                                logger.debug(f"MDL файл не найден по пути: {mdl_rel_path}")
                        except Exception as e:
                            logger.warning(f"Ошибка при проверке пути {mdl_rel_path}: {e}", exc_info=True)
                            last_error = e
                            continue
                    
                    if not found_mdl_path:
                        paths_str = "\n".join([f"  - {path}" for path in paths_to_try])
                        error_msg = t['error_mdl_not_found'].format(paths=paths_str, vpk_file=tf2_misc_vpk)
                        if last_error:
                            error_msg += f"\n{str(last_error)}"
                        logger.error(f"Модель не найдена для {weapon_key}. Проверенные пути: {len(paths_to_try)}")
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, error_msg
                    
                    # Теперь извлекаем все файлы модели для найденного пути (MDL, VVD, VTX, PHY и прочую хуйню)
                    logger.info(f"Извлекаем все файлы модели по найденному пути: {found_mdl_path}")
                    extracted_files = TF2VPKExtractService.extract_file_set(
                        tf2_misc_vpk,
                        found_mdl_path,
                        str(ctx.extract_dir),
                        str(VPKService._get_vpk_tool())
                    )
                    
                    # Находим .mdl файл среди извлеченных (он должен быть там, но на всякий случай проверяем)
                    mdl_file = None
                    for file_path in extracted_files:
                        if file_path.endswith('.mdl'):
                            mdl_file = file_path
                            break
                    
                    if not mdl_file:
                        error_msg = t['error_mdl_not_extracted'].format(path=found_mdl_path)
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, error_msg
                    
                    if debug_mode:
                        DebugService.save_extracted_stage(ctx, extracted_files)
                    
                    # Декомпилируем модель через Crowbar
                    qc_path = ModelBuildService.decompile(
                        mdl_file,
                        ctx.decompile_dir,
                        crowbar_exe
                    )
                    
                    if debug_mode:
                        DebugService.save_decompiled_stage(ctx, ctx.decompile_dir)
                    
                    if draw_uv_layout:
                        VPKService._generate_uv_layout(ctx, weapon_key, size, export_folder, language)
                    
                    # Удаляем LOD файлы - они нам не нужны, только мусорят (это уровни детализации, для скинов не нужны)
                    ModelBuildService.remove_lod_files(ctx.decompile_dir)
                    
                    # Заменяем модель, если включен режим замены
                    # Диалог выбора файла показываем здесь, после декомпиляции (чтобы знать куда копировать)
                    replace_model_smd_path = None
                    if replace_model_enabled:
                        # Если передан путь модели напрямую (для тестового режима), используем его
                        if replace_model_path and os.path.exists(replace_model_path):
                            replace_model_smd_path = replace_model_path
                            logger.info(f"Используется предустановленный файл для замены модели: {replace_model_smd_path}")
                        elif model_file_callback:
                            # Используем callback для запроса файла из главного потока (Qt не любит UI из воркера)
                            file_path = model_file_callback()
                            if file_path and os.path.exists(file_path):
                                replace_model_smd_path = file_path
                                logger.info(f"Выбран файл для замены модели через callback: {replace_model_smd_path}")
                            else:
                                logger.info("Выбор SMD файла отменен, продолжаем без замены модели")
                        elif parent_window:
                            # Показываем диалог выбора SMD файла (только если не в рабочем потоке, иначе Qt упадет)
                            from PySide6.QtWidgets import QFileDialog
                            
                            file_path, _ = QFileDialog.getOpenFileName(
                                parent_window,
                                "Выберите SMD файл модели для замены",
                                "",
                                "SMD Files (*.smd);;All Files (*)"
                            )
                            
                            if file_path and os.path.exists(file_path):
                                replace_model_smd_path = file_path
                                logger.info(f"Выбран файл для замены модели: {replace_model_smd_path}")
                            else:
                                logger.info("Выбор SMD файла отменен, продолжаем без замены модели")
                        else:
                            logger.warning("Режим замены модели включен, но путь к модели не указан и нет способа запросить файл")
                    
                    if replace_model_smd_path and os.path.exists(replace_model_smd_path):
                        try:
                            # Находим reference SMD файл в декомпилированной директории (это оригинальная модель из игры)
                            logger.debug(f"Ищем reference SMD файл для weapon_key: {weapon_key} в {ctx.decompile_dir}")
                            original_smd_path = SMDService.find_reference_smd(str(ctx.decompile_dir), weapon_key)
                            
                            if original_smd_path:
                                # Проверяем, что найденный файл действительно соответствует weapon_key
                                # Иначе можем загрузить не то оружие и все сломается (например, scattergun вместо bat)
                                file_name = os.path.basename(original_smd_path)
                                if weapon_key.lower() not in file_name.lower():
                                    logger.error(f"Найденный SMD файл {file_name} не соответствует weapon_key {weapon_key}!")
                                    logger.warning("Пропускаем замену модели, чтобы избежать загрузки неправильного оружия")
                                    original_smd_path = None
                            
                            if original_smd_path:
                                logger.info(f"Заменяем модель: {replace_model_smd_path} -> {original_smd_path}")
                                # Заменяем секции: nodes и skeleton из оригинального (иначе модель не скомпилируется),
                                # названия материалов из оригинального (иначе текстуры не загрузятся),
                                # данные треугольников из пользовательского (это то, что юзер хочет заменить)
                                SMDService.replace_model_sections(
                                    replace_model_smd_path,
                                    original_smd_path,
                                    original_smd_path  # Перезаписываем оригинальный файл под тем же именем
                                )
                                logger.info(f"Модель успешно заменена: {original_smd_path}")
                            else:
                                logger.warning(f"Не найден reference SMD файл для {weapon_key} в {ctx.decompile_dir}")
                                if ctx.decompile_dir.exists():
                                    smd_files = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')]
                                    logger.debug(f"Доступные SMD файлы в директории: {smd_files}")
                        except Exception as e:
                            logger.error(f"Ошибка при замене модели: {e}", exc_info=True)
                            # Не прерываем сборку, просто продолжаем с оригинальной моделью (лучше так, чем упасть)
                    
                    # Извлекаем путь из $cdmaterials в QC файле (до патчинга, потому что потом мы его изменим)
                    original_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
                    
                    if not original_cdmaterials_path:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_cdmaterials_not_extracted'].format(qc_path=qc_path)
                    
                    # Извлекаем имя файла из $texturegroup (до патчинга, потому что потом мы его изменим)
                    texture_filename = ModelBuildService.extract_texturegroup_filename(qc_path)
                    if not texture_filename:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_texturegroup_not_extracted'].format(qc_path=qc_path)
                    
                    # Пропатчиваем QC файл: добавляем console\ к $cdmaterials (чтобы текстуры загружались из консольных команд),
                    # удаляем $lod (они нам не нужны, только мусорят)
                    ModelBuildService.patch_qc_file(qc_path, weapon_key, original_cdmaterials_path)
                    
                    # Извлекаем путь из $cdmaterials после патчинга (теперь с префиксом console\)
                    patched_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
                    if not patched_cdmaterials_path:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_cdmaterials_patched_not_extracted'].format(qc_path=qc_path)
                    
                    # Конвертируем путь из $cdmaterials в путь для материалов
                    # Путь теперь в формате: console\models\weapons\v_bonesaw
                    # Конвертируем в: materials/console/models/weapons/v_bonesaw/ (потому что VPK требует такую структуру)
                    materials_rel_path = "materials/" + patched_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
                    if not materials_rel_path.endswith('/'):
                        materials_rel_path += '/'
                    
                    vmt_filename = f"{texture_filename}.vmt"
                    vtf_filename = f"{texture_filename}.vtf"
                    
                    # Подготавливаем пути в vpkroot (создаем структуру папок как в VPK)
                    materials_path_parts = materials_rel_path.rstrip('/').split('/')
                    vtf_output_path = ctx.vpkroot_dir
                    for part in materials_path_parts:
                        vtf_output_path = vtf_output_path / part
                    vmt_path = vtf_output_path / vmt_filename
                    vtf_temp_png = vtf_output_path / vtf_filename.replace(".vtf", ".png")
                    
                    try:
                        ensure_directory_exists(vtf_output_path)
                    except OSError as e:
                        if "path too long" in str(e).lower():
                            logger.error(f"Путь слишком длинный для режима {mode}")
                            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                            return False, t['error_path_too_long'].format(mode=mode)
                        else:
                            raise
                    
                    if custom_vtf_path:
                        # Если юзер сам сделал VTF - просто копируем его, не генерируем из картинки
                        vtf_file_path = vtf_output_path / vtf_filename
                        ensure_directory_exists(vtf_output_path)
                        copy_file_safe(custom_vtf_path, vtf_file_path)
                        logger.info(f"Использован пользовательский VTF файл: {custom_vtf_path} -> {vtf_file_path}")
                    else:
                        VPKService._process_image(image_path, vtf_temp_png, size)
                        
                        # Разделяем флаги на опции VTFCmd и флаги VTF (потому что они передаются по-разному)
                        vtf_flags, flags_parsed_options = VPKService._parse_vtf_flags_and_options(flags)
                        
                        # Объединяем опции из UI с опциями из флагов (UI имеет приоритет, но флаги могут переопределить)
                        merged_options = {}
                        if vtf_options:
                            merged_options.update(vtf_options)
                        merged_options.update(flags_parsed_options)
                        
                        is_normal_map = merged_options.get("normal", False)
                        
                        # Если normal map включена, создаем обычную текстуру БЕЗ опции normal
                        # Потом создаем отдельную normal текстуру с суффиксом _normal (это костыль, но так работает Source)
                        if is_normal_map:
                            normal_options = merged_options.copy()
                            normal_options.pop("normal", None)
                            
                            # Создаем обычную VTF текстуру без normal опции (это базовая текстура)
                            VPKService._create_vtf(str(vtf_temp_png), str(vtf_output_path), format_type, vtf_flags, normal_options)
                            logger.info(f"Создана обычная VTF текстура: {vtf_filename}")
                            
                            # Создаем normal VTF текстуру с суффиксом _normal (это для бампмаппинга)
                            normal_vtf_filename = f"{texture_filename}_normal.vtf"
                            normal_temp_png = vtf_output_path / f"{texture_filename}_normal.png"
                            
                            import shutil
                            shutil.copy2(vtf_temp_png, normal_temp_png)
                            
                            normal_options_normal = {"normal": True}
                            
                            # VTFCmd создает файл с именем входного PNG файла, поэтому создаем с правильным именем
                            # (это баг VTFCmd, но мы обходим его переименованием)
                            VPKService._create_vtf(str(normal_temp_png), str(vtf_output_path), format_type, [], normal_options_normal)
                            
                            # VTFCmd создает VTF файл с именем PNG файла, переименовываем в правильное имя
                            normal_png_name = normal_temp_png.stem
                            created_normal_vtf = vtf_output_path / f"{normal_png_name}.vtf"
                            normal_vtf_path = vtf_output_path / normal_vtf_filename
                            
                            if created_normal_vtf.exists():
                                created_normal_vtf.rename(normal_vtf_path)
                                logger.info(f"Создана normal VTF текстура: {normal_vtf_filename}")
                            else:
                                logger.warning(f"Normal VTF файл не был создан: {created_normal_vtf}")
                            
                            if normal_temp_png.exists():
                                normal_temp_png.unlink()
                        else:
                            VPKService._create_vtf(str(vtf_temp_png), str(vtf_output_path), format_type, vtf_flags, merged_options)
                        
                        if vtf_temp_png.exists():
                            vtf_temp_png.unlink()
                    
                    # Пробуем извлечь VMT файл, используя оригинальный путь из QC (до патчинга)
                    # Потому что в VPK он лежит по оригинальному пути, а не по патченному
                    vmt_file = None
                    # Пробуем найти tf2_textures_dir.vpk для извлечения VMT (там обычно лежат текстуры)
                    tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
                    if original_cdmaterials_path and tf2_textures_vpk:
                        vmt_file = TF2VPKExtractService.extract_vmt_file(
                            tf2_textures_vpk,
                            original_cdmaterials_path,
                            texture_filename,
                            ctx.decompile_dir
                        )
                        if vmt_file:
                            logger.info(f"Извлечен VMT файл: {vmt_file}")
                        else:
                            # Пробуем также tf2_misc_dir.vpk (иногда текстуры лежат там, потому что Valve)
                            vmt_file = TF2VPKExtractService.extract_vmt_file(
                                tf2_misc_vpk,
                                original_cdmaterials_path,
                                texture_filename,
                                str(ctx.decompile_dir)
                            )
                            if vmt_file:
                                logger.info(f"Извлечен VMT файл из misc: {vmt_file}")
                    elif original_cdmaterials_path:
                        # Пробуем tf2_misc_dir.vpk если textures не найден (fallback)
                        vmt_file = TF2VPKExtractService.extract_vmt_file(
                            tf2_misc_vpk,
                            original_cdmaterials_path,
                            texture_filename,
                            str(ctx.decompile_dir)
                        )
                        if vmt_file:
                            logger.info(f"Извлечен VMT файл: {vmt_file}")
                    
                    # Проверяем, есть ли отредактированный VMT файл (приоритет 1 - юзер знает лучше)
                    from src.services.edited_vmt_service import EditedVMTService
                    edited_vmt_path = EditedVMTService.get_edited_vmt(texture_filename)
                    
                    if edited_vmt_path and Path(edited_vmt_path).exists():
                        # Используем отредактированный VMT файл (юзер его правил через редактор)
                        copy_file_safe(edited_vmt_path, vmt_path)
                        # Обновляем путь $baseTexture в отредактированном VMT файле на основе пути из QC
                        # (потому что путь может измениться, а юзер редактировал старый)
                        VMTService.update_vmt_basetexture_path(str(vmt_path), patched_cdmaterials_path, texture_filename)
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
                    
                    # Если normal map включена, обновляем VMT файл для добавления $bumpmap
                    # (это нужно для бампмаппинга, иначе нормалмап не загрузится)
                    if is_normal_map:
                        normal_weapon_key = f"{texture_filename}_normal"
                        VMTService.update_vmt_bumpmap_path(str(vmt_path), patched_cdmaterials_path, normal_weapon_key)
                        logger.info(f"Обновлен VMT файл для добавления $bumpmap: {normal_weapon_key}")
                    
                    if debug_mode:
                        DebugService.save_patched_stage(ctx, ctx.decompile_dir)
                    
                    # Компилируем модель через studiomdl (это официальный компилятор Source, без него никак)
                    ModelBuildService.compile(
                        qc_path,
                        ctx.compile_dir,
                        studiomdl_exe,
                        tf_dir
                    )
                    
                    if debug_mode:
                        DebugService.save_compiled_stage(ctx, ctx.compile_dir)
                    
                    # Копируем скомпилированные файлы в vpkroot (VMT файл уже скопирован ранее)
                    # Используем путь из $modelname в QC файле (чтобы структура папок была правильной)
                    VPKService._copy_compiled_models_to_vpkroot(ctx, qc_path)
                    
                except Exception as e:
                    error_msg = str(e)
                    if hasattr(e, 'stderr') and e.stderr:
                        error_msg += f"\nSTDERR: {e.stderr}"
                    if hasattr(e, 'stdout') and e.stdout:
                        error_msg += f"\nSTDOUT: {e.stdout}"
                    
                    if keep_temp_on_error:
                        error_msg += f"\n\nВременные файлы сохранены в: {ctx.temp_dir}"
                    
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_model_work'].format(error=error_msg)
            
            # Собираем VPK файл (финальный этап - упаковываем все в один файл)
            vpk_path = VPKService._create_vpk_file(ctx, filename, export_folder, language)
            
            # Если использовали отредактированный VMT - удаляем его после сборки (чтобы не засорять папку)
            if vmt_to_delete:
                from src.services.edited_vmt_service import EditedVMTService
                if EditedVMTService.delete_edited_vmt(vmt_to_delete):
                    logger.info(f"Удален отредактированный VMT файл: {vmt_to_delete}")
            
            # Чистим папку с временными VMT файлами (которые доставали из игры для редактора)
            # (это мусор, который остается после работы редактора VMT)
            temp_vmt_extract_dir = DirectoryPaths.TEMP_VMT_EXTRACT_DIR
            if temp_vmt_extract_dir.exists():
                try:
                    for file_path in temp_vmt_extract_dir.iterdir():
                        try:
                            if file_path.is_file() or file_path.is_symlink():
                                file_path.unlink()
                            elif file_path.is_dir():
                                shutil.rmtree(file_path)
                        except Exception as e:
                            logger.warning(f"Не удалось удалить {file_path}: {e}", exc_info=True)
                    logger.debug("Очищена папка temp_vmt_extract")
                except Exception as e:
                    logger.warning(f"Не удалось очистить папку temp_vmt_extract: {e}", exc_info=True)
            
            ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=debug_mode)
            
            success_message = t.get('vpk_success', 'VPK successfully created: {path}').format(path=vpk_path)
            return True, success_message
            
        except Exception as e:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
            error_msg = t['error_vpk_creation'].format(error=str(e))
            if ctx:
                if keep_temp_on_error:
                    error_msg += f"\n\n{t.get('temp_files_saved', 'Temporary files saved in')}: {ctx.temp_dir}"
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, error_msg
    
    @staticmethod
    def _build_special_mode_vpk(
        ctx: BuildContext,
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
        """
        Создает VPK для специальных режимов (critHIT и т.д.)
        Возвращает Tuple[success, message, vmt_to_delete] - где vmt_to_delete это имя файла для удаления, если был использован отредактированный VMT
        (для спец режимов не нужны модели, только текстуры, поэтому проще)
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        
        try:
            rel_path, vmt_filename, vtf_filename = VMTService.get_weapon_relpaths(mode)
            
            vtf_output_path = ctx.vpkroot_dir / rel_path
            vmt_path = vtf_output_path / vmt_filename
            vtf_temp_png = vtf_output_path / vtf_filename.replace(".vtf", ".png")
            
            try:
                ensure_directory_exists(vtf_output_path)
            except OSError as e:
                if "path too long" in str(e).lower():
                    logger.error(f"Путь слишком длинный для режима {mode}")
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_path_too_long'].format(mode=mode), None
                else:
                    raise
            
            if custom_vtf_path:
                # Для специальных режимов имя VTF файла соответствует имени VMT файла (простая логика)
                vtf_filename_for_mode = vmt_filename.replace('.vmt', '.vtf')
                vtf_file_path = vtf_output_path / vtf_filename_for_mode
                ensure_directory_exists(vtf_output_path)
                copy_file_safe(custom_vtf_path, vtf_file_path)
                logger.info(f"Использован пользовательский VTF файл для специального режима: {custom_vtf_path} -> {vtf_file_path}")
            else:
                VPKService._process_image(image_path, vtf_temp_png, size)
                
                vtf_flags, flags_parsed_options = VPKService._parse_vtf_flags_and_options(flags)
                
                merged_options = {}
                if vtf_options:
                    merged_options.update(vtf_options)
                merged_options.update(flags_parsed_options)
                
                is_normal_map = merged_options.get("normal", False)
                
                # Если normal map включена, создаем обычную текстуру БЕЗ опции normal
                # Потом создаем отдельную normal текстуру с суффиксом _normal (костыль, но так работает)
                if is_normal_map:
                    normal_options = merged_options.copy()
                    normal_options.pop("normal", None)
                    
                    VPKService._create_vtf(str(vtf_temp_png), str(vtf_output_path), format_type, vtf_flags, normal_options)
                    logger.info(f"Создана обычная VTF текстура для специального режима: {vtf_filename_for_mode}")
                    
                    normal_vtf_filename = f"{vmt_filename.replace('.vmt', '')}_normal.vtf"
                    normal_temp_png = vtf_output_path / f"{vmt_filename.replace('.vmt', '')}_normal.png"
                    
                    import shutil
                    shutil.copy2(vtf_temp_png, normal_temp_png)
                    
                    normal_options_normal = {"normal": True}
                    
                    VPKService._create_vtf(str(normal_temp_png), str(vtf_output_path), format_type, [], normal_options_normal)
                    
                    # VTFCmd создает VTF файл с именем PNG файла, переименовываем в правильное имя (баг VTFCmd)
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
                    VPKService._create_vtf(str(vtf_temp_png), str(vtf_output_path), format_type, vtf_flags, merged_options)
                
                if vtf_temp_png.exists():
                    vtf_temp_png.unlink()
            
            # Проверяем, есть ли отредактированный VMT файл для специальных режимов
            from src.services.edited_vmt_service import EditedVMTService
            # Для специальных режимов используем имя файла из режима (например, "crit" для critHIT)
            vmt_filename_without_ext = os.path.splitext(vmt_filename)[0]
            edited_vmt_path = EditedVMTService.get_edited_vmt(vmt_filename_without_ext)
            vmt_to_delete = None
            
            # Определяем путь к mod_data для специальных режимов (там лежат шаблоны VMT)
            if mode == "critHIT":
                mod_data_base = DirectoryPaths.MOD_DATA_DIR
            else:
                mod_data_base = DirectoryPaths.MOD_DATA_DIR / mode
            
            mod_data_vmt_path = mod_data_base / vmt_filename
            
            if edited_vmt_path and os.path.exists(edited_vmt_path):
                # Используем отредактированный VMT файл (приоритет 1 - юзер знает лучше)
                copy_file_safe(edited_vmt_path, vmt_path)
                logger.info(f"Использован отредактированный VMT файл для специального режима: {edited_vmt_path} -> {vmt_path}")
                vmt_to_delete = vmt_filename_without_ext
            elif mod_data_vmt_path.exists():
                # Используем существующий VMT файл из mod_data (приоритет 2 - шаблон из проекта)
                copy_file_safe(mod_data_vmt_path, vmt_path)
                logger.info(f"Использован VMT файл из mod_data: {mod_data_vmt_path} -> {vmt_path}")
            else:
                # Создаем VMT файл из шаблона (приоритет 3 - базовый шаблон, если ничего нет)
                class_name = mode.split('_')[0].capitalize() if '_' in mode else "Unknown"
                weapon_type = "Primary"
                VMTService.create_vmt_template(str(vmt_path), mode, class_name, weapon_type)
                logger.info(f"Создан VMT файл из шаблона: {vmt_path}")
            
            # Если normal map включена, обновляем VMT файл для добавления $bumpmap
            # (иначе нормалмап не загрузится, и бампмаппинг не будет работать)
            if is_normal_map:
                normal_texture_filename = vmt_filename.replace('.vmt', '_normal')
                # Для специальных режимов используем путь относительно materials (без префикса)
                normal_cdmaterials_path = rel_path.replace('materials/', '').rstrip('/')
                VMTService.update_vmt_bumpmap_path(str(vmt_path), normal_cdmaterials_path, normal_texture_filename)
                logger.info(f"Обновлен VMT файл для добавления $bumpmap: {normal_texture_filename}")
            
            # Копируем PCF файл для critHIT режима (если существует)
            # PCF - это файлы частиц, нужны для эффекта крита
            if mode == "critHIT":
                pcf_filename = "crit.pcf"
                mod_data_pcf_path = mod_data_base / pcf_filename
                if mod_data_pcf_path.exists():
                    # PCF файлы должны быть в папке particles (так требует Source Engine)
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
    
    @staticmethod
    def _validate_build_params(
        image_path: str,
        mode: str,
        filename: str,
        size: Tuple[int, int],
        format_type: str,
        tf2_root_dir: str,
        t: dict = None,
        custom_vtf_path: str = None
    ) -> Optional[str]:
        """
        Валидирует параметры сборки VPK. Если custom_vtf_path указан - пропускается проверка image_path (VTF уже готов).
        Возвращает None если валидация прошла успешно, иначе строка с описанием ошибки (чтобы показать юзеру что не так).
        """
        if t is None:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS['en']
        
        if not custom_vtf_path:
            if not image_path or not isinstance(image_path, str):
                return t['error_image_not_specified']
            
            if not os.path.exists(image_path):
                return t['error_image_not_found'].format(path=image_path)
            
            if not os.path.isfile(image_path):
                return t['error_image_not_file'].format(path=image_path)
        else:
            if not os.path.exists(custom_vtf_path):
                return t.get('error_custom_vtf_not_found', f'Custom VTF file not found: {custom_vtf_path}')
            
            if not os.path.isfile(custom_vtf_path):
                return t.get('error_custom_vtf_not_file', f'Custom VTF path is not a file: {custom_vtf_path}')
        
        if not mode or not isinstance(mode, str):
            return t['error_mode_not_specified']
        
        if not filename or not isinstance(filename, str):
            return t['error_filename_not_specified']
        
        if not filename.endswith('.vpk'):
            return t['error_filename_no_vpk']
        
        if not isinstance(size, (tuple, list)) or len(size) != 2:
            return t['error_size_invalid']
        
        width, height = size
        if not isinstance(width, int) or not isinstance(height, int):
            return t['error_size_not_int']
        
        if width <= 0 or height <= 0:
            return t['error_size_not_positive']
        
        # Список всех поддерживаемых форматов VTF (кроме P8, который не поддерживается VTFCmd, поэтому его нет в списке)
        valid_formats = [
            'DXT1',
            'DXT3',
            'DXT5',
            'RGBA8888',
            'ABGR8888',
            'RGB888',
            'BGR888',
            'RGB565',
            'BGR565',
            'I8',
            'IA88',
            'A8',
            'RGB888 Bluescreen',
            'BGR888 Bluescreen',
            'ARGB8888',
            'BGRA8888',
            'BGRX8888',
            'BGRX5551',
            'BGRA4444',
            'DXT1 With One Bit Alpha',
            'BGRA5551',
            'UV88',
            'UVWQ8888',
            'RGBA16161616F',
            'RGBA16161616',
            'UVLX8888'
        ]
        if format_type not in valid_formats:
            return t['error_format_invalid'].format(format=format_type, formats=', '.join(valid_formats))
        
        weapon_key = mode.split('_', 1)[1] if '_' in mode else mode
        if mode not in SPECIAL_MODES.values():
            if not tf2_root_dir or not isinstance(tf2_root_dir, str):
                return t['error_tf2_required']
            
            if not os.path.exists(tf2_root_dir):
                return t['error_tf2_not_found'].format(path=tf2_root_dir)
            
            if not os.path.isdir(tf2_root_dir):
                return t['error_tf2_not_dir'].format(path=tf2_root_dir)
        
        return None
    
    @staticmethod
    def _process_image(input_path: str, output_path: str, size: Tuple[int, int]) -> None:
        """Обрабатывает изображение для VTF. Определяет наличие альфа-канала и конвертирует соответственно (RGBA если есть альфа, RGB если нет)."""
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Изображение не найдено: {input_path}")
        
        img = Image.open(input_path)
        # Определяем есть ли альфа-канал в исходном изображении (RGBA, LA или transparency в info)
        has_alpha = img.mode in ('RGBA', 'LA') or 'transparency' in img.info
        
        # Конвертируем в RGBA только если есть альфа, иначе в RGB
        # Это важно чтобы VTFCmd правильно определял наличие альфа-канала (иначе может использовать DXT5 вместо DXT1)
        if has_alpha:
            img = img.convert("RGBA").resize(size)
        else:
            img = img.convert("RGB").resize(size)
        
        img.save(output_path)
    
    @staticmethod
    def _parse_vtf_flags_and_options(flags: List[str]) -> Tuple[List[str], dict]:
        """
        Преобразует флаги из UI в опции VTFCmd и флаги VTF.
        Возвращает Tuple[vtf_flags, options] - флаги для передачи через -flag и опции VTFCmd (потому что они передаются по-разному).
        """
        if flags is None:
            flags = []
        
        vtf_flags = []
        options = {}
        
        for flag in flags:
            flag_upper = flag.upper()
            
            # Опции VTFCmd (передаются как отдельные параметры, не через -flag, потому что так работает VTFCmd - ебанутый формат)
            if flag_upper == "NOMIP":
                options["nomipmaps"] = True
            else:
                vtf_flags.append(flag)
        
        return vtf_flags, options
    
    @staticmethod
    def _create_vtf(png_path: str, output_path: str, format_type: str, flags: List[str], 
                   options: dict = None) -> None:
        """
        Создает VTF файл из PNG через VTFCmd. 
        options может содержать nomipmaps, nothumbnail, noreflectivity, gamma, normal и прочую хуйню (все опции VTFCmd).
        """
        if options is None:
            options = {}
        
        # Маппинг форматов из UI в форматы которые понимает VTFCmd
        # Некоторые форматы с пробелами имеют альтернативные названия (потому что VTFCmd не любит пробелы - ебанутый формат)
        format_mapping = {
            "RGB888 Bluescreen": "RGB888_BLUESCREEN",
            "BGR888 Bluescreen": "BGR888_BLUESCREEN",
            "DXT1 With One Bit Alpha": "DXT1_ONEBITALPHA"
        }
        
        vtf_format = format_mapping.get(format_type, format_type)
        
        # Проверяем есть ли альфа-канал в изображении (нужно для правильной обработки)
        has_alpha = False
        try:
            from PIL import Image
            with Image.open(png_path) as img:
                has_alpha = img.mode in ('RGBA', 'LA') or 'transparency' in img.info
        except Exception as e:
            logger.warning(f"Не удалось проверить альфа-канал: {e}")
        
        logger.info(f"Создание VTF с форматом: {format_type} -> {vtf_format}, альфа-канал: {has_alpha}")
        
        vtf_args = [
            str(VPKService._get_vtf_tool()),
            "-file", png_path,
            "-output", output_path,
            "-format", vtf_format
        ]
        
        # Если изображение содержит альфа-канал - добавляем -alphaformat
        # Это важно потому что VTFCmd может использовать DXT5 по умолчанию для альфа-канала (даже если мы хотим DXT1)
        if has_alpha:
            vtf_args.extend(["-alphaformat", vtf_format])
        
        # Добавляем опции VTFCmd
        if options.get("nomipmaps", False):
            vtf_args.append("-nomipmaps")
        if options.get("nothumbnail", False):
            vtf_args.append("-nothumbnail")
        if options.get("noreflectivity", False):
            vtf_args.append("-noreflectivity")
        if options.get("gamma", False):
            vtf_args.append("-gamma")
            if "gcorrection" in options:
                vtf_args.extend(["-gcorrection", str(options["gcorrection"])])
        if options.get("normal", False):
            vtf_args.append("-normal")
            if "nkernel" in options:
                vtf_args.extend(["-nkernel", str(options["nkernel"])])
            if "nheight" in options:
                vtf_args.extend(["-nheight", str(options["nheight"])])
            if "nalpha" in options:
                vtf_args.extend(["-nalpha", str(options["nalpha"])])
            if "nscale" in options:
                vtf_args.extend(["-nscale", str(options["nscale"])])
            if options.get("nwrap", False):
                vtf_args.append("-nwrap")
        if "bumpscale" in options:
            vtf_args.extend(["-bumpscale", str(options["bumpscale"])])
        
        # Добавляем флаги VTF через -flag
        # Маппинг флагов из UI в названия которые понимает VTFCmd (потому что VTFCmd требует нижний регистр - ебанутый формат)
        flag_mapping = {
            "CLAMPS": "clamps",
            "CLAMPT": "clampt", 
            "NOLOD": "nolod",
            "NOMIP": "nomip",  # Если нужно использовать как флаг (но лучше через -nomipmaps)
            "NOMINMIP": "minmip",  # No minimum Mipmap (используется флаг MINMIP, потому что логика Valve)
            "POINTSAMPLE": "pointsample",
            "TRILINEAR": "trilinear",
            "ANISOTROPIC": "anisotropic",
            "SRGB": "srgb",
            "NOCOMPRESS": "nocompress",
            "NODEBUGOVERRIDE": "nodebugoverride",
            "SINGLECOPY": "singlecopy",
            "NODEPTHBUFFER": "nodepthbuffer",
            "CLAMPU": "clampu",
            "VERTEXTEXTURE": "vertextexture",
            "SSBUMP": "ssbump",
            "BORDER": "border"
        }
        
        for flag in flags:
            # Пропускаем NOMIP, так как он уже обработан как опция nomipmaps (чтобы не дублировать)
            if flag.upper() == "NOMIP":
                continue
            
            # Если флаг в маппинге - используем его значение (потому что VTFCmd требует точные названия)
            if flag in flag_mapping:
                vtf_args.extend(["-flag", flag_mapping[flag]])
            else:
                # Иначе передаем как есть (в нижнем регистре, потому что VTFCmd так требует - ебанутый формат)
                vtf_args.extend(["-flag", flag.lower()])
        
        # Логируем полную команду для отладки (на случай если что-то сломается)
        logger.info(f"VTFCmd команда: {' '.join(vtf_args)}")
        logger.info(f"VTFCmd аргументы (список): {vtf_args}")
        logger.info(f"Передаваемый формат: {vtf_format} (исходный: {format_type})")
        logger.info(f"Опции VTFCmd: {options}")
        logger.info(f"Флаги VTF: {flags}")
        
        result = subprocess.run(vtf_args, check=True, capture_output=True, text=True)
        if result.returncode != 0:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise RuntimeError(
                t['error_vtf_creation_failed'].format(
                    command=' '.join(vtf_args),
                    stdout=result.stdout,
                    stderr=result.stderr
                )
            )
    
    @staticmethod
    def _create_vpk_file(ctx: BuildContext, filename: str, export_folder: str = "export", language: str = "en") -> str:
        """
        Создает VPK файл из vpkroot.
        
        Args:
            ctx: Контекст сборки
            filename: Имя выходного файла
            
        Returns:
            Путь к созданному VPK файлу
        """
        # vpk.exe создает файл с именем папки, т.е. vpkroot.vpk (это баг/особенность vpk.exe, но мы обходим переименованием)
        # Файл создается в директории vpkroot_dir (в родительской папке, потому что так работает vpk.exe - ебанутый формат)
        vpkroot_parent = os.path.dirname(ctx.vpkroot_dir)
        temp_vpk_path = os.path.join(vpkroot_parent, "vpkroot.vpk")
        
        # Отладочный вывод: проверяем содержимое vpkroot перед созданием VPK (на случай если что-то не так)
        logger.debug(f"Создание VPK из: {ctx.vpkroot_dir}")
        if ctx.vpkroot_dir.exists():
            logger.debug("Содержимое vpkroot_dir:")
            for root, dirs, files in os.walk(ctx.vpkroot_dir):
                level = root.replace(str(ctx.vpkroot_dir), '').count(os.sep)
                indent = ' ' * 2 * level
                logger.debug(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    logger.debug(f"{subindent}{file}")
        else:
            logger.warning(f"vpkroot_dir не существует: {ctx.vpkroot_dir}")
        
        # Удаляем существующий VPK если есть (чтобы не было конфликтов)
        temp_vpk_path_obj = Path(temp_vpk_path)
        if temp_vpk_path_obj.exists():
            temp_vpk_path_obj.unlink()
        
        # Создаем VPK
        # vpk.exe создает файл в той же директории где находится папка vpkroot (это особенность vpk.exe - ебанутый формат)
        logger.info("Запуск vpk.exe для создания VPK...")
        result = subprocess.run([
            str(VPKService._get_vpk_tool()),
            "-v", str(ctx.vpkroot_dir.resolve())
        ], cwd=str(vpkroot_parent), capture_output=True, text=True)
        
        logger.debug(f"vpk.exe завершился с кодом: {result.returncode}")
        if result.stdout:
            logger.debug(f"STDOUT: {result.stdout}")
        if result.stderr:
            logger.debug(f"STDERR: {result.stderr}")
        
        if result.returncode != 0:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            error_msg = t['error_vpk_creation_failed'].format(
                stdout=result.stdout,
                stderr=result.stderr
            )
            logger.error(f"Ошибка создания VPK: {error_msg}")
            raise VPKCreationError(result.stdout, result.stderr)
        
        if not temp_vpk_path_obj.exists():
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            error_msg = t['error_vpkroot_not_found'].format(path=vpkroot_parent)
            logger.error(error_msg)
            raise FileNotFoundError(temp_vpk_path, error_msg)
        
        # Перемещаем в export (переименовываем в нужное имя, потому что vpk.exe создает vpkroot.vpk - баг/особенность)
        export_folder_path = Path(export_folder)
        ensure_directory_exists(export_folder_path)
        final_output = export_folder_path / filename
        if final_output.exists():
            final_output.unlink()
        shutil.move(str(temp_vpk_path), str(final_output))
        
        # Логируем на английском (для логов используется английский)
        logger.info(f"VPK successfully created: {final_output}")
        return str(final_output)
    
    @staticmethod
    def _copy_compiled_models_to_vpkroot(ctx: BuildContext, qc_path: str) -> None:
        """
        Копирует скомпилированные файлы модели в vpkroot.
        
        Использует путь из $modelname в QC файле для создания правильной структуры директорий (чтобы модель загрузилась в игре).
        
        Args:
            ctx: Контекст сборки
            qc_path: Путь к QC файлу (для извлечения пути из $modelname)
        """
        # Извлекаем путь из $modelname в QC файле (это путь по которому модель должна лежать в VPK)
        modelname_path = ModelBuildService.extract_modelname_path(qc_path)
        if not modelname_path:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise FileNotFoundError(t['error_modelname_not_extracted'].format(qc_path=qc_path))
        
        # Нормализуем путь (заменяем обратные слеши на прямые, потому что QC может использовать оба)
        normalized_path = modelname_path.replace('\\', '/')
        path_parts = normalized_path.split('/')
        
        # Убираем имя файла (последняя часть), оставляем только путь к директории
        if len(path_parts) > 1:
            # Путь к директории без имени файла
            model_dir_path = '/'.join(path_parts[:-1])
        else:
            # Если путь состоит только из имени файла - используем корень models (fallback)
            model_dir_path = ""
        
        # Строим полный путь в vpkroot: models/<путь_из_modelname_без_имени_файла>
        # (чтобы структура папок была правильной для VPK)
        if model_dir_path:
            target_dir = ctx.vpkroot_dir / "models" / model_dir_path
        else:
            target_dir = ctx.vpkroot_dir / "models"
        
        ensure_directory_exists(target_dir)
        
        # Копируем только файлы модели из compile_dir которые соответствуют имени модели из $modelname
        if not ctx.compile_dir.exists():
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise FileNotFoundError(str(ctx.compile_dir), t['error_compile_dir_not_found'].format(path=ctx.compile_dir))
        
        # Извлекаем имя модели из $modelname (без расширения)
        model_filename = Path(modelname_path).name
        model_basename = Path(model_filename).stem
        
        # Находим только файлы модели которые начинаются с model_basename
        # Это предотвращает копирование файлов других моделей (например, bat при компиляции scattergun, потому что studiomdl компилирует все модели из QC)
        model_files = []
        for file_path in ctx.compile_dir.iterdir():
            if file_path.is_file():
                file_name = file_path.name
                # Проверяем, что файл начинается с model_basename и является файлом модели (MDL, VVD, VTX, PHY)
                if file_name.startswith(model_basename) and file_name.endswith(('.mdl', '.vvd', '.vtx', '.phy')):
                    model_files.append(file_name)
        
        if not model_files:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise FileNotFoundError(t['error_model_files_not_found'].format(path=ctx.compile_dir, model=model_basename))
        
        # Копируем файлы (все файлы модели нужны для загрузки в игре - MDL, VVD, VTX, PHY)
        logger.debug(f"Копируем {len(model_files)} файлов модели из {ctx.compile_dir} в {target_dir}")
        for file_name in model_files:
            src = ctx.compile_dir / file_name
            dst = target_dir / file_name
            logger.debug(f"Копируем: {file_name} -> {dst}")
            copy_file_safe(src, dst)
            logger.debug(f"Скопирован файл модели: {file_name}")
        
        logger.info(f"Все файлы модели скопированы в VPK root: {target_dir}")
    
    @staticmethod
    def _generate_uv_layout(ctx: BuildContext, weapon_key: str, image_size: Tuple[int, int], export_folder: str = "export", language: str = "en") -> None:
        """
        Генерирует UV разметку из SMD файла и сохраняет в export (это для отладки, чтобы видеть где какая часть текстуры).
        
        Args:
            ctx: Контекст сборки
            weapon_key: Ключ оружия
            image_size: Размер изображения для UV разметки
        """
        try:
            from src.services.uv_layout_service import UVLayoutService
            
            logger.info(f"Генерация UV разметки для оружия: {weapon_key}")
            logger.debug(f"Директория декомпиляции: {ctx.decompile_dir}")
            
            # Находим reference SMD файл (это оригинальная модель из игры, из которой мы берем UV координаты)
            smd_path = SMDService.find_reference_smd(str(ctx.decompile_dir), weapon_key)
            if not smd_path or not os.path.exists(smd_path):
                logger.warning(f"Не найден SMD файл для генерации UV разметки: {weapon_key}")
                logger.debug(f"Проверяемая директория: {ctx.decompile_dir}")
                if ctx.decompile_dir.exists():
                    smd_files = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')]
                    logger.debug(f"Найденные SMD файлы в директории: {smd_files}")
                return
            
            logger.debug(f"Найден SMD файл: {smd_path}")
            
            # Создаем имя файла для UV разметки (просто добавляем _uv_layout к имени оружия)
            uv_filename = f"{weapon_key}_uv_layout.png"
            uv_output_path = Path(export_folder) / uv_filename
            
            # Создаем папку export если её нет (на всякий случай)
            ensure_directory_exists(uv_output_path.parent)
            
            # Генерируем UV разметку (рисуем линии на картинке, показывающие где какая часть модели)
            if UVLayoutService.generate_uv_layout_from_smd(smd_path, str(uv_output_path), image_size):
                logger.info(f"UV разметка сохранена: {uv_output_path}")
            else:
                logger.error(f"Ошибка при создании UV разметки для {weapon_key}")
        except Exception as e:
            logger.error(f"Ошибка при генерации UV разметки: {e}", exc_info=True)
            # Не прерываем сборку из-за ошибки UV разметки (это не критично, просто отладочная фича)
