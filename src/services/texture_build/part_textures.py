"""
VMT материалов частей модели (src/services/part_materials.py)
"""

import os
from typing import Optional

from src.services.vmt_service import VMTService
from src.shared.logging_config import get_logger

from . import game_source

logger = get_logger(__name__)


def write_part_materials(variants: dict, specs, ctx, slots,
                          blu_of: Optional[dict] = None,
                          strip_paints: bool = False) -> dict:
    """
    VMT материалов частей (src/services/part_materials.py)

    Материал части - отдельный материал модели. В каждой строке скина его
    VMT начинается с ИГРОВОГО VMT материала, стоящего на его месте
    (главный, BLU, золото, стиль), и поверх ложится правка VMT части.
    $basetexture - своя картинка части для её команды (`image` в строках
    исходного, `image_blu` в строках его синего, `blu_of`), её правка
    стиля в строке стиля (`style_images` по материалу строки), иначе
    игровая текстура строки, выбранный человеком в правке - он. Картинку, правку и
    карты исходного материал части получил копией при создании
    (PartsEditor._fork_card): то, что лежит на исходном сейчас, его не
    касается

    Returns:
        {имя строки: (картинка, материал части)} - что отрендерить в
        `<имя строки>.vtf`; VMT уже лежит, рендер его не перезапишет
    """
    from src.services import part_materials as pm
    from src.services.edited_vmt_service import EditedVMTService

    by_name = {str(s['name']).lower(): s for s in specs if not s.get('existing')}
    names = sorted(by_name, key=len, reverse=True)
    blu_of = {str(k).lower(): str(v).lower() for k, v in (blu_of or {}).items()}
    written = {p.stem.lower(): p for p in slots.vtf_output_path.glob('*.vmt')}
    renders = {}

    def read(path) -> str:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    for name, source in variants.items():
        name, source = name.lower(), str(source)
        owner = next((n for n in names if name == n or name.startswith(n + '_')), name)
        spec = by_name.get(owner, {})
        origin = str(spec.get('base') or source)
        # Своего VMT у синего «сделать командным» в игре нет - тогда VMT
        # исходного, мод сам его не пишет - тот, что записан для строки
        template = (game_source.find_original_vmt(source, ctx, slots)
                    or game_source.find_original_vmt(origin, ctx, slots)
                    or written.get(source.lower()))
        if not template or not os.path.exists(template):
            logger.warning(f"[ЧАСТИ] {name}: нет VMT материала {source} - часть пропущена")
            ctx.warn(f"Материал части «{name}» не записан: нет VMT «{source}»")
            continue
        text = read(template)
        chosen = False
        edited = EditedVMTService.get_edited_vmt(owner)
        if edited and os.path.exists(edited):
            start = EditedVMTService.read_original_backup(owner)
            if start is None:
                # Правка без сохранённого оригинала: сравниваем с игровым
                # VMT исходного - с него правка и начиналась
                first = game_source.find_original_vmt(origin, ctx, slots)
                start = read(first) if first else text
            mine = read(edited)
            text = pm.overlay_vmt(text, start, mine)
            chosen = pm.basetexture_changed(start, mine)
        target = slots.vmt(name)
        with open(target, 'w', encoding='utf-8') as f:
            f.write(text)
        if strip_paints:
            VMTService.remove_paint_proxies(str(target))
        low = source.lower()
        image = (spec.get('image') if low == origin.lower()
                 else spec.get('image_blu') if low == blu_of.get(origin.lower())
                 else (spec.get('style_images') or {}).get(low))
        if image and not chosen:
            VMTService.update_vmt_basetexture_path(
                str(target), slots.patched_cdmaterials_path, name)
            renders[name] = (image, owner)
        logger.info(f"[ЧАСТИ] VMT {name} по образцу {source}"
                    f"{' + правка' if edited else ''}{' + своя картинка' if name in renders else ''}")
    return renders
