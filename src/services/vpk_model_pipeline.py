"""
Модельный конвейер VPK-сборки (вынесено из VPKService).

Поиск/подбор .mdl, разрешение SMD замены модели, получение декомпилированного
QC, применение замены модели, сборка доп. классовых/стилевых моделей шапок,
копирование прекомпилированных моделей и запуск компиляции. Извлечено
extract-class из ``VPKService``; методы статические, внутренние вызовы
переиспользуют этот класс, вторичная текстура идёт в ``VpkTextureBuilder``,
копирование скомпилированных моделей — напрямую в ``ModelService``.
"""

import os
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from src.services.debug_service import DebugService
from src.services.decompile_cache import get_cached_decompile, restore_from_cache, save_to_cache
from src.services.model_build_service import ModelBuildService
from src.services.model_service import ModelService
from src.services.smd_service import SMDService
from src.services.tf2_paths import build_hat_mdl_candidates
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.services.vpk_texture_builder import VpkTextureBuilder
from src.data.weapons import WEAPON_MDL_PATHS
from src.data.player_characters import (
    PLAYER_BODY_MODE_KEYS,
    SPY_MASK_MODE_KEY,
    SPY_MDL_PATH,
)
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class VpkModelPipeline:
    """Модельный конвейер VPK-сборки (см. модуль)."""

    @staticmethod
    def _build_mdl_search_paths(
        mode: str,
        weapon_key: str,
        hat_mdl_path: Optional[str],
        t: dict,
        tf2_root: Optional[str] = None,
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
            # Единая логика кандидатов (%s, workshop-варианты, суффиксы класса)
            return build_hat_mdl_candidates(hat_mdl_path), None

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

        # Точный путь из items_game.txt (авторитетный) — первым кандидатом.
        # Убирает зависимость от угадывания папок/префиксов и ручных оверрайдов.
        if tf2_root:
            try:
                from src.data.weapon_model_index import resolve_weapon_mdl
                _exact = resolve_weapon_mdl(weapon_key, tf2_root)
                if _exact:
                    paths_to_try.append(_exact)
            except Exception as _e:
                logger.debug(f"weapon index: {_e}")

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
        keep_user_materials: bool = False,
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

                original_smd_path = VpkModelPipeline._find_decompiled_reference_smd(
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
                        keep_user_materials=keep_user_materials,
                    )
                    logger.info(
                        f"Модель успешно заменена: {original_smd_path} "
                        f"(keep_user_materials={keep_user_materials})"
                    )
                else:
                    ctx.warn(
                        "Замена модели не выполнена: не найден reference SMD "
                        f"для {weapon_key}. В мод попадёт оригинальная геометрия."
                    )
                    if ctx.decompile_dir.exists():
                        smd_files = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')]
                        logger.debug(f"Доступные SMD файлы в директории: {smd_files}")
            except Exception as e:
                logger.error(f"Ошибка при замене модели: {e}", exc_info=True)
                ctx.warn(
                    "Замена модели завершилась ошибкой — в мод попадёт "
                    f"оригинальная модель. ({e})"
                )
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
                logger.debug("Нет callback для замены доп. частей модели, пропускаем")

    @staticmethod
    def _build_extra_class_hat_models(
        ctx,
        hat_mdl_path: str,
        built_mdl_path: Optional[str],
        replace_model_smd_path: Optional[str],
        keep_user_materials: bool,
        tf2_misc_vpk: str,
        studiomdl_exe: str,
        crowbar_exe: str,
        tf_dir: str,
        language: str,
        emit_sub,
        target_mdl_paths: Optional[list] = None,
    ) -> None:
        """
        Собирает модель для остальных классов мультиклассовой шапки при замене модели.

        Основная сборка компилирует модель только одного класса. У мультиклассовых
        шапок каждый класс — отдельная MDL со СВОИМ скелетом (bonemerge), поэтому
        просто скопировать модель одного класса на путь другого нельзя (съедет). Для
        каждого ОСТАЛЬНОГО класса декомпилируем его MDL, вставляем геометрию
        пользователя (скелет берём класса), компилируем и кладём в VPK по его
        $modelname.

        Источник списка путей:
          • target_mdl_paths — явные MDL-пути остальных классов (model_player_per_class
            с произвольными путями; основной режим — выбор классов в UI);
          • иначе — legacy %s-шаблон в hat_mdl_path, раскрытый по всем классам.

        Ошибки одного класса не валят сборку — этот класс просто останется с
        оригинальной игровой моделью.
        """
        if not (replace_model_smd_path and os.path.exists(replace_model_smd_path)):
            return
        use_explicit = bool(target_mdl_paths)
        if not use_explicit and (not hat_mdl_path or "%s" not in hat_mdl_path):
            return

        import re as _re
        from src.services.tf2_paths import build_hat_mdl_candidates
        from src.services.decompile_cache import (
            get_cached_decompile, restore_from_cache,
        )

        _cls_pat = _re.compile(
            r'_(heavy|scout|soldier|pyro|demoman|engineer|medic|sniper|spy)\.mdl$',
            _re.IGNORECASE,
        )

        def _cls_of(p: str) -> Optional[str]:
            m = _cls_pat.search((p or '').replace('\\', '/').lower())
            return m.group(1) if m else None

        to_build: list = []
        seen = set()
        if use_explicit:
            # Явные пути остальных классов (основной класс уже собран primary-сборкой).
            # Пути из model_player_per_class авторитетны — берём как есть, без
            # суффиксной экспансии (она могла бы подставить модель другого класса).
            for cand in target_mdl_paths:
                norm = (cand or '').replace('\\', '/').lower()
                if not norm or norm in seen:
                    continue
                try:
                    if TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, norm):
                        to_build.append(norm)
                        seen.add(norm)
                    else:
                        logger.warning(f"[HAT MULTI] MDL класса не найден в игре, пропуск: {norm}")
                except Exception:
                    continue
        else:
            # Legacy %s: один существующий MDL на класс (исключая уже собранный).
            built_cls = _cls_of(built_mdl_path or '')
            seen_cls = {built_cls} if built_cls else set()
            for cand in build_hat_mdl_candidates(hat_mdl_path):
                cls = _cls_of(cand)
                if not cls or cls in seen_cls:
                    continue
                try:
                    if TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, cand):
                        to_build.append(cand)
                        seen_cls.add(cls)
                except Exception:
                    continue

        if not to_build:
            return
        logger.info(
            f"[HAT MULTI] доп. классы для замены модели: "
            f"{[(_cls_of(p) or Path(p).stem) for p in to_build]}"
        )

        for mdl_rel in to_build:
            cls = _cls_of(mdl_rel)
            wk = Path(mdl_rel).stem
            try:
                _lbl = cls or wk
                emit_sub(-1, f"Class model: {_lbl}..." if language == "en"
                         else f"Модель класса: {_lbl}...")
                cls_root = ctx.temp_dir / f"hatcls_{wk}"
                extract_d = cls_root / "extract"
                decomp_d = cls_root / "decompile"
                comp_d = cls_root / "compile"
                for _d in (extract_d, decomp_d, comp_d):
                    ensure_directory_exists(_d)

                # QC: из кэша декомпила или свежая декомпиляция.
                cached = get_cached_decompile(wk, tf2_misc_vpk, mdl_rel)
                if cached:
                    qc_p = restore_from_cache(cached, str(decomp_d))
                else:
                    extracted = TF2VPKExtractService.extract_file_set(
                        tf2_misc_vpk, mdl_rel, str(extract_d)
                    )
                    mdl_file = next((f for f in extracted if f.endswith('.mdl')), None)
                    if not mdl_file:
                        logger.warning(f"[HAT MULTI] {cls}: MDL не извлёкся")
                        continue
                    qc_p = ModelBuildService.decompile(mdl_file, str(decomp_d), crowbar_exe)
                    ModelBuildService.remove_lod_files(str(decomp_d))
                    save_to_cache(wk, tf2_misc_vpk, mdl_rel, str(decomp_d))

                if not qc_p or not os.path.exists(qc_p):
                    logger.warning(f"[HAT MULTI] {cls}: QC не найден")
                    continue

                # Вставляем геометрию пользователя в reference SMD ЭТОГО класса
                # (скелет/кости — класса, иначе bonemerge съедет).
                ref_smd = VpkModelPipeline._find_decompiled_reference_smd(qc_p, wk, decomp_d)
                if not ref_smd:
                    logger.warning(f"[HAT MULTI] {cls}: reference SMD не найден — пропуск")
                    continue
                SMDService.replace_model_sections(
                    replace_model_smd_path, ref_smd, ref_smd,
                    keep_user_materials=keep_user_materials,
                )

                # Патчим cdmaterials под console\ (как основная модель) — чтобы
                # модель класса нашла нашу текстуру по тому же пути.
                ModelBuildService.patch_qc_file(qc_p)

                ModelBuildService.compile(qc_p, str(comp_d), studiomdl_exe, tf_dir)

                # Копируем скомпилированные файлы в VPK по $modelname этого класса.
                _sub = type('SubCtx', (), {'compile_dir': comp_d, 'vpkroot_dir': ctx.vpkroot_dir})()
                ModelService.copy_compiled_models_to_vpkroot(_sub, qc_p)
                logger.info(f"[HAT MULTI] модель класса {cls} собрана и добавлена в мод")
            except Exception as exc:
                logger.warning(
                    f"[HAT MULTI] класс {cls}: ошибка сборки модели — класс останется "
                    f"с оригинальной моделью: {exc}", exc_info=True
                )

    @staticmethod
    def _build_extra_style_models(
        ctx,
        hat_style_builds: list,
        tf2_misc_vpk: str,
        studiomdl_exe: str,
        crowbar_exe: str,
        tf_dir: str,
        language: str,
        emit_sub,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict,
        base_vmt_path: Path,
    ) -> None:
        """
        Собирает доп. ИЗМЕНЁННЫЕ стили-модели шапки — каждый со СВОЕЙ моделью и
        СВОЕЙ текстурой в тот же VPK (накопленные пер-стилевые правки из UI).

        Для каждого стиля и каждой его MDL:
          1. декомпилируем MDL (с кэшем);
          2. при наличии — вставляем геометрию пользователя (replace_smd) в
             reference SMD этого стиля (скелет берём стиля);
          3. патчим $cdmaterials под console\\ (чтобы модель нашла нашу текстуру);
          4. компилируем и кладём модель в vpkroot по её $modelname;
          5. пишем текстуру стиля {texture_filename}.vtf + .vmt по console-пути.

        Каждый стиль обычно несёт собственное имя текстуры из $texturegroup, так
        что текстуры стилей не конфликтуют. Ошибки одного стиля не валят сборку.
        """
        if not hat_style_builds:
            return
        from src.services.decompile_cache import (
            get_cached_decompile, restore_from_cache,
        )

        for entry in hat_style_builds:
            replace_smd = entry.get('replace_smd')
            keep_mat = bool(entry.get('keep_materials'))
            img = entry.get('vtf_path') or entry.get('image_path')
            for mdl_rel in (entry.get('mdl_paths') or []):
                mdl_norm = (mdl_rel or '').replace('\\', '/').lower()
                if not mdl_norm:
                    continue
                wk = Path(mdl_norm).stem
                try:
                    if not TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, mdl_norm):
                        logger.warning(f"[HAT STYLE] MDL стиля не найден в игре, пропуск: {mdl_norm}")
                        continue
                    emit_sub(-1, f"Style model: {wk}..." if language == "en"
                             else f"Модель стиля: {wk}...")
                    st_root = ctx.temp_dir / f"hatstyle_{wk}"
                    extract_d = st_root / "extract"
                    decomp_d = st_root / "decompile"
                    comp_d = st_root / "compile"
                    for _d in (extract_d, decomp_d, comp_d):
                        ensure_directory_exists(_d)

                    # QC: из кэша декомпила или свежая декомпиляция.
                    cached = get_cached_decompile(wk, tf2_misc_vpk, mdl_norm)
                    if cached:
                        qc_p = restore_from_cache(cached, str(decomp_d))
                    else:
                        extracted = TF2VPKExtractService.extract_file_set(
                            tf2_misc_vpk, mdl_norm, str(extract_d)
                        )
                        mdl_file = next((f for f in extracted if f.endswith('.mdl')), None)
                        if not mdl_file:
                            logger.warning(f"[HAT STYLE] {wk}: MDL не извлёкся")
                            continue
                        qc_p = ModelBuildService.decompile(mdl_file, str(decomp_d), crowbar_exe)
                        ModelBuildService.remove_lod_files(str(decomp_d))
                        save_to_cache(wk, tf2_misc_vpk, mdl_norm, str(decomp_d))

                    if not qc_p or not os.path.exists(qc_p):
                        logger.warning(f"[HAT STYLE] {wk}: QC не найден")
                        continue

                    # Имя текстуры и cdmaterials стиля — ДО патча console\.
                    tex_name = ModelBuildService.extract_texturegroup_filename(qc_p)
                    cdmat0 = ModelBuildService.extract_cdmaterials_path_from_qc(qc_p)
                    if not tex_name or not cdmat0:
                        logger.warning(f"[HAT STYLE] {wk}: нет texturegroup/cdmaterials — пропуск")
                        continue

                    # Замена геометрии стиля (если пользователь загрузил свою модель).
                    if replace_smd and os.path.exists(replace_smd):
                        ref_smd = VpkModelPipeline._find_decompiled_reference_smd(qc_p, wk, decomp_d)
                        if ref_smd:
                            SMDService.replace_model_sections(
                                replace_smd, ref_smd, ref_smd, keep_user_materials=keep_mat,
                            )
                        else:
                            logger.warning(f"[HAT STYLE] {wk}: reference SMD не найден — геометрия оригинала")

                    # Патчим cdmaterials под console\ и компилируем.
                    ModelBuildService.patch_qc_file(qc_p)
                    ModelBuildService.compile(qc_p, str(comp_d), studiomdl_exe, tf_dir)
                    _sub = type('SubCtx', (), {'compile_dir': comp_d, 'vpkroot_dir': ctx.vpkroot_dir})()
                    ModelService.copy_compiled_models_to_vpkroot(_sub, qc_p)

                    # Текстура стиля → materials/console/<cdmat0>/<tex_name>.vtf+.vmt
                    if img and os.path.isfile(img):
                        _lo = cdmat0.lower()
                        if _lo.startswith('console\\') or _lo.startswith('console/'):
                            patched_cd = cdmat0.replace('/', '\\')
                        else:
                            patched_cd = 'console\\' + cdmat0.lstrip('\\/')
                        materials_rel = "materials/" + patched_cd.replace('\\', '/').strip().rstrip('/')
                        vtf_dir = ctx.vpkroot_dir
                        for part in materials_rel.split('/'):
                            vtf_dir = vtf_dir / part
                        VpkTextureBuilder._render_extra_texture(
                            tex_name, img, vtf_dir, base_vmt_path, patched_cd,
                            size, format_type, flags, vtf_options,
                        )
                        logger.info(f"[HAT STYLE] стиль {wk}: модель+текстура '{tex_name}' добавлены в мод")
                    else:
                        logger.info(f"[HAT STYLE] стиль {wk}: модель добавлена (без своей текстуры)")
                except Exception as exc:
                    logger.warning(
                        f"[HAT STYLE] {wk}: ошибка сборки стиля — пропуск: {exc}",
                        exc_info=True,
                    )

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
                    original_smd_path = VpkModelPipeline._find_decompiled_reference_smd(
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
                VpkModelPipeline._copy_precompiled_model(
                    model_ready_path, qc_path, weapon_key, ctx, language, emit_sub
                )
                thread = threading.Thread(target=lambda: None, daemon=True)
        else:
            # Обычная сборка: компилируем декомпилированный QC
            thread = threading.Thread(target=_do_compile, daemon=True)

        thread.start()
        return thread, compile_exc
