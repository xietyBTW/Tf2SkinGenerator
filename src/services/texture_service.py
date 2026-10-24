import os
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image, ImageOps
from src.shared.exceptions import VTFCreationError
from src.shared.logging_config import get_logger
from src.services import vtf_writer
from src.services.vtflib_wrapper import VTFLib, VTFImageFormat, VTFImageFlags

logger = get_logger(__name__)



def _normal_settings(options):
    from src.services.normal_map import NormalSettings
    return NormalSettings.from_options(options)


class TextureService:
    # Маппинг читаемых имён форматов -> внутренние идентификаторы.
    # Используется и анимацией (_map_format_to_vtflib), и create_vtf
    _FORMAT_ALIASES: dict = {
        "RGB888 Bluescreen":    "RGB888_BLUESCREEN",
        "BGR888 Bluescreen":    "BGR888_BLUESCREEN",
        "DXT1 With One Bit Alpha": "DXT1_ONEBITALPHA",
    }

    # UI-имя флага -> бит VTFImageFlags (VTFLib-путь). Флаги вне таблицы
    # игнорируются
    _VTFLIB_FLAG_BITS: dict = {
        "CLAMPS": VTFImageFlags.CLAMPS,
        "CLAMPT": VTFImageFlags.CLAMPT,
        "NOMIP": VTFImageFlags.NOMIP,
        "NOLOD": VTFImageFlags.NOLOD,
        # «No Minimum Mipmap» = TEXTUREFLAGS_ALL_MIPS (0x400)
        "NOMINMIP": VTFImageFlags.ALL_MIPS,
        "POINTSAMPLE": VTFImageFlags.POINTSAMPLE,
        "TRILINEAR": VTFImageFlags.TRILINEAR,
        "ANISOTROPIC": VTFImageFlags.ANISOTROPIC,
        "SRGB": VTFImageFlags.SRGB,
        # Нормаль: без флага VTFLib-путь (анимация) писал её как цвет
        "NORMAL": VTFImageFlags.NORMAL,
        "NODEBUGOVERRIDE": VTFImageFlags.NODEBUGOVERRIDE,
        "SINGLECOPY": VTFImageFlags.SINGLECOPY,
        "NODEPTHBUFFER": VTFImageFlags.NODEPTHBUFFER,
        "CLAMPU": VTFImageFlags.CLAMPU,
        "VERTEXTEXTURE": VTFImageFlags.VERTEXTEXTURE,
        "SSBUMP": VTFImageFlags.SSBUMP,
        "BORDER": VTFImageFlags.BORDER,
    }

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
        Строит карту эффекта ИЗ базовой текстуры (без участия пользователя)

        kind:
          • "phong"     -> RGBA: RGB = яркость (карта экспоненты: светлое -> острый
                          блик), ALPHA = 255 (маска rim light). Маска блеска -
                          в альфе нормали, не здесь.
          • "selfillum" -> L (grayscale): маска свечения по яркости / порогу

        threshold: 0..255 - если задан, маска бинаризуется по этому порогу
                   (блестит/светится только то, что ярче). None -> плавно.
        contrast:  авто-контраст яркости (растягивает динамику)
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
            # $phongexponenttexture (вики Valve): R - размер блика, G - маска
            # $phongalbedotint, A - маска rim light ($rimmask). ГДЕ блестит -
            # не здесь, а в альфе нормали (её кладёт сборка). Альфа 255 -
            # обводка не обрезается
            full = Image.new("L", gray.size, 255)
            out = Image.merge("RGBA", (gray, gray, gray, full))
        elif kind == "selfillum":
            out = _mask(gray).convert("L")
        elif kind == "envmapmask":
            # Маска отражения кубмапа: светлое/металл (или ярче порога) блестит сильнее
            out = _mask(gray).convert("L")
        else:
            out = gray
        out.save(out_png_path)
        logger.info(f"Карта '{kind}' выведена из базовой текстуры: {out_png_path}")
        return out_png_path

    @staticmethod
    def write_normal_vtf(image_path, vtf_output_path: Path, normal_base: str,
                         format_type: str, options: Optional[dict] = None,
                         stock_normal=None) -> Optional[Path]:
        """{normal_base}_normal.vtf из картинки (normal_map) - путь или None

        Флаг NORMAL - как у нормалей Valve: движок не трактует её как цвет.
        Формат свой (DXT5/без потерь), а не как у базы
        """
        from src.services import normal_map

        png = Path(vtf_output_path) / f"{normal_base}_normal.png"
        try:
            TextureService.write_normal_png(image_path, png, _normal_settings(options),
                                            stock_normal)
            TextureService.create_vtf(str(png), str(vtf_output_path),
                                      normal_map.vtf_format(format_type), ["NORMAL"], {})
        finally:
            if png.exists():
                png.unlink()
        out = Path(vtf_output_path) / f"{normal_base}_normal.vtf"
        if out.exists():
            logger.info(f"Создана normal VTF текстура: {out.name}")
            return out
        logger.warning(f"Normal VTF файл не был создан: {out}")
        return None

    @staticmethod
    def write_normal_png(image_path, out_png_path, settings=None, stock_normal=None) -> str:
        """Карта нормалей картинки в PNG (normal_map) - для сборки и авто-нормали"""
        import numpy as np
        from src.services import normal_map

        with Image.open(image_path) as src:
            rgb = np.asarray(src.convert("RGB"))
        rgba = normal_map.make(rgb, settings or normal_map.NormalSettings(), stock_normal)
        Image.fromarray(rgba, "RGBA").save(str(out_png_path))
        return str(out_png_path)

    @staticmethod
    def process_image(input_path: str, output_path: str, size: Tuple[int, int]) -> None:
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Изображение не найдено: {input_path}")
        with Image.open(input_path) as src:
            has_alpha = src.mode in ('RGBA', 'LA') or 'transparency' in src.info
            mode = "RGBA" if has_alpha else "RGB"
            img = src.convert(mode).resize(size)
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
        """(сколько кадров берём, есть ли прозрачность) - по метаданным, без декода

        Альфа определяется по источнику, а не по декодированным кадрам: иначе
        пришлось бы держать их все в памяти ради одного bool
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
        normal_settings=None,
        stock_normal=None,
    ) -> "object":
        """Отдаёт кадры RGBA по одному (пик памяти - один кадр, не вся гифка)

        Задержки кадров дописываются в durations_out: в VTF частота одна на всю
        анимацию, поэтому fps считается по ним ПОСЛЕ обхода (см. _fps_from_durations)

        as_normal=True - каждый кадр превращается в карту нормалей (normal_map,
        уже после ресайза - как и в статичном пути)
        """
        import numpy as np
        from src.services import normal_map

        settings = normal_settings or normal_map.NormalSettings()
        if as_normal and stock_normal is not None:
            # Родная нормаль к размеру кадра - один раз, а не на каждом кадре
            stock_normal = np.asarray(Image.fromarray(stock_normal, "RGBA").resize(
                tuple(size), Image.BILINEAR))
        with Image.open(input_path) as img:
            for i in range(count):
                img.seek(i)
                durations_out.append(int(img.info.get("duration", 0) or 0))
                frame = img.convert("RGBA").resize(size, Image.LANCZOS)
                if as_normal:
                    frame = Image.fromarray(normal_map.make(
                        np.asarray(frame), settings, stock_normal), "RGBA")
                yield frame.tobytes()

    @staticmethod
    def _fps_from_durations(durations: list) -> int:
        """Средний fps по задержкам кадров

        Не по первому кадру: у гифок с переменными задержками скорость в игре
        вышла бы неверной. Задержка < 20 мс трактуется как
        100 мс: так делают браузеры и так размечена масса гифок в вебе
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
        stock_normal=None,
    ) -> Optional[int]:
        if options is None:
            options = {}

        # options["normal"] -> на выходе многокадровая КАРТА НОРМАЛЕЙ той же
        # анимации
        as_normal = bool(options.get("normal", False))

        count, has_alpha = TextureService._animation_info(input_path)
        if count < 1:
            raise RuntimeError("No frames extracted")
        if as_normal:
            # Альфа нормали - маска блеска родной нормали, если она есть
            has_alpha = stock_normal is not None

        dest_format = TextureService._map_format_to_vtflib(format_type, has_alpha=has_alpha)
        vtf_flags = TextureService._map_flags_to_vtflib(flags, options)
        # Многокадровая VTF создаётся без мип-уровней (vlImageCreate, bMipmaps=0),
        # поэтому движку это надо сообщить флагами - иначе он ждёт мипы, которых нет
        vtf_flags |= VTFImageFlags.NOMIP | VTFImageFlags.NOLOD
        generate_thumbnail = not options.get("nothumbnail", False)

        durations: list = []
        VTFLib.create_animated_vtf(
            frames_rgba8888=TextureService._iter_animation_frames_rgba(
                input_path, size, count, durations, as_normal=as_normal,
                normal_settings=_normal_settings(options) if as_normal else None,
                stock_normal=stock_normal),
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
        Парсит флаги VTF и сливает их с UI-опциями

        UI-опции применяются первыми, опции из флагов - поверх (могут
        переопределить). drop_normal=True убирает ключ 'normal' - для
        доп./BLU/variant материалов, где normal-map не применяется

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
        stock_normal=None,
        jobs=None,
    ) -> Tuple[Optional[float], bool]:
        """
        Рендерит изображение в VTF: анимированный / normal-map / обычный

        ``stock_normal`` - родная нормаль материала (RGBA): рельеф картинки
        ляжет поверх неё, её альфа (маска блеска) сохранится

        Единый рендер главной текстуры для обычной сборки и спец-режимов

        Args:
            out_vtf_path:   полный путь к итоговому .vtf (для анимированного).
            temp_png_path:  временный PNG для конвертации обычной текстуры.
            normal_base:    стем для файлов normal-map ('{normal_base}_normal.vtf').
            vtf_output_path: директория, куда ложится .vtf.
            jobs:           VtfJobs - сжать в фоне (кроме анимации)

        Returns:
            (animated_fps, is_normal_map). animated_fps != None - анимация
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
            # Нормаль включена + анимация -> бамп тоже анимированный, из тех же
            # кадров и с тем же fps (VMT анимирует $bumpmap через $bumpframe)
            if is_normal_map:
                normal_vtf_path = vtf_output_path / f"{normal_base}_normal.vtf"
                from src.services import normal_map
                TextureService.create_animated_vtf(
                    image_path, str(normal_vtf_path), size,
                    normal_map.vtf_format(format_type), ["NORMAL"],
                    {**merged, "normal": True}, stock_normal=stock_normal,
                )
                logger.info(f"Создана анимированная normal VTF: {normal_vtf_path.name}")
            return animated_fps, is_normal_map

        args = (image_path, vtf_output_path, temp_png_path, normal_base, size,
                format_type, vtf_flags, merged, is_normal_map, stock_normal)
        if jobs is not None:
            jobs.submit(TextureService.image_to_vtf, *args, key=str(temp_png_path))
        else:
            TextureService.image_to_vtf(*args)
        return animated_fps, is_normal_map

    @staticmethod
    def image_to_vtf(image_path, vtf_output_path, temp_png_path, normal_base: str,
                     size, format_type: str, vtf_flags: List[str], merged: dict,
                     is_normal_map: bool = False, stock_normal=None) -> None:
        """Картинка -> временный PNG -> VTF (и {normal_base}_normal.vtf)"""
        TextureService.process_image(image_path, temp_png_path, size)
        if is_normal_map:
            normal_options = merged.copy()
            normal_options.pop("normal", None)
            # Нормаль жмётся одновременно с базой
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as ex:
                normal = ex.submit(TextureService.write_normal_vtf, temp_png_path,
                                   vtf_output_path, normal_base, format_type,
                                   merged, stock_normal)
                TextureService.create_vtf(str(temp_png_path), str(vtf_output_path),
                                          format_type, vtf_flags, normal_options)
                normal.result()
        else:
            TextureService.create_vtf(str(temp_png_path), str(vtf_output_path), format_type, vtf_flags, merged)

        if Path(temp_png_path).exists():
            Path(temp_png_path).unlink()

    @staticmethod
    def _gamma_value(options: dict) -> float:
        """Гамма из текстового поля: «2,2» с русской раскладки тоже число,
        пустое или неверное - 2.0, как по умолчанию"""
        raw = str(options.get("gcorrection", "")).strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            return 2.0
        return value if value > 0 else 2.0

    @staticmethod
    def create_vtf(png_path: str, output_path: str, format_type: str, flags: List[str], options: dict = None) -> None:
        """PNG -> {output_path}/{имя PNG}.vtf. Опция normal здесь не действует:
        карту нормалей строит normal_map, все вызовы её отбрасывают"""
        if options is None:
            options = {}
        vtf_format = TextureService._FORMAT_ALIASES.get(format_type, format_type).upper()
        out_file = Path(output_path) / f"{Path(png_path).stem}.vtf"
        gamma = TextureService._gamma_value(options) if options.get("gamma") else None
        logger.info(f"Создание VTF {out_file.name}: {vtf_format}, флаги {flags}, опции {options}")
        try:
            with Image.open(png_path) as img:
                vtf_writer.write_vtf(
                    img, out_file, vtf_format,
                    TextureService._map_flags_to_vtflib(flags, options),
                    mipmaps=not options.get("nomipmaps", False),
                    thumbnail=not options.get("nothumbnail", False),
                    with_reflectivity=not options.get("noreflectivity", False),
                    gamma=gamma,
                    bump_scale=float(options.get("bumpscale", 1.0)))
        except Exception as e:
            raise VTFCreationError(f"{png_path} -> {out_file.name} ({vtf_format})", stderr=str(e)) from e
