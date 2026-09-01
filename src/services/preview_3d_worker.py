"""
Воркер для подготовки данных 3D Preview в фоновом потоке.

Шаги:
  1. Проверяем кэш декомпиляции (fast path).
  2. Если нет кэша — извлекаем MDL из VPK, декомпилируем через Crowbar.
  3. Находим reference SMD среди декомпилированных файлов.
  4. Конвертируем SMD → OBJ + MTL.
  5. Извлекаем основную текстуру VTF → PNG.
  6. Эмитируем ready(obj_path, texture_path).
"""

import glob
import os
import tempfile
from typing import Optional

from src.services.base_worker import Signal

from src.data.item_kinds import kind_of
from src.data.weapons import WEAPON_MDL_PATHS
from src.services import model_decompile_service
from src.services import qc_skin_parser, vmt_tint
from src.services.base_worker import BaseWorker
from src.services.game_vpk_reader import GameVpkReader
from src.services.material_resolver import MaterialResolver
from src.services.smd_service import NON_REFERENCE_SMD_KEYWORDS
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class Preview3DWorker(BaseWorker):
    """Готовит OBJ + текстуру для 3D Preview."""

    # Модель и первый кадр текстуры готовы
    ready    = Signal(str, str)
    # Анимированная текстура RED: список путей к PNG кадрам + framerate
    # Эмитируется ПОСЛЕ ready если кадров > 1
    animated = Signal(object, float)
    # BLU-вариант текстуры: [frame_paths], framerate
    # Эмитируется только если у оружия есть командная раскраска
    blu_ready = Signal(object, float)
    # Несколько текстур для мульти-материальных моделей: {mat_name: png_path}
    # Эмитируется вместо animated когда модель имеет > 1 материал
    multi_material = Signal(object)
    # BLU-вариант мульти-материальных текстур: {mat_name: png_path}
    # Эмитируется для персонажей когда у каждого меша есть своя BLU-текстура
    blu_multi_material = Signal(object)
    # Australium/Gold/Festive вариант оружия: (png_path, material_name)
    # Эмитируется когда в QC skinfamilies есть вариантная строка без 'blue'
    australium_ready = Signal(str, str)
    # BLU-скин есть, но в стоке он выглядит ТОЧНО как RED (та же текстура,
    # та же краска в VMT). Переключатель команд оставляем — свою BLU-текстуру
    # сделать можно, — но честно предупреждаем, что в игре разницы нет.
    blu_same_as_red = Signal()
    # Как рисовать материалы: {имя материала: {blend, opacity, twoSided…}}.
    # Без этого вьювер рисует всё непрозрачным и матовым: стекло банки
    # Мутировавшего молока ($additive) превращается в серый пластик.
    render_hints = Signal(object)
    # Ошибка
    failed   = Signal(str)
    # Текстовый прогресс для UI
    progress = Signal(str)

    _PROGRESS = {
        'ru': {
            'searching':   'Поиск модели...',
            'converting':  'Конвертация модели...',
            'texture':     'Загрузка текстуры...',
            'extracting':  'Извлечение модели из VPK...',
            'decompiling': 'Декомпиляция модели...',
            'not_found':   'Модель не найдена в VPK',
            'conv_error':  'Ошибка конвертации модели',
        },
        'en': {
            'searching':   'Searching for model...',
            'converting':  'Converting model...',
            'texture':     'Loading texture...',
            'extracting':  'Extracting model from VPK...',
            'decompiling': 'Decompiling model...',
            'not_found':   'Model not found in VPK',
            'conv_error':  'Model conversion error',
        },
    }

    def __init__(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
        lang: str = 'en',
        parent=None,
    ):
        super().__init__(parent)
        self.weapon_key        = weapon_key
        self.mode              = mode
        #: Вид предмета: вместо разбросанных проверок «mode == 'hat'» и
        #: «mode in HAND_MODE_KEYS» (см. src/data/item_kinds.py)
        self.kind              = kind_of(mode)
        self.misc_vpk_path     = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self._preview_dir: Optional[str] = None
        self._decomp_dir:  Optional[str] = None  # папка с декомпилированными QC/SMD
        self._hat_decomp_dir: Optional[str] = None  # алиас для режима hat
        #: {материал: ResolvedMaterial} для RED — с чем сравнивать BLU,
        #: чтобы понять, отличаются ли команды вообще
        self._red_looks: dict = {}
        #: Ленивый резолвер материалов и кэш разбора QC (по папке декомпиляции)
        self._materials: Optional[MaterialResolver] = None
        self._models: dict = {}
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
        # Один кэширующий читатель VPK на весь прогон: vpk.open парсит весь индекс
        # архива — раньше каждый метод открывал те же VPK заново (5-9 раз/прогон).
        self._reader = GameVpkReader([self.textures_vpk_path, self.misc_vpk_path])
        try:
            self._preview_dir = tempfile.mkdtemp(prefix="tf2sg_3d_")

            # ── 1. SMD ────────────────────────────────────────────────────── #
            self.progress.emit(self._p['searching'])
            smd_path = self._get_reference_smd()
            if not smd_path:
                self.failed.emit(self._p['not_found'])
                return
            # Сохраняем папку декомпиляции: нужна для QC-парсинга BLU текстур
            self._decomp_dir = os.path.dirname(smd_path)
            if self.kind.is_hat:
                self._hat_decomp_dir = self._decomp_dir
            if self.isInterruptionRequested():
                return

            # ── 2. OBJ ────────────────────────────────────────────────────── #
            self.progress.emit(self._p['converting'])
            obj_path = os.path.join(self._preview_dir, "model.obj")
            from src.services.smd_to_obj_service import SmdToObjService

            # Ищем bodygroup SMDs в той же папке (например c_righthand_bodygroup.smd)
            bodygroup_smds = self._find_bodygroup_smds(smd_path)
            if bodygroup_smds:
                logger.info(
                    f"[3D] Найдены bodygroup SMD: "
                    f"{[os.path.basename(b) for b in bodygroup_smds]}"
                )

            # Персонажи TF2 компилируются с $upaxis Y — SMD уже Y-up,
            # конвертацию Z→Y для них не делаем
            _source_zup = self.kind.model_is_z_up

            # Превью-фильтр материалов: для моделей, где надо показать только часть
            # (напр. Dead Ringer на viewmodel с руками — оставляем только часы).
            _include_mats = None
            from src.data.weapons import PREVIEW_MAT_WHITELIST
            _wl = PREVIEW_MAT_WHITELIST.get(self.weapon_key)
            if _wl:
                _all_mats = SmdToObjService.scan_material_names(
                    [smd_path] + bodygroup_smds)
                _keep = {m for m in _all_mats if any(s in m.lower() for s in _wl)}
                if _keep:
                    _include_mats = _keep
                    logger.info(f"[3D] Превью-фильтр {self.weapon_key}: оставляем меши {_keep}")
                else:
                    logger.warning(
                        f"[3D] Whitelist {_wl} не совпал ни с одним материалом "
                        f"({_all_mats}) — показываю всю модель"
                    )

            # Поза из первой последовательности QC: игра всегда её проигрывает,
            # и reference-меш — не то, что видит игрок (у Мутировавшего молока
            # хлеб в bind-позе торчит из банки). Модель, чья поза совпадает с
            # bind, остаётся нетронутой — таких подавляющее большинство.
            _pose_smd = self._find_pose_smd()

            ok, mat_names = SmdToObjService.convert(
                smd_path, obj_path,
                include_mats=_include_mats,
                extra_smd_paths=bodygroup_smds,
                source_zup=_source_zup,
                pose_smd_path=_pose_smd,
            )
            if not ok:
                self.failed.emit(self._p['conv_error'])
                return
            if self.isInterruptionRequested():
                return

            # ── 3. Текстура ───────────────────────────────────────────────── #
            self.progress.emit(self._p['texture'])

            # Свойства рисования — ДО текстур: вьювер применит их к материалам
            # по мере поступления картинок, а не пересоберёт материалы дважды.
            self._emit_render_hints(mat_names)

            if self.kind.multi_material and mat_names:
                self._emit_multi_tex_mode(obj_path, mat_names)
            elif self.kind.is_hat:
                self._emit_hat_textures(obj_path, mat_names)
            else:
                self._emit_weapon_textures(obj_path, mat_names)

        except Exception as exc:
            logger.error(f"Preview3DWorker: {exc}", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            self._reader.close()

    def _find_pose_smd(self) -> Optional[str]:
        """SMD анимации из QC модели — поза, в которой предмет виден в игре."""
        if not self._decomp_dir:
            return None
        try:
            from src.services import smd_pose
            model = self._model(self._decomp_dir)
            if model is None:
                return None
            return smd_pose.find_pose_smd(model.qc_path)
        except Exception as exc:
            logger.debug(f"[3D] SMD анимации не найден: {exc}")
            return None

    def _emit_render_hints(self, mat_names: list) -> None:
        """Отдаёт вьюверу прозрачность/блик/отражение материалов модели.

        Свойства берутся из VMT (vmt_render) и зависят только от материала,
        не от того, какая картинка на нём сейчас: пользователь может бросить
        свою текстуру на стекло, и оно обязано остаться стеклом.
        """
        try:
            hints = self.materials.render_map(
                list(mat_names or []), self._get_qc_cdmaterials())
        except Exception as exc:
            logger.debug(f"[3D] свойства материалов не собраны: {exc}")
            hints = {}
        # Отправляем ВСЕГДА, даже пустое: иначе на новой модели останутся
        # свойства предыдущей, а материалы у разных пушек нередко тёзки
        # (36 моделей стока делят главную текстуру с соседней).
        if hints:
            logger.info(f"[3D] особые материалы: {hints}")
        self.render_hints.emit(hints)

    # ── Ветки извлечения текстур (по режиму) ────────────────────────────── #

    def _emit_multi_tex_mode(self, obj_path: str, mat_names: list) -> None:
        """Руки / тело персонажа: мульти-материал — каждый меш получает свою текстуру."""
        tex_map = self._extract_multi_textures(mat_names)
        # Служебные материалы $texturegroup вне геометрии (eyeball_invun,
        # *_zombie …) — для селектора «Прочее» в 2D.
        _misc_extras = self._extract_texturegroup_misc_extras(mat_names)
        if _misc_extras:
            tex_map.update(_misc_extras)
        self.ready.emit(obj_path, "")
        if tex_map:
            self.multi_material.emit(tex_map)
        # BLU detection для персонажей:
        # Для многоматериальных моделей — строим полную карту {mat: blu_png}.
        # Если не удалось — пробуем одиночный BLU (старый путь как fallback).
        if self._decomp_dir and mat_names:
            try:
                raw = self._extract_blu_multi_textures_via_qc(mat_names)
                if raw:
                    # raw: {red_mat_name: (blu_png_path | None, blu_display_name)}
                    # tex_map — только записи с реальным PNG (для 3D-превью)
                    # name_map — все записи где BLU-имя отличается от RED (для лейблов карточек)
                    tex_map  = {k: v[0] for k, v in raw.items() if v[0]}
                    name_map = {k: v[1] for k, v in raw.items()}
                    self.blu_multi_material.emit((tex_map, name_map))
                    logger.info(
                        f"[3D] BLU multi-tex: {len(tex_map)} текстур, "
                        f"{len(name_map)} имён"
                    )
                else:
                    # Fallback: ищем единственный BLU VTF через QC
                    blu_paths, blu_fps = self._extract_blu_via_qc(
                        self._decomp_dir, 0.0, mat_names
                    )
                    if blu_paths:
                        self.blu_ready.emit(blu_paths, blu_fps)
            except Exception as _exc:
                logger.debug(f"[3D] BLU detection (multi-tex): {_exc}")

    def _emit_hat_textures(self, obj_path: str, mat_names: list) -> None:
        """Шапки: QC → VMT → $baseTexture → VTF (+ BLU через skinfamilies skin 1)."""
        _qc_dir = self._hat_decomp_dir
        if not _qc_dir:
            from src.services import decompile_cache as _dc
            _cached_qc = _dc.find_cached_qc_for_weapon(self.weapon_key)
            if _cached_qc:
                _qc_dir = os.path.dirname(_cached_qc)

        hat_tex_map: dict = {}
        if _qc_dir and mat_names:
            try:
                hat_tex_map = self._extract_hat_textures_via_qc_vmt(
                    _qc_dir, mat_names
                )
            except Exception as exc:
                logger.warning(f"[3D] Ошибка QC→VMT→VTF: {exc}")

        if hat_tex_map:
            first_tex = next(iter(hat_tex_map.values()))
            self.ready.emit(obj_path, first_tex)
            if len(hat_tex_map) > 1:
                self.multi_material.emit(hat_tex_map)
        else:
            # Fallback: угадываем VTF по имени MDL
            logger.debug("[3D] QC→VMT не дал результата, используем fallback")
            frame_paths, _ = self._extract_hat_texture_frames()
            self.ready.emit(obj_path, frame_paths[0] if frame_paths else "")

        if self.isInterruptionRequested():
            return

        if _qc_dir:
            # Сначала пробуем по материалам: у многоматериальной шапки команда
            # меняет не все из них, и одна общая BLU-текстура легла бы на все
            # меши сразу (линза Alcoholic Automaton получала корпус)
            raw = self._extract_hat_blu_textures(_qc_dir, mat_names)
            if raw:
                tex_map = {m: png for m, (png, _n) in raw.items() if png}
                name_map = {m: n for m, (_p, n) in raw.items() if n}
                self.blu_multi_material.emit((tex_map, name_map))
                logger.info(
                    f"[3D] BLU шапки по материалам: {len(tex_map)} текстур "
                    f"из {len(mat_names)}"
                )
                # Одноматериальная шапка (Battle Balaclava «No Gloves»):
                # карточек нет, и панель ищет BLU не по имени материала, а
                # кадром. Без этого поле синей команды оставалось пустым.
                # Считаем материалы так же, как панель считает карточки:
                # служебные меши (глаза, sheen) карточку не получают.
                from src.data.material_filter import is_editable_material
                _editable = [m for m in mat_names if is_editable_material(m)]
                if len(tex_map) == 1 and len(_editable or mat_names) <= 1:
                    self.blu_ready.emit(list(tex_map.values()), 0.0)
            else:
                blu_paths, blu_fps = self._extract_blu_via_qc(
                    _qc_dir, 0.0, mat_names)
                if blu_paths:
                    self.blu_ready.emit(blu_paths, blu_fps)

    def _emit_weapon_textures(self, obj_path: str, mat_names: list) -> None:
        """Обычное оружие: текстуры + BLU/Australium через QC skinfamilies."""
        # Доп. текстуры по фиксированному пути (вне QC/модели), напр.
        # HUD-вставки Dead Ringer (pocket_watch_fg/bg).
        fixed_extras = self._extract_fixed_extra_textures()
        # Материалы из QC $texturegroup, которых нет в геометрии
        # (напр. smiley у гранатомёта) — чтобы карточки 2D совпадали
        # с тем, что предлагает сборка.
        tg_extras = self._extract_texturegroup_extras(mat_names)

        # Служебные материалы $texturegroup вне геометрии — для «Прочее».
        misc_extras = self._extract_texturegroup_misc_extras(mat_names)

        if len(mat_names) > 1:
            # ── Мульти-материальное оружие (shell, scope и т.п.) ─────── #
            tex_map = self._extract_multi_textures(mat_names)
            if fixed_extras:
                tex_map.update(fixed_extras)
            if tg_extras:
                tex_map.update(tg_extras)
            if misc_extras:
                tex_map.update(misc_extras)
            first_tex = next(iter(tex_map.values()), "") if tex_map else ""
            self.ready.emit(obj_path, first_tex)
            if tex_map:
                self.multi_material.emit(tex_map)
            framerate = 0.0
        else:
            # ── Одиночная текстура (возможно анимированная) ──────────── #
            frame_paths, framerate = self._extract_texture_frames()
            first_tex = frame_paths[0] if frame_paths else ""
            self.ready.emit(obj_path, first_tex)
            # Главная текстура + доп. (фиксированные и из $texturegroup) → карточки 2D
            extra_cards: dict = {}
            extra_cards.update(fixed_extras)
            extra_cards.update(tg_extras)
            if extra_cards:
                combined: dict = {}
                main_name = mat_names[0] if mat_names else self.weapon_key
                if first_tex:
                    combined[main_name] = first_tex
                combined.update(extra_cards)
                if len(combined) > 1:
                    self.multi_material.emit(combined)
            elif len(frame_paths) > 1:
                self.animated.emit(frame_paths, framerate)

        if self.isInterruptionRequested():
            return

        # ── BLU + Australium через QC skinfamilies ───────────────────── #
        blu_paths, blu_fps = [], 0.0
        blu_multi_done = False
        # Материалы, которые в итоге ПОКАЗЫВАЮТСЯ: геометрия плюс добавки из
        # $texturegroup. Командной бывает только добавка — граната у quadball,
        # ядро у cannon, руки шпиона у часов; их геометрия одноматериальная, и
        # по одному имени модели BLU для них не искался вовсе.
        card_names = list(dict.fromkeys(
            list(mat_names) + list(tg_extras) + list(fixed_extras)))
        if self._decomp_dir:
            # Мульти-материальное командное оружие (напр. праздничное:
            # клинок и lights меняются по команде в РАЗНЫХ колонках
            # $texturegroup) — BLU строим как карту {материал: blu_png}.
            # Одиночный BLU тут наложил бы одну текстуру на всю модель.
            if len(card_names) > 1:
                _model = self._model(self._decomp_dir)
                if _model and _model.spec.team:
                    try:
                        raw = self._extract_blu_multi_textures_via_qc(card_names)
                        tex_map  = {k: v[0] for k, v in raw.items() if v[0]}
                        name_map = {k: v[1] for k, v in raw.items()}
                        if name_map:
                            self.blu_multi_material.emit((tex_map, name_map))
                            blu_multi_done = True
                    except Exception as _exc:
                        logger.debug(f"[3D] BLU multi (оружие): {_exc}")
            if not blu_multi_done:
                blu_paths, blu_fps = self._extract_blu_via_qc(
                    self._decomp_dir, framerate, mat_names
                )
            # Вариантные строки (Australium/Gold/Festive) проверяем
            # НЕЗАВИСИМО от BLU: у большинства австралиум-оружий
            # (ракетница и т.п.) есть И команды, И gold-строки —
            # раньше «if not blu_paths» полностью скрывал вариант.
            aus_path, aus_mat = self._extract_variant_via_qc(self._decomp_dir)
            if aus_path:
                self.australium_ready.emit(aus_path, aus_mat or "")
        # Fallback: прямой поиск {wk}_blue.vtf
        if not blu_multi_done and not blu_paths:
            blu_paths, blu_fps = self._extract_blu_texture_frames(framerate)
        if blu_paths:
            self.blu_ready.emit(blu_paths, blu_fps)

    # ── Получение SMD ─────────────────────────────────────────────────────── #

    def _get_reference_smd(self) -> Optional[str]:
        """Возвращает reference SMD из кэша или после декомпиляции."""
        from src.data.weapons import PREVIEW_MDL_OVERRIDE
        _override = PREVIEW_MDL_OVERRIDE.get(self.weapon_key)
        # У шапок, персонажей и масок weapon_key — это уже полный путь MDL
        if self.kind.is_hat or self.kind.is_character or self.kind.is_spy_mask:
            # weapon_key IS the full MDL path for hats and player body modes
            mdl_rel = self.weapon_key
        elif _override:
            # Превью-подмена модели (напр. Dead Ringer → viewmodel v_watch_pocket_spy)
            mdl_rel = _override
        else:
            mdl_rel = WEAPON_MDL_PATHS.get(
                self.weapon_key,
                f"models/weapons/c_models/{self.weapon_key}/{self.weapon_key}.mdl",
            )

        result = model_decompile_service.ensure_decompiled(
            self.weapon_key,
            self.misc_vpk_path,
            self._mdl_candidates(mdl_rel),
            cancelled=self.isInterruptionRequested,
            on_progress=self._emit_decompile_stage,
        )
        if result is None:
            return None
        return self._find_reference_smd(result.directory)

    def _emit_decompile_stage(self, stage: model_decompile_service.Stage) -> None:
        """Стадия из сервиса → переведённая строка прогресса."""
        self.progress.emit(self._p[stage.value])

    def _mdl_candidates(self, mdl_rel_hint: str) -> list:
        """Пути MDL внутри VPK в порядке приоритета.

        Шапка лежит не там, где записано в предмете (workshop/, суффикс класса),
        поэтому её путь раскрывается в список кандидатов. У персонажей, масок и
        превью-подмен путь известен точно.
        """
        from src.data.weapons import PREVIEW_MDL_OVERRIDE
        if self.kind.is_hat:
            from src.services.tf2_paths import build_hat_mdl_candidates
            return build_hat_mdl_candidates(mdl_rel_hint)
        if (self.kind.is_character or self.kind.is_spy_mask
                or self.weapon_key in PREVIEW_MDL_OVERRIDE):
            return [mdl_rel_hint]

        from src.data.weapon_model_index import tf2_root_from_misc_vpk
        from src.services.extract_model_service import ExtractModelService
        return ExtractModelService._build_paths_to_try(
            self.mode, self.weapon_key, tf2_root_from_misc_vpk(self.misc_vpk_path)
        )

    def _find_reference_smd(self, directory: str) -> Optional[str]:
        """Находит reference SMD (исключая physics/anim) в директории."""
        def skip(path: str) -> bool:
            return any(kw in os.path.basename(path).lower() for kw in NON_REFERENCE_SMD_KEYWORDS)

        # ── Персонажи TF2: проверяем ДО *_reference.smd ───────────────────── #
        # Причина: у персонажей bodygroup'ы (рюкзак медика medipack_reference.smd,
        # шапка и т.п.) тоже имеют _reference в имени и алфавитно могут идти раньше
        # основного тела. Поэтому для персонажей сразу ищем *_morphs_low.smd.
        #
        # weapon_key для персонажей = полный MDL путь: "models/player/medic.mdl".
        # Стэм файла ("medic", "demo", ...) — правильное короткое имя класса,
        # именно так Crowbar называет декомпилированные SMD файлы.
        # Важно: у демомена MDL называется demo.mdl, а не demoman.mdl.
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS

        # ── Режим масок шпиона: загружаем spy_mask.smd (bodygroup) ─────────── #
        if self.kind.is_spy_mask:
            mask_smd = os.path.join(directory, "spy_mask.smd")
            if os.path.exists(mask_smd):
                logger.debug("[3D] spy_mask.smd найден")
                return mask_smd
            # Fallback: ищем любой *mask*.smd
            mask_smds = [p for p in glob.glob(os.path.join(directory, "*mask*.smd"))
                         if not skip(p) and "lod" not in os.path.basename(p).lower()]
            if mask_smds:
                return mask_smds[0]

        if self.mode in PLAYER_BODY_MODE_KEYS:
            class_short = os.path.splitext(os.path.basename(self.weapon_key))[0]
            # Например: "models/player/medic.mdl" → "medic"
            #            "models/player/demo.mdl"  → "demo"

            # Приоритет 1: *{class}_morphs_low.smd — именно так Crowbar называет тело
            morphs_smds = [
                p for p in glob.glob(os.path.join(directory, f"*{class_short}*_morphs_low.smd"))
                if not skip(p)
            ]
            if morphs_smds:
                logger.debug(f"[3D] Персонаж SMD (morphs_low): {os.path.basename(morphs_smds[0])}")
                return morphs_smds[0]

            # Приоритет 2: любой *{class}*.smd (не physics/anim)
            class_smds = [
                p for p in glob.glob(os.path.join(directory, f"*{class_short}*.smd"))
                if not skip(p)
            ]
            # Дополнительно исключаем bodygroup'ы: они не должны содержать класс как основу
            # (medipack.smd, backpack.smd и т.п.)
            _BODYGROUP_WORDS = ("pack", "backpack", "helmet", "hat", "glasses",
                                "mask", "coat", "vest", "arm", "hand")
            main_smds = [
                p for p in class_smds
                if not any(w in os.path.basename(p).lower() for w in _BODYGROUP_WORDS)
            ]
            chosen = main_smds if main_smds else class_smds
            if chosen:
                logger.debug(f"[3D] Персонаж SMD (class fallback): {os.path.basename(chosen[0])}")
                return chosen[0]

        # ── Обычные оружия и руки: *_reference.smd ───────────────────────── #
        refs = [p for p in glob.glob(os.path.join(directory, "*_reference.smd"))
                if not skip(p)]
        if refs:
            return refs[0]

        # SMD с weapon_key в имени (оружия и руки)
        wk_smds = [
            p for p in glob.glob(os.path.join(directory, f"*{self.weapon_key}*.smd"))
            if not skip(p)
        ]
        if wk_smds:
            return wk_smds[0]

        # Любой SMD не physics/anim
        all_smds = [p for p in glob.glob(os.path.join(directory, "*.smd"))
                    if not skip(p)]
        return all_smds[0] if all_smds else None

    def _find_bodygroup_smds(self, reference_smd_path: str) -> list:
        """
        Ищет *_bodygroup.smd файлы в той же папке что и reference SMD.

        Source Engine хранит опциональную геометрию (бодигруппы) в отдельных
        SMD файлах рядом с reference SMD. Пример: c_righthand_bodygroup.smd
        внутри c_pyro_arms — правая рука, которая включается при нужном оружии.

        Дополнительно подбирает ВСЕ part-SMD, на которые ссылается QC через
        $body/$bodygroup (studio "...smd") — например центральную вставку
        Dead Ringer (pocket_watch_fg), которая лежит отдельным part-SMD и иначе
        не попала бы в превью (её материала не было бы среди mat_names).

        Returns:
            Список путей к доп. SMD (bodygroup-файлы + part-SMD из QC).
        """
        directory = os.path.dirname(reference_smd_path)
        found = set(glob.glob(os.path.join(directory, "*_bodygroup.smd")))

        # Части модели из QC. Берём вариант ПО УМОЛЧАНИЮ каждой бодигруппы:
        # переключаемая группа (broken у бутылки, bites у сэндвича, reload у
        # гранатомёта, класс у id_badge) показывает в игре ровно один вариант,
        # и складывать их все в одну модель значит показать бутылку целой и
        # разбитой разом. Материалы скрытых вариантов не теряются — они
        # приходят карточками из $texturegroup (_extract_texturegroup_extras).
        try:
            model = self._model(directory)
            if model is not None:
                from src.services.model_build_service import ModelBuildService
                for smd in ModelBuildService.extract_default_body_smds(model.qc_path):
                    found.add(smd)
        except Exception as exc:
            logger.debug(f"[3D] Не удалось собрать part-SMD из QC: {exc}")

        # Не включаем сам reference (он уже основной)
        found.discard(os.path.abspath(reference_smd_path))
        found.discard(reference_smd_path)

        # Тело шпиона: маска маскировки объявлена в QC как $bodygroup и иначе
        # попала бы в превью тела. Но у маски своя секция (режим spy_masks /
        # SPY_MASK_MODE_KEY), поэтому из тела её исключаем.
        return sorted(self._strip_spy_disguise_mask(found, self.mode))

    @staticmethod
    def _strip_spy_disguise_mask(smd_paths, mode: str) -> list:
        """Убирает SMD маски маскировки из bodygroup'ов ТЕЛА шпиона.

        Маска шпиона (``spy_mask.smd`` / ``*mask*.smd``) — отдельная секция
        (SPY_MASK_MODE_KEY), в превью тела (mode == "spy_body") её быть не должно.
        Для остальных режимов список не меняется.
        """
        paths = list(smd_paths)
        if mode != "spy_body":
            return paths
        kept = [p for p in paths if "mask" not in os.path.basename(p).lower()]
        removed = [p for p in paths if p not in kept]
        if removed:
            logger.info(
                "[3D] Тело шпиона: маска исключена из bodygroup'ов "
                f"({[os.path.basename(p) for p in removed]}) — у неё своя секция"
            )
        return kept

    # ── Извлечение нескольких текстур (мульти-материал) ──────────────────── #

    def _extract_multi_textures(self, mat_names: list) -> dict:
        """
        Для каждого имени материала из SMD ищет VTF в VPK и сохраняет как PNG.

        Returns:
            {mat_name: png_path} — только для найденных текстур.
        """
        result: dict = {}
        try:
            from src.data.player_hands import HAND_MODES

            # Кэширующий reader открывает оба VPK один раз: VTF обычно в textures,
            # VMT (для материалов с $basetexture) — чаще в misc.
            paks = self._reader.paks
            if not paks:
                return result

            # Для моделей рук / скинов персонажа определяем папку (materials/models/player/{folder}/)
            # Все материалы SMD текстурируем — _find_vtf_for_mat ищет сначала
            # в папке игрока, что покрывает и руки, и рукав костюма.
            from src.data.player_characters import PLAYER_CHARACTERS
            arm_folder: Optional[str] = None
            if self.kind.is_hands:
                textures_list = HAND_MODES.get(self.mode, {}).get("textures", [])
                if textures_list:
                    arm_folder = textures_list[0][0]
            elif self.kind.is_character:
                # Берём папку текстур из PLAYER_CHARACTERS["folder"].
                # Нельзя просто брать стем MDL — у Heavy MDL = "heavy.mdl",
                # но папка текстур = "hvyweapon".
                arm_folder = PLAYER_CHARACTERS.get(self.mode, {}).get(
                    "folder",
                    os.path.splitext(os.path.basename(self.weapon_key))[0]
                )

            # Пути материалов из QC ($cdmaterials) — авторитетный источник для
            # оружия: позволяет найти ВСЕ материалы модели (вторая текстура и т.п.),
            # даже если их папка не совпадает с именем материала.
            cdmats = self._get_qc_cdmaterials()

            for mat_name in mat_names:
                # 1) Прямой поиск VTF по угадываемым путям и $cdmaterials.
                vtf_data = None
                for _pak in paks:
                    vtf_data = self._find_vtf_for_mat(_pak, mat_name, arm_folder, cdmats)
                    if vtf_data:
                        break
                # 2) Fallback: материал → его VMT → $basetexture → VTF
                #    (покрывает материалы без прямого VTF, напр. pocket_watch_fg).
                if not vtf_data and cdmats:
                    vtf_data = self._resolve_vtf_via_vmt(paks, cdmats, mat_name)
                if not vtf_data:
                    logger.warning(f"[3D] Текстура для материала '{mat_name}' не найдена")
                    continue

                png_path = self._vtf_data_to_png(vtf_data, mat_name)
                if not png_path:
                    continue
                # Краска материала ($blendtintbybasealpha) — у пяти стоковых
                # пушек (Cow Mangler, Lollichop, праздничные) окрашиваемые
                # места в текстуре тоже лежат почти чёрными
                vmt_tint.apply_to_png(
                    png_path, self.materials.tint_for(mat_name, cdmats))
                result[mat_name] = png_path
                logger.debug(f"[3D] Материал '{mat_name}' → {os.path.basename(png_path)}")

        except Exception as exc:
            logger.warning(f"[3D] Ошибка извлечения мульти-текстур: {exc}", exc_info=True)

        return result

    def _extract_blu_multi_textures_via_qc(self, mat_names: list) -> dict:
        """
        Для каждого материала из SMD ищет BLU-вариант через QC skinfamilies.

        Логика:
          1. Читает QC из _decomp_dir, парсит skin_families[0] (RED) и [1] (BLU).
          2. Для каждого mat_name ищет совпадение в skin_families[0] по индексу.
          3. Берёт соответствующее имя из skin_families[1] и ищет VTF в VPK.
          4. Декодирует VTF → PNG.

        Returns:
            {mat_name: png_path} — только для найденных BLU текстур.
            Пустой dict если BLU варианта нет.
        """
        if not self._decomp_dir or not mat_names:
            return {}

        model = self._model(self._decomp_dir)
        if model is None:
            return {}

        cdmaterials = model.cdmaterials
        layout = model.layout
        if not layout.second_row or not cdmaterials:
            logger.debug(
                "[3D] _extract_blu_multi_textures_via_qc: "
                "второй скин в QC не найден → нет BLU варианта"
            )
            return {}

        red_family = [t.lower() for t in layout.base_rows[0]]
        blu_family = layout.second_row

        result: dict = {}
        try:
            paks = self._reader.paks
            if not paks:
                return {}

            from src.data.player_characters import PLAYER_CHARACTERS
            arm_folder: Optional[str] = PLAYER_CHARACTERS.get(self.mode, {}).get("folder", "")

            for mat_name in mat_names:
                # Ищем mat_name в RED skin family (case-insensitive)
                mat_lower = mat_name.lower()
                try:
                    idx = red_family.index(mat_lower)
                except ValueError:
                    # Попытка частичного совпадения (конец строки)
                    idx = next(
                        (i for i, r in enumerate(red_family) if mat_lower.endswith(r) or r.endswith(mat_lower)),
                        -1
                    )

                if idx < 0 or idx >= len(blu_family):
                    logger.debug(f"[3D] BLU multi: mat '{mat_name}' не найден в RED family")
                    continue

                blu_tex_name = blu_family[idx]
                blu_lower = blu_tex_name.lower()
                vtf_data: Optional[bytes] = None

                # Поиск VTF в VPK
                for cdmat in cdmaterials:
                    vtf_candidate = f"materials/{cdmat}/{blu_lower}.vtf"
                    for pak in paks:
                        try:
                            vtf_data = pak[vtf_candidate].read()
                            logger.debug(f"[3D] BLU multi VTF: {vtf_candidate}")
                            break
                        except KeyError:
                            continue
                    if vtf_data:
                        break

                # Fallback через arm_folder
                if not vtf_data and arm_folder:
                    candidate = f"materials/models/player/{arm_folder}/{blu_lower}.vtf"
                    for pak in paks:
                        try:
                            vtf_data = pak[candidate].read()
                            logger.debug(f"[3D] BLU multi VTF (arm_folder): {candidate}")
                            break
                        except KeyError:
                            continue

                # Fallback: тот же поиск, что и для RED (_find_vtf_for_mat умеет
                # отрезать суффикс _red/_blue → scout_head_blue ищет scout_head.vtf,
                # т.к. голова персонажа — общий файл, тонируемый под команду в VMT).
                if not vtf_data:
                    for pak in paks:
                        vtf_data = self._find_vtf_for_mat(pak, blu_tex_name, arm_folder)
                        if vtf_data:
                            logger.debug(f"[3D] BLU multi VTF (find_vtf_for_mat): {blu_tex_name}")
                            break

                if not vtf_data:
                    logger.debug(f"[3D] BLU multi: VTF не найден для '{blu_tex_name}'")
                    # VTF нет, но маппинг имён всё равно записываем — чтобы карточки
                    # показывали BLU-имена даже без превью-текстуры.
                    if blu_tex_name.lower() != mat_name.lower():
                        result[mat_name] = (None, blu_tex_name)
                    continue

                # Декодируем VTF → PNG (первый кадр)
                png_path = self._vtf_data_to_png(vtf_data, f"blu_{mat_name}")
                if not png_path:
                    continue
                result[mat_name] = (png_path, blu_tex_name)
                logger.debug(
                    f"[3D] BLU multi: '{mat_name}' → '{blu_tex_name}' "
                    f"({os.path.basename(png_path)})"
                )

        except Exception as exc:
            logger.warning(f"[3D] _extract_blu_multi_textures_via_qc: {exc}", exc_info=True)

        # result: {red_mat_name: (blu_png_path, blu_display_name)}
        return result

    def _extract_fixed_extra_textures(self) -> dict:
        """
        Извлекает доп. текстуры предмета, заданные ФИКСИРОВАННЫМ путём в VPK
        (вне QC и геометрии модели) — см. WEAPON_EXTRA_TEXTURES.

        Пример: HUD-вставки Dead Ringer pocket_watch_fg/bg по пути
        materials/vgui/replay/thumbnails/deadringer/...

        Returns:
            {material_name: png_path} для найденных текстур.
        """
        from src.data.weapons import WEAPON_EXTRA_TEXTURES
        extras = WEAPON_EXTRA_TEXTURES.get(self.weapon_key, [])
        if not extras:
            return {}

        result: dict = {}
        try:
            paks = self._reader.paks

            for ex in extras:
                # 1) Прямой VTF по указанному пути.
                data = None
                for pak in paks:
                    try:
                        data = pak[ex["vpk"]].read()
                        break
                    except KeyError:
                        continue
                # 2) Через VMT → $basetexture (часто VTF лежит не там, куда смотрит HUD).
                if not data and ex.get("vmt"):
                    for pak in paks:
                        try:
                            vmt_raw = pak[ex["vmt"]].read()
                        except KeyError:
                            continue
                        base = GameVpkReader.parse_basetexture(
                            vmt_raw.decode("utf-8", errors="replace"))
                        if base:
                            for pak2 in paks:
                                data = GameVpkReader.find_vtf_in_pak(pak2, base)
                                if data:
                                    break
                        if data:
                            break

                png = self._vtf_data_to_png(data, ex["name"]) if data else None
                # 3) Слот предлагаем ВСЕГДА — даже без оригинала (пустой плейсхолдер).
                if not png:
                    png = self._make_blank_png(ex["name"])
                    logger.info(f"[3D] Фикс. доп. текстура без оригинала — пустой слот: {ex['name']}")
                if png:
                    result[ex["name"]] = png
        except Exception as exc:
            logger.warning(f"[3D] Ошибка извлечения фикс. доп. текстур: {exc}", exc_info=True)
        return result

    def _extract_texturegroup_extras(self, mat_names: list) -> dict:
        """
        Материалы из QC $texturegroup (колонки 1+), которых НЕТ среди материалов
        геометрии (mat_names) — напр. smiley у гранатомёта демомена. Сборка их
        предлагает (из $texturegroup), поэтому показываем их карточками и в 2D,
        чтобы списки совпадали (единый источник — тот же блэклист).

        Текстуру резолвим через $cdmaterials; если не нашли — пустой слот.

        Returns:
            {material_name: png_path} для материалов вне геометрии.
        """
        if not self._decomp_dir:
            return {}
        try:
            model = self._model(self._decomp_dir)
            if model is None:
                return {}
            from src.services.model_build_service import ModelBuildService
            from src.data.material_filter import is_editable_material, is_user_blacklisted
            tg = ModelBuildService.extract_texturegroup_structure(model.qc_path)
            extras = tg.get('extra_materials', []) or []
            known = {m.lower() for m in mat_names}
            # Редактируемые (не служебные) и не скрытые пользовательским ЧС,
            # которых нет в геометрии (иначе материал уже показан обычным путём).
            missing = [m for m in extras
                       if m.lower() not in known and is_editable_material(m)
                       and not is_user_blacklisted(m)]

            # Доп. косметические стили (bloody/clean) — материалы строк-стилей,
            # которых нет в геометрии. Показываем карточкой, чтобы стиль можно было
            # перекрасить (сборка пакует их через blu_row). Только настоящие стили
            # (selector_spec.styles), не команда/австралий.
            _lay = model.layout
            for _lbl, _idx in qc_skin_parser.selector_spec(_lay).styles:
                if 0 <= _idx < len(_lay.all_rows):
                    for _m in _lay.all_rows[_idx]:
                        ml = _m.lower()
                        if (ml not in known and is_editable_material(_m)
                                and not is_user_blacklisted(_m) and _m not in missing):
                            missing.append(_m)

            if not missing:
                return {}
            logger.info(f"[3D] Доп. материалы из $texturegroup (вне геометрии): {missing}")
            resolved = self._extract_multi_textures(missing)
            result: dict = {}
            for m in missing:
                png = resolved.get(m) or self._make_blank_png(m)
                if png:
                    result[m] = png
            return result
        except Exception as exc:
            logger.debug(f"[3D] Не удалось собрать доп. материалы $texturegroup: {exc}")
            return {}

    def _extract_texturegroup_misc_extras(self, mat_names: list) -> dict:
        """Служебные (блэклист) материалы из QC $texturegroup по ВСЕМ строкам,
        которых НЕТ в геометрии — напр. eyeball_invun, *_invun, *_zombie у тела
        персонажа (они используются другими скинами, поэтому в рендер скина 0 не
        попадают). Нужны для селектора «Прочее» в 2D: показываем их оригинальные
        игровые текстуры как превью, чтобы пользователь мог опционально заменить.

        Returns: {material_name: png_path} (с прозрачным плейсхолдером, если
        оригинал по путям модели не нашёлся).
        """
        if not self._decomp_dir:
            return {}
        try:
            model = self._model(self._decomp_dir)
            if model is None:
                return {}
            from src.data.material_filter import is_editable_material, is_user_blacklisted
            _lay = model.layout
            known = {m.lower() for m in mat_names}
            seen: set = set()
            misc: list = []
            for _row in (_lay.all_rows or []):
                for _m in _row:
                    ml = (_m or '').lower()
                    if not ml or ml in known or ml in seen:
                        continue
                    # Служебные (не основные) и НЕ скрытые пользовательским ЧС.
                    if not is_editable_material(_m) and not is_user_blacklisted(_m):
                        seen.add(ml)
                        misc.append(_m)
            if not misc:
                return {}
            logger.info(f"[3D] Служебные материалы $texturegroup (для «Прочее»): {misc}")
            resolved = self._extract_multi_textures(misc)
            result: dict = {}
            for m in misc:
                png = resolved.get(m) or self._make_blank_png(m)
                if png:
                    result[m] = png
            return result
        except Exception as exc:
            logger.debug(f"[3D] Не удалось собрать служебные материалы $texturegroup: {exc}")
            return {}

    def _make_blank_png(self, name: str) -> Optional[str]:
        """Создаёт пустой прозрачный PNG-плейсхолдер (для слота без оригинала)."""
        try:
            from PIL import Image
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            png_path = os.path.join(self._preview_dir, f"{name}.png")
            img.save(png_path)
            return png_path
        except Exception as exc:
            logger.debug(f"[3D] Не удалось создать плейсхолдер для {name}: {exc}")
            return None

    def _resolve_vtf_via_vmt(self, paks: list, cdmaterials: list, mat_name: str) -> Optional[bytes]:
        """
        Резолвит VTF материала через его VMT: {cdmat}/{mat}.vmt → $basetexture → VTF.

        Нужно для материалов, у которых текстура задаётся через VMT, а не лежит
        по «угадываемому» пути (напр. центральная вставка Dead Ringer
        'pocket_watch_fg'). VMT и VTF могут быть в разных VPK — ищем по всем.
        """
        mat_lower = mat_name.lower()
        for pak in paks:
            info = GameVpkReader.find_vmt_in_pak(pak, cdmaterials, mat_lower)
            if not info:
                continue
            base = GameVpkReader.parse_basetexture(info[1])
            if not base:
                continue
            for pak2 in paks:
                data = GameVpkReader.find_vtf_in_pak(pak2, base)
                if data:
                    logger.debug(f"[3D] '{mat_name}' резолвлен через VMT → {base}")
                    return data
        return None

    def _get_qc_cdmaterials(self) -> list:
        """
        Возвращает список путей $cdmaterials из QC декомпилированной модели
        (без 'materials/' и слешей по краям). Кэшируется. Нужен чтобы найти
        текстуры ВСЕХ материалов оружия по авторитетным путям из QC.
        """
        if getattr(self, '_cached_cdmaterials', None) is not None:
            return self._cached_cdmaterials
        cdmats: list = []
        try:
            model = self._model(getattr(self, '_decomp_dir', None))
            if model:
                cdmats = model.cdmaterials
        except Exception as exc:
            logger.debug(f"[3D] Не удалось распарсить $cdmaterials: {exc}")
        self._cached_cdmaterials = cdmats
        return cdmats

    def _find_vtf_for_mat(
        self, pak, mat_name: str, arm_folder: Optional[str],
        cdmaterials: Optional[list] = None,
    ) -> Optional[bytes]:
        """Ищет VTF-данные для имени материала из SMD."""
        paths: list = []
        mat_lower = mat_name.lower()

        # Приоритет: папка рук игрока (materials/models/player/{folder}/)
        # Пробуем оба варианта: оригинальный регистр и lowercase,
        # т.к. SMD может использовать mixed-case (engineer_handL), а VTF в VPK
        # хранится в lowercase (engineer_handl).
        if arm_folder:
            paths.append(f"materials/models/player/{arm_folder}/{mat_name}.vtf")
            if mat_lower != mat_name:
                paths.append(f"materials/models/player/{arm_folder}/{mat_lower}.vtf")

            # Fallback для головных текстур персонажей (кроме Шпиона):
            # SMD ссылается на {class}_head_red или {class}_head_blue,
            # но реальный VTF называется {class}_head.vtf (без командного суффикса).
            # Например: scout_head_red → scout_head.vtf
            #            demoman_head_red → demoman_head.vtf
            #            heavy_head_red  → heavy_head.vtf
            _TEAM_SUFFIXES = ("_red", "_blue")
            for suf in _TEAM_SUFFIXES:
                if mat_lower.endswith(suf):
                    base_no_team = mat_name[: -len(suf)]
                    base_no_team_lower = base_no_team.lower()
                    paths.append(
                        f"materials/models/player/{arm_folder}/{base_no_team}.vtf"
                    )
                    if base_no_team_lower != base_no_team:
                        paths.append(
                            f"materials/models/player/{arm_folder}/{base_no_team_lower}.vtf"
                        )
                    break

            # Fallback для sheen/overlay мешей: в TF2 эти материалы содержат
            # ту же геометрию рук, что и базовый материал, но рендерятся с
            # эффектом киллстрика. VTF для sheen в VPK нет — используем базовый.
            # Например: hvyweapon_hands_sheen → hvyweapon_hands.vtf
            _OVERLAY_SUFFIXES = ("_sheen2", "_sheen", "_overlay", "_fresnel")
            for suf in _OVERLAY_SUFFIXES:
                if mat_lower.endswith(suf):
                    base = mat_name[: -len(suf)]
                    base_lower = base.lower()
                    paths.append(
                        f"materials/models/player/{arm_folder}/{base}.vtf"
                    )
                    if base_lower != base:
                        paths.append(
                            f"materials/models/player/{arm_folder}/{base_lower}.vtf"
                        )
                    break

        # Пути из QC ($cdmaterials) — авторитетные: текстура лежит ровно там,
        # куда указывает модель. Покрывает вторую/третью текстуру оружия в
        # нестандартных папках (parts/, общая папка модели и т.п.).
        for cd in (cdmaterials or []):
            paths.append(f"materials/{cd}/{mat_name}.vtf")
            if mat_lower != mat_name:
                paths.append(f"materials/{cd}/{mat_lower}.vtf")

        # Стандартные пути оружий (fallback-угадывание)
        paths += [
            f"materials/models/workshop_partner/weapons/c_models/{mat_name}/{mat_name}.vtf",
            f"materials/models/weapons/c_models/{mat_name}/{mat_name}.vtf",
            f"materials/models/weapons/c_items/{mat_name}.vtf",
            f"materials/models/workshop/weapons/c_models/{mat_name}/{mat_name}.vtf",
        ]

        for path in paths:
            try:
                return pak[path].read()
            except KeyError:
                continue
        return None

    # ── QC-парсинг текстур (единая логика — см. qc_skin_parser) ─────────── #

    def _extract_blu_via_qc(self, decomp_dir: str, red_framerate: float,
                            mat_names: Optional[list] = None) -> tuple:
        """
        Извлекает BLU-вариант текстуры используя QC $texturegroup skinfamilies.

        Читает QC из decomp_dir, парсит skin family 1 (BLU),
        ищет соответствующие VTF в VPK (сначала прямой путь, затем через VMT).

        Args:
            mat_names: материалы, которые реально показаны в превью. Строка
                $texturegroup описывает ВСЮ модель, а показываем мы иногда лишь
                её часть (Dead Ringer рисуется вьюмоделью, где рядом с часами
                лежат руки шпиона) — без этого списка синей текстурой предмета
                становился первый попавшийся столбец, то есть чужие руки.

        Returns:
            (frame_paths: list[str], framerate: float)
            Пустой список если BLU варианта нет.
        """
        model = self._model(decomp_dir)
        if model is None:
            logger.debug(f"[3D] _extract_blu_via_qc: QC не найден в {decomp_dir}")
            return [], 0.0

        cdmaterials = model.cdmaterials
        layout = model.layout
        if not layout.second_row:
            logger.debug("[3D] _extract_blu_via_qc: второго скина в QC нет → нет BLU варианта")
            return [], 0.0

        # Переключатель RED/BLU показываем только для настоящей команды
        # (единый авторитет selector_spec.team — тот же, что у сборки), а не для
        # стилей вроде bloody/clean.
        if not qc_skin_parser.selector_spec(layout).team:
            logger.info(
                f"[3D] второй скин не является BLU-командой: {layout.second_row} "
                f"— стиль или вариант, переключатель команд не нужен"
            )
            return [], 0.0

        own = self._own_blu_names(model, mat_names)
        if own is None:
            blu_tex_names = layout.second_row      # сопоставить не с чем — как раньше
        elif not own:
            logger.info(
                f"[3D] {self.weapon_key}: столбцы модели в $texturegroup командными "
                f"не являются — BLU у предмета нет (строка {layout.second_row})"
            )
            return [], 0.0
        else:
            blu_tex_names = own

        logger.info(
            f"[3D] QC BLU skin family: cdmaterials={cdmaterials}, "
            f"tex_names={blu_tex_names}"
        )

        try:
            paks = self._reader.paks
            if not paks:
                return [], 0.0

            for tex_name in blu_tex_names:
                tex_lower = tex_name.lower()
                vtf_data: Optional[bytes] = None
                blu_look: Optional[tuple] = None

                # ── Метод 1: прямой путь materials/{cdmat}/{name}.vtf ─────── #
                for cdmat in cdmaterials:
                    vtf_candidate = f"materials/{cdmat}/{tex_lower}.vtf"
                    for pak in paks:
                        try:
                            vtf_data = pak[vtf_candidate].read()
                            logger.debug(f"[3D] BLU прямой VTF: {vtf_candidate}")
                            break
                        except KeyError:
                            continue
                    if vtf_data:
                        break

                # ── Метод 2: VMT → $baseTexture → VTF ────────────────────── #
                if not vtf_data and cdmaterials:
                    for pak in paks:
                        vmt_info = GameVpkReader.find_vmt_in_pak(
                            pak, cdmaterials, tex_lower
                        )
                        if vmt_info:
                            _, vmt_content = vmt_info
                            basetexture = GameVpkReader.parse_basetexture(vmt_content)
                            blu_look = (basetexture,
                                        vmt_tint.parse_tint(vmt_content))
                            if basetexture:
                                for pak2 in paks:
                                    vtf_data = GameVpkReader.find_vtf_in_pak(
                                        pak2, basetexture
                                    )
                                    if vtf_data:
                                        logger.debug(
                                            f"[3D] BLU через VMT: {basetexture}"
                                        )
                                        break
                            break

                if not vtf_data:
                    logger.debug(
                        f"[3D] BLU VTF не найден для '{tex_lower}' "
                        f"(cdmaterials={cdmaterials})"
                    )
                    continue

                # ── Декодируем все кадры из VTF ───────────────────────────── #
                from src.services import vtf_preview_service as _vps
                frame_paths = _vps.vtf_bytes_to_frame_pngs(
                    vtf_data, self._preview_dir, "texture_blu")
                if not frame_paths:
                    continue

                # Синий материал может отличаться от красного ТОЛЬКО краской
                # в VMT (329 стоковых шапок) — без её применения переключатель
                # команд показывал бы две одинаковые картинки
                if blu_look is not None:
                    for frame in frame_paths:
                        vmt_tint.apply_to_png(frame, blu_look[1])
                    # _red_looks хранит ResolvedMaterial — сравниваем по .look
                    first_red = next(iter(self._red_looks.values()), None)
                    if first_red is not None and vmt_tint.same_material_look(
                            first_red.look, blu_look):
                        logger.info(
                            "[3D] BLU-скин совпадает с RED и текстурой, и "
                            "краской — в игре команды не отличаются"
                        )
                        self.blu_same_as_red.emit()

                fps = red_framerate if len(frame_paths) > 1 else 0.0
                logger.info(
                    f"[3D] BLU via QC: {len(frame_paths)} frame(s) "
                    f"@ {fps:.1f} fps для {self.weapon_key}"
                )
                return frame_paths, fps

        except Exception as exc:
            logger.warning(f"[3D] _extract_blu_via_qc: {exc}", exc_info=True)

        return [], 0.0

    @staticmethod
    def _own_blu_names(model, mat_names: Optional[list]) -> Optional[list]:
        """Синие имена ТОЛЬКО тех столбцов, что принадлежат материалам модели.

        Команда в Source меняет материалы поколоночно, поэтому синюю пару надо
        брать из столбца СВОЕГО материала. Пробегать всю строку нельзя: в ней
        стоят и чужие столбцы (у вьюмодели часов рядом с самими часами лежат
        руки шпиона), и общие для команд — и первый же попавшийся `*_blue`
        уезжал предмету на текстуру.

        Returns:
            Список синих имён; пустой список — свои столбцы командными не
            оказались (BLU у предмета нет); None — сопоставить не удалось,
            решать вызывающему.
        """
        by_lower = {k.lower(): v for k, v in (model.team_map or {}).items()}
        if not by_lower or not mat_names:
            return None
        names: list = []
        matched = False
        for mat in mat_names:
            ml = (mat or "").lower()
            if not ml:
                continue
            blu = by_lower.get(ml)
            if blu is None:
                # Имена материалов SMD и $texturegroup иногда расходятся
                # префиксом пути — сверяем по хвосту, как в мульти-ветке.
                blu = next((v for k, v in by_lower.items()
                            if ml.endswith(k) or k.endswith(ml)), None)
            if blu is None:
                continue
            matched = True
            if not qc_skin_parser.is_shared_column(ml, blu) and blu not in names:
                names.append(blu)
        return names if matched else None

    def _extract_variant_via_qc(self, decomp_dir: str) -> Optional[str]:
        """
        Извлекает текстуру варианта оружия (Australium/Gold/Festive) из QC.

        Строку варианта выбирает qc_skin_parser.pick_preview_variant:
        приоритет у настоящего австралиума, затем прочие «внешние» варианты.

        Returns:
            Путь к PNG-файлу варианта или None если нет.
        """
        model = self._model(decomp_dir)
        if model is None:
            return None, None

        cdmaterials = model.cdmaterials
        layout = model.layout
        if not cdmaterials:
            return None, None

        variant_family = qc_skin_parser.pick_preview_variant(layout)
        if not variant_family:
            return None, None

        # Текстура варианта — col 0 этой строки
        variant_tex = variant_family[0].lower()
        logger.info(f"[3D] Обнаружен вариант оружия: {variant_tex}")

        try:
            paks = self._reader.paks

            vtf_data: Optional[bytes] = None
            for cdmat in cdmaterials:
                for pak in paks:
                    try:
                        vtf_data = pak[f"materials/{cdmat}/{variant_tex}.vtf"].read()
                        break
                    except KeyError:
                        continue
                if vtf_data:
                    break

            if not vtf_data:
                return None, None

            out = self._vtf_data_to_png(vtf_data, "texture_variant")
            if not out:
                return None, None
            logger.info(f"[3D] Вариант оружия извлечён: {out}")
            return out, variant_tex

        except Exception as exc:
            logger.warning(f"[3D] _extract_variant_via_qc: {exc}")
            return None, None

    # ── VMT-поиск: QC → VMT → $baseTexture → VTF ────────────────────────── #
    @property
    def materials(self) -> MaterialResolver:
        """Единая цепочка «материал → PNG» с кэшем на весь прогон."""
        if self._materials is None:
            self._materials = MaterialResolver(self._reader, self._preview_dir)
        return self._materials

    def _model(self, decomp_dir: Optional[str]):
        """Разбор QC этой папки — один раз за прогон (см. QcModel).

        None на входе (папки декомпиляции ещё нет) — None на выходе, чтобы
        вызывающим не приходилось проверять это перед каждым обращением.
        """
        if not decomp_dir:
            return None
        if decomp_dir not in self._models:
            self._models[decomp_dir] = qc_skin_parser.load_model(decomp_dir)
        return self._models[decomp_dir]

    def _vtf_data_to_png(self, vtf_data: bytes, name: str) -> Optional[str]:
        """
        Сохраняет VTF-байты как PNG в preview_dir.
        Возвращает путь к PNG или None при ошибке.
        """
        from src.services import vtf_preview_service as _vps
        return _vps.vtf_bytes_to_png(
            vtf_data, os.path.join(self._preview_dir, f"{name}.png"), self._preview_dir)

    def _extract_hat_blu_textures(self, decomp_dir: str, mat_names: list) -> dict:
        """
        BLU-текстуры шапки ПО МАТЕРИАЛАМ: {red_mat: (png | None, blu_mat_name)}.

        Шапка часто многоматериальная, и команда переключает НЕ ВСЁ. У
        hwn2022_alcoholic_automaton в $texturegroup четыре столбца, и линза в
        обеих строках одна и та же:

            { auto_1       auto       auto_1_blue auto_blue }
            { auto_1_blue  auto_blue  auto_1_blue auto_blue }

        Одна общая BLU-текстура (путь _extract_blu_via_qc) натягивала на
        линзу текстуру корпуса. Здесь каждый материал берёт свой столбец —
        те, что в обеих строках одинаковы, так и остаются прежними.

        Returns:
            {} — если второй скин не команда, QC не читается или ничего не нашли.
        """
        model = self._model(decomp_dir)
        if not model or not mat_names or not model.cdmaterials:
            return {}
        # Карта «столбец RED → столбец BLU»; пустая, если второй скин не
        # команда (стиль bloody/clean) — тот же авторитет, что у сборки
        by_lower = {k.lower(): v for k, v in model.team_map.items()}
        if not by_lower:
            return {}

        result: dict = {}
        for mat_name in mat_names:
            mat_lower = mat_name.lower()
            blu_name = by_lower.get(mat_lower)
            if blu_name is None:
                # Имена материалов SMD и $texturegroup иногда расходятся
                # префиксом пути — сверяем по хвосту, как в оружейном пути
                blu_name = next(
                    (v for k, v in by_lower.items()
                     if mat_lower.endswith(k) or k.endswith(mat_lower)), None)
            if blu_name is None:
                continue
            if qc_skin_parser.is_shared_column(mat_lower, blu_name):
                # Материал в обеих строках один и тот же: на BLU он остаётся
                # собой. Записываем это явно — по такой «ссылке на себя»
                # панель понимает, что карточку при смене команды не трогать.
                result[mat_lower] = (None, mat_name)
                continue

            blu = self.materials.resolve(blu_name, model.cdmaterials,
                                         out_name=f"blu_{mat_lower}")
            png_path = blu.png_path
            if png_path and blu.same_look(self._red_looks.get(mat_lower)):
                # Числится командным, а выглядит точно как RED — для панели
                # это такой же общий материал
                png_path, blu_name = None, mat_name
            elif not png_path:
                # Материал командный, но его текстуру в игре не нашли. Показать
                # нечего, и пометить его командным значит оставить пустое поле
                # у синей команды — честнее считать материал общим.
                logger.info(
                    f"[3D] BLU-текстура '{blu_name}' не найдена — материал "
                    f"'{mat_lower}' показываем общим для команд"
                )
                blu_name = mat_name
            result[mat_lower] = (png_path, blu_name)

        # Ни одной реальной BLU-текстуры — сообщать не о чем
        if not any(png for png, _ in result.values()):
            if result:
                logger.info(
                    "[3D] BLU-скин шапки не отличается от RED ни одной "
                    "текстурой — команды выглядят одинаково"
                )
                self.blu_same_as_red.emit()
            return {}
        return result

    def _extract_hat_textures_via_qc_vmt(
        self, decomp_dir: str, mat_names: list
    ) -> dict:
        """
        Текстуры шапки: материалы модели → цепочка VMT → $basetexture → VTF.

        Сама цепочка (включая командную краску из VMT) живёт в
        MaterialResolver — здесь только выбор материалов и запоминание того,
        как выглядит RED: по этому потом видно, отличается ли BLU-скин.

        Returns:
            {mat_name: png_path}  (пустой dict если ничего не нашлось)
        """
        model = self._model(decomp_dir)
        if not model or not model.cdmaterials:
            logger.warning(f"[3D] $cdmaterials не найден в QC: {decomp_dir}")
            return {}

        logger.info(
            f"[3D] Hat QC: cdmaterials={model.cdmaterials}, materials={mat_names}")

        result: dict = {}
        for mat_name in mat_names:
            mat_lower = mat_name.lower()
            res = self.materials.resolve(mat_lower, model.cdmaterials,
                                         out_name=f"hat_{mat_lower}")
            if res.ok:
                self._red_looks[mat_lower] = res
                result[mat_lower] = res.png_path
        return result

    def _extract_hat_texture_frames(self) -> tuple:
        """
        Fallback-метод: угадывает VTF-путь напрямую по имени MDL.

        Используется только если основной QC→VMT→VTF путь не дал результата.
        MDL-имя → имя материала (например hat_heavy.mdl → hat_heavy.vtf).

        Returns:
            (frame_paths: list[str], framerate: float)
        """
        try:
            _TF2_CLASSES = ["heavy", "scout", "soldier", "pyro",
                            "demoman", "engineer", "medic", "sniper", "spy"]
            mdl = self.weapon_key.replace("\\", "/").lower()

            # Если путь содержит %s — раскрываем во все классы
            if "%s" in mdl:
                mdl_candidates = []
                for cls in _TF2_CLASSES:
                    try:
                        v = mdl % cls
                    except (TypeError, ValueError):
                        v = mdl.replace("%s", cls)
                    if v not in mdl_candidates:
                        mdl_candidates.append(v)
            else:
                mdl_candidates = [mdl]

            # Строим список VTF-путей из всех MDL-кандидатов
            _WORKSHOP_SWAPS = [
                ("materials/models/player/items",
                 "materials/models/workshop_partner/player/items"),
                ("materials/models/player/items",
                 "materials/models/workshop/player/items"),
                ("materials/models/workshop_partner/player/items",
                 "materials/models/player/items"),
                ("materials/models/workshop/player/items",
                 "materials/models/player/items"),
            ]
            vtf_paths: list = []
            for mdl_c in mdl_candidates:
                base_no_ext = mdl_c[:-4] if mdl_c.endswith(".mdl") else mdl_c
                mat_base = "materials/" + base_no_ext
                v0 = mat_base + ".vtf"
                if v0 not in vtf_paths:
                    vtf_paths.append(v0)
                for src, dst in _WORKSHOP_SWAPS:
                    if src in mat_base:
                        v = mat_base.replace(src, dst) + ".vtf"
                        if v not in vtf_paths:
                            vtf_paths.append(v)

            # Ищем в текстурах VPK, затем в misc VPK (порядок reader.paks).
            vtf_data: Optional[bytes] = None
            for pak in self._reader.paks:
                for path in vtf_paths:
                    try:
                        vtf_data = pak[path].read()
                        logger.debug(f"[3D] Hat texture: {path}")
                        break
                    except KeyError:
                        continue
                if vtf_data:
                    break

            if not vtf_data:
                shown = vtf_paths[:4]
                logger.warning(
                    f"[3D] Текстура шапки не найдена (weapon_key={self.weapon_key}). "
                    f"Проверено путей: {len(vtf_paths)}, первые: {shown}"
                )
                return [], 0.0

            from src.services import vtf_preview_service as _vps
            frame_paths = _vps.vtf_bytes_to_frame_pngs(
                vtf_data, self._preview_dir, "hat_tex")
            return frame_paths, 0.0

        except Exception as exc:
            logger.warning(f"[3D] Не удалось извлечь текстуру шапки: {exc}")
            return [], 0.0

    def _extract_spy_mask_texture(self, mask_vtf_name: str) -> tuple:
        """Извлекает текстуру маски шпиона из VPK.

        Args:
            mask_vtf_name: имя VTF без расширения (напр. 'mask_spy', 'mask_scout')

        Returns:
            (frame_paths, framerate) — стандартный формат как у других методов.
        """
        try:
            from src.services import vtf_preview_service as _vps
            paks = _vps.open_vpks([self.textures_vpk_path, self.misc_vpk_path])
            vtf_data = _vps.read_from_vpks(
                paks, f"materials/models/player/spy/{mask_vtf_name}.vtf")
            if not vtf_data:
                logger.warning(f"[3D] Маска {mask_vtf_name}.vtf не найдена в VPK")
                return [], 0.0
            png_path = self._vtf_data_to_png(vtf_data, mask_vtf_name)
            if not png_path:
                return [], 0.0
            logger.info(f"[3D] Маска шпиона извлечена: {png_path}")
            return [png_path], 0.0
        except Exception as exc:
            logger.warning(f"[3D] _extract_spy_mask_texture: {exc}", exc_info=True)
            return [], 0.0

    def _extract_texture_frames(self) -> tuple:
        """
        Извлекает VTF текстуру из VPK.

        Если VTF содержит несколько кадров (анимированная текстура) —
        сохраняет каждый кадр отдельным PNG и читает framerate из VMT.

        Returns:
            (frame_paths: list[str], framerate: float)
            frame_paths пустой если текстура не найдена.
        """
        if self.mode == "hat":
            return self._extract_hat_texture_frames()

        # ── Режим масок шпиона: извлекаем mask_spy.vtf по умолчанию ─────── #
        if self.kind.is_spy_mask:
            return self._extract_spy_mask_texture("mask_spy")

        try:
            from src.data.weapons import WEAPON_TEXTURE_PATHS

            wk = self.weapon_key
            _standard = [
                f"materials/models/workshop_partner/weapons/c_models/{wk}/{wk}.vtf",
                f"materials/models/weapons/c_models/{wk}/{wk}.vtf",
                # c_items оружия хранят текстуру плоско: c_items/{name}.vtf (без подпапки)
                f"materials/models/weapons/c_items/{wk}.vtf",
                f"materials/models/workshop/weapons/c_models/{wk}/{wk}.vtf",
            ]
            # Нестандартные пути проверяем первыми
            vtf_search = WEAPON_TEXTURE_PATHS.get(wk, []) + _standard
            vmt_search = [p.replace(".vtf", ".vmt") for p in vtf_search]

            paks_tex = self._reader.paks
            pak = paks_tex[0] if paks_tex else None
            vtf_data: Optional[bytes] = None

            # ── Сначала — путь из QC ТОЙ модели, которую показываем ──────── #
            # У части оружия в игре ДВЕ версии: старая в models/weapons/c_items
            # и мастерская в models/workshop/weapons/c_models. Геометрию мы
            # берём по MDL модели, а список ниже перебирается по порядку, и
            # c_items стоит в нём раньше workshop — у c_shortstop и
            # c_soda_popper из-за этого бралась текстура 512×512 от СТАРОЙ
            # версии, а развёртка была от мастерской. Текстура не совпадала с
            # моделью. $cdmaterials из QC указывает на материалы именно той
            # модели, поэтому спрашиваем его первым.
            if self._decomp_dir:
                vtf_data = self._extract_red_texture_via_qc(paks_tex)
                if vtf_data:
                    logger.debug(f"3D Preview текстура: по $cdmaterials из QC")

            if pak and not vtf_data:
                for path in vtf_search:
                    try:
                        vtf_data = pak[path].read()
                        logger.debug(f"3D Preview текстура: {path}")
                        break
                    except KeyError:
                        continue

            if not vtf_data:
                logger.warning(f"Текстура для {self.weapon_key} не найдена в VPK")
                return [], 0.0

            from src.services import vtf_preview_service as _vps
            frame_paths = _vps.vtf_bytes_to_frame_pngs(
                vtf_data, self._preview_dir, "texture")

            # Краска из VMT: без неё окрашиваемые места показываются чёрными
            tint = self._tint_from_vmt_paths(paks_tex, vmt_search)
            if tint is not None:
                for frame in frame_paths:
                    vmt_tint.apply_to_png(frame, tint)

            # Framerate из VMT
            framerate = 0.0
            if len(frame_paths) > 1:
                framerate = self._read_vmt_framerate(
                    paks_tex[0] if paks_tex else None, vmt_search
                )
                logger.info(
                    f"Анимированная текстура: {len(frame_paths)} кадров "
                    f"@ {framerate:.1f} fps для {self.weapon_key}"
                )

            return frame_paths, framerate

        except Exception as exc:
            logger.warning(f"Не удалось извлечь текстуру для 3D Preview: {exc}")
            return [], 0.0

    def _extract_red_texture_via_qc(self, paks: list) -> Optional[bytes]:
        """
        Fallback: ищет RED (skin 0) текстуру через QC $cdmaterials.

        Используется когда стандартные пути _extract_texture_frames не нашли VTF.
        Аналогично тому, как _extract_blu_via_qc ищет BLU, только читает
        skin_families[0] (или weapon_key если texturegroup отсутствует).

        Returns:
            VTF-байты или None.
        """
        if not self._decomp_dir or not paks:
            return None

        model = self._model(self._decomp_dir)
        if model is None:
            return None

        cdmaterials = model.cdmaterials
        if not cdmaterials:
            return None

        # RED-текстуры: первая строка группы (или weapon_key как единственный кандидат)
        rows = model.layout.all_rows
        if rows:
            red_tex_names = [t for t in rows[0] if t]
        else:
            red_tex_names = [self.weapon_key]

        logger.debug(
            f"[3D] RED via QC: cdmaterials={cdmaterials}, "
            f"red_tex_names={red_tex_names}"
        )

        for tex_name in red_tex_names:
            tex_lower = tex_name.lower()
            for cdmat in cdmaterials:
                vtf_candidate = f"materials/{cdmat}/{tex_lower}.vtf"
                for pak in paks:
                    try:
                        data = pak[vtf_candidate].read()
                        logger.info(f"[3D] RED texture via QC: {vtf_candidate}")
                        return data
                    except KeyError:
                        continue

            # Если прямой путь не нашёл — пробуем через VMT → $baseTexture
            for pak in paks:
                vmt_info = GameVpkReader.find_vmt_in_pak(pak, cdmaterials, tex_lower)
                if vmt_info:
                    _, vmt_content = vmt_info
                    basetexture = GameVpkReader.parse_basetexture(vmt_content)
                    if basetexture:
                        for pak2 in paks:
                            data = GameVpkReader.find_vtf_in_pak(pak2, basetexture)
                            if data:
                                logger.info(
                                    f"[3D] RED texture via QC→VMT: {basetexture}"
                                )
                                return data

        return None

    def _extract_blu_texture_frames(self, red_framerate: float) -> tuple:
        """
        Пробует найти BLU-вариант текстуры (суффикс _blue) в VPK.

        Возвращает (frame_paths: list[str], framerate: float).
        Если BLU текстура не найдена — возвращает ([], 0.0).
        """
        try:
            from src.data.weapons import WEAPON_TEXTURE_PATHS

            wk = self.weapon_key
            _extra_blu = [
                p.replace(".vtf", "_blue.vtf")
                for p in WEAPON_TEXTURE_PATHS.get(wk, [])
            ]
            _std_blu = [
                f"materials/models/workshop_partner/weapons/c_models/{wk}/{wk}_blue.vtf",
                f"materials/models/weapons/c_models/{wk}/{wk}_blue.vtf",
                # c_items оружия хранят текстуру плоско: c_items/{name}_blue.vtf
                f"materials/models/weapons/c_items/{wk}_blue.vtf",
                f"materials/models/workshop/weapons/c_models/{wk}/{wk}_blue.vtf",
            ]
            blu_vtf_search = _extra_blu + _std_blu

            vtf_data: Optional[bytes] = None
            for path in blu_vtf_search:
                vtf_data = self._reader.read(path)
                if vtf_data:
                    logger.debug(f"3D Preview BLU текстура: {path}")
                    break

            if not vtf_data:
                return [], 0.0

            from src.services import vtf_preview_service as _vps
            frame_paths = _vps.vtf_bytes_to_frame_pngs(
                vtf_data, self._preview_dir, "texture_blu")
            if not frame_paths:
                return [], 0.0

            # Используем тот же framerate что и у RED (из VMT)
            fps = red_framerate if len(frame_paths) > 1 else 0.0
            logger.info(
                f"BLU текстура найдена: {len(frame_paths)} кадров "
                f"@ {fps:.1f} fps для {self.weapon_key}"
            )
            return frame_paths, fps

        except Exception as exc:
            logger.debug(f"BLU текстура не найдена для {self.weapon_key}: {exc}")
            return [], 0.0

    def _read_vmt_framerate(self, pak, vmt_search: list) -> float:
        """Ищет animatedtextureframerate в VMT файле из VPK (общий парсер)."""
        from src.services import vtf_preview_service as _vps
        return _vps.read_vmt_framerate(pak, vmt_search)

    def _tint_from_vmt_paths(self, paks: list, vmt_search: list):
        """Краска из первого найденного VMT по списку путей; None — нет."""
        for pak in paks or []:
            for path in vmt_search:
                try:
                    return vmt_tint.parse_tint(
                        pak[path].read().decode("utf-8", "replace"))
                except KeyError:
                    continue
                except Exception:
                    return None
        return None
