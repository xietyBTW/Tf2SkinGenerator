"""
Конструктор узора блеска Killstreak: узор из слоёв → кадры маски.

Как маска ложится на оружие (калибровка в игре 2026-10-13, Scattergun):
плоская проекция сбоку, насквозь модели. X маски — вдоль оружия, Y — сверху
вниз, вся маска растянута на габариты модели. Поэтому слои считаются в
«пространстве оружия»: x от 0 до A (A = длина / высота), y от 0 до 1 — тогда
искры на оружии круглые, а наклон полос такой, как в превью. Квадратная
маска потом сжимается по X в A раз, а игра растягивает её обратно.

Время узора — доля прохода t от 0 до 1; сколько это секунд, решает число
кадров (длина прохода в эффекте), кадры крутит прокси игры со скоростью 25 в
секунду. Кадр 0 игра не рисует — он пустой.

Свои узоры живут в work/sheen_patterns/<id>.json (картинки слоёв — рядом,
в images/). В VMT стоит `tf2sg/sheen/<id>_a<A·10>_<кадров>`, файл маски
по этому имени строит сборка (sheen_patterns.materialize): правка узора
доходит до всех оружий с ним при следующей сборке.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SIZE = 128                    # высота маски по умолчанию
#: Качество - высота маски; ширина по пропорции оружия (mask_shape).
QUALITY = {"low": 64, "medium": 128, "high": 256}
PEAK = 230                    # как у готовых узоров (стоковая маска до 216)
MAX_LAYERS = 8
DEFAULT_ASPECT = 3.0          # пропорция большинства стволов
ID_RE = re.compile(r'^u[0-9a-f]{8}$')
#: Углы: 0° — вдоль оружия к дулу (→), 90° — вниз (↓), как на плитке превью.
_OLD_DIRS = {"right": 0, "down": 90, "left": 180, "up": 270}

#: Типы слоёв и их поля. Это же отдаётся странице: поля формы строятся отсюда.
#: (ключ, вид, умолчание, мин, макс, шаг, подписи ru/en)
DEFAULT_STOPS = [[0.0, "#ff4d4d"], [0.5, "#ffc93c"], [1.0, "#3fd8ff"]]
MAX_STOPS = 8
_COMMON = [
    ("fill", "choice", "solid", ("solid", "space", "time"), None, None, ("Заливка", "Fill")),
    ("color", "color", "#ffffff", None, None, None, ("Цвет слоя", "Layer color")),
    ("stops", "stops", DEFAULT_STOPS, None, None, None, ("Градиент", "Gradient")),
    ("gangle", "angle", 0, 0, 359, 1, ("Направление градиента", "Gradient direction")),
    ("power", "range", 1.0, 0, 1, 0.05, ("Яркость", "Brightness")),
    ("fade", "range", 0.15, 0, 0.5, 0.01, ("Плавность входа и выхода", "Fade in and out")),
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
        ],
    },
}
CHOICE_LABELS = {
    "right": ("→", "→"), "left": ("←", "←"), "down": ("↓", "↓"), "up": ("↑", "↑"),
    "reveal": ("Полосой", "With a stripe"), "flash": ("Вспышкой", "As a flash"),
    "still": ("Всё время", "All the time"),
    "fit": ("Целиком", "Whole"), "stretch": ("Растянуть", "Stretch"),
    "solid": ("Один цвет", "One color"), "space": ("По оружию", "Across the weapon"),
    "time": ("Во времени", "Over time"),
}


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clean_stops(value) -> list:
    """Точки градиента [[позиция 0…1, #rrggbb]], от 2 до MAX_STOPS, по порядку."""
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
    """Цвет градиента 0…1 в точках x (любой формы) → (..., 3)."""
    pos = [st[0] for st in stops]
    cols = np.array([[int(st[1][i:i + 2], 16) / 255 for i in (1, 3, 5)] for st in stops])
    return np.stack([np.interp(x, pos, cols[:, c]) for c in range(3)], axis=-1)


# ── Узор: проверка ───────────────────────────────────────────────────────── #

def _defaults(kind: str) -> dict:
    out = {"type": kind, "on": True, "start": 0.0, "end": 0.9}
    for key, _view, default, *_rest in _COMMON + LAYER_TYPES[kind]["fields"]:
        out[key] = [list(st) for st in default] if key == "stops" else default
    return out


def new_layer(kind: str) -> dict:
    return _defaults(kind)


def clean_spec(spec) -> dict:  # noqa: C901
    """Узор из присланного: известные типы, поля в пределах, не больше
    MAX_LAYERS слоёв. Мусор не роняет сборку — берутся умолчания."""
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
                              else int(round(v)) if view == "seed" or key in ("count", "pulses")
                              else v)
        layers.append(layer)
    quality = (spec or {}).get("quality") if isinstance(spec, dict) else None
    return {"layers": layers, "quality": quality if quality in QUALITY else "medium"}


# ── Отрисовка ────────────────────────────────────────────────────────────── #

def _noise(w: int, h: int, cells_y: float, cells_x: float, seed: int) -> np.ndarray:
    """Плавный шум 0…1 размером h×w: cells_y клеток по высоте, cells_x по
    ширине (в пространстве оружия клетки квадратные), бесшовный по обеим
    осям — дымку можно сдвигать под любым углом."""
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


def _band(q: np.ndarray, center: float, width: float, soft: float) -> np.ndarray:
    """Полоса шириной `width` вокруг center: мягкость 1 — треугольник,
    ближе к 0 — резкий край."""
    z = np.abs(q - center) / max(width / 2, 1e-4)
    return np.clip((1 - z) / max(soft, 0.05), 0, 1)


def _resolve_image(value: str) -> Optional[Path]:
    """Файл картинки слоя, всегда абсолютным путём: в библиотеке узор
    хранит её как images/<файл>, страница присылает полный путь.

    Абсолютным - обязательно: в приложении папка работ задана относительно
    (data_dir() = "."), и относительный путь, отданный странице, при
    следующем превью искался уже внутри библиотеки - картинка пропадала."""
    if not value:
        return None
    p = Path(value)
    if not p.is_absolute():
        inside = library_dir() / value
        p = inside if inside.is_file() else p
    p = p.resolve()
    return p if p.is_file() else None


def _load_image(layer: dict, h: int, w: int, aspect: float) -> Optional[np.ndarray]:
    """Картинка слоя в маске (h×w, 0…1): «целиком» — с пропорцией картинки
    на оружии, «растянуть» — на весь бок оружия."""
    from PIL import Image

    path = _resolve_image(layer.get("image", ""))
    if not path:
        return None
    with Image.open(path) as src:
        img = src.convert("RGBA")
    # Яркость × прозрачность: прозрачное и чёрное блеском не светится.
    lum = Image.fromarray((np.asarray(img.convert("L"), np.float32)
                           * np.asarray(img.getchannel("A"), np.float32) / 255).astype(np.uint8))
    if layer.get("fit") == "stretch":
        return np.asarray(lum.resize((w, h), Image.LANCZOS), np.float32) / 255
    # Холст в пропорции оружия, картинка по центру целиком; потом холст
    # приводится к маске — на оружии игра растянет её обратно в пропорцию.
    cw, ch = max(1, int(round(h * aspect))), h
    scale = min(cw / lum.width, ch / lum.height)
    pic = lum.resize((max(1, int(lum.width * scale)), max(1, int(lum.height * scale))), Image.LANCZOS)
    canvas = Image.new("L", (cw, ch), 0)
    canvas.paste(pic, ((cw - pic.width) // 2, (ch - pic.height) // 2))
    return np.asarray(canvas.resize((w, h), Image.LANCZOS), np.float32) / 255


def mask_shape(aspect: float, quality: str = "medium") -> tuple:
    """(высота, ширина) маски. Высота — от качества, ширина — степень двойки
    по пропорции оружия: игра растягивает маску на бок оружия, и квадратная
    маска 128×128 давала на стволе 3:1 всего ~43 точки на высоту по длине."""
    h = QUALITY.get(quality, QUALITY["medium"])
    w = 2 ** int(round(math.log2(max(4.0, h * max(0.5, aspect)))))
    return h, int(min(1024, max(16, w)))


class _Layer:
    """Слой, готовый к отрисовке: всё, что не зависит от кадра, считается
    один раз. Маска h×w; x — вдоль оружия 0…A, y — по высоте 0…1."""

    def __init__(self, spec: dict, h: int, w: int, aspect: float):
        self.s = spec
        self.h, self.w = h, w
        self.aspect = aspect
        # float32: на маске 256×1024 вдвое меньше памяти и заметно быстрее.
        v, u = np.mgrid[0:h, 0:w].astype(np.float32)
        self.x = (u + 0.5) / w * np.float32(aspect)  # пространство оружия
        self.y = (v + 0.5) / h
        if spec.get("fill") == "space":
            self.gfield = self._along(float(spec["gangle"]))[0]
        if "angle" in spec:
            # Направление слоя за проход не меняется — проекции один раз,
            # а не на каждый кадр (на 256×1024 это половина всего расчёта).
            q, r, span = self._along(float(spec["angle"]))
            self.motion = (q * span, r, span)
        kind = spec["type"]
        if kind == "flash":
            self.grain = _fbm(w, h, 3, 3 * aspect, 5)
        elif kind == "sparkle":
            rng = np.random.default_rng(int(spec["seed"]))
            n = int(spec["count"])
            life = float(spec["life"])
            self.pos = np.column_stack([rng.random(n) * aspect, rng.random(n)])
            self.birth = rng.random(n) * max(0.0, 1 - life)
            self.stamp = self._stamp()
        elif kind == "clouds":
            # Шум шире маски вдвое — есть куда плыть; бесшовный. Клетки
            # квадратные на оружии: по длине их в A раз больше.
            cells = 12.0 / float(spec["scale"])
            cloud = _fbm(w * 2, h, cells, cells * aspect * 2, int(spec["seed"]))
            # Сетка шума видна ступеньками — сглаживаем один раз.
            from PIL import Image, ImageFilter
            img = Image.fromarray((cloud * 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(h / 48))
            self.cloud = np.asarray(img, np.float32) / 255
        elif kind == "image":
            try:
                self.pic = _load_image(spec, h, w, aspect)
            except Exception as exc:                       # noqa: BLE001
                logger.warning(f"[sheen] картинка слоя не читается: {exc}")
                self.pic = None

    def colour(self, s: float) -> np.ndarray:
        """Цвет слоя: (3,) или (h, w, 3). «По оружию» — градиент под углом
        `gangle`, «во времени» — по доле s отрезка слоя."""
        fill = self.s.get("fill", "solid")
        if fill == "solid":
            hexc = self.s["color"]
            return np.array([int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)])
        stops = self.s["stops"]
        if fill == "time":
            return _gradient(stops, np.array(s))
        return _gradient(stops, self.gfield)

    def _along(self, angle: float) -> tuple:
        """Координата вдоль направления под углом (0…1 от края до края
        оружия) и поперёк него (0…1). Угол в пространстве оружия: на
        плитке и на боку оружия 45° — это правда диагональ."""
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
        поперечная 0…1) для угла слоя."""
        q, r, span = self.motion
        margin = 0.6
        front = -margin + (span + 2 * margin) * p
        return q, front, r

    def blank(self) -> np.ndarray:
        return np.zeros((self.h, self.w))

    def frame(self, s: float) -> np.ndarray:
        """Яркость слоя 0…1 в доле s его отрезка времени."""
        sp = self.s
        fade = float(sp["fade"])
        fade_env = max(0.0, 1.0 if fade <= 0 else min(1.0, s / fade, (1 - s) / fade))
        env = fade_env * float(sp["power"])
        kind = sp["type"]
        if kind == "stripe":
            q, front, across = self._moving(s)
            q = (q + math.tan(math.radians(sp["tilt"])) * (across - 0.5)
                 + sp["wave"] * np.sin(2 * np.pi * sp["waves"] * across + s * 6))
            # Полоса j стоит в front - j·spacing. Точку задевают только
            # ближайшие полосы — считаем их, а не все (до 12) на всю маску.
            n = int(sp["count"])
            d = max(float(sp["spacing"]), 1e-3)
            reach = int(math.ceil(float(sp["width"]) / 2 / d)) + 1
            out = np.zeros_like(q)
            trail = 1 - float(sp["trail"])
            if n <= 2 * reach + 1:
                for j in range(n):
                    out = np.maximum(out, trail ** j * _band(q, front - j * d, sp["width"], sp["soft"]))
                return out * env
            near = np.floor((front - q) / d)
            for off in range(-reach, reach + 1):
                j = near + off
                ok = (j >= 0) & (j < n)
                if not ok.any():
                    continue
                band = _band(q, front - j * d, sp["width"], sp["soft"]) * np.power(trail, np.clip(j, 0, n))
                out = np.maximum(out, np.where(ok, band, 0.0))
            return out * env
        if kind == "flash":
            beat = np.sin(np.pi * int(sp["pulses"]) * s) ** 2
            beat = beat ** (1 + 6 * float(sp["sharp"]))
            g = float(sp["grain"])
            return (1 - g + g * self.grain) * beat * env
        if kind == "sparkle":
            # Искры гаснут сами — плавность слоя только приглушает край.
            return self._sparkles(s) * min(1.0, fade_env * 3) * float(sp["power"])
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
                return self.pic * env
            if mode == "flash":
                return self.pic * np.sin(np.pi * s) ** 2 * float(sp["power"])
            q, front, _r = self._moving(s)
            return self.pic * _band(q, front, sp["width"], 1.0) * float(sp["power"])
        return self.blank()

    def _stamp(self) -> np.ndarray:
        """Одна искра в пикселях маски: точка и лучи креста — круглая на
        оружии при любой пропорции маски."""
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
        return dot

    def _sparkles(self, s: float) -> np.ndarray:
        h, w = self.h, self.w
        out = np.zeros((h, w))
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


def render(spec: dict, count: int, aspect: float = DEFAULT_ASPECT,
           quality: Optional[str] = None) -> List[np.ndarray]:
    """Кадры маски RGBA uint8 (h×w по `mask_shape`): кадр 0 пустой, слои
    складываются по max. `quality` — вместо качества узора (превью
    шаблонов считается мельче)."""
    spec = clean_spec(spec)
    aspect = min(12.0, max(0.5, float(aspect or DEFAULT_ASPECT)))
    h, w = mask_shape(aspect, quality or spec["quality"])
    layers = [_Layer(l, h, w, aspect) for l in spec["layers"] if l["on"]]
    blank = np.zeros((h, w, 4), np.uint8)
    blank[..., 3] = 255
    out = [blank]
    for i in range(1, count):
        t = (i - 1) / max(1, count - 2)
        acc = np.zeros((h, w, 3), np.float32)
        for layer in layers:
            a, b = layer.s["start"], layer.s["end"]
            if a <= t <= b:
                s = (t - a) / max(b - a, 1e-6)
                lum = layer.frame(s)
                # Слои складываются «светлее»: по каждому каналу ярчайший.
                acc = np.maximum(acc, lum[..., None] * layer.colour(s))
        rgb = np.clip(acc * PEAK, 0, 255).astype(np.uint8)
        out.append(np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)]))
    return out


def mod_bytes(count: int, aspect: float, quality: str) -> int:
    """Сколько маска весит в моде: DXT1 — полбайта на точку, кадров count."""
    h, w = mask_shape(aspect, quality)
    return count * h * w // 2


def preview_sheet(spec: dict, count: int, aspect: float, out_png: Path) -> dict:
    """Кадры одной картинкой-сеткой для превью страницы — те же, что уйдут
    в мод, в том же качестве. Ширина листа до 4096 точек."""
    from PIL import Image

    frames = render(spec, count, aspect)
    h, w = frames[0].shape[:2]
    cols = max(1, 4096 // w)
    rows = (len(frames) + cols - 1) // cols
    sheet = np.zeros((rows * h, cols * w, 3), np.uint8)
    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = f[..., :3]
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(sheet).save(out_png)
    quality = clean_spec(spec)["quality"]
    return {"image": str(out_png), "frames": len(frames), "cols": cols, "cell_w": w, "cell_h": h,
            "bytes": mod_bytes(len(frames), aspect, quality)}


def thumbnail(spec: dict, aspect: float, out_png: Path) -> str:
    """Один кадр узора (самый яркий из прохода) — карточка шаблона."""
    from PIL import Image

    frames = render(spec, 31, aspect, "low")
    best = max(frames, key=lambda f: int(f[..., :3].sum()))
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(best[..., :3]).save(out_png)
    return str(out_png)


# ── Библиотека своих узоров ──────────────────────────────────────────────── #

def library_dir() -> Path:
    """work/sheen_patterns — рядом с работами (у dev-сервера своя папка)."""
    from src.services import work_store
    return (Path(work_store.WORK_DIR) / "sheen_patterns").resolve()


def list_patterns() -> List[dict]:
    folder = library_dir()
    out = []
    for path in sorted(folder.glob("u*.json")) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if ID_RE.match(path.stem):
            out.append({"id": path.stem, "name": str(data.get("name") or path.stem),
                        "length": float(data.get("length") or 2.5)})
    return sorted(out, key=lambda p: p["name"].lower())


def load(pattern_id: str, deleted: bool = False) -> Optional[dict]:
    """Узор по id. `deleted` — искать и среди удалённых: сборка работы, где
    узор ещё стоит, не должна падать из-за того, что его убрали из списка."""
    if not ID_RE.match(str(pattern_id or "")):
        return None
    path = library_dir() / f"{pattern_id}.json"
    if deleted and not path.exists():
        path = library_dir() / "deleted" / f"{pattern_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    spec = clean_spec(data.get("spec"))
    for layer in spec["layers"]:
        path = _resolve_image(layer.get("image", "")) if layer["type"] == "image" else None
        if path:
            layer["image"] = str(path)
    return {"id": pattern_id, "name": str(data.get("name") or pattern_id),
            "length": float(data.get("length") or 2.5), "spec": spec}


def save(pattern_id: Optional[str], name: str, spec: dict, length: float) -> str:
    """Сохраняет узор; картинки слоёв копируются в библиотеку (по
    содержимому), чтобы узор не зависел от временных файлов."""
    folder = library_dir()
    (folder / "images").mkdir(parents=True, exist_ok=True)
    if not ID_RE.match(str(pattern_id or "")):
        pattern_id = "u" + secrets.token_hex(4)
    from PIL import Image

    spec = clean_spec(spec)
    for layer in spec["layers"]:
        src = _resolve_image(layer.get("image", "")) if layer["type"] == "image" else None
        if src:
            try:
                with Image.open(src) as img:
                    img.load()
            except Exception as exc:                       # noqa: BLE001
                raise ValueError(f"картинка {src.name} не читается: {exc}") from exc
        if src and src.is_absolute() and folder not in src.parents:
            digest = hashlib.sha1(src.read_bytes()).hexdigest()[:16]
            target = folder / "images" / f"{digest}{src.suffix.lower() or '.png'}"
            if not target.exists():
                shutil.copyfile(src, target)
            layer["image"] = f"images/{target.name}"
        elif src and folder in src.parents:
            layer["image"] = src.relative_to(folder).as_posix()
    data = {"name": (name or "").strip()[:60] or "Мой узор", "length": float(length or 2.5),
            "spec": spec}
    (folder / f"{pattern_id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    return pattern_id


def delete(pattern_id: str) -> bool:
    if not ID_RE.match(str(pattern_id or "")):
        return False
    path = library_dir() / f"{pattern_id}.json"
    if not path.exists():
        return False
    trash = library_dir() / "deleted"
    trash.mkdir(parents=True, exist_ok=True)
    path.replace(trash / path.name)
    return True


def content_hash(pattern_id: str) -> str:
    """Отпечаток узора: в моде маска лежит под ним, чтобы моды, собранные до
    и после правки узора, не делили один путь с разным содержимым."""
    data = load(pattern_id, deleted=True)
    if data is None:
        return ""
    blob = json.dumps(data["spec"], sort_keys=True).encode()
    for layer in data["spec"]["layers"]:
        path = _resolve_image(layer.get("image", "")) if layer["type"] == "image" else None
        if path:
            blob += path.read_bytes()
    return hashlib.sha1(blob).hexdigest()[:8]


# ── Готовые стартовые узоры (как готовые узоры эффекта) ─────────────────── #

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
