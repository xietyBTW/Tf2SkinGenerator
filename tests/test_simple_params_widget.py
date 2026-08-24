"""Виджет простого режима: редакторы крутилок поверх схемы SIMPLE_PARAMS.

Проверяется то, на чём легко потерять данные пользователя: значение вне
мягкого диапазона (ползунок) должно показываться КАК ЕСТЬ и не переписываться
при построении строки, а программная установка значения не должна выглядеть
как правка.

Тест пропускается, если PySide6 недоступен или подменён заглушкой соседних
worker-тестов (см. test_particles_cp_controls).
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_pyside = sys.modules.get("PySide6")
if _pyside is not None and not hasattr(_pyside, "__path__"):
    pytest.skip("PySide6 подменён заглушкой соседних тестов",
                allow_module_level=True)

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from src.data.translations import TRANSLATIONS            # noqa: E402
from src.services import simple_params                    # noqa: E402
from src.ui.particles_panel import _SimpleParamsWidget     # noqa: E402
from src.ui.styled_dialog import _colors                   # noqa: E402

PARAMS = {p.key: p for p in simple_params.SIMPLE_PARAMS}


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _sys_json(rate=12.0):
    return {
        "attrs": {"radius": {"t": "float", "v": 5.0},
                  "max_particles": {"t": "integer", "v": 100}},
        "renderers": [],
        "emitters": [{"functionName": "emit_continuously",
                      "attrs": {"emission_rate": {"t": "float", "v": rate}}}],
        "initializers": [], "operators": [], "forces": [], "constraints": [],
        "children": [],
    }


def _widget():
    return _SimpleParamsWidget(TRANSLATIONS["en"], _colors())


def test_value_above_soft_range_is_shown_as_is(app):
    """emission_rate = 2000 при ползунке до 500: поле показывает 2000
    (а не 500), ползунок стоит в конце, в модель ничего не уходит."""
    w = _widget()
    edits = []
    w.edited.connect(lambda p, v: edits.append((p.key, v)))
    w.set_system(_sys_json(rate=2000.0))

    editor = w._rows["spawn_rate"]["editor"]
    assert editor.spin.value() == 2000.0
    assert editor.slider.value() == editor.slider.maximum()
    assert edits == [], "перечитывание значений — не правка"


def test_system_attr_row_is_ready_without_modules(app):
    """У системного параметра (radius) модулей нет вовсе — строка сразу
    рабочая и показывает умолчание, а не заготовку."""
    w = _widget()
    js = _sys_json()
    del js["attrs"]["radius"]
    w.set_system(js)

    row = w._rows["size"]
    assert not row["placeholder"]
    assert row["editor"].spin.isEnabled()
    assert row["editor"].spin.value() == PARAMS["size"].default


def test_missing_module_row_is_editable_placeholder(app):
    """Модуля нет — строка не выключена, а показана бледной заготовкой:
    поле рабочее, в нём умолчание, а подсказка называет модуль, который
    появится при первой правке. Кнопки «Включить» в панели больше нет —
    она съедала колонку и выдавливала подписи за край."""
    w = _widget()
    w.show()                      # видимость строк проверяется только у показанного
    w.set_system(_sys_json())
    row = w._rows["size_range"]   # Radius Random в системе отсутствует
    assert row["placeholder"]
    spin = row["editor"].spins[0]
    assert spin.isEnabled(), "заготовку можно править — это и есть включение"
    assert spin.property("placeholder") is True
    assert spin.value() == PARAMS["size_range"].default
    assert "Radius Random" in spin.toolTip()
    w.hide()


def test_editing_placeholder_emits_edit(app):
    """Правка заготовки уходит наверх обычным сигналом: создание модуля —
    забота панели, виджет о нём не знает."""
    w = _widget()
    edits = []
    w.edited.connect(lambda p, v: edits.append((p.key, v)))
    w.set_system(_sys_json())
    w._rows["size_range"]["editor"].spins[1].setValue(12.0)
    assert [k for k, _ in edits] == ["size_range"]
    assert edits[0][1][1] == 12.0


def test_long_label_is_elided_not_clipped(app):
    """Подпись сокращается многоточием, а полный текст остаётся в
    подсказке: панель узкая, и распирать её подписи не должны."""
    w = _widget()
    w.resize(180, 400)
    w.show()
    label = w._rows["max_particles"]["label"]
    label.setFullText("Очень длинная подпись параметра, которая не влезает")
    label.resize(60, 16)
    assert label.text() != label._full
    assert label.text().endswith("…")
    w.hide()


def test_emitter_only_rows_hidden_without_emitter(app):
    """Крутилки эмиттера (creatable=False) на системе без него не
    показываются: создавать эмиттер за пользователя нельзя — задвоит залп."""
    w = _widget()
    w.show()
    js = _sys_json()
    js["emitters"] = []
    w.set_system(js)
    assert not w._rows["spawn_rate"]["label"].isVisible()
    assert not w._rows["spawn_rate"]["editor"].slider.isVisible()
    w.hide()


def test_slider_edit_emits_curved_value(app):
    """Ползунок посередине на кривой sqrt даёт четверть диапазона, а не
    половину — и уходит в модель одной правкой."""
    w = _widget()
    edits = []
    w.edited.connect(lambda p, v: edits.append((p.key, v)))
    w.set_system(_sys_json())

    editor = w._rows["spawn_rate"]["editor"]
    editor.slider.setValue(editor.slider.maximum() // 2)
    assert [k for k, _ in edits] == ["spawn_rate"]
    assert abs(edits[0][1] - 125.0) < 1.0, edits     # 500 * 0.5² = 125


def test_every_param_has_editor_and_label(app):
    """Схема и виджет не разъезжаются: на каждый SimpleParam есть строка."""
    w = _widget()
    assert set(w._rows) == {p.key for p in simple_params.SIMPLE_PARAMS}
    for key, row in w._rows.items():
        assert row["label"].text(), key
        assert row["editor"].widgets, key


def test_float_decimals_keeps_small_values(app):
    """Диалог правки числа не должен обрезать значение уже при открытии:
    в стоке есть drag -0.0004 и animation rate 1e-5."""
    from src.ui.particles_panel import _float_decimals
    assert _float_decimals(12.5) == 4
    assert _float_decimals(0) == 4
    assert _float_decimals(-0.0004) >= 4
    assert _float_decimals(1e-5) >= 5
    assert _float_decimals(1e-8) >= 8
    assert _float_decimals(1e-30) <= 12          # потолок, а не бесконечность
    assert _float_decimals("nonsense") == 4


def test_attr_row_shows_enum_label(app):
    """Голое «7» в дереве ни о чём не говорит — рядом идёт подпись поля."""
    from PySide6.QtWidgets import QTreeWidgetItem
    from src.ui.particles_panel import ParticlesPanel

    panel = ParticlesPanel.__new__(ParticlesPanel)     # без тяжёлого __init__
    panel.language = "en"
    panel.t = TRANSLATIONS["en"]
    panel._c = _colors()
    item = QTreeWidgetItem(["output field", ""])
    panel._paint_attr_item(item, "output field", {"t": "integer", "v": 7})
    assert item.text(1).startswith("7")
    assert "alpha" in item.text(1)
    assert "output field" in panel._attr_tooltip("output field")
    assert len(panel._attr_tooltip("output field")) > len("output field")


def test_panel_creates_module_on_first_placeholder_edit(app):
    """Сквозь панель: правка заготовки создаёт недостающий модуль и пишет
    в него значение. Это замена кнопке «Включить» — отдельного действия у
    пользователя больше нет."""
    pytest.importorskip("srctools.dmx")
    from PySide6.QtCore import QTimer

    from src.services.particle_editor_service import ParticleEditorService
    from src.ui.particles_panel import ParticlesPanel
    from tests.test_particle_editor_service import _make_pcf_bytes

    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    panel = ParticlesPanel.__new__(ParticlesPanel)   # без тяжёлого __init__
    panel.service = svc
    panel.tf2_root = ""
    panel._payload = {"systems": svc.systems_json(), "materials": {}}
    panel._current_system = "fx"
    panel._simple_pending_attrs = set()
    panel._simple_pending_rebuild = False
    panel._simple_timer = QTimer()

    param = PARAMS["size_range"]
    assert simple_params.read_param(panel._payload["systems"]["fx"], param) is None

    panel._on_simple_edit(param, (2.0, 9.0))

    fresh = svc.systems_json()["fx"]
    assert simple_params.read_param(fresh, param) == (2.0, 9.0)
    assert any(m["functionName"].lower() == "radius random"
               for m in fresh["initializers"])
    assert panel._simple_pending_rebuild, "дереву нужна пересборка: модуль новый"
