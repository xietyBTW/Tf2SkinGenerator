"""Модель, доехавшая при сцене в кадре, не затирает подложку сцены."""

from src.app.preview_controller import Preview3DController
from src.domain.preview.session import PreviewSession


def test_scene_extra_waits_for_scene_exit():
    s = PreviewSession()
    c = Preview3DController(s)
    s.scene_extra_textures = {'arms': 'arms.png'}   # руки сцены
    c.scene_up = lambda: True

    c._on_scene_extra(({'carrier': 'gun.png'}, ['deco']))
    assert s.scene_extra_textures == {'arms': 'arms.png'}

    # Выход из сцены возвращает подложку обычной модели.
    c.scene_up = lambda: False
    c.apply_scene_extra()
    assert s.scene_extra_textures == {'carrier': 'gun.png'}
    assert s.scene_item_materials == ['deco']
