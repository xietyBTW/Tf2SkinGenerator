"""Импорт OBJ/GLB в SMD «только геометрия», подгонка, упрощение, текстуры.

Проверяем оси (glTF/OBJ Y-up, вперёд −Z → SMD оружия стволом в +Z),
запекание подгонки, лимиты studiomdl, разбор GLB с трансформом узла,
упрощение через meshoptimizer с сохранением UV и подхват базового цвета.
"""

import base64
import json
import math
import os
import struct

import numpy as np
import pytest

from src.services import mesh_import_service as mis

_OBJ = """# два треугольника с двумя материалами
mtllib m.mtl
v 0 0 0
v 1 0 0
v 0 1 0
v 0 0 1
vt 0 0
vt 1 0
vt 0 1
vn 0 0 1
usemtl Body.001
f 1/1/1 2/2/1 3/3/1
usemtl Grip
f 1/1 2/2 4/3
"""

_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


def _write_obj(tmp_path, with_mtl=True):
    src = tmp_path / "m.obj"
    src.write_text(_OBJ, encoding="utf-8")
    if with_mtl:
        (tmp_path / "m.mtl").write_text(
            "newmtl Body.001\nmap_Kd -s 1 1 1 body.png\nnewmtl Grip\nmap_Kd missing.png\n",
            encoding="utf-8")
        (tmp_path / "body.png").write_bytes(_PNG)
    return src


def test_obj_axes_materials_and_flat_normals(tmp_path):
    mesh = mis.load_mesh(str(_write_obj(tmp_path)))
    # Имена — под studiomdl: без точек, в нижнем регистре, порядок как в файле
    assert mesh.materials == ["body_001", "grip"]
    assert mesh.triangle_count == 2 and mesh.has_uv
    tri = mesh.triangles("body_001")[0]
    # (x, y, z) → (−x, y, −z): точка (1, 0, 0) уходит в (−1, 0, 0)
    assert tri[1][:3].tolist() == [-1.0, 0.0, 0.0]
    assert tri[0][3:6].tolist() == [0.0, 0.0, -1.0]      # нормаль тоже развёрнута
    # Без vn нормаль плоская: грань (0,0,0),(1,0,0),(0,0,1) смотрит в −Y
    flat = mesh.triangles("grip")[0][0][3:6]
    assert [round(float(v), 6) for v in flat] == [0.0, -1.0, 0.0]
    # map_Kd подхвачен только там, где файл есть; опции перед именем не мешают
    assert list(mesh.textures) == ["body_001"]
    assert mesh.textures["body_001"].endswith("body.png")


def test_obj_without_mtl_has_no_textures(tmp_path):
    mesh = mis.load_mesh(str(_write_obj(tmp_path, with_mtl=False)))
    assert mesh.textures == {}


def test_fit_is_baked_into_smd(tmp_path):
    mesh = mis.load_mesh(str(_write_obj(tmp_path)))
    out = tmp_path / "m.smd"
    # Поворот на 90° вокруг Y: SMD-точка (−1, 0, 0) → (0, 0, 1); масштаб 2, сдвиг +5 по Y
    mis.write_smd(mesh, str(out), mis.Fit(scale=2.0, rotate=(0, 90, 0), offset=(0, 5, 0)))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[:4] == ["version 1", "nodes", '0 "root" -1', "end"]
    assert lines[lines.index("triangles") + 1] == "body_001"
    body = [l for l in lines[lines.index("triangles") + 1:] if l[:1] == "0"]
    x, y, z = (float(v) for v in body[1].split()[1:4])
    assert (round(x, 4), round(y, 4), round(z, 4)) == (0.0, 5.0, 2.0)
    # Нормаль (0,0,−1) после поворота на 90° вокруг Y → (−1, 0, 0), масштаб не трогает
    nx, ny, nz = (float(v) for v in body[0].split()[4:7])
    assert (round(nx, 4), round(ny, 4), round(nz, 4)) == (-1.0, 0.0, 0.0)


def _mesh_of(tris: np.ndarray, material="a"):
    return mis.Mesh(corners=np.asarray(tris, np.float32).reshape(-1, 8),
                    groups=[(material, 0, len(tris))])


def test_limits_count_split_vertices():
    tri = np.array([[0, 0, 0, 0, 0, 1, 0, 0], [1, 0, 0, 0, 0, 1, 1, 0],
                    [0, 1, 0, 0, 0, 1, 0, 1]], np.float32)
    mesh = _mesh_of(np.stack([tri, tri]))
    assert mesh.vertex_count() == 3                 # одинаковые вершины слились
    assert mis.check_limits(mesh) is None
    mesh = _mesh_of(np.repeat(tri[None], mis.MAX_STUDIO_TRIANGLES + 1, axis=0))
    assert "треугольников" in mis.check_limits(mesh)
    many = mis.Mesh(corners=np.repeat(tri, mis.MAX_STUDIO_SKINS + 1, axis=0),
                    groups=[(f"m{i}", i, 1) for i in range(mis.MAX_STUDIO_SKINS + 1)])
    assert "материалов" in mis.check_limits(many)


def _glb(tmp_path, node_extra, with_texture=False):
    """GLB с одним треугольником; узел — с переданным трансформом."""
    pos = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    uv = [(0, 0), (1, 0), (0, 1)]
    blob = b"".join(struct.pack("<3f", *p) for p in pos)
    blob += b"".join(struct.pack("<2f", *t) for t in uv)
    blob += struct.pack("<3H", 0, 1, 2) + b"\0\0"
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
             {"buffer": 0, "byteOffset": 36, "byteLength": 24},
             {"buffer": 0, "byteOffset": 60, "byteLength": 6}]
    material = {"name": "Metal"}
    doc = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [dict(mesh=0, **node_extra)],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                                    "indices": 2, "material": 0}]}],
        "materials": [material],
        "bufferViews": views,
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                      {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
                      {"bufferView": 2, "componentType": 5123, "count": 3, "type": "SCALAR"}],
    }
    if with_texture:
        blob += _PNG                       # 68 байт до — уже кратно 4
        views.append({"buffer": 0, "byteOffset": 68, "byteLength": len(_PNG)})
        doc["images"] = [{"bufferView": 3, "mimeType": "image/png"}]
        doc["textures"] = [{"source": 0}]
        material["pbrMetallicRoughness"] = {"baseColorTexture": {"index": 0}}
    doc["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js
    body += struct.pack("<II", len(blob), 0x004E4942) + blob
    data = b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body
    path = tmp_path / "m.glb"
    path.write_bytes(data)
    return path


def test_glb_node_transform_uv_flip_and_flat_normal(tmp_path):
    path = _glb(tmp_path, {"translation": [0, 0, 10], "scale": [2, 2, 2]})
    mesh = mis.load_mesh(str(path))
    assert mesh.materials == ["metal"]
    tri = mesh.triangles("metal")[0]
    # Узел: масштаб 2, сдвиг +10 по Z; потом оси: (x, y, z) → (−x, y, −z)
    assert tri[1][:3].tolist() == [-2.0, 0.0, -10.0]
    # UV glTF сверху вниз, SMD — снизу вверх
    assert tri[2][6:8].tolist() == [0.0, 0.0]
    # Нормали в файле нет — плоская, от треугольника в плоскости XY: +Z → −Z
    assert [round(float(v), 6) for v in tri[0][3:6]] == [0.0, 0.0, -1.0]
    assert mesh.textures == {}


def test_glb_embedded_base_color_is_extracted(tmp_path):
    mesh = mis.load_mesh(str(_glb(tmp_path, {}, with_texture=True)))
    path = mesh.textures["metal"]
    assert path.endswith("metal.png") and open(path, "rb").read() == _PNG


def test_gltf_external_buffer_missing_is_explained(tmp_path):
    (tmp_path / "m.gltf").write_text(json.dumps({
        "asset": {"version": "2.0"}, "buffers": [{"uri": "m.bin", "byteLength": 4}],
        "nodes": [], "scenes": [{"nodes": []}]}), encoding="utf-8")
    with pytest.raises(mis.MeshImportError, match="GLB"):
        mis.load_mesh(str(tmp_path / "m.gltf"))


def test_unsupported_and_empty():
    with pytest.raises(mis.MeshImportError, match="не поддерживается"):
        mis.load_mesh("model.fbx")
    assert mis.Fit.from_dict({"scale": "0", "rotate": [1, "x", 3]}).scale == 1.0
    assert math.isclose(mis.Fit(rotate=(0, 0, 90)).matrix()[1][0], 1.0)


def _grid(n: int, material="a") -> mis.Mesh:
    """Плоская сетка n×n с UV по координате: 2(n−1)² треугольников."""
    xs, ys = np.meshgrid(np.arange(n, dtype=np.float32), np.arange(n, dtype=np.float32))
    pos = np.stack([xs.ravel(), ys.ravel(), np.zeros(n * n, np.float32)], 1)
    uv = pos[:, :2] / (n - 1)
    verts = np.hstack([pos, np.tile([0, 0, 1], (n * n, 1)), uv]).astype(np.float32)
    idx = []
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            idx += [a, a + 1, a + n, a + 1, a + n + 1, a + n]
    return _mesh_of(verts[np.array(idx)].reshape(-1, 3, 8), material)


@pytest.mark.skipif(not os.path.isfile("tools/meshoptimizer/meshoptimizer.dll"),
                    reason="нет собранной DLL")
def test_simplify_keeps_uv_and_material_groups():
    mesh = _grid(60)                                   # 6962 треугольника
    out = mis.simplify(mesh, target_triangles=400)
    assert 200 <= out.triangle_count <= 500
    assert out.groups[0][0] == "a" and out.groups[0][2] == out.triangle_count
    # UV остаётся координатой на плоскости: u == x/59, v == y/59 у каждой вершины
    c = out.corners
    assert np.allclose(c[:, 6], c[:, 0] / 59, atol=1e-3)
    assert np.allclose(c[:, 7], c[:, 1] / 59, atol=1e-3)
    # Края сетки заперты (LockBorder): крайние точки на месте
    assert c[:, 0].min() == 0 and c[:, 0].max() == 59 and c[:, 1].max() == 59
    assert not mis.over_limits(out)


def test_transform_smd_moves_vertices_only(tmp_path):
    src = tmp_path / "in.smd"
    src.write_text(
        'version 1\nnodes\n0 "weapon_bone" -1\nend\nskeleton\ntime 0\n'
        '0 0 0 0 0 0 0\nend\ntriangles\nc_pistol\n'
        '0 1.000000 0.000000 0.000000 0.000000 0.000000 1.000000 0.5 0.5 1 0 1.0\n'
        '0 0 0 0 0 0 1 0 0\n0 0 1 0 0 0 1 0 1\nend\n', encoding="utf-8")
    out = tmp_path / "out.smd"
    mis.transform_smd(str(src), str(out), mis.Fit(scale=2.0, rotate=(0, 90, 0), offset=(0, 0, 5)))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[2] == '0 "weapon_bone" -1' and lines[9] == "c_pistol"
    v = lines[10].split()
    # (1,0,0) → поворот вокруг Y на 90° → (0,0,−1) → ×2 → +5 по Z = (0, 0, 3)
    assert [round(float(x), 3) for x in v[1:4]] == [0.0, 0.0, 3.0]
    assert [round(float(x), 3) for x in v[4:7]] == [1.0, 0.0, 0.0]   # нормаль (0,0,1) → (1,0,0)
    assert v[7:] == ["0.5", "0.5", "1", "0", "1.0"]                    # UV и веса не тронуты


def _skinned_glb(tmp_path):
    """GLB с двумя костями игры и скином: треугольник, углы весят на разные кости."""
    pos = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    joints = [(0, 1, 0, 0), (1, 0, 0, 0), (0, 0, 0, 0)]
    weights = [(0.75, 0.25, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0)]
    blob = b"".join(struct.pack("<3f", *v) for v in pos)
    blob += b"".join(struct.pack("<4B", *j) for j in joints)
    blob += b"".join(struct.pack("<4f", *w) for w in weights)
    blob += struct.pack("<3H", 0, 1, 2) + b"\0\0"
    doc = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}],
        "nodes": [{"name": "weapon_bone", "children": [2]},
                  {"mesh": 0, "skin": 0, "translation": [50, 0, 0]},
                  {"name": "weapon_bone_1"}],
        "skins": [{"joints": [0, 2]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2},
                                    "indices": 3, "material": 0}]}],
        "materials": [{"name": "c_pistol"}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                        {"buffer": 0, "byteOffset": 36, "byteLength": 12},
                        {"buffer": 0, "byteOffset": 48, "byteLength": 48},
                        {"buffer": 0, "byteOffset": 96, "byteLength": 6}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                      {"bufferView": 1, "componentType": 5121, "count": 3, "type": "VEC4"},
                      {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC4"},
                      {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"}],
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js
    body += struct.pack("<II", len(blob), 0x004E4942) + blob
    path = tmp_path / "s.glb"
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    return path


def test_skinned_glb_keeps_bone_names_and_weights(tmp_path):
    mesh = mis.load_mesh(str(_skinned_glb(tmp_path)))
    assert mesh.bones == ["weapon_bone", "weapon_bone_1"]
    # Скиннутый меш лежит в пространстве скелета: сдвиг узла (50, 0, 0) не применяется
    assert mesh.triangles("c_pistol")[0][1][:3].tolist() == [-1.0, 0.0, 0.0]
    out = tmp_path / "s.smd"
    mis.write_smd(mesh, str(out))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[1:4] == ["nodes", '0 "weapon_bone" -1', '1 "weapon_bone_1" -1']
    tri = lines[lines.index("triangles") + 2:lines.index("triangles") + 5]
    # Главная кость строки — самая тяжёлая, дальше все ненулевые связи
    assert tri[0].split()[0] == "0" and tri[0].split()[9:] == ["2", "0", "0.750000", "1", "0.250000"]
    assert tri[1].split()[0] == "1" and tri[1].split()[9:] == ["1", "1", "1.000000"]
    # Вершины с разными костями не свариваются, лимит считает их отдельно
    assert mesh.vertex_count() == 3


def test_unskinned_mesh_under_bone_rides_that_bone(tmp_path):
    """Меш без скина, но под узлом-костью («parent to bone» в Blender): весь на ней."""
    path = _skinned_glb(tmp_path)
    import json as _json
    data = bytearray(path.read_bytes())
    # Проще собрать заново: узел меша без скина, ребёнок weapon_bone_1
    doc_len = struct.unpack_from("<I", data, 12)[0]
    doc = _json.loads(bytes(data[20:20 + doc_len]).decode())
    doc["nodes"][1].pop("skin")
    doc["nodes"][2]["children"] = [1]
    doc["scenes"][0]["nodes"] = [0]
    js = _json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    blob = bytes(data[20 + doc_len + 8:])
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    mesh = mis.load_mesh(str(path))
    assert mesh.skin[:, 0].tolist() == [1.0, 1.0, 1.0] and mesh.skin[:, 4].tolist() == [1.0, 1.0, 1.0]
    # Без скина трансформ узла применяется: сдвиг (50,0,0) → после осей (−50, …)
    assert mesh.triangles("c_pistol")[0][0][:3].tolist() == [-50.0, 0.0, 0.0]
