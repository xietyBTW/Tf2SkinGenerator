"""
Воркер насмешки: персонаж играет тонт с реквизитом.

Задача та же, что у вида от первого лица, только вместо рук — весь персонаж:
скелет один (модель класса), а реквизит подвешен к его костям `prop_bone…` по
совпадению имён. Поэтому сцену собирает та же `viewmodel_animation.build_scene`
— в ней «руки» это персонаж, а «оружие» реквизит.

Что откуда:
  * класс и последовательность — из items_game ([taunt_scenes]);
  * модель класса, модель анимаций и сам реквизит — через общий кэш
    декомпиляции ([model_decompile_service]);
  * последовательность по имени — из QC модели анимаций ([weapon_anim_catalog]);
  * текстуры обеих частей — MaterialResolver по `$cdmaterials` каждой модели.

Отдельный случай — реквизит, которому персонаж не нужен: у танка водитель сидит
неподвижно, а едет сам танк своей анимацией. Тогда в сцене остаётся один
реквизит, и ведёт его собственный скелет.

Сигналы намеренно повторяют ViewmodelPreviewWorker: страница уже умеет
показывать анимированную сцену, и второй такой ветки в ней быть не должно.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import replace
from typing import Optional

from src.data import taunt_scenes
from src.data.viewmodel_anims import CLASS_MODEL_STEM
from src.services import model_decompile_service as mds
from src.services import smd_service, viewmodel_animation, viewmodel_pose
from src.services import weapon_anim_catalog as anim_catalog
from src.services.base_worker import BaseWorker, Signal
from src.services.game_vpk_reader import GameVpkReader
from src.services.material_resolver import MaterialResolver
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Ось «вверх» из QC. У персонажей стоит `$upaxis Y` — их SMD уже Y-вверх, и
#: общий поворот корня укладывал бы такую сцену набок.
_UPAXIS = re.compile(r'^\s*\$upaxis\s+(\w+)', re.M | re.I)

#: Меш модели из QC: `$model "scout" "scout_morphs_low.smd"`.
_MODEL_SMD = re.compile(r'^\s*\$model\s+"[^"]*"\s+"([^"]+\.smd)"', re.M | re.I)


def qc_text(directory: str) -> str:
    """Текст QC из папки декомпиляции (первый файл) или пусто."""
    names = [n for n in sorted(os.listdir(directory or '.')) if n.endswith('.qc')]
    if not names:
        return ''
    try:
        return open(os.path.join(directory, names[0]),
                    encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


def root_rotation(directory: str) -> float:
    """Поворот корня сцены для модели из этой папки.

    `$upaxis Y` — модель уже в осях вьювера, поворачивать нечего. Иначе это
    обычная Source-модель с Z вверх, и её разворачивает общий поворот.
    """
    found = _UPAXIS.search(qc_text(directory))
    if found and found.group(1).upper() == 'Y':
        return 0.0
    return viewmodel_animation.ROOT_ROTATION_X


#: Доля костей с ненулевой позицией, при которой кадр считается настоящей
#: позой. У заглушки нули у всех, кроме таза, — то есть около одной сотой.
_POSED = 0.5


def has_motion(smd_path: str) -> bool:
    """
    Настоящая ли это анимация, а не заглушка.

    Насмешку Valve хранит двумя-тремя частями: сама последовательность бывает
    пустой (крутится один таз), а движение лежит рядом — в `layer_<имя>` у
    медика, в `<имя>interior` у гитариста. Имя правило не даёт, зато даёт
    содержимое: в настоящей позе у костей стоят их смещения от родителя, а в
    заглушке нули. Смотрим ПЕРВЫЙ кадр — читать файл целиком незачем.
    """
    rows = moving = 0
    try:
        with open(smd_path, encoding='utf-8', errors='replace') as f:
            started = frame = False
            for line in f:
                text = line.strip()
                if text == 'skeleton':
                    started = True
                    continue
                if not started:
                    continue
                if text.startswith('time'):
                    if frame:
                        break               # кадр закончился
                    frame = True
                    continue
                if text == 'end':
                    break
                parts = text.split()
                if len(parts) == 7 and parts[0].isdigit():
                    rows += 1
                    if any(abs(float(v)) > 1e-6 for v in parts[1:4]):
                        moving += 1
    except (OSError, ValueError):
        return False
    return bool(rows) and moving / rows >= _POSED


def hidden_ranges(events, fps: float):
    """Секунды, когда реквизита в кадре нет, по событиям AE_WPN_HIDE/UNHIDE.

    События описывают то, что персонаж держит в руке: медик прячет снимок за
    пазухой, достаёт его на 23-м кадре и убирает на 166-м. Без них реквизит
    висел бы в руке всю насмешку.

    Скрывать по одному лишь HIDE нельзя: у обычных насмешек он прячет ОРУЖИЕ,
    которого в сцене и так нет, а реквизит виден с первого кадра — такая
    последовательность спрятала бы его целиком. Поэтому правило действует
    только там, где есть и обратное событие.
    """
    if not any(hidden is False for _, hidden in events):
        return []
    rate = float(fps) or 30.0
    ranges, start = [], None
    for frame, hidden in events:
        if hidden and start is None:
            start = frame / rate
        elif not hidden and start is not None:
            ranges.append([start, frame / rate])
            start = None
    if start is not None:
        ranges.append([start, None])          # до конца клипа
    return ranges


def body_smd(directory: str) -> str:
    """
    Меш персонажа — по `$model` из QC.

    Общий `find_reference_smd` здесь не годится: он выбирает по имени файла, а
    в папке класса лежат и `soldier_rocket.smd`, и `demo_smiley.smd`, и они
    выигрывают у настоящего `soldier_morphs_low.smd` длиной имени. В сцену
    вместо персонажа попадала ракета.
    """
    found = _MODEL_SMD.search(qc_text(directory))
    if not found:
        return ''
    smd = os.path.join(directory, found.group(1).replace('\\', os.sep))
    return smd if os.path.isfile(smd) else ''


class TauntPreviewWorker(BaseWorker):
    """Готовит анимированную сцену насмешки и текстуры к ней."""

    #: Сцена с дорожками костей — тем же словарём, что у вида от первого лица.
    animated_ready = Signal(object)
    #: {имя материала: PNG} — и персонаж, и реквизит.
    multi_material = Signal(object)
    #: Материалы РЕКВИЗИТА: только их человек вправе перекрашивать.
    editable_materials = Signal(object)
    #: Как рисовать материалы (прозрачность, блик) — см. vmt_render.
    render_hints = Signal(object)
    #: Кто ещё умеет эту насмешку: список классов для выбора.
    classes_available = Signal(object)
    progress = Signal(str)
    failed = Signal(str)

    _PROGRESS = {
        'ru': {
            'prop': 'Загрузка реквизита…',
            'player': 'Загрузка модели класса…',
            'anims': 'Загрузка анимаций класса…',
            'scene': 'Сборка сцены…',
            'texture': 'Загрузка текстур…',
            'no_taunt': 'Для этого реквизита насмешка не найдена',
            'no_models': 'Модели для насмешки не найдены',
            'scene_error': 'Не удалось собрать сцену',
        },
        'en': {
            'prop': 'Loading the prop…',
            'player': 'Loading the class model…',
            'anims': 'Loading class animations…',
            'scene': 'Building the scene…',
            'texture': 'Loading textures…',
            'no_taunt': 'No taunt found for this prop',
            'no_models': 'Models for the taunt were not found',
            'scene_error': 'Failed to build the scene',
        },
    }

    def __init__(self, prop_key: str, prop_mdl: str, misc_vpk_path: str,
                 textures_vpk_path: str, tf2_root: str = "",
                 tf2_class: str = "", lang: str = 'en', parent=None):
        super().__init__(parent)
        self.prop_key = prop_key
        self.prop_mdl = (prop_mdl or '').replace('\\', '/').lower()
        self.misc_vpk_path = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self.tf2_root = tf2_root
        #: Чей тонт показывать. Пусто — первый класс, который его умеет.
        self.tf2_class = (tf2_class or '').lower()
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])
        self._preview_dir: Optional[str] = None
        #: Папка декомпиляции модели анимаций — из неё взята выбранная
        #: последовательность. Нужна, чтобы узнать её оси.
        self._anims_dir: str = ''

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
        reader = GameVpkReader([self.textures_vpk_path, self.misc_vpk_path])
        try:
            self._preview_dir = tempfile.mkdtemp(prefix='tf2sg_taunt_')

            uses = taunt_scenes.uses(self.prop_mdl, self.tf2_root)
            classes = [c for c in CLASS_MODEL_STEM if c in uses]
            self.classes_available.emit(classes)

            tf2_class = self.tf2_class if self.tf2_class in uses else (
                classes[0] if classes else
                # items_game знает не про всякий реквизит; у части имя модели
                # само называет класс и совпадает с именем последовательности.
                taunt_scenes.class_from_prop(self.prop_mdl))
            prop_mdl, scene_stem = uses.get(tf2_class, (self.prop_mdl, ''))

            self.progress.emit(self._p['prop'])
            prop_dir = self._decompile(f'__prop_{self.prop_key}_{tf2_class}',
                                       prop_mdl)
            if prop_dir is None:
                return
            # Меш реквизита берём из `$model` его QC. Общий поиск по имени
            # здесь спотыкается: он отбрасывает файлы, в имени которых есть
            # «anim», а `balloon_animal_pyro.smd` — это надувной ЗВЕРЬ.
            prop_ref = body_smd(prop_dir) or smd_service.find_reference_smd(
                prop_dir, os.path.basename(prop_mdl).removesuffix('.mdl'))
            if not prop_ref:
                self.failed.emit(self._p['no_models'])
                return

            sequence = player_ref = None
            if tf2_class:
                player_ref, sequence = self._player_and_sequence(
                    tf2_class, scene_stem)
                if self.isInterruptionRequested():
                    return

            if sequence is None:
                # Персонажу играть нечего — показываем реквизит своей
                # анимацией (танк едет сам).
                sequence = self._own_sequence(prop_dir)
                player_ref = None
            if sequence is None:
                self.failed.emit(self._p['no_taunt'])
                return

            self.progress.emit(self._p['scene'])
            try:
                scene = self._build(player_ref, prop_ref, prop_dir, sequence,
                                    tf2_class, self._anims_dir)
            except viewmodel_pose.NotHeldInHands:
                # Реквизит не держат в руках: стенд, стул и машинка стоят в
                # мире, и с костями персонажа у них общего ничего. Зато у
                # таких почти всегда есть своя анимация — её и показываем.
                own = self._own_sequence(prop_dir)
                if own is None:
                    self.failed.emit(self._p['no_taunt'])
                    return
                logger.info(f"[taunt] {self.prop_key}: в руках не держат — "
                            f"своя анимация {own.name}")
                sequence, player_ref = own, None
                scene = self._build(None, prop_ref, prop_dir, sequence,
                                    tf2_class)
            if not scene:
                self.failed.emit(self._p['scene_error'])
                return
            if self.isInterruptionRequested():
                return

            self.progress.emit(self._p['texture'])
            self._emit_scene(reader, scene, prop_dir,
                             self._player_dir(tf2_class) if player_ref else '')
            logger.info(f"[taunt] {self.prop_key}: класс {tf2_class or '—'}, "
                        f"последовательность {sequence.name}")

        except mds.DecompileError as exc:
            logger.warning(f"[taunt] {self.prop_key}: {exc}")
            self.failed.emit(str(exc))
        except Exception as exc:                              # noqa: BLE001
            logger.error(f"[taunt] {self.prop_key}: {exc}", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            reader.close()

    # ── Шаги ──────────────────────────────────────────────────────────────── #

    def _build(self, player_ref, prop_ref: str, prop_dir: str, sequence,
               tf2_class: str, anims_dir: str = ''):
        """Сцена: персонаж с реквизитом либо один реквизит.

        Оси задаёт та модель, что ведёт сцену: у персонажа `$upaxis Y`, у
        мирового реквизита (танк, стенд) обычный Source Z-вверх.
        """
        from src.services.viewmodel_worker import _default_body_parts

        driver_dir = self._player_dir(tf2_class) if player_ref else prop_dir
        # У пиро тело почти целиком лежит в бодигруппах: в `$model` остаётся
        # семикилобайтная заглушка, и без них в кадре была бы пустота.
        extra = _default_body_parts(driver_dir, player_ref or prop_ref)
        return viewmodel_animation.build_scene(
            arms_ref_smd=player_ref or prop_ref,
            arms_extra_smds=extra,
            weapon_ref_smd=prop_ref if player_ref else '',
            anim_smd=sequence.smd_path,
            clip_name=sequence.name,
            fps=sequence.fps,
            loop=sequence.loop,
            editable_mats=None if player_ref else self._mats(prop_ref),
            # Реквизит игра надевает на персонажа целиком, по именам костей.
            merge_by_name=bool(player_ref),
            weapon_hidden=hidden_ranges(getattr(sequence, 'hide_events', ()),
                                        sequence.fps) if player_ref else (),
            root_rotation_x=root_rotation(driver_dir),
            # Кадры и меш бывают в разных осях: модель класса экспортирована
            # `$upaxis Y`, модель её анимаций — обычной Z-вверх. Разница их
            # поворотов и есть та поправка, которую надо внести в корень.
            anim_rotation_x=(root_rotation(anims_dir) - root_rotation(driver_dir)
                             if anims_dir else 0.0),
        )

    def _decompile(self, cache_key: str, mdl: str) -> Optional[str]:
        result = mds.ensure_decompiled(
            cache_key, self.misc_vpk_path, [mdl],
            cancelled=self.isInterruptionRequested,
        )
        if result is None:
            logger.warning(f"[taunt] не достали модель {mdl}")
            self.failed.emit(self._p['no_models'])
            return None
        return result.directory

    def _player_dir(self, tf2_class: str) -> str:
        stem = CLASS_MODEL_STEM.get(tf2_class, '')
        result = mds.ensure_decompiled(
            f'__player_{tf2_class}', self.misc_vpk_path,
            [f'models/player/{stem}.mdl'],
            cancelled=self.isInterruptionRequested,
        )
        return result.directory if result else ''

    def _player_and_sequence(self, tf2_class: str, scene_stem: str):
        """(reference SMD персонажа, последовательность) или (None, None)."""
        self.progress.emit(self._p['player'])
        player_dir = self._player_dir(tf2_class)
        if not player_dir:
            return None, None
        stem = CLASS_MODEL_STEM.get(tf2_class, '')
        player_ref = body_smd(player_dir)
        if not player_ref:
            logger.warning(f"[taunt] нет reference SMD у модели {tf2_class}")
            return None, None

        self.progress.emit(self._p['anims'])
        # Сперва модель анимаций мастерской: в ней лежат современные насмешки,
        # и она вдесятеро меньше общей (95 анимаций против тысячи).
        known = {}
        for cache_key, mdl in (
            (f'__taunts_{tf2_class}',
             f'models/workshop/player/animations/{stem}_workshop_animations.mdl'),
            (f'__anims_full_{tf2_class}', f'models/player/{stem}_animations.mdl'),
        ):
            if self.isInterruptionRequested():
                return None, None
            result = mds.ensure_decompiled(
                cache_key, self.misc_vpk_path, [mdl],
                cancelled=self.isInterruptionRequested,
            )
            if result is None:
                continue
            catalog = anim_catalog.load(result.directory)
            if catalog is None:
                continue
            for sequence in catalog.sequences:
                known.setdefault(sequence.name, (sequence, result.directory))
            # Точное имя ищем в КАЖДОЙ модели по мере разбора, а похожее — уже
            # по всем сразу: у пиро «taunt_party_trick» лежит в общей модели, а
            # в модели мастерской нашлось бы созвучное «…_trick2».
            found = self._pick(known, scene_stem, tf2_class, fuzzy=False)
            if found is not None:
                return player_ref, found
        found = self._pick(known, scene_stem, tf2_class, fuzzy=True)
        return (player_ref, found) if found is not None else (None, None)

    def _pick(self, known: dict, scene_stem: str, tf2_class: str, fuzzy: bool):
        """
        Последовательность по имени среди уже разобранных моделей.

        Насмешка хранится ДВУМЯ частями: сама последовательность и слой
        `layer_<имя>` поверх неё. Движение целиком в слое — в базе у медика
        ненулевых строк 185 из 17020 (крутится один таз), и персонаж от такой
        «анимации» складывался в комок. Поэтому слой предпочитаем базе.
        """
        name = taunt_scenes.sequence_name(
            self.prop_key, scene_stem, tf2_class, list(known), fuzzy=fuzzy)
        if not name:
            return None
        # Родня найденного имени: слой и продолжения (`…interior`, `…in`).
        family = [known[name]] if name in known else []
        family += [pair for key, pair in known.items()
                   if key != name and (key == f'layer_{name}'
                                       or key.startswith(name))]
        posed = [(seq, where) for seq, where in family
                 if seq.exists and has_motion(seq.smd_path)]
        if not posed:
            return None
        # Из движущихся берём самую длинную: `…in` и `…out` — это входы и
        # выходы на десяток кадров, а нужна сама насмешка.
        sequence, where = max(posed,
                              key=lambda pair: os.path.getsize(pair[0].smd_path))
        # Оси кадров берутся у ТОЙ модели, откуда последовательность.
        self._anims_dir = where
        # События показа реквизита Valve пишет в БАЗОВУЮ последовательность, а
        # играем мы слой поверх неё: у `layer_taunt_xray` их нет, у
        # `taunt_xray` — три. Кадры у обеих частей общие, так что переносим.
        if not sequence.hide_events and name in known:
            base = known[name][0]
            if base.hide_events:
                sequence = replace(sequence, hide_events=base.hide_events)
        return sequence

    def _own_sequence(self, prop_dir: str):
        """Своя анимация реквизита: самая длинная, кроме опорного кадра."""
        catalog = anim_catalog.load(prop_dir)
        if catalog is None:
            return None
        movers = [s for s in catalog.sequences
                  if s.exists and s.name.lower() not in ('ref', 'reference')]
        if not movers:
            return None
        # Длина в кадрах прямо не записана — берём вес SMD: у опорной позы он
        # на порядок меньше, чем у настоящей анимации.
        return max(movers, key=lambda s: os.path.getsize(s.smd_path))

    def _mats(self, smd: str) -> list:
        from src.services.smd_to_obj_service import SmdToObjService
        return sorted(SmdToObjService.scan_material_names([smd]))

    def _emit_scene(self, reader, scene: dict, prop_dir: str,
                    player_dir: str) -> None:
        """Текстуры обеих частей сцены и сама сцена."""
        from src.services.viewmodel_worker import _cdmaterials, _scene_materials

        resolver = MaterialResolver(reader, self._preview_dir)
        # В сцене с персонажем реквизит идёт «оружием», а персонаж «руками».
        # Без персонажа реквизит остаётся единственным мешем — то есть тем же
        # «руками», и материалы приходят вторым списком.
        weapon_names, arms_names = _scene_materials(scene)
        prop_names, player_names = ((weapon_names, arms_names) if player_dir
                                    else (arms_names, []))

        textures: dict = {}
        hints: dict = {}
        for names, directory in ((prop_names, prop_dir),
                                 (player_names, player_dir)):
            if not names or not directory:
                continue
            cdmaterials = _cdmaterials(directory)
            textures.update({name: png for name, png
                             in resolver.texture_map(names, cdmaterials).items()
                             if png})
            hints.update(resolver.render_map(names, cdmaterials))

        # Свойства материалов — ДО сцены: вьювер применит их по мере прихода
        # картинок, а не пересоберёт материалы дважды.
        self.render_hints.emit(hints)
        self.animated_ready.emit(scene)
        self.editable_materials.emit(
            list(scene.get('weaponMaterials') or prop_names))
        if textures:
            self.multi_material.emit(textures)
        missing = [n for n in (*prop_names, *player_names) if n not in textures]
        if missing:
            logger.warning(f"[taunt] без текстуры остались материалы: {missing}")
