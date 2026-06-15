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
import shutil
import tempfile
from typing import Optional

from PySide6.QtCore import QThread, Signal

from src.data.weapons import WEAPON_MDL_PATHS
from src.services import decompile_cache
from src.services import qc_skin_parser
from src.services.model_build_service import ModelBuildService
from src.services.tf2_paths import TF2Paths
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class Preview3DWorker(QThread):
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
        self.misc_vpk_path     = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self._preview_dir: Optional[str] = None
        self._decomp_dir:  Optional[str] = None  # папка с декомпилированными QC/SMD
        self._hat_decomp_dir: Optional[str] = None  # алиас для режима hat
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
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
            if self.mode == "hat":
                self._hat_decomp_dir = self._decomp_dir
            if self.isInterruptionRequested():
                return

            # ── 2. OBJ ────────────────────────────────────────────────────── #
            self.progress.emit(self._p['converting'])
            obj_path = os.path.join(self._preview_dir, "model.obj")
            from src.services.smd_to_obj_service import SmdToObjService
            from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES

            # Ищем bodygroup SMDs в той же папке (например c_righthand_bodygroup.smd)
            bodygroup_smds = self._find_bodygroup_smds(smd_path)
            if bodygroup_smds:
                logger.info(
                    f"[3D] Найдены bodygroup SMD: "
                    f"{[os.path.basename(b) for b in bodygroup_smds]}"
                )

            from src.data.player_characters import PLAYER_BODY_MODE_KEYS as _PBK
            # Персонажи TF2 компилируются с $upaxis Y — SMD уже Y-up, конвертацию Z→Y не делаем
            _source_zup = self.mode not in _PBK

            # Превью-фильтр материалов: для моделей, где надо показать только часть
            # (напр. Dead Ringer на viewmodel с руками — оставляем только часы).
            _include_mats = None
            from src.data.weapons import PREVIEW_MAT_WHITELIST
            _wl = PREVIEW_MAT_WHITELIST.get(self.weapon_key)
            if _wl:
                _all_mats = self._scan_smd_mat_names([smd_path] + bodygroup_smds)
                _keep = {m for m in _all_mats if any(s in m.lower() for s in _wl)}
                if _keep:
                    _include_mats = _keep
                    logger.info(f"[3D] Превью-фильтр {self.weapon_key}: оставляем меши {_keep}")
                else:
                    logger.warning(
                        f"[3D] Whitelist {_wl} не совпал ни с одним материалом "
                        f"({_all_mats}) — показываю всю модель"
                    )

            ok, mat_names = SmdToObjService.convert(
                smd_path, obj_path,
                include_mats=_include_mats,
                extra_smd_paths=bodygroup_smds,
                source_zup=_source_zup,
            )
            if not ok:
                self.failed.emit(self._p['conv_error'])
                return
            if self.isInterruptionRequested():
                return

            # ── 3. Текстура ───────────────────────────────────────────────── #
            self.progress.emit(self._p['texture'])

            from src.data.player_characters import PLAYER_BODY_MODE_KEYS
            is_multi_tex_mode = self.mode in HAND_MODE_KEYS or self.mode in PLAYER_BODY_MODE_KEYS
            if is_multi_tex_mode and mat_names:
                # Режим рук / скина персонажа: мульти-материал — каждый меш получает свою текстуру
                tex_map = self._extract_multi_textures(mat_names)
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
                                self._decomp_dir, 0.0
                            )
                            if blu_paths:
                                self.blu_ready.emit(blu_paths, blu_fps)
                    except Exception as _exc:
                        logger.debug(f"[3D] BLU detection (multi-tex): {_exc}")

            elif self.mode == "hat":
                # ── Шапки: QC → VMT → $baseTexture → VTF ─────────────────── #
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

                # ── BLU для шапки (через QC skinfamilies skin 1) ─────────── #
                if _qc_dir:
                    blu_paths, blu_fps = self._extract_blu_via_qc(_qc_dir, 0.0)
                    if blu_paths:
                        self.blu_ready.emit(blu_paths, blu_fps)

            else:
                # Обычное оружие
                # Доп. текстуры по фиксированному пути (вне QC/модели), напр.
                # HUD-вставки Dead Ringer (pocket_watch_fg/bg).
                fixed_extras = self._extract_fixed_extra_textures()
                # Материалы из QC $texturegroup, которых нет в геометрии
                # (напр. smiley у гранатомёта) — чтобы карточки 2D совпадали
                # с тем, что предлагает сборка.
                tg_extras = self._extract_texturegroup_extras(mat_names)

                if len(mat_names) > 1:
                    # ── Мульти-материальное оружие (shell, scope и т.п.) ─────── #
                    tex_map = self._extract_multi_textures(mat_names)
                    if fixed_extras:
                        tex_map.update(fixed_extras)
                    if tg_extras:
                        tex_map.update(tg_extras)
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
                if self._decomp_dir:
                    blu_paths, blu_fps = self._extract_blu_via_qc(
                        self._decomp_dir, framerate
                    )
                    # Вариантные строки (Australium/Gold/Festive) проверяем
                    # НЕЗАВИСИМО от BLU: у большинства австралиум-оружий
                    # (ракетница и т.п.) есть И команды, И gold-строки —
                    # раньше «if not blu_paths» полностью скрывал вариант.
                    aus_path, aus_mat = self._extract_variant_via_qc(self._decomp_dir)
                    if aus_path:
                        self.australium_ready.emit(aus_path, aus_mat or "")
                # Fallback: прямой поиск {wk}_blue.vtf
                if not blu_paths:
                    blu_paths, blu_fps = self._extract_blu_texture_frames(framerate)
                if blu_paths:
                    self.blu_ready.emit(blu_paths, blu_fps)

        except Exception as exc:
            logger.error(f"Preview3DWorker: {exc}", exc_info=True)
            self.failed.emit(str(exc))

    # ── Получение SMD ─────────────────────────────────────────────────────── #

    def _get_reference_smd(self) -> Optional[str]:
        """Возвращает reference SMD из кэша или после декомпиляции."""
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS as _PBK, SPY_MASK_MODE_KEY as _SMK
        from src.data.weapons import PREVIEW_MDL_OVERRIDE
        _override = PREVIEW_MDL_OVERRIDE.get(self.weapon_key)
        if self.mode == "hat" or self.mode in _PBK or self.mode == _SMK:
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

        cached = decompile_cache.get_cached_decompile(
            self.weapon_key, self.misc_vpk_path, mdl_rel
        )
        if cached:
            logger.info(f"3D Preview: кэш декомпила для {self.weapon_key}")
            return self._find_reference_smd(cached)

        return self._extract_and_decompile(mdl_rel)

    def _extract_and_decompile(self, mdl_rel_hint: str) -> Optional[str]:
        """Извлекает MDL из VPK и декомпилирует через Crowbar."""
        from src.services.extract_model_service import ExtractModelService

        self.progress.emit(self._p['extracting'])

        # ── Диагностика: проверяем доступность VPK и инструментов ─────────── #
        if not os.path.exists(self.misc_vpk_path):
            logger.error(f"[3D] misc VPK не найден: {self.misc_vpk_path}")
            self.failed.emit(f"VPK not found: {self.misc_vpk_path}")
            return None

        crowbar = TF2Paths.get_crowbar_path()
        crowbar_abs = os.path.abspath(crowbar)
        if not os.path.exists(crowbar_abs):
            logger.error(f"[3D] Crowbar не найден: {crowbar_abs}")
            self.failed.emit(f"Crowbar not found: {crowbar_abs}")
            return None

        logger.info(f"[3D] cwd={os.getcwd()} | crowbar={crowbar_abs} | vpk={self.misc_vpk_path}")

        from src.data.player_characters import PLAYER_BODY_MODE_KEYS as _PBK, SPY_MASK_MODE_KEY as _SMK
        from src.data.weapons import PREVIEW_MDL_OVERRIDE
        if self.mode == "hat":
            from src.services.tf2_paths import build_hat_mdl_candidates
            paths_to_try = build_hat_mdl_candidates(mdl_rel_hint)
        elif self.mode in _PBK or self.mode == _SMK or self.weapon_key in PREVIEW_MDL_OVERRIDE:
            # Персонажи, маски шпиона и превью-подмены: прямой путь (weapon_key —
            # это уже полный путь MDL, не ключ из WEAPON_MDL_PATHS).
            paths_to_try = [mdl_rel_hint]
        else:
            from src.data.weapon_model_index import tf2_root_from_misc_vpk
            _tf2_root = tf2_root_from_misc_vpk(self.misc_vpk_path)
            paths_to_try = ExtractModelService._build_paths_to_try(
                self.mode, self.weapon_key, _tf2_root
            )

        found_rel: Optional[str] = None
        for path in paths_to_try:
            if self.isInterruptionRequested():
                return None
            try:
                if TF2VPKExtractService.check_mdl_exists(self.misc_vpk_path, path):
                    found_rel = path
                    logger.info(f"[3D] MDL найден: {path}")
                    break
            except Exception as e:
                logger.debug(f"[3D] check_mdl_exists ошибка для {path}: {e}")
                continue

        if not found_rel:
            logger.warning(f"[3D] MDL не найден в VPK для {self.weapon_key}. Пробовали: {paths_to_try[:3]}")
            return None

        try:
            mdl_dir = tempfile.mkdtemp(prefix="tf2sg_mdl_")
            extracted = TF2VPKExtractService.extract_file_set(
                self.misc_vpk_path, found_rel, mdl_dir
            )
            mdl_file = next((f for f in extracted if f.endswith(".mdl")), None)
            if not mdl_file:
                logger.error(f"[3D] MDL файл не найден после извлечения: {extracted}")
                shutil.rmtree(mdl_dir, ignore_errors=True)
                return None

            if self.isInterruptionRequested():
                shutil.rmtree(mdl_dir, ignore_errors=True)
                return None

            self.progress.emit(self._p['decompiling'])
            decomp_dir = tempfile.mkdtemp(prefix="tf2sg_decomp_")
            logger.info(f"[3D] Запускаем Crowbar: mdl={mdl_file} → {decomp_dir}")
            ModelBuildService.decompile(mdl_file, decomp_dir, crowbar)
            logger.info(f"[3D] Crowbar завершён успешно")

            cached_dir = decompile_cache.save_to_cache(
                self.weapon_key, self.misc_vpk_path, found_rel, decomp_dir
            )

            shutil.rmtree(mdl_dir, ignore_errors=True)
            # Дальше работаем с копией в кэше, а temp-папку удаляем —
            # иначе tf2sg_decomp_* копились бы в %TEMP% бесконечно.
            if cached_dir:
                shutil.rmtree(decomp_dir, ignore_errors=True)
                return self._find_reference_smd(cached_dir)
            return self._find_reference_smd(decomp_dir)

        except Exception as exc:
            logger.error(f"[3D] Ошибка декомпиляции для {self.weapon_key}: {exc}", exc_info=True)
            self.failed.emit(f"Decompile error: {exc}")
            return None

    def _find_reference_smd(self, directory: str) -> Optional[str]:
        """Находит reference SMD (исключая physics/anim) в директории."""
        _SKIP = ("physics", "phys", "anim", "idle", "pose")

        def skip(path: str) -> bool:
            return any(kw in os.path.basename(path).lower() for kw in _SKIP)

        # ── Персонажи TF2: проверяем ДО *_reference.smd ───────────────────── #
        # Причина: у персонажей bodygroup'ы (рюкзак медика medipack_reference.smd,
        # шапка и т.п.) тоже имеют _reference в имени и алфавитно могут идти раньше
        # основного тела. Поэтому для персонажей сразу ищем *_morphs_low.smd.
        #
        # weapon_key для персонажей = полный MDL путь: "models/player/medic.mdl".
        # Стэм файла ("medic", "demo", ...) — правильное короткое имя класса,
        # именно так Crowbar называет декомпилированные SMD файлы.
        # Важно: у демомена MDL называется demo.mdl, а не demoman.mdl.
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS, SPY_MASK_MODE_KEY

        # ── Режим масок шпиона: загружаем spy_mask.smd (bodygroup) ─────────── #
        if self.mode == SPY_MASK_MODE_KEY:
            mask_smd = os.path.join(directory, "spy_mask.smd")
            if os.path.exists(mask_smd):
                logger.debug(f"[3D] spy_mask.smd найден")
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

        # Все доп. body-SMD из QC (исключая основной/physics/anim — это делает сервис).
        try:
            qcs = glob.glob(os.path.join(directory, "*.qc"))
            if qcs:
                from src.services.model_build_service import ModelBuildService
                for smd in ModelBuildService.extract_extra_body_smds(qcs[0], self.weapon_key):
                    found.add(smd)
        except Exception as exc:
            logger.debug(f"[3D] Не удалось собрать part-SMD из QC: {exc}")

        # Не включаем сам reference (он уже основной)
        found.discard(os.path.abspath(reference_smd_path))
        found.discard(reference_smd_path)
        return sorted(found)

    @staticmethod
    def _scan_smd_mat_names(smd_paths: list) -> set:
        """
        Быстрое сканирование имён материалов из нескольких SMD файлов.

        Читает только имена материалов (без парсинга вершин) — в 10-30 раз
        быстрее чем полный _parse_triangles_by_mat.

        Returns:
            Множество всех имён материалов из всех SMD файлов.
        """
        import re
        result: set = set()
        for path in smd_paths:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                m = re.search(r"\btriangles\b(.*?)\bend\b", content,
                              re.DOTALL | re.IGNORECASE)
                if not m:
                    continue
                lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
                # Каждые 4 строки: имя_материала, вершина1, вершина2, вершина3
                result.update(lines[i] for i in range(0, len(lines), 4))
            except Exception:
                pass
        return result

    # ── Извлечение нескольких текстур (мульти-материал) ──────────────────── #

    def _extract_multi_textures(self, mat_names: list) -> dict:
        """
        Для каждого имени материала из SMD ищет VTF в VPK и сохраняет как PNG.

        Returns:
            {mat_name: png_path} — только для найденных текстур.
        """
        result: dict = {}
        try:
            import vpk as vpklib
            from PIL import Image
            from src.services.vtflib_wrapper import VTFLib
            from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES

            # Открываем ОБА VPK: VTF обычно в textures, но VMT (для материалов,
            # чья текстура задаётся через $basetexture, напр. pocket_watch_fg
            # у Dead Ringer) — чаще в misc.
            paks: list = []
            for _vpk_path in [self.textures_vpk_path, self.misc_vpk_path]:
                if _vpk_path and os.path.exists(_vpk_path):
                    try:
                        paks.append(vpklib.open(_vpk_path))
                    except Exception as _exc:
                        logger.debug(f"[3D] Ошибка открытия VPK {_vpk_path}: {_exc}")
            if not paks:
                return result

            # Для моделей рук / скинов персонажа определяем папку (materials/models/player/{folder}/)
            # Все материалы SMD текстурируем — _find_vtf_for_mat ищет сначала
            # в папке игрока, что покрывает и руки, и рукав костюма.
            from src.data.player_characters import PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS
            arm_folder: Optional[str] = None
            if self.mode in HAND_MODE_KEYS:
                textures_list = HAND_MODES.get(self.mode, {}).get("textures", [])
                if textures_list:
                    arm_folder = textures_list[0][0]
            elif self.mode in PLAYER_BODY_MODE_KEYS:
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

        import glob
        qc_files = glob.glob(os.path.join(self._decomp_dir, "*.qc"))
        if not qc_files:
            return {}

        cdmaterials = qc_skin_parser.parse_cdmaterials(qc_files[0])
        layout = qc_skin_parser.parse_skin_layout(qc_files[0])
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
            import vpk as vpklib
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image

            paks: list = []
            for vpk_path in [self.textures_vpk_path, self.misc_vpk_path]:
                if vpk_path and os.path.exists(vpk_path):
                    try:
                        paks.append(vpklib.open(vpk_path))
                    except Exception as exc:
                        logger.debug(f"[3D] Ошибка открытия VPK {vpk_path}: {exc}")
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
            import vpk as vpklib
            paks: list = []
            for _vpk_path in [self.textures_vpk_path, self.misc_vpk_path]:
                if _vpk_path and os.path.exists(_vpk_path):
                    try:
                        paks.append(vpklib.open(_vpk_path))
                    except Exception as _exc:
                        logger.debug(f"[3D] Ошибка открытия VPK {_vpk_path}: {_exc}")

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
                        base = self._parse_basetexture_from_vmt(
                            vmt_raw.decode("utf-8", errors="replace"))
                        if base:
                            for pak2 in paks:
                                data = self._find_vtf_for_basetexture(pak2, base)
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
            qc_files = glob.glob(os.path.join(self._decomp_dir, "*.qc"))
            if not qc_files:
                return {}
            from src.services.model_build_service import ModelBuildService
            from src.data.material_filter import is_editable_material
            tg = ModelBuildService.extract_texturegroup_structure(qc_files[0])
            extras = tg.get('extra_materials', []) or []
            known = {m.lower() for m in mat_names}
            # Тем же блэклистом, что и сборка/карточки, и только то, чего нет
            # в геометрии (иначе материал уже показан обычным путём).
            missing = [m for m in extras
                       if m.lower() not in known and is_editable_material(m)]
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
            info = self._find_vmt_content_in_vpk(pak, cdmaterials, mat_lower)
            if not info:
                continue
            base = self._parse_basetexture_from_vmt(info[1])
            if not base:
                continue
            for pak2 in paks:
                data = self._find_vtf_for_basetexture(pak2, base)
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
            import glob
            decomp = getattr(self, '_decomp_dir', None)
            if decomp:
                qcs = glob.glob(os.path.join(decomp, "*.qc"))
                if qcs:
                    cdmats = qc_skin_parser.parse_cdmaterials(qcs[0])
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

    def _extract_blu_via_qc(self, decomp_dir: str, red_framerate: float) -> tuple:
        """
        Извлекает BLU-вариант текстуры используя QC $texturegroup skinfamilies.

        Читает QC из decomp_dir, парсит skin family 1 (BLU),
        ищет соответствующие VTF в VPK (сначала прямой путь, затем через VMT).

        Returns:
            (frame_paths: list[str], framerate: float)
            Пустой список если BLU варианта нет.
        """
        qc_files = glob.glob(os.path.join(decomp_dir, "*.qc"))
        if not qc_files:
            logger.debug(f"[3D] _extract_blu_via_qc: QC не найден в {decomp_dir}")
            return [], 0.0

        cdmaterials = qc_skin_parser.parse_cdmaterials(qc_files[0])
        layout = qc_skin_parser.parse_skin_layout(qc_files[0])
        if not layout.second_row:
            logger.debug("[3D] _extract_blu_via_qc: второго скина в QC нет → нет BLU варианта")
            return [], 0.0

        # Переключатель RED/BLU показываем только для настоящей команды
        # (по именам: col0 + _blue/_blu), а не для стилей вроде bloody/clean.
        if not layout.blu_is_team:
            logger.info(
                f"[3D] второй скин не является BLU-командой: {layout.second_row} "
                f"— стиль или вариант, переключатель команд не нужен"
            )
            return [], 0.0

        blu_tex_names = layout.second_row

        logger.info(
            f"[3D] QC BLU skin family: cdmaterials={cdmaterials}, "
            f"tex_names={blu_tex_names}"
        )

        try:
            import vpk as vpklib
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image

            paks: list = []
            for vpk_path in [self.textures_vpk_path, self.misc_vpk_path]:
                if vpk_path and os.path.exists(vpk_path):
                    try:
                        paks.append(vpklib.open(vpk_path))
                    except Exception as exc:
                        logger.debug(f"[3D] Ошибка открытия VPK {vpk_path}: {exc}")
            if not paks:
                return [], 0.0

            for tex_name in blu_tex_names:
                tex_lower = tex_name.lower()
                vtf_data: Optional[bytes] = None

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
                        vmt_info = self._find_vmt_content_in_vpk(
                            pak, cdmaterials, tex_lower
                        )
                        if vmt_info:
                            _, vmt_content = vmt_info
                            basetexture = self._parse_basetexture_from_vmt(vmt_content)
                            if basetexture:
                                for pak2 in paks:
                                    vtf_data = self._find_vtf_for_basetexture(
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

                fps = red_framerate if len(frame_paths) > 1 else 0.0
                logger.info(
                    f"[3D] BLU via QC: {len(frame_paths)} frame(s) "
                    f"@ {fps:.1f} fps для {self.weapon_key}"
                )
                return frame_paths, fps

        except Exception as exc:
            logger.warning(f"[3D] _extract_blu_via_qc: {exc}", exc_info=True)

        return [], 0.0

    def _extract_variant_via_qc(self, decomp_dir: str) -> Optional[str]:
        """
        Извлекает текстуру варианта оружия (Australium/Gold/Festive) из QC.

        Строку варианта выбирает qc_skin_parser.pick_preview_variant:
        приоритет у настоящего австралиума, затем прочие «внешние» варианты.

        Returns:
            Путь к PNG-файлу варианта или None если нет.
        """
        import glob
        qc_files = glob.glob(os.path.join(decomp_dir, "*.qc"))
        if not qc_files:
            return None, None

        cdmaterials = qc_skin_parser.parse_cdmaterials(qc_files[0])
        layout = qc_skin_parser.parse_skin_layout(qc_files[0])
        if not cdmaterials:
            return None, None

        variant_family = qc_skin_parser.pick_preview_variant(layout)
        if not variant_family:
            return None, None

        # Текстура варианта — col 0 этой строки
        variant_tex = variant_family[0].lower()
        logger.info(f"[3D] Обнаружен вариант оружия: {variant_tex}")

        try:
            import vpk as vpklib
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image

            paks: list = []
            for vpk_path in [self.textures_vpk_path, self.misc_vpk_path]:
                if vpk_path and os.path.exists(vpk_path):
                    try:
                        paks.append(vpklib.open(vpk_path))
                    except Exception:
                        pass

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

    @staticmethod
    def _find_vmt_content_in_vpk(pak, cdmaterials: list, mat_name: str) -> Optional[tuple]:
        """
        Ищет VMT-файл для имени материала в открытом VPK.

        Проверяет все комбинации cdmaterials × workshop-вариантов.
        Пропускает VMT, в контенте или пути которых есть «backpack»
        (это иконки инвентаря, не модельные текстуры).

        Returns:
            (vmt_path, vmt_content_str) или None.
        """
        swaps = Preview3DWorker._WORKSHOP_SWAPS
        candidates: list = []
        for cdmat in cdmaterials:
            base_dir = f"materials/{cdmat}"
            candidates.append(f"{base_dir}/{mat_name}.vmt")
            for src, dst in swaps:
                if base_dir.startswith(src):
                    alt = base_dir.replace(src, dst, 1)
                    candidates.append(f"{alt}/{mat_name}.vmt")

        for path in candidates:
            try:
                raw = pak[path].read()
            except KeyError:
                continue
            try:
                content = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            if "backpack" in path.lower() or "backpack" in content.lower():
                logger.debug(f"[3D] Пропускаем backpack VMT: {path}")
                continue
            return path, content
        return None

    @staticmethod
    def _parse_basetexture_from_vmt(vmt_content: str) -> Optional[str]:
        """Извлекает значение $baseTexture из VMT-контента.

        Обрабатывает все встречающиеся форматы:
            $baseTexture      "path/to/texture"   ← ключ без кавычек
            "$basetexture"    "path/to/texture"   ← ключ в кавычках (TF2 workshop VMT)
            $baseTexture      path/to/texture      ← значение без кавычек
        """
        import re
        # Ключ с кавычками или без, значение с кавычками
        m = re.search(
            r'"?\$baseTexture"?\s+"([^"]+)"',
            vmt_content, re.IGNORECASE,
        )
        if m:
            return m.group(1).replace("\\", "/").lower()
        # Значение без кавычек
        m = re.search(
            r'"?\$baseTexture"?\s+([^\s"{}]+)',
            vmt_content, re.IGNORECASE,
        )
        return m.group(1).replace("\\", "/").lower() if m else None

    @staticmethod
    def _find_vtf_for_basetexture(pak, basetexture: str) -> Optional[bytes]:
        """
        Находит VTF-файл в открытом VPK по значению $baseTexture.

        $baseTexture в VMT — путь относительно materials/ (без расширения).
        """
        path = basetexture.replace("\\", "/").lower().strip("/")
        if not path.startswith("materials/"):
            path = "materials/" + path
        if not path.endswith(".vtf"):
            path += ".vtf"
        try:
            return pak[path].read()
        except KeyError:
            return None

    def _vtf_data_to_png(self, vtf_data: bytes, name: str) -> Optional[str]:
        """
        Сохраняет VTF-байты как PNG в preview_dir.
        Возвращает путь к PNG или None при ошибке.
        """
        from src.services import vtf_preview_service as _vps
        return _vps.vtf_bytes_to_png(
            vtf_data, os.path.join(self._preview_dir, f"{name}.png"), self._preview_dir)

    def _extract_hat_textures_via_qc_vmt(
        self, decomp_dir: str, mat_names: list
    ) -> dict:
        """
        Главный метод извлечения текстур шапки через цепочку QC → VMT → VTF.

        1. Читает QC из decomp_dir, получает $cdmaterials пути.
        2. Открывает ОБА VPK (misc + textures) сразу, т.к. VMT и VTF
           могут быть в РАЗНЫХ архивах:
           – VMT → tf2_misc_dir.vpk
           – VTF → tf2_textures_dir.vpk
        3. Для каждого имени материала из SMD ищет VMT в любом из пакетов,
           пропускает VMT с «backpack», читает $baseTexture → ищет VTF → PNG.

        Returns:
            {mat_name: png_path}  (пустой dict если ничего не нашлось)
        """
        import vpk as vpklib

        qc_files = glob.glob(os.path.join(decomp_dir, "*.qc"))
        if not qc_files:
            logger.warning(f"[3D] QC не найден в {decomp_dir}")
            return {}

        cdmaterials = qc_skin_parser.parse_cdmaterials(qc_files[0])
        if not cdmaterials:
            logger.warning(f"[3D] $cdmaterials не найден в QC: {qc_files[0]}")
            return {}

        logger.info(f"[3D] Hat QC: cdmaterials={cdmaterials}, materials={mat_names}")

        # Открываем оба VPK сразу — VMT обычно в misc, VTF в textures
        paks: list = []
        for vpk_path in [self.misc_vpk_path, self.textures_vpk_path]:
            if not vpk_path or not os.path.exists(vpk_path):
                continue
            try:
                paks.append(vpklib.open(vpk_path))
            except Exception as exc:
                logger.debug(f"[3D] Ошибка открытия VPK {vpk_path}: {exc}")

        if not paks:
            logger.warning("[3D] Не удалось открыть ни один VPK")
            return {}

        result: dict = {}
        for mat_name in mat_names:
            mat_lower = mat_name.lower()

            # ── Ищем VMT в любом из открытых VPK ─────────────────────── #
            vmt_info = None
            for pak in paks:
                vmt_info = self._find_vmt_content_in_vpk(pak, cdmaterials, mat_lower)
                if vmt_info:
                    break

            if not vmt_info:
                logger.info(
                    f"[3D] VMT не найден: mat='{mat_lower}', cdmaterials={cdmaterials}"
                )
                continue

            vmt_path, vmt_content = vmt_info
            basetexture = self._parse_basetexture_from_vmt(vmt_content)
            if not basetexture:
                logger.warning(f"[3D] $baseTexture не найден в VMT: {vmt_path}")
                continue

            # ── Ищем VTF в любом из открытых VPK ─────────────────────── #
            vtf_data = None
            for pak in paks:
                vtf_data = self._find_vtf_for_basetexture(pak, basetexture)
                if vtf_data:
                    break

            if not vtf_data:
                logger.warning(
                    f"[3D] VTF не найден: $baseTexture={basetexture} "
                    f"(VMT={vmt_path})"
                )
                continue

            png_path = self._vtf_data_to_png(vtf_data, f"hat_{mat_lower}")
            if png_path:
                result[mat_lower] = png_path
                logger.info(
                    f"[3D] Шапка '{mat_lower}': VMT={vmt_path} → {basetexture}"
                )

        return result

    # ── Извлечение текстуры ───────────────────────────────────────────────── #

    def _extract_hat_texture_frames(self) -> tuple:
        """
        Fallback-метод: угадывает VTF-путь напрямую по имени MDL.

        Используется только если основной QC→VMT→VTF путь не дал результата.
        MDL-имя → имя материала (например hat_heavy.mdl → hat_heavy.vtf).

        Returns:
            (frame_paths: list[str], framerate: float)
        """
        try:
            import vpk as vpklib

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

            # Ищем в текстурах VPK, затем в misc VPK
            vtf_data: Optional[bytes] = None
            for vpk_path in [self.textures_vpk_path, self.misc_vpk_path]:
                if not vpk_path or not os.path.exists(vpk_path):
                    continue
                try:
                    pak = vpklib.open(vpk_path)
                    for path in vtf_paths:
                        try:
                            vtf_data = pak[path].read()
                            logger.debug(f"[3D] Hat texture: {path}")
                            break
                        except KeyError:
                            continue
                    if vtf_data:
                        break
                except Exception as exc:
                    logger.debug(f"[3D] Ошибка открытия VPK {vpk_path}: {exc}")

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
        from src.data.player_characters import SPY_MASK_MODE_KEY
        if self.mode == SPY_MASK_MODE_KEY:
            return self._extract_spy_mask_texture("mask_spy")

        try:
            import vpk as vpklib
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

            paks_tex: list = []
            for vpk_path in [self.textures_vpk_path, self.misc_vpk_path]:
                if vpk_path and os.path.exists(vpk_path):
                    try:
                        paks_tex.append(vpklib.open(vpk_path))
                    except Exception as _e:
                        logger.debug(f"[3D] Ошибка открытия VPK {vpk_path}: {_e}")

            pak = paks_tex[0] if paks_tex else None
            vtf_data: Optional[bytes] = None

            if pak:
                for path in vtf_search:
                    try:
                        vtf_data = pak[path].read()
                        logger.debug(f"3D Preview текстура: {path}")
                        break
                    except KeyError:
                        continue

            # ── Fallback: QC $cdmaterials → materials/{cdmat}/{skin0}.vtf ── #
            # Используется для оружий с нестандартным расположением текстур
            # (например c_items, где путь не совпадает с weapon_key).
            if not vtf_data and self._decomp_dir:
                vtf_data = self._extract_red_texture_via_qc(paks_tex)

            if not vtf_data:
                logger.warning(f"Текстура для {self.weapon_key} не найдена в VPK")
                return [], 0.0

            from src.services import vtf_preview_service as _vps
            frame_paths = _vps.vtf_bytes_to_frame_pngs(
                vtf_data, self._preview_dir, "texture")

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

        qc_files = glob.glob(os.path.join(self._decomp_dir, "*.qc"))
        if not qc_files:
            return None

        cdmaterials = qc_skin_parser.parse_cdmaterials(qc_files[0])
        if not cdmaterials:
            return None

        # RED-текстуры: первая строка группы (или weapon_key как единственный кандидат)
        rows = qc_skin_parser.parse_texturegroup_rows(qc_files[0])
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
                vmt_info = self._find_vmt_content_in_vpk(pak, cdmaterials, tex_lower)
                if vmt_info:
                    _, vmt_content = vmt_info
                    basetexture = self._parse_basetexture_from_vmt(vmt_content)
                    if basetexture:
                        for pak2 in paks:
                            data = self._find_vtf_for_basetexture(pak2, basetexture)
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
            import vpk as vpklib
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

            pak = vpklib.open(self.textures_vpk_path)
            vtf_data: Optional[bytes] = None
            for path in blu_vtf_search:
                try:
                    vtf_data = pak[path].read()
                    logger.debug(f"3D Preview BLU текстура: {path}")
                    break
                except KeyError:
                    continue

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
        """Ищет animatedtextureframerate в VMT файле из VPK."""
        import re
        DEFAULT_FPS = 15.0
        if pak is None:
            return DEFAULT_FPS
        for path in vmt_search:
            try:
                content = pak[path].read().decode("utf-8", errors="replace")
                m = re.search(
                    r'"animatedtextureframerate"\s+"?([0-9.]+)"?',
                    content,
                    re.IGNORECASE,
                )
                if m:
                    return max(0.1, float(m.group(1)))
                break   # VMT найден, но без framerate — используем дефолт
            except KeyError:
                continue
        return DEFAULT_FPS
