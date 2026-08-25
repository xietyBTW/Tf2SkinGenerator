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
import json
import os
import re
import struct
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services import vmt_parse
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

def flatten_hierarchy(tree: list) -> List[str]:
    """Имена из дерева сверху вниз, каждое по одному разу."""
    out, seen = [], set()

    def walk(nodes):
        for name, kids in nodes:
            if name not in seen:
                seen.add(name)
                out.append(name)
            walk(kids)

    walk(tree)
    return out


#: Сколько контрольных точек знает движок Source (MAX_PARTICLE_CONTROL_POINTS).
MAX_CONTROL_POINTS = 64

#: Имена атрибутов, которые НЕ являются номером контрольной точки, хотя и
#: содержат нужные слова: это границы диапазонов и счётчики (в стоке там
#: встречаются 20/30/40 — за пределами реальных CP эффекта).
_NOT_CP_ATTRS = ("maximum end control point", "# of control points to set",
                 "control point movement distance tolerance",
                 "control point offset for fast collisions",
                 "emission count scale control point field")


def referenced_control_points(sys_json: dict,
                              systems: Optional[dict] = None) -> List[int]:
    """
    Номера контрольных точек, от которых зависит система (и её дети).

    Ими игра управляет из кода — цвет килстрика на CP 9, положение оружия на
    CP 1 и так далее. В превью такие точки надо выставить руками, а понять,
    какие именно, можно только вычитав их из модулей эффекта.
    """
    found: set = set()
    seen: set = set()
    pending = [sys_json]
    while pending:
        s = pending.pop()
        if s is None or id(s) in seen:
            continue
        seen.add(id(s))
        for group in MODULE_GROUPS:
            for mod in s.get(group) or []:
                for name, tv in (mod.get("attrs") or {}).items():
                    low = name.lower()
                    if "control point" not in low and "control_point" not in low:
                        continue
                    if any(low == skip or low.startswith(skip)
                           for skip in _NOT_CP_ATTRS):
                        continue
                    v = tv.get("v")
                    if isinstance(v, bool) or not isinstance(v, int):
                        continue
                    if 0 <= v < MAX_CONTROL_POINTS:
                        found.add(v)
        if systems:
            for ch in s.get("children") or []:
                pending.append(systems.get(ch.get("childName")))
    return sorted(found)


def system_hierarchy(systems: dict, order: Optional[List[str]] = None) -> list:
    """Иерархия систем: [(имя, [(ребёнок, [...]), ...]), ...].

    Корень — система, которую никто, кроме неё самой, не называет своим
    ребёнком. В большом файле корней в разы меньше, чем определений: в
    summer2024_unusuals.pcf из 611 систем корней 52, остальные — служебные
    держатели и спавнеры.

    Один ребёнок может висеть сразу у нескольких родителей (в PCF это ссылка
    по имени, а не владение) — тогда он появится под каждым из них, так оно и
    есть на самом деле. Циклы обрываются по пути от корня.

    Из списка ничего не пропадает: система, до которой не дотянуться ни от
    одного корня (взаимный цикл), добавляется вершиной сама.

    order задаёт порядок вершин; имена не из systems игнорируются.
    """
    names = list(order) if order is not None else list(systems)
    names = [n for n in names if n in systems]

    referenced = set()
    for name, s in systems.items():
        for c in s.get("children") or []:
            child = c.get("childName")
            if child != name:          # сам себе родителем не считается
                referenced.add(child)

    def subtree(name: str, path: frozenset) -> tuple:
        kids = []
        for c in systems.get(name, {}).get("children") or []:
            child = c.get("childName")
            if child in systems and child not in path:
                kids.append(subtree(child, path | {child}))
        return (name, kids)

    tree = [subtree(n, frozenset({n})) for n in names if n not in referenced]

    # Взаимный цикл без входа снаружи: иначе такие системы исчезли бы из UI
    shown = set(flatten_hierarchy(tree))
    for n in names:
        if n not in shown:
            node = subtree(n, frozenset({n}))
            tree.append(node)
            shown.update(flatten_hierarchy([node]))
    return tree


#: Каталог модулей для «Добавить модуль…» — ходовые functionName из стоковых
#: PCF TF2 (написание — как в файлах игры). Идут первыми в списке выбора,
#: остальные модули игры добавляются к ним из каталога параметров.
#:
#: Правило отбора: сюда попадает всё, что умеет движок превью, плюс то, что
#: массово встречается в эффектах игры (счётчики — по срезу 134 стоковых PCF).
#: Модули, которых превью не понимает, помечаются в диалоге отдельно —
#: скрывать их нельзя: в игре они работают, и без них не собрать половину
#: приёмов Valve (спавн по модели, привязка к кости).
MODULE_CATALOG = {
    "emitters": ["emit_continuously", "emit_instantaneously", "emit noise"],
    "initializers": [
        "Position Within Sphere Random", "Position Within Box Random",
        "Position Modify Offset Random", "Position Modify Warp Random",
        "Position From Parent Particles", "Position on Model Random",
        "Position Along Path Sequential", "Position Along Path Random",
        "Lifetime Random", "Radius Random", "Alpha Random", "Color Random",
        "Rotation Random", "Rotation Speed Random", "Rotation Yaw Random",
        "Rotation Yaw Flip Random", "Sequence Random", "Sequence Two Random",
        "Trail Length Random",
        "Velocity Random", "Velocity Noise",
        "Velocity Inherit from Control Point", "lifetime from sequence",
        "Lifetime From Control Point Life Time", "Lifetime Pre-Age Noise",
        "remap initial scalar", "Remap Initial Distance to Control Point to Scalar",
        "Remap Noise to Scalar", "Remap Control Point to Vector",
        "Remap Control Point to Scalar", "Remap Scalar to Vector",
        "Assign target CP", "move particles between 2 control points",
    ],
    "operators": [
        "Lifespan Decay", "Movement Basic", "Movement Lock to Control Point",
        "Movement Rotate Particle Around Axis", "Movement Max Velocity",
        "Movement Lock to Bone", "Movement Follow CP",
        "Movement Dampen Relative to Control Point",
        "Movement Match Particle Velocities",
        "Radius Scale", "Color Fade", "Alpha Fade In Random",
        "Alpha Fade Out Random", "Alpha Fade and Decay",
        "Rotation Basic", "Rotation Spin Roll", "Rotation Spin Yaw",
        "Rotation Orient to 2D Direction", "Rotation Orient Relative to CP",
        "Oscillate Scalar", "Oscillate Vector", "Noise Scalar",
        "Remap Scalar",
        "Remap Distance to Control Point to Scalar",
        "Remap Distance to Control Point to Vector",
        "Remap Dot Product to Scalar",
        "Set child control points from particle positions",
        "Set Control Point Positions", "Set Control Point To Player",
        "Set Control Point To Particles' Center",
        "Cull when crossing plane", "Cull Random",
    ],
    "forces": ["random force", "Pull towards control point", "twist around axis"],
    "constraints": [
        "Collision via traces", "Constrain distance to control point",
        "Constrain distance to path between two control points",
        "Prevent passing through a plane",
    ],
    "renderers": ["render_animated_sprites", "render_rope",
                  "render_sprite_trail", "render_screen_velocity_rotate"],
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


#: Только для ЗАМЕНЫ строки $basetexture в тексте VMT. Чтение — через
#: vmt_parse: регулярка не отличает настоящий параметр от закомментированного.
_RE_BASETEXTURE_LINE = re.compile(
    r'^[ \t]*"?\$basetexture"?[ \t]+"?([^"\r\n]+?)"?[ \t]*(?://[^\r\n]*)?\r?$',
    re.IGNORECASE | re.MULTILINE)


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

    #: Кэш списка игровых particle-материалов. Наполняется в том же проходе,
    #: что и каталог параметров (build_attr_catalog), и живёт на диске.
    _game_materials_cache: Optional[List[str]] = None

    @staticmethod
    def _is_particle_material(name: str) -> bool:
        """Спрайтовая particle-текстура (effects//particle), не служебная."""
        if not name or "custom_" in name.lower():
            return False
        return name.replace("\\", "/").lower().startswith(("effects/", "particle/"))

    @classmethod
    def game_effect_materials(cls, tf2_root_dir: str) -> List[str]:
        """
        Материалы (текстуры) из ВСЕХ particle-эффектов игры — для выбора
        существующей игровой текстуры вместо своей картинки. Такой материал
        уже есть в игре, поэтому мод работает в казуале (bypass не нужно
        добавлять новый файл).

        Собирается вместе с каталогом параметров одним сканом; результат
        кэшируется на диск и переживает перезапуск.
        """
        if cls._game_materials_cache is not None:
            return cls._game_materials_cache
        cls.build_attr_catalog(tf2_root_dir)   # заполнит и материалы
        if cls._game_materials_cache is None:
            cls._game_materials_cache = []
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

    # ── Снимки состояния (undo/redo) ─────────────────────────────────────── #

    def snapshot(self) -> Optional[dict]:
        """
        Полное состояние редактора одним снимком.

        Дерево сериализуется в байты (тот же формат, что и файл — сжатие
        default-атрибутов НЕ применяем, снимок должен быть точной копией),
        рядом кладутся оверрайды текстур. Снимочный подход выбран вместо
        обратимых команд: он автоматически покрывает и будущие операции —
        забыть «откат» для новой правки невозможно.
        """
        if self.root is None:
            return None
        enc_ver, fmt_name, fmt_ver = self._encoding
        buf = io.BytesIO()
        self.root.export_binary(
            buf, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver,
            unicode="silent")
        return {
            "pcf": buf.getvalue(),
            "custom_files": dict(self.custom_files),
            "custom_material_info": dict(self._custom_material_info),
            "overwritten": {k: dict(v) for k, v in self._overwritten.items()},
        }

    def restore(self, snap: dict) -> bool:
        """Возвращает состояние из снимка (дерево + оверрайды текстур)."""
        if not snap or not SRCTOOLS_AVAILABLE:
            return False
        try:
            root, _, _ = Element.parse(io.BytesIO(snap["pcf"]))
        except Exception as exc:
            logger.error(f"Восстановление снимка PCF: {exc}")
            return False
        self.root = root
        self.custom_files = dict(snap.get("custom_files") or {})
        self._custom_material_info = dict(
            snap.get("custom_material_info") or {})
        self._overwritten = {k: dict(v)
                             for k, v in (snap.get("overwritten") or {}).items()}
        return True

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

        vmt = vmt_parse.parse(vmt_text)
        shader = vmt.shader
        base = vmt.path("basetexture")
        if not base:
            # Материалы без $basetexture (vgui/white и т.п.) — однотонный квад
            # с вершинным цветом; важно сохранить хотя бы режим блендинга
            return {
                "dataUrl": None,
                "sheet": None,
                "additive": vmt.flag("additive"),
                "shader": shader,
                "width": 0,
                "height": 0,
            }
        vtf_rel = base
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
            "additive": vmt.flag("additive"),
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

    def ensure_attr(
        self, system_name: str, group: Optional[str], module_index: int,
        attr_name: str, attr_type: str, value: Any,
    ) -> bool:
        """
        set_attr; если атрибута нет — создаёт его с заданным DMX-типом.
        Нужно простому режиму: крутилка должна работать и на модуле,
        у которого этот атрибут ещё не записан (игра держит его в дефолте).
        """
        if self.set_attr(system_name, group, module_index, attr_name, value):
            return True
        d = self._find_definition(system_name)
        if d is None:
            return False
        el = d
        if group is not None:
            if group not in d:
                return False
            try:
                el = list(d[group].iter_elem())[module_index]
            except (IndexError, Exception):
                return False
        if attr_name in el:
            return False   # атрибут есть, но set_attr отверг значение
        # Новый атрибут — в написании игры, иначе Source его не прочитает
        canon = self.canonical_attr_name(
            group, self._module_fn(el) if group else "", attr_name)
        attr = self._attr_from_json(canon, {"t": attr_type, "v": value})
        if attr is None:
            return False
        el[canon] = attr
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

    @classmethod
    def canonical_attr_name(cls, group: Optional[str], function_name: str,
                            attr_name: str) -> str:
        """
        Имя атрибута в написании игры.

        Source читает атрибуты С УЧЁТОМ РЕГИСТРА: записанный строчными
        'spin strength' игра молча игнорирует и берёт умолчание, ей нужен
        'Spin Strength'. AI-пресеты и ручной ввод часто дают строчные —
        приводим к написанию из стоковых эффектов.
        """
        key = (group, (function_name or "").strip().lower())
        canon = cls._attr_canonical.get(key)
        if canon:
            return canon.get(attr_name.lower(), attr_name)
        # Модуля нет в каталоге — поищем это имя у любого другого модуля
        for names in cls._attr_canonical.values():
            hit = names.get(attr_name.lower())
            if hit:
                return hit
        return attr_name

    def _paste_attrs(self, el, attrs: Dict[str, dict], overwrite: bool = True,
                     report: Optional[list] = None,
                     where: str = "", group: Optional[str] = None) -> bool:
        """Merge-вставка атрибутов в элемент: новые добавляются, совпадающие
        перезаписываются (overwrite=False — существующие не трогаются).

        report — сюда складываются проблемы, чтобы вставка не проваливалась
        молча: битые значения видны пользователю."""
        changed = False
        if not isinstance(attrs, dict):
            if report is not None:
                report.append(("particles_paste_bad_attrs", {"where": where}))
            return False
        for name, tv in attrs.items():
            if str(name).lower() in ("functionname", "name", "id"):
                continue
            if not isinstance(tv, dict) or "v" not in tv:
                if report is not None:
                    report.append(("particles_paste_bad_value",
                                   {"where": where, "attr": name}))
                continue
            if not overwrite and name in el:
                continue
            # Существующий атрибут сохраняет своё написание; НОВЫЙ создаём
            # в написании игры, иначе Source его не увидит
            orig_name = (el[name].name if name in el
                         else self.canonical_attr_name(
                             group, self._module_fn(el) if group else "", name))
            attr = self._attr_from_json(orig_name, tv)
            if attr is None:
                if report is not None:
                    report.append(("particles_paste_bad_value",
                                   {"where": where, "attr": name}))
                continue
            # Кладём ПО КАНОНИЧЕСКОМУ ключу: srctools пишет в файл имя ключа,
            # а Source читает атрибуты с учётом регистра
            el[orig_name] = attr
            changed = True
        return changed

    def paste_params(self, system_name: str, payload: dict,
                     mode: str = "overwrite",
                     report: Optional[list] = None) -> bool:
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
        if self._paste_attrs(d, payload.get("attrs") or {}, overwrite,
                             report, where="attrs", group=None):
            changed = True
        modules = payload.get("modules") or {}
        if not isinstance(modules, dict):
            if report is not None:
                report.append(("particles_paste_bad_modules", {}))
            modules = {}
        for group, mods in modules.items():
            if group not in MODULE_GROUPS:
                if report is not None:
                    report.append(("particles_paste_unknown_group",
                                   {"group": group,
                                    "known": ", ".join(MODULE_GROUPS)}))
                continue
            try:
                pairs = list(mods.items() if isinstance(mods, dict) else mods)
            except TypeError:
                if report is not None:
                    report.append(("particles_paste_bad_group",
                                   {"group": group}))
                continue
            occurrence: Dict[str, int] = {}
            for pair in pairs:
                try:
                    fn, attrs = pair
                except (TypeError, ValueError):
                    if report is not None:
                        report.append(("particles_paste_bad_group",
                                       {"group": group}))
                    continue
                fn = (str(fn) if fn is not None else "").strip()
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
                    # Модуля с таким именем нет в игре — почти наверняка
                    # опечатка: игра его проигнорирует
                    if report is not None and self._attr_catalog and \
                            (group, fn.lower()) not in self._attr_catalog:
                        report.append(("particles_paste_unknown_module",
                                       {"group": group, "module": fn}))
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
                if self._paste_attrs(target, attrs or {}, overwrite,
                                     report, where=fn, group=group):
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
        vtf_bytes, w, h = built["vtf"], built["w"], built["h"]
        png_b64, sheet, fps = built["png_b64"], built["sheet"], built["fps"]
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
        if vmt_text and fps:
            # Гифка: кадры многокадрового VTF в игре крутит прокси AnimatedTexture
            # ($basetexture/$frame) — как у анимированных текстур оружия.
            from src.services.vmt_service import VMTService
            vmt_text = VMTService.add_animated_texture_proxy(vmt_text, fps)
            logger.info(f"Материал {material_name}: добавлен прокси "
                        f"AnimatedTexture @ {fps}fps")
        if vmt_text:
            # Оригинальный игровой VMT кладём рядом с VTF: текстурная часть
            # мода самодостаточна (casual-pre-loader ставит материалы только
            # из аддонов, и его автор просит модмейкеров включать VMT).
            self.custom_files[f"materials/{_norm_mat(material_name)}"] = (
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
            t = vmt_parse.parse(vmt_text).path("basetexture")
            if t:
                tex_rel = t[:-4] if t.endswith(".vtf") else t
        if tex_rel is None:
            tex_rel = vmt_rel[:-4]
            if tf2_root_dir:
                logger.warning(
                    f"Не удалось прочитать VMT {vmt_rel} — путь текстуры взят "
                    f"из имени материала ({tex_rel}); для казуала проверьте, "
                    f"что такой VTF есть в игре.")
        return vmt_text, tex_rel

    #: Больше кадров в лист не влезает без потери разрешения (8×8 клеток).
    _SHEET_MAX_FRAMES = 64

    @staticmethod
    def _gif_to_sheet(image_path: str, cap: int):
        """Анимированная картинка → (лист-изображение, sheet-данные).

        Кадры раскладываются в сетку из степеней двойки (лист остаётся POT),
        а sheet-данные — тот же формат, что отдаёт parse_vtf_sheet для игровых
        листов, поэтому движок превью анимирует их без единой правки.

        ponytail: скорость проигрывания в превью задаёт 'animation rate'
        рендерера системы, а не собственный fps гифки — так же, как это делает
        игра с настоящим спрайт-листом. Длительности кадров относительные.
        """
        from PIL import Image

        from src.services.texture_service import TextureService

        count, _ = TextureService._animation_info(
            image_path, ParticleEditorService._SHEET_MAX_FRAMES)
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

    @staticmethod
    def _image_to_vtf(image_path: str, max_size: int, uncompressed: bool):
        """Картинка → {vtf, w, h, png_b64, sheet, fps} либо None при ошибке.
        Размеры → степени двойки (<= max_size, потолок 1024). NOMIP|NOLOD.

        Анимированная картинка (GIF/APNG/WebP): VTF многокадровый (в игре кадры
        крутит прокси AnimatedTexture, fps != None), а в превью уходит спрайт-лист
        с sheet-данными — движок превью умеет только листы.
        """
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

        sheet = None
        preview_img = None
        from src.services.texture_service import TextureService
        if TextureService.is_animated_image(image_path):
            try:
                # img (первый кадр в полном разрешении) не трогаем — он идёт в VTF.
                preview_img, sheet = ParticleEditorService._gif_to_sheet(
                    image_path, cap)
            except Exception as exc:
                # Не смогли собрать лист — молча остаёмся на первом кадре.
                logger.warning(f"Гифка → спрайт-лист не удалась: {exc}", exc_info=True)
                sheet = preview_img = None

        w, h = _pot(img.width), _pot(img.height)
        if (w, h) != img.size:
            img = img.resize((w, h), Image.LANCZOS)
        if preview_img is None:
            preview_img = img

        fps = None
        tmp_path = None
        try:
            from src.services.vtflib_wrapper import (
                VTFImageFlags, VTFImageFormat, VTFLib)
            fd, tmp_path = tempfile.mkstemp(suffix=".vtf")
            os.close(fd)
            if sheet is not None:
                # Многокадровый VTF: кадры анимации крутит прокси AnimatedTexture
                # из VMT (тот же механизм, что у анимированных текстур оружия).
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
        preview_img.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"vtf": vtf_bytes, "w": w, "h": h, "png_b64": png_b64,
                "sheet": sheet, "fps": fps}

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
        self._seed_spawn_area(d, mod)
        if group in d:
            d[group].append(mod)
        else:
            arr = Attribute.array(group, ValueType.ELEMENT)
            arr.append(mod)
            d[group] = arr
        return True

    @classmethod
    def _seed_spawn_area(cls, definition, mod) -> bool:
        """
        Даёт вырожденной области спавна видимый размер, соразмерный эффекту.

        Шаблоны стоковых PCF часто приходят с нулевой областью (у бокса
        min == max) — добавленный модуль спавнит всё в одну точку, каркас
        в превью не рисуется и тянуть нечего. Размер берём от радиуса
        частиц системы, чтобы область была соразмерна тому, что видно.
        Осмысленные значения из шаблона не трогаем.
        """
        fn = cls._module_fn(mod)
        if fn not in ("position within box random",
                      "position within sphere random"):
            return False
        radius = 5.0
        if "radius" in definition:
            try:
                radius = abs(definition["radius"].val_float) or 5.0
            except Exception:
                radius = 5.0
        extent = max(4.0, radius * 4.0)

        def _vec(el, name):
            try:
                return list(el[name].val_vec3) if name in el else None
            except Exception:
                return None

        if fn == "position within box random":
            lo, hi = _vec(mod, "min"), _vec(mod, "max")
            if lo is not None and hi is not None and \
                    any(abs(hi[i] - lo[i]) > 1e-6 for i in range(3)):
                return False        # у шаблона нормальный бокс
            mod["min"] = Attribute.vec3(
                mod["min"].name if "min" in mod else "min",
                -extent, -extent, -extent)
            mod["max"] = Attribute.vec3(
                mod["max"].name if "max" in mod else "max",
                extent, extent, extent)
            return True

        try:
            d_max = mod["distance_max"].val_float if "distance_max" in mod else 0.0
        except Exception:
            d_max = 0.0
        if abs(d_max) > 1e-6:
            return False            # у шаблона нормальная сфера
        mod["distance_max"] = Attribute.float(
            mod["distance_max"].name if "distance_max" in mod else "distance_max",
            extent * 1.5)
        return True

    #: Кэш каталогов параметров: {(группа|None, fn_lower): {имя: {"t","v"}}}.
    _attr_catalog: Dict[tuple, Dict[str, dict]] = {}
    #: Каноническое написание functionName: {(группа, fn_lower): "Имя Как В Игре"}.
    _module_display: Dict[tuple, str] = {}
    #: Каноническое написание ИМЁН АТРИБУТОВ, как их пишет игра:
    #: {(группа, fn_lower): {имя_в_нижнем: "Имя Как В Игре"}}.
    #: КРИТИЧНО: Source читает атрибуты С УЧЁТОМ РЕГИСТРА — записанный
    #: строчными 'spin strength' игра игнорирует, ей нужен 'Spin Strength'.
    _attr_canonical: Dict[tuple, Dict[str, str]] = {}
    #: Версия формата дискового кэша (растёт, когда меняется его состав).
    _CATALOG_FORMAT = 5   # 5: + разброс значений параметра (lo/hi/n)

    #: Служебные поля — их не показываем и не даём удалять.
    _SERVICE_ATTRS = ("functionname", "name", "id")

    @staticmethod
    def _attr_catalog_file() -> Path:
        return (Path(os.path.expanduser("~")) / ".tf2skingen_cache"
                / "particle_attr_catalog.json")

    @classmethod
    def _game_stamp(cls, tf2_root_dir: str) -> str:
        """Отпечаток контента игры — чтобы кэш протух после обновления TF2."""
        try:
            _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
            st = Path(misc_vpk).stat()
            return f"{st.st_size}-{int(st.st_mtime)}"
        except Exception:
            return ""

    @classmethod
    def _load_disk_catalog(cls, tf2_root_dir: str) -> bool:
        """Поднимает каталог из файла, если он от той же версии игры."""
        path = cls._attr_catalog_file()
        try:
            if not path.is_file():
                return False
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("stamp") != cls._game_stamp(tf2_root_dir):
                return False
            if data.get("format") != cls._CATALOG_FORMAT:
                return False        # старый кэш без канонических имён
            for key_str, attrs in (data.get("catalog") or {}).items():
                group, _, fn = key_str.partition("|")
                cls._attr_catalog[(group or None, fn)] = attrs
            for key_str, disp in (data.get("display") or {}).items():
                group, _, fn = key_str.partition("|")
                cls._module_display[(group or None, fn)] = disp
            for key_str, names in (data.get("canonical") or {}).items():
                group, _, fn = key_str.partition("|")
                cls._attr_canonical[(group or None, fn)] = names
            cls._game_materials_cache = list(data.get("materials") or [])
        except Exception as exc:
            logger.warning(f"Кэш каталога параметров не прочитан: {exc}")
            return False
        return bool(cls._attr_catalog)

    @classmethod
    def _save_disk_catalog(cls, tf2_root_dir: str) -> None:
        path = cls._attr_catalog_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "format": cls._CATALOG_FORMAT,
                "stamp": cls._game_stamp(tf2_root_dir),
                "catalog": {f"{g or ''}|{fn}": attrs
                            for (g, fn), attrs in cls._attr_catalog.items()},
                "display": {f"{g or ''}|{fn}": name
                            for (g, fn), name in cls._module_display.items()},
                "canonical": {f"{g or ''}|{fn}": names
                              for (g, fn), names in cls._attr_canonical.items()},
                "materials": cls._game_materials_cache or [],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Кэш каталога параметров не сохранён: {exc}")

    @classmethod
    def build_attr_catalog(cls, tf2_root_dir: str) -> None:
        """
        Собирает каталог параметров для ВСЕХ модулей игры за один проход.

        Раньше сканировали под каждый запрошенный модуль отдельно, и
        пользователь ловил пятисекундную паузу снова и снова — теперь
        один скан на всё, плюс он переживает перезапуск приложения.
        """
        if cls._attr_catalog or not tf2_root_dir:
            return
        if cls._load_disk_catalog(tf2_root_dir):
            return
        # Собираем в локальные словари и присваиваем целиком: сбор идёт в
        # фоне, а UI не должен видеть наполовину готовый каталог. Материалы
        # копим в том же проходе — PCF уже загружены, это бесплатно.
        catalog: Dict[tuple, Dict[str, dict]] = {}
        canon: Dict[tuple, Dict[str, Dict[str, int]]] = {}
        materials: set = set()
        for pcf in cls.list_game_pcfs(tf2_root_dir):
            try:
                other = cls()
                other.load_from_game(tf2_root_dir, pcf)
            except Exception:
                continue
            cls._collect_catalog(other, catalog, canon)
            for m in other.material_names():
                if cls._is_particle_material(m):
                    materials.add(m)
        if catalog:
            cls._attr_catalog = catalog
            # Побеждает самое частое написание (см. _canon)
            cls._attr_canonical = {
                key: {low: max(variants.items(), key=lambda kv: kv[1])[0]
                      for low, variants in names.items()}
                for key, names in canon.items()}
            cls._game_materials_cache = sorted(materials, key=str.lower)
            cls._save_disk_catalog(tf2_root_dir)

    @staticmethod
    def _track_range(entry: dict, value: Any) -> None:
        """Копит разброс числового параметра по эффектам игры.

        Одного «примера» мало: по нему не понять, 0.1 — это норма или
        экзотика. Границы нужны и подсказке в дереве свойств, и справочнику
        для ИИ. bool считать бессмысленно, вектора и строки — пропускаем.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        entry["n"] = entry.get("n", 0) + 1
        lo, hi = entry.get("lo"), entry.get("hi")
        entry["lo"] = value if lo is None else min(lo, value)
        entry["hi"] = value if hi is None else max(hi, value)

    @classmethod
    def attr_stats(cls, group: Optional[str], function_name: str,
                   attr_name: str) -> Optional[dict]:
        """
        Как этот параметр настроен в эффектах игры: {'lo','hi','n','v'}.

        Только по уже собранному каталогу — сканирование не запускает
        (его греет фоновый воркер), поэтому годится для подсказок в UI.
        None — каталога нет, параметр не числовой или встречен один раз.
        """
        key = (group, (function_name or "").strip().lower())
        entry = (cls._attr_catalog.get(key) or {}).get(
            (attr_name or "").strip().lower())
        if not entry or entry.get("n", 0) < 2 or entry.get("lo") is None:
            return None
        return entry

    @classmethod
    def _collect_catalog(cls, svc: "ParticleEditorService",
                         catalog: Dict[tuple, Dict[str, dict]],
                         canon: Optional[dict] = None) -> None:
        """Добавляет в каталог параметры всех модулей одного файла."""
        def _canon(key, el):
            """Копит ВАРИАНТЫ написания имён атрибутов со счётчиком.

            Считаем, а не берём первое встреченное: собственный мод
            пользователя тоже лежит в VPK игры и может нести неверный
            регистр — побеждает написание, которое чаще у Valve."""
            if canon is None:
                return
            m = canon.setdefault(key, {})
            for a in el.values():
                per_name = m.setdefault(a.name.lower(), {})
                per_name[a.name] = per_name.get(a.name, 0) + 1

        for d in svc._all_definition_elements():
            sys_cat = catalog.setdefault((None, ""), {})
            for name, tv in _element_attrs_to_json(d).items():
                if name not in cls._SERVICE_ATTRS:
                    cls._track_range(sys_cat.setdefault(name, dict(tv)),
                                     tv["v"])
            _canon((None, ""), d)
            for group in MODULE_GROUPS:
                if group not in d:
                    continue
                try:
                    for mod in d[group].iter_elem():
                        fn = cls._module_fn(mod)
                        cat = catalog.setdefault((group, fn), {})
                        mod_json = _module_to_json(mod)
                        # Каноническое имя нужно для генерации пресетов:
                        # в ключах каталога оно приведено к нижнему регистру
                        cls._module_display.setdefault(
                            (group, fn), mod_json["functionName"])
                        _canon((group, fn), mod)
                        for name, tv in mod_json["attrs"].items():
                            if name not in cls._SERVICE_ATTRS:
                                cls._track_range(
                                    cat.setdefault(name, dict(tv)), tv["v"])
                except Exception:
                    continue

    @classmethod
    def module_attr_catalog(
        cls, group: Optional[str], function_name: str,
        tf2_root_dir: str = "", current: Optional["ParticleEditorService"] = None,
    ) -> Dict[str, dict]:
        """
        Все параметры, которые встречаются у этого модуля в эффектах игры.

        Список полей нигде не задекларирован, поэтому собираем его из
        стоковых PCF. Значение берём первое встреченное: оно заведомо
        осмысленное (так настроено у Valve) и годится как значение по
        умолчанию при добавлении. group=None — параметры самого определения
        системы.
        """
        cls.build_attr_catalog(tf2_root_dir)
        key = (group, (function_name or "").strip().lower())
        catalog = dict(cls._attr_catalog.get(key) or {})
        # Открытый файл может знать поля, которых нет в стоке (чужой мод)
        if current is not None:
            probe: Dict[tuple, Dict[str, dict]] = {}
            cls._collect_catalog(current, probe)
            for name, tv in (probe.get(key) or {}).items():
                catalog.setdefault(name, tv)
        return catalog

    #: Инструкция для ИИ-ассистента, вкладывается в справочник по выбору
    #: пользователя. На английском: модели точнее следуют инструкциям на нём,
    #: а пользователь всё равно пишет свои требования отдельным сообщением.
    _AI_INSTRUCTIONS = [
        "You help build a Team Fortress 2 particle effect. The user sends "
        "you this file TOGETHER WITH their own description of the effect "
        "they want. This file is the reference of everything you may use.",
        "",
        "OUTPUT",
        "- Reply with a single JSON object shaped exactly like "
        "clipboard_format.example in this file, and nothing else around it: "
        "no markdown fences, no comments inside the JSON.",
        "- The user copies it and presses Ctrl+V in the editor, so it must "
        "be valid JSON on its own.",
        "- After the JSON, in a separate message part, add a short "
        "plain-language summary of what each module does, so the user can "
        "tweak it.",
        "",
        "HARD RULES",
        "- Use ONLY module names and parameter names that appear in "
        "'modules' and 'system_params' of this file. Never invent or guess "
        "names: unknown ones are silently ignored on paste.",
        "- One preset describes ONE particle system. Child systems cannot "
        "be created through the clipboard. If the effect needs layers, say "
        "so and tell the user to add a layer in the editor and paste a "
        "second preset into it.",
        "- Include only parameters you actually want to change. Anything "
        "omitted keeps the engine default, which is usually what you want.",
        "- A visible system needs at least one emitter and one renderer "
        "(render_animated_sprites is the usual renderer).",
        "- Order matters inside a group: position initializers run in "
        "sequence, so 'Position Modify Offset Random' must come after the "
        "module that sets the base position.",
        "- Modules marked \"previewed\": false do work in game but are NOT "
        "simulated by the editor's 3D preview. Prefer previewed modules, "
        "and warn the user when you use one.",
        "- \"full\" decides how the paste behaves and must match what the "
        "user wants:",
        "    \"full\": false — an ADDITION. Parameters you list are merged "
        "into the system: matching ones are overwritten, everything else "
        "the system already has stays untouched. Use this to adjust or "
        "extend an existing effect.",
        "    \"full\": true — a COMPLETE effect. On paste the editor asks "
        "the user whether to keep the existing parameters or replace the "
        "system entirely, so send a self-sufficient set: emitter, position "
        "and lifetime initializers, renderer, material, and anything else "
        "the effect needs to work on its own.",
        "",
        "UNITS AND CONVENTIONS",
        "- Distances are Hammer units: a player is about 83 units tall, a "
        "weapon about 30 units long, 1 unit is roughly 1.9 cm. Z is up.",
        "- Times are in seconds. Colors are [r, g, b, a], each 0-255.",
        "- 'material' is the particle texture. Pick one from "
        "available_materials.paths in this file — those are the materials "
        "that actually ship with the game, so the effect works without the "
        "user supplying any texture. Copy the path exactly, including "
        "backslashes (escape them in JSON: \"effects\\\\crit.vmt\"). Never "
        "invent a material path: a missing material means no texture in game.",
        "- 'example' values in this file come from real game effects. They "
        "are not engine defaults; use them as a sanity check for scale.",
        "- ANIMATED textures (a material whose .vtf is a multi-frame sprite "
        "sheet, e.g. animated butterflies/vortex): to make the frames play, "
        "the render_animated_sprites renderer needs either "
        "\"animation_fit_lifetime\": true (plays the whole sheet once over "
        "each particle's lifetime — the safe default), OR a high "
        "\"animation rate\" with \"use animation rate as fps\": true where "
        "the rate is frames per second (~24-30). 'animation rate': 1 means "
        "one frame per second — a 32-frame sheet then looks frozen. When the "
        "user asks for an animated texture, always set one of these.",
        "- To make a sprite face the direction it moves ON SCREEN (a "
        "butterfly, spider or ghost flying head-first), add a SECOND "
        "renderer 'render_screen_velocity_rotate' with 'forward_angle' "
        "(degrees, usually 90 or -90 depending on which way the texture's "
        "head points) alongside render_animated_sprites — this is what the "
        "game's own effects use. Do NOT use the 'Rotation Orient to 2D "
        "Direction' operator for this: it orients in the WORLD horizontal "
        "plane (compass heading, top-down view), so camera-facing sprites "
        "end up sideways; it only suits flat/top-down sprites such as "
        "shark fins on water.",
        "",
        "ASK BEFORE ANSWERING",
        "Always make sure you know ONE thing before writing any JSON: is "
        "this a brand-new effect that should replace the whole system "
        "(\"full\": true), or an addition to an effect the user already "
        "has (\"full\": false)? If the user did not say, ask.",
        "Then, if the description leaves any of the following unclear, ask "
        "about them too — in one short message, at most four questions, "
        "and wait for the answer:",
        "1. Spawn area: a single point, a sphere or a box, and how large.",
        "2. Context and scale: on a weapon, on the player, or an explosion "
        "in the world? How large should it read on screen?",
        "3. Timing: a one-shot burst or a continuous stream, and for how "
        "long each particle lives.",
        "4. Look: colors, whether particles glow, and how they move "
        "(fly outward, rise, fall, hover, swirl).",
        "5. Density: roughly how many particles at once.",
        "If the description is already detailed, skip the questions and "
        "answer directly.",
    ]

    @staticmethod
    def _param_reference_entry(tv: dict) -> dict:
        """Описание одного параметра для справочника: тип, пример и разброс.

        Разброс по эффектам игры отвечает на вопрос, который не решается
        одним примером: 0.1 — это норма или экзотика.
        """
        entry = {"type": tv["t"], "example": tv["v"]}
        if tv.get("lo") is not None and tv.get("lo") != tv.get("hi"):
            entry["range"] = [tv["lo"], tv["hi"]]
        return entry

    @classmethod
    def param_reference(cls, tf2_root_dir: str = "",
                        supported: Optional[dict] = None,
                        with_prompt: bool = False,
                        materials: Optional[List[str]] = None) -> dict:
        """
        Справочник параметров для генерации пресетов внешними средствами.

        Отдаёт всё, что нужно, чтобы собрать корректный набор параметров
        и вставить его в редактор через буфер обмена: формат буфера, типы
        значений, модули по группам с их параметрами и примерами значений
        из эффектов игры, плюс отметка, какие модули отыгрывает превью.
        """
        cls.build_attr_catalog(tf2_root_dir)
        # У части модулей в файлах игры старое написание имени — движок
        # превью знает их через таблицу алиасов, учитываем и здесь
        aliases = {str(k).lower(): str(v).lower()
                   for k, v in ((supported or {}).get("aliases") or {}).items()}
        groups: Dict[str, dict] = {}
        for (group, fn), attrs in sorted(
                cls._attr_catalog.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
            if group is None:
                continue
            entry = {
                "params": {name: cls._param_reference_entry(tv)
                           for name, tv in sorted(attrs.items())},
            }
            if supported is not None:
                known = {str(s).strip().lower()
                         for s in (supported.get(group) or [])}
                entry["previewed"] = aliases.get(fn, fn) in known
            groups.setdefault(group, {})[
                cls._module_display.get((group, fn), fn)] = entry

        system_attrs = cls._attr_catalog.get((None, ""), {})
        reference: Dict[str, Any] = {
            "format": 1,
            "about": "Справочник параметров частиц TF2. Соберите набор в "
                     "поле clipboard_format.example и вставьте его в "
                     "редактор через Ctrl+V (правый клик по дереву свойств "
                     "→ Вставить параметры).",
            "notes": [
                "Имена параметров и модулей писать точно как здесь.",
                "example — значение из реального эффекта игры, а не "
                "умолчание движка: это ориентир по смыслу и порядку величин.",
                "range — [минимум, максимум] этого параметра по всем "
                "эффектам игры: значения вне него почти наверняка ошибка "
                "порядка величины.",
                "Отсутствующий параметр не ошибка: движок берёт своё "
                "умолчание. Указывайте только то, что нужно менять.",
                "previewed=false — модуль работает в игре, но 3D-превью "
                "редактора его не симулирует.",
            ],
            "value_types": {
                "float": "число, например 1.5",
                "integer": "целое число",
                "bool": "true / false",
                "string": "строка, например \"effects\\\\crit.vmt\"",
                "vec3": "[x, y, z]",
                "color": "[r, g, b, a], каждое 0-255",
            },
            "clipboard_format": {
                "description": "Значение JSON, которое кладётся в буфер "
                               "обмена. attrs — параметры самой системы, "
                               "modules — модули по группам: список пар "
                               "[имя модуля, {параметры}]. full=true "
                               "означает полный набор — при вставке "
                               "редактор спросит, заменять ли существующие.",
                "example": {
                    "tf2sgParticleParams": {
                        "attrs": {"max_particles": {"t": "integer", "v": 50},
                                  "radius": {"t": "float", "v": 8.0}},
                        "modules": {
                            "emitters": [["emit_instantaneously", {
                                "num_to_emit": {"t": "integer", "v": 30}}]],
                            "initializers": [["Lifetime Random", {
                                "lifetime_min": {"t": "float", "v": 0.5},
                                "lifetime_max": {"t": "float", "v": 1.2}}]],
                        },
                        "full": False,
                    }
                },
            },
            "module_groups": list(MODULE_GROUPS),
            "system_params": {name: cls._param_reference_entry(tv)
                              for name, tv in sorted(system_attrs.items())},
            "modules": groups,
        }
        if materials is not None:
            # Текстуры частиц, которые уже есть в игре: эффект с таким
            # материалом работает сразу, ничего доустанавливать не нужно
            reference["available_materials"] = {
                "about": "Particle materials shipped with the game. Use one "
                         "of these as the 'material' value; paths are exact.",
                "count": len(materials),
                "paths": list(materials),
            }
        if with_prompt:
            # Инструкция идёт первым ключом: модели читают файл сверху вниз
            reference = {"instructions_for_ai": "\n".join(cls._AI_INSTRUCTIONS),
                         **reference}
        return reference

    @classmethod
    def group_module_catalog(cls, group: str, tf2_root_dir: str = "") -> List[str]:
        """
        Полный список модулей группы для диалога «Добавить модуль…».

        Ходовые (и понятные превью) идут первыми из MODULE_CATALOG, затем —
        ВСЕ остальные модули этой группы, что реально встречаются в эффектах
        игры (из _module_display, канонический регистр). Так в списке есть
        всё, а частое — под рукой.
        """
        curated = list(MODULE_CATALOG.get(group, []))
        seen = {name.lower() for name in curated}
        cls.build_attr_catalog(tf2_root_dir)
        rest = []
        for (g, fn), display in cls._module_display.items():
            if g == group and fn not in seen:
                rest.append(display)
                seen.add(fn)
        return curated + sorted(rest, key=str.lower)

    def missing_attrs(
        self, system_name: str, group: Optional[str], module_index: int,
        tf2_root_dir: str = "",
    ) -> Dict[str, dict]:
        """Параметры из каталога, которых у этого модуля/системы ещё нет."""
        d = self._find_definition(system_name)
        if d is None:
            return {}
        el = d
        fn = ""
        if group is not None:
            if group not in d:
                return {}
            try:
                el = list(d[group].iter_elem())[module_index]
            except (IndexError, Exception):
                return {}
            fn = self._module_fn(el)
        catalog = self.module_attr_catalog(group, fn, tf2_root_dir, current=self)
        return {name: tv for name, tv in catalog.items() if name not in el}

    def remove_attr(self, system_name: str, group: Optional[str],
                    module_index: int, attr_name: str) -> bool:
        """
        Удаляет параметр — значение возвращается к умолчанию движка.

        Полезно вдвойне: убирает лишнее и уменьшает PCF (для казуала файл
        не должен превышать оригинальный).
        """
        if (attr_name or "").lower() in self._SERVICE_ATTRS:
            return False
        d = self._find_definition(system_name)
        if d is None:
            return False
        el = d
        if group is not None:
            if group not in d:
                return False
            try:
                el = list(d[group].iter_elem())[module_index]
            except (IndexError, Exception):
                return False
        if attr_name not in el:
            return False
        del el[attr_name]
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

    def rename_system(self, old_name: str, new_name: str) -> bool:
        """
        Переименовывает систему вместе со всеми ссылками на неё.

        Дети ссылаются на объект-определение, а не на имя, поэтому связь
        не рвётся; но у элемента-ссылки (DmeParticleChild) собственное имя
        совпадает с именем ребёнка — приводим и его, иначе файл выглядит
        рассогласованным.
        """
        new_name = (new_name or "").strip()
        target = self._find_definition(old_name)
        if target is None or not new_name or new_name == old_name:
            return False
        if self._find_definition(new_name) is not None:
            return False        # имя занято

        target.name = new_name
        if "name" in target:
            target["name"] = Attribute.string(target["name"].name, new_name)

        for el in self._all_definition_elements():
            if "children" not in el:
                continue
            try:
                for ch in el["children"].iter_elem():
                    if "child" not in ch:
                        continue
                    try:
                        if ch["child"].val_elem is target:
                            ch.name = new_name
                    except Exception:
                        continue
            except Exception:
                continue
        return True

    def rename_material(self, old_material: str, new_material: str) -> bool:
        """
        Меняет путь материала у всех систем, где он используется.

        Если текстура была заменена своей картинкой, кастомные файлы
        переезжают на новый путь (и VMT начинает ссылаться на новый VTF) —
        так эффект получает СВОЙ материал вместо перезаписи стокового,
        и замена перестаёт менять текстуру у других эффектов игры.
        """
        new_material = (new_material or "").strip()
        if not new_material or not old_material:
            return False
        old_key, new_key = _norm_mat(old_material), _norm_mat(new_material)
        if old_key == new_key:
            return False

        changed = False
        for el in self._all_definition_elements():
            if "material" not in el:
                continue
            try:
                if _norm_mat(el["material"].val_str) != old_key:
                    continue
            except Exception:
                continue
            el["material"] = Attribute.string(
                el["material"].name, new_material)
            changed = True
        if not changed:
            return False

        entry = self._overwritten.pop(old_key, None)
        if entry is not None:
            old_tex = entry["tex_rel"]
            new_tex = new_key[:-4] if new_key.endswith(".vmt") else new_key
            vtf = self.custom_files.pop(f"materials/{old_tex}.vtf", None)
            vmt = self.custom_files.pop(f"materials/{old_key}", None)
            if vtf is not None:
                self.custom_files[f"materials/{new_tex}.vtf"] = vtf
            if vmt is not None:
                text = vmt.decode("utf-8", errors="replace")
                text = _RE_BASETEXTURE_LINE.sub(
                    f'\t"$basetexture" "{new_tex}"', text)
                self.custom_files[f"materials/{new_key}"] = text.encode("utf-8")
            self._overwritten[new_key] = {
                "tex_rel": new_tex, "material": new_material}
            info = self._custom_material_info.pop(old_key, None)
            if info is not None:
                self._custom_material_info[new_key] = info
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
