"""
Единственная точка «имя материала → картинка»: VMT → $basetexture → VTF → PNG.

Эта цепочка нужна всем: превью оружия, шапок, персонажей, рук, редактору
частиц, экспорту текстур. Раньше она была переписана в каждом из них своими
руками — только в одном воркере превью насчитывалось двадцать циклов «перебрать
паки», одиннадцать повторных `glob(*.qc)` и пять почти одинаковых стратегий
поиска. Копии расходились: одна применяла командную краску, другая нет; одна
знала про поколоночные скины, другая брала первую попавшуюся текстуру.

Здесь цепочка одна, и у неё три свойства, которых у копий не было:

* КЭШ на прогон. Один и тот же материал в модели встречается по несколько раз
  (RED-строка, BLU-строка, карточки, 3D) — VPK читается один раз.
* КРАСКА применяется здесь же. У двух третей шапок цвет команды лежит не в
  текстуре, а в VMT ($blendtintbybasealpha) — забыть её означает показать
  чёрные пятна, и именно так и забывали.
* ПРОЗРАЧНОСТЬ решения. Результат несёт, откуда он взялся (какой VMT, какая
  текстура, какая краска) — по нему сравнивают материалы между собой,
  например чтобы понять, отличается ли BLU-скин от RED вообще.

Модуль без Qt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.services import vmt_parse, vmt_tint
from src.services.game_vpk_reader import GameVpkReader
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedMaterial:
    """Что удалось узнать о материале и во что он превратился."""

    name: str                          # имя материала как в модели
    vmt_path: Optional[str] = None     # путь VMT внутри VPK
    basetexture: Optional[str] = None  # значение $basetexture (rel. materials/)
    png_path: Optional[str] = None     # готовая картинка для превью
    tint: Optional[vmt_tint.TintSpec] = None
    shader: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.png_path)

    @property
    def look(self) -> tuple:
        """Из чего складывается вид материала: текстура + краска.

        По этой паре материалы сравнивают между собой (`same_look`): у 46
        стоковых шапок BLU-скин отличается от RED только именем.
        """
        return (self.basetexture, self.tint)

    def same_look(self, other: Optional["ResolvedMaterial"]) -> bool:
        if other is None:
            return False
        return vmt_tint.same_material_look(self.look, other.look)


class MaterialResolver:
    """
    Резолвер материалов поверх открытых VPK. Один экземпляр на прогон.

    Args:
        reader: GameVpkReader с уже открытыми архивами.
        out_dir: куда класть PNG.
        apply_tint: впечатывать ли командную краску из VMT (для превью — да;
            для экспорта исходной текстуры — нет, в игре её накладывает движок).
    """

    def __init__(self, reader: GameVpkReader, out_dir: str,
                 apply_tint: bool = True):
        self._reader = reader
        self._out_dir = out_dir
        self._apply_tint = apply_tint
        self._cache: Dict[tuple, ResolvedMaterial] = {}
        self._described: Dict[tuple, ResolvedMaterial] = {}

    # ── Публичное ────────────────────────────────────────────────────────── #

    def resolve(self, mat_name: str, cdmaterials: List[str],
                out_name: Optional[str] = None) -> ResolvedMaterial:
        """Материал → ResolvedMaterial (всегда объект, даже если ничего нет)."""
        key = (mat_name.strip().lower(), tuple(cdmaterials or ()), out_name)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self._resolve_uncached(mat_name, cdmaterials, out_name)
        self._cache[key] = result
        return result

    def resolve_many(self, mat_names: List[str],
                     cdmaterials: List[str]) -> Dict[str, ResolvedMaterial]:
        """{имя в нижнем регистре: результат} только для найденных картинок."""
        out: Dict[str, ResolvedMaterial] = {}
        for name in mat_names or []:
            res = self.resolve(name, cdmaterials)
            if res.ok:
                out[name.strip().lower()] = res
        return out

    def describe(self, mat_name: str,
                 cdmaterials: List[str]) -> ResolvedMaterial:
        """Что за материал — без превращения в картинку.

        Отдельно от resolve(), потому что не всем нужен PNG: экспорт отдаёт
        сырой VTF, а покраску оружия достаточно знать по VMT.
        """
        key = (mat_name.strip().lower(), tuple(cdmaterials or ()))
        cached = self._described.get(key)
        if cached is None:
            cached = self._describe_uncached(mat_name, cdmaterials)
            self._described[key] = cached
        return cached

    def tint_for(self, mat_name: str,
                 cdmaterials: List[str]) -> Optional[vmt_tint.TintSpec]:
        """Только краска материала — без картинки.

        Нужна там, где текстуру нашли своим путём (у оружия она часто лежит
        по угадываемому пути, минуя VMT), а покрасить всё равно надо.
        """
        return self.describe(mat_name, cdmaterials).tint

    def vtf_bytes(self, mat_name: str,
                  cdmaterials: List[str]) -> Optional[bytes]:
        """Сырые байты VTF материала (для экспорта — без краски и без PNG).

        Сами байты не кэшируются: это мегабайты на материал, а нужны они
        обычно один раз. Кэшируется разбор VMT, который к ним ведёт.
        """
        info = self.describe(mat_name, cdmaterials)
        if not info.basetexture:
            return None
        return self._reader.find_vtf_for_basetexture(info.basetexture)

    def texture_map(self, mat_names: List[str],
                    cdmaterials: List[str]) -> Dict[str, str]:
        """{имя материала: путь PNG} — то, что ждут превью и карточки."""
        return {name: res.png_path
                for name, res in self.resolve_many(mat_names, cdmaterials).items()}

    # ── Внутреннее ───────────────────────────────────────────────────────── #

    def _describe_uncached(self, mat_name: str,
                           cdmaterials: List[str]) -> ResolvedMaterial:
        mat_lower = mat_name.strip().lower()
        vmt_info = self._find_vmt(mat_lower, cdmaterials)
        if vmt_info is None:
            logger.info(
                f"[mat] VMT не найден: '{mat_lower}' (cdmaterials={cdmaterials})")
            return ResolvedMaterial(name=mat_lower)

        vmt_path, vmt_text = vmt_info
        doc = vmt_parse.parse(vmt_text)
        basetexture = doc.path("basetexture")
        if not basetexture:
            logger.info(f"[mat] нет $basetexture в {vmt_path}")
        return ResolvedMaterial(
            name=mat_lower, vmt_path=vmt_path, basetexture=basetexture,
            tint=vmt_tint.parse_tint(vmt_text), shader=doc.shader)

    def _resolve_uncached(self, mat_name: str, cdmaterials: List[str],
                          out_name: Optional[str]) -> ResolvedMaterial:
        info = self.describe(mat_name, cdmaterials)
        if not info.basetexture:
            return info

        vtf_data = self._reader.find_vtf_for_basetexture(info.basetexture)
        if not vtf_data:
            logger.info(
                f"[mat] VTF не найден: {info.basetexture} (VMT={info.vmt_path})")
            return info

        png_path = self._to_png(vtf_data, out_name or info.name)
        if png_path and self._apply_tint:
            vmt_tint.apply_to_png(png_path, info.tint)
        return ResolvedMaterial(
            name=info.name, vmt_path=info.vmt_path,
            basetexture=info.basetexture, png_path=png_path,
            tint=info.tint, shader=info.shader)

    def _find_vmt(self, mat_lower: str, cdmaterials: List[str]):
        """VMT материала: сначала по $cdmaterials, потом по пути внутри имени.

        Второй случай — материалы, у которых в модели записан полный путь
        (`models/workshop/.../hat`), а не голое имя.
        """
        found = self._reader.find_vmt(cdmaterials or [], mat_lower)
        if found:
            return found
        if "/" in mat_lower or "\\" in mat_lower:
            rel = mat_lower.replace("\\", "/").strip("/")
            data = self._reader.read(f"materials/{rel}.vmt")
            if data:
                return f"materials/{rel}.vmt", data.decode("utf-8", "replace")
        return None

    def _to_png(self, vtf_data: bytes, name: str) -> Optional[str]:
        from src.services import vtf_preview_service as vps

        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        os.makedirs(self._out_dir, exist_ok=True)
        return vps.vtf_bytes_to_png(
            vtf_data, os.path.join(self._out_dir, f"{safe}.png"), self._out_dir)
