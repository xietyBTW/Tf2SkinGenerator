"""
Воркер спец-режимов: солдат умирает нужной смертью.

Крит и эффекты смерти — это не предмет, а то, как игрок выглядит в момент
гибели, и показывать их на кубиках-заглушке бессмысленно. Модель анимаций
класса хранит ровно те три смерти, которые нам нужны, — от выстрела в голову,
от удара в спину и от огня, — и играются они той же машинерией, что насмешка
([taunt_worker]): скелет персонажа, дорожки костей, один меш.

Что какому режиму досталось:

  * ``critHIT``    — выстрел в голову: крит-попадание и есть смертельный удар,
    а текстура крита висит билбордом над телом;
  * ``death_ice``  — удар в спину: лёд намораживается на труп, и смерть тут
    подходит любая тихая;
  * ``death_gold`` — тот же удар в спину: золотая статуя это застывшее тело;
  * ``death_fire`` — своя анимация горения.

Сигналы намеренно те же, что у насмешки: страница уже умеет показывать
анимированную сцену, и второй такой ветки в ней быть не должно.
"""

from __future__ import annotations

import tempfile
from typing import Optional

from src.services import model_decompile_service as mds
from src.services import viewmodel_animation
from src.services import weapon_anim_catalog as anim_catalog
from src.services.base_worker import BaseWorker, Signal
from src.services.game_vpk_reader import GameVpkReader
from src.services.material_resolver import MaterialResolver
from src.services.taunt_worker import body_smd, root_rotation
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Чью смерть показываем. Один класс на все режимы: анимации у классов
#: одинаковые по смыслу, а солдат — самый узнаваемый силуэт.
SCENE_CLASS = 'soldier'

#: Режимы, где игра ЗАМОРАЖИВАЕТ тело. Спайсикл и золотая сковорода не дают
#: жертве упасть тряпичной куклой: она доигрывает свою анимацию смерти и
#: застывает в этой позе статуей («always perform their unique backstab death
#: animation, causing them to freeze in a pose» — вики TF2). Статуя и есть то,
#: на что человек здесь кладёт текстуру, поэтому показать её надо обязательно.
FROZEN = ('death_ice', 'death_gold')

#: Сколько держать застывшую позу, прежде чем показать смерть заново. В игре
#: статуя стоит до конца раунда; в превью нужен и сам удар, и результат.
STATUE_HOLD = 3.0

#: Две ручки заморозки, выверенные по игре. Тело замирает ПОСРЕДИ падения:
#: статуя стоит там, где жертва была в тот миг, а доигранная до конца
#: анимация вместо неё кладёт солдата на землю. Поэтому показываем движение
#: медленнее его тридцати кадров в секунду (`DEATH_SECONDS`) и обрываем
#: раньше конца (`FREEZE_AT`). Числа подбираются глазами по игре, здесь.
DEATH_SECONDS = 2.4
FREEZE_AT = 1.8

#: Режим → последовательность из модели анимаций класса.
SEQUENCES = {
    'critHIT': 'primary_death_headshot',
    'death_ice': 'primary_death_backStab',
    'death_gold': 'primary_death_backStab',
    # Горение — не смерть: игрок стоит с оружием в руках и вздрагивает от
    # каждого тика урона. Стойка и вздрагивание в игре лежат отдельно.
    'death_fire': 'stand_PRIMARY',
}

#: Разностный слой поверх последовательности. `a_flinch01` — это вздрагивание
#: от урона (`ACT_MP_GESTURE_FLINCH_CHEST`), и в SMD у него нули вместо поз:
#: сам по себе он ничего не показывает, а поверх стойки даёт то самое
#: подёргивание горящего.
LAYERS = {
    'death_fire': 'a_flinch01',
}


class DeathScenePreviewWorker(BaseWorker):
    """Готовит сцену смерти и текстуры персонажа к ней."""

    #: Сцена с дорожками костей — тем же словарём, что у вида от первого лица.
    animated_ready = Signal(object)
    #: {имя материала: PNG} — текстуры самого персонажа.
    multi_material = Signal(object)
    #: Как рисовать материалы (прозрачность, блик) — см. vmt_render.
    render_hints = Signal(object)
    progress = Signal(str)
    failed = Signal(str)

    _PROGRESS = {
        'ru': {
            'player': 'Загрузка модели класса…',
            'anims': 'Загрузка анимаций класса…',
            'scene': 'Сборка сцены…',
            'texture': 'Загрузка текстур…',
            'no_models': 'Модель персонажа не найдена',
            'no_anim': 'Анимация смерти не найдена',
            'scene_error': 'Не удалось собрать сцену',
        },
        'en': {
            'player': 'Loading the class model…',
            'anims': 'Loading class animations…',
            'scene': 'Building the scene…',
            'texture': 'Loading textures…',
            'no_models': 'The class model was not found',
            'no_anim': 'The death animation was not found',
            'scene_error': 'Failed to build the scene',
        },
    }

    def __init__(self, mode: str, misc_vpk_path: str, textures_vpk_path: str,
                 lang: str = 'en', parent=None):
        super().__init__(parent)
        self.mode = mode
        self.misc_vpk_path = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])
        self._preview_dir: Optional[str] = None

    def run(self) -> None:
        reader = GameVpkReader([self.textures_vpk_path, self.misc_vpk_path])
        try:
            self._preview_dir = tempfile.mkdtemp(prefix='tf2sg_death_')

            self.progress.emit(self._p['player'])
            player_dir = self._decompile(f'__player_{SCENE_CLASS}',
                                         f'models/player/{SCENE_CLASS}.mdl')
            if player_dir is None:
                return
            player_ref = body_smd(player_dir)
            if not player_ref:
                self.failed.emit(self._p['no_models'])
                return

            self.progress.emit(self._p['anims'])
            anims_dir = self._decompile(
                f'__anims_full_{SCENE_CLASS}',
                f'models/player/{SCENE_CLASS}_animations.mdl')
            if anims_dir is None:
                return
            sequence, layer = self._sequence(anims_dir)
            if sequence is None:
                self.failed.emit(self._p['no_anim'])
                return
            if self.isInterruptionRequested():
                return

            self.progress.emit(self._p['scene'])
            scene = self._build(player_dir, player_ref, anims_dir, sequence,
                                layer)
            if not scene:
                self.failed.emit(self._p['scene_error'])
                return
            if self.isInterruptionRequested():
                return

            self.progress.emit(self._p['texture'])
            self._emit_scene(reader, scene, player_dir)
            logger.info(f"[смерть] {self.mode}: {sequence.name}, "
                        f"{scene['clip']['duration']:.2f} с")

        except mds.DecompileError as exc:
            logger.warning(f"[смерть] {self.mode}: {exc}")
            self.failed.emit(str(exc))
        except Exception as exc:                              # noqa: BLE001
            logger.error(f"[смерть] {self.mode}: {exc}", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            reader.close()

    # ── Шаги ──────────────────────────────────────────────────────────────── #

    def _decompile(self, cache_key: str, mdl: str) -> Optional[str]:
        result = mds.ensure_decompiled(
            cache_key, self.misc_vpk_path, [mdl],
            cancelled=self.isInterruptionRequested,
        )
        if result is None:
            logger.warning(f"[смерть] не достали модель {mdl}")
            self.failed.emit(self._p['no_models'])
            return None
        return result.directory

    def _sequence(self, anims_dir: str):
        """(последовательность, разностный слой) для этого режима."""
        catalog = anim_catalog.load(anims_dir)
        if catalog is None:
            return None, ''
        found = catalog.by_name.get(SEQUENCES.get(self.mode, ''))
        if found is None or not found.exists:
            return None, ''
        layer = catalog.by_name.get(LAYERS.get(self.mode, ''))
        return found, (layer.smd_path if layer is not None and layer.exists
                       else '')

    def _rate(self, sequence) -> float:
        """Частота показа: у замороженных смертей движение растянуто.

        Кадры лежат на тридцати в секунду — всё падение проходит за 1.23 с, а
        в игре тело замирает ближе к двум и ещё в движении. Растягиваем до
        `DEATH_SECONDS`, чтобы обрыв на `FREEZE_AT` пришёлся на середину.
        """
        if self.mode not in FROZEN:
            return sequence.fps
        with open(sequence.smd_path, encoding='utf-8', errors='replace') as f:
            frames = sum(1 for line in f if line.strip().startswith('time'))
        return (frames - 1) / DEATH_SECONDS if frames > 1 else sequence.fps

    def _build(self, player_dir: str, player_ref: str, anims_dir: str,
               sequence, layer_smd: str = ''):
        from src.services.viewmodel_worker import _default_body_parts

        return viewmodel_animation.build_scene(
            arms_ref_smd=player_ref,
            # У пиро тело почти целиком в бодигруппах, и у солдата так же
            # лежат ранец и каска: без них в кадре половина персонажа.
            arms_extra_smds=_default_body_parts(player_dir, player_ref),
            weapon_ref_smd='',
            anim_smd=sequence.smd_path,
            clip_name=sequence.name,
            fps=self._rate(sequence),
            loop=sequence.loop,
            anim_layer_smd=layer_smd,
            clip_hold=STATUE_HOLD if self.mode in FROZEN else 0.0,
            clip_cut=FREEZE_AT if self.mode in FROZEN else 0.0,
            root_rotation_x=root_rotation(player_dir),
            # Кадры и меш в разных осях: модель класса экспортирована
            # `$upaxis Y`, модель её анимаций — обычной Z-вверх.
            anim_rotation_x=root_rotation(anims_dir) - root_rotation(player_dir),
        )

    def _emit_scene(self, reader, scene: dict, player_dir: str) -> None:
        """Текстуры персонажа и сама сцена.

        У эффекта смерти своих текстур персонаж не получает: лёд, золото и
        огонь в игре ЗАМЕНЯЮТ его материалы целиком, и одна картинка ложится
        на всё тело. Доставать под неё родные текстуры — лишняя работа и гонка
        за то, какая ляжет последней.
        """
        from src.data.weapons import VTF_ONLY_SPECIAL_MODES
        from src.services.viewmodel_worker import _cdmaterials, _scene_materials

        if self.mode in VTF_ONLY_SPECIAL_MODES:
            self.animated_ready.emit(scene)
            return

        # Реквизита в сцене нет, персонаж идёт «руками» — его материалы
        # приходят вторым списком.
        _weapon_names, names = _scene_materials(scene)
        resolver = MaterialResolver(reader, self._preview_dir)
        cdmaterials = _cdmaterials(player_dir)
        textures = {name: png for name, png
                    in resolver.texture_map(names, cdmaterials).items() if png}

        # Свойства материалов — ДО сцены: вьювер применит их по мере прихода
        # картинок, а не пересоберёт материалы дважды.
        self.render_hints.emit(resolver.render_map(names, cdmaterials))
        self.animated_ready.emit(scene)
        if textures:
            self.multi_material.emit(textures)
        missing = [n for n in names if n not in textures]
        if missing:
            logger.warning(f"[смерть] без текстуры остались материалы: {missing}")
