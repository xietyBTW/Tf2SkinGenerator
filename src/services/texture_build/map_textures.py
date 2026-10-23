"""
Текстуры карт материала: нормаль с маской в альфе, Phong-карта по
каналам, авто-нормаль и $phong там, где без него эффект не считается
"""

import os
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def ensure_phong(vmt_path: Path, cdmaterials: str) -> bool:
    """$phong там, где без него эффект не считается: с силой 0, чтобы
    блика не появилось (вики Valve, $phongboost: «phong boost of zero is
    visually identical to no phong, and can be used to work around certain
    shader parameter combinations that require phong»)"""
    from src.services import vmt_parse
    doc = vmt_parse.parse(Path(vmt_path).read_text(encoding="utf-8", errors="ignore"))
    if doc.flag("$phong"):
        return False
    params = {"$phong": "1", "$phongboost": "0"}
    if doc.get("$phongfresnelranges") is None:
        params["$phongfresnelranges"] = "[0 0.5 1]"
    VMTService.add_material_map_params(str(vmt_path), cdmaterials, None, None, params)
    return True


def mask_png(spec: dict, kind: str, base_image_path: Optional[str],
              out_dir: Path, stem: str, size: Tuple[int, int]) -> Optional[Path]:
    """Маска (L) из записи карты: из базы по яркости (derive, с порогом) или
    из файла. None - не из чего"""
    png = Path(out_dir) / f"{stem}.png"
    try:
        if spec.get("derive"):
            if not (base_image_path and os.path.isfile(base_image_path)):
                return None
            thr = spec.get("threshold")
            TextureService.derive_effect_map(
                base_image_path, str(png), kind, size,
                threshold=int(thr) if thr not in (None, "") else None)
        elif spec.get("image") and os.path.isfile(spec["image"]):
            TextureService.process_image(spec["image"], str(png), size)
        else:
            return None
    except Exception as e:                              # noqa: BLE001
        logger.warning(f"Маска '{stem}' не вышла: {e}", exc_info=True)
        return None
    return png if png.exists() else None


def normal_with_mask(mask_png: Path, mat: str, vmt_path: Path, out_dir: Path,
                      cdmaterials: str, size: Tuple[int, int],
                      base_image_path: Optional[str],
                      read_texture: Optional[Callable[[str], Optional[bytes]]]) -> bool:
    """
    {mat}_normal.vtf = нормаль (RGB) + маска в альфе; $bumpmap - на неё

    RGB нормали - по старшинству: уже собранная нами (галка Normal Map,
    рельеф поверх родного), родная нормаль материала (`read_texture` по
    его $bumpmap - из мода или игры), иначе построенная из базы. Так маска
    не стирает рельеф предмета, как стёрла бы «нормаль из диффуза»
    """
    import numpy as np
    from PIL import Image

    from src.services import normal_map, vmt_parse

    out_dir = Path(out_dir)
    ours = out_dir / f"{mat}_normal.vtf"
    if ours.exists() and _vtf_frames(ours) > 1:
        # Многокадровый рельеф (гифка + Normal Map): маска на первом кадре
        # заморозила бы его. Оставляем как есть
        logger.warning(f"[{mat}] нормаль анимирована - маску в её альфу не кладём")
        return False
    rgba = None
    try:
        if ours.exists():
            rgba = normal_map.rgba_from_vtf(ours.read_bytes())
        if rgba is None and read_texture:
            text = Path(vmt_path).read_text(encoding="utf-8", errors="ignore")
            bump = vmt_parse.parse(text).path("$bumpmap")
            data = read_texture(bump) if bump else None
            rgba = normal_map.rgba_from_vtf(data) if data else None
        if rgba is None:
            if not (base_image_path and os.path.isfile(base_image_path)):
                return False
            with Image.open(base_image_path) as base:
                rgb = np.asarray(base.convert("RGB").resize(tuple(size), Image.LANCZOS))
            rgba = normal_map.encode(normal_map.from_image(rgb), None)
        rows, cols = rgba.shape[:2]
        with Image.open(mask_png) as mask:
            alpha = np.asarray(mask.convert("L").resize((cols, rows), Image.LANCZOS))
        rgba = rgba.copy()
        rgba[..., 3] = alpha
        png = out_dir / f"{mat}_normal.png"
        Image.fromarray(rgba, "RGBA").save(png)
        # DXT5 хранит альфу, флаг NORMAL - как у нормалей Valve
        TextureService.create_vtf(str(png), str(out_dir), "DXT5", ["NORMAL"], {})
        png.unlink(missing_ok=True)
    except Exception as e:                              # noqa: BLE001
        logger.warning(f"[{mat}] нормаль с маской не вышла: {e}", exc_info=True)
        return False
    if not ours.exists():
        return False
    VMTService.update_vmt_bumpmap_path(str(vmt_path), cdmaterials, f"{mat}_normal")
    logger.info(f"[{mat}] маска положена в альфу нормали")
    return True


def _vtf_frames(path: Path) -> int:
    """Число кадров VTF из заголовка (uint16 по смещению 24, VTF 7.x)"""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
        return int.from_bytes(head[24:26], "little") if head[:4] == b"VTF\0" else 1
    except OSError:
        return 1


def mask_params(vmt_path: Path, cdmaterials: str, mat: str, extra: dict,
                 out_dir: Path) -> bool:
    """Параметры для маски в альфе нормали. $basemapalphaphongmask (у 2105
    материалов TF2) снимается: при нём движок берёт и маску отражения из
    альфы основы (вики Valve, $normalmapalphaenvmapmask), и наша маска
    молча не работала бы. Синий VMT смотрит на ту же нормаль красного"""
    if not (Path(out_dir) / f"{mat}_normal.vtf").exists():
        return False
    VMTService.update_vmt_bumpmap_path(str(vmt_path), cdmaterials, f"{mat}_normal")
    if VMTService.remove_param(str(vmt_path), "$basemapalphaphongmask"):
        logger.info(f"[{mat}] $basemapalphaphongmask снят: маска блеска теперь в альфе нормали")
    if extra and "$envmap" in extra:
        from src.services import vmt_parse
        text = Path(vmt_path).read_text(encoding="utf-8", errors="ignore")
        if vmt_parse.parse(text).get("$envmap") is not None:
            # Окружение предмета (золото, студийный блик) не подменяем
            extra = {k: v for k, v in extra.items() if k != "$envmap"}
    if extra:
        VMTService.add_material_map_params(str(vmt_path), cdmaterials, None, None, extra)
    return True


def ensure_derived_normal(
    base_image_path: str,
    vtf_output_path: Path,
    texture_filename: str,
    vmt_path: Path,
    patched_cdmaterials_path: str,
    size: Tuple[int, int],
    is_normal_map: bool,
) -> None:
    """
    Гарантирует наличие карты нормалей для phong (без неё блик не считается)

    Если normal уже сгенерирован (галочка Normal Map) или файл уже есть -
    ничего не делает. Иначе строит {texture}_normal.vtf из базовой текстуры
    (normal_map, формат DXT5) и прописывает $bumpmap в VMT
    """
    normal_vtf = vtf_output_path / f"{texture_filename}_normal.vtf"
    if is_normal_map or normal_vtf.exists():
        return
    try:
        norm_png = vtf_output_path / f"{texture_filename}_normal.png"
        TextureService.process_image(base_image_path, str(norm_png), size)
        TextureService.write_normal_png(norm_png, norm_png)
        TextureService.create_vtf(str(norm_png), str(vtf_output_path), "DXT5", ["NORMAL"], {})
        if norm_png.exists():
            norm_png.unlink()
        if normal_vtf.exists():
            VMTService.update_vmt_bumpmap_path(
                str(vmt_path), patched_cdmaterials_path, f"{texture_filename}_normal"
            )
            logger.info(f"Авто-нормаль для phong создана: {normal_vtf.name}")
    except Exception as e:
        logger.warning(f"Не удалось создать авто-нормаль для phong: {e}", exc_info=True)


def compose_exponent(mat: str, vmt_path: Path, out_dir: Path,
                      read_texture: Optional[Callable[[str], Optional[bytes]]],
                      albedo: Optional[float], rim_mask: Optional[Path],
                      own_exp: bool = False) -> bool:
    """{mat}_exp.vtf с G = сила окраски и A = маска обводки

    Основа (R - размер блика) - по старшинству: Phong-карта, собранная
    этой же сборкой (`own_exp`; файл с тем же именем из мода - не наш, он
    мог быть снят), Phong-карта материала (`read_texture`), иначе ровная из
    его $phongexponent (R = (e − 1) / 149, обратная к 1 + 149·R шейдера;
    при заданном $phongexponent R всё равно не читается)

    G: у родной Phong-карты с $phongalbedotint зелёный - поканальная маска
    Valve (металл окрашен, дерево нет): её масштабируем, а не заливаем"""
    import numpy as np
    from PIL import Image

    from src.services import normal_map, vmt_parse

    out_dir = Path(out_dir)
    ours = out_dir / f"{mat}_exp.vtf"
    doc = vmt_parse.parse(Path(vmt_path).read_text(encoding="utf-8", errors="ignore"))
    try:
        rgba = None
        stock_mask = False
        if own_exp and ours.exists():
            rgba = normal_map.rgba_from_vtf(ours.read_bytes())
        if rgba is None and read_texture and doc.path("$phongexponenttexture"):
            data = read_texture(doc.path("$phongexponenttexture"))
            rgba = normal_map.rgba_from_vtf(data) if data else None
            stock_mask = rgba is not None and doc.flag("$phongalbedotint")
        if rgba is None:
            exponent = doc.number("$phongexponent", 5.0) or 5.0
            exponent = exponent if exponent > 0 else 5.0
            side = 64
            if rim_mask is not None:
                with Image.open(rim_mask) as m:
                    side = max(m.size)
            rgba = np.zeros((side, side, 4), np.uint8)
            rgba[..., 0] = int(round(min(1.0, max(0.0, (exponent - 1) / 149.0)) * 255))
            rgba[..., 3] = 255
        rgba = rgba.copy()
        rows, cols = rgba.shape[:2]
        if albedo is not None:
            if stock_mask:
                rgba[..., 1] = np.round(rgba[..., 1] * albedo).astype(np.uint8)
            else:
                rgba[..., 1] = int(round(albedo * 255))
        if rim_mask is not None:
            with Image.open(rim_mask) as m:
                rgba[..., 3] = np.asarray(m.convert("L").resize((cols, rows), Image.LANCZOS))
        png = out_dir / f"{mat}_exp.png"
        Image.fromarray(rgba, "RGBA").save(png)
        TextureService.create_vtf(str(png), str(out_dir), "DXT5", [], {})
        png.unlink(missing_ok=True)
    except Exception as e:                              # noqa: BLE001
        logger.warning(f"[{mat}] Phong-карта по каналам не вышла: {e}", exc_info=True)
        return False
    return ours.exists()
