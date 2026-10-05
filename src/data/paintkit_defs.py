"""
War Paint из игры: рецепты раскраски оружия (`tf/scripts/protodefs/proto_defs.vpd`).

Рецепт — дерево операций над текстурами (`texture_lookup`, `combine_*`,
`select`, `apply_sticker`), которое игра собирает компоновщиком прямо во
время игры и кладёт на оружие прокси `WeaponSkin`. Здесь рецепт только
ЧИТАЕТСЯ: файл подписан (`proto_defs.vpd.sig`), и правленый игра не
запустит. Собирает картинку `services/paintkit_compositor.py`.

Формат файла — блоки `[тип u32][кол-во u32]`, за ними сообщения
`[размер u32][protobuf]`. Схема — `tf_proto_def_messages.proto` из
source-sdk-2013 (TF2 SDK); декодер свой, без protoc: нужны десяток типов
сообщений, а зависимость ради них не окупается.

Значения переменных подставляются так же, как в `econ_paintkit.cpp`
(`CPaintKitDefinition::GetItemPaintKitDefinitionKV`): переменные шаблона
War Paint, поверх — переменные пушки в War Paint, заголовка описания пушки и
выбранного уровня износа. Переопределять можно только переменные с
`inherit` (по умолчанию да).
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Типы определений (enum ProtoDefTypes).
_T_OPERATION = 7
_T_ITEM_DEF = 8
_T_PAINTKIT = 9
_T_HEADER_ONLY = 10

#: Поля CMsgPaintKit_OperationStage → вид узла.
STAGES = {1: 'texture_lookup', 2: 'combine_add', 3: 'combine_lerp',
          4: 'combine_multiply', 5: 'select', 6: 'apply_sticker'}

#: Поля-переменные стадий (номер поля → имя), см. .proto.
_TEXTURE_FIELDS = {1: 'texture', 2: 'texture_red', 3: 'texture_blue',
                   4: 'adjust_black', 5: 'adjust_offset', 6: 'adjust_gamma',
                   7: 'rotation', 8: 'translate_u', 9: 'translate_v',
                   10: 'scale_uv', 11: 'flip_u', 12: 'flip_v'}
_COMBINE_FIELDS = {1: 'adjust_black', 2: 'adjust_offset', 3: 'adjust_gamma',
                   4: 'rotation', 5: 'translate_u', 6: 'translate_v',
                   7: 'scale_uv', 8: 'flip_u', 9: 'flip_v'}
_STICKER_STAGE_FIELDS = {2: 'dest_tl', 3: 'dest_tr', 4: 'dest_bl',
                         5: 'adjust_black', 6: 'adjust_offset', 7: 'adjust_gamma'}
_STICKER_FIELDS = {1: 'base', 2: 'weight', 3: 'spec'}

#: Уровни износа War Paint по порядку (1…5 в рецепте).
WEAR_LEVELS = ('Factory New', 'Minimal Wear', 'Field-Tested',
               'Well-Worn', 'Battle Scarred')


# ── protobuf wire format ───────────────────────────────────────────────── #

def _varint(b: bytes, i: int) -> Tuple[int, int]:
    result = shift = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return result, i


def _fields(b: bytes) -> List[Tuple[int, object]]:
    """[(номер поля, значение)]: varint → int, length-delimited → bytes."""
    out, i = [], 0
    while i < len(b):
        key, i = _varint(b, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _varint(b, i)
        elif wire == 2:
            n, i = _varint(b, i)
            val, i = b[i:i + n], i + n
        elif wire == 5:
            val, i = b[i:i + 4], i + 4
        elif wire == 1:
            val, i = b[i:i + 8], i + 8
        else:
            raise ValueError(f'wire type {wire}')
        out.append((num, val))
    return out


def _first(fs, num, default=None):
    return next((v for n, v in fs if n == num), default)


def _all(fs, num):
    return [v for n, v in fs if n == num]


def _str(v) -> str:
    return v.decode('utf-8', 'replace') if isinstance(v, bytes) else ''


def _var_field(b: bytes) -> Tuple[str, str]:
    """CMsgVarField → (имя переменной или '', значение по умолчанию)."""
    fs = _fields(b)
    name = _str(_first(fs, 1, b''))
    value = ''
    for num, v in fs:
        if num == 9:
            value = _str(v)
        elif num == 2 and isinstance(v, bytes):
            value = repr(struct.unpack('<f', v)[0])
        elif num in (4, 6, 8) and isinstance(v, int):
            value = str(v)
    return name, value


def _def_id(b: bytes) -> Tuple[int, int]:
    """CMsgProtoDefID → (defindex, тип)."""
    fs = _fields(b)
    return int(_first(fs, 1, 0)), int(_first(fs, 2, 0))


@dataclass
class Header:
    defindex: int
    name: str
    prefabs: List[int]
    tags: List[str]
    #: {имя: (значение, можно ли переопределить)}
    variables: Dict[str, Tuple[str, bool]]


def _header(b: bytes) -> Header:
    fs = _fields(b)
    variables = {}
    for v in _all(fs, 6):
        vf = _fields(v)
        name = _str(_first(vf, 1, b''))
        variables[name] = (_str(_first(vf, 3, b'')), bool(_first(vf, 2, 1)))
    return Header(defindex=int(_first(fs, 1, 0)), name=_str(_first(fs, 2, b'')),
                  prefabs=[_def_id(p)[0] for p in _all(fs, 3)],
                  tags=[_str(t) for t in _all(fs, 4)], variables=variables)


# ── Определения ─────────────────────────────────────────────────────────── #

@dataclass
class ItemDef:
    """Описание пушки для War Paint (CMsgPaintKit_ItemDefinition)."""
    header: Header
    item_index: int                     # номер предмета в items_game
    #: Уровни износа: [(шаблон операций или None, [(переменная, значение)])]
    wears: List[Tuple[Optional[int], List[Tuple[str, str]]]]


@dataclass
class KitItem:
    """Пушка в War Paint (CMsgPaintKit_Definition.Item)."""
    item_def: int
    can_apply: bool
    material_override: str
    variables: List[Tuple[str, str]]


@dataclass
class PaintKit:
    header: Header
    loc_token: str
    operation: Optional[int]
    has_team_textures: bool
    items: List[KitItem] = field(default_factory=list)


def _kit_item(b: bytes) -> Optional[KitItem]:
    fs = _fields(b)
    ref = _first(fs, 1)
    if ref is None:
        return None
    data = _fields(_first(fs, 5, b''))
    return KitItem(item_def=_def_id(ref)[0],
                   can_apply=bool(_first(data, 2, 1)),
                   material_override=_str(_first(data, 3, b'')),
                   variables=[_var_field(v) for v in _all(data, 4)])


class PaintKitDefs:
    """Разобранный proto_defs.vpd: War Paint, описания пушек, шаблоны операций."""

    def __init__(self, blob: bytes):
        self.operations: Dict[int, bytes] = {}
        self.item_defs: Dict[int, ItemDef] = {}
        self.kits: Dict[int, PaintKit] = {}
        self.header_only: Dict[int, Header] = {}
        off = 0
        while off < len(blob):
            kind, count = struct.unpack_from('<II', blob, off)
            off += 8
            for _ in range(count):
                (size,) = struct.unpack_from('<I', blob, off)
                msg = blob[off + 4:off + 4 + size]
                off += 4 + size
                self._add(kind, msg)

    def _add(self, kind: int, msg: bytes) -> None:
        if kind not in (_T_OPERATION, _T_ITEM_DEF, _T_PAINTKIT, _T_HEADER_ONLY):
            return
        fs = _fields(msg)
        header = _header(_first(fs, 1, b''))
        if kind == _T_OPERATION:
            self.operations[header.defindex] = msg
        elif kind == _T_HEADER_ONLY:
            self.header_only[header.defindex] = header
        elif kind == _T_ITEM_DEF:
            wears = []
            for d in _all(fs, 4):
                dfs = _fields(d)
                op = _first(dfs, 1)
                wears.append((_def_id(op)[0] if op else None,
                              [_var_field(v) for v in _all(dfs, 2)]))
            self.item_defs[header.defindex] = ItemDef(
                header=header, item_index=int(_first(fs, 2, 0)), wears=wears)
        else:
            op = _first(fs, 3)
            kit = PaintKit(header=header, loc_token=_str(_first(fs, 2, b'')),
                           operation=_def_id(op)[0] if op else None,
                           has_team_textures=bool(_first(fs, 4, 0)))
            # Поле 5 — список старых декорированных пушек, 6…50 — по полю на
            # пушку War Paint. Порядок полей неважен: пушку ищут по описанию.
            for num, val in fs:
                if num >= 5 and isinstance(val, bytes):
                    item = _kit_item(val)
                    if item is not None:
                        kit.items.append(item)
            self.kits[header.defindex] = kit

    # ── Рецепт ──────────────────────────────────────────────────────────── #

    def item_variables(self, item_def: ItemDef) -> Dict[str, str]:
        """Переменные заголовка описания пушки вместе с префабами (префаб — под своими)."""
        merged: Dict[str, str] = {}
        for pid in item_def.header.prefabs:
            prefab = self.header_only.get(pid)
            if prefab:
                merged.update({k: v for k, (v, _inh) in prefab.variables.items()})
        merged.update({k: v for k, (v, _inh) in item_def.header.variables.items()})
        return merged

    def variables(self, kit: PaintKit, item: KitItem,
                  wear: int) -> Optional[Tuple[int, Dict[str, str]]]:
        """(операция, значения переменных) War Paint на пушке при износе
        ``wear`` — то, что рецепт подставляет в узлы. None — рецепта нет."""
        item_def = self.item_defs.get(item.item_def)
        if item_def is None or not item_def.wears:
            return None
        index = min(max(wear, 1), len(item_def.wears)) - 1
        wear_op, wear_vars = item_def.wears[index]

        op_id, base_header = kit.operation, kit.header
        if wear_op is not None and wear_op in self.operations:
            op_id = wear_op
            base_header = _header(_first(_fields(self.operations[wear_op]), 1, b''))
        if op_id is None or op_id not in self.operations:
            return None

        # {имя: [значение, можно переопределить]} — как itemVarDict в игре.
        values = {k: [v, inh] for k, (v, inh) in base_header.variables.items()}

        def override(name: str, value: str) -> None:
            slot = values.get(name)
            if slot is not None and slot[1]:
                slot[0] = value

        for name, value in item.variables:
            override(name, value)
        for name, value in self.item_variables(item_def).items():
            override(name, value)
        for name, value in wear_vars:
            override(name, value)

        return op_id, {k: v for k, (v, _inh) in values.items()}

    def recipe(self, kit: PaintKit, item: KitItem, wear: int,
               forced: Optional[Dict[str, str]] = None,
               strip_stickers: bool = False) -> Optional[dict]:
        """
        Дерево операций War Paint на пушке при износе ``wear`` (1…5) с
        подставленными значениями переменных. None — рецепта нет.

        ``forced`` — значения поверх всего, без оглядки на inherit: так
        универсальный режим подменяет входы пушки своими (альбедо, группы…).
        ``strip_stickers`` — наклейки убираются (их место задано в развёртке
        пушки-донора, на чужой модели оно ничего не значит).
        """
        found = self.variables(kit, item, wear)
        if found is None:
            return None
        op_id, resolved = found
        resolved.update(forced or {})
        roots = self._nodes(self.operations[op_id], 2, resolved, depth=0)
        if strip_stickers:
            roots = [_without_stickers(r) for r in roots]
        if not roots:
            return None
        # Корень у рецепта верхнего уровня один; несколько бывает только у
        # вложенных шаблонов (ao), и там они становятся детьми родителя.
        return roots[0] if len(roots) == 1 else {
            'type': 'combine_multiply', 'fields': {}, 'nodes': roots}

    def _nodes(self, msg: bytes, field_no: int, values: Dict[str, str],
               depth: int) -> List[dict]:
        """Узлы (CMsgPaintKit_OperationNode) из поля ``field_no`` сообщения."""
        if depth > 32:
            raise ValueError('слишком глубокая вложенность шаблонов')
        out = []
        for node in _all(_fields(msg), field_no):
            nfs = _fields(node)
            stage = _first(nfs, 1)
            ref = _first(nfs, 2)
            if stage is not None:
                parsed = self._stage(stage, values, depth)
                if parsed is not None:
                    out.append(parsed)
            elif ref is not None:
                # Шаблон подставляется своими узлами прямо в родителя
                # (OperationToKV по CMsgProtoDefID).
                sub = self.operations.get(_def_id(ref)[0])
                if sub is not None:
                    out.extend(self._nodes(sub, 2, values, depth + 1))
        return out

    def _stage(self, stage: bytes, values: Dict[str, str], depth: int) -> Optional[dict]:
        for num, body in _fields(stage):
            kind = STAGES.get(num)
            if kind is None or not isinstance(body, bytes):
                continue
            fs = _fields(body)

            def var(b: bytes) -> str:
                name, default = _var_field(b)
                return values.get(name, default) if name else default

            if kind == 'texture_lookup':
                return {'type': kind, 'nodes': [],
                        'fields': {n: var(v) for f, v in fs
                                   if (n := _TEXTURE_FIELDS.get(f))}}
            if kind == 'select':
                groups = _first(fs, 1)
                return {'type': kind, 'nodes': [],
                        'fields': {'groups': var(groups) if groups else ''},
                        'select': [var(v) for v in _all(fs, 2)]}
            if kind == 'apply_sticker':
                stickers = []
                for s in _all(fs, 1):
                    sfs = _fields(s)
                    stickers.append({n: var(v) for f, v in sfs
                                     if (n := _STICKER_FIELDS.get(f))})
                return {'type': kind, 'stickers': stickers,
                        'fields': {n: var(v) for f, v in fs
                                   if (n := _STICKER_STAGE_FIELDS.get(f))},
                        'nodes': self._nodes(body, 9, values, depth + 1)}
            return {'type': kind,
                    'fields': {n: var(v) for f, v in fs
                               if (n := _COMBINE_FIELDS.get(f))},
                    'nodes': self._nodes(body, 11, values, depth + 1)}
        return None


def _without_stickers(node: dict) -> dict:
    """Узел без наклеек: наклейка заменяется поверхностью, на которую ложилась."""
    while node.get('type') == 'apply_sticker' and node.get('nodes'):
        node = node['nodes'][0]
    return dict(node, nodes=[_without_stickers(n) for n in node.get('nodes') or []])


# ── Универсальный режим: War Paint на оружии, у которого его нет ───────── #

#: Шаблон, нарисованный под одну развёртку: на чужую модель не переносится.
_UV_BOUND_TEMPLATES = ('custom_uv',)

#: Пушки-доноры по порядку предпочтения: у них средняя плотность развёртки,
#: и масштаб узоров с них на чужой модели выглядит естественно.
_DONORS = ('c_scattergun.mdl', 'c_shotgun.mdl', 'c_smg.mdl', 'c_rocketlauncher.mdl',
           'c_pistol.mdl', 'c_grenadelauncher.mdl', 'c_minigun.mdl')


def template_layers(defs: PaintKitDefs, kit: PaintKit) -> Tuple[List[int], bool]:
    """(слои узора по порядку, «поверх альбедо») шаблона War Paint.

    У обычного шаблона первый слой — основа (лежит везде, где не выбран
    другой), у «over_albedo» основа — сама текстура пушки, а слои кладутся
    только на выбранные группы.
    """
    import re

    op = defs.operations.get(kit.operation) if kit.operation is not None else None
    if op is None:
        return [], False
    header = _header(_first(_fields(op), 1, b''))
    layers = sorted({int(m.group(1)) for name in header.variables
                     if (m := re.match(r'texture_layer_(\d+)$', name))})
    return layers, 'over_albedo' in header.name


def generic_kits(tf2_root: str, lang: str = 'ru') -> List[dict]:
    """
    War Paint, которые можно положить на любое оружие: [{id, name, item,
    wears, team, generic}] по алфавиту. ``item`` — описание пушки-донора.
    """
    defs = load(tf2_root)
    if defs is None:
        return []
    models = item_models(tf2_root)
    rank = {m: i for i, m in enumerate(_DONORS)}
    out = []
    for kit in defs.kits.values():
        if kit.operation is None or kit.operation not in defs.operations:
            continue
        header = _header(_first(_fields(defs.operations[kit.operation]), 1, b''))
        if header.name in _UV_BOUND_TEMPLATES or 'weapon_groups' not in header.variables:
            continue
        donors = []
        for item in kit.items:
            idef = defs.item_defs.get(item.item_def)
            model = models.get(idef.item_index) if idef else None
            if idef and item.can_apply and idef.wears and model:
                donors.append((rank.get(model, len(rank)), item.item_def, len(idef.wears)))
        if not donors:
            continue
        _rank, donor, wears = min(donors)
        out.append({'id': kit.header.defindex, 'name': kit_name(tf2_root, kit, lang),
                    'item': donor, 'wears': wears, 'team': kit.has_team_textures,
                    'generic': True})
    out.sort(key=lambda k: k['name'].lower())
    return out


# ── Каталог: какие War Paint ложатся на модель ─────────────────────────── #

_MODELS: Dict[Tuple[str, int], Dict[int, str]] = {}


def item_models(tf2_root: str) -> Dict[int, str]:
    """{номер предмета: имя файла модели (c_scattergun.mdl)}."""
    return {i: p.rsplit('/', 1)[-1] for i, p in item_model_paths(tf2_root).items()}


def item_model_path(tf2_root: str, defs: 'PaintKitDefs', item_def: int) -> str:
    """Модель, на которую игра кладёт War Paint этого описания пушки.

    Не путь из таблицы оружия приложения: у двадцати с лишним пушек две
    версии модели (старая c_items и мастерская), War Paint — у мастерской.
    """
    idef = defs.item_defs.get(int(item_def))
    return item_model_paths(tf2_root).get(idef.item_index, '') if idef else ''


def item_model_paths(tf2_root: str) -> Dict[int, str]:
    """{номер предмета: путь модели в игре (models/…/c_scattergun.mdl)} из items_game."""
    path = os.path.join(tf2_root, 'tf', 'scripts', 'items', 'items_game.txt')
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return {}
    cached = _MODELS.get(key)
    if cached is None:
        from src.data import items_game_kv as kv
        game = kv.ItemsGame.load(path)
        if game is None:
            return {}
        cached = {}
        for idx, block in game.items:
            model = game.inherited(block, 'model_player')
            if model and str(idx).isdigit():
                cached[int(idx)] = model.replace('\\', '/').lower()
        _MODELS.clear()
        _MODELS[key] = cached
    return cached


def _names(tf2_root: str, lang: str) -> Dict[str, str]:
    from src.data.hats_parser import parse_localization
    return parse_localization(tf2_root, 'russian' if lang == 'ru' else 'english',
                              stem='tf_proto_obj_defs')


def kit_name(tf2_root: str, kit: PaintKit, lang: str = 'ru') -> str:
    """Название War Paint на языке интерфейса (английское, если перевода нет)."""
    for names in (_names(tf2_root, lang), _names(tf2_root, 'en')):
        # В файле названия в кавычках-ёлочках самой игры: \"Night Owl\".
        text = (names.get(kit.loc_token) or '').strip().strip('"').strip()
        if text and not text[0].isdigit():
            return text
    return kit.header.name


def for_model(tf2_root: str, model: str, lang: str = 'ru') -> List[dict]:
    """
    War Paint, которые игра кладёт на модель ``model`` (имя или путь .mdl):
    [{id, name, item, wears, team}] по алфавиту.

    ``item`` — номер описания пушки внутри War Paint: у одной модели их
    бывает несколько (обычная и «улучшаемая» версии предмета), берём первое.
    """
    defs = load(tf2_root)
    if defs is None:
        return []
    want = str(model or '').replace('\\', '/').rsplit('/', 1)[-1].lower()
    if not want.endswith('.mdl'):
        want += '.mdl'
    models = item_models(tf2_root)
    out = []
    for kit in defs.kits.values():
        for item in kit.items:
            item_def = defs.item_defs.get(item.item_def)
            if (item_def is None or not item.can_apply or not item_def.wears
                    or models.get(item_def.item_index) != want):
                continue
            out.append({'id': kit.header.defindex,
                        'name': kit_name(tf2_root, kit, lang),
                        'item': item.item_def,
                        'wears': len(item_def.wears),
                        'team': kit.has_team_textures,
                        # Шаблонный War Paint раскладывается по группам —
                        # раскладку можно переделать; ручной (рецепт под одну
                        # пушку) — нет.
                        'layered': bool(template_layers(defs, kit)[0])})
            break
    out.sort(key=lambda k: k['name'].lower())
    return out


def find_item(defs: PaintKitDefs, kit_id: int, item_def: int) -> Tuple[Optional[PaintKit], Optional[KitItem]]:
    kit = defs.kits.get(int(kit_id))
    item = next((i for i in kit.items if i.item_def == int(item_def)), None) if kit else None
    return kit, item


# ── Загрузка ────────────────────────────────────────────────────────────── #

_CACHE: Dict[Tuple[str, int], PaintKitDefs] = {}


def vpd_path(tf2_root: str) -> str:
    return os.path.join(tf2_root, 'tf', 'scripts', 'protodefs', 'proto_defs.vpd')


def load(tf2_root: str) -> Optional[PaintKitDefs]:
    """Разобранный proto_defs.vpd игры (кэш по mtime) или None, если файла нет."""
    path = vpd_path(tf2_root)
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return None
    defs = _CACHE.get(key)
    if defs is None:
        with open(path, 'rb') as f:
            defs = PaintKitDefs(f.read())
        _CACHE.clear()
        _CACHE[key] = defs
        logger.info(f'[paintkit] {len(defs.kits)} War Paint, '
                    f'{len(defs.item_defs)} описаний пушек')
    return defs
