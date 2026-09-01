"""
Камера вида от первого лица (viewer_camera.js) через Node.

Ошибку здесь Python-тесты не увидят: сцена соберётся правильно, а камера
встанет не туда — и вьюмодель окажется за спиной или боком. Оси не абстрактные,
а замеренные на настоящих моделях TF2 (см. комментарий в модуле): после
конвертации осей вперёд — это +Z, вверх — +Y.

Тест пропускается, если node недоступен.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path("src/static/js/viewer_camera.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not MODULE.exists(),
    reason="node недоступен или viewer_camera.js не найден")


def _run(body: str) -> dict:
    script = f"""
import {{ firstPersonCamera, clampFov, DEFAULT_RIG, DEFAULT_VIEWMODEL_FOV,
         MIN_VIEWMODEL_FOV, MAX_VIEWMODEL_FOV }} from {MODULE.as_uri()!r};
const out = (() => {{ {body} }})();
console.log(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_camera_sits_in_the_eye_and_looks_forward():
    """Глаз в начале координат, взгляд по +Z — это и есть кадр игрока."""
    out = _run("return firstPersonCamera({});")
    assert out["position"] == [0, 0, 0]
    assert out["target"] == [0, 0, 1]
    assert out["up"] == [0, 1, 0]
    assert out["fov"] == 54


def test_eye_offset_moves_the_target_with_it():
    """Сдвиг глаза — калибровочная ручка; направление взгляда меняться не должно."""
    out = _run("return firstPersonCamera({eye: [1, -2, 3]});")
    assert out["position"] == [1, -2, 3]
    assert out["target"] == [1, -2, 4]


def test_forward_is_normalized():
    out = _run("return firstPersonCamera({forward: [0, 0, 10]});")
    assert out["target"] == [0, 0, 1]


def test_degenerate_direction_falls_back_instead_of_producing_nan():
    """Нулевой вектор взгляда развалил бы матрицу вида — лучше вернуться к дефолту."""
    out = _run("return firstPersonCamera({forward: [0, 0, 0], up: [0, 0, 0]});")
    assert out["target"] == [0, 0, 1]
    assert out["up"] == [0, 1, 0]


def test_broken_input_is_survivable():
    out = _run("""return [
        firstPersonCamera(null),
        firstPersonCamera({eye: 'nope', forward: [1], up: [0, 'x', 0]}),
    ];""")
    for camera in out:
        assert camera["position"] == [0, 0, 0]
        assert camera["target"] == [0, 0, 1]
        assert camera["up"] == [0, 1, 0]


def test_fov_is_clamped_to_a_usable_range():
    out = _run("""return {
        low:  clampFov(1),
        high: clampFov(400),
        ok:   clampFov(70),
        junk: clampFov('abc'),
        none: clampFov(undefined),
        min:  MIN_VIEWMODEL_FOV,
        max:  MAX_VIEWMODEL_FOV,
    };""")
    assert out["low"] == out["min"]
    assert out["high"] == out["max"]
    assert out["ok"] == 70
    assert out["junk"] == 54 and out["none"] == 54


def test_rig_fov_reaches_the_camera():
    out = _run("return firstPersonCamera({fov: 90});")
    assert out["fov"] == 90


def test_defaults_are_the_measured_axes():
    """Если конвертацию осей когда-нибудь поменяют, тест обязан упасть здесь."""
    out = _run("return DEFAULT_RIG;")
    assert out == {"eye": [0, 0, 0], "forward": [0, 0, 1],
                   "up": [0, 1, 0], "fov": 54}
