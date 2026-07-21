"""Тесты particle_editor_service: JSON-конвертация, правка, roundtrip, sheet."""

import io
import struct

import pytest

srctools_dmx = pytest.importorskip("srctools.dmx")
from srctools.dmx import Attribute, Element  # noqa: E402

from src.services.particle_editor_service import (  # noqa: E402
    ParticleEditorService,
    parse_vtf_sheet,
)


def _make_pcf_bytes() -> bytes:
    """Минимальный PCF: система fx с инициализатором и ребёнком."""
    root = Element("root", "DmElement")

    child = Element("fx_child", "DmeParticleSystemDefinition")
    child["max_particles"] = Attribute.int("max_particles", 20)
    # Тот же материал, но с другим регистром/слэшами — для проверки нормализации
    child["material"] = Attribute.string("material", "Effects/TEST.vmt")

    init = Element("Color Random", "DmeParticleOperator")
    init["functionName"] = Attribute.string("functionName", "Color Random")
    init["color1"] = Attribute.color("color1", 0, 255, 30, 255)

    sys_el = Element("fx", "DmeParticleSystemDefinition")
    sys_el["max_particles"] = Attribute.int("max_particles", 100)
    sys_el["radius"] = Attribute.float("radius", 5.0)
    sys_el["material"] = Attribute.string("material", "effects\\test.vmt")
    sys_el["initializers"] = Attribute.array("initializers", srctools_dmx.ValueType.ELEMENT)
    sys_el["initializers"].append(init)

    ch_ref = Element("child01", "DmeParticleChild")
    ch_ref["delay"] = Attribute.float("delay", 0.25)
    ch_ref["child"] = Attribute("child", srctools_dmx.ValueType.ELEMENT, child)
    sys_el["children"] = Attribute.array("children", srctools_dmx.ValueType.ELEMENT)
    sys_el["children"].append(ch_ref)

    defs = Attribute.array("particleSystemDefinitions", srctools_dmx.ValueType.ELEMENT)
    defs.append(sys_el)
    root["particleSystemDefinitions"] = defs

    out = io.BytesIO()
    root.export_binary(out, version=2, fmt_name="pcf", fmt_ver=1, unicode="format")
    return out.getvalue()


def test_systems_json_structure():
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    assert svc.system_names() == ["fx"]
    systems = svc.systems_json()
    # Ребёнок, на которого ссылаются только children, добавлен в результат
    assert set(systems) == {"fx", "fx_child"}

    fx = systems["fx"]
    assert fx["attrs"]["max_particles"] == {"t": "integer", "v": 100}
    assert fx["attrs"]["radius"]["v"] == 5.0
    assert fx["children"] == [{"delay": 0.25, "childName": "fx_child"}]
    assert fx["initializers"][0]["functionName"] == "Color Random"
    assert fx["initializers"][0]["attrs"]["color1"] == {
        "t": "color", "v": [0, 255, 30, 255]}

    assert set(svc.material_names()) == {"effects\\test.vmt", "Effects/TEST.vmt"}


def test_set_attr_and_save_roundtrip(tmp_path):
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    assert svc.set_attr("fx", "initializers", 0, "color1", [255, 0, 255, 128])
    assert svc.set_attr("fx", None, 0, "radius", 12.5)
    # Несуществующие цели — False, не исключение
    assert not svc.set_attr("nope", None, 0, "radius", 1)
    assert not svc.set_attr("fx", "initializers", 5, "color1", [1, 2, 3, 4])
    assert not svc.set_attr("fx", "initializers", 0, "missing_attr", 1)

    dest = tmp_path / "out.pcf"
    svc.save(str(dest))

    svc2 = ParticleEditorService()
    svc2.load_file(str(dest))
    systems = svc2.systems_json()
    assert systems["fx"]["initializers"][0]["attrs"]["color1"]["v"] == [255, 0, 255, 128]
    assert systems["fx"]["attrs"]["radius"]["v"] == 12.5


def test_set_system_texture_overwrites_original(tmp_path):
    """Своя картинка ПЕРЕЗАПИСЫВАЕТ оригинальный VTF-путь (для казуала):
    имя материала в PCF не меняется, custom_-путей не появляется."""
    pytest.importorskip("PIL")
    from pathlib import Path as _P
    if not _P("tools/VTF/VTFLib.dll").exists():
        pytest.skip("VTFLib.dll недоступна")
    from PIL import Image

    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    img = tmp_path / "tex.png"
    Image.new("RGBA", (100, 60), (255, 0, 0, 255)).save(img)

    res = svc.set_system_texture("fx", str(img), tf2_root_dir="")
    assert res is not None
    mat, info = res
    assert (info["width"], info["height"]) == (64, 32)   # степени двойки
    assert info["dataUrl"].startswith("data:image/png;base64,")

    # ИМЯ МАТЕРИАЛА НЕ ИЗМЕНИЛОСЬ и никаких custom_-путей
    assert mat == "effects\\test.vmt"
    assert svc.systems_json()["fx"]["attrs"]["material"]["v"] == "effects\\test.vmt"
    assert set(svc.custom_files) == {"materials/effects/test.vtf",
                                 "materials/effects/test.vmt"}
    assert not any("custom_" in p for p in svc.custom_files)
    assert svc.custom_files["materials/effects/test.vtf"][:4] == b"VTF\x00"

    # превью видит кастом; fx_child делит материал (иной регистр) → тоже
    assert svc.materials_json("").get("effects\\test.vmt") is not None
    assert svc.materials_json("").get("Effects/TEST.vmt") is not None
    assert svc.is_custom_material("effects\\test.vmt")

    # повторная замена — тот же путь, один файл
    img2 = tmp_path / "tex2.png"
    Image.new("RGBA", (64, 64), (0, 255, 0, 255)).save(img2)
    assert svc.set_system_texture("fx", str(img2), tf2_root_dir="") is not None
    assert set(svc.custom_files) == {"materials/effects/test.vtf",
                                 "materials/effects/test.vmt"}

    # сброс — оверрайд убран
    assert svc.reset_material_texture("effects\\test.vmt") == "effects\\test.vmt"
    assert svc.custom_files == {}
    assert not svc.is_custom_material("effects\\test.vmt")
    assert svc.reset_material_texture("effects\\test.vmt") is None

    # «сироты»: материал больше не используется → файл не в экспорте
    svc2 = ParticleEditorService()
    svc2.load_bytes(_make_pcf_bytes())
    svc2.set_material_texture("effects\\test.vmt", str(img), "")
    assert len(svc2._active_custom_files()) == 2  # VTF + сгенерированный VMT
    svc2.remove_system("fx")
    assert svc2._active_custom_files() == {}

    # общий tex_rel: reset одного не удаляет файл, нужный второму
    svc3 = ParticleEditorService()
    svc3.load_bytes(_make_pcf_bytes())
    svc3._overwritten = {
        "effects/a.vmt": {"tex_rel": "effects/shared", "material": "effects/a.vmt"},
        "effects/b.vmt": {"tex_rel": "effects/shared", "material": "effects/b.vmt"},
    }
    svc3._custom_material_info = {"effects/a.vmt": {}, "effects/b.vmt": {}}
    svc3.custom_files = {"materials/effects/shared.vtf": b"VTF\x00x"}
    svc3.reset_material_texture("effects/a.vmt")
    assert "materials/effects/shared.vtf" in svc3.custom_files   # ещё нужен b
    svc3.reset_material_texture("effects/b.vmt")
    assert svc3.custom_files == {}


def test_set_material_to_game():
    """Переназначение материала на игровой: имя строки меняется, новых
    custom-файлов не создаётся (для казуала)."""
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    # fx и fx_child делят effects/test → оба переводятся на игровой материал
    assert svc.set_material_to_game("effects\\test.vmt", "effects\\yellowflare.vmt")
    sysj = svc.systems_json()
    assert sysj["fx"]["attrs"]["material"]["v"] == "effects\\yellowflare.vmt"
    assert sysj["fx_child"]["attrs"]["material"]["v"] == "effects\\yellowflare.vmt"
    # никаких кастомных файлов
    assert svc.custom_files == {}
    # несуществующий исходный материал → False
    assert not svc.set_material_to_game("effects\\nope.vmt", "effects\\x.vmt")


def test_pcf_compression_strips_defaults(tmp_path):
    """save() вырезает default-атрибуты (для влезания в слот VPK казуала),
    рабочее дерево не мутируется, эффект остаётся валидным."""
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    # добавим оператору дефолтный атрибут «operator start fadein» = 0.0
    assert svc.add_module("fx", "operators", "Movement Basic")
    d = svc._find_definition("fx")
    op = list(d["operators"].iter_elem())[0]
    from srctools.dmx import Attribute as _A
    op["operator start fadein"] = _A.float("operator start fadein", 0.0)
    op["operator end fadeout"] = _A.float("operator end fadeout", 2.5)  # не дефолт

    dest = tmp_path / "compressed.pcf"
    svc.save(str(dest))
    data = dest.read_bytes()

    # рабочее дерево НЕ тронуто — дефолтный атрибут ещё на месте
    op_live = list(svc._find_definition("fx")["operators"].iter_elem())[0]
    assert "operator start fadein" in op_live

    # в файле: дефолтный вырезан, недефолтный сохранён
    svc2 = ParticleEditorService()
    svc2.load_bytes(data)
    op2 = list(svc2._find_definition("fx")["operators"].iter_elem())[0]
    assert "operator start fadein" not in op2
    assert "operator end fadeout" in op2
    assert abs(op2["operator end fadeout"].val_float - 2.5) < 1e-6

    # casual_size_overflow: сжатый < загруженного (в фикстуре дефолтов нет,
    # но метод не должен падать)
    assert isinstance(svc.casual_size_overflow(), int)


def test_structural_editing():
    """add/remove module, duplicate/remove system, add/remove child."""
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    # добавление модуля: шаблона в файле нет → элемент с functionName
    assert svc.add_module("fx", "operators", "Rotation Spin Roll")
    ops = svc.systems_json()["fx"]["operators"]
    assert [o["functionName"] for o in ops] == ["Rotation Spin Roll"]

    # добавление по шаблону из текущего файла: Color Random есть в fx
    assert svc.add_module("fx_child", "initializers", "Color Random")
    child_inits = svc.systems_json()["fx_child"]["initializers"]
    assert child_inits[0]["functionName"] == "Color Random"
    # атрибуты скопированы из шаблона
    assert child_inits[0]["attrs"]["color1"]["v"] == [0, 255, 30, 255]
    # копия отвязана: правка копии не трогает оригинал
    assert svc.set_attr("fx_child", "initializers", 0, "color1", [1, 2, 3, 4])
    assert svc.systems_json()["fx"]["initializers"][0]["attrs"]["color1"]["v"] \
        == [0, 255, 30, 255]

    # удаление модуля (последнего в группе → пустая типизированная группа)
    assert svc.remove_module("fx", "operators", 0)
    assert svc.systems_json()["fx"]["operators"] == []
    assert not svc.remove_module("fx", "operators", 0)

    # дублирование системы
    assert svc.duplicate_system("fx", "fx_stars")
    assert not svc.duplicate_system("fx", "fx_stars")   # имя занято
    sysj = svc.systems_json()
    assert "fx_stars" in sysj
    assert sysj["fx_stars"]["attrs"]["max_particles"]["v"] == 100
    # правка копии не трогает оригинал
    assert svc.set_attr("fx_stars", "initializers", 0, "color1", [9, 9, 9, 9])
    assert svc.systems_json()["fx"]["initializers"][0]["attrs"]["color1"]["v"] \
        == [0, 255, 30, 255]

    # дети: подцепить дубль ребёнком к fx, потом отцепить
    assert svc.add_child("fx", "fx_stars", delay=0.5)
    ch = svc.systems_json()["fx"]["children"]
    assert {"delay": 0.5, "childName": "fx_stars"} in ch
    # цикл запрещён: fx достижим из fx_stars? нет, но fx_stars уже ребёнок fx
    # → обратная связь создала бы цикл
    assert not svc.add_child("fx_stars", "fx")
    assert svc.remove_child("fx", len(ch) - 1)
    assert not any(c["childName"] == "fx_stars"
                   for c in svc.systems_json()["fx"]["children"])

    # копия сохраняет регистр имён атрибутов в файле (functionName и т.п.)
    import io as _io
    buf = _io.BytesIO()
    svc.root.export_binary(buf, version=2, fmt_name="pcf", fmt_ver=1,
                           unicode="silent")
    assert b"functionName" in buf.getvalue()

    # удаление системы + roundtrip всего через сохранение
    assert svc.remove_system("fx_stars")
    assert "fx_stars" not in svc.system_names()
    import io as _io
    buf = _io.BytesIO()
    svc.root.export_binary(buf, version=2, fmt_name="pcf", fmt_ver=1,
                           unicode="silent")
    svc2 = ParticleEditorService()
    svc2.load_bytes(buf.getvalue())
    assert svc2.systems_json()["fx_child"]["initializers"][0]["attrs"]["color1"]["v"] \
        == [1, 2, 3, 4]


def test_add_layer():
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    layer = svc.add_layer("fx")
    assert layer == "fx_layer"
    sysj = svc.systems_json()
    assert layer in sysj
    assert {"delay": 0.0, "childName": layer} in sysj["fx"]["children"]
    lj = sysj[layer]
    assert lj["emitters"][0]["functionName"] == "emit_instantaneously"
    assert lj["emitters"][0]["attrs"]["num_to_emit"]["v"] == 50
    assert [o["functionName"] for o in lj["operators"]] == [
        "Lifespan Decay", "Movement Basic", "Alpha Fade Out Simple",
        "Rotation Spin Roll"]
    # второй слой получает уникальное имя
    assert svc.add_layer("fx") == "fx_layer2"

    # удаление системы отцепляет её от родителя и освобождает имя
    assert svc.remove_system("fx_layer2")
    assert not any(c["childName"] == "fx_layer2"
                   for c in svc.systems_json()["fx"]["children"])
    assert svc.add_layer("fx") == "fx_layer2"   # имя переиспользуется
    # functionName сохраняет регистр в файле
    import io as _io
    buf = _io.BytesIO()
    svc.root.export_binary(buf, version=2, fmt_name="pcf", fmt_ver=1,
                           unicode="silent")
    assert b"functionName" in buf.getvalue()
    svc2 = ParticleEditorService()
    svc2.load_bytes(buf.getvalue())
    assert "fx_layer2" in svc2.systems_json()


def test_use_texture_colors():
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    removed = svc.use_texture_colors("fx")
    assert removed == 1   # Color Random из фикстуры
    sysj = svc.systems_json()
    assert sysj["fx"]["initializers"] == []
    # повторный вызов — модулей больше нет
    assert svc.use_texture_colors("fx") == 0

    # roundtrip: изменения переживают сохранение
    import io as _io
    buf = _io.BytesIO()
    svc.root.export_binary(buf, version=2, fmt_name="pcf", fmt_ver=1,
                           unicode="silent")
    svc2 = ParticleEditorService()
    svc2.load_bytes(buf.getvalue())
    assert svc2.systems_json()["fx"]["initializers"] == []


def test_paste_params():
    """Копи-паста параметров: merge атрибутов системы и модулей по functionName."""
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    payload = {
        "attrs": {"radius": {"t": "float", "v": 42.0},          # есть в fx
                  "new_scale": {"t": "float", "v": 1.5}},       # нет в fx
        "modules": {
            "initializers": {
                # Color Random есть в fx → merge: color1 перезаписан, color2 добавлен
                "Color Random": {"color1": {"t": "color", "v": [1, 2, 3, 4]},
                                 "color2": {"t": "color", "v": [9, 9, 9, 9]}},
            },
            "operators": {
                # операторов в fx нет вовсе → создаются и группа, и модуль
                "Movement Basic": {"gravity": {"t": "vec3", "v": [0, 0, -400]}},
            },
        },
    }
    assert svc.paste_params("fx", payload)
    fx = svc.systems_json()["fx"]
    assert fx["attrs"]["radius"]["v"] == 42.0
    assert fx["attrs"]["new_scale"]["v"] == 1.5
    init = fx["initializers"][0]
    assert init["functionName"] == "Color Random"
    assert init["attrs"]["color1"]["v"] == [1, 2, 3, 4]
    assert init["attrs"]["color2"]["v"] == [9, 9, 9, 9]
    op = fx["operators"][0]
    assert op["functionName"] == "Movement Basic"
    assert op["attrs"]["gravity"]["v"] == [0.0, 0.0, -400.0]

    # несуществующая система / пустой payload → False
    assert not svc.paste_params("nope", payload)
    assert not svc.paste_params("fx", {"attrs": {}, "modules": {}})

    # roundtrip: вставленное переживает сохранение
    buf = io.BytesIO()
    svc.root.export_binary(buf, version=2, fmt_name="pcf", fmt_ver=1,
                           unicode="silent")
    svc2 = ParticleEditorService()
    svc2.load_bytes(buf.getvalue())
    assert svc2.systems_json()["fx"]["operators"][0]["attrs"]["gravity"]["v"] \
        == [0.0, 0.0, -400.0]


def test_paste_params_modes():
    """Режимы вставки: keep не трогает существующее, replace сносит всё."""
    payload = {
        "attrs": {"radius": {"t": "float", "v": 42.0},
                  "new_scale": {"t": "float", "v": 1.5}},
        "modules": {
            "initializers": {
                "Color Random": {"color1": {"t": "color", "v": [1, 2, 3, 4]},
                                 "color2": {"t": "color", "v": [9, 9, 9, 9]}},
            },
        },
    }

    # keep: существующие radius и color1 не тронуты, недостающие добавлены
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    assert svc.paste_params("fx", payload, mode="keep")
    fx = svc.systems_json()["fx"]
    assert fx["attrs"]["radius"]["v"] == 5.0            # осталось
    assert fx["attrs"]["new_scale"]["v"] == 1.5         # добавлено
    init = fx["initializers"][0]
    assert init["attrs"]["color1"]["v"] == [0, 255, 30, 255]   # осталось
    assert init["attrs"]["color2"]["v"] == [9, 9, 9, 9]        # добавлено

    # replace: старые параметры и модули снесены, остались вставленные;
    # children и имя системы сохраняются
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    assert svc.paste_params("fx", payload, mode="replace")
    fx = svc.systems_json()["fx"]
    assert fx["attrs"]["radius"]["v"] == 42.0
    assert fx["attrs"]["new_scale"]["v"] == 1.5
    assert "max_particles" not in fx["attrs"]           # снесено
    assert "material" not in fx["attrs"]                # снесено
    assert [m["functionName"] for m in fx["initializers"]] == ["Color Random"]
    assert fx["initializers"][0]["attrs"]["color1"]["v"] == [1, 2, 3, 4]
    assert fx["children"] == [{"delay": 0.25, "childName": "fx_child"}]


def test_seed_spawn_area():
    """Добавленная область спавна не должна быть точкой: вырожденной задаём
    размер от радиуса частиц, осмысленную из шаблона не трогаем."""
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    d = svc._find_definition("fx")          # radius = 5.0 в фикстуре

    def _mod(fn, attrs=()):
        el = Element(fn, "DmeParticleOperator")
        el["functionName"] = Attribute.string("functionName", fn)
        for name, attr in attrs:
            el[name] = attr
        return el

    # Вырожденный бокс (min == max) → куб ±radius*4
    box = _mod("Position Within Box Random", [
        ("min", Attribute.vec3("min", 0, 0, 64)),
        ("max", Attribute.vec3("max", 0, 0, 64))])
    assert ParticleEditorService._seed_spawn_area(d, box)
    assert list(box["min"].val_vec3) == [-20.0, -20.0, -20.0]
    assert list(box["max"].val_vec3) == [20.0, 20.0, 20.0]

    # Бокс вообще без атрибутов — тоже получает размер
    bare = _mod("Position Within Box Random")
    assert ParticleEditorService._seed_spawn_area(d, bare)
    assert list(bare["max"].val_vec3) == [20.0, 20.0, 20.0]

    # Осмысленный бокс не трогаем
    good = _mod("Position Within Box Random", [
        ("min", Attribute.vec3("min", -3, -3, -3)),
        ("max", Attribute.vec3("max", 3, 3, 3))])
    assert not ParticleEditorService._seed_spawn_area(d, good)
    assert list(good["min"].val_vec3) == [-3.0, -3.0, -3.0]

    # Сфера нулевого радиуса → radius*6; ненулевая не трогается
    sph = _mod("Position Within Sphere Random", [
        ("distance_max", Attribute.float("distance_max", 0.0))])
    assert ParticleEditorService._seed_spawn_area(d, sph)
    assert abs(sph["distance_max"].val_float - 30.0) < 1e-6
    sph2 = _mod("Position Within Sphere Random", [
        ("distance_max", Attribute.float("distance_max", 7.0))])
    assert not ParticleEditorService._seed_spawn_area(d, sph2)

    # Не-позиционные модули не трогаем вовсе
    other = _mod("Lifetime Random")
    assert not ParticleEditorService._seed_spawn_area(d, other)

    # Размер соразмерен радиусу системы
    d["radius"] = Attribute.float("radius", 25.0)
    big = _mod("Position Within Box Random")
    ParticleEditorService._seed_spawn_area(d, big)
    assert list(big["max"].val_vec3) == [100.0, 100.0, 100.0]

    # add_module применяет то же самое (сквозной путь)
    svc.add_module("fx", "initializers", "Position Within Box Random")
    added = [m for m in svc.systems_json()["fx"]["initializers"]
             if m["functionName"] == "Position Within Box Random"][-1]
    assert added["attrs"]["max"]["v"] == [100.0, 100.0, 100.0]


def test_paste_params_duplicate_modules():
    """Списковый формат буфера: два одинаковых модуля не схлопываются,
    n-я копия в буфере метит n-ю копию у цели (инцидент halloween_ghosts —
    два Remap Noise to Scalar, radius-ремап терялся при копировании)."""
    payload = {
        "attrs": {},
        "modules": {
            "initializers": [
                ["Remap Noise to Scalar",
                 {"output field": {"t": "integer", "v": 3},
                  "output minimum": {"t": "float", "v": 0.5}}],
                ["Remap Noise to Scalar",
                 {"output field": {"t": "integer", "v": 1},
                  "output minimum": {"t": "float", "v": 0.6}}],
            ],
        },
    }
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    assert svc.paste_params("fx", payload)
    inits = svc.systems_json()["fx"]["initializers"]
    remaps = [m for m in inits if m["functionName"] == "Remap Noise to Scalar"]
    assert [m["attrs"]["output field"]["v"] for m in remaps] == [3, 1]

    # повторная вставка: 1-я запись мержится в 1-ю копию, 2-я во 2-ю —
    # модули не плодятся
    assert svc.paste_params("fx", payload)
    inits = svc.systems_json()["fx"]["initializers"]
    remaps = [m for m in inits if m["functionName"] == "Remap Noise to Scalar"]
    assert len(remaps) == 2

    # легаси-формат (dict) по-прежнему принимается
    legacy = {"attrs": {}, "modules": {
        "operators": {"Movement Basic": {"drag": {"t": "float", "v": 0.5}}}}}
    assert svc.paste_params("fx", legacy)
    ops = svc.systems_json()["fx"]["operators"]
    assert ops[0]["attrs"]["drag"]["v"] == 0.5


def test_snapshot_restore():
    """Снимок/восстановление для Ctrl+Z: дерево и оверрайды текстур."""
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    snap0 = svc.snapshot()
    assert snap0 is not None and snap0["pcf"][:4] == b"<!--"

    # Структурная и атрибутная правки + «оверрайд текстуры»
    assert svc.set_attr("fx", None, 0, "radius", 99.0)
    assert svc.add_module("fx", "operators", "Movement Basic")
    svc.custom_files["materials/effects/test.vtf"] = b"VTF\x00fake"
    svc._overwritten["effects/test.vmt"] = {
        "tex_rel": "effects/test", "material": "effects\\test.vmt"}
    snap1 = svc.snapshot()

    # Возврат к исходному состоянию
    assert svc.restore(snap0)
    sysj = svc.systems_json()
    assert sysj["fx"]["attrs"]["radius"]["v"] == 5.0
    assert sysj["fx"]["operators"] == []
    assert svc.custom_files == {}
    assert not svc.is_custom_material("effects\\test.vmt")

    # И вперёд к правленому
    assert svc.restore(snap1)
    sysj = svc.systems_json()
    assert sysj["fx"]["attrs"]["radius"]["v"] == 99.0
    assert [m["functionName"] for m in sysj["fx"]["operators"]] == ["Movement Basic"]
    assert "materials/effects/test.vtf" in svc.custom_files
    assert svc.is_custom_material("effects\\test.vmt")

    # Снимок — независимая копия: правки после него не протекают в историю
    svc.set_attr("fx", None, 0, "radius", 1.0)
    svc.custom_files["materials/effects/other.vtf"] = b"x"
    assert svc.restore(snap1)
    assert svc.systems_json()["fx"]["attrs"]["radius"]["v"] == 99.0
    assert "materials/effects/other.vtf" not in svc.custom_files

    # Битый снимок не рушит сервис
    assert not svc.restore({"pcf": b"garbage"})
    assert not svc.restore({})


def test_parse_vtf_sheet():
    # Sheet: version 1 (4 coords/кадр), 1 секвенция, 2 кадра
    sheet = struct.pack("<II", 1, 1)
    sheet += struct.pack("<III", 3, 1, 2)     # seqNo=3, clamp=1, frames=2
    sheet += struct.pack("<f", 2.0)           # total duration
    for frame in range(2):
        sheet += struct.pack("<f", 1.0)       # frame duration
        for c in range(4):
            sheet += struct.pack("<4f", 0.0, 0.0, 0.5, 0.5)

    # VTF 7.3 с одним ресурсом 0x10 сразу после заголовка
    data_offs = 0x50 + 8
    header = b"VTF\x00" + struct.pack("<II", 7, 3) + struct.pack("<I", data_offs)
    header = header.ljust(0x44, b"\x00") + struct.pack("<I", 1)  # numResources=1
    header = header.ljust(0x50, b"\x00")
    header += b"\x10\x00\x00" + b"\x00" + struct.pack("<I", data_offs)
    raw = header + struct.pack("<I", len(sheet)) + sheet

    parsed = parse_vtf_sheet(raw)
    assert parsed is not None
    seq = parsed["sequences"][3]
    assert seq["clamp"] is True
    assert seq["duration"] == 2.0
    assert len(seq["frames"]) == 2
    assert len(seq["frames"][0]["coords"]) == 4
    assert seq["frames"][0]["coords"][0] == [0.0, 0.0, 0.5, 0.5]

    # Не-VTF и VTF 7.2 (без ресурсов) → None
    assert parse_vtf_sheet(b"not a vtf") is None
    v72 = b"VTF\x00" + struct.pack("<II", 7, 2) + b"\x00" * 0x60
    assert parse_vtf_sheet(v72) is None
