"""
Стадия «варианты стилей» (skinfamilies) своей модели
"""

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def remap_skin_data_to_smd(skin_build_data: dict, smd_mats: list) -> dict:
    """
    Переименовывает материалы стилей под ФАКТИЧЕСКИЕ имена материалов SMD

    UI собирает имена из превью-загрузки, к моменту сборки имена меша в SMD
    могут отличаться (другой экспорт/регистр). Сопоставляем UI↔SMD ПО ИНДЕКСУ
    (порядок появления материалов) и переписываем mesh_materials / tg_overrides /
    variant_files на SMD-имена. Картинки вариантов сохраняются
    """
    ui_mats = skin_build_data.get('mesh_materials', [])
    if not ui_mats or not smd_mats:
        return skin_build_data

    name_map = {um: (smd_mats[i] if i < len(smd_mats) else um)
                for i, um in enumerate(ui_mats)}

    old_variants = skin_build_data.get('variant_files', {})
    new_tg: dict = {}
    new_variants: dict = {}
    for skin_idx, mats in skin_build_data.get('tg_overrides', {}).items():
        for ui_mat, old_vname in mats.items():
            base = name_map.get(ui_mat, ui_mat)
            # суффикс роли = хвост старого имени варианта после "ui_mat_"
            prefix = (ui_mat + '_')
            suffix = old_vname[len(prefix):] if old_vname.lower().startswith(prefix.lower()) else old_vname
            new_vname = f"{base}_{suffix}"
            new_tg.setdefault(skin_idx, {})[base] = new_vname
            if old_vname in old_variants:
                new_variants[new_vname] = old_variants[old_vname]

    return {
        'mesh_materials': [name_map.get(m, m) for m in ui_mats],
        'tg_overrides': new_tg,
        'variant_files': new_variants,
    }
