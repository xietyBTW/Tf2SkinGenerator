import os
from pathlib import Path
from typing import Tuple
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.logging_config import get_logger
from src.services.model_build_service import ModelBuildService
from src.services.smd_service import SMDService

logger = get_logger(__name__)


class ModelService:
    @staticmethod
    def copy_compiled_models_to_vpkroot(ctx, qc_path: str) -> None:
        modelname_path = ModelBuildService.extract_modelname_path(qc_path)
        if not modelname_path:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])
            from src.shared.exceptions import FileNotFoundError
            raise FileNotFoundError(t['error_modelname_not_extracted'].format(qc_path=qc_path))
        normalized_path = modelname_path.replace('\\', '/')
        path_parts = normalized_path.split('/')
        if len(path_parts) > 1:
            model_dir_path = '/'.join(path_parts[:-1])
        else:
            model_dir_path = ""
        if model_dir_path:
            target_dir = ctx.vpkroot_dir / "models" / model_dir_path
        else:
            target_dir = ctx.vpkroot_dir / "models"
        ensure_directory_exists(target_dir)
        if not ctx.compile_dir.exists():
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])
            from src.shared.exceptions import FileNotFoundError
            raise FileNotFoundError(str(ctx.compile_dir), t['error_compile_dir_not_found'].format(path=ctx.compile_dir))
        model_filename = Path(modelname_path).name
        model_basename = Path(model_filename).stem
        model_files = []
        for file_path in ctx.compile_dir.iterdir():
            if file_path.is_file():
                file_name = file_path.name
                if file_name.startswith(model_basename) and file_name.endswith(('.mdl', '.vvd', '.vtx', '.phy')):
                    model_files.append(file_name)
        if not model_files:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])
            from src.shared.exceptions import FileNotFoundError
            raise FileNotFoundError(t['error_model_files_not_found'].format(path=ctx.compile_dir, model=model_basename))
        logger.debug(f"Копируем {len(model_files)} файлов модели из {ctx.compile_dir} в {target_dir}")
        for file_name in model_files:
            src = ctx.compile_dir / file_name
            dst = target_dir / file_name
            logger.debug(f"Копируем: {file_name} -> {dst}")
            copy_file_safe(src, dst)
            logger.debug(f"Скопирован файл модели: {file_name}")
        logger.info(f"Все файлы модели скопированы в VPK root: {target_dir}")

    @staticmethod
    def generate_uv_layout(ctx, weapon_key: str, image_size: Tuple[int, int], export_folder: str = "export", language: str = "en") -> None:
        try:
            from src.services.uv_layout_service import UVLayoutService
            logger.info(f"Генерация UV разметки для оружия: {weapon_key}")
            logger.debug(f"Директория декомпиляции: {ctx.decompile_dir}")
            smd_path = SMDService.find_reference_smd(str(ctx.decompile_dir), weapon_key)
            if not smd_path or not os.path.exists(smd_path):
                logger.warning(f"Не найден SMD файл для генерации UV разметки: {weapon_key}")
                logger.debug(f"Проверяемая директория: {ctx.decompile_dir}")
                if ctx.decompile_dir.exists():
                    smd_files = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')]
                    logger.debug(f"Найденные SMD файлы в директории: {smd_files}")
                return
            logger.debug(f"Найден SMD файл: {smd_path}")
            uv_filename = f"{weapon_key}_uv_layout.png"
            uv_output_path = Path(export_folder) / uv_filename
            ensure_directory_exists(uv_output_path.parent)
            if UVLayoutService.generate_uv_layout_from_smd(smd_path, str(uv_output_path), image_size):
                logger.info(f"UV разметка сохранена: {uv_output_path}")
            else:
                logger.error(f"Ошибка при создании UV разметки для {weapon_key}")
        except Exception as e:
            logger.error(f"Ошибка при генерации UV разметки: {e}", exc_info=True)
