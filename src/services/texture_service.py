import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image, ImageOps, ImageFilter
from src.shared.constants import ToolPaths, ToolTimeouts
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
    def derive_effect_map(
        base_image_path: str,
        out_png_path: str,
        kind: str,
        size: Tuple[int, int],
        threshold: Optional[int] = None,
        contrast: bool = True,
    ) -> str:
        """
        Строит карту эффекта ИЗ базовой текстуры (без участия пользователя).

        kind:
          • "phong"     → RGBA: RGB = яркость (карта экспоненты), ALPHA = маска
                          блеска (по яркости / порогу). Светлые линии → острый
                          блик, тёмное → матовое.
          • "selfillum" → L (grayscale): маска свечения по яркости / порогу.

        threshold: 0..255 — если задан, маска бинаризуется по этому порогу
                   (блестит/светится только то, что ярче). None → плавно.
        contrast:  авто-контраст яркости (растягивает динамику).
        """
        img = Image.open(base_image_path).convert("RGB")
        if size:
            img = img.resize(size, Image.LANCZOS)
        gray = ImageOps.grayscale(img)
        if contrast:
            gray = ImageOps.autocontrast(gray)

        def _mask(src):
            if threshold is None:
                return src
            return src.point(lambda p: 255 if p >= threshold else 0)

        if kind == "phong":
            out = Image.merge("RGBA", (gray, gray, gray, _mask(gray)))
        elif kind == "selfillum":
            out = _mask(gray).convert("L")
        elif kind == "envmapmask":
            # Маска отражения кубмапа: светлое/металл (или ярче порога) блестит сильнее.
            out = _mask(gray).convert("L")
        else:
            out = gray
        out.save(out_png_path)
        logger.info(f"Карта '{kind}' выведена из базовой текстуры: {out_png_path}")
        return out_png_path

    @staticmethod
    def make_normal_with_alpha(
        base_image_path: str,
        mask_png_path: str,
        out_png_path: str,
        size: Tuple[int, int],
    ) -> str:
        """
        Строит карту нормалей из базовой текстуры (Sobel по яркости) и кладёт
        в её АЛЬФУ маску из mask_png_path.

        Нужно для сосуществования отражения и эффектов с нормалью: при наличии
        $bumpmap движок игнорирует отдельный $envmapmask и читает маску отражения
        из альфы нормали ($normalmapalphaenvmapmask). Нормаль приближённая (как и
        любая «нормаль из диффуза»), но направление здесь некритично — важна альфа.
        """
        base = Image.open(base_image_path).convert("RGB")
        if size:
            base = base.resize(size, Image.LANCZOS)
        gray = ImageOps.grayscale(base)
        sx = ImageFilter.Kernel((3, 3), (-1, 0, 1, -2, 0, 2, -1, 0, 1), scale=2, offset=128)
        sy = ImageFilter.Kernel((3, 3), (-1, -2, -1, 0, 0, 0, 1, 2, 1), scale=2, offset=128)
        r = gray.filter(sx)                      # наклон по X
        g = gray.filter(sy)                      # наклон по Y
        b = Image.new("L", gray.size, 255)       # Z вверх (приближённо)
        mask = Image.open(mask_png_path).convert("L").resize(gray.size, Image.LANCZOS)
        Image.merge("RGBA", (r, g, b, mask)).save(out_png_path)
        logger.info(f"Нормаль с маской отражения в альфе: {out_png_path}")
        return out_png_path

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
    def resolve_vtf_flags_and_options(
        flags: List[str], vtf_options: dict = None, drop_normal: bool = False
    ) -> Tuple[List[str], dict]:
        """
        Парсит флаги VTF и сливает их с UI-опциями.

        UI-опции применяются первыми, опции из флагов — поверх (могут
        переопределить). drop_normal=True убирает ключ 'normal' — для
        доп./BLU/variant материалов, где normal-map не применяется.

        Returns:
            (vtf_flags, merged_options)
        """
        vtf_flags, flags_parsed = TextureService.parse_vtf_flags_and_options(flags)
        merged = dict(vtf_options) if vtf_options else {}
        merged.update(flags_parsed)
        if drop_normal:
            merged.pop("normal", None)
        return vtf_flags, merged

    @staticmethod
    def render_image_to_vtf(
        image_path: str,
        vtf_output_path: Path,
        out_vtf_path: Path,
        temp_png_path: Path,
        normal_base: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict = None,
    ) -> Tuple[Optional[float], bool]:
        """
        Рендерит изображение в VTF: анимированный / normal-map / обычный.

        Единый рендер главной текстуры для обычной сборки и спец-режимов
        (раньше дублировался в двух местах).

        Args:
            out_vtf_path:   полный путь к итоговому .vtf (для анимированного).
            temp_png_path:  временный PNG для конвертации обычной текстуры.
            normal_base:    стем для файлов normal-map ('{normal_base}_normal.vtf').
            vtf_output_path: директория, куда VTFCmd кладёт .vtf.

        Returns:
            (animated_fps, is_normal_map). animated_fps != None — анимация.
        """
        vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options)
        is_normal_map = merged.get("normal", False)
        animated_fps = None

        if TextureService.is_animated_image(image_path):
            animated_fps = TextureService.create_animated_vtf(
                image_path, str(out_vtf_path), size, format_type, vtf_flags, merged
            )
            logger.info(f"Создана анимированная VTF текстура: {out_vtf_path.name}")
            return animated_fps, is_normal_map

        TextureService.process_image(image_path, temp_png_path, size)
        if is_normal_map:
            normal_options = merged.copy()
            normal_options.pop("normal", None)
            TextureService.create_vtf(str(temp_png_path), str(vtf_output_path), format_type, vtf_flags, normal_options)
            normal_temp_png = vtf_output_path / f"{normal_base}_normal.png"
            shutil.copy2(temp_png_path, normal_temp_png)
            TextureService.create_vtf(str(normal_temp_png), str(vtf_output_path), format_type, [], {"normal": True})
            created_normal_vtf = vtf_output_path / f"{normal_temp_png.stem}.vtf"
            normal_vtf_path = vtf_output_path / f"{normal_base}_normal.vtf"
            if created_normal_vtf.exists():
                created_normal_vtf.rename(normal_vtf_path)
                logger.info(f"Создана normal VTF текстура: {normal_vtf_path.name}")
            else:
                logger.warning(f"Normal VTF файл не был создан: {created_normal_vtf}")
            if normal_temp_png.exists():
                normal_temp_png.unlink()
        else:
            TextureService.create_vtf(str(temp_png_path), str(vtf_output_path), format_type, vtf_flags, merged)

        if Path(temp_png_path).exists():
            Path(temp_png_path).unlink()
        return animated_fps, is_normal_map

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
        logger.debug(f"Формат: {vtf_format} (исходный: {format_type}), опции: {options}, флаги: {flags}")
        # Без check=True: при ненулевом коде формируем информативное исключение
        # с выводом VTFCmd, а не сырой CalledProcessError.
        from src.shared.exceptions import VTFCreationError
        try:
            result = subprocess.run(vtf_args, capture_output=True, text=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    timeout=ToolTimeouts.VTF)
        except subprocess.TimeoutExpired:
            raise VTFCreationError(
                ' '.join(vtf_args), "",
                f"VTFCmd timed out after {ToolTimeouts.VTF}s"
            )
        if result.returncode != 0:
            raise VTFCreationError(' '.join(vtf_args), result.stdout, result.stderr)
