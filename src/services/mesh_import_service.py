"""
Импорт «интернетных» моделей (OBJ, glTF/GLB) в SMD «только геометрия».

Человеку, который нашёл модель на сайте, не нужен Blender ради экспорта в
SMD: приложение читает файл само, кладёт все вершины на одну кость `root`
(дальше её сажает на хват оружия `SMDService.replace_model_sections`) и
запекает подгонку — масштаб, поворот, сдвиг — прямо в вершины. Через QC
(`$scale`/`$origin`) подгонять нельзя: `$scale` растягивает и скелет, и
attachment'ы (дульная вспышка, гильзы, unusual_0), оружие уезжает из рук.

Оси. OBJ и glTF живут в Y-up (у glTF вперёд −Z). Оружие TF2 в SMD тоже Y-up,
но стволом в +Z (см. `$attachment "muzzle" ... rotate -90 0 0` у c_-моделей).
Поэтому импорт разворачивает модель на 180° вокруг Y: (x, y, z) → (−x, y, −z).
Это собственный поворот (det = +1), обход треугольников сохраняется — у
glTF/OBJ лицевая сторона против часовой, как и у SMD из Blender.

Лимиты studiomdl (public/studio.h): MAXSTUDIOVERTS = MAXSTUDIOTRIANGLES =
65536. Вершины считаются после разрезания по нормалям и UV-швам, поэтому
модель на 40k треугольников с острыми гранями легко даёт 80k вершин — считаем
именно так, а не по числу позиций. Что выше лимита — упрощаем (`simplify`,
meshoptimizer с сохранением UV: см. tools/meshoptimizer).

Геометрия хранится в numpy: у скульпта из интернета миллионы треугольников,
и кортежи Python на них съедали бы гигабайты и десятки секунд.
"""

import base64
import ctypes
import io
import json
import math
import os
import struct
import tempfile
from array import array
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.shared.logging_config import get_logger
from src.shared.paths import install_dir

logger = get_logger(__name__)

#: public/studio.h: MAXSTUDIOVERTS / MAXSTUDIOTRIANGLES (не Xbox)
MAX_STUDIO_VERTS = 65536
MAX_STUDIO_TRIANGLES = 65536
#: MAXSTUDIOSKINS — материалов на модель
MAX_STUDIO_SKINS = 32
#: Куда упрощаем: чуть ниже лимита, чтобы вершины после разрезания влезли.
SIMPLIFY_TARGET_TRIANGLES = 60000

SUPPORTED_EXTENSIONS = ('.obj', '.gltf', '.glb')

Vec3 = Tuple[float, float, float]

#: Колонки `Mesh.corners`: x y z nx ny nz u v
_COLS = 8


class MeshImportError(ValueError):
    """Файл не прочитан или не годится для studiomdl. Текст — человеку."""


@dataclass
class Mesh:
    """Треугольники подряд по материалам, уже в осях SMD оружия.

    `corners` — (3·T, 8) float32: позиция, нормаль, UV каждого угла;
    `groups` — (материал, первый треугольник, сколько), в порядке файла.
    """
    corners: np.ndarray = field(default_factory=lambda: np.zeros((0, _COLS), np.float32))
    groups: List[Tuple[str, int, int]] = field(default_factory=list)
    has_uv: bool = True
    #: Базовый цвет из MTL (`map_Kd`) / glTF (`baseColorTexture`): материал → файл.
    textures: Dict[str, str] = field(default_factory=dict)
    #: Скиннинг из glTF: имена костей и на каждый угол (3T, 8) — четыре номера
    #: кости в `bones` и четыре веса. None — костей в файле нет, всё на `root`.
    #: Кости сопоставляются с игровыми ПО ИМЕНИ (SMDService._bone_mapping):
    #: назвав их как в игре (weapon_bone, weapon_bone_1…), получают анимацию
    #: частей; чужие имена садятся на хват.
    bones: List[str] = field(default_factory=list)
    skin: Optional[np.ndarray] = None

    @property
    def triangle_count(self) -> int:
        return len(self.corners) // 3

    @property
    def materials(self) -> List[str]:
        return [g[0] for g in self.groups]

    def triangles(self, material: str) -> np.ndarray:
        """(n, 3, 8) — треугольники одного материала."""
        for name, first, count in self.groups:
            if name == material:
                return self.corners[first * 3:(first + count) * 3].reshape(-1, 3, _COLS)
        return np.zeros((0, 3, _COLS), np.float32)

    def vertex_count(self) -> int:
        """Вершины по-studiomdl: уникальные (позиция, нормаль, UV, кости)."""
        rows = self.corners if self.skin is None else np.hstack([self.corners, self.skin])
        return len(_unique_rows(rows)[0])


def _unique_rows(rows: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """(уникальные строки, номер строки для каждого угла) — по округлённым
    значениям: studiomdl сваривает то, что совпало после квантования."""
    if len(rows) == 0:
        return rows, np.zeros(0, np.int64)
    keyed = np.ascontiguousarray(np.round(rows, 4).astype(np.float32))
    packed = keyed.view(np.dtype((np.void, keyed.dtype.itemsize * rows.shape[1]))).ravel()
    _, first, inverse = np.unique(packed, return_index=True, return_inverse=True)
    return rows[first], inverse.ravel()


@dataclass(frozen=True)
class Fit:
    """Подгонка в осях SMD оружия: масштаб, повороты вокруг X/Y/Z в градусах
    (применяются X → Y → Z), сдвиг в юнитах."""
    scale: float = 1.0
    rotate: Vec3 = (0.0, 0.0, 0.0)
    offset: Vec3 = (0.0, 0.0, 0.0)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Fit":
        d = d or {}

        def num(v, default=0.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        rot = d.get('rotate') or (0, 0, 0)
        off = d.get('offset') or (0, 0, 0)
        scale = num(d.get('scale', 1.0), 1.0)
        if scale <= 0:
            scale = 1.0
        return cls(scale=scale,
                   rotate=tuple(num(v) for v in rot)[:3],
                   offset=tuple(num(v) for v in off)[:3])

    def to_dict(self) -> dict:
        return {'scale': self.scale, 'rotate': list(self.rotate),
                'offset': list(self.offset)}

    def matrix(self) -> List[List[float]]:
        """3×3: Rz · Ry · Rx (без масштаба — он отдельно, нормали не трогает)."""
        rx, ry, rz = (math.radians(a) for a in self.rotate)
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        return (mz @ my @ mx).tolist()


# ── Чтение ───────────────────────────────────────────────────────────────── #

def load_mesh(path: str) -> Mesh:
    """OBJ или glTF/GLB → Mesh в осях SMD оружия. Ошибки — MeshImportError."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise MeshImportError(
            f'Формат {ext or "без расширения"} не поддерживается: нужен OBJ, GLB или glTF')
    if not os.path.isfile(path):
        raise MeshImportError('Файл модели не найден')
    mesh = _load_obj(path) if ext == '.obj' else _load_gltf(path)
    if mesh.triangle_count == 0:
        raise MeshImportError('В файле нет ни одного треугольника')
    return mesh


def check_limits(mesh: Mesh) -> Optional[str]:
    """Текст ошибки, если studiomdl такое не скомпилирует; None — в лимитах."""
    tris, verts = mesh.triangle_count, mesh.vertex_count()
    mats, limit = len(mesh.groups), MAX_STUDIO_VERTS
    if tris > MAX_STUDIO_TRIANGLES:
        return f'{tris} треугольников — лимит игры {limit}. Упростите модель в редакторе'
    if verts > MAX_STUDIO_VERTS:
        return f'{verts} вершин (после разрезания по швам и рёбрам) — лимит игры {limit}. Упростите модель в редакторе'
    if mats > MAX_STUDIO_SKINS:
        return f'{mats} материалов — лимит игры {MAX_STUDIO_SKINS}. Объедините материалы в редакторе'
    return None


def over_limits(mesh: Mesh) -> bool:
    """Не влезает по треугольникам или вершинам — то, что лечится упрощением."""
    return (mesh.triangle_count > MAX_STUDIO_TRIANGLES
            or mesh.vertex_count() > MAX_STUDIO_VERTS)


def _to_weapon_axes(rows: np.ndarray) -> np.ndarray:
    """Y-up, вперёд −Z (glTF/OBJ) → SMD оружия: Y-up, стволом в +Z.
    Годится и позициям, и нормалям (меняют знак столбцы x и z)."""
    out = rows.astype(np.float32, copy=True)
    out[:, 0] *= -1
    out[:, 2] *= -1
    return out


def _material_name(raw: str, index: int) -> str:
    from src.services.smd_service import SMDService
    name = SMDService._sanitize_material_name(raw)
    # studiomdl имя не пустое и без пробелов/слэшей: это имя VMT-файла.
    name = ''.join(ch if (ch.isalnum() or ch in '_-') else '_' for ch in name)
    return name or f'material_{index}'


def _flat_normals(pos: np.ndarray) -> np.ndarray:
    """(3T, 3) позиций → (3T, 3) плоских нормалей по треугольникам."""
    tri = pos.reshape(-1, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(length == 0, 1.0, length)
    return np.repeat(n, 3, axis=0).astype(np.float32)


def _assemble(pos: np.ndarray, nrm: Optional[np.ndarray], uv: Optional[np.ndarray],
              missing_nrm: Optional[np.ndarray] = None) -> np.ndarray:
    """Углы (3T, 8) в осях SMD из массивов в осях файла.

    `missing_nrm` — маска углов без нормали в файле (OBJ разрешает смешивать):
    им достаётся плоская нормаль треугольника.
    """
    flat = _flat_normals(pos)
    if nrm is None:
        nrm = flat
    elif missing_nrm is not None and missing_nrm.any():
        nrm = np.where(missing_nrm[:, None], flat, nrm)
    if uv is None:
        uv = np.zeros((len(pos), 2), np.float32)
    return np.hstack([_to_weapon_axes(pos), _to_weapon_axes(nrm),
                      uv.astype(np.float32)]).astype(np.float32)


def _load_obj(path: str) -> Mesh:
    positions: List[float] = []
    uvs: List[float] = []
    normals: List[float] = []
    #: Углы по материалам: имя → array из троек (v, vt, vn); -1 — нет
    faces: Dict[str, array] = {}
    order: List[str] = []
    material = 'material_0'
    mat_index = 0
    mtl_names: Dict[str, str] = {}      # имя после чистки → как в файле
    mtllib: List[str] = []

    def index(raw: str, count: int) -> int:
        if not raw:
            return -1
        i = int(raw)
        return i - 1 if i > 0 else count + i

    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0].startswith('#'):
                continue
            tag = parts[0]
            try:
                if tag == 'v' and len(parts) >= 4:
                    positions += (float(parts[1]), float(parts[2]), float(parts[3]))
                elif tag == 'vt' and len(parts) >= 3:
                    uvs += (float(parts[1]), float(parts[2]))
                elif tag == 'vn' and len(parts) >= 4:
                    normals += (float(parts[1]), float(parts[2]), float(parts[3]))
                elif tag == 'usemtl':
                    mat_index += 1
                    raw = ' '.join(parts[1:])
                    material = _material_name(raw, mat_index)
                    mtl_names.setdefault(material, raw)
                elif tag == 'mtllib':
                    mtllib.append(' '.join(parts[1:]))
                elif tag == 'f' and len(parts) >= 4:
                    corners = []
                    for token in parts[1:]:
                        vi, ti, ni = (token.split('/') + ['', ''])[:3]
                        corners.append((index(vi, len(positions) // 3),
                                        index(ti, len(uvs) // 2),
                                        index(ni, len(normals) // 3)))
                    if material not in faces:
                        faces[material] = array('q')
                        order.append(material)
                    dst = faces[material]
                    # Полигон → веер треугольников (OBJ разрешает n-угольники).
                    for k in range(1, len(corners) - 1):
                        dst.extend(corners[0])
                        dst.extend(corners[k])
                        dst.extend(corners[k + 1])
            except (ValueError, IndexError) as exc:
                raise MeshImportError(f'OBJ повреждён: строка «{line.strip()[:60]}» ({exc})')

    pos_arr = np.array(positions, np.float32).reshape(-1, 3)
    uv_arr = np.array(uvs, np.float32).reshape(-1, 2)
    nrm_arr = np.array(normals, np.float32).reshape(-1, 3)
    chunks, groups, first = [], [], 0
    has_uv = False
    for material in order:
        idx = np.frombuffer(faces[material], dtype=np.int64).reshape(-1, 3)
        vi, ti, ni = idx[:, 0], idx[:, 1], idx[:, 2]
        if (vi < 0).any() or (vi >= len(pos_arr)).any():
            raise MeshImportError('OBJ повреждён: грань ссылается на несуществующую вершину')
        uv_ok = (ti >= 0) & (ti < len(uv_arr))
        uv = np.zeros((len(vi), 2), np.float32)
        uv[uv_ok] = uv_arr[ti[uv_ok]]
        has_uv = has_uv or bool(uv_ok.any())
        nrm_ok = (ni >= 0) & (ni < len(nrm_arr))
        nrm = np.zeros((len(vi), 3), np.float32)
        nrm[nrm_ok] = nrm_arr[ni[nrm_ok]]
        chunks.append(_assemble(pos_arr[vi], nrm, uv, missing_nrm=~nrm_ok))
        count = len(vi) // 3
        groups.append((material, first, count))
        first += count
    mesh = Mesh(corners=np.vstack(chunks) if chunks else np.zeros((0, _COLS), np.float32),
                groups=groups, has_uv=has_uv)
    mesh.textures = _obj_textures(path, mtllib, mtl_names)
    return mesh


def _obj_textures(obj_path: str, mtllib: List[str], names: Dict[str, str]) -> Dict[str, str]:
    """map_Kd из MTL рядом с OBJ: материал → путь к картинке (если файл есть)."""
    base = os.path.dirname(obj_path)
    by_raw = {raw: clean for clean, raw in names.items()}
    out: Dict[str, str] = {}
    for lib in mtllib or []:
        mtl = os.path.join(base, lib)
        if not os.path.isfile(mtl):
            continue
        current = None
        try:
            with open(mtl, encoding='utf-8', errors='replace') as f:
                for line in f:
                    parts = line.split()
                    if not parts:
                        continue
                    if parts[0] == 'newmtl':
                        current = by_raw.get(' '.join(parts[1:]))
                    elif parts[0].lower() == 'map_kd' and current and len(parts) > 1:
                        # Опции (-s, -o …) идут перед именем файла: берём последнее.
                        img = os.path.join(base, parts[-1].replace('\\', '/'))
                        if os.path.isfile(img):
                            out[current] = img
        except OSError:
            continue
    return out


# glTF: componentType → numpy dtype
_GLTF_DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
                5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_GLTF_TYPE_SIZE = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
                   'MAT4': 16, 'MAT3': 9, 'MAT2': 4}
_GLTF_MIME_EXT = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
_GLTF_BROKEN = 'glTF повреждён или использует расширение, которое не поддерживается ({})'


def _load_gltf(path: str) -> Mesh:
    with open(path, 'rb') as f:
        data = f.read()
    base_dir = os.path.dirname(path)
    buffers: List[bytes] = []
    if data[:4] == b'glTF':
        # GLB: заголовок 12 байт, дальше чанки (длина, тип, данные).
        _, _, total = struct.unpack_from('<III', data, 0)
        pos, doc, bin_chunk = 12, None, b''
        while pos + 8 <= min(total, len(data)):
            length, kind = struct.unpack_from('<II', data, pos)
            chunk = data[pos + 8:pos + 8 + length]
            if kind == 0x4E4F534A:
                doc = json.loads(chunk.decode('utf-8'))
            elif kind == 0x004E4942:
                bin_chunk = chunk
            pos += 8 + length
        if doc is None:
            raise MeshImportError('GLB без JSON-описания')
        for i, b in enumerate(doc.get('buffers') or []):
            buffers.append(_gltf_buffer(b, base_dir, bin_chunk if i == 0 else None))
    else:
        try:
            doc = json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MeshImportError(f'glTF не разобран: {exc}')
        for b in doc.get('buffers') or []:
            buffers.append(_gltf_buffer(b, base_dir, None))

    def view_bytes(view_idx: int, offset: int = 0, length: Optional[int] = None) -> bytes:
        view = doc['bufferViews'][view_idx]
        buf = buffers[view['buffer']]
        start = view.get('byteOffset', 0) + offset
        span = view['byteLength'] - offset if length is None else length
        return buf[start:start + span]

    def accessor(idx: int) -> np.ndarray:
        acc = doc['accessors'][idx]
        dtype = np.dtype(_GLTF_DTYPES[acc['componentType']]).newbyteorder('<')
        width = _GLTF_TYPE_SIZE[acc['type']]
        count = acc['count']
        if 'bufferView' not in acc:
            return np.zeros((count, width), np.float32)
        view = doc['bufferViews'][acc['bufferView']]
        row = dtype.itemsize * width
        stride = view.get('byteStride') or row
        raw = view_bytes(acc['bufferView'], acc.get('byteOffset', 0), stride * (count - 1) + row)
        if stride == row:
            vals = np.frombuffer(raw, dtype=dtype, count=count * width).reshape(count, width)
        else:
            vals = np.lib.stride_tricks.as_strided(
                np.frombuffer(raw, dtype=np.uint8), shape=(count, row), strides=(stride, 1)
            ).copy().view(dtype).reshape(count, width)
        out = vals.astype(np.float32)
        if acc.get('normalized') and dtype.kind in 'iu':
            out = np.maximum(out / np.iinfo(dtype).max, -1.0)
        return out

    materials = doc.get('materials') or []
    has_uv = [False]
    # Один материал может прийти из нескольких примитивов: сливаем в одну
    # группу по имени, чтобы studiomdl не получил дубли.
    pending: Dict[str, List[np.ndarray]] = {}
    pending_skin: Dict[str, List[np.ndarray]] = {}
    order: List[str] = []

    # Кости: все суставы всех скинов, по имени узла. Номер в `bones` —
    # общий для модели; у примитива JOINTS_0 нумерует суставы своего скина.
    nodes = doc.get('nodes') or []
    bones: List[str] = []
    bone_of_node: Dict[int, int] = {}
    for sk in doc.get('skins') or []:
        for j in sk.get('joints') or []:
            if j not in bone_of_node and j < len(nodes):
                bone_of_node[j] = len(bones)
                bones.append(nodes[j].get('name') or f'bone_{j}')
    any_skin = bool(bones)

    def skin_rows(prim: dict, node: dict, idx: np.ndarray,
                  bone_parent: Optional[int]) -> np.ndarray:
        """(3T, 8): 4 номера костей + 4 веса на угол."""
        attrs = prim.get('attributes') or {}
        rows = np.zeros((len(idx), 8), np.float32)
        if 'skin' in node and 'JOINTS_0' in attrs and 'WEIGHTS_0' in attrs:
            joints = doc['skins'][node['skin']].get('joints') or []
            lut = np.array([bone_of_node.get(j, 0) for j in joints] or [0], np.float32)
            jn = np.clip(accessor(attrs['JOINTS_0'])[:, :4].astype(np.int64), 0, len(lut) - 1)
            wt = accessor(attrs['WEIGHTS_0'])[:, :4]
            total = wt.sum(axis=1, keepdims=True)
            wt = wt / np.where(total == 0, 1.0, total)
            rows[:, :4] = lut[jn][idx]
            rows[:, 4:] = wt[idx]
        else:
            # Меш без скина, но под костью (в Blender — «parent to bone»):
            # целиком на неё; без кости — на первую, дальше её пересадит хват.
            rows[:, 0] = bone_parent if bone_parent is not None else 0
            rows[:, 4] = 1.0
        return rows

    def visit(node_idx: int, parent: np.ndarray, bone_parent: Optional[int]) -> None:
        node = doc['nodes'][node_idx]
        world = parent @ _gltf_node_matrix(node)
        rot = world[:3, :3]
        if node_idx in bone_of_node:
            bone_parent = bone_of_node[node_idx]
        if 'mesh' in node:
            for prim in doc['meshes'][node['mesh']].get('primitives') or []:
                if prim.get('mode', 4) != 4:
                    continue                 # линии/точки/полосы — не наш случай
                attrs = prim.get('attributes') or {}
                if 'POSITION' not in attrs:
                    continue
                if 'skin' in node:
                    # По спецификации glTF скиннутый меш лежит в пространстве
                    # скелета, трансформ его узла не применяется.
                    world = np.eye(4)
                    rot = world[:3, :3]
                pos = accessor(attrs['POSITION'])[:, :3] @ rot.T + world[:3, 3]
                nrm = None
                if 'NORMAL' in attrs:
                    nrm = accessor(attrs['NORMAL'])[:, :3] @ np.linalg.inv(rot).T
                    length = np.linalg.norm(nrm, axis=1, keepdims=True)
                    nrm = nrm / np.where(length == 0, 1.0, length)
                uv = None
                if 'TEXCOORD_0' in attrs:
                    uv = accessor(attrs['TEXCOORD_0'])[:, :2].copy()
                    uv[:, 1] = 1.0 - uv[:, 1]        # glTF сверху вниз, SMD снизу вверх
                    has_uv[0] = True
                if 'indices' in prim:
                    idx = accessor(prim['indices'])[:, 0].astype(np.int64)
                else:
                    idx = np.arange(len(pos))
                idx = idx[:len(idx) - len(idx) % 3]
                if (idx >= len(pos)).any():
                    raise MeshImportError(_GLTF_BROKEN.format('index out of range'))
                mi = prim.get('material')
                raw_name = (materials[mi].get('name') if mi is not None
                            and mi < len(materials) else '') or f'material_{mi or 0}'
                material = _material_name(raw_name, (mi or 0) + 1)
                if material not in pending:
                    pending[material] = []
                    order.append(material)
                pending[material].append(_assemble(
                    pos[idx].astype(np.float32),
                    None if nrm is None else nrm[idx].astype(np.float32),
                    None if uv is None else uv[idx]))
                if any_skin:
                    pending_skin.setdefault(material, []).append(
                        skin_rows(prim, node, idx, bone_parent))
        for child in node.get('children') or []:
            visit(child, world, bone_parent)

    scene_idx = doc.get('scene', 0)
    scenes = doc.get('scenes') or []
    roots = (scenes[scene_idx].get('nodes') if scene_idx < len(scenes)
             else list(range(len(doc.get('nodes') or []))))
    try:
        for r in roots or []:
            visit(r, np.eye(4), None)
    except (KeyError, IndexError, ValueError, struct.error) as exc:
        raise MeshImportError(_GLTF_BROKEN.format(exc))

    chunks, skins, groups, first = [], [], [], 0
    for material in order:
        block = np.vstack(pending[material])
        chunks.append(block)
        if any_skin:
            skins.append(np.vstack(pending_skin[material]))
        count = len(block) // 3
        groups.append((material, first, count))
        first += count
    mesh = Mesh(corners=np.vstack(chunks) if chunks else np.zeros((0, _COLS), np.float32),
                groups=groups, has_uv=has_uv[0], bones=bones,
                skin=np.vstack(skins) if skins else None)
    mesh.textures = _gltf_textures(doc, base_dir, view_bytes, materials, set(order))
    return mesh


def _gltf_textures(doc: dict, base_dir: str, view_bytes, materials: list,
                   wanted: set) -> Dict[str, str]:
    """baseColorTexture каждого материала → файл картинки (встроенную пишем во
    временный файл: приложение кладёт текстуры по пути)."""
    out: Dict[str, str] = {}
    images = doc.get('images') or []
    textures = doc.get('textures') or []
    tmp = None
    for mi, mat in enumerate(materials):
        name = _material_name(mat.get('name') or f'material_{mi}', mi + 1)
        if name not in wanted or name in out:
            continue
        tex = ((mat.get('pbrMetallicRoughness') or {}).get('baseColorTexture') or {}).get('index')
        if tex is None or tex >= len(textures):
            continue
        src = textures[tex].get('source')
        if src is None or src >= len(images):
            continue
        img = images[src]
        try:
            if img.get('uri', '').startswith('data:'):
                header, payload = img['uri'].split(',', 1)
                ext = _GLTF_MIME_EXT.get(header[5:].split(';')[0], '.png')
                tmp = tmp or tempfile.mkdtemp(prefix='tf2_mesh_tex_')
                path = os.path.join(tmp, f'{name}{ext}')
                with open(path, 'wb') as f:
                    f.write(base64.b64decode(payload))
            elif img.get('uri'):
                path = os.path.join(base_dir, img['uri'])
                if not os.path.isfile(path):
                    continue
            elif 'bufferView' in img:
                ext = _GLTF_MIME_EXT.get(img.get('mimeType', ''), '.png')
                tmp = tmp or tempfile.mkdtemp(prefix='tf2_mesh_tex_')
                path = os.path.join(tmp, f'{name}{ext}')
                with open(path, 'wb') as f:
                    f.write(view_bytes(img['bufferView']))
            else:
                continue
        except (OSError, ValueError, KeyError, IndexError) as exc:
            logger.debug(f"текстура glTF не извлечена ({name}): {exc}")
            continue
        out[name] = path
    return out


def _gltf_buffer(desc: dict, base_dir: str, glb_bin: Optional[bytes]) -> bytes:
    uri = desc.get('uri')
    if not uri:
        if glb_bin is None:
            raise MeshImportError('glTF ссылается на буфер, которого нет в файле')
        return glb_bin
    if uri.startswith('data:'):
        return base64.b64decode(uri.split(',', 1)[1])
    full = os.path.join(base_dir, uri)
    if not os.path.isfile(full):
        raise MeshImportError(
            f'Рядом с glTF нет файла {uri} — сохраните модель как GLB (один файл)')
    with open(full, 'rb') as f:
        return f.read()


def _gltf_node_matrix(node: dict) -> np.ndarray:
    if 'matrix' in node:
        return np.array(node['matrix'], np.float64).reshape(4, 4).T   # column-major
    t = node.get('translation', [0, 0, 0])
    x, y, z, w = node.get('rotation', [0, 0, 0, 1])       # x y z w
    s = node.get('scale', [1, 1, 1])
    rot = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    m = np.eye(4)
    m[:3, :3] = rot * np.array(s, np.float64)[None, :]
    m[:3, 3] = t
    return m


# ── Упрощение ────────────────────────────────────────────────────────────── #

_MESHOPT_DLL = 'tools/meshoptimizer/meshoptimizer.dll'
_SIMPLIFY_LOCK_BORDER = 1 << 0
_simplify_fn = None

#: Вес UV в метрике упрощения (позиции meshoptimizer нормирует сам).
_UV_WEIGHTS = np.array([1.0, 1.0], np.float32)
#: Ребро острее этого угла остаётся жёстким при пересчёте нормалей.
_SMOOTH_ANGLE_DEG = 60.0


def _meshopt():
    """meshopt_simplifyWithAttributes из своей сборки DLL (scripts/build_meshoptimizer.ps1)."""
    global _simplify_fn
    if _simplify_fn is None:
        path = str(install_dir() / _MESHOPT_DLL)
        if not os.path.isfile(path):
            raise MeshImportError('Упрощение недоступно: нет tools/meshoptimizer/meshoptimizer.dll')
        fn = ctypes.CDLL(path).meshopt_simplifyWithAttributes
        fn.restype = ctypes.c_size_t
        fn.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,          # dst, indices, index_count
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t,          # positions, vertex_count, stride
            ctypes.c_void_p, ctypes.c_size_t,                           # attributes, stride
            ctypes.c_void_p, ctypes.c_size_t,                           # weights, attribute_count
            ctypes.c_void_p,                                            # vertex_lock
            ctypes.c_size_t, ctypes.c_float, ctypes.c_uint,             # target, error, options
            ctypes.POINTER(ctypes.c_float),                             # result_error
        ]
        _simplify_fn = fn
    return _simplify_fn


def _weld_pos_uv(corners: np.ndarray, skin: Optional[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """Сварка по (позиция, UV[, кости]) без нормали: (вершины (V, 5 или 13),
    номер для угла).

    Нормаль в ключ не входит нарочно. У плоско-затенённой модели каждый угол
    со своей нормалью, и meshoptimizer видел бы в вершине шесть «клиньев» —
    такие он запирает, и упрощать становится нечего. Нормали после упрощения
    считаются заново (`_recompute_normals`)."""
    rows = corners[:, [0, 1, 2, 6, 7]]
    if skin is not None:
        rows = np.hstack([rows, skin])
    keyed = np.ascontiguousarray(np.round(rows, 4).astype(np.float32))
    packed = keyed.view(np.dtype((np.void, keyed.dtype.itemsize * rows.shape[1]))).ravel()
    _, first, inverse = np.unique(packed, return_index=True, return_inverse=True)
    return rows[first], inverse.ravel()


def _recompute_normals(corners: np.ndarray) -> np.ndarray:
    """Нормали углов по новой геометрии: среднее по граням в той же точке,
    но только по тем, чей наклон к грани угла меньше `_SMOOTH_ANGLE_DEG` —
    так скруглённое остаётся гладким, а грани оружия — острыми."""
    pos = corners[:, :3]
    face_n = _flat_normals(pos)[::3]                          # (T, 3)
    face_of = np.repeat(np.arange(len(face_n)), 3)             # (3T,)
    keyed = np.ascontiguousarray(np.round(pos, 4).astype(np.float32))
    packed = keyed.view(np.dtype((np.void, 12))).ravel()
    _, point = np.unique(packed, return_inverse=True)
    point = point.ravel()
    order = np.argsort(point, kind='stable')
    starts = np.searchsorted(point[order], np.arange(point.max() + 1))
    ends = np.append(starts[1:], len(order))
    cos_limit = math.cos(math.radians(_SMOOTH_ANGLE_DEG))
    out = np.empty((len(corners), 3), np.float32)
    for c in range(len(corners)):
        members = order[starts[point[c]]:ends[point[c]]]
        faces = face_of[members]
        mine = face_n[face_of[c]]
        near = face_n[faces][face_n[faces] @ mine > cos_limit]
        n = near.sum(axis=0) if len(near) else mine
        length = np.linalg.norm(n) or 1.0
        out[c] = n / length
    return out


def simplify(mesh: Mesh, target_triangles: int = SIMPLIFY_TARGET_TRIANGLES) -> Mesh:
    """Упрощает до `target_triangles` (и до лимита вершин), сохраняя UV и
    границы между материалами. Материалы упрощаются по отдельности с
    запертыми краями — иначе на стыках появились бы щели."""
    fn = _meshopt()
    verts, inverse = _weld_pos_uv(mesh.corners, mesh.skin)
    positions = np.ascontiguousarray(verts[:, :3], np.float32)
    uvs = np.ascontiguousarray(verts[:, 3:5], np.float32)
    total = mesh.triangle_count
    ratio = min(1.0, target_triangles / max(total, 1))
    out = mesh
    for _ in range(6):
        chunks, skins, groups, first = [], [], [], 0
        for material, start, count in mesh.groups:
            idx = np.ascontiguousarray(inverse[start * 3:(start + count) * 3], np.uint32)
            target = max(1, int(round(count * ratio))) * 3
            dst = np.empty_like(idx)
            err = ctypes.c_float(0)
            n = fn(dst.ctypes.data, idx.ctypes.data, len(idx),
                   positions.ctypes.data, len(positions), 12,
                   uvs.ctypes.data, 8, _UV_WEIGHTS.ctypes.data, 2, None,
                   target, 1.0, _SIMPLIFY_LOCK_BORDER, ctypes.byref(err))
            kept = verts[dst[:n]]
            block = np.zeros((n, _COLS), np.float32)
            block[:, :3] = kept[:, :3]
            block[:, 6:8] = kept[:, 3:5]
            chunks.append(block)
            if mesh.skin is not None:
                skins.append(kept[:, 5:13])
            groups.append((material, first, n // 3))
            first += n // 3
        corners = np.vstack(chunks) if chunks else mesh.corners[:0]
        if len(corners):
            corners[:, 3:6] = _recompute_normals(corners)
        out = Mesh(corners=corners, groups=groups, has_uv=mesh.has_uv,
                   textures=dict(mesh.textures), bones=list(mesh.bones),
                   skin=np.vstack(skins) if skins else None)
        if not over_limits(out):
            break
        ratio *= 0.8                     # вершин всё ещё много — режем дальше
    logger.info(f"упрощение: {total} → {out.triangle_count} треугольников")
    return out


# ── Запись ───────────────────────────────────────────────────────────────── #

def transform_smd(src_path: str, out_path: str, fit: Fit) -> str:
    """Тот же SMD с подгонкой, запечённой в вершины: кости, веса, материалы и
    всё остальное остаются как есть — двигаются только позиции и нормали."""
    rot = np.array(fit.matrix(), np.float32)
    off = np.array(fit.offset, np.float32)
    out = []
    section = ''
    with open(src_path, encoding='utf-8', errors='replace') as f:
        for raw in f:
            line = raw.rstrip('\n')
            low = line.strip().lower()
            if low in ('nodes', 'skeleton', 'triangles', 'vertexanimation'):
                section = low
            elif low == 'end':
                section = ''
            elif section == 'triangles':
                parts = line.split()
                # Строка вершины: кость x y z nx ny nz u v [links…]; строка
                # материала чисел не содержит.
                if len(parts) >= 9 and parts[0].isdigit():
                    try:
                        pos = np.array([float(v) for v in parts[1:4]], np.float32)
                        nrm = np.array([float(v) for v in parts[4:7]], np.float32)
                    except ValueError:
                        out.append(line)
                        continue
                    pos = rot @ pos * fit.scale + off
                    nrm = rot @ nrm
                    parts[1:7] = [f'{v:.6f}' for v in (*pos, *nrm)]
                    line = ' '.join(parts)
            out.append(line)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    return out_path


def write_smd(mesh: Mesh, out_path: str, fit: Optional[Fit] = None) -> str:
    """SMD с подгонкой, запечённой в вершины. Без скиннинга — одна кость
    `root`; с ним — кости из файла и веса на каждый угол (nodes/skeleton
    игра потом подставит свои, кости сойдутся по имени)."""
    fit = fit or Fit()
    rot = np.array(fit.matrix(), np.float32)
    pos = mesh.corners[:, :3] @ rot.T * fit.scale + np.array(fit.offset, np.float32)
    nrm = mesh.corners[:, 3:6] @ rot.T
    rows = np.hstack([pos, nrm, mesh.corners[:, 6:8]])

    buf = io.StringIO()
    np.savetxt(buf, rows, fmt='%.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f', newline='\n')
    vlines = buf.getvalue().split('\n')
    if mesh.skin is None or not mesh.bones:
        vlines = ['0 ' + v for v in vlines]
        nodes = ['0 "root" -1']
        pose = ['0 0 0 0 0 0 0']
    else:
        # Главная кость строки — самая тяжёлая; дальше все ненулевые связи.
        joints = mesh.skin[:, :4].astype(np.int64)
        weights = mesh.skin[:, 4:]
        main = joints[np.arange(len(joints)), weights.argmax(axis=1)]
        links = [f'{sum(1 for b in w if b > 0)} '
                 + ' '.join(f'{int(a)} {b:.6f}' for a, b in zip(j, w) if b > 0)
                 for j, w in zip(joints, weights)]
        vlines = [f'{m} {v} {l}' for m, v, l in zip(main, vlines, links)]
        nodes = [f'{i} "{name}" -1' for i, name in enumerate(mesh.bones)]
        pose = [f'{i} 0 0 0 0 0 0' for i in range(len(mesh.bones))]

    lines = ['version 1', 'nodes', *nodes, 'end',
             'skeleton', 'time 0', *pose, 'end', 'triangles']
    for material, first, count in mesh.groups:
        for t in range(first, first + count):
            lines.append(material)
            lines.extend(vlines[t * 3:t * 3 + 3])
    lines.append('end')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    logger.info(f"импорт модели: {mesh.triangle_count} треугольников, {len(mesh.groups)} матер. → {os.path.basename(out_path)}")
    return out_path
