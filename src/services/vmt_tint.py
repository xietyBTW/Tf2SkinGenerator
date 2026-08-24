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

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: VMT Valve пишет с CRLF — якорь конца строки обязан это учитывать.
def _param_re(name: str) -> re.Pattern:
    return re.compile(
        r'^[ \t]*"?\$' + name + r'"?[ \t]+"?([^"\r\n]+?)"?[ \t]*\r?$',
        re.IGNORECASE | re.MULTILINE)


_RE_BLEND = _param_re("blendtintbybasealpha")
_RE_OVER_BASE = _param_re("blendtintcoloroverbase")
_RE_TINT_BASE = _param_re("colortint_base")
_RE_COLOR2 = _param_re("color2")
_RE_TRANSLUCENT = _param_re("translucent")
_RE_ALPHATEST = _param_re("alphatest")

#: «{ 189 59 59 }» — целые 0-255, «[0.7 0.2 0.2]» — доли единицы.
_RE_TRIPLE = re.compile(r'[-+]?\d*\.?\d+')


@dataclass(frozen=True)
class TintSpec:
    """Как красить текстуру: цвет и насколько он перекрывает базовый."""
    color: Tuple[int, int, int]
    over_base: float = 0.0

    @property
    def is_neutral(self) -> bool:
        """Белая краска поверх нуля ничего не меняет — красить нечего."""
        return self.color == (255, 255, 255) and self.over_base <= 0.0


def parse_color(value: str) -> Optional[Tuple[int, int, int]]:
    """«{ 189 59 59 }» или «[.74 .23 .23]» → (r, g, b) 0-255."""
    if not value:
        return None
    nums = _RE_TRIPLE.findall(value)
    if len(nums) < 3:
        return None
    floats = [float(n) for n in nums[:3]]
    # Скобки решают: фигурные — уже 0-255, квадратные — доли единицы.
    # Ориентируемся на скобку, а не на «есть ли значение > 1»: [1 1 1] это
    # белый, а не почти чёрный.
    if "[" in value:
        floats = [f * 255.0 for f in floats]
    return tuple(max(0, min(255, int(round(f)))) for f in floats)


def parse_tint(vmt_text: str) -> Optional[TintSpec]:
    """
    Краска материала либо None, если материал так не красится.

    None означает «текстуру трогать нельзя»: у обычного материала альфа —
    это прозрачность, а не маска краски, и заливать её нельзя.
    """
    if not vmt_text:
        return None
    blend = _RE_BLEND.search(vmt_text)
    if not blend or parse_color(blend.group(1)) == (0, 0, 0) \
            or blend.group(1).strip() in ("0", "0.0"):
        return None
    # Прозрачность и маска краски в одном материале несовместимы: раз VMT
    # просит прозрачность, альфу считаем прозрачностью и не трогаем.
    for rx in (_RE_TRANSLUCENT, _RE_ALPHATEST):
        m = rx.search(vmt_text)
        if m and m.group(1).strip() not in ("0", "0.0", ""):
            return None

    src = _RE_TINT_BASE.search(vmt_text) or _RE_COLOR2.search(vmt_text)
    color = parse_color(src.group(1)) if src else None
    if color is None:
        color = (255, 255, 255)     # краски нет, но альфа-маска всё равно есть
    over = _RE_OVER_BASE.search(vmt_text)
    try:
        over_base = float(over.group(1)) if over else 0.0
    except ValueError:
        over_base = 0.0
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
