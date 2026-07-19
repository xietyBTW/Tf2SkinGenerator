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


def test_set_system_texture_without_game(tmp_path):
    """Замена текстуры без установленной TF2: fallback-VMT, resize к степени
    двойки, материал переписан, файлы готовы к экспорту."""
    pytest.importorskip("PIL")
    from pathlib import Path as _P
    if not _P("tools/VTF/VTFLib.dll").exists():
        pytest.skip("VTFLib.dll недоступна")
    from PIL import Image

    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())

    img = tmp_path / "tex.png"
    Image.new("RGBA", (100, 60), (255, 0, 0, 255)).save(img)

    info = svc.set_system_texture("fx", str(img), tf2_root_dir="")
    assert info is not None
    assert (info["width"], info["height"]) == (64, 32)   # степени двойки
    assert info["dataUrl"].startswith("data:image/png;base64,")

    # слаг — от имени материала (effects\test.vmt → custom_test)
    mat = svc.systems_json()["fx"]["attrs"]["material"]["v"]
    assert mat == "particle/custom_test.vmt"
    assert set(svc.custom_files) == {
        "materials/particle/custom_test.vmt",
        "materials/particle/custom_test.vtf",
    }
    vmt_text = svc.custom_files["materials/particle/custom_test.vmt"].decode()
    assert '"$basetexture" "particle/custom_test"' in vmt_text
    assert svc.custom_files["materials/particle/custom_test.vtf"][:4] == b"VTF\x00"
    # кастомный материал виден превью даже без TF2
    assert mat in svc.materials_json("")

    # повторная замена: тот же путь (перезапись), базис — прежний кастомный VMT
    img2 = tmp_path / "tex2.png"
    Image.new("RGBA", (64, 64), (0, 255, 0, 255)).save(img2)
    info2 = svc.set_system_texture("fx", str(img2), tf2_root_dir="")
    assert info2 is not None
    assert svc.systems_json()["fx"]["attrs"]["material"]["v"] == mat
    assert set(svc.custom_files) == {
        "materials/particle/custom_test.vmt",
        "materials/particle/custom_test.vtf",
    }

    # замена по материалу затрагивает и дочернюю систему с тем же материалом,
    # даже если регистр/слэши записаны иначе (Effects/TEST.vmt)
    svc2 = ParticleEditorService()
    svc2.load_bytes(_make_pcf_bytes())
    res = svc2.set_material_texture("effects\\test.vmt", str(img), "")
    assert res is not None
    new_mat, _info = res
    sysj = svc2.systems_json()
    assert sysj["fx"]["attrs"]["material"]["v"] == new_mat
    assert sysj["fx_child"]["attrs"]["material"]["v"] == new_mat

    # сброс к текстуре игры: материал возвращён, файлы замены убраны
    assert svc2.is_custom_material(new_mat)
    orig = svc2.reset_material_texture(new_mat)
    assert orig == "effects\\test.vmt"
    sysj = svc2.systems_json()
    assert sysj["fx"]["attrs"]["material"]["v"] == orig
    assert sysj["fx_child"]["attrs"]["material"]["v"] == orig
    assert svc2.custom_files == {}
    assert not svc2.is_custom_material(new_mat)
    assert svc2.reset_material_texture(new_mat) is None


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
