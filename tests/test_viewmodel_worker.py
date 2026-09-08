"""
Воркер вида от первого лица: порядок шагов и что уходит наверх.

Геометрию и позу проверяют соседние тесты; здесь — решения самого воркера:
кому отказать, что считать редактируемым и в каком порядке слать сигналы.
Особенно важен отказ: у щитов, ботинок и рюкзаков вида от первого лица нет
вовсе, и показать вместо него пустую сцену хуже, чем честно сказать об этом.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.services import viewmodel_worker as vw            # noqa: E402
from src.services.model_decompile_service import DecompileError, Decompiled  # noqa: E402
from src.services.weapon_anim_catalog import Action, AnimSequence  # noqa: E402


class _Recorder:
    """Собирает всё, что воркер отправил наверх, в порядке отправки."""

    def __init__(self, worker):
        self.order = []
        self.data = {}
        for name in ("ready", "animated_ready", "clip_ready", "multi_material",
                     "editable_materials", "render_hints", "failed",
                     "progress", "actions_available"):
            getattr(worker, name).connect(self._make(name))

    def _make(self, name):
        def slot(*args):
            self.order.append(name)
            self.data[name] = args[0] if len(args) == 1 else args
        return slot


SEQUENCE = AnimSequence(name="sg_idle", smd_path="anims/sg_idle.smd",
                        activity="ACT_PRIMARY_VM_IDLE")
SCENE = SimpleNamespace(
    obj_path="scene.obj",
    weapon_materials=["c_scattergun"],
    # Пушка-носитель праздничной гирлянды: в кадре есть, предмету не
    # принадлежит. У обычного оружия список пуст, но само поле обязано быть —
    # `_scene_materials` читает его у любой сцены.
    carrier_materials=[],
    arms_materials=["scout_hands"],
    materials=["c_scattergun", "scout_hands"],
)

#: Анимированная сцена — основной путь: меш в bind-позе плюс дорожки костей.
ANIMATED = {
    "bones": [{"name": "root", "parent": -1}],
    "parts": [
        {"kind": "weapon", "materials": ["c_scattergun"]},
        {"kind": "arms", "materials": ["scout_hands"]},
    ],
    "clip": {"name": "sg_idle", "times": [0.0], "tracks": []},
}


def _run(worker, *, sequence=SEQUENCE, scene=SCENE, animated=ANIMATED,
         decompile=None, textures=None, resolver=None, on_build=None,
         catalog_actions=(), team_map=None):
    """Прогоняет run() с подменёнными соседями."""
    textures = {"c_scattergun": "gun.png", "scout_hands": "hands.png"} \
        if textures is None else textures

    class _Resolver:
        def __init__(self, *_a, **_k):
            pass

        def texture_map(self, names, _cd):
            return {n: textures.get(n) for n in names}

        def render_map(self, names, _cd):
            return {n: {"blend": "additive"} for n in names if n == "glass"}

    def _build(*_a, **kwargs):
        if on_build is not None:
            on_build(kwargs)
        return scene

    def _build_animated(**kwargs):
        if on_build is not None:
            on_build(kwargs)
        return animated

    decompile = decompile or (lambda key, *a, **k: Decompiled(
        directory=f"decomp/{key}", mdl_rel="x.mdl", cached=True))

    recorder = _Recorder(worker)
    recorder.asked = {}

    def _find(slot, action, replacement=None):
        recorder.asked.update(slot=slot, action=action, replacement=replacement)
        return sequence

    catalog = SimpleNamespace(
        find=_find,
        actions_for=lambda _slot, _rep=None: dict.fromkeys(catalog_actions))
    with patch.object(vw, "GameVpkReader", lambda *_a: SimpleNamespace(close=lambda: None)), \
         patch.object(vw.mds, "ensure_decompiled", decompile), \
         patch.object(vw.anim_catalog, "load", lambda _d: catalog), \
         patch.object(vw.smd_service, "find_reference_smd",
                      lambda d, prefer="": f"{d}/mesh.smd"), \
         patch.object(vw.viewmodel_scene, "build", _build), \
         patch.object(vw.viewmodel_animation, "build_scene", _build_animated), \
         patch.object(vw, "MaterialResolver", resolver or _Resolver), \
         patch.object(vw.qc_skin_parser, "load_model",
                      lambda _d: SimpleNamespace(cdmaterials=["models/x"], bonemerge=[],
                                                team_map=team_map or {},
                                                qc_path="x.qc")):
        worker.run()
    return recorder


def _worker(key="c_scattergun", **kwargs):
    return vw.ViewmodelPreviewWorker(key, "misc.vpk", "textures.vpk",
                                     tf2_root="root", **kwargs)


# ── Успешный путь ─────────────────────────────────────────────────────────── #

def test_scene_and_textures_reach_the_ui():
    """По умолчанию отдаётся анимация: она оказалась не дороже запекания позы."""
    rec = _run(_worker())
    assert rec.data["animated_ready"] is ANIMATED
    assert rec.data["multi_material"] == {"c_scattergun": "gun.png",
                                          "scout_hands": "hands.png"}
    assert "failed" not in rec.data


def test_static_pose_is_still_available():
    """Запечённая поза осталась запасным путём — через OBJ, без скиннинга."""
    rec = _run(_worker(animate=False))
    assert rec.data["ready"] == ("scene.obj", "")
    assert "animated_ready" not in rec.data


def test_only_the_weapon_is_editable():
    """Руки показываются, но пользовательская текстура относится к оружию."""
    rec = _run(_worker())
    assert rec.data["editable_materials"] == ["c_scattergun"]


def test_render_hints_go_before_the_model():
    """Иначе вьювер соберёт материалы дважды, и стекло успеет побыть пластиком."""
    rec = _run(_worker())
    assert rec.order.index("render_hints") < rec.order.index("animated_ready")
    assert rec.order.index("animated_ready") < rec.order.index("multi_material")


def test_textures_of_both_parts_are_collected():
    """У рук свои $cdmaterials — их текстуры лежат не там, где у оружия."""
    seen = []

    class _Resolver:
        def __init__(self, *_a, **_k):
            pass

        def texture_map(self, names, cd):
            seen.append((tuple(names), tuple(cd)))
            return {n: f"{n}.png" for n in names}

        def render_map(self, *_a):
            return {}

    rec = _run(_worker(), resolver=_Resolver)
    assert len(seen) == 2, "текстуры оружия и рук берутся отдельными запросами"
    assert rec.data["multi_material"] == {"c_scattergun": "c_scattergun.png",
                                          "scout_hands": "scout_hands.png"}


def test_material_without_a_texture_is_dropped_not_passed_as_none():
    rec = _run(_worker(), textures={"c_scattergun": "gun.png"})
    assert rec.data["multi_material"] == {"c_scattergun": "gun.png"}


# ── Отказы ────────────────────────────────────────────────────────────────── #

def test_item_without_a_viewmodel_is_refused():
    """У щита нет последовательности — показывать нечего."""
    rec = _run(_worker("c_targe"), sequence=None)
    assert "failed" in rec.data
    assert "first-person" in rec.data["failed"]
    assert "ready" not in rec.data


def test_unknown_weapon_class_is_refused_before_any_work():
    rec = _Recorder(w := _worker("не_оружие"))
    with patch.object(vw.mds, "ensure_decompiled",
                      side_effect=AssertionError("до декомпиляции доходить нельзя")):
        w.run()
    assert "failed" in rec.data
    assert "class" in rec.data["failed"]


def test_missing_model_is_refused():
    rec = _run(_worker(), decompile=lambda *_a, **_k: None)
    assert "failed" in rec.data
    assert "not found" in rec.data["failed"]


def test_scene_that_did_not_build_is_refused():
    rec = _run(_worker(), animated=None)
    assert "failed" in rec.data
    assert "animated_ready" not in rec.data


def test_decompile_error_is_reported_not_swallowed():
    def boom(*_a, **_k):
        raise DecompileError("Crowbar not found: nope.exe")

    rec = _run(_worker(), decompile=boom)
    assert rec.data["failed"] == "Crowbar not found: nope.exe"


# ── Кэш и параметры ───────────────────────────────────────────────────────── #

def test_arms_and_animations_are_cached_per_class_not_per_weapon():
    """Иначе смена оружия вытесняла бы из кэша общие модели класса."""
    keys = []
    _run(_worker(), decompile=lambda key, *a, **k: (
        keys.append(key) or Decompiled(directory=f"d/{key}", mdl_rel="x", cached=True)))
    assert keys == ["c_scattergun", "__arms_scout", "__anims_scout"]


def test_action_and_frame_are_passed_through():
    """Основа для будущего выбора анимации: воркер ничего не зашивает.

    Действие уходит в каталог, кадр — в сборку сцены.
    """
    built = {}
    rec = _run(_worker(action=Action.INSPECT_IDLE, frame_index=7,
                       animate=False), on_build=built.update)

    assert rec.asked["action"] is Action.INSPECT_IDLE
    assert built["frame_index"] == 7


def test_clip_only_skips_geometry_and_textures():
    """Смена анимации не должна трогать ничего, кроме дорожек.

    Иначе каждое нажатие заново распаковывает те же самые VTF: замер дал
    863 мс против 9 мс.
    """
    touched = []

    class _Resolver:
        def __init__(self, *_a, **_k):
            pass

        def texture_map(self, *_a):
            touched.append("текстуры")
            return {}

        def render_map(self, *_a):
            touched.append("свойства")
            return {}

    with patch.object(vw.viewmodel_animation, "build_clip",
                      lambda **_k: {"name": "sg_reload", "times": [0.0]}):
        rec = _run(_worker(clip_only=True), resolver=_Resolver,
                   on_build=lambda _kw: touched.append("геометрия"))

    assert rec.data["clip_ready"]["name"] == "sg_reload"
    assert touched == [], "при смене анимации пересобирать нечего"
    assert "animated_ready" not in rec.data


def test_clip_that_did_not_build_is_reported():
    with patch.object(vw.viewmodel_animation, "build_clip", lambda **_k: None):
        rec = _run(_worker(clip_only=True))
    assert "failed" in rec.data
    assert "clip_ready" not in rec.data


def test_activity_replacement_reaches_the_catalog():
    """Слот у куная melee, а набор — ITEM2; знает об этом только items_game.

    Если подмена не доедет до каталога, все ножи шпиона снова покажут анимацию
    обычного ножа-бабочки.
    """
    kunai = {"ACT_VM_IDLE": "ACT_ITEM2_VM_IDLE"}
    info = SimpleNamespace(slot="melee", replacement=kunai)
    with patch.object(vw.viewmodel_anims, "anim_info", lambda *_a: info):
        rec = _run(_worker("c_shogun_kunai"))
    assert rec.asked["replacement"] == kunai


def test_weapon_without_a_replacement_asks_with_an_empty_table():
    with patch.object(vw.viewmodel_anims, "anim_info", lambda *_a: None):
        rec = _run(_worker())
    assert rec.asked["replacement"] == {}


def test_available_actions_are_reported_for_the_selector():
    """Интерфейс предлагает только то, что это оружие действительно умеет."""
    rec = _run(_worker(), catalog_actions=[Action.IDLE, Action.RELOAD])
    assert rec.data["actions_available"] == ["IDLE", "RELOAD"]


def test_slot_comes_from_items_game_not_from_our_own_table():
    """У револьвера шпиона наша вкладка говорит primary, а игра — secondary.

    Последовательностей `primary_*` у шпиона нет вовсе, так что ошибка здесь
    означала бы «у револьвера нет вида от первого лица».
    """
    with patch.object(vw.viewmodel_anims, "slot_for", return_value="secondary"):
        rec = _run(_worker("c_revolver"))
    assert rec.asked["slot"] == "secondary"



# ── Граница перезарядки ──────────────────────────────────────────────────── #
# Быстрый путь смены анимации меняет только дорожки, но у солдата в перезарядке
# ПОЯВЛЯЕТСЯ ракета: она лежит в модели рук, и в покое её быть не должно. Через
# эту границу сцену нужно собирать заново.

def test_actions_on_one_side_of_the_boundary_share_the_mesh():
    assert vw.same_arms_mesh("IDLE", "INSPECT_IDLE")
    assert vw.same_arms_mesh("RELOAD", "RELOAD_START")


def test_crossing_the_reload_boundary_needs_a_rebuild():
    assert not vw.same_arms_mesh("IDLE", "RELOAD")
    assert not vw.same_arms_mesh("RELOAD_FINISH", "FIRE")


def test_unknown_action_name_counts_as_no_prop():
    assert vw.same_arms_mesh("", "IDLE")
    assert not vw.same_arms_mesh("нет_такого", "RELOAD")


# ── Командные руки ───────────────────────────────────────────────────────── #
#
# У медика, снайпера, инженера, пиро, подрывника, солдата и шпиона рукава и
# перчатки командные. Оружие красит панель — у неё своя машинерия команд, — а
# руки приходят из воркера вместе с мешем, и без этого на синей стороне они
# оставались красными.

def test_blue_team_gets_the_blue_arms_texture():
    """Картинка синяя, а ключ красный: меши в сцене названы по первому скину."""
    rec = _run(_worker(team="blu"),
               team_map={"scout_hands": "scout_hands_blue"},
               textures={"c_scattergun": "gun.png", "scout_hands": "hands.png",
                         "scout_hands_blue": "hands_blue.png"})
    assert rec.data["multi_material"]["scout_hands"] == "hands_blue.png"


def test_red_team_is_left_alone():
    rec = _run(_worker(),
               team_map={"scout_hands": "scout_hands_blue"},
               textures={"c_scattergun": "gun.png", "scout_hands": "hands.png",
                         "scout_hands_blue": "hands_blue.png"})
    assert rec.data["multi_material"]["scout_hands"] == "hands.png"


def test_neutral_material_keeps_its_texture_on_blue():
    """У скаута и хэви руки нейтральные — подменять нечего."""
    rec = _run(_worker(team="blu"),
               team_map={"scout_hands": "scout_hands"})
    assert rec.data["multi_material"]["scout_hands"] == "hands.png"


def test_missing_blue_texture_does_not_wipe_the_red_one():
    """Синего файла может не оказаться — руки остаются красными, а не пустыми."""
    rec = _run(_worker(team="blu"),
               team_map={"scout_hands": "scout_hands_blue"})
    assert rec.data["multi_material"]["scout_hands"] == "hands.png"


# ── Своя модель вида ─────────────────────────────────────────────────────── #
#
# Часы шпиона от первого лица показываются моделью `v_watch_*.mdl`: там уже
# есть и руки, и часы, и свои последовательности. Их `c_*_watch` — модель для
# мира и рюкзака, у неё одна кость `static_prop`, и в руку её сажать нечем.
# Пока ветки не было, все три пары часов писали «вида от первого лица нет».

def _view_worker(key="c_pocket_watch", **kwargs):
    return _worker(key, tf2_class="spy", **kwargs)


def test_watch_is_built_from_its_own_viewmodel():
    asked = {}

    def decompile(key, *_a, **_k):
        asked.setdefault("keys", []).append(key)
        return Decompiled(directory=f"decomp/{key}", mdl_rel="x.mdl", cached=True)

    rec = _run(_view_worker(), decompile=decompile,
               animated={"bones": [], "parts": [{"kind": "arms",
                                                 "materials": ["c_pocket_watch"]}],
                         "clip": {}, "weaponMaterials": ["c_pocket_watch"]})
    assert rec.data["animated_ready"]["weaponMaterials"] == ["c_pocket_watch"]
    # Модель вида достаётся под своим ключом — она общая для всех действий.
    assert "__vm_c_pocket_watch" in asked["keys"]


def test_watch_scene_is_built_without_a_weapon_mesh():
    """Руки и часы там в одном меше — сажать в руку нечего."""
    seen = {}
    _run(_view_worker(), on_build=lambda kwargs: seen.update(kwargs),
         animated={"bones": [], "parts": [], "clip": {},
                   "weaponMaterials": []})
    assert not seen.get("weapon_ref_smd")
    assert seen.get("editable_mats") is not None


def test_ordinary_weapon_still_goes_the_usual_way():
    seen = {}
    _run(_worker(), on_build=lambda kwargs: seen.update(kwargs))
    assert seen.get("weapon_ref_smd")
