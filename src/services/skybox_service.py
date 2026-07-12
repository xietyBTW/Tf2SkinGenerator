"""
Сервис скайбокс-модов: перечисление стоковых небес, нарезка панорамы на грани,
сборка VPK (materials/skybox/*).

Сборка не требует TF2 (как спец-режимы): пишутся только материалы. Папка игры
нужна лишь для расширенного списка небес и стоковых граней в превью.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.data.skyboxes import SKY_FACES, STOCK_SKY_NAMES
from src.services.vpk_cache import open_vpk_cached
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Форматы без альфы, осмысленные для граней неба (DXT1 — сжатый дефолт,
# BGR888 — без потерь для градиентов, где DXT даёт полосы).
SKYBOX_ALLOWED_FORMATS = ("DXT1", "BGR888")

# Шаблон VMT грани: стоковый минимум (шейдер sky + $nofog/$ignorez), как в
# оригинальных материалах TF2. И LDR-, и _hdr-вариант пишутся с одинаковым
# содержимым: в HDR движок предпочитает материалы <sky>_hdr<грань>, и без
# нашего override HDR-клиенты продолжали бы видеть стоковое небо.
_SKY_VMT_TEMPLATE = (
    '"sky"\n'
    '{{\n'
    '\t"$basetexture" "skybox/{stem}{face}"\n'
    '\t"$nofog" "1"\n'
    '\t"$ignorez" "1"\n'
    '}}\n'
)

# Префикс материалов неба внутри VPK (ключи vpk — lowercase, прямые слеши).
_SKYBOX_VPK_PREFIX = "materials/skybox/"

# Кэш результата enumerate_sky_names по корню TF2: первый вызов парсит индекс
# tf2_misc_dir.vpk (дорого), а список небес меняется только с обновлением игры.
_sky_names_cache: Dict[str, List[str]] = {}

# Базисы граней (forward, right, up) в Source-координатах (Z — верх).
# Согласованы с калиброванным SRC_FACE_MAP в viewer3d.html (менять ТОЛЬКО
# вместе): грани хранятся «как фото» (без зеркала), цепочка горизонта при
# повороте вправо — ft → lf → bk → rt; низ картинки up примыкает к rt,
# верх картинки dn — тоже к rt. Пиксель (u, v) грани (u вправо, v вверх,
# оба в [-1..1]) смотрит в направлении forward + u·right + v·up.
FACE_BASES: Dict[str, Tuple[Tuple[float, float, float], ...]] = {
    "ft": ((1, 0, 0), (0, -1, 0), (0, 0, 1)),
    "lf": ((0, -1, 0), (-1, 0, 0), (0, 0, 1)),
    "bk": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "rt": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "up": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "dn": ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
}


class SkyboxService:
    @staticmethod
    def enumerate_sky_names(tf2_root_dir: str) -> List[str]:
        """
        Список имён стоковых небес: STOCK_SKY_NAMES ∪ скан установленной игры.

        Скан: ключи tf2_misc_dir.vpk вида materials/skybox/<имя>up.vmt
        (грань «up» есть у каждого неба, одного суффикса достаточно);
        HDR-варианты (<имя>_hdr) — это то же небо, отбрасываем. Любая проблема
        (нет папки/vpk/библиотеки) — молча возвращаем фолбэк: список небес не
        критичен для работы. Вызов из UI-потока — принятый компромисс: первый
        вызов платит парсинг индекса VPK, дальше результат кэшируется.
        """
        cached = _sky_names_cache.get(tf2_root_dir)
        if cached is not None:
            return cached
        names = set(STOCK_SKY_NAMES)
        try:
            misc_vpk = os.path.join(tf2_root_dir, "tf", "tf2_misc_dir.vpk")
            if tf2_root_dir and os.path.exists(misc_vpk):
                pak = open_vpk_cached(misc_vpk)
                if pak is not None:
                    names |= SkyboxService._scan_sky_names(pak)
        except Exception as e:
            logger.warning(f"Скан небес из VPK не удался, фолбэк-список: {e}")
        result = sorted(names)
        _sky_names_cache[tf2_root_dir] = result
        return result

    @staticmethod
    def split_equirect_to_faces(equirect_path: str, face_size: int,
                                out_dir: str,
                                cancel_callback=None) -> Dict[str, str]:
        """
        Режет equirectangular-панораму (2:1, как фото 360°) на 6 квадратных
        граней Source-скайбокса. Возвращает {грань: путь к PNG} (неполный,
        если cancel_callback вернул True между гранями).

        Центр панорамы попадает в центр грани ft; движение вправо по панораме —
        поворот вправо (ft → lf → bk → rt, калиброванная цепочка). Билинейная
        выборка с заворотом по долготе (шов панорамы) и зажимом по широте
        (полюса). numpy импортируется лениво — нужен только этой функции.
        """
        import numpy as np
        from PIL import Image

        os.makedirs(out_dir, exist_ok=True)
        src = np.asarray(Image.open(equirect_path).convert("RGB"), dtype=np.float32)
        h, w = src.shape[:2]

        # Центры пикселей грани: u вправо, v вверх, оба в [-1..1].
        a = (np.arange(face_size, dtype=np.float32) + 0.5) / face_size * 2.0 - 1.0
        vv, uu = np.meshgrid(-a, a, indexing="ij")   # строка 0 = верх (v=+1)

        result: Dict[str, str] = {}
        for face in SKY_FACES:
            if cancel_callback and cancel_callback():
                return result
            fwd, right, up = (np.asarray(b, dtype=np.float32)
                              for b in FACE_BASES[face])
            d = (fwd[None, None, :]
                 + uu[..., None] * right[None, None, :]
                 + vv[..., None] * up[None, None, :])
            d /= np.linalg.norm(d, axis=-1, keepdims=True)

            lon = np.arctan2(d[..., 1], d[..., 0])          # +Y = влево от ft
            lat = np.arcsin(np.clip(d[..., 2], -1.0, 1.0))
            # Вправо по панораме — поворот вправо (убывание lon от центра +X).
            xf = (0.5 - lon / (2.0 * np.pi)) * w - 0.5
            yf = (0.5 - lat / np.pi) * h - 0.5

            x0 = np.floor(xf).astype(np.int64)
            y0 = np.floor(yf).astype(np.int64)
            tx = (xf - x0)[..., None]
            ty = (yf - y0)[..., None]
            x0 %= w
            x1 = (x0 + 1) % w                                # шов — заворот
            # Полюса — зажим; y1 от НЕзажатого y0, иначе у верхнего полюса
            # (y0 = -1) подмешивалась бы строка 1 вместо повтора строки 0.
            y1 = np.clip(y0 + 1, 0, h - 1)
            y0 = np.clip(y0, 0, h - 1)

            top = src[y0, x0] * (1 - tx) + src[y0, x1] * tx
            bot = src[y1, x0] * (1 - tx) + src[y1, x1] * tx
            out = (top * (1 - ty) + bot * ty).round().astype(np.uint8)

            path = os.path.join(out_dir, f"{face}.png")
            Image.fromarray(out).save(path)
            result[face] = path
        return result

    # ═══════════════════════════════════════════════════════════════════════ #
    # Сборка VPK
    # ═══════════════════════════════════════════════════════════════════════ #

    @staticmethod
    def validate_skybox_request(request, t: dict) -> Optional[str]:
        """Проверяет параметры скайбокс-сборки. Текст ошибки или None (всё ок).

        TF2 не требуется: мод — только материалы. Вход: панорама (image_path)
        И/ИЛИ ручные грани; без панорамы нужны все 6 граней."""
        if not request.filename or not request.filename.lower().endswith('.vpk'):
            return t.get('filename_must_be_vpk', 'Filename must end with .vpk')
        if not request.skybox_sky_names:
            return t.get('error_skybox_no_sky', 'No sky selected to replace.')
        overrides = request.skybox_face_overrides or {}
        has_pano = bool(request.image_path and os.path.isfile(request.image_path))
        overrides_ok = all(
            face in overrides and os.path.isfile(overrides[face])
            for face in SKY_FACES
        )
        if not has_pano and not overrides_ok:
            return t.get('error_skybox_no_input',
                         'Load a panorama or all 6 face textures.')
        size = request.size
        if (not isinstance(size, (tuple, list)) or len(size) != 2
                or int(size[0]) <= 0):
            return t.get('invalid_size', 'Invalid texture size.')
        return None

    @staticmethod
    def build_skybox_vpk(request, *, sub_progress_callback=None,
                         cancel_callback=None) -> Tuple[bool, str]:
        """
        Собирает VPK скайбокс-мода.

        6 VTF пишутся ОДИН раз (materials/skybox/<стем><грань>.vtf, стем — из
        имени файла мода), а на каждое выбранное небо — 12 VMT (<небо><грань>
        + <небо>_hdr<грань>), ссылающихся на общие VTF: мод на «Все карты»
        остаётся лёгким. Флаги VTF принудительные (CLAMPS/CLAMPT/NOLOD +
        nomipmaps): без них на стыках граней видны швы.
        """
        from src.data.translations import TRANSLATIONS
        from src.services.build_context import BuildContext
        from src.services.packaging_service import PackagingService
        from src.services.texture_service import TextureService
        from src.shared.file_utils import copy_file_safe, ensure_directory_exists

        t = TRANSLATIONS.get(request.language, TRANSLATIONS['en'])

        error = SkyboxService.validate_skybox_request(request, t)
        if error:
            return False, error

        def cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

        def sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        ctx = None
        try:
            ctx = BuildContext.create("skybox", "skybox",
                                      debug_mode=request.debug_mode)
            sky_dir = ctx.vpkroot_dir / "materials" / "skybox"
            ensure_directory_exists(sky_dir)

            stem = SkyboxService._vtf_stem(request.filename)
            face_size = int(request.size[0])
            format_type = (request.format_type
                           if request.format_type in SKYBOX_ALLOWED_FORMATS
                           else "DXT1")

            # ── Источники граней: нарезка панорамы + ручные оверрайды ────── #
            sources: Dict[str, str] = {}
            if request.image_path and os.path.isfile(request.image_path):
                sub(-1, t.get('build_skybox_split', 'Splitting panorama...'))
                sources = SkyboxService.split_equirect_to_faces(
                    request.image_path, face_size,
                    str(ctx.temp_dir / "sky_faces"),
                    cancel_callback=cancel_callback)
                if cancelled():
                    ctx.cleanup(on_error=True,
                                keep_on_error=request.keep_temp_on_error,
                                debug_mode=request.debug_mode)
                    return False, t.get('build_cancelled',
                                        'Build cancelled by user')
            for face, path in (request.skybox_face_overrides or {}).items():
                if face in SKY_FACES and path and os.path.isfile(path):
                    sources[face] = path
            missing = [f for f in SKY_FACES if f not in sources]
            if missing:
                ctx.cleanup(on_error=True,
                            keep_on_error=request.keep_temp_on_error,
                            debug_mode=request.debug_mode)
                return False, t.get('error_skybox_no_input',
                                    'Load a panorama or all 6 face textures.')

            # ── 6 VTF (общие для всех небес) ──────────────────────────────── #
            for i, face in enumerate(SKY_FACES):
                if cancelled():
                    ctx.cleanup(on_error=True,
                                keep_on_error=request.keep_temp_on_error,
                                debug_mode=request.debug_mode)
                    return False, t.get('build_cancelled', 'Build cancelled by user')
                sub(int(i / len(SKY_FACES) * 70),
                    t.get('build_skybox_faces', 'Building sky faces...'))
                src = sources[face]
                if src.lower().endswith('.vtf'):
                    # Готовый VTF пользователя — как есть (флаги/формат его).
                    copy_file_safe(src, sky_dir / f"{stem}{face}.vtf")
                    continue
                png = sky_dir / f"{stem}{face}.png"
                SkyboxService._normalize_face_to_square(
                    src, str(png), face_size, face=face)
                TextureService.create_vtf(
                    str(png), str(sky_dir), format_type,
                    ["CLAMPS", "CLAMPT", "NOLOD"],
                    {"nomipmaps": True, "nothumbnail": True},
                )
                if png.exists():
                    png.unlink()

            # ── VMT на каждое небо × грань (LDR + HDR) ────────────────────── #
            sub(80, t.get('build_skybox_vmts', 'Writing sky materials...'))
            for sky in request.skybox_sky_names:
                for face in SKY_FACES:
                    content = _SKY_VMT_TEMPLATE.format(stem=stem, face=face)
                    for name in (f"{sky}{face}.vmt", f"{sky}_hdr{face}.vmt"):
                        with open(sky_dir / name, 'w', encoding='utf-8') as f:
                            f.write(content)
            logger.info(
                f"[SKYBOX] {len(SKY_FACES)} VTF ({stem}*) + "
                f"{len(request.skybox_sky_names) * len(SKY_FACES) * 2} VMT "
                f"({len(request.skybox_sky_names)} небес)")

            sub(90, t.get('build_packaging', 'Packaging VPK...'))
            vpk_path = PackagingService.create_vpk_file(
                ctx, request.filename, request.export_folder, request.language)
            ctx.cleanup(on_error=False,
                        keep_on_error=request.keep_temp_on_error,
                        debug_mode=request.debug_mode)
            logger.info(f"[SKYBOX] VPK готов: {vpk_path}")
            return True, vpk_path
        except Exception as exc:
            logger.error(f"build_skybox_vpk: {exc}", exc_info=True)
            if ctx:
                ctx.cleanup(on_error=True,
                            keep_on_error=request.keep_temp_on_error,
                            debug_mode=request.debug_mode)
            return False, str(exc)

    @staticmethod
    def _vtf_stem(filename: str) -> str:
        """Стем общих VTF из имени VPK-файла (lowercase, [a-z0-9_])."""
        stem = re.sub(r'[^a-z0-9_]', '_', Path(filename).stem.lower()).strip('_')
        return stem or "customsky"

    @staticmethod
    def _normalize_face_to_square(src_path: str, out_png: str, size: int,
                                  face: str = "ft") -> None:
        """Готовит грань к записи в VTF: квадрат size×size.

        Картинки 2:1 (половинная высота, как боковые грани стоковых небес)
        движок кладёт на верхнюю половину грани — сохраняем это поведение,
        разворачивая их в квадрат тем же способом (верхняя половина + низ из
        растянутой нижней строки), чтобы вид в игре не менялся. Правило —
        только для боковых граней: up/dn в Source всегда квадратные."""
        from PIL import Image
        is_side = face not in ("up", "dn")
        with Image.open(src_path) as im:
            im = im.convert("RGB")
            if is_side and im.width >= im.height * 2:
                out = Image.new("RGB", (size, size))
                out.paste(im.resize((size, size // 2), Image.LANCZOS), (0, 0))
                bottom = im.crop((0, im.height - 1, im.width, im.height))
                out.paste(bottom.resize((size, size - size // 2)), (0, size // 2))
            else:
                out = im.resize((size, size), Image.LANCZOS)
            out.save(out_png)

    @staticmethod
    def _scan_sky_names(pak) -> Set[str]:
        """Имена небес из итерируемого vpk-объекта (выделено для тестов)."""
        found = set()
        suffix = "up.vmt"
        for key in pak:
            k = key.replace("\\", "/").lower()
            if not (k.startswith(_SKYBOX_VPK_PREFIX) and k.endswith(suffix)):
                continue
            name = k[len(_SKYBOX_VPK_PREFIX):-len(suffix)]
            if name and not name.endswith("_hdr") and "/" not in name:
                found.add(name)
        return found
