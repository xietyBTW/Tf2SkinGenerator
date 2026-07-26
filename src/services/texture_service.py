import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image, ImageOps, ImageFilter
from src.shared.constants import ToolPaths, ToolTimeouts
from src.shared.exceptions import VTFCreationError
from src.shared.logging_config import get_logger
from src.services.vtflib_wrapper import VTFLib, VTFImageFormat, VTFImageFlags

logger = get_logger(__name__)

# Ядра Sobel для «нормали из яркости». Общие для статичной нормали с маской
# в альфе (make_normal_with_alpha) и для покадровой нормали анимации.
_SOBEL_X = ImageFilter.Kernel((3, 3), (-1, 0, 1, -2, 0, 2, -1, 0, 1), scale=2, offset=128)
_SOBEL_Y = ImageFilter.Kernel((3, 3), (-1, -2, -1, 0, 0, 0, 1, 2, 1), scale=2, offset=128)


class TextureService:
    # Маппинг читаемых имён форматов → внутренние идентификаторы.
    # Используется и VTFLib-путём (_map_format_to_vtflib) и VTFCmd-путём (create_vtf).
    _FORMAT_ALIASES: dict = {
        "RGB888 Bluescreen":    "RGB888_BLUESCREEN",
        "BGR888 Bluescreen":    "BGR888_BLUESCREEN",
        "DXT1 With One Bit Alpha": "DXT1_ONEBITALPHA",
    }

    # UI-имя флага → бит VTFImageFlags (VTFLib-путь). Флаги вне таблицы
    # игнорируются — как и раньше в elif-цепочке.
    _VTFLIB_FLAG_BITS: dict = {
        "CLAMPS": VTFImageFlags.CLAMPS,
        "CLAMPT": VTFImageFlags.CLAMPT,
        "NOMIP": VTFImageFlags.NOMIP,
        "NOLOD": VTFImageFlags.NOLOD,
        # «No Minimum Mipmap» = TEXTUREFLAGS_ALL_MIPS (0x400). Раньше в
        # VTFLib-пути не обрабатывался → галка была пустышкой.
        "NOMINMIP": VTFImageFlags.ALL_MIPS,
        "POINTSAMPLE": VTFImageFlags.POINTSAMPLE,
        "TRILINEAR": VTFImageFlags.TRILINEAR,
        "ANISOTROPIC": VTFImageFlags.ANISOTROPIC,
        "SRGB": VTFImageFlags.SRGB,
        "NODEBUGOVERRIDE": VTFImageFlags.NODEBUGOVERRIDE,
        "SINGLECOPY": VTFImageFlags.SINGLECOPY,
        "NODEPTHBUFFER": VTFImageFlags.NODEPTHBUFFER,
        "CLAMPU": VTFImageFlags.CLAMPU,
        "VERTEXTEXTURE": VTFImageFlags.VERTEXTEXTURE,
        "SSBUMP": VTFImageFlags.SSBUMP,
        "BORDER": VTFImageFlags.BORDER,
    }

    # UI-имя флага → аргумент VTFCmd -flag. Всё, чего нет в таблице,
    # передаётся как flag.lower() (совпадает для остальных флагов).
    _VTFCMD_FLAG_ALIASES: dict = {
        "NOMINMIP": "minmip",
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
        mask = Image.open(mask_png_path).convert("L").resize(gray.size, Image.LANCZOS)
        normal = TextureService._normal_from_gray(gray)
        normal.putalpha(mask)
        normal.save(out_png_path)
        logger.info(f"Нормаль с маской отражения в альфе: {out_png_path}")
        return out_png_path

    @staticmethod
    def _normal_from_gray(gray: "Image.Image") -> "Image.Image":
        """Приближённая карта нормалей из яркости: R=наклон X, G=наклон Y, Z вверх.

        Альфа = 255 (непрозрачная). Тот же приём, что в make_normal_with_alpha —
        нормаль из диффуза, а не из настоящего хайтмапа.
        """
        return Image.merge("RGBA", (
            gray.filter(_SOBEL_X),
            gray.filter(_SOBEL_Y),
            Image.new("L", gray.size, 255),
            Image.new("L", gray.size, 255),
        ))

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
    def _animation_info(input_path: str, max_frames: int = 512) -> Tuple[int, bool]:
        """(сколько кадров берём, есть ли прозрачность) — по метаданным, без декода.

        Альфа определяется по источнику, а не по декодированным кадрам: иначе
        пришлось бы держать их все в памяти ради одного bool.
        """
        with Image.open(input_path) as img:
            n_frames = int(getattr(img, "n_frames", 1))
            has_alpha = ("transparency" in img.info
                         or img.mode in ("RGBA", "LA", "PA"))
        if n_frames > max_frames:
            logger.warning(
                f"Анимация обрезана: {n_frames} кадров → {max_frames} "
                f"({os.path.basename(input_path)})")
        return min(n_frames, max_frames), has_alpha

    @staticmethod
    def _iter_animation_frames_rgba(
        input_path: str,
        size: Tuple[int, int],
        count: int,
        durations_out: list,
        as_normal: bool = False,
    ) -> "object":
        """Отдаёт кадры RGBA по одному (пик памяти — один кадр, не вся гифка).

        Задержки кадров дописываются в durations_out: в VTF частота одна на всю
        анимацию, поэтому fps считается по ним ПОСЛЕ обхода (см. _fps_from_durations).

        as_normal=True — каждый кадр превращается в карту нормалей (Sobel по
        яркости, уже после ресайза — как и в статичном пути через VTFCmd).
        """
        with Image.open(input_path) as img:
            for i in range(count):
                img.seek(i)
                durations_out.append(int(img.info.get("duration", 0) or 0))
                frame = img.convert("RGBA").resize(size, Image.LANCZOS)
                if as_normal:
                    frame = TextureService._normal_from_gray(ImageOps.grayscale(frame))
                yield frame.tobytes()

    @staticmethod
    def _fps_from_durations(durations: list) -> int:
        """Средний fps по задержкам кадров.

        Раньше брался duration ПЕРВОГО кадра — у гифок с переменными задержками
        скорость в игре получалась неверной. Задержка < 20 мс трактуется как
        100 мс: так делают браузеры и так размечена масса гифок в вебе.
        """
        vals = [d if d >= 20 else 100 for d in durations] or [100]
        avg_ms = sum(vals) / len(vals)
        return max(1, min(240, int(round(1000 / avg_ms))))

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
        result = 0
        for flag in flags or []:
            result |= TextureService._VTFLIB_FLAG_BITS.get((flag or "").upper(), 0)

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

        # options["normal"] → на выходе многокадровая КАРТА НОРМАЛЕЙ той же
        # анимации (VTFCmd -normal тут неприменим: он умеет только один кадр).
        as_normal = bool(options.get("normal", False))

        count, has_alpha = TextureService._animation_info(input_path)
        if count < 1:
            raise RuntimeError("No frames extracted")
        if as_normal:
            has_alpha = False   # нормаль строится непрозрачной

        dest_format = TextureService._map_format_to_vtflib(format_type, has_alpha=has_alpha)
        vtf_flags = TextureService._map_flags_to_vtflib(flags, options)
        # Многокадровая VTF создаётся без мип-уровней (vlImageCreate, bMipmaps=0),
        # поэтому движку это надо сообщить флагами — иначе он ждёт мипы, которых нет.
        vtf_flags |= VTFImageFlags.NOMIP | VTFImageFlags.NOLOD
        generate_thumbnail = not options.get("nothumbnail", False)

        durations: list = []
        VTFLib.create_animated_vtf(
            frames_rgba8888=TextureService._iter_animation_frames_rgba(
                input_path, size, count, durations, as_normal=as_normal),
            width=size[0],
            height=size[1],
            dest_format=dest_format,
            flags=vtf_flags,
            output_file=output_file,
            generate_thumbnail=generate_thumbnail,
            frame_count=count,
        )
        return TextureService._fps_from_durations(durations) if count > 1 else None

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
            base_options = merged.copy()
            base_options.pop("normal", None)
            animated_fps = TextureService.create_animated_vtf(
                image_path, str(out_vtf_path), size, format_type, vtf_flags, base_options
            )
            logger.info(f"Создана анимированная VTF текстура: {out_vtf_path.name}")
            # Нормаль включена + анимация → бамп тоже анимированный, из тех же
            # кадров и с тем же fps (VMT анимирует $bumpmap через $bumpframe).
            if is_normal_map:
                normal_vtf_path = vtf_output_path / f"{normal_base}_normal.vtf"
                TextureService.create_animated_vtf(
                    image_path, str(normal_vtf_path), size, format_type, [],
                    {**base_options, "normal": True}
                )
                logger.info(f"Создана анимированная normal VTF: {normal_vtf_path.name}")
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
        for flag in flags:
            name = flag.upper()
            if name == "NOMIP":
                continue
            cmd_flag = TextureService._VTFCMD_FLAG_ALIASES.get(name, flag.lower())
            vtf_args.extend(["-flag", cmd_flag])
        logger.info(f"VTFCmd команда: {' '.join(vtf_args)}")
        logger.debug(f"Формат: {vtf_format} (исходный: {format_type}), опции: {options}, флаги: {flags}")
        # Без check=True: при ненулевом коде формируем информативное исключение
        # с выводом VTFCmd, а не сырой CalledProcessError.
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
