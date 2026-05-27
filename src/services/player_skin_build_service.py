"""
Обёртка для обратной совместимости.
Вся логика перенесена в PlayerTextureBuildService.
"""
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.services.build_context import BuildContext
from src.services.player_texture_build_service import PlayerTextureBuildService


class PlayerSkinBuildService:
    """
    Устаревший класс. Используй PlayerTextureBuildService.build_player_skin().
    Оставлен для обратной совместимости — все вызовы делегируются новому классу.
    """

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
        return PlayerTextureBuildService.build_player_skin(
            ctx=ctx,
            mode=mode,
            image_path=image_path,
            size=size,
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
        """Делегирует в PlayerTextureBuildService._convert_image_to_vtf."""
        PlayerTextureBuildService._convert_image_to_vtf(
            src_image, dest_vtf, vtf_output_dir, size, format_type, vtf_flags, merged_options,
        )
