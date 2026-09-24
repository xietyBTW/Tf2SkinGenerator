"""
Гирлянда поверх оружия: праздничная версия и фестивайзер в превью.

Как это устроено в игре. Гирлянда — отдельная модель, которую игра рисует
МАТРИЦАМИ КОСТЕЙ оружия (`DrawEconEntityAttachedModels` в SDK). Праздничная
версия предмета берёт её из `attached_models`, фестивайзер — из
`attached_models_festive` (атрибут `is_festivized`). Сама пушка при этом та же
модель, что у обычной версии, поэтому менять гирлянду имеет смысл отдельно.

Материалы гирлянды зовутся `deco:<вид>/<материал>`: вьювер держит их своим
слоем поверх модели, а альбом — отдельными карточками. Правки гирлянды не
смешиваются с оружием: в его сборку они не идут, гирлянду собирает свой шаг
(`decor_build`) — своей моделью и с материалами в своей папке, чтобы новая
текстура не легла на гирлянды остальных оружий. Выключенная гирлянда ничего не
стоит.

Модуль без Qt.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from src.domain.preview.texture_state import DECOR_PREFIX as PREFIX
from src.services.base_worker import BaseWorker, Signal
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def card(kind: str, material: str) -> str:
    """Имя карточки (и меша) материала гирлянды: `deco:festivizer/festive_lights_red`.

    Вид в имени обязателен: у праздничной версии и фестивайзера материалы
    свои, и правка одного не должна лечь на другой.
    """
    return f"{PREFIX}{kind}/{material}"


def parse_card(name: str) -> tuple:
    """(вид, материал) из имени карточки; ('', '') — это не гирлянда."""
    if not name or not name.startswith(PREFIX) or "/" not in name:
        return "", ""
    kind, _, material = name[len(PREFIX):].partition("/")
    return kind, material


@dataclass(frozen=True)
class Decor:
    """Готовая к показу гирлянда."""

    kind: str
    #: Ключ предмета, на котором она висит: результат старого запроса к
    #: новому предмету не относится.
    weapon_key: str
    #: OBJ в осях превью (те же, что у модели предмета).
    obj_path: str
    #: Reference SMD гирлянды — для сцены от первого лица.
    smd_path: str
    #: {`deco:материал`: {"red": [кадры], "blu": [кадры], "fps": частота}}.
    #: Лампочки мигают: базовая текстура у них многокадровая.
    materials: Dict[str, dict] = field(default_factory=dict)
    #: {`deco:материал`: как рисовать} — самосвет, прозрачность (vmt_render).
    hints: Dict[str, dict] = field(default_factory=dict)
    #: {меш: [жёсткая группа каждой вершины OBJ]} — для изгиба во вьювере
    #: (см. rigid_groups): лампочки двигаются целиком, провод гнётся.
    groups: Dict[str, List[int]] = field(default_factory=dict)
    #: Своя модель гирлянды, из которой собрана эта (пусто — стоковая): по
    #: ней кэш показа отличает старую сборку от новой.
    source: str = ''

    @property
    def has_team(self) -> bool:
        """Синяя команда видит другие огоньки (у фестивайзера — синие)."""
        return any(m["blu"] != m["red"] for m in self.materials.values())

    def as_event(self) -> dict:
        return {"kind": self.kind, "obj": self.obj_path,
                "materials": self.materials, "hints": self.hints,
                "groups": self.groups}


def kinds(weapon_key: str, tf2_root: str) -> Dict[str, str]:
    """{вид: путь MDL} гирлянд, которые игра вешает на эту модель."""
    from src.data import viewmodel_anims
    try:
        return viewmodel_anims.decor_models(weapon_key, tf2_root)
    except Exception as exc:                                  # noqa: BLE001
        logger.debug(f"[гирлянда] items_game не прочитан: {exc}")
        return {}


def build(weapon_key: str, kind: str, misc_vpk: str, textures_vpk: str,
          tf2_root: str, cancelled: Optional[Callable[[], bool]] = None,
          on_progress: Optional[Callable] = None,
          custom_smd: str = '') -> Optional[Decor]:
    """Достаёт гирлянду и готовит её к показу. None — гирлянды нет.

    `custom_smd` — своя модель гирлянды: её треугольники садятся на скелет
    стоковой (кости по имени, остальное — на главную), QC остаётся стоковым.
    Материалы — свои; у каких в игре нет текстуры, те серые до покраски.

    Raises:
        model_decompile_service.DecompileError: нет Crowbar или он упал.
    """
    from src.services import model_decompile_service as mds
    from src.services import qc_skin_parser, smd_service
    from src.services.game_vpk_reader import GameVpkReader
    from src.services.smd_to_obj_service import MeshPart, SmdToObjService

    mdl = kinds(weapon_key, tf2_root).get(kind)
    if not mdl:
        return None
    stem = os.path.splitext(os.path.basename(mdl))[0]
    stop = cancelled or (lambda: False)

    found = mds.ensure_decompiled(stem, misc_vpk, [mdl], cancelled=stop,
                                  on_progress=on_progress)
    if found is None or stop():
        return None
    smd = smd_service.find_reference_smd(found.directory, stem)
    model = qc_skin_parser.load_model(found.directory)
    if not smd or model is None:
        logger.warning(f"[гирлянда] {stem}: нет меша или QC в {found.directory}")
        return None

    out_dir = tempfile.mkdtemp(prefix="tf2sg_decor_")
    if custom_smd:
        smd = own_on_stock(custom_smd, smd, os.path.join(out_dir, "custom.smd"))
    obj = os.path.join(out_dir, "decor.obj")
    ok, names = SmdToObjService.convert_parts(
        [MeshPart(smd_path=smd, skinning=_weapon_pose(weapon_key, smd),
                  material_prefix=card(kind, ""))], obj)
    if not ok or stop():
        return None

    reader = GameVpkReader([textures_vpk, misc_vpk])
    try:
        materials, hints = _materials(reader, model, names, out_dir, card(kind, ""),
                                      blank=bool(custom_smd))
    finally:
        reader.close()
    logger.info(f"[гирлянда] {weapon_key}: {kind} = {stem}, "
                f"материалы {sorted(materials)}")
    return Decor(kind=kind, weapon_key=weapon_key, obj_path=obj,
                 smd_path=smd, materials=materials, hints=hints,
                 groups=bend_groups(smd, card(kind, "")), source=custom_smd)


def own_on_stock(custom_smd: str, stock_smd: str, out_path: str) -> str:
    """Своя гирлянда на скелете стоковой: в игре её везут кости оружия."""
    from src.services.smd_service import SMDService
    return SMDService.replace_model_sections(custom_smd, stock_smd, out_path,
                                             keep_user_materials=True)


def _weapon_pose(weapon_key: str, decor_smd: str) -> Optional[dict]:
    """Поза оружия, переложенная на кости гирлянды.

    Превью ставит оружие в позу его `idle`, и гирлянда обязана встать туда
    же — в игре она едет костями оружия. Матрицы позы нумеруются костями
    ОРУЖИЯ, а порядок костей у гирлянды бывает другим (у медигана шланг и
    рычаг переставлены), поэтому перекладываем по именам.
    """
    from src.services import decompile_cache, smd_pose, smd_service

    # ponytail: поза только из кэша декомпиляции. У мода из VPK стоковое
    # оружие могло ещё не разбираться — тогда гирлянда в bind-позе; это
    # заметно лишь у немногих моделей, чей idle не совпадает с bind.
    qc = decompile_cache.find_cached_qc_for_weapon(weapon_key)
    if not qc:
        return None
    ref = smd_service.find_reference_smd(os.path.dirname(qc), weapon_key)
    pose = smd_pose.find_pose_smd(qc)
    mats = smd_pose.skinning_matrices(ref, pose) if ref and pose else None
    if not mats:
        return None
    weapon_names = smd_pose.parse_node_names(ref)
    decor_index = {name: i for i, name in smd_pose.parse_node_names(decor_smd).items()}
    moved = {decor_index[weapon_names[i]]: m for i, m in mats.items()
             if weapon_names.get(i) in decor_index}
    return moved or None


# ── Изгиб гирлянды ───────────────────────────────────────────────────────────
#
# Гирлянду гнут «мягким выделением», как в Blender: схватили точку, всё в
# радиусе тянется следом с плавным затуханием. Правка — СПИСОК движений
# {c: точка, r: радиус, d: сдвиг} в осях SMD гирлянды; вьювер показывает их
# сразу (js/viewer_bend.js), сборка и вид от первого лица повторяют их на
# вершинах SMD — формула одна, её совпадение держит тест.
#
# Мелкие куски (лампочка, её патрон) двигаются ЦЕЛИКОМ — по весу в своём
# центре: иначе край радиуса мял бы лампочку. Гнётся только крупное — провод.

#: Диагональ габарита, ниже которой кусок считается мелким и не мнётся.
RIGID_SIZE = 4.0
#: Зазор, в котором мелкие куски считаются одним: лампочка сидит в патроне,
#: но вершин с ним не делит.
RIGID_TOUCH = 0.25


def falloff(t: float) -> float:
    """Вес движения на доле радиуса t: 1 в центре, плавно к 0 на краю."""
    if t >= 1.0:
        return 0.0
    u = 1.0 - t * t
    return u * u


def rigid_groups(points: List[tuple], triangles: int) -> List[int]:
    """Номер жёсткой группы каждой вершины (-1 — гнётся сама по себе).

    `points` — вершины треугольников подряд (по три на треугольник), как их
    отдаёт разбор SMD и как они лежат в OBJ вьювера. Кусок — вершины,
    связанные треугольниками (совпадение по положению: швы развёртки дробят
    вершины, но не кусок).
    """
    parent: Dict[tuple, tuple] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys = [tuple(round(c, 3) for c in pt) for pt in points]
    for i in range(triangles):
        a, b, c = keys[3 * i:3 * i + 3]
        parent[find(b)] = find(a)
        parent[find(c)] = find(a)

    islands: Dict[tuple, List[int]] = {}
    for idx, key in enumerate(keys):
        islands.setdefault(find(key), []).append(idx)
    boxes = []
    for members in islands.values():
        lo = [min(points[i][k] for i in members) for k in range(3)]
        hi = [max(points[i][k] for i in members) for k in range(3)]
        size = sum((hi[k] - lo[k]) ** 2 for k in range(3)) ** 0.5
        boxes.append((members, lo, hi, size < RIGID_SIZE))

    small = [b for b in boxes if b[3]]
    link = list(range(len(small)))

    def root(i):
        while link[i] != i:
            link[i] = link[link[i]]
            i = link[i]
        return i

    for i, (_, lo_a, hi_a, _) in enumerate(small):
        for j in range(i + 1, len(small)):
            _, lo_b, hi_b, _ = small[j]
            if all(lo_a[k] - RIGID_TOUCH <= hi_b[k] and lo_b[k] - RIGID_TOUCH <= hi_a[k]
                   for k in range(3)):
                link[root(j)] = root(i)

    out = [-1] * len(points)
    numbers: Dict[int, int] = {}
    for i, (members, *_rest) in enumerate(small):
        group = numbers.setdefault(root(i), len(numbers))
        for idx in members:
            out[idx] = group
    return out


def apply_bends(points: List[list], groups: List[int], bends: List[dict]) -> None:
    """Изгибы по порядку — на месте. Оси — те же, что у `bends` (SMD)."""
    for bend in bends or ():
        c = [float(v) for v in bend.get('c') or (0, 0, 0)]
        d = [float(v) for v in bend.get('d') or (0, 0, 0)]
        r = float(bend.get('r') or 0)
        if r <= 0:
            continue
        sums: Dict[int, list] = {}
        for pt, g in zip(points, groups):
            if g >= 0:
                acc = sums.setdefault(g, [0.0, 0.0, 0.0, 0])
                acc[0] += pt[0]
                acc[1] += pt[1]
                acc[2] += pt[2]
                acc[3] += 1
        weight_of: Dict[int, float] = {}
        for g, (x, y, z, n) in sums.items():
            dist = ((x / n - c[0]) ** 2 + (y / n - c[1]) ** 2 + (z / n - c[2]) ** 2) ** 0.5
            weight_of[g] = falloff(dist / r)
        for pt, g in zip(points, groups):
            if g >= 0:
                w = weight_of[g]
            else:
                dist = ((pt[0] - c[0]) ** 2 + (pt[1] - c[1]) ** 2 + (pt[2] - c[2]) ** 2) ** 0.5
                w = falloff(dist / r)
            if w:
                pt[0] += w * d[0]
                pt[1] += w * d[1]
                pt[2] += w * d[2]


def _smd_triangles(text: str) -> tuple:
    """(строки, [(материал, [номер строки ×3], [точка ×3], [(связи, нормаль) ×3])])
    в ПОРЯДКЕ разбора SMD→OBJ: материалы по первому появлению, треугольники
    подряд.

    Повторяет правила `SmdToObjService._parse_triangles_by_mat` (пустые
    строки не считаются, треугольник без трёх вершин отбрасывается) — иначе
    номера вершин вьювера и сборки разошлись бы. Строки режутся только по
    переводу строки: `splitlines` резал бы и по служебным символам, и номера
    строк уехали бы от счёта `\n`.
    """
    from src.services.smd_to_obj_service import _RE_TRIANGLES, SmdToObjService

    lines = text.split('\n')
    match = _RE_TRIANGLES.search(text)
    if not match:
        return lines, []
    offset = text.count('\n', 0, match.start(1))
    body = [(offset + i, ln) for i, ln in enumerate(match.group(1).split('\n'))
            if ln.strip()]
    by_mat: Dict[str, list] = {}
    i = 0
    while i < len(body):
        material = body[i][1].strip()
        i += 1
        rows, pts, extra = [], [], []
        for _ in range(3):
            if i >= len(body):
                break
            vert = SmdToObjService._parse_vertex(body[i][1].strip())
            if vert is not None:
                rows.append(body[i][0])
                pts.append(tuple(vert['pos']))
                extra.append((tuple(vert.get('links') or ()), tuple(vert['nrm'])))
            i += 1
        if len(pts) == 3:
            by_mat.setdefault(material, []).append((material, rows, pts, extra))
    return lines, [tri for tris in by_mat.values() for tri in tris]


def bend_groups(smd_path: str, prefix: str) -> Dict[str, List[int]]:
    """Жёсткие группы вершин по мешам вьювера: {`prefix`+материал: [группа]}."""
    with open(smd_path, encoding='utf-8', errors='replace') as f:
        _lines, tris = _smd_triangles(f.read())
    points = [pt for tri in tris for pt in tri[2]]
    flat = rigid_groups(points, len(tris))
    out: Dict[str, List[int]] = {}
    for n, tri in enumerate(tris):
        out.setdefault(prefix + tri[0], []).extend(flat[3 * n:3 * n + 3])
    return out


def weapon_pose(weapon_key: str, decor_smd: str) -> Optional[dict]:
    """Поза, в которой превью показывает гирлянду (см. _weapon_pose)."""
    return _weapon_pose(weapon_key, decor_smd) if weapon_key else None


def bend_smd(src_path: str, out_path: str, bends: List[dict],
             pose: Optional[dict] = None) -> str:
    """SMD с изгибами в позициях вершин: кости, веса, нормали — как были.

    Изгибы сделаны на гирлянде В ПОЗЕ превью (idle оружия): там их схватили
    мышью. Поэтому и здесь они считаются по вершинам в той же позе, а сдвиг
    возвращается в исходную позу SMD обратной матрицей кости вершины. Поза
    — та же функция и та же проверка на разъезд, что у OBJ превью
    (SmdToObjService._apply_skinning): где превью позу не взяло, не берём и мы.
    """
    from src.services import smd_pose

    with open(src_path, encoding='utf-8', errors='replace') as f:
        lines, tris = _smd_triangles(f.read())
    points = [list(pt) for tri in tris for pt in tri[2]]
    extra = [e for tri in tris for e in tri[3]]
    groups = rigid_groups([tuple(p) for p in points], len(tris))

    posed = None
    if pose:
        posed = [list(smd_pose.apply_to_vertex(pose, links, pt, nrm)[0])
                 for pt, (links, nrm) in zip(points, extra)]
        if not smd_pose.looks_sane(points, posed):
            posed = None
    if posed is None:
        apply_bends(points, groups, bends)
    else:
        moved = [list(p) for p in posed]
        apply_bends(moved, groups, bends)
        for pt, was, now, (links, _nrm) in zip(points, posed, moved, extra):
            delta = [now[k] - was[k] for k in range(3)]
            if not any(delta):
                continue
            bone = max(links, key=lambda bw: bw[1])[0] if links else None
            m = pose.get(bone) if bone is not None else None
            back = smd_pose.transform_dir(smd_pose.rigid_inverse(m), delta) if m else delta
            for k in range(3):
                pt[k] += back[k]

    rows = [row for tri in tris for row in tri[1]]
    for row, pt in zip(rows, points):
        parts = lines[row].split()
        parts[1:4] = [f'{v:.6f}' for v in pt]
        lines[row] = ' '.join(parts)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return out_path


def shaped_smd(smd_path: str, fit: Optional[dict],
               bends: Optional[List[dict]] = None,
               pose: Optional[dict] = None) -> str:
    """SMD гирлянды с изгибами и подгонкой; без правок — сам исходник.

    Порядок тот же, что во вьювере: изгибы — по самой гирлянде (в позе
    превью, см. bend_smd), подгонка — поверх неё целиком. Вершины двигаются
    в осях модели, веса костей остаются: в игре гирлянда по-прежнему едет
    костями оружия. Файл кладётся во временную папку под именем от правок и
    исходника; пишется через временный и переименовывается — недописанный
    файл в кэше не останется.
    """
    import hashlib
    import json

    from src.services import mesh_import_service

    parsed = mesh_import_service.Fit.from_dict(fit)
    moved = bool(fit) and parsed != mesh_import_service.Fit()
    if not moved and not bends:
        return smd_path
    try:
        stamp_src = os.path.getmtime(smd_path)
    except OSError:
        stamp_src = 0
    pose_key = sorted((k, [round(v, 5) for v in m]) for k, m in (pose or {}).items())
    stamp = hashlib.sha1(json.dumps(
        [smd_path, stamp_src, parsed.to_dict(), bends or [], pose_key],
        sort_keys=True).encode()).hexdigest()[:12]
    out = os.path.join(tempfile.gettempdir(), "tf2sg_decor_fit",
                       f"{os.path.splitext(os.path.basename(smd_path))[0]}_{stamp}.smd")
    if not os.path.isfile(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = f"{out}.{os.getpid()}.tmp"
        src = bend_smd(smd_path, tmp, bends, pose) if bends else smd_path
        if moved:
            mesh_import_service.transform_smd(src, tmp, parsed)
        os.replace(tmp, out)
    return out


# ── Мигание лампочек ─────────────────────────────────────────────────────────
#
# Лампочки мигают многокадровой базовой текстурой (прокси AnimatedTexture, кадр
# в секунду): в каждом кадре один цвет приглушён, а альфа — маска самосвета
# ($selfillum) — у него чёрная. Своя текстура человека (кистью по частям,
# картинкой) — один кадр, и мигание пропало бы. Поэтому её раскладываем на те
# же кадры сами: где в игровом кадре лампочка погашена, гасим и свой цвет в
# той же доле, а маску свечения берём игровую. Никаких полос и цветов здесь не
# предполагается — только «насколько этот пиксель в кадре тусклее, чем горя».


def _grey_png(out_dir: str, name: str) -> str:
    from PIL import Image
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    path = os.path.join(out_dir, f"{safe}_blank.png")
    Image.new("RGBA", (64, 64), (160, 160, 160, 255)).save(path)
    return path


def _sibling(path: str, suffix: str) -> str:
    stem, ext = os.path.splitext(path)
    return f"{stem}_{suffix}{ext or '.png'}"


def _rgba(path: str, size=None):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGBA")
        if size and im.size != size:
            im = im.resize(size, Image.BILINEAR)
        return np.asarray(im, dtype=np.float32)


def lit_frame(frames: List[str], out: str) -> str:
    """Кадр «всё горит»: каждый пиксель — из того кадра, где он ярче всего.

    Один кадр — он сам и есть.
    """
    import numpy as np
    from PIL import Image

    if len(frames) < 2:
        return frames[0]
    stack = np.stack([_rgba(p) for p in frames])            # кадр, y, x, rgba
    best = stack[..., :3].max(axis=3).argmax(axis=0)        # y, x
    lit = np.take_along_axis(stack, best[None, :, :, None], axis=0)[0]
    lit[..., 3] = stack[..., 3].max(axis=0)
    Image.fromarray(lit.clip(0, 255).astype(np.uint8), "RGBA").save(out)
    return out


def blink_like(image: str, stock: List[str], out_dir: str, name: str) -> List[str]:
    """Своя текстура — теми же кадрами, что игровые: [png кадра]. У игровой
    текстуры один кадр — мигать нечему, отдаётся сама картинка."""
    import numpy as np
    from PIL import Image

    if len(stock) < 2:
        return [image]
    with Image.open(image) as im:
        own = np.asarray(im.convert("RGB"), dtype=np.float32)
        size = im.size
    frames = [_rgba(p, size) for p in stock]
    value = [f[..., :3].max(axis=2) for f in frames]
    top = np.maximum(np.max(value, axis=0), 1.0)
    out = []
    os.makedirs(out_dir, exist_ok=True)
    for k, (frame, v) in enumerate(zip(frames, value)):
        dim = (v / top).clip(0.0, 1.0)[..., None]
        rgba = np.concatenate([own * dim, frame[..., 3:4]], axis=2)
        path = os.path.join(out_dir, f"{name}_{k:02d}.png")
        Image.fromarray(rgba.clip(0, 255).astype(np.uint8), "RGBA").save(path)
        out.append(path)
    return out


def _materials(reader, model, names: List[str], out_dir: str,
               prefix: str, blank: bool = False) -> tuple:
    """Кадры RED/BLU и свойства рисования каждого материала гирлянды.

    `blank` — своя модель: материал без игровой текстуры получает серую
    основу, чтобы у него была карточка и его можно было покрасить.
    """
    from src.services import vmt_parse, vmt_tint
    from src.services.material_resolver import MaterialResolver
    from src.services.vtf_preview_service import vtf_bytes_to_frame_pngs

    resolver = MaterialResolver(reader, out_dir)
    cdmats = list(model.cdmaterials)
    team = {red.lower(): blu for red, blu in model.team_map.items()}

    def frames(mat: str) -> tuple:
        """(кадры, частота, светится ли) одного материала."""
        info = resolver.describe(mat, cdmats)
        data = (reader.find_vtf_for_basetexture(info.basetexture)
                if info.basetexture else None)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in mat)
        pngs = vtf_bytes_to_frame_pngs(data, out_dir, safe) if data else []
        for png in pngs:
            vmt_tint.apply_to_png(png, info.tint)
        raw_vmt = reader.read(info.vmt_path) if info.vmt_path else None
        text = raw_vmt.decode("utf-8", "replace") if raw_vmt else ""
        fps = (vmt_parse.animated_framerate(text) or 0.0) if len(pngs) > 1 else 0.0
        # Лампочки в игре светятся сами ($selfillum в ветке >=DX90): без
        # этого в превью они тусклые, как крашеный пластик.
        glow = any(v.strip() == "1" for v in
                   vmt_parse.params_named(vmt_parse.parse(text).root, "selfillum"))
        return pngs, fps, glow

    materials: Dict[str, dict] = {}
    hints: Dict[str, dict] = {}
    for name in names:
        raw = name[len(prefix):]
        red, fps, glow = frames(raw)
        if not red and blank:
            red = [_grey_png(out_dir, raw)]
        if not red:
            logger.info(f"[гирлянда] без текстуры: {raw}")
            continue
        blu_name = team.get(raw.lower())
        blu = frames(blu_name)[0] if blu_name and blu_name.lower() != raw.lower() else []
        blu = blu or red
        materials[name] = {"red": red, "blu": blu, "fps": fps, "glow": glow,
                           # Лампочки «все горят» — основа карточки и частей:
                           # в первом кадре один цвет погашен, и кисть по
                           # нему давала бы тёмный цвет.
                           "lit": {"red": lit_frame(red, _sibling(red[0], "lit")),
                                   "blu": lit_frame(blu, _sibling(blu[0], "lit"))}}
    for raw, spec in resolver.render_map([n[len(prefix):] for n in names],
                                         cdmats).items():
        hints[prefix + raw] = spec
    return materials, hints


class FestiveDecorWorker(BaseWorker):
    """Сборка гирлянды в фоне: декомпиляция — это секунды, а не миллисекунды."""

    ready = Signal(object)          # Decor
    failed = Signal(str)
    progress = Signal(str)

    _STAGES = {
        "ru": {"extracting": "Извлечение гирлянды…",
               "decompiling": "Разбор гирлянды…"},
        "en": {"extracting": "Extracting the lights…",
               "decompiling": "Decompiling the lights…"},
    }

    def __init__(self, weapon_key: str, kind: str, misc_vpk: str,
                 textures_vpk: str, tf2_root: str, lang: str = "en",
                 custom_smd: str = ''):
        super().__init__()
        self.custom_smd = custom_smd
        self.weapon_key = weapon_key
        self.kind = kind
        self._args = (misc_vpk, textures_vpk, tf2_root)
        self._p = self._STAGES.get(lang, self._STAGES["en"])

    def run(self) -> None:
        misc_vpk, textures_vpk, tf2_root = self._args
        try:
            decor = build(self.weapon_key, self.kind, misc_vpk, textures_vpk,
                          tf2_root, cancelled=self.isInterruptionRequested,
                          on_progress=lambda s: self.progress.emit(self._p[s.value]),
                          custom_smd=self.custom_smd)
        except Exception as exc:                              # noqa: BLE001
            logger.warning(f"[гирлянда] {self.weapon_key}/{self.kind}: {exc}",
                           exc_info=True)
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
            return
        if self.isInterruptionRequested():
            return
        if decor is None:
            self.failed.emit(f"{self.weapon_key}: {self.kind}")
            return
        self.ready.emit(decor)
