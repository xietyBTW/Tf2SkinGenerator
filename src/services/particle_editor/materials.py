"""Материалы систем: текстуры для превью, смена материала у систем"""

import base64
import io
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

from src.services import vmt_parse
from src.services.particle_editor.pcf_format import Attribute, norm_mat
from src.services.particle_editor.vtf_sheet import parse_vtf_sheet
from src.services.tf2_paths import TF2Paths
from src.services.vtf_preview_service import open_vpks, read_from_vpks
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Режимы Sprite-шейдера, которые складывают цвет с фоном: 3 glow, 5 add,
#: 7 add frame blend, 8 alpha add, 9 world glow (RenderMode_t). У таких VMT
#: «$additive» часто не написан, а текстура без альфы - без этого она
#: рисовалась чёрным квадратом
_ADDITIVE_SPRITE_MODES = (3, 5, 7, 8, 9)


def _is_additive(vmt) -> bool:
    if vmt.flag("additive"):
        return True
    return int(vmt.number("spriterendermode", 0) or 0) in _ADDITIVE_SPRITE_MODES


# Якорь по началу строки: иначе матчились закомментированные строки и ссылки
# на $basetexture внутри proxies; хвостовой //-комментарий отсекается.
# \r?$ обязателен: VMT Valve с CRLF-концами строк.
#: Только для ЗАМЕНЫ строки $basetexture в тексте VMT. Чтение - через
#: vmt_parse: регулярка не отличает настоящий параметр от закомментированного
_RE_BASETEXTURE_LINE = re.compile(
    r'^[ \t]*"?\$basetexture"?[ \t]+"?([^"\r\n]+?)"?[ \t]*(?://[^\r\n]*)?\r?$',
    re.IGNORECASE | re.MULTILINE)


def _mtime(path: Optional[str]) -> int:
    """mtime файла в наносекундах, нет файла - ноль"""
    try:
        return os.stat(path).st_mtime_ns if path else 0
    except OSError:
        return 0


def set_material_to_game(pcf, old_material: str, game_material: str) -> bool:
    """
    Переводит все системы с материалом old_material на СУЩЕСТВУЮЩИЙ игровой
    материал game_material (просто меняет строку - новый файл не создаётся).
    Работает в казуале: игра уже содержит этот материал
    """
    def _norm(m: str) -> str:
        return m.replace("\\", "/").lower()

    target = _norm(old_material)
    changed = False
    for el in pcf._all_definition_elements():
        if "material" in el and _norm(el["material"].val_str) == target:
            el["material"] = Attribute.string(
                el["material"].name, game_material)
            changed = True
    return changed


def material_names(pcf) -> List[str]:
    """Уникальные пути материалов всех систем (как записаны в PCF)"""
    names = []
    for _name, sys_json in pcf.systems_json().items():
        mat = sys_json["attrs"].get("material", {}).get("v")
        if mat and mat not in names:
            names.append(mat)
    return names


def materials_json(pcf, tf2_root_dir: str, cancel_check=None,
                   names: Optional[List[str]] = None) -> Dict[str, dict]:
    """
    Резолвит материалы систем в текстуры для JS:
    {mat: {"dataUrl": png, "sheet": {...}|None, "additive": bool,
           "shader": str, "width": int, "height": int}}

    Ошибки не фатальны - система без текстуры рендерится белым спрайтом.
    cancel_check: колбэк () -> bool; True - прервать (для фоновых воркеров).
    names: только эти материалы (эффект, а не весь файл): у item_fx их 96,
    и распаковка всех VTF при первом открытии - полторы секунды из двух
    """
    # Перезаписанные текстуры - превью-инфо по нормализованному ключу
    out: Dict[str, dict] = {}
    names = material_names(pcf) if names is None else list(names)
    for mat in names:
        ck = norm_mat(mat)
        if ck in pcf._custom_material_info:
            out[mat] = pcf._custom_material_info[ck]
    try:
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
    except FileNotFoundError:
        return out
    textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
    # hl2-VPK обязательны: часть particle-материалов (particle_glow_* и
    # др.) лежит в контенте HL2, который TF2 монтирует
    vpks = [misc_vpk, textures_vpk] + TF2Paths.resolve_hl2_vpks(tf2_root_dir)
    paks = None
    # Стоковые материалы одни на все PCF и не меняются между загрузками:
    # `effects/…` повторяются из файла в файл, а VTF->PNG стоил три
    # четверти времени открытия. Ключ с mtime архива: обновление игры
    # подменяет VPK, и старая картинка его не переживёт
    stamp = tuple(_mtime(v) for v in vpks)
    cache = _stock_material_cache
    if cache.get('stamp') != stamp:
        cache.clear()
        cache['stamp'] = stamp

    for mat in names:
        if cancel_check is not None and cancel_check():
            break
        if mat in out:
            continue
        ck = norm_mat(mat)
        if ck in cache:
            if cache[ck] is not None:
                out[mat] = cache[ck]
            continue
        if paks is None:
            paks = open_vpks(vpks)
        info = _resolve_material(paks, mat)
        cache[ck] = info
        if info is not None:
            out[mat] = info
    return out


#: Разобранные стоковые материалы: {норм. путь: info | None} плюс
#: `stamp` - mtime архивов, для которых они разобраны
_stock_material_cache: Dict[str, Any] = {}


def _resolve_material(paks: list, mat: str) -> Optional[dict]:
    # Путь строим той же нормализацией, что и ключ материала: иначе
    # искали бы в архиве не то, с чем потом сопоставляем
    vmt_rel = "materials/" + norm_mat(mat)

    vmt_raw = read_from_vpks(paks, vmt_rel)
    if vmt_raw is None:
        logger.warning(f"VMT не найден: {vmt_rel}")
        return None
    vmt_text = vmt_raw.decode("utf-8", errors="replace")

    vmt = vmt_parse.parse(vmt_text)
    shader = vmt.shader
    base = vmt.path("basetexture")
    if not base:
        # Материалы без $basetexture (vgui/white и т.п.) - однотонный квад
        # с вершинным цветом, важно сохранить хотя бы режим блендинга
        return {
            "dataUrl": None,
            "sheet": None,
            "additive": _is_additive(vmt),
            "mod2x": vmt.flag("mod2x"),
            "shader": shader,
            # Refract без искажения и размытия (nothing2, effect_mask,
            # skullmask - 8 материалов в стоке) в игре невидим: это маска,
            # которая прячет частицы за собой. Рисовать за него мягкий
            # белый круг значило показывать «белый шар»
            "invisible": (shader.lower() == "refract"
                          and not vmt.number("refractamount", 0)
                          and not vmt.number("bluramount", 0)),
            "width": 0,
            "height": 0,
        }
    vtf_rel = "materials/" + norm_mat(base, ".vtf")

    vtf_raw = read_from_vpks(paks, vtf_rel)
    if vtf_raw is None:
        logger.warning(f"VTF не найден: {vtf_rel}")
        return None

    png = _vtf_to_png(vtf_raw)
    if png is None:
        return None
    data_url, width, height = png
    return {
        "dataUrl": data_url,
        "sheet": parse_vtf_sheet(vtf_raw),
        "additive": _is_additive(vmt),
        # Модуляция (glow_modulate, beam_generic_3_modulate): цвет
        # УМНОЖАЕТ фон ×2, серый - нейтрален. Через обычный бленд такой
        # спрайт виден серым квадратом
        "mod2x": vmt.flag("mod2x"),
        "shader": shader,
        "width": width,
        "height": height,
    }


def _vtf_to_png(vtf_raw: bytes) -> Optional[tuple]:
    """VTF-байты -> (data URL PNG, w, h). VTFLib читает только с диска -
    пишем во временный файл"""
    tmp_path = None
    try:
        from PIL import Image
        from src.services.vtflib_wrapper import VTFLib
        fd, tmp_path = tempfile.mkstemp(suffix=".vtf")
        with os.fdopen(fd, "wb") as f:
            f.write(vtf_raw)
        rgba, w, h = VTFLib.read_vtf_as_rgba(tmp_path)
        buf = io.BytesIO()
        # Сжатие послабее: уровень 3 против 6 - 2 мс вместо 29 на текстуру
        # 256², а картинка тяжелее лишь на десятую часть
        Image.frombytes("RGBA", (w, h), rgba).save(buf, format="PNG",
                                                   compress_level=3)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}", w, h
    except Exception as exc:
        logger.warning(f"VTF→PNG не удался: {exc}")
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def additive_card_url(data_url: str) -> str:
    """Картинка для карточки аддитивного материала: то, что спрайт складывает
    с фоном, - цвет, умноженный на альфу, на чёрном

    Альфа у таких текстур бывает почти пустой (wispy_smoke_add: не выше 37 из
    255), и карточка рисовала дым прозрачным - белый пропадал на любом фоне.
    Цвет у неё же почти ровный, форма лежит в альфе, поэтому альфу растягиваем
    до полной: в игре яркость набирают десятки наложенных частиц
    """
    try:
        from PIL import Image, ImageChops
        raw = base64.b64decode(data_url.split(",", 1)[1])
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        alpha = img.getchannel("A")
        top = alpha.getextrema()[1]
        # Совсем пустая альфа - текстура без неё, цвет и есть картинка
        alpha = (alpha.point(lambda v: v * 255 // top) if top
                 else Image.new("L", img.size, 255))
        lit = ImageChops.multiply(img.convert("RGB"),
                                  Image.merge("RGB", (alpha, alpha, alpha)))
        buf = io.BytesIO()
        lit.save(buf, format="PNG", compress_level=3)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.warning(f"картинка карточки не получилась: {exc}")
        return data_url


def rename_material(pcf, old_material: str, new_material: str) -> bool:
    """
    Меняет путь материала у всех систем, где он используется

    Если текстура была заменена своей картинкой, кастомные файлы
    переезжают на новый путь (и VMT начинает ссылаться на новый VTF) -
    так эффект получает СВОЙ материал вместо перезаписи стокового,
    и замена перестаёт менять текстуру у других эффектов игры
    """
    new_material = (new_material or "").strip()
    if not new_material or not old_material:
        return False
    old_key, new_key = norm_mat(old_material), norm_mat(new_material)
    if old_key == new_key:
        return False

    changed = False
    for el in pcf._all_definition_elements():
        if "material" not in el:
            continue
        try:
            if norm_mat(el["material"].val_str) != old_key:
                continue
        except Exception:
            continue
        el["material"] = Attribute.string(
            el["material"].name, new_material)
        changed = True
    if not changed:
        return False

    entry = pcf._overwritten.pop(old_key, None)
    if entry is not None:
        old_tex = entry["tex_rel"]
        new_tex = new_key[:-4] if new_key.endswith(".vmt") else new_key
        vtf = pcf.custom_files.pop(f"materials/{old_tex}.vtf", None)
        vmt = pcf.custom_files.pop(f"materials/{old_key}", None)
        if vtf is not None:
            pcf.custom_files[f"materials/{new_tex}.vtf"] = vtf
        if vmt is not None:
            text = vmt.decode("utf-8", errors="replace")
            text = _RE_BASETEXTURE_LINE.sub(
                f'\t"$basetexture" "{new_tex}"', text)
            pcf.custom_files[f"materials/{new_key}"] = text.encode("utf-8")
        pcf._overwritten[new_key] = {
            "tex_rel": new_tex, "material": new_material}
        info = pcf._custom_material_info.pop(old_key, None)
        if info is not None:
            pcf._custom_material_info[new_key] = info
    return True
