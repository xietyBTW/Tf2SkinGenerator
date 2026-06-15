"""
Единый парсер $texturegroup ("skinfamilies") из QC-файлов.

Единственный источник правды о том, как устроены skin-семейства TF2:
  • СТРОКИ (rows)    = скины (RED, BLU, стили bloody/clean, варианты gold/festive…)
  • СТОЛБЦЫ (columns)= материалы модели (body, shell, scope…)

Раньше это знание было размазано по трём независимым парсерам
(ModelBuildService, Preview3DWorker ×2) с четырьмя разными списками
вариантных суффиксов и тремя правилами определения BLU. Теперь все
потребители (сборка, 3D-превью, определение стилей, извлечение текстур
шапок) ходят сюда.

Терминология:
  base rows    — строки без вариантного суффикса в col0 (RED/BLU/стили).
  variant rows — строки-варианты (australium/gold/festive/…): отдельные
                 «виды» оружия, а не стили.
  second_row   — вторая базовая строка КАК ЕСТЬ (позиционно). Для сборки
                 это «второй скин, который надо отрендерить» — командный
                 он или стилевой (bloody), решает blu_is_team.
  blu_is_team  — вторая строка является именно BLU-командой (проверка по
                 именам: col0 + '_blue'/'_blu'), а не стилем вроде bloody.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# ── Единственная копия вариантных суффиксов ─────────────────────────────── #
# suffix → вид варианта. '_strange'/'_unusual' встречаются редко (обычно
# padding-строки не переименованы), но исключаются из базовых на всякий случай.
VARIANT_SUFFIXES: Dict[str, str] = {
    '_australium': 'australium',
    '_gold':       'australium',
    '_festive':    'festive',
    '_xmas':       'festive',
    '_botkiller':  'botkiller',
    '_strange':    'strange',
    '_unusual':    'unusual',
}

# Виды вариантов, которые показываются в превью как «вариант оружия»
# (strange/unusual — это padding, не отдельный внешний вид).
PREVIEW_VARIANT_KINDS = ('australium', 'festive', 'botkiller')

# Дружелюбные подписи стилей по суффиксу текстуры col0.
_FRIENDLY_STYLE_SUFFIXES = {'_bloody': 'Bloody', '_clean': 'Clean', '_dirty': 'Dirty'}


def variant_kind(texture_name: str) -> Optional[str]:
    """
    Вид варианта по суффиксу имени текстуры, или None для базовых имён.

    Командный суффикс _blue/_blu перед проверкой отрезается:
    'c_rocketlauncher_gold_blue' — это BLU-вариант австралиума, а не
    отдельный базовый скин (раньше такие строки считались фантомным
    «Skin N» при определении стилей).
    """
    name = (texture_name or '').lower()
    for team_suffix in ('_blue', '_blu'):
        if name.endswith(team_suffix):
            name = name[: -len(team_suffix)]
            break
    for suffix, kind in VARIANT_SUFFIXES.items():
        if name.endswith(suffix):
            return kind
    return None


# ── Низкоуровневый парсинг QC ───────────────────────────────────────────── #

def parse_texturegroup_rows(qc_path: str) -> List[List[str]]:
    """
    Парсит строки-скины из $texturegroup в QC файле.

    Каждый скин — это внутренний блок `{ ... }`, который МОЖЕТ занимать
    несколько строк (studiomdl/Crowbar часто пишут каждый материал на своей
    строке). Поэтому парсим по фигурным скобкам, а не построчно — иначе одна
    строка-скин из N материалов ошибочно превращается в N «скинов».

    Имя группы не проверяется ($texturegroup "skinfamilies" или любое другое).

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


def parse_cdmaterials(qc_path: str) -> List[str]:
    """
    Все пути $cdmaterials из QC, нормализованные для поиска в VPK:
      • backslashes → '/', срезаны слеши по краям;
      • префикс 'console/' (добавляет Crowbar) убирается — в VPK его нет;
      • относительные пути с '..' (системные папки движка) пропускаются.

    Returns:
        Список путей вида 'models/weapons/c_models/c_test' (без 'materials/').
    """
    try:
        with open(qc_path, encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        return []

    result: List[str] = []
    for raw in re.findall(r'\$cdmaterials\s+"([^"]+)"', content, re.IGNORECASE):
        p = raw.replace('\\', '/').strip('/')
        if p.lower().startswith('console/'):
            p = p[len('console/'):]
        if '..' in p:
            continue
        p = p.strip('/')
        if p:
            result.append(p)
    return result


# ── Классификация строк ─────────────────────────────────────────────────── #

@dataclass
class SkinLayout:
    """Структурированное содержимое $texturegroup одного QC."""

    all_rows: List[List[str]] = field(default_factory=list)
    #: Базовые строки КАК ЕСТЬ (без вариантов, но с возможными padding-дублями).
    #: Позиционная семантика сборки опирается именно на них.
    base_rows: List[List[str]] = field(default_factory=list)
    #: Базовые строки после схлопывания идентичных (padding) — для UI/стилей.
    unique_base_rows: List[List[str]] = field(default_factory=list)
    main_texture: Optional[str] = None
    extra_materials: List[str] = field(default_factory=list)
    #: Вторая базовая строка (позиционно): BLU-команда ИЛИ стиль (bloody…).
    second_row: List[str] = field(default_factory=list)
    #: Вторая УНИКАЛЬНАЯ базовая строка — именно BLU-команда (по именам).
    blu_is_team: bool = False
    #: Вид варианта → первая строка этого вида (в порядке файла).
    variants: Dict[str, List[str]] = field(default_factory=dict)
    #: Подписи уникальных скинов для UI: RED/BLU, Bloody/Clean или Skin N.
    roles: List[str] = field(default_factory=list)
    #: ВСЕ осмысленные скины (база + команда + варианты) для кастомной модели:
    #: [{'index': сырой_индекс_в_all_rows, 'role': подпись}]. Индекс сохраняется
    #: «как в модели» — игра выбирает скин (команда/качество/стиль) по нему.
    skins: List[dict] = field(default_factory=list)

    def describe(self) -> str:
        """Одна строка для лога: как классифицирован QC."""
        return (
            f"main={self.main_texture!r}, extras={self.extra_materials}, "
            f"second_row={'team-BLU' if self.blu_is_team else (self.second_row and 'style' or 'none')}"
            f"{self.second_row and '=' + str(self.second_row) or ''}, "
            f"variants={list(self.variants)}, roles={self.roles}"
        )


def _style_label(row: List[str], idx: int) -> str:
    """Дружелюбная подпись скина по суффиксу его текстуры (иначе 'Skin N')."""
    if idx == 0:
        return 'Skin 0'
    name = (row[0] if row else '').lower()
    for suffix, label in _FRIENDLY_STYLE_SUFFIXES.items():
        if name.endswith(suffix):
            return label
    return f'Skin {idx}'


def classify_rows(rows: List[List[str]]) -> SkinLayout:
    """
    Классифицирует строки $texturegroup.

    Правила (зафиксированы тестами на корпусе QC):
      1. Строка с вариантным суффиксом в col0 → variant (не базовая).
      2. Если все строки — варианты, базовыми считаются все (fallback).
      3. main_texture = col0 первой базовой строки.
      4. second_row = вторая базовая строка позиционно (для сборки).
      5. blu_is_team — по именам: col0 второй УНИКАЛЬНОЙ базовой строки ==
         col0 первой + '_blue'/'_blu'.
      6. extra_materials = col1+ первой базовой строки, кроме имён, уже
         присутствующих в second_row (Valve иногда пишет BLU-варианты
         столбцами в одной строке).
      7. Идентичные базовые строки (padding для strange/killstreak)
         схлопываются ТОЛЬКО в unique_base_rows/roles — base_rows/second_row
         сохраняют исходную позиционность.
    """
    layout = SkinLayout(all_rows=rows)
    if not rows:
        return layout

    # 1-2: базовые строки и варианты
    base_rows: List[List[str]] = []
    for row in rows:
        kind = variant_kind(row[0]) if row else None
        if kind is None:
            base_rows.append(row)
        else:
            layout.variants.setdefault(kind, row)
    if not base_rows:
        base_rows = rows[:]
    layout.base_rows = base_rows

    # Праздничные (festive) варианты — это ВСЕГДА отдельные модели (c_*_xmas.mdl).
    # Поэтому если САМ основной материал festive (база и BLU оканчиваются на
    # _xmas, напр. c_sapper_xmas / c_wrangler_xmas), модель НАТИВНО праздничная,
    # а не имеет overlay-вариант — убираем festive из variants, иначе в превью
    # всплывёт ложная карточка варианта. Australium так НЕ трогаем: золотой скин
    # живёт в той же модели отдельной строкой (skin 0 = норма, skin 1 = золото).
    _main_kind = variant_kind(base_rows[0][0]) if (base_rows and base_rows[0]) else None
    if _main_kind == 'festive':
        layout.variants.pop('festive', None)

    # 3-4: главная текстура, второй скин (позиционно)
    layout.main_texture = base_rows[0][0]
    layout.second_row = base_rows[1] if len(base_rows) > 1 else []

    # 6: extra_materials (минус имена из second_row — см. док-стринг)
    second_names = set(layout.second_row)
    extra_raw = base_rows[0][1:] if len(base_rows[0]) > 1 else []
    layout.extra_materials = [m for m in extra_raw if m not in second_names]

    # 7: дедуп идентичных строк (padding) — для UI/стилей
    seen = set()
    unique_rows: List[List[str]] = []
    for r in base_rows:
        key = tuple(x.lower() for x in r)
        if key not in seen:
            seen.add(key)
            unique_rows.append(r)
    layout.unique_base_rows = unique_rows

    # 5: командность второй уникальной строки — строго по именам
    if len(unique_rows) >= 2 and unique_rows[0] and unique_rows[1]:
        b0 = unique_rows[0][0].lower()
        b1 = unique_rows[1][0].lower()
        layout.blu_is_team = b1 in (b0 + '_blue', b0 + '_blu')

    # Подписи скинов для UI
    n = len(unique_rows)
    if n <= 1:
        layout.roles = ['Skin 0'] if n == 1 else []
    elif layout.blu_is_team:
        layout.roles = ['RED', 'BLU'] + [f'Skin {i}' for i in range(2, n)]
    else:
        layout.roles = [_style_label(unique_rows[i], i) for i in range(n)]

    # Полный список скинов для кастомной модели: ВСЕ осмысленные строки (база +
    # команда + варианты), с СЫРЫМ индексом (позиция в all_rows = индекс скина в
    # модели). Padding-дубли skin 0 пропускаем — сборка заполнит их базой; но
    # индексы оставшихся строк сохраняем, чтобы команда/австралий/стиль
    # выбирались игрой по правильному индексу.
    has_team = any(
        r and (r[0].lower().endswith('_blue') or r[0].lower().endswith('_blu'))
        for r in rows
    )
    skins: List[dict] = []
    seen_keys = set()
    for raw_idx, row in enumerate(rows):
        if not row:
            continue
        key = tuple(x.lower() for x in row)
        if raw_idx != 0 and key in seen_keys:
            continue  # padding/дубль базового скина
        seen_keys.add(key)
        col0 = row[0].lower()
        kind = variant_kind(row[0])
        if raw_idx == 0:
            role = 'RED' if has_team else 'Skin 0'
        elif kind:
            role = kind.capitalize()
        elif col0.endswith('_blue') or col0.endswith('_blu'):
            role = 'BLU'
        else:
            role = _style_label(row, raw_idx)
        skins.append({'index': raw_idx, 'role': role})
    layout.skins = skins

    return layout


def parse_skin_layout(qc_path: str) -> SkinLayout:
    """Парсит QC и классифицирует его $texturegroup одной операцией."""
    layout = classify_rows(parse_texturegroup_rows(qc_path))
    logger.debug(f"skin layout {os.path.basename(qc_path)}: {layout.describe()}")
    return layout


def pick_preview_variant(layout: SkinLayout) -> Optional[List[str]]:
    """
    Строка варианта для 3D-превью: приоритет — настоящий австралиум,
    затем прочие «внешние» варианты в порядке файла.
    """
    if 'australium' in layout.variants:
        return layout.variants['australium']
    for kind in PREVIEW_VARIANT_KINDS:
        if kind in layout.variants:
            return layout.variants[kind]
    return None


# ── Ограничение раскладки списком разрешённых материалов (режимы рук) ───── #

def restrict_to_materials(
    main_texture: str,
    red_row: List[str],
    blu_row: List[str],
    allowed_names: List[str],
) -> tuple:
    """
    Сужает раскладку до разрешённых материалов, сохраняя выравнивание колонок.

    Используется для режимов рук: QC рук инженера/медика в col0 содержит
    текстуру ТЕЛА (engineer_red), и без фильтрации картинка пользователя
    заменила бы всё тело. Оставляем только материалы из allowed_names
    (+ их BLU-варианты на тех же позициях).

    Args:
        main_texture:  текущая главная текстура (col0 red_row).
        red_row:       полная RED строка.
        blu_row:       полная BLU строка (выровнена по колонкам с RED).
        allowed_names: разрешённые имена (например, текстуры рук из
                       player_hands); регистр не важен.

    Returns:
        (main_texture, extra_materials, blu_row) после фильтрации.
        Если main_texture не входит в allowed — заменяется первым разрешённым
        материалом из red_row, иначе первым из allowed_names.
    """
    allowed_lc = {n.lower() for n in allowed_names}

    # Позиции разрешённых материалов в red_row
    hand_idx = [i for i, t in enumerate(red_row) if t.lower() in allowed_lc]

    # Главная текстура: если col0 — не разрешённый материал (текстура тела),
    # берём первый разрешённый из строки, иначе первый из allowed_names.
    if main_texture.lower() not in allowed_lc:
        if hand_idx:
            main_texture = red_row[hand_idx[0]]
        elif allowed_names:
            main_texture = allowed_names[0]

    # BLU: только на позициях разрешённых материалов; пары, где BLU == RED,
    # пропускаем — это нейтральная (общая) текстура, она пойдёт через
    # main/extra, а не через BLU-путь.
    filtered_blu: List[str] = []
    for i in hand_idx:
        if i < len(blu_row):
            b, r = blu_row[i], red_row[i]
            if b.lower() != r.lower():
                filtered_blu.append(b)
    filtered_blu_lc = {t.lower() for t in filtered_blu}

    # Доп. материалы: разрешённые из red_row, кроме главной и кроме уже
    # попавших в BLU (иначе создадутся дважды).
    extra_materials = [
        red_row[i] for i in hand_idx
        if red_row[i].lower() != main_texture.lower()
        and red_row[i].lower() not in filtered_blu_lc
    ]

    return main_texture, extra_materials, filtered_blu


def detect_shoulder_materials(mesh_materials: List[str],
                              hand_whitelist: List[str]) -> List[str]:
    """
    Материалы arms-модели, которые НЕ являются руками (т.е. «плечи/тело»,
    общие с мировым персонажем). Это ровно те материалы, что сейчас
    выкидываются restrict_to_materials.

    Args:
        mesh_materials: материалы меша arms-модели (red_row из $texturegroup).
        hand_whitelist: известные имена текстур рук (HAND_MODES[...]["textures"]).

    Returns:
        Список «плечевых» материалов (порядок сохранён, дубли убраны). Пусто —
        руки «чистые» (без мирового тела), изолировать нечего.
    """
    allowed = {n.lower() for n in hand_whitelist}
    seen: set = set()
    out: List[str] = []
    for m in mesh_materials:
        ml = m.lower()
        if not m or ml in allowed or ml in seen:
            continue
        seen.add(ml)
        out.append(m)
    return out


def team_reference(rows: List[List[str]]):
    """
    Находит «эталонный» командный столбец в строках $texturegroup — тот, где
    есть пара X_red / X_blue (по нему отличаем RED-скины от BLU). Используется,
    чтобы понять, какие строки относятся к синей команде.

    Returns:
        (col_index, blue_value) или None, если команд-столбца нет.
    """
    if not rows:
        return None
    ncols = max((len(r) for r in rows), default=0)
    # Приоритет: точная пара X_red / X_blue с одинаковым стеблем.
    for c in range(ncols):
        vals = {r[c].lower() for r in rows if c < len(r)}
        reds = [v for v in vals if v.endswith('_red')]
        blues = [v for v in vals if v.endswith('_blue')]
        for red in reds:
            stem = red[:-4]
            if f"{stem}_blue" in blues:
                return c, f"{stem}_blue"
    # Фолбэк: любой столбец, где встречаются и *_red, и *_blue.
    for c in range(ncols):
        vals = {r[c].lower() for r in rows if c < len(r)}
        blues = [v for v in vals if v.endswith('_blue')]
        reds = [v for v in vals if v.endswith('_red')]
        if blues and reds:
            return c, blues[0]
    return None


def neutral_materials(rows: List[List[str]]) -> List[str]:
    """
    Материалы из столбцов $texturegroup, значение которых ОДИНАКОВО во всех
    скинах (нейтральные — не меняются между RED и BLU). Это кандидаты на
    «повышение» до командных. Порядок сохранён, дубли убраны.
    """
    if not rows:
        return []
    ncols = max((len(r) for r in rows), default=0)
    out: List[str] = []
    seen: set = set()
    for c in range(ncols):
        vals = {r[c] for r in rows if c < len(r)}
        if len(vals) == 1:
            m = next(iter(vals))
            if m and m.lower() not in seen:
                seen.add(m.lower())
                out.append(m)
    return out


def apply_team_promotions(rows: List[List[str]], promotions: dict) -> List[List[str]]:
    """
    «Повышает» нейтральные материалы до командных: в строках СИНЕЙ команды
    заменяет материал на его BLU-вариант (RED-строки не трогает).

    Args:
        rows:       строки $texturegroup.
        promotions: {material_lower: blue_variant_name}.

    Returns:
        Новые строки (копия). Если команд-эталон не найден или promotions пуст —
        возвращает копию без изменений.
    """
    base = [list(r) for r in rows]
    if not promotions:
        return base
    ref = team_reference(rows)
    if not ref:
        return base
    col, blue_val = ref
    bl = blue_val.lower()
    out: List[List[str]] = []
    for r in base:
        is_blue = col < len(r) and r[col].lower() == bl
        if is_blue:
            out.append([promotions.get(c.lower(), c) for c in r])
        else:
            out.append(list(r))
    return out
