"""
Свои настройки карт: отражение ($envmap, оттенок, френель), свечение
($selfillumtint, пульсация, контур) и каналы Phong-карты (цвет блика,
маска обводки)
"""

import os
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.services.vmt_service import VMTService
from src.shared.logging_config import get_logger

from . import map_textures

logger = get_logger(__name__)

#: Метка наших прокси свечения: по ней их снимает повторная сборка
_GLOW_MARK = "// tf2sg glow"


def _vmt_io_read(path: str):
    from src.services.vmt_service import _read_vmt
    return _read_vmt(path)


def _vmt_io_write(path: str, text: str, encoding: str) -> None:
    from src.services.vmt_service import _write_vmt
    _write_vmt(path, text, encoding)


def _rgb(hex_colour: str):
    return [int(hex_colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]


def _srgb_to_linear(values):
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in values]


def _vec(values):
    return "[%.3f %.3f %.3f]" % tuple(values)


def _doc(vmt_path):
    from src.services import vmt_parse
    return vmt_parse.parse(Path(vmt_path).read_text(encoding="utf-8", errors="ignore"))


def _native(vmt_path, name: str):
    """Вектор параметра материала: [r g b] - доли, {r g b} - 0..255.
    Значения выше 1 сохраняются (у Valve $selfillumtint бывает [2 .5 .1])"""
    import re
    raw = _doc(vmt_path).get(name) or ""
    nums = [float(n) for n in re.findall(r"-?\d*\.?\d+", raw)][:3]
    if len(nums) == 1:
        nums = nums * 3                       # «$envmaptint 0.5» - на все каналы
    if len(nums) != 3:
        return None
    return [n / 255.0 for n in nums] if "{" in raw else nums


def apply_settings(entries: dict, mat: str, vmt_path: Path, out_dir: Path,
                   cdmaterials: str, size: Tuple[int, int],
                   base_image_path: Optional[str], is_normal_map: bool,
                   params_only: bool, was_phong: Optional[bool] = None) -> None:
    """
    Свои настройки отражения и свечения (MATERIAL_MAPS[…]["settings"]).
    Пустое поле - «как у материала»: в VMT ничего не пишется

    Отражение: окружение ($envmap), цвет и сила ($envmaptint - без phong
    игра возводит его в степень 2.2, с phong берёт как есть), френель ($envmapfresnel,
    на ветке TF2 считается только при $phong).
    Свечение: цвет и яркость ($selfillumtint) через свой прокси в конце
    блока - так он перебивает родные прокси свечения (у многих вещей
    Equals $glowcolor -> $selfillumtint), пульсация - Sine × Multiply, как у
    Valve; контур - $selfillumfresnel (нужен $bumpmap)
    """
    if was_phong is None:
        was_phong = _doc(vmt_path).flag("$phong")
    env = entries.get("envmapmask") or {}
    _reflection(env, mat, vmt_path, cdmaterials)
    glow = entries.get("selfillum") or {}
    _glow_tint(glow, mat, vmt_path)
    if glow.get("glow_edge") == "on":
        _glow_edge(glow, mat, vmt_path, out_dir, cdmaterials, size,
                   base_image_path, is_normal_map, params_only)
    _envmap_tint(env, mat, vmt_path, cdmaterials, was_phong)


def _reflection(env: dict, mat: str, vmt_path: Path, cdmaterials: str) -> None:
    """Окружение ($envmap) и «сильнее по краю» ($envmapfresnel)"""
    from src.data.material_maps import CUBEMAPS
    params = {}
    if env.get("env_cubemap") in CUBEMAPS:
        params["$envmap"] = CUBEMAPS[env["env_cubemap"]]
    if env.get("env_fresnel"):
        amount = float(env["env_fresnel"]) / 100.0
        params["$envmapfresnel"] = "%g" % amount
        if amount > 0:
            doc = _doc(vmt_path)
            if doc.get("$envmapmask") is not None and not doc.flag("$phong"):
                # С phong отдельная маска не читается (вики Valve) - маску
                # предмета не ломаем, френель без phong не считается
                params.pop("$envmapfresnel")
                logger.warning(f"[{mat}] «сильнее по краю» пропущено: у материала "
                               f"отдельная маска отражения, а с phong она не работает")
            elif map_textures.ensure_phong(vmt_path, cdmaterials):
                logger.info(f"[{mat}] $phong с силой 0: $envmapfresnel без него не считается")
    if params:
        VMTService.add_material_map_params(str(vmt_path), cdmaterials, None, None, params)


def _glow_tint(glow: dict, mat: str, vmt_path: Path) -> None:
    """Цвет, яркость и пульсация свечения ($selfillumtint через свои прокси)"""
    from src.services import vmt_effects
    if glow and _doc(vmt_path).flag("$blendtintbybasealpha"):
        # skin_ps20b.fxc: «SKIP: ($BLENDTINTBYBASEALPHA) && ($SELFILLUM)» -
        # такой комбинации шейдера нет, у красящихся вещей свечения не будет
        logger.warning(f"[{mat}] самосвечение не работает с покраской по альфе "
                       f"($blendtintbybasealpha) - в игре его не будет")
    pulse = glow.get("glow_pulse", "off")
    pulsing = pulse in ("slow", "medium", "fast")
    if not (glow.get("glow_color") or glow.get("glow_power") or pulsing):
        return
    power = float(glow.get("glow_power", 100)) / 100.0
    # Цвет не выбран - родной цвет свечения материала, а не белый.
    # $selfillumtint движок берёт как есть, без перевода из гаммы
    # (SetPixelShaderConstant_W, в отличие от $envmaptint), - цвет из
    # палитры переводим в линейный сами, иначе он выходил бледнее
    base = (_srgb_to_linear(_rgb(glow["glow_color"])) if glow.get("glow_color")
            else _native(vmt_path, "$selfillumtint") or [1.0, 1.0, 1.0])
    tint = _vec([c * power for c in base])
    text, encoding = _vmt_io_read(str(vmt_path))
    text = vmt_effects._strip_marked_proxies(text, _GLOW_MARK)
    text = VMTService._set_vmt_param(text, "$selfillumtint", tint)
    tail = ""
    if pulsing:
        period = {"slow": 3.0, "medium": 1.5, "fast": 0.6}[pulse]
        low = float(glow.get("glow_pulse_min", 30)) / 100.0
        text = VMTService._set_vmt_param(text, "$tf2sg_glow", tint)
        text = VMTService._set_vmt_param(text, "$tf2sg_pulse", "1")
        tail = (vmt_effects._proxy("Sine", [
                    ("sineperiod", "%g" % period), ("sinemin", "%g" % low),
                    ("sinemax", "1"), ("resultVar", "$tf2sg_pulse")], _GLOW_MARK)
                + vmt_effects._proxy("Multiply", [
                    ("srcVar1", "$tf2sg_glow"), ("srcVar2", "$tf2sg_pulse"),
                    ("resultVar", "$selfillumtint")], _GLOW_MARK))
    elif glow.get("glow_color"):
        # Свой цвет перебивает родные прокси свечения (Equals
        # $glowcolor -> $selfillumtint) - наш Equals в конце блока.
        # Только яркость - без прокси: родные эффекты не трогаем
        text = VMTService._set_vmt_param(text, "$tf2sg_glow", tint)
        tail = vmt_effects._proxy("Equals", [
            ("srcVar1", "$tf2sg_glow"), ("resultVar", "$selfillumtint")], _GLOW_MARK)
    if tail:
        text = vmt_effects._add_proxies(text, "", tail)
    _vmt_io_write(str(vmt_path), text, encoding)


def _glow_edge(glow: dict, mat: str, vmt_path: Path, out_dir: Path, cdmaterials: str,
               size, base_image_path, is_normal_map: bool, params_only: bool) -> None:
    """Затухание свечения к краю ($selfillumfresnel, нужен $bumpmap)"""
    bright = float(glow.get("edge_bright", 5))
    sharp = float(glow.get("edge_sharp", 8))
    doc = _doc(vmt_path)
    if doc.get("$bumpmap") is None:
        # Вики Valve: $selfillumfresnel требует $bumpmap. Синий - на
        # нормаль красного, если она собрана
        if params_only:
            if (Path(out_dir) / f"{mat}_normal.vtf").exists():
                VMTService.update_vmt_bumpmap_path(str(vmt_path), cdmaterials,
                                                   f"{mat}_normal")
        elif base_image_path and os.path.isfile(base_image_path):
            map_textures.ensure_derived_normal(
                base_image_path, out_dir, mat, vmt_path, cdmaterials, size, is_normal_map)
        doc = _doc(vmt_path)
    if doc.get("$bumpmap") is None:
        logger.warning(f"[{mat}] затухание свечения пропущено: нет карты нормалей "
                       f"и не из чего её построить")
        return
    if doc.flag("$normalmapalphaenvmapmask") or doc.get("$envmapmask") is not None:
        logger.warning(f"[{mat}] затухание свечения отключает маску отражения "
                       f"(вики Valve, $selfillumfresnel)")
    if doc.get("$selfillummask") is not None:
        # skin_ps20b.fxc: в режиме френеля вес - baseColor.a * френель,
        # маска $selfillummask не читается
        logger.warning(f"[{mat}] при затухании к краю игра берёт маску свечения из "
                       f"альфы основной текстуры, а не из карты самосвечения")
    if doc.get("$lightwarptexture") is not None or doc.get("$detail") is not None:
        if map_textures.ensure_phong(vmt_path, cdmaterials):
            logger.info(f"[{mat}] $phong с силой 0: контур свечения с lightwarp/detail "
                        f"без него не работает")
    VMTService.add_material_map_params(str(vmt_path), cdmaterials, None, None, {
        "$selfillumfresnel": "1",
        "$selfillumfresnelminmaxexp": "[0 %g %g]" % (bright, sharp)})


def _envmap_tint(env: dict, mat: str, vmt_path: Path, cdmaterials: str,
                 was_phong: bool) -> None:
    """
    $envmaptint - последним, когда $phong уже окончательный (его включают
    карты, френель отражения и контур свечения)

    Phong-материал берёт $envmaptint линейным (skin_dx9_helper.cpp), без
    phong движок переводит его из гаммы, возводя в 2.2
    (vertexlitgeneric_dx9_helper.cpp). Цвет палитры пишем так, чтобы в
    шейдер пришло одно и то же: цвет в линейном × сила. Родной оттенок
    материала написан под его прежний phong: если сборка phong включила,
    переводим его в линейный сами, иначе отражение стало бы ярче
    """
    doc = _doc(vmt_path)
    phong = doc.flag("$phong")
    own = _native(vmt_path, "$envmaptint")
    if own is not None and phong and not was_phong:
        own = [c ** 2.2 if c > 0 else c for c in own]
    if env.get("env_tint") or env.get("env_strength"):
        k = float(env.get("env_strength", 100)) / 100.0
        scale = k if phong else k ** (1 / 2.2)
        if env.get("env_tint"):
            base = _rgb(env["env_tint"])
            base = _srgb_to_linear(base) if phong else base
        else:
            # Цвет не выбран - оттенок материала (у золота он тёплый),
            # иначе «Сила» перекрашивала бы его в серебро
            base = own or [1.0, 1.0, 1.0]
        tint = [c * scale for c in base]
    elif own is not None and phong and not was_phong and doc.get("$envmap") is not None:
        tint = own
        logger.info(f"[{mat}] $envmaptint переведён в линейный: материал стал phong")
    else:
        return
    VMTService.add_material_map_params(str(vmt_path), cdmaterials, None, None,
                                       {"$envmaptint": _vec(tint)})


def phong_channels(material_maps: dict, mat: str, vmt_path: Path, out_dir: Path,
                    cdmaterials: str, size: Tuple[int, int],
                    base_image_path: Optional[str],
                    read_texture: Optional[Callable[[str], Optional[bytes]]],
                    params_only: bool, red: Optional[dict], result: dict) -> None:
    """
    «Цвет блика» и маска Rim light - каналы Phong-карты {mat}_exp

    Шейдер (skin_ps20b.fxc): оттенок блика = lerp(1, цвет текстуры, G) при
    $phongalbedotint, а $phongtint его отключает, обводка × lerp(1, A,
    $rimmask). Поэтому обе вещи живут в одной текстуре: G и A
    дописываются в нашу Phong-карту, в Phong-карту материала (из мода или
    игры) или в новую, если её не было

    Что не вышло - не трогает материал: маска не собралась - родная маска
    обводки на месте и цвет блика всё равно делается; Phong-карта не
    собралась - $phongtint материала не снят
    """
    from src.services.mod_textures import texture_key

    def active(entry):
        return bool(entry) and entry.get("enabled") and not (entry.get("mod") or entry.get("off"))

    colour = material_maps.get("phongcolor") or {}
    rim = material_maps.get("rimlight") or {}
    albedo = tint = None
    if active(colour):
        # «Как у предмета» - цвет блика не трогаем (карточка может быть
        # включена ради краёв блика)
        mode = colour.get("tint", "keep")
        if mode == "albedo":
            albedo = int(colour.get("tint_amount", 100)) / 100.0
        elif mode == "color":
            tint = colour.get("tint_color", "#ffc864")
        fresnel_ranges(colour, vmt_path, cdmaterials)
    # Нет выбора в записи (карта из старой работы) - маску материала не трогаем
    rim_mode = rim.get("rim_mask") if active(rim) else None

    mask = None
    if rim_mode in ("auto", "file"):
        if params_only:
            # Синий: маска та же, что у красного, - если она у него вышла
            if not (red and red.get("rim")):
                rim_mode = None
        else:
            spec = ({"image": rim.get("rim_image")} if rim_mode == "file"
                    else {"derive": True, "threshold": rim.get("rim_threshold")})
            mask = map_textures.mask_png(
                spec, "envmapmask", base_image_path, out_dir, f"{mat}_rim_src", size)
            if mask is None:
                logger.warning(f"[{mat}] маска обводки не вышла (нет файла или базы) - "
                               f"обводка как у материала")
                rim_mode = None
    result["rim"] = rim_mode in ("auto", "file")

    if tint:
        rgb = [int(tint[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        VMTService.remove_param(str(vmt_path), "$phongalbedotint")
        VMTService.add_material_map_params(
            str(vmt_path), cdmaterials, None, None,
            {"$phongtint": "[%.3f %.3f %.3f]" % tuple(rgb)})
    if rim_mode == "all":
        # «Везде» - значит и без родной маски обводки
        VMTService.remove_param(str(vmt_path), "$rimmask")

    if albedo is None and rim_mode not in ("auto", "file"):
        return

    if params_only:
        # Синий идёт за Phong-картой красного, если она у красного своя
        # (тогда синий уже смотрит на неё) или у них была одна и та же
        own = result.get("exp_tex")
        ok = bool(red and red.get("exp_extra")) and (
            bool(red.get("exp")) or own is None
            or texture_key(own) == texture_key(red.get("exp_tex") or ""))
    else:
        ok = map_textures.compose_exponent(
            mat, vmt_path, out_dir, read_texture, albedo, mask,
            own_exp=bool(result.get("exp")))
        result["exp_extra"] = ok
    if mask and mask.exists():
        mask.unlink()
    if not ok:
        logger.warning(f"[{mat}] Phong-карта для цвета блика / маски обводки не вышла - "
                       f"материал оставлен как был")
        return
    params = {}
    if albedo is not None:
        VMTService.remove_param(str(vmt_path), "$phongtint")
        params["$phongalbedotint"] = "1"
    if rim_mode in ("auto", "file"):
        params["$rimmask"] = "1"
    VMTService.add_material_map_params(
        str(vmt_path), cdmaterials, f"{mat}_exp", "$phongexponenttexture", params)


def fresnel_ranges(entry: dict, vmt_path: Path, cdmaterials: str) -> None:
    """«Где ярче блик» -> $phongfresnelranges [центр середина край].
    Незаданное - как у материала (у оружия TF2 свои значения), иначе
    [.25 .5 1] - так у 5922 материалов Valve"""
    import re

    from src.services import vmt_parse

    keys = ("fres_center", "fres_mid", "fres_edge")
    if not any(str(entry.get(k, "")).strip() for k in keys):
        return
    own = vmt_parse.parse(Path(vmt_path).read_text(encoding="utf-8", errors="ignore")
                          ).get("$phongfresnelranges") or ""
    nums = [float(n) for n in re.findall(r"-?\d*\.?\d+", own)][:3]
    current = nums if len(nums) == 3 else [0.25, 0.5, 1.0]
    values = [float(entry[k]) if str(entry.get(k, "")).strip() else current[i]
              for i, k in enumerate(keys)]
    VMTService.add_material_map_params(
        str(vmt_path), cdmaterials, None, None,
        {"$phongfresnelranges": "[%g %g %g]" % tuple(values)})
