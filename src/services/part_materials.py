"""
Часть модели как отдельный материал.

Зачем. Эффекты VMT (блеск, свечение, прозрачность, анимация текстуры)
действуют на материал целиком, а материал у оружия обычно один на всю модель.
Чтобы светился только экран или блестел только ствол, часть надо сделать
своим материалом: её треугольники получают в SMD новое имя, и у нового имени
свой VMT.

Где это живёт. Разбор на части и покраска об этом не знают: часть остаётся
частью своего материала, а пока у нового материала нет своей картинки, он
берёт текстуру исходного вместе с её покраской. Своё у него — VMT, карты
материала, настройки текстуры и, если человек положит, картинка.

Как сборка находит треугольники. Номера треугольников части — номера в OBJ
превью внутри материала. OBJ пишется из SMD подряд: основной файл, затем
бодигруппы, и треугольник попадает в него, только если все три вершины
разобрались (`SmdToObjService`). Здесь тот же обход тех же файлов тем же
разбором, поэтому номер ведёт ровно к тому треугольнику. Список файлов OBJ
помнит сам — строкой `# Sources:` в шапке.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Строка шапки OBJ со списком исходных SMD (имена через «|», по порядку).
SOURCES_PREFIX = '# Sources:'

_RE_TRIANGLES = re.compile(r"\btriangles\b(.*?)\bend\b", re.DOTALL | re.IGNORECASE)


# ── Имена ─────────────────────────────────────────────────────────────────── #

def next_name(base: str, taken: Iterable[str],
              busy: Callable[[str], bool] = lambda name: False) -> str:
    """Свободное имя нового материала: `<исходный>_part<N>`.

    Нижний регистр: Source ищет материалы в нижнем регистре, а VPK — нет.
    `busy` — имя занято не моделью: под ним лежит правка VMT прежнего
    материала (правки хранятся по имени), и новый унаследовал бы её.
    """
    used = {str(t).lower() for t in taken}
    stem = str(base).lower()
    n = 1
    while f"{stem}_part{n}" in used or busy(f"{stem}_part{n}"):
        n += 1
    return f"{stem}_part{n}"


def variant_name(part: str, base: str, variant: str, row: int) -> str:
    """Имя части в строке скина, где исходный материал заменён вариантом.

    Хвост варианта переезжает к части: `c_x_blue` → `c_x_part1_blue`,
    `hat_red`/`hat_blue` → `hat_red_part1_blue`. Так у части выходит
    `<часть>_blue`, а это имя сборка уже знает: карты материала она сама
    дублирует в `<материал>_blue.vmt`.
    """
    a, b = base.lower(), variant.lower()
    common = os.path.commonprefix([a, b])
    tail = b[len(common):].strip('_')
    return f"{part}_{tail}" if tail else f"{part}_s{row}"


# ── OBJ превью → SMD ─────────────────────────────────────────────────────── #

def sources_of_obj(obj_path: str) -> List[str]:
    """Имена SMD, из которых по порядку собран OBJ превью (пусто — не знаем)."""
    try:
        with open(obj_path, encoding='utf-8', errors='replace') as f:
            for _ in range(8):
                line = f.readline()
                if line.startswith(SOURCES_PREFIX):
                    names = line[len(SOURCES_PREFIX):].strip()
                    return [n for n in names.split('|') if n]
    except OSError:
        pass
    return []


def rename_triangles(smd_text: str, material: str, names: Dict[int, str],
                     start: int = 0) -> Tuple[str, int, Counter]:
    """
    Переименовывает материал у выбранных треугольников одного SMD.

    `names` — {номер треугольника `material` в OBJ превью: новое имя},
    `start` — сколько таких треугольников было в предыдущих файлах. Все части
    одного материала идут ОДНИМ проходом: переименованный треугольник уже не
    `material`, и вторая часть, пройдя файл после первой, считала бы номера со
    сдвигом. Обход повторяет `SmdToObjService._parse_triangles_by_mat`:
    непустые строки секции, имя и три вершины подряд, в счёт идёт только
    треугольник с тремя разобранными вершинами.

    Returns:
        (новый текст, сколько треугольников `material` в файле,
        {новое имя: сколько треугольников получило его})
    """
    from src.services.smd_to_obj_service import SmdToObjService

    renamed: Counter = Counter()
    m = _RE_TRIANGLES.search(smd_text)
    if not m:
        return smd_text, 0, renamed
    lines = smd_text[m.start(1):m.end(1)].splitlines(keepends=True)
    filled = [i for i, ln in enumerate(lines) if ln.strip()]
    count = 0
    k = 0
    while k < len(filled):
        name_at = filled[k]
        name = lines[name_at].strip()
        verts = [SmdToObjService._parse_vertex(lines[j].strip())
                 for j in filled[k + 1:k + 4]]
        k += 4
        if len(verts) < 3 or any(v is None for v in verts) or name != material:
            continue
        new_name = names.get(start + count)
        if new_name:
            line = lines[name_at]
            lead = line[:len(line) - len(line.lstrip())]
            end = line[len(line.rstrip('\r\n')):]
            lines[name_at] = lead + new_name + end
            renamed[new_name] += 1
        count += 1
    text = smd_text[:m.start(1)] + ''.join(lines) + smd_text[m.end(1):]
    return text, count, renamed


def add_part_columns(rows: List[List[str]],
                     parts: Sequence[Tuple[str, str]]
                     ) -> Tuple[List[List[str]], Dict[str, str]]:
    """
    Добавляет части столбцами в строки `$texturegroup`.

    `parts` — пары (часть, исходный материал). В строке, где исходный
    материал заменён вариантом (BLU, австралий, стиль), часть получает свой
    вариант (см. variant_name). Исходного материала в группе нет — часть в
    неё не добавляется: материал вне группы одинаков во всех скинах, и так
    было с ним и раньше.

    Returns:
        (новые строки, {имя части в строке: материал, чей VMT она берёт}).
    """
    rows = [list(r) for r in rows]
    variants: Dict[str, str] = {}
    for part, base in parts:
        head = [n.lower() for n in rows[0]] if rows else []
        col = head.index(base.lower()) if base.lower() in head else -1
        if col < 0:
            variants[part] = base
            continue
        for r, row in enumerate(rows):
            source = row[col] if col < len(row) else base
            name = (part if source.lower() == base.lower()
                    else variant_name(part, base, source, r))
            if variants.get(name, source).lower() != source.lower():
                name = f"{part}_s{r}"
            variants[name] = source
            row.append(name)
    return rows, variants


def apply_to_model(qc_path: str, specs: Sequence[dict],
                   warn: Callable[[str], None] = lambda message: None) -> Dict[str, str]:
    """
    Делает части своими материалами в разобранной модели перед компиляцией.

    Переписывает SMD рядом с QC и `$texturegroup` в самом QC. `specs` —
    [{name, base, tris, total, sources}] (см. AppSession._part_material_specs).

    Номера треугольников годятся только для той модели, на которой выбирали
    части. Нет какого-то из её SMD или у материала не столько треугольников,
    сколько было тогда (`total`), — части этого материала не переносятся
    вовсе, и `warn` говорит об этом: по чужим номерам они легли бы не на те
    треугольники.

    Returns:
        {имя материала части: материал, чей VMT она берёт} — по нему сборка
        пишет VMT частей.
    """
    folder = os.path.dirname(qc_path)
    groups: Dict[str, List[dict]] = {}
    for spec in specs:
        groups.setdefault(str(spec['base']), []).append(spec)

    applied: List[Tuple[str, str]] = []
    for base, group in groups.items():
        names = {int(t): str(s['name']).lower() for s in group for t in s.get('tris') or ()}
        paths = [os.path.join(folder, os.path.basename(src))
                 for src in group[0].get('sources') or ()]
        total = next((int(s['total']) for s in group if s.get('total')), 0)
        out, seen, renamed = [], 0, Counter()
        if paths and all(os.path.isfile(p) for p in paths):
            for path in paths:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    text, count, done = rename_triangles(f.read(), base, names, seen)
                seen += count
                renamed += done
                out.append((path, text, done))
        if not out or (total and seen != total):
            logger.warning(f"[ЧАСТИ] {base}: SMD {len(out)}/{len(paths)}, "
                           f"треугольников {seen} при выборе {total} — части пропущены")
            for s in group:
                name = str(s['name']).lower()
                warn(f"Материал части «{name}» не собран: модель не та, на которой выбирали части")
            continue
        for path, text, done in out:
            if done:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text)
        for s in group:
            name = str(s['name']).lower()
            if renamed[name]:
                applied.append((name, base))
                logger.info(f"[ЧАСТИ] {name}: {renamed[name]} треугольников из {base}")
            else:
                logger.warning(f"[ЧАСТИ] {name}: треугольники не найдены — часть пропущена")

    variants: Dict[str, str] = {}
    if not applied:
        return variants
    from src.services import qc_skin_parser
    from src.services.model_build_service import ModelBuildService
    rows = qc_skin_parser.parse_texturegroup_rows(qc_path)
    if rows:
        rows, variants = add_part_columns(rows, applied)
        ModelBuildService.replace_texturegroup_in_qc(
            qc_path, ModelBuildService.generate_renamed_texturegroup(rows, {}))
    else:
        variants = {name: base for name, base in applied}
    return variants


# ── VMT ───────────────────────────────────────────────────────────────────── #

def _spelled(key: str) -> str:
    """Ключ для записи: разбор хранит его без «$» и в нижнем регистре."""
    return key if key.startswith('%') else f'${key}'


def _drop_key(text: str, key: str) -> str:
    from src.services.vmt_effects import _key_re
    return re.sub(_key_re(key).pattern + r'\n?', '', text,
                  flags=re.IGNORECASE | re.MULTILINE)


def _proxies_span(text: str) -> Optional[Tuple[int, int]]:
    """Начало и конец (включительно с «}») блока Proxies, если он есть."""
    from src.services.vmt_effects import _PROXIES_RE, _match_brace
    m = _PROXIES_RE.search(text)
    if not m:
        return None
    close = _match_brace(text, m.end() - 1)
    return (m.start(), close + 1) if close >= 0 else None


def _set_shader(text: str, shader: str) -> str:
    from src.services.vmt_effects import _first_brace
    at = _first_brace(text)
    if at < 0:
        return text
    head = re.sub(r'"?[\w.\-]+"?(\s*)$', lambda m: f'"{shader}"{m.group(1)}',
                  text[:at], count=1)
    return head + text[at:]


def _basetexture(vmt_text: str) -> str:
    from src.services import vmt_parse
    value = vmt_parse.parse(vmt_text).get('basetexture') or ''
    return value.replace('\\', '/').strip('/').lower()


def basetexture_changed(original: str, edited: str) -> bool:
    """Человек сам сменил $basetexture в правке части. Это выбор (белая основа
    под свечение, чужая текстура игры), а не устаревший путь: сборка его не
    подменяет, как и у главного материала (VpkTextureBuilder._basetexture_chosen)."""
    chosen = _basetexture(edited)
    return bool(chosen) and chosen != _basetexture(original)


def overlay_vmt(base: str, original: str, edited: str) -> str:
    """
    Переносит на VMT другого скина то, что человек поменял в VMT части.

    `original` — с чего человек начинал правку (VMT исходного материала),
    `edited` — что получилось. Изменённые и добавленные параметры ставятся в
    `base`, удалённые убираются, блок Proxies заменяется целиком, если его
    трогали. $basetexture переносится, только если человек выбрал его сам
    (basetexture_changed): иначе текстура у каждого скина своя (у синего —
    синяя, у австралия — золото).
    """
    from src.services import vmt_parse
    from src.services.vmt_effects import _set_key

    was, now = vmt_parse.parse(original), vmt_parse.parse(edited)
    keep = set() if basetexture_changed(original, edited) else {'basetexture'}
    out = base
    if now.shader and now.shader != was.shader:
        out = _set_shader(out, now.shader)
    for key, value in now.root.params.items():
        if key not in keep and was.root.params.get(key) != value:
            out = _set_key(out, _spelled(key), value)
    for key in was.root.params:
        if key != 'basetexture' and key not in now.root.params:
            out = _drop_key(out, _spelled(key))
    if now.block('proxies') != was.block('proxies'):
        theirs = _proxies_span(edited)
        mine = _proxies_span(out)
        block = edited[theirs[0]:theirs[1]] if theirs else ''
        if mine:
            out = out[:mine[0]] + block + out[mine[1]:]
        elif block:
            close = out.rfind('}')
            out = (out[:close].rstrip() + '\n' + block + '\n' + out[close:]
                   if close >= 0 else out + '\n' + block)
    return out
