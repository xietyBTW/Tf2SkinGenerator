import os
import shutil
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict, Any

from src.data.translations import TRANSLATIONS
from src.data.weapons import WEAPON_MDL_PATHS
from src.services.build_context import BuildContext
from src.services.model_build_service import ModelBuildService
from src.services.tf2_paths import TF2Paths
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.file_utils import ensure_directory_exists
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class ExtractModelService:
    @staticmethod
    def _next_available_dir(base_dir: Path, base_name: str) -> Path:
        for i in range(1, 1000000):
            candidate = base_dir / f"{base_name}_{i}"
            if not candidate.exists():
                return candidate
        raise RuntimeError("Не удалось подобрать уникальное имя папки экспорта")

    @staticmethod
    def _next_available_file(base_dir: Path, file_name: str) -> Path:
        candidate = base_dir / file_name
        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        for i in range(1, 1000000):
            cand = base_dir / f"{stem}_{i}{suffix}"
            if not cand.exists():
                return cand
        raise RuntimeError("Не удалось подобрать уникальное имя файла экспорта")

    @staticmethod
    def _build_paths_to_try(mode: str, weapon_key: str) -> list[str]:
        base_path_from_config = WEAPON_MDL_PATHS[weapon_key]
        paths_to_try = []

        workshop_partner_path_with_folder = base_path_from_config.replace(
            "models/weapons/", "models/workshop_partner/weapons/"
        )
        paths_to_try.append(workshop_partner_path_with_folder)
        if f"/{weapon_key}/{weapon_key}.mdl" in workshop_partner_path_with_folder:
            paths_to_try.append(
                workshop_partner_path_with_folder.replace(
                    f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl"
                )
            )

        workshop_path_with_folder = base_path_from_config.replace(
            "models/weapons/", "models/workshop/weapons/"
        )
        paths_to_try.append(workshop_path_with_folder)
        if f"/{weapon_key}/{weapon_key}.mdl" in workshop_path_with_folder:
            paths_to_try.append(
                workshop_path_with_folder.replace(
                    f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl"
                )
            )

        paths_to_try.append(base_path_from_config)
        if f"/{weapon_key}/{weapon_key}.mdl" in base_path_from_config:
            paths_to_try.append(
                base_path_from_config.replace(
                    f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl"
                )
            )

        c_items_path_with_folder = base_path_from_config.replace(
            "models/weapons/c_models/", "models/weapons/c_items/"
        )
        paths_to_try.append(c_items_path_with_folder)
        if f"/{weapon_key}/{weapon_key}.mdl" in c_items_path_with_folder:
            paths_to_try.append(
                c_items_path_with_folder.replace(
                    f"/{weapon_key}/{weapon_key}.mdl", f"/{weapon_key}.mdl"
                )
            )

        if "_" in mode:
            class_name_lower = mode.split("_", 1)[0]
            paths_to_try.append(f"models/player/items/{class_name_lower}/{weapon_key}/{weapon_key}.mdl")
            paths_to_try.append(f"models/player/items/{class_name_lower}/{weapon_key}.mdl")

        return paths_to_try

    @staticmethod
    def cleanup_temp_dir(temp_dir: str) -> None:
        try:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

    @staticmethod
    def prepare_decompiled_model_files_with_progress(
        tf2_root_dir: str,
        mode: str,
        weapon_key: str,
        language: str = "en",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, str, bool, Optional[Dict[str, Any]]]:
        t = TRANSLATIONS.get(language, TRANSLATIONS["en"])

        def emit_progress(pct: int, status_key: str, fallback: str) -> None:
            if progress_callback:
                progress_callback(pct, t.get(status_key, fallback))

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

        ctx: Optional[BuildContext] = None
        try:
            emit_progress(5, "extract_model_init", "Инициализация извлечения модели...")
            if is_cancelled():
                return False, t.get("extract_model_cancelled", "Извлечение отменено пользователем"), True, None

            if not tf2_root_dir:
                return False, t.get("tf2_path_not_specified", "TF2 path not specified in settings"), False, None

            if weapon_key not in WEAPON_MDL_PATHS:
                return (
                    False,
                    t.get("error_weapon_not_found", "Weapon not found").format(weapon_key=weapon_key),
                    False,
                    None,
                )

            crowbar_exists, crowbar_error = TF2Paths.check_crowbar()
            if not crowbar_exists:
                return False, crowbar_error or "Crowbar CLI missing", False, None

            emit_progress(15, "extract_model_checking", "Проверка файлов игры...")
            _, tf2_misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)

            paths_to_try = ExtractModelService._build_paths_to_try(mode, weapon_key)
            found_mdl_path = None
            last_error = None
            for idx, mdl_rel_path in enumerate(paths_to_try):
                if is_cancelled():
                    return False, t.get("extract_model_cancelled", "Извлечение отменено пользователем"), True, None
                try:
                    if TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, mdl_rel_path):
                        found_mdl_path = mdl_rel_path
                        break
                except Exception as e:
                    last_error = e
                if progress_callback:
                    pct = 15 + int((idx + 1) / max(1, len(paths_to_try)) * 20)
                    progress_callback(pct, t.get("extract_model_searching", "Поиск модели..."))

            if not found_mdl_path:
                paths_str = "\n".join([f"  - {path}" for path in paths_to_try])
                error_msg = t.get(
                    "error_mdl_not_found",
                    "MDL not found.\nPaths:\n{paths}\nVPK: {vpk_file}",
                ).format(paths=paths_str, vpk_file=tf2_misc_vpk)
                if last_error:
                    error_msg += f"\n{str(last_error)}"
                return False, error_msg, False, None

            emit_progress(40, "extract_model_extracting", "Извлечение модели...")
            if is_cancelled():
                return False, t.get("extract_model_cancelled", "Извлечение отменено пользователем"), True, None

            ctx = BuildContext.create(f"model_export_{mode}", weapon_key, debug_mode=False)

            extracted_files = TF2VPKExtractService.extract_file_set(
                tf2_misc_vpk,
                found_mdl_path,
                str(ctx.extract_dir),
                None,
            )

            mdl_file = None
            for file_path in extracted_files:
                if file_path.endswith(".mdl"):
                    mdl_file = file_path
                    break
            if not mdl_file:
                return (
                    False,
                    t.get("error_mdl_not_extracted", "MDL not extracted").format(path=found_mdl_path),
                    False,
                    None,
                )

            emit_progress(70, "extract_model_decompiling", "Декомпиляция модели...")
            if is_cancelled():
                return False, t.get("extract_model_cancelled", "Извлечение отменено пользователем"), True, None

            crowbar_exe = TF2Paths.get_crowbar_path()
            _ = ModelBuildService.decompile(mdl_file, str(ctx.decompile_dir), crowbar_exe)

            emit_progress(95, "extract_model_completed", "Извлечение завершено")

            decompile_dir = Path(ctx.decompile_dir)
            files: List[str] = []
            for p in decompile_dir.rglob("*"):
                if p.is_file():
                    files.append(p.relative_to(decompile_dir).as_posix())
            files.sort()

            data = {
                "temp_dir": str(ctx.temp_dir),
                "decompile_dir": str(decompile_dir),
                "files": files,
            }
            return True, t.get("extract_model_completed", "Извлечение завершено"), False, data
        except Exception as e:
            logger.error(f"Ошибка при подготовке файлов модели: {e}", exc_info=True)
            if ctx:
                ExtractModelService.cleanup_temp_dir(str(ctx.temp_dir))
            return False, str(e), False, None

    @staticmethod
    def export_selected_files(
        decompile_dir: str,
        selected_files: List[str],
        export_folder: str,
        weapon_key: str,
    ) -> str:
        export_base = ensure_directory_exists(Path(export_folder))
        src_base = Path(decompile_dir)

        selected_files = [f for f in selected_files if f]
        if not selected_files:
            raise ValueError("No files selected")

        if len(selected_files) == 1:
            rel = selected_files[0]
            src = src_base / rel
            dst = ExtractModelService._next_available_file(export_base, src.name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return str(dst)

        export_dir = ExtractModelService._next_available_dir(export_base, weapon_key)
        ensure_directory_exists(export_dir)
        for rel in selected_files:
            src = src_base / rel
            dst = export_dir / Path(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return str(export_dir)

    @staticmethod
    def extract_original_model_with_progress(*args, **kwargs):
        raise RuntimeError("extract_original_model_with_progress is deprecated; use prepare_decompiled_model_files_with_progress + export_selected_files")
