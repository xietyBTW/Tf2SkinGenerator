"""Тесты проверок эффекта перед сборкой."""

import pytest

from src.services.particle_lint import (
    apply_fixes, attr_warning, check_game_conflicts, check_systems,
)


def _system(**over):
    base = {
        "name": "fx",
        "attrs": {"max_particles": {"t": "integer", "v": 100},
                  "radius": {"t": "float", "v": 5.0},
                  "material": {"t": "string", "v": "effects/test.vmt"}},
        "renderers": [{"functionName": "render_animated_sprites", "attrs": {}}],
        "emitters": [{"functionName": "emit_continuously", "attrs": {}}],
        "initializers": [],
        # Без оператора смерти частицы бессмертны — рабочий эффект так не
        # выглядит, и правило immortal справедливо ругается (см. тесты ниже)
        "operators": [{"functionName": "Lifespan Decay", "attrs": {}}],
        "forces": [], "constraints": [],
        "children": [],
    }
    base.update(over)
    return base


def test_clean_effect_has_no_findings():
    assert check_systems({"fx": _system()}) == []


def test_hidden_from_camera_is_reported_and_fixable():
    """Тот самый случай: эффект перенесли в чужой контекст, и он скрыт."""
    s = _system()
    s["attrs"]["control point to disable rendering if it is the camera"] = {
        "t": "integer", "v": 0}
    found = check_systems({"fx": s})
    assert [f.rule for f in found] == ["cp_camera"]
    assert found[0].fixable and found[0].fix_value == -1


def test_invisible_particles_rules():
    no_particles = _system()
    no_particles["attrs"]["max_particles"] = {"t": "integer", "v": 0}
    zero_radius = _system()
    zero_radius["attrs"]["radius"] = {"t": "float", "v": 0.0}
    zero_alpha = _system()
    zero_alpha["attrs"]["color"] = {"t": "color", "v": [255, 0, 0, 0]}

    assert "no_particles" in [f.rule for f in check_systems({"fx": no_particles})]
    assert "zero_radius" in [f.rule for f in check_systems({"fx": zero_radius})]
    alpha_found = check_systems({"fx": zero_alpha})
    assert "zero_alpha" in [f.rule for f in alpha_found]
    assert next(f for f in alpha_found if f.rule == "zero_alpha").fix_value \
        == [255, 0, 0, 255]

    # Нулевой радиус при Radius Random — норма, модуль задаёт размер сам
    ok = _system(initializers=[{"functionName": "Radius Random", "attrs": {}}])
    ok["attrs"]["radius"] = {"t": "float", "v": 0.0}
    assert "zero_radius" not in [f.rule for f in check_systems({"fx": ok})]


def test_container_systems_are_not_noise():
    """Родитель без рендерера/эмиттера, но с детьми — норма Valve (14% стока)."""
    parent = _system(renderers=[], emitters=[],
                     children=[{"delay": 0.0, "childName": "kid"}])
    systems = {"fx": parent, "kid": _system()}
    assert check_systems(systems) == []

    # А вот система, которая спавнит частицы без рендерера — проблема
    orphan = _system(renderers=[])
    assert "no_renderer" in [f.rule for f in check_systems({"fx": orphan})]
    # ...и полностью пустая система тоже
    dead = _system(renderers=[], emitters=[])
    assert "no_emitter" in [f.rule for f in check_systems({"fx": dead})]


def test_missing_child_and_material():
    s = _system(children=[{"delay": 0.0, "childName": "ghost"}])
    found = check_systems({"fx": s})
    assert [f.rule for f in found] == ["missing_child"]
    assert found[0].params["child"] == "ghost"

    # Материалы проверяются, только если резолв вообще выполнялся
    assert check_systems({"fx": _system()}, materials={}) == []
    found = check_systems({"fx": _system()}, materials={"other.vmt": {}})
    assert [f.rule for f in found] == ["material_missing"]


def test_baseline_filters_untouched_systems():
    """Особенности стоковых систем не должны попадать в отчёт."""
    stock = _system()
    stock["attrs"]["control point to disable rendering if it is the camera"] = {
        "t": "integer", "v": 0}
    systems = {"fx": stock}
    assert check_systems(systems, baseline=systems) == []

    # Та же проблема, но принесённая правкой — сообщаем
    edited = {"fx": stock, "my_copy": dict(stock, name="my_copy")}
    found = check_systems(edited, baseline=systems)
    assert [f.system for f in found] == ["my_copy"]


def test_root_scope_limits_check():
    """С указанием корня проверяются только он и его дети."""
    systems = {
        "root": _system(children=[{"delay": 0.0, "childName": "kid"}]),
        "kid": _system(renderers=[]),
        "unrelated": _system(renderers=[]),
    }
    found = check_systems(systems, root_name="root")
    assert {f.system for f in found} == {"kid"}


def test_attr_warning():
    cp = "control point to disable rendering if it is the camera"
    assert attr_warning(cp, 0) == "particles_lint_cp_camera"
    assert attr_warning(cp, -1) is None
    assert attr_warning("max_particles", 0) == "particles_lint_no_particles"
    assert attr_warning("max_particles", 50) is None
    assert attr_warning("radius", 0.0) == "particles_lint_zero_radius"
    assert attr_warning("color", [1, 2, 3, 0]) == "particles_lint_zero_alpha"
    assert attr_warning("color", [1, 2, 3, 255]) is None
    assert attr_warning("view model effect", True) == "particles_lint_viewmodel"
    assert attr_warning("radius", "не число") is None


def test_custom_override_detection(tmp_path):
    """Рассыпной PCF в tf/custom перекрывает мод — самая коварная причина
    «мод не работает»."""
    custom = tmp_path / "tf" / "custom" / "somemod" / "particles"
    custom.mkdir(parents=True)
    (custom / "crit.pcf").write_bytes(b"x")
    found = check_game_conflicts(str(tmp_path), "particles/crit.pcf")
    assert [f.rule for f in found] == ["custom_override"]
    assert "somemod" in found[0].params["path"]

    # другой файл не мешает
    assert check_game_conflicts(str(tmp_path), "particles/other.pcf") == []
    assert check_game_conflicts("", "particles/crit.pcf") == []


def test_apply_fixes_writes_to_tree():
    srctools_dmx = pytest.importorskip("srctools.dmx")
    from tests.test_particle_editor_service import _make_pcf_bytes
    from src.services.particle_editor_service import ParticleEditorService

    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    # Без эмиттера max_particles не при чём — система и так не спавнит
    svc.add_module("fx", "emitters", "emit_continuously")
    d = svc._find_definition("fx")
    d["control point to disable rendering if it is the camera"] = \
        srctools_dmx.Attribute.int(
            "control point to disable rendering if it is the camera", 0)
    d["max_particles"] = srctools_dmx.Attribute.int("max_particles", 0)

    found = check_systems(svc.systems_json())
    assert apply_fixes(svc, [f for f in found if f.fixable]) == 2
    attrs = svc.systems_json()["fx"]["attrs"]
    assert attrs["control point to disable rendering if it is the camera"]["v"] == -1
    assert attrs["max_particles"]["v"] == 100
    # Починяемые находки ушли (осталось лишь то, что руками: у фикстуры
    # нет рендерера)
    assert not [f for f in check_systems(svc.systems_json()) if f.fixable]


def _sheet(frames: int, seq: str = "0") -> dict:
    """Материал со спрайт-листом на заданное число кадров."""
    return {"sheet": {"sequences": {seq: {"clamp": True, "duration": 1.0,
                                          "frames": [[0, 0, 1, 1]] * frames}}}}


def test_immortal_particles_reported():
    """Непрерывный поток без оператора смерти: частицы копятся до потолка,
    и эффект замирает навсегда — в превью это выглядит как «сначала шло,
    потом перестало»."""
    s = _system(operators=[])
    assert "immortal" in [f.rule for f in check_systems({"fx": s})]

    # Смерть может приходить и от Alpha Fade and Decay — тогда всё в порядке
    ok = _system(operators=[{"functionName": "Alpha Fade and Decay", "attrs": {}}])
    assert "immortal" not in [f.rule for f in check_systems({"fx": ok})]

    # Разовый залп копиться не может — правило молчит
    burst = _system(operators=[],
                    emitters=[{"functionName": "emit_instantaneously",
                               "attrs": {}}])
    assert "immortal" not in [f.rule for f in check_systems({"fx": burst})]


def test_frozen_animation_reported_and_fixable():
    """Гифка из 30 кадров при «1 кадр в секунду» и жизни в секунду: в игре
    частица так и стоит первым кадром. Чинится растягиванием листа на жизнь."""
    s = _system(initializers=[{"functionName": "Lifetime Random",
                               "attrs": {"lifetime_max": {"t": "float", "v": 1.0}}}],
                renderers=[{"functionName": "render_animated_sprites",
                            "attrs": {"animation rate": {"t": "float", "v": 1.0},
                                      "use animation rate as fps":
                                          {"t": "bool", "v": True}}}])
    found = check_systems({"fx": s}, materials={"effects/test.vmt": _sheet(30)})
    frozen = [f for f in found if f.rule == "frozen_animation"]
    assert len(frozen) == 1, [f.rule for f in found]
    assert frozen[0].params["frames"] == 30
    assert frozen[0].fix == ("renderers", 0, "animation_fit_lifetime", "bool")
    assert frozen[0].fix_value is True


def test_animation_not_reported_when_it_plays():
    """Способы проиграть лист, которыми пользуется сама игра."""
    mats = {"effects/test.vmt": _sheet(30)}
    life = [{"functionName": "Lifetime Random",
             "attrs": {"lifetime_max": {"t": "float", "v": 1.0}}}]

    fit = _system(initializers=life, renderers=[
        {"functionName": "render_animated_sprites",
         "attrs": {"animation_fit_lifetime": {"t": "bool", "v": True},
                   "animation rate": {"t": "float", "v": 0.1}}}])
    fps = _system(initializers=life, renderers=[
        {"functionName": "render_animated_sprites",
         "attrs": {"use animation rate as fps": {"t": "bool", "v": True},
                   "animation rate": {"t": "float", "v": 30.0}}}])
    cycles = _system(initializers=life, renderers=[
        {"functionName": "render_animated_sprites",
         "attrs": {"animation rate": {"t": "float", "v": 1.0}}}])
    for case in (fit, fps, cycles):
        assert "frozen_animation" not in [
            f.rule for f in check_systems({"fx": case}, materials=mats)]

    # Одно-кадровый лист анимировать нечем — молчим
    single = _system(initializers=life, renderers=[
        {"functionName": "render_animated_sprites",
         "attrs": {"animation rate": {"t": "float", "v": 0.1}}}])
    assert "frozen_animation" not in [
        f.rule for f in check_systems({"fx": single},
                                      materials={"effects/test.vmt": _sheet(1)})]


def test_slow_sheet_scroll_is_not_reported():
    """Приём Valve: длинный лист еле ползёт, зато Sequence Random раздаёт
    частицам разные стартовые кадры. Так сделаны кровь и дым — это не
    ошибка, и ругаться на неё значит утопить отчёт в шуме."""
    mats = {"effects/test.vmt": _sheet(15)}
    life = [{"functionName": "Lifetime Random",
             "attrs": {"lifetime_max": {"t": "float", "v": 0.5}}}]
    slow = [{"functionName": "render_animated_sprites",
             "attrs": {"animation rate": {"t": "float", "v": 0.1}}}]

    with_random = _system(
        initializers=life + [{"functionName": "Sequence Random", "attrs": {}}],
        renderers=slow)
    assert "frozen_animation" not in [
        f.rule for f in check_systems({"fx": with_random}, materials=mats)]

    # Без раздачи кадров та же настройка — статичная картинка
    without = _system(initializers=life, renderers=slow)
    assert "frozen_animation" in [
        f.rule for f in check_systems({"fx": without}, materials=mats)]


def test_frozen_animation_uses_system_sequence_number():
    """Кадры считаются по той последовательности, которую система играет."""
    mats = {"effects/test.vmt": {"sheet": {"sequences": {
        "0": {"frames": [[0, 0, 1, 1]]},
        "3": {"frames": [[0, 0, 1, 1]] * 16}}}}}
    s = _system(initializers=[{"functionName": "Lifetime Random",
                               "attrs": {"lifetime_max": {"t": "float", "v": 1.0}}}],
                renderers=[{"functionName": "render_animated_sprites",
                            "attrs": {"animation rate": {"t": "float", "v": 0.1}}}])
    s["attrs"]["sequence_number"] = {"t": "integer", "v": 3}
    assert "frozen_animation" in [
        f.rule for f in check_systems({"fx": s}, materials=mats)]

    s["attrs"]["sequence_number"] = {"t": "integer", "v": 0}    # один кадр
    assert "frozen_animation" not in [
        f.rule for f in check_systems({"fx": s}, materials=mats)]
