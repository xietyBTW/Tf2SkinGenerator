"""Контекст осмотренного мода — распарсенное содержимое распакованного VPK.

Проверки (checks.py) работают ТОЛЬКО с этим контекстом (чистые функции), поэтому
их легко тестировать: собрал InspectedMod вручную/из временной папки — прогнал
проверку — сверил находки. Никакого доступа к диску внутри самих проверок.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from src.services.diagnostics.mdl_reader import MdlHeader

# Параметры VMT, чьё значение — текстура, которую мод обычно ВЕЗЁТ С СОБОЙ.
# Намеренно НЕ включаем часто-общие с игрой ($detail, $lightwarptexture,
# $phong*texture): реальные рескины ссылаются на игровые lightwarp/detail и не
# кладут их в мод — иначе была бы гора ложных предупреждений.
TEXTURE_PARAMS = (
    "basetexture", "basetexture2", "bumpmap",
    "selfillummask", "envmapmask", "blendmodulatetexture",
)

# Пути-префиксы общих игровых ассетов: даже если такой путь попал в отслеживаемый
# параметр, его отсутствие в моде — норма (берётся из игры), не предупреждаем.
_SHARED_PREFIXES = (
    "models/lightwarps/", "detail/", "effects/", "dev/", "vgui/", "shadertest/",
)

_KV_RE = re.compile(r'(?im)^\s*"?\$(\w+)"?\s+(?:"([^"]*)"|(\S+))')


def normalize_material_path(value: str) -> str:
    """Приводит путь материала/текстуры к каноничному виду: прямые слеши,
    нижний регистр, без крайних слешей и расширения."""
    v = value.strip().replace("\\", "/").lower().strip("/")
    for ext in (".vtf", ".vmt"):
        if v.endswith(ext):
            v = v[: -len(ext)]
    return v


@dataclass
class VmtInfo:
    """Разобранный VMT."""

    rel_path: str                       # "materials/…/x.vmt" (lowercase, '/')
    content: str
    shader: str = ""                    # первый токен (unlitgeneric/vertexlitgeneric)
    params: Dict[str, str] = field(default_factory=dict)  # $param → value (lower key)

    def texture_refs(self) -> Dict[str, str]:
        """{param: normalized_path} только для текстур, которые мод должен нести
        сам (не спец-значения и не общие игровые ассеты)."""
        out: Dict[str, str] = {}
        for p in TEXTURE_PARAMS:
            if p not in self.params:
                continue
            val = self.params[p].strip()
            low = val.lower()
            # env_cubemap / рантайм-текстуры / пустые — не файлы мода.
            if not val or low == "env_cubemap" or low.startswith("_rt_"):
                continue
            norm = normalize_material_path(val)
            if any(norm.startswith(pref) for pref in _SHARED_PREFIXES):
                continue   # общий игровой ассет — отсутствие в моде это норма
            out[p] = "materials/" + norm
        return out


@dataclass
class MdlInfo:
    """Модель + наличие обязательных спутников (.vvd/.vtx)."""

    rel_path: str        # "models/…/x.mdl" (lowercase, '/')
    header: MdlHeader
    has_vvd: bool = False
    has_vtx: bool = False


@dataclass
class InspectedMod:
    """Полный слепок распакованного мода для проверок."""

    root: Path
    vmts: List[VmtInfo] = field(default_factory=list)
    vtf_rel: Set[str] = field(default_factory=set)   # {"materials/…/x" (без .vtf)}
    #: {"materials/…/x" (без .vtf): (width, height)} — размеры VTF (для POT-чека).
    vtf_sizes: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    #: VTF с непрочитанным заголовком (битые/пустые), rel без .vtf.
    bad_vtf: Set[str] = field(default_factory=set)
    mdls: List[MdlInfo] = field(default_factory=list)
    all_rel: Set[str] = field(default_factory=set)   # все файлы, rel, lowercase
    top_entries: List[str] = field(default_factory=list)  # имена в корне мода
    #: Пути (rel, lowercase) из ДРУГИХ включённых модов в tf/custom — для поиска
    #: конфликтов. Пусто, если путь к TF2 не задан.
    external_paths: Set[str] = field(default_factory=set)

    def has_vtf(self, materials_rel_no_ext: str) -> bool:
        """Есть ли VTF по каноничному пути 'materials/…/name' (без .vtf)."""
        return materials_rel_no_ext in self.vtf_rel

    def vmt_rel_paths(self) -> Set[str]:
        """Множество путей всех VMT (для проверки «модель ждёт материал»)."""
        return {v.rel_path for v in self.vmts}

    def top_dirs(self) -> Set[str]:
        """Верхнеуровневые сегменты путей (materials/models/… или обёртка)."""
        return {rel.split("/", 1)[0] for rel in self.all_rel}


def parse_vmt(rel_path: str, content: str) -> VmtInfo:
    """Разбирает текст VMT в VmtInfo (шейдер + $-параметры). Не валидирует."""
    info = VmtInfo(rel_path=rel_path, content=content)
    # Шейдер — первый непустой не-комментарий токен в кавычках или без.
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        m = re.match(r'"?([A-Za-z][\w]*)"?', s)
        if m:
            info.shader = m.group(1).lower()
        break
    for m in _KV_RE.finditer(content):
        key = m.group(1).lower()
        val = m.group(2) if m.group(2) is not None else (m.group(3) or "")
        info.params.setdefault(key, val)
    return info
