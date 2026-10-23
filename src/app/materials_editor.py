"""
Материал карточки: карты (самосвечение, отражение, нормаль, lightwarp,
phongwarp), настройки текстуры и правка VMT вручную

Своего состояния нет: карты и настройки живут в состоянии превью сеанса
(`preview.texture_maps` и др.), сюда - только как их показать, проверить
и записать. Какой материал правит карточка - `_card_key` сеанса

Доступ - `session().materials`; `api.py` зовёт его методы напрямую
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


class MaterialsEditor:
    """Карты материала и VMT карточки"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host

    def texture_maps(self, material: str = '') -> Dict[str, Any]:
        """Карты материала для показа в диалоге

        У мода из VPK это и карты из VMT самого мода (``{"mod": True,
        "preview": …}``) - они отмечены, а не пусты. Сохранённая запись
        важнее: снятая (``off``) не показывается, оставленная - с превью мода
        """
        key = self._host._card_key(material)
        mod = self._host.preview.mod_maps.get(key) or {}
        out = {map_id: dict(entry) for map_id, entry in mod.items()}
        for map_id, entry in (self._host.preview.texture_maps.get(key) or {}).items():
            if entry.get('off'):
                out.pop(map_id, None)
            elif entry.get('mod') and map_id in mod:
                out[map_id] = {**mod[map_id], **entry}
            else:
                out[map_id] = dict(entry)
        return out

    def set_texture_maps(self, material: str = '',
                         maps: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Записывает карты материала. Пустой набор снимает их совсем

        Присланное проверяется (``normalize_maps``): запись уходит в генератор
        VTF и в VMT, и мусорный ключ там превращается в сломанный материал.
        Полоска из конструктора (``generate``) рисуется здесь же в PNG - дальше
        она обычная картинка карты, и сборка о конструкторе не знает

        Карта мода, которой в присланном нет, сохраняется отметкой ``off``:
        сборка уберёт её из VMT. Без отметки «снял» не отличить от «не
        трогал» - и после перезапуска карта мода вернулась бы
        """
        from src.data.material_maps import MATERIAL_MAPS, normalize_maps

        if not getattr(self._host, '_mode', ''):
            return {'error': 'Сначала выберите предмет'}

        key = self._host._card_key(material)
        maps = {map_id: dict(entry) for map_id, entry in (maps or {}).items()
                if isinstance(entry, dict)}
        for map_id, entry in maps.items():
            name = (MATERIAL_MAPS.get(map_id) or {}).get('generator')
            if name and isinstance(entry.get('generate'), dict):
                entry['image'] = self._generated_png(name, entry['generate'])
        for map_id in self._host.preview.mod_maps.get(key) or {}:
            maps.setdefault(map_id, {'off': True})
        clean = normalize_maps(maps)
        with self._host._lock:
            if clean:
                self._host.preview.texture_maps[key] = clean
            else:
                self._host.preview.texture_maps.pop(key, None)
        self._host._autosave()
        return {'material': key, 'maps': clean}

    def _generated_png(self, name: str, params: Dict[str, Any]) -> str:
        """PNG карты из конструктора (lightwarp, phongwarp) - рядом с
        загрузками страницы (работа копирует его к себе, как любую картинку
        карты). Дальше это обычная картинка, сборка о конструкторе не знает"""
        import hashlib
        import json
        import tempfile
        from pathlib import Path

        from src.data.material_maps import generator

        module = generator(name)
        params = module.clean_params(params)
        digest = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]
        out = Path(tempfile.gettempdir()) / 'tf2sg_uploads' / f'{name}_{digest}.png'
        out.parent.mkdir(parents=True, exist_ok=True)
        return module.write_png(params, str(out), self._game_root())

    @staticmethod
    def _game_root() -> str:
        """Папка игры из настроек - без проверок tf2_paths: превью полоски
        дёргается на каждое движение ползунка, а основа нужна только для
        чтения VPK (нет игры - основа x/2)"""
        from src.config.app_config import AppConfig
        return (AppConfig.load_config().get('tf2_game_folder') or '').strip()

    def lightwarp_ramp(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Полоска конструктора для живого превью: 256 цветов [r, g, b] и
        она же точками"""
        from src.services import lightwarp

        params = lightwarp.clean_params(params or {})
        strip = lightwarp.ramp(params, self._game_root())
        # Точки той же полоски - для «Сделать точками»: любую основу со всеми
        # настройками можно дальше править руками
        return {'params': params, 'ramp': strip.tolist(), 'stops': lightwarp.to_stops(strip)}

    def map_preview(self, material: str = '', map_id: str = 'selfillum',
                    spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Картинки для превью карты материала: текстура материала, её альфа и
        сама карта - та же, что построит сборка (derive_effect_map /
        process_image / карта мода). Смешивает их страница по формуле шейдера

        `map`: самосвечение, отражение, маска обводки - L; Phong-карта - RGBA
        (R - размер блика); detail - RGBA в своём размере (она тайлится).
        `mask`: у Phong-карты «Авто» - где блестит (сборка кладёт её в альфу
        нормали). `env`: у отражения - шесть граней кубмапы строкой

        Не больше 256 px: превью, а не сборка. Имена по содержимому - браузер
        не покажет старую картинку из кэша
        """
        import hashlib
        import tempfile
        from pathlib import Path

        from PIL import Image

        from src.services.texture_service import TextureService

        key = self._host._card_key(material)
        tex = self._host.preview.textures.resolve_base(key)
        if not tex or not os.path.isfile(tex):
            # Без текстуры шар отражения и обводки всё равно показываем
            tex = None
            if map_id == 'selfillum':
                return {'error': 'У материала нет текстуры для превью'}
        spec = dict(spec or {})
        out = Path(tempfile.gettempdir()) / 'tf2sg_mapview'
        out.mkdir(parents=True, exist_ok=True)
        stamp = hashlib.sha1(repr((key, tex, tex and os.path.getmtime(tex), map_id, sorted(
            (k, str(v)) for k, v in spec.items()))).encode()).hexdigest()[:12]

        result = {'texture': '', 'alpha': '', 'map': '', 'mask': ''}
        size = None
        if tex:
            with Image.open(tex) as img:
                rgba = img.convert('RGBA')
            rgba.thumbnail((256, 256), Image.LANCZOS)
            size = rgba.size
            texture = out / f'tex_{stamp}.png'
            alpha = out / f'alpha_{stamp}.png'
            rgba.convert('RGB').save(texture)
            rgba.getchannel('A').save(alpha)
            result.update(texture=str(texture), alpha=str(alpha))

        kind = {'selfillum': 'selfillum', 'phongexp': 'phong'}.get(map_id, 'envmapmask')
        colour = map_id in ('phongexp', 'detail')
        thr = str(spec.get('threshold', '')).strip()
        thr = int(thr) if thr.isdigit() else None
        made = out / f'map_{stamp}.png'
        # Имя по входным данным, но не по содержимому карты мода или файла:
        # прошлый файл с тем же именем мог остаться от другого материала
        made.unlink(missing_ok=True)
        source = None
        if spec.get('derive') and tex:
            if map_id != 'detail':
                TextureService.derive_effect_map(str(texture), str(made), kind, size,
                                                 threshold=None if colour else thr)
            if map_id == 'phongexp':
                # Где блестит: сборка кладёт маску в альфу нормали
                # (VpkTextureBuilder: «Авто-блеск»), по яркости и порогу
                mask = out / f'mask_{stamp}.png'
                TextureService.derive_effect_map(str(texture), str(mask), 'envmapmask',
                                                 size, threshold=thr)
                result['mask'] = str(mask)
        elif spec.get('image') and os.path.isfile(spec['image']):
            source = spec['image']
        elif spec.get('mod'):
            source = ((self._host.preview.mod_maps.get(key) or {}).get(map_id) or {}).get('preview')
        if source and os.path.isfile(source):
            with Image.open(source) as img:
                pic = img.convert('RGBA' if colour else 'L')
            if map_id == 'detail' or not size:
                pic.thumbnail((256, 256), Image.LANCZOS)   # detail: своя развёртка × $detailscale
            else:
                pic = pic.resize(size, Image.LANCZOS)
            pic.save(made)
        if made.exists():
            with Image.open(made) as img:
                pic = img.convert('RGBA' if colour else 'L')
            if colour:
                # Альфа отдельно: браузер обнуляет цвет там, где альфа 0, а у
                # Phong-карты альфа - маска обводки, у detail она нужна режиму 2
                if map_id == 'detail':
                    alpha_map = out / f'map_alpha_{stamp}.png'
                    pic.getchannel('A').save(alpha_map)
                    result['map_alpha'] = str(alpha_map)
                pic = pic.convert('RGB')
            pic.save(made)
            result['map'] = str(made)
        if map_id == 'envmapmask':
            result.update(self._cubemap_strip(material, spec.get('cubemap') or 'keep'))
        return result

    def _cubemap_strip(self, material: str, choice: str) -> Dict[str, Any]:
        """Окружение отражения для превью: шесть граней кубмапы строкой
        (+X -X +Y -Y +Z -Z, как в VTF). `env_cubemap` - окружение карты, его
        в файлах нет: показываем студийный cubemap_specular001 (`stand_in`)"""
        import tempfile
        from pathlib import Path

        import numpy as np
        from PIL import Image

        from src.data.material_maps import CUBEMAPS
        from src.services import vmt_parse
        from src.services.game_vpk_reader import GameVpkReader
        from src.services.vtflib_wrapper import VTFLib

        name = CUBEMAPS.get(choice)
        if choice == 'keep':
            vmt = self.open_vmt(material)
            name = vmt_parse.parse(vmt.get('content') or '').path('$envmap') or ''
        stand_in = not name or name == 'env_cubemap'     # path() уже с прямыми слэшами
        if stand_in:
            name = CUBEMAPS['specular']
        out = Path(tempfile.gettempdir()) / 'tf2sg_mapview' / (
            'env_' + name.replace('/', '_') + '.png')
        if not out.exists():
            paths = self._host.tf2_paths()
            if 'error' in paths:
                return {'env': '', 'stand_in': stand_in}
            reader = GameVpkReader([paths['textures_vpk'], paths['misc_vpk']])
            try:
                data = reader.find_vtf_for_basetexture(name)
            finally:
                reader.close()
            if not data:
                return {'env': '', 'stand_in': stand_in}
            vtf = out.with_suffix('.vtf')
            vtf.write_bytes(data)
            try:
                faces = []
                for face in range(6):
                    raw, w, h = VTFLib.read_vtf_as_rgba(str(vtf), face)
                    faces.append(np.frombuffer(raw, np.uint8).reshape(h, w, 4)[..., :3])
                Image.fromarray(np.concatenate(faces, axis=1)).save(out)
            except Exception as exc:                       # noqa: BLE001
                logger.warning(f'[maps] кубмапа {name} не читается: {exc}')
                return {'env': '', 'stand_in': stand_in}
            finally:
                vtf.unlink(missing_ok=True)
        return {'env': str(out), 'stand_in': stand_in}

    @staticmethod
    def phongwarp_preview(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Градиент блика для живого превью - уменьшенный (64×64)"""
        from src.services import phongwarp

        params = phongwarp.clean_params(params or {})
        return {'params': params, 'image': phongwarp.preview(params)}

    def add_to_style(self, material: str = '') -> Dict[str, Any]:
        """Добавляет материал в активный стиль (пустой карточкой)"""
        with self._host._lock:
            ok = self._host.preview.add_to_style(material)
        if not ok:
            return {'error': 'В стиль можно добавить только материал модели'}
        self._host._autosave()
        return self._host.view_state()

    def drop_from_style(self, material: str = '') -> Dict[str, Any]:
        """Убирает материал из стиля - он вернётся к базовой текстуре"""
        with self._host._lock:
            self._host.preview.drop_from_style(material)
        self._host._autosave()
        return self._host.view_state()

    def texture_settings(self, material: str = '') -> Dict[str, Any]:
        """Свои настройки материала или пусто, если он собирается как все"""
        key = self._host._card_key(material)
        return {'material': key,
                'settings': dict(self._host.preview.texture_overrides.get(key, {}))}

    def set_texture_settings(self, material: str = '',
                             settings: Optional[Dict[str, Any]] = None
                             ) -> Dict[str, Any]:
        """
        Задаёт материалу свои настройки сборки, пустые - возврат к глобальным

        Страница присылает полный набор (разрешение, формат, флаги, опции):
        частичная запись потребовала бы знать здесь, что именно на ней сейчас
        показано, а показанное - уже отражение этого состояния
        """
        from src.data.texture_overrides import override_badge

        if not getattr(self._host, '_mode', ''):
            return {'error': 'Сначала выберите предмет'}

        key = self._host._card_key(material)
        clean = {k: v for k, v in (settings or {}).items()
                 if k in ('size', 'format', 'flags', 'options') and v is not None}
        with self._host._lock:
            if clean:
                self._host.preview.texture_overrides[key] = clean
            else:
                self._host.preview.texture_overrides.pop(key, None)
        self._host._autosave()
        return {'material': key, 'settings': clean,
                'badge': override_badge(clean)}

    def texture_badges(self) -> Dict[str, str]:
        """{материал: подпись} - у каких карточек свои настройки сборки"""
        from src.data.texture_overrides import override_badge
        return {mat: override_badge(ov)
                for mat, ov in self._host.preview.texture_overrides.items() if ov}

    def vmt_target(self, material: str = '') -> Any:
        """(ключ правки, ключ модели, имя материала) либо словарь с ошибкой"""
        from src.data.weapons import SPECIAL_MODES
        from src.services import vmt_source_service

        mode = getattr(self._host, '_mode', '')
        if not mode:
            return {'error': 'Сначала выберите предмет'}
        if mode == 'custom':
            # Мод из VPK: правится VMT самого мода (путь в архиве вместо
            # ключа оружия), правка - под ключом этого мода
            from src.services.edited_vmt_service import EditedVMTService
            card = self._host._card_key(material)
            vmt = self._host.preview.mod_vmts.get(card)
            if not (vmt and self._host._vpk_mod_path):
                return {'error': 'У этой текстуры в моде нет VMT'}
            return vmt, EditedVMTService.mod_key(self._host._vpk_mod_path, card)
        if mode in SPECIAL_MODES:
            return {'error': 'Для этого режима редактор VMT недоступен'}

        target = vmt_source_service.resolve_target(
            mode, hat_mdl=self._host.preview.weapon_key)
        if target is None:
            return {'error': 'Для этого режима редактор VMT недоступен'}

        weapon_key, _display = target
        # Ключ хранения правки - имя материала: у главного он совпадает с
        # texture_filename, который сборка и ищет
        return weapon_key, (self._host._card_key(material) or weapon_key)

    def _vmt_label(self, edit_key: str, material: str) -> str:
        """Имя материала для страницы - она шлёт его обратно при сохранении.
        У мода из VPK ключ хранения свой (EditedVMTService.mod_key), и
        вернувшись, он не находил карточку: «нет VMT»"""
        if getattr(self._host, '_mode', '') == 'custom':
            return self._host._card_key(material)
        return edit_key

    def open_vmt(self, material: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """
        Отдаёт текст VMT для правки: сохранённую версию либо игровой оригинал

        Оригинал возвращается всегда отдельным полем - по нему работает
        «вернуть как в игре», и без него сброс вернул бы саму правку
        """
        from src.services.edited_vmt_service import EditedVMTService

        target = self.vmt_target(material)
        if isinstance(target, dict):
            return target
        weapon_key, edit_key = target
        mode = getattr(self._host, '_mode', '')

        paths = self._host.tf2_paths()
        tf2_root = '' if 'error' in paths else paths['root']

        original = None
        edited_path = EditedVMTService.get_edited_vmt(edit_key)
        if edited_path and os.path.exists(edited_path):
            original = EditedVMTService.read_original_backup(edit_key)
            if original is None and tf2_root:
                original = self._vmt_original(mode, weapon_key, tf2_root, edit_key, lang)
            try:
                with open(edited_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError as exc:
                return {'error': f'не прочитать правку: {exc}'}
            return {'material': self._vmt_label(edit_key, material), 'content': content,
                    'original': original if original is not None else content,
                    'edited': True}

        if not tf2_root:
            return paths
        original = self._vmt_original(mode, weapon_key, tf2_root, edit_key, lang)
        if original is None:
            return {'error': f'Оригинальный VMT для «{edit_key}» не найден'}
        return {'material': self._vmt_label(edit_key, material), 'content': original,
                'original': original, 'edited': False}

    def _vmt_original(self, mode: str, weapon_key: str, tf2_root: str,
                      edit_key: str, lang: str) -> Optional[str]:
        """
        С чего начинается правка VMT материала

        У части, ставшей своим материалом, в игре VMT нет: она начинается с
        игрового VMT исходного. Правку исходного, какой та была при создании,
        материал части получил копией (PartsEditor._fork_vmt), поздние правки
        исходного его не касаются (src/services/part_materials.py)
        """
        from src.services import vmt_source_service

        if mode == 'custom':
            return self._mod_vmt_text(weapon_key)
        base = self._host.preview.textures.part_cards.get(edit_key)
        if base is not None:
            edit_key = self._host._card_key(base) or weapon_key
        if not tf2_root:
            return None
        return vmt_source_service.original_content(
            mode, weapon_key, tf2_root, edit_key, lang)

    def _mod_vmt_text(self, vmt_rel: str) -> Optional[str]:
        """VMT из архива показанного мода - оригинал для его редактора"""
        import vpk as vpklib
        try:
            data = vpklib.open(self._host._vpk_mod_path)[vmt_rel].read()
        except Exception as exc:                             # noqa: BLE001
            logger.warning(f'VMT мода не прочитан ({vmt_rel}): {exc}')
            return None
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.decode('cp1251', errors='replace')

    def save_vmt(self, material: str = '', content: str = '',
                 original: str = '', lang: str = 'ru') -> Dict[str, Any]:
        """Сохраняет правку VMT. Сломанный синтаксис не сохраняется"""
        from src.services import vmt_source_service

        target = self.vmt_target(material)
        if isinstance(target, dict):
            return target
        _weapon_key, edit_key = target

        ok, error, saved = vmt_source_service.save_edit(
            edit_key, content, original or None, lang)
        if not ok:
            return {'error': error}
        return {'material': self._vmt_label(edit_key, material), 'content': saved, 'edited': True}

    def save_vmt_all(self, material: str, content: str, before: str, original: str,
                     materials: List[str], bounds: Optional[dict] = None,
                     lang: str = 'ru') -> Dict[str, Any]:
        """Правка без шестерёнки: в этот материал и во все остальные

        Остальным уходит не текст, а разбор правки `before` -> `content`:
        эффекты собираются в каждом заново, ключи - без путей текстур
        (src/services/vmt_spread.py)
        """
        from src.services import vmt_spread

        main = self.save_vmt(material, content, original, lang)
        if 'error' in main:
            return main
        plan = vmt_spread.plan(before, content, original, bounds)
        updated, skipped = [], []
        here = self.vmt_target(material)
        for other in dict.fromkeys(materials):
            target = self.vmt_target(other)
            if plan.empty or isinstance(target, dict) or target == here:
                continue
            cur = self.open_vmt(other, lang)
            if 'error' in cur:
                skipped.append({'material': other, 'reason': cur['error']})
                continue
            text, problems = vmt_spread.apply_plan(plan, cur['content'], cur['original'], bounds)
            if problems:
                skipped.append({'material': cur['material'], 'reason': '; '.join(problems)})
            if text == cur['content']:
                continue
            res = self.save_vmt(other, text, cur['original'], lang)
            if 'error' in res:
                skipped.append({'material': cur['material'], 'reason': res['error']})
            else:
                updated.append(res['material'])
        main['spread'] = {'updated': updated, 'skipped': skipped, 'notes': plan.notes}
        return main

    def reset_vmt_all(self, materials: List[str]) -> Dict[str, Any]:
        """«Как в игре» без шестерёнки: правки снимаются у всех материалов"""
        done = [self.reset_vmt(m) for m in dict.fromkeys(materials)]
        return {'reset': [d['material'] for d in done if 'error' not in d]}

    def reset_vmt(self, material: str = '') -> Dict[str, Any]:
        """Удаляет правку: материал вернётся к игровому оригиналу"""
        from src.services.edited_vmt_service import EditedVMTService

        target = self.vmt_target(material)
        if isinstance(target, dict):
            return target
        _weapon_key, edit_key = target
        EditedVMTService.delete_edited_vmt(edit_key)
        return {'material': self._vmt_label(edit_key, material), 'edited': False}
