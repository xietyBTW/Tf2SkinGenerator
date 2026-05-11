"""
Сборщик VPK-модов для текстур рук персонажей TF2.

Логика значительно проще, чем для оружия:
  - Не нужны MDL / декомпиляция / компиляция / VMT
  - Просто конвертируем PNG → VTF и кладём по нужному пути в VPK
  - Путь: materials/models/player/{folder}/{vtf_name}.vtf

Для персонажей с несколькими текстурами (Engineer, Medic, Spy):
  - Первая текстура берётся из основного image_path
  - Дополнительные запрашиваются через extra_texture_callback(vtf_name, mode_key)
  - Если callback не предоставлен или пользователь отказался — копируем первую текстуру
"""

import shutil
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.data.player_hands import HAND_MODES, get_hand_textures
from src.services.build_context import BuildContext
from src.services.texture_service import TextureService
from src.shared.file_utils import copy_file_safe, ensure_directory_exists
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_PLAYER_MAT_BASE = "materials/models/player"


class HandsBuildService:
    """Сборка VPK-модов для текстур рук персонажей."""

    @staticmethod
    def build(
        ctx: BuildContext,
        mode: str,
        image_path: Optional[str],
        size: Tuple[int, int],
        format_type: str = "DXT1",
        flags: Optional[List[str]] = None,
        vtf_options: Optional[dict] = None,
        keep_temp_on_error: bool = False,
        debug_mode: bool = False,
        language: str = "en",
        custom_vtf_path: Optional[str] = None,
        extra_texture_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Создаёт VTF файлы для рук персонажа и помещает их в vpkroot.

        Args:
            ctx:                    Контекст сборки (temp директории, vpkroot и т.д.)
            mode:                   Ключ режима (например, "scout_hands")
            image_path:             Путь к исходному изображению (основная текстура)
            size:                   Целевое разрешение VTF
            format_type:            DXT1/DXT5/etc.
            flags:                  Флаги VTFCmd
            vtf_options:            Дополнительные опции VTFCmd
            keep_temp_on_error:     Не удалять temp при ошибке
            debug_mode:             Режим отладки
            language:               Язык для сообщений об ошибках
            custom_vtf_path:        Готовый VTF файл вместо генерации из PNG
            extra_texture_callback: callback(vtf_name, mode) → Optional[str]
            sub_progress_callback:  callback(pct, label)

        Returns:
            (True, success_message) или (False, error_message)
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS["en"])

        def emit_sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        try:
            textures = get_hand_textures(mode)
            if not textures:
                return False, f"Unknown hand mode: {mode}"

            flags = flags or []
            vtf_options = vtf_options or {}

            # Разбираем флаги VTFCmd один раз
            vtf_flags, flags_parsed_options = TextureService.parse_vtf_flags_and_options(flags)
            merged_options: dict = {}
            if vtf_options:
                merged_options.update(vtf_options)
            merged_options.update(flags_parsed_options)
            # Normal map не имеет смысла для текстур рук, убираем
            merged_options.pop("normal", None)

            n_textures = len(textures)

            # Первичный источник текстуры (может быть custom VTF или PNG)
            primary_source = custom_vtf_path or image_path
            primary_vtf_path: Optional[Path] = None  # заполним при обработке первой текстуры

            for idx, (folder, vtf_name) in enumerate(textures):
                pct_start = int(idx / n_textures * 90)
                pct_end = int((idx + 1) / n_textures * 90)

                label_processing = (
                    f"Processing {vtf_name}..." if language == "en"
                    else f"Обработка {vtf_name}..."
                )
                emit_sub(pct_start, label_processing)
                logger.info(f"[hands] Обрабатываем текстуру {idx + 1}/{n_textures}: {vtf_name}")

                # Путь назначения в vpkroot
                vtf_output_dir = ctx.vpkroot_dir / _PLAYER_MAT_BASE / folder
                ensure_directory_exists(vtf_output_dir)
                dest_vtf = vtf_output_dir / f"{vtf_name}.vtf"

                if idx == 0:
                    # ── Первая текстура: основное изображение / custom VTF ──────────────
                    if custom_vtf_path:
                        copy_file_safe(custom_vtf_path, dest_vtf)
                        logger.info(f"[hands] Скопирован custom VTF: {dest_vtf}")
                    else:
                        HandsBuildService._convert_image_to_vtf(
                            image_path, dest_vtf, vtf_output_dir,
                            size, format_type, vtf_flags, merged_options
                        )
                        logger.info(f"[hands] Создан VTF: {dest_vtf}")
                    primary_vtf_path = dest_vtf

                else:
                    # ── Дополнительные текстуры: спрашиваем пользователя ───────────────
                    extra_src: Optional[str] = None
                    if extra_texture_callback:
                        extra_src = extra_texture_callback(vtf_name, mode)
                        if extra_src and not Path(extra_src).is_file():
                            logger.warning(f"[hands] Файл не найден: {extra_src}")
                            extra_src = None

                    if extra_src:
                        if custom_vtf_path:
                            # Пользователь дал VTF напрямую
                            copy_file_safe(extra_src, dest_vtf)
                        else:
                            HandsBuildService._convert_image_to_vtf(
                                extra_src, dest_vtf, vtf_output_dir,
                                size, format_type, vtf_flags, merged_options
                            )
                        logger.info(f"[hands] Доп. текстура из пользователя: {dest_vtf}")
                    else:
                        # Пользователь отказался — копируем первую текстуру
                        if primary_vtf_path and primary_vtf_path.exists():
                            copy_file_safe(primary_vtf_path, dest_vtf)
                            logger.info(
                                f"[hands] Доп. текстура скопирована из первичной: "
                                f"{primary_vtf_path.name} → {dest_vtf.name}"
                            )
                        else:
                            logger.warning(f"[hands] Первичная текстура недоступна для копирования: {dest_vtf}")

                emit_sub(pct_end, label_processing)

            emit_sub(90, "Done" if language == "en" else "Готово")
            return True, ""

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[hands] Ошибка при обработке текстур рук: {error_msg}", exc_info=True)
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, t.get("error_model_work", "Error: {error}").format(error=error_msg)

    # -----------------------------------------------------------------------
    # Вспомогательные методы
    # -----------------------------------------------------------------------

    @staticmethod
    def _convert_image_to_vtf(
        src_image: str,
        dest_vtf: Path,
        vtf_output_dir: Path,
        size: Tuple[int, int],
        format_type: str,
        vtf_flags: List[str],
        merged_options: dict,
    ) -> None:
        """Конвертирует PNG → VTF и перемещает в dest_vtf."""
        if TextureService.is_animated_image(src_image):
            TextureService.create_animated_vtf(
                src_image, str(dest_vtf), size, format_type, vtf_flags, merged_options
            )
            return

        # Для статичных изображений: resize → PNG → VTFCmd → переименовать
        stem = dest_vtf.stem
        temp_png = vtf_output_dir / f"{stem}.png"
        TextureService.process_image(src_image, temp_png, size)
        TextureService.create_vtf(str(temp_png), str(vtf_output_dir), format_type, vtf_flags, merged_options)
        if temp_png.exists():
            temp_png.unlink()

        # VTFCmd создаёт файл с тем же именем что у PNG — он уже в нужном месте
        created_vtf = vtf_output_dir / f"{stem}.vtf"
        if created_vtf.exists() and created_vtf != dest_vtf:
            created_vtf.rename(dest_vtf)
