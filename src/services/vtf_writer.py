"""
Картинка -> VTF без внешних программ

Повторяет файл, который писал VTFCmd 1.3.2 (эталон снят прогоном по всем
форматам): версия 7.3, мипмапы усреднением 2x2 до 1x1, превью в DXT1 не
больше 16x16, reflectivity как среднее (c/255)^2.2, флаги альфы по формату.
Сжатие DXT делает libsquish внутри srctools, он отпускает GIL, поэтому
VtfJobs жмёт текстуры параллельно в потоках

16-битные HDR-форматы srctools писать не умеет, их пишет VTFLib без мипмапов
"""

import io
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from srctools.vtf import VTF, Frame, ImageFormats, VTFFlags

from src.services.vtflib_wrapper import VTFLib, VTFImageFormat, VTFImageFlags

VERSION = (7, 3)
# Без превью srctools в 7.3 всё равно пишет пустую запись LOW_RES, у VTFCmd
# и у стоковых текстур её нет. В 7.2 записей нет вовсе, так хранится часть
# стокового неба
VERSION_NO_THUMB = (7, 2)
THUMB_MAX = 16

_HDR_FORMATS = frozenset({"RGBA16161616F", "RGBA16161616"})
# 565 srctools раскладывает с R и B наоборот против VTFLib
_SWAP_RB = frozenset({"RGB565", "BGR565"})
# Серый VTFLib считал яркостью 0.299/0.587/0.114, srctools - средним каналов
_LUMA = frozenset({"I8", "IA88"})

# Какой флаг альфы VTFCmd ставил формату, независимо от содержимого картинки
_ONE_BIT_ALPHA = frozenset({"DXT1_ONEBITALPHA", "BGRA5551"})
_EIGHT_BIT_ALPHA = frozenset({
    "DXT3", "DXT5", "RGBA8888", "ABGR8888", "ARGB8888", "BGRA8888", "BGRA4444",
    "IA88", "A8", "UVWQ8888", "UVLX8888", "RGBA16161616F", "RGBA16161616",
})


def alpha_flags(fmt: str) -> int:
    if fmt in _ONE_BIT_ALPHA:
        return VTFImageFlags.ONEBITALPHA
    if fmt in _EIGHT_BIT_ALPHA:
        return VTFImageFlags.EIGHTBITALPHA
    return 0


def gamma_correct(rgba: Image.Image, gamma: float) -> Image.Image:
    """Цвет в степень 1/gamma, альфа без изменений"""
    lut = [round(255 * (i / 255) ** (1 / gamma)) for i in range(256)]
    return rgba.point(lut * 3 + list(range(256)))


def reflectivity(rgba: Image.Image) -> tuple:
    rgb = np.asarray(rgba, dtype=np.float32)[..., :3] / 255
    return tuple(float(c) for c in (rgb ** 2.2).reshape(-1, 3).mean(0))


def _to_format_channels(rgba: Image.Image, fmt: str) -> Image.Image:
    if fmt in _SWAP_RB:
        r, g, b, a = rgba.split()
        return Image.merge("RGBA", (b, g, r, a))
    if fmt in _LUMA:
        gray = rgba.convert("L")
        return Image.merge("RGBA", (gray, gray, gray, rgba.getchannel("A")))
    return rgba


def _halve(level: np.ndarray) -> np.ndarray:
    """Следующий мип-уровень: среднее 2x2 из предыдущего, как у VTFCmd. Не
    Image.resize: Pillow усредняет RGBA с учётом альфы, и цвет полупрозрачных
    пикселей уезжает"""
    h, w = level.shape[:2]
    fy, fx = (2 if h > 1 else 1), (2 if w > 1 else 1)
    return level.reshape(h // fy, fy, w // fx, fx, 4).mean(axis=(1, 3))


def thumb_size(width: int, height: int) -> tuple:
    while width > THUMB_MAX or height > THUMB_MAX:
        width, height = max(width // 2, 1), max(height // 2, 1)
    return width, height


def write_vtf(image: Image.Image, out_file, fmt: str, flags: int = 0, *,
              mipmaps: bool = True, thumbnail: bool = True,
              with_reflectivity: bool = True, gamma: Optional[float] = None,
              bump_scale: float = 1.0) -> None:
    """``fmt`` - имя формата VTF в верхнем регистре (DXT5, RGBA8888...)"""
    rgba = image.convert("RGBA")
    if gamma:
        rgba = gamma_correct(rgba, gamma)
    flags |= alpha_flags(fmt)
    out_file = Path(out_file)

    if fmt in _HDR_FORMATS:
        VTFLib.create_animated_vtf(
            [rgba.tobytes()], rgba.width, rgba.height, getattr(VTFImageFormat, fmt),
            flags | VTFImageFlags.NOMIP | VTFImageFlags.NOLOD, str(out_file),
            generate_thumbnail=thumbnail)
        return

    width, height = rgba.size
    vtf = VTF(width, height, VERSION if thumbnail else VERSION_NO_THUMB,
              fmt=getattr(ImageFormats, fmt),
              flags=VTFFlags(flags), bump_scale=bump_scale,
              ref=reflectivity(rgba) if with_reflectivity else (1, 1, 1),
              thumb_fmt=ImageFormats.DXT1 if thumbnail else ImageFormats.NONE)
    # Цепочка до 1x1 и у неквадратных, как у VTFCmd и у всех стоковых текстур.
    # srctools заводит кадры только до 1 пикселя по меньшей стороне, остальные
    # добавляем сами
    vtf.mipmap_count = max(width, height).bit_length() if mipmaps else 1
    # Нулевой уровень остаётся uint8: float-копия 2048x2048 весит 64 МБ на поток
    level = np.asarray(_to_format_channels(rgba, fmt))
    for mip in range(vtf.mipmap_count):
        if mip:
            level = _halve(level.astype(np.float32, copy=False))
        frame = vtf._frames.setdefault((0, 0, mip), Frame(level.shape[1], level.shape[0]))
        frame.copy_from(np.round(level).astype(np.uint8).tobytes())

    # Превью srctools сам не заполняет: без этого оно в файле чёрное
    tw, th = thumb_size(width, height) if thumbnail else (0, 0)
    vtf._low_res = Frame(tw, th)
    if thumbnail:
        vtf._low_res.copy_from(rgba.resize((tw, th), Image.BOX).tobytes())

    # save() зовёт compute_mipmaps, а тот всегда перерисовывает превью из мипа,
    # где у 565 и серых форматов каналы уже переложены. Кадры все заполнены
    vtf.compute_mipmaps = lambda *a, **k: None
    # Сначала в память: ошибка посреди записи не оставит полфайла
    buf = io.BytesIO()
    vtf.save(buf)
    out_file.write_bytes(buf.getvalue())
