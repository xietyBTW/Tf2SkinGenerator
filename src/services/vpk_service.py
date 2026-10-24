"""
Работа с VPK файлами: распаковка, сборка, конвертация текстур
"""

import os
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple, Optional, Callable, NamedTuple
from .build_context import BuildContext, MaterialSlots, TextureBuildContext
from .build_request import BuildRequest
from .build_service import BuildService
from .packaging_service import PackagingService
from .model_service import ModelService
from .model_build_service import ModelBuildService
from .vpk_texture_builder import VpkTextureBuilder
from .texture_build.vtf_jobs import VtfJobs
from .vpk_model_pipeline import VpkModelPipeline
from .material_plan import MaterialPlan, apply_force_team, plan_materials
from .tf2_paths import TF2Paths
from .debug_service import DebugService
from .smd_service import SMDService
from src.data.weapons import SPECIAL_MODES
from src.data.player_hands import HAND_MODE_KEYS
from src.data.player_characters import (
    PLAYER_BODY_MODE_KEYS,
    SPY_MASK_MODE_KEY,
    SPY_MDL_PATH,
)
from src.shared.logging_config import get_logger
from src.shared.constants import DirectoryPaths, EXTRA_TEX_USE_GAME_ORIGINAL
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.validators import validate_build_params
from src.shared.paths import data_dir

logger = get_logger(__name__)


class _Tools(NamedTuple):
    """Инструменты и пути сборки (стадия 1)"""
    studiomdl_exe: str
    tf2_misc_vpk: str
    tf_dir: str
    paths_to_try: list


@dataclass
class _ModelSource:
    """Разобранная модель после замены геометрии: исходные (игровые) имена
    материалов из QC до его патча (стадия 3)"""
    found_mdl_path: str
    replace_model_smd_path: Optional[str]
    original_cdmaterials_path: str
    original_cdmaterials_paths: list
    texture_filename: str


@dataclass
class _MaterialOutput:
    """Куда пишутся материалы главной текстуры: путь обхода sv_pure (стадия 5)"""
    patched_cdmaterials_path: str
    vtf_output_path: Path
    vmt_path: Path
    vtf_filename: str
    vtf_temp_png: Path


class VPKService:
    """Главный конвейер сборки VPK файлов. Детали ошибок - в логах"""

    @staticmethod
    def _is_attachment_only(weapon_key: str, tf2_misc_vpk: str) -> bool:
        """Навесное украшение (гирлянда `*_xmas`), а не само оружие: items_game
        вешает его на базовую пушку через `attached_models`"""
        try:
            from src.data.weapon_model_index import (
                attachment_only_models, tf2_root_from_misc_vpk,
            )
            return weapon_key.lower() in attachment_only_models(
                tf2_root_from_misc_vpk(tf2_misc_vpk))
        except Exception as exc:                  # noqa: BLE001 - только уточнение
            logger.debug(f"attachment check: {exc}")
            return False
    
    @staticmethod
    def build_with_progress(
        request,
        *,
        model_file_callback: Optional[Callable[[], Optional[str]]] = None,
        extra_texture_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        extra_model_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        texture_mismatch_callback: Optional[Callable[[str], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, str, bool]:
        # Здесь нужны лишь те поля, что используются ДО build_vpk (ветка custom,
        # выбор спец-режима, гейтинг колбэка). Остальное распакует сам build_vpk
        r = request
        mode = r.mode
        image_path = r.image_path
        size = r.size
        format_type = r.format_type
        flags = r.flags or []
        vtf_options = r.vtf_options or {}
        export_folder = r.export_folder
        filename = r.filename
        language = r.language
        custom_vtf_path = r.custom_vtf_path
        custom_vpk_source_path = r.custom_vpk_source_path
        hat_mdl_path = r.hat_mdl_path
        replace_model_enabled = r.replace_model_enabled
        logger.info(f"[BUILD] режим={r.mode!r}, isolate_shoulders={r.isolate_shoulders}, force_team={r.force_team}")

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

            # Кастомный мод (пользователь загрузил готовый VPK)
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
                    decor_builds=r.decor_builds,
                    tf2_root_dir=r.tf2_root_dir,
                    bypass_method=r.bypass_method,
                    material_maps=r.material_maps,
                    material_settings=r.material_settings,
                )
                emit_progress(100 if success else 0,
                              t.get('build_completed', 'Build completed') if success
                              else t.get('build_error_status', 'Build error'))
                return success, message, False

            # Скайбокс: свой пайплайн (панорама/грани -> materials/skybox) ─
            # Ранняя ветка как у custom: _validate_build_params требует
            # image_path/TF2 и не знает про 6 граней - валидация своя
            from src.data.skyboxes import SKYBOX_MODE
            if mode == SKYBOX_MODE:
                from src.services.skybox_service import SkyboxService
                emit_progress(10, t.get('build_skybox_faces', 'Building sky faces...'))
                success, message = SkyboxService.build_skybox_vpk(
                    request,
                    sub_progress_callback=emit_sub,
                    cancel_callback=cancel_callback,
                )
                if is_cancelled():
                    return False, t.get('build_cancelled', 'Build cancelled by user'), True
                emit_progress(100 if success else 0,
                              t.get('build_completed', 'Build completed') if success
                              else t.get('build_error_status', 'Build error'))
                return success, message, False

            is_special_mode = mode in SPECIAL_MODES

            _sub_label_init = "Preparing..." if language == "en" else "Подготовка..."
            emit_sub(-1, _sub_label_init)

            # Прогресс эмитится самим build_vpk на реальных границах стадий
            # (декомпиляция / текстуры / компиляция / упаковка) - без
            # потока-имитатора с фиксированными процентами
            if is_special_mode:
                emit_progress(20, t.get('build_processing', 'Processing texture...'))
            else:
                emit_progress(10, t.get('build_extracting', 'Extracting model...'))

            # Параметры сборки целиком в request; build_vpk сам их распакует.
            # Колбэки - runtime UI-потока, передаём отдельно. model_file_callback
            # имеет смысл только при включённой замене модели
            success, message = VPKService.build_vpk(
                request,
                model_file_callback=model_file_callback if replace_model_enabled else None,
                extra_texture_callback=extra_texture_callback,
                extra_model_callback=extra_model_callback,
                texture_mismatch_callback=texture_mismatch_callback,
                sub_progress_callback=emit_sub,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

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
    def _ready_model_texture_mismatch(
        model_ready_path: Optional[str],
        qc_path: str,
        weapon_key: str,
        decompile_dir: str,
        language: str,
    ) -> Optional[str]:
        """
        Режим «готовая модель»: возвращает текст предупреждения, если материалы
        пользовательского SMD не совпадают с оригиналом, иначе None.
        Чистая проверка (только сравнение + лог) - решение продолжать/отменить
        принимает вызывающий код через texture_mismatch_callback
        """
        if not (model_ready_path and os.path.exists(model_ready_path)
                and model_ready_path.lower().endswith('.smd')):
            return None
        try:
            user_materials = SMDService.extract_unique_materials(model_ready_path)
            if not user_materials:
                return None
            original_smd = VpkModelPipeline._find_decompiled_reference_smd(
                qc_path, weapon_key, decompile_dir)
            if not original_smd:
                return None
            original_materials = SMDService.extract_unique_materials(original_smd)
            if not original_materials:
                return None
            if user_materials == original_materials:
                logger.info(f"[MODEL READY] Текстуры SMD совпадают с оригиналом: {user_materials}")
                return None

            missing_in_user = original_materials - user_materials
            extra_in_user = user_materials - original_materials
            lines = []
            if language == "ru":
                lines.append("Текстуры в вашем SMD файле не совпадают с оригинальной моделью.\n")
                if missing_in_user:
                    lines.append("Отсутствуют (есть в оригинале, нет у вас):")
                    lines += [f"  • {m}" for m in sorted(missing_in_user)]
                if extra_in_user:
                    lines.append("Лишние (есть у вас, нет в оригинале):")
                    lines += [f"  • {m}" for m in sorted(extra_in_user)]
                lines.append("\nПродолжить сборку с этими текстурами?")
            else:
                lines.append("Textures in your SMD file do not match the original model.\n")
                if missing_in_user:
                    lines.append("Missing (in original, not in yours):")
                    lines += [f"  • {m}" for m in sorted(missing_in_user)]
                if extra_in_user:
                    lines.append("Extra (in yours, not in original):")
                    lines += [f"  • {m}" for m in sorted(extra_in_user)]
                lines.append("\nContinue building with these textures?")

            warning_msg = "\n".join(lines)
            logger.warning(f"[MODEL READY] Несовпадение текстур SMD:\n{warning_msg}")
            return warning_msg
        except Exception as exc:
            logger.warning(f"[MODEL READY] Ошибка проверки текстур SMD: {exc}", exc_info=True)
            return None

    @staticmethod
    def _write_hand_mirror_vmts(ctx, mode: str, weapon_key: str,
                                original_cdmaterials_path: Optional[str],
                                vtf_output_path) -> None:
        """
        Для рук и MIRROR_VMT_WEAPON_KEYS дублирует VMT по ОРИГИНАЛЬНОМУ пути из
        $cdmaterials. Причина: эти модели ссылаются на оригинальный путь
        (materials/models/player/spy/...), а не на пропатченный console\\-путь,
        иначе мод игнорируется. VTF не дублируются - зеркальный VMT указывает на
        те же файлы (по console\\-пути внутри мод-VPK)
        """
        from src.data.player_hands import HAND_MODE_KEYS as _HAND_MODE_KEYS
        from src.data.weapon_quirks import MIRROR_VMT_WEAPON_KEYS as _MIRROR_KEYS
        if not ((mode in _HAND_MODE_KEYS or weapon_key in _MIRROR_KEYS)
                and original_cdmaterials_path):
            return
        orig_vtf_dir = VPKService._mirror_dir(ctx, original_cdmaterials_path)
        if orig_vtf_dir == vtf_output_path:
            logger.debug("Оригинальный и пропатченный пути совпадают, зеркало не нужно")
            return
        ensure_directory_exists(orig_vtf_dir)
        for _vmt_src in vtf_output_path.glob("*.vmt"):
            _vmt_mirror = orig_vtf_dir / _vmt_src.name
            if not _vmt_mirror.exists():
                copy_file_safe(_vmt_src, _vmt_mirror)
                logger.info(f"Зеркальный VMT по оригинальному пути: {_vmt_mirror.name}")

    @staticmethod
    def _mirror_dir(ctx, original_cdmaterials_path: str) -> Path:
        """Папка зеркальных VMT в моде: оригинальный путь $cdmaterials"""
        rel = original_cdmaterials_path.replace('\\', '/').strip().strip('/')
        return ctx.vpkroot_dir.joinpath("materials", *rel.split('/'))

    @staticmethod
    def _purge_dir_contents(directory: Path, label: str) -> None:
        """
        Удаляет всё содержимое директории (файлы и поддиректории), не трогая саму
        папку. Для очистки временных папок после сборки. Ошибки не фатальны - лог
        """
        if not directory.exists():
            return
        try:
            for entry in directory.iterdir():
                try:
                    if entry.is_file() or entry.is_symlink():
                        entry.unlink()
                    elif entry.is_dir():
                        shutil.rmtree(entry)
                except Exception as e:
                    logger.warning(f"Не удалось удалить {entry}: {e}", exc_info=True)
            logger.debug(f"Очищена папка {label}")
        except Exception as e:
            logger.warning(f"Не удалось очистить папку {label}: {e}", exc_info=True)

    @staticmethod
    def _finalize_build_success(ctx, vpk_path: str, vmt_to_delete, language: str,
                                debug_mode: bool, t: dict) -> str:
        """
        Постобработка успешной сборки: удаляет отредактированный пользователем VMT,
        чистит временные папки редактора, удаляет temp-директорию сборки и собирает
        итоговое сообщение (с накопленными предупреждениями ctx.warnings)
        """
        # Правленый VMT после сборки НЕ удаляется: правка - часть работы, как
        # своя текстура: иначе вторая сборка того же предмета молча вышла бы с
        # игровым материалом. Откат - кнопка «Как в игре» в редакторе
        if vmt_to_delete:
            logger.info(f"Правленый VMT использован и оставлен: {vmt_to_delete}")

        # Чистим временные папки редактора VMT (мусор от достанных из игры VMT)
        VPKService._purge_dir_contents(DirectoryPaths.TEMP_VMT_EXTRACT_DIR, "temp_vmt_extract")
        VPKService._purge_dir_contents(data_dir() / "tools/backupVMT", "backupVMT")

        ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=debug_mode)

        success_message = t.get('vpk_success', 'VPK successfully created: {path}').format(path=vpk_path)
        # Показываем накопленные предупреждения (напр. не найденную игровую
        # текстуру) - иначе пользователь узнает о фиолете только в игре
        if ctx.warnings:
            _hdr = ("\n\nВнимание:" if language == "ru" else "\n\nWarnings:")
            success_message += _hdr + "".join(f"\n- {w}" for w in ctx.warnings)
        return success_message

    @staticmethod
    def _resolve_weapon_key(mode: str, hat_mdl_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Определяет weapon_key (ключ модели/файлов) по режиму сборки

        Для оружия - суффикс mode (scout_c_scattergun -> c_scattergun), для рук -
        ключ arm-модели, для тела/масок шпиона - стем MDL; для шапки - стем
        hat_mdl_path

        Returns:
            (weapon_key, None) при успехе либо (None, error_message), если для
            режима рук не задана arm-модель
        """
        if mode == "hat" and hat_mdl_path:
            weapon_key = Path(hat_mdl_path).stem
            logger.info(f"[HAT] hat_mdl_path={hat_mdl_path!r}  →  weapon_key={weapon_key!r}")
            return weapon_key, None
        if mode in HAND_MODE_KEYS:
            from src.data.player_hands import HAND_MODES as _HAND_MODES
            arm_key = _HAND_MODES.get(mode, {}).get('arm_model', '')
            if not arm_key:
                return None, f"No arm_model defined for hand mode: {mode}"
            return arm_key, None
        if mode in PLAYER_BODY_MODE_KEYS:
            from src.data.player_characters import PLAYER_CHARACTERS as _PC
            mdl_path = _PC.get(mode, {}).get('mdl_path', '')
            return (Path(mdl_path).stem if mdl_path else mode), None
        if mode == SPY_MASK_MODE_KEY:
            # Маски маскировки: тот же MDL, что и для скина шпиона
            return Path(SPY_MDL_PATH).stem, None
        return (mode.split('_', 1)[1] if '_' in mode else mode), None

    @staticmethod
    def _stage_locate_tools(
        ctx, mode: str, weapon_key: str, hat_mdl_path, tf2_root_dir, t: dict,
        keep_temp_on_error: bool, debug_mode: bool,
    ):
        """
        Стадия 1 модельного конвейера: инструменты и пути

        Проверяет TF2/Crowbar, резолвит studiomdl/misc-VPK/tf-папку и строит
        список кандидатов MDL

        Returns:
            (error_result, None) - ошибка, ctx очищен; error_result - готовый
            ответ build_vpk (False, message);
            (None, (studiomdl_exe, tf2_misc_vpk, tf_dir, paths_to_try)) - успех
        """
        def _fail(message: str):
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return (False, message), None

        # Без пути к TF2 продолжать нельзя - нужны VPK файлы игры
        if not tf2_root_dir:
            logger.error("Путь к TF2 не указан")
            return _fail(t['error_tf2_not_specified'])

        # Crowbar нужен для декомпиляции, без него никак
        crowbar_exists, crowbar_error = TF2Paths.check_crowbar()
        if not crowbar_exists:
            return _fail(crowbar_error)

        try:
            studiomdl_exe, tf2_misc_vpk, tf_dir = TF2Paths.resolve(tf2_root_dir)
        except FileNotFoundError as e:
            return _fail(str(e))

        paths_to_try, _mdl_path_error = VpkModelPipeline._build_mdl_search_paths(
            mode, weapon_key, hat_mdl_path, t, tf2_root_dir
        )
        if _mdl_path_error:
            return _fail(_mdl_path_error)

        return None, _Tools(studiomdl_exe, tf2_misc_vpk, tf_dir, paths_to_try)

    @staticmethod
    def _stage_find_and_decompile(
        ctx, mode: str, weapon_key: str, hat_mdl_path, paths_to_try,
        tf2_misc_vpk: str, draw_uv_layout: bool, size,
        export_folder: str, keep_temp_on_error: bool, debug_mode: bool,
        language: str, t: dict, emit_progress, emit_sub, is_cancelled,
        cancelled_result,
    ):
        """
        Стадия 2 модельного конвейера: MDL в игровом VPK + декомпиляция

        Находит MDL по кандидатам, для %s-шапок обновляет weapon_key на
        реальный стем, получает декомпилированный QC (через кэш декомпиляции),
        рисует UV-шаблон (по запросу) и чистит LOD в папке сборки

        Returns:
            (error_result, '', weapon_key, '') - ошибка/отмена, ctx очищен
            (для отмены - cancelled_result);
            (None, found_mdl_path, weapon_key, qc_path) - успех
        """
        def _fail(message_result):
            return message_result, '', weapon_key, ''

        found_mdl_path, _mdl_find_error = VpkModelPipeline._find_existing_mdl(
            paths_to_try, tf2_misc_vpk, weapon_key, t
        )
        if _mdl_find_error:
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return _fail((False, _mdl_find_error))

        # Для шапок с %s-плейсхолдером: обновляем weapon_key на реальный стем
        # (all_domination_%s -> all_domination_heavy), иначе кэш и имена файлов сломаются
        if mode == "hat" and hat_mdl_path and "%s" in hat_mdl_path:
            weapon_key = Path(found_mdl_path).stem
            logger.info(f"Hat weapon_key обновлён: {weapon_key}")

        # Праздничные пушки - базовая модель ПЛЮС отдельная модель-гирлянда;
        # в списке гирлянда выглядит как оружие, но перекрашивается только она.
        # Молчать нельзя: пользователь красит «Праздничный пулемёт» и не видит
        # изменений на стволе (items_game: "attached_models")
        if mode != "hat" and VPKService._is_attachment_only(weapon_key, tf2_misc_vpk):
            ctx.warn(
                f"'{weapon_key}' - это навесное украшение (гирлянда), а не сам "
                f"ствол: игра рисует его поверх базового оружия. Красится только "
                f"украшение; чтобы изменить сам ствол, соберите базовое оружие."
            )

        if is_cancelled():
            return _fail(cancelled_result(ctx))
        emit_progress(25, t.get('build_decompiling', 'Decompiling model...'))

        qc_path, _decomp_error = VpkModelPipeline._obtain_decompiled_qc(
            ctx, found_mdl_path, weapon_key, tf2_misc_vpk,
            debug_mode, language, t, emit_sub,
        )
        if _decomp_error:
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return _fail((False, _decomp_error))

        if draw_uv_layout:
            ModelService.generate_uv_layout(ctx, weapon_key, size, export_folder, language)

        # Только в папке сборки: в кэше лежит полный вывод Crowbar (экспорт отдаёт LOD)
        ModelBuildService.remove_lod_files(ctx.decompile_dir)

        return None, found_mdl_path, weapon_key, qc_path

    @staticmethod
    def _build_model_mode_vpk(
        ctx: BuildContext,
        r: BuildRequest,
        weapon_key: str,
        t: dict,
        *,
        model_file_callback=None,
        extra_texture_callback=None,
        extra_model_callback=None,
        texture_mismatch_callback=None,
        emit_progress,
        emit_sub,
        is_cancelled,
        cancelled_result,
    ) -> Tuple[bool, str]:
        """
        Конвейер МОДЕЛЬНОГО мода (оружие/шапка/руки/тело): поиск MDL в игровом
        VPK -> декомпиляция (cache-aware) -> замена модели -> план материалов ->
        рендер всех текстур (параллельно с компиляцией) -> сборка доп. моделей
        (классы/стили шапок). Спец-режимы (critHIT/спрей/маски) сюда не заходят

        Returns:
            (False, error_message)  - ошибка/отмена, ctx уже очищен;
            (True, vmt_to_delete)   - успех; vmt_to_delete - имя
                                      отредактированного VMT ('' если нет),
                                      упаковку VPK выполняет вызывающий
        """
        def _fail(message: str, on_error: bool = True) -> Tuple[bool, str]:
            ctx.cleanup(on_error=on_error, keep_on_error=r.keep_temp_on_error,
                        debug_mode=r.debug_mode)
            return False, message

        # Папка обхода sv_pure для $cdmaterials (console\ или vgui\replay\thumbnails\)
        from src.shared.constants import bypass_prefix as _resolve_bypass_prefix
        bypass_prefix = _resolve_bypass_prefix(r.bypass_method)

        # Стадия 1: инструменты и пути (TF2/Crowbar/studiomdl/кандидаты MDL)
        err, tools = VPKService._stage_locate_tools(
            ctx, r.mode, weapon_key, r.hat_mdl_path, r.tf2_root_dir, t,
            r.keep_temp_on_error, r.debug_mode,
        )
        if err is not None:
            return err

        try:
            # Стадия 2: поиск MDL в игровом VPK + декомпиляция (cache-aware)
            err, found_mdl_path, weapon_key, qc_path = VPKService._stage_find_and_decompile(
                ctx, r.mode, weapon_key, r.hat_mdl_path, tools.paths_to_try,
                tools.tf2_misc_vpk, r.draw_uv_layout, r.size,
                r.export_folder, r.keep_temp_on_error, r.debug_mode, r.language, t,
                emit_progress, emit_sub, is_cancelled, cancelled_result,
            )
            if err is not None:
                return err

            if is_cancelled():
                return cancelled_result(ctx)
            emit_progress(40, t.get('build_processing', 'Processing texture...'))

            # Стадия 3: замена модели + исходные имена материалов
            error, src = VPKService._stage_prepare_model(
                ctx, r, t, weapon_key, found_mdl_path, qc_path, tools.tf2_misc_vpk,
                model_file_callback, extra_model_callback, emit_sub,
            )
            if error:
                return _fail(error)

            # Стадия 4: план материалов (QC патчится здесь)
            # «Сделать командным»: синтез BLU-строки для оружия БЕЗ нативной
            # команды. Делаем ДО извлечения tg_structure - тогда весь командный
            # путь (blu_row, генерация BLU, рекомпиляция) сработает как у
            # нативно-командного оружия
            apply_force_team(r.force_team, r.mode, qc_path, weapon_key, ctx)
            plan = plan_materials(
                qc_path, r.mode, weapon_key, ctx, src.texture_filename, r.image_path,
                r.blu_image_path, r.panel_extra_textures or {}, r.panel_blu_textures,
                r.isolate_shoulders, r.blu_mode, r.skin_build_data,
                r.replace_keep_materials, r.custom_qc_text, src.original_cdmaterials_path,
                bypass_prefix=bypass_prefix, misc_materials=r.misc_materials or [],
            )

            # Стадия 5: куда писать материалы (путь обхода sv_pure)
            error, out = VPKService._stage_material_output(
                ctx, qc_path, plan.texture_filename, r.mode, t)
            if error:
                return _fail(error)

            declined = VPKService._ready_model_declined(
                r, qc_path, weapon_key, ctx, texture_mismatch_callback)
            if declined:
                return _fail(declined, on_error=False)

            part_variants, part_specs = VPKService._stage_part_materials(
                ctx, r, qc_path, weapon_key, src.replace_model_smd_path)

            if is_cancelled():
                return cancelled_result(ctx)
            emit_progress(60, t.get('build_compiling', 'Compiling model...'))
            # Игровой tf2_textures_dir.vpk - резолвим один раз (RED-оригинал
            # и извлечение оригинального VMT, гирлянды)
            tf2_textures_vpk = TF2Paths.resolve_textures_vpk(r.tf2_root_dir)
            # «Сделать праздничным»: гирлянда - в меш оружия до компиляции
            from src.services import decor_bake
            baked = decor_bake.bake_entry(r.decor_builds)
            if baked and r.model_ready_path:
                # Готовую модель не перекомпилировать - вшить некуда
                baked = None
                if hasattr(ctx, 'warn'):
                    ctx.warn('Гирлянда не вшита: модель оружия готовая (MDL)')
            if baked:
                decor_bake.bake(
                    ctx, baked, qc_path, weapon_key, misc_vpk=tools.tf2_misc_vpk,
                    textures_vpk=tf2_textures_vpk, studiomdl_exe=tools.studiomdl_exe,
                    tf_dir=tools.tf_dir, size=r.size, format_type=r.format_type,
                    flags=r.flags or [], vtf_options=r.vtf_options or {},
                    bypass_prefix=bypass_prefix)

            # Стадия 6: компиляция модели в фоне, текстуры параллельно
            compile_thread, compile_exc = VpkModelPipeline._start_model_compile(
                r.model_ready_path, qc_path, weapon_key, ctx,
                tools.studiomdl_exe, tools.tf_dir, r.debug_mode, r.language, emit_sub,
            )
            image_path, vmt_to_delete = VPKService._stage_textures(
                ctx, r, src, plan, out, weapon_key, tools.tf2_misc_vpk,
                tf2_textures_vpk, part_variants, part_specs, extra_texture_callback,
            )
            compile_thread.join()
            if compile_exc[0] is not None:
                raise compile_exc[0]

            # Стадия 7: модели в мод (основная, классы и стили шапки, гирлянды)
            VPKService._stage_collect_models(
                ctx, r, src, plan, out, tools, weapon_key, qc_path,
                tf2_textures_vpk, part_variants, part_specs, image_path,
                bypass_prefix, emit_sub,
            )
            VPKService._drop_stray_blue(
                ctx, weapon_key, plan.blu_is_team, plan.texture_filename,
                out.vtf_output_path, src.original_cdmaterials_path)

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'stderr') and e.stderr:
                error_msg += f"\nSTDERR: {e.stderr}"
            if hasattr(e, 'stdout') and e.stdout:
                error_msg += f"\nSTDOUT: {e.stdout}"

            if r.keep_temp_on_error:
                error_msg += f"\n\nВременные файлы сохранены в: {ctx.temp_dir}"

            return _fail(t['error_model_work'].format(error=error_msg))

        return True, vmt_to_delete or ''

    @staticmethod
    def _stage_prepare_model(
        ctx, r: BuildRequest, t: dict, weapon_key: str, found_mdl_path: str,
        qc_path: str, tf2_misc_vpk: str, model_file_callback, extra_model_callback,
        emit_sub,
    ) -> Tuple[Optional[str], Optional[_ModelSource]]:
        """
        Стадия 3: замена модели (SMD пользователя) и исходные имена из QC -
        $cdmaterials и главная текстура ДО патча QC (дальше он их изменит)

        Returns:
            (error_message, None) - ошибка, ctx НЕ очищен;
            (None, _ModelSource) - успех
        """
        # Для рук замена SMD-модели не поддерживается
        replace_model_enabled = False if r.mode in HAND_MODE_KEYS else r.replace_model_enabled

        # Пропускаем если model_ready_path задан - пользователь уже указал готовый файл.
        # Диалог выбора файла показываем здесь, после декомпиляции (чтобы знать куда копировать)
        replace_model_smd_path = VpkModelPipeline._resolve_replace_model_smd(
            replace_model_enabled, r.model_ready_path, r.replace_model_path,
            model_file_callback,
        )

        VpkModelPipeline._apply_model_replacement(
            ctx, qc_path, weapon_key, replace_model_smd_path,
            extra_model_callback, r.language, emit_sub,
            keep_user_materials=r.replace_keep_materials,
            part_models=r.part_models,
        )

        # Извлекаем путь из $cdmaterials в QC файле (до патчинга, потому что потом мы его изменим)
        original_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
        # Все $cdmaterials пути (для поиска оригинальных VTF в VPK игры)
        original_cdmaterials_paths = ModelBuildService.extract_all_cdmaterials_paths_from_qc(qc_path)

        # Гирлянда праздничного оружия берёт огоньки из ОБЩЕЙ папки: у 26
        # гирлянд `models/player/items/heavy/xms_colored_lights` один на
        # всех. Мод двух разных праздничных оружий писал бы одну и ту же
        # текстуру, и в игре обе гирлянды показали бы ту, чей VPK победил.
        # Своя папка на модель - та же, что у сборки гирлянды через
        # переключатель на базовом оружии (decor_build). Исходные пути уже
        # сняты выше: по ним ищутся оригиналы в игре
        if VPKService._is_attachment_only(weapon_key, tf2_misc_vpk):
            from src.services.decor_build import DECOR_MATERIALS_ROOT, _set_cdmaterials
            _set_cdmaterials(qc_path, f"{DECOR_MATERIALS_ROOT}\\{Path(found_mdl_path).stem}")

        if not original_cdmaterials_path:
            return t['error_cdmaterials_not_extracted'].format(qc_path=qc_path), None

        # Извлекаем имя файла из $texturegroup (до патчинга, потому что потом мы его изменим)
        texture_filename = ModelBuildService.extract_texturegroup_filename(qc_path)
        if not texture_filename:
            return t['error_texturegroup_not_extracted'].format(qc_path=qc_path), None

        if r.mode == "hat":
            logger.info(
                f"[HAT BUILD NAMES]  qc={qc_path!r}\n"
                f"  weapon_key          = {weapon_key!r}\n"
                f"  texture_filename    = {texture_filename!r}\n"
                f"  cdmaterials_path    = {original_cdmaterials_path!r}\n"
                f"  replace_smd_path    = {replace_model_smd_path!r}"
            )
            # Показываем пользователю оригинальные имена из игры (не имена файла-замены)
            if replace_model_smd_path and os.path.basename(replace_model_smd_path):
                emit_sub(-1,
                    f"Original game names: model={weapon_key}, texture={texture_filename}"
                    if r.language == "en" else
                    f"Оригинальные имена из игры: модель={weapon_key}, текстура={texture_filename}"
                )

        return None, _ModelSource(
            found_mdl_path=found_mdl_path,
            replace_model_smd_path=replace_model_smd_path,
            original_cdmaterials_path=original_cdmaterials_path,
            original_cdmaterials_paths=original_cdmaterials_paths,
            texture_filename=texture_filename,
        )

    @staticmethod
    def _stage_material_output(
        ctx, qc_path: str, texture_filename: str, mode: str, t: dict,
    ) -> Tuple[Optional[str], Optional[_MaterialOutput]]:
        """
        Стадия 5: куда писать материалы главной текстуры - папка из
        $cdmaterials ПОСЛЕ патча QC (с префиксом обхода sv_pure)

        Returns:
            (error_message, None) - ошибка, ctx НЕ очищен;
            (None, _MaterialOutput) - успех, папка создана
        """
        # Путь из $cdmaterials после патчинга (с префиксом console\)
        patched_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
        if not patched_cdmaterials_path:
            return t['error_cdmaterials_patched_not_extracted'].format(qc_path=qc_path), None

        # Путь в формате: console\models\weapons\v_bonesaw
        # Конвертируем в: materials/console/models/weapons/v_bonesaw/ (потому что VPK требует такую структуру)
        materials_rel_path = "materials/" + patched_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
        if not materials_rel_path.endswith('/'):
            materials_rel_path += '/'

        vmt_filename = f"{texture_filename}.vmt"
        vtf_filename = f"{texture_filename}.vtf"

        # Подготавливаем пути в vpkroot (создаем структуру папок как в VPK)
        vtf_output_path = ctx.vpkroot_dir.joinpath(*materials_rel_path.rstrip('/').split('/'))

        try:
            ensure_directory_exists(vtf_output_path)
        except OSError as e:
            if "path too long" in str(e).lower():
                logger.error(f"Путь слишком длинный для режима {mode}")
                return t['error_path_too_long'].format(mode=mode), None
            raise

        return None, _MaterialOutput(
            patched_cdmaterials_path=patched_cdmaterials_path,
            vtf_output_path=vtf_output_path,
            vmt_path=vtf_output_path / vmt_filename,
            vtf_filename=vtf_filename,
            vtf_temp_png=vtf_output_path / vtf_filename.replace(".vtf", ".png"),
        )

    @staticmethod
    def _ready_model_declined(r: BuildRequest, qc_path: str, weapon_key: str, ctx,
                              texture_mismatch_callback) -> Optional[str]:
        """Режим «Модель уже готова»: материалы SMD не совпали с игровыми, и
        человек отказался продолжать. -> текст отмены или None"""
        mismatch = VPKService._ready_model_texture_mismatch(
            r.model_ready_path, qc_path, weapon_key, ctx.decompile_dir, r.language)
        if not (mismatch and texture_mismatch_callback
                and not texture_mismatch_callback(mismatch)):
            return None
        logger.info("[MODEL READY] Пользователь отменил сборку из-за несовпадения текстур")
        return ("Сборка отменена: несовпадение текстур в SMD файле."
                if r.language == "ru" else
                "Build cancelled: texture mismatch in SMD file.")

    @staticmethod
    def _stage_part_materials(ctx, r: BuildRequest, qc_path: str, weapon_key: str,
                              replace_model_smd_path) -> Tuple[dict, object]:
        """
        Части модели - своими материалами: их треугольники в SMD под новым
        именем и столбец в $texturegroup (src/services/part_materials.py).
        После плана материалов - иначе сборка спросила бы, чем красить
        новый материал, до компиляции - он должен попасть в модель

        Returns: (part_variants, part_specs)
        """
        part_variants = {}
        part_specs = r.part_materials
        if r.part_materials and not r.model_ready_path:
            from src.services import part_materials as _pm
            if replace_model_smd_path:
                # Своя модель: её треугольники уже в reference-SMD разобранной
                # модели (_apply_model_replacement) - под именами модели
                _ref_smd = VpkModelPipeline._find_decompiled_reference_smd(
                    qc_path, weapon_key, ctx.decompile_dir)
                part_specs = (_pm.specs_for_custom_model(
                    r.part_materials, _ref_smd, r.replace_keep_materials)
                    if _ref_smd else [])
            part_variants = _pm.apply_to_model(qc_path, part_specs, ctx.warn)
        return part_variants, part_specs

    @staticmethod
    def _stage_textures(
        ctx, r: BuildRequest, src: _ModelSource, plan: MaterialPlan,
        out: _MaterialOutput, weapon_key: str, tf2_misc_vpk: str,
        tf2_textures_vpk, part_variants: dict, part_specs, extra_texture_callback,
    ) -> Tuple[object, Optional[str]]:
        """
        Стадия 6: все текстуры и VMT мода (идёт параллельно с компиляцией)

        Returns: (image_path главной после рендера, vmt_to_delete)
        """
        texture_filename = plan.texture_filename
        flags = r.flags or []
        vtf_options = r.vtf_options or {}
        panel_extra_textures = r.panel_extra_textures or {}
        strip_paints = (r.mode == "hat" and not r.hat_apply_game_paints)

        # Эффективные настройки на материал: пер-текстурный оверрайд
        # поверх глобальных (size/format/flags/options), без оверрайда -
        # глобальные. Замыкание нужно и для главной текстуры, и для
        # panel-extra текстур дальше по коду
        from src.data.texture_overrides import effective_settings as _eff_settings
        from src.data.texture_overrides import own_settings as _own_settings
        _global_tex = {'size': r.size, 'format': r.format_type,
                       'flags': flags, 'options': vtf_options}
        material_settings = r.material_settings or {}

        def _eff(_mat):
            # Имя карточки и материала модели расходятся (Material.001,
            # пустой ключ главного у одноматериальной модели)
            own = _own_settings(material_settings, _mat, texture_filename)
            e = _eff_settings(_global_tex, own)
            return e['size'], e['format'], e['flags'], e['options']

        # Два контекста на всю запись материалов: куда писать и где искать
        # оригиналы (slots) + как рендерить VTF (tex_ctx), а не дюжина
        # значений по одному в каждую функцию
        slots = MaterialSlots(
            vtf_output_path=out.vtf_output_path,
            vmt_path=out.vmt_path,
            patched_cdmaterials_path=out.patched_cdmaterials_path,
            original_cdmaterials_paths=src.original_cdmaterials_paths,
            tf2_textures_vpk=tf2_textures_vpk,
            tf2_misc_vpk=tf2_misc_vpk,
        )
        tex_ctx = TextureBuildContext(
            vtf_output_path=out.vtf_output_path,
            size=r.size,
            format_type=r.format_type,
            flags=flags,
            vtf_options=vtf_options,
            custom_vtf_path=r.custom_vtf_path,
            stock_normal_ok=not (src.replace_model_smd_path or r.model_ready_path),
            main_from_game=r.main_from_game,
            settings_for=_eff,
            # Главная, доп. материалы и синие жмутся одновременно, до finish().
            # ponytail: при ошибке посреди стадии фоновые сжатия дорабатывают
            # без ожидания, как и компиляция модели
            jobs=VtfJobs(),
        )

        # Главная текстура: RED-резолв -> VTF (custom/готовый/рендер) ->
        # оригинальный VMT с перенаправлением $basetexture
        image_path, animated_fps, is_normal_map, vmt_to_delete = (
            VpkTextureBuilder._build_main_material(
                plan.image_path, texture_filename, out.vtf_filename, out.vtf_temp_png,
                src.original_cdmaterials_path, plan.game_vmt_name, r.mode,
                r.hat_apply_game_paints, ctx, slots, tex_ctx,
                extra_texture_callback, weapon_key, _eff,
            )
        )

        # Пер-текстурные файловые карты (detail/selfillum/phong) применяются
        # ПОЗЖЕ - после создания VMT доп. материалов и BLU (см. ниже),
        # чтобы карты ложились в VMT именно своего материала

        # BLU Team Texture (командная раскраска)
        # Для оружия с одной общей текстурой (часы шпиона) BLU не создаём,
        # даже если в BLU-слот случайно попала картинка - иначе появится
        # лишний {texture}_blue.vtf/vmt
        VpkTextureBuilder._maybe_build_blu_team_texture(
            weapon_key, plan.blu_row, plan.blu_is_team, plan.blu_mode, r.blu_image_path,
            out.vtf_filename, texture_filename, slots,
            tex_ctx.for_material(texture_filename),   # синий главной - её карточка
            red_row=plan.tg_structure.get('red_row') or [],
        )

        # Создаем текстуры для дополнительных материалов модели (shell, scope и т.д.)
        # Это столбцы 1+ из RED строки $texturegroup
        # Словарь для хранения путей к VTF дополнительных материалов (нужно для BLU копий)
        _variant_copies: list = []
        extra_materials_vtf_paths = VpkTextureBuilder._build_extra_material_textures(
            plan.extra_materials, weapon_key, ctx, slots, tex_ctx,
            extra_texture_callback, animated_fps,
            tg_rows=plan.tg_structure.get('all_rows') or [], deferred=_variant_copies,
            strip_paints=strip_paints,
        )

        # Блэклист/служебные материалы: запись ОРИГИНАЛЬНОГО VMT
        # Глаза/убер/зомби и т.п. не редактируются (нет карточек), но из-за
        # console\-cdmaterials модель ищет их VMT по новому пути - без него
        # материал фиолетовый. Копируем оригинальный VMT материала в
        # console\-путь: его текстурные ссылки АБСОЛЮТНЫЕ (eyeball->shared,
        # invun/zombie->models/player/...), поэтому отдельный VTF не нужен -
        # игровые текстуры находятся по абсолютным путям. На случай
        # относительного $basetexture дополнительно кладём VTF, если он есть
        VpkTextureBuilder._write_blacklisted_materials(
            plan.blacklisted_extra, panel_extra_textures, ctx, slots)

        # Изолированные плечи вьюмодели
        # Пишем переименованный материал плеч (vm_<orig>) под главным
        # console-путём. Источник: пользовательская текстура (ключ -
        # ОРИГИНАЛЬНОЕ имя материала) либо оригинал тела из игры
        VpkTextureBuilder._write_shoulder_iso_materials(
            plan.shoulder_iso, ctx, slots, tex_ctx)

        # Создаем текстуры для BLU команды
        # BLU - это отдельная строка (row 1) в $texturegroup
        # Для каждого материала в BLU строке спрашиваем отдельное изображение,
        # если пользователь отказывается - копируем соответствующую RED текстуру
        VpkTextureBuilder._build_blu_row_textures(
            plan.blu_row, plan.tg_structure, texture_filename, out.vtf_filename, ctx,
            slots, tex_ctx, extra_texture_callback, weapon_key,
            animated_fps, is_normal_map, extra_materials_vtf_paths,
        )
        tex_ctx.jobs.finish()
        tex_ctx.jobs = None   # дальше шаги читают VTF сразу после записи
        # Синие убер/зомби с «Скопировать главную»: их пара появилась только сейчас
        VpkTextureBuilder._finish_variant_copies(
            _variant_copies, ctx, slots, strip_paints=strip_paints)

        # Зеркальные VMT по оригинальному пути (руки / spy-watch и т.п.).
        # Для all-class %s-шапок зеркало НЕ создаём (его заменила пер-классовая
        # сборка, иначе затёрлась бы текстура у невыбранных классов)
        VPKService._write_hand_mirror_vmts(
            ctx, r.mode, weapon_key, src.original_cdmaterials_path, out.vtf_output_path)

        if r.debug_mode:
            DebugService.save_patched_stage(ctx, ctx.decompile_dir)

        # Текстуры из 2D панели (c_arrow, sniper_lens и т.п.)
        # Материалы из SMD модели которые НЕ в QC skinfamilies ->
        # extra_texture_callback их не покрывает -> добавляем здесь.
        # Фиксированные доп. текстуры (vgui-вставки и т.п.) - пишем по
        # их зашитому пути, не по cdmaterials. Возвращает обработанные имена
        VpkTextureBuilder._build_secondary_textures(
            weapon_key, panel_extra_textures, ctx, slots, tex_ctx,
            r.material_maps or {}, texture_filename, image_path, is_normal_map,
            plan.has_skins, plan.skin_build_data, _eff,
            part_variants=part_variants, part_specs=part_specs,
            # Синий у исходного материала части: в его строках у части
            # своя синяя картинка
            blu_of=(dict(zip(plan.tg_structure.get('red_row') or [],
                             plan.tg_structure.get('blu_row') or []))
                    if plan.blu_is_team else None),
            strip_paints=strip_paints,
        )
        # Служебные материалы, которые в игре делят текстуру с собранным
        # (руки хэви - с телом), смотрят на текстуру мода
        VpkTextureBuilder._follow_shared_textures(ctx, slots)
        return image_path, vmt_to_delete

    @staticmethod
    def _stage_collect_models(
        ctx, r: BuildRequest, src: _ModelSource, plan: MaterialPlan,
        out: _MaterialOutput, tools: _Tools, weapon_key: str, qc_path: str,
        tf2_textures_vpk, part_variants: dict, part_specs, image_path,
        bypass_prefix: str, emit_sub,
    ) -> None:
        """Стадия 7: скомпилированная модель в vpkroot + доп. модели в тот же
        мод (остальные классы и стили шапки, гирлянды)"""
        flags = r.flags or []
        vtf_options = r.vtf_options or {}

        # Копируем скомпилированные файлы в vpkroot (VMT файл уже скопирован ранее)
        # Используем путь из $modelname в QC файле (чтобы структура папок была правильной).
        # Для material-only оружия (Dead Ringer) модель в мод НЕ кладём -
        # его показывает родная игровая модель (viewmodel), а скин и карты
        # находятся через зеркальный VMT по оригинальному пути, который
        # ссылается на console-VTF. Папку console при этом ОСТАВЛЯЕМ
        from src.data.weapon_quirks import MATERIAL_ONLY_WEAPON_KEYS as _MAT_ONLY
        if weapon_key in _MAT_ONLY:
            logger.info(f"[{weapon_key}] Material-only: модель в мод не включается (console сохраняется)")
        else:
            ModelService.copy_compiled_models_to_vpkroot(ctx, qc_path)

        # Мультиклассовая шапка: собираем модель для ОСТАЛЬНЫХ выбранных
        # классов (основная сборка делает только один). Нужно и БЕЗ замены
        # геометрии: у каждой классовой модели свой файл, и путь к
        # материалам на папку обхода переписывается при компиляции -
        # непересобранный класс грузит оригинальную текстуру игры.
        # Источник: явный список выбранных классов (model_player_per_class)
        # либо legacy %s-шаблон в hat_mdl_path
        if r.mode == "hat":
            _extra_targets = None
            if r.hat_class_models and len(r.hat_class_models) > 1:
                # Все выбранные классы, КРОМЕ primary (он уже собран)
                _extra_targets = [
                    m for m in r.hat_class_models.values() if m != r.hat_mdl_path
                ]
            _is_pct_tmpl = bool(r.hat_mdl_path and "%s" in r.hat_mdl_path)
            if _extra_targets or _is_pct_tmpl:
                VpkModelPipeline._build_extra_class_hat_models(
                    ctx, r.hat_mdl_path, src.found_mdl_path, src.replace_model_smd_path,
                    r.replace_keep_materials, tools.tf2_misc_vpk, tools.studiomdl_exe,
                    tools.tf_dir, r.language, emit_sub,
                    target_mdl_paths=_extra_targets,
                    bypass_prefix=bypass_prefix,
                    # Части выбирали на модели этого класса: остальным их
                    # переносят по участкам текстуры.
                    # Родная цель частей (`existing`) столбца не даёт, но
                    # треугольники переименовала - классы узнают о ней тоже
                    # (specs_for_other_model её не переносит и скажет)
                    part_specs=part_specs if (part_variants or any(
                        s.get('existing') for s in part_specs or ())) else None,
                    part_source_qc=qc_path,
                    part_names=part_variants,
                )

        # Этап 3: доп. ИЗМЕНЁННЫЕ стили-модели шапки - каждый своей
        # моделью и своей текстурой в тот же мод (активный стиль уже
        # собран основным пайплайном выше)
        if r.mode == "hat" and r.hat_style_builds:
            # Текстура активного стиля уже записана основным пайплайном -
            # передаём её, чтобы поймать стили, делящие один материал
            _written = {
                f"{out.patched_cdmaterials_path}/{plan.texture_filename}".lower():
                    image_path or "",
            }
            VpkModelPipeline._build_extra_style_models(
                ctx, r.hat_style_builds, tools.tf2_misc_vpk, tools.studiomdl_exe,
                tools.tf_dir, r.language, emit_sub,
                r.size, r.format_type, flags, vtf_options, out.vmt_path,
                bypass_prefix=bypass_prefix,
                written_textures=_written,
            )

        # Гирлянды поверх оружия - своими моделями в тот же мод
        if r.decor_builds:
            from src.services.decor_build import build_decor_models
            build_decor_models(
                ctx, r.decor_builds, misc_vpk=tools.tf2_misc_vpk,
                textures_vpk=tf2_textures_vpk, studiomdl_exe=tools.studiomdl_exe,
                tf_dir=tools.tf_dir, size=r.size, format_type=r.format_type,
                flags=flags, vtf_options=vtf_options,
                bypass_prefix=bypass_prefix, emit_sub=emit_sub,
                language=r.language)

    @staticmethod
    def _drop_stray_blue(ctx, weapon_key: str, blu_is_team: bool, texture_filename: str,
                         vtf_output_path: Path, original_cdmaterials_path: str) -> None:
        """
        Подстраховка: удаляем любые {texture}_blue.*, если их успел
        создать другой путь, а настоящей команды у предмета нет
        (одиночная текстура ИЛИ вариант-онли без c_xxx_blue в группе)
        """
        from src.data.weapon_quirks import NO_BLU_WEAPON_KEYS
        if not (weapon_key in NO_BLU_WEAPON_KEYS or not blu_is_team):
            return
        # С зеркальными копиями VMT (руки, часы): иначе копия по
        # оригинальному пути осталась бы ссылкой на удалённый VTF
        _dirs = [vtf_output_path]
        if original_cdmaterials_path:
            _mirror = VPKService._mirror_dir(ctx, original_cdmaterials_path)
            if _mirror != vtf_output_path:
                _dirs.append(_mirror)
        for _blue in (b for d in _dirs for b in d.glob(f"{texture_filename}_blue.*")):
            try:
                _blue.unlink()
                logger.info(f"[{weapon_key}] Удалён лишний BLU-файл: {_blue.name}")
            except OSError:
                pass

    @staticmethod
    def _is_decor_only(r: BuildRequest) -> bool:
        """В сборке только гирлянды: ни своей текстуры оружия, ни модели

        Любая правка самого оружия (карты, стили, «сделать командным»)
        ведёт в обычную сборку: там она либо соберётся, либо о ней скажут,
        а молча выпасть из мода ради гирлянды она не должна
        """
        from src.domain.preview.texture_state import is_decor
        from src.services.decor_bake import bake_entry
        weapon_maps = [m for m in (r.material_maps or {}) if not is_decor(m)]
        # Вшитая гирлянда - часть модели оружия: оно в мод идёт обязательно
        return bool(r.decor_builds) and not bake_entry(r.decor_builds) and not (
            r.image_path or r.custom_vtf_path or r.panel_extra_textures
            or r.panel_blu_textures or r.replace_model_enabled
            or r.model_ready_path or r.custom_vpk_source_path
            or weapon_maps or r.skin_build_data or r.force_team
            or r.hat_style_builds or r.part_models)

    @staticmethod
    def _build_decor_only_vpk(ctx, r: BuildRequest, weapon_key: str, t: dict,
                              emit_progress, emit_sub) -> Tuple[bool, str]:
        """Мод из одних гирлянд: модель оружия остаётся игровой"""
        from src.services.decor_build import build_decor_models
        from src.shared.constants import bypass_prefix as _resolve_bypass_prefix

        err, tools = VPKService._stage_locate_tools(
            ctx, r.mode, weapon_key, r.hat_mdl_path, r.tf2_root_dir, t,
            r.keep_temp_on_error, r.debug_mode)
        if err is not None:
            return err
        studiomdl_exe, tf2_misc_vpk, tf_dir, _paths = tools
        emit_progress(40, t.get('build_compiling', 'Compiling model...'))
        built = build_decor_models(
            ctx, r.decor_builds, misc_vpk=tf2_misc_vpk,
            textures_vpk=TF2Paths.resolve_textures_vpk(r.tf2_root_dir),
            studiomdl_exe=studiomdl_exe, tf_dir=tf_dir, size=r.size,
            format_type=r.format_type, flags=r.flags or [],
            vtf_options=r.vtf_options or {},
            bypass_prefix=_resolve_bypass_prefix(r.bypass_method),
            emit_sub=emit_sub, language=r.language)
        if not built:
            ctx.cleanup(on_error=True, keep_on_error=r.keep_temp_on_error,
                        debug_mode=r.debug_mode)
            return False, ("Lights could not be built - see the log"
                           if r.language == 'en' else
                           "Гирлянду собрать не удалось - подробности в журнале")
        return True, ''

    @staticmethod
    def _strip_game_tint(vpkroot) -> None:
        """
        Снимает покраску игры с материалов мода, чья текстура - своя

        Одним проходом по готовому vpkroot, а не в каждом месте записи VMT:
        главный, BLU, доп. и «вторичные» материалы пишутся разными путями, и
        пропустить хоть один значило бы оставить, например, BLU красным.
        Своя текстура - та, чей VTF лежит в моде: служебные материалы пишутся
        оригиналом и ссылаются на игровой путь, их покраску не трогаем
        """
        from src.services import vmt_parse, vmt_tint
        from src.services.vmt_service import VMTService

        root = Path(vpkroot)
        for vmt in root.rglob('*.vmt'):
            try:
                text = vmt.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            if vmt_tint.parse_tint(text) is None:
                continue
            base = vmt_parse.parse(text).path('basetexture')
            if not base or not (root / 'materials' / f'{base}.vtf').exists():
                continue
            VMTService.remove_paint_proxies(str(vmt))
            logger.info(f"[tint] покраска игры снята: {vmt.name}")

    @staticmethod
    def build_vpk(
        request: Optional[BuildRequest] = None,
        *,
        model_file_callback=None,  # Колбэк для запроса файла у страницы
        extra_texture_callback=None,  # Колбэк для запроса одной доп. текстуры: callback(material_name, weapon_key) -> Optional[str]
        extra_model_callback=None,  # Колбэк для запроса доп. модели: callback(smd_name, weapon_key) -> Optional[str]
        texture_mismatch_callback=None,  # Колбэк для предупреждения о несовпадении текстур: callback(msg) -> bool
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,  # Главный прогресс (проценты стадий)
        cancel_callback: Optional[Callable[[], bool]] = None,  # True = пользователь запросил отмену
        **legacy_kwargs,  # Совместимость: build_vpk(image_path=..., mode=...) собирает BuildRequest
    ) -> Tuple[bool, str]:
        """
        Главная функция: делает из картинки VPK файл.
        Возвращает (success, message), при ошибке message содержит описание.
        Здесь весь конвейер: модель -> текстуры -> компиляция -> упаковка

        Параметры сборки берутся из ``request`` (BuildRequest). Для обратной
        совместимости (и тестов) допускается старый вызов через kwargs -
        тогда BuildRequest собирается из них. Колбэки - это runtime-функции
        UI-потока, они всегда передаются отдельно
        """
        if request is None:
            request = BuildRequest(**legacy_kwargs)

        # Распаковываем только то, что нужно оркестратору (валидация, спец-режимы,
        # упаковка). Модельный конвейер распаковывает запрос сам -
        # см. _build_model_mode_vpk
        r = request
        image_path = r.image_path
        mode = r.mode
        filename = r.filename
        size = r.size
        format_type = r.format_type
        flags = r.flags or []
        vtf_options = r.vtf_options or {}
        tf2_root_dir = r.tf2_root_dir
        export_folder = r.export_folder
        keep_temp_on_error = r.keep_temp_on_error
        debug_mode = r.debug_mode
        hat_mdl_path = r.hat_mdl_path
        language = r.language
        custom_vtf_path = r.custom_vtf_path

        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit_sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        def emit_progress(value: int, message: str) -> None:
            if progress_callback:
                progress_callback(value, message)

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

        def cancelled_result(ctx) -> Tuple[bool, str]:
            """Очистка ctx и стандартный ответ при отмене пользователем"""
            if ctx is not None:
                ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=debug_mode)
            logger.info("Сборка отменена пользователем")
            return False, t.get('build_cancelled', 'Build cancelled by user')

        # Правлена одна гирлянда: оружие в мод не идёт, собирать его незачем
        decor_only = VPKService._is_decor_only(r)

        ctx = None
        try:
            # Проверяем что все на месте, иначе потом будет больно (валидация параметров)
            validation_error = validate_build_params(
                EXTRA_TEX_USE_GAME_ORIGINAL if decor_only else image_path,
                mode, filename, size, format_type, tf2_root_dir, t, custom_vtf_path
            )
            if validation_error:
                return False, validation_error

            # weapon_key - ключ модели/файлов: для рук это arm-модель, для тела/
            # масок шпиона - стем MDL, для шапки - стем hat_mdl_path, иначе суффикс mode
            weapon_key, _wk_error = VPKService._resolve_weapon_key(mode, hat_mdl_path)
            if _wk_error:
                return False, _wk_error

            # Запоминаем какой VMT надо будет удалить после сборки (если юзер его редактировал через редактор)
            vmt_to_delete = None
            
            ctx = BuildContext.create(mode, weapon_key, debug_mode=debug_mode)
            
            # Маски маскировки шпиона
            # Не нужен MDL, QC-патчинг или компиляция.
            # Просто кладём mask_*.vtf/vmt по оригинальному пути игры:
            #   materials/models/player/spy/mask_*.vtf
            # Это прямой override, как у SPECIAL_MODES
            if mode == SPY_MASK_MODE_KEY:
                from src.services.spy_mask_build import build_spy_masks_vpk
                result = build_spy_masks_vpk(
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
            if mode in SPECIAL_MODES:
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

            elif decor_only:
                ok, payload = VPKService._build_decor_only_vpk(
                    ctx, request, weapon_key, t, emit_progress, emit_sub)
                if not ok:
                    return False, payload
                vmt_to_delete = None

            else:
                ok, payload = VPKService._build_model_mode_vpk(
                    ctx, request, weapon_key, t,
                    model_file_callback=model_file_callback,
                    extra_texture_callback=extra_texture_callback,
                    extra_model_callback=extra_model_callback,
                    texture_mismatch_callback=texture_mismatch_callback,
                    emit_progress=emit_progress,
                    emit_sub=emit_sub,
                    is_cancelled=is_cancelled,
                    cancelled_result=cancelled_result,
                )
                if not ok:
                    return False, payload
                vmt_to_delete = payload or None

            
            if request.strip_game_tint:
                VPKService._strip_game_tint(ctx.vpkroot_dir)

            # Собираем VPK файл (финальный этап - упаковываем все в один файл)
            if is_cancelled():
                return cancelled_result(ctx)
            emit_progress(80, t.get('build_packing', 'Creating VPK file...'))
            emit_sub(-1, "Packing VPK..." if language == "en" else "Упаковка VPK...")
            # Содержимое vpkroot: краткая сводка всегда, полный список - только в
            # debug-режиме (сотни строк на сборку засоряли tf2sg.log)
            if ctx.vpkroot_dir.exists():
                vpkroot_files = []
                for _root, _dirs, _files in os.walk(ctx.vpkroot_dir):
                    for _f in _files:
                        rel = os.path.relpath(os.path.join(_root, _f), ctx.vpkroot_dir).replace('\\', '/')
                        vpkroot_files.append(rel)
                logger.info(f"[VPK CONTENTS] файлов в VPK: {len(vpkroot_files)}")
                if debug_mode:
                    logger.info("[VPK CONTENTS]\n" +
                                "\n".join(f"  {f}" for f in vpkroot_files))
            vpk_path = PackagingService.create_vpk_file(ctx, filename, export_folder, language)

            success_message = VPKService._finalize_build_success(
                ctx, vpk_path, vmt_to_delete, language, debug_mode, t
            )
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
