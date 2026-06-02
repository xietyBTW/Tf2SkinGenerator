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
from .build_context import BuildContext, TextureBuildContext
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
from src.data.player_characters import (
    PLAYER_BODY_MODE_KEYS,
    SPY_MASK_MODE_KEY,
    SPY_MDL_PATH,
    SPY_DISGUISE_MASKS,
    SPY_MASK_VTF_NAMES,
)
from src.shared.logging_config import get_logger
from src.shared.constants import ToolPaths, DirectoryPaths, EXTRA_TEX_USE_GAME_ORIGINAL
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
    def _get_vpk_tool() -> Path:
        return ToolPaths.get_vpk_tool()

    @staticmethod
    def _build_mdl_search_paths(
        mode: str,
        weapon_key: str,
        hat_mdl_path: Optional[str],
        t: dict,
    ) -> Tuple[List[str], Optional[str]]:
        """
        Строит список путей-кандидатов к MDL внутри игрового VPK.

        TF2 хранит модели в разных местах (workshop / workshop_partner /
        weapons/c_models / c_items / player/items), поэтому пробуем все
        вероятные варианты по порядку.

        Returns:
            (paths_to_try, error). error != None — фатальная ошибка режима
            (нет mdl_path для персонажа или оружие не найдено в конфиге);
            вызывающий код должен очистить ctx и вернуть ошибку.
        """
        # ── Шапка: путь из items_game.txt, возможно с %s-плейсхолдером ──── #
        if mode == "hat" and hat_mdl_path:
            _norm = hat_mdl_path.replace("\\", "/")
            _TF2_CLASSES = [
                "heavy", "scout", "soldier", "pyro",
                "demoman", "engineer", "medic", "sniper", "spy",
            ]
            base_candidates = []
            if "%s" in _norm:
                for cls in _TF2_CLASSES:
                    try:
                        base_candidates.append(_norm % cls)
                    except (TypeError, ValueError):
                        base_candidates.append(_norm.replace("%s", cls))
            else:
                base_candidates.append(_norm)

            paths_to_try = []
            for c in base_candidates:
                paths_to_try.append(c)
                if "models/player/items" in c and "workshop" not in c:
                    paths_to_try.append(c.replace("models/player/items",
                                                  "models/workshop_partner/player/items"))
                    paths_to_try.append(c.replace("models/player/items",
                                                  "models/workshop/player/items"))
                elif "models/workshop/player/items" in c:
                    paths_to_try.append(c.replace("models/workshop/player/items",
                                                  "models/workshop_partner/player/items"))
                    paths_to_try.append(c.replace("models/workshop/player/items",
                                                  "models/player/items"))
                elif "models/workshop_partner/player/items" in c:
                    paths_to_try.append(c.replace("models/workshop_partner/player/items",
                                                  "models/workshop/player/items"))
                    paths_to_try.append(c.replace("models/workshop_partner/player/items",
                                                  "models/player/items"))

            seen_paths = set()
            paths_to_try = [p for p in paths_to_try if not (p in seen_paths or seen_paths.add(p))]
            return paths_to_try, None

        # ── Тело персонажа / маски шпиона: прямой путь к MDL ────────────── #
        if mode in PLAYER_BODY_MODE_KEYS or mode == SPY_MASK_MODE_KEY:
            if mode == SPY_MASK_MODE_KEY:
                _char_mdl = SPY_MDL_PATH
            else:
                from src.data.player_characters import PLAYER_CHARACTERS as _PC
                _char_mdl = _PC.get(mode, {}).get('mdl_path', '')
            if not _char_mdl:
                return [], f"No mdl_path defined for character mode: {mode}"
            return [_char_mdl], None

        # ── Обычное оружие: пробуем все вероятные места хранения ─────────── #
        if weapon_key not in WEAPON_MDL_PATHS:
            return [], t['error_weapon_not_found'].format(weapon_key=weapon_key)

        base_path = WEAPON_MDL_PATHS[weapon_key]
        _folder_suffix = f"/{weapon_key}/{weapon_key}.mdl"
        _flat_suffix = f"/{weapon_key}.mdl"
        paths_to_try = []

        # workshop_partner → workshop → стандарт → c_items: путь с папкой и без
        for _candidate in (
            base_path.replace("models/weapons/", "models/workshop_partner/weapons/"),
            base_path.replace("models/weapons/", "models/workshop/weapons/"),
            base_path,
            base_path.replace("models/weapons/c_models/", "models/weapons/c_items/"),
        ):
            paths_to_try.append(_candidate)
            if _folder_suffix in _candidate:
                paths_to_try.append(_candidate.replace(_folder_suffix, _flat_suffix))

        # Последний шанс — папки классов (там обычно старьё)
        if '_' in mode:
            class_name_lower = mode.split('_', 1)[0]
            paths_to_try.append(f"models/player/items/{class_name_lower}/{weapon_key}/{weapon_key}.mdl")
            paths_to_try.append(f"models/player/items/{class_name_lower}/{weapon_key}.mdl")

        return paths_to_try, None
    
    @staticmethod
    def _find_existing_mdl(
        paths_to_try: List[str],
        tf2_misc_vpk: str,
        weapon_key: str,
        t: dict,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Ищет первый существующий MDL среди путей-кандидатов внутри VPK.

        Только проверяет наличие (check_mdl_exists), не распаковывая файлы —
        так быстрее, чем тащить всю папку.

        Returns:
            (found_path, error). Ровно одно из значений не None.
        """
        last_error = None
        for mdl_rel_path in paths_to_try:
            try:
                logger.debug(f"Проверяем наличие MDL по пути: {mdl_rel_path}")
                if TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, mdl_rel_path):
                    logger.info(f"MDL файл найден по пути: {mdl_rel_path}")
                    return mdl_rel_path, None
                logger.debug(f"MDL файл не найден по пути: {mdl_rel_path}")
            except Exception as e:
                logger.warning(f"Ошибка при проверке пути {mdl_rel_path}: {e}", exc_info=True)
                last_error = e

        paths_str = "\n".join([f"  - {path}" for path in paths_to_try])
        error_msg = t['error_mdl_not_found'].format(paths=paths_str, vpk_file=tf2_misc_vpk)
        if last_error:
            error_msg += f"\n{str(last_error)}"
        logger.error(f"Модель не найдена для {weapon_key}. Проверенные пути: {len(paths_to_try)}")
        return None, error_msg

    @staticmethod
    def _resolve_replace_model_smd(
        replace_model_enabled: bool,
        model_ready_path: Optional[str],
        replace_model_path: Optional[str],
        model_file_callback,
        parent_window,
    ) -> Optional[str]:
        """
        Определяет путь к пользовательскому SMD для режима «замена модели».

        Источники по приоритету: прямой путь (тесты) → callback (UI-поток) →
        диалог QFileDialog (если есть parent_window). Возвращает None, если
        режим выключен, задан model_ready_path или пользователь отменил выбор.
        """
        if not replace_model_enabled or model_ready_path:
            return None

        if replace_model_path and os.path.exists(replace_model_path):
            logger.info(f"Используется предустановленный файл для замены модели: {replace_model_path}")
            return replace_model_path

        if model_file_callback:
            # Qt не любит UI из рабочего потока — запрашиваем файл через callback главного потока
            file_path = model_file_callback()
            if file_path and os.path.exists(file_path):
                logger.info(f"Выбран файл для замены модели через callback: {file_path}")
                return file_path
            logger.info("Выбор SMD файла отменен, продолжаем без замены модели")
            return None

        if parent_window:
            from PySide6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                parent_window,
                "Выберите SMD файл модели для замены",
                "",
                "SMD Files (*.smd);;All Files (*)",
            )
            if file_path and os.path.exists(file_path):
                logger.info(f"Выбран файл для замены модели: {file_path}")
                return file_path
            logger.info("Выбор SMD файла отменен, продолжаем без замены модели")
            return None

        logger.warning("Режим замены модели включен, но путь к модели не указан и нет способа запросить файл")
        return None

    @staticmethod
    def _write_material_vmt(target_vmt_path, base_vmt_path, cdmaterials_path: str, tex_name: str) -> None:
        """
        Записывает VMT вторичного материала (extra / variant / shared / BLU).

        Если базовый VMT существует — копирует его и переставляет $basetexture
        на tex_name; иначе создаёт VMT из шаблона по $cdmaterials.
        """
        if base_vmt_path.exists():
            copy_file_safe(base_vmt_path, target_vmt_path)
            VMTService.update_vmt_basetexture_path(str(target_vmt_path), cdmaterials_path, tex_name)
        else:
            VMTService.create_vmt_template_from_cdmaterials(str(target_vmt_path), cdmaterials_path, tex_name)
        logger.info(f"Создан VMT вторичного материала: {target_vmt_path.name}")

    @staticmethod
    def _build_blu_team_texture(
        blu_mode: str,
        blu_image_path: Optional[str],
        vtf_output_path: Path,
        vtf_filename: str,
        vmt_path: Path,
        texture_filename: str,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict,
    ) -> None:
        """
        Создаёт BLU-командную текстуру (и VMT) рядом с RED.

        blu_mode == 'same'        → копия RED VTF;
        иначе при blu_image_path  → отдельное изображение → VTF.
        BLU VMT — копия RED VMT с обновлённым $basetexture. Ошибки не критичны
        (мод соберётся и без BLU-варианта).

        Примечание: BLU намеренно использует только UI-опции (vtf_options),
        не подмешивая опции из флагов — поведение сохранено как в оригинале.
        """
        if not blu_mode or blu_mode in ('none', ''):
            return
        try:
            red_vtf_path = vtf_output_path / vtf_filename
            blu_vtf_name = f"{texture_filename}_blue.vtf"
            blu_vtf_path = vtf_output_path / blu_vtf_name
            blu_created = False

            if blu_mode == 'same':
                if red_vtf_path.exists():
                    shutil.copy2(red_vtf_path, blu_vtf_path)
                    blu_created = True
                    logger.info(f"BLU текстура скопирована из RED: {blu_vtf_name}")
            elif blu_image_path and os.path.exists(blu_image_path):
                blu_png_tmp = vtf_output_path / f"{texture_filename}_blue.png"
                VPKService._process_image(blu_image_path, str(blu_png_tmp), size)
                blu_vtf_flags, _ = TextureService.parse_vtf_flags_and_options(flags or [])
                blu_opts = dict(vtf_options or {})
                blu_opts.pop('normal', None)   # BLU — не normal map
                VPKService._create_vtf(
                    str(blu_png_tmp), str(vtf_output_path), format_type, blu_vtf_flags, blu_opts
                )
                if blu_png_tmp.exists():
                    blu_png_tmp.unlink()
                blu_created = blu_vtf_path.exists()
                if blu_created:
                    logger.info(f"BLU текстура создана: {blu_vtf_name}")

            # BLU VMT — копия RED с обновлённым $basetexture
            if blu_created and vmt_path.exists():
                blu_vmt_path = vtf_output_path / f"{texture_filename}_blue.vmt"
                shutil.copy2(vmt_path, blu_vmt_path)
                VMTService.update_vmt_basetexture_path(
                    str(blu_vmt_path), patched_cdmaterials_path, f"{texture_filename}_blue"
                )
                logger.info(f"BLU VMT создан: {blu_vmt_path.name}")
        except Exception as _blu_exc:
            logger.warning(
                f"Не удалось создать BLU текстуру (не критично): {_blu_exc}", exc_info=True
            )

    @staticmethod
    def _extract_original_vmt(
        cdmaterials_path: Optional[str],
        texture_filename: str,
        tf2_textures_vpk: Optional[str],
        tf2_misc_vpk: str,
        decompile_dir,
    ) -> Optional[str]:
        """
        Извлекает оригинальный VMT текстуры из игровых VPK.

        Порядок: tf2_textures_dir.vpk → tf2_misc_dir.vpk (Valve кладёт текстуры
        то туда, то туда). Возвращает путь к извлечённому VMT или None.
        """
        if not cdmaterials_path:
            return None
        if tf2_textures_vpk:
            vmt = TF2VPKExtractService.extract_vmt_file(
                tf2_textures_vpk, cdmaterials_path, texture_filename, decompile_dir
            )
            if vmt:
                logger.info(f"Извлечен VMT файл: {vmt}")
                return vmt
        vmt = TF2VPKExtractService.extract_vmt_file(
            tf2_misc_vpk, cdmaterials_path, texture_filename, str(decompile_dir)
        )
        if vmt:
            logger.info(f"Извлечен VMT файл из misc: {vmt}")
        return vmt

    @staticmethod
    def _find_decompiled_reference_smd(qc_path: str, weapon_key: str, decompile_dir) -> Optional[str]:
        """
        Находит основной reference-SMD декомпилированной модели.

        Сначала через QC-директивы ($body/studio) — надёжнее, т.к. Crowbar
        может назвать SMD иначе, чем weapon_key (особенно для шапок).
        Иначе — запасной поиск по имени файла.
        """
        smd = ModelBuildService.extract_main_body_smd(qc_path, weapon_key)
        if not smd:
            smd = SMDService.find_reference_smd(str(decompile_dir), weapon_key)
        return smd

    @staticmethod
    def _obtain_decompiled_qc(
        ctx,
        found_mdl_path: str,
        weapon_key: str,
        tf2_misc_vpk: str,
        crowbar_exe: str,
        debug_mode: bool,
        language: str,
        t: dict,
        emit_sub,
    ) -> Tuple[Optional[str], bool, Optional[str]]:
        """
        Возвращает QC-файл декомпилированной модели.

        Сначала пытается восстановить из кэша (cache hit — пропускает
        распаковку и Crowbar). Иначе извлекает MDL-набор из VPK и
        декомпилирует через Crowbar.

        Returns:
            (qc_path, was_cached, error). error != None → фатальная ошибка
            (MDL не извлёкся); вызывающий код чистит ctx и возвращает ошибку.
        """
        cached_decompile = get_cached_decompile(weapon_key, tf2_misc_vpk, found_mdl_path)
        if cached_decompile:
            # CACHE HIT — пропускаем extraction и decompile
            emit_sub(-1, "Restoring cache..." if language == "en" else "Восстановление кэша...")
            qc_path = restore_from_cache(cached_decompile, ctx.decompile_dir)
            return qc_path, True, None

        # CACHE MISS — извлекаем и декомпилируем
        emit_sub(-1, "Extracting model..." if language == "en" else "Извлечение модели...")
        logger.info(f"Извлекаем файлы модели: {found_mdl_path}")
        extracted_files = TF2VPKExtractService.extract_file_set(
            tf2_misc_vpk,
            found_mdl_path,
            str(ctx.extract_dir),
            str(VPKService._get_vpk_tool()),
        )

        mdl_file = next((f for f in extracted_files if f.endswith('.mdl')), None)
        if not mdl_file:
            return None, False, t['error_mdl_not_extracted'].format(path=found_mdl_path)

        if debug_mode:
            DebugService.save_extracted_stage(ctx, extracted_files)

        emit_sub(-1, "Decompiling model..." if language == "en" else "Декомпиляция модели...")
        logger.info(f"Запускаем Crowbar для {weapon_key}...")
        qc_path = ModelBuildService.decompile(mdl_file, ctx.decompile_dir, crowbar_exe)
        if debug_mode:
            DebugService.save_decompiled_stage(ctx, ctx.decompile_dir)
        return qc_path, False, None

    @staticmethod
    def _apply_model_replacement(
        ctx,
        qc_path: str,
        weapon_key: str,
        replace_model_smd_path: Optional[str],
        extra_model_callback,
        language: str,
        emit_sub,
    ) -> None:
        """
        Применяет пользовательскую замену модели поверх декомпилированных SMD.

        1. Главный reference-SMD: nodes/skeleton/материалы — из оригинала,
           данные треугольников — из пользовательского файла.
        2. Доп. части (shell, scope и т.п.): спрашивает каждую через
           extra_model_callback и заменяет по тому же принципу.

        Ошибки замены не прерывают сборку — логируются, сборка продолжается
        с оригинальной моделью.
        """
        if replace_model_smd_path and os.path.exists(replace_model_smd_path):
            try:
                # Ищем основной reference-SMD через QC-директивы ($body/studio).
                # Это надёжнее поиска по имени файла, т.к. Crowbar может назвать SMD
                # иначе чем weapon_key (особенно для шапок).
                _smd_files_in_decompile = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')] if ctx.decompile_dir.exists() else []
                logger.info(f"[REPLACE] weapon_key={weapon_key!r}  decompile SMDs={_smd_files_in_decompile}")

                original_smd_path = VPKService._find_decompiled_reference_smd(
                    qc_path, weapon_key, ctx.decompile_dir
                )

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

    @staticmethod
    def _copy_precompiled_model(
        model_ready_path: str,
        qc_path: str,
        weapon_key: str,
        ctx,
        language: str,
        emit_sub,
    ) -> None:
        """
        Копирует pre-compiled модель (.mdl/.vvd/.vtx/.phy) в compile_dir,
        переименовывая под $modelname из QC (а не под имя пользовательского
        файла) — иначе все файлы мода получат чужое имя. studiomdl не нужен.
        """
        emit_sub(-1, "Copying ready model..." if language == "en" else "Копирование готовой модели...")
        try:
            ready_dir   = os.path.dirname(model_ready_path)
            ready_stem  = os.path.splitext(os.path.basename(model_ready_path))[0]
            model_exts  = ('.mdl', '.vvd', '.vtx', '.phy', '.dx80.vtx', '.dx90.vtx', '.sw.vtx')
            # Целевое имя: $modelname из QC (совпадает с weapon_key).
            # Запрещено падать обратно на ready_stem (имя пользовательского файла) —
            # это приводит к тому, что все файлы мода переименовываются в имя
            # загруженной модели вместо оригинального имени шапки/оружия.
            qc_modelname = ModelBuildService.extract_modelname_path(qc_path)
            if qc_modelname:
                target_stem = os.path.splitext(os.path.basename(qc_modelname))[0]
            else:
                # Fallback на weapon_key (оригинальное имя из игры), а не на ready_stem
                target_stem = weapon_key
                logger.warning(
                    f"[MODEL READY] $modelname не найден в QC, используем weapon_key={weapon_key!r} "
                    f"вместо ready_stem={ready_stem!r}"
                )
            logger.info(
                f"[MODEL READY] ready_stem={ready_stem!r} → target_stem={target_stem!r}"
            )
            ensure_directory_exists(ctx.compile_dir)
            copied = 0
            for fname in os.listdir(ready_dir):
                base, ext = os.path.splitext(fname)
                # Простые расширения (os.path.splitext возвращает с точкой: '.mdl')
                if base == ready_stem and ext.lower() in ('.mdl', '.vvd', '.phy'):
                    dst_name = target_stem + ext
                    copy_file_safe(
                        os.path.join(ready_dir, fname),
                        str(ctx.compile_dir / dst_name)
                    )
                    copied += 1
                elif fname.startswith(ready_stem) and any(fname.endswith(e) for e in model_exts):
                    # Составные расширения: .dx90.vtx, .sw.vtx и т.п.
                    suffix  = fname[len(ready_stem):]
                    dst_name = target_stem + suffix
                    copy_file_safe(
                        os.path.join(ready_dir, fname),
                        str(ctx.compile_dir / dst_name)
                    )
                    copied += 1
            if copied == 0:
                logger.warning(
                    f"Не найдено ни одного файла модели рядом с {model_ready_path}. "
                    "Попробуем всё равно продолжить."
                )
            logger.info(f"Готовая модель: скопировано {copied} файлов в {ctx.compile_dir}")
        except Exception as _e:
            logger.error(f"Ошибка копирования готовой модели: {_e}", exc_info=True)

    @staticmethod
    def _start_model_compile(
        model_ready_path: Optional[str],
        qc_path: str,
        weapon_key: str,
        ctx,
        studiomdl_exe: str,
        tf_dir: str,
        debug_mode: bool,
        language: str,
        emit_sub,
    ) -> Tuple[threading.Thread, list]:
        """
        Запускает (в фоне) получение скомпилированной модели и возвращает
        (compile_thread, compile_exc). Вызывающий код делает join() и, если
        compile_exc[0] не None, поднимает исключение.

        Сценарии:
          • model_ready = .smd → заменяем reference SMD и компилируем studiomdl;
          • model_ready = .mdl → копируем pre-compiled файлы (без studiomdl);
          • обычная сборка → компилируем декомпилированный QC.
        Компиляция идёт в фоне параллельно генерации VTF/VMT в главном потоке.
        """
        compile_exc: list = [None]

        def _do_compile() -> None:
            try:
                emit_sub(-1, "Compiling model..." if language == "en" else "Компиляция модели...")
                ModelBuildService.compile(qc_path, ctx.compile_dir, studiomdl_exe, tf_dir)
                if debug_mode:
                    DebugService.save_compiled_stage(ctx, ctx.compile_dir)
            except Exception as _e:
                compile_exc[0] = _e

        if model_ready_path and os.path.exists(model_ready_path):
            if model_ready_path.lower().endswith('.smd'):
                # SMD: заменяем reference SMD оригинала и компилируем через studiomdl
                emit_sub(-1, "Replacing model SMD..." if language == "en" else "Замена SMD модели...")
                try:
                    original_smd_path = VPKService._find_decompiled_reference_smd(
                        qc_path, weapon_key, ctx.decompile_dir
                    )
                    if original_smd_path:
                        logger.info(f"[MODEL READY SMD] Копируем {model_ready_path} → {original_smd_path}")
                        copy_file_safe(model_ready_path, original_smd_path)
                    else:
                        logger.warning(
                            f"[MODEL READY SMD] Не найден reference SMD для {weapon_key}, "
                            f"копируем в decompile_dir как {weapon_key}_reference.smd"
                        )
                        copy_file_safe(model_ready_path, str(ctx.decompile_dir / f"{weapon_key}_reference.smd"))
                except Exception as _e:
                    logger.error(f"Ошибка замены SMD модели: {_e}", exc_info=True)
                thread = threading.Thread(target=_do_compile, daemon=True)
            else:
                # MDL: копируем готовые pre-compiled файлы, studiomdl не нужен
                VPKService._copy_precompiled_model(
                    model_ready_path, qc_path, weapon_key, ctx, language, emit_sub
                )
                thread = threading.Thread(target=lambda: None, daemon=True)
        else:
            # Обычная сборка: компилируем декомпилированный QC
            thread = threading.Thread(target=_do_compile, daemon=True)

        thread.start()
        return thread, compile_exc

    @staticmethod
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
        после сборки), либо None.

        Приоритет источника: отредактированный пользователем VMT → извлечённый
        из игры → шаблон по $cdmaterials. Затем: снятие красок (шапки),
        анимация ($basetexture) и $bumpmap (normal-map).
        """
        vmt_to_delete = None
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

        # Для шапок: если пользователь не хочет красок из игры — удаляем прокси красок
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
        return vmt_to_delete

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
        model_ready_path: Optional[str] = None,
        draw_uv_layout: bool = False,
        replace_model_path: str = None,
        model_file_callback: Optional[Callable[[], Optional[str]]] = None,
        extra_texture_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        extra_model_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        texture_mismatch_callback: Optional[Callable[[str], bool]] = None,
        language: str = "en",
        custom_vtf_path: str = None,
        blu_mode: str = "none",
        blu_image_path: Optional[str] = None,
        custom_vpk_source_path: Optional[str] = None,
        hat_mdl_path: Optional[str] = None,
        hat_apply_game_paints: bool = True,
        panel_extra_textures: Optional[dict] = None,
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

            # ── Кастомный мод (пользователь загрузил готовый VPK) ───────── #
            if mode == "custom":
                from src.services.custom_vpk_service import CustomVPKService
                if not custom_vpk_source_path:
                    return False, t.get('error_no_custom_vpk', 'No custom VPK file loaded.'), False

                emit_progress(10, t.get('build_extracting', 'Extracting model...'))
                success, message = CustomVPKService.build_custom_mod(
                    custom_vpk_source_path=custom_vpk_source_path,
                    image_path=image_path,
                    size=size,
                    format_type=format_type,
                    flags=flags,
                    vtf_options=vtf_options,
                    export_folder=export_folder,
                    filename=filename,
                    extra_texture_callback=extra_texture_callback,
                    language=language,
                    sub_progress_callback=emit_sub,
                    custom_vtf_path=custom_vtf_path,
                    hat_mdl_path=hat_mdl_path,
                )
                emit_progress(100 if success else 0,
                              t.get('build_completed', 'Build completed') if success
                              else t.get('build_error_status', 'Build error'))
                return success, message, False

            is_special_mode = mode in SPECIAL_MODES.values()

            _sub_label_init = "Preparing..." if language == "en" else "Подготовка..."
            emit_sub(-1, _sub_label_init)

            # Аргументы build_vpk одинаковы для обоих режимов — собираем один раз.
            build_kwargs = dict(
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
                model_ready_path=model_ready_path,
                draw_uv_layout=draw_uv_layout,
                replace_model_path=replace_model_path,
                model_file_callback=model_file_callback if replace_model_enabled else None,
                extra_texture_callback=extra_texture_callback,
                extra_model_callback=extra_model_callback,
                texture_mismatch_callback=texture_mismatch_callback,
                language=language,
                custom_vtf_path=custom_vtf_path,
                blu_mode=blu_mode,
                blu_image_path=blu_image_path,
                sub_progress_callback=emit_sub,
                hat_mdl_path=hat_mdl_path,
                hat_apply_game_paints=hat_apply_game_paints,
                panel_extra_textures=panel_extra_textures,
            )

            if is_special_mode:
                emit_progress(20, t.get('build_processing', 'Processing texture...'))
                success, message = VPKService.build_vpk(**build_kwargs)
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
                    success, message = VPKService.build_vpk(**build_kwargs)
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
        model_ready_path: Optional[str] = None,
        draw_uv_layout: bool = False,
        parent_window=None,  # Окно для диалогов (если нужно показать что-то юзеру)
        replace_model_path: str = None,  # Путь к модели для замены (для тестов, обычно None)
        model_file_callback=None,  # Колбэк для запроса файла из UI потока (потому что Qt не любит мультипоточность)
        extra_texture_callback=None,  # Колбэк для запроса одной доп. текстуры: callback(material_name, weapon_key) -> Optional[str]
        extra_model_callback=None,  # Колбэк для запроса доп. модели: callback(smd_name, weapon_key) -> Optional[str]
        texture_mismatch_callback=None,  # Колбэк для предупреждения о несовпадении текстур: callback(msg) -> bool
        hat_mdl_path: Optional[str] = None,  # Прямой MDL-путь для шапок (обходит WEAPON_MDL_PATHS)
        hat_apply_game_paints: bool = True,  # True = сохранить краски игры, False = убрать прокси красок из VMT
        language: str = "en",  # Язык для ошибок
        custom_vtf_path: str = None,  # Если юзер сам сделал VTF - используем его вместо генерации из картинки
        blu_mode: str = "none",       # BLU-командная текстура: 'none' | 'same' | 'upload' | 'hue_shift'
        blu_image_path: str = None,   # Путь к BLU-изображению (для 'upload' / 'hue_shift')
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        panel_extra_textures: Optional[dict] = None,  # {mat_name: img_path} из 2D панели
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
            
            # Для режимов рук weapon_key — это ключ arm-модели (например "c_scout_arms"),
            # а не суффикс mode-строки (который дал бы бессмысленное "hands").
            # Для режимов скина персонажа weapon_key — это ключ MDL модели (например "player_scout").
            if mode == "hat" and hat_mdl_path:
                # Шапка: weapon_key берём из стема MDL-пути
                weapon_key = Path(hat_mdl_path).stem
                logger.info(f"[HAT] hat_mdl_path={hat_mdl_path!r}  →  weapon_key={weapon_key!r}")
            elif mode in HAND_MODE_KEYS:
                from src.data.player_hands import HAND_MODES as _HAND_MODES
                _arm_key = _HAND_MODES.get(mode, {}).get('arm_model', '')
                if not _arm_key:
                    return False, f"No arm_model defined for hand mode: {mode}"
                weapon_key = _arm_key
            elif mode in PLAYER_BODY_MODE_KEYS:
                from src.data.player_characters import PLAYER_CHARACTERS as _PC
                _mdl_path = _PC.get(mode, {}).get('mdl_path', '')
                weapon_key = Path(_mdl_path).stem if _mdl_path else mode
            elif mode == SPY_MASK_MODE_KEY:
                # Маски маскировки: используем тот же MDL что и для скина шпиона
                weapon_key = Path(SPY_MDL_PATH).stem  # = 'spy'
            else:
                weapon_key = mode.split('_', 1)[1] if '_' in mode else mode
            
            # Запоминаем какой VMT надо будет удалить после сборки (если юзер его редактировал через редактор)
            vmt_to_delete = None
            
            ctx = BuildContext.create(mode, weapon_key, debug_mode=debug_mode)
            
            # ── Маски маскировки шпиона ──────────────────────────────────────── #
            # Не нужен MDL, QC-патчинг или компиляция.
            # Просто кладём mask_*.vtf/vmt по оригинальному пути игры:
            #   materials/models/player/spy/mask_*.vtf
            # Это прямой override, как у SPECIAL_MODES.
            if mode == SPY_MASK_MODE_KEY:
                result = VPKService._build_spy_masks_vpk(
                    ctx=ctx,
                    image_path=image_path,
                    size=size,
                    format_type=format_type,
                    flags=flags or [],
                    vtf_options=vtf_options,
                    filename=filename,
                    export_folder=export_folder,
                    language=language,
                    extra_texture_callback=extra_texture_callback,
                    tf2_root_dir=tf2_root_dir,
                    keep_temp_on_error=keep_temp_on_error,
                    debug_mode=debug_mode,
                    t=t,
                )
                return result

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

            else:
                # Для обычного оружия и рук — декомпиляция + патч QC + компиляция.
                # Для рук замена SMD-модели не поддерживается.
                if mode in HAND_MODE_KEYS:
                    replace_model_enabled = False

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
                
                # ── Строим список путей для поиска MDL ───────────────────────────── #
                paths_to_try, _mdl_path_error = VPKService._build_mdl_search_paths(
                    mode, weapon_key, hat_mdl_path, t
                )
                if _mdl_path_error:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, _mdl_path_error

                crowbar_exe = TF2Paths.get_crowbar_path()
                
                try:
                    found_mdl_path, _mdl_find_error = VPKService._find_existing_mdl(
                        paths_to_try, tf2_misc_vpk, weapon_key, t
                    )
                    if _mdl_find_error:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, _mdl_find_error
                    
                    # Для шапок с %s-плейсхолдером: обновляем weapon_key на реальный стем
                    # (all_domination_%s → all_domination_heavy), иначе кэш и имена файлов сломаются
                    if mode == "hat" and hat_mdl_path and "%s" in hat_mdl_path:
                        weapon_key = Path(found_mdl_path).stem
                        logger.info(f"Hat weapon_key обновлён: {weapon_key}")

                    # === Кэш декомпила — проверяем ДО extraction ===
                    # Ключ: weapon_key + vpk_path + mdl_rel_path + mtime(vpk).
                    # mtime VPK меняется при каждом обновлении TF2 → авто-инвалидация.
                    # При cache hit: пропускаем extract_file_set (3-10 сек) + Crowbar (10-30 сек).
                    qc_path, cached_decompile, _decomp_error = VPKService._obtain_decompiled_qc(
                        ctx, found_mdl_path, weapon_key, tf2_misc_vpk, crowbar_exe,
                        debug_mode, language, t, emit_sub,
                    )
                    if _decomp_error:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, _decomp_error

                    if draw_uv_layout:
                        VPKService._generate_uv_layout(ctx, weapon_key, size, export_folder, language)

                    # Удаляем LOD файлы до кэширования — чтобы в кэше лежали уже чистые файлы
                    ModelBuildService.remove_lod_files(ctx.decompile_dir)

                    # Сохраняем в кэш после очистки — следующая сборка пропустит extraction + decompile
                    if not cached_decompile:
                        save_to_cache(weapon_key, tf2_misc_vpk, found_mdl_path, ctx.decompile_dir)
                    
                    # Заменяем модель, если включен режим замены
                    # Пропускаем если model_ready_path задан — пользователь уже указал готовый файл
                    # Диалог выбора файла показываем здесь, после декомпиляции (чтобы знать куда копировать)
                    replace_model_smd_path = VPKService._resolve_replace_model_smd(
                        replace_model_enabled, model_ready_path, replace_model_path,
                        model_file_callback, parent_window,
                    )
                    
                    VPKService._apply_model_replacement(
                        ctx, qc_path, weapon_key, replace_model_smd_path,
                        extra_model_callback, language, emit_sub,
                    )
                    
                    # Извлекаем путь из $cdmaterials в QC файле (до патчинга, потому что потом мы его изменим)
                    original_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
                    # Все $cdmaterials пути (для поиска оригинальных VTF в VPK игры)
                    original_cdmaterials_paths = ModelBuildService.extract_all_cdmaterials_paths_from_qc(qc_path)

                    if not original_cdmaterials_path:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_cdmaterials_not_extracted'].format(qc_path=qc_path)
                    
                    # Извлекаем имя файла из $texturegroup (до патчинга, потому что потом мы его изменим)
                    texture_filename = ModelBuildService.extract_texturegroup_filename(qc_path)
                    if not texture_filename:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, t['error_texturegroup_not_extracted'].format(qc_path=qc_path)

                    if mode == "hat":
                        logger.info(
                            f"[HAT BUILD NAMES]  qc={qc_path!r}\n"
                            f"  weapon_key          = {weapon_key!r}\n"
                            f"  texture_filename    = {texture_filename!r}\n"
                            f"  cdmaterials_path    = {original_cdmaterials_path!r}\n"
                            f"  replace_smd_path    = {replace_model_smd_path!r}"
                        )
                        # Показываем пользователю оригинальные имена из игры (не имена файла-замены)
                        _repl_name = os.path.basename(replace_model_smd_path) if replace_model_smd_path else None
                        if _repl_name:
                            emit_sub(-1,
                                f"Original game names: model={weapon_key}, texture={texture_filename}"
                                if language == "en" else
                                f"Оригинальные имена из игры: модель={weapon_key}, текстура={texture_filename}"
                            )
                    
                    # Извлекаем полную структуру $texturegroup для поддержки:
                    # 1. BLU команды (отдельная строка/row в texturegroup)
                    # 2. Дополнительных материалов (shell, scope и т.д. - столбцы/columns)
                    tg_structure = ModelBuildService.extract_texturegroup_structure(qc_path)
                    blu_row = tg_structure.get('blu_row', [])
                    extra_materials = tg_structure.get('extra_materials', [])

                    # ── Для режимов рук: фильтруем $texturegroup до актуальных текстур рук ─────────
                    # Проблема: QC руки инженера (c_engineer_arms) в column 0 содержит "engineer_red"
                    # (текстуру ТЕЛА), а не текстуру руки. Аналогично у медика — "medic_red".
                    # Без фильтрации пользовательское изображение заменяет всё тело персонажа,
                    # а не только руки, потому что именно column 0 получает изображение пользователя.
                    #
                    # Решение: для hand-режимов сравниваем текстуры из QC со списком рук
                    # из player_hands.py и оставляем только совпадающие (+ их BLU-варианты).
                    if mode in HAND_MODE_KEYS:
                        from src.data.player_hands import get_hand_textures as _ght_hands
                        _h_list = _ght_hands(mode)  # [(folder, vtf_name), ...]
                        _h_names_lc = {n.lower() for _, n in _h_list}

                        _red_row_full = tg_structure.get('red_row', [])
                        _blu_row_full = tg_structure.get('blu_row', [])

                        # Позиции в red_row, где стоят настоящие текстуры рук
                        _hand_idx = [i for i, t in enumerate(_red_row_full)
                                     if t.lower() in _h_names_lc]

                        # Переопределяем texture_filename если column 0 — текстура тела
                        if texture_filename.lower() not in _h_names_lc:
                            if _hand_idx:
                                texture_filename = _red_row_full[_hand_idx[0]]
                            elif _h_list:
                                texture_filename = _h_list[0][1]
                            logger.info(
                                f"[HANDS] texture_filename → {texture_filename!r} "
                                f"(body texture excluded from mod)"
                            )

                        # blu_row: BLU-варианты строго на позициях hand-текстур в red_row.
                        # Если BLU-текстура на этой позиции совпадает с RED — это нейтральная
                        # (общая) текстура; она будет создана через путь extra_materials/main, не BLU.
                        # Важно: вычисляем РАНЬШЕ extra_materials, чтобы избежать дублирования.
                        _filtered_blu: list = []
                        for _hi in _hand_idx:
                            if _hi < len(_blu_row_full):
                                _b = _blu_row_full[_hi]
                                _r = _red_row_full[_hi]
                                if _b.lower() != _r.lower():
                                    _filtered_blu.append(_b)
                        blu_row = _filtered_blu
                        _filtered_blu_lc = {t.lower() for t in _filtered_blu}

                        # extra_materials: hand-текстуры из red_row, кроме основной
                        # и кроме тех, что уже попали в blu_row (иначе создадутся дважды).
                        extra_materials = [
                            _red_row_full[i] for i in _hand_idx
                            if _red_row_full[i].lower() != texture_filename.lower()
                            and _red_row_full[i].lower() not in _filtered_blu_lc
                        ]

                        logger.info(
                            f"[HANDS] texture_filename={texture_filename!r}, "
                            f"extra_materials={extra_materials}, blu_row={blu_row}"
                        )

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
                    
                    # ── Проверка текстур в пользовательском SMD (режим «Модель уже готова») ──
                    if (model_ready_path and os.path.exists(model_ready_path)
                            and model_ready_path.lower().endswith('.smd')):
                        try:
                            user_materials = SMDService.extract_unique_materials(model_ready_path)
                            if user_materials:
                                # Ищем оригинальный reference SMD для сравнения
                                original_smd_for_check = VPKService._find_decompiled_reference_smd(
                                    qc_path, weapon_key, ctx.decompile_dir
                                )

                                if original_smd_for_check:
                                    original_materials = SMDService.extract_unique_materials(original_smd_for_check)
                                    if original_materials and user_materials != original_materials:
                                        # Есть расхождение — формируем сообщение
                                        missing_in_user = original_materials - user_materials
                                        extra_in_user = user_materials - original_materials

                                        lines = []
                                        if language == "ru":
                                            lines.append("Текстуры в вашем SMD файле не совпадают с оригинальной моделью.\n")
                                            if missing_in_user:
                                                lines.append("Отсутствуют (есть в оригинале, нет у вас):")
                                                for m in sorted(missing_in_user):
                                                    lines.append(f"  • {m}")
                                            if extra_in_user:
                                                lines.append("Лишние (есть у вас, нет в оригинале):")
                                                for m in sorted(extra_in_user):
                                                    lines.append(f"  • {m}")
                                            lines.append("\nПродолжить сборку с этими текстурами?")
                                        else:
                                            lines.append("Textures in your SMD file do not match the original model.\n")
                                            if missing_in_user:
                                                lines.append("Missing (in original, not in yours):")
                                                for m in sorted(missing_in_user):
                                                    lines.append(f"  • {m}")
                                            if extra_in_user:
                                                lines.append("Extra (in yours, not in original):")
                                                for m in sorted(extra_in_user):
                                                    lines.append(f"  • {m}")
                                            lines.append("\nContinue building with these textures?")

                                        warning_msg = "\n".join(lines)
                                        logger.warning(f"[MODEL READY] Несовпадение текстур SMD:\n{warning_msg}")

                                        if texture_mismatch_callback:
                                            should_continue = texture_mismatch_callback(warning_msg)
                                            if not should_continue:
                                                logger.info("[MODEL READY] Пользователь отменил сборку из-за несовпадения текстур")
                                                ctx.cleanup(on_error=False, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                                                cancel_msg = (
                                                    "Сборка отменена: несовпадение текстур в SMD файле."
                                                    if language == "ru" else
                                                    "Build cancelled: texture mismatch in SMD file."
                                                )
                                                return False, cancel_msg
                                    elif original_materials:
                                        logger.info(f"[MODEL READY] Текстуры SMD совпадают с оригиналом: {user_materials}")
                        except Exception as _tex_check_err:
                            logger.warning(f"[MODEL READY] Ошибка проверки текстур SMD: {_tex_check_err}", exc_info=True)
                            # Не блокируем сборку из-за ошибки проверки

                    # ── Компиляция модели в фоне: обычная / SMD-замена / готовый MDL ──
                    _compile_thread, _compile_exc = VPKService._start_model_compile(
                        model_ready_path, qc_path, weapon_key, ctx,
                        studiomdl_exe, tf_dir, debug_mode, language, emit_sub,
                    )

                    is_normal_map = False
                    animated_fps = None

                    # spy_masks обрабатывается РАНЬШЕ (до MDL pipeline) через
                    # _build_spy_masks_vpk — сюда попасть не должен.

                    # RED не загружен — сначала спрашиваем пользователя
                    # через существующий extra_texture_callback (стандартный диалог).
                    # Если callback вернул EXTRA_TEX_USE_GAME_ORIGINAL или None —
                    # извлекаем оригинал из игрового VPK.
                    if image_path == EXTRA_TEX_USE_GAME_ORIGINAL:
                        if extra_texture_callback:
                            image_path = extra_texture_callback(texture_filename, weapon_key)
                            logger.info(f"Callback для основной RED текстуры: {image_path!r}")

                        if image_path == EXTRA_TEX_USE_GAME_ORIGINAL or not image_path:
                            # Пользователь выбрал «из игры» или ничего — берём оригинал
                            _tex_vpk_early = TF2Paths.resolve_textures_vpk(tf2_root_dir)
                            _orig_red = VPKService._get_original_vtf_bytes(
                                texture_filename, original_cdmaterials_paths,
                                _tex_vpk_early, tf2_misc_vpk
                            )
                            ensure_directory_exists(vtf_output_path)
                            vtf_file_path = vtf_output_path / vtf_filename
                            if _orig_red:
                                with open(vtf_file_path, "wb") as _f:
                                    _f.write(_orig_red)
                                logger.info(f"Оригинальная RED VTF из игры: {vtf_filename}")
                            else:
                                logger.warning(f"Не найден оригинальный RED VTF: '{texture_filename}'")
                            image_path = None  # VTF уже на месте, не передаём дальше

                    if custom_vtf_path:
                        # Если юзер сам сделал VTF - просто копируем его, не генерируем из картинки
                        vtf_file_path = vtf_output_path / vtf_filename
                        ensure_directory_exists(vtf_output_path)
                        copy_file_safe(custom_vtf_path, vtf_file_path)
                        logger.info(f"Использован пользовательский VTF файл: {custom_vtf_path} -> {vtf_file_path}")
                    elif image_path:
                        animated_fps, is_normal_map = TextureService.render_image_to_vtf(
                            image_path,
                            vtf_output_path=vtf_output_path,
                            out_vtf_path=vtf_output_path / vtf_filename,
                            temp_png_path=vtf_temp_png,
                            normal_base=texture_filename,
                            size=size,
                            format_type=format_type,
                            flags=flags,
                            vtf_options=vtf_options,
                        )
                    
                    # Извлекаем оригинальный VMT по пути из QC (до патчинга) — в VPK он
                    # лежит по оригинальному пути. tf2_textures_vpk нужен и дальше по коду.
                    tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
                    vmt_file = VPKService._extract_original_vmt(
                        original_cdmaterials_path, texture_filename,
                        tf2_textures_vpk, tf2_misc_vpk, ctx.decompile_dir,
                    )
                    
                    vmt_to_delete = VPKService._write_main_vmt(
                        vmt_file, vmt_path, texture_filename, patched_cdmaterials_path,
                        mode, hat_apply_game_paints, animated_fps, is_normal_map,
                    )

                    # ── BLU Team Texture (командная раскраска) ───────────────────────────
                    VPKService._build_blu_team_texture(
                        blu_mode, blu_image_path, vtf_output_path, vtf_filename, vmt_path,
                        texture_filename, patched_cdmaterials_path, size, format_type, flags, vtf_options,
                    )

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
                        
                        # Спрашиваем пользователя — нужна ли отдельная текстура для этого материала
                        extra_image_path = extra_texture_callback(extra_mat_name, weapon_key) if extra_texture_callback else None
                        # «Использовать обычную» — берём VTF прямо из игрового VPK
                        if extra_image_path == EXTRA_TEX_USE_GAME_ORIGINAL:
                            logger.info(f"Извлекаем оригинал из игры для: {extra_mat_name}")
                            _game_vtf = VPKService._get_original_vtf_bytes(
                                extra_mat_name, original_cdmaterials_paths,
                                tf2_textures_vpk, tf2_misc_vpk
                            )
                            if _game_vtf:
                                with open(extra_vtf_path, "wb") as _f:
                                    _f.write(_game_vtf)
                                logger.info(f"VTF из игры скопирован: {extra_mat_name}.vtf")
                            else:
                                # Fallback: копируем основную текстуру
                                red_vtf_path = vtf_output_path / vtf_filename
                                if red_vtf_path.exists():
                                    copy_file_safe(red_vtf_path, extra_vtf_path)
                            extra_image_path = None  # VTF уже на месте, пропускаем if-блок ниже

                        if extra_image_path and not os.path.isfile(extra_image_path):
                            logger.warning(f"Файл не найден: {extra_image_path}")
                            extra_image_path = None

                        extra_animated_fps = None
                        if extra_image_path and os.path.isfile(extra_image_path):
                            # Пользователь предоставил отдельное изображение для этого материала
                            logger.info(f"Используем отдельное изображение для {extra_mat_name}: {extra_image_path}")

                            if custom_vtf_path:
                                # Пользователь использует VTF - копируем
                                copy_file_safe(extra_image_path, extra_vtf_path)
                            elif TextureService.is_animated_image(extra_image_path):
                                vtf_flags_extra, merged_extra = TextureService.resolve_vtf_flags_and_options(flags, vtf_options)
                                extra_animated_fps = TextureService.create_animated_vtf(
                                    extra_image_path, str(extra_vtf_path),
                                    size, format_type, vtf_flags_extra, merged_extra
                                )
                            else:
                                extra_temp_png = vtf_output_path / f"{extra_mat_name}.png"
                                VPKService._process_image(extra_image_path, extra_temp_png, size)
                                vtf_flags_extra, merged_extra = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                                VPKService._create_vtf(str(extra_temp_png), str(vtf_output_path), format_type, vtf_flags_extra, merged_extra)
                                if extra_temp_png.exists():
                                    extra_temp_png.unlink()
                        else:
                            # Пользователь не предоставил изображение.
                            # В мод попадает ТОЛЬКО то, что пользователь явно загрузил
                            # или выбрал «использовать из игры». Всё остальное движок
                            # найдёт через другие $cdmaterials пути — не добавляем.
                            if not extra_vtf_path.exists():
                                logger.debug(f"Доп. материал пропускается (нет изображения): {extra_mat_name}")
                                continue
                        
                        extra_materials_vtf_paths[extra_mat_name] = extra_vtf_path
                        
                        # VMT для дополнительного материала
                        VPKService._write_material_vmt(extra_vmt_path, vmt_path, patched_cdmaterials_path, extra_mat_name)
                        
                        # Если пользователь загрузил свою extra-текстуру — используем её FPS.
                        # Если extra_image не было (скопирована основная VTF) — используем FPS основной.
                        # Если extra_image статична — не анимируем extra VMT вообще.
                        if extra_image_path and os.path.isfile(extra_image_path):
                            _extra_fps = extra_animated_fps
                        else:
                            _extra_fps = animated_fps
                        if _extra_fps:
                            VMTService.enable_animated_basetexture(str(extra_vmt_path), _extra_fps)
                    
                    # === Создаем текстуры для BLU команды ===
                    # BLU - это отдельная строка (row 1) в $texturegroup
                    # Для каждого материала в BLU строке спрашиваем отдельное изображение,
                    # если пользователь отказывается — копируем соответствующую RED текстуру
                    if blu_row:
                        red_row = tg_structure.get('red_row', [])
                        tex_ctx = TextureBuildContext(
                            vtf_output_path=vtf_output_path,
                            size=size,
                            format_type=format_type,
                            flags=flags,
                            vtf_options=vtf_options,
                            custom_vtf_path=custom_vtf_path,
                        )

                        for col_idx, blu_tex_name in enumerate(blu_row):
                            # Находим соответствующее RED имя для этого столбца
                            red_tex_name = red_row[col_idx] if col_idx < len(red_row) else None

                            if not red_tex_name:
                                # Скин-вариант (австралий, gold) имеет БОЛЬШЕ материалов, чем обычный.
                                # Например: normal { c_scattergun }, australian { c_scattergun, c_scattergun_gold }.
                                # c_scattergun_gold нет в RED-строке, но нам всё равно нужно его включить в мод.
                                # Спрашиваем пользователя и создаём текстуру (или копируем основную).
                                logger.info(
                                    f"Дополнительный материал варианта (нет RED аналога): {blu_tex_name} (col {col_idx})"
                                )
                                _variant_vtf_path = vtf_output_path / f"{blu_tex_name}.vtf"
                                _variant_vmt_path = vtf_output_path / f"{blu_tex_name}.vmt"

                                if not _variant_vtf_path.exists():
                                    _variant_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                                    if _variant_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                                        logger.info(f"Извлекаем оригинал варианта из игры: {blu_tex_name}")
                                        _game_vtf = VPKService._get_original_vtf_bytes(
                                            blu_tex_name, original_cdmaterials_paths,
                                            tf2_textures_vpk, tf2_misc_vpk
                                        )
                                        if _game_vtf:
                                            with open(_variant_vtf_path, "wb") as _f:
                                                _f.write(_game_vtf)
                                        else:
                                            _main_vtf = vtf_output_path / vtf_filename
                                            if _main_vtf.exists():
                                                copy_file_safe(_main_vtf, _variant_vtf_path)
                                        _variant_img = None  # VTF на месте, пропускаем блок ниже
                                    if _variant_img and not os.path.isfile(_variant_img):
                                        _variant_img = None
                                    if _variant_img:
                                        tex_ctx.render_user_image_vtf(_variant_img, _variant_vtf_path, f"{blu_tex_name}.png")
                                        logger.info(f"Создан VTF варианта (отд. изображение): {blu_tex_name}.vtf")
                                    elif not _variant_vtf_path.exists():
                                        # Пользователь отказался или нет callback — копируем основную
                                        _main_vtf = vtf_output_path / vtf_filename
                                        if _main_vtf.exists():
                                            copy_file_safe(_main_vtf, _variant_vtf_path)
                                            logger.info(f"Создан VTF варианта (копия основной): {blu_tex_name}.vtf")
                                        else:
                                            logger.warning(f"Основной VTF не найден для варианта: {_main_vtf}")

                                if not _variant_vmt_path.exists():
                                    VPKService._write_material_vmt(_variant_vmt_path, vmt_path, patched_cdmaterials_path, blu_tex_name)
                                    if animated_fps:
                                        VMTService.enable_animated_basetexture(str(_variant_vmt_path), animated_fps)
                                continue
                            
                            # Если BLU имя совпадает с RED — shared/нейтральная текстура.
                            #
                            # Два типа:
                            #   1. СИСТЕМНЫЕ (eyeball, invulnfx, _invun, _zombie) — пропускаем.
                            #      Движок найдёт сам через другой $cdmaterials (effects/).
                            #   2. НАСТОЯЩИЕ СКИНОВЫЕ (sniper_lens, c_arrow и т.п.) — спрашиваем
                            #      пользователя через extra_texture_callback, как для extra_materials.
                            if blu_tex_name == red_tex_name:
                                if blu_tex_name == texture_filename:
                                    continue

                                _n = blu_tex_name.lower()
                                _is_system_tex = (
                                    'eyeball'  in _n or
                                    'invulnfx' in _n or
                                    '_invun'   in _n or   # sniper_red_invun
                                    '_invuln'  in _n or   # sniper_lens_invuln
                                    '_zombie'  in _n
                                )

                                shared_vtf_path = vtf_output_path / f"{blu_tex_name}.vtf"
                                if not shared_vtf_path.exists():
                                    if _is_system_tex:
                                        # Системная — тихо пропускаем, движок обработает
                                        logger.debug(f"Системная shared texture пропускается: {blu_tex_name}")
                                        continue

                                    # Скиновая shared текстура — спрашиваем пользователя
                                    _shared_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                                    if _shared_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                                        _game_vtf = VPKService._get_original_vtf_bytes(
                                            blu_tex_name, original_cdmaterials_paths,
                                            tf2_textures_vpk, tf2_misc_vpk, log_not_found=False
                                        )
                                        if _game_vtf:
                                            with open(shared_vtf_path, "wb") as _f:
                                                _f.write(_game_vtf)
                                            logger.info(f"Shared VTF из игры: {blu_tex_name}.vtf")
                                        else:
                                            logger.debug(f"Shared VTF не найден в игре, пропуск: {blu_tex_name}")
                                            continue
                                    elif _shared_img and os.path.isfile(_shared_img):
                                        _sh_flags, _sh_merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                                        _sh_png = vtf_output_path / f"{blu_tex_name}.png"
                                        VPKService._process_image(_shared_img, _sh_png, size)
                                        VPKService._create_vtf(str(_sh_png), str(vtf_output_path), format_type, _sh_flags, _sh_merged)
                                        if _sh_png.exists():
                                            _sh_png.unlink()
                                        logger.info(f"Создан shared VTF: {blu_tex_name}.vtf")
                                    else:
                                        # Пользователь пропустил — не включаем
                                        logger.debug(f"Shared texture пропущена пользователем: {blu_tex_name}")
                                        continue

                                # VTF существует → создаём VMT если нет
                                shared_vmt_path = vtf_output_path / f"{blu_tex_name}.vmt"
                                if not shared_vmt_path.exists():
                                    VPKService._write_material_vmt(shared_vmt_path, vmt_path, patched_cdmaterials_path, blu_tex_name)
                                if animated_fps:
                                    VMTService.enable_animated_basetexture(str(shared_vmt_path), animated_fps)
                                continue
                            
                            logger.info(f"Создаем текстуры для BLU команды: {blu_tex_name} (RED: {red_tex_name})")
                            
                            blu_vtf_filename = f"{blu_tex_name}.vtf"
                            blu_vmt_filename = f"{blu_tex_name}.vmt"
                            blu_vtf_path = vtf_output_path / blu_vtf_filename
                            blu_vmt_path = vtf_output_path / blu_vmt_filename
                            
                            # Спрашиваем у пользователя отдельное изображение для BLU материала
                            _blu_mat_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                            if _blu_mat_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                                _game_vtf = VPKService._get_original_vtf_bytes(
                                    blu_tex_name, original_cdmaterials_paths, tf2_textures_vpk, tf2_misc_vpk
                                )
                                if _game_vtf:
                                    with open(blu_vtf_path, "wb") as _f:
                                        _f.write(_game_vtf)
                                    logger.info(f"Извлечён VTF из игры для BLU текстуры: {blu_tex_name}.vtf")
                                else:
                                    if col_idx == 0:
                                        _red_src = vtf_output_path / f"{red_tex_name}.vtf"
                                    else:
                                        _red_src = extra_materials_vtf_paths.get(
                                            red_tex_name, vtf_output_path / f"{red_tex_name}.vtf"
                                        )
                                    if _red_src.exists():
                                        copy_file_safe(_red_src, blu_vtf_path)
                                _blu_mat_img = None
                            if _blu_mat_img and not os.path.isfile(_blu_mat_img):
                                _blu_mat_img = None

                            if _blu_mat_img and os.path.isfile(_blu_mat_img):
                                # Пользователь дал отдельное изображение для этого BLU материала
                                logger.info(f"Используем отдельное изображение для BLU {blu_tex_name}: {_blu_mat_img}")
                                tex_ctx.render_user_image_vtf(_blu_mat_img, blu_vtf_path, f"{blu_tex_name}.png")
                            elif not blu_vtf_path.exists():
                                # Пользователь не предоставил изображение для BLU —
                                # не включаем в мод, движок найдёт оригинал сам.
                                logger.debug(f"BLU текстура пропускается (нет изображения): {blu_tex_name}")
                                continue

                            # Создаем VMT для BLU (копируем RED VMT и обновляем $basetexture)
                            red_vmt_src = vtf_output_path / f"{red_tex_name}.vmt"
                            VPKService._write_material_vmt(blu_vmt_path, red_vmt_src, patched_cdmaterials_path, blu_tex_name)
                            
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
                    
                    # ── Зеркальные VMT по оригинальному пути (для режимов рук) ────────────
                    # Проблема: модели оружий шпиона (Dead Ringer, Invis Watch и т.д.)
                    # ссылаются на текстуры по оригинальному пути materials/models/player/spy/,
                    # а не по пропатченному console\models\player\spy\. Из-за этого левая
                    # рука шпиона (slot 1 = spy_hands_blue) игнорирует мод.
                    # Аналогично могут быть устроены другие оружия других классов.
                    #
                    # Фикс: для режимов рук дополнительно создаём VMT-файлы по ОРИГИНАЛЬНОМУ
                    # пути из $cdmaterials (до патча). VMT указывает на те же VTF что и уже
                    # созданный мод (по console\ пути), т.е. VTF-файлы не дублируются.
                    from src.data.player_hands import HAND_MODE_KEYS as _HAND_MODE_KEYS
                    if mode in _HAND_MODE_KEYS and original_cdmaterials_path:
                        orig_mat_rel = "materials/" + original_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
                        orig_vtf_dir = ctx.vpkroot_dir
                        for _part in orig_mat_rel.rstrip('/').split('/'):
                            orig_vtf_dir = orig_vtf_dir / _part

                        if orig_vtf_dir != vtf_output_path:
                            ensure_directory_exists(orig_vtf_dir)
                            # Для каждого VMT в console\ пути создаём зеркало по оригинальному пути.
                            # Содержимое зеркального VMT = копия console\ VMT:
                            # $basetexture в нём уже ссылается на console\ VTF — это ОК,
                            # Source Engine найдёт VTF по этому абсолютному пути в мод-VPK.
                            for _vmt_src in vtf_output_path.glob("*.vmt"):
                                _vmt_mirror = orig_vtf_dir / _vmt_src.name
                                if not _vmt_mirror.exists():
                                    copy_file_safe(_vmt_src, _vmt_mirror)
                                    logger.info(f"Зеркальный VMT по оригинальному пути: {_vmt_mirror.name}")
                        else:
                            logger.debug("Оригинальный и пропатченный пути совпадают, зеркало не нужно")

                    # ── Зеркальные VMT для all-class шапок ───────────────────────────────
                    # Проблема: у all-class шапок каждый класс имеет свою модель (%s-плейсхолдер).
                    # Инструмент компилирует модель только одного класса (первый найденный в VPK)
                    # с пропатченным $cdmaterials (console\ путь). Модели остальных восьми классов
                    # берутся из базового VPK игры и ссылаются на ОРИГИНАЛЬНЫЙ путь текстур.
                    # Из-за этого только один класс видит новую текстуру.
                    #
                    # Фикс: создаём зеркальные VMT по оригинальному пути из $cdmaterials.
                    # Зеркальные VMT ссылаются на те же VTF (по console\ пути) — дублировать их не нужно.
                    # Так все классы, использующие оригинальные модели, тоже найдут кастомную текстуру.
                    if mode == "hat" and hat_mdl_path and "%s" in hat_mdl_path and original_cdmaterials_path:
                        _hat_orig_rel = "materials/" + original_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
                        _hat_orig_dir = ctx.vpkroot_dir
                        for _part in _hat_orig_rel.rstrip('/').split('/'):
                            _hat_orig_dir = _hat_orig_dir / _part

                        if _hat_orig_dir != vtf_output_path:
                            ensure_directory_exists(_hat_orig_dir)
                            for _vmt_src in vtf_output_path.glob("*.vmt"):
                                _vmt_mirror = _hat_orig_dir / _vmt_src.name
                                if not _vmt_mirror.exists():
                                    copy_file_safe(_vmt_src, _vmt_mirror)
                                    logger.info(f"Зеркальный VMT для all-class шапки: {_vmt_mirror.name}")
                        else:
                            logger.debug("Пути для шапки совпадают, зеркало не нужно")

                    if debug_mode:
                        DebugService.save_patched_stage(ctx, ctx.decompile_dir)

                    # ── Текстуры из 2D панели (c_arrow, sniper_lens и т.п.) ──────── #
                    # Материалы из SMD модели которые НЕ в QC skinfamilies →
                    # extra_texture_callback их не покрывает → добавляем здесь.
                    if panel_extra_textures:
                        # Собираем уже созданные имена (extra_materials + BLU)
                        _processed = set()
                        for _f in vtf_output_path.glob("*.vtf"):
                            _processed.add(_f.stem)

                        for _pet_name, _pet_img in panel_extra_textures.items():
                            # Защита от UI-sentinel: '__single__' — главная текстура,
                            # а не имя материала. Если протёк — пропускаем, иначе
                            # в VPK появятся мусорные __single__.vmt / __single__.vtf.
                            if not _pet_name or _pet_name.startswith('__'):
                                continue
                            if _pet_name in _processed:
                                continue   # уже создан через skinfamilies
                            if not _pet_img or not os.path.isfile(_pet_img):
                                continue
                            try:
                                ensure_directory_exists(vtf_output_path)
                                _pet_png = vtf_output_path / f"{_pet_name}.png"
                                _pet_vtf = vtf_output_path / f"{_pet_name}.vtf"
                                _pet_vmt = vtf_output_path / f"{_pet_name}.vmt"
                                VPKService._process_image(_pet_img, _pet_png, size)
                                _pet_flags, _pet_merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                                VPKService._create_vtf(
                                    str(_pet_png), str(vtf_output_path),
                                    format_type, _pet_flags, _pet_merged
                                )
                                if _pet_png.exists():
                                    _pet_png.unlink()
                                if not _pet_vmt.exists():
                                    VPKService._write_material_vmt(_pet_vmt, vmt_path, patched_cdmaterials_path, _pet_name)
                                logger.info(f"Panel extra texture: {_pet_name}.vtf/vmt")
                            except Exception as _pet_exc:
                                logger.warning(f"Panel extra texture ошибка '{_pet_name}': {_pet_exc}")

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
            # Логируем все файлы в VPK root (для отладки, чтобы видеть какие файлы идут в мод)
            if ctx.vpkroot_dir.exists():
                vpkroot_files = []
                for _root, _dirs, _files in os.walk(ctx.vpkroot_dir):
                    for _f in _files:
                        rel = os.path.relpath(os.path.join(_root, _f), ctx.vpkroot_dir).replace('\\', '/')
                        vpkroot_files.append(rel)
                logger.info(f"[VPK CONTENTS] Files going into VPK ({len(vpkroot_files)} total):\n" +
                            "\n".join(f"  {f}" for f in vpkroot_files))
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
    def _build_spy_masks_vpk(
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
        Строит VPK-мод с кастомными масками маскировки шпиона.

        В отличие от player skin, здесь НЕТ деcompile/patch/compile — только
        VTF+VMT файлы по оригинальному пути materials/models/player/spy/.
        Это гарантирует что body-текстуры шпиона остаются из игры.
        """
        try:
            is_ru = (language == 'ru')
            # Папка для текстур масок внутри vpkroot
            masks_dir = ctx.vpkroot_dir / "materials" / "models" / "player" / "spy"
            ensure_directory_exists(masks_dir)

            tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
            try:
                _, tf2_misc_vpk_path, _ = TF2Paths.resolve(tf2_root_dir)
            except Exception:
                tf2_misc_vpk_path = None

            # Оригинальный cdmaterials — нужен для VMT $basetexture
            spy_cdmat = "models/player/spy"

            any_created = False

            for cls_key, vtf_name, name_en, name_ru, btn in SPY_DISGUISE_MASKS:
                display = name_ru if is_ru else name_en
                mask_vtf_path = masks_dir / f"{vtf_name}.vtf"
                mask_vmt_path = masks_dir / f"{vtf_name}.vmt"

                # Спрашиваем пользователя через стандартный callback
                mask_img = extra_texture_callback(vtf_name, "spy") if extra_texture_callback else None

                if mask_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                    # Берём оригинал из VPK
                    orig = VPKService._get_original_vtf_bytes(
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
                elif mask_img and os.path.isfile(mask_img):
                    # Конвертируем изображение пользователя.
                    # ВАЖНО: имя PNG должно совпадать с именем VTF (без _tmp),
                    # иначе VTFCmd создаст файл с неправильным именем.
                    tmp_png = masks_dir / f"{vtf_name}.png"
                    VPKService._process_image(mask_img, tmp_png, size)
                    vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                    VPKService._create_vtf(str(tmp_png), str(masks_dir), format_type, vtf_flags, merged)
                    if tmp_png.exists():
                        tmp_png.unlink()
                    logger.info(f"Создан VTF маски: {vtf_name}.vtf")
                else:
                    # Пользователь пропустил — не включаем
                    logger.debug(f"Маска пропущена: {vtf_name}")
                    continue

                # VMT — простой VertexLitGeneric по оригинальному пути
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
            vpk_path = VPKService._create_vpk_file(ctx, filename, export_folder, language)
            ctx.cleanup(on_error=False, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            logger.info(f"VPK масок шпиона готов: {vpk_path}")
            return True, vpk_path

        except Exception as exc:
            logger.error(f"_build_spy_masks_vpk: {exc}", exc_info=True)
            if ctx:
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, str(exc)

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
    def _get_original_vtf_bytes(
        mat_name: str,
        cdmaterials_paths,          # str | list[str] | None
        textures_vpk: Optional[str],
        misc_vpk: Optional[str],
        log_not_found: bool = True,
    ) -> Optional[bytes]:
        """
        Извлекает оригинальный VTF из игровых VPK-файлов.

        Crowbar добавляет префикс ``console\\`` ко всем $cdmaterials путям.
        В реальных VPK этого префикса нет, поэтому мы его снимаем.
        Пути вида ``console\\..\\..\\effects`` (для частиц) пропускаются.

        Args:
            mat_name:          Имя материала (без расширения).
            cdmaterials_paths: Один путь или список путей из $cdmaterials QC.
                               Crowbar-префикс ``console/`` снимается автоматически.
            textures_vpk:      Путь к tf2_textures_dir.vpk.
            misc_vpk:          Путь к tf2_misc_dir.vpk.

        Returns:
            Байты VTF или None если не найдено.
        """
        try:
            import vpk as vpklib

            mat_lower = mat_name.lower()

            # Нормализуем cdmaterials_paths в список
            if cdmaterials_paths is None:
                raw_paths: list = []
            elif isinstance(cdmaterials_paths, str):
                raw_paths = [cdmaterials_paths]
            else:
                raw_paths = list(cdmaterials_paths)

            def _normalize(raw: str) -> Optional[str]:
                """Снять console/ prefix, пропустить пути с '..'."""
                p = raw.strip("/\\").replace("\\", "/")
                # Crowbar добавляет "console/" — снимаем
                if p.lower().startswith("console/"):
                    p = p[len("console/"):]
                # Пути типа "../../effects" — не текстурные, пропускаем
                if ".." in p:
                    return None
                return p.rstrip("/")

            candidates: list = []

            # Кандидаты из QC ($cdmaterials), все строки
            seen_cdmat = set()
            for raw in raw_paths:
                cdmat = _normalize(raw)
                if cdmat and cdmat not in seen_cdmat:
                    seen_cdmat.add(cdmat)
                    candidates.append(f"materials/{cdmat}/{mat_lower}.vtf")

            # Стандартные fallback-пути для оружий и персонажей
            candidates += [
                f"materials/models/weapons/c_models/{mat_lower}/{mat_lower}.vtf",
                f"materials/models/weapons/c_items/{mat_lower}.vtf",
                f"materials/models/workshop_partner/weapons/c_models/{mat_lower}/{mat_lower}.vtf",
                f"materials/models/workshop/weapons/c_models/{mat_lower}/{mat_lower}.vtf",
                f"materials/models/player/{mat_lower}/{mat_lower}.vtf",
            ]

            for vpk_path in filter(None, [textures_vpk, misc_vpk]):
                if not os.path.exists(vpk_path):
                    continue
                try:
                    pak = vpklib.open(vpk_path)
                    for vtf_path in candidates:
                        try:
                            data = pak[vtf_path].read()
                            logger.debug(f"Оригинальный VTF из игры: {vtf_path}")
                            return data
                        except KeyError:
                            continue
                except Exception as _e:
                    logger.debug(f"VPK ошибка при поиске оригинала {mat_name}: {_e}")

            if log_not_found:
                logger.warning(
                    f"Оригинальный VTF не найден в игре для '{mat_name}' "
                    f"(cdmaterials={cdmaterials_paths})"
                )
            else:
                logger.debug(
                    f"Shared texture не в основном cdmaterials, пропускаем: '{mat_name}'"
                )
            return None

        except Exception as exc:
            logger.warning(f"_get_original_vtf_bytes: {exc}")
            return None

    @staticmethod
    def _process_image(input_path: str, output_path: str, size: Tuple[int, int]) -> None:
        return TextureService.process_image(input_path, output_path, size)
    
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
