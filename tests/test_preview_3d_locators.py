"""
Поиск SMD и текстур для 3D-превью: какие файлы и в каком порядке берутся

Характеризующие тесты: сняты с поведения воркера до того, как поиск уехал в
чистые функции. Архивы поддельные (tests/fake_vpk), порядок обращений к ним
проверяется дословно - именно он решает, какая из двух версий текстуры
(c_items или workshop) попадёт в кадр
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.services import smd_locator, texture_locator
from src.services.preview_3d_worker import Preview3DWorker
from tests.fake_vpk import FakePak, fake_reader, vmt


@pytest.fixture(autouse=True)
def _stub_vtf_decoder(monkeypatch):
    """«VTF-байты» здесь - уже готовая картинка: пишем их как есть"""
    from src.services import vtf_preview_service as vps

    def fake(data, out_png_path, tmp_dir=None):
        if not data:
            return None
        Path(out_png_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_png_path).write_bytes(data)
        return out_png_path

    def fake_frames(data, out_dir, base_name, tmp_dir=None):
        p = fake(data, str(Path(out_dir) / f"{base_name}.png"))
        return [p] if p else []

    monkeypatch.setattr(vps, "vtf_bytes_to_png", fake)
    monkeypatch.setattr(vps, "vtf_bytes_to_frame_pngs", fake_frames)
    monkeypatch.setattr("src.services.vmt_tint.apply_to_png", lambda *a, **k: None)


def _png(tag: str) -> bytes:
    return f"PNG:{tag}".encode()


def _worker(tmp, files=None, weapon_key="c_gun", mode="scout_c_gun", qc=None):
    w = Preview3DWorker(weapon_key, mode, "", "")
    w._preview_dir = os.path.join(tmp, "preview")
    os.makedirs(w._preview_dir, exist_ok=True)
    w._reader = fake_reader(files or {})
    if qc is not None:
        decomp = os.path.join(tmp, "decomp")
        os.makedirs(decomp, exist_ok=True)
        Path(decomp, "model.qc").write_text(qc, encoding="utf-8")
        w._decomp_dir = decomp
    return w


def _touch(directory, *names):
    for n in names:
        Path(directory, n).write_text("version 1\n", encoding="utf-8")


def _content(paths):
    return {k: Path(v).read_bytes() for k, v in paths.items()}


# Адаптеры: единственное место, которое знает, где живёт поиск

def reference_smd(w, directory):
    return smd_locator.find_reference_smd(directory, w.mode, w.weapon_key, w._model)


def vtf_for_mat(w, pak, mat, arm_folder, cdmaterials=None):
    return texture_locator.find_vtf_for_mat(pak, mat, arm_folder, cdmaterials)


# Reference SMD

def test_spy_mask_mode_takes_spy_mask_smd():
    with TemporaryDirectory() as tmp:
        _touch(tmp, "spy_reference.smd", "spy_mask.smd")
        w = _worker(tmp, weapon_key="models/player/spy.mdl", mode="spy_masks")
        assert os.path.basename(reference_smd(w, tmp)) == "spy_mask.smd"


def test_spy_mask_mode_falls_back_to_any_mask_but_not_lod():
    with TemporaryDirectory() as tmp:
        _touch(tmp, "head_mask_lod1.smd", "head_mask.smd", "spy_reference.smd")
        w = _worker(tmp, weapon_key="models/player/spy.mdl", mode="spy_masks")
        assert os.path.basename(reference_smd(w, tmp)) == "head_mask.smd"


def test_character_without_qc_prefers_morphs_low():
    with TemporaryDirectory() as tmp:
        _touch(tmp, "scout_reference.smd", "scout_morphs_low.smd")
        w = _worker(tmp, weapon_key="models/player/scout.mdl", mode="scout_body")
        assert os.path.basename(reference_smd(w, tmp)) == "scout_morphs_low.smd"


def test_character_class_fallback_skips_bodygroup_words():
    with TemporaryDirectory() as tmp:
        _touch(tmp, "scout_backpack.smd", "scout_main.smd", "scout_anims.smd")
        w = _worker(tmp, weapon_key="models/player/scout.mdl", mode="scout_body")
        assert os.path.basename(reference_smd(w, tmp)) == "scout_main.smd"


def test_weapon_reference_then_key_then_anything():
    with TemporaryDirectory() as tmp:
        _touch(tmp, "c_gun_physics.smd", "c_gun_reference.smd")
        w = _worker(tmp)
        assert os.path.basename(reference_smd(w, tmp)) == "c_gun_reference.smd"
    with TemporaryDirectory() as tmp:
        _touch(tmp, "c_gun_physics.smd", "my_c_gun_part.smd")
        assert os.path.basename(reference_smd(_worker(tmp), tmp)) == "my_c_gun_part.smd"
    with TemporaryDirectory() as tmp:
        _touch(tmp, "c_gun_physics.smd", "other.smd")
        assert os.path.basename(reference_smd(_worker(tmp), tmp)) == "other.smd"
    with TemporaryDirectory() as tmp:
        _touch(tmp, "c_gun_physics.smd")
        assert reference_smd(_worker(tmp), tmp) is None


# Где ищется VTF материала

def test_vtf_candidates_order_for_player_material():
    with TemporaryDirectory() as tmp:
        w = _worker(tmp)
        pak = FakePak({})
        assert vtf_for_mat(w, pak, "Scout_Head_red", "scout",
                           ["models/weapons/c_items"]) is None
        assert pak.reads == [
            "materials/models/player/scout/Scout_Head_red.vtf",
            "materials/models/player/scout/scout_head_red.vtf",
            "materials/models/player/scout/Scout_Head.vtf",
            "materials/models/player/scout/scout_head.vtf",
            "materials/models/weapons/c_items/Scout_Head_red.vtf",
            "materials/models/weapons/c_items/scout_head_red.vtf",
            "materials/models/workshop_partner/weapons/c_models/Scout_Head_red/Scout_Head_red.vtf",
            "materials/models/weapons/c_models/Scout_Head_red/Scout_Head_red.vtf",
            "materials/models/weapons/c_items/Scout_Head_red.vtf",
            "materials/models/workshop/weapons/c_models/Scout_Head_red/Scout_Head_red.vtf",
        ]


def test_vtf_candidates_strip_overlay_suffix():
    with TemporaryDirectory() as tmp:
        w = _worker(tmp)
        pak = FakePak({"materials/models/player/hvyweapon/hvyweapon_hands.vtf": b"X"})
        assert vtf_for_mat(w, pak, "hvyweapon_hands_sheen", "hvyweapon") == b"X"
        assert pak.reads == [
            "materials/models/player/hvyweapon/hvyweapon_hands_sheen.vtf",
            "materials/models/player/hvyweapon/hvyweapon_hands.vtf",
        ]


# Несколько материалов

QC_CD = '$modelname "x.mdl"\n$cdmaterials "models\\weapons\\c_items\\"\n'
CD = "materials/models/weapons/c_items"


def test_multi_textures_by_player_folder_and_via_vmt():
    files = {
        "materials/models/player/scout/scout_red.vtf": _png("body"),
        f"{CD}/insert.vmt": vmt(basetexture="vgui/insert_tex"),
        "materials/vgui/insert_tex.vtf": _png("insert"),
    }
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, files, weapon_key="models/player/scout.mdl",
                    mode="scout_body", qc=QC_CD)
        out = w._extract_multi_textures(["scout_red", "insert", "missing"])
        assert _content(out) == {"scout_red": _png("body"), "insert": _png("insert")}


QC_BODY_TEAM = QC_CD + (
    '$texturegroup "skinfamilies"\n{\n'
    '\t{ "scout_red" "scout_head_red" "scout_eyes" }\n'
    '\t{ "scout_blue" "scout_head_blue" "scout_eyes_b" }\n}\n')


def test_blu_multi_textures_by_cdmaterials_player_folder_and_names_only():
    files = {
        f"{CD}/scout_blue.vtf": _png("blue body"),
        "materials/models/player/scout/scout_head.vtf": _png("head"),
    }
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, files, weapon_key="models/player/scout.mdl",
                    mode="scout_body", qc=QC_BODY_TEAM)
        raw = w._extract_blu_multi_textures_via_qc(
            ["scout_red", "scout_head_red", "scout_eyes", "unknown"])
        assert set(raw) == {"scout_red", "scout_head_red", "scout_eyes"}
        assert Path(raw["scout_red"][0]).read_bytes() == _png("blue body")
        assert raw["scout_red"][1] == "scout_blue"
        assert Path(raw["scout_head_red"][0]).read_bytes() == _png("head")
        assert raw["scout_eyes"] == (None, "scout_eyes_b")


# Одна текстура оружия

def test_weapon_texture_from_standard_paths_and_blu_by_suffix():
    files = {
        "materials/models/weapons/c_items/c_gun.vtf": _png("red"),
        "materials/models/weapons/c_models/c_gun/c_gun_blue.vtf": _png("blu"),
    }
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, files)
        frames, fps = w._extract_texture_frames(["c_gun"])
        assert [Path(f).read_bytes() for f in frames] == [_png("red")] and fps == 0.0
        frames, fps = w._extract_blu_texture_frames(12.0)
        assert [Path(f).read_bytes() for f in frames] == [_png("blu")] and fps == 0.0


def test_weapon_texture_prefers_qc_folder_over_older_version():
    """Две версии модели в игре: текстура - по $cdmaterials показываемой"""
    qc = '$modelname "x.mdl"\n$cdmaterials "models\\workshop\\weapons\\c_models\\c_gun\\"\n'
    files = {
        "materials/models/weapons/c_items/c_gun.vtf": _png("old"),
        "materials/models/workshop/weapons/c_models/c_gun/c_gun.vtf": _png("workshop"),
    }
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, files, qc=qc)
        frames, _ = w._extract_texture_frames(["c_gun"])
        assert Path(frames[0]).read_bytes() == _png("workshop")


def test_variant_texture_is_first_column_of_gold_row():
    qc = QC_CD + ('$texturegroup "skinfamilies"\n{\n'
                  '\t{ "c_gun" }\n\t{ "c_gun_blue" }\n\t{ "c_gun_gold" }\n}\n')
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, {f"{CD}/c_gun_gold.vtf": _png("gold")}, qc=qc)
        path, name = w._extract_variant_via_qc(w._decomp_dir)
        assert name == "c_gun_gold" and Path(path).read_bytes() == _png("gold")
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, {}, qc=qc)
        assert w._extract_variant_via_qc(w._decomp_dir) == (None, None)


def test_hat_texture_guess_tries_class_and_workshop_paths():
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, {}, weapon_key="models/player/items/%s/cap.mdl", mode="hat")
        assert w._extract_hat_texture_frames() == ([], 0.0)
        reads = w._reader.paks[0].reads
        assert reads[:3] == [
            "materials/models/player/items/heavy/cap.vtf",
            "materials/models/workshop_partner/player/items/heavy/cap.vtf",
            "materials/models/workshop/player/items/heavy/cap.vtf",
        ]
        assert len(reads) == 27
        found = "materials/models/workshop/player/items/spy/cap.vtf"
        w = _worker(tmp, {found: _png("cap")},
                    weapon_key="models/player/items/%s/cap.mdl", mode="hat")
        frames, _ = w._extract_hat_texture_frames()
        assert Path(frames[0]).read_bytes() == _png("cap")


# Добавки: фиксированные пути и $texturegroup

def test_fixed_extra_textures_game_path_vmt_and_blank():
    files = {
        "materials/vgui/pocket_watch_fg.vtf": _png("fg"),
    }
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, files, weapon_key="c_pocket_watch", mode="spy_c_pocket_watch")
        out = w._extract_fixed_extra_textures()
        assert Path(out["pocket_watch_fg"]).read_bytes() == _png("fg")
        assert os.path.isfile(out["pocket_watch_bg"]), "пустой слот без оригинала"

    files = {
        "materials/vgui/replay/thumbnails/deadringer/pocket_watch_bg.vmt":
            vmt(basetexture="vgui/real_bg"),
        "materials/vgui/real_bg.vtf": _png("bg"),
    }
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, files, weapon_key="c_pocket_watch", mode="spy_c_pocket_watch")
        out = w._extract_fixed_extra_textures()
        assert Path(out["pocket_watch_bg"]).read_bytes() == _png("bg")


QC_EXTRAS = QC_CD + ('$texturegroup "skinfamilies"\n{\n'
                     '\t{ "c_gun" "smiley" "eyeball_invun" }\n'
                     '\t{ "c_gun" "smiley" "eyeball_invun" }\n}\n')


def test_texturegroup_extras_and_misc():
    with TemporaryDirectory() as tmp:
        w = _worker(tmp, {f"{CD}/smiley.vtf": _png("smiley")}, qc=QC_EXTRAS)
        extras = w._extract_texturegroup_extras(["c_gun"])
        assert _content(extras) == {"smiley": _png("smiley")}
        misc = w._extract_texturegroup_misc_extras(["c_gun"])
        assert list(misc) == ["eyeball_invun"] and os.path.isfile(misc["eyeball_invun"])
