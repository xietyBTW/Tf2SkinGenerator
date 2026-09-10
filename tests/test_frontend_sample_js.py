"""
Пипетка берёт цвет ОТТУДА, куда ткнули.

Кадр показывает текстуру целиком (`object-fit: contain`), и квадратной она
бывает не всегда: у тела шпиона 1024×512, и по одной оси у кадра остаются
поля. Ошибка во вписывании даёт не поломку, а цвет соседнего пикселя — на
глаз такое не отличить от правды, поэтому арифметика проверяется числами.

Тест пропускается, если node недоступен.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SAMPLE_JS = Path("frontend/mockup/sample.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not SAMPLE_JS.exists(),
    reason="node недоступен или sample.js не найден")

#: (рамка, картинка, щелчок) → ожидаемый пиксель или None («мимо»).
_CASES = [
    # Квадратная текстура в квадратном кадре: полей нет.
    (((256, 256), (512, 512), (0, 0)), (0, 0)),
    (((256, 256), (512, 512), (128, 128)), (256, 256)),
    (((256, 256), (512, 512), (255.9, 255.9)), (511, 511)),
    # 1024×512 в квадратном кадре: поля сверху и снизу по четверти высоты.
    (((256, 256), (1024, 512), (0, 64)), (0, 0)),
    (((256, 256), (1024, 512), (128, 128)), (512, 256)),
    (((256, 256), (1024, 512), (128, 63)), None),
    (((256, 256), (1024, 512), (128, 193)), None),
    # 512×1024: поля слева и справа.
    (((256, 256), (512, 1024), (64, 0)), (0, 0)),
    (((256, 256), (512, 1024), (63, 128)), None),
    # Кадр меньше текстуры и наоборот — масштаб в обе стороны.
    (((64, 64), (512, 512), (32, 32)), (256, 256)),
    (((1024, 1024), (64, 64), (512, 512)), (32, 32)),
    # За краем рамки: щелчок мимо кадра тоже «мимо».
    (((256, 256), (512, 512), (-1, 10)), None),
    (((256, 256), (512, 512), (10, 256)), None),
]


def _js(cases) -> list:
    """Гоняет containPixel в Node на тех же входах."""
    script = f"""
import {{ containPixel, rgbHex }} from {SAMPLE_JS.as_uri()!r};
const cases = {json.dumps([c for c, _ in cases])};
const out = cases.map(([box, size, point]) => {{
  const at = containPixel({{ w: box[0], h: box[1] }},
                          {{ w: size[0], h: size[1] }},
                          {{ x: point[0], y: point[1] }});
  return at ? [at.x, at.y] : null;
}});
console.log(JSON.stringify({{ pixels: out, hex: rgbHex(0, 8, 255) }}));
"""
    tmp = SAMPLE_JS.parent / "_sample_check.mjs"
    tmp.write_text(script, encoding="utf-8")
    try:
        res = subprocess.run(["node", str(tmp)], capture_output=True,
                             text=True, timeout=60)
    finally:
        tmp.unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_contain_fit_maps_the_click_to_the_right_pixel():
    got = _js(_CASES)
    for (inputs, want), pixel in zip(_CASES, got["pixels"]):
        assert pixel == (list(want) if want else None), inputs


def test_hex_keeps_two_digits_per_channel():
    """«#0008ff», а не «#08ff»: короткий код поле цвета не примет."""
    assert _js(_CASES)["hex"] == "#0008ff"
