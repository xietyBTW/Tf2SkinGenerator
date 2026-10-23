"""
Сцена «На персонаже» для надеваемого оружия: тот же воркер, что у шапок

Проверяется только то, чем оружие отличается от шапки: модель ищется по
ключу предмета среди путей-кандидатов, класс берётся из режима, а в руках у
персонажа - стоковое оружие, как у шапки
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.app import weapon_wear                                   # noqa: E402
from src.data.stock_loadout import StockWeapon                    # noqa: E402
from src.services import hat_scene_worker as hsw                  # noqa: E402

STOCK = [StockWeapon("primary", "PRIMARY", "models/rocket.mdl"),
         StockWeapon("secondary", "SECONDARY", "models/shotgun.mdl"),
         StockWeapon("melee", "MELEE", "models/shovel.mdl")]


def _run(**kw):
    w = hsw.HatScenePreviewWorker({"soldier": ["models/item.mdl"]}, "misc.vpk", "tex.vpk",
                                  tf2_root="root", tf2_class="soldier", **kw)
    got = {"decompiled": [], "slots": None, "scene": None}
    w.slots_available.connect(lambda info: got.__setitem__("slots", info))

    def decompile(key, mdl, slow=""):
        got["decompiled"].append((key, mdl))
        return f"dir/{key}"

    def build(**scene):
        got["scene"] = scene
        return {"parts": []}

    with patch.object(hsw.stock_loadout, "loadout", lambda *_a: list(STOCK)), \
         patch.object(w, "_decompile", decompile), \
         patch.object(hsw, "body_smd", lambda d: f"{d}/body.smd"), \
         patch.object(w, "_stance_of", lambda *a: (SimpleNamespace(
             smd_path="stand.smd", name="stand", fps=30.0), 0.0)), \
         patch.object(hsw, "root_rotation", lambda *_a: 0.0), \
         patch.object(hsw.viewmodel_animation, "build_scene", lambda **s: build(**s)), \
         patch.object(w, "_emit_scene", lambda *a: None):
        w.run()
    return got


def test_worn_weapon_keeps_the_stock_loadout_like_a_hat():
    got = _run(weapon_key="c_rocketboots_soldier", slot="melee")
    assert got["slots"]["slots"] == ["primary", "secondary", "melee"]
    assert got["scene"]["weapon_carrier_smd"].endswith("body.smd")   # лопата в руке
    assert got["decompiled"][0] == ("c_rocketboots_soldier", ["models/item.mdl"])


def test_scene_args_know_the_class_and_the_custom_model():
    host = SimpleNamespace(_mode="soldier_c_rocketboots_soldier", preview=SimpleNamespace(
        custom_smd_path="my.smd", custom_keep_materials=True))
    with patch("src.services.extract_model_service.ExtractModelService._build_paths_to_try",
               lambda *a: ["models/workshop/weapons/c_models/c_rocketboots_soldier.mdl"]):
        args = weapon_wear.scene_args(host, "")
    assert list(args["hat_models"]) == ["soldier"]
    assert (args["weapon_key"], args["custom_smd"], args["custom_keep"]) == (
        "c_rocketboots_soldier", "my.smd", True)
