"""
Конструктор узора блеска Killstreak: узор из слоёв -> кадры маски

Как маска ложится на оружие (калибровка в игре, Scattergun):
плоская проекция сбоку, насквозь модели. X маски - вдоль оружия, Y - сверху
вниз, вся маска растянута на габариты модели. Поэтому слои считаются в
«пространстве оружия»: x от 0 до A (A = длина / высота), y от 0 до 1 - тогда
искры на оружии круглые, а наклон полос такой, как в превью. Квадратная
маска потом сжимается по X в A раз, а игра растягивает её обратно

Время узора - доля прохода t от 0 до 1; сколько это секунд, решает число
кадров (длина прохода в эффекте), кадры крутит прокси игры со скоростью 25 в
секунду. Кадр 0 игра не рисует - он пустой

Свои узоры живут в work/sheen_patterns/<id>.json (картинки слоёв - рядом,
в images/). В VMT стоит `tf2sg/sheen/<id>_a<A·10>_<кадров>`, файл маски
по этому имени строит сборка (sheen_patterns.materialize): правка узора
доходит до всех оружий с ним при следующей сборке
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import secrets
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SIZE = 128                    # высота маски по умолчанию
#: Качество - высота маски, ширина по пропорции оружия (mask_shape)
QUALITY = {"low": 64, "medium": 128, "high": 256}
PEAK = 230                    # как у готовых узоров (стоковая маска до 216)
MAX_LAYERS = 8
DEFAULT_ASPECT = 3.0          # пропорция большинства стволов
#: Углы: 0° - вдоль оружия к дулу (->), 90° - вниз (↓), как на плитке превью
_OLD_DIRS = {"right": 0, "down": 90, "left": 180, "up": 270}

#: Типы слоёв и их поля. Это же отдаётся странице: поля формы строятся отсюда.
#: (ключ, вид, умолчание, мин, макс, шаг, подписи ru/en)
DEFAULT_STOPS = [[0.0, "#ff4d4d"], [0.5, "#ffc93c"], [1.0, "#3fd8ff"]]
MAX_STOPS = 8
#: «image» - цвета самой картинки, есть только у слоя-картинки
_COMMON = [
    ("fill", "choice", "solid", ("solid", "space", "time", "image"), None, None, ("Заливка", "Fill")),
    ("color", "color", "#ffffff", None, None, None, ("Цвет слоя", "Layer color")),
    ("stops", "stops", DEFAULT_STOPS, None, None, None, ("Градиент", "Gradient")),
    ("gangle", "angle", 0, 0, 359, 1, ("Направление градиента", "Gradient direction")),
    ("power", "range", 1.0, 0, 1, 0.05, ("Яркость", "Brightness")),
    ("blend", "choice", "max", ("max", "add", "mask", "cut"), None, None,
     ("Смешивание со слоями ниже", "Blend with layers below")),
    ("fade", "range", 0.15, 0, 0.5, 0.01, ("Плавность входа и выхода", "Fade in and out")),
    ("repeat", "range", 1, 1, 8, 1, ("Повторов за отрезок", "Repeats")),
    ("bounce", "choice", "once", ("once", "back"), None, None, ("Как повторять", "Repeat as")),
]
LAYER_TYPES: Dict[str, dict] = {
    "stripe": {
        "label": ("Полоса", "Stripe"),
        "fields": [
            ("angle", "angle", 0, 0, 359, 1, ("Направление", "Direction")),
            ("count", "range", 1, 1, 12, 1, ("Сколько полос", "Stripes")),
            ("spacing", "range", 0.35, 0.05, 2, 0.05, ("Расстояние между", "Spacing")),
            ("trail", "range", 0.3, 0, 1, 0.05, ("Затухание следующих", "Trailing fade")),
            ("width", "range", 0.25, 0.02, 1.5, 0.01, ("Ширина", "Width")),
            ("soft", "range", 0.8, 0.05, 1, 0.05, ("Мягкость края", "Edge softness")),
            ("tilt", "range", 0, -60, 60, 1, ("Наклон, °", "Tilt, °")),
            ("wave", "range", 0.05, 0, 0.5, 0.01, ("Волнистость", "Waviness")),
            ("waves", "range", 1.5, 0.5, 8, 0.5, ("Частота волн", "Wave frequency")),
        ],
    },
    "flash": {
        "label": ("Вспышка", "Flash"),
        "fields": [
            ("pulses", "range", 1, 1, 8, 1, ("Сколько вспышек", "Flashes")),
            ("sharp", "range", 0.3, 0, 1, 0.05, ("Резкость", "Sharpness")),
            ("grain", "range", 0.25, 0, 1, 0.05, ("Рисунок", "Texture")),
        ],
    },
    "sparkle": {
        "label": ("Искры", "Sparkles"),
        "fields": [
            ("count", "range", 60, 5, 400, 5, ("Сколько искр", "Sparkles")),
            ("size", "range", 0.05, 0.01, 0.12, 0.005, ("Размер", "Size")),
            ("life", "range", 0.2, 0.05, 1, 0.05, ("Сколько живёт искра", "Sparkle life")),
            ("star", "range", 0.5, 0, 1, 0.05, ("Лучи звезды", "Star rays")),
            ("seed", "seed", 1, 0, 9999, 1, ("Расклад", "Layout")),
        ],
    },
    "clouds": {
        "label": ("Дымка", "Mist"),
        "fields": [
            ("angle", "angle", 0, 0, 359, 1, ("Куда плывёт", "Drift")),
            ("scale", "range", 3, 1, 10, 0.5, ("Размер клубов", "Cloud size")),
            ("density", "range", 0.5, 0.05, 1, 0.05, ("Плотность", "Density")),
            ("speed", "range", 1, 0, 4, 0.1, ("Скорость", "Speed")),
            ("seed", "seed", 1, 0, 9999, 1, ("Расклад", "Layout")),
        ],
    },
    "image": {
        "label": ("Картинка", "Picture"),
        "fields": [
            ("image", "image", "", None, None, None, ("Картинка", "Picture")),
            ("mode", "choice", "reveal", ("reveal", "flash", "still"), None, None,
             ("Как появляется", "How it shows")),
            ("angle", "angle", 0, 0, 359, 1, ("Направление", "Direction")),
            ("width", "range", 0.6, 0.05, 3, 0.05, ("Ширина проявления", "Reveal width")),
            ("fit", "choice", "fit", ("fit", "stretch"), None, None, ("Размещение", "Placement")),
            ("scale", "range", 1.0, 0.1, 2, 0.05, ("Размер", "Size")),
            ("pos_x", "range", 0.5, 0, 1, 0.01, ("Положение по длине", "Position along")),
            ("pos_y", "range", 0.5, 0, 1, 0.01, ("Положение по высоте", "Position up and down")),
            ("rot", "range", 0, -180, 180, 1, ("Поворот, °", "Rotation, °")),
            ("invert", "choice", "no", ("no", "yes"), None, None, ("Негатив", "Invert")),
        ],
    },
}
CHOICE_LABELS = {
    "right": ("→", "→"), "left": ("←", "←"), "down": ("↓", "↓"), "up": ("↑", "↑"),
    "reveal": ("Полосой", "With a stripe"), "flash": ("Вспышкой", "As a flash"),
    "still": ("Всё время", "All the time"),
    "fit": ("Целиком", "Whole"), "stretch": ("Растянуть", "Stretch"),
    "solid": ("Один цвет", "One color"), "space": ("По оружию", "Across the weapon"),
    "time": ("Во времени", "Over time"), "image": ("Цвета картинки", "Picture colors"),
    "max": ("Светлее", "Lighten"), "add": ("Сложить", "Add"),
    "mask": ("Маска", "Mask"), "cut": ("Вырезать", "Cut out"),
    "once": ("Заново", "Restart"), "back": ("Туда и обратно", "Back and forth"),
    "no": ("Нет", "No"), "yes": ("Да", "Yes"),
}


#: Поля-счётчики: целые
_WHOLE = ("count", "pulses", "repeat")


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clean_stops(value) -> list:
    """Точки градиента [[позиция 0…1, #rrggbb]], от 2 до MAX_STOPS, по порядку"""
    out = []
    for item in value if isinstance(value, list) else []:
        try:
            pos, colour = float(item[0]), str(item[1]).lower()
        except (TypeError, ValueError, IndexError):
            continue
        if re.fullmatch(r"#[0-9a-f]{6}", colour) and math.isfinite(pos):
            out.append([min(1.0, max(0.0, pos)), colour])
    out.sort(key=lambda st: st[0])
    return out[:MAX_STOPS] if len(out) >= 2 else [list(st) for st in DEFAULT_STOPS]


def _gradient(stops: list, x: np.ndarray) -> np.ndarray:
    """Цвет градиента 0…1 в точках x (любой формы) -> (..., 3)"""
    pos = [st[0] for st in stops]
    cols = np.array([_rgb(st[1]) for st in stops])
    return np.stack([np.interp(x, pos, cols[:, c]) for c in range(3)], axis=-1).astype(np.float32)


def _rgb(hexc: str) -> np.ndarray:
    """#rrggbb -> (3,) float32 0…1"""
    return np.array([int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)], np.float32)


# Узор: проверка

def _defaults(kind: str) -> dict:
    out = {"type": kind, "on": True, "start": 0.0, "end": 0.9}
    for key, _view, default, *_rest in _COMMON + LAYER_TYPES[kind]["fields"]:
        out[key] = [list(st) for st in default] if key == "stops" else default
    return out


def new_layer(kind: str) -> dict:
    return _defaults(kind)


def clean_spec(spec) -> dict:  # noqa: C901
    """Узор из присланного: известные типы, поля в пределах, не больше
    MAX_LAYERS слоёв. Мусор не роняет сборку - берутся умолчания"""
    layers = []
    for raw in (spec or {}).get("layers", []) if isinstance(spec, dict) else []:
        if not isinstance(raw, dict) or raw.get("type") not in LAYER_TYPES:
            continue
        if len(layers) >= MAX_LAYERS:
            break
        kind = raw["type"]
        layer = _defaults(kind)
        layer["on"] = bool(raw.get("on", True))
        raw = dict(raw)
        if "angle" not in raw and raw.get("dir") in _OLD_DIRS:
            raw["angle"] = _OLD_DIRS[raw["dir"]]
        if raw.get("fill") in ("along", "across"):
            raw["gangle"] = 0 if raw["fill"] == "along" else 90
            raw["fill"] = "space"
        for key in ("start", "end"):
            try:
                layer[key] = min(1.0, max(0.0, float(raw.get(key, layer[key]))))
            except (TypeError, ValueError):
                pass
        if layer["end"] < layer["start"]:
            layer["start"], layer["end"] = layer["end"], layer["start"]
        if layer["end"] - layer["start"] < 0.02:
            layer["end"] = min(1.0, layer["start"] + 0.02)
            layer["start"] = layer["end"] - 0.02
        for key, view, default, lo, hi, _step, _label in _COMMON + LAYER_TYPES[kind]["fields"]:
            value = raw.get(key, default)
            if view == "choice":
                layer[key] = value if value in lo else default
            elif view == "stops":
                layer[key] = _clean_stops(value)
            elif view == "color":
                layer[key] = (str(value).lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", str(value))
                              else default)
            elif view == "image":
                layer[key] = str(value or "")
            else:
                try:
                    v = min(hi, max(lo, float(value)))
                except (TypeError, ValueError):
                    v = default
                if view == "angle":
                    v = float(raw.get(key, default)) % 360 if _finite(raw.get(key)) else default
                layer[key] = (int(round(v)) % 360 if view == "angle"
                              else int(round(v)) if view == "seed" or key in _WHOLE
                              else v)
        if layer["fill"] == "image" and kind != "image":
            layer["fill"] = "solid"
        layers.append(layer)
    quality = (spec or {}).get("quality") if isinstance(spec, dict) else None
    return {"layers": layers, "quality": quality if quality in QUALITY else "medium"}


# Отрисовка

def _noise(w: int, h: int, cells_y: float, cells_x: float, seed: int) -> np.ndarray:
    """Плавный шум 0…1 размером h×w: cells_y клеток по высоте, cells_x по
    ширине (в пространстве оружия клетки квадратные), бесшовный по обеим
    осям - дымку можно сдвигать под любым углом"""
    rng = np.random.default_rng(seed)
    cy = max(2, int(round(cells_y)))
    cx = max(2, int(round(cells_x)))
    grid = rng.random((cy, cx))
    grid = np.concatenate([grid, grid[:, :1]], axis=1)
    grid = np.concatenate([grid, grid[:1, :]], axis=0)
    ys = np.linspace(0, cy, h, endpoint=False)
    xs = np.linspace(0, cx, w, endpoint=False)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy = ((1 - np.cos((ys - y0) * np.pi)) / 2)[:, None]
    fx = ((1 - np.cos((xs - x0) * np.pi)) / 2)[None, :]
    a = grid[y0][:, x0] * (1 - fx) + grid[y0][:, x0 + 1] * fx
    b = grid[y0 + 1][:, x0] * (1 - fx) + grid[y0 + 1][:, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def _fbm(w: int, h: int, cells: float, cells_x: float, seed: int) -> np.ndarray:
    out = sum(_noise(w, h, cells * 2 ** k, cells_x * 2 ** k, seed + k) / 2 ** k
              for k in range(3))
    out -= out.min()
    return out / max(out.max(), 1e-6)


def _band(q: np.ndarray, center, width: float, soft: float) -> np.ndarray:
    """Полоса шириной `width` вокруг center: мягкость 1 - треугольник,
    ближе к 0 - резкий край. clip((1 - |q-c| / (w/2)) / soft) на месте,
    без промежуточных массивов: это самый частый расчёт кадра"""
    soft = max(soft, 0.05)
    out = q - center
    np.abs(out, out=out)
    out *= -1 / (max(width / 2, 1e-4) * soft)
    out += 1 / soft
    return np.clip(out, 0, 1, out=out)


def resolve_image(value: str) -> Optional[Path]:
    """Файл картинки слоя, всегда абсолютным путём: в библиотеке узор
    хранит её как images/<файл>, страница присылает полный путь

    Абсолютным - обязательно: в приложении папка работ задана относительно
    (data_dir() = "."), и относительный путь, отданный странице, при
    следующем превью искался уже внутри библиотеки - картинка пропадала"""
    if not value:
        return None
    p = Path(value)
    if not p.is_absolute():
        inside = library_dir() / value
        p = inside if inside.is_file() else p
    p = p.resolve()
    return p if p.is_file() else None


#: Картинка слоя хранится не крупнее ~1 Мп: маска не бывает больше
#: 1024×256, и такой запас покрывает любую пропорцию картинки до 16:1
_SOURCE_PIXELS = 1 << 20


@functools.lru_cache(maxsize=16)
def _source(path: str, _mtime_ns: int, _size: int):
    """Картинка слоя RGBA, уже уменьшенная. Кэш по пути, времени и размеру
    файла: без него каждая правка узора заново декодировала все картинки
    (8000×8000 PNG - 2.5 с, восемь слоёв - больше 10 с на одно превью)"""
    from PIL import Image, ImageOps

    def fit(width: int, height: int) -> tuple:
        k = min(1.0, math.sqrt(_SOURCE_PIXELS / max(1, width * height)))
        return max(1, math.ceil(width * k)), max(1, math.ceil(height * k))

    with Image.open(path) as src:
        src.draft(src.mode, fit(src.width, src.height))   # JPEG декодируется сразу мельче
        img = ImageOps.exif_transpose(src).convert("RGBA")
    size = fit(img.width, img.height)
    return img if size == img.size else img.resize(size, Image.LANCZOS, reducing_gap=3.0)


def _picture(layer: dict, h: int, w: int, aspect: float) -> Optional[tuple]:
    """Картинка слоя в маске: (покрытие h×w, цвет 3×h×w), всё 0…1 и цвет уже
    умножен на покрытие. «Целиком» - с пропорцией картинки на оружии,
    «растянуть» - на весь бок, потом размер, поворот (по часовой, как на
    плитке превью) и положение центра"""
    from PIL import Image

    path = resolve_image(layer.get("image", ""))
    if not path:
        return None
    st = path.stat()
    src = _source(str(path), st.st_mtime_ns, st.st_size)
    # Холст в пропорции оружия, потом он приводится к маске - на оружии
    # игра растянет её обратно в пропорцию
    cw, ch = max(1, int(round(h * aspect))), h
    if layer.get("fit") == "stretch":
        bw, bh = cw, ch
    else:
        k = min(cw / src.width, ch / src.height)
        bw, bh = src.width * k, src.height * k
    zoom = float(layer.get("scale", 1.0))
    size = (max(1, int(bw * zoom)), max(1, int(bh * zoom)))
    pic = src.resize(size, Image.LANCZOS)
    # Поворот - на холсте в пропорции оружия: точки там квадратные на его
    # боку, и картинка не перекашивается
    rot = float(layer.get("rot", 0) or 0)
    if rot:
        pic = pic.rotate(-rot, Image.BICUBIC, expand=True)
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    # floor, как у (cw - w) // 2: узоры старых работ по центру не сдвигаются
    canvas.paste(pic, (math.floor(float(layer.get("pos_x", 0.5)) * cw - pic.width / 2),
                       math.floor(float(layer.get("pos_y", 0.5)) * ch - pic.height / 2)))
    arr = np.asarray(canvas.resize((w, h), Image.LANCZOS), np.float32) / 255
    cover = np.ascontiguousarray(arr[..., 3])
    rgb = np.moveaxis(arr[..., :3], -1, 0) * cover          # (3, h, w), см. iter_frames
    if layer.get("invert") == "yes":
        rgb = cover - rgb
    return cover, rgb


def mask_shape(aspect: float, quality: str = "medium") -> tuple:
    """(высота, ширина) маски. Высота - от качества, ширина - степень двойки
    по пропорции оружия: игра растягивает маску на бок оружия, и квадратная
    маска 128×128 давала на стволе 3:1 всего ~43 точки на высоту по длине"""
    h = QUALITY.get(quality, QUALITY["medium"])
    w = 2 ** int(round(math.log2(max(4.0, h * max(0.5, aspect)))))
    return h, int(min(1024, max(16, w)))


class _Layer:
    """Слой, готовый к отрисовке: всё, что не зависит от кадра, считается
    один раз. Маска h×w; x - вдоль оружия 0…A, y - по высоте 0…1"""

    def __init__(self, spec: dict, h: int, w: int, aspect: float):
        self.s = spec
        self.h, self.w = h, w
        self.aspect = aspect
        self.pic = self.pic_rgb = None             # картинка: яркость и свой цвет
        # float32: на маске 256×1024 вдвое меньше памяти и заметно быстрее
        v, u = np.mgrid[0:h, 0:w].astype(np.float32)
        self.x = (u + 0.5) / w * np.float32(aspect)  # пространство оружия
        self.y = (v + 0.5) / h
        if spec.get("fill") == "space":
            self.gfield = self._along(float(spec["gangle"]))[0]
        if "angle" in spec:
            # Направление слоя за проход не меняется - проекции один раз,
            # а не на каждый кадр (на 256×1024 это половина всего расчёта)
            q, r, span = self._along(float(spec["angle"]))
            self.motion = (q * span, r, span)
        kind = spec["type"]
        if kind == "stripe":
            # Наклон за проход не меняется, волна - только фазой
            q, across, _span = self.motion
            self.tilted = q + np.float32(math.tan(math.radians(spec["tilt"]))) * (across - 0.5)
            self.wave_at = np.float32(2 * np.pi * spec["waves"]) * across
        elif kind == "flash":
            g = float(spec["grain"])
            self.grain = (1 - g + g * _fbm(w, h, 3, 3 * aspect, 5)).astype(np.float32)
        elif kind == "sparkle":
            rng = np.random.default_rng(int(spec["seed"]))
            n = int(spec["count"])
            life = float(spec["life"])
            self.pos = np.column_stack([rng.random(n) * aspect, rng.random(n)])
            self.birth = rng.random(n) * max(0.0, 1 - life)
            self.stamp = self._stamp()
        elif kind == "clouds":
            # Шум шире маски вдвое - есть куда плыть, бесшовный. Клетки
            # квадратные на оружии: по длине их в A раз больше
            cells = 12.0 / float(spec["scale"])
            cloud = _fbm(w * 2, h, cells, cells * aspect * 2, int(spec["seed"]))
            # Сетка шума видна ступеньками - сглаживаем один раз
            from PIL import Image, ImageFilter
            img = Image.fromarray((cloud * 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(h / 48))
            self.cloud = np.asarray(img, np.float32) / 255
        elif kind == "image":
            try:
                pic = _picture(spec, h, w, aspect)
            except Exception as exc:                       # noqa: BLE001
                logger.warning(f"[sheen] картинка слоя не читается: {exc}")
                pic = None
            if pic is not None:
                cover, rgb = pic
                if spec.get("fill") == "image":
                    # Яркость - покрытие, цвет - сама картинка (без покрытия)
                    self.pic = cover
                    self.pic_rgb = np.divide(rgb, cover, out=np.zeros_like(rgb), where=cover > 1e-4)
                else:
                    self.pic = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]   # как Pillow «L»
        # Цвет, не зависящий от кадра, - один раз, «во времени» - по кадрам
        fill = spec.get("fill", "solid")
        if fill == "time":
            self.fixed = None
        elif fill == "space":
            self.fixed = np.ascontiguousarray(np.moveaxis(_gradient(spec["stops"], self.gfield), -1, 0))
        elif fill == "image" and self.pic_rgb is not None:
            self.fixed = self.pic_rgb
        else:
            self.fixed = _rgb(spec["color"]).reshape(3, 1, 1)
        self.repeat = int(spec.get("repeat", 1))
        self.bounce = spec.get("bounce") == "back"

    def colour(self, s: float) -> np.ndarray:
        """Цвет слоя каналом вперёд: (3, 1, 1) или (3, h, w). «По оружию» -
        градиент под углом `gangle`, «во времени» - по доле s отрезка слоя"""
        if self.fixed is None:
            return _gradient(self.s["stops"], np.array(s)).reshape(3, 1, 1)
        return self.fixed

    def phase(self, s: float) -> float:
        """Доля движения слоя: за отрезок оно идёт `repeat` раз, «туда и
        обратно» - каждый второй раз назад"""
        if self.repeat <= 1:
            return s
        x = s * self.repeat
        k = min(int(x), self.repeat - 1)
        f = x - k
        return 1 - f if self.bounce and k % 2 else f

    def _along(self, angle: float) -> tuple:
        """Координата вдоль направления под углом (0…1 от края до края
        оружия) и поперёк него (0…1). Угол в пространстве оружия: на
        плитке и на боку оружия 45° - это правда диагональ"""
        a = math.radians(angle)
        c, s = math.cos(a), math.sin(a)
        dx, dy = self.x - self.aspect / 2, self.y - 0.5
        span = self.aspect * abs(c) + abs(s)            # ширина оружия вдоль направления
        cross = self.aspect * abs(s) + abs(c)           # и поперёк
        q = (dx * c + dy * s) / span + 0.5
        r = (-dx * s + dy * c) / cross + 0.5
        return q, r, span

    def _moving(self, p: float) -> tuple:
        """(координата вдоль движения в высотах оружия, положение фронта,
        поперечная 0…1) для угла слоя"""
        q, r, span = self.motion
        margin = 0.6
        front = -margin + (span + 2 * margin) * p
        return q, front, r

    def blank(self) -> np.ndarray:
        return np.zeros((self.h, self.w), np.float32)

    def frame(self, s: float) -> np.ndarray:
        """Яркость слоя 0…1 (h×w) в доле s его отрезка времени: плавность
        входа и выхода - по всему отрезку, движение - по `phase`"""
        sp = self.s
        fade = float(sp["fade"])
        fade_env = max(0.0, 1.0 if fade <= 0 else min(1.0, s / fade, (1 - s) / fade))
        env = fade_env * float(sp["power"])
        s = self.phase(s)
        kind = sp["type"]
        if kind == "stripe":
            return self._stripes(s) * np.float32(env)
        if kind == "flash":
            beat = np.sin(np.pi * int(sp["pulses"]) * s) ** 2
            beat = beat ** (1 + 6 * float(sp["sharp"]))
            return self.grain * np.float32(beat * env)
        if kind == "sparkle":
            # Искры гаснут сами - плавность слоя только приглушает край
            return self._sparkles(s) * np.float32(min(1.0, fade_env * 3) * float(sp["power"]))
        if kind == "clouds":
            a = math.radians(float(sp["angle"]))
            dist = float(sp["speed"]) * s               # путь в высотах оружия
            cloud = np.roll(self.cloud, (int(round(dist * math.sin(a) * self.h)),
                                         int(round(dist * math.cos(a) * self.w / self.aspect))),
                            axis=(0, 1))
            dens = float(sp["density"])
            view = cloud[:, :self.w]
            return np.clip((view - (1 - dens)) / 0.4, 0, 1) * env
        if kind == "image":
            if self.pic is None:
                return self.blank()
            mode = sp["mode"]
            if mode == "still":
                return self.pic * np.float32(env)
            if mode == "flash":
                return self.pic * np.float32(np.sin(np.pi * s) ** 2 * float(sp["power"]))
            q, front, _r = self._moving(s)
            return self.pic * _band(q, front, sp["width"], 1.0) * float(sp["power"])
        return self.blank()

    def _stripes(self, s: float) -> np.ndarray:
        """Полосы в доле s движения, яркость 0…1"""
        sp = self.s
        _q, front, _r = self._moving(s)
        q = self.tilted
        if sp["wave"]:
            q = q + np.float32(sp["wave"]) * np.sin(self.wave_at + np.float32(s * 6))
        width, soft = float(sp["width"]), max(float(sp["soft"]), 0.05)
        # Полоса j стоит в front - j·spacing. Точку задевают только полосы
        # ближе width/2: от near-(k-1) до near+k, где near - ближайшая
        # впереди. Считаем их, а не все (до 12) на всю маску
        n = int(sp["count"])
        d = max(float(sp["spacing"]), 1e-3)
        k = max(1, int(math.ceil(width / 2 / d)))
        trail = 1 - float(sp["trail"])
        if n <= 2 * k:
            out = _band(q, front, width, soft)
            for j in range(1, n):
                np.maximum(out, _band(q, front - j * d, width, soft) * np.float32(trail ** j), out=out)
            return out
        u = (front - q) * np.float32(1 / d)        # положение в шагах полос
        near = np.floor(u)
        frac = u - near                             # 0…1: до полосы near
        first = near.astype(np.intp) + 1            # её номер в таблице яркости
        lo, hi = int(first.min()) - 1, int(first.max()) - 1
        # Яркость полосы j - таблицей: по краям нули (j < 0 и j ≥ n), так
        # и без where и pow на всю маску
        weight = np.zeros(n + 2, np.float32)
        weight[1:-1] = trail ** np.arange(n)
        slope = np.float32(-d / (width / 2 * soft))
        out = np.zeros_like(q)
        for off in range(1 - k, k + 1):
            if hi + off < 0 or lo + off >= n:
                continue
            # Расстояние до полосы near+off - |off - frac| шагов
            band = frac - np.float32(off)
            np.abs(band, out=band)
            band *= slope
            band += np.float32(1 / soft)
            np.clip(band, 0, 1, out=band)
            band *= weight[np.clip(first + off, 0, n + 1)]
            np.maximum(out, band, out=out)
        return out

    def _stamp(self) -> np.ndarray:
        """Одна искра в пикселях маски: точка и лучи креста - круглая на
        оружии при любой пропорции маски"""
        sp = self.s
        r = float(sp["size"]) / 2                      # в высотах оружия
        star = float(sp["star"])
        reach = r * (2.5 + 1.5 * star)                 # лучи до 4r
        px_y, px_x = self.h, self.w / self.aspect      # пикселей на высоту оружия
        ry = max(1, int(math.ceil(reach * px_y)))
        rx = max(1, int(math.ceil(reach * px_x)))
        yy, xx = np.mgrid[-ry:ry + 1, -rx:rx + 1].astype(np.float64)
        dx = xx / px_x
        dy = yy / px_y
        dot = np.exp(-(dx * dx + dy * dy) / (r * r))
        if star > 0:
            ray = (np.exp(-(dy / (r * 0.15)) ** 2 - (dx / (r * 4)) ** 2)
                   + np.exp(-(dx / (r * 0.15)) ** 2 - (dy / (r * 4)) ** 2))
            dot = np.maximum(dot, star * ray)
        return dot.astype(np.float32)

    def _sparkles(self, s: float) -> np.ndarray:
        h, w = self.h, self.w
        out = np.zeros((h, w), np.float32)
        life = float(self.s["life"])
        stamp = self.stamp
        hy, hx = stamp.shape[0] // 2, stamp.shape[1] // 2
        k = (s - self.birth) / life
        for i in np.nonzero((k > 0) & (k < 1))[0]:
            bright = math.sin(math.pi * k[i]) ** 2
            cx = int(self.pos[i, 0] / self.aspect * w)
            cy = int(self.pos[i, 1] * h)
            x0, x1 = max(0, cx - hx), min(w, cx + hx + 1)
            y0, y1 = max(0, cy - hy), min(h, cy + hy + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            part = stamp[y0 - cy + hy:y1 - cy + hy, x0 - cx + hx:x1 - cx + hx]
            np.maximum(out[y0:y1, x0:x1], bright * part, out=out[y0:y1, x0:x1])
        return out


class Cancelled(Exception):
    """Расчёт кадров прерван: узор уже поменялся, результат не нужен"""


def iter_frames(spec: dict, count: int, aspect: float = DEFAULT_ASPECT,
                quality: Optional[str] = None,
                cancelled: Optional[Callable[[], bool]] = None,
                palette: str = "warm") -> Iterator[np.ndarray]:
    """Кадры маски RGBA uint8 (h×w по `mask_shape`) по одному: кадр 0
    пустой. `quality` - вместо качества узора (превью шаблонов считается
    мельче). `cancelled()` спрашивается перед каждым кадром - True
    прерывает расчёт исключением Cancelled

    Слои накладываются снизу списка вверх (как слои в редакторах картинок):
    «светлее» - по каждому каналу ярчайший, «сложить» - сумма, «маска» -
    всё, что под слоем, видно только сквозь него, «вырезать» - наоборот.
    Для «светлее» и «сложить» порядок не важен

    `palette` - гамма узора (sheen_palette): в холодной красный канал несёт
    форму слоёв, а не цвет - иначе чёрный слой исчез бы из маски"""
    spec = clean_spec(spec)
    aspect = min(12.0, max(0.5, float(aspect or DEFAULT_ASPECT)))
    h, w = mask_shape(aspect, quality or spec["quality"])
    layers = [_Layer(l, h, w, aspect) for l in reversed(spec["layers"]) if l["on"]]
    blank = np.zeros((h, w, 4), np.uint8)
    blank[..., 3] = 255
    yield blank
    # Каналом вперёд (3, h, w): у (h, w, 3) внутренний цикл numpy шёл бы
    # по трём числам, и каждая операция кадра была втрое-вчетверо дольше
    acc = np.empty((3, h, w), np.float32)
    cold = palette == "cold"
    cov = np.empty((h, w), np.float32)          # форма слоёв без цвета
    for i in range(1, count):
        if cancelled is not None and cancelled():
            raise Cancelled()
        t = (i - 1) / max(1, count - 2)
        acc.fill(0)
        cov.fill(0)
        for layer in layers:
            a, b = layer.s["start"], layer.s["end"]
            blend = layer.s["blend"]
            if not a <= t <= b:
                if blend == "mask":                 # маска вне своего времени закрывает всё
                    acc.fill(0)
                    cov.fill(0)
                continue
            s = (t - a) / max(b - a, 1e-6)
            lum = layer.frame(s)
            if blend == "mask":
                acc *= lum
                cov *= lum
            elif blend == "cut":
                acc *= 1 - lum
                cov *= 1 - lum
            elif blend == "add":
                acc += lum * layer.colour(s)
                cov += lum
            else:
                np.maximum(acc, lum * layer.colour(s), out=acc)
                np.maximum(cov, lum, out=cov)
        if cold:
            acc[0] = cov
        acc *= PEAK
        np.clip(acc, 0, 255, out=acc)
        frame = np.empty((h, w, 4), np.uint8)
        frame[..., 3] = 255
        frame[..., :3] = acc.transpose(1, 2, 0)
        yield frame


def render(spec: dict, count: int, aspect: float = DEFAULT_ASPECT,
           quality: Optional[str] = None, palette: str = "warm") -> List[np.ndarray]:
    """Все кадры маски списком (`iter_frames`) - для записи VTF"""
    return list(iter_frames(spec, count, aspect, quality, palette=palette))


def mod_bytes(count: int, aspect: float, quality: str) -> int:
    """Сколько маска весит в моде: DXT1 - полбайта на точку, кадров count"""
    h, w = mask_shape(aspect, quality)
    return count * h * w // 2


def _sheet_layout(count: int, aspect: float, quality: str) -> dict:
    """Раскладка листа кадров: ширина листа до 4096 точек"""
    h, w = mask_shape(min(12.0, max(0.5, float(aspect or DEFAULT_ASPECT))), quality)
    return {"frames": count, "cols": max(1, 4096 // w), "cell_w": w, "cell_h": h,
            "bytes": mod_bytes(count, aspect, quality)}


def preview_sheet(spec: dict, count: int, aspect: float, out_png: Path,
                  cancelled: Optional[Callable[[], bool]] = None,
                  palette: str = "warm") -> dict:
    """Кадры одной картинкой-сеткой для превью страницы - те же, что уйдут
    в мод, в том же качестве. Кадры пишутся в лист сразу, списком не
    копятся: на высоком качестве и 8 с прохода это 200 МБ лишней памяти"""
    from PIL import Image

    layout = _sheet_layout(count, aspect, clean_spec(spec)["quality"])
    h, w, cols = layout["cell_h"], layout["cell_w"], layout["cols"]
    sheet = np.zeros((-(-count // cols) * h, cols * w, 3), np.uint8)
    for i, f in enumerate(iter_frames(spec, count, aspect, cancelled=cancelled,
                                      palette=palette)):
        r, c = divmod(i, cols)
        sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = f[..., :3]
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    # Через временный файл: недописанный лист не должен попасть в кэш превью.
    # Сжатие быстрое - файл читается тут же (2 с -> 0.3 с)
    part = out_png.with_name(f"{out_png.stem}.{secrets.token_hex(4)}.part")
    Image.fromarray(sheet).save(part, format="PNG", compress_level=1)
    part.replace(out_png)
    return {"image": str(out_png), **layout}


#: Сколько последних листов превью держать: Ctrl+Z в конструкторе
#: возвращает к ним без расчёта
PREVIEW_KEEP = 10
#: Версия отрисовки в ключе кэша превью: папка во временных файлах
#: переживает обновление приложения. Менять при правке математики кадров
_RENDER_VERSION = 3


def preview(spec: dict, count: int, aspect: float, folder: Path,
            cancelled: Optional[Callable[[], bool]] = None,
            gamut_spec: Optional[dict] = None) -> dict:
    """Лист кадров для страницы (`preview_sheet`) с кэшем в `folder`: тот же
    узор с теми же файлами картинок - тот же лист, без расчёта. Лист - сама
    маска в гамме узора, страница показывает её так, как смешает игра, по
    `palette`, а слои из `lost` в игре не видны (sheen_palette). Гамму
    решает весь узор (`gamut_spec`), даже когда в превью один слой «соло»"""
    import os
    from src.services import sheen_palette

    spec = clean_spec(spec)
    gamut = sheen_palette.classify(clean_spec(gamut_spec) if gamut_spec else spec)
    files = []
    for layer in spec["layers"]:
        path = resolve_image(layer.get("image", "")) if layer["type"] == "image" else None
        if path:
            st = path.stat()
            files.append([str(path), st.st_mtime_ns, st.st_size])
    key = hashlib.sha1(json.dumps([_RENDER_VERSION, spec, count, aspect, files, gamut],
                                  sort_keys=True)
                       .encode()).hexdigest()[:16]
    folder = Path(folder)
    out = folder / f"{key}.png"
    if out.is_file():
        try:
            os.utime(out)                       # свежий - не уйдёт при чистке
            return {"image": str(out), **_sheet_layout(count, aspect, spec["quality"]),
                    **gamut}
        except OSError:                         # соседний запрос как раз удалил
            pass
    res = {**preview_sheet(spec, count, aspect, out, cancelled, gamut["palette"]), **gamut}
    # Чистят и параллельные запросы: файл может пропасть между glob и stat
    def age(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    for old in sorted(folder.glob("*.png"), key=age, reverse=True)[PREVIEW_KEEP:]:
        old.unlink(missing_ok=True)
    return res


def thumbnail(spec: dict, aspect: float, out_png: Path) -> str:
    """Один кадр узора (самый яркий из прохода) - карточка шаблона"""
    from PIL import Image

    best = max(iter_frames(spec, 31, aspect, "low"), key=lambda f: int(f[..., :3].sum()))
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(best[..., :3]).save(out_png)
    return str(out_png)


def library_dir() -> Path:
    """work/sheen_patterns - рядом с работами (у dev-сервера своя папка)"""
    from src.services import work_store
    return (Path(work_store.WORK_DIR) / "sheen_patterns").resolve()


# Готовые стартовые узоры (как готовые узоры эффекта)

def _l(kind: str, **kw) -> dict:
    layer = new_layer(kind)
    layer.update(kw)
    return layer


PRESETS: Dict[str, dict] = {
    "classic": {"label": ("Одна полоса", "One stripe"),
                "spec": {"layers": [_l("stripe", width=0.5)]}},
    "double": {"label": ("Две полосы", "Two stripes"),
               "spec": {"layers": [_l("stripe", count=2, spacing=0.8, trail=0.25, width=0.4)]}},
    "running": {"label": ("Бегущие полосы", "Running stripes"),
                "spec": {"layers": [_l("stripe", count=8, spacing=0.45, trail=0, width=0.12,
                                       soft=0.6, angle=20)]}},
    "pulse": {"label": ("Вспышка", "Flash"), "spec": {"layers": [_l("flash")]}},
    "sparkle": {"label": ("Искры", "Sparkles"),
                "spec": {"layers": [_l("sparkle", count=80)]}},
    "comet": {"label": ("Комета с искрами", "Comet with sparkles"),
              "spec": {"layers": [_l("stripe", width=0.2, end=0.7),
                                  _l("sparkle", count=50, size=0.04, start=0.15, end=0.9)]}},
    "mist": {"label": ("Дымка", "Mist"),
             "spec": {"layers": [_l("clouds", scale=4, density=0.5)]}},
}
