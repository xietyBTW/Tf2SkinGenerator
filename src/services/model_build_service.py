"""
Сервис для декомпила и компила моделей TF2.
Вся хуйня с Crowbar, studiomdl, QC файлами и прочей ебаниной.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
from src.shared.logging_config import get_logger
from src.shared.file_utils import ensure_directory_exists

# Предкомпилированные regex — создаются один раз при импорте модуля
_RE_LOD          = re.compile(r'^\$lod\s+\d+',                     re.IGNORECASE)
_RE_CDMATERIALS  = re.compile(r'^\$cdmaterials\s*"([^"]*)"',        re.IGNORECASE)
_RE_CDMAT_DETECT = re.compile(r'^\$cdmaterials\s+',                  re.IGNORECASE)
_RE_MODELNAME    = re.compile(r'\$modelname\s+"([^"]+)"',             re.IGNORECASE)
_RE_TEXGROUP     = re.compile(r'^\$texturegroup\s+',                  re.IGNORECASE)
_RE_STUDIO_SMD   = re.compile(r'studio\s+"([^"]+\.smd)"',             re.IGNORECASE)

logger = get_logger(__name__)


class ModelBuildService:
    """Вся хуйня с декомпилом и компилом моделей. Crowbar для декомпила, studiomdl для компила. Без них - никак."""
    
    @staticmethod
    def decompile(
        mdl_path: str,
        out_dir: str,
        crowbar_decomp_exe: str
    ) -> str:
        """
        Декомпилирует .mdl в QC через Crowbar.
        
        Без Crowbar - хуй че получится, studiomdl не умеет обратно из MDL делать QC.
        Это единственный способ получить QC из готовой модели.
        
        Args:
            mdl_path: Путь к .mdl файлу
            out_dir: Куда складывать результат
            qc_path: Не используется, оставлен для совместимости (legacy код)
            
        Returns:
            Путь к созданному QC файлу
            
        Raises:
            RuntimeError: Если Crowbar вернул ошибку (обычно значит что-то не так с моделью)
        """
        if not os.path.exists(mdl_path):
            raise FileNotFoundError(f"MDL file not found: {mdl_path}")

        if not os.path.exists(crowbar_decomp_exe):
            raise FileNotFoundError(f"Crowbar decompile exe not found: {crowbar_decomp_exe}")
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Запускаем Crowbar. Формат команды может отличаться в зависимости от версии, но обычно работает так
        result = subprocess.run(
            [
                os.path.abspath(crowbar_decomp_exe),
                "-p", os.path.abspath(mdl_path),
                "-o", os.path.abspath(out_dir)
            ],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(crowbar_decomp_exe),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        
        if result.returncode != 0:
            raise RuntimeError(
                f"Decompilation failed:\n"
                f"Command: {' '.join([crowbar_decomp_exe, '-p', mdl_path, '-o', out_dir])}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        # Ищем созданный QC файл. Crowbar обычно создает с именем модели, но не всегда (потому что Crowbar)
        mdl_basename = os.path.splitext(os.path.basename(mdl_path))[0]
        qc_path = os.path.join(out_dir, f"{mdl_basename}.qc")
        
        # Если не нашли по стандартному имени - ищем любой .qc в директории (костыль на случай если Crowbar назвал по-другому)
        if not os.path.exists(qc_path):
            for file in os.listdir(out_dir):
                if file.endswith(".qc"):
                    qc_path = os.path.join(out_dir, file)
                    break
        
        if not os.path.exists(qc_path):
            raise RuntimeError(
                f"QC file not found after decompile in {out_dir}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        return qc_path
    
    @staticmethod
    def extract_cdmaterials_path_from_qc(qc_path: str) -> Optional[str]:
        """
        Вытаскивает путь из первой непустой строки $cdmaterials.
        
        В QC может быть куча $cdmaterials (включая пустые), нам нужен тот где реально указан путь.
        Пропускаем пустые, ищем первый непустой.
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Путь из $cdmaterials или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Ищем первую непустую $cdmaterials без относительных переходов (..)
        # Пути вида "console\..\..\effects" — это системные папки движка (глаза, эффекты),
        # а не папки скинов модели. Их пропускаем — нам нужен путь к текстурам тела.
        for line in lines:
            stripped = line.strip()
            if re.match(r'\$cdmaterials\s+', stripped, re.IGNORECASE):
                path_match = re.search(r'\$cdmaterials\s*"([^"]*)"', line, re.IGNORECASE)
                if path_match:
                    path = path_match.group(1)
                    if path.strip() and '..' not in path:
                        return path

        return None
    
    @staticmethod
    def extract_all_cdmaterials_paths_from_qc(qc_path: str) -> list:
        """
        Возвращает ВСЕ непустые пути $cdmaterials из QC файла в порядке появления.

        Crowbar добавляет префикс ``console\\`` и иногда включает пути вида
        ``console\\..\\..\\effects`` (для частиц — не текстуры). Эта функция
        возвращает сырые значения; нормализацию (стрип console/, пропуск ..)
        делает потребитель.

        Args:
            qc_path: Путь к QC файлу

        Returns:
            Список непустых путей из всех $cdmaterials (может быть пустым).
        """
        if not os.path.exists(qc_path):
            return []

        result = []
        with open(qc_path, 'r', encoding='utf-8') as f:
            for line in f:
                if re.match(r'\s*\$cdmaterials\s+', line, re.IGNORECASE):
                    m = re.search(r'\$cdmaterials\s*"([^"]*)"', line, re.IGNORECASE)
                    if m:
                        path = m.group(1).strip()
                        if path:
                            result.append(path)
        return result

    @staticmethod
    def extract_modelname_path(qc_path: str) -> Optional[str]:
        """
        Вытаскивает путь из $modelname в QC файле.
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Путь из $modelname (например, "weapons/c_models/c_bonesaw/c_bonesaw.mdl") или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ищем $modelname с путем
        pattern = r'\$modelname\s+"([^"]+)"'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None
    
    @staticmethod
    def extract_texturegroup_filename(qc_path: str) -> Optional[str]:
        """
        Вытаскивает имя файла из $texturegroup.
        
        В $texturegroup может быть куча вариантов (обычный, золотой, странный и т.д.), 
        а нам нужен базовый без суффиксов типа _gold, _xmas. Выбираем самое простое.
        
        Формат:
        $texturegroup "skinfamilies"
        {
            { "c_scattergun"      "c_scattergun_gold" }
            ...
        }
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Имя файла (например, "c_scattergun") или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Ищем $texturegroup
            if re.match(r'\$texturegroup\s+', stripped, re.IGNORECASE):
                i += 1
                
                # Пропускаем пустые строки и комментарии (мусор)
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                    i += 1
                
                # Ищем открывающую скобку
                if i < len(lines) and lines[i].strip().startswith('{'):
                    i += 1
                    
                    # Снова пропускаем мусор
                    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                        i += 1
                    
                    # Собираем все имена из блока (может быть несколько вариантов)
                    all_names = []
                    brace_count = 0
                    start_reading = False
                    
                    while i < len(lines):
                        current_line = lines[i]
                        stripped_current = current_line.strip()
                        
                        # Если встретили закрывающую скобку - выходим
                        if stripped_current == '}':
                            break
                        
                        # Вытаскиваем все имена в кавычках из строки (формат: { "имя1" "имя2" } или { "имя" })
                        matches = re.findall(r'"([^"]+)"', current_line)
                        for name in matches:
                            if name.strip():  # Пустые игнорируем
                                all_names.append(name.strip())
                        
                        i += 1
                    
                    # Если нашли имена - выбираем самое простое без суффиксов (_gold, _xmas и т.д.)
                    if all_names:
                        # Список суффиксов которые нужно отфильтровать (варианты оружия, нам нужен базовый)
                        suffixes_to_avoid = ['_gold', '_xmas', '_festive', '_australium', '_botkiller', '_strange', '_unusual']
                        
                        # Ищем имя без суффиксов (базовое имя текстуры)
                        simple_name = None
                        for name in all_names:
                            has_suffix = any(name.endswith(suffix) for suffix in suffixes_to_avoid)
                            if not has_suffix:
                                simple_name = name
                                break
                        
                        # Если не нашли без суффиксов - берем первое (fallback, хотя такое маловероятно)
                        if simple_name:
                            return simple_name
                        else:
                            return all_names[0]
            
            i += 1
        
        return None
    
    @staticmethod
    def extract_texturegroup_all_columns(qc_path: str) -> List[str]:
        """
        Вытаскивает ВСЕ столбцы из базовой строки (RED) $texturegroup.
        
        В TF2 QC файлах $texturegroup содержит СТРОКИ (skin families):
        - Строка 0 (row 0): RED команда
        - Строка 1 (row 1): BLU команда (если есть)
        - Строки 2+: gold, festive и другие варианты
        
        И СТОЛБЦЫ (разные материалы на модели):
        - Столбец 0: основная текстура (body)
        - Столбец 1+: дополнительные текстуры (shell, scope и т.д.)
        
        Формат:
        $texturegroup "skinfamilies"
        {
            { "c_flaregun"      "c_flaregun_shell" }         // RED: body + shell
            { "c_flaregun_blue" "c_flaregun_shell_blue" }    // BLU: body + shell
        }
        
        Метод возвращает все столбцы из RED строки (базовой строки без суффиксов).
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Список имен текстур из RED строки (например, ["c_flaregun", "c_flaregun_shell"])
            Пустой список если $texturegroup не найден
        """
        info = ModelBuildService.extract_texturegroup_structure(qc_path)
        return info.get('red_row', [])
    
    @staticmethod
    def _parse_texturegroup_rows(qc_path: str) -> List[List[str]]:
        """
        Парсит строки-скины из $texturegroup в QC файле.

        Каждый скин — это внутренний блок `{ ... }`, который МОЖЕТ занимать
        несколько строк (studiomdl/Crowbar часто пишут каждый материал на своей
        строке). Поэтому парсим по фигурным скобкам, а не построчно — иначе одна
        строка-скин из N материалов ошибочно превращается в N «скинов».

        Returns:
            Список скинов, каждый скин — список имён материалов.
        """
        if not os.path.exists(qc_path):
            return []

        try:
            with open(qc_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            return []

        # Находим начало блока $texturegroup и его открывающую скобку.
        m = re.search(r'(?im)^[ \t]*\$texturegroup\b', content)
        if not m:
            return []
        outer_open = content.find('{', m.end())
        if outer_open == -1:
            return []

        # Находим закрывающую скобку всего блока (учёт вложенности).
        depth = 0
        outer_close = None
        for i in range(outer_open, len(content)):
            c = content[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    outer_close = i
                    break
        if outer_close is None:
            return []

        inner = content[outer_open + 1:outer_close]

        # Каждый внутренний { ... } — один скин (может быть многострочным).
        rows: List[List[str]] = []
        for grp in re.finditer(r'\{([^{}]*)\}', inner, re.DOTALL):
            names = [n.strip() for n in re.findall(r'"([^"]+)"', grp.group(1)) if n.strip()]
            if names:
                rows.append(names)
        return rows
    
    @staticmethod
    def extract_texturegroup_structure(qc_path: str) -> dict:
        """
        Анализирует $texturegroup и возвращает структурированную информацию
        о текстурах для RED/BLU команд и дополнительных материалах.
        
        В TF2:
        - СТРОКИ (rows) = skin families (RED, BLU, gold, festive...)
        - СТОЛБЦЫ (columns) = разные материалы модели (body, shell, scope...)
        
        Пример QC:
        $texturegroup "skinfamilies"
        {
            { "c_flaregun"      "c_flaregun_shell" }         // RED row: body + shell
            { "c_flaregun_blue" "c_flaregun_shell_blue" }    // BLU row: body + shell
            { "c_flaregun_gold" "c_flaregun_shell_gold" }    // Gold variant
        }
        
        Returns:
            {
                'red_row': ['c_flaregun', 'c_flaregun_shell'],          # RED материалы
                'blu_row': ['c_flaregun_blue', 'c_flaregun_shell_blue'],# BLU материалы (пустой если нет)
                'main_texture': 'c_flaregun',                           # Главная текстура (col 0 RED)
                'extra_materials': ['c_flaregun_shell'],                # Доп. материалы RED (col 1+)
                'all_rows': [...]                                        # Все строки
            }
        """
        rows = ModelBuildService._parse_texturegroup_rows(qc_path)
        
        result = {
            'red_row': [],
            'blu_row': [],
            'main_texture': None,
            'extra_materials': [],
            'all_rows': rows,
        }
        
        if not rows:
            return result
        
        # Суффиксы вариантов которые нужно пропускать при поиске базовых строк
        variant_suffixes = ['_gold', '_xmas', '_festive', '_australium', '_botkiller', '_strange', '_unusual']
        
        # Находим "базовые" строки — те, у которых первый столбец не имеет суффиксов вариантов
        base_rows = []
        for row in rows:
            first_name = row[0]
            has_variant_suffix = any(first_name.endswith(suffix) for suffix in variant_suffixes)
            if not has_variant_suffix:
                base_rows.append(row)
        
        # Если ни одна строка не "базовая" (все с суффиксами) — берем все строки как базовые
        if not base_rows:
            base_rows = rows[:]
        
        # Первая базовая строка = RED
        result['red_row'] = base_rows[0]
        result['main_texture'] = base_rows[0][0]
        
        # Ищем BLU строку: вторая базовая строка (если есть)
        # В TF2 BLU обычно идет сразу после RED
        blu_row_raw = base_rows[1] if len(base_rows) > 1 else []
        
        # НЕ дедуплицируем BLU строку — сохраняем column alignment с RED строкой.
        # Важно для моделей персонажей (medic, scout…) где Valve повторяет текстуры
        # в нескольких колонках для нужд шейдеров (eyeball, invulnfx и т.п.):
        #   RED col5=medic_blue, BLU col5=medic_blue → shared → обработается автоматически.
        # Дублирующиеся VTF не создаются дважды благодаря exists()-проверкам в цикле BLU.
        result['blu_row'] = blu_row_raw

        # extra_materials = столбцы RED строки начиная с col 1, НО без тех что уже есть в BLU строке.
        # Проблема: Valve иногда пишет ВСЕ скины в одну RED строку:
        #   { "c_flaregun" "c_flaregun_shell" "c_flaregun_blue" "c_flaregun_shell_blue" }
        # В этом случае "c_flaregun_blue" и "c_flaregun_shell_blue" — это BLU варианты, а не extra_materials.
        # Они обрабатываются в BLU loop, поэтому из extra_materials их нужно исключить.
        # Используем set() из уникальных имён BLU строки для фильтрации.
        blu_names_set = set(blu_row_raw)
        extra_raw = base_rows[0][1:] if len(base_rows[0]) > 1 else []
        result['extra_materials'] = [m for m in extra_raw if m not in blu_names_set]

        return result

    @staticmethod
    def generate_texturegroup_block(mesh_materials: List[str],
                                    skin_overrides: dict) -> str:
        """
        Генерирует блок $texturegroup "skinfamilies" из материалов меша и
        переопределений по скинам.

        Args:
            mesh_materials: имена материалов меша (порядок = skin 0, базовые имена).
            skin_overrides: {skin_index(int>=1): {material_name: variant_texture_name}}.
                            Только материалы, которые пользователь сделал РАЗНЫМИ
                            в этом скине. Остальные наследуют базовое имя.

        Правила Source:
          • в группу попадают ТОЛЬКО переменные материалы (переопределённые хоть в
            одном скине); постоянные не пишутся вообще;
          • во всех строках одинаковые столбцы, в порядке mesh_materials;
          • skin 0 = базовые имена; skin K = вариант (если есть) или базовое имя.

        Returns:
            Текст блока $texturegroup (с переводом строки) или '' если вариантов нет
            (тогда группа не нужна — модель одно-скиновая).
        """
        if not skin_overrides:
            return ''

        # Переменные материалы — те, что переопределены хотя бы в одном скине.
        # Сохраняем порядок mesh_materials (важно для выравнивания столбцов).
        overridden = set()
        for ov in skin_overrides.values():
            overridden.update(ov.keys())
        variant_mats = [m for m in mesh_materials if m in overridden]
        if not variant_mats:
            return ''

        n_skins = 1 + max(skin_overrides.keys())

        lines = ['$texturegroup "skinfamilies"', '{']
        for skin in range(n_skins):
            ov = skin_overrides.get(skin, {})
            names = []
            for mat in variant_mats:
                # skin 0 — всегда базовое имя; иначе вариант или базовое (наследование)
                names.append(mat if skin == 0 else ov.get(mat, mat))
            row = ' '.join(f'"{n}"' for n in names)
            lines.append(f'\t{{ {row} }}')
        lines.append('}')
        return '\n'.join(lines) + '\n'

    # Суффиксы строк-вариантов (австралий/голд/festive и т.п.) — это НЕ обычные
    # скины-стили, а отдельные «варианты»; считаем их отдельно.
    _VARIANT_SUFFIXES = ('_gold', '_australium', '_botkiller', '_strange',
                         '_unusual', '_festive', '_xmas')

    @staticmethod
    def _skin_role_label(row: List[str], idx: int) -> str:
        """Дружелюбная подпись скина по суффиксу его текстуры (иначе 'Skin N')."""
        if idx == 0:
            return 'Skin 0'
        name = (row[0] if row else '').lower()
        friendly = {'_bloody': 'Bloody', '_clean': 'Clean', '_dirty': 'Dirty'}
        for suf, label in friendly.items():
            if name.endswith(suf):
                return label
        return f'Skin {idx}'

    @staticmethod
    def extract_skin_info(qc_path: str) -> dict:
        """
        Читает $texturegroup игрового QC и возвращает инфу о скинах — для UI
        (вкладки) и генерации. ОТДЕЛЬНАЯ новая функция: существующую логику
        (extract_texturegroup_structure / RED-BLU) НЕ трогает.

        Returns:
            {
              'num_skins': int,        # число базовых строк-скинов (0/1 = без стилей)
              'roles': [str, ...],     # подпись каждого скина (RED/BLU или Skin N)
              'is_team': bool,         # row1 = команда (суффикс _blue/_blu)
              'has_australium': bool,  # присутствует строка-вариант (_gold и т.п.)
              'rows': [[...], ...],    # сырые строки группы
            }
        """
        rows = ModelBuildService._parse_texturegroup_rows(qc_path)
        info = {'num_skins': len(rows), 'roles': [], 'is_team': False,
                'has_australium': False, 'rows': rows}
        if not rows:
            return info

        sufx = ModelBuildService._VARIANT_SUFFIXES
        info['has_australium'] = any(
            r and any(r[0].lower().endswith(s) for s in sufx) for r in rows
        )
        # Базовые строки (без variant-суффикса в первом материале)
        base_rows = [r for r in rows if r and not any(r[0].lower().endswith(s) for s in sufx)]
        if not base_rows:
            base_rows = rows

        # Дедуп идентичных строк. TF2 часто ПАДДИТ skinfamilies одинаковыми
        # строками, чтобы разные индексы скина (обычный/странный/фестив/килстрик)
        # давали один и тот же вид — это НЕ разные стили. Схлопываем их в один.
        seen = set()
        unique_rows = []
        for r in base_rows:
            key = tuple(x.lower() for x in r)
            if key not in seen:
                seen.add(key)
                unique_rows.append(r)
        base_rows = unique_rows
        n = len(base_rows)
        info['num_skins'] = n

        # Детект команды: row1[0] == row0[0] + _blue/_blu
        is_team = False
        if n >= 2 and base_rows[0] and base_rows[1]:
            b0 = base_rows[0][0].lower()
            b1 = base_rows[1][0].lower()
            is_team = b1 in (b0 + '_blue', b0 + '_blu')
        info['is_team'] = is_team

        if n <= 1:
            info['roles'] = ['Skin 0'] if n == 1 else []
        elif is_team:
            info['roles'] = ['RED', 'BLU'] + [f'Skin {i}' for i in range(2, n)]
        else:
            info['roles'] = [ModelBuildService._skin_role_label(base_rows[i], i) for i in range(n)]
        return info

    @staticmethod
    def _strip_texturegroup(content: str) -> str:
        """Удаляет блок $texturegroup { ... } из текста QC (с учётом вложенности)."""
        m = re.search(r'(?im)^[ \t]*\$texturegroup\b', content)
        if not m:
            return content
        brace = content.find('{', m.end())
        if brace == -1:
            return content
        depth = 0
        end = None
        for i in range(brace, len(content)):
            if content[i] == '{':
                depth += 1
            elif content[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            return content
        start = content.rfind('\n', 0, m.start()) + 1
        tail = end + 1
        if tail < len(content) and content[tail] == '\n':
            tail += 1
        return content[:start] + content[tail:]

    @staticmethod
    def replace_texturegroup_in_qc(qc_path: str, new_block: str) -> bool:
        """
        Заменяет $texturegroup в QC на сгенерированный (или удаляет, если new_block пуст).

        Только для КАСТОМНЫХ моделей: исходная группа ссылается на игровые имена
        материалов, которых нет в меше пользователя — её надо убрать/заменить,
        иначе studiomdl ругается на висящие материалы. Пустой new_block → модель
        одно-скиновая (без группы, что валидно).

        Returns True, если файл изменён.
        """
        if not os.path.exists(qc_path):
            return False
        with open(qc_path, 'r', encoding='utf-8') as f:
            content = f.read()

        content = ModelBuildService._strip_texturegroup(content)

        if new_block and new_block.strip():
            # Вставляем после $modelname (texturegroup должен идти после $body/$model)
            m = re.search(r'(?im)^[ \t]*\$modelname\b.*$', content)
            if m:
                insert_at = m.end()
                content = content[:insert_at] + '\n\n' + new_block.rstrip() + '\n' + content[insert_at:]
            else:
                content = new_block.rstrip() + '\n' + content

        with open(qc_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True

    @staticmethod
    def determine_weapon_type_and_path(weapon_key: str, cdmaterials_path: Optional[str]) -> Tuple[str, str]:
        """
        Определяет тип оружия (v_ или c_) и правильный путь для $cdmaterials.
        
        К исходному пути добавляется префикс vgui\replay\thumbnails\ - это костыль для работы в TF2,
        потому что текстуры должны лежать в этой структуре для загрузки через консольные команды.
        Без этого префикса текстуры не загрузятся, потому что Source Engine - ебанутый.
        
        Args:
            weapon_key: Ключ оружия (например, c_shogun_kunai или v_machete)
            cdmaterials_path: Путь из $cdmaterials в QC файле (опционально)
            
        Returns:
            Tuple[weapon_type, cdmaterials_path]
            weapon_type: 'v' или 'c'
            cdmaterials_path: Путь для $cdmaterials с добавленным префиксом vgui\replay\thumbnails\
        """
        # Префикс - костыль для работы в TF2, без него текстуры не загрузятся
        prefix = 'vgui\\replay\\thumbnails\\'
        
        # Сначала пытаемся определить тип по исходному пути из QC (если путь есть)
        if cdmaterials_path:
            # Нормализуем путь (QC использует обратные слеши, сохраняем их)
            normalized_path = cdmaterials_path.strip().rstrip('\\').rstrip('/')
            
            # Если путь уже содержит префикс - не дублируем
            if normalized_path.lower().startswith('vgui\\replay\\thumbnails\\') or normalized_path.lower().startswith('vgui/replay/thumbnails/'):
                cdmaterials_new_path = normalized_path.replace('/', '\\')
            else:
                # Добавляем префикс, убираем лишние слеши
                if normalized_path.startswith('\\') or normalized_path.startswith('/'):
                    cdmaterials_new_path = prefix + normalized_path.lstrip('\\').lstrip('/')
                else:
                    cdmaterials_new_path = prefix + normalized_path
            
            # Нормализуем слеши для определения типа (используем прямые для проверки)
            normalized_for_check = normalized_path.replace('\\', '/').strip().rstrip('/')
            path_parts = normalized_for_check.split('/')
            last_part = path_parts[-1] if path_parts else ""
            
            # Определяем тип оружия (v_ - viewmodel, c_ - worldmodel)
            if last_part.startswith('v_'):
                weapon_type = 'v'
            elif 'c_models' in normalized_for_check or 'c_items' in normalized_for_check:
                weapon_type = 'c'
            else:
                # Если не удалось определить по пути - определяем по weapon_key (fallback)
                weapon_type = 'v' if weapon_key.startswith('v_') else 'c'
            
            return weapon_type, cdmaterials_new_path
        
        # Если исходный путь не предоставлен - определяем по weapon_key (fallback)
        if weapon_key.startswith('v_'):
            weapon_type = 'v'
            # Для v_ оружия - каждое в своей папке
            weapon_name = weapon_key
            cdmaterials_new_path = f'{prefix}models\\workshop_partner\\weapons\\{weapon_name}\\'
        else:
            weapon_type = 'c'
            # Для c_ оружия - все в одной папке c_models
            cdmaterials_new_path = f'{prefix}models\\workshop_partner\\weapons\\c_models\\'
        
        return weapon_type, cdmaterials_new_path
    
    @staticmethod
    def extract_extra_body_smds(qc_path: str, weapon_key: str) -> List[str]:
        """
        Находит дополнительные SMD файлы (bodygroup) в QC файле.
        
        При декомпиляции MDL через Crowbar получаются несколько SMD:
        - Основной: c_flaregun_reference.smd (основное тело оружия)
        - Дополнительные: c_flaregun_shell.smd, c_flaregun_scope.smd и т.д.
        
        В QC файле они указаны в $body и $bodygroup:
        $body studio "c_flaregun_reference.smd"
        $bodygroup "shell"
        {
            studio "c_flaregun_shell.smd"
            blank
        }
        
        Метод возвращает пути к дополнительным SMD (не основному body).
        
        Args:
            qc_path: Путь к QC файлу
            weapon_key: Ключ оружия (для определения основного SMD)
            
        Returns:
            Список путей к дополнительным SMD файлам (абсолютные пути)
        """
        if not os.path.exists(qc_path):
            return []
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        qc_dir = os.path.dirname(qc_path)
        
        # Находим ВСЕ studio ссылки на SMD файлы в QC
        # Формат: studio "имя_файла.smd" или $body studio "имя_файла.smd"
        all_smd_refs = re.findall(r'studio\s+"([^"]+\.smd)"', content, re.IGNORECASE)
        
        if not all_smd_refs:
            return []
        
        # Определяем основной SMD (reference) - это тот, который содержит weapon_key
        # и/или имеет "_reference" в названии
        main_smd_name = None
        for smd_ref in all_smd_refs:
            smd_base = os.path.splitext(os.path.basename(smd_ref))[0].lower()
            wk_lower = weapon_key.lower()
            
            # Основной SMD - первый, который:
            # 1. Содержит weapon_key + "_reference"
            # 2. Или просто совпадает с weapon_key
            if wk_lower + '_reference' == smd_base or wk_lower == smd_base:
                main_smd_name = smd_ref
                break
        
        # Если не нашли по точному совпадению - берем первый SMD с weapon_key в имени
        if not main_smd_name:
            for smd_ref in all_smd_refs:
                smd_base = os.path.basename(smd_ref).lower()
                if weapon_key.lower() in smd_base and 'reference' in smd_base:
                    main_smd_name = smd_ref
                    break
        
        # Если и так не нашли - первый SMD = основной
        if not main_smd_name and all_smd_refs:
            main_smd_name = all_smd_refs[0]
        
        # Все остальные SMD (не основной, не physics, не anim) = дополнительные
        extra_smds = []
        seen = set()
        for smd_ref in all_smd_refs:
            smd_lower = smd_ref.lower()
            
            # Пропускаем основной
            if smd_ref == main_smd_name:
                continue
            
            # Пропускаем physics и animation файлы
            if any(skip in smd_lower for skip in ['physics', 'phys', 'anim', 'idle', 'pose']):
                continue
            
            # Пропускаем дубли
            if smd_lower in seen:
                continue
            seen.add(smd_lower)
            
            # Проверяем что файл существует
            smd_full_path = os.path.join(qc_dir, smd_ref)
            if os.path.exists(smd_full_path):
                extra_smds.append(smd_full_path)
            else:
                logger.debug(f"Доп. SMD файл указан в QC, но не найден: {smd_full_path}")
        
        return extra_smds

    
    @staticmethod
    def extract_main_body_smd(qc_path: str, weapon_key: str) -> Optional[str]:
        """
        Возвращает абсолютный путь к основному reference-SMD, который QC передаёт компилятору.

        Читает директивы $body / studio из QC файла напрямую — это надёжнее поиска по
        имени файла (weapon_key), т.к. Crowbar может назвать SMD иначе чем мы ожидаем.

        Алгоритм выбора «основного» SMD (в порядке убывания приоритета):
          1. Первый studio-ссылка сразу после $body (однострочный формат).
          2. Первый studio-ссылка, содержащий weapon_key + "_reference".
          3. Первый studio-ссылка, содержащий weapon_key.
          4. Первый studio-ссылка с "_reference" в имени.
          5. Самый первый studio-ссылка в файле.

        Args:
            qc_path:    Путь к QC файлу (может быть не пропатчен).
            weapon_key: Ключ оружия / шапки (используется для приоритизации).

        Returns:
            Абсолютный путь к SMD-файлу или None если не найдено.
        """
        if not os.path.exists(qc_path):
            return None

        with open(qc_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        qc_dir = os.path.dirname(qc_path)
        wk_low = weapon_key.lower()

        # Все ссылки studio "*.smd" в порядке появления
        all_refs: List[str] = re.findall(r'studio\s+"([^"]+\.smd)"', content, re.IGNORECASE)
        if not all_refs:
            return None

        def _abs(ref: str) -> Optional[str]:
            p = os.path.join(qc_dir, ref)
            return p if os.path.exists(p) else None

        # Приоритет 1: $body … "ref.smd"  (строчный формат без bodygroup)
        body_inline = re.search(r'^\s*\$body\b[^"\n]*"([^"]+\.smd)"', content, re.IGNORECASE | re.MULTILINE)
        if body_inline:
            p = _abs(body_inline.group(1))
            if p:
                logger.debug(f"[MAIN BODY SMD] via $body inline: {p}")
                return p

        # Приоритет 2-5: перебираем все studio-ссылки
        found_wk_ref = found_wk = found_ref = found_first = None
        for ref in all_refs:
            base = os.path.splitext(os.path.basename(ref))[0].lower()
            if found_wk_ref is None and wk_low in base and 'reference' in base:
                found_wk_ref = ref
            if found_wk is None and wk_low in base:
                found_wk = ref
            if found_ref is None and 'reference' in base:
                found_ref = ref
            if found_first is None:
                found_first = ref

        for candidate in (found_wk_ref, found_wk, found_ref, found_first):
            if candidate:
                p = _abs(candidate)
                if p:
                    logger.debug(f"[MAIN BODY SMD] candidate={candidate!r} → {p}")
                    return p

        return None

    @staticmethod
    def patch_qc_file(qc_path: str, weapon_key: str, cdmaterials_path: Optional[str] = None) -> None:
        """
        Пропатчивает QC файл после декомпиляции.
        
        Нужно чтобы модель правильно компилировалась и текстуры загружались:
        - НЕ трогаем $modelname (оставляем как есть, путь модели должен быть правильным)
        - Добавляем префикс console\\ к $cdmaterials (чтобы текстуры загружались из консольных команд)
        - Удаляем все блоки $lod (LOD нам не нужны, только мусорят)
        
        Args:
            qc_path: Путь к QC файлу
            weapon_key: Не используется, оставлен для совместимости (legacy)
            cdmaterials_path: Не используется, оставлен для совместимости (legacy)
        """
        if not os.path.exists(qc_path):
            raise FileNotFoundError(f"QC file not found: {qc_path}")

        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines: List[str] = []
        # Индекс в new_lines ПОСЛЕ последнего записанного непустого $cdmaterials.
        # Туда вставим пустой $cdmaterials "" за один проход, без предварительного счёта.
        last_cdmat_insert_pos = -1
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # --- $lod блок: пропускаем целиком ---
            if _RE_LOD.match(stripped):
                i += 1
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                    i += 1
                if i < len(lines) and lines[i].strip().startswith('{'):
                    depth = 0
                    opened = False
                    while i < len(lines):
                        for ch in lines[i]:
                            if ch == '{':
                                depth += 1
                                opened = True
                            elif ch == '}':
                                depth -= 1
                        i += 1
                        if opened and depth == 0:
                            break
                    if i < len(lines) and not lines[i].strip():
                        i += 1
                continue

            # --- $cdmaterials ---
            if _RE_CDMAT_DETECT.match(stripped):
                m = _RE_CDMATERIALS.match(stripped)
                if m:
                    original_path = m.group(1)
                    if not original_path.strip():
                        i += 1
                        continue  # пустой путь — пропускаем

                    prefix = 'console\\'
                    lo = original_path.lower()
                    if lo.startswith('console\\') or lo.startswith('console/'):
                        modified_path = original_path.replace('/', '\\')
                    elif original_path.startswith(('\\', '/')):
                        modified_path = prefix + original_path.lstrip('\\/')
                    else:
                        modified_path = prefix + original_path

                    new_lines.append(f'$cdmaterials "{modified_path}"\n')
                    last_cdmat_insert_pos = len(new_lines)  # позиция после этой строки
                else:
                    i += 1
                    continue
                i += 1
                continue

            new_lines.append(line)
            i += 1

        # Вставляем пустой $cdmaterials "" сразу после последнего непустого
        if last_cdmat_insert_pos >= 0:
            new_lines.insert(last_cdmat_insert_pos, '$cdmaterials ""\n')

        with open(qc_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    
    @staticmethod
    def remove_lod_files(decompile_dir: str) -> None:
        """
        Удаляет все файлы с окончанием .lod<номер> из декомпилированной директории.
        
        LOD файлы - это уровни детализации, для скинов не нужны, только мусорят.
        
        Args:
            decompile_dir: Директория с декомпилированными файлами
        """
        if not os.path.exists(decompile_dir):
            return
        
        # Паттерн для файлов с .lod<номер> в названии
        lod_pattern = re.compile(r'\.lod\d+', re.IGNORECASE)
        
        removed_count = 0
        for file_name in os.listdir(decompile_dir):
            if lod_pattern.search(file_name):
                file_path = os.path.join(decompile_dir, file_name)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        removed_count += 1
                        logger.debug(f"Удален LOD файл: {file_name}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить LOD файл {file_name}: {e}", exc_info=True)
        
        if removed_count > 0:
            logger.info(f"Удалено LOD файлов: {removed_count}")
    
    @staticmethod
    def compile(
        qc_path: str,
        out_dir: str,
        studiomdl_exe: str,
        game_dir_or_gameinfo: str
    ) -> None:
        """
        Компилирует QC файл в .mdl через studiomdl.
        
        studiomdl - это официальный компилятор Source, без него никак.
        
        Args:
            qc_path: Путь к QC файлу
            out_dir: Директория для выходных файлов
            studiomdl_exe: Путь к studiomdl.exe
            game_dir_or_gameinfo: Путь к папке игры или gameinfo.txt
            
        Raises:
            RuntimeError: Если компил не удался (обычно значит что-то не так с QC или путями)
        """
        if not os.path.exists(qc_path):
            raise FileNotFoundError(f"QC file not found: {qc_path}")
        
        if not os.path.exists(studiomdl_exe):
            raise FileNotFoundError(f"studiomdl.exe not found: {studiomdl_exe}")
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Определяем это папка игры или gameinfo.txt
        if os.path.isdir(game_dir_or_gameinfo):
            game_arg = "-game"
        else:
            game_arg = "-gameinfo"
        
        cmd = [
            os.path.abspath(studiomdl_exe),
            game_arg, os.path.abspath(game_dir_or_gameinfo),
            "-nop4",
            "-nopack",
            "-quiet",           # Подавляем вывод прогресса — studiomdl тратит время на буферизацию stdout
            os.path.abspath(qc_path)
        ]
        
        # Запускаем без capture_output на happy path — быстрее, т.к. нет буферизации stdout/stderr
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(studiomdl_exe),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            # На ошибке — перезапускаем с захватом stdout для диагностики
            result2 = subprocess.run(
                [c for c in cmd if c != "-quiet"],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(studiomdl_exe),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            raise RuntimeError(
                f"Compilation failed:\n"
                f"Command: {' '.join([studiomdl_exe, game_arg, game_dir_or_gameinfo, '-nop4', '-nopack', qc_path])}\n"
                f"STDOUT: {result2.stdout}\n"
                f"STDERR: {result2.stderr}"
            )

        
        # Определяем базовое имя модели из $modelname в QC (переиспользуем уже загруженный метод)
        qc_basename = os.path.splitext(os.path.basename(qc_path))[0]
        modelname_path = ModelBuildService.extract_modelname_path(qc_path)
        if modelname_path:
            normalized_path = modelname_path.replace('\\', '/')
            modelname_path_parts = normalized_path.split('/')
            if modelname_path_parts:
                qc_basename = os.path.splitext(modelname_path_parts[-1])[0]
        
        # Определяем путь где studiomdl создал файлы
        # game_dir_or_gameinfo - это tf_dir (например, D:\Steam\steamapps\common\Team Fortress 2\tf)
        # studiomdl компилирует в: <tf_dir>/models/workshop_partner/weapons/c_models/<weapon_key>/
        if os.path.isdir(game_dir_or_gameinfo):
            tf_dir = game_dir_or_gameinfo
        else:
            # Если это gameinfo.txt - берем родительскую директорию
            tf_dir = os.path.dirname(game_dir_or_gameinfo)
        
        # Извлекаем weapon_key из пути модели
        # Путь: workshop_partner\weapons\c_models\<weapon_key>\<weapon_key>.mdl
        if modelname_path:
            # Нормализуем путь (заменяем обратные слеши на прямые для разделения)
            normalized_path = modelname_path.replace('\\', '/')
            path_parts = normalized_path.split('/')
            # Ищем weapon_key (это папка перед именем файла)
            if len(path_parts) >= 2:
                weapon_key = path_parts[-2]  # Предпоследняя часть пути
                # Строим путь к папке с файлами: <tf_dir>/models/workshop_partner/weapons/c_models/<weapon_key>/
                model_dir_in_tf = os.path.join(tf_dir, "models", *path_parts[:-1])
            else:
                # Fallback: используем базовое имя QC файла
                model_dir_in_tf = os.path.join(tf_dir, "models", "workshop_partner", "weapons", "c_models", qc_basename)
        else:
            # Fallback: используем базовое имя QC файла
            model_dir_in_tf = os.path.join(tf_dir, "models", "workshop_partner", "weapons", "c_models", qc_basename)
        
        # Копируем файлы из папки TF2 в out_dir
        mdl_found = False
        copied_files = []
        
        logger.debug(f"Ищем скомпилированные файлы в: {model_dir_in_tf}")
        logger.debug(f"Копируем в: {out_dir}")
        logger.debug(f"Базовое имя модели: {qc_basename}")
        
        if not os.path.exists(model_dir_in_tf):
            raise RuntimeError(
                f"Compiled files folder not found: {model_dir_in_tf}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        # Копируем только файлы модели которые начинаются с qc_basename
        # Это предотвращает копирование файлов других моделей (например, bat при компиляции scattergun)
        for file_name in os.listdir(model_dir_in_tf):
            # Проверяем что файл начинается с qc_basename (имя модели из QC)
            if file_name.startswith(qc_basename):
                src = os.path.join(model_dir_in_tf, file_name)
                if os.path.isfile(src):
                    dst = os.path.join(out_dir, file_name)
                    shutil.copy2(src, dst)
                    copied_files.append(file_name)
                    if file_name.endswith('.mdl'):
                        mdl_found = True
                    logger.debug(f"Скопирован файл модели из TF2: {file_name} -> {dst}")
        
        logger.info(f"Всего скопировано файлов: {len(copied_files)}")
        logger.debug(f"Список скопированных файлов: {copied_files}")
        
        if not mdl_found:
            raise RuntimeError(
                f".mdl file not found after compilation in {model_dir_in_tf}\n"
                f"Files in folder: {os.listdir(model_dir_in_tf) if os.path.exists(model_dir_in_tf) else 'folder does not exist'}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

