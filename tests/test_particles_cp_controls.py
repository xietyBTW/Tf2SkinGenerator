"""Полоса контрол-пойнтов в редакторе частиц.

Логика мелкая, но кусачая: значения хранятся на каждый CP отдельно, нулевые
углы означают СБРОС ориентации (нули — это не дефолтный базис движка, а
поворот «смотрим по +X»), а при сборке виджета setValue уже дёргает отправку
в превью, когда половины полей ещё нет.

Тест пропускается, если PySide6 недоступен или подменён заглушкой соседних
worker-тестов.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Worker-тесты подменяют PySide6 заглушкой в sys.modules и не возвращают её
# обратно. Поднимать настоящий PySide6 поверх такой заглушки нельзя: часть
# модулей уже импортирована с фейком, и смесь роняет процесс по access
# violation. Поэтому в общем прогоне модуль пропускается — как соседний
# test_simple_params. Запуск отдельно: pytest tests/test_particles_cp_controls.py
_pyside = sys.modules.get("PySide6")
if _pyside is not None and not hasattr(_pyside, "__path__"):
    pytest.skip("PySide6 подменён заглушкой соседних тестов",
                allow_module_level=True)

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from src.data.translations import TRANSLATIONS          # noqa: E402
from src.ui.particles_panel import _CpControlsWidget    # noqa: E402
from src.ui.styled_dialog import _colors                # noqa: E402


class _FakeView:
    """Ловушка вызовов ParticleViewWidget."""

    def __init__(self):
        self.calls = []

    def set_control_point(self, i, x, y, z):
        self.calls.append(("pos", i, x, y, z))

    def set_control_point_orientation(self, i, pitch, yaw, roll):
        self.calls.append(("ang", i, pitch, yaw, roll))

    def clear_control_point_orientation(self, i):
        self.calls.append(("clear", i))

    def set_control_point_motion(self, i, kind, amp, period):
        self.calls.append(("motion", i, kind, amp, period))

    def load_model_obj(self, obj_text, textures=None):
        self.calls.append(("model_obj", len(obj_text), dict(textures or {})))

    def set_model_visible(self, visible):
        self.calls.append(("model_visible", visible))

    def clear_model(self):
        self.calls.append(("model_clear",))


@pytest.fixture(scope="module")
def _app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def widget(_app):
    view = _FakeView()
    w = _CpControlsWidget(view, TRANSLATIONS["ru"], _colors())
    # Сборка не должна ничего отправлять: поля ещё неполные
    assert view.calls == []
    return w, view


def test_position_and_zero_angles_reset_orientation(widget):
    w, view = widget
    w.pos_spins[2].setValue(40.0)
    assert ("pos", 0, 0.0, 0.0, 40.0) in view.calls
    assert ("clear", 0) in view.calls
    assert not any(c[0] == "ang" for c in view.calls)


def test_nonzero_angles_go_to_preview(widget):
    w, view = widget
    w.ang_spins[1].setValue(90.0)
    assert ("ang", 0, 0.0, 90.0, 0.0) in view.calls


def test_motion_preset_sent_with_amp_and_period(widget):
    w, view = widget
    view.calls.clear()
    w.motion_combo.setCurrentIndex(3)          # orbit
    assert ("motion", 0, "orbit", 24.0, 2.0) in view.calls


def test_values_are_per_control_point(widget):
    w, _ = widget
    w.ang_spins[1].setValue(90.0)
    w.motion_combo.setCurrentIndex(4)          # spin
    w.cp_index.setValue(1)
    assert [sp.value() for sp in w.ang_spins] == [0.0, 0.0, 0.0]
    assert w.motion_combo.currentData() == "none"
    w.cp_index.setValue(0)
    assert [sp.value() for sp in w.ang_spins] == [0.0, 90.0, 0.0]
    assert w.motion_combo.currentData() == "spin"


def test_reset_clears_current_control_point(widget):
    w, view = widget
    w.pos_spins[0].setValue(30.0)
    w.ang_spins[0].setValue(45.0)
    view.calls.clear()
    w._on_reset()
    assert [sp.value() for sp in w.pos_spins] == [0.0, 0.0, 0.0]
    assert [sp.value() for sp in w.ang_spins] == [0.0, 0.0, 0.0]
    assert ("clear", 0) in view.calls


def test_language_switch_keeps_state_and_is_silent(widget):
    w, view = widget
    w.motion_combo.setCurrentIndex(3)
    view.calls.clear()
    w.update_language(TRANSLATIONS["en"])
    assert view.calls == []
    assert w.motion_combo.currentData() == "orbit"
    assert w.motion_combo.itemText(3).startswith("Orbit")


def test_attachment_fills_position_and_orientation(widget):
    """Выбор точки крепления кладёт в превью и позицию, и углы: в игре CP
    получает от attachment именно трансформ, а не одну точку."""
    from src.services.model_attachments import Attachment

    w, view = widget
    w._attachments = [Attachment("unusual_0", "weapon_bone",
                                 (0.0, 3.77, 45.82), (-90.0, 0.0, 0.0))]
    w._loading = True
    try:
        w.attach_combo.addItem("unusual_0  (weapon_bone)", 0)
        w.attach_combo.setEnabled(True)
    finally:
        w._loading = False

    view.calls.clear()
    w._on_attachment(0)
    assert ("pos", 0, 0.0, 3.8, 45.8) in view.calls, view.calls
    assert ("ang", 0, -90.0, 0.0, 0.0) in view.calls, view.calls
    assert [sp.value() for sp in w.ang_spins] == [-90.0, 0.0, 0.0]


def test_scene_mode_needs_a_model(widget, monkeypatch):
    """«На модели» без выбранной модели не переключает сцену: сначала надо
    выбрать модель, а если пользователь отказался — остаёмся в мире."""
    w, view = widget
    monkeypatch.setattr(w, "_on_pick_model", lambda: None)
    view.calls.clear()
    w._set_scene_mode(True)
    assert w._model_mode is False
    assert view.calls == []


def test_scene_mode_toggles_model_visibility(widget):
    w, view = widget
    w._model_loaded = True          # как после удачной загрузки меша
    view.calls.clear()
    w._set_scene_mode(True)
    assert ("model_visible", True) in view.calls
    assert w._model_mode is True
    view.calls.clear()
    w._set_scene_mode(False)
    assert ("model_visible", False) in view.calls
    assert w._model_mode is False


_TRI_SMD = """version 1
nodes
  0 "root" -1
end
skeleton
  time 0
    0 0 0 0 0 0 0
end
triangles
mat
  0 0.0 0.0 0.0 0.0 0.0 1.0 0.0 0.0
  0 1.0 0.0 0.0 0.0 0.0 1.0 1.0 0.0
  0 0.0 1.0 0.0 0.0 0.0 1.0 0.0 1.0
end
"""


def test_load_model_mesh_sends_obj_without_game_path(widget, tmp_path):
    """Меш строится из reference-SMD и уходит в превью; без пути к игре
    текстур нет, но модель всё равно показывается — серой."""
    w, view = widget
    (tmp_path / "m.smd").write_text(_TRI_SMD, encoding="utf-8")
    qc = tmp_path / "m.qc"
    qc.write_text('$modelname "m.mdl"\n$cdmaterials "models/test/"\n',
                  encoding="utf-8")

    view.calls.clear()
    assert w._load_model_mesh(str(qc)) is True
    sent = [c for c in view.calls if c[0] == "model_obj"]
    assert len(sent) == 1, view.calls
    assert sent[0][1] > 0          # OBJ не пустой
    assert sent[0][2] == {}        # путь к игре не задан — текстур нет
