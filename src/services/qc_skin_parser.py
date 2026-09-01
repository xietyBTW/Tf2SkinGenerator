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

import glob
import os
import posixpath
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


def _team_form(texture_name: str) -> tuple:
    """
    (основа, синий?) — имя материала без командного суффикса.

    Командный суффикс стоит либо в конце ('c_scattergun_blue'), либо ПЕРЕД
    вариантным ('c_ambassador_opt_blue_xmas'). База может уже нести '_red'
    (festive_lights_red / festive_lights_blue) — тогда основа общая.
    """
    name = (texture_name or '').lower()
    tail = ''
    for suffix in VARIANT_SUFFIXES:
        if name.endswith(suffix):
            name, tail = name[: -len(suffix)], suffix
            break
    for team_suffix in ('_blue', '_blu'):
        if name.endswith(team_suffix):
            return name[: -len(team_suffix)] + tail, True
    if name.endswith('_red'):
        return name[:-4] + tail, False
    return name + tail, False


def _is_own_material(name: str, row: List[str]) -> bool:
    """
    Столбец несёт СВОЙ материал, а не командную/вариантную копию соседнего.

    В красной строке Valve нередко держит и синие имена, и австралий соседнего
    столбца (c_scattergun рядом с c_scattergun_gold). Их пишут отдельные ветки
    сборки, и в списке материалов предмета им делать нечего. При этом имя с
    '_xmas' само по себе поводом не является: у праздничного револьвера так
    называется его единственный собственный материал — вариантом столбец
    считается, только если рядом лежит его база.
    """
    name = (name or '').lower()
    if not name or _team_form(name)[1]:
        return False
    if variant_kind(name):
        present = {(n or '').lower() for n in row}
        for suffix in VARIANT_SUFFIXES:
            if name.endswith(suffix) and name[: -len(suffix)] in present:
                return False
    return True


#: Порог «этот столбец и есть модель»: главным назначается не нулевой столбец,
#: только если он покрывает не меньше половины модели И как минимум втрое
#: больше нулевого. Откалибровано по стоку: переезжают очевидные случаи
#: (Quick-Fix 93% против 6%, C.A.P.P.E.R 99% против 0%, праздничный револьвер
#: 58% против 13%), а спорные остаются на порядке автора — Mad Milk (стекло 67%
#: против жидкости 32%) и Карамельная трость (60/40) не трогаются.
MAIN_COLUMN_MIN_SHARE = 0.50
MAIN_COLUMN_MIN_RATIO = 3.0
#: Ниже этой доли покрытия веса считаются несопоставимыми с $texturegroup
#: (имена мешей разошлись с именами столбцов) и не используются вовсе.
MAIN_COLUMN_MIN_COVERAGE = 0.50


def choose_main_column(row: List[str], weights: Optional[Dict[str, int]]) -> int:
    """
    Номер столбца, который пользователь считает «текстурой предмета».

    По умолчанию это нулевой столбец — порядок, в котором материалы записал
    автор модели. Но порядок ничего не обещает: у Quick-Fix первым идёт стекло
    (4% модели), у C.A.P.P.E.R — экранчик (0.1%), и основная картинка уезжала
    на них, а корпус оставался «доп. материалом». Если веса мешей показывают,
    что модель почти целиком покрыта другим столбцом, главным становится он.

    weights — {имя материала: сколько треугольников} (SMDService.
    material_triangle_counts). Без весов или при слабом перевесе → 0.

    Синие имена в основные не берём никогда, а вариантные — только если в том
    же ряду есть их база: у c_tw_eagle 82% модели покрывает столбец
    'c_tw_eagle_gold', и красить надо не его, а стоящий рядом 'c_tw_eagle'.
    Само по себе имя с '_xmas' поводом не является — у праздничного револьвера
    так называется его единственный собственный материал.
    """
    if not row or not weights:
        return 0
    total = sum(weights.values())
    if total <= 0:
        return 0

    def share(index: int) -> float:
        name = (row[index] or '').lower() if index < len(row) else ''
        return weights.get(name, 0) / total

    if sum(share(i) for i in range(len(row))) < MAIN_COLUMN_MIN_COVERAGE:
        logger.debug("choose_main_column: веса мешей не сходятся с $texturegroup")
        return 0

    from src.data.material_filter import is_editable_material

    def eligible(name: str) -> bool:
        return _is_own_material(name, row) and is_editable_material(name)

    best = 0
    for i, name in enumerate(row):
        if eligible(name) and share(i) > share(best):
            best = i
    if best and share(best) >= MAIN_COLUMN_MIN_SHARE \
            and share(best) >= MAIN_COLUMN_MIN_RATIO * share(0):
        logger.info(
            f"Главный материал по мешам: '{row[best]}' ({share(best):.0%} модели) "
            f"вместо столбца 0 '{row[0]}' ({share(0):.0%})"
        )
        return best
    return 0


def is_team_row_pair(red_row: List[str], blu_row: List[str]) -> bool:
    """
    Вторая строка $texturegroup — именно BLU-команда, а не стиль/вариант?

    Команда в Source меняет материалы ПОКОЛОНОЧНО и не обязательно все:
    столбец либо остаётся тем же (нейтральная деталь), либо заменяется на
    свою синюю пару. Достаточно одного изменённого столбца — но любая
    ПОСТОРОННЯЯ разница означает, что это стиль (bloody/clean), а не команда.

        { c_proto_medigun_glass  c_proto_medigun       c_proto_medigun_blue }
        { c_proto_medigun_glass  c_proto_medigun_blue  c_proto_medigun_blue }

    Проверка только по col0 признала бы Quick-Fix некомандным: стекло у него
    общее, а меняется второй столбец.
    """
    width = min(len(red_row or []), len(blu_row or []))
    if not width:
        return False
    changed = False
    for i in range(width):
        red, blu = (red_row[i] or '').lower(), (blu_row[i] or '').lower()
        if red == blu:
            continue
        red_stem, red_is_blue = _team_form(red)
        blu_stem, blu_is_blue = _team_form(blu)
        if blu_is_blue and not red_is_blue and red_stem == blu_stem:
            changed = True
            continue
        return False
    return changed


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


def parse_bonemerge(qc_path: str) -> List[str]:
    """
    Имена костей из $bonemerge — ровно те, что модель отдаёт родителю.

    У оружия TF2 это обычно `weapon_bone` и `c_weapon_stattrack`, а вовсе не
    все кости: `weapon_bone_1..4` у револьвера — это его собственные курок,
    барабан и спуск. Сливать их с одноимёнными костями руки нельзя — у руки
    это лесенка точек крепления под разную длину оружия, и револьвер от такого
    слияния разлетается на 73 единицы вместо своих двадцати.

    Returns:
        Список имён в порядке объявления. Пусто — в QC директивы нет.
    """
    try:
        with open(qc_path, encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        return []
    return re.findall(r'^\s*\$bonemerge\s+"([^"]+)"', content,
                      re.IGNORECASE | re.MULTILINE)


def resolve_cdmaterials(raw_paths: List[str]) -> List[str]:
    """
    Пути $cdmaterials, готовые к поиску в VPK:
      • backslashes → '/', срезаны слеши по краям;
      • префикс 'console/' (добавляет Crowbar) убирается — в VPK его нет;
      • путь с '..' разрешается ОТНОСИТЕЛЬНО соседних абсолютных строк.

    Последнее — не мелочь. В QC тела шпиона рядом стоят

        $cdmaterials "\\..\\..\\effects"
        $cdmaterials "models\\player\\spy\\"

    и вместе это `models/effects` — там лежат материалы убер-эффекта
    (invulnfx_red/blue). Раньше строки с '..' просто выбрасывались, и такие
    материалы оставались без текстуры и в превью, и в моде. Порядок строк в QC
    не задан, поэтому сначала берутся абсолютные, а по ним разрешаются
    относительные; ушедшие выше `materials/` отбрасываются.

    Returns:
        Список путей вида 'models/weapons/c_models/c_test' (без 'materials/'),
        без повторов, в порядке приоритета поиска.
    """
    cleaned: List[str] = []
    for raw in raw_paths or []:
        p = (raw or '').replace('\\', '/').strip('/')
        if p.lower().startswith('console/'):
            p = p[len('console/'):]
        p = p.strip('/')
        if p:
            cleaned.append(p)

    absolute = [p for p in cleaned if '..' not in p]
    ordered = list(absolute)
    for p in cleaned:
        if '..' not in p:
            continue
        for base in absolute:
            merged = posixpath.normpath(f'{base}/{p}').strip('/')
            if merged and merged != '.' and not merged.startswith('..'):
                ordered.append(merged)

    seen: set = set()
    result: List[str] = []
    for p in ordered:
        if p.lower() not in seen:
            seen.add(p.lower())
            result.append(p)
    return result


def parse_cdmaterials(qc_path: str) -> List[str]:
    """Пути $cdmaterials из QC (см. resolve_cdmaterials)."""
    try:
        with open(qc_path, encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        return []
    return resolve_cdmaterials(
        re.findall(r'\$cdmaterials\s+"([^"]+)"', content, re.IGNORECASE))


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
    #: Столбец, из которого взята main_texture. Обычно 0, но при явном перевесе
    #: по мешам — другой (см. choose_main_column). Командную пару главной надо
    #: брать из ЭТОГО столбца второй строки, иначе синяя уедет не туда.
    main_index: int = 0
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


def classify_rows(rows: List[List[str]],
                  weights: Optional[Dict[str, int]] = None) -> SkinLayout:
    """
    Классифицирует строки $texturegroup.

    weights — {материал: сколько треугольников} из мешей модели (необязательно).
    Только они отличают корпус от стекла и лампочки; без них раскладка честно
    остаётся на порядке столбцов автора.

    Правила (зафиксированы тестами на корпусе QC):
      1. Строка с вариантным суффиксом в col0 → variant (не базовая).
      2. Если все строки — варианты, базовыми считаются все (fallback).
      3. main_texture = главный столбец первой базовой строки: нулевой, а при
         явном перевесе по мешам — покрывающий модель (choose_main_column).
      4. second_row = вторая базовая строка позиционно (для сборки).
      5. blu_is_team — по именам, ПО ВСЕМ СТОЛБЦАМ (is_team_row_pair).
      6. extra_materials = остальные столбцы первой базовой строки, кроме имён,
         уже присутствующих в second_row (Valve иногда пишет BLU-варианты
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

    # 3-4: главная текстура, второй скин (позиционно)
    layout.main_index = choose_main_column(base_rows[0], weights)
    layout.main_texture = base_rows[0][layout.main_index] if base_rows[0] else None
    layout.second_row = base_rows[1] if len(base_rows) > 1 else []

    # Праздничные (festive) варианты — это ВСЕГДА отдельные модели (c_*_xmas.mdl).
    # Поэтому если САМ основной материал festive (c_sapper_xmas / c_wrangler_xmas),
    # модель НАТИВНО праздничная, а не имеет overlay-вариант — убираем festive из
    # variants, иначе в превью всплывёт ложная карточка варианта. Australium так
    # НЕ трогаем: золотой скин живёт в той же модели отдельной строкой.
    if variant_kind(layout.main_texture or '') == 'festive':
        layout.variants.pop('festive', None)

    # 6: extra_materials — остальные столбцы первой базовой строки, кроме
    # СИНИХ имён и вариантов соседнего столбца (c_scattergun_gold рядом с
    # c_scattergun): и то и другое пишут свои ветки сборки. Общие материалы
    # (стекло Quick-Fix) в списке остаются — раньше их выбрасывало правило
    # «минус имена из второй строки», хотя общий материал там есть всегда.
    # Столбцы, которых нет ни на одном меше, тоже выбрасываем: у праздничного
    # сапёра в строке лежит материал обычного сапёра, но на модели его нет.
    layout.extra_materials = [
        m for i, m in enumerate(base_rows[0])
        if i != layout.main_index and _is_own_material(m, base_rows[0])
        and (not weights or weights.get(m.lower(), 0) > 0)
    ]

    # 7: дедуп идентичных строк (padding) — для UI/стилей
    seen = set()
    unique_rows: List[List[str]] = []
    for r in base_rows:
        key = tuple(x.lower() for x in r)
        if key not in seen:
            seen.add(key)
            unique_rows.append(r)
    layout.unique_base_rows = unique_rows

    # 5: командность второй уникальной строки — строго по именам, ПО ВСЕМ
    # СТОЛБЦАМ (см. is_team_row_pair). Раньше смотрели только col0, и команда
    # терялась там, где по команде меняется не первый материал: Quick-Fix,
    # Overdose, Manmelter, C.A.P.P.E.R, праздничные пушки, Conspiracy Cap.
    if len(unique_rows) >= 2:
        layout.blu_is_team = is_team_row_pair(unique_rows[0], unique_rows[1])

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
    has_team = any(is_team_row_pair(rows[0], r) for r in rows[1:])
    skins: List[dict] = []
    seen_keys = set()
    for raw_idx, row in enumerate(rows):
        if not row:
            continue
        key = tuple(x.lower() for x in row)
        if raw_idx != 0 and key in seen_keys:
            continue  # padding/дубль базового скина
        seen_keys.add(key)
        kind = variant_kind(row[0])
        if raw_idx == 0:
            role = 'RED' if has_team else 'Skin 0'
        elif kind:
            role = kind.capitalize()
        elif is_team_row_pair(rows[0], row):
            role = 'BLU'
        else:
            role = _style_label(row, raw_idx)
        skins.append({'index': raw_idx, 'role': role})
    layout.skins = skins

    return layout


#: (qc_path, mtime) -> веса материалов. Раскладку одной модели за сборку
#: спрашивают несколько раз, а SMD у пушек весят мегабайты.
_WEIGHTS_CACHE: Dict[tuple, Dict[str, int]] = {}


def mesh_material_weights(qc_path: str) -> Dict[str, int]:
    """
    {материал: сколько треугольников} по ВСЕМ мешам модели.

    Берём все варианты бодигрупп, а не только видимые по умолчанию: парашют
    B.A.S.E. Jumper и разбитая бутылка — переключаемые части, но материалы у
    них настоящие и красить их надо. Ноль треугольников означает, что столбец
    $texturegroup на модели не используется вовсе.

    Пусто, если QC или SMD рядом нет: тогда раскладка останется на порядке
    столбцов, как раньше.
    """
    if not qc_path or not os.path.isfile(qc_path):
        return {}
    try:
        key = (os.path.abspath(qc_path), os.path.getmtime(qc_path))
    except OSError:
        return {}
    cached = _WEIGHTS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from src.services.model_build_service import ModelBuildService
        from src.services.smd_service import SMDService
        weights = SMDService.material_triangle_counts(
            ModelBuildService.extract_all_mesh_smds(qc_path))
    except Exception as exc:
        logger.debug(f"mesh_material_weights({os.path.basename(qc_path)}): {exc}")
        weights = {}
    if len(_WEIGHTS_CACHE) > 64:
        _WEIGHTS_CACHE.clear()
    _WEIGHTS_CACHE[key] = weights
    return weights


def parse_skin_layout(qc_path: str,
                      weights: Optional[Dict[str, int]] = None) -> SkinLayout:
    """
    Парсит QC и классифицирует его $texturegroup одной операцией.

    Веса материалов по мешам берутся из SMD рядом с QC — только они отличают
    корпус от стекла и лампочки (см. choose_main_column). Явный аргумент
    weights нужен там, где меши уже посчитаны или их заведомо нет.
    """
    if weights is None:
        weights = mesh_material_weights(qc_path)
    layout = classify_rows(parse_texturegroup_rows(qc_path), weights)
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


# ── Единый «авторитет» селекторов: что показывать для любой модели ──────── #

@dataclass
class SelectorSpec:
    """Какие селекторы должна показать UI для данной модели — ЕДИНЫЙ источник
    истины (и для оружия, и для шапок, и для снарядов, и т.д.). Считается из
    $texturegroup, поэтому детект одинаков для всех типов и не расходится.

    team    — показывать переключатель RED/BLU.
    variant — вид внешнего варианта ('australium'/'festive'/'botkiller') или None
              → показывать карточку варианта.
    styles  — доп. стили-скины (bloody/clean и т.п.), КРОМЕ базового/RED/BLU и
              варианта: список (подпись, сырой_индекс_скина). Индекс — позиция в
              all_rows (как в модели), чтобы сборка/превью выбирали верный скин.
    """
    team: bool = False
    variant: Optional[str] = None
    styles: List[tuple] = field(default_factory=list)


def selector_spec(layout: SkinLayout) -> SelectorSpec:
    """Единая классификация: команда / вариант / стили — из одного разбора QC."""
    spec = SelectorSpec()
    if layout is None:
        return spec

    spec.team = bool(layout.blu_is_team)

    pv = pick_preview_variant(layout)
    if pv:
        spec.variant = variant_kind(pv[0])

    # Стили: ТОЛЬКО косметические (bloody/clean/dirty — именованные).
    # Генерик-«Skin N» НЕ включаем: у тел персонажей это функциональные скины
    # (убер-заряд invun, маскировка mask_*, зомби), а не косметика, которую правят.
    _base_roles = {'red', 'blu', 'skin 0'}
    for s in layout.skins:
        idx = s.get('index', -1)
        role = s.get('role', '')
        rl = role.lower()
        if rl in _base_roles or role.startswith('Skin '):
            continue
        col0 = layout.all_rows[idx][0] if 0 <= idx < len(layout.all_rows) and layout.all_rows[idx] else ''
        if variant_kind(col0):
            continue  # это вариант (austr/festive/botkiller) — учтён в spec.variant
        spec.styles.append((role, idx))
    return spec


@dataclass
class QcModel:
    """
    Разобранный QC декомпилированной модели — один раз на прогон.

    Раньше каждый метод воркера сам искал QC в папке (`glob(*.qc)` встречался
    одиннадцать раз) и заново разбирал его: за один показ шапки один и тот же
    файл читался и парсился по нескольку раз, а какой именно из QC достанется
    методу, зависело от порядка файлов в папке. Здесь это делается один раз, и
    все шаги работают с одним и тем же разбором.
    """

    qc_path: str
    cdmaterials: List[str] = field(default_factory=list)
    layout: SkinLayout = field(default_factory=SkinLayout)
    #: Кости из $bonemerge — те, что в игре получают положение от РОДИТЕЛЬСКОЙ
    #: модели. Остальные кости модели двигаются сами (курок, барабан, цевьё).
    bonemerge: List[str] = field(default_factory=list)

    @property
    def team_map(self) -> Dict[str, str]:
        """{материал RED: материал BLU} по столбцам (см. team_material_map)."""
        return team_material_map(self.layout)

    @property
    def spec(self) -> "SelectorSpec":
        """Команда / вариант / стили — одной классификацией."""
        return selector_spec(self.layout)

    @property
    def skin0(self) -> List[str]:
        """Материалы первой строки $texturegroup (skin 0)."""
        return self.layout.base_rows[0] if self.layout.base_rows else []


def load_model(decomp_dir: str) -> Optional[QcModel]:
    """QC из папки декомпиляции, разобранный целиком. None — QC нет."""
    if not decomp_dir:
        return None
    qc_files = sorted(glob.glob(os.path.join(decomp_dir, "*.qc")))
    if not qc_files:
        logger.debug(f"QC не найден в {decomp_dir}")
        return None
    qc_path = qc_files[0]
    return QcModel(
        qc_path=qc_path,
        cdmaterials=parse_cdmaterials(qc_path),
        layout=parse_skin_layout(qc_path),
        bonemerge=parse_bonemerge(qc_path),
    )


def is_shared_column(red_name: str, blu_name: str) -> bool:
    """
    Столбец не меняется по команде: в обеих строках стоит один материал.

    Одно правило на сборку и на превью. Регистр в $texturegroup у Valve
    гуляет от файла к файлу, поэтому сравнение регистронезависимое — сборка
    раньше сравнивала строки как есть и на файле с разным регистром сделала бы
    лишний BLU-материал.
    """
    return (red_name or "").strip().lower() == (blu_name or "").strip().lower()


def team_material_map(layout: SkinLayout) -> Dict[str, str]:
    """
    {материал RED: материал BLU} — ПО СТОЛБЦАМ $texturegroup.

    Команда в Source меняет материалы поколоночно, и меняет не обязательно
    все. У hwn2022_alcoholic_automaton четыре столбца, а переключаются два:

        { auto_1      auto      auto_1_blue auto_blue }
        { auto_1_blue auto_blue auto_1_blue auto_blue }

    Столбцы 3-4 в обеих строках одинаковы — это детали, которые синие
    ВСЕГДА (линза), а не командный вариант. Такие материалы отображаются
    сами в себя: потребитель по этому видит, что при смене команды их
    трогать не нужно. Раньше знание жило только в превью, где вместо карты
    брали ОДНУ первую BLU-текстуру и клали её на всю модель.

    Пусто, если второй скин — не команда (стиль bloody/clean или вариант).
    """
    if not selector_spec(layout).team:
        return {}
    red = layout.base_rows[0] if layout.base_rows else []
    blu = layout.second_row
    return {name: (blu[i] if i < len(blu) else name)
            for i, name in enumerate(red)}


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
