"""
Сборка анимированной вьюмодели (viewer_skinned.js) через Node.

Проверяется то, что ломает сцену целиком и не видно в Python-тестах: порядок
создания костей (родитель должен существовать раньше ребёнка), нарезка
атрибутов по материалам и имена дорожек — ошибка в любом из трёх даёт либо
пустой экран, либо неподвижный меш.

THREE подменяется заглушкой: модуль принимает библиотеку параметром именно
ради этого (тот же приём, что в viewer_materials.js).

Тест пропускается, если node недоступен.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path("src/static/js/viewer_skinned.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not MODULE.exists(),
    reason="node недоступен или viewer_skinned.js не найден")

STUB = """
class Obj3D {
  constructor() { this.children = []; this.parent = null;
    this.position = vec3(); this.quaternion = quat();
    this.rotation = vec3(); this.userData = {}; this.name = '';
    this.worldUpdates = 0; }
  add(child) { if (child) { child.parent = this; this.children.push(child); } }
  updateMatrixWorld() { this.worldUpdates++;
    this.children.forEach(c => c.updateMatrixWorld()); }
}
function vec3() { const v = { x: 0, y: 0, z: 0,
  set(x, y, z) { v.x = x; v.y = y; v.z = z; return v; } }; return v; }
function quat() { const q = { x: 0, y: 0, z: 0, w: 1,
  set(x, y, z, w) { q.x = x; q.y = y; q.z = z; q.w = w; return q; } }; return q; }

const THREE = {
  LoopOnce: 'once', LoopRepeat: 'repeat',
  Group: class extends Obj3D {},
  Bone: class extends Obj3D {},
  Skeleton: class { constructor(bones) { this.bones = bones;
    this.builtAfterWorldUpdate = bones.every(b => rootOf(b).worldUpdates > 0); } },
  BufferGeometry: class { constructor() { this.attributes = {}; }
    setAttribute(name, attr) { this.attributes[name] = attr; } },
  Float32BufferAttribute: class { constructor(array, size) {
    this.array = array; this.itemSize = size; } },
  Uint16BufferAttribute: class { constructor(array, size) {
    this.array = array; this.itemSize = size; } },
  SkinnedMesh: class extends Obj3D {
    constructor(geometry, material) { super();
      this.geometry = geometry; this.material = material; this.bound = null;
      this.boundInsideGroup = null; this.bindMatrix = null; }
    // Настоящий three.js без явной матрицы берёт текущую matrixWorld: у меша
    // вне сцены она единичная, и поворот группы применяется дважды.
    bind(skeleton, matrix) { this.bound = skeleton; this.bindMatrix = matrix;
      this.boundInsideGroup = Boolean(this.parent); } },
  AnimationMixer: class { constructor(root) { this.root = root; this.actions = []; }
    clipAction(clip) { const a = { clip, loop: null, played: false,
        getClip() { return clip; },
        setLoop(mode) { a.loop = mode; }, play() { a.played = true; } };
      this.actions.push(a); return a; }
    stopAllAction() { this.actions.forEach(a => { a.played = false; }); }
    uncacheClip(clip) { this.uncached = clip; } },
  AnimationClip: class { constructor(name, duration, tracks) {
    this.name = name; this.duration = duration; this.tracks = tracks; } },
  VectorKeyframeTrack: class { constructor(path, times, values) {
    this.kind = 'vector'; this.path = path; this.times = times; this.values = values; } },
  QuaternionKeyframeTrack: class { constructor(path, times, values) {
    this.kind = 'quaternion'; this.path = path; this.times = times; this.values = values; } },
};
function rootOf(o) { return o.parent ? rootOf(o.parent) : o; }
const makeMaterial = name => ({ name });
"""

# Две кости и две части по одному материалу — минимум, на котором видно всё.
DATA = {
    "rootRotationX": -1.5707963,
    "bones": [
        {"name": "root", "parent": -1, "position": [0, 0, 0],
         "quaternion": [0, 0, 0, 1]},
        {"name": "bip_hand_R", "parent": 0, "position": [0, 10, 0],
         "quaternion": [0, 0, 0, 1]},
    ],
    "parts": [
        {"kind": "weapon", "materials": ["c_scattergun"],
         "positions": [0, 0, 0, 1, 0, 0, 0, 1, 0],
         "normals": [0, 0, 1] * 3, "uvs": [0, 0, 1, 0, 0, 1],
         "skinIndex": [1, 0, 0, 0] * 3, "skinWeight": [1, 0, 0, 0] * 3,
         "groups": [{"material": "c_scattergun", "start": 0, "count": 3}]},
        {"kind": "arms", "materials": ["scout_hands"],
         "positions": [2, 0, 0, 3, 0, 0, 2, 1, 0],
         "normals": [0, 0, 1] * 3, "uvs": [0, 0, 1, 0, 0, 1],
         "skinIndex": [1, 0, 0, 0] * 3, "skinWeight": [1, 0, 0, 0] * 3,
         "groups": [{"material": "scout_hands", "start": 0, "count": 3}]},
    ],
    "clip": {"name": "primary_inspect_idle", "fps": 30, "loop": True,
             "times": [0.0, 0.033], "duration": 0.033,
             "tracks": [{"bone": 1, "positions": [0, 10, 0, 0, 11, 0],
                         "quaternions": [0, 0, 0, 1, 0, 0, 0.1, 0.99]}]},
}


def _run(body: str, data=None) -> dict:
    script = f"""
import {{ buildSkinnedScene, applyClip, createBones, createClip,
         updateHidden }} from {MODULE.as_uri()!r};
{STUB}
const DATA = {json.dumps(data if data is not None else DATA)};
const out = (() => {{ {body} }})();
console.log(JSON.stringify(out));
"""
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── Скелет ────────────────────────────────────────────────────────────────── #

def test_bones_form_a_hierarchy():
    out = _run("""const bones = createBones(THREE, DATA.bones);
        return { count: bones.length, childOfRoot: bones[0].children.length,
                 parentName: bones[1].parent.name, name: bones[1].name,
                 pos: [bones[1].position.x, bones[1].position.y, bones[1].position.z] };""")
    assert out == {"count": 2, "childOfRoot": 1, "parentName": "root",
                   "name": "bip_hand_R", "pos": [0, 10, 0]}


def test_skeleton_is_created_after_world_matrices_are_ready():
    """THREE.Skeleton берёт обратные матрицы из мировых.

    Создать его раньше updateMatrixWorld — значит получить единичные обратные
    матрицы и меш, вывернутый наизнанку при первом же кадре.
    """
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return s.skeleton.builtAfterWorldUpdate;""")
    assert out is True


def test_root_rotation_converts_the_axes():
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return Math.round(s.group.rotation.x * 1000) / 1000;""")
    assert out == -1.571


# ── Меши ──────────────────────────────────────────────────────────────────── #

def test_one_mesh_per_material_named_by_it():
    """По этим именам вьювер потом кладёт текстуры — как в обычном превью."""
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return s.meshes.map(m => [m.name, m.kind, m.mesh.material.name]);""")
    assert out == [["c_scattergun", "weapon", "c_scattergun"],
                   ["scout_hands", "arms", "scout_hands"]]


def test_mesh_is_bound_only_after_it_is_placed_in_the_scene():
    """Привязка до добавления в группу берёт единичную bindMatrix.

    Тогда поворот корня (оси Source → оси Three.js) применяется дважды, и
    руки с оружием растягивает в шипы — ровно то, что и было видно на экране.
    """
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return s.meshes.map(m => [m.mesh.boundInsideGroup,
                                  m.mesh.bindMatrix !== null]);""")
    assert out == [[True, True], [True, True]]


def test_every_mesh_is_bound_to_the_shared_skeleton():
    """Скелет один: оружие подвешено к костям руки, своего у него нет."""
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return s.meshes.every(m => m.mesh.bound === s.skeleton);""")
    assert out is True


def test_attributes_are_sliced_per_material_group():
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        const a = s.meshes[0].mesh.geometry.attributes;
        return { position: a.position.array.length, uv: a.uv.array.length,
                 skinIndex: a.skinIndex.array.length,
                 skinWeight: a.skinWeight.array.length };""")
    assert out == {"position": 9, "uv": 6, "skinIndex": 12, "skinWeight": 12}


def test_second_group_takes_its_own_slice():
    """Смещение групп считается по вершинам, а не по числам в массиве."""
    data = json.loads(json.dumps(DATA))
    part = data["parts"][0]
    part["positions"] += [5, 0, 0, 6, 0, 0, 5, 1, 0]
    part["normals"] += [0, 0, 1] * 3
    part["uvs"] += [0, 0, 1, 0, 0, 1]
    part["skinIndex"] += [0, 0, 0, 0] * 3
    part["skinWeight"] += [1, 0, 0, 0] * 3
    part["groups"].append({"material": "c_scattergun_gold", "start": 3, "count": 3})
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return { names: s.meshes.map(m => m.name),
                 second: s.meshes[1].mesh.geometry.attributes.position.array };""",
               data)
    assert out["names"][:2] == ["c_scattergun", "c_scattergun_gold"]
    assert out["second"] == [5, 0, 0, 6, 0, 0, 5, 1, 0]


# ── Клип ──────────────────────────────────────────────────────────────────── #

def test_clip_has_a_track_pair_per_animated_bone():
    out = _run("""const bones = createBones(THREE, DATA.bones);
        const clip = createClip(THREE, DATA.clip, bones);
        return { name: clip.name,
                 tracks: clip.tracks.map(t => [t.kind, t.path]) };""")
    assert out["name"] == "primary_inspect_idle"
    assert out["tracks"] == [["vector", "bip_hand_R.position"],
                             ["quaternion", "bip_hand_R.quaternion"]]


def test_every_animation_repeats_even_a_one_shot_one():
    """В игре «достать оружие» играется один раз, в превью — по кругу.

    Однократный показ не даёт рассмотреть движение, а именно за этим сюда и
    приходят.
    """
    out = _run("""const once = JSON.parse(JSON.stringify(DATA));
        once.clip.loop = false;
        return { looped: buildSkinnedScene(THREE, DATA, makeMaterial).action.loop,
                 once:   buildSkinnedScene(THREE, once, makeMaterial).action.loop };""")
    assert out == {"looped": "repeat", "once": "repeat"}


def test_animation_starts_playing():
    out = _run("""return buildSkinnedScene(THREE, DATA, makeMaterial).action.played;""")
    assert out is True


def test_scene_without_a_clip_is_still_shown():
    """Одна поза без движения — тоже нормальный результат, не повод падать."""
    data = json.loads(json.dumps(DATA))
    data["clip"] = {"times": [], "tracks": []}
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return { action: s.action, meshes: s.meshes.length, duration: s.duration };""",
               data)
    assert out == {"action": None, "meshes": 2, "duration": 0}


def test_track_for_a_missing_bone_is_skipped():
    data = json.loads(json.dumps(DATA))
    data["clip"]["tracks"].append({"bone": 99, "positions": [0, 0, 0],
                                   "quaternions": [0, 0, 0, 1]})
    out = _run("""const bones = createBones(THREE, DATA.bones);
        return createClip(THREE, DATA.clip, bones).tracks.length;""", data)
    assert out == 2


# ── Смена анимации на готовой сцене ───────────────────────────────────────── #

def test_new_clip_replaces_the_old_one_without_rebuilding():
    """Меш, скелет и текстуры не зависят от выбора анимации.

    Пересборка сцены ради дорожек означала бы распаковку тех же самых текстур
    заново — около секунды на каждое нажатие.
    """
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        const meshes = s.meshes.map(m => m.mesh);
        const before = s.action;
        const clip = JSON.parse(JSON.stringify(DATA.clip));
        clip.name = 'sg_reload';
        const after = applyClip(THREE, s, clip);
        return { name: after.clip.name, changed: after !== before,
                 sameMeshes: s.meshes.every((m, i) => m.mesh === meshes[i]),
                 sameSkeleton: s.meshes.every(m => m.mesh.bound === s.skeleton),
                 played: after.played, loop: after.loop };""")
    assert out == {"name": "sg_reload", "changed": True, "sameMeshes": True,
                   "sameSkeleton": True, "played": True, "loop": "repeat"}


def test_tracks_find_their_bone_by_name():
    """Клип приходит отдельно от сцены — совпадение порядка костей не гарантия."""
    out = _run("""const bones = createBones(THREE, DATA.bones);
        const clip = JSON.parse(JSON.stringify(DATA.clip));
        clip.tracks[0].bone = 999;             // индекс мимо
        clip.tracks[0].name = 'bip_hand_R';    // а имя верное
        return createClip(THREE, clip, bones).tracks.map(t => t.path);""")
    assert out == ["bip_hand_R.position", "bip_hand_R.quaternion"]


def test_clip_without_tracks_leaves_the_scene_alone():
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        const result = applyClip(THREE, s, { times: [], tracks: [] });
        return { result, meshes: s.meshes.length, action: s.action };""")
    assert out == {"result": None, "meshes": 2, "action": None}


# ── Показ реквизита по событиям насмешки ──────────────────────────────────── #

def test_prop_is_hidden_only_within_its_ranges():
    """Медик лезет за снимком за пазуху и убирает его в конце.

    Секунды приходят из Python (`taunt_worker.hidden_ranges`) по событиям
    AE_WPN_HIDE/UNHIDE из QC. Конец `null` — «до конца клипа».
    """
    data = json.loads(json.dumps(DATA))
    data["weaponHidden"] = [[0, 0.77], [5.53, None]]
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        const prop = s.meshes.find(m => m.kind === 'weapon').mesh;
        const arm  = s.meshes.find(m => m.kind === 'arms').mesh;
        const at = t => { s.action.time = t; updateHidden(s);
                          return [prop.visible, arm.visible]; };
        return { start: at(0.1), middle: at(3), tail: at(6) };""", data)
    # Рука видна всегда: события про то, что персонаж держит, а не про него.
    assert out == {"start": [False, None], "middle": [True, None],
                   "tail": [False, None]}


def test_without_events_the_prop_is_always_visible():
    """У обычной насмешки скрывать нечего — и трогать меши незачем."""
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        s.action.time = 0;
        updateHidden(s);
        return { props: s.props.length,
                 visible: s.meshes.map(m => m.mesh.visible) };""")
    assert out == {"props": 0, "visible": [None, None]}


def test_hold_lengthens_the_clip_so_the_pose_stays():
    """Замороженная смерть: тело доигрывает удар и застывает в этой позе.

    Отдельной логики это не требует — за концом дорожки three.js отдаёт её
    последнее значение, поэтому пауза это просто более длинный клип.
    """
    data = json.loads(json.dumps(DATA))
    data["clip"]["duration"] = 1.23
    data["clip"]["hold"] = 3.0
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return { duration: s.duration, tracks: s.action.clip.tracks.length };""",
               data)
    assert out == {"duration": 4.23, "tracks": 2}


def test_clip_without_hold_is_unchanged():
    out = _run("""const s = buildSkinnedScene(THREE, DATA, makeMaterial);
        return s.duration;""")
    assert out == DATA["clip"]["duration"]


def test_empty_data_does_not_explode():
    out = _run("""const s = buildSkinnedScene(THREE, {}, makeMaterial);
        return { meshes: s.meshes.length, action: s.action };""", {})
    assert out == {"meshes": 0, "action": None}
