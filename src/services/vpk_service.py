"""
Вся хуйня с VPK файлами - распаковка, сборка, конвертация текстур.
Если что-то сломалось - виноват не я, а Valve с их ебанутым форматом.
"""

import os
import shutil
import time
import threading
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any, Callable
from .build_context import BuildContext
from .vmt_service import VMTService
from .build_service import BuildService
from .texture_service import TextureService
from .packaging_service import PackagingService
from .model_service import ModelService
from .tf2_vpk_extract_service import TF2VPKExtractService
from .model_build_service import ModelBuildService
from .tf2_paths import TF2Paths
from .debug_service import DebugService
from .smd_service import SMDService
from .decompile_cache import get_cached_decompile, restore_from_cache, save_to_cache
from src.data.weapons import SPECIAL_MODES, WEAPON_MDL_PATHS
from src.data.player_hands import HAND_MODE_KEYS
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
from src.shared.validators import validate_build_params

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
    def build_with_progress(
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
        replace_model_path: str = None,
        model_file_callback: Optional[Callable[[], Optional[str]]] = None,
        extra_texture_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        extra_model_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        language: str = "en",
        custom_vtf_path: str = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None
    ) -> Tuple[bool, str, bool]:
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit_progress(value: int, message: str) -> None:
            if progress_callback:
                progress_callback(value, message)

        def emit_sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())
        
        try:
            logger.info(f"Начало сборки VPK: {filename}")
            emit_progress(5, t.get('build_init', 'Initializing build...'))

            is_special_mode = mode in SPECIAL_MODES.values() or mode in HAND_MODE_KEYS

            _sub_label_init = "Preparing..." if language == "en" else "Подготовка..."
            emit_sub(-1, _sub_label_init)

            if is_special_mode:
                emit_progress(20, t.get('build_processing', 'Processing texture...'))

                success, message = VPKService.build_vpk(
                    image_path=image_path,
                    mode=mode,
                    filename=filename,
                    size=size,
                    format_type=format_type,
                    flags=flags,
                    vtf_options=vtf_options,
                    tf2_root_dir=tf2_root_dir,
                    export_folder=export_folder,
                    keep_temp_on_error=keep_temp_on_error,
                    debug_mode=debug_mode,
                    replace_model_enabled=replace_model_enabled,
                    draw_uv_layout=draw_uv_layout,
                    replace_model_path=replace_model_path,
                    model_file_callback=model_file_callback if replace_model_enabled else None,
                    extra_texture_callback=extra_texture_callback,
                    extra_model_callback=extra_model_callback,
                    language=language,
                    custom_vtf_path=custom_vtf_path,
                    sub_progress_callback=emit_sub,
                )

                if not is_cancelled():
                    emit_progress(60, t.get('build_packing', 'Creating VPK file...'))
            else:
                emit_progress(10, t.get('build_extracting', 'Extracting model...'))

                build_complete = threading.Event()
                build_result: List[Optional[object]] = [None, None]

                def update_progress() -> None:
                    stages = [
                        (25, t.get('build_decompiling', 'Decompiling model...')),
                        (40, t.get('build_processing', 'Processing texture...')),
                        (60, t.get('build_compiling', 'Compiling model...')),
                        (80, t.get('build_packing', 'Creating VPK file...')),
                    ]
                    for progress, status in stages:
                        if build_complete.is_set():
                            break
                        time.sleep(0.5)
                        if not is_cancelled():
                            emit_progress(progress, status)

                progress_thread = threading.Thread(target=update_progress, daemon=True)
                progress_thread.start()

                try:
                    success, message = VPKService.build_vpk(
                        image_path=image_path,
                        mode=mode,
                        filename=filename,
                        size=size,
                        format_type=format_type,
                        flags=flags,
                        vtf_options=vtf_options,
                        tf2_root_dir=tf2_root_dir,
                        export_folder=export_folder,
                        keep_temp_on_error=keep_temp_on_error,
                        debug_mode=debug_mode,
                        replace_model_enabled=replace_model_enabled,
                        draw_uv_layout=draw_uv_layout,
                        replace_model_path=replace_model_path,
                        model_file_callback=model_file_callback if replace_model_enabled else None,
                        extra_texture_callback=extra_texture_callback,
                        extra_model_callback=extra_model_callback,
                        language=language,
                        custom_vtf_path=custom_vtf_path,
                        sub_progress_callback=emit_sub,
                    )
                    build_result[0] = success
                    build_result[1] = message
                finally:
                    build_complete.set()
                    progress_thread.join(timeout=1.0)

                success, message = build_result[0], build_result[1]

            if is_cancelled():
                return False, t.get('build_cancelled', 'Build cancelled by user'), True

            if success:
                emit_sub(100, "Done" if language == "en" else "Готово")
                emit_progress(100, t.get('build_completed', 'Build completed'))
                return True, message, False

            emit_progress(0, t.get('build_error_status', 'Build error'))
            return False, message, False
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при сборке: {error_msg}", exc_info=True)
            emit_progress(0, t.get('build_critical_error', 'Critical error'))
            return False, error_msg, False
    
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
        extra_texture_callback=None,  # Колбэк для запроса доп. текстуры: callback(material_name, weapon_key) -> Optional[str]
        extra_model_callback=None,  # Колбэк для запроса доп. модели: callback(smd_name, weapon_key) -> Optional[str]
        language: str = "en",  # Язык для ошибок
        custom_vtf_path: str = None,  # Если юзер сам сделал VTF - используем его вместо генерации из картинки
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Главная функция - делает из картинки VPK файл. 
        Если что-то пойдет не так - вернет False и описание проблемы.
        Вся эта хуйня с моделями, текстурами и VPK - тут.
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit_sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

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
                result = BuildService.build_special_mode_vpk(
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

            elif mode in HAND_MODE_KEYS:
                # Руки персонажей: только VTF, никакой модели/VMT
                from src.services.hands_build_service import HandsBuildService
                emit_sub(-1, "Processing hand textures..." if language == "en" else "Обработка текстур рук...")
                success, error_msg = HandsBuildService.build(
                    ctx=ctx,
                    mode=mode,
                    image_path=image_path,
                    size=size,
                    format_type=format_type,
                    flags=flags,
                    vtf_options=vtf_options,
                    keep_temp_on_error=keep_temp_on_error,
                    debug_mode=debug_mode,
                    language=language,
                    custom_vtf_path=custom_vtf_path,
                    extra_texture_callback=extra_texture_callback,
                    sub_progress_callback=emit_sub,
                )
                if not success:
                    return False, error_msg

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

                    # === Кэш декомпила — проверяем ДО extraction ===
                    # Ключ: weapon_key + vpk_path + mdl_rel_path + mtime(vpk).
                    # mtime VPK меняется при каждом обновлении TF2 → авто-инвалидация.
                    # При cache hit: пропускаем extract_file_set (3-10 сек) + Crowbar (10-30 сек).
                    cached_decompile = get_cached_decompile(weapon_key, tf2_misc_vpk, found_mdl_path)

                    if cached_decompile:
                        # === CACHE HIT: пропускаем extraction и decompile ===
                        emit_sub(-1, "Restoring cache..." if language == "en" else "Восстановление кэша...")
                        qc_path = restore_from_cache(cached_decompile, ctx.decompile_dir)
                    else:
                        # === CACHE MISS: извлекаем и декомпилируем ===
                        emit_sub(-1, "Extracting model..." if language == "en" else "Извлечение модели...")
                        logger.info(f"Извлекаем файлы модели: {found_mdl_path}")
                        extracted_files = TF2VPKExtractService.extract_file_set(
                            tf2_misc_vpk,
                            found_mdl_path,
                            str(ctx.extract_dir),
                            str(VPKService._get_vpk_tool())
                        )
                        
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
                        
                        emit_sub(-1, "Decompiling model..." if language == "en" else "Декомпиляция модели...")
                        logger.info(f"Запускаем Crowbar для {weapon_key}...")
                        qc_path = ModelBuildService.decompile(
                            mdl_file,
                            ctx.decompile_dir,
                            crowbar_exe
                        )
                        if debug_mode:
                            DebugService.save_decompiled_stage(ctx, ctx.decompile_dir)

                    if draw_uv_layout:
                        VPKService._generate_uv_layout(ctx, weapon_key, size, export_folder, language)

                    # Удаляем LOD файлы до кэширования — чтобы в кэше лежали уже чистые файлы
                    ModelBuildService.remove_lod_files(ctx.decompile_dir)

                    # Сохраняем в кэш после очистки — следующая сборка пропустит extraction + decompile
                    if not cached_decompile:
                        save_to_cache(weapon_key, tf2_misc_vpk, found_mdl_path, ctx.decompile_dir)
                    
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
                                emit_sub(-1, "Replacing model..." if language == "en" else "Замена модели...")
                                # Заменяем секции: nodes и skeleton из оригинального (иначе модель не скомпилируется),
                                # названия материалов из оригинального (иначе текстуры не загрузятся),
                                # данные треугольников из пользовательского (это то, что юзер хочет заменить)
                                SMDService.replace_model_sections(
                                    replace_model_smd_path,
                                    original_smd_path,
                                    original_smd_path,  # Перезаписываем оригинальный файл под тем же именем
                                    progress_cb=lambda pct: emit_sub(pct, "Replacing model..." if language == "en" else "Замена модели..."),
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
                    
                    # === Замена дополнительных частей модели (shell, scope и т.д.) ===
                    # Проверяем, есть ли в QC файле дополнительные bodygroup SMD
                    extra_body_smds = ModelBuildService.extract_extra_body_smds(qc_path, weapon_key)
                    if extra_body_smds:
                        extra_smd_names = [os.path.basename(s) for s in extra_body_smds]
                        logger.info(f"Найдены дополнительные части модели: {extra_smd_names}")
                        
                        if extra_model_callback:
                            for extra_smd_path in extra_body_smds:
                                extra_smd_name = os.path.basename(extra_smd_path)
                                extra_smd_base = os.path.splitext(extra_smd_name)[0]
                                
                                try:
                                    # Спрашиваем пользователя через callback
                                    user_extra_smd = extra_model_callback(extra_smd_base, weapon_key)
                                    
                                    if user_extra_smd and os.path.exists(user_extra_smd):
                                        logger.info(f"Заменяем доп. часть модели: {user_extra_smd} -> {extra_smd_path}")
                                        emit_sub(-1, f"Replacing {extra_smd_base}..." if language == "en" else f"Замена {extra_smd_base}...")
                                        SMDService.replace_model_sections(
                                            user_extra_smd,
                                            extra_smd_path,
                                            extra_smd_path,  # Перезаписываем оригинал
                                            progress_cb=lambda pct: emit_sub(pct, f"Replacing {extra_smd_base}..." if language == "en" else f"Замена {extra_smd_base}..."),
                                        )
                                        logger.info(f"Доп. часть модели успешно заменена: {extra_smd_name}")
                                    else:
                                        logger.info(f"Пользователь пропустил замену доп. части: {extra_smd_name}")
                                except Exception as e:
                                    logger.error(f"Ошибка при замене доп. части модели {extra_smd_name}: {e}", exc_info=True)
                        else:
                            logger.debug(f"Нет callback для замены доп. частей модели, пропускаем")
                    
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
                    
                    # Извлекаем полную структуру $texturegroup для поддержки:
                    # 1. BLU команды (отдельная строка/row в texturegroup)
                    # 2. Дополнительных материалов (shell, scope и т.д. - столбцы/columns)
                    tg_structure = ModelBuildService.extract_texturegroup_structure(qc_path)
                    blu_row = tg_structure.get('blu_row', [])
                    extra_materials = tg_structure.get('extra_materials', [])
                    
                    if blu_row:
                        logger.info(f"Найдена BLU команда: {blu_row}")
                    if extra_materials:
                        logger.info(f"Найдены дополнительные материалы модели: {extra_materials}")
                    
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
                    
                    # Компиляция и создание текстур независимы — запускаем studiomdl в фоне
                    # параллельно с тем, как главный поток занимается VTF/VMT
                    _compile_exc: list = [None]
                    def _do_compile() -> None:
                        try:
                            emit_sub(-1, "Compiling model..." if language == "en" else "Компиляция модели...")
                            ModelBuildService.compile(qc_path, ctx.compile_dir, studiomdl_exe, tf_dir)
                            if debug_mode:
                                DebugService.save_compiled_stage(ctx, ctx.compile_dir)
                        except Exception as _e:
                            _compile_exc[0] = _e
                    _compile_thread = threading.Thread(target=_do_compile, daemon=True)
                    _compile_thread.start()

                    is_normal_map = False
                    animated_fps = None
                    if custom_vtf_path:
                        # Если юзер сам сделал VTF - просто копируем его, не генерируем из картинки
                        vtf_file_path = vtf_output_path / vtf_filename
                        ensure_directory_exists(vtf_output_path)
                        copy_file_safe(custom_vtf_path, vtf_file_path)
                        logger.info(f"Использован пользовательский VTF файл: {custom_vtf_path} -> {vtf_file_path}")
                    else:
                        # Разделяем флаги на опции VTFCmd и флаги VTF (потому что они передаются по-разному)
                        vtf_flags, flags_parsed_options = VPKService._parse_vtf_flags_and_options(flags)
                        
                        # Объединяем опции из UI с опциями из флагов (UI имеет приоритет, но флаги могут переопределить)
                        merged_options = {}
                        if vtf_options:
                            merged_options.update(vtf_options)
                        merged_options.update(flags_parsed_options)
                        
                        is_normal_map = merged_options.get("normal", False)

                        if TextureService.is_animated_image(image_path):
                            vtf_file_path = vtf_output_path / vtf_filename
                            animated_fps = TextureService.create_animated_vtf(
                                image_path,
                                str(vtf_file_path),
                                size,
                                format_type,
                                vtf_flags,
                                merged_options
                            )
                            logger.info(f"Создана анимированная VTF текстура: {vtf_filename}")
                        else:
                            VPKService._process_image(image_path, vtf_temp_png, size)
                            if is_normal_map:
                                normal_options = merged_options.copy()
                                normal_options.pop("normal", None)
                                VPKService._create_vtf(str(vtf_temp_png), str(vtf_output_path), format_type, vtf_flags, normal_options)
                                logger.info(f"Создана обычная VTF текстура: {vtf_filename}")
                                normal_vtf_filename = f"{texture_filename}_normal.vtf"
                                normal_temp_png = vtf_output_path / f"{texture_filename}_normal.png"
                                import shutil
                                shutil.copy2(vtf_temp_png, normal_temp_png)
                                normal_options_normal = {"normal": True}
                                VPKService._create_vtf(str(normal_temp_png), str(vtf_output_path), format_type, [], normal_options_normal)
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

                    if animated_fps:
                        VMTService.enable_animated_basetexture(str(vmt_path), animated_fps)
                    
                    # Если normal map включена, обновляем VMT файл для добавления $bumpmap
                    # (это нужно для бампмаппинга, иначе нормалмап не загрузится)
                    if is_normal_map:
                        normal_weapon_key = f"{texture_filename}_normal"
                        VMTService.update_vmt_bumpmap_path(str(vmt_path), patched_cdmaterials_path, normal_weapon_key)
                        logger.info(f"Обновлен VMT файл для добавления $bumpmap: {normal_weapon_key}")
                    
                    # === Создаем текстуры для дополнительных материалов модели (shell, scope и т.д.) ===
                    # Это столбцы 1+ из RED строки $texturegroup
                    # Словарь для хранения путей к VTF дополнительных материалов (нужно для BLU копий)
                    extra_materials_vtf_paths = {}
                    
                    for extra_mat_name in extra_materials:
                        logger.info(f"Создаем текстуры для дополнительного материала: {extra_mat_name}")
                        
                        extra_vtf_filename = f"{extra_mat_name}.vtf"
                        extra_vmt_filename = f"{extra_mat_name}.vmt"
                        extra_vtf_path = vtf_output_path / extra_vtf_filename
                        extra_vmt_path = vtf_output_path / extra_vmt_filename
                        
                        # Спрашиваем у пользователя отдельное изображение для этого материала
                        extra_image_path = None
                        if extra_texture_callback:
                            extra_image_path = extra_texture_callback(extra_mat_name, weapon_key)
                            logger.info(f"Результат extra_texture_callback для '{extra_mat_name}': {extra_image_path!r}")
                            if extra_image_path and not os.path.isfile(extra_image_path):
                                logger.warning(f"Файл не найден: {extra_image_path}")
                                extra_image_path = None
                        
                        if extra_image_path and os.path.isfile(extra_image_path):
                            # Пользователь предоставил отдельное изображение для этого материала
                            logger.info(f"Используем отдельное изображение для {extra_mat_name}: {extra_image_path}")
                            
                            if custom_vtf_path:
                                # Пользователь использует VTF - копируем
                                copy_file_safe(extra_image_path, extra_vtf_path)
                            elif TextureService.is_animated_image(extra_image_path):
                                vtf_flags_extra, flags_parsed_extra = VPKService._parse_vtf_flags_and_options(flags)
                                merged_extra = {}
                                if vtf_options:
                                    merged_extra.update(vtf_options)
                                merged_extra.update(flags_parsed_extra)
                                TextureService.create_animated_vtf(
                                    extra_image_path, str(extra_vtf_path),
                                    size, format_type, vtf_flags_extra, merged_extra
                                )
                            else:
                                extra_temp_png = vtf_output_path / f"{extra_mat_name}.png"
                                VPKService._process_image(extra_image_path, extra_temp_png, size)
                                vtf_flags_extra, flags_parsed_extra = VPKService._parse_vtf_flags_and_options(flags)
                                merged_extra = {}
                                if vtf_options:
                                    merged_extra.update(vtf_options)
                                merged_extra.update(flags_parsed_extra)
                                merged_extra.pop("normal", None)
                                VPKService._create_vtf(str(extra_temp_png), str(vtf_output_path), format_type, vtf_flags_extra, merged_extra)
                                if extra_temp_png.exists():
                                    extra_temp_png.unlink()
                        else:
                            # Пользователь не предоставил изображение - копируем основную текстуру
                            red_vtf_path = vtf_output_path / vtf_filename
                            if red_vtf_path.exists():
                                copy_file_safe(red_vtf_path, extra_vtf_path)
                                logger.info(f"Скопирована основная текстура для доп. материала: {vtf_filename} -> {extra_vtf_filename}")
                            else:
                                logger.warning(f"Основной VTF не найден для копирования: {red_vtf_path}")
                        
                        extra_materials_vtf_paths[extra_mat_name] = extra_vtf_path
                        
                        # Создаем VMT для дополнительного материала
                        if vmt_path.exists():
                            copy_file_safe(vmt_path, extra_vmt_path)
                            VMTService.update_vmt_basetexture_path(str(extra_vmt_path), patched_cdmaterials_path, extra_mat_name)
                            logger.info(f"Создан VMT для доп. материала: {extra_vmt_filename}")
                        else:
                            VMTService.create_vmt_template_from_cdmaterials(str(extra_vmt_path), patched_cdmaterials_path, extra_mat_name)
                            logger.info(f"Создан VMT из шаблона для доп. материала: {extra_vmt_filename}")
                        
                        if animated_fps:
                            VMTService.enable_animated_basetexture(str(extra_vmt_path), animated_fps)
                    
                    # === Создаем текстуры для BLU команды ===
                    # BLU - это отдельная строка (row 1) в $texturegroup
                    # Для каждого материала в BLU строке спрашиваем отдельное изображение,
                    # если пользователь отказывается — копируем соответствующую RED текстуру
                    if blu_row:
                        red_row = tg_structure.get('red_row', [])
                        
                        for col_idx, blu_tex_name in enumerate(blu_row):
                            # Находим соответствующее RED имя для этого столбца
                            red_tex_name = red_row[col_idx] if col_idx < len(red_row) else None
                            
                            if not red_tex_name:
                                logger.warning(f"Нет соответствующей RED текстуры для BLU столбца {col_idx}: {blu_tex_name}")
                                continue
                            
                            # Если BLU имя совпадает с RED - пропускаем (текстура одна и та же)
                            if blu_tex_name == red_tex_name:
                                logger.debug(f"BLU текстура совпадает с RED, пропускаем: {blu_tex_name}")
                                continue
                            
                            logger.info(f"Создаем текстуры для BLU команды: {blu_tex_name} (RED: {red_tex_name})")
                            
                            blu_vtf_filename = f"{blu_tex_name}.vtf"
                            blu_vmt_filename = f"{blu_tex_name}.vmt"
                            blu_vtf_path = vtf_output_path / blu_vtf_filename
                            blu_vmt_path = vtf_output_path / blu_vmt_filename
                            
                            # Спрашиваем у пользователя отдельное изображение для BLU материала
                            blu_image_path = None
                            if extra_texture_callback:
                                blu_image_path = extra_texture_callback(blu_tex_name, weapon_key)
                                logger.info(f"Результат extra_texture_callback для BLU '{blu_tex_name}': {blu_image_path!r}")
                                if blu_image_path and not os.path.isfile(blu_image_path):
                                    logger.warning(f"Файл BLU не найден: {blu_image_path}")
                                    blu_image_path = None
                            
                            if blu_image_path and os.path.isfile(blu_image_path):
                                # Пользователь дал отдельное изображение для этого BLU материала
                                logger.info(f"Используем отдельное изображение для BLU {blu_tex_name}: {blu_image_path}")
                                if custom_vtf_path:
                                    copy_file_safe(blu_image_path, blu_vtf_path)
                                elif TextureService.is_animated_image(blu_image_path):
                                    vtf_flags_blu, flags_parsed_blu = VPKService._parse_vtf_flags_and_options(flags)
                                    merged_blu = {}
                                    if vtf_options:
                                        merged_blu.update(vtf_options)
                                    merged_blu.update(flags_parsed_blu)
                                    merged_blu.pop("normal", None)
                                    TextureService.create_animated_vtf(
                                        blu_image_path, str(blu_vtf_path),
                                        size, format_type, vtf_flags_blu, merged_blu
                                    )
                                else:
                                    blu_temp_png = vtf_output_path / f"{blu_tex_name}.png"
                                    VPKService._process_image(blu_image_path, blu_temp_png, size)
                                    vtf_flags_blu, flags_parsed_blu = VPKService._parse_vtf_flags_and_options(flags)
                                    merged_blu = {}
                                    if vtf_options:
                                        merged_blu.update(vtf_options)
                                    merged_blu.update(flags_parsed_blu)
                                    merged_blu.pop("normal", None)
                                    VPKService._create_vtf(str(blu_temp_png), str(vtf_output_path), format_type, vtf_flags_blu, merged_blu)
                                    if blu_temp_png.exists():
                                        blu_temp_png.unlink()
                            else:
                                # Пользователь отказался — копируем VTF из соответствующего RED материала
                                # Ищем RED VTF: может быть основная текстура или extra_materials VTF
                                if col_idx == 0:
                                    red_vtf_src = vtf_output_path / f"{red_tex_name}.vtf"
                                else:
                                    red_vtf_src = extra_materials_vtf_paths.get(red_tex_name,
                                                  vtf_output_path / f"{red_tex_name}.vtf")
                                if red_vtf_src.exists():
                                    copy_file_safe(red_vtf_src, blu_vtf_path)
                                    logger.info(f"Скопирован VTF для BLU: {red_tex_name}.vtf -> {blu_vtf_filename}")
                                else:
                                    logger.warning(f"RED VTF не найден для BLU копии: {red_vtf_src}")
                            
                            # Создаем VMT для BLU (копируем RED VMT и обновляем $basetexture)
                            red_vmt_src = vtf_output_path / f"{red_tex_name}.vmt"
                            if red_vmt_src.exists():
                                copy_file_safe(red_vmt_src, blu_vmt_path)
                                VMTService.update_vmt_basetexture_path(str(blu_vmt_path), patched_cdmaterials_path, blu_tex_name)
                                logger.info(f"Создан VMT для BLU: {blu_vmt_filename}")
                            else:
                                VMTService.create_vmt_template_from_cdmaterials(str(blu_vmt_path), patched_cdmaterials_path, blu_tex_name)
                                logger.info(f"Создан VMT из шаблона для BLU: {blu_vmt_filename}")
                            
                            if animated_fps:
                                VMTService.enable_animated_basetexture(str(blu_vmt_path), animated_fps)
                            
                            # Normal map для BLU
                            if is_normal_map:
                                blu_normal_vtf = f"{blu_tex_name}_normal.vtf"
                                red_normal_vtf = vtf_output_path / f"{red_tex_name}_normal.vtf"
                                blu_normal_vtf_path = vtf_output_path / blu_normal_vtf
                                
                                if red_normal_vtf.exists():
                                    copy_file_safe(red_normal_vtf, blu_normal_vtf_path)
                                    logger.info(f"Скопирован normal VTF для BLU: {blu_normal_vtf}")
                                
                                blu_normal_key = f"{blu_tex_name}_normal"
                                VMTService.update_vmt_bumpmap_path(str(blu_vmt_path), patched_cdmaterials_path, blu_normal_key)
                                logger.info(f"Обновлен VMT $bumpmap для BLU: {blu_normal_key}")
                    
                    if debug_mode:
                        DebugService.save_patched_stage(ctx, ctx.decompile_dir)
                    
                    # Ждём завершения компиляции (шла параллельно с текстурами)
                    _compile_thread.join()
                    if _compile_exc[0] is not None:
                        raise _compile_exc[0]

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
            emit_sub(-1, "Packing VPK..." if language == "en" else "Упаковка VPK...")
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

            backup_vmt_dir = Path("tools/backupVMT")
            if backup_vmt_dir.exists():
                try:
                    for file_path in backup_vmt_dir.iterdir():
                        try:
                            if file_path.is_file() or file_path.is_symlink():
                                file_path.unlink()
                            elif file_path.is_dir():
                                shutil.rmtree(file_path)
                        except Exception as e:
                            logger.warning(f"Не удалось удалить {file_path}: {e}", exc_info=True)
                    logger.debug("Очищена папка backupVMT")
                except Exception as e:
                    logger.warning(f"Не удалось очистить папку backupVMT: {e}", exc_info=True)
            
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
        return BuildService.build_special_mode_vpk(
            ctx,
            mode,
            image_path,
            size,
            format_type,
            flags,
            vtf_options,
            keep_temp_on_error,
            debug_mode,
            language,
            custom_vtf_path
        )
    
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
        return validate_build_params(
            image_path,
            mode,
            filename,
            size,
            format_type,
            tf2_root_dir,
            t,
            custom_vtf_path
        )
    
    @staticmethod
    def _process_image(input_path: str, output_path: str, size: Tuple[int, int]) -> None:
        return TextureService.process_image(input_path, output_path, size)
    
    @staticmethod
    def _parse_vtf_flags_and_options(flags: List[str]) -> Tuple[List[str], dict]:
        return TextureService.parse_vtf_flags_and_options(flags)
    
    @staticmethod
    def _create_vtf(png_path: str, output_path: str, format_type: str, flags: List[str], 
                   options: dict = None) -> None:
        return TextureService.create_vtf(png_path, output_path, format_type, flags, options)
    
    @staticmethod
    def _create_vpk_file(ctx: BuildContext, filename: str, export_folder: str = "export", language: str = "en") -> str:
        return PackagingService.create_vpk_file(ctx, filename, export_folder, language)
    
    @staticmethod
    def _copy_compiled_models_to_vpkroot(ctx: BuildContext, qc_path: str) -> None:
        return ModelService.copy_compiled_models_to_vpkroot(ctx, qc_path)
    
    @staticmethod
    def _generate_uv_layout(ctx: BuildContext, weapon_key: str, image_size: Tuple[int, int], export_folder: str = "export", language: str = "en") -> None:
        return ModelService.generate_uv_layout(ctx, weapon_key, image_size, export_folder, language)
