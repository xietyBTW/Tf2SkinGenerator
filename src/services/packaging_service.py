import os
import shutil
import subprocess
from pathlib import Path
from src.shared.constants import ToolPaths
from src.shared.file_utils import ensure_directory_exists
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class PackagingService:
    @staticmethod
    def get_vpk_tool() -> Path:
        return ToolPaths.get_vpk_tool()

    @staticmethod
    def create_vpk_file(ctx, filename: str, export_folder: str = "export", language: str = "en") -> str:
        vpkroot_parent = os.path.dirname(ctx.vpkroot_dir)
        temp_vpk_path = os.path.join(vpkroot_parent, "vpkroot.vpk")
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
        temp_vpk_path_obj = Path(temp_vpk_path)
        if temp_vpk_path_obj.exists():
            temp_vpk_path_obj.unlink()
        logger.info("Запуск vpk.exe для создания VPK...")
        result = subprocess.run([
            str(PackagingService.get_vpk_tool()),
            "-v", str(ctx.vpkroot_dir.resolve())
        ], cwd=str(vpkroot_parent), capture_output=True, text=True,
           creationflags=subprocess.CREATE_NO_WINDOW)
        logger.debug(f"vpk.exe завершился с кодом: {result.returncode}")
        if result.stdout:
            logger.debug(f"STDOUT: {result.stdout}")
        if result.stderr:
            logger.debug(f"STDERR: {result.stderr}")
        if result.returncode != 0:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])
            error_msg = t['error_vpk_creation_failed'].format(
                stdout=result.stdout,
                stderr=result.stderr
            )
            logger.error(f"Ошибка создания VPK: {error_msg}")
            from src.shared.exceptions import VPKCreationError
            raise VPKCreationError(result.stdout, result.stderr)
        if not temp_vpk_path_obj.exists():
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])
            error_msg = t['error_vpkroot_not_found'].format(path=vpkroot_parent)
            logger.error(error_msg)
            from src.shared.exceptions import FileNotFoundError
            raise FileNotFoundError(temp_vpk_path, error_msg)
        export_folder_path = Path(export_folder)
        ensure_directory_exists(export_folder_path)
        final_output = export_folder_path / filename
        if final_output.exists():
            final_output.unlink()
        shutil.move(str(temp_vpk_path), str(final_output))
        logger.info(f"VPK successfully created: {final_output}")
        return str(final_output)
