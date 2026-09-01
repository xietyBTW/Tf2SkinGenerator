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
# Список допустимых форматов — правило, живёт в домене.
from src.domain.format_choices import SKYBOX_ALLOWED_FORMATS  # noqa: F401 — реэкспорт

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

# Шаблон VMT АНИМИРОВАННОЙ грани. Шейдер sky не обрабатывает material-прокси,
# поэтому для анимации переключаемся на UnlitGeneric + прокси AnimatedTexture
# (проверенный рецепт TF2-сообщества). $hdrbasetexture указывает на тот же VTF —
# иначе HDR-клиенты видят стоковое небо/неверный цвет. Пишется ТОЛЬКО для граней,
# чьё исходное изображение реально анимировано (у статичных остаётся шейдер sky).
_SKY_VMT_ANIMATED_TEMPLATE = (
    '"UnlitGeneric"\n'
    '{{\n'
    '\t"$basetexture" "skybox/{stem}{face}"\n'
    '\t"$hdrbasetexture" "skybox/{stem}{face}"\n'
    '\t"$nofog" "1"\n'
    '\t"$ignorez" "1"\n'
    '\t"Proxies"\n'
    '\t{{\n'
    '\t\t"AnimatedTexture"\n'
    '\t\t{{\n'
    '\t\t\t"animatedTextureVar" "$basetexture"\n'
    '\t\t\t"animatedTextureFrameNumVar" "$frame"\n'
    '\t\t\t"animatedTextureFrameRate" "{fps}"\n'
    '\t\t}}\n'
    '\t}}\n'
    '}}\n'
)

# Статичная грань, но на шейдере UnlitGeneric (без прокси). Нужна, когда в
# скайбоксе есть хоть одна анимированная грань: весь куб рендерится одним
# шейдером, иначе на стыке статичной sky-грани и анимированной UnlitGeneric-грани
# возможна разница в тоне. Анимационных параметров тут нет — только базовый
# материал (требование «у статичной грани ничего анимационного не добавляем»).
_SKY_VMT_UNLIT_STATIC_TEMPLATE = (
    '"UnlitGeneric"\n'
    '{{\n'
    '\t"$basetexture" "skybox/{stem}{face}"\n'
    '\t"$hdrbasetexture" "skybox/{stem}{face}"\n'
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
    def _face_sample_map(face: str, w: int, h: int, face_size: int):
        """Координаты билинейной выборки грани из equirect-панорамы w×h.

        Зависят ТОЛЬКО от геометрии грани и размеров панорамы (не от пикселей) —
        поэтому для анимации считаются один раз и переиспользуются на всех кадрах.
        Центр панорамы → центр грани ft; вправо по панораме = поворот вправо
        (ft → lf → bk → rt). Заворот по долготе (шов), зажим по широте (полюса).
        Возвращает (y0, x0, y1, x1, tx, ty). numpy лениво — нужен только здесь.
        """
        import numpy as np
        # Центры пикселей грани: u вправо, v вверх, оба в [-1..1].
        a = (np.arange(face_size, dtype=np.float32) + 0.5) / face_size * 2.0 - 1.0
        vv, uu = np.meshgrid(-a, a, indexing="ij")   # строка 0 = верх (v=+1)
        fwd, right, up = (np.asarray(b, dtype=np.float32) for b in FACE_BASES[face])
        d = (fwd[None, None, :]
             + uu[..., None] * right[None, None, :]
             + vv[..., None] * up[None, None, :])
        d /= np.linalg.norm(d, axis=-1, keepdims=True)

        lon = np.arctan2(d[..., 1], d[..., 0])          # +Y = влево от ft
        lat = np.arcsin(np.clip(d[..., 2], -1.0, 1.0))
        # Вправо по панораме — поворот вправо (убывание lon от центра +X).
        xf = (0.5 - lon / (2.0 * np.pi)) * w - 0.5
        yf = (0.5 - lat / np.pi) * h - 0.5

        # int32, не int64: карта выборки — самый крупный массив в нарезке
        # (на сетке 2048² это 64 МиБ против 128 на каждый из четырёх индексов).
        x0 = np.floor(xf).astype(np.int32)
        y0 = np.floor(yf).astype(np.int32)
        # Явный float32: float32 - int32 numpy повышает до float64, и тогда ВСЯ
        # последующая выборка считалась бы в двойной точности (вдвое памяти
        # и времени на ровном месте).
        tx = (xf - x0.astype(np.float32))[..., None]
        ty = (yf - y0.astype(np.float32))[..., None]
        x0 %= w
        x1 = (x0 + 1) % w                                # шов — заворот
        # Полюса — зажим; y1 от НЕзажатого y0, иначе у верхнего полюса
        # (y0 = -1) подмешивалась бы строка 1 вместо повтора строки 0.
        y1 = np.clip(y0 + 1, 0, h - 1)
        y0 = np.clip(y0, 0, h - 1)
        return y0, x0, y1, x1, tx, ty

    @staticmethod
    def _gather_face(src, sample_map):
        """Билинейно собирает грань из RGB-массива src по готовым координатам.

        Возвращает float32 в единицах src (БЕЗ округления в uint8): выборка идёт
        в линейном свете, где значения лежат в 0..1 и округление до целых
        обнулило бы почти всю картинку.
        """
        y0, x0, y1, x1, tx, ty = sample_map
        top = src[y0, x0] * (1 - tx) + src[y0, x1] * tx
        bot = src[y1, x0] * (1 - tx) + src[y1, x1] * tx
        return top * (1 - ty) + bot * ty

    @staticmethod
    def _srgb_to_linear(img_u8):
        """uint8 sRGB → float32 в линейном свете (через таблицу на 256 значений).

        Смешивать яркости надо линейно: усреднение sRGB-значений гасит мелкие
        яркие детали. Звезда 255 рядом с чёрным небом при усреднении 4 отсчётов
        даёт в sRGB ~64, а физически верно ~140 — именно поэтому звёзды и
        «пропадали» при нарезке.
        """
        import numpy as np
        lut = getattr(SkyboxService, "_SRGB_LUT", None)
        if lut is None:
            lut = (np.arange(256, dtype=np.float32) / 255.0) ** 2.2
            SkyboxService._SRGB_LUT = lut
        return lut[img_u8]

    @staticmethod
    def _linear_to_srgb_u8(arr):
        """float32 в линейном свете → uint8 sRGB."""
        import numpy as np
        return (np.clip(arr, 0.0, 1.0) ** (1 / 2.2) * 255.0).round().astype(np.uint8)

    @staticmethod
    def _downsample_box(arr, factor: int):
        """Усредняет блоки factor×factor (точная площадная фильтрация).

        Кратный делитель → box-фильтр здесь корректнее LANCZOS: тот на уже
        суперсэмплированной сетке даёт звон вокруг ярких точек.
        """
        h, w = arr.shape[0] // factor, arr.shape[1] // factor
        return arr.reshape(h, factor, w, factor, -1).mean(axis=(1, 3))

    @staticmethod
    def split_equirect_to_faces(equirect_path: str, face_size: int,
                                out_dir: str,
                                cancel_callback=None,
                                supersample: int = 1) -> Dict[str, str]:
        """
        Режет equirectangular-панораму (2:1, как фото 360°) на 6 квадратных
        граней Source-скайбокса. Возвращает {грань: путь к PNG} (неполный,
        если cancel_callback вернул True между гранями).

        Вся выборка идёт в ЛИНЕЙНОМ СВЕТЕ (см. _srgb_to_linear) — иначе мелкие
        яркие детали (звёзды, блики) гаснут при усреднении.

        supersample=N: грань выбирается в N раз крупнее и усредняется блоками
        N×N. Нужно, когда панорама подробнее грани: один отсчёт на пиксель
        выбрасывает остальные данные и даёт алиасинг (мойре, «шипение» мелких
        деталей). Цена — N² работы и памяти, поэтому живое превью зовёт с 1,
        а сборка мода — с 2.

        Резкость применяется ВСЕГДА, а не только при апскейле: в игре грань
        покрывает 90° обзора, то есть на экране 1920 текстура 1024 растянута
        почти вдвое и сглажена билинейно движком. Нерезкая маска компенсирует
        именно это увеличение (сильнее — когда мы ещё и сами тянули панораму).
        """
        import numpy as np
        from PIL import Image, ImageFilter

        os.makedirs(out_dir, exist_ok=True)
        with Image.open(equirect_path) as im:
            w, h = im.size
            src = SkyboxService._srgb_to_linear(np.asarray(im.convert("RGB")))
        ss = max(1, int(supersample))
        # Панорама беднее грани → апскейл, деталей взять негде: суперсэмплинг
        # только тратит время.
        upscaling = w < 4 * face_size
        if upscaling:
            ss = 1
        # Грань 2048 с ss=2 — сетка 4096²: карты выборки и промежуточные массивы
        # уходят за 2 ГиБ. На таком разрешении алиасинг и так вдвое слабее.
        if face_size * ss > 2048:
            ss = 1
        if upscaling:
            logger.warning(
                f"Панорама {w}x{h} беднее граней {face_size}: для честных "
                f"{face_size} нужна ширина {4 * face_size}. Максимум без "
                f"растягивания — грани {w // 4}.")

        result: Dict[str, str] = {}
        for face in SKY_FACES:
            if cancel_callback and cancel_callback():
                return result
            smap = SkyboxService._face_sample_map(face, w, h, face_size * ss)
            out = SkyboxService._gather_face(src, smap)
            if ss > 1:
                out = SkyboxService._downsample_box(out, ss)
            img = Image.fromarray(SkyboxService._linear_to_srgb_u8(out))
            img = img.filter(ImageFilter.UnsharpMask(
                radius=1.2, percent=70 if upscaling else 45, threshold=2))
            path = os.path.join(out_dir, f"{face}.png")
            img.save(path)
            result[face] = path
        return result

    @staticmethod
    def split_equirect_animated_to_faces(equirect_path: str, face_size: int,
                                         out_dir: str,
                                         cancel_callback=None) -> Dict[str, str]:
        """
        Режет АНИМИРОВАННУЮ equirect-панораму (GIF/APNG) на 6 анимированных граней
        (APNG, без потери цвета). Возвращает {грань: путь к APNG}; {} при отмене.

        Та же математика проекции и тот же линейный свет, что у статичной
        нарезки → грани сходятся на стыках так же. Карты выборки считаются ОДИН
        раз (не зависят от кадра), далее на каждом кадре — только дешёвая
        билинейная сборка.

        Суперсэмплинга здесь нет намеренно: он умножает цену КАЖДОГО кадра
        (30-кадровая панорама уехала бы в минуты).

        ponytail: держит все кадры×6 граней PIL-картинок в памяти
        (≈ frames·6·face_size²·3 Б). Для типичной панорамы (десятки кадров) ок;
        upgrade path — стриминг во временные файлы, если пойдут OOM на 4K×сотни кадров.
        """
        import numpy as np
        from PIL import Image, ImageSequence

        os.makedirs(out_dir, exist_ok=True)
        im = Image.open(equirect_path)
        w, h = im.size
        smaps = {f: SkyboxService._face_sample_map(f, w, h, face_size)
                 for f in SKY_FACES}
        per_face: Dict[str, list] = {f: [] for f in SKY_FACES}
        durations: List[int] = []
        for frame in ImageSequence.Iterator(im):
            if cancel_callback and cancel_callback():
                return {}
            durations.append(int(frame.info.get("duration", 0)
                                 or im.info.get("duration", 0) or 100))
            arr = SkyboxService._srgb_to_linear(np.asarray(frame.convert("RGB")))
            for f in SKY_FACES:
                per_face[f].append(Image.fromarray(
                    SkyboxService._linear_to_srgb_u8(
                        SkyboxService._gather_face(arr, smaps[f]))))

        result: Dict[str, str] = {}
        for f in SKY_FACES:
            frames = per_face[f]
            path = os.path.join(out_dir, f"{f}.png")   # APNG (full-colour)
            frames[0].save(path, save_all=True, append_images=frames[1:],
                           duration=durations, loop=0, format="PNG")
            result[f] = path
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
                # Анимированная панорама (GIF/APNG) → анимированные грани;
                # обычная — статичные PNG. Выбор по самому файлу, без доп. опции.
                _faces_dir = str(ctx.temp_dir / "sky_faces")
                if TextureService.is_animated_image(request.image_path):
                    sources = SkyboxService.split_equirect_animated_to_faces(
                        request.image_path, face_size, _faces_dir,
                        cancel_callback=cancel_callback)
                else:
                    # supersample=2 только в сборке: +8 с на 6 граней 1024, зато
                    # без алиасинга. Живое превью режет с 1, чтобы не тормозить.
                    sources = SkyboxService.split_equirect_to_faces(
                        request.image_path, face_size, _faces_dir,
                        cancel_callback=cancel_callback, supersample=2)
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
            # animated_faces: {грань: fps} — только реально анимированные грани.
            # Пустой словарь ⇒ ни одной анимации ⇒ все VMT остаются на шейдере sky.
            animated_faces: Dict[str, int] = {}
            # CLAMPS/CLAMPT обязательны (иначе видны швы на стыках граней),
            # мипы гране неба не нужны. Из пользовательских флагов осмысленен
            # один: POINTSAMPLE — без сглаживания звёзды остаются точками, а не
            # мягкими пятнами (грань растянута на 90° обзора).
            _vtf_flags = ["CLAMPS", "CLAMPT", "NOLOD"]
            if "POINTSAMPLE" in (request.flags or []):
                _vtf_flags.append("POINTSAMPLE")
                logger.info("Скайбокс: POINTSAMPLE — билинейная фильтрация выключена")
            _vtf_opts = {"nomipmaps": True, "nothumbnail": True}
            for i, face in enumerate(SKY_FACES):
                if cancelled():
                    ctx.cleanup(on_error=True,
                                keep_on_error=request.keep_temp_on_error,
                                debug_mode=request.debug_mode)
                    return False, t.get('build_cancelled', 'Build cancelled by user')
                sub(int(i / len(SKY_FACES) * 70),
                    t.get('build_skybox_faces', 'Building sky faces...'))
                src = sources[face]
                out_vtf = sky_dir / f"{stem}{face}.vtf"
                if src.lower().endswith('.vtf'):
                    # Готовый VTF пользователя — как есть (флаги/формат его).
                    copy_file_safe(src, out_vtf)
                    continue
                if TextureService.is_animated_image(src):
                    # Многокадровый VTF. create_animated_vtf возвращает fps
                    # (среднее по длительностям кадров); формат сохраняется —
                    # у нарезанных граней альфы нет, апгрейда DXT1→DXT5 не будет.
                    fps = TextureService.create_animated_vtf(
                        src, str(out_vtf), (face_size, face_size),
                        format_type, _vtf_flags, _vtf_opts)
                    animated_faces[face] = int(fps or 24)
                    continue
                png = sky_dir / f"{stem}{face}.png"
                SkyboxService._normalize_face_to_square(
                    src, str(png), face_size, face=face)
                TextureService.create_vtf(
                    str(png), str(sky_dir), format_type, _vtf_flags, _vtf_opts)
                if png.exists():
                    png.unlink()

            # ── VMT на каждое небо × грань (LDR + HDR) ────────────────────── #
            sub(80, t.get('build_skybox_vmts', 'Writing sky materials...'))
            # Если анимирована хоть одна грань — весь куб на UnlitGeneric (один
            # шейдер, без стыка sky/UnlitGeneric); статичные грани без прокси.
            # Полностью статичный скайбокс остаётся на нативном шейдере sky.
            _has_animation = bool(animated_faces)
            for sky in request.skybox_sky_names:
                for face in SKY_FACES:
                    if face in animated_faces:
                        content = _SKY_VMT_ANIMATED_TEMPLATE.format(
                            stem=stem, face=face, fps=animated_faces[face])
                    elif _has_animation:
                        content = _SKY_VMT_UNLIT_STATIC_TEMPLATE.format(
                            stem=stem, face=face)
                    else:
                        content = _SKY_VMT_TEMPLATE.format(stem=stem, face=face)
                    for name in (f"{sky}{face}.vmt", f"{sky}_hdr{face}.vmt"):
                        with open(sky_dir / name, 'w', encoding='utf-8') as f:
                            f.write(content)
            logger.info(
                f"[SKYBOX] {len(SKY_FACES)} VTF ({stem}*) + "
                f"{len(request.skybox_sky_names) * len(SKY_FACES) * 2} VMT "
                f"({len(request.skybox_sky_names)} небес; "
                f"анимированных граней: {len(animated_faces)})")

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
