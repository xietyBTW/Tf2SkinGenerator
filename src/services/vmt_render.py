"""
Как материал РИСУЕТСЯ: прозрачность, смешивание, отсечение граней.

Соседний модуль `vmt_tint` достаёт из VMT краску команды; здесь — вторая
половина того же вопроса «что игрок реально видит». Превью до сих пор рисовало
каждый меш непрозрачным, и стекло банки Мутировавшего молока превращалось в
серый бублик: у него в VMT стоит `$additive 1`, а базовая текстура — пузырьковый
шлем пиро, которая без смешивания читается как пластик.

По стоку (2005 уникальных материалов оружия и шапок):

    $additive     101      $nocull      25
    $translucent   98      $alpha<1      2
    $alphatest     35

То есть 236 материалов требуют смешивания, а `$nocull` объявлен всего у 25 —
остальные в игре односторонние.

ПРО БЛИК. `$phong` стоит у 1972 материалов, и соблазн добавить его велик, но в
Source он ВСЕГДА ограничен маской: блестит ствол, а не приклад. Маска лежит в
альфе бампмапа (991 материал стока), в альфе базовой текстуры при
`$basemapalphaphongmask` (515) или в exp-текстуре (19); у 475 её нет вовсе.
Блик без маски покрывает модель ровной белёсой плёнкой — «серебряная оболочка»,
и именно так этот модуль однажды и сделал. То же с `$envmap`: в модельном VMT
он означает «отражай кубмап КАРТЫ», а у вьювера карты нет, и подставленный
вместо неё градиент просто размазывает свой цвет по текстуре.

Поэтому блик и отражение здесь не разбираются. Захочется вернуть — только
вместе с настоящей маской из текстуры, иначе получится ровно то же серебро.

Модуль без Qt и без three.js — чистый разбор.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.services import vmt_parse
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Режимы смешивания, понятные вьюверу.
BLEND_OPAQUE = "opaque"
BLEND_ALPHA = "alpha"      # $translucent — обычная альфа-прозрачность
BLEND_ADD = "add"          # $additive — цвет прибавляется к фону
BLEND_CUTOUT = "cutout"    # $alphatest — пиксель либо есть, либо нет

#: Порог отсечения по умолчанию для $alphatest (значение Source).
DEFAULT_ALPHA_TEST = 0.5


@dataclass(frozen=True)
class RenderSpec:
    """Во что превращается VMT для 3D-превью."""

    blend: str = BLEND_OPAQUE
    opacity: float = 1.0
    alpha_test: float = 0.0
    two_sided: bool = False

    @property
    def is_transparent(self) -> bool:
        """Материал попадает в сортируемый проход (не пишет глубину)."""
        return self.blend in (BLEND_ALPHA, BLEND_ADD)

    @property
    def is_plain(self) -> bool:
        """Ничего особенного — вьюверу можно не передавать."""
        return (self.blend == BLEND_OPAQUE and self.opacity >= 1.0
                and not self.two_sided)

    def as_dict(self) -> dict:
        """Компактный JSON для вьювера (только значимые поля)."""
        out: dict = {"blend": self.blend}
        if self.opacity < 1.0:
            out["opacity"] = round(self.opacity, 3)
        if self.alpha_test:
            out["alphaTest"] = round(self.alpha_test, 3)
        if self.two_sided:
            out["twoSided"] = True
        return out


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_render(vmt_text: Optional[str]) -> RenderSpec:
    """Разбирает VMT в RenderSpec. Пустой/битый текст → значения по умолчанию."""
    if not vmt_text:
        return RenderSpec()
    try:
        doc = vmt_parse.parse(vmt_text)
    except Exception as exc:                     # разбор VMT не должен ронять превью
        logger.debug(f"[render] VMT не разобран: {exc}")
        return RenderSpec()
    return from_doc(doc)


def from_doc(doc: vmt_parse.VmtDoc) -> RenderSpec:
    """RenderSpec из уже разобранного VMT (чтобы не парсить дважды)."""
    opacity = doc.number("alpha", 1.0) or 1.0
    opacity = _clamp(float(opacity), 0.0, 1.0)

    # $additive и $translucent нередко стоят вместе (c_madmilk_glass): в игре
    # такой материал уходит в прозрачный проход и складывается с фоном —
    # решает именно $additive.
    if doc.flag("additive"):
        blend = BLEND_ADD
    elif doc.flag("translucent") or opacity < 1.0:
        blend = BLEND_ALPHA
    elif doc.flag("alphatest"):
        blend = BLEND_CUTOUT
    else:
        blend = BLEND_OPAQUE

    alpha_test = 0.0
    if blend == BLEND_CUTOUT:
        alpha_test = _clamp(
            float(doc.number("alphatestreference", DEFAULT_ALPHA_TEST) or
                  DEFAULT_ALPHA_TEST), 0.01, 0.99)

    return RenderSpec(
        blend=blend,
        opacity=opacity,
        alpha_test=alpha_test,
        two_sided=doc.flag("nocull"),
    )
