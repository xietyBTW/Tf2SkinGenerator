import os
import subprocess
from pathlib import Path
from typing import List, Tuple
from PIL import Image
from src.shared.constants import ToolPaths
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class TextureService:
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
        format_mapping = {
            "RGB888 Bluescreen": "RGB888_BLUESCREEN",
            "BGR888 Bluescreen": "BGR888_BLUESCREEN",
            "DXT1 With One Bit Alpha": "DXT1_ONEBITALPHA"
        }
        vtf_format = format_mapping.get(format_type, format_type)
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
        result = subprocess.run(vtf_args, check=True, capture_output=True, text=True)
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
