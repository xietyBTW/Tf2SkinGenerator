"""
Воркер вида от первого лица: собирает сцену «руки класса с оружием».

Отдельно от Preview3DWorker намеренно. Тот построен на «один предмет — одна
модель — один набор текстур», и вьюмодель в эту схему не ложится: моделей три
(оружие, руки, анимации), декомпилировать надо все три, а материалы делятся на
редактируемые (оружие) и стоковые (руки).

Порядок работы:

  1. Класс и слот оружия — из items_game ([viewmodel_anims]).
  2. Три модели через общий кэш декомпиляции ([model_decompile_service]).
  3. Последовательность по активности ([weapon_anim_catalog]).
  4. Сцена в один OBJ ([viewmodel_scene]).
  5. Текстуры обеих частей — через MaterialResolver, по $cdmaterials из QC
     каждой модели. У рук это `models/player/<класс>/`, у оружия своя папка.

Сигналы намеренно повторяют Preview3DWorker: панель превью уже умеет их
принимать, и переиспользование слотов дешевле новой ветки в UI.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

from src.services.base_worker import Signal

from src.data import viewmodel_anims
from src.data.weapons import WEAPON_MDL_PATHS
from src.services import model_decompile_service as mds
from src.services import qc_skin_parser, smd_service
from src.services import viewmodel_animation, viewmodel_scene
from src.services import weapon_anim_catalog as anim_catalog
from src.services.base_worker import BaseWorker
from src.services.game_vpk_reader import GameVpkReader
from src.services.material_resolver import MaterialResolver
from src.services.weapon_anim_catalog import Action
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class ViewmodelPreviewWorker(BaseWorker):
    """Готовит OBJ вьюмодели и текстуры к нему."""

    #: Модель готова: (obj_path, "") — текстуры приходят отдельно, как у 3D.
    ready = Signal(str, str)
    #: Анимированная сцена: меш в bind-позе + дорожки костей одним словарём.
    #: Эмитится вместо `ready`, когда воркер просили не позу, а движение.
    animated_ready = Signal(object)
    #: Только дорожки: сцена на экране та же, сменилась лишь анимация.
    clip_ready = Signal(object)
    #: {имя материала: PNG} — и оружие, и руки.
    multi_material = Signal(object)
    #: Материалы ОРУЖИЯ: только их пользователь вправе перекрашивать.
    editable_materials = Signal(object)
    #: Как рисовать материалы (прозрачность, блик) — см. vmt_render.
    render_hints = Signal(object)
    #: Что это оружие вообще умеет: [(имя действия, подпись)] для выбора в UI.
    actions_available = Signal(object)
    #: Текстовый прогресс для UI.
    progress = Signal(str)
    failed = Signal(str)

    _PROGRESS = {
        'ru': {
            'extracting':  'Извлечение модели из VPK...',
            'decompiling': 'Декомпиляция модели...',
            'arms':        'Загрузка рук класса...',
            'pose':        'Поиск анимации...',
            'converting':  'Сборка сцены...',
            'texture':     'Загрузка текстур...',
            'no_class':    'Неизвестно, какому классу принадлежит оружие',
            'no_models':   'Модели вида от первого лица не найдены',
            'no_pose':     'У этого предмета нет вида от первого лица',
            'scene_error': 'Не удалось собрать сцену',
        },
        'en': {
            'extracting':  'Extracting model from VPK...',
            'decompiling': 'Decompiling model...',
            'arms':        'Loading class arms...',
            'pose':        'Looking up animation...',
            'converting':  'Building scene...',
            'texture':     'Loading textures...',
            'no_class':    'Cannot tell which class this weapon belongs to',
            'no_models':   'First-person models not found',
            'no_pose':     'This item has no first-person view',
            'scene_error': 'Failed to build the scene',
        },
    }

    def __init__(
        self,
        weapon_key: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
        tf2_root: str = "",
        tf2_class: str = "",
        action: Action = Action.IDLE,
        frame_index: int = 0,
        animate: bool = True,
        clip_only: bool = False,
        custom_smd_path: str = "",
        custom_keep_materials: bool = False,
        team: str = "red",
        lang: str = 'en',
        parent=None,
    ):
        super().__init__(parent)
        self.weapon_key = weapon_key
        self.misc_vpk_path = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self.tf2_root = tf2_root
        #: Чьи руки показывать. Задаётся снаружи, потому что всеклассовое оружие
        #: принадлежит сразу девяти классам, и выбор делает пользователь.
        self.tf2_class = (tf2_class or "").lower()
        self.action = action
        self.frame_index = frame_index
        #: True (по умолчанию) — отдать всю последовательность, а не один её
        #: кадр. Замер показал, что это даже чуть дешевле запекания позы в OBJ:
        #: не пишется текстовый файл и не гоняется скиннинг рук на Python.
        #: False оставлен для диагностики и как запасной путь через OBJ.
        self.animate = animate
        #: True — сцена этого оружия уже на экране, нужны только дорожки.
        #: Меш, скелет, материалы и текстуры от выбора анимации не зависят, а
        #: их пересборка — это распаковка тех же VTF и повторное чтение SMD.
        self.clip_only = clip_only
        #: SMD пользователя вместо игровой геометрии. Сцена собирается тем
        #: же слиянием, что и мод: nodes/skeleton из игровой модели, кости
        #: сопоставляются по имени, треугольники — пользовательские. Значит
        #: превью показывает ровно то, что попадёт в игру: одна кость —
        #: жёсткий кусок, игровые кости — с анимацией частей.
        self.custom_smd_path = custom_smd_path or ""
        #: «Готовая» модель со своими материалами: их имена сохраняются.
        self.custom_keep_materials = bool(custom_keep_materials)
        #: Команда, за которую показывать РУКИ. У медика, снайпера,
        #: инженера, пиро, подрывника, солдата и шпиона рукава и перчатки
        #: командные, и на синей стороне они синие. Оружие красит панель —
        #: у него своя машинерия команд.
        self.team = (team or "red").lower()
        #: Подмена активностей из items_game — заполняется в run().
        self._replacement: dict = {}
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])
        self._preview_dir: Optional[str] = None

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
        reader = GameVpkReader([self.textures_vpk_path, self.misc_vpk_path])
        try:
            self._preview_dir = tempfile.mkdtemp(prefix="tf2sg_fp_")

            tf2_class = self.tf2_class or viewmodel_anims.class_of(self.weapon_key)
            if tf2_class not in viewmodel_anims.CLASS_MODEL_STEM:
                self.failed.emit(self._p['no_class'])
                return
            slot = viewmodel_anims.slot_for(self.weapon_key, self.tf2_root)
            # Подмена активностей из items_game точнее слота: у куная и
            # Большого добытчика слот остаётся melee, а играют они набор ITEM2.
            info = viewmodel_anims.anim_info(self.weapon_key, self.tf2_root)
            self._replacement = info.replacement if info else {}

            # Часы шпиона показываются СВОЕЙ моделью вида: руки, часы и
            # последовательности лежат в ней вместе, и рук класса ей не надо.
            own_view = viewmodel_anims.viewmodel_mdl(self.weapon_key)
            if own_view:
                self._run_own_viewmodel(reader, own_view, tf2_class)
                return

            parts = self._decompile_all(tf2_class)
            if parts is None:
                return                       # причину уже сообщили
            weapon_dir, arms_dir, anims_dir = parts

            self.progress.emit(self._p['pose'])
            sequence = self._find_sequence(anims_dir, slot)
            if sequence is None:
                self.failed.emit(self._p['no_pose'])
                return
            if self.isInterruptionRequested():
                return

            if self.clip_only:
                self._emit_clip(arms_dir, sequence)
                return

            self.progress.emit(self._p['converting'])
            try:
                scene, carrier_dir = self._build_scene(
                    weapon_dir, arms_dir, sequence)
            except viewmodel_scene.NotHeldInHands as exc:
                logger.info(f"[fp] {self.weapon_key}: {exc} — предмет носят, "
                            f"а не держат в руках")
                self.failed.emit(self._p['no_pose'])
                return
            if scene is None:
                self.failed.emit(self._p['scene_error'])
                return
            if self.isInterruptionRequested():
                return

            self.progress.emit(self._p['texture'])
            self._emit_scene(reader, scene, weapon_dir, arms_dir,
                             carrier_dir)

        except mds.DecompileError as exc:
            logger.warning(f"[fp] {self.weapon_key}: {exc}")
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.error(f"[fp] {self.weapon_key}: {exc}", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            reader.close()

    # ── Шаги ──────────────────────────────────────────────────────────────── #

    def _run_own_viewmodel(self, reader, mdl_path: str, tf2_class: str) -> None:
        """Ветка для предметов со СВОЕЙ моделью вида (часы шпиона).

        В `v_watch_*.mdl` уже есть и руки, и часы, и свои последовательности,
        так что ни рук класса, ни bonemerge не нужно: меш показывается как
        есть, а движение берётся из его собственного QC. Правится в нём всё,
        кроме рук — их материалы берём из модели рук класса.
        """
        result = mds.ensure_decompiled(
            f"__vm_{self.weapon_key}", self.misc_vpk_path, [mdl_path],
            cancelled=self.isInterruptionRequested,
            on_progress=self._emit_stage,
        )
        if result is None:
            logger.warning(f"[fp] модель вида не достали: {mdl_path}")
            self.failed.emit(self._p['no_models'])
            return
        view_dir = result.directory
        ref = smd_service.find_reference_smd(view_dir, self.weapon_key)
        if not ref:
            self.failed.emit(self._p['scene_error'])
            return

        self.progress.emit(self._p['pose'])
        sequence = self._find_sequence(view_dir, anim_catalog.VIEWMODEL_SLOT)
        if sequence is None:
            self.failed.emit(self._p['no_pose'])
            return
        if self.isInterruptionRequested():
            return
        if self.clip_only:
            self._emit_clip(view_dir, sequence, arms_smd=ref)
            return

        self.progress.emit(self._p['converting'])
        scene = viewmodel_animation.build_scene(
            arms_ref_smd=ref,
            anim_smd=sequence.smd_path,
            clip_name=sequence.name,
            fps=sequence.fps,
            loop=sequence.loop,
            arms_extra_smds=_default_body_parts(view_dir, ref),
            editable_mats=self._own_view_editable(ref, tf2_class),
        )
        if scene is None:
            self.failed.emit(self._p['scene_error'])
            return
        self.progress.emit(self._p['texture'])
        self._emit_scene(reader, scene, view_dir, view_dir)

    def _own_view_editable(self, ref: str, tf2_class: str) -> list:
        """Материалы модели вида за вычетом рук класса — это и есть предмет."""
        from src.services.smd_to_obj_service import SmdToObjService
        found = SmdToObjService.scan_material_names([ref])
        hands = mds.ensure_decompiled(
            f"__arms_{tf2_class}", self.misc_vpk_path,
            [viewmodel_anims.arms_mdl(tf2_class)],
            cancelled=self.isInterruptionRequested,
        )
        arms_smd = smd_service.find_reference_smd(hands.directory, "arms")             if hands else ""
        skip = SmdToObjService.scan_material_names([arms_smd]) if arms_smd else set()
        editable = sorted(found - skip)
        logger.info(f"[fp] {self.weapon_key}: правится {editable}, "
                    f"руки {sorted(found & skip)}")
        return editable

    def _decompile_all(self, tf2_class: str) -> Optional[tuple]:
        """Папки декомпиляции оружия, рук и модели анимаций.

        Руки и анимации общие на весь класс, поэтому кэшируются под своими
        синтетическими ключами: они не привязаны к конкретному оружию и не
        должны вытесняться при каждой его смене.
        """
        wanted = (
            (self.weapon_key, self._mdl_candidates(self.weapon_key)),
            (f"__arms_{tf2_class}", [viewmodel_anims.arms_mdl(tf2_class)]),
            (f"__anims_{tf2_class}", [viewmodel_anims.animations_mdl(tf2_class)]),
        )
        dirs = []
        for cache_key, candidates in wanted:
            if self.isInterruptionRequested():
                return None
            if not candidates or not candidates[0]:
                self.failed.emit(self._p['no_models'])
                return None
            result = mds.ensure_decompiled(
                cache_key, self.misc_vpk_path, candidates,
                cancelled=self.isInterruptionRequested,
                on_progress=self._emit_stage,
            )
            if result is None:
                logger.warning(f"[fp] не нашли модель для ключа {cache_key}")
                self.failed.emit(self._p['no_models'])
                return None
            dirs.append(result.directory)
        return tuple(dirs)

    def _mdl_candidates(self, weapon_key: str) -> list:
        from src.data.weapon_model_index import tf2_root_from_misc_vpk
        from src.services.extract_model_service import ExtractModelService
        try:
            return ExtractModelService._build_paths_to_try(
                f"scout_{weapon_key}", weapon_key,
                tf2_root_from_misc_vpk(self.misc_vpk_path),
            )
        except Exception as exc:
            logger.debug(f"[fp] кандидаты MDL не собрались: {exc}")
            fallback = WEAPON_MDL_PATHS.get(weapon_key)
            return [fallback] if fallback else []

    def _find_sequence(self, anims_dir: str, slot: str):
        catalog = anim_catalog.load(anims_dir)
        if catalog is None:
            return None
        # Что доступно этому оружию — наверх сразу: список нужен интерфейсу
        # даже тогда, когда выбранного действия у оружия нет.
        available = [a.name for a in catalog.actions_for(slot, self._replacement)]
        self.actions_available.emit(available)
        sequence = catalog.find(slot, self.action, self._replacement)
        if sequence is None and available:
            # Набор действий у каждого оружия свой: перезарядки у биты нет.
            # Показать первое, что оно умеет, честнее, чем «вида от первого
            # лица у предмета нет» — интерфейс встанет на то же значение
            # (см. _update_fp_action_combo: он тоже берёт первое из списка).
            logger.info(f"[fp] {self.weapon_key}: {self.action.name} нет для "
                        f"слота '{slot}' — показываю {available[0]}")
            self.action = Action[available[0]]
            sequence = catalog.find(slot, self.action, self._replacement)
        if sequence is None:
            logger.info(
                f"[fp] {self.weapon_key}: нет {self.action.name} для слота "
                f"'{slot}' — вида от первого лица у предмета нет")
            return None
        logger.info(
            f"[fp] {self.weapon_key}: слот '{slot}', {self.action.name} → "
            f"{sequence.name}")
        return sequence

    def _emit_clip(self, arms_dir: str, sequence, arms_smd: str = "") -> None:
        """Только дорожки кадров — сцена на экране остаётся прежней.

        `arms_smd` задаётся явно для предметов со своей моделью вида: скелет
        там её собственный, и рук класса в сцене нет.
        """
        arms_smd = arms_smd or smd_service.find_reference_smd(arms_dir, "arms")
        clip = viewmodel_animation.build_clip(
            arms_ref_smd=arms_smd,
            anim_smd=sequence.smd_path,
            clip_name=sequence.name,
            fps=sequence.fps,
            loop=sequence.loop,
        ) if arms_smd else None
        if clip is None:
            self.failed.emit(self._p['scene_error'])
            return
        self.clip_ready.emit(clip)

    def _build_scene(self, weapon_dir: str, arms_dir: str, sequence):
        weapon_smd = self._weapon_smd(weapon_dir)
        arms_smd = smd_service.find_reference_smd(arms_dir, "arms")
        if not weapon_smd or not arms_smd:
            logger.warning(
                f"[fp] {self.weapon_key}: нет reference SMD "
                f"(оружие={bool(weapon_smd)}, руки={bool(arms_smd)})")
            return None
        # $bonemerge из QC оружия: только перечисленные там кости сажаются в
        # руку. Без этого совпадение имён сливало и собственные части оружия —
        # револьвер разлетался на 73 единицы вместо своих двадцати.
        weapon_qc = qc_skin_parser.load_model(weapon_dir)
        merge_bones = list(weapon_qc.bonemerge) if weapon_qc else None
        # Бодигруппы всегда игровые, и отсекать основной меш надо тоже по
        # игровому пути: с кастомной моделью weapon_smd указывает во временную
        # папку, и оригинал прошёл бы в сцену вторым мешем поверх своего.
        weapon_extra = _default_body_parts(
            weapon_dir, smd_service.find_reference_smd(weapon_dir, self.weapon_key))
        arms_extra = _default_body_parts(arms_dir, arms_smd)
        carrier_smd, carrier_extra, carrier_dir = self._carrier_smd()

        if self.animate:
            return viewmodel_animation.build_scene(
                arms_ref_smd=arms_smd,
                weapon_ref_smd=weapon_smd,
                anim_smd=sequence.smd_path,
                clip_name=sequence.name,
                fps=sequence.fps,
                loop=sequence.loop,
                weapon_merge_bones=merge_bones,
                weapon_carrier_smd=carrier_smd,
                carrier_extra_smds=carrier_extra,
                weapon_extra_smds=weapon_extra,
                arms_extra_smds=arms_extra,
                arms_include_mats=self._arms_whitelist(arms_smd, arms_extra),
            ), carrier_dir
        return viewmodel_scene.build(
            os.path.join(self._preview_dir, "viewmodel.obj"),
            weapon_ref_smd=weapon_smd,
            arms_ref_smd=arms_smd,
            anim_smd=sequence.smd_path,
            frame_index=self.frame_index,
            weapon_extra_smds=weapon_extra,
            arms_extra_smds=arms_extra,
            weapon_merge_bones=merge_bones,
            arms_include_mats=self._arms_whitelist(arms_smd, arms_extra),
            weapon_carrier_smd=carrier_smd,
            carrier_extra_smds=carrier_extra,
        ), carrier_dir

    def _weapon_smd(self, weapon_dir: str) -> str:
        """Меш оружия: игровой либо пользовательский, слитый со скелетом игры.

        Слияние делает та же функция, что и сборка мода, поэтому в руке видно
        ровно то, что попадёт в игру. Не получилось — показываем игровой меш и
        пишем в лог: превью не повод отменять показ.
        """
        game_smd = smd_service.find_reference_smd(weapon_dir, self.weapon_key)
        if not self.custom_smd_path or not game_smd:
            return game_smd or ""
        if not os.path.exists(self.custom_smd_path):
            logger.warning(f"[fp] кастомной модели нет: {self.custom_smd_path}")
            return game_smd
        merged = os.path.join(self._preview_dir or "", "custom_reference.smd")
        try:
            from src.services.smd_service import SMDService
            SMDService.replace_model_sections(
                self.custom_smd_path, game_smd, merged,
                keep_user_materials=self.custom_keep_materials,
            )
        except Exception as exc:                              # noqa: BLE001
            logger.warning(f"[fp] кастомная модель не слилась со скелетом: {exc}")
            return game_smd
        logger.info(f"[fp] {self.weapon_key}: в руке кастомная модель "
                    f"{os.path.basename(self.custom_smd_path)}")
        return merged

    def _carrier_smd(self) -> tuple:
        """(меш носителя, его бодигруппы, папка) либо ("", [], "").

        Праздничное оружие — навесная гирлянда: сама пушка остаётся в
        `model_player` предмета. Без носителя в руке висят одни огоньки.
        Кого и как искать — в `carrier_model`, общем с обычным превью.
        """
        from src.services import carrier_model
        found = carrier_model.find(
            self.weapon_key, self.misc_vpk_path, self.tf2_root,
            cancelled=self.isInterruptionRequested,
            on_progress=self._emit_stage,
        )
        if not found:
            return "", [], ""
        return found.smds[0], list(found.smds[1:]), found.directory

    def _arms_whitelist(self, arms_smd: str, extra: list) -> Optional[set]:
        """Материалы рук, которые показываем.

        В модели рук лежит не только рука: у солдата там же РАКЕТА для
        перезарядки. В покое её быть не должно, а в самой перезарядке — должна,
        поэтому список зависит от того, что проигрываем.
        """
        if self.action in RELOAD_ACTIONS:
            return None
        from src.services.smd_to_obj_service import SmdToObjService
        found = SmdToObjService.scan_material_names([arms_smd, *extra])
        props = {n for n in found
                 if n.lower() in viewmodel_anims.ARMS_PROP_MATERIALS}
        if not props:
            return None
        logger.info(f"[fp] реквизит рук скрыт вне перезарядки: {sorted(props)}")
        return found - props

    def _emit_scene(self, reader, scene, weapon_dir: str, arms_dir: str,
                    carrier_dir: str = "") -> None:
        """Текстуры и свойства материалов обеих частей сцены."""
        resolver = MaterialResolver(reader, self._preview_dir)
        # `cdmaterials` у пушки-носителя свой: гирлянда лежит в папке оружия, а
        # сам миниган — в своей. Ищем по обеим, порядок значения не имеет.
        weapon_cd = _cdmaterials(weapon_dir) + (
            _cdmaterials(carrier_dir) if carrier_dir else [])
        arms_cd = _cdmaterials(arms_dir)
        weapon_names, arms_names = _scene_materials(scene)

        textures: dict = {}
        hints: dict = {}
        for names, cdmaterials in ((weapon_names, weapon_cd),
                                   (arms_names, arms_cd)):
            if not names:
                continue
            textures.update({name: png for name, png
                             in resolver.texture_map(names, cdmaterials).items()
                             if png})
            hints.update(resolver.render_map(names, cdmaterials))
        textures.update(self._blue_arms(resolver, arms_names, arms_cd, arms_dir))

        # Свойства материалов — ДО модели: вьювер применит их по мере прихода
        # картинок, а не пересоберёт материалы дважды.
        self.render_hints.emit(hints)
        if isinstance(scene, dict):
            self.animated_ready.emit(scene)
        else:
            self.ready.emit(scene.obj_path, "")
        # Редактировать можно только САМ предмет: пушка-носитель под гирляндой
        # в превью есть, но текстуру на неё не бросишь.
        self.editable_materials.emit(
            list(scene.get("weaponMaterials") or weapon_names)
            if isinstance(scene, dict) else list(scene.weapon_materials))
        if textures:
            self.multi_material.emit(textures)
        missing = [n for n in (*weapon_names, *arms_names) if n not in textures]
        if missing:
            logger.warning(f"[fp] без текстуры остались материалы: {missing}")

    def _blue_arms(self, resolver, arms_names, cdmaterials, arms_dir: str) -> dict:
        """Синие текстуры рук под именами КРАСНЫХ материалов.

        Меши в сцене названы по материалам первого скина (`medic_red`), а
        картинку под этим именем можно положить любую — вьювер адресует
        материалы по имени. Соответствие берётся из `$texturegroup` модели рук:
        второй скин там и есть синяя команда.

        Пусто — команда красная, синих вариантов нет или QC не разобрался.
        """
        if self.team not in ("blu", "blue") or not arms_names:
            return {}
        model = qc_skin_parser.load_model(arms_dir)
        pairs = model.team_map if model else {}
        wanted = {red: blue for red, blue in pairs.items()
                  if red in arms_names and blue and blue != red}
        if not wanted:
            return {}
        blue_map = resolver.texture_map(sorted(set(wanted.values())), cdmaterials)
        swapped = {red: blue_map[blue] for red, blue in wanted.items()
                   if blue_map.get(blue)}
        if swapped:
            logger.info(f"[fp] руки за BLU: {sorted(swapped)}")
        return swapped

    def _emit_stage(self, stage: mds.Stage) -> None:
        self.progress.emit(self._p[stage.value])


#: Действия, в которых реквизит из модели РУК нужен: ракета солдата лежит там
#: же, где рука, и в покое её быть не должно, а в перезарядке — должна.
RELOAD_ACTIONS = frozenset({Action.RELOAD, Action.RELOAD_START,
                            Action.RELOAD_FINISH})


def same_arms_mesh(one: str, two: str) -> bool:
    """Одинаковы ли меши рук у двух действий (имена как у `Action`).

    Смена анимации обычно меняет только дорожки, и сцену пересобирать незачем.
    Но на границе перезарядки меняется сама геометрия рук — появляется или
    исчезает ракета, — и быстрый путь через неё вёл бы к ракете в покое.
    """
    def reloads(name: str) -> bool:
        action = getattr(Action, (name or "").upper(), None)
        return action in RELOAD_ACTIONS
    return reloads(one) == reloads(two)


def _scene_materials(scene) -> tuple:
    """(материалы оружия, материалы рук) — одинаково для позы и для анимации.

    Статичная сцена отдаёт их полями, анимированная — словарём с частями. Для
    текстур разницы нет, и разводить две ветки ниже незачем.
    """
    if not isinstance(scene, dict):
        # Носитель идёт к оружию: текстуры ему нужны так же, а редактируемым
        # его делает не этот список, а `editable_materials` ниже.
        return (list(scene.weapon_materials) + list(scene.carrier_materials),
                list(scene.arms_materials))
    weapon, arms = [], []
    for part in scene.get("parts", ()):
        (weapon if part.get("kind") == "weapon" else arms).extend(
            part.get("materials") or ())
    return weapon, arms


def _default_body_parts(decomp_dir: str, main_smd: str) -> list:
    """Части модели, которые видны по умолчанию, кроме основного меша.

    У пиро и инженера ПРАВАЯ РУКА объявлена отдельной бодигруппой
    (`c_righthand_bodygroup.smd`, `c_glove_bodygroup.smd`), и без неё в сцене
    оказывалась одна левая. У оружия так же лежат откидные части.

    Берётся вариант по умолчанию каждой бодигруппы — тот, что игра показывает,
    пока ничего не переключали.
    """
    model = qc_skin_parser.load_model(decomp_dir)
    if model is None:
        return []
    try:
        from src.services.model_build_service import ModelBuildService
        parts = ModelBuildService.extract_default_body_smds(model.qc_path)
    except Exception as exc:                            # noqa: BLE001
        logger.debug(f"[fp] бодигруппы не собрались ({decomp_dir}): {exc}")
        return []
    main = os.path.normcase(os.path.abspath(main_smd or ""))
    return [p for p in parts if os.path.normcase(os.path.abspath(p)) != main]


def _cdmaterials(decomp_dir: str) -> list:
    """Пути $cdmaterials из QC модели — где искать её текстуры."""
    model = qc_skin_parser.load_model(decomp_dir)
    return list(model.cdmaterials) if model else []
