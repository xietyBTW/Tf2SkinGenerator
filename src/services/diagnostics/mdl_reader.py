"""Лёгкий парсер заголовка Source-модели (.mdl / studiohdr_t).

Диагностике нужно из готовой модели узнать то, что автор задал в QC и что
«запеклось» в .mdl:
  • version           — совместимость с TF2 (обычно 48/49);
  • material_names    — имена материалов (должны иметь парные VMT);
  • cdmaterials       — папки поиска материалов ($cdmaterials);
  • drawn_materials   — какие из них рисует хоть одна сетка в каком-нибудь
                        скине (в таблице скинов бывают столбцы без сетки:
                        у рук инженера — рука Ганслингера).

Парсим ТОЛЬКО заголовок, таблицы строк и номера материалов сеток — без
геометрии/костей. Всё
защищено границами: на любом непонятном файле возвращаем частичный/пустой
результат, а не исключение.

Смещения полей studiohdr_t (little-endian, int32), выверенные по Source SDK:
    0x04  version
    0xCC  numtextures      0xD0  textureindex     (mstudiotexture_t, 64 байта)
    0xD4  numcdtextures    0xD8  cdtextureindex    (массив int-смещений строк)
    0xDC  numskinref       0xE0  numskinfamilies  0xE4  skinindex (short)
    0xE8  numbodyparts     0xEC  bodypartindex
mstudiobodyparts_t (16 байт): name, nummodels, base, modelindex;
mstudiomodel_t (148 байт): nummeshes @72, meshindex @76;
mstudiomesh_t (116 байт): material @0 — номер столбца таблицы скинов.
mstudiotexture_t: первое поле sznameindex (int) — смещение имени ОТ начала
структуры этого материала.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional

_MAGIC = b"IDST"
_MSTUDIOTEXTURE_SIZE = 64

# Смещения в studiohdr_t.
_OFF_VERSION = 0x04
_OFF_NUM_TEXTURES = 0xCC
_OFF_TEXTURE_INDEX = 0xD0
_OFF_NUM_CDTEXTURES = 0xD4
_OFF_CDTEXTURE_INDEX = 0xD8
_OFF_SKINS = 0xDC
_OFF_BODYPARTS = 0xE8

# Разумные лимиты — защита от мусорных счётчиков в битом файле.
_MAX_ENTRIES = 4096


@dataclass
class MdlHeader:
    """Разобранный заголовок .mdl."""

    version: int = 0
    material_names: List[str] = field(default_factory=list)
    cdmaterials: List[str] = field(default_factory=list)
    # None — сетки не прочитались, и рисуемыми считаются все материалы.
    drawn_materials: Optional[List[str]] = None
    valid: bool = False   # True, если сигнатура IDST на месте


def read_mdl(path: str) -> Optional[MdlHeader]:
    """Читает .mdl с диска. None — если файл не прочитался."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return parse_mdl(data)


def parse_mdl(data: bytes) -> MdlHeader:
    """Разбирает байты .mdl. Никогда не бросает — при проблемах возвращает
    то, что удалось (valid=False, если даже сигнатуры нет)."""
    hdr = MdlHeader()
    if len(data) < 0xDC or data[:4] != _MAGIC:
        return hdr
    hdr.valid = True
    try:
        hdr.version = _i32(data, _OFF_VERSION)
        hdr.material_names = _read_material_names(data)
        hdr.cdmaterials = _read_cdmaterials(data)
        hdr.drawn_materials = _read_drawn_materials(data)
    except (struct.error, IndexError, ValueError):
        # Частичный результат лучше падения — что успели прочитать, то и вернём.
        pass
    return hdr


# ── Внутреннее ──────────────────────────────────────────────────────────── #

def _i32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def _read_cstr(data: bytes, offset: int) -> str:
    """Null-terminated ASCII-строка начиная с offset."""
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("ascii", errors="replace")


def _read_material_names(data: bytes) -> List[str]:
    return [n for n in _texture_names(data) if n]


def _texture_names(data: bytes) -> List[str]:
    """Имена материалов по их номерам в .mdl ('' — имя не прочиталось)."""
    count = _i32(data, _OFF_NUM_TEXTURES)
    base = _i32(data, _OFF_TEXTURE_INDEX)
    if count <= 0 or count > _MAX_ENTRIES or base <= 0:
        return []
    names: List[str] = []
    for i in range(count):
        struct_off = base + i * _MSTUDIOTEXTURE_SIZE
        if struct_off + 4 > len(data):
            break
        name_off = struct_off + _i32(data, struct_off)   # sznameindex относителен структуры
        names.append(_read_cstr(data, name_off))
    return names


def _read_cdmaterials(data: bytes) -> List[str]:
    count = _i32(data, _OFF_NUM_CDTEXTURES)
    base = _i32(data, _OFF_CDTEXTURE_INDEX)
    if count <= 0 or count > _MAX_ENTRIES or base <= 0:
        return []
    dirs: List[str] = []
    for i in range(count):
        ptr_off = base + i * 4
        if ptr_off + 4 > len(data):
            break
        str_off = _i32(data, ptr_off)   # смещение строки от начала файла
        cd = _read_cstr(data, str_off)
        if cd:
            dirs.append(cd)
    return dirs


def _read_drawn_materials(data: bytes) -> Optional[List[str]]:
    """Материалы без тех, что стоят только в столбцах скинов без сетки.

    Материал вне таблицы скинов (замена материала у LOD) сетки не знают, но
    игра его рисует: такой проверяется, как и раньше.
    """
    num_skinref, num_families, skin_index = struct.unpack_from("<iii", data, _OFF_SKINS)
    num_bodyparts, bodypart_index = struct.unpack_from("<ii", data, _OFF_BODYPARTS)
    if not (0 < num_skinref <= _MAX_ENTRIES and 0 < num_families <= _MAX_ENTRIES
            and 0 <= num_bodyparts <= _MAX_ENTRIES):
        return None
    columns = set()
    for bp in range(num_bodyparts):
        bpo = bodypart_index + bp * 16
        _, num_models, _, model_index = struct.unpack_from("<iiii", data, bpo)
        if not 0 <= num_models <= _MAX_ENTRIES:
            return None
        for m in range(num_models):
            mo = bpo + model_index + m * 148
            num_meshes, mesh_index = struct.unpack_from("<ii", data, mo + 72)
            if not 0 <= num_meshes <= _MAX_ENTRIES:
                return None
            for k in range(num_meshes):
                columns.add(_i32(data, mo + mesh_index + k * 116))
    if not columns:
        return None     # сеток не нашлось: судить не по чему
    table = [[struct.unpack_from("<h", data, skin_index + (f * num_skinref + c) * 2)[0]
              for c in range(num_skinref)] for f in range(num_families)]
    drawn = {row[c] for row in table for c in columns if 0 <= c < num_skinref}
    idle = {i for row in table for i in row} - drawn
    return [n for i, n in enumerate(_texture_names(data)) if n and i not in idle]
