"""
Построение текстур/материалов VPK-сборки: фасад над стадиями

Стадии живут в ``src/services/texture_build/``:

- ``main_texture``    - главный VTF/VMT и синяя пара главной;
- ``extra_materials`` - доп. материалы, «Прочее», служебные, плечи рук;
- ``blu_rows``        - синяя строка $texturegroup поколоночно;
- ``material_maps``   - карты материала (нормаль, phong, envmap, detail...),
  с помощниками ``map_textures`` и ``map_settings``;
- ``panel_extras``    - текстуры 2D-панели, варианты стилей, части;
- ``fixed_extras``, ``styles``, ``part_textures`` - их составляющие;
- ``game_source``     - оригиналы игры и общие записи VMT

Фасад держит имена, которыми зовёт VPKService. Подменять в тестах
надо функцию в модуле стадии: вызовы между стадиями фасад не видят
"""

from src.services.texture_build import (
    blu_rows,
    extra_materials,
    game_source,
    main_texture,
    map_settings,
    material_maps,
    panel_extras,
    part_textures,
    styles,
)


class VpkTextureBuilder:
    """Прежний интерфейс сборки текстур (см. модуль)"""

    # Стадии в порядке сборки (VPKService._stage_textures)
    _build_main_material = staticmethod(main_texture.build_main_material)
    _maybe_build_blu_team_texture = staticmethod(main_texture.maybe_build_blu_team_texture)
    _build_extra_material_textures = staticmethod(extra_materials.build_extra_material_textures)
    _write_blacklisted_materials = staticmethod(extra_materials.write_blacklisted_materials)
    _write_shoulder_iso_materials = staticmethod(extra_materials.write_shoulder_iso_materials)
    _build_blu_row_textures = staticmethod(blu_rows.build_blu_row_textures)
    _finish_variant_copies = staticmethod(extra_materials.finish_variant_copies)
    _build_secondary_textures = staticmethod(panel_extras.build_secondary_textures)
    _follow_shared_textures = staticmethod(extra_materials.follow_shared_textures)

    # Отдельные шаги, которыми пользуются другие сервисы и тесты
    _render_panel_extras = staticmethod(panel_extras.render_panel_extras)
    _render_extra_texture = staticmethod(panel_extras.render_extra_texture)
    _write_part_materials = staticmethod(part_textures.write_part_materials)
    _remap_skin_data_to_smd = staticmethod(styles.remap_skin_data_to_smd)
    _build_material_maps = staticmethod(material_maps.build_material_maps)
    _apply_maps_for_material = staticmethod(material_maps.apply_maps_for_material)
    _apply_settings = staticmethod(map_settings.apply_settings)
    _fresnel_ranges = staticmethod(map_settings.fresnel_ranges)
    _apply_edited_vmt = staticmethod(game_source.apply_edited_vmt)
    _basetexture_chosen = staticmethod(game_source.basetexture_chosen)
    _basetexture_fps = staticmethod(game_source.basetexture_fps)
    _get_original_vtf_bytes = staticmethod(game_source.get_original_vtf_bytes)
    _vtf_via_vmt = staticmethod(game_source.vtf_via_vmt)
    texture_reader = staticmethod(game_source.texture_reader)
