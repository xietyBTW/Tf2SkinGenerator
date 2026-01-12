"""
Сервис для работы с VPK файлами
"""

import os
import shutil
import subprocess
from typing import Tuple, List, Optional
from PIL import Image
from .build_context import BuildContext
from .vmt_service import VMTService
from .tf2_vpk_extract_service import TF2VPKExtractService
from .model_build_service import ModelBuildService
from .tf2_paths import TF2Paths
from .debug_service import DebugService
from .smd_service import SMDService
from src.data.weapons import SPECIAL_MODES, WEAPON_MDL_PATHS


class VPKService:
    """Сервис для создания VPK файлов"""
    
    VTF_TOOL_PATH = "tools/VTF/VTFCmd.exe"
    VPK_TOOL_PATH = "tools/VPK/vpk.exe"
    CROWBAR_PATH = "tools/crowbar/CrowbarCommandLineDecomp.exe"
    
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
        parent_window=None,  # Для показа диалогов
        replace_model_path: str = None,  # Путь к модели для замены (для тестового режима)
        language: str = "en",  # Язык для сообщений об ошибках
        custom_vtf_path: str = None  # Путь к пользовательскому VTF файлу (если указан, используется вместо создания из изображения)
    ) -> Tuple[bool, str]:
        """
        Создает VPK файл из изображения с автоматической сборкой моделей
        
        Args:
            image_path: Путь к исходному изображению
            mode: Режим оружия
            filename: Имя выходного файла
            size: Размер изображения (width, height)
            format_type: Формат VTF
            flags: Флаги VTF (CLAMPS, CLAMPT, NOLOD, etc.)
            vtf_options: Опции VTFCmd (nomipmaps, nothumbnail, noreflectivity, gamma, etc.)
            tf2_root_dir: Корневая директория TF2 (steamapps/common/Team Fortress 2)
            export_folder: Папка для экспорта файлов (по умолчанию "export")
            keep_temp_on_error: Сохранить временные файлы при ошибке
            debug_mode: Режим отладки (сохраняет состояние на каждом этапе)
            replace_model_enabled: Включена ли замена модели (диалог выбора покажется после декомпиляции)
            parent_window: Родительское окно для диалогов
            language: Язык для сообщений об ошибках (по умолчанию "en")
            
        Returns:
            Tuple[success, message]
        """
        # Загружаем переводы
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        
        ctx = None
        try:
            # Валидация входных данных
            # Если используется custom_vtf_path, пропускаем проверку image_path
            validation_error = VPKService._validate_build_params(
                image_path, mode, filename, size, format_type, tf2_root_dir, t, custom_vtf_path
            )
            if validation_error:
                return False, validation_error
            
            if flags is None:
                flags = []
            
            # Извлекаем weapon_key
            weapon_key = mode.split('_', 1)[1] if '_' in mode else mode
            
            # Переменная для хранения ключа VMT, который нужно удалить после сборки
            vmt_to_delete = None
            
            # Создаем контекст сборки
            ctx = BuildContext.create(mode, weapon_key, debug_mode=debug_mode)
            
            # Для специальных режимов создаем текстуры сразу
            if mode in SPECIAL_MODES.values():
                result = VPKService._build_special_mode_vpk(
                    ctx, mode, image_path, size, format_type, flags, vtf_options,
                    keep_temp_on_error, debug_mode, language, custom_vtf_path
                )
                if not result[0]:
                    # В случае ошибки возвращаем только success и message (для обратной совместимости)
                    return result[0], result[1]
                # Если был использован отредактированный VMT, получаем его имя для удаления
                if len(result) > 2 and result[2]:
                    vmt_to_delete = result[2]
                else:
                    vmt_to_delete = None
            else:
                # Для обычного оружия - сначала декомпилируем, затем создаем текстуры с путем из QC
                # Проверяем, что TF2 root dir задан
                if not tf2_root_dir:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_tf2_not_specified']
                
                # Проверяем Crowbar
                crowbar_exists, crowbar_error = TF2Paths.check_crowbar()
                if not crowbar_exists:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, crowbar_error
                
                # Разрешаем пути TF2
                try:
                    studiomdl_exe, tf2_misc_vpk, tf_dir = TF2Paths.resolve(tf2_root_dir)
                except FileNotFoundError as e:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, str(e)
                
                # Проверяем, что weapon_key есть в WEAPON_MDL_PATHS
                if weapon_key not in WEAPON_MDL_PATHS:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_weapon_not_found'].format(weapon_key=weapon_key)
                
                # Формируем пути для поиска MDL файла в порядке приоритета:
                # 1. models/workshop_partner/weapons/c_models (самый приоритетный - здесь хранятся папки с оружиями)
                # 2. models/workshop/weapons/c_models (приоритетный путь)
                # 3. models/weapons/c_models (резервный путь)
                # 4. models/weapons/c_items (альтернативный путь для некоторых оружий)
                # 5. models/player/items/{class_name} (последний путь - низкий приоритет, здесь папки с классами)
                # Для каждого пути пробуем два варианта: с подпапкой и без подпапки
                
                # Базовый путь из WEAPON_MDL_PATHS: models/weapons/c_models/{weapon_key}/{weapon_key}.mdl
                base_path_from_config = WEAPON_MDL_PATHS[weapon_key]
                
                # Создаем список путей для проверки в порядке приоритета
                paths_to_try = []
                
                # 0. САМЫЙ ПРИОРИТЕТНЫЙ путь: models/workshop_partner/weapons/c_models/{weapon_key}/{weapon_key}.mdl
                # Здесь хранятся папки с оружиями, проверяем первым
                workshop_partner_path_with_folder = base_path_from_config.replace("models/weapons/", "models/workshop_partner/weapons/")
                paths_to_try.append(workshop_partner_path_with_folder)
                
                # 0.1. САМЫЙ ПРИОРИТЕТНЫЙ путь без подпапки: models/workshop_partner/weapons/c_models/{weapon_key}.mdl
                if f"/{weapon_key}/{weapon_key}.mdl" in workshop_partner_path_with_folder:
                    workshop_partner_path_no_folder = workshop_partner_path_with_folder.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(workshop_partner_path_no_folder)
                
                # 1. Приоритетный путь: models/workshop/weapons/c_models/{weapon_key}/{weapon_key}.mdl
                workshop_path_with_folder = base_path_from_config.replace("models/weapons/", "models/workshop/weapons/")
                paths_to_try.append(workshop_path_with_folder)
                
                # 2. Приоритетный путь без подпапки: models/workshop/weapons/c_models/{weapon_key}.mdl
                if f"/{weapon_key}/{weapon_key}.mdl" in workshop_path_with_folder:
                    workshop_path_no_folder = workshop_path_with_folder.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(workshop_path_no_folder)
                
                # 3. Резервный путь: models/weapons/c_models/{weapon_key}/{weapon_key}.mdl
                paths_to_try.append(base_path_from_config)
                
                # 4. Резервный путь без подпапки: models/weapons/c_models/{weapon_key}.mdl
                if f"/{weapon_key}/{weapon_key}.mdl" in base_path_from_config:
                    fallback_path_no_folder = base_path_from_config.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(fallback_path_no_folder)
                
                # 5. Альтернативный путь: models/weapons/c_items/{weapon_key}/{weapon_key}.mdl (для некоторых оружий)
                c_items_path_with_folder = base_path_from_config.replace("models/weapons/c_models/", "models/weapons/c_items/")
                paths_to_try.append(c_items_path_with_folder)
                
                # 6. Альтернативный путь без подпапки: models/weapons/c_items/{weapon_key}.mdl
                if f"/{weapon_key}/{weapon_key}.mdl" in c_items_path_with_folder:
                    c_items_path_no_folder = c_items_path_with_folder.replace(f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl")
                    paths_to_try.append(c_items_path_no_folder)
                
                # 7. ПОСЛЕДНИЙ ПУТЬ (низкий приоритет): models/player/items/{class_name}/{weapon_key}.mdl
                # Здесь хранятся папки с названиями классов, внутри которых mdl файлы
                # Извлекаем имя класса из mode (формат: {class_name.lower()}_{weapon_key})
                if '_' in mode:
                    class_name_lower = mode.split('_', 1)[0]  # Получаем scout, soldier и т.д.
                    
                    # Вариант с подпапкой: models/player/items/{class_name}/{weapon_key}/{weapon_key}.mdl
                    player_items_path_with_folder = f"models/player/items/{class_name_lower}/{weapon_key}/{weapon_key}.mdl"
                    paths_to_try.append(player_items_path_with_folder)
                    
                    # Вариант без подпапки: models/player/items/{class_name}/{weapon_key}.mdl
                    player_items_path_no_folder = f"models/player/items/{class_name_lower}/{weapon_key}.mdl"
                    paths_to_try.append(player_items_path_no_folder)
                
                crowbar_exe = TF2Paths.get_crowbar_path()
                
                try:
                    # ОПТИМИЗАЦИЯ: Сначала проверяем существование MDL файла по каждому пути
                    # Только после нахождения - извлекаем все файлы
                    # Это быстрее, т.к. не извлекаем лишние файлы для несуществующих путей
                    found_mdl_path = None
                    last_error = None
                    
                    # Быстрая проверка существования MDL по всем путям (без извлечения файлов)
                    for mdl_rel_path in paths_to_try:
                        try:
                            print(f"Проверяем наличие MDL по пути: {mdl_rel_path}")
                            if TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, mdl_rel_path):
                                found_mdl_path = mdl_rel_path
                                print(f"✓ MDL файл найден по пути: {mdl_rel_path}")
                                break
                            else:
                                print(f"✗ MDL файл не найден по пути: {mdl_rel_path}")
                        except Exception as e:
                            print(f"Ошибка при проверке пути {mdl_rel_path}: {str(e)}")
                            last_error = e
                            continue
                    
                    # Если MDL не найден - возвращаем ошибку
                    if not found_mdl_path:
                        paths_str = "\n".join([f"  - {path}" for path in paths_to_try])
                        error_msg = t['error_mdl_not_found'].format(paths=paths_str, vpk_file=tf2_misc_vpk)
                        if last_error:
                            error_msg += f"\n{str(last_error)}"
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, error_msg
                    
                    # Теперь извлекаем все файлы модели для найденного пути
                    print(f"Извлекаем все файлы модели по найденному пути: {found_mdl_path}")
                    extracted_files = TF2VPKExtractService.extract_file_set(
                        tf2_misc_vpk,
                        found_mdl_path,
                        ctx.extract_dir,
                        VPKService.VPK_TOOL_PATH
                    )
                    
                    # Находим .mdl файл среди извлеченных
                    mdl_file = None
                    for file_path in extracted_files:
                        if file_path.endswith('.mdl'):
                            mdl_file = file_path
                            break
                    
                    if not mdl_file:
                        error_msg = t['error_mdl_not_extracted'].format(path=found_mdl_path)
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, error_msg
                    
                    # Сохраняем состояние отладки: этап 1 - после извлечения MDL
                    if debug_mode:
                        DebugService.save_extracted_stage(ctx, extracted_files)
                    
                    # Декомпилируем модель
                    qc_path = ModelBuildService.decompile(
                        mdl_file,
                        ctx.decompile_dir,
                        crowbar_exe
                    )
                    
                    # Сохраняем состояние отладки: этап 2 - после декомпиляции
                    if debug_mode:
                        DebugService.save_decompiled_stage(ctx, ctx.decompile_dir)
                    
                    # Генерируем UV разметку, если включено
                    if draw_uv_layout:
                        VPKService._generate_uv_layout(ctx, weapon_key, size, export_folder, language)
                    
                    # Удаляем LOD файлы из декомпилированной директории
                    ModelBuildService.remove_lod_files(ctx.decompile_dir)
                    
                    # Заменяем модель, если включен режим замены
                    # Диалог выбора файла показываем здесь, после декомпиляции
                    replace_model_smd_path = None
                    if replace_model_enabled:
                        # Если передан путь модели напрямую (для тестового режима), используем его
                        if replace_model_path and os.path.exists(replace_model_path):
                            replace_model_smd_path = replace_model_path
                            print(f"Используется предустановленный файл для замены модели: {replace_model_smd_path}")
                        elif parent_window:
                            # Показываем диалог выбора SMD файла
                            from PySide6.QtWidgets import QFileDialog
                            
                            file_path, _ = QFileDialog.getOpenFileName(
                                parent_window,
                                "Выберите SMD файл модели для замены",
                                "",
                                "SMD Files (*.smd);;All Files (*)"
                            )
                            
                            if file_path and os.path.exists(file_path):
                                replace_model_smd_path = file_path
                                print(f"Выбран файл для замены модели: {replace_model_smd_path}")
                            else:
                                # Пользователь отменил выбор - продолжаем без замены
                                print("Выбор SMD файла отменен, продолжаем без замены модели")
                        else:
                            print("Режим замены модели включен, но путь к модели не указан и нет окна для диалога")
                    
                    if replace_model_smd_path and os.path.exists(replace_model_smd_path):
                        try:
                            # Находим reference SMD файл в декомпилированной директории
                            print(f"Ищем reference SMD файл для weapon_key: {weapon_key} в {ctx.decompile_dir}")
                            original_smd_path = SMDService.find_reference_smd(ctx.decompile_dir, weapon_key)
                            
                            if original_smd_path:
                                # Проверяем, что найденный файл действительно соответствует weapon_key
                                file_name = os.path.basename(original_smd_path)
                                if weapon_key.lower() not in file_name.lower():
                                    print(f"ОШИБКА: Найденный SMD файл {file_name} не соответствует weapon_key {weapon_key}!")
                                    print(f"Пропускаем замену модели, чтобы избежать загрузки неправильного оружия")
                                    original_smd_path = None
                            
                            if original_smd_path:
                                print(f"Заменяем модель: {replace_model_smd_path} -> {original_smd_path}")
                                # Заменяем секции: nodes и skeleton из оригинального,
                                # названия материалов из оригинального,
                                # данные треугольников из пользовательского
                                SMDService.replace_model_sections(
                                    replace_model_smd_path,
                                    original_smd_path,
                                    original_smd_path  # Перезаписываем оригинальный файл под тем же именем
                                )
                                print(f"Модель успешно заменена: {original_smd_path}")
                            else:
                                print(f"Предупреждение: Не найден reference SMD файл для {weapon_key} в {ctx.decompile_dir}")
                                # Выводим список всех SMD файлов для отладки
                                if os.path.exists(ctx.decompile_dir):
                                    smd_files = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')]
                                    print(f"Доступные SMD файлы в директории: {smd_files}")
                        except Exception as e:
                            print(f"Ошибка при замене модели: {e}")
                            # Не прерываем сборку, просто продолжаем с оригинальной моделью
                    
                    # Извлекаем путь из $cdmaterials в QC файле (до патчинга)
                    original_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
                    
                    if not original_cdmaterials_path:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_cdmaterials_not_extracted'].format(qc_path=qc_path)
                    
                    # Извлекаем имя файла из $texturegroup (до патчинга)
                    texture_filename = ModelBuildService.extract_texturegroup_filename(qc_path)
                    if not texture_filename:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_texturegroup_not_extracted'].format(qc_path=qc_path)
                    
                    # Пропатчиваем QC файл: добавляем console\ к $cdmaterials, удаляем $lod
                    ModelBuildService.patch_qc_file(qc_path, weapon_key, original_cdmaterials_path)
                    
                    # Извлекаем путь из $cdmaterials после патчинга (теперь с префиксом console\)
                    patched_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
                    if not patched_cdmaterials_path:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_cdmaterials_patched_not_extracted'].format(qc_path=qc_path)
                    
                    # Конвертируем путь из $cdmaterials в путь для материалов (добавляем materials/ и конвертируем слеши)
                    # Путь теперь в формате: console\models\weapons\v_bonesaw
                    # Конвертируем в: materials/console/models/weapons/v_bonesaw/
                    materials_rel_path = "materials/" + patched_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
                    if not materials_rel_path.endswith('/'):
                        materials_rel_path += '/'
                    
                    # Имя файла - из $texturegroup
                    vmt_filename = f"{texture_filename}.vmt"
                    vtf_filename = f"{texture_filename}.vtf"
                    
                    # Подготавливаем пути в vpkroot
                    vtf_output_path = os.path.join(ctx.vpkroot_dir, materials_rel_path.rstrip('/'))
                    vmt_path = os.path.join(vtf_output_path, vmt_filename)
                    vtf_temp_png = os.path.join(vtf_output_path, vtf_filename.replace(".vtf", ".png"))
                    
                    # Создаем директорию
                    try:
                        os.makedirs(vtf_output_path, exist_ok=True)
                    except OSError as e:
                        if "path too long" in str(e).lower():
                            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                            return False, t['error_path_too_long'].format(mode=mode)
                        else:
                            raise
                    
                    # Если используется пользовательский VTF файл, копируем его
                    if custom_vtf_path:
                        # Копируем пользовательский VTF файл в нужную директорию
                        vtf_file_path = os.path.join(vtf_output_path, vtf_filename)
                        os.makedirs(vtf_output_path, exist_ok=True)
                        shutil.copy2(custom_vtf_path, vtf_file_path)
                        print(f"Использован пользовательский VTF файл: {custom_vtf_path} -> {vtf_file_path}")
                    else:
                        # Обрабатываем изображение
                        VPKService._process_image(image_path, vtf_temp_png, size)
                        
                        # Разделяем флаги на опции VTFCmd и флаги VTF
                        vtf_flags, flags_parsed_options = VPKService._parse_vtf_flags_and_options(flags)
                        
                        # Объединяем опции из UI с опциями из флагов
                        merged_options = {}
                        if vtf_options:
                            merged_options.update(vtf_options)
                        merged_options.update(flags_parsed_options)
                        
                        # Создаем VTF файл
                        VPKService._create_vtf(vtf_temp_png, vtf_output_path, format_type, vtf_flags, merged_options)
                        
                        # Удаляем временный PNG файл
                        if os.path.exists(vtf_temp_png):
                            os.remove(vtf_temp_png)
                    
                    # Пробуем извлечь VMT файл, используя оригинальный путь из QC (до патчинга)
                    vmt_file = None
                    # Пробуем найти tf2_textures_dir.vpk для извлечения VMT
                    tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
                    if original_cdmaterials_path and tf2_textures_vpk:
                        vmt_file = TF2VPKExtractService.extract_vmt_file(
                            tf2_textures_vpk,
                            original_cdmaterials_path,
                            texture_filename,
                            ctx.decompile_dir
                        )
                        if vmt_file:
                            print(f"Извлечен VMT файл: {vmt_file}")
                        else:
                            # Пробуем также tf2_misc_dir.vpk
                            vmt_file = TF2VPKExtractService.extract_vmt_file(
                                tf2_misc_vpk,
                                original_cdmaterials_path,
                                texture_filename,
                                ctx.decompile_dir
                            )
                            if vmt_file:
                                print(f"Извлечен VMT файл из misc: {vmt_file}")
                    elif original_cdmaterials_path:
                        # Пробуем tf2_misc_dir.vpk если textures не найден
                        vmt_file = TF2VPKExtractService.extract_vmt_file(
                            tf2_misc_vpk,
                            original_cdmaterials_path,
                            texture_filename,
                            ctx.decompile_dir
                        )
                        if vmt_file:
                            print(f"Извлечен VMT файл: {vmt_file}")
                    
                    # Проверяем, есть ли отредактированный VMT файл
                    from src.services.edited_vmt_service import EditedVMTService
                    edited_vmt_path = EditedVMTService.get_edited_vmt(texture_filename)
                    
                    if edited_vmt_path and os.path.exists(edited_vmt_path):
                        # Используем отредактированный VMT файл
                        shutil.copy2(edited_vmt_path, vmt_path)
                        # Обновляем путь $baseTexture в отредактированном VMT файле на основе пути из QC
                        VMTService.update_vmt_basetexture_path(vmt_path, patched_cdmaterials_path, texture_filename)
                        print(f"Использован отредактированный VMT файл: {edited_vmt_path} -> {vmt_path}")
                        # Помечаем, что нужно удалить отредактированный VMT после сборки
                        vmt_to_delete = texture_filename
                    elif vmt_file and os.path.exists(vmt_file):
                        # Если VMT файл извлечен, копируем его в нужную директорию и обновляем путь $baseTexture
                        # Используем путь из исправленного QC файла (patched_cdmaterials_path)
                        shutil.copy2(vmt_file, vmt_path)
                        # Обновляем путь $baseTexture в извлеченном VMT файле на основе пути из QC
                        VMTService.update_vmt_basetexture_path(vmt_path, patched_cdmaterials_path, texture_filename)
                        print(f"Скопирован и обновлен извлеченный VMT файл: {vmt_file} -> {vmt_path}")
                    else:
                        # Если VMT файл не извлечен, создаем из шаблона используя путь из исправленного QC
                        VMTService.create_vmt_template_from_cdmaterials(vmt_path, patched_cdmaterials_path, texture_filename)
                        print(f"Создан VMT файл из шаблона: {vmt_path}")
                    
                    # Сохраняем состояние отладки: этап 3 - после редактирования (патчинга)
                    if debug_mode:
                        DebugService.save_patched_stage(ctx, ctx.decompile_dir)
                    
                    # Компилируем модель
                    ModelBuildService.compile(
                        qc_path,
                        ctx.compile_dir,
                        studiomdl_exe,
                        tf_dir
                    )
                    
                    # Сохраняем состояние отладки: этап 4 - после компиляции
                    if debug_mode:
                        DebugService.save_compiled_stage(ctx, ctx.compile_dir)
                    
                    # Копируем скомпилированные файлы в vpkroot (VMT файл уже скопирован ранее)
                    # Используем путь из $modelname в QC файле
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
            
            # Создаем VPK файл
            vpk_path = VPKService._create_vpk_file(ctx, filename, export_folder, language)
            
            # Удаляем отредактированный VMT файл после успешной сборки (если он был использован)
            if vmt_to_delete:
                from src.services.edited_vmt_service import EditedVMTService
                if EditedVMTService.delete_edited_vmt(vmt_to_delete):
                    print(f"Удален отредактированный VMT файл: {vmt_to_delete}")
            
            # Очищаем папку temp_vmt_extract (временные извлеченные VMT файлы)
            temp_vmt_extract_dir = os.path.join("tools", "temp_vmt_extract")
            if os.path.exists(temp_vmt_extract_dir):
                try:
                    # Удаляем все файлы из папки
                    for filename_in_dir in os.listdir(temp_vmt_extract_dir):
                        file_path = os.path.join(temp_vmt_extract_dir, filename_in_dir)
                        try:
                            if os.path.isfile(file_path) or os.path.islink(file_path):
                                os.unlink(file_path)
                            elif os.path.isdir(file_path):
                                shutil.rmtree(file_path)
                        except Exception as e:
                            print(f"Предупреждение: Не удалось удалить {file_path}: {e}")
                    print(f"Очищена папка temp_vmt_extract")
                except Exception as e:
                    print(f"Предупреждение: Не удалось очистить папку temp_vmt_extract: {e}")
            
            # Успех - очищаем временные файлы (но сохраняем если включен режим отладки)
            ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=debug_mode)
            
            return True, f"VPK успешно создан: {vpk_path}"
            
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
        language: str = "en"
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Создает VPK для специальных режимов (critHIT и т.д.)
        
        Returns:
            Tuple[success, message, vmt_to_delete] - где vmt_to_delete это имя файла для удаления, если был использован отредактированный VMT
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        
        try:
            # Получаем относительные пути (без basepath)
            rel_path, vmt_filename, vtf_filename = VMTService.get_weapon_relpaths(mode)
            
            # Подготавливаем пути в vpkroot
            vtf_output_path = os.path.join(ctx.vpkroot_dir, rel_path)
            vmt_path = os.path.join(vtf_output_path, vmt_filename)
            vtf_temp_png = os.path.join(vtf_output_path, vtf_filename.replace(".vtf", ".png"))
            
            # Создаем директорию
            try:
                os.makedirs(vtf_output_path, exist_ok=True)
            except OSError as e:
                if "path too long" in str(e).lower():
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_path_too_long'].format(mode=mode)
                else:
                    raise
            
            # Если используется пользовательский VTF файл, копируем его
            if custom_vtf_path:
                # Копируем пользовательский VTF файл в нужную директорию
                # Для специальных режимов имя VTF файла соответствует имени VMT файла
                vtf_filename_for_mode = vmt_filename.replace('.vmt', '.vtf')
                vtf_file_path = os.path.join(vtf_output_path, vtf_filename_for_mode)
                os.makedirs(vtf_output_path, exist_ok=True)
                shutil.copy2(custom_vtf_path, vtf_file_path)
                print(f"Использован пользовательский VTF файл для специального режима: {custom_vtf_path} -> {vtf_file_path}")
            else:
                # Обрабатываем изображение
                VPKService._process_image(image_path, vtf_temp_png, size)
                
                # Разделяем флаги на опции VTFCmd и флаги VTF
                vtf_flags, flags_parsed_options = VPKService._parse_vtf_flags_and_options(flags)
                
                # Объединяем опции из UI с опциями из флагов
                merged_options = {}
                if vtf_options:
                    merged_options.update(vtf_options)
                merged_options.update(flags_parsed_options)
                
                # Создаем VTF файл
                VPKService._create_vtf(vtf_temp_png, vtf_output_path, format_type, vtf_flags, merged_options)
                
                # Удаляем временный PNG файл
                if os.path.exists(vtf_temp_png):
                    os.remove(vtf_temp_png)
            
            # Проверяем, есть ли отредактированный VMT файл для специальных режимов
            from src.services.edited_vmt_service import EditedVMTService
            # Для специальных режимов используем имя файла из режима (например, "crit" для critHIT)
            vmt_filename_without_ext = os.path.splitext(vmt_filename)[0]
            edited_vmt_path = EditedVMTService.get_edited_vmt(vmt_filename_without_ext)
            vmt_to_delete = None
            
            # Определяем путь к mod_data для специальных режимов
            if mode == "critHIT":
                mod_data_base = "tools/mod_data"
            else:
                mod_data_base = os.path.join("tools", "mod_data", mode)
            
            mod_data_vmt_path = os.path.join(mod_data_base, vmt_filename)
            
            if edited_vmt_path and os.path.exists(edited_vmt_path):
                # Используем отредактированный VMT файл (приоритет 1)
                shutil.copy2(edited_vmt_path, vmt_path)
                print(f"Использован отредактированный VMT файл для специального режима: {edited_vmt_path} -> {vmt_path}")
                vmt_to_delete = vmt_filename_without_ext
            elif os.path.exists(mod_data_vmt_path):
                # Используем существующий VMT файл из mod_data (приоритет 2)
                shutil.copy2(mod_data_vmt_path, vmt_path)
                print(f"Использован VMT файл из mod_data: {mod_data_vmt_path} -> {vmt_path}")
            else:
                # Создаем VMT файл из шаблона (приоритет 3)
                class_name = mode.split('_')[0].capitalize() if '_' in mode else "Unknown"
                weapon_type = "Primary"
                VMTService.create_vmt_template(vmt_path, mode, class_name, weapon_type)
                print(f"Создан VMT файл из шаблона: {vmt_path}")
            
            # Копируем PCF файл для critHIT режима (если существует)
            if mode == "critHIT":
                pcf_filename = "crit.pcf"
                mod_data_pcf_path = os.path.join(mod_data_base, pcf_filename)
                if os.path.exists(mod_data_pcf_path):
                    # PCF файлы должны быть в папке particles
                    pcf_output_path = os.path.join(ctx.vpkroot_dir, "particles")
                    os.makedirs(pcf_output_path, exist_ok=True)
                    pcf_dest_path = os.path.join(pcf_output_path, pcf_filename)
                    shutil.copy2(mod_data_pcf_path, pcf_dest_path)
                    print(f"Скопирован PCF файл: {mod_data_pcf_path} -> {pcf_dest_path}")
                else:
                    print(f"Предупреждение: PCF файл не найден: {mod_data_pcf_path}")
            
            return True, "Текстуры для специального режима созданы успешно", vmt_to_delete
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
        Валидирует параметры сборки VPK
        
        Args:
            custom_vtf_path: Если указан, пропускается проверка image_path
        
        Returns:
            None если валидация прошла успешно, иначе строка с описанием ошибки
        """
        if t is None:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS['en']
        
        # Проверка изображения (пропускаем, если используется custom_vtf_path)
        if not custom_vtf_path:
            if not image_path or not isinstance(image_path, str):
                return t['error_image_not_specified']
            
            if not os.path.exists(image_path):
                return t['error_image_not_found'].format(path=image_path)
            
            if not os.path.isfile(image_path):
                return t['error_image_not_file'].format(path=image_path)
        else:
            # Проверяем, что custom_vtf_path существует
            if not os.path.exists(custom_vtf_path):
                return t.get('error_custom_vtf_not_found', f'Custom VTF file not found: {custom_vtf_path}')
            
            if not os.path.isfile(custom_vtf_path):
                return t.get('error_custom_vtf_not_file', f'Custom VTF path is not a file: {custom_vtf_path}')
        
        # Проверка режима
        if not mode or not isinstance(mode, str):
            return t['error_mode_not_specified']
        
        # Проверка имени файла
        if not filename or not isinstance(filename, str):
            return t['error_filename_not_specified']
        
        if not filename.endswith('.vpk'):
            return t['error_filename_no_vpk']
        
        # Проверка размера
        if not isinstance(size, (tuple, list)) or len(size) != 2:
            return t['error_size_invalid']
        
        width, height = size
        if not isinstance(width, int) or not isinstance(height, int):
            return t['error_size_not_int']
        
        if width <= 0 or height <= 0:
            return t['error_size_not_positive']
        
        # Проверка формата
        valid_formats = ['DXT1', 'DXT5', 'RGBA8888']
        if format_type not in valid_formats:
            return t['error_format_invalid'].format(format=format_type, formats=', '.join(valid_formats))
        
        # Проверка пути TF2 (для обычных режимов)
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
        """Обрабатывает изображение для VTF"""
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Изображение не найдено: {input_path}")
        
        img = Image.open(input_path).convert("RGBA").resize(size)
        img.save(output_path)
    
    @staticmethod
    def _parse_vtf_flags_and_options(flags: List[str]) -> Tuple[List[str], dict]:
        """
        Преобразует флаги из UI в опции VTFCmd и флаги VTF
        
        Args:
            flags: Список флагов из UI (например, ["CLAMPS", "CLAMPT", "NOMIP", "NOLOD"])
            
        Returns:
            Tuple[vtf_flags, options]:
                - vtf_flags: Список флагов для передачи через -flag
                - options: Словарь опций VTFCmd
        """
        if flags is None:
            flags = []
        
        vtf_flags = []
        options = {}
        
        for flag in flags:
            flag_upper = flag.upper()
            
            # Опции VTFCmd (передаются как отдельные параметры, не через -flag)
            if flag_upper == "NOMIP":
                options["nomipmaps"] = True
            # Остальные флаги передаются через -flag
            else:
                vtf_flags.append(flag)
        
        return vtf_flags, options
    
    @staticmethod
    def _create_vtf(png_path: str, output_path: str, format_type: str, flags: List[str], 
                   options: dict = None) -> None:
        """
        Создает VTF файл из PNG
        
        Args:
            png_path: Путь к PNG файлу
            output_path: Путь к директории вывода
            format_type: Формат VTF (DXT1, DXT5, RGBA8888, etc.)
            flags: Список флагов VTF (CLAMPS, CLAMPT, NOLOD, POINTSAMPLE, TRILINEAR, etc.)
            options: Словарь опций VTFCmd:
                - nomipmaps: bool - не генерировать mipmaps
                - nothumbnail: bool - не генерировать миниатюру
                - noreflectivity: bool - не вычислять отражательную способность
                - gamma: bool - гамма-коррекция
                - gcorrection: float - значение гамма-коррекции
                - normal: bool - конвертировать в нормальную карту
                - nkernel: str - ядро генерации нормальной карты
                - nheight: str - метод расчета высоты для нормальной карты
                - nalpha: str - результат альфа-канала для нормальной карты
                - nscale: float - масштаб нормальной карты
                - nwrap: bool - обернуть нормальную карту для тайловых текстур
                - bumpscale: float - масштаб bump mapping в движке
        """
        if options is None:
            options = {}
        
        vtf_args = [
            os.path.abspath(VPKService.VTF_TOOL_PATH),
            "-file", png_path,
            "-output", output_path,
            "-format", format_type
        ]
        
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
        # Маппинг флагов из UI в названия, которые понимает VTFCmd
        flag_mapping = {
            "CLAMPS": "clamps",
            "CLAMPT": "clampt", 
            "NOLOD": "nolod",
            "NOMIP": "nomip",  # Если нужно использовать как флаг (но лучше через -nomipmaps)
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
            # Пропускаем NOMIP, так как он уже обработан как опция nomipmaps
            if flag.upper() == "NOMIP":
                continue
            
            # Если флаг в маппинге, используем его значение
            if flag in flag_mapping:
                vtf_args.extend(["-flag", flag_mapping[flag]])
            else:
                # Иначе передаем как есть (в нижнем регистре)
                vtf_args.extend(["-flag", flag.lower()])
        
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
        Создает VPK файл из vpkroot
        
        Args:
            ctx: Контекст сборки
            filename: Имя выходного файла
            
        Returns:
            Путь к созданному VPK файлу
        """
        # vpk.exe создает файл с именем папки, т.е. vpkroot.vpk
        # Файл создается в директории vpkroot_dir (в родительской папке)
        vpkroot_parent = os.path.dirname(ctx.vpkroot_dir)
        temp_vpk_path = os.path.join(vpkroot_parent, "vpkroot.vpk")
        
        # Отладочный вывод: проверяем содержимое vpkroot перед созданием VPK
        print(f"[DEBUG] Создание VPK из: {ctx.vpkroot_dir}")
        if os.path.exists(ctx.vpkroot_dir):
            print(f"[DEBUG] Содержимое vpkroot_dir:")
            for root, dirs, files in os.walk(ctx.vpkroot_dir):
                level = root.replace(ctx.vpkroot_dir, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    print(f"{subindent}{file}")
        else:
            print(f"[DEBUG] ВНИМАНИЕ: vpkroot_dir не существует: {ctx.vpkroot_dir}")
        
        # Удаляем существующий VPK если есть
        if os.path.exists(temp_vpk_path):
            os.remove(temp_vpk_path)
        
        # Создаем VPK
        # vpk.exe создает файл в той же директории, где находится папка vpkroot
        print(f"[DEBUG] Запуск vpk.exe для создания VPK...")
        result = subprocess.run([
            os.path.abspath(VPKService.VPK_TOOL_PATH),
            "-v", os.path.abspath(ctx.vpkroot_dir)
        ], cwd=vpkroot_parent, capture_output=True, text=True)
        
        print(f"[DEBUG] vpk.exe завершился с кодом: {result.returncode}")
        if result.stdout:
            print(f"[DEBUG] STDOUT: {result.stdout}")
        if result.stderr:
            print(f"[DEBUG] STDERR: {result.stderr}")
        
        if result.returncode != 0:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise RuntimeError(
                t['error_vpk_creation_failed'].format(
                    stdout=result.stdout,
                    stderr=result.stderr
                )
            )
        
        if not os.path.exists(temp_vpk_path):
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise FileNotFoundError(t['error_vpkroot_not_found'].format(path=vpkroot_parent))
        
        # Перемещаем в export
        os.makedirs(export_folder, exist_ok=True)
        final_output = os.path.join(export_folder, filename)
        if os.path.exists(final_output):
            os.remove(final_output)
        shutil.move(temp_vpk_path, final_output)
        
        return final_output
    
    @staticmethod
    def _copy_compiled_models_to_vpkroot(ctx: BuildContext, qc_path: str) -> None:
        """
        Копирует скомпилированные файлы модели в vpkroot
        
        Использует путь из $modelname в QC файле для создания правильной структуры директорий
        
        Args:
            ctx: Контекст сборки
            qc_path: Путь к QC файлу (для извлечения пути из $modelname)
        """
        # Извлекаем путь из $modelname в QC файле
        modelname_path = ModelBuildService.extract_modelname_path(qc_path)
        if not modelname_path:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise FileNotFoundError(t['error_modelname_not_extracted'].format(qc_path=qc_path))
        
        # Нормализуем путь (заменяем обратные слеши на прямые)
        normalized_path = modelname_path.replace('\\', '/')
        path_parts = normalized_path.split('/')
        
        # Убираем имя файла (последняя часть), оставляем только путь к директории
        if len(path_parts) > 1:
            # Путь к директории без имени файла
            model_dir_path = '/'.join(path_parts[:-1])
        else:
            # Если путь состоит только из имени файла, используем корень models
            model_dir_path = ""
        
        # Строим полный путь в vpkroot: models/<путь_из_modelname_без_имени_файла>
        if model_dir_path:
            target_dir = os.path.join(ctx.vpkroot_dir, "models", model_dir_path)
        else:
            target_dir = os.path.join(ctx.vpkroot_dir, "models")
        
        os.makedirs(target_dir, exist_ok=True)
        
        # Копируем только файлы модели из compile_dir, которые соответствуют имени модели из $modelname
        if not os.path.exists(ctx.compile_dir):
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise FileNotFoundError(t['error_compile_dir_not_found'].format(path=ctx.compile_dir))
        
        # Извлекаем имя модели из $modelname (без расширения)
        model_filename = os.path.basename(modelname_path)
        model_basename = os.path.splitext(model_filename)[0]
        
        # Находим только файлы модели, которые начинаются с model_basename
        # Это предотвращает копирование файлов других моделей (например, bat при компиляции scattergun)
        model_files = []
        for file_name in os.listdir(ctx.compile_dir):
            file_path = os.path.join(ctx.compile_dir, file_name)
            if os.path.isfile(file_path):
                # Проверяем, что файл начинается с model_basename и является файлом модели
                if file_name.startswith(model_basename) and file_name.endswith(('.mdl', '.vvd', '.vtx', '.phy')):
                    model_files.append(file_name)
        
        if not model_files:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])  # Используем английский для внутренних ошибок
            raise FileNotFoundError(t['error_model_files_not_found'].format(path=ctx.compile_dir, model=model_basename))
        
        # Копируем файлы
        print(f"[DEBUG] Копируем {len(model_files)} файлов модели из {ctx.compile_dir} в {target_dir}")
        for file_name in model_files:
            src = os.path.join(ctx.compile_dir, file_name)
            dst = os.path.join(target_dir, file_name)
            print(f"[DEBUG] Копируем: {file_name} -> {dst}")
            shutil.copy2(src, dst)
            print(f"[DEBUG] Скопирован файл модели: {file_name}")
        
        print(f"[DEBUG] Все файлы модели скопированы в VPK root: {target_dir}")
    
    @staticmethod
    def _generate_uv_layout(ctx: BuildContext, weapon_key: str, image_size: Tuple[int, int], export_folder: str = "export", language: str = "en") -> None:
        """
        Генерирует UV разметку из SMD файла и сохраняет в export
        
        Args:
            ctx: Контекст сборки
            weapon_key: Ключ оружия
            image_size: Размер изображения для UV разметки
        """
        try:
            from src.services.uv_layout_service import UVLayoutService
            
            print(f"Генерация UV разметки для оружия: {weapon_key}")
            print(f"Директория декомпиляции: {ctx.decompile_dir}")
            
            # Находим reference SMD файл
            smd_path = SMDService.find_reference_smd(ctx.decompile_dir, weapon_key)
            if not smd_path or not os.path.exists(smd_path):
                print(f"Предупреждение: Не найден SMD файл для генерации UV разметки: {weapon_key}")
                print(f"Проверяемая директория: {ctx.decompile_dir}")
                if os.path.exists(ctx.decompile_dir):
                    smd_files = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')]
                    print(f"Найденные SMD файлы в директории: {smd_files}")
                return
            
            print(f"Найден SMD файл: {smd_path}")
            
            # Создаем имя файла для UV разметки
            uv_filename = f"{weapon_key}_uv_layout.png"
            uv_output_path = os.path.join(export_folder, uv_filename)
            
            # Создаем папку export, если её нет
            os.makedirs(export_folder, exist_ok=True)
            
            # Генерируем UV разметку
            if UVLayoutService.generate_uv_layout_from_smd(smd_path, uv_output_path, image_size):
                print(f"UV разметка сохранена: {uv_output_path}")
            else:
                print(f"Ошибка при создании UV разметки для {weapon_key}")
        except Exception as e:
            import traceback
            print(f"Ошибка при генерации UV разметки: {e}")
            print(f"Трассировка: {traceback.format_exc()}")
            # Не прерываем сборку из-за ошибки UV разметки
