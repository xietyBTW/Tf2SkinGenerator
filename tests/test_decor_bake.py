"""
«Сделать праздничным»: гирлянда вшивается в модель оружия (decor_bake)

Проверено в игре на обрезе: вшитая гирлянда видна и мигает.
Здесь - то, что легко сломать: кости гирлянды по именам, командный столбец
скинов и то, что сборка не путает вшитую гирлянду с отдельной моделью
"""

from pathlib import Path
from types import SimpleNamespace

from src.domain.preview.session import PreviewSession
from src.services import decor_bake, decor_build
from src.services.build_request import BuildRequest
from src.services.vpk_service import VPKService

WEAPON_SMD = """version 1
nodes
  0 "weapon_bone" -1
  1 "weapon_bone_1" 0
end
skeleton
time 0
  0 0 0 0 0 0 0
  1 0 1 0 0 0 0
end
triangles
gun
  0 0 0 0 0 0 1 0 0 1 0 1.0
  0 1 0 0 0 0 1 1 0 1 0 1.0
  1 0 1 0 0 0 1 0 1 1 1 1.0
end
"""

# У гирлянды кости в другом порядке: номер 0 у неё - weapon_bone_1
GARLAND_SMD = """version 1
nodes
  0 "weapon_bone_1" -1
  1 "weapon_bone" 0
end
skeleton
time 0
  0 0 1 0 0 0 0
  1 0 0 0 0 0 0
end
triangles
lights
  0 5 5 5 0 0 1 0 0 1 0 1.0
  1 6 5 5 0 0 1 1 0 1 1 1.0
  0 5 6 5 0 0 1 0 1 1 0 1.0
end
"""


def test_garland_triangles_keep_their_bones_by_name(tmp_path):
    body, garland = tmp_path / "gun.smd", tmp_path / "lights.smd"
    body.write_text(WEAPON_SMD, encoding="utf-8")
    garland.write_text(GARLAND_SMD, encoding="utf-8")
    decor_bake.append_triangles(str(body), str(garland))
    lines = body.read_text(encoding="utf-8").splitlines()
    assert lines[-1] == "end" and lines.count("end") == 3
    tri = lines[lines.index("lights") + 1:lines.index("lights") + 4]
    # weapon_bone_1 у оружия - кость 1, weapon_bone - кость 0
    assert [row.split()[0] for row in tri] == ["1", "0", "1"]
    assert tri[0].split()[10] == "1" and tri[1].split()[10] == "0"
    assert "gun" in lines                                 # меш оружия на месте


def test_team_lights_follow_the_weapon_skin_pairs():
    weapon = [["gun", "gun_gold"], ["gun_blu", "gun_gold"], ["gun_gold", "gun_gold"]]
    garland = [["lights"], ["lights_blu"]]
    assert decor_bake.skin_rows(weapon, garland) == [
        ["gun", "gun_gold", "lights"], ["gun_blu", "gun_gold", "lights_blu"],
        ["gun_gold", "gun_gold", "lights"]]
    assert decor_bake.skin_rows([], garland) == garland      # оружие без скинов
    # Одна строка у оружия (револьвер): синему всё равно нужна своя
    assert decor_bake.skin_rows([["gun"]], garland) == [["gun", "lights"],
                                                        ["gun", "lights_blu"]]
    assert decor_bake.skin_rows(weapon, [["lights"]]) == []   # гирлянда без команд


def test_qc_gets_the_garland_folder_and_skins(tmp_path):
    qc = tmp_path / "gun.qc"
    qc.write_text('$modelname "weapons/gun.mdl"\n$body body "gun.smd"\n'
                  '$cdmaterials "vgui\\models\\gun\\"\n$cdmaterials ""\n'
                  '$texturegroup "skinfamilies"\n{\n\t{ "gun" }\n\t{ "gun_blu" }\n}\n',
                  encoding="utf-8")
    decor_bake.add_to_qc(str(qc), "vgui\\models\\tf2sg_decor\\gun_xmas",
                         [["lights"], ["lights_blu"]])
    text = qc.read_text(encoding="utf-8")
    assert '$cdmaterials "vgui\\models\\tf2sg_decor\\gun_xmas\\"' in text
    assert '$cdmaterials "vgui\\models\\gun\\"' in text
    assert '{ "gun" "lights" }' in text and '{ "gun_blu" "lights_blu" }' in text


def _editor(baked=""):
    from src.app.decor_editor import DecorEditor

    preview = PreviewSession()
    preview.decor_baked = baked
    host = SimpleNamespace(preview=preview, _shown_weapon=lambda: "c_scattergun")
    return DecorEditor(host)


def test_baked_garland_goes_to_the_build_with_every_native_emptied(monkeypatch):
    from src.services import festive_decor

    monkeypatch.setattr(festive_decor, "kinds", lambda key, root: {
        "xmas": "models/x_xmas.mdl", "festivizer": "models/x_festivizer.mdl"})
    assert _editor().builds("root") == []                     # без правок - ничего
    [entry] = _editor("xmas").builds("root")
    assert entry["kind"] == "xmas" and entry["bake"]
    assert entry["empty"] == ["models/x_xmas.mdl", "models/x_festivizer.mdl"]


def test_build_keeps_the_weapon_and_skips_the_baked_garland_model():
    baked = [{"kind": "xmas", "mdl": "m", "bake": True, "textures": {}}]
    assert not VPKService._is_decor_only(BuildRequest(decor_builds=baked))
    assert VPKService._is_decor_only(BuildRequest(
        decor_builds=[{"kind": "xmas", "mdl": "m", "textures": {}}]))
    ctx = SimpleNamespace(temp_dir=str(Path(".")), vpkroot_dir=Path("."))
    assert decor_build.build_decor_models(
        ctx, baked, misc_vpk="", textures_vpk="", studiomdl_exe="", tf_dir="",
        size=(4, 4), format_type="DXT5", flags=[], vtf_options={}) == 0


def test_baked_kind_lives_in_the_work():
    p = PreviewSession()
    p.decor_baked = "festivizer"
    edits = p.user_edits()
    q = PreviewSession()
    q.apply_user_edits(edits)
    assert q.decor_baked == "festivizer"
