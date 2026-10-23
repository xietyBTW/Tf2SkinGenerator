"""Характеризующие тесты ParticleEditorService:
игровая версия файла (stock), сборка VPK, ветки «родных цветов», полный
список модулей группы. Держат поведение при разборе сервиса на модули"""

import pytest

srctools_dmx = pytest.importorskip("srctools.dmx")
from srctools.dmx import Attribute, Element  # noqa: E402

from src.services.particle_editor_service import (  # noqa: E402
    MODULE_CATALOG,
    ParticleEditorService,
)
from tests.test_particle_editor_service import _make_pcf_bytes  # noqa: E402


def test_stock_is_loaded_once_per_path(monkeypatch):
    calls = []

    def fake_load(self, root, path):
        calls.append(path)
        self.load_bytes(_make_pcf_bytes(), source=f"vpk:{path}")

    monkeypatch.setattr(ParticleEditorService, "load_from_game", fake_load)
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes(), source=r"C:\mods\crit.pcf")
    stock = svc.stock("D:/tf2")
    assert stock is not None and stock.source_path == "vpk:particles/crit.pcf"
    assert svc.stock("D:/tf2") is stock
    assert svc.stock_diff("D:/tf2")["fx"]["status"] == "same"
    assert calls == ["particles/crit.pcf"]

    # Нет стока - None, и это тоже запоминается
    def broken(self, root, path):
        calls.append(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(ParticleEditorService, "load_from_game", broken)
    other = ParticleEditorService()
    other.load_bytes(_make_pcf_bytes(), source="vpk:particles/gone.pcf")
    assert other.stock("D:/tf2") is None
    assert other.stock("D:/tf2") is None
    assert other.stock_diff("D:/tf2") == {}
    assert calls[1:] == ["particles/gone.pcf"]
    assert not other.revert_attr("D:/tf2", "fx", None, 0, "radius")


def test_export_vpk_packs_pcf_and_texture_part(tmp_path, monkeypatch):
    from src.services.packaging_service import PackagingService

    packed = {}

    def fake_pack(vpkroot_dir, filename, export_folder, language):
        files = sorted(p.relative_to(vpkroot_dir).as_posix()
                       for p in vpkroot_dir.rglob("*") if p.is_file())
        packed[filename] = (files, export_folder, language)
        return f"{export_folder}/{filename}"

    monkeypatch.setattr(PackagingService, "pack_directory", staticmethod(fake_pack))
    svc = ParticleEditorService()
    with pytest.raises(RuntimeError):
        svc.export_vpk(str(tmp_path / "m.vpk"))

    svc.load_bytes(_make_pcf_bytes(), source=r"C:\mods\My.pcf")
    svc.custom_files = {"materials/effects/test.vtf": b"v",
                        "materials/effects/test.vmt": b"t",
                        "materials/effects/orphan.vtf": b"o"}
    svc._overwritten = {"effects/test.vmt": {"tex_rel": "effects/test",
                                             "material": "effects\\test.vmt"}}
    out = svc.export_vpk(str(tmp_path / "m.vpk"), language="ru")
    assert out == f"{tmp_path}/m.vpk"
    assert packed["m.vpk"] == (
        ["materials/effects/test.vmt", "materials/effects/test.vtf",
         "particles/My.pcf"], str(tmp_path), "ru")
    assert packed["m_textures.vpk"][0] == [
        "materials/effects/test.vmt", "materials/effects/test.vtf"]
    assert svc.last_textures_vpk == f"{tmp_path}/m_textures.vpk"

    # Без своих текстур второй архив не собирается
    packed.clear()
    svc._overwritten = {}
    svc.export_vpk(str(tmp_path / "m.vpk"))
    assert list(packed) == ["m.vpk"] and svc.last_textures_vpk is None


def test_use_texture_colors_field_remaps_and_children():
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    d = svc._find_definition("fx")
    child = svc._find_definition("fx_child")
    child["color"] = Attribute.color("color", 10, 20, 30, 40)

    def op(fn, **ints):
        el = Element(fn, "DmeParticleOperator")
        el["functionName"] = Attribute.string("functionName", fn)
        for k, v in ints.items():
            el[k.replace("_", " ")] = Attribute.int(k.replace("_", " "), v)
        return el

    ops = Attribute.array("operators", srctools_dmx.ValueType.ELEMENT)
    for el in (op("Remap Control Point to Vector", output_field=6),
               op("Remap Control Point to Vector", output_field=0),
               op("Oscillate Vector", oscillation_field=6),
               op("Oscillate Vector"),
               op("Color Fade")):
        ops.append(el)
    child["operators"] = ops
    d["children"].append(Element("dangling", "DmeParticleChild"))

    assert svc.use_texture_colors("nope") == 0
    assert svc.use_texture_colors("fx") == 4
    sysj = svc.systems_json()
    assert [m["attrs"].get("output field", m["attrs"].get("oscillation field"))
            for m in sysj["fx_child"]["operators"]] == [
        {"t": "integer", "v": 0}, None]
    assert sysj["fx_child"]["attrs"]["color"]["v"] == [255, 255, 255, 255]


def test_group_module_catalog_puts_curated_first():
    saved = dict(ParticleEditorService._module_display)
    ParticleEditorService._module_display.clear()
    try:
        ParticleEditorService._module_display.update({
            ("forces", "random force"): "random force",
            ("forces", "zz custom force"): "ZZ Custom Force",
            ("forces", "a custom force"): "a Custom Force",
            ("operators", "elsewhere"): "Elsewhere",
        })
        assert ParticleEditorService.group_module_catalog("forces") == (
            MODULE_CATALOG["forces"] + ["a Custom Force", "ZZ Custom Force"])
    finally:
        ParticleEditorService._module_display.clear()
        ParticleEditorService._module_display.update(saved)
