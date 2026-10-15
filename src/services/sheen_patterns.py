"""
Свои узоры блеска Killstreak: анимированная маска `$sheenmapmask`.

Как это устроено в игре (source-sdk-2013: c_tf_player.cpp,
weapon_sheen_pass_ps2x.fxc):
  • прокси AnimatedWeaponSheen берёт число кадров у САМОЙ текстуры маски
    (GetNumAnimationFrames) и крутит их с tf_sheen_framerate = 25 кадров в
    секунду; паузу между проходами он сокращает с серией убийств (5 с без
    убийств, 0 с при пяти) — для своей маски всё это остаётся;
  • кадр 0 не рисуется (ShouldDrawMaterialSheen), поэтому он пустой;
  • маска умножает цвет блеска (RGB) и даёт прозрачность (красный канал),
    координата X — вдоль оружия: стоковая полоса идёт по X слева направо
    за 50 кадров шириной ~0.2, потом ~10 пустых кадров.

Моды с GameBanana (Pulsing Killstreak Sheens, Sap Experimental) подменяют
общую маску effects/animatedsheen/animatedsheen0 у ВСЕГО оружия. Здесь маска
своя у материала: `$sheenmapmask "tf2sg/sheen/<узор>_<кадров>"`, а файл
по этому имени достраивает сборка (`materialize`) — хранить его не нужно,
он целиком задаётся именем.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Узоры (подписи - в форме эффекта, vmt_effects).
PATTERNS = ("double", "pulse", "pulse2", "stripes", "sparkle", "mist", "calib")

PREFIX = "tf2sg/sheen/"
SIZE = 128
FPS = 25                       # tf_sheen_framerate игры
MIN_FRAMES, MAX_FRAMES = 26, 201
PEAK = 230                     # стоковая маска доходит до 216

#: Ровная кубмапа блеска вместо игровой cubemaps/cubemap_sheen001. Цвет
#: прохода = кубмапа x цвет x 10 x маска, а прозрачность - его яркость; у
#: игровой кубмапы почти всё тёмное (в среднем 30-60 из 255) с редкими
#: светлыми пятнами, поэтому от узора видны только куски. Серый 89 (sRGB)
#: = 0.1 линейно: x10 даёт ровно цвет блеска по всему узору.
FLAT_CUBE = PREFIX + "flat"
FLAT_GREY = 89
STOCK_CUBE = "cubemaps/cubemap_sheen001"

#: Готовый узор: имя, «_r» - маска повёрнута (оружие длинное по Z), кадры.
_NAME_RE = re.compile(r'^tf2sg/sheen/([a-z0-9]+?)(_r)?_(\d+)$')
#: `$sheenmapmask` с нашей маской: в кавычках или без, с пробелом или без,
#: с обратными слэшами, с папкой-обходом впереди (повторная упаковка).
_VMT_RE = re.compile(r'("?\$sheenmapmask"?\s*"?)((?:[\w.\\/-]*[\\/])?tf2sg[\\/]sheen[\\/]\w+?_\d+)'
                     r'(?:\.vtf)?', re.IGNORECASE)


#: `$sheenmap` с нашей ровной кубмапой (не `$sheenmapmask`).
_CUBE_RE = re.compile(r'("?\$sheenmap"?\s+"?)((?:[\w.\\/-]*[\\/])?tf2sg[\\/]sheen[\\/]flat)'
                      r'(?:\.vtf)?(?![\w])', re.IGNORECASE)


def is_flat_cube(name: str) -> bool:
    """`$sheenmap` - наша ровная кубмапа (в том числе уже в папке-обходе)."""
    return str(name or '').strip().lower().replace('\\', '/').endswith(FLAT_CUBE)


def frames_for(seconds: float) -> int:
    """Кадров на проход заданной длины (+ пустой нулевой)."""
    return int(min(MAX_FRAMES, max(MIN_FRAMES, round(seconds * FPS) + 1)))


def texture_name(pattern: str, frames: int, rotate: bool = False) -> str:
    return f"{PREFIX}{pattern}{'_r' if rotate else ''}_{int(frames)}"


def rotated(name: str) -> bool:
    """Маска повёрнута на 90°: оружие длинное по Z, маска лежит по X и Z
    (vmt_effects.sheen_mask_params, «stencil»), а рисуется длиной по X."""
    short = str(name or '').strip().lower().replace('\\', '/')
    m = _NAME_RE.match(short)
    if m and m.group(1) in PATTERNS:
        return bool(m.group(2))
    m = _CUSTOM_RE.match(short)
    return bool(m and m.group(3))


def parse(name: str) -> Optional[Tuple[str, int]]:
    """(узор, кадров) по имени текстуры или None — не наша / не та."""
    m = _NAME_RE.match(str(name or '').strip().lower().replace('\\', '/'))
    if not m or m.group(1) not in PATTERNS:
        return None
    frames = int(m.group(3))
    return (m.group(1), frames) if MIN_FRAMES <= frames <= MAX_FRAMES else None


#: Своя маска: id узора, (в моде) отпечаток содержимого, пропорция, кадры.
_CUSTOM_RE = re.compile(r'^tf2sg/sheen/(u[0-9a-f]{8})(?:_h[0-9a-f]{8})?_a(\d+)(r?)_(\d+)$')


def custom_name(pattern_id: str, aspect: float, frames: int, rotate: bool = False) -> str:
    """Своя маска из конструктора: id узора, пропорция оружия ×10 («r» -
    маска повёрнута), кадры."""
    return (f"{PREFIX}{pattern_id}_a{int(round(max(0.5, min(12.0, aspect)) * 10))}"
            f"{'r' if rotate else ''}_{int(frames)}")


def parse_custom(name: str) -> Optional[Tuple[str, float, int]]:
    """(id узора, пропорция, кадров) или None."""
    m = _CUSTOM_RE.match(str(name or '').strip().lower().replace('\\', '/'))
    if not m:
        return None
    frames = int(m.group(4))
    if not MIN_FRAMES <= frames <= MAX_FRAMES:
        return None
    return m.group(1), int(m.group(2)) / 10.0, frames


def _envelope(t: float) -> float:
    """Плавно появиться и погаснуть; последние ~10 % прохода пусто, как у
    стоковой маски (пауза внутри прохода)."""
    t = min(1.0, max(0.0, t / 0.9))
    return min(1.0, t / 0.12) * min(1.0, (1 - t) / 0.2)


def _noise(size: int, cells: int, seed: int) -> np.ndarray:
    """Плавный бесшовный шум (value noise, косинусная интерполяция) 0…1."""
    rng = np.random.default_rng(seed)
    grid = rng.random((cells, cells))
    x = np.arange(size) * cells / size
    i0 = np.floor(x).astype(int) % cells
    i1 = (i0 + 1) % cells
    f = (1 - np.cos((x - np.floor(x)) * np.pi)) / 2
    rows = grid[i0] * (1 - f)[:, None] + grid[i1] * f[:, None]
    return rows[:, i0] * (1 - f)[None, :] + rows[:, i1] * f[None, :]


def _fbm(size: int, seed: int) -> np.ndarray:
    out = sum(_noise(size, c, seed + k) / (k + 1) for k, c in enumerate((4, 8, 16)))
    out -= out.min()
    return out / max(out.max(), 1e-6)


def _frame(pattern: str, t: float, u: np.ndarray, v: np.ndarray, extra) -> np.ndarray:
    """Яркость маски 0…1 в момент t (0…1 прохода)."""
    env = _envelope(t)
    if env <= 0:
        return np.zeros_like(u)
    wave = 0.03 * np.sin(v * 2 * np.pi * 1.5 + t * 6)
    if pattern == "double":
        head = -0.15 + 1.4 * t
        g1 = np.exp(-((u - head + wave) / 0.07) ** 2)
        g2 = np.exp(-((u - head + 0.32 + wave) / 0.06) ** 2)
        return np.maximum(g1, 0.75 * g2) * env
    if pattern in ("pulse", "pulse2"):
        k = 1 if pattern == "pulse" else 2
        tt = min(1.0, t / 0.9)
        beat = np.sin(np.pi * k * tt) ** 2
        # Не ровная заливка: лёгкий рисунок, иначе вспышка выглядит плоской.
        return beat * (0.75 + 0.25 * extra) * np.ones_like(u)
    if pattern == "stripes":
        phase = u * 5.0 - t * 3.0 + wave * 4
        return (0.5 + 0.5 * np.cos(2 * np.pi * phase)) ** 8 * env
    if pattern == "sparkle":
        pos, birth = extra
        out = np.zeros_like(u)
        life = 0.18
        for (px, py), b in zip(pos, birth):
            k = (t - b) / life
            if 0 < k < 1:
                bright = np.sin(np.pi * k) ** 2
                d2 = (u - px) ** 2 + ((v - py) * 0.5) ** 2
                out = np.maximum(out, bright * np.exp(-d2 / 0.0005))
        return out * min(1.0, env * 3)
    if pattern == "mist":
        a, b = extra
        n = SIZE
        sx = int(t * n * 1.2) % n
        flow = np.roll(a, sx, axis=1) * np.roll(b, -sx // 2, axis=0)
        band = np.exp(-((u - (-0.2 + 1.4 * t)) / 0.35) ** 2)
        return np.clip((flow - 0.2) * 2.6, 0, 1) * band * env
    raise ValueError(f"unknown sheen pattern {pattern}")


#: Калибровка крупнее: на 128 px цифры и буква не читаются на оружии.
CALIB_SIZE = 256


def _calibration(size: int = CALIB_SIZE) -> np.ndarray:
    """Неподвижная картинка, по которой видно, как маска легла на модель:
    сетка 4×4 толстыми линиями и крупные цифры 1…16 по порядку чтения
    (слева направо, сверху вниз). Цифры несимметричны — по ним видно и
    направление осей, и зеркало. Мелкие подписи на оружии не читались
    (тест 2026-10-13). Белое на чёрном: маска умножает цвет блеска."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    cell = size // 4

    font = None
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, int(cell * 0.62))
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    for i in range(5):
        d.line([(i * cell, 0), (i * cell, size)], fill=140, width=6)
        d.line([(0, i * cell), (size, i * cell)], fill=140, width=6)
    for row in range(4):
        for col in range(4):
            d.text((col * cell + cell // 2, row * cell + cell // 2), str(row * 4 + col + 1),
                   fill=255, font=font, anchor="mm")
    return np.asarray(img)


def frames(pattern: str, count: int, size: int = SIZE) -> List[np.ndarray]:
    """Кадры маски RGBA uint8; кадр 0 пустой (игра его не рисует)."""
    if pattern not in PATTERNS:
        raise ValueError(f"unknown sheen pattern {pattern}")
    if pattern == "calib":
        # Картинка стоит весь проход: её успеваешь снять скриншотом.
        lum = _calibration()
        still = np.dstack([lum, lum, lum, np.full_like(lum, 255)])
        blank = np.zeros_like(still)
        blank[..., 3] = 255
        return [blank] + [still] * (count - 1)
    v, u = np.mgrid[0:size, 0:size] / float(size)
    rng = np.random.default_rng(7)
    extra = None
    if pattern in ("pulse", "pulse2"):
        extra = _fbm(size, 3)
    elif pattern == "sparkle":
        extra = (rng.random((120, 2)), rng.random(120) * 0.8)
    elif pattern == "mist":
        extra = (_fbm(size, 11), _fbm(size, 23))
    out = [np.zeros((size, size, 4), np.uint8)]
    for i in range(1, count):
        t = (i - 1) / max(1, count - 2)
        lum = np.clip(_frame(pattern, t, u, v, extra) * PEAK, 0, 255).astype(np.uint8)
        out.append(np.dstack([lum, lum, lum, np.full_like(lum, 255)]))
    out[0][..., 3] = 255
    return out


def write_vtf(pattern: str, count: int, out_path: Path) -> Path:
    """VTF маски: DXT1 без мипмапов, как маски модов (NOMIP | NOLOD)."""
    return _write(frames(pattern, count), out_path)


def _write(pics: List[np.ndarray], out_path: Path) -> Path:
    from src.services.vtflib_wrapper import VTFImageFormat, VTFImageFlags, VTFLib

    h, w = pics[0].shape[:2]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    VTFLib.create_animated_vtf(
        [p.tobytes() for p in pics], w, h, VTFImageFormat.DXT1,
        VTFImageFlags.NOMIP | VTFImageFlags.NOLOD, str(out_path))
    return out_path


def _bypass_folder() -> str:
    """Папка-обход sv_pure из настроек (console или vgui/replay/thumbnails):
    в казуале из мода грузятся только файлы в ней — маска должна лежать там
    же, где сборка кладёт остальные файлы оружия."""
    try:
        from src.config.app_config import AppConfig
        from src.shared.constants import bypass_prefix
        return bypass_prefix(AppConfig.load_config().get('sv_pure_bypass', 'console'))
    except Exception:                                      # noqa: BLE001
        return "console"


def materialize(vpkroot_dir: Path, folder: Optional[str] = None) -> int:
    """Маски узоров, на которые ссылаются VMT мода, — в мод; сколько создано.

    Редактор пишет короткое имя `tf2sg/sheen/<узор>_<кадров>`; здесь ссылка
    в VMT мода переносится в папку-обход (`folder`, по умолчанию из
    настроек), и файл кладётся туда же. Не вышло — исключение: мод без маски
    в игре показал бы на оружии «шахматку».
    """
    root = Path(vpkroot_dir)
    materials = root / "materials"
    if not materials.is_dir():
        return 0
    folder = (_bypass_folder() if folder is None else folder).replace('\\', '/').strip('/').lower()
    wanted = set()
    for vmt in materials.rglob("*.vmt"):
        try:
            raw = vmt.read_bytes()
        except OSError:
            continue
        text = raw.decode("latin-1")             # байты как есть: кириллица в комментариях цела
        if "sheen" not in text.lower():
            continue

        def move(m):
            ref = m.group(2).replace('\\', '/').lower()
            short = ref[ref.index('tf2sg/sheen/'):]
            own = parse_custom(short)
            if own:
                # В моде — с отпечатком содержимого: моды, собранные до и
                # после правки узора, не делят один путь.
                from src.services import sheen_builder
                digest = sheen_builder.content_hash(own[0])
                if not digest:
                    raise RuntimeError(f"sheen pattern {own[0]} not found in "
                                       f"{sheen_builder.library_dir()}")
                short = (f"{PREFIX}{own[0]}_h{digest}_a{int(round(own[1] * 10))}"
                         f"{'r' if rotated(short) else ''}_{own[2]}")
            elif not parse(short):
                return m.group(0)
            wanted.add(short)
            return m.group(1) + (f"{folder}/{short}" if folder else short)

        def cube(m):
            wanted.add(FLAT_CUBE)
            return m.group(1) + (f"{folder}/{FLAT_CUBE}" if folder else FLAT_CUBE)

        new = _CUBE_RE.sub(cube, _VMT_RE.sub(move, text))
        if new != text:
            vmt.write_bytes(new.encode("latin-1"))
    made = 0
    for short in sorted(wanted):
        target = materials / folder / (short + ".vtf") if folder else materials / (short + ".vtf")
        if target.exists():
            continue
        if short == FLAT_CUBE:
            from src.services.vtflib_wrapper import VTFLib
            target.parent.mkdir(parents=True, exist_ok=True)
            face = bytes((FLAT_GREY, FLAT_GREY, FLAT_GREY, 255)) * 16
            VTFLib.create_cubemap_vtf([face] * 6, 4, str(target))
            made += 1
            continue
        own = parse_custom(short)
        if own:
            from src.services import sheen_builder
            pattern_id, aspect, count = own
            data = sheen_builder.load(pattern_id, deleted=True)
            if data is None:
                raise RuntimeError(f"sheen pattern {pattern_id} not found in "
                                   f"{sheen_builder.library_dir()}")
            pics = sheen_builder.render(data["spec"], count, aspect)
        else:
            pattern, count = parse(short)
            pics = frames(pattern, count)
        if rotated(short):
            # Длина узора - по вертикали маски (ось Z оружия).
            pics = [np.ascontiguousarray(np.transpose(p, (1, 0, 2))) for p in pics]
        _write(pics, target)
        logger.info(f"[sheen] маска узора {target.relative_to(root).as_posix()} ({count} кадров)")
        made += 1
    return made
