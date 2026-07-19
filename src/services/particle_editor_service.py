"""
Сервис редактора частиц: PCF ⇄ JSON для JS-движка превью + правка атрибутов.

Схема работы:
    • PCF загружается через srctools.dmx (из файла или из tf2_misc_dir.vpk);
      Element-дерево — единственный источник правды о данных.
    • Для JS-движка превью дерево конвертируется в JSON: каждая система —
      атрибуты + модули (initializers/operators/emitters/renderers/forces/
      constraints) + children (по имени). Каждый атрибут — {"t": тип, "v": знач}:
      один формат читают и JS-движок, и Qt-редактор свойств.
    • Материалы систем резолвятся в текстуры: VMT (regex $basetexture) →
      VTF из tf2_textures_dir.vpk / tf2_misc_dir.vpk → PNG data URL через VTFLib.
      Sheet-данные (спрайт-листы частиц) парсятся из ресурса VTF 0x10 напрямую.
    • Правки применяются к Element-дереву (set_attr) и сохраняются обратно
      в бинарный PCF с исходным encoding/format (как в CritPcfService).
"""

import base64
import io
import os
import re
import struct
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.crit_pcf_service import CritPcfService
from src.services.tf2_paths import TF2Paths
from src.services.vtf_preview_service import open_vpks, read_from_vpks
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

try:
    from srctools.dmx import Attribute, Element, ValueType
    SRCTOOLS_AVAILABLE = True
except ImportError:
    SRCTOOLS_AVAILABLE = False
    Attribute = Element = ValueType = None  # type: ignore

#: Группы модулей внутри определения системы частиц.
MODULE_GROUPS = (
    "renderers", "operators", "initializers", "emitters", "forces", "constraints",
)

# Якорь по началу строки: иначе матчились закомментированные строки и ссылки
# на $basetexture внутри proxies; хвостовой //-комментарий отсекается.
# \r?$ обязателен: VMT Valve с CRLF-концами строк.
_RE_BASETEXTURE = re.compile(
    r'^[ \t]*"?\$basetexture"?[ \t]+"?([^"\r\n]+?)"?[ \t]*(?://[^\r\n]*)?\r?$',
    re.IGNORECASE | re.MULTILINE)
_RE_ADDITIVE = re.compile(r'"?\$additive"?\s+"?1"?', re.IGNORECASE)
_RE_SHADER = re.compile(r'^\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*$', re.MULTILINE)


# ── Конвертация атрибутов DMX → JSON ─────────────────────────────────────── #

def _attr_scalar_to_json(attr) -> Any:
    """Значение скалярного атрибута → JSON-совместимое значение."""
    vt = attr.type
    if vt is ValueType.COLOR:
        c = attr.val_color
        return [c.r, c.g, c.b, c.a]
    if vt is ValueType.BOOL:
        return attr.val_bool
    if vt is ValueType.INTEGER:
        return attr.val_int
    if vt in (ValueType.FLOAT, ValueType.TIME):
        return attr.val_float
    if vt is ValueType.STRING:
        return attr.val_str
    return None


def _attr_to_json(attr) -> Optional[dict]:
    """Атрибут DMX → {"t": тип, "v": значение} либо None для несериализуемых."""
    vt = attr.type
    if vt in (ValueType.ELEMENT, ValueType.BINARY, ValueType.MATRIX,
              ValueType.QUATERNION):
        return None
    type_name = vt.name.lower()
    if attr.is_array:
        if vt is ValueType.FLOAT:
            return {"t": "float_array", "v": list(attr.iter_float())}
        if vt is ValueType.INTEGER:
            return {"t": "int_array", "v": list(attr.iter_int())}
        return None
    if vt is ValueType.VEC3:
        return {"t": "vec3", "v": list(attr.val_vec3)}
    if vt is ValueType.VEC2:
        return {"t": "vec2", "v": list(attr.val_vec2)}
    if vt is ValueType.VEC4:
        return {"t": "vec4", "v": list(attr.val_vec4)}
    val = _attr_scalar_to_json(attr)
    if val is None and vt is not ValueType.STRING:
        return None
    return {"t": type_name, "v": val}


def _element_attrs_to_json(el) -> Dict[str, dict]:
    """Все скалярные атрибуты элемента → {имя: {"t","v"}} (модульные группы пропускаются)."""
    out: Dict[str, dict] = {}
    for key in el.keys():
        if key in MODULE_GROUPS or key == "children":
            continue
        j = _attr_to_json(el[key])
        if j is not None:
            out[key] = j
    return out


def _module_to_json(el) -> dict:
    """Модуль (оператор/инициализатор/...) → JSON с functionName и атрибутами."""
    attrs = _element_attrs_to_json(el)
    # srctools хранит имена атрибутов в нижнем регистре
    fn = attrs.get("functionname", {}).get("v") or el.name
    return {"functionName": fn, "name": el.name, "attrs": attrs}


# ── Sheet-данные из VTF ──────────────────────────────────────────────────── #

def parse_vtf_sheet(raw: bytes) -> Optional[dict]:
    """
    Извлекает sheet-данные (спрайт-лист частиц) из ресурса VTF 0x10.

    Формат VTF 7.3+: numResources по смещению 0x44, записи ресурсов с 0x50
    по 8 байт: тег (3 байта + флаг) и смещение данных. Тег 0x10 — sheet.
    Формат sheet: version(u32 0|1), sequenceCount(u32); на секвенцию:
    seqNo, clamp, frameCount (u32×3), totalDuration(f32); на кадр:
    duration(f32) + N×(u0,v0,u1,v1) f32, где N=4 при version=1 иначе 1.

    Returns:
        {"sequences": {seqNo: {"clamp": bool, "duration": float,
         "frames": [{"duration": float, "coords": [[u0,v0,u1,v1], ...]}]}}}
        либо None (нет ресурса / старая версия VTF / битые данные).
    """
    try:
        if len(raw) < 0x50 or raw[:4] != b"VTF\x00":
            return None
        ver_major, ver_minor = struct.unpack_from("<II", raw, 4)
        if ver_major != 7 or ver_minor < 3:
            return None
        (num_resources,) = struct.unpack_from("<I", raw, 0x44)
        sheet_offs = None
        for i in range(num_resources):
            entry = 0x50 + i * 8
            tag = raw[entry:entry + 3]
            flag = raw[entry + 3]
            (data_offs,) = struct.unpack_from("<I", raw, entry + 4)
            if tag == b"\x10\x00\x00" and flag != 0x02:
                sheet_offs = data_offs
                break
        if sheet_offs is None:
            return None

        (size,) = struct.unpack_from("<I", raw, sheet_offs)
        buf = raw[sheet_offs + 4: sheet_offs + 4 + size]
        pos = 0

        def u32():
            nonlocal pos
            (v,) = struct.unpack_from("<I", buf, pos)
            pos += 4
            return v

        def f32():
            nonlocal pos
            (v,) = struct.unpack_from("<f", buf, pos)
            pos += 4
            return v

        version = u32()
        if version not in (0, 1):
            return None
        coords_per_frame = 4 if version == 1 else 1
        sequences: Dict[int, dict] = {}
        for _ in range(u32()):
            seq_no = u32()
            clamp = u32() != 0
            frame_count = u32()
            total_duration = f32()
            frames = []
            for _f in range(frame_count):
                duration = f32()
                coords = []
                for _c in range(coords_per_frame):
                    coords.append([f32(), f32(), f32(), f32()])
                frames.append({"duration": duration, "coords": coords})
            sequences[seq_no] = {
                "clamp": clamp, "duration": total_duration, "frames": frames,
            }
        return {"sequences": sequences}
    except (struct.error, IndexError) as exc:
        logger.warning(f"Sheet-данные VTF не распарсились: {exc}")
        return None


# ── Сервис ───────────────────────────────────────────────────────────────── #

class ParticleEditorService:
    """Загрузка, конвертация, правка и сохранение PCF."""

    def __init__(self) -> None:
        self.root = None                       # корневой Element PCF
        self._encoding = (2, "pcf", 1)         # (enc_ver, fmt_name, fmt_ver)
        self.source_path: Optional[str] = None  # откуда загружен (файл или vpk:путь)
        #: Кастомные материалы (замена текстур): {rel_path: bytes} —
        #: и .vmt (текст), и .vtf (бинарь); попадают в превью и в экспорт VPK.
        self.custom_files: Dict[str, bytes] = {}
        #: Превью-инфо кастомных материалов: {имя материала из PCF: info-dict}.
        self._custom_material_info: Dict[str, dict] = {}

    # ── Загрузка ─────────────────────────────────────────────────────────── #

    def load_bytes(self, raw: bytes, source: str = "") -> None:
        """Парсит PCF из байтов (бросает исключение при ошибке)."""
        if not SRCTOOLS_AVAILABLE:
            raise RuntimeError("srctools не установлен (pip install srctools)")
        self._encoding = CritPcfService._detect_encoding(raw)
        self.root, _, _ = Element.parse(io.BytesIO(raw))
        self.source_path = source
        self.custom_files = {}
        self._custom_material_info = {}
        self._material_base_rel = {}
        self._material_original = {}   # кастомный материал → исходный из игры

    def load_file(self, path: str) -> None:
        self.load_bytes(Path(path).read_bytes(), source=path)

    def load_from_game(self, tf2_root_dir: str, vpk_path: str) -> None:
        """Загружает PCF по внутреннему пути из tf2_misc_dir.vpk."""
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        raw = read_from_vpks(open_vpks([misc_vpk]), vpk_path)
        if raw is None:
            raise FileNotFoundError(f"{vpk_path} не найден в {misc_vpk}")
        self.load_bytes(raw, source=f"vpk:{vpk_path}")

    @staticmethod
    def list_game_pcfs(tf2_root_dir: str) -> List[str]:
        """Список путей particles/*.pcf внутри tf2_misc_dir.vpk (отсортирован)."""
        try:
            _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        except FileNotFoundError:
            return []
        paks = open_vpks([misc_vpk])
        if not paks:
            return []
        out = []
        for pak in paks:
            try:
                for path in pak:
                    name = str(path)
                    if name.startswith("particles/") and name.endswith(".pcf"):
                        out.append(name)
            except Exception as exc:
                logger.warning(f"Не удалось перечислить PCF в VPK: {exc}")
        return sorted(set(out))

    # ── Определения систем ───────────────────────────────────────────────── #

    def _definitions(self) -> list:
        if self.root is None:
            return []
        try:
            return list(self.root["particleSystemDefinitions"].iter_elem())
        except KeyError:
            return []

    def system_names(self) -> List[str]:
        return [d.name for d in self._definitions()]

    def _find_definition(self, name: str):
        for d in self._definitions():
            if d.name == name:
                return d
        return None

    def _all_definition_elements(self) -> list:
        """Все определения систем: корневой список + достижимые через children
        (некоторые дочерние системы не значатся в корневом списке)."""
        out, seen, pending = [], set(), list(self._definitions())
        while pending:
            d = pending.pop(0)
            if id(d) in seen:
                continue
            seen.add(id(d))
            out.append(d)
            if "children" in d:
                try:
                    for ch in d["children"].iter_elem():
                        if "child" in ch:
                            try:
                                pending.append(ch["child"].val_elem)
                            except Exception:
                                pass
                except Exception:
                    pass
        return out

    def systems_json(self) -> Dict[str, dict]:
        """
        Все системы частиц → {имя: система} для JS-движка и редактора.

        children сериализуются как [{"delay": float, "childName": имя}];
        системы, на которые ссылаются только children (нет в корневом списке),
        добавляются в результат при обходе.
        """
        result: Dict[str, dict] = {}
        pending = list(self._definitions())
        while pending:
            d = pending.pop(0)
            if d.name in result:
                continue
            sys_json = {
                "name": d.name,
                "attrs": _element_attrs_to_json(d),
                "children": [],
            }
            for group in MODULE_GROUPS:
                mods = []
                if group in d:
                    try:
                        mods = [_module_to_json(m) for m in d[group].iter_elem()]
                    except Exception as exc:
                        logger.warning(f"{d.name}/{group}: {exc}")
                sys_json[group] = mods
            if "children" in d:
                try:
                    for ch in d["children"].iter_elem():
                        delay = 0.0
                        if "delay" in ch:
                            delay = ch["delay"].val_float
                        child_el = None
                        if "child" in ch:
                            try:
                                child_el = ch["child"].val_elem
                            except Exception:
                                child_el = None
                        if child_el is None:
                            continue
                        sys_json["children"].append(
                            {"delay": delay, "childName": child_el.name}
                        )
                        pending.append(child_el)
                except Exception as exc:
                    logger.warning(f"{d.name}/children: {exc}")
            result[d.name] = sys_json
        return result

    # ── Материалы ────────────────────────────────────────────────────────── #

    def material_names(self) -> List[str]:
        """Уникальные пути материалов всех систем (как записаны в PCF)."""
        names = []
        for _name, sys_json in self.systems_json().items():
            mat = sys_json["attrs"].get("material", {}).get("v")
            if mat and mat not in names:
                names.append(mat)
        return names

    def materials_json(self, tf2_root_dir: str, cancel_check=None) -> Dict[str, dict]:
        """
        Резолвит материалы систем в текстуры для JS:
        {mat: {"dataUrl": png, "sheet": {...}|None, "additive": bool,
               "shader": str, "width": int, "height": int}}.

        Ошибки не фатальны — система без текстуры рендерится белым спрайтом.
        cancel_check: колбэк () -> bool; True — прервать (для фоновых воркеров).
        """
        # Кастомные материалы (замена текстур) не зависят от установки TF2
        out: Dict[str, dict] = dict(self._custom_material_info)
        try:
            _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        except FileNotFoundError:
            return out
        textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
        # hl2-VPK обязательны: часть particle-материалов (particle_glow_* и
        # др.) лежит в контенте HL2, который TF2 монтирует
        paks = open_vpks(
            [misc_vpk, textures_vpk] + TF2Paths.resolve_hl2_vpks(tf2_root_dir))

        for mat in self.material_names():
            if cancel_check is not None and cancel_check():
                break
            if mat in out:
                continue
            info = self._resolve_material(paks, mat)
            if info is not None:
                out[mat] = info
        return out

    def _resolve_material(self, paks: list, mat: str) -> Optional[dict]:
        vmt_rel = mat.replace("\\", "/").lower()
        if not vmt_rel.endswith(".vmt"):
            vmt_rel += ".vmt"
        if not vmt_rel.startswith("materials/"):
            vmt_rel = "materials/" + vmt_rel

        vmt_raw = read_from_vpks(paks, vmt_rel)
        if vmt_raw is None:
            logger.warning(f"VMT не найден: {vmt_rel}")
            return None
        vmt_text = vmt_raw.decode("utf-8", errors="replace")

        shader_m = _RE_SHADER.search(vmt_text)
        shader = (shader_m.group(1).lower() if shader_m else "")
        base_m = _RE_BASETEXTURE.search(vmt_text)
        if not base_m:
            # Материалы без $basetexture (vgui/white и т.п.) — однотонный квад
            # с вершинным цветом; важно сохранить хотя бы режим блендинга
            return {
                "dataUrl": None,
                "sheet": None,
                "additive": bool(_RE_ADDITIVE.search(vmt_text)),
                "shader": shader,
                "width": 0,
                "height": 0,
            }
        vtf_rel = base_m.group(1).strip().replace("\\", "/").lower()
        if not vtf_rel.endswith(".vtf"):
            vtf_rel += ".vtf"
        if not vtf_rel.startswith("materials/"):
            vtf_rel = "materials/" + vtf_rel

        vtf_raw = read_from_vpks(paks, vtf_rel)
        if vtf_raw is None:
            logger.warning(f"VTF не найден: {vtf_rel}")
            return None

        png = self._vtf_to_png(vtf_raw)
        if png is None:
            return None
        data_url, width, height = png
        return {
            "dataUrl": data_url,
            "sheet": parse_vtf_sheet(vtf_raw),
            "additive": bool(_RE_ADDITIVE.search(vmt_text)),
            "shader": shader,
            "width": width,
            "height": height,
        }

    @staticmethod
    def _vtf_to_png(vtf_raw: bytes) -> Optional[tuple]:
        """VTF-байты → (data URL PNG, w, h). VTFLib читает только с диска —
        пишем во временный файл."""
        tmp_path = None
        try:
            from PIL import Image
            from src.services.vtflib_wrapper import VTFLib
            fd, tmp_path = tempfile.mkstemp(suffix=".vtf")
            with os.fdopen(fd, "wb") as f:
                f.write(vtf_raw)
            rgba, w, h = VTFLib.read_vtf_as_rgba(tmp_path)
            buf = io.BytesIO()
            Image.frombytes("RGBA", (w, h), rgba).save(buf, format="PNG")
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

    # ── Правка ───────────────────────────────────────────────────────────── #

    def set_attr(
        self,
        system_name: str,
        group: Optional[str],
        module_index: int,
        attr_name: str,
        value: Any,
    ) -> bool:
        """
        Меняет значение существующего атрибута.

        Args:
            system_name:  имя системы частиц
            group:        группа модулей (из MODULE_GROUPS) либо None —
                          атрибут самой системы
            module_index: индекс модуля в группе (игнорируется при group=None)
            attr_name:    имя атрибута
            value:        новое значение из GUI: число, bool, строка,
                          [x,y,z] для vec3, [r,g,b,a] 0–255 для color

        Returns:
            True если атрибут найден и обновлён.
        """
        d = self._find_definition(system_name)
        if d is None:
            return False
        el = d
        if group is not None:
            if group not in d:
                return False
            try:
                mods = list(d[group].iter_elem())
                el = mods[module_index]
            except (IndexError, Exception):
                return False
        if attr_name not in el:
            return False

        # Пересоздаём атрибут с ИСХОДНЫМ именем (ключи srctools casefold-ятся,
        # а в файле имя должно остаться как было) и исходным типом.
        orig_name = el[attr_name].name
        vt = el[attr_name].type
        try:
            if vt is ValueType.COLOR:
                r, g, b, a = [max(0, min(255, int(x))) for x in value]
                el[attr_name] = Attribute.color(orig_name, r, g, b, a)
            elif vt is ValueType.VEC3:
                x, y, z = [float(v) for v in value]
                el[attr_name] = Attribute.vec3(orig_name, x, y, z)
            elif vt is ValueType.BOOL:
                el[attr_name] = Attribute.bool(orig_name, bool(value))
            elif vt is ValueType.INTEGER:
                el[attr_name] = Attribute.int(orig_name, int(value))
            elif vt is ValueType.TIME:
                el[attr_name] = Attribute.time(orig_name, float(value))
            elif vt is ValueType.FLOAT:
                el[attr_name] = Attribute.float(orig_name, float(value))
            elif vt is ValueType.STRING:
                el[attr_name] = Attribute.string(orig_name, str(value))
            else:
                return False
        except (TypeError, ValueError) as exc:
            logger.warning(f"set_attr({system_name}.{attr_name}={value!r}): {exc}")
            return False
        return True

    # ── Замена текстуры ──────────────────────────────────────────────────── #

    def set_system_texture(
        self, system_name: str, image_path: str, tf2_root_dir: str,
    ) -> Optional[dict]:
        """Замена текстуры ТЕКУЩЕГО материала системы (шорткат к
        set_material_texture)."""
        d = self._find_definition(system_name)
        if d is None or "material" not in d:
            return None
        res = self.set_material_texture(
            d["material"].val_str, image_path, tf2_root_dir)
        return res[1] if res else None

    def set_material_texture(
        self, material_name: str, image_path: str, tf2_root_dir: str,
        max_size: int = 512, uncompressed: bool = False,
    ) -> Optional[tuple]:
        """
        Заменяет текстуру МАТЕРИАЛА: все системы PCF, использующие его
        (включая дочерние), переводятся на кастомный материал.

        Картинка конвертируется в VTF (DXT5, размеры приводятся к степени
        двойки, максимум 512), VMT копируется с оригинального материала
        (сохраняются $additive и прочие параметры) с новым $basetexture.
        Файлы копятся в custom_files для экспорта VPK.

        Returns:
            (новое имя материала, info-dict для превью) либо None при ошибке.
        """
        # Сравнение нормализованное: в PCF встречаются разные регистр и слэши
        # ('effects\X.vmt' vs 'effects/x.vmt') для одного материала
        def _norm(m: str) -> str:
            return m.replace("\\", "/").lower()

        target = _norm(material_name)
        affected = [
            el for el in self._all_definition_elements()
            if "material" in el and _norm(el["material"].val_str) == target
        ]
        if not affected:
            return None
        old_mat = material_name

        # ── Оригинальный VMT — базис для параметров ────────────────────────
        vmt_rel = old_mat.replace("\\", "/").lower()
        if not vmt_rel.endswith(".vmt"):
            vmt_rel += ".vmt"
        if not vmt_rel.startswith("materials/"):
            vmt_rel = "materials/" + vmt_rel

        vmt_text = None
        # Повторная замена: текущий материал уже кастомный — базис берём из
        # него, иначе потеряются параметры оригинала ($additive и пр.)
        if vmt_rel in self.custom_files:
            vmt_text = self.custom_files[vmt_rel].decode("utf-8", errors="replace")
        else:
            try:
                _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
                paks = open_vpks(
                    [misc_vpk, TF2Paths.resolve_textures_vpk(tf2_root_dir)]
                    + TF2Paths.resolve_hl2_vpks(tf2_root_dir))
                raw = read_from_vpks(paks, vmt_rel)
                if raw is not None:
                    vmt_text = raw.decode("utf-8", errors="replace")
            except FileNotFoundError:
                pass
        if vmt_text is None:
            # Оригинала нет — минимальный спрайтовый VMT
            vmt_text = (
                '"SpriteCard"\n{\n\t"$basetexture" "placeholder"\n'
                '\t"$vertexcolor" 1\n\t"$vertexalpha" 1\n\t"$additive" 1\n}\n'
            )

        # ── Картинка → RGBA с размерами-степенями двойки ───────────────────
        try:
            from PIL import Image
            img = Image.open(image_path).convert("RGBA")
        except Exception as exc:
            logger.error(f"Не удалось открыть картинку {image_path}: {exc}")
            return None

        cap = max(64, min(int(max_size), 1024))

        def _pot(n: int) -> int:
            p = 1
            while p * 2 <= min(n, cap):
                p *= 2
            return p

        w, h = _pot(img.width), _pot(img.height)
        if (w, h) != img.size:
            img = img.resize((w, h), Image.LANCZOS)

        # ── VTF через VTFLib (пишет только на диск) ────────────────────────
        base_rel = self._custom_base_rel(material_name)
        tmp_path = None
        try:
            from src.services.vtflib_wrapper import VTFImageFlags, VTFImageFormat, VTFLib
            fd, tmp_path = tempfile.mkstemp(suffix=".vtf")
            os.close(fd)
            VTFLib.create_animated_vtf(
                [img.tobytes()], w, h,
                VTFImageFormat.RGBA8888 if uncompressed else VTFImageFormat.DXT5,
                # NOMIP|NOLOD обязательны: мипы не генерируем, без флагов игра
                # полезет за отсутствующими уровнями
                VTFImageFlags.CLAMPS | VTFImageFlags.CLAMPT
                | VTFImageFlags.NOMIP | VTFImageFlags.NOLOD,
                tmp_path,
            )
            vtf_bytes = Path(tmp_path).read_bytes()
        except Exception as exc:
            logger.error(f"Картинка → VTF не удалась: {exc}", exc_info=True)
            return None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        # ── VMT: оригинал с новым $basetexture ─────────────────────────────
        # Заменяем ВСЕ вхождения: в VMT бывают дубли в fallback-блоках DX
        if _RE_BASETEXTURE.search(vmt_text):
            new_vmt = _RE_BASETEXTURE.sub(
                lambda _m: f'\t"$basetexture" "{base_rel}"', vmt_text)
        else:
            new_vmt = vmt_text.replace(
                "{", '{\n\t"$basetexture" "' + base_rel + '"', 1)

        new_mat = f"{base_rel}.vmt"
        self.custom_files[f"materials/{base_rel}.vmt"] = new_vmt.encode("utf-8")
        self.custom_files[f"materials/{base_rel}.vtf"] = vtf_bytes
        for el in affected:
            el["material"] = Attribute.string(el["material"].name, new_mat)

        # ── Превью-инфо ────────────────────────────────────────────────────
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        shader_m = _RE_SHADER.search(new_vmt)
        info = {
            "dataUrl": f"data:image/png;base64,{b64}",
            "sheet": None,
            "additive": bool(_RE_ADDITIVE.search(new_vmt)),
            "shader": shader_m.group(1).lower() if shader_m else "",
            "width": w,
            "height": h,
        }
        self._custom_material_info[new_mat] = info
        # Для сброса к текстуре игры: первый исходный материал запоминаем
        # (повторная замена кастомного не должна его затирать)
        if not hasattr(self, "_material_original"):
            self._material_original = {}
        if new_mat != material_name:
            self._material_original.setdefault(new_mat, material_name)
        return new_mat, info

    def is_custom_material(self, material_name: str) -> bool:
        """True, если материал — наша замена (можно сбросить к игровому)."""
        return material_name in getattr(self, "_material_original", {})

    def reset_material_texture(self, custom_material_name: str) -> Optional[str]:
        """
        Сбрасывает кастомный материал обратно к исходному игровому: все
        системы возвращаются на оригинальный материал, файлы замены
        убираются из экспорта.

        Returns:
            Имя исходного материала либо None (материал не был заменён).
        """
        orig = getattr(self, "_material_original", {}).get(custom_material_name)
        if orig is None:
            return None

        target = custom_material_name.replace("\\", "/").lower()
        for el in self._all_definition_elements():
            if ("material" in el
                    and el["material"].val_str.replace("\\", "/").lower() == target):
                el["material"] = Attribute.string(el["material"].name, orig)

        base_rel = target[:-4] if target.endswith(".vmt") else target
        self.custom_files.pop(f"materials/{base_rel}.vmt", None)
        self.custom_files.pop(f"materials/{base_rel}.vtf", None)
        self._custom_material_info.pop(custom_material_name, None)
        self._material_original.pop(custom_material_name, None)
        return orig

    def _custom_base_rel(self, material_name: str) -> str:
        """Уникальный базовый путь кастомного материала.

        Повторная замена того же (в т.ч. уже кастомного) материала получает
        прежний путь — файлы перезаписываются; разные материалы со
        схлопывающимися слагами разводятся суффиксом-счётчиком.
        """
        norm = material_name.replace("\\", "/").lower()
        if norm.endswith(".vmt"):
            norm = norm[:-4]
        if norm.startswith("particle/custom_"):
            return norm  # повторная замена уже кастомного
        if not hasattr(self, "_material_base_rel"):
            self._material_base_rel: Dict[str, str] = {}
        if material_name in self._material_base_rel:
            return self._material_base_rel[material_name]
        stem = norm.rsplit("/", 1)[-1]
        slug = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "tex"
        base = f"particle/custom_{slug}"
        candidate, n = base, 2
        taken = set(self._material_base_rel.values())
        while candidate in taken:
            candidate = f"{base}_{n}"
            n += 1
        self._material_base_rel[material_name] = candidate
        return candidate

    # ── Экспорт VPK ──────────────────────────────────────────────────────── #

    def pcf_vpk_path(self) -> str:
        """Путь PCF внутри VPK-мода (particles/<имя файла>)."""
        src = self.source_path or "custom.pcf"
        if src.startswith("vpk:"):
            return src[4:]
        return f"particles/{Path(src).name}"

    def export_vpk(self, dest_path: str, language: str = "en") -> str:
        """
        Собирает VPK-мод: правленый PCF + кастомные материалы.

        Args:
            dest_path: полный путь к итоговому .vpk
            language:  язык сообщений об ошибках упаковки

        Returns:
            Путь к созданному VPK.
        """
        if self.root is None:
            raise RuntimeError("PCF не загружен")
        from src.services.packaging_service import PackagingService

        dest = Path(dest_path)
        tmp_root = Path(tempfile.mkdtemp(prefix="tf2sg_particles_"))
        try:
            vpkroot = tmp_root / "vpkroot"
            pcf_dest = vpkroot / self.pcf_vpk_path()
            pcf_dest.parent.mkdir(parents=True, exist_ok=True)
            self.save(str(pcf_dest))
            for rel, data in self.custom_files.items():
                f = vpkroot / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
            return PackagingService.pack_directory(
                vpkroot_dir=vpkroot,
                filename=dest.name,
                export_folder=str(dest.parent),
                language=language,
            )
        finally:
            import shutil
            shutil.rmtree(tmp_root, ignore_errors=True)

    # ── Натуральные цвета текстуры ───────────────────────────────────────── #

    #: Модули, красящие частицы (тинт умножается на текстуру).
    _COLOR_MODULE_NAMES = {"color random", "color fade", "color lit per particle"}

    def use_texture_colors(self, system_name: str) -> int:
        """
        Заставляет эффект использовать родные цвета текстур: у системы и всех
        её дочерних удаляются модули тинта (Color Random, Color Fade,
        Color Lit Per Particle, ремапы CP/осцилляция в поле цвета), базовый
        цвет ставится белым. Тот же приём, что colored-crit в CritPcfService.

        Returns:
            Количество удалённых модулей (0 — красящих модулей не было).
        """
        root_def = self._find_definition(system_name)
        if root_def is None:
            return 0

        # Система + все дочерние (эффект целиком)
        targets, seen, pending = [], set(), [root_def]
        while pending:
            d = pending.pop(0)
            if id(d) in seen:
                continue
            seen.add(id(d))
            targets.append(d)
            if "children" in d:
                try:
                    for ch in d["children"].iter_elem():
                        if "child" in ch:
                            try:
                                pending.append(ch["child"].val_elem)
                            except Exception:
                                pass
                except Exception:
                    pass

        removed = 0
        for d in targets:
            for group in ("initializers", "operators"):
                if group not in d:
                    continue
                kept = []
                for mod in d[group].iter_elem():
                    if self._is_color_module(mod):
                        removed += 1
                    else:
                        kept.append(mod)
                if len(kept) != len(d[group]):
                    if kept:
                        d[group] = kept
                    else:
                        # Пустому списку srctools не выводит тип — явный массив
                        d[group] = Attribute.array(
                            d[group].name, ValueType.ELEMENT)
            if "color" in d:
                d["color"] = Attribute.color(d["color"].name, 255, 255, 255, 255)
        return removed

    @classmethod
    def _is_color_module(cls, mod) -> bool:
        """True для модулей, задающих/меняющих цвет частиц."""
        fn = ""
        if "functionname" in mod:
            try:
                fn = mod["functionname"].val_str
            except Exception:
                fn = ""
        fn = (fn or mod.name or "").strip().lower()
        if fn in cls._COLOR_MODULE_NAMES:
            return True

        def _field(attr_name: str) -> Optional[int]:
            if attr_name not in mod:
                return None
            try:
                return mod[attr_name].val_int
            except Exception:
                return None

        # 6 = TINT_RGB (цвет частицы) в индексации полей Source
        if fn == "remap control point to vector" and _field("output field") == 6:
            return True
        if fn == "oscillate vector" and _field("oscillation field") == 6:
            return True
        return False

    # ── Сохранение ───────────────────────────────────────────────────────── #

    def save(self, dest_path: str) -> None:
        """Сохраняет текущее дерево в бинарный PCF с исходным encoding."""
        if self.root is None:
            raise RuntimeError("PCF не загружен")
        enc_ver, fmt_name, fmt_ver = self._encoding
        out = io.BytesIO()
        # unicode="silent" ОБЯЗАТЕЛЬНО: "format" пишет в заголовок
        # "unicode_binary", который парсер DMX игры не знает — TF2 молча
        # отбрасывает весь PCF и эффекты пропадают
        self.root.export_binary(
            out, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver,
            unicode="silent",
        )
        Path(dest_path).write_bytes(out.getvalue())
        logger.info(f"PCF сохранён: {dest_path}")
