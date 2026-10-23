"""Замена текстуры материала своей картинкой (перезапись VTF игры)"""

import base64
import io
import os
import tempfile
from pathlib import Path
from typing import Optional

from src.services import vmt_parse
from src.services.particle_editor.pcf_format import norm_mat
from src.services.tf2_paths import TF2Paths
from src.services.vtf_preview_service import open_vpks, read_from_vpks
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def set_system_texture(
    pcf, system_name: str, image_path: str, tf2_root_dir: str,
    max_size: int = 512, uncompressed: bool = False,
) -> Optional[tuple]:
    """Заменяет текстуру системы своей картинкой. Имя материала в PCF НЕ
    меняется - ПЕРЕЗАПИСЫВАЕТСЯ оригинальный VTF-файл игры (для казуала -
    bypass подменяет только существующие файлы). Returns (материал, info)"""
    d = pcf._find_definition(system_name)
    if d is None or "material" not in d:
        return None
    mat = d["material"].val_str
    info = overwrite_texture(pcf, 
        mat, image_path, tf2_root_dir, max_size, uncompressed)
    return (mat, info) if info is not None else None


def set_material_texture(
    pcf, material_name: str, image_path: str, tf2_root_dir: str,
    max_size: int = 512, uncompressed: bool = False,
) -> Optional[tuple]:
    """То же по имени материала (перезапись одного общего VTF-файла)"""
    info = overwrite_texture(pcf, 
        material_name, image_path, tf2_root_dir, max_size, uncompressed)
    return (material_name, info) if info is not None else None


def overwrite_texture(
    pcf, material_name: str, image_path: str, tf2_root_dir: str,
    max_size: int, uncompressed: bool,
) -> Optional[dict]:
    """
    Перезаписывает ОРИГИНАЛЬНЫЙ VTF-файл материала своей картинкой.
    Материал в PCF не переименовывается. КРИТИЧНО для казуала: bypass
    подменяет только существующие файлы игры, новый путь он пропускает.
    Кастомный VTF кладётся по пути $basetexture стокового VMT
    """
    vmt_text, tex_rel = pcf._resolve_texture_path(material_name, tf2_root_dir)
    built = pcf._image_to_vtf(image_path, max_size, uncompressed,
                               square=_sprite_only_material(pcf, material_name))
    if built is None:
        return None
    vtf_bytes, w, h = built["vtf"], built["w"], built["h"]
    png_b64, sheet, fps = built["png_b64"], built["sheet"], built["fps"]
    pcf.custom_files[f"materials/{tex_rel}.vtf"] = vtf_bytes
    if not vmt_text:
        # Материала нет в игре (кастомное имя у ребёнка-партикла): без VMT
        # Source не загрузит материал вовсе - генерируем шаблон по образцу
        # стоковых партикл-материалов TF2 (effects/crit.vmt)
        vmt_text = (
            '"SpriteCard"\n'
            '{\n'
            f'\t"$basetexture" "{tex_rel}"\n'
            '\t"$translucent" 1\n'
            '\t"$vertexcolor" 1\n'
            '\t"$vertexalpha" 1\n'
            '}\n'
        )
    if vmt_text and fps:
        # Гифка: кадры многокадрового VTF в игре крутит прокси AnimatedTexture
        # ($basetexture/$frame) - как у анимированных текстур оружия
        from src.services.vmt_service import VMTService
        vmt_text = VMTService.add_animated_texture_proxy(vmt_text, fps)
        logger.info(f"Материал {material_name}: добавлен прокси "
                    f"AnimatedTexture @ {fps}fps")
    if vmt_text:
        # Оригинальный игровой VMT кладём рядом с VTF: текстурная часть
        # мода самодостаточна (casual-pre-loader ставит материалы только
        # из аддонов, и его автор просит модмейкеров включать VMT)
        pcf.custom_files[f"materials/{norm_mat(material_name)}"] = (
            vmt_text.encode("utf-8"))

    shader, additive = "", True
    if vmt_text:
        vmt = vmt_parse.parse(vmt_text)
        shader = vmt.shader
        additive = vmt.flag("additive")
    info = {
        "dataUrl": f"data:image/png;base64,{png_b64}", "sheet": sheet,
        "additive": additive, "shader": shader, "width": w, "height": h,
    }
    key = norm_mat(material_name)
    pcf._custom_material_info[key] = info
    pcf._overwritten[key] = {"tex_rel": tex_rel, "material": material_name}
    return info


def resolve_texture_path(pcf, material_name: str, tf2_root_dir: str):
    """(текст VMT|None, rel-путь текстуры без .vtf). Путь берётся из
    $basetexture стокового VMT; фолбэк - имя материала"""
    vmt_rel = norm_mat(material_name)
    vmt_text = None
    try:
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        paks = open_vpks(
            [misc_vpk, TF2Paths.resolve_textures_vpk(tf2_root_dir)]
            + TF2Paths.resolve_hl2_vpks(tf2_root_dir))
        raw = read_from_vpks(paks, "materials/" + vmt_rel)
        if raw is not None:
            vmt_text = raw.decode("utf-8", errors="replace")
    except FileNotFoundError:
        pass
    tex_rel = None
    if vmt_text:
        t = vmt_parse.parse(vmt_text).path("basetexture")
        if t:
            tex_rel = t[:-4] if t.endswith(".vtf") else t
    if tex_rel is None:
        tex_rel = vmt_rel[:-4]
        if tf2_root_dir:
            logger.warning(
                f"Не удалось прочитать VMT {vmt_rel} - путь текстуры взят "
                f"из имени материала ({tex_rel}); для казуала проверьте, "
                f"что такой VTF есть в игре.")
    return vmt_text, tex_rel


#: Больше кадров в лист не влезает без потери разрешения (8×8 клеток)
_SHEET_MAX_FRAMES = 64


def gif_to_sheet(image_path: str, cap: int):
    """Анимированная картинка -> (лист-изображение, sheet-данные)

    Кадры раскладываются в сетку из степеней двойки (лист остаётся POT),
    а sheet-данные - тот же формат, что отдаёт parse_vtf_sheet для игровых
    листов, поэтому движок превью анимирует их без единой правки

    ponytail: скорость проигрывания в превью задаёт 'animation rate'
    рендерера системы, а не собственный fps гифки - так же, как это делает
    игра с настоящим спрайт-листом. Длительности кадров относительные
    """
    from PIL import Image

    from src.services.texture_service import TextureService

    count, _ = TextureService._animation_info(
        image_path, _SHEET_MAX_FRAMES)
    cols = 1
    while cols * cols < count:
        cols *= 2
    rows = 1
    while cols * rows < count:
        rows *= 2
    cell = 1
    while cell * 2 * max(cols, rows) <= cap:
        cell *= 2

    durations: list = []
    frames = [
        Image.frombytes("RGBA", (cell, cell), buf)
        for buf in TextureService._iter_animation_frames_rgba(
            image_path, (cell, cell), count, durations)
    ]
    sheet_img = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
    mean = (sum(d or 100 for d in durations) / len(durations)) or 100
    seq_frames = []
    for i, frame in enumerate(frames):
        col, row = i % cols, i // cols
        sheet_img.paste(frame, (col * cell, row * cell))
        seq_frames.append({
            "duration": (durations[i] or 100) / mean,
            "coords": [[col / cols, row / rows,
                        (col + 1) / cols, (row + 1) / rows]],
        })
    sheet = {"sequences": {0: {
        "clamp": False,
        "duration": sum(f["duration"] for f in seq_frames),
        "frames": seq_frames,
    }}}
    logger.info(f"Гифка → спрайт-лист {cols}x{rows} по {cell}px "
                f"({count} кадров): {os.path.basename(image_path)}")
    return sheet_img, sheet


#: Рендереры, рисующие частицу квадратом: текстура растягивается на него
#: целиком, какой бы формы она ни была
_SQUARE_RENDERERS = {"render_animated_sprites", "render_screen_velocity_rotate"}


def _sprite_only_material(pcf, material_name: str) -> bool:
    """True, если материал рисуют только квадратные спрайты (не верёвки/следы)"""
    key = norm_mat(material_name)
    fns = {(m.get("functionName") or "").lower()
           for s in pcf.systems_json().values()
           if norm_mat((s["attrs"].get("material") or {}).get("v") or "") == key
           for m in s.get("renderers") or []}
    return bool(fns) and fns <= _SQUARE_RENDERERS


def image_to_vtf(image_path: str, max_size: int, uncompressed: bool,
                  square: bool = False):
    """Картинка -> {vtf, w, h, png_b64, sheet, fps} либо None при ошибке.
    Размеры -> степени двойки (<= max_size, потолок 1024) с сохранением
    пропорций. NOMIP|NOLOD

    square=True - неквадратная картинка дополняется прозрачными полями до
    квадрата: спрайт в игре квадратный, иначе 1024×512 на нём сплющится

    Анимированная картинка (GIF/APNG/WebP): VTF многокадровый (в игре кадры
    крутит прокси AnimatedTexture, fps != None), а в превью уходит спрайт-лист
    с sheet-данными - движок превью умеет только листы
    """
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGBA")
    except Exception as exc:
        logger.error(f"Не удалось открыть картинку {image_path}: {exc}")
        return None
    cap = max(64, min(int(max_size), 1024))
    # img (первый кадр в полном разрешении) не трогаем - он идёт в VTF
    preview_img, sheet = _preview_sheet(image_path, cap)
    img, w, h = _fit_pot(img, cap, square and sheet is None)
    if preview_img is None:
        preview_img = img
    try:
        vtf_bytes, fps = _write_vtf(image_path, img, w, h, uncompressed,
                                    animated=sheet is not None)
    except Exception as exc:
        logger.error(f"Картинка → VTF не удалась: {exc}", exc_info=True)
        return None
    buf = io.BytesIO()
    preview_img.save(buf, format="PNG")
    png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"vtf": vtf_bytes, "w": w, "h": h, "png_b64": png_b64,
            "sheet": sheet, "fps": fps}


def _preview_sheet(image_path: str, cap: int):
    """(лист-картинка, sheet) для анимированной картинки, иначе (None, None)"""
    from src.services.texture_service import TextureService
    if not TextureService.is_animated_image(image_path):
        return None, None
    try:
        return gif_to_sheet(image_path, cap)
    except Exception as exc:
        # Не смогли собрать лист - молча остаёмся на первом кадре
        logger.warning(f"Гифка → спрайт-лист не удалась: {exc}", exc_info=True)
        return None, None


def _fit_pot(img, cap: int, pad_square: bool):
    """Картинка под VTF: (img, w, h) со сторонами-степенями двойки <= cap"""
    from PIL import Image

    def _pot(n: int) -> int:
        p = 1
        while p * 2 <= min(n, cap):
            p *= 2
        return p

    if pad_square and img.width != img.height:
        # ponytail: гифки по-прежнему тянутся на квадратные клетки листа
        side = max(img.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        img = canvas
    # Потолок по большей стороне, а не по каждой отдельно: иначе
    # 1024×512 при потолке 512 становилось 512×512
    k = min(1.0, cap / max(img.size))
    w, h = _pot(round(img.width * k)), _pot(round(img.height * k))
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS)
    return img, w, h


def _write_vtf(image_path: str, img, w: int, h: int, uncompressed: bool,
               animated: bool):
    """(байты VTF, fps | None). Бросает исключение, если VTF не собрался"""
    from src.services.texture_service import TextureService
    from src.services.vtflib_wrapper import (
        VTFImageFlags, VTFImageFormat, VTFLib)
    fps = None
    fd, tmp_path = tempfile.mkstemp(suffix=".vtf")
    os.close(fd)
    try:
        if animated:
            # Многокадровый VTF: кадры анимации крутит прокси AnimatedTexture
            # из VMT (тот же механизм, что у анимированных текстур оружия)
            fps = TextureService.create_animated_vtf(
                image_path, tmp_path, (w, h),
                "RGBA8888" if uncompressed else "DXT5",
                ["CLAMPS", "CLAMPT"], {},
            )
        else:
            VTFLib.create_animated_vtf(
                [img.tobytes()], w, h,
                VTFImageFormat.RGBA8888 if uncompressed else VTFImageFormat.DXT5,
                VTFImageFlags.CLAMPS | VTFImageFlags.CLAMPT
                | VTFImageFlags.NOMIP | VTFImageFlags.NOLOD,
                tmp_path,
            )
        return Path(tmp_path).read_bytes(), fps
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def is_custom_material(pcf, material_name: str) -> bool:
    """True, если текстура материала заменена своей картинкой (можно сбросить)"""
    return norm_mat(material_name) in pcf._overwritten


def reset_material_texture(pcf, material_name: str) -> Optional[str]:
    """Убирает перезапись текстуры (возврат к текстуре игры). Материал в
    PCF не менялся - просто удаляем оверрайд-файл"""
    key = norm_mat(material_name)
    entry = pcf._overwritten.pop(key, None)
    if entry is None:
        return None
    pcf._custom_material_info.pop(key, None)
    # Файл удаляем ТОЛЬКО если tex_rel не делит другой активный оверрайд
    tex_rel = entry["tex_rel"]
    if not any(e["tex_rel"] == tex_rel for e in pcf._overwritten.values()):
        pcf.custom_files.pop(f"materials/{tex_rel}.vtf", None)
    pcf.custom_files.pop(f"materials/{key}", None)  # VMT этого материала
    return material_name
