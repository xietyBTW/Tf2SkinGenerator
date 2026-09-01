"""
Переключатель вида от первого лица в панели превью.

Проверяются переходы, а не картинка: режим взаимоисключающий с остальными, и
именно на переходах раньше протекало состояние (см. preview_mode.py). Плюс
доступность: у шапок и тел персонажей вида от первого лица не существует, и
кнопка не должна предлагать несуществующее.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_pyside = sys.modules.get("PySide6")
if _pyside is not None and not hasattr(_pyside, "__path__"):
    pytest.skip("PySide6 подменён заглушкой соседних тестов",
                allow_module_level=True)

pytest.importorskip("PySide6.QtWidgets")

from src.domain.preview.mode import PreviewMode        # noqa: E402
from src.ui.preview_panel import PreviewPanel      # noqa: E402

WEAPON = ("c_scattergun", "scout_c_scattergun", "misc.vpk", "tex.vpk")
HAT = ("models/player/items/scout/hat.mdl", "hat", "misc.vpk", "tex.vpk")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    p = PreviewPanel()
    p._started = []
    p._start_fp_worker = lambda *a: p._started.append(("fp", a))
    p._start_3d_worker = lambda *a: p._started.append(("3d", a))
    p._rigs = []
    if p._3d_widget is not None:
        p._3d_widget.set_view_rig = lambda rig: p._rigs.append(rig)
    return p


def _select(panel, params):
    panel.set_3d_params(weapon_key=params[0], mode=params[1],
                        misc_vpk_path=params[2], textures_vpk_path=params[3])
    panel._update_3d_buttons_visibility()


def test_button_appears_only_for_weapons(panel):
    """У шапки вида от первого лица нет — предлагать его нельзя."""
    _select(panel, WEAPON)
    assert not panel.btn_fp.isHidden()
    _select(panel, HAT)
    assert panel.btn_fp.isHidden()


def test_button_is_hidden_until_something_is_selected(panel):
    assert panel.btn_fp.isHidden()


def test_switching_starts_the_viewmodel_worker(panel):
    _select(panel, WEAPON)
    panel._switch_to_fp()
    assert panel._pstate.mode is PreviewMode.FIRST_PERSON
    assert panel._started == [("fp", WEAPON)]


def test_switching_without_a_selection_does_nothing(panel):
    panel._switch_to_fp()
    assert not panel._pstate.is_first_person
    assert panel._started == []


def test_returning_to_3d_rebuilds_the_normal_model(panel):
    """В сцене стоит вьюмодель — обычную модель надо собрать заново."""
    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._started.clear()
    panel._switch_to_3d()
    assert not panel._pstate.is_first_person
    assert panel._started == [("3d", WEAPON)]


def test_returning_to_2d_leaves_the_mode(panel):
    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._switch_to_2d()
    assert not panel._pstate.is_first_person


def test_camera_rig_is_set_on_enter_and_cleared_on_exit(panel):
    """Оставленный риг развалил бы кадр обычного превью."""
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._switch_to_3d()
    assert panel._rigs and panel._rigs[-1] is None
    assert isinstance(panel._rigs[0], dict) and panel._rigs[0]["fov"]


def test_leaving_is_idempotent(panel):
    _select(panel, WEAPON)
    panel._leave_first_person()
    panel._leave_first_person()
    assert not panel._pstate.is_first_person


def test_selecting_a_hat_while_in_first_person_leaves_the_mode(panel):
    """Иначе на шапке остался бы риг вьюмодели и чужая сцена."""
    _select(panel, WEAPON)
    panel._switch_to_fp()
    _select(panel, HAT)
    assert not panel._pstate.is_first_person
    assert panel.btn_fp.isHidden()


def test_user_texture_is_reapplied_to_the_viewmodel(panel):
    """Материалы оружия в обеих сценах названы одинаково, значит и текстура одна.

    Без этого переход 3D → FP показывал сток вместо того, что нарисовал
    пользователь.
    """
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    loaded, reapplied = [], []
    panel._3d_widget.load_model_files = lambda *a, **k: loaded.append((a, k))
    panel._run_after_model_load = lambda fn, **_k: fn()
    panel._reapply_textures_to_3d = lambda **k: reapplied.append(k)

    panel._on_fp_ready("viewmodel.obj", "")

    assert loaded and loaded[0][1]["normalize"] is False, \
        "сцену нельзя вписывать в кадр — она стоит относительно глаза"
    assert reapplied, "пользовательская текстура обязана лечь на вьюмодель"


def test_only_weapon_meshes_stay_editable_in_first_person(panel):
    """Руки в сцене стоковые и чужие — красить их пользователь не просил."""
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    names = []
    panel._3d_widget.set_editable_mesh_names = names.append
    panel._on_fp_editable_materials(["c_scattergun"])
    assert names == [["c_scattergun"]]


# ── Кэш собранных сцен ────────────────────────────────────────────────────── #

@pytest.fixture
def scene_file(tmp_path):
    obj = tmp_path / "viewmodel.obj"
    obj.write_text("# scene\n", encoding="utf-8")
    return str(obj)


def _cache_scene(panel, scene_file):
    """Проходит полный цикл сборки, как это делают сигналы воркера."""
    panel._start_fp_worker(*WEAPON)
    panel._on_fp_editable_materials(["c_scattergun"])
    panel._on_fp_ready(scene_file, "")
    panel._on_fp_multi_material({"c_scattergun": "gun.png",
                                 "scout_hands": "hands.png"})


def test_second_entry_does_not_rebuild_the_scene(panel, scene_file):
    """Пересборка стоит около секунды — за неё платить дважды незачем."""
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_model_files = lambda *a, **k: None
    panel._3d_widget.apply_material_map = lambda *a: None
    panel._3d_widget.set_editable_mesh_names = lambda *a: None

    _select(panel, WEAPON)
    _cache_scene(panel, scene_file)
    panel._started.clear()

    panel._switch_to_3d()
    panel._started.clear()
    panel._switch_to_fp()

    assert panel._started == [], "сцена уже собрана — воркер не нужен"


def test_editable_filter_is_set_after_the_model_not_before(panel, scene_file):
    """Загрузка модели сбрасывает фильтр — выставленный заранее пропадает молча.

    Проверено в настоящем вьювере: при обратном порядке пользовательская
    текстура ложилась и на руки.
    """
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    order = []
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_model_files = (
        lambda *a, **k: order.append(("load", k.get("editable_mesh_names"))))
    panel._3d_widget.apply_material_map = lambda *a: None
    panel._3d_widget.set_editable_mesh_names = lambda n: order.append(("filter", n))

    _select(panel, WEAPON)
    _cache_scene(panel, scene_file)
    order.clear()
    panel._show_cached_scene()

    assert order and order[0][0] == "load", "фильтр не должен опережать модель"
    assert order[0][1] == ["c_scattergun"], \
        "список редактируемых мешей уходит вместе с загрузкой"


def test_cached_scene_keeps_its_textures_and_editable_meshes(panel, scene_file):
    """Иначе возврат показал бы вьюмодель без текстур и с красимыми руками."""
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    shown = {}
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_model_files = lambda *a, **k: shown.update(obj=a[0], kw=k)
    panel._3d_widget.apply_material_map = lambda m: shown.update(tex=m)
    panel._3d_widget.set_editable_mesh_names = lambda n: shown.update(edit=n)

    _select(panel, WEAPON)
    _cache_scene(panel, scene_file)
    shown.clear()

    assert panel._show_cached_scene() is True
    assert shown["obj"] == scene_file
    assert shown["kw"]["normalize"] is False
    assert shown["tex"] == {"c_scattergun": "gun.png", "scout_hands": "hands.png"}
    assert shown["kw"]["editable_mesh_names"] == ["c_scattergun"]


def test_scene_of_another_weapon_is_not_reused(panel, scene_file):
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_model_files = lambda *a, **k: None
    panel._3d_widget.apply_material_map = lambda *a: None
    panel._3d_widget.set_editable_mesh_names = lambda *a: None

    _select(panel, WEAPON)
    _cache_scene(panel, scene_file)
    _select(panel, ("c_bat", "scout_c_bat", "misc.vpk", "tex.vpk"))
    assert panel._show_cached_scene() is False


def test_scene_whose_file_vanished_is_forgotten(panel, scene_file):
    """Временные папки живут не вечно — на исчезнувший файл нельзя ссылаться."""
    _select(panel, WEAPON)
    panel.remember_scene(scene_file, {}, ["c_scattergun"])
    os.remove(scene_file)
    assert panel._show_cached_scene() is False
    assert panel._scene_cache == {}


def test_cache_does_not_grow_without_bound(panel, tmp_path):
    """Каждая сцена — временная папка; держать их все нельзя."""
    for i in range(panel._SCENE_CACHE_LIMIT + 3):
        obj = tmp_path / f"scene{i}.obj"
        obj.write_text("#", encoding="utf-8")
        _select(panel, (f"c_w{i}", f"scout_c_w{i}", "misc.vpk", "tex.vpk"))
        panel.remember_scene(str(obj), {}, [])
    assert len(panel._scene_cache) == panel._SCENE_CACHE_LIMIT


def test_returning_to_3d_reuses_the_model_already_on_disk(panel, scene_file):
    """Состояние панели вход в FP не трогает — обычную модель не надо собирать."""
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    loaded = []
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_model_files = lambda *a, **k: loaded.append(a)
    panel._3d_widget.set_editable_mesh_names = lambda *a: None

    _select(panel, WEAPON)
    panel._cur_obj = (WEAPON[1], scene_file, "tex.png")
    panel._switch_to_fp()
    panel._started.clear()
    loaded.clear()

    panel._switch_to_3d()
    assert panel._started == [], "модель уже на диске — воркер не нужен"
    assert loaded == [(scene_file, "tex.png")]


def test_missing_plain_model_falls_back_to_the_worker(panel):
    _select(panel, WEAPON)
    panel._cur_obj = (WEAPON[1], "сгинул.obj", "")
    panel._switch_to_fp()
    panel._started.clear()
    panel._switch_to_3d()
    assert panel._started == [("3d", WEAPON)]


def test_switching_animation_asks_only_for_the_tracks(panel, scene_file):
    """Меш, скелет и текстуры от выбора анимации не зависят.

    Полная пересборка распаковывала бы те же самые VTF заново: замер дал
    863 мс против 9 мс на одни дорожки.
    """
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_viewmodel_animated = lambda *a, **k: None
    panel._3d_widget.apply_material_map = lambda *a: None
    panel._3d_widget.set_editable_mesh_names = lambda *a: None
    clips = []
    panel._start_fp_clip_worker = lambda *a: clips.append(a)

    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._on_fp_animated_ready({"parts": [], "clip": {}})
    panel._started.clear()

    panel.fp_action_combo.addItem("Осмотр", "INSPECT_IDLE")
    panel.fp_action_combo.setCurrentIndex(panel.fp_action_combo.count() - 1)

    assert clips == [WEAPON], "смена анимации не должна пересобирать сцену"
    assert panel._started == []


def test_crossing_the_reload_boundary_rebuilds_the_scene(panel, scene_file):
    """В перезарядке у солдата ПОЯВЛЯЕТСЯ ракета из модели рук.

    Она часть геометрии, а не дорожек, так что подменой одних дорожек не
    обойтись — иначе ракета осталась бы висеть и в покое.
    """
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_viewmodel_animated = lambda *a, **k: None
    panel._3d_widget.apply_material_map = lambda *a: None
    panel._3d_widget.set_editable_mesh_names = lambda *a: None
    clips = []
    panel._start_fp_clip_worker = lambda *a: clips.append(a)

    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._on_fp_animated_ready({"parts": [], "clip": {}})
    panel._started.clear()

    panel.fp_action_combo.addItem("Перезарядка", "RELOAD")
    panel.fp_action_combo.setCurrentIndex(panel.fp_action_combo.count() - 1)

    assert clips == [], "через границу перезарядки одних дорожек мало"
    assert panel._started == [("fp", WEAPON)]


def test_switching_animation_without_a_scene_builds_the_whole_thing(panel):
    """Первый показ собирать надо целиком — накладывать клип не на что."""
    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._started.clear()
    clips = []
    panel._start_fp_clip_worker = lambda *a: clips.append(a)

    panel.fp_action_combo.addItem("Перезарядка", "RELOAD")
    panel.fp_action_combo.setCurrentIndex(panel.fp_action_combo.count() - 1)

    assert clips == []
    assert panel._started == [("fp", WEAPON)]


def test_first_person_is_hidden_for_a_replaced_model(panel):
    """Сцена собирается из ИГРОВОГО оружия — с подменённой моделью это ложь."""
    _select(panel, WEAPON)
    assert not panel.btn_fp.isHidden()
    panel._custom_vpk_mode = True
    panel._update_3d_buttons_visibility()
    assert panel.btn_fp.isHidden()


def test_load_buttons_are_hidden_in_first_person(panel):
    """Подменять модель в руках нечем — кнопки загрузки там не при чём."""
    _select(panel, WEAPON)
    panel._switch_to_fp()
    assert panel.btn_load_3d.isHidden()
    assert panel.btn_load_vpk.isHidden()


def test_replaced_model_keeps_the_button(panel):
    """Кастомную модель вид от первого лица показывает наравне с игровой.

    Сцена собирается тем же слиянием, что и мод: скелет из игровой модели,
    треугольники пользователя.
    """
    _select(panel, WEAPON)
    panel._custom_smd_path = "C:/models/my_gun.smd"
    panel._update_3d_buttons_visibility()
    assert not panel.btn_fp.isHidden()


def test_loaded_vpk_hides_the_button(panel):
    """В загруженном VPK лежит уже скомпилированная MDL.

    Что там за оружие и какому классу оно принадлежит — неизвестно, так что
    руки предлагать не по чему.
    """
    _select(panel, WEAPON)
    panel._custom_vpk_mode = True
    panel._update_3d_buttons_visibility()
    assert panel.btn_fp.isHidden()
    assert not panel._pstate.is_first_person


def test_custom_model_is_handed_to_the_viewmodel_worker(panel):
    """Иначе в руках оказался бы сток вместо пользовательской геометрии."""
    _select(panel, WEAPON)
    panel._custom_smd_path = "C:/models/my_gun.smd"
    panel._switch_to_fp()
    assert panel._started == [("fp", WEAPON)]


def test_replacing_the_model_does_not_reuse_the_stock_scene(panel):
    """Ключ кэша сцен учитывает подмену: оружие то же, а сцена другая."""
    _select(panel, WEAPON)
    stock = panel._scene_cache_key()
    panel._custom_smd_path = "C:/models/my_gun.smd"
    assert panel._scene_cache_key() != stock


def test_returning_from_first_person_brings_back_the_custom_model(panel, tmp_path):
    """Подменённую модель показывает не воркер, а конвертер SMD.

    `_cur_obj` о ней не знает, и возврат из вида от первого лица подсовывал
    стоковую геометрию вместо пользовательской.
    """
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    shown = []
    panel._3d_widget.load_model_files = lambda path, *a, **k: shown.append(path)
    panel._run_after_model_load = lambda fn, **k: None

    stock = tmp_path / "stock.obj"
    custom = tmp_path / "custom.obj"
    stock.write_text("# сток", encoding="utf-8")
    custom.write_text("# кастом", encoding="utf-8")

    _select(panel, WEAPON)
    panel._cur_obj = (WEAPON[1], str(stock), "")
    panel._custom_smd_path = "C:/models/my_gun.smd"
    panel._custom_obj_path = str(custom)

    panel._switch_to_fp()
    shown.clear()
    panel._switch_to_3d()
    assert shown == [str(custom)]


def test_without_a_custom_model_the_stock_one_comes_back(panel, tmp_path):
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    shown = []
    panel._3d_widget.load_model_files = lambda path, *a, **k: shown.append(path)
    panel._run_after_model_load = lambda fn, **k: None

    stock = tmp_path / "stock.obj"
    stock.write_text("# сток", encoding="utf-8")
    _select(panel, WEAPON)
    panel._cur_obj = (WEAPON[1], str(stock), "")

    panel._switch_to_fp()
    shown.clear()
    panel._switch_to_3d()
    assert shown == [str(stock)]


def test_team_switch_rebuilds_the_first_person_scene(panel):
    """Руки у семи классов командные, и приходят они из воркера.

    Панель красит только оружие, так что подменой одних её текстур синие
    рукава на экране не появятся.
    """
    from src.shared.constants import Team
    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._started.clear()
    panel._switch_team(Team.BLU)
    assert panel._started == [("fp", WEAPON)]


def test_team_is_part_of_the_scene_key(panel):
    from src.shared.constants import Team
    _select(panel, WEAPON)
    red = panel._scene_cache_key()
    panel._active_team = Team.BLU
    assert panel._scene_cache_key() != red


# ── Выбор анимации ────────────────────────────────────────────────────────── #
#
# Список приносит воркер, но запускается он не всегда: повторный вход в режим,
# смена команды и возврат к уже показанной анимации берут сцену из кэша. Раньше
# список показывался только по сигналу воркера — и на кэше молча исчезал.

def _prepare_fp(panel):
    _select(panel, WEAPON)
    panel._switch_to_fp()
    panel._on_fp_actions_available(["IDLE", "DRAW", "RELOAD"])


def test_actions_appear_when_the_worker_reports_them(panel):
    _prepare_fp(panel)
    combo = panel.fp_action_combo
    assert not combo.isHidden()
    assert [combo.itemData(i) for i in range(combo.count())] == \
        ["IDLE", "DRAW", "RELOAD"]


def test_actions_survive_a_scene_taken_from_the_cache(panel, scene_file):
    """Второй вход собирать нечего — но выбирать анимацию по-прежнему есть из чего."""
    if panel._3d_widget is None:
        pytest.skip("3D-виджет недоступен")
    panel._run_after_model_load = lambda fn, **_k: None
    panel._3d_widget.load_model_files = lambda *a, **k: None
    panel._3d_widget.apply_material_map = lambda *a: None
    panel._3d_widget.set_editable_mesh_names = lambda *a: None

    _prepare_fp(panel)
    _cache_scene(panel, scene_file)
    panel._switch_to_3d()
    assert panel.fp_action_combo.isHidden(), "вне режима выбора анимации нет"

    panel._started.clear()
    panel._switch_to_fp()
    assert panel._started == [], "сцена уже собрана — воркер не нужен"
    assert not panel.fp_action_combo.isHidden(), \
        "список обязан вернуться вместе с режимом"


def test_actions_of_another_weapon_are_not_offered(panel):
    """Набор действий у каждого оружия свой — чужой был бы обещанием пустого."""
    _prepare_fp(panel)
    _select(panel, ("c_bat", "scout_c_bat", "misc.vpk", "tex.vpk"))
    panel._switch_to_fp()
    assert panel.fp_action_combo.isHidden()


def test_unavailable_action_falls_back_to_the_first_one(panel):
    """У биты нет перезарядки: подписать её и показать покой — обман."""
    _prepare_fp(panel)
    panel._fp_action = "RELOAD"
    panel._on_fp_actions_available(["IDLE", "DRAW"])
    assert panel._fp_action == "IDLE"
    assert panel.fp_action_combo.currentData() == "IDLE"


def test_failed_scene_takes_the_list_with_it(panel):
    """Сцены нет — выбирать анимацию не для чего."""
    _prepare_fp(panel)
    panel._on_fp_failed("нет вида от первого лица")
    assert panel.fp_action_combo.isHidden()


# ── «Сделать командным» ───────────────────────────────────────────────────── #

def test_make_team_is_not_offered_for_material_only_items(panel):
    """Синтез команды живёт в $texturegroup модели, а модели в моде нет.

    Часы шпиона рисует РОДНАЯ вьюмодель: сборка кладёт только материалы и
    вдобавок выкидывает BLU-строку (NO_BLU_WEAPON_KEYS). Кнопка обещала бы то,
    чего сборка не сделает.
    """
    panel._weapon_mode = "spy_c_pocket_watch"
    panel._weapon_key = "c_pocket_watch"
    assert panel._is_force_team_eligible() is False

    panel._weapon_mode = "scout_c_scattergun"
    panel._weapon_key = "c_scattergun"
    assert panel._is_force_team_eligible() is True
