"""Сборка мультиклассовой шапки — ровно для выбранных классов."""

from types import SimpleNamespace

from src.app.session import AppSession as Session

MODELS = {
    "scout": "models/hat/hat_scout.mdl",
    "spy": "models/hat/hat_spy.mdl",
    "medic": "models/hat/hat_medic.mdl",
}


def _session(preview_model="models/hat/hat_scout.mdl"):
    s = SimpleNamespace(_hat_models=dict(MODELS),
                        preview=SimpleNamespace(weapon_key=preview_model))
    s._hat_models_for = lambda classes: Session._hat_models_for(s, classes)
    return s


def test_single_selected_class_is_the_one_built():
    # В превью скаут, выбран только шпион: собираться должен шпион. Раньше
    # основной шла модель превью, и шпион в мод не попадал вовсе.
    primary, models = Session._hat_build_models(_session(), ["spy"])
    assert primary == MODELS["spy"]
    assert list(models.values()) == [MODELS["spy"]]


def test_unselected_preview_class_is_not_primary():
    primary, models = Session._hat_build_models(_session(), ["spy", "medic"])
    assert primary in (MODELS["spy"], MODELS["medic"])
    assert MODELS["scout"] not in models.values()


def test_selected_preview_class_stays_primary():
    primary, _ = Session._hat_build_models(_session(), ["medic", "scout"])
    assert primary == MODELS["scout"]


def test_empty_selection_means_all():
    primary, models = Session._hat_build_models(_session(), [])
    assert primary == MODELS["scout"] and models == MODELS


def test_style_builds_follow_class_selection():
    s = SimpleNamespace(_hat_style=0, _hat_styles={
        1: {"image_path": "style.png", "edits": {}, "models": dict(MODELS)},
    })
    [build] = Session._hat_style_builds(s, ["spy"])
    assert build["mdl_paths"] == [MODELS["spy"]]
    [build] = Session._hat_style_builds(s, [])
    assert sorted(build["mdl_paths"]) == sorted(MODELS.values())
