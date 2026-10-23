"""
Конструктор $lightwarptexture - полоски, которая перекрашивает освещение

Как её читает игра (source-sdk-2013, common_vertexlitgeneric_dx9.h,
DiffuseTerm): освещённость точки в half-lambert, `0.5·N·L + 0.5` (0 - тень,
1 - прямой свет), - это координата X полоски, а результат
`2.0 · tex1D(lightwarp, x)`. Отсюда:

  * пиксель 128 (0.5) = обычная яркость, 255 = пересвет вдвое;
  * полоска читается ЛИНЕЙНО (EnableSRGBRead для её сэмплера не зовётся ни в
    vertexlitgeneric_dx9_helper.cpp, ни в skin_dx9_helper.cpp) - пишем числа
    как есть, без гамма-коррекции;
  * нужна ширина 256 (больше - без пользы), высота 1, BGR888 без сжатия
    (DXT даёт полосы на градиенте), CLAMPS/CLAMPT, без мипов -
    developer.valvesoftware.com/wiki/$lightwarptexture. Формат и флаги
    задаёт MATERIAL_MAPS['lightwarp']

Основа - НАСТОЯЩИЕ полоски игры, а не придуманные формулы: нейтральная
`dev/identitylightwarp` (Valve: «как будто lightwarp нет») S-образная, и её
приближение x/2 ошибается до 7/255. Без игры основа - x/2
"""

from __future__ import annotations

import os
import re
from typing import Dict, Tuple

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

WIDTH = 256

#: Основы: (VPK относительно корня игры, путь текстуры). Сколько материалов
#: TF2 берёт каждую, посчитано по tf2_misc/tf2_textures
PRESETS: Dict[str, Tuple[str, str]] = {
    # 6231 материал: персонажи и большинство вещей
    'tf2_player': ('tf/tf2_textures_dir.vpk', 'models/player/pyro/pyro_lightwarp'),
    # 956: резкая двухтоновая ступень
    'tf2_weapon': ('tf/tf2_textures_dir.vpk', 'models/lightwarps/weapon_lightwarp'),
    # 123: мягкий переход
    'tf2_soft': ('tf/tf2_textures_dir.vpk', 'models/lightwarps/softened_weapon_lightwarp'),
    # Valve: так модель выглядит без $lightwarptexture
    'neutral': ('hl2/hl2_textures_dir.vpk', 'dev/identitylightwarp'),
}
DEFAULT_PRESET = 'tf2_player'
#: Своя основа - цветные точки (`stops`), их значения пишутся в файл как есть
CUSTOM = 'custom'
MAX_STEPS = 8
MAX_STOPS = 16
#: «Как без lightwarp» по яркости: от чёрного до 128 (в игре ×2 = обычная)
DEFAULT_STOPS = [[0.0, '#000000'], [1.0, '#808080']]

#: Значения по умолчанию - «полоска основы как есть»
DEFAULTS = {
    'preset': DEFAULT_PRESET,
    'steps': 0,                 # 0 - плавно, 2..8 - ступени (cel shading)
    'shadow_color': '#4060c0',
    'shadow': 0,                # сила оттенка теней, 0..100
    'light_color': '#ffd090',
    'light': 0,                 # сила оттенка света, 0..100
    'brightness': 100,          # 50..150 %
    'stops': DEFAULT_STOPS,     # только у основы CUSTOM: [[позиция 0..1, '#rrggbb'], …]
}

_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def clean_params(raw) -> Dict[str, object]:
    """Параметры со страницы -> проверенные (всё лишнее и битое - к умолчаниям)"""
    raw = raw if isinstance(raw, dict) else {}

    def num(key, lo, hi):
        try:
            return int(min(hi, max(lo, round(float(raw.get(key, DEFAULTS[key]))))))
        except (TypeError, ValueError):
            return DEFAULTS[key]

    def color(key):
        value = str(raw.get(key, '')).strip()
        return value.lower() if _HEX.match(value) else DEFAULTS[key]

    steps = num('steps', 0, MAX_STEPS)
    preset = raw.get('preset')
    return {
        'preset': preset if preset in PRESETS or preset == CUSTOM else DEFAULT_PRESET,
        'stops': clean_stops(raw.get('stops')),
        'steps': 0 if steps == 1 else steps,
        'shadow_color': color('shadow_color'),
        'shadow': num('shadow', 0, 100),
        'light_color': color('light_color'),
        'light': num('light', 0, 100),
        'brightness': num('brightness', 50, 150),
    }


def clean_stops(raw) -> list:
    """Точки градиента: 2..16 штук, позиция 0..1, цвет #rrggbb, по порядку"""
    stops = []
    for item in raw if isinstance(raw, (list, tuple)) else ():
        try:
            pos, colour = float(item[0]), str(item[1]).strip().lower()
        except (TypeError, ValueError, IndexError):
            continue
        if _HEX.match(colour):
            stops.append([round(min(1.0, max(0.0, pos)), 4), colour])
    stops.sort(key=lambda st: st[0])
    if len(stops) < 2:
        return [list(st) for st in DEFAULT_STOPS]
    return stops[:MAX_STOPS]


def stops_curve(stops) -> np.ndarray:
    """Полоска из точек: между соседними - прямая по каждому каналу. Две
    точки на одной позиции - резкая граница (cel shading без ступеней)"""
    x = np.linspace(0.0, 1.0, WIDTH)
    pos = np.array([st[0] for st in stops], np.float64)
    # np.interp ждёт неубывающие позиции, совпавшие разводим на волосок
    pos = pos + np.arange(len(pos)) * 1e-6
    rgb = np.array([[int(st[1][i:i + 2], 16) for i in (1, 3, 5)] for st in stops],
                   np.float64) / 255.0
    return np.stack([np.interp(x, pos, rgb[:, c]) for c in range(3)], axis=1)


def to_stops(curve: np.ndarray, tolerance: int = 3) -> list:
    """Готовая полоска (256×3 uint8) -> немного точек, по которым она
    повторяется с ошибкой не больше `tolerance` из 255. Резкая ступень
    weapon_lightwarp так и остаётся резкой: точку кладём туда, где ошибка
    наибольшая"""
    curve = np.asarray(curve, np.float64)
    picks = [0, WIDTH - 1]
    while len(picks) < MAX_STOPS:
        approx = np.stack([np.interp(np.arange(WIDTH), picks, curve[picks, c])
                           for c in range(3)], axis=1)
        error = np.abs(approx - curve).max(axis=1)
        worst = int(error.argmax())
        if error[worst] <= tolerance:
            break
        picks = sorted(picks + [worst])
    return [[round(i / (WIDTH - 1), 4),
             '#%02x%02x%02x' % tuple(int(v) for v in curve[i].round())] for i in picks]


#: {(основа, папка игры): полоска}. Только удачные чтения: запасная x/2,
#: запомненная при занятом VPK, держалась бы до перезапуска
_CURVES: Dict[Tuple[str, str], Tuple[Tuple[float, float, float], ...]] = {}


def _preset_curve(preset: str, tf2_root: str) -> Tuple[Tuple[float, float, float], ...]:
    """Полоска основы из игры: 256 значений RGB 0..1 (средняя строка VTF)"""
    cached = _CURVES.get((preset, tf2_root))
    if cached is not None:
        return cached
    from src.services import normal_map
    from src.services.game_vpk_reader import GameVpkReader

    pak_rel, texture = PRESETS[preset]
    pak = os.path.join(tf2_root or '', *pak_rel.split('/'))
    rgba = None
    if tf2_root and os.path.isfile(pak):
        reader = GameVpkReader([pak])
        try:
            data = reader.find_vtf_for_basetexture(texture)
        finally:
            reader.close()
        rgba = normal_map.rgba_from_vtf(data) if data else None
    if rgba is None:
        logger.warning(f"[lightwarp] основа {preset!r} не найдена в игре - беру x/2")
        x = np.linspace(0.0, 0.5, WIDTH)
        return tuple((v, v, v) for v in x)
    row = rgba[rgba.shape[0] // 2, :, :3].astype(np.float64) / 255.0
    if row.shape[0] != WIDTH:
        src = np.linspace(0.0, 1.0, row.shape[0])
        dst = np.linspace(0.0, 1.0, WIDTH)
        row = np.stack([np.interp(dst, src, row[:, c]) for c in range(3)], axis=1)
    curve = tuple(tuple(px) for px in row)
    _CURVES[(preset, tf2_root)] = curve
    return curve


def _linear(hex_color: str) -> np.ndarray:
    """Цвет из палитры (sRGB) -> линейный: полоска читается линейно"""
    srgb = np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], np.float64) / 255.0
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _tint(curve: np.ndarray, color: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Сдвиг оттенка без изменения яркости: цвет нормируется по яркости, и
    тень остаётся тенью, а свет светом"""
    lum = lambda c: c @ np.array([0.2126, 0.7152, 0.0722])
    hue = color / max(float(lum(color)), 0.05)
    tinted = lum(curve)[:, None] * hue[None, :]
    return curve + (tinted - curve) * weight[:, None]


def ramp(params, tf2_root: str = '') -> np.ndarray:
    """Полоска 256×3 uint8 по параметрам (`clean_params`)"""
    p = clean_params(params)
    if p['preset'] == CUSTOM:
        curve = stops_curve(p['stops'])
    else:
        curve = np.array(_preset_curve(p['preset'], os.path.normpath(tf2_root) if tf2_root else ''))
    x = np.linspace(0.0, 1.0, WIDTH)

    if p['steps']:
        # Ступени: внутри полосы освещённости - значение основы в её
        # середине. Это и есть cel shading из статьи Valve про lightwarp
        n = p['steps']
        band = np.minimum((x * n).astype(int), n - 1)
        centre = ((band + 0.5) / n * (WIDTH - 1)).round().astype(int)
        curve = curve[centre]

    # Оттенки - только у основ игры: в своём градиенте цвет задают точки, и
    # второй способ подкрасить то же место лишь путал бы
    if p['shadow'] and p['preset'] != CUSTOM:
        curve = _tint(curve, _linear(p['shadow_color']), p['shadow'] / 100 * (1 - x) ** 2)
    if p['light'] and p['preset'] != CUSTOM:
        curve = _tint(curve, _linear(p['light_color']), p['light'] / 100 * x ** 2)
    curve = curve * (p['brightness'] / 100)
    return (np.clip(curve, 0.0, 1.0) * 255).round().astype(np.uint8)


def write_png(params, out_path: str, tf2_root: str = '') -> str:
    """PNG 256×1 для сборки (формат и флаги VTF - из MATERIAL_MAPS)"""
    from PIL import Image

    Image.fromarray(ramp(params, tf2_root)[None, :, :], 'RGB').save(out_path)
    return out_path


if __name__ == '__main__':
    flat = {'preset': 'neutral', 'steps': 3}
    r = ramp(flat)                                    # без игры: основа x/2
    assert r.shape == (WIDTH, 3) and r.dtype == np.uint8
    assert len({tuple(px) for px in r}) == 3          # ровно три ступени
    assert r[0, 0] < r[-1, 0]                         # тень темнее света
    assert clean_params({'steps': 99, 'shadow_color': 'red'})['steps'] == MAX_STEPS
    blue = ramp({'preset': 'neutral', 'shadow': 100, 'shadow_color': '#0000ff'})
    assert blue[40, 2] > blue[40, 0]                  # тени посинели
    own = ramp({'preset': CUSTOM, 'stops': [[0, '#ff0000'], [1, '#0000ff']]})
    assert tuple(own[0]) == (255, 0, 0) and tuple(own[-1]) == (0, 0, 255)
    step = ramp({'preset': CUSTOM, 'stops': [[0, '#000000'], [0.5, '#000000'],
                                             [0.5, '#808080'], [1, '#808080']]})
    assert len({tuple(px) for px in step}) <= 3       # резкая граница
    back = stops_curve(to_stops(step)) * 255
    assert np.abs(back - step).max() <= 3             # точки повторяют полоску
    print('ok')
