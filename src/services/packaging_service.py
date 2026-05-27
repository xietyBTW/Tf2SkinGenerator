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
        """Создаёт VPK из ctx.vpkroot_dir и перемещает в export_folder/filename."""
        if ctx.vpkroot_dir.exists():
            logger.debug(f"Создание VPK из: {ctx.vpkroot_dir}")
            for root, dirs, files in os.walk(ctx.vpkroot_dir):
                level = root.replace(str(ctx.vpkroot_dir), '').count(os.sep)
                logger.debug(f"{'  ' * level}{os.path.basename(root)}/")
                for file in files:
                    logger.debug(f"{'  ' * (level + 1)}{file}")
        else:
            logger.warning(f"vpkroot_dir не существует: {ctx.vpkroot_dir}")

        return PackagingService.pack_directory(
            vpkroot_dir=ctx.vpkroot_dir,
            filename=filename,
            export_folder=export_folder,
            language=language,
        )

    @staticmethod
    def pack_directory(
        vpkroot_dir: Path,
        filename: str,
        export_folder: str = "export",
        language: str = "en",
    ) -> str:
        """
        Запускает vpk.exe -v <vpkroot_dir>, перемещает результат в export_folder/filename.

        Это единственное место в проекте где вызывается vpk.exe.
        MergeVPKService и CustomVPKService должны использовать этот метод.

        Args:
            vpkroot_dir:   Директория с содержимым мода (должна называться vpkroot)
            filename:      Имя выходного .vpk файла (например, "my_mod.vpk")
            export_folder: Куда переместить готовый файл
            language:      Язык для сообщений об ошибках

        Returns:
            Абсолютный путь к созданному VPK файлу.

        Raises:
            VPKCreationError:  vpk.exe вернул ненулевой код
            FileNotFoundError: vpk.exe не создал файл
        """
        from src.data.translations import TRANSLATIONS
        from src.shared.exceptions import VPKCreationError
        from src.shared.exceptions import FileNotFoundError as TFFileNotFoundError

        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        vpkroot_parent = vpkroot_dir.parent
        temp_vpk_path = vpkroot_parent / "vpkroot.vpk"

        if temp_vpk_path.exists():
            temp_vpk_path.unlink()

        logger.info("Запуск vpk.exe для создания VPK...")
        result = subprocess.run(
            [str(ToolPaths.get_vpk_tool()), "-v", str(vpkroot_dir.resolve())],
            cwd=str(vpkroot_parent),
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        logger.debug(f"vpk.exe завершился с кодом: {result.returncode}")
        if result.stdout:
            logger.debug(f"STDOUT: {result.stdout}")
        if result.stderr:
            logger.debug(f"STDERR: {result.stderr}")

        if result.returncode != 0:
            error_msg = t.get('error_vpk_creation_failed', 'VPK creation failed').format(
                stdout=result.stdout, stderr=result.stderr,
            )
            logger.error(f"Ошибка создания VPK: {error_msg}")
            raise VPKCreationError(result.stdout, result.stderr)

        if not temp_vpk_path.exists():
            error_msg = t.get('error_vpkroot_not_found', 'VPK file not found after creation').format(
                path=vpkroot_parent,
            )
            logger.error(error_msg)
            raise TFFileNotFoundError(temp_vpk_path, error_msg)

        export_folder_path = Path(export_folder)
        ensure_directory_exists(export_folder_path)
        final_output = export_folder_path / filename
        if final_output.exists():
            final_output.unlink()
        shutil.move(str(temp_vpk_path), str(final_output))

        logger.info(f"VPK успешно создан: {final_output}")
        return str(final_output)
