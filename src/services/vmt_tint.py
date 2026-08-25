"""
Командная окраска материала: $blendtintbybasealpha в понятном виде.

Две трети шапок TF2 (1353 модели из 1978 в стоке) не хранят цвет команды в
текстуре. Вместо этого альфа-канал `$basetexture` — это МАСКА окраски, а сам
цвет лежит в VMT (`$colortint_base`/`$color2`) и подмешивается шейдером:

    tinted = base_rgb * color
    tinted = lerp(tinted, color, $blendtintcoloroverbase)
    out    = lerp(base_rgb, tinted, base_alpha)

Отсюда два эффекта, которые видит пользователь, если этого не учитывать:

* окрашиваемые участки в текстуре почти чёрные (их цвет всё равно заменит
  краска), и превью показывает шапку с чёрными пятнами;
* RED и BLU у таких шапок ссылаются на ОДНУ текстуру и отличаются только
  цветом в VMT — переключатель команд показывает две одинаковые картинки.

Модуль без Qt и без обращений к VPK: на вход текст VMT и PNG-файл.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from src.services import vmt_parse
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Разбор цвета VMT — общий (фигурные скобки 0-255, квадратные — доли).
parse_color = vmt_parse.parse_color


@dataclass(frozen=True)
class TintSpec:
    """Как красить текстуру: цвет и насколько он перекрывает базовый."""
    color: Tuple[int, int, int]
    over_base: float = 0.0

    @property
    def is_neutral(self) -> bool:
        """Белая краска поверх нуля ничего не меняет — красить нечего."""
        return self.color == (255, 255, 255) and self.over_base <= 0.0


def parse_tint(vmt_text: str) -> Optional[TintSpec]:
    """
    Краска материала либо None, если материал так не красится.

    None означает «текстуру трогать нельзя»: у обычного материала альфа —
    это прозрачность, а не маска краски, и заливать её нельзя.
    """
    if not vmt_text:
        return None
    vmt = vmt_parse.parse(vmt_text)
    if not vmt.flag("blendtintbybasealpha"):
        return None
    # Прозрачность и маска краски в одном материале несовместимы: раз VMT
    # просит прозрачность, альфу считаем прозрачностью и не трогаем.
    if vmt.flag("translucent") or vmt.flag("alphatest"):
        return None

    color = vmt.color("colortint_base") or vmt.color("color2")
    if color is None:
        color = (255, 255, 255)     # краски нет, но альфа-маска всё равно есть
    over_base = vmt.number("blendtintcoloroverbase", 0.0) or 0.0
    return TintSpec(color, max(0.0, min(1.0, over_base)))


def same_look(red: Optional[TintSpec], blu: Optional[TintSpec]) -> bool:
    """Дают ли две краски одинаковый результат на одной и той же текстуре."""
    if red is None or blu is None:
        return red is blu or (red is None and blu is None)
    if red.is_neutral and blu.is_neutral:
        return True
    return red.color == blu.color and abs(red.over_base - blu.over_base) < 1e-6


def same_material_look(red: Optional[tuple], blu: Optional[tuple]) -> bool:
    """
    Дают ли два материала одну и ту же картинку.

    Аргументы — пары (basetexture, TintSpec): именно из них складывается вид
    материала. У 46 стоковых шапок BLU-скин — точная копия RED, и
    переключатель команд там ничего не меняет; у 329 других текстура та же,
    но краска разная — это уже настоящая разница.
    """
    if not red or not blu:
        return False
    return red[0] == blu[0] and same_look(red[1], blu[1])


def apply_to_png(png_path: str, spec: Optional[TintSpec]) -> bool:
    """
    Впечатывает краску в PNG на месте: то, что игрок увидит в игре.

    Альфа после этого — сплошная непрозрачность: в исходной текстуре она
    была маской краски, и оставлять её значит показывать шапку дырявой.

    Returns:
        True, если файл изменён.
    """
    if spec is None or not png_path:
        return False
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return False
    try:
        with Image.open(png_path) as img:
            src = img.convert("RGBA")
        r, g, b, alpha = src.split()
        base = Image.merge("RGB", (r, g, b))
        if spec.is_neutral:
            tinted = base
        else:
            multiplied = Image.merge("RGB", [
                ImageChops.multiply(ch, Image.new("L", src.size, level))
                for ch, level in zip((r, g, b), spec.color)])
            flat = Image.new("RGB", src.size, spec.color)
            tinted = (multiplied if spec.over_base <= 0 else
                      Image.blend(multiplied, flat, spec.over_base))
        out = Image.composite(tinted, base, alpha)
        out.putalpha(Image.new("L", src.size, 255))
        out.save(png_path)
        return True
    except Exception as exc:
        logger.warning(f"[tint] окраска {png_path} не удалась: {exc}")
        return False
