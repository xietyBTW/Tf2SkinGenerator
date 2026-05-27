"""
Универсальный сборщик VTF-текстур для любой модели персонажа TF2.

Заменяет HandsBuildService и PlayerSkinBuildService — оба были идентичны
на 99%, разница только в том, какую функцию вызывать для получения списка
текстур. Теперь этот список передаётся снаружи через texture_getter.

Использование:
    # Руки
    PlayerTextureBuildService.build_hands(ctx, "scout_hands", img, size, ...)

    # Тело персонажа
    PlayerTextureBuildService.build_player_skin(ctx, "scout_body", img, size, ...)

    # Любой кастомный набор текстур
    PlayerTextureBuildService.build(
        ctx, mode, img, size,
        texture_getter=my_getter_func,
        log_tag="custom",
        ...
    )
"""

from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.services.build_context import BuildContext
from src.services.texture_service import TextureService
from src.shared.file_utils import copy_file_safe, ensure_directory_exists
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_PLAYER_MAT_BASE = "materials/models/player"


class PlayerTextureBuildService:
    """
    Сборка VTF-текстур для персонажей TF2 с произвольным набором текстур.

    Логика:
      - Не нужны MDL / декомпиляция / VMT
      - Конвертируем image → VTF и кладём по нужному пути в VPK
      - Путь: materials/models/player/{folder}/{vtf_name}.vtf
      - Первая текстура → основное изображение пользователя
      - Дополнительные → extra_texture_callback или копия первой
    """

    @staticmethod
    def build(
        ctx: BuildContext,
        mode: str,
        image_path: Optional[str],
        size: Tuple[int, int],
        texture_getter: Callable[[str], List[Tuple[str, str]]],
        log_tag: str = "player",
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
        Создаёт VTF файлы для персонажа и помещает их в vpkroot.

        Args:
            ctx:                    Контекст сборки (temp директории, vpkroot и т.д.)
            mode:                   Ключ режима (например, "scout_hands")
            image_path:             Путь к исходному изображению (основная текстура)
            size:                   Целевое разрешение VTF
            texture_getter:         Функция (mode) → List[(folder, vtf_name)].
                                    Определяет какие текстуры нужно создать.
            log_tag:                Префикс для лог-сообщений (например, "hands", "player_skin")
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
            (True, "") при успехе, (False, error_message) при ошибке.
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS["en"])

        def emit_sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        try:
            textures = texture_getter(mode)
            if not textures:
                return False, f"[{log_tag}] No textures defined for mode: {mode!r}"

            flags = flags or []
            vtf_options = vtf_options or {}

            # Разбираем флаги VTFCmd один раз для всех текстур.
            # Normal map не имеет смысла для текстур персонажей — убираем.
            vtf_flags, flags_parsed_options = TextureService.parse_vtf_flags_and_options(flags)
            merged_options: dict = {**vtf_options, **flags_parsed_options}
            merged_options.pop("normal", None)

            n_textures = len(textures)
            primary_vtf_path: Optional[Path] = None

            for idx, (folder, vtf_name) in enumerate(textures):
                pct_start = int(idx / n_textures * 90)
                pct_end = int((idx + 1) / n_textures * 90)

                label = (
                    f"Processing {vtf_name}..." if language == "en"
                    else f"Обработка {vtf_name}..."
                )
                emit_sub(pct_start, label)
                logger.info(f"[{log_tag}] Текстура {idx + 1}/{n_textures}: {vtf_name}")

                vtf_output_dir = ctx.vpkroot_dir / _PLAYER_MAT_BASE / folder
                ensure_directory_exists(vtf_output_dir)
                dest_vtf = vtf_output_dir / f"{vtf_name}.vtf"

                if idx == 0:
                    # ── Первая текстура: основное изображение / custom VTF ──────────────
                    if custom_vtf_path:
                        copy_file_safe(custom_vtf_path, dest_vtf)
                        logger.info(f"[{log_tag}] Скопирован custom VTF → {dest_vtf}")
                    else:
                        PlayerTextureBuildService._convert_image_to_vtf(
                            image_path, dest_vtf, vtf_output_dir,
                            size, format_type, vtf_flags, merged_options,
                        )
                        logger.info(f"[{log_tag}] Создан VTF: {dest_vtf}")
                    primary_vtf_path = dest_vtf

                else:
                    # ── Дополнительные текстуры: спрашиваем пользователя ───────────────
                    extra_src: Optional[str] = None
                    if extra_texture_callback:
                        extra_src = extra_texture_callback(vtf_name, mode)
                        if extra_src and not Path(extra_src).is_file():
                            logger.warning(f"[{log_tag}] Файл не найден: {extra_src}")
                            extra_src = None

                    if extra_src:
                        if custom_vtf_path:
                            copy_file_safe(extra_src, dest_vtf)
                        else:
                            PlayerTextureBuildService._convert_image_to_vtf(
                                extra_src, dest_vtf, vtf_output_dir,
                                size, format_type, vtf_flags, merged_options,
                            )
                        logger.info(f"[{log_tag}] Доп. текстура от пользователя → {dest_vtf}")
                    else:
                        # Пользователь отказался — копируем первую текстуру
                        if primary_vtf_path and primary_vtf_path.exists():
                            copy_file_safe(primary_vtf_path, dest_vtf)
                            logger.info(
                                f"[{log_tag}] Доп. текстура скопирована: "
                                f"{primary_vtf_path.name} → {dest_vtf.name}"
                            )
                        else:
                            logger.warning(f"[{log_tag}] Первичная текстура недоступна: {dest_vtf}")

                emit_sub(pct_end, label)

            emit_sub(90, "Done" if language == "en" else "Готово")
            return True, ""

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{log_tag}] Ошибка: {error_msg}", exc_info=True)
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, t.get("error_model_work", "Error: {error}").format(error=error_msg)

    # ── Convenience-методы для стандартных сценариев ────────────────────── #

    @classmethod
    def build_hands(
        cls,
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
        """Строит VTF-моды для текстур рук персонажей."""
        from src.data.player_hands import get_hand_textures
        return cls.build(
            ctx=ctx,
            mode=mode,
            image_path=image_path,
            size=size,
            texture_getter=get_hand_textures,
            log_tag="hands",
            format_type=format_type,
            flags=flags,
            vtf_options=vtf_options,
            keep_temp_on_error=keep_temp_on_error,
            debug_mode=debug_mode,
            language=language,
            custom_vtf_path=custom_vtf_path,
            extra_texture_callback=extra_texture_callback,
            sub_progress_callback=sub_progress_callback,
        )

    @classmethod
    def build_player_skin(
        cls,
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
        """Строит VTF-моды для текстур тела персонажей."""
        from src.data.player_characters import get_player_body_textures
        return cls.build(
            ctx=ctx,
            mode=mode,
            image_path=image_path,
            size=size,
            texture_getter=get_player_body_textures,
            log_tag="player_skin",
            format_type=format_type,
            flags=flags,
            vtf_options=vtf_options,
            keep_temp_on_error=keep_temp_on_error,
            debug_mode=debug_mode,
            language=language,
            custom_vtf_path=custom_vtf_path,
            extra_texture_callback=extra_texture_callback,
            sub_progress_callback=sub_progress_callback,
        )

    # ── Внутренние хелперы ───────────────────────────────────────────────── #

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
        """Конвертирует PNG/GIF → VTF и кладёт в dest_vtf."""
        if TextureService.is_animated_image(src_image):
            TextureService.create_animated_vtf(
                src_image, str(dest_vtf), size, format_type, vtf_flags, merged_options,
            )
            return

        # Статичное изображение: resize → PNG → VTFCmd
        stem = dest_vtf.stem
        temp_png = vtf_output_dir / f"{stem}.png"
        TextureService.process_image(src_image, str(temp_png), size)
        TextureService.create_vtf(str(temp_png), str(vtf_output_dir), format_type, vtf_flags, merged_options)
        if temp_png.exists():
            temp_png.unlink()

        # VTFCmd создаёт файл с именем PNG-стема — переименовываем если нужно
        created_vtf = vtf_output_dir / f"{stem}.vtf"
        if created_vtf.exists() and created_vtf != dest_vtf:
            created_vtf.rename(dest_vtf)
