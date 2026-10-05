"""
Воркер сцены «На модели»: персонаж класса в игровой стойке, на нём — шапка.

Шапку в игре не видят висящей в пустоте: она на голове, а персонаж держит
оружие. Сцена собирается той же `viewmodel_animation.build_scene`, что насмешка:
«руки» — это персонаж, «оружие» — шапка (её кости сливаются с одноимёнными
костями персонажа, как делает игра, EF_BONEMERGE), а стоковое оружие слота —
носитель: в кадре, но не в правке.

Что откуда:
  * модель класса и модель его анимаций — общий кэш декомпиляции, те же ключи,
    что у насмешки (`__player_*`, `__anims_full_*`), — разобранное один раз
    годится обеим сценам;
  * стойка — последовательность по активности `ACT_MP_STAND_<слот>`;
  * оружие слота — стоковое из items_game ([stock_loadout]);
  * текстуры — MaterialResolver по `$cdmaterials` каждой из трёх моделей.

Сигналы — как у TauntPreviewWorker: страница уже умеет показывать такую сцену.
"""

from __future__ import annotations

import os
import tempfile
from typing import Dict, Optional

from src.data import stock_loadout
from src.data.viewmodel_anims import CLASS_MODEL_STEM
from src.services import anim_store
from src.services import model_decompile_service as mds
from src.services import smd_service, viewmodel_animation
from src.services import weapon_anim_catalog as anim_catalog
from src.services.base_worker import BaseWorker, Signal
from src.services.game_vpk_reader import GameVpkReader
from src.services.material_resolver import MaterialResolver
from src.services.taunt_worker import body_smd, root_rotation
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class HatScenePreviewWorker(BaseWorker):
    """Готовит сцену «персонаж в стойке с шапкой» и текстуры к ней."""

    animated_ready = Signal(object)
    multi_material = Signal(object)
    #: Материалы ШАПКИ: только их человек правит; персонаж и оружие — фон.
    editable_materials = Signal(object)
    render_hints = Signal(object)
    #: Классы, которые носят эту шапку.
    classes_available = Signal(object)
    #: Слоты стокового оружия выбранного класса и какой из них показан.
    slots_available = Signal(object)
    progress = Signal(str)
    failed = Signal(str)

    _PROGRESS = {
        'ru': {
            'hat': 'Загрузка шапки…',
            'player': 'Загрузка модели класса…',
            'anims': 'Загрузка анимаций класса…',
            'anims_slow': 'Распаковка анимаций класса (первый раз — до полуминуты)…',
            'weapon': 'Загрузка оружия…',
            'scene': 'Сборка сцены…',
            'texture': 'Загрузка текстур…',
            'no_models': 'Модели для сцены не найдены',
            'no_stance': 'Стойка класса не найдена',
            'scene_error': 'Не удалось собрать сцену',
        },
        'en': {
            'hat': 'Loading the hat…',
            'player': 'Loading the class model…',
            'anims': 'Loading class animations…',
            'anims_slow': 'Unpacking class animations (first time, up to half a minute)…',
            'weapon': 'Loading the weapon…',
            'scene': 'Building the scene…',
            'texture': 'Loading textures…',
            'no_models': 'Models for the scene were not found',
            'no_stance': 'Class stance not found',
            'scene_error': 'Failed to build the scene',
        },
    }

    def __init__(self, hat_models: Dict[str, str], misc_vpk_path: str,
                 textures_vpk_path: str, tf2_root: str = "",
                 tf2_class: str = "", slot: str = "", lang: str = 'en',
                 hidden_bodygroups: Optional[Dict[str, int]] = None,
                 parent=None):
        super().__init__(parent)
        #: Что шапка прячет у персонажа ({бодигруппа: вариант}) — каска
        #: солдата под шапкой на голову. Без этого она торчала сквозь шапку.
        self.hidden_bodygroups = dict(hidden_bodygroups or {})
        #: {класс: модель шапки}; у одномодельной шапки модель у всех одна.
        #: Путь как есть: он же ключ кэша декомпиляции у превью шапки.
        self.hat_models = {c.lower(): m for c, m in (hat_models or {}).items() if m}
        self.misc_vpk_path = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self.tf2_root = tf2_root
        self.tf2_class = (tf2_class or '').lower()
        self.slot = (slot or '').lower()
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])
        self._preview_dir: Optional[str] = None

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
        reader = GameVpkReader([self.textures_vpk_path, self.misc_vpk_path])
        try:
            self._preview_dir = tempfile.mkdtemp(prefix='tf2sg_wear_')
            classes = [c for c in CLASS_MODEL_STEM if c in self.hat_models]
            self.classes_available.emit(classes)
            if not classes:
                self.failed.emit(self._p['no_models'])
                return
            cls = self.tf2_class if self.tf2_class in classes else classes[0]

            weapons = stock_loadout.loadout(cls, self.tf2_root)
            weapon = next((w for w in weapons if w.slot == self.slot),
                          weapons[0] if weapons else None)
            self.slots_available.emit({'slots': [w.slot for w in weapons],
                                       'slot': weapon.slot if weapon else '',
                                       'tf2_class': cls})

            self.progress.emit(self._p['hat'])
            hat_mdl = self.hat_models[cls]
            # Ключ — путь модели, как у превью шапки: распакованное там
            # берётся отсюда же, без второго Crowbar.
            hat_dir = self._decompile(hat_mdl, hat_mdl)
            if not hat_dir:
                return
            hat_ref = body_smd(hat_dir) or smd_service.find_reference_smd(
                hat_dir, os.path.basename(hat_mdl).removesuffix('.mdl'))

            self.progress.emit(self._p['player'])
            stem = CLASS_MODEL_STEM[cls]
            player_dir = self._decompile(f'__player_{cls}', f'models/player/{stem}.mdl')
            player_ref = body_smd(player_dir) if player_dir else ''
            if not (hat_ref and player_ref):
                self.failed.emit(self._p['no_models'])
                return

            self.progress.emit(self._p['anims'])
            sequence, anim_rotation = self._stance_of(cls, stem, weapon, weapons)
            if sequence is None:
                self.failed.emit(self._p['no_stance'])
                return

            weapon_ref, weapon_dir = '', ''
            if weapon and weapon.model:
                self.progress.emit(self._p['weapon'])
                weapon_dir = self._decompile(f'__stock_{cls}_{weapon.slot}',
                                             weapon.model) or ''
                weapon_ref = (body_smd(weapon_dir) or smd_service.find_reference_smd(
                    weapon_dir, os.path.basename(weapon.model).removesuffix('.mdl'))
                    if weapon_dir else '')
            if self.isInterruptionRequested():
                return

            self.progress.emit(self._p['scene'])
            from src.services.viewmodel_worker import _default_body_parts
            scene = viewmodel_animation.build_scene(
                arms_ref_smd=player_ref,
                arms_extra_smds=_default_body_parts(player_dir, player_ref,
                                                    self.hidden_bodygroups),
                weapon_ref_smd=hat_ref,
                # Оружие в руке — фон сцены: видно, но не правится.
                weapon_carrier_smd=weapon_ref or '',
                anim_smd=sequence.smd_path,
                clip_name=sequence.name,
                fps=sequence.fps,
                loop=True,
                # Шапку игра надевает целиком, по именам костей.
                merge_by_name=True,
                root_rotation_x=root_rotation(player_dir),
                anim_rotation_x=anim_rotation - root_rotation(player_dir),
            )
            if not scene:
                self.failed.emit(self._p['scene_error'])
                return
            if self.isInterruptionRequested():
                return

            self.progress.emit(self._p['texture'])
            self._emit_scene(reader, scene, (hat_dir, weapon_dir, player_dir))
            logger.info(f"[wear] {os.path.basename(hat_mdl)}: класс {cls}, "
                        f"слот {weapon.slot if weapon else '—'}, стойка {sequence.name}")

        except mds.DecompileError as exc:
            logger.warning(f"[wear] {exc}")
            self.failed.emit(str(exc))
        except Exception as exc:                              # noqa: BLE001
            logger.error(f"[wear] {exc}", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            reader.close()

    # ── Шаги ──────────────────────────────────────────────────────────────── #

    def _decompile(self, cache_key: str, mdl: str, slow: str = '') -> Optional[str]:
        """Папка распакованной модели; `slow` — подпись на случай, когда
        Crowbar и правда пошёл (из кэша это мгновенно)."""
        def stage(step) -> None:
            if slow and step is mds.Stage.DECOMPILING:
                self.progress.emit(self._p[slow])

        result = mds.ensure_decompiled(
            cache_key, self.misc_vpk_path, [mdl],
            cancelled=self.isInterruptionRequested, on_progress=stage,
        )
        if result is None:
            logger.warning(f"[wear] не достали модель {mdl}")
            self.failed.emit(self._p['no_models'])
            return None
        return result.directory

    def _stance_of(self, cls: str, stem: str, weapon, weapons):
        """
        (стойка слота, поворот модели её анимаций) или (None, 0.0).

        Из своей копии (anim_store), иначе из распаковки модели анимаций
        класса — тогда в копию ложатся стойки ВСЕХ слотов класса: смена
        оружия на сцене дальше обходится без Crowbar, даже когда 150 МБ
        распаковки вытеснит кэш декомпиляции.
        """
        want = (weapon.anim if weapon else 'MELEE').upper()
        stored = anim_store.get(f'stand/{cls}/{want}', self.misc_vpk_path)
        if stored:
            return stored
        anims_dir = self._decompile(f'__anims_full_{cls}',
                                    f'models/player/{stem}_animations.mdl', slow='anims_slow')
        if not anims_dir:
            return None, 0.0
        rotation = root_rotation(anims_dir)
        found = None
        for anim in dict.fromkeys([want, *((w.anim or 'MELEE').upper() for w in weapons)]):
            sequence = self._stance(anims_dir, anim)
            if sequence is not None:
                kept = anim_store.put(f'stand/{cls}/{anim}', self.misc_vpk_path,
                                      sequence, rotation)
                found = found or (kept if anim == want else None)
        return found, rotation

    @staticmethod
    def _stance(anims_dir: Optional[str], anim: str):
        """Стойка слота: по активности, по имени, в крайнем случае — любая."""
        catalog = anim_catalog.load(anims_dir) if anims_dir else None
        if catalog is None:
            return None
        anim = anim.upper()
        for key in (anim, 'MELEE', 'PRIMARY'):
            seq = (catalog.by_activity.get(f'ACT_MP_STAND_{key}')
                   or catalog.by_name.get(f'stand_{key}'))
            if seq is not None and seq.exists:
                return seq
        return None

    def _emit_scene(self, reader, scene: dict, dirs) -> None:
        """Текстуры всех трёх моделей сцены и сама сцена.

        Имя материала у шапки, оружия и персонажа своё, а искать его надо по
        `$cdmaterials` той модели, откуда он: пробуем по очереди, найденное
        второй раз не ищем.
        """
        from src.services.viewmodel_worker import _cdmaterials, _scene_materials

        resolver = MaterialResolver(reader, self._preview_dir)
        weapon_names, player_names = _scene_materials(scene)
        names = [*weapon_names, *player_names]
        textures: dict = {}
        hints: dict = {}
        for directory in dirs:
            left = [n for n in names if n not in textures]
            if not directory or not left:
                continue
            cdmaterials = _cdmaterials(directory)
            textures.update({n: png for n, png
                             in resolver.texture_map(left, cdmaterials).items() if png})
            hints.update(resolver.render_map(left, cdmaterials))

        self.render_hints.emit(hints)
        self.animated_ready.emit(scene)
        self.editable_materials.emit(list(scene.get('weaponMaterials') or []))
        if textures:
            self.multi_material.emit(textures)
        missing = [n for n in names if n not in textures]
        if missing:
            logger.warning(f"[wear] без текстуры остались материалы: {missing}")
