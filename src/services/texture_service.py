import os
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image
from src.shared.constants import ToolPaths
from src.shared.logging_config import get_logger
from src.services.vtflib_wrapper import VTFLib, VTFImageFormat, VTFImageFlags

logger = get_logger(__name__)


class TextureService:
    # Маппинг читаемых имён форматов → внутренние идентификаторы.
    # Используется и VTFLib-путём (_map_format_to_vtflib) и VTFCmd-путём (create_vtf).
    _FORMAT_ALIASES: dict = {
        "RGB888 Bluescreen":    "RGB888_BLUESCREEN",
        "BGR888 Bluescreen":    "BGR888_BLUESCREEN",
        "DXT1 With One Bit Alpha": "DXT1_ONEBITALPHA",
    }

    @staticmethod
    def get_vtf_tool() -> Path:
        return ToolPaths.get_vtf_tool()

    @staticmethod
    def process_image(input_path: str, output_path: str, size: Tuple[int, int]) -> None:
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Изображение не найдено: {input_path}")
        img = Image.open(input_path)
        has_alpha = img.mode in ('RGBA', 'LA') or 'transparency' in img.info
        if has_alpha:
            img = img.convert("RGBA").resize(size)
        else:
            img = img.convert("RGB").resize(size)
        img.save(output_path)

    @staticmethod
    def is_animated_image(input_path: str) -> bool:
        try:
            with Image.open(input_path) as img:
                return bool(getattr(img, "is_animated", False)) and int(getattr(img, "n_frames", 1)) > 1
        except Exception:
            return False

    @staticmethod
    def _extract_animation_frames_rgba(
        input_path: str,
        size: Tuple[int, int],
        max_frames: int = 512,
    ) -> Tuple[list[bytes], Optional[int]]:
        frames: list[bytes] = []
        fps: Optional[int] = None

        with Image.open(input_path) as img:
            n_frames = int(getattr(img, "n_frames", 1))
            if n_frames <= 1:
                frame = img.convert("RGBA").resize(size)
                frames.append(frame.tobytes())
                return frames, None

            duration_ms = None
            try:
                duration_ms = int(img.info.get("duration", 0)) if isinstance(img.info, dict) else None
            except Exception:
                duration_ms = None
            if duration_ms and duration_ms > 0:
                fps = max(1, min(240, int(round(1000 / duration_ms))))

            count = min(n_frames, max_frames)
            for i in range(count):
                img.seek(i)
                frame = img.convert("RGBA").resize(size)
                frames.append(frame.tobytes())

        return frames, fps

    @staticmethod
    def _map_format_to_vtflib(format_type: str, has_alpha: bool) -> int:
        vtf_format = TextureService._FORMAT_ALIASES.get(format_type, format_type).upper()

        if vtf_format == "DXT1" and has_alpha:
            return VTFImageFormat.DXT5

        if hasattr(VTFImageFormat, vtf_format):
            return int(getattr(VTFImageFormat, vtf_format))
        return VTFImageFormat.RGBA8888

    @staticmethod
    def _map_flags_to_vtflib(flags: List[str], options: dict) -> int:
        if flags is None:
            flags = []
        result = 0
        for flag in flags:
            f = (flag or "").upper()
            if f == "CLAMPS":
                result |= VTFImageFlags.CLAMPS
            elif f == "CLAMPT":
                result |= VTFImageFlags.CLAMPT
            elif f == "NOMIP":
                result |= VTFImageFlags.NOMIP
            elif f == "NOLOD":
                result |= VTFImageFlags.NOLOD
            elif f == "POINTSAMPLE":
                result |= VTFImageFlags.POINTSAMPLE
            elif f == "TRILINEAR":
                result |= VTFImageFlags.TRILINEAR
            elif f == "ANISOTROPIC":
                result |= VTFImageFlags.ANISOTROPIC
            elif f == "SRGB":
                result |= VTFImageFlags.SRGB
            elif f == "NODEBUGOVERRIDE":
                result |= VTFImageFlags.NODEBUGOVERRIDE
            elif f == "SINGLECOPY":
                result |= VTFImageFlags.SINGLECOPY
            elif f == "NODEPTHBUFFER":
                result |= VTFImageFlags.NODEPTHBUFFER
            elif f == "CLAMPU":
                result |= VTFImageFlags.CLAMPU
            elif f == "VERTEXTEXTURE":
                result |= VTFImageFlags.VERTEXTEXTURE
            elif f == "SSBUMP":
                result |= VTFImageFlags.SSBUMP
            elif f == "BORDER":
                result |= VTFImageFlags.BORDER

        if options and options.get("nomipmaps", False):
            result |= VTFImageFlags.NOMIP | VTFImageFlags.NOLOD

        return result

    @staticmethod
    def create_animated_vtf(
        input_path: str,
        output_file: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        options: dict = None,
    ) -> Optional[int]:
        if options is None:
            options = {}

        frames, fps = TextureService._extract_animation_frames_rgba(input_path, size)
        if not frames:
            raise RuntimeError("No frames extracted")

        if len(frames) > 1 and fps is None:
            fps = 30

        has_alpha = True
        if options.get("normal", False):
            raise RuntimeError("Animated normal maps are not supported")

        dest_format = TextureService._map_format_to_vtflib(format_type, has_alpha=has_alpha)
        vtf_flags = TextureService._map_flags_to_vtflib(flags, options)
        generate_thumbnail = not options.get("nothumbnail", False)

        VTFLib.create_animated_vtf(
            frames_rgba8888=frames,
            width=size[0],
            height=size[1],
            dest_format=dest_format,
            flags=vtf_flags,
            output_file=output_file,
            generate_thumbnail=generate_thumbnail,
        )
        return fps

    @staticmethod
    def parse_vtf_flags_and_options(flags: List[str]) -> Tuple[List[str], dict]:
        if flags is None:
            flags = []
        vtf_flags = []
        options = {}
        for flag in flags:
            flag_upper = flag.upper()
            if flag_upper == "NOMIP":
                options["nomipmaps"] = True
            else:
                vtf_flags.append(flag)
        return vtf_flags, options

    @staticmethod
    def create_vtf(png_path: str, output_path: str, format_type: str, flags: List[str], options: dict = None) -> None:
        if options is None:
            options = {}
        vtf_format = TextureService._FORMAT_ALIASES.get(format_type, format_type)
        has_alpha = False
        try:
            with Image.open(png_path) as img:
                has_alpha = img.mode in ('RGBA', 'LA') or 'transparency' in img.info
        except Exception as e:
            logger.warning(f"Не удалось проверить альфа-канал: {e}")
        logger.info(f"Создание VTF с форматом: {format_type} -> {vtf_format}, альфа-канал: {has_alpha}")
        vtf_args = [
            str(TextureService.get_vtf_tool()),
            "-file", png_path,
            "-output", output_path,
            "-format", vtf_format
        ]
        if has_alpha:
            vtf_args.extend(["-alphaformat", vtf_format])
        if options.get("nomipmaps", False):
            vtf_args.append("-nomipmaps")
        if options.get("nothumbnail", False):
            vtf_args.append("-nothumbnail")
        if options.get("noreflectivity", False):
            vtf_args.append("-noreflectivity")
        if options.get("gamma", False):
            vtf_args.append("-gamma")
            if "gcorrection" in options:
                vtf_args.extend(["-gcorrection", str(options["gcorrection"])])
        if options.get("normal", False):
            vtf_args.append("-normal")
            if "nkernel" in options:
                vtf_args.extend(["-nkernel", str(options["nkernel"])])
            if "nheight" in options:
                vtf_args.extend(["-nheight", str(options["nheight"])])
            if "nalpha" in options:
                vtf_args.extend(["-nalpha", str(options["nalpha"])])
            if "nscale" in options:
                vtf_args.extend(["-nscale", str(options["nscale"])])
            if options.get("nwrap", False):
                vtf_args.append("-nwrap")
        if "bumpscale" in options:
            vtf_args.extend(["-bumpscale", str(options["bumpscale"])])
        flag_mapping = {
            "CLAMPS": "clamps",
            "CLAMPT": "clampt",
            "NOLOD": "nolod",
            "NOMIP": "nomip",
            "NOMINMIP": "minmip",
            "POINTSAMPLE": "pointsample",
            "TRILINEAR": "trilinear",
            "ANISOTROPIC": "anisotropic",
            "SRGB": "srgb",
            "NOCOMPRESS": "nocompress",
            "NODEBUGOVERRIDE": "nodebugoverride",
            "SINGLECOPY": "singlecopy",
            "NODEPTHBUFFER": "nodepthbuffer",
            "CLAMPU": "clampu",
            "VERTEXTEXTURE": "vertextexture",
            "SSBUMP": "ssbump",
            "BORDER": "border"
        }
        for flag in flags:
            if flag.upper() == "NOMIP":
                continue
            if flag in flag_mapping:
                vtf_args.extend(["-flag", flag_mapping[flag]])
            else:
                vtf_args.extend(["-flag", flag.lower()])
        logger.info(f"VTFCmd команда: {' '.join(vtf_args)}")
        logger.info(f"VTFCmd аргументы (список): {vtf_args}")
        logger.info(f"Передаваемый формат: {vtf_format} (исходный: {format_type})")
        logger.info(f"Опции VTFCmd: {options}")
        logger.info(f"Флаги VTF: {flags}")
        result = subprocess.run(vtf_args, check=True, capture_output=True, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get('en', TRANSLATIONS['en'])
            raise RuntimeError(
                t['error_vtf_creation_failed'].format(
                    command=' '.join(vtf_args),
                    stdout=result.stdout,
                    stderr=result.stderr
                )
            )
