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

#: Атрибуты со значениями по умолчанию Source: при экспорте вырезаются
#: (lossless — игра/превью подставляют те же дефолты). Присутствуют почти на
#: каждом операторе/рендерере, поэтому дают килобайты экономии. Это нужно,
#: чтобы модифицированный PCF влез в слот VPK: casual-bypass не грузит PCF
#: больше оригинала (та же причина, по которой у casual-pre-loader есть
#: pcf_compress). Значения — как в constants.py casual-pre-loader.
_PCF_DEFAULT_ATTRS = {
    "operator start fadein": 0.0,
    "operator end fadein": 0.0,
    "operator start fadeout": 0.0,
    "operator end fadeout": 0.0,
    "operator fade oscillate": 0.0,
    "visibility proxy input control point number": -1,
    "visibility proxy radius": 1.0,
    "visibility input minimum": 0.0,
    "visibility input maximum": 1.0,
    "visibility alpha scale minimum": 0.0,
    "visibility alpha scale maximum": 1.0,
    "visibility radius scale minimum": 1.0,
    "visibility radius scale maximum": 1.0,
    "visibility camera depth bias": 0.0,
}

#: Каталог модулей для «Добавить модуль…» — ходовые functionName из стоковых
#: PCF TF2 (написание — как в файлах игры). Превью умеет большинство из них.
MODULE_CATALOG = {
    "emitters": ["emit_continuously", "emit_instantaneously", "emit noise"],
    "initializers": [
        "Position Within Sphere Random", "Position Within Box Random",
        "Position Modify Offset Random", "Position Modify Warp Random",
        "Position From Parent Particles",
        "Lifetime Random", "Radius Random", "Alpha Random", "Color Random",
        "Rotation Random", "Rotation Speed Random", "Rotation Yaw Random",
        "Rotation Yaw Flip Random", "Sequence Random", "Trail Length Random",
        "Velocity Random", "Velocity Noise", "lifetime from sequence",
        "remap initial scalar", "Remap Initial Distance to Control Point to Scalar",
        "Remap Noise to Scalar", "Remap Control Point to Vector",
    ],
    "operators": [
        "Lifespan Decay", "Movement Basic", "Movement Lock to Control Point",
        "Movement Rotate Particle Around Axis", "Movement Max Velocity",
        "Radius Scale", "Color Fade", "Alpha Fade In Random",
        "Alpha Fade Out Random", "Alpha Fade and Decay",
        "Rotation Basic", "Rotation Spin Roll", "Rotation Spin Yaw",
        "Oscillate Scalar", "Oscillate Vector", "Remap Scalar",
        "Remap Distance to Control Point to Scalar",
        "Set child control points from particle positions",
    ],
    "forces": ["random force", "Pull towards control point", "twist around axis"],
    "constraints": [
        "Collision via traces", "Constrain distance to control point",
    ],
    "renderers": ["render_animated_sprites", "render_rope", "render_sprite_trail"],
}

# Якорь по началу строки: иначе матчились закомментированные строки и ссылки
# на $basetexture внутри proxies; хвостовой //-комментарий отсекается.
# \r?$ обязателен: VMT Valve с CRLF-концами строк.
def _norm_mat(name: str) -> str:
    """Материал → нормализованный rel-путь под materials/ (effects/crit.vmt).
    Ключ для сопоставления материалов с разным регистром/слэшами."""
    n = name.replace("\\", "/").lower()
    if not n.endswith(".vmt"):
        n += ".vmt"
    if n.startswith("materials/"):
        n = n[len("materials/"):]
    return n


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
        #: Превью-инфо кастомных материалов: {норм. имя материала: info-dict}.
        self._custom_material_info: Dict[str, dict] = {}
        #: Перезаписанные текстуры: {норм. имя материала: {tex_rel, material}}.
        self._overwritten: Dict[str, dict] = {}
        #: Путь к <имя>_textures.vpk из последнего export_vpk (None — не собирался).
        self.last_textures_vpk: Optional[str] = None

    # ── Загрузка ─────────────────────────────────────────────────────────── #

    def load_bytes(self, raw: bytes, source: str = "") -> None:
        """Парсит PCF из байтов (бросает исключение при ошибке)."""
        if not SRCTOOLS_AVAILABLE:
            raise RuntimeError("srctools не установлен (pip install srctools)")
        self._encoding = CritPcfService._detect_encoding(raw)
        self.root, _, _ = Element.parse(io.BytesIO(raw))
        self.source_path = source
        self._loaded_size = len(raw)   # «потолок» размера для казуала
        self.custom_files = {}
        self._custom_material_info = {}
        self._overwritten = {}

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

    #: Кэш списка игровых particle-материалов (скан всех PCF — дорогой).
    _game_materials_cache: Optional[List[str]] = None

    @classmethod
    def game_effect_materials(cls, tf2_root_dir: str) -> List[str]:
        """
        Материалы (текстуры) из ВСЕХ particle-эффектов игры — для выбора
        существующей игровой текстуры вместо своей картинки. Такой материал
        уже есть в игре, поэтому мод работает в казуале (bypass не нужно
        добавлять новый файл). Результат кэшируется на весь запуск.
        """
        if cls._game_materials_cache is not None:
            return cls._game_materials_cache
        mats = set()
        for pcf in cls.list_game_pcfs(tf2_root_dir):
            try:
                svc = cls()
                svc.load_from_game(tf2_root_dir, pcf)
                for m in svc.material_names():
                    if not m or "custom_" in m.lower():
                        continue
                    # Только спрайтовые particle-текстуры (effects/particle),
                    # без модельных/бэкпак-материалов — чтобы список был к делу
                    norm = m.replace("\\", "/").lower()
                    if norm.startswith(("effects/", "particle/")):
                        mats.add(m)
            except Exception:
                continue
        cls._game_materials_cache = sorted(mats, key=str.lower)
        return cls._game_materials_cache

    def set_material_to_game(self, old_material: str, game_material: str) -> bool:
        """
        Переводит все системы с материалом old_material на СУЩЕСТВУЮЩИЙ игровой
        материал game_material (просто меняет строку — новый файл не создаётся).
        Работает в казуале: игра уже содержит этот материал.
        """
        def _norm(m: str) -> str:
            return m.replace("\\", "/").lower()

        target = _norm(old_material)
        changed = False
        for el in self._all_definition_elements():
            if "material" in el and _norm(el["material"].val_str) == target:
                el["material"] = Attribute.string(
                    el["material"].name, game_material)
                changed = True
        return changed

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
        # Системы, существующие только как children (нет в корневом списке)
        for d in self._all_definition_elements():
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
        # Перезаписанные текстуры — превью-инфо по нормализованному ключу
        out: Dict[str, dict] = {}
        for mat in self.material_names():
            ck = _norm_mat(mat)
            if ck in self._custom_material_info:
                out[mat] = self._custom_material_info[ck]
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

    # ── Копирование / вставка параметров ─────────────────────────────────── #

    @staticmethod
    def _attr_from_json(name: str, tv: dict) -> Optional["Attribute"]:
        """{"t","v"} из systems_json → Attribute (None — неизвестный тип/битое значение)."""
        t, v = tv.get("t"), tv.get("v")
        try:
            if t == "color":
                r, g, b, a = (list(v) + [255])[:4]
                return Attribute.color(name, int(r), int(g), int(b), int(a))
            if t == "vec3":
                return Attribute.vec3(name, [float(x) for x in v])
            if t == "vec2":
                return Attribute.vec2(name, [float(x) for x in v])
            if t == "vec4":
                return Attribute.vec4(name, [float(x) for x in v])
            if t == "bool":
                return Attribute.bool(name, bool(v))
            if t == "integer":
                return Attribute.int(name, int(v))
            if t == "time":
                return Attribute.time(name, float(v))
            if t == "float":
                return Attribute.float(name, float(v))
            if t == "string":
                return Attribute.string(name, str(v))
            if t == "float_array":
                return Attribute.array(name, ValueType.FLOAT,
                                       [float(x) for x in v])
            if t == "int_array":
                return Attribute.array(name, ValueType.INTEGER,
                                       [int(x) for x in v])
        except (TypeError, ValueError) as exc:
            logger.warning(f"Вставка атрибута {name}={v!r}: {exc}")
        return None

    def _paste_attrs(self, el, attrs: Dict[str, dict],
                     overwrite: bool = True) -> bool:
        """Merge-вставка атрибутов в элемент: новые добавляются, совпадающие
        перезаписываются (overwrite=False — существующие не трогаются)."""
        changed = False
        for name, tv in attrs.items():
            if name.lower() in ("functionname", "name", "id"):
                continue
            if not overwrite and name in el:
                continue
            orig_name = el[name].name if name in el else name
            attr = self._attr_from_json(orig_name, tv)
            if attr is not None:
                el[name] = attr
                changed = True
        return changed

    def paste_params(self, system_name: str, payload: dict,
                     mode: str = "overwrite") -> bool:
        """
        Вставляет скопированный набор параметров в систему.

        payload — формат буфера копирования панели:
            {"attrs": {имя: {"t","v"}},
             "modules": {группа: [[functionName, {имя: {"t","v"}}], ...]}}
        (легаси-формат {группа: {functionName: attrs}} тоже принимается —
        старые копии в буфере обмена).

        mode:
            "overwrite" — merge, совпадающие имена перезаписываются молча;
            "keep"      — merge, существующие параметры цели не трогаются,
                          добавляются только недостающие;
            "replace"   — параметры и модули цели удаляются, остаются только
                          вставляемые (children и имя системы сохраняются).

        Модуль ищется по functionName с учётом номера вхождения (у эффектов
        бывает два одинаковых модуля, напр. Remap Noise to Scalar); нет
        такого — создаётся новый.
        """
        d = self._find_definition(system_name)
        if d is None:
            return False
        overwrite = mode != "keep"
        changed = False
        if mode == "replace":
            # Сносим скалярные атрибуты (кроме имени) и все группы модулей;
            # children и прочие element-ссылки не трогаем
            for key in list(d.keys()):
                if key in ("name", "id"):
                    continue
                if key in MODULE_GROUPS:
                    d[key] = Attribute.array(d[key].name, ValueType.ELEMENT)
                elif d[key].type is not ValueType.ELEMENT:
                    del d[key]
                changed = True
        if self._paste_attrs(d, payload.get("attrs") or {}, overwrite):
            changed = True
        for group, mods in (payload.get("modules") or {}).items():
            if group not in MODULE_GROUPS:
                continue
            pairs = mods.items() if isinstance(mods, dict) else mods
            occurrence: Dict[str, int] = {}
            for fn, attrs in pairs:
                fn = (fn or "").strip()
                if not fn:
                    continue
                # n-я копия модуля в буфере метит n-ю копию у цели
                n = occurrence.get(fn.lower(), 0)
                occurrence[fn.lower()] = n + 1
                target = None
                if group in d:
                    k = 0
                    for m in d[group].iter_elem():
                        if self._module_fn(m) == fn.lower():
                            if k == n:
                                target = m
                                break
                            k += 1
                if target is None:
                    target = Element(fn, "DmeParticleOperator")
                    target["functionName"] = Attribute.string(
                        "functionName", fn)
                    if group in d:
                        d[group].append(target)
                    else:
                        arr = Attribute.array(group, ValueType.ELEMENT)
                        arr.append(target)
                        d[group] = arr
                    changed = True
                if self._paste_attrs(target, attrs or {}, overwrite):
                    changed = True
        return changed

    # ── Замена текстуры ──────────────────────────────────────────────────── #

    def set_system_texture(
        self, system_name: str, image_path: str, tf2_root_dir: str,
        max_size: int = 512, uncompressed: bool = False,
    ) -> Optional[tuple]:
        """Заменяет текстуру системы своей картинкой. Имя материала в PCF НЕ
        меняется — ПЕРЕЗАПИСЫВАЕТСЯ оригинальный VTF-файл игры (для казуала —
        bypass подменяет только существующие файлы). Returns (материал, info)."""
        d = self._find_definition(system_name)
        if d is None or "material" not in d:
            return None
        mat = d["material"].val_str
        info = self._overwrite_texture(
            mat, image_path, tf2_root_dir, max_size, uncompressed)
        return (mat, info) if info is not None else None

    def set_material_texture(
        self, material_name: str, image_path: str, tf2_root_dir: str,
        max_size: int = 512, uncompressed: bool = False,
    ) -> Optional[tuple]:
        """То же по имени материала (перезапись одного общего VTF-файла)."""
        info = self._overwrite_texture(
            material_name, image_path, tf2_root_dir, max_size, uncompressed)
        return (material_name, info) if info is not None else None

    def _overwrite_texture(
        self, material_name: str, image_path: str, tf2_root_dir: str,
        max_size: int, uncompressed: bool,
    ) -> Optional[dict]:
        """
        Перезаписывает ОРИГИНАЛЬНЫЙ VTF-файл материала своей картинкой.
        Материал в PCF не переименовывается. КРИТИЧНО для казуала: bypass
        подменяет только существующие файлы игры; новый путь он пропускает.
        Кастомный VTF кладётся по пути $basetexture стокового VMT.
        """
        vmt_text, tex_rel = self._resolve_texture_path(material_name, tf2_root_dir)
        built = self._image_to_vtf(image_path, max_size, uncompressed)
        if built is None:
            return None
        vtf_bytes, w, h, png_b64 = built
        self.custom_files[f"materials/{tex_rel}.vtf"] = vtf_bytes
        if not vmt_text:
            # Материала нет в игре (кастомное имя у ребёнка-партикла): без VMT
            # Source не загрузит материал вовсе — генерируем шаблон по образцу
            # стоковых партикл-материалов TF2 (effects/crit.vmt).
            vmt_text = (
                '"SpriteCard"\n'
                '{\n'
                f'\t"$basetexture" "{tex_rel}"\n'
                '\t"$translucent" 1\n'
                '\t"$vertexcolor" 1\n'
                '\t"$vertexalpha" 1\n'
                '}\n'
            )
        if vmt_text:
            # Оригинальный игровой VMT кладём рядом с VTF: текстурная часть
            # мода самодостаточна (casual-pre-loader ставит материалы только
            # из аддонов, и его автор просит модмейкеров включать VMT).
            self.custom_files[f"materials/{_norm_mat(material_name)}"] = (
                vmt_text.encode("utf-8"))

        shader, additive = "", True
        if vmt_text:
            sm = _RE_SHADER.search(vmt_text)
            shader = sm.group(1).lower() if sm else ""
            additive = bool(_RE_ADDITIVE.search(vmt_text))
        info = {
            "dataUrl": f"data:image/png;base64,{png_b64}", "sheet": None,
            "additive": additive, "shader": shader, "width": w, "height": h,
        }
        key = _norm_mat(material_name)
        self._custom_material_info[key] = info
        self._overwritten[key] = {"tex_rel": tex_rel, "material": material_name}
        return info

    def _resolve_texture_path(self, material_name: str, tf2_root_dir: str):
        """(текст VMT|None, rel-путь текстуры без .vtf). Путь берётся из
        $basetexture стокового VMT; фолбэк — имя материала."""
        vmt_rel = _norm_mat(material_name)
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
            m = _RE_BASETEXTURE.search(vmt_text)
            if m:
                t = m.group(1).strip().replace("\\", "/").lower()
                tex_rel = t[:-4] if t.endswith(".vtf") else t
        if tex_rel is None:
            tex_rel = vmt_rel[:-4]
            if tf2_root_dir:
                logger.warning(
                    f"Не удалось прочитать VMT {vmt_rel} — путь текстуры взят "
                    f"из имени материала ({tex_rel}); для казуала проверьте, "
                    f"что такой VTF есть в игре.")
        return vmt_text, tex_rel

    @staticmethod
    def _image_to_vtf(image_path: str, max_size: int, uncompressed: bool):
        """Картинка → (vtf_bytes, w, h, png_base64). None при ошибке.
        Размеры → степени двойки (<= max_size, потолок 1024). NOMIP|NOLOD."""
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

        tmp_path = None
        try:
            from src.services.vtflib_wrapper import (
                VTFImageFlags, VTFImageFormat, VTFLib)
            fd, tmp_path = tempfile.mkstemp(suffix=".vtf")
            os.close(fd)
            VTFLib.create_animated_vtf(
                [img.tobytes()], w, h,
                VTFImageFormat.RGBA8888 if uncompressed else VTFImageFormat.DXT5,
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
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return vtf_bytes, w, h, png_b64

    def is_custom_material(self, material_name: str) -> bool:
        """True, если текстура материала заменена своей картинкой (можно сбросить)."""
        return _norm_mat(material_name) in self._overwritten

    def reset_material_texture(self, material_name: str) -> Optional[str]:
        """Убирает перезапись текстуры (возврат к текстуре игры). Материал в
        PCF не менялся — просто удаляем оверрайд-файл."""
        key = _norm_mat(material_name)
        entry = self._overwritten.pop(key, None)
        if entry is None:
            return None
        self._custom_material_info.pop(key, None)
        # Файл удаляем ТОЛЬКО если tex_rel не делит другой активный оверрайд
        tex_rel = entry["tex_rel"]
        if not any(e["tex_rel"] == tex_rel for e in self._overwritten.values()):
            self.custom_files.pop(f"materials/{tex_rel}.vtf", None)
        self.custom_files.pop(f"materials/{key}", None)  # VMT этого материала
        return material_name

    # ── Экспорт VPK ──────────────────────────────────────────────────────── #

    def pcf_vpk_path(self) -> str:
        """Путь PCF внутри VPK-мода (particles/<имя файла>)."""
        src = self.source_path or "custom.pcf"
        if src.startswith("vpk:"):
            return src[4:]
        return f"particles/{Path(src).name}"

    def _active_custom_files(self) -> Dict[str, bytes]:
        """Оверрайд-файлы без «сирот»: перезаписи текстур материалов, которые
        больше не используются ни одной системой, в VPK не попадают."""
        used_mats = set()
        for el in self._all_definition_elements():
            if "material" in el:
                try:
                    used_mats.add(_norm_mat(el["material"].val_str))
                except Exception:
                    pass
        active_paths = set()
        for k, e in self._overwritten.items():
            if k in used_mats:
                active_paths.add(f"materials/{e['tex_rel']}.vtf")
                active_paths.add(f"materials/{k}")  # оригинальный VMT материала
        return {rel: data for rel, data in self.custom_files.items()
                if rel in active_paths}

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
        self.last_textures_vpk = None
        materials = self._active_custom_files()
        tmp_root = Path(tempfile.mkdtemp(prefix="tf2sg_particles_"))
        try:
            vpkroot = tmp_root / "vpkroot"
            pcf_dest = vpkroot / self.pcf_vpk_path()
            pcf_dest.parent.mkdir(parents=True, exist_ok=True)
            self.save(str(pcf_dest))
            for rel, data in materials.items():
                f = vpkroot / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
            out = PackagingService.pack_directory(
                vpkroot_dir=vpkroot,
                filename=dest.name,
                export_folder=str(dest.parent),
                language=language,
            )
            # Текстурная часть отдельным VPK без PCF: casual-pre-loader
            # относит мод с любым .pcf к партикл-пакам и материалы из него
            # не устанавливает — аддоном он увидит только чистый vpk.
            if materials:
                texroot = tmp_root / "texroot"
                for rel, data in materials.items():
                    f = texroot / rel
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                self.last_textures_vpk = PackagingService.pack_directory(
                    vpkroot_dir=texroot,
                    filename=f"{dest.stem}_textures.vpk",
                    export_folder=str(dest.parent),
                    language=language,
                )
            return out
        finally:
            import shutil
            shutil.rmtree(tmp_root, ignore_errors=True)

    # ── Структурное редактирование ───────────────────────────────────────── #

    #: Кэш шаблонов модулей из стоковых PCF: {(group, fn_lower): Element}.
    _module_templates: Dict[tuple, "Element"] = {}

    @staticmethod
    def _copy_module(el) -> "Element":
        """Отвязанная копия модуля: все атрибуты копируются по значению.

        Ключ — ОРИГИНАЛЬНОЕ имя атрибута (el.keys() отдаёт casefold-ключи,
        присваивание по ним затирало бы регистр имён в файле)."""
        new = Element(el.name, el.type)
        for attr in el.values():
            new[attr.name] = attr.copy()
        return new

    @classmethod
    def _module_fn(cls, mod) -> str:
        """functionName модуля (нижний регистр) с фолбэком на имя элемента."""
        fn = ""
        if "functionname" in mod:
            try:
                fn = mod["functionname"].val_str
            except Exception:
                fn = ""
        return (fn or mod.name or "").strip().lower()

    def _find_module_template(
        self, group: str, function_name: str, tf2_root_dir: str,
    ) -> Optional["Element"]:
        """
        Шаблон модуля с реалистичными атрибутами: ищем модуль с таким
        functionName в текущем PCF, затем по стоковым PCF игры (первое
        совпадение кэшируется на весь запуск).
        """
        key = (group, function_name.lower())
        if key in ParticleEditorService._module_templates:
            cached = ParticleEditorService._module_templates[key]
            # None — закэшированный промах (не сканировать 134 PCF повторно)
            return self._copy_module(cached) if cached is not None else None

        def _scan(svc) -> Optional["Element"]:
            for d in svc._all_definition_elements():
                if group not in d:
                    continue
                try:
                    for mod in d[group].iter_elem():
                        if self._module_fn(mod) == key[1]:
                            return mod
                except Exception:
                    continue
            return None

        found = _scan(self)
        if found is None and tf2_root_dir:
            for pcf in self.list_game_pcfs(tf2_root_dir):
                try:
                    other = ParticleEditorService()
                    other.load_from_game(tf2_root_dir, pcf)
                except Exception:
                    continue
                found = _scan(other)
                if found is not None:
                    break
        if found is None:
            ParticleEditorService._module_templates[key] = None
            return None
        template = self._copy_module(found)
        ParticleEditorService._module_templates[key] = template
        return self._copy_module(template)

    def add_module(
        self, system_name: str, group: str, function_name: str,
        tf2_root_dir: str = "",
    ) -> bool:
        """
        Добавляет модуль в группу системы. Атрибуты берутся из шаблона
        (первый такой же модуль в текущем/стоковых PCF); если шаблона нет —
        создаётся элемент с одним functionName (движок игры и превью
        подставляют дефолты).
        """
        d = self._find_definition(system_name)
        if d is None or group not in MODULE_GROUPS:
            return False
        mod = self._find_module_template(group, function_name, tf2_root_dir)
        if mod is None:
            mod = Element(function_name, "DmeParticleOperator")
            mod["functionName"] = Attribute.string("functionName", function_name)
        if group in d:
            d[group].append(mod)
        else:
            arr = Attribute.array(group, ValueType.ELEMENT)
            arr.append(mod)
            d[group] = arr
        return True

    def remove_module(self, system_name: str, group: str, index: int) -> bool:
        """Удаляет модуль по индексу из группы системы."""
        d = self._find_definition(system_name)
        if d is None or group not in d:
            return False
        try:
            mods = list(d[group].iter_elem())
            mods.pop(index)
        except (IndexError, Exception):
            return False
        if mods:
            d[group] = mods
        else:
            d[group] = Attribute.array(d[group].name, ValueType.ELEMENT)
        return True

    def duplicate_system(self, system_name: str, new_name: str) -> bool:
        """
        Дублирует систему под новым именем (в корневой список определений).

        Модули копируются по значению (правки копии не трогают оригинал);
        ссылки children остаются на те же дочерние системы.
        """
        d = self._find_definition(system_name)
        if d is None or self._find_definition(new_name) is not None:
            return False
        new = Element(new_name, d.type)
        for attr in d.values():
            key = attr.name          # оригинальный регистр — уходит в файл
            kl = key.casefold()
            if kl in MODULE_GROUPS:
                mods = [self._copy_module(m) for m in attr.iter_elem()]
                if mods:
                    new[key] = mods
                else:
                    new[key] = Attribute.array(key, ValueType.ELEMENT)
            elif kl == "children":
                # Копируем элементы-ссылки, сами дочерние системы — общие
                refs = [self._copy_module(ch) for ch in attr.iter_elem()]
                if refs:
                    new[key] = refs
                else:
                    new[key] = Attribute.array(key, ValueType.ELEMENT)
            else:
                new[key] = attr.copy()
        if "name" in new:
            new["name"] = Attribute.string(new["name"].name, new_name)
        self.root["particleSystemDefinitions"].append(new)
        return True

    def remove_system(self, system_name: str) -> bool:
        """Удаляет систему совсем: из корневого списка И из children всех
        родителей (иначе она оставалась «призраком» — играла у родителя и
        держала имя занятым)."""
        target = self._find_definition(system_name)
        if target is None:
            return False

        # Отцепить все ссылки на target по всему дереву (до удаления из корня)
        for el in self._all_definition_elements():
            if "children" not in el:
                continue
            try:
                refs = list(el["children"].iter_elem())
            except Exception:
                continue
            kept_refs = []
            for ch in refs:
                is_target = False
                if "child" in ch:
                    try:
                        is_target = ch["child"].val_elem is target
                    except Exception:
                        is_target = False
                if not is_target:
                    kept_refs.append(ch)
            if len(kept_refs) != len(refs):
                if kept_refs:
                    el["children"] = kept_refs
                else:
                    el["children"] = Attribute.array(
                        "children", ValueType.ELEMENT)

        defs = self._definitions()
        kept = [d for d in defs if d is not target]
        if kept:
            self.root["particleSystemDefinitions"] = kept
        else:
            self.root["particleSystemDefinitions"] = Attribute.array(
                "particleSystemDefinitions", ValueType.ELEMENT)
        return True

    @staticmethod
    def _make_module(function_name: str, element_type: str, attrs: list) -> "Element":
        """Модуль из functionName и готовых Attribute."""
        el = Element(function_name, element_type)
        el["functionName"] = Attribute.string("functionName", function_name)
        for attr in attrs:
            el[attr.name] = attr
        return el

    def add_layer(self, parent_name: str,
                  layer_name: Optional[str] = None) -> Optional[str]:
        """
        Создаёт новый слой-подэффект и цепляет его ребёнком к parent_name.

        Слой — готовый «залп спрайтов» с разумными настройками (50 частиц
        разлетаются из центра, крутятся, гаснут и падают): пользователю
        остаётся дать текстуру и крутить параметры. Возвращает имя слоя.
        """
        parent = self._find_definition(parent_name)
        if parent is None:
            return None
        if not layer_name:
            base, n = f"{parent_name}_layer", 2
            layer_name = base
            while self._find_definition(layer_name) is not None:
                layer_name = f"{base}{n}"
                n += 1
        elif self._find_definition(layer_name) is not None:
            return None

        d = Element(layer_name, "DmeParticleSystemDefinition")
        d["max_particles"] = Attribute.int("max_particles", 300)
        d["material"] = Attribute.string("material", "effects\\yellowflare.vmt")
        d["radius"] = Attribute.float("radius", 5.0)
        d["color"] = Attribute.color("color", 255, 255, 255, 255)

        op = "DmeParticleOperator"
        d["renderers"] = [self._make_module("render_animated_sprites", op, [
            Attribute.float("animation rate", 1.0),
            Attribute.int("orientation_type", 0),
        ])]
        d["emitters"] = [self._make_module("emit_instantaneously", op, [
            Attribute.int("num_to_emit", 50),
            Attribute.float("emission_start_time", 0.0),
        ])]
        d["initializers"] = [
            self._make_module("Position Within Sphere Random", op, [
                Attribute.float("distance_min", 0.0),
                Attribute.float("distance_max", 4.0),
                Attribute.float("speed_min", 150.0),
                Attribute.float("speed_max", 300.0),
                Attribute.float("speed_random_exponent", 1.0),
            ]),
            self._make_module("Lifetime Random", op, [
                Attribute.float("lifetime_min", 0.4),
                Attribute.float("lifetime_max", 0.8),
            ]),
            self._make_module("Radius Random", op, [
                Attribute.float("radius_min", 3.0),
                Attribute.float("radius_max", 6.0),
            ]),
            self._make_module("Rotation Random", op, []),
        ]
        d["operators"] = [
            self._make_module("Lifespan Decay", op, []),
            self._make_module("Movement Basic", op, [
                Attribute.vec3("gravity", 0.0, 0.0, -200.0),
                Attribute.float("drag", 0.0),
            ]),
            self._make_module("Alpha Fade Out Simple", op, [
                Attribute.float("proportional fade out time", 0.25),
            ]),
            self._make_module("Rotation Spin Roll", op, [
                Attribute.int("spin_rate_degrees", 240),
                Attribute.int("spin_stop_time", 0),
            ]),
        ]

        self.root["particleSystemDefinitions"].append(d)
        if not self.add_child(parent_name, layer_name):
            return None
        return layer_name

    def add_child(self, parent_name: str, child_name: str,
                  delay: float = 0.0) -> bool:
        """Подцепляет существующую систему ребёнком к parent_name."""
        parent = self._find_definition(parent_name)
        child = self._find_definition(child_name)
        if parent is None or child is None or parent is child:
            return False
        # Гард от цикла: если parent достижим из child по children — в игре
        # это бесконечная рекурсия инстанцирования (крэш клиента)
        pending, seen = [child], set()
        while pending:
            cur = pending.pop()
            if cur is parent:
                return False
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            if "children" in cur:
                try:
                    for ch in cur["children"].iter_elem():
                        if "child" in ch:
                            try:
                                pending.append(ch["child"].val_elem)
                            except Exception:
                                pass
                except Exception:
                    pass
        ref = Element(child_name, "DmeParticleChild")
        ref["delay"] = Attribute.float("delay", float(delay))
        ref["child"] = Attribute("child", ValueType.ELEMENT, child)
        if "children" in parent:
            parent["children"].append(ref)
        else:
            arr = Attribute.array("children", ValueType.ELEMENT)
            arr.append(ref)
            parent["children"] = arr
        return True

    def remove_child(self, parent_name: str, index: int) -> bool:
        """Отцепляет ребёнка по индексу (сама дочерняя система остаётся)."""
        parent = self._find_definition(parent_name)
        if parent is None or "children" not in parent:
            return False
        try:
            refs = list(parent["children"].iter_elem())
            # UI нумерует только валидные ссылки (systems_json пропускает
            # битые) — маппим индекс на сырой массив
            valid = [i for i, ch in enumerate(refs) if "child" in ch]
            refs.pop(valid[index])
        except (IndexError, Exception):
            return False
        if refs:
            parent["children"] = refs
        else:
            parent["children"] = Attribute.array("children", ValueType.ELEMENT)
        return True

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

    def _serialize_pcf(self) -> bytes:
        """
        Сериализует дерево в бинарный PCF, вырезав default-атрибуты (сжатие
        как у casual-pre-loader — чтобы файл влез в слот VPK для казуала).

        Работает на КОПИИ дерева (re-parse собственных байтов): рабочее дерево
        не мутируется, обзор свойств в UI сохраняет все строки.

        unicode="silent" ОБЯЗАТЕЛЬНО: "format" пишет в заголовок
        "unicode_binary", который парсер DMX игры не знает — TF2 молча
        отбрасывает весь PCF и эффекты пропадают.
        """
        enc_ver, fmt_name, fmt_ver = self._encoding

        raw0 = io.BytesIO()
        self.root.export_binary(
            raw0, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver,
            unicode="silent")
        copy_root, _, _ = Element.parse(io.BytesIO(raw0.getvalue()))
        self._strip_default_attrs(copy_root)

        out = io.BytesIO()
        copy_root.export_binary(
            out, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver,
            unicode="silent")
        return out.getvalue()

    @staticmethod
    def _strip_default_attrs(root) -> int:
        """Удаляет из всех элементов дерева атрибуты со значением-дефолтом.
        Lossless: игра и превью подставляют те же дефолты. Возвращает счётчик."""
        removed, seen, stack = 0, set(), [root]
        while stack:
            el = stack.pop()
            if id(el) in seen:
                continue
            seen.add(id(el))
            for key in list(el.keys()):
                attr = el[key]
                if attr.type is ValueType.ELEMENT:
                    # спуск в дочерние элементы/массивы элементов
                    try:
                        if attr.is_array:
                            for sub in attr.iter_elem():
                                if sub is not None:
                                    stack.append(sub)
                        else:
                            sub = attr.val_elem
                            if sub is not None:
                                stack.append(sub)
                    except Exception:
                        pass
                    continue
                dv = _PCF_DEFAULT_ATTRS.get(attr.name.lower())
                if dv is None:
                    continue
                try:
                    if attr.type in (ValueType.FLOAT, ValueType.TIME) \
                            and abs(attr.val_float - dv) < 1e-9:
                        del el[key]
                        removed += 1
                    elif attr.type is ValueType.INTEGER and attr.val_int == dv:
                        del el[key]
                        removed += 1
                except Exception:
                    pass
        return removed

    def serialized_size(self) -> int:
        """Размер экспортируемого (сжатого) PCF в байтах."""
        return len(self._serialize_pcf())

    def casual_size_overflow(self) -> Optional[int]:
        """
        На сколько байт сжатый PCF превышает исходный (потолок казуала).
        <= 0 — влезает; > 0 — в казуале не загрузится (бай-пасс не берёт PCF
        больше оригинального слота VPK). None — потолок неизвестен.
        """
        ceiling = getattr(self, "_loaded_size", None)
        if not ceiling:
            return None
        return self.serialized_size() - ceiling

    def save(self, dest_path: str) -> None:
        """Сохраняет текущее дерево в бинарный (сжатый) PCF."""
        if self.root is None:
            raise RuntimeError("PCF не загружен")
        Path(dest_path).write_bytes(self._serialize_pcf())
        logger.info(f"PCF сохранён: {dest_path}")
