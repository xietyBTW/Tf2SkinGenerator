"""
Фоновая сборка War Paint в текстуру: рецепт → компоновщик → PNG.

Текстуры рецепта читаются из VPK игры и кэшируются между запусками: человек
перебирает сид и износ одного War Paint, а узоры, маски групп и альбедо пушки
при этом те же — распаковывать их заново значило бы ждать каждый раз.
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections import OrderedDict
from typing import Optional, Tuple

import numpy as np

from src.services.base_worker import StandardWorker
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Сколько разобранных текстур держать: у War Paint их 10–20, у соседнего
#: износа они почти те же. По 4 МБ на 1024² — десятки мегабайт, не больше.
_CACHE_LIMIT = 48
_cache: "OrderedDict[Tuple[str, int, bool], Optional[np.ndarray]]" = OrderedDict()
_cache_lock = threading.Lock()


def _downscale(rgba: np.ndarray, limit: int, raw: bool = False) -> np.ndarray:
    """Уменьшает вдвое, пока сторона больше ``limit`` (компоновщик больше не прочтёт).

    raw — маска групп: прореживаем, а не усредняем (номера групп не смешивать).
    """
    while max(rgba.shape[:2]) > limit and min(rgba.shape[:2]) >= 2:
        if raw:
            rgba = rgba[::2, ::2]
            continue
        h, w = rgba.shape[0] // 2 * 2, rgba.shape[1] // 2 * 2
        a = rgba[:h, :w].astype(np.uint16)
        rgba = ((a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2] + 2) // 4
                ).astype(np.uint8)
    return rgba


def make_loader(reader, size: int):
    """Функция чтения текстуры рецепта (путь материала → RGBA uint8) с кэшем."""
    from src.services.vtflib_wrapper import VTFLib

    def load(path: str, raw: bool = False) -> Optional[np.ndarray]:
        name = path.replace('\\', '/').lower()
        # У части рецептов путь с расширением исходника (…_miami_pixels.tga):
        # в игре по нему лежит обычный VTF.
        stem, ext = os.path.splitext(name)
        if ext in ('.tga', '.vtf', '.png', '.psd', '.jpg'):
            name = stem
        key = (name, int(size), bool(raw))
        with _cache_lock:
            if key in _cache:
                _cache.move_to_end(key)
                return _cache[key]
        data = reader.read(f'materials/{key[0]}.vtf')
        rgba = None
        if data:
            fd, tmp = tempfile.mkstemp(suffix='.vtf', prefix='tf2sg_pk_')
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(data)
                data_rgba, w, h = VTFLib.read_vtf_as_rgba(tmp)
                rgba = _downscale(np.frombuffer(data_rgba, np.uint8).reshape(h, w, 4),
                                  size, raw)
            except Exception as exc:                      # noqa: BLE001
                logger.warning(f'[paintkit] {path}: {exc}')
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        with _cache_lock:
            _cache[key] = rgba
            while len(_cache) > _CACHE_LIMIT:
                _cache.popitem(last=False)
        return rgba

    return load


def _find_mdl(reader, mdl_path: str) -> Optional[bytes]:
    """MDL оружия: по пути, а если модель лежит не там — по имени файла."""
    path = mdl_path.replace('\\', '/').lower()
    data = reader.read(path) if '/' in path else None
    if data:
        return data
    base = '/' + path.rsplit('/', 1)[-1]
    for pak in reader.paks:
        for name in pak:
            if name.lower().endswith(base):
                return pak[name].read()
    return None


def paintable_materials(reader, mdl_path: str) -> list:
    """
    Материалы модели, на которые игра кладёт War Paint (имена без пути, lower).

    Игра подставляет War Paint прокси `WeaponSkin` в каждый VMT, где он
    записан. Обычно это главный материал и его синяя пара, но у Детонатора
    ещё и гильза — поэтому список, а не «главный материал».
    """
    from src.services.mdl_mesh import materials

    mdl = _find_mdl(reader, mdl_path)
    if not mdl:
        return []
    names, cds = materials(mdl)
    found = []
    for name in names:
        for cd in cds or ['']:
            rel = '/'.join(x for x in (cd.strip('/'), name.strip('/')) if x)
            text = reader.read(f'materials/{rel}.vmt'.lower())
            if text is None:
                continue
            if b'weaponskin' in text.lower():
                found.append(name.rsplit('/', 1)[-1].lower())
            break
    return found


class PaintkitWorker(StandardWorker):
    """Собирает War Paint ``kit_id`` на пушке ``item_def`` в PNG ``out_path``."""

    def __init__(self, tf2_root: str, textures_vpk: str, misc_vpk: str,
                 kit_id: int, item_def: int, wear: int, team: str, seed: int,
                 out_path: str, size: int = 1024, mdl_path: str = '',
                 generic: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.tf2_root = tf2_root
        self.vpks = [textures_vpk, misc_vpk]
        self.kit_id, self.item_def = int(kit_id), int(item_def)
        self.wear, self.team, self.seed = int(wear), team, int(seed)
        # Больше 2048 у игры текстур оружия нет, меньше 256 — узор не разглядеть.
        self.size = min(max(int(size), 256), 2048)
        self.out_path = out_path
        self.mdl_path = mdl_path
        #: Универсальный режим (у оружия нет War Paint в игре): {obj_path,
        #: cuts, regions, card, base_png, layout_seed} — см. paintkit_generic.
        self.generic = generic
        #: Материалы, на которые игра кладёт War Paint (см. paintable_materials).
        self.materials: list = []
        #: Текстуры рецепта, которых в игре не нашлось (для подсказки человеку).
        self.missing: list = []

    def work(self) -> Tuple[bool, str]:
        from PIL import Image

        from src.data import paintkit_defs
        from src.services.game_vpk_reader import GameVpkReader
        from src.services.paintkit_compositor import PaintkitCompositor

        self.progress.emit(10, 'Читаю рецепт War Paint…')
        defs = paintkit_defs.load(self.tf2_root)
        if defs is None:
            return False, 'В игре нет файла War Paint (proto_defs.vpd)'
        kit, item = paintkit_defs.find_item(defs, self.kit_id, self.item_def)
        if not (kit and item):
            return False, 'Этот War Paint не ложится на это оружие'
        generated = {}
        if self.generic:
            inputs = self._generic_inputs(defs, kit)
            if inputs is None:
                return False, 'У модели нет развёртки — War Paint положить некуда'
            generated = inputs.textures
            recipe = defs.recipe(kit, item, self.wear, forced=inputs.forced,
                                 strip_stickers=True)
        else:
            recipe = defs.recipe(kit, item, self.wear)
        if recipe is None:
            return False, 'Этот War Paint не ложится на это оружие'

        self.progress.emit(30, 'Наношу War Paint…')
        reader = GameVpkReader(self.vpks)
        try:
            game_loader = make_loader(reader, self.size)

            def loader(path: str, raw: bool = False):
                own = generated.get(path)
                return own if own is not None else game_loader(path, raw=raw)

            comp = PaintkitCompositor(loader, self.size, self.team)
            rgba = comp.compose(recipe, seed=self.seed)
            # Модель — та, на которую игра кладёт War Paint (items_game), а
            # если её не узнать — модель оружия приложения. У универсального
            # режима модель своя, и War Paint ложится на её главную карточку.
            mdl = (paintkit_defs.item_model_path(self.tf2_root, defs, self.item_def)
                   or self.mdl_path)
            if mdl and not self.generic:
                self.materials = paintable_materials(reader, mdl)
        finally:
            reader.close()
        if self.isInterruptionRequested():
            return False, 'Отменено'
        self.missing = list(comp.missing)
        os.makedirs(os.path.dirname(self.out_path) or '.', exist_ok=True)
        Image.fromarray(rgba, 'RGBA').save(self.out_path)
        logger.info(f'[paintkit] {kit.header.name} износ {self.wear} {self.team} '
                    f'сид {self.seed} → {self.out_path}')
        return True, self.out_path

    def _generic_inputs(self, defs, kit):
        """Альбедо, группы, износ и AO из самой модели (paintkit_generic)."""
        from PIL import Image

        from src.data import paintkit_defs
        from src.services import mesh_parts_service
        from src.services.paintkit_generic import build_inputs

        g = self.generic
        model = mesh_parts_service.load(g.get('obj_path', ''), g.get('cuts'), g.get('regions'))
        if model is None or not model.materials:
            return None
        card = g.get('card', '')
        # Карточка одноматериальной модели зовётся служебным ключом, а в OBJ
        # материал назван по SMD — берём единственный или самый большой.
        if card in model.materials:
            material = card
        else:
            material = max(model.materials,
                           key=lambda m: sum(p.uv_area for p in model.materials[m]))
        try:
            base = np.asarray(Image.open(g['base_png']).convert('RGBA'))
        except (OSError, KeyError, ValueError):
            base = np.full((self.size, self.size, 4), 160, np.uint8)
        layers, over_albedo = paintkit_defs.template_layers(defs, kit)
        return build_inputs(model, material, base, self.size, layers, over_albedo,
                            int(g.get('layout_seed') or 0))
