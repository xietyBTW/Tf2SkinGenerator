"""
Компоновщик War Paint: рецепт из `data/paintkit_defs.py` → текстура оружия.

В игре это делает закрытый CTextureCompositor (materialsystem.dll) шейдером
`compositor_ps2x.fxc` — он в SDK открыт, и математика взята оттуда:

* текстуры читаются как sRGB и считаются в линейном пространстве, результат
  пишется в sRGB (EnableSRGBRead/EnableSRGBWrite в compositor.cpp); маска
  групп читается без перевода;
* уровни (black / white / gamma) — «как в Photoshop», в sRGB;
* multiply / add — произведение и сумма входов, lerp — смешивание двух входов
  по красному каналу третьего, select — белое там, где номер группы
  (`round(R·255/16)`) совпал с одним из `select/16`;
* наклейка кладётся по альфе, её «блеск» (spec) — в альфу результата.

Чего в SDK нет — порядок случайных значений и сборка матрицы UV — взято по
открытому повтору компоновщика (github.com/Rhgx/warpaint-viewer, сверен с
игрой его автором): матрица R·S·(uv + T), сид делится на два потока
CUniformRandomStream (Numerical Recipes ran1), узлы берут из них значения по
очереди. Код оттуда не переносился — только формулы.

Модуль без Qt и без UI: на вход дерево и функция чтения текстур, на выход
RGBA uint8.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Функция чтения текстуры: (путь материала, raw) → RGBA uint8 (H,W,4) или
#: None, если такой текстуры в игре нет. raw — данные, а не цвет (маска групп):
#: уменьшать её можно только выбрасыванием текселей, усреднение смешало бы
#: номера соседних групп.
TextureLoader = Callable[..., Optional[np.ndarray]]


# ── CUniformRandomStream ──────────────────────────────────────────────── #

class UniformRandomStream:
    """vstdlib/random.cpp (Numerical Recipes ran1) — генератор компоновщика."""

    NTAB, IA, IM, IQ, IR = 32, 16807, 2147483647, 127773, 2836
    NDIV = 1 + (IM - 1) // NTAB
    AM = 1.0 / IM
    RNMX = 1.0 - 1.2e-7
    MAX_RANGE = 0x7FFFFFFF

    def __init__(self, seed: int):
        seed = int(seed)
        self.idum = seed if seed < 0 else -seed
        self.iy = 0
        self.iv = [0] * self.NTAB

    def _generate(self) -> int:
        if self.idum <= 0 or not self.iy:
            self.idum = max(1, -self.idum)
            for j in range(self.NTAB + 7, -1, -1):
                k = int(self.idum / self.IQ)
                self.idum = self.IA * (self.idum - k * self.IQ) - self.IR * k
                if self.idum < 0:
                    self.idum += self.IM
                if j < self.NTAB:
                    self.iv[j] = self.idum
            self.iy = self.iv[0]
        k = int(self.idum / self.IQ)
        self.idum = self.IA * (self.idum - k * self.IQ) - self.IR * k
        if self.idum < 0:
            self.idum += self.IM
        j = int(self.iy / self.NDIV)
        if j < 0 or j >= self.NTAB:
            j &= self.NTAB - 1
        self.iy = self.iv[j]
        self.iv[j] = self.idum
        return self.iy

    def random_float(self, low: float = 0.0, high: float = 1.0) -> float:
        value = min(self.AM * self._generate(), self.RNMX)
        return value * (high - low) + low

    def random_int(self, low: int, high: int) -> int:
        span = high - low + 1
        if span <= 1 or self.MAX_RANGE < span - 1:
            return low
        max_ok = self.MAX_RANGE - ((self.MAX_RANGE + 1) % span)
        while True:
            value = self._generate()
            if value <= max_ok:
                return low + value % span


def _to_int32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


class _Seeds:
    """Два потока по сиду War Paint: чётные биты сида — первому, нечётные — второму."""

    def __init__(self, seed: int):
        seed &= (1 << 64) - 1
        lo = hi = 0
        for i in range(32):
            lo |= ((seed >> (2 * i)) & 1) << i
            hi |= ((seed >> (2 * i + 1)) & 1) << i
        self.streams = [UniformRandomStream(_to_int32(lo)),
                        UniformRandomStream(_to_int32(hi))]
        self.current = 0

    @property
    def rng(self) -> UniformRandomStream:
        return self.streams[self.current]

    def advance(self) -> None:
        self.current ^= 1


# ── Разбор значений ───────────────────────────────────────────────────── #

def _range(text: str) -> Optional[Tuple[float, float]]:
    parts = str(text or '').replace(',', ' ').split()
    try:
        nums = [float(p) for p in parts[:2]]
    except ValueError:
        return None
    if not nums:
        return None
    return (nums[0], nums[-1])


def _atoi(text) -> int:
    """atoi(): ведущие цифры, мусор после них отбрасывается ("96```" → 96)."""
    s = str(text or '').strip()
    n = ''
    for ch in s:
        if ch.isdigit() or (not n and ch in '+-'):
            n += ch
        else:
            break
    try:
        return int(n)
    except ValueError:
        return 0


@dataclass
class Transform:
    black: float = 0.0
    white: float = 1.0
    gamma: float = 1.0
    rotation: float = 0.0
    translate_u: float = 0.0
    translate_v: float = 0.0
    scale: float = 1.0
    flip_u: bool = False
    flip_v: bool = False

    def is_identity_uv(self) -> bool:
        return (self.rotation == 0 and self.translate_u == 0 and self.translate_v == 0
                and self.scale == 1 and not self.flip_u and not self.flip_v)

    def is_identity_levels(self) -> bool:
        return self.black == 0 and self.white == 1 and self.gamma == 1

    def matrix(self) -> np.ndarray:
        """UV-матрица 2×3: R·S·(uv + T) — порядок Source."""
        rad = math.radians(self.rotation)
        c, s = math.cos(rad), math.sin(rad)
        sx = (-1 if self.flip_u else 1) * self.scale
        sy = (-1 if self.flip_v else 1) * self.scale
        tu, tv = self.translate_u, self.translate_v
        return np.array([[c * sx, -s * sy, c * sx * tu - s * sy * tv],
                         [s * sx, c * sy, s * sx * tu + c * sy * tv]], dtype=np.float64)


def _levels(fields: Dict[str, str], seeds: _Seeds) -> Tuple[float, float, float]:
    """black / white / gamma: чёрная и «отступ» — из 0…255, gamma обратная."""
    rng = seeds.rng
    black = _draw(rng, fields.get('adjust_black'), 0.0, scale=1 / 255)
    offset = _draw(rng, fields.get('adjust_offset'), 255.0, scale=1 / 255)
    gamma = _draw(rng, fields.get('adjust_gamma'), 1.0, inverse=True)
    return black, black + offset, gamma


def _draw(rng: UniformRandomStream, text, default: float,
          scale: float = 1.0, inverse: bool = False) -> float:
    """Значение из диапазона «a b» (или одного числа) — всегда одно чтение потока."""
    rg = _range(text) if text not in (None, '') else None
    low, high = rg if rg else (default, default)
    if inverse:
        low = 1.0 / low if low else 1.0
        high = 1.0 / high if high else 1.0
    return rng.random_float(low * scale, high * scale)


def _flip(rng: UniformRandomStream, text) -> bool:
    """flip "1" — случайное отражение (одно чтение), "0"/пусто — без чтения."""
    rg = _range(text) if text not in (None, '') else None
    if not rg:
        return False
    low, high = int(rg[0]), int(rg[1])
    if low == high:
        return rng.random_int(0, 1) != 0 if low else False
    return rng.random_int(low, high) != 0


# ── Выборка текстур ───────────────────────────────────────────────────── #

def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


class _Texture:
    """Текстура с пирамидой уровней (как mip-карты у видеокарты)."""

    def __init__(self, rgba: np.ndarray, srgb: bool, max_size: int):
        img = rgba.astype(np.float32) / 255.0
        while max(img.shape[:2]) > max_size and min(img.shape[:2]) >= 2:
            # Цвет усредняем, данные (маску групп) прореживаем.
            img = _half(img) if srgb else img[::2, ::2]
        if srgb:
            img[..., :3] = srgb_to_linear(img[..., :3])
        self.levels = [img]
        while min(self.levels[-1].shape[:2]) >= 2:
            self.levels.append(_half(self.levels[-1]))

    def level_for(self, footprint: float) -> np.ndarray:
        """Уровень, у которого тексель примерно равен пикселю результата."""
        lod = int(math.floor(math.log2(footprint))) if footprint > 1 else 0
        return self.levels[min(max(lod, 0), len(self.levels) - 1)]


def _half(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[0] // 2 * 2, img.shape[1] // 2 * 2
    img = img[:h, :w]
    return (img[0::2, 0::2] + img[1::2, 0::2] + img[0::2, 1::2] + img[1::2, 1::2]) * 0.25


def _bilinear(img: np.ndarray, u: np.ndarray, v: np.ndarray, wrap: bool = True) -> np.ndarray:
    """Билинейная выборка в UV (v вниз, как у текстур Source); повтор по краям."""
    h, w = img.shape[:2]
    x = u * w - 0.5
    y = v * h - 0.5
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = (x - x0)[..., None].astype(np.float32)
    fy = (y - y0)[..., None].astype(np.float32)
    x0 = x0.astype(np.int64)
    y0 = y0.astype(np.int64)
    if wrap:
        x0 %= w
        y0 %= h
        x1 = (x0 + 1) % w
        y1 = (y0 + 1) % h
    else:
        x1 = np.clip(x0 + 1, 0, w - 1)
        y1 = np.clip(y0 + 1, 0, h - 1)
        x0 = np.clip(x0, 0, w - 1)
        y0 = np.clip(y0, 0, h - 1)
    top = img[y0, x0] * (1 - fx) + img[y0, x1] * fx
    bottom = img[y1, x0] * (1 - fx) + img[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def adjust_levels(rgba: np.ndarray, black: float, white: float, gamma: float) -> np.ndarray:
    """AdjustLevels из compositor_ps2x.fxc: уровни в sRGB, результат снова линейный."""
    if black == 0 and white == 1 and gamma == 1:
        return rgba
    out = rgba.copy()
    out[..., :3] = linear_to_srgb(out[..., :3])
    if white == black:
        # invlerp с нулевым отрезком — в шейдере бесконечность, после saturate
        # это порог: выше чёрной точки 1, ниже 0.
        pcg = (out > black).astype(np.float32)
    else:
        pcg = np.clip((out - black) / (white - black), 0.0, 1.0)
    pcg = np.power(pcg, gamma)
    pcg[..., :3] = srgb_to_linear(pcg[..., :3])
    return np.clip(pcg, 0.0, 1.0)


# ── Узлы ──────────────────────────────────────────────────────────────── #

@dataclass
class _Input:
    """Вход операции: либо текстура (ещё не выбрана), либо готовый слой."""
    transform: Transform
    texture: Optional[_Texture] = None
    image: Optional[np.ndarray] = None


class PaintkitCompositor:
    """Собирает рецепт War Paint в RGBA-текстуру размером ``size``×``size``."""

    def __init__(self, loader: TextureLoader, size: int = 1024, team: str = 'red'):
        self.loader = loader
        self.size = int(size)
        self.blue = str(team).lower().startswith('b')
        self._textures: Dict[Tuple[str, bool], Optional[_Texture]] = {}
        self.missing: List[str] = []
        n = self.size
        grid = (np.arange(n, dtype=np.float64) + 0.5) / n
        self._u, self._v = np.meshgrid(grid, grid)

    # ── Точка входа ───────────────────────────────────────────────────── #

    def compose(self, recipe: dict, seed: int = 0) -> np.ndarray:
        """RGBA uint8 (sRGB, альфа — маска блеска, как у игры)."""
        seeds = _Seeds(int(seed))
        root = self._eval(recipe, seeds)
        linear = self._sample(root)
        out = linear.copy()
        out[..., :3] = linear_to_srgb(out[..., :3])
        return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)

    # ── Текстуры ──────────────────────────────────────────────────────── #

    def _texture(self, path: str, srgb: bool = True, report: bool = True) -> Optional[_Texture]:
        """Текстура рецепта; report=False — отсутствие нормально (необязательный spec)."""
        key = (path, srgb)
        if key not in self._textures:
            rgba = self.loader(path, raw=not srgb) if path else None
            if rgba is None:
                if report and path and path not in self.missing:
                    self.missing.append(path)
                    logger.warning(f'[paintkit] нет текстуры: {path}')
                self._textures[key] = None
            else:
                self._textures[key] = _Texture(rgba, srgb, max_size=max(self.size, 16))
        return self._textures[key]

    def _sample(self, inp: _Input) -> np.ndarray:
        """Вход на сетке результата: выборка по UV-матрице и уровни."""
        t = inp.transform
        if inp.image is not None:
            img = inp.image
            if not t.is_identity_uv():
                img = self._resample(img, t)
        elif inp.texture is not None:
            tex = inp.texture
            base = tex.levels[0]
            footprint = abs(t.scale) * max(base.shape[:2]) / self.size
            img = self._resample(tex.level_for(footprint), t)
        else:
            img = np.ones((self.size, self.size, 4), np.float32)
        return adjust_levels(img, t.black, t.white, t.gamma)

    def _resample(self, img: np.ndarray, t: Transform) -> np.ndarray:
        m = t.matrix()
        u = m[0, 0] * self._u + m[0, 1] * self._v + m[0, 2]
        v = m[1, 0] * self._u + m[1, 1] * self._v + m[1, 2]
        if img.shape[0] == self.size and img.shape[1] == self.size and t.is_identity_uv():
            return img
        return _bilinear(img, u, v, wrap=True)

    # ── Вычисление узлов (порядок чтения случайных чисел — как в игре) ── #

    def _eval(self, node: dict, seeds: _Seeds) -> _Input:
        kind = node['type']
        fields = node.get('fields') or {}
        if kind == 'texture_lookup':
            rng = seeds.rng
            flip_u = _flip(rng, fields.get('flip_u'))
            flip_v = _flip(rng, fields.get('flip_v'))
            tu = _draw(rng, fields.get('translate_u'), 0.0)
            tv = _draw(rng, fields.get('translate_v'), 0.0)
            rot = _draw(rng, fields.get('rotation'), 0.0)
            scale = _draw(rng, fields.get('scale_uv'), 1.0)
            black, white, gamma = _levels(fields, seeds)
            seeds.advance()
            path = fields.get('texture') or ''
            team_path = fields.get('texture_blue' if self.blue else 'texture_red')
            if team_path:
                path = team_path
            return _Input(Transform(black, white, gamma, rot, tu, tv,
                                    scale or 1.0, flip_u, flip_v),
                          texture=self._texture(path))
        if kind == 'select':
            return _Input(Transform(), image=self._select(node))
        if kind == 'apply_sticker':
            return self._sticker(node, seeds)
        # combine_*: у самого узла только уровни — применяются, когда его
        # результат читает родитель; UV-поля у combine игра не использует.
        black, white, gamma = _levels(fields, seeds)
        seeds.advance()
        children = [self._eval(child, seeds) for child in node.get('nodes') or []]
        return _Input(Transform(black, white, gamma), image=self._combine(kind, children))

    def _combine(self, kind: str, children: List[_Input]) -> np.ndarray:
        n = self.size
        layers = [self._sample(c) for c in children]
        if kind == 'combine_lerp':
            if len(layers) < 3:
                logger.warning(f'[paintkit] lerp с {len(layers)} входами')
                return np.ones((n, n, 4), np.float32)
            a, b, sel = layers[0], layers[1], layers[2][..., :1]
            out = a + (b - a) * sel
        elif kind == 'combine_add':
            out = np.zeros((n, n, 4), np.float32)
            for layer in layers:
                out = out + layer
        else:
            out = np.ones((n, n, 4), np.float32)
            for layer in layers:
                out = out * layer
        # Промежуточный слой в игре — 8-битная текстура: всё за [0, 1] срезается.
        return np.clip(out, 0.0, 1.0).astype(np.float32)

    def _select(self, node: dict) -> np.ndarray:
        n = self.size
        wanted = {round(v / 16.0) for v in (_atoi(s) for s in node.get('select') or []) if v}
        tex = self._texture((node.get('fields') or {}).get('groups', ''), srgb=False)
        if not wanted or tex is None:
            return np.zeros((n, n, 4), np.float32)
        # Ближайший тексель: билинейная выборка на шве двух групп дала бы
        # третью (48 и 80 → 64).
        raw = tex.levels[0]
        h, w = raw.shape[:2]
        xs = np.minimum((self._u[0] * w).astype(np.int64), w - 1)
        ys = np.minimum((self._v[:, 0] * h).astype(np.int64), h - 1)
        groups = raw[ys[:, None], xs[None, :], 0]
        ids = np.round(groups * 255.0 / 16.0)
        mask = np.isin(ids, list(wanted)).astype(np.float32)
        return np.repeat(mask[..., None], 4, axis=2)

    def _sticker(self, node: dict, seeds: _Seeds) -> _Input:
        fields = node.get('fields') or {}
        rng = seeds.rng
        stickers = node.get('stickers') or []
        weights = [max(_range(s.get('weight'))[0] if _range(s.get('weight')) else 1.0, 0.0)
                   for s in stickers]
        total = sum(weights) or 1.0
        pick = rng.random_float(0.0, total)
        chosen = stickers[0] if stickers else {}
        for s, w in zip(stickers, weights):
            if pick < w:
                chosen = s
                break
            pick -= w
        black, white, gamma = _levels(fields, seeds)
        seeds.advance()
        children = [self._eval(child, seeds) for child in node.get('nodes') or []]
        base = self._sample(children[0]) if children else np.ones(
            (self.size, self.size, 4), np.float32)
        out = self._apply_sticker(base, chosen, fields)
        return _Input(Transform(black, white, gamma), image=out)

    def _apply_sticker(self, base: np.ndarray, sticker: dict, fields: Dict[str, str]) -> np.ndarray:
        """Наклейка по трём углам (tl, tr, bl) в UV: цвет по альфе, блеск — в альфу."""
        art = self._texture(sticker.get('base', ''))
        if art is None:
            return base
        # Пустой spec — «имя основы + _spec» (комментарий к полю в .proto); нет
        # и его — блеск нулевой. Читается как sRGB: compositor.cpp для ps20b
        # включает EnableSRGBRead на всех четырёх сэмплерах.
        spec_name = sticker.get('spec') or ''
        if not spec_name and sticker.get('base'):
            stem, ext = os.path.splitext(sticker['base'])
            spec_name = f'{stem}_spec{ext}'
        spec = self._texture(spec_name, srgb=True, report=False) if spec_name else None

        def corner(key, default):
            rg = _range(fields.get(key))
            text = str(fields.get(key) or '').replace(',', ' ').split()
            if len(text) >= 2:
                try:
                    return float(text[0]), float(text[1])
                except ValueError:
                    pass
            return default if not rg else (rg[0], rg[1])

        tl = np.array(corner('dest_tl', (0.0, 0.0)))
        tr = np.array(corner('dest_tr', (1.0, 0.0)))
        bl = np.array(corner('dest_bl', (0.0, 1.0)))
        ex, ey = tr - tl, bl - tl
        det = ex[0] * ey[1] - ex[1] * ey[0]
        if abs(det) < 1e-12:
            return base
        du, dv = self._u - tl[0], self._v - tl[1]
        s = (du * ey[1] - dv * ey[0]) / det
        t = (ex[0] * dv - ex[1] * du) / det
        inside = ((s >= 0) & (s <= 1) & (t >= 0) & (t <= 1))[..., None]
        color = _bilinear(art.levels[0], s, t, wrap=False)
        alpha = color[..., 3:4] * inside
        spec_r = (_bilinear(spec.levels[0], s, t, wrap=False)[..., :1]
                  if spec is not None else np.zeros_like(alpha))
        out = base.copy()
        out[..., :3] = base[..., :3] * (1 - alpha) + color[..., :3] * alpha
        out[..., 3:4] = base[..., 3:4] * (1 - alpha) + spec_r * alpha
        return out
