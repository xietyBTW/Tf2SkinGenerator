"""
Конструктор $phongwarptexture - двумерного градиента, который красит блик

Как его читает игра (source-sdk-2013, common_vertexlitgeneric_dx9.h,
SpecularAndRimTerms): блик умножается на
`tex2D(phongwarp, float2(блик, френель))`:

  * X (столбец) - сила блика в точке, (L·R)^k: 0 - вне блика, 1 - его центр;
  * Y (строка) - френель (1 − N·V)²: 0 - поверхность смотрит на зрителя,
    1 - край модели, взгляд по касательной;
  * множитель: белый - блик как был, цвет - блик этого цвета, ярче белого
    не бывает, силу блика задаёт $phongboost;
  * читается ЛИНЕЙНО (skin_dx9_helper.cpp не включает sRGB для сэмплера) -
    цвета пишутся в файл как есть;
  * с ним отключается обычная маска $phongfresnelranges (вики Valve, $phong)

256×256, BGR888, CLAMPS/CLAMPT, без мипов - MATERIAL_MAPS['phongwarp'].
У Valve 77 материалов TF2 с phongwarp (v_bat, c_ambassador, c_pomson…)
"""

from __future__ import annotations

import colorsys
import re
from typing import Dict

import numpy as np

from src.services.lightwarp import clean_stops, stops_curve

SIZE = 256
PRESETS = ('rainbow', 'oil', 'gold', 'custom')
MAX_BANDS = 6
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')

DEFAULTS = {
    'preset': 'rainbow',
    'strength': 100,            # 0 - блик белый, 100 - узор целиком
    'bands': 2,                 # сколько раз проходит радуга / плёнка
    'shift': 0,                 # сдвиг оттенка, 0..100 (= полный круг)
    'edge_color': '#80c0ff',    # цвет блика у края модели
    'edge': 0,                  # сила этого цвета, 0..100
    'stops': [[0.0, '#4060ff'], [1.0, '#ffffff']],   # «Свой»: от края блика к центру
    # Направление цветов точек по квадрату, градусы: 0 - слева направо
    # (от края блика к центру), 90 - сверху вниз (от камеры к краю модели)
    'angle': 0,
    # Второй ряд точек: цвета у края модели (низ квадрата). Верх берёт первый
    # ряд, низ - второй, между ними плавный переход
    'edge_row': False,
    'edge_stops': [[0.0, '#ff4080'], [1.0, '#ffd0e0']],
}
#: Золото: тёмная медь у края блика, светлая середина, почти белый центр
_GOLD = [[0.0, '#7a3d00'], [0.5, '#ffae3d'], [1.0, '#fff4d6']]


def clean_params(raw) -> Dict[str, object]:
    """Параметры со страницы -> проверенные (лишнее и битое - к умолчаниям)"""
    raw = raw if isinstance(raw, dict) else {}

    def num(key, lo, hi):
        try:
            return int(min(hi, max(lo, round(float(raw.get(key, DEFAULTS[key]))))))
        except (TypeError, ValueError):
            return DEFAULTS[key]

    edge = str(raw.get('edge_color', '')).strip()
    stops = raw.get('stops')
    edge_stops = raw.get('edge_stops')
    return {
        'preset': raw.get('preset') if raw.get('preset') in PRESETS else DEFAULTS['preset'],
        'strength': num('strength', 0, 100),
        'bands': num('bands', 1, MAX_BANDS),
        'shift': num('shift', 0, 100),
        'edge_color': edge.lower() if _HEX.match(edge) else DEFAULTS['edge_color'],
        'edge': num('edge', 0, 100),
        'stops': clean_stops(stops) if stops else [list(st) for st in DEFAULTS['stops']],
        'angle': num('angle', -360, 360) % 360,
        'edge_row': bool(raw.get('edge_row')),
        'edge_stops': (clean_stops(edge_stops) if edge_stops
                       else [list(st) for st in DEFAULTS['edge_stops']]),
    }


def _along(angle: float, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Положение 0..1 вдоль направления `angle` (как linear-gradient в CSS:
    угол в угол квадрата - от 0 до 1)"""
    a = np.radians(angle)
    c, s = np.cos(a), np.sin(a)
    span = abs(c) + abs(s)
    return np.clip(0.5 + ((u - 0.5) * c + (v - 0.5) * s) / span, 0.0, 1.0)


def _sample(curve: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Цвет полоски (256×3) в положениях t (любой формы) -> t.shape + (3,)"""
    return curve[np.rint(t * (len(curve) - 1)).astype(int)]


def _hex(colour: str) -> np.ndarray:
    return np.array([int(colour[i:i + 2], 16) for i in (1, 3, 5)], np.float64) / 255.0


def image(params) -> np.ndarray:
    """Градиент SIZE×SIZE×3 uint8: строка - френель, столбец - сила блика"""
    p = clean_params(params)
    u = np.linspace(0.0, 1.0, SIZE)[None, :]          # блик
    v = np.linspace(0.0, 1.0, SIZE)[:, None]          # френель
    shift = p['shift'] / 100.0

    if p['preset'] == 'rainbow':
        # Радужный отлив, как у Охотника из Episode Two (вики Valve): оттенок
        # бежит и вдоль блика, и к краю модели
        hue = (p['bands'] * (0.45 * u + 0.55 * v) + shift) % 1.0
        rgb = np.vectorize(lambda h: colorsys.hsv_to_rgb(h, 0.85, 1.0), otypes=[object])
        pattern = np.array([list(c) for c in rgb(hue).ravel()], np.float64).reshape(SIZE, SIZE, 3)
    elif p['preset'] == 'oil':
        # Бензиновая плёнка: полосы интерференции от толщины, которая растёт
        # к краю модели, у каналов разная «длина волны»
        thickness = p['bands'] * (0.25 + 0.75 * v) + 0.2 * u + shift
        waves = np.array([1.0, 1.25, 1.55])
        pattern = 0.5 + 0.5 * np.cos(2 * np.pi * (thickness[..., None] * waves))
    else:
        # Градиент из точек - по выбранному направлению, со вторым рядом -
        # сверху цвета первого ряда, снизу (край модели) второго
        stops = _GOLD if p['preset'] == 'gold' else p['stops']
        t = _along(p['angle'], u + 0 * v, v + 0 * u)
        pattern = _sample(stops_curve(stops), t)
        if p['preset'] == 'custom' and p['edge_row']:
            edge_pattern = _sample(stops_curve(p['edge_stops']), t)
            pattern = pattern + (edge_pattern - pattern) * np.broadcast_to(v, t.shape)[..., None]

    white = np.ones_like(pattern)
    out = white + (pattern - white) * (p['strength'] / 100.0)
    if p['edge']:
        weight = (p['edge'] / 100.0) * (v ** 2)        # к краю модели
        out = out + (_hex(p['edge_color'])[None, None, :] - out) * weight[..., None]
    return (np.clip(out, 0.0, 1.0) * 255).round().astype(np.uint8)


def preview(params, size: int = 64) -> list:
    """Уменьшенный градиент для живого превью (полный - 196 тысяч чисел)"""
    full = image(params)
    step = SIZE // size
    return full[::step, ::step].tolist()


def write_png(params, out_path: str, tf2_root: str = '') -> str:
    """PNG 256×256 для сборки. `tf2_root` не нужен - сигнатура как у lightwarp"""
    from PIL import Image

    Image.fromarray(image(params), 'RGB').save(out_path)
    return out_path


if __name__ == '__main__':
    for name in PRESETS:
        img = image({'preset': name})
        assert img.shape == (SIZE, SIZE, 3) and img.dtype == np.uint8, name
    flat = image({'preset': 'rainbow', 'strength': 0})
    assert flat.min() == 255                         # сила 0 - блик как был
    edge = image({'preset': 'custom', 'stops': [[0, '#ffffff'], [1, '#ffffff']],
                  'edge': 100, 'edge_color': '#ff0000'})
    assert tuple(edge[-1, 128]) == (255, 0, 0) and tuple(edge[0, 128]) == (255, 255, 255)
    assert clean_params({'bands': 99, 'preset': 'x'})['bands'] == MAX_BANDS
    red_blue = [[0, '#ff0000'], [1, '#0000ff']]
    down = image({'preset': 'custom', 'stops': red_blue, 'angle': 90})
    assert tuple(down[0, 10]) == (255, 0, 0) and tuple(down[-1, 10]) == (0, 0, 255)
    two = image({'preset': 'custom', 'stops': [[0, '#ffffff'], [1, '#ffffff']],
                 'edge_row': True, 'edge_stops': [[0, '#00ff00'], [1, '#00ff00']]})
    assert tuple(two[0, 5]) == (255, 255, 255) and tuple(two[-1, 5]) == (0, 255, 0)
    print('ok')
