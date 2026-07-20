"""_active_custom_files: экспорт включает и VTF, и оригинальный VMT материала."""
from src.services.particle_editor_service import ParticleEditorService


class _Attr:
    def __init__(self, v):
        self.val_str = v


def _service_with_override():
    svc = ParticleEditorService()
    svc.custom_files = {
        "materials/effects/crit.vtf": b"vtf",
        "materials/effects/crit.vmt": b"vmt",
        "materials/effects/orphan.vtf": b"unused",
    }
    svc._overwritten = {
        "effects/crit.vmt": {"tex_rel": "effects/crit", "material": "effects\\crit.vmt"},
    }
    svc._all_definition_elements = lambda: [{"material": _Attr("effects\\crit.vmt")}]
    return svc


def test_export_includes_vtf_and_original_vmt():
    files = _service_with_override()._active_custom_files()
    assert files == {
        "materials/effects/crit.vtf": b"vtf",
        "materials/effects/crit.vmt": b"vmt",
    }


def test_unused_material_stays_out():
    svc = _service_with_override()
    svc._all_definition_elements = lambda: []
    assert svc._active_custom_files() == {}


def test_missing_game_vmt_generates_spritecard_template():
    svc = ParticleEditorService()
    svc._resolve_texture_path = lambda material_name, tf2_root_dir: (
        None, "effects/custom_new")
    svc._image_to_vtf = lambda *a: (b"vtf", 64, 64, "")
    info = svc._overwrite_texture(
        "effects/custom_new.vmt", "img.png", "", 512, False)
    vmt = svc.custom_files["materials/effects/custom_new.vmt"].decode()
    assert '"SpriteCard"' in vmt
    assert '"$basetexture" "effects/custom_new"' in vmt
    assert '"$vertexcolor" 1' in vmt
    assert info["shader"] == "spritecard"
    assert info["additive"] is False
