"""
SMD сервис — замена секций nodes/skeleton/material в SMD файлах.

Оптимизирован для больших файлов:
- Читаем файл один раз через readlines() (O(1) alloc)
- Пишем через writelines() вместо join() больших строк
- Используем индексы вместо slice-копий строк при парсинге
"""

import os
import re
import time
from typing import Callable, Dict, List, Optional, Tuple

#: Подстроки в имени SMD, по которым файл НЕ является видимым reference-мешем
#: (физика, анимации, позы). Единый источник для всех мест, что ищут reference SMD.
NON_REFERENCE_SMD_KEYWORDS: Tuple[str, ...] = ("physics", "phys", "anim", "idle", "pose")

#: Уровни детализации — в превью нужен нулевой, самый подробный.
_LOD_MARKER = "lod"


def find_reference_smd(directory: str, prefer: str = "") -> Optional[str]:
    """
    Видимый меш модели среди декомпилированных SMD.

    Приоритет: `*_reference.smd` → имя содержит `prefer` → самый крупный
    оставшийся файл. Крупнейший как последний рубеж не случаен: у моделей без
    `_reference` в имени основной меш всё равно тяжелее любого куска.

    Физика, анимации, позы и LOD-и исключаются всегда.

    Returns:
        Путь к SMD или None, если подходящих файлов нет.
    """
    import glob

    def usable(path: str) -> bool:
        name = os.path.basename(path).lower()
        return (_LOD_MARKER not in name
                and not any(kw in name for kw in NON_REFERENCE_SMD_KEYWORDS))

    candidates = [p for p in glob.glob(os.path.join(directory or "", "*.smd"))
                  if usable(p)]
    if not candidates:
        return None
    for group in (
        [p for p in candidates if "_reference" in os.path.basename(p).lower()],
        [p for p in candidates if prefer and prefer.lower() in os.path.basename(p).lower()],
    ):
        if group:
            return min(group, key=lambda p: len(os.path.basename(p)))
    return max(candidates, key=os.path.getsize)


#: Имена костей-хватов в TF2: за них оружие и держат.
_GRIP_PREFIXES = ("weapon_bone", "vm_weapon_bone")

#: Строка секции nodes: `0 "weapon_bone" -1`.
_NODE_RE = re.compile(r'\s*(\d+)\s+"([^"]*)"\s+(-?\d+)')


class SMDService:

    @staticmethod
    def material_triangle_counts(smd_paths: List[str]) -> dict:
        """
        {имя материала (lower): сколько треугольников} по нескольким SMD.

        В секции triangles каждый треугольник записан четырьмя строками: имя
        материала и три вершины. Считаем только имена — это дешёвая мера
        «сколько модели покрывает материал», по которой видно, какой материал
        основной, а какой — стекло, лампочка или экранчик.

        Отсутствующие и битые файлы просто пропускаются: мера вспомогательная,
        без неё вызывающий откатывается на порядок столбцов из QC.
        """
        counts: dict = {}
        for path in smd_paths or []:
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    in_triangles = False
                    step = 0
                    for line in f:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        low = stripped.lower()
                        if not in_triangles:
                            in_triangles = low == "triangles"
                            continue
                        if low == "end":
                            break
                        if step == 0:
                            name = os.path.splitext(
                                stripped.replace("\\", "/").rsplit("/", 1)[-1])[0].lower()
                            counts[name] = counts.get(name, 0) + 1
                        step = (step + 1) % 4
            except Exception:
                continue
        return counts

    @staticmethod
    def replace_model_sections(
        user_smd_path: str,
        original_smd_path: str,
        output_smd_path: Optional[str] = None,
        progress_cb: Optional[Callable[[int], None]] = None,
        keep_user_materials: bool = False,
    ) -> str:
        """
        Заменяет секции nodes/skeleton (а опц. и имена материалов) в пользовательском
        SMD на соответствующие из оригинального SMD игры.

        Args:
            user_smd_path:     Путь к SMD пользователя (геометрия)
            original_smd_path: Путь к оригинальному SMD из игры (bones, skeleton, materials)
            output_smd_path:   Куда записать результат (None = перезаписать user_smd_path)
            progress_cb:       Опциональный callback(pct: int 0-100). Вызывается с троттлингом
                               ~60 fps, чтобы не замедлять парсинг.
            keep_user_materials: True — сохранить ИМЕНА материалов пользователя (для
                               многотекстурных/«готовых» моделей; иначе все материалы
                               схлопнутся в один материал оригинала). nodes/skeleton
                               всё равно берутся из оригинала (риггинг под скелет TF2).
        Returns:
            Путь к записанному файлу.
        """
        if not os.path.exists(user_smd_path):
            raise FileNotFoundError(f"User SMD not found: {user_smd_path}")
        if not os.path.exists(original_smd_path):
            raise FileNotFoundError(f"Original SMD not found: {original_smd_path}")

        # Throttle: не чаще 60 fps, чтобы сигнал не съедал время парсинга
        _THROTTLE = 0.016
        _last_cb: List[float] = [0.0]

        def _cb(pct: int) -> None:
            if progress_cb is None:
                return
            now = time.monotonic()
            if now - _last_cb[0] >= _THROTTLE or pct >= 100:
                _last_cb[0] = now
                progress_cb(pct)

        with open(user_smd_path, 'r', encoding='utf-8') as f:
            user_lines = f.readlines()
        with open(original_smd_path, 'r', encoding='utf-8') as f:
            orig_lines = f.readlines()

        # Парсинг user-файла  → 0..60 %
        user_parts = SMDService._parse_smd_lines(user_lines, _cb, pct_start=0, pct_end=60)
        # Парсинг original-файла → 60..80 %
        orig_parts = SMDService._parse_smd_lines(orig_lines, _cb, pct_start=60, pct_end=80)

        if not user_parts or not orig_parts:
            raise ValueError("Failed to parse one of the SMD files")

        if output_smd_path is None:
            output_smd_path = user_smd_path

        with open(output_smd_path, 'w', encoding='utf-8') as out:
            _wlines(out, orig_parts.get('version') or user_parts.get('version'))
            _wlines(out, orig_parts.get('nodes') or user_parts.get('nodes'))
            _wlines(out, orig_parts.get('skeleton') or user_parts.get('skeleton'))
            # Запись треугольников → 80..100 %
            # keep_user_materials → передаём пустой список оригинальных имён,
            # тогда _write_merged_triangles сохраняет материалы пользователя.
            _orig_mat_names = [] if keep_user_materials else orig_parts.get('material_names', [])
            # Кости сопоставляются по ИМЕНИ: номера у риггера свои, а порядок в
            # декомпиляции произвольный (у Детонатора weapon_bone,
            # weapon_bone_3, weapon_bone_4, weapon_bone_2). Что не опознали —
            # на главный хват, то есть на кость, несущую бо́льшую часть
            # оригинального меша: у модели «только геометрия» кость одна и
            # зовётся `root`, в игровой таблице такой нет.
            SMDService._write_merged_triangles(
                out,
                user_parts.get('triangles_data', []),
                _orig_mat_names,
                progress_cb=_cb,
                pct_start=80,
                pct_end=100,
                bone_mapping=SMDService._bone_mapping(user_parts.get('nodes'),
                                                     orig_parts.get('nodes')),
                fallback_bone=SMDService._grip_bone(
                    orig_parts.get('nodes'),
                    orig_parts.get('triangles_data', [])),
            )

        _cb(100)
        return output_smd_path

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_smd_lines(
        lines: List[str],
        progress_cb: Optional[Callable[[int], None]] = None,
        pct_start: int = 0,
        pct_end: int = 100,
    ) -> dict:
        """
        Разбирает SMD на секции за один проход.

        progress_cb(pct) вызывается по мере обработки строк triangle-секции
        (самой длинной части файла). pct масштабируется в диапазон [pct_start, pct_end].
        """
        result: dict = {
            'version': None,
            'nodes': None,
            'skeleton': None,
            'triangles_data': [],
            'material_names': [],
        }

        n = len(lines)
        i = 0

        # --- version ---
        while i < n:
            s = lines[i].lstrip()
            if s.startswith('version'):
                start = i
                i += 1
                while i < n and not lines[i].lstrip().startswith(('nodes', 'skeleton', 'triangles')):
                    i += 1
                result['version'] = lines[start:i]
                break
            i += 1

        # --- nodes ---
        while i < n:
            if lines[i].lstrip().startswith('nodes'):
                start = i
                i += 1
                while i < n:
                    if lines[i].strip() == 'end':
                        result['nodes'] = lines[start:i + 1]
                        i += 1
                        break
                    i += 1
                break
            i += 1

        # --- skeleton ---
        while i < n:
            if lines[i].lstrip().startswith('skeleton'):
                start = i
                i += 1
                while i < n:
                    if lines[i].strip() == 'end':
                        result['skeleton'] = lines[start:i + 1]
                        i += 1
                        break
                    i += 1
                break
            i += 1

        # --- triangles — самая длинная секция, отсюда репортим прогресс ---
        tri_start_line = i  # строка "triangles"
        remaining = max(1, n - tri_start_line)  # строк в triangle-секции

        while i < n:
            if lines[i].lstrip().startswith('triangles'):
                i += 1
                current_mat: Optional[str] = None
                current_tris: List[str] = []

                while i < n:
                    raw = lines[i]
                    s = raw.strip()

                    if not s:
                        i += 1
                        continue

                    if s == 'end':
                        break

                    first_char = s[0]
                    is_tri = first_char.isdigit() or first_char == '-'

                    if is_tri:
                        if current_mat is not None:
                            current_tris.append(raw)
                    else:
                        if current_mat is not None and current_tris:
                            result['triangles_data'].append((current_mat, current_tris))
                            result['material_names'].append(current_mat)
                        current_mat = s
                        current_tris = []

                    i += 1

                    # Репортим прогресс каждые 256 строк (минимальный оверхед)
                    if progress_cb and (i & 0xFF) == 0:
                        done = i - tri_start_line
                        ratio = min(1.0, done / remaining)
                        progress_cb(pct_start + int(ratio * (pct_end - pct_start)))

                if current_mat is not None and current_tris:
                    result['triangles_data'].append((current_mat, current_tris))
                    result['material_names'].append(current_mat)

                break
            i += 1

        return result

    @staticmethod
    def _node_names(nodes_lines: Optional[List[str]]) -> Dict[int, str]:
        """{номер кости: имя} из секции nodes."""
        names: Dict[int, str] = {}
        for line in nodes_lines or ():
            m = _NODE_RE.match(line)
            if m:
                names[int(m.group(1))] = m.group(2)
        return names

    @staticmethod
    def _bone_mapping(user_nodes: Optional[List[str]],
                      orig_nodes: Optional[List[str]]) -> Dict[int, int]:
        """{номер кости у пользователя: номер той же кости по ИМЕНИ в игре}.

        Номера костей у риггера свои, и совпасть с игровыми они не могут:
        порядок в декомпиляции произвольный (у Детонатора `weapon_bone`,
        `weapon_bone_3`, `weapon_bone_4`, `weapon_bone_2`). Пока переносились
        одни номера, модель, зарриганная под игровые ИМЕНА, садилась на чужие
        кости — а угадать нужный порядок риггер не может никак.
        """
        by_name = {name: bone
                   for bone, name in SMDService._node_names(orig_nodes).items()}
        return {bone: by_name[name]
                for bone, name in SMDService._node_names(user_nodes).items()
                if name in by_name}

    @staticmethod
    def _mesh_bones(triangles_data: List[Tuple[str, List[str]]]) -> set:
        """Номера костей, которые меш действительно использует."""
        used: set = set()
        for _material, lines in triangles_data or ():
            for line in lines:
                parts = line.split()
                if len(parts) < 9:
                    continue
                try:
                    used.add(int(parts[0]))
                    count = int(parts[9]) if len(parts) > 9 else 0
                    for k in range(count):
                        used.add(int(parts[10 + k * 2]))
                except (ValueError, IndexError):
                    continue
        return used

    @staticmethod
    def _grip_bone(nodes_lines: Optional[List[str]],
                   triangles_data: List[Tuple[str, List[str]]]) -> int:
        """Кость, за которую оружие держат. -1 — определить нечем.

        На неё садятся вершины, чью кость по имени не опознали: у модели
        «только геометрия» кость обычно одна и зовётся `root`. Берётся самая
        ВЕРХНЯЯ из костей меша, названных по-хватовому (`weapon_bone`,
        `weapon_bone_L` у медигана, `vm_weapon_bone` у кулаков); если таких
        нет — просто самая верхняя из используемых.

        Ни номер ноль, ни «самая нагруженная» не годятся: нулевой у медигана
        `weapon_bone_L`, а у Фалломорфера узел по имени модели, который к руке
        не крепится вовсе; больше всего вершин у минигана несёт вращающийся
        `barrel`, а у Святой макрели — `jiggle3`.
        """
        names, parents = {}, {}
        for line in nodes_lines or ():
            m = _NODE_RE.match(line)
            if m:
                bone = int(m.group(1))
                names[bone] = m.group(2)
                parents[bone] = int(m.group(3))
        used = SMDService._mesh_bones(triangles_data) & set(names)
        if not used:
            used = set(names)
        if not used:
            return -1

        def depth(bone: int) -> int:
            steps, seen = 0, set()
            while bone in parents and parents[bone] >= 0 and bone not in seen:
                seen.add(bone)
                bone = parents[bone]
                steps += 1
            return steps

        grips = {b for b in used if names[b].startswith(_GRIP_PREFIXES)}
        return min(grips or used, key=lambda b: (depth(b), b))

    @staticmethod
    def _remap_vertex_line(line: str, mapping: Dict[int, int],
                           fallback: int) -> str:
        """Переписывает номера костей в строке вершины на игровые."""
        parts = line.split()
        if len(parts) < 9:
            return line
        tail = "\n" if line.endswith("\n") else ""

        def swap(raw: str) -> str:
            try:
                bone = int(raw)
            except ValueError:
                return raw
            if bone in mapping:
                return str(mapping[bone])
            return str(fallback) if fallback >= 0 else raw

        parts[0] = swap(parts[0])
        try:
            count = int(parts[9]) if len(parts) > 9 else 0
        except ValueError:
            count = 0
        for k in range(count):
            idx = 10 + k * 2
            if idx < len(parts):
                parts[idx] = swap(parts[idx])
        return " ".join(parts) + tail

    @staticmethod
    def _write_merged_triangles(
        out,
        user_triangles_data: List[Tuple[str, List[str]]],
        original_material_names: List[str],
        progress_cb: Optional[Callable[[int], None]] = None,
        pct_start: int = 80,
        pct_end: int = 100,
        bone_mapping: Optional[Dict[int, int]] = None,
        fallback_bone: int = -1,
    ) -> None:
        """
        Записывает секцию triangles прямо в открытый файл.

        Геометрия — из user_triangles_data, имена материалов — из
        original_material_names, номера костей — переписаны по именам
        (`bone_mapping`, см. `_bone_mapping`). Без отображения строки идут как
        есть.
        """
        if not user_triangles_data:
            out.write('triangles')
            return

        out.write('triangles\n')
        n_orig = len(original_material_names)
        n_total = max(1, len(user_triangles_data))

        for idx, (user_mat, tri_lines) in enumerate(user_triangles_data):
            mat = (
                original_material_names[idx] if idx < n_orig else original_material_names[-1]
            ) if n_orig > 0 else SMDService._sanitize_material_name(user_mat)
            # keep_user_materials (n_orig==0): имя материала меша нормализуется
            # (lowercase + точки→'_'). studiomdl трактует имя материала как файл и
            # ОБРЕЗАЕТ всё после первой точки: 'material.001' → 'material',
            # 'material.001_bloody' → 'material' → оба скина схлопываются, группа
            # выбрасывается → текстура не находится (фиолет). Точку убираем.

            out.write(mat)
            out.write('\n')
            if bone_mapping:
                out.writelines(
                    SMDService._remap_vertex_line(line, bone_mapping, fallback_bone)
                    for line in tri_lines
                )
            else:
                out.writelines(tri_lines)

            if progress_cb:
                ratio = (idx + 1) / n_total
                progress_cb(pct_start + int(ratio * (pct_end - pct_start)))

        out.write('end\n')

    # ------------------------------------------------------------------
    # Поиск reference SMD
    # ------------------------------------------------------------------

    @staticmethod
    def find_reference_smd(decompile_dir: str, weapon_key: str) -> Optional[str]:
        """Ищет reference SMD файл (оригинальная модель из игры)."""
        if not os.path.exists(decompile_dir):
            return None

        # Приоритет: стандартные имена
        for name in (f"{weapon_key}_reference.smd", f"{weapon_key}.smd"):
            fp = os.path.join(decompile_dir, name)
            if os.path.exists(fp):
                return fp

        wk_low = weapon_key.lower()

        # Имя содержит "reference" и weapon_key
        for fn in os.listdir(decompile_dir):
            if (fn.endswith('.smd') and
                    'reference' in fn.lower() and
                    wk_low in fn.lower()):
                return os.path.join(decompile_dir, fn)

        # Любой SMD с weapon_key, не physics/anim
        for fn in os.listdir(decompile_dir):
            fn_low = fn.lower()
            if (fn.endswith('.smd') and
                    'physics' not in fn_low and
                    'anim' not in fn_low and
                    'anims' not in fn_low and
                    wk_low in fn_low):
                return os.path.join(decompile_dir, fn)

        return None

    @staticmethod
    def extract_unique_materials(smd_path: str) -> set:
        """
        Извлекает уникальные имена материалов/текстур из SMD файла.

        В секции triangles каждый треугольник начинается со строки с названием
        материала, за которой следуют ровно 3 строки вершин (начинаются с цифры
        или '-'). Метод собирает все уникальные названия материалов.

        Args:
            smd_path: Путь к SMD файлу.

        Returns:
            Множество (set) уникальных имён материалов.
        """
        materials: set = set()
        if not os.path.exists(smd_path):
            return materials

        in_triangles = False
        with open(smd_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if not in_triangles:
                    if s == 'triangles':
                        in_triangles = True
                    continue
                if s == 'end':
                    break
                first = s[0]
                # Строки вершин начинаются с цифры или '-'
                if first.isdigit() or first == '-':
                    continue
                # Всё остальное — имя материала
                materials.add(s)

        return materials

    @staticmethod
    def _sanitize_material_name(name: str) -> str:
        """
        Нормализует имя материала под Source/studiomdl.

        • lowercase — Source ищет пути материалов в нижнем регистре;
        • точки → '_' — studiomdl трактует имя как файл и обрезает всё после
          первой точки ('material.001' → 'material'), что ломает скины и текстуры.
        """
        return (name or '').strip().lower().replace('.', '_')

    @staticmethod
    def ordered_unique_materials(smd_path: str) -> List[str]:
        """
        Имена материалов SMD в порядке первого появления (уникальные).

        Это «источник истины» для сборки: модель компилируется именно с этими
        именами, поэтому имена VTF/VMT, $texturegroup и $basetexture должны им
        соответствовать (иначе текстура не находится — фиолетовая).
        """
        result: List[str] = []
        seen = set()
        if not os.path.exists(smd_path):
            return result
        in_triangles = False
        with open(smd_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if not in_triangles:
                    if s == 'triangles':
                        in_triangles = True
                    continue
                if s == 'end':
                    break
                if s[0].isdigit() or s[0] == '-':
                    continue
                if s not in seen:
                    seen.add(s)
                    result.append(s)
        return result

    @staticmethod
    def rename_materials_in_smd(smd_path: str, rename_map: dict) -> int:
        """
        Переименовывает материалы в секции triangles SMD (привязка меша).

        Нужно для изоляции: studiomdl берёт имена материалов skin 0 из самого SMD,
        поэтому чтобы модель ссылалась на новый материал (vm_engineer_red),
        переименование надо сделать здесь, а не только в $texturegroup.

        rename_map: {orig_lower: new_name}. Сопоставление без учёта регистра.
        Возвращает число заменённых строк-материалов.
        """
        if not os.path.exists(smd_path) or not rename_map:
            return 0
        rm = {k.lower(): v for k, v in rename_map.items()}
        out_lines: List[str] = []
        in_triangles = False
        changed = 0
        with open(smd_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if not in_triangles:
                    out_lines.append(line)
                    if s == 'triangles':
                        in_triangles = True
                    continue
                if s == 'end':
                    in_triangles = False
                    out_lines.append(line)
                    continue
                # Строка материала — не вершина (не начинается с цифры/'-') и не пустая.
                if s and not (s[0].isdigit() or s[0] == '-') and s.lower() in rm:
                    nl = line.replace(s, rm[s.lower()], 1)
                    out_lines.append(nl)
                    changed += 1
                else:
                    out_lines.append(line)
        if changed:
            with open(smd_path, 'w', encoding='utf-8') as f:
                f.writelines(out_lines)
        return changed


# ---------------------------------------------------------------------------
# Backward-compat aliases (используются тестами)
# ---------------------------------------------------------------------------

# Добавляем как методы класса после определения класса
def _parse_smd_file_compat(content: str) -> dict:
    return SMDService._parse_smd_lines(content.splitlines(keepends=True))


def _merge_triangles_compat(user_triangles_data: list, original_material_names: list) -> str:
    import io
    buf = io.StringIO()
    SMDService._write_merged_triangles(buf, user_triangles_data, original_material_names)
    return buf.getvalue().rstrip('\n')


SMDService._parse_smd_file = staticmethod(_parse_smd_file_compat)
SMDService._merge_triangles = staticmethod(_merge_triangles_compat)


# ---------------------------------------------------------------------------
# Вспомогательные функции (модульный уровень)
# ---------------------------------------------------------------------------

def _wlines(f, lines) -> None:
    """Записывает список строк в файл. Игнорирует None."""
    if lines:
        f.writelines(lines)
        # Гарантируем перенос строки после секции
        if lines and not lines[-1].endswith('\n'):
            f.write('\n')
