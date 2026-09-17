"""
Геометрия модели прямо из MDL/VVD/VTX — там, где Crowbar её теряет.

Crowbar 0.68 у меша, разбитого на две strip-группы VTX (флексы + обычная),
пишет в SMD только первую: у Air Head оставалось 112 треугольников из 1398,
у Sheriff's Stetson — 478 из 1374, у тела пиромана — четыре. В превью такая
шапка — чёрная пуговица, а собранный из этого SMD стиль в игре — тоже.

Здесь читаются три файла модели (формат v48, без фикс-апов и с ними) и
отдаются треугольники LOD0 в том же виде, что пишет Crowbar: позиция и
нормаль в пространстве модели, UV как в VVD, веса костей по номерам костей
MDL. `repair_smd` дописывает в SMD Crowbar недостающие треугольники, не
трогая уже записанные — их номера вершин держит VTA флексов.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: mstudiovertex_t: веса (3f) + кости (3B) + число (B) + позиция + нормаль + UV.
_VERT = struct.Struct('<3f3BB3f3f2f')
_VTX_VERT = struct.Struct('<3BBH3B')          # Vertex_t, 9 байт
_STRIP = struct.Struct('<iiiihBii')            # StripHeader_t, 27 байт
_GROUP = struct.Struct('<iiiiiiB')             # StripGroupHeader_t, 25 байт
_MESH = struct.Struct('<iiB')                  # MeshHeader_t, 9 байт
_STRIP_IS_TRILIST = 1


@dataclass
class Tri:
    material: str
    verts: List[tuple]                         # (pos, normal, uv, [(bone, weight)…])


@dataclass
class ModelMesh:
    """Один `$model`/`studio` — треугольники LOD0 по strip-группам."""
    bodypart: int
    model: int
    name: str
    groups: List[List[Tri]] = field(default_factory=list)

    @property
    def tris(self) -> List[Tri]:
        return [t for g in self.groups for t in g]


def _cstr(data: bytes, offset: int) -> str:
    end = data.index(b'\0', offset)
    return data[offset:end].decode('ascii', 'replace')


def _vvd_vertices(vvd: bytes) -> List[tuple]:
    """Вершины LOD0 с учётом таблицы фикс-апов."""
    num_lods = struct.unpack_from('<i', vvd, 12)[0]
    num_fixups, fixup_start, vert_start = struct.unpack_from('<iii', vvd, 48)
    count = struct.unpack_from('<i', vvd, 16)[0]        # numLODVertexes[0]
    raw = [_VERT.unpack_from(vvd, vert_start + i * _VERT.size)
           for i in range(count if not num_fixups else
                          (len(vvd) - vert_start) // _VERT.size)]
    if not num_fixups:
        return raw
    out: List[tuple] = []
    for i in range(num_fixups):
        lod, source, n = struct.unpack_from('<iii', vvd, fixup_start + i * 12)
        if lod >= 0:                                   # 0 = LOD0 включительно
            out.extend(raw[source:source + n])
    return out


def _mdl_meshes(mdl: bytes) -> Iterator[Tuple[int, int, str, int, List[Tuple[int, int]]]]:
    """(bodypart, model, имя модели, первый индекс VVD, [(смещение, материал)…])."""
    num_textures, texture_index = struct.unpack_from('<ii', mdl, 204)
    num_skinref, num_skinfam, skin_index = struct.unpack_from('<iii', mdl, 220)
    # Имя материала в MDL бывает с путём (у мастерской —
    # models/workshop/…/dec25_air_head); Crowbar и QC знают его по basename.
    textures = [_cstr(mdl, texture_index + i * 64
                      + struct.unpack_from('<i', mdl, texture_index + i * 64)[0])
                .replace(chr(92), '/').rsplit('/', 1)[-1]
                for i in range(num_textures)]
    # Материал меша — номер в skin-таблице, а не в списке текстур.
    skin0 = [struct.unpack_from('<h', mdl, skin_index + i * 2)[0]
             for i in range(num_skinref)] if num_skinfam else list(range(num_textures))
    num_bodyparts, bodypart_index = struct.unpack_from('<ii', mdl, 232)
    for bp in range(num_bodyparts):
        bpo = bodypart_index + bp * 16
        _, num_models, _, model_index = struct.unpack_from('<iiii', mdl, bpo)
        for m in range(num_models):
            mo = bpo + model_index + m * 148
            name = mdl[mo:mo + 64].split(b'\0')[0].decode('ascii', 'replace')
            _, _, num_meshes, mesh_index, _, vertex_index = struct.unpack_from(
                '<ifiiii', mdl, mo + 64)
            meshes = []
            for k in range(num_meshes):
                ko = mo + mesh_index + k * 116
                material, _, _, vertex_offset = struct.unpack_from('<iiii', mdl, ko)
                ref = skin0[material] if material < len(skin0) else material
                meshes.append((vertex_offset, textures[ref] if ref < len(textures) else ''))
            yield bp, m, name, vertex_index // _VERT.size, meshes


def read_meshes(mdl: bytes, vvd: bytes, vtx: bytes) -> List[ModelMesh]:
    """Треугольники LOD0 всех моделей всех частей тела."""
    verts = _vvd_vertices(vvd)
    num_bodyparts, bodypart_offset = struct.unpack_from('<ii', vtx, 28)
    out: List[ModelMesh] = []
    for bp, m, name, first, meshes in _mdl_meshes(mdl):
        bpo = bodypart_offset + bp * 8
        num_models, model_offset = struct.unpack_from('<ii', vtx, bpo)
        if m >= num_models:
            continue
        mo = bpo + model_offset + m * 8
        _, lod_offset = struct.unpack_from('<ii', vtx, mo)
        lo = mo + lod_offset                              # LOD0
        num_meshes, mesh_offset, _ = struct.unpack_from('<iif', vtx, lo)
        model = ModelMesh(bp, m, name)
        for k in range(min(num_meshes, len(meshes))):
            vertex_offset, material = meshes[k]
            ko = lo + mesh_offset + k * _MESH.size
            num_groups, group_offset, _ = _MESH.unpack_from(vtx, ko)
            for g in range(num_groups):
                go = ko + group_offset + g * _GROUP.size
                num_v, v_off, num_i, i_off, num_strips, strip_off, _ = _GROUP.unpack_from(vtx, go)
                gverts = [_VTX_VERT.unpack_from(vtx, go + v_off + i * _VTX_VERT.size)[4]
                          for i in range(num_v)]
                indices = struct.unpack_from(f'<{num_i}H', vtx, go + i_off)
                tris: List[Tri] = []
                for s in range(num_strips):
                    so = go + strip_off + s * _STRIP.size
                    s_num_i, s_i_off, _, _, _, flags, _, _ = _STRIP.unpack_from(vtx, so)
                    idx = indices[s_i_off:s_i_off + s_num_i]
                    faces = (zip(idx[0::3], idx[1::3], idx[2::3]) if flags & _STRIP_IS_TRILIST
                             else _unstrip(idx))
                    # Обход как у Crowbar: второй и третий поменяны местами.
                    for a, b, c in faces:
                        tris.append(Tri(material, [
                            _vert(verts[first + vertex_offset + gverts[i]]) for i in (a, c, b)]))
                model.groups.append(tris)
        out.append(model)
    return out


def _unstrip(idx) -> Iterator[Tuple[int, int, int]]:
    """Полоса → треугольники, с чередованием обхода; вырожденные — мимо."""
    for i in range(len(idx) - 2):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        if a == b or b == c or a == c:
            continue
        yield (a, b, c) if i % 2 == 0 else (b, a, c)


def _vert(v: tuple) -> tuple:
    w = v[0:3]
    bones = v[3:6]
    n = v[6]
    links = [(bones[i], w[i]) for i in range(min(n, 3)) if w[i] > 0]
    # V в SMD идёт снизу вверх — Crowbar пишет 1 - v.
    return (v[7:10], v[10:13], (v[13], 1.0 - v[14]), links or [(bones[0], 1.0)])


def format_tri(tri: Tri) -> str:
    """Треугольник строками SMD — как пишет Crowbar."""
    lines = [tri.material]
    for pos, nrm, uv, links in tri.verts:
        parent = links[0][0]
        lines.append(
            f'  {parent} {pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f} '
            f'{nrm[0]:.6f} {nrm[1]:.6f} {nrm[2]:.6f} {uv[0]:.6f} {uv[1]:.6f} '
            f'{len(links)} ' + ' '.join(f'{b} {w:.6f}' for b, w in links))
    return '\n'.join(lines)


# ── Починка SMD после Crowbar ─────────────────────────────────────────────── #

def smd_triangle_count(path: str) -> int:
    n = 0
    inside = False
    with open(path, encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('triangles'):
                inside = True
            elif inside and line.startswith('end'):
                break
            elif inside and line[:1] not in ' \t\r\n':
                n += 1
    return n


def _qc_studios(qc_text: str) -> List[str]:
    """Файлы `$model`/`$body`/`studio` в порядке частей тела; `blank` — пусто."""
    out: List[str] = []
    for m in re.finditer(r'^\s*(?:\$model\s+"[^"]*"\s+"([^"]+)"|\$body\s+"[^"]*"\s+"([^"]+)"'
                         r'|studio\s+"([^"]+)"|(blank))', qc_text, re.M | re.I):
        out.append(m.group(1) or m.group(2) or m.group(3) or '')
    return out


def repair_smd(qc_path: str, mdl: bytes, vvd: bytes, vtx: bytes) -> Dict[str, int]:
    """
    Дописывает в SMD декомпиляции треугольники, которых Crowbar не записал.

    SMD сопоставляются моделям MDL по порядку в QC (`$model`, `$body`,
    `studio` внутри `$bodygroup`). Записанные Crowbar треугольники не
    трогаем: их вершины нумерует VTA флексов. Считаем, что Crowbar пишет
    strip-группы по порядку и обрывается целыми группами — так у всех
    проверенных моделей; иначе SMD оставляем как есть.

    Returns: {файл SMD: сколько треугольников дописано}.
    """
    try:
        with open(qc_path, encoding='utf-8', errors='ignore') as f:
            studios = _qc_studios(f.read())
        models = read_meshes(mdl, vvd, vtx)
    except Exception as exc:                          # noqa: BLE001
        logger.warning(f"[mdl] геометрия не прочитана: {exc}")
        return {}
    done: Dict[str, int] = {}
    folder = os.path.dirname(qc_path)
    for smd_name, model in zip(studios, models):
        if not smd_name:
            continue
        path = os.path.join(folder, smd_name)
        if not os.path.isfile(path):
            continue
        have = smd_triangle_count(path)
        total = sum(len(g) for g in model.groups)
        if have >= total:
            continue
        # Записаны первые группы целиком — дописываем остальные.
        seen = 0
        missing: List[Tri] = []
        for group in model.groups:
            if seen < have:
                seen += len(group)
                continue
            missing.extend(group)
        if seen != have or not missing:
            logger.warning(f"[mdl] {smd_name}: {have} треугольников в SMD против "
                           f"{total} в VTX, но по группам не сходится — не трогаю")
            continue
        _append_triangles(path, missing)
        done[smd_name] = len(missing)
        logger.info(f"[mdl] {smd_name}: дописано {len(missing)} треугольников "
                    f"(было {have}, в модели {total})")
    return done


def _append_triangles(path: str, tris: List[Tri]) -> None:
    with open(path, encoding='utf-8', errors='ignore') as f:
        text = f.read()
    at = text.rfind('\nend')
    if at == -1:
        return
    body = '\n'.join(format_tri(t) for t in tris)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text[:at] + '\n' + body + text[at:])
