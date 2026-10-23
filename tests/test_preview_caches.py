"""Кэши повторного показа: OBJ из SMD, PNG из VTF, списки War Paint"""

import os
import time
from types import SimpleNamespace
from unittest.mock import patch

from src.data import paintkit_defs
from src.services import vtf_preview_service
from src.services.smd_to_obj_service import SmdToObjService

V = "0 0 0 0 0 0 1 {u} 0 1 0 1"


def _smd(path, mat, u=0.0):
    tri = f"{mat}\n  {V.format(u=u)}\n  {V.format(u=u)}\n  {V.format(u=u)}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write("version 1\nnodes\n0 \"root\" -1\nend\nskeleton\ntime 0\n"
                "0 0 0 0 0 0 0\nend\ntriangles\n" + tri + "end\n")


def test_same_smd_is_converted_once(tmp_path):
    smd = tmp_path / "m.smd"
    _smd(smd, "gun")
    first, second = tmp_path / "a" / "model.obj", tmp_path / "b" / "model.obj"
    os.makedirs(first.parent)
    assert SmdToObjService.convert(str(smd), str(first))[0]
    with patch.object(SmdToObjService, "_convert_parts",
                      side_effect=AssertionError("должно прийти из памяти")):
        ok, names = SmdToObjService.convert(str(smd), str(second))
    assert ok and names == ["gun"]
    assert second.read_bytes() == first.read_bytes()
    assert second.with_suffix(".mtl").read_bytes() == first.with_suffix(".mtl").read_bytes()


def test_changed_smd_is_converted_again(tmp_path):
    smd = tmp_path / "m.smd"
    _smd(smd, "gun")
    out = tmp_path / "model.obj"
    SmdToObjService.convert(str(smd), str(out))
    time.sleep(0.01)
    _smd(smd, "barrel")
    ok, names = SmdToObjService.convert(str(smd), str(out))
    assert ok and names == ["barrel"]


def test_same_vtf_is_decoded_once(tmp_path):
    frames = ([b"\xff\x00\x00\xff" * 4], 2, 2)
    with patch("src.services.vtflib_wrapper.VTFLib.read_vtf_all_frames",
               return_value=frames) as decode:
        a = vtf_preview_service.vtf_bytes_to_png(b"VTF-a", str(tmp_path / "a.png"))
        b = vtf_preview_service.vtf_bytes_to_png(b"VTF-a", str(tmp_path / "b.png"))
        vtf_preview_service.vtf_bytes_to_png(b"VTF-b", str(tmp_path / "c.png"))
    assert decode.call_count == 2
    assert open(a, "rb").read() == open(b, "rb").read()


def test_paintkit_list_is_rebuilt_only_for_new_defs():
    first, second = SimpleNamespace(), SimpleNamespace()
    built = []

    def build(root, lang):
        built.append(lang)
        return [{"id": len(built)}]

    paintkit_defs._LISTS.clear()
    with patch.object(paintkit_defs, "load", side_effect=[first, first, second]):
        a = paintkit_defs._remembered("t", "root", "en", build)
        b = paintkit_defs._remembered("t", "root", "en", build)
        c = paintkit_defs._remembered("t", "root", "en", build)
    paintkit_defs._LISTS.clear()
    assert a == b == [{"id": 1}] and c == [{"id": 2}]
    assert len(built) == 2
