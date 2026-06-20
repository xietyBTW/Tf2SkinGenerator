"""
Воркер для загрузки пользовательского VPK мода в 3D Preview.

Шаги:
  1. Открываем VPK пользователя.
  2. Сканируем: MDL файлы, VMT файлы ($basetexture), VTF файлы.
  3. Если MDL есть  → извлекаем + декомпилируем → SMD → OBJ.
  4. Если MDL нет   → по имени VTF / $basetexture определяем ключ оружия
                      → берём оригинальную модель из игровых VPK.
  5. Извлекаем основную текстуру из мода (по $basetexture).
     Игнорируем lightwarp, phongwarp, bumpmap и т.п.
     Если текстуры в моде нет — берём из игры.
  6. Эмитируем ready(obj_path, texture_path).
"""

import glob
import os
import re
import shutil
import tempfile
from typing import List, Optional

from PySide6.QtCore import Signal

from src.services.base_worker import BaseWorker
from src.services.game_vpk_reader import GameVpkReader
from src.services.smd_service import NON_REFERENCE_SMD_KEYWORDS
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# VTF-параметры которые не являются основной текстурой (basetexture ≠ это)
_SKIP_VMT_KEYS = {
    "$lightwarptexture", "$bumpmap", "$normalmap", "$phongwarptexture",
    "$envmap", "$envmapmask", "$detail", "$selfillummask",
    "$blendmodulatetexture", "$maskstexture", "$phongexponenttexture",
    "$rimlight", "$rimlightexponent",
}

# Слова в пути VTF-файла которые говорят «это не основная текстура»
_SKIP_VTF_KEYWORDS = (
    "lightwarp", "phongwarp", "envmap", "cubemap", "sheen",
    "bump", "normal", "detail", "spec", "mask", "selfillum",
)


# ── Утилиты ──────────────────────────────────────────────────────────────── #

def _weapon_key_from_path(path: str) -> Optional[str]:
    """
    Пытается извлечь ключ оружия (c_xxxx) из пути к файлу.
    Сверяет кандидатов с таблицей WEAPON_MDL_PATHS.

    Пример:
      'materials/models/weapons/c_models/c_scattergun/c_scattergun.vtf'
      → 'c_scattergun'
    """
    from src.data.weapons import WEAPON_MDL_PATHS

    candidates = re.findall(r"(c_[a-z0-9_]+)", path.lower())
    # Перебираем с конца — ключ оружия обычно в самом конце пути
    for part in reversed(candidates):
        if part in WEAPON_MDL_PATHS:
            return part
    return None


def _is_base_vtf(vtf_path: str) -> bool:
    """True если VTF скорее всего является основной текстурой (не служебной)."""
    low = vtf_path.lower()
    return not any(kw in low for kw in _SKIP_VTF_KEYWORDS)


# ── Воркер ───────────────────────────────────────────────────────────────── #

class PreviewVpkModWorker(BaseWorker):
    """Готовит OBJ + текстуру из пользовательского VPK мода для 3D Preview."""

    ready     = Signal(str, str)      # (obj_path, first_frame_path)
    animated  = Signal(object, float) # ([frame_paths], framerate) — только если кадров > 1
    blu_ready = Signal(object, float) # BLU командная раскраска — если найдена
    cards_ready = Signal(object)      # [card_dict] — 2D-карточки всех текстур мода
    materials_ready = Signal(object)  # [material_name] — имена материалов модели (для наложения по мешам)
    skins_ready = Signal(object)      # skin_info — стили модели (skinfamilies) из QC
    failed    = Signal(str)
    progress  = Signal(str)

    _PROGRESS = {
        'ru': {
            'opening':          'Открытие VPK мода...',
            'open_error':       'Не удалось открыть VPK: {err}',
            'scanning':         'Анализ содержимого VPK...',
            'decompiling_mod':  'Декомпиляция MDL из мода...',
            'loading_original': 'Загрузка оригинальной модели из игры...',
            'extracting_tex':   'Извлечение текстуры...',
            'converting':       'Конвертация модели...',
            'decompiling_orig': 'Декомпиляция оригинальной модели...',
            'not_found':        (
                'Модель не найдена ни в моде, ни в игре. '
                'Проверьте что VPK содержит .mdl или что путь к игре настроен.'
            ),
        },
        'en': {
            'opening':          'Opening VPK mod...',
            'open_error':       'Failed to open VPK: {err}',
            'scanning':         'Scanning VPK contents...',
            'decompiling_mod':  'Decompiling MDL from mod...',
            'loading_original': 'Loading original model from game...',
            'extracting_tex':   'Extracting texture...',
            'converting':       'Converting model...',
            'decompiling_orig': 'Decompiling original model...',
            'not_found':        (
                'Model not found in the mod or the game. '
                'Make sure the VPK contains a .mdl file or that the TF2 path is configured.'
            ),
        },
    }

    def __init__(
        self,
        user_vpk_path: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
        lang: str = 'en',
        parent=None,
    ):
        super().__init__(parent)
        self.user_vpk_path     = user_vpk_path
        self.misc_vpk_path     = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self._preview_dir: Optional[str] = None
        self._model_materials: List[str] = []
        # Игровой tf2_textures_dir.vpk открываем один раз за прогон (fallback-пути).
        self._game_reader: Optional[GameVpkReader] = None
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])

    def _game_textures_pak(self):
        """Хэндл игрового tf2_textures_dir.vpk (открыт один раз, кэш). None если нет."""
        if self._game_reader is None:
            self._game_reader = GameVpkReader([self.textures_vpk_path])
        paks = self._game_reader.paks
        return paks[0] if paks else None

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
        try:
            self._preview_dir = tempfile.mkdtemp(prefix="tf2sg_vpkmod_")

            import vpk as vpklib

            self.progress.emit(self._p['opening'])
            try:
                pak = vpklib.open(self.user_vpk_path)
            except Exception as exc:
                self.failed.emit(self._p['open_error'].format(err=exc))
                return

            if self.isInterruptionRequested():
                return

            # ── 1. Сканируем содержимое ───────────────────────────────────── #
            self.progress.emit(self._p['scanning'])

            mdl_files: List[str] = []
            vmt_files: List[str] = []
            vtf_files: List[str] = []

            for filepath in pak:
                fp_low = filepath.lower()
                if fp_low.endswith(".mdl"):
                    mdl_files.append(filepath)
                elif fp_low.endswith(".vmt"):
                    vmt_files.append(filepath)
                elif fp_low.endswith(".vtf"):
                    vtf_files.append(filepath)

            logger.info(
                f"VPK мод «{os.path.basename(self.user_vpk_path)}»: "
                f"{len(mdl_files)} MDL, {len(vmt_files)} VMT, {len(vtf_files)} VTF"
            )

            # ── 2D-карточки всех текстур мода (РАНО) ──────────────────────── #
            # Эмитим карточки сразу после сканирования VTF, ДО тяжёлой/прерываемой
            # работы по модели — иначе перезапуск воркера (смена категории) мог
            # прервать run() до их формирования, и в 2D оставалась лишь одна
            # карточка (от обычной фильтрации материалов модели).
            try:
                cards = self._build_cards_from_pak(pak, vtf_files, vmt_files)
                if cards:
                    logger.info(f"VPK мод: 2D-карточек подготовлено: {len(cards)}")
                    self.cards_ready.emit(cards)
            except Exception as exc:
                logger.debug(f"VPK мод: не удалось собрать 2D-карточки: {exc}")

            if self.isInterruptionRequested():
                return

            # ── 2. Парсим VMT → $basetexture ─────────────────────────────── #
            basetexture_path: Optional[str] = None
            for vmt_rel in vmt_files:
                try:
                    data = pak[vmt_rel].read()
                    vmt_content = data.decode("utf-8", errors="replace")
                    bt = GameVpkReader.parse_basetexture(vmt_content)
                    if bt:
                        basetexture_path = bt
                        logger.info(f"$basetexture из VMT «{vmt_rel}»: {bt}")
                        break
                except Exception:
                    continue

            # ── 3. Определяем ключ оружия ─────────────────────────────────── #
            weapon_key: Optional[str] = None

            # Приоритет: MDL → basetexture → VTF
            for mdl_rel in mdl_files:
                weapon_key = _weapon_key_from_path(mdl_rel)
                if weapon_key:
                    break

            if not weapon_key and basetexture_path:
                weapon_key = _weapon_key_from_path(basetexture_path)

            if not weapon_key:
                for vtf_rel in vtf_files:
                    if _is_base_vtf(vtf_rel):
                        weapon_key = _weapon_key_from_path(vtf_rel)
                        if weapon_key:
                            break

            logger.info(f"Определён ключ оружия из VPK мода: {weapon_key!r}")

            if self.isInterruptionRequested():
                return

            # ── 4. Получаем OBJ ───────────────────────────────────────────── #
            obj_path: Optional[str] = None
            decomp_dir: Optional[str] = None

            if mdl_files:
                # Декомпилируем MDL из мода
                self.progress.emit(self._p['decompiling_mod'])
                obj_path, decomp_dir = self._decompile_mdl_from_pak(
                    pak, mdl_files[0], weapon_key
                )

            if not obj_path and weapon_key and self.misc_vpk_path:
                # Нет MDL в моде — берём оригинальную TF2 модель
                self.progress.emit(self._p['loading_original'])
                orig_obj, orig_decomp = self._load_original_model(weapon_key)
                if not obj_path:
                    obj_path = orig_obj
                if not decomp_dir:
                    decomp_dir = orig_decomp

            if not obj_path:
                self.failed.emit(self._p['not_found'])
                return

            if self.isInterruptionRequested():
                return

            # ── 5. Получаем текстуру ──────────────────────────────────────── #
            self.progress.emit(self._p['extracting_tex'])
            frame_paths, framerate = self._extract_texture_frames_from_pak(
                pak, vtf_files, basetexture_path, vmt_files,
                weapon_key=weapon_key, decomp_dir=decomp_dir,
            )

            # Fallback: текстура из игры
            if not frame_paths and weapon_key and self.textures_vpk_path:
                frame_paths, framerate = self._extract_game_texture_frames(weapon_key)

            first_tex = frame_paths[0] if frame_paths else ""
            self.ready.emit(obj_path, first_tex)

            # Имена материалов модели → панель наложит текстуры мода по мешам.
            if self._model_materials:
                logger.info(f"VPK мод: материалы модели: {self._model_materials}")
                self.materials_ready.emit(list(self._model_materials))

            if len(frame_paths) > 1:
                self.animated.emit(frame_paths, framerate)

            if self.isInterruptionRequested():
                return

            # ── 6. BLU-вариант текстуры ───────────────────────────────────── #
            blu_paths, blu_fps = self._extract_blu_texture(
                pak, vtf_files, basetexture_path, weapon_key, framerate,
                decomp_dir=decomp_dir,
            )
            if blu_paths:
                self.blu_ready.emit(blu_paths, blu_fps)

            # ── 7. Стили модели (skinfamilies) из QC ──────────────────────── #
            try:
                if decomp_dir:
                    qc_path = self._find_qc_in_dir(decomp_dir)
                    if qc_path:
                        from src.services.model_build_service import ModelBuildService
                        info = ModelBuildService.extract_skin_info(qc_path)
                        skins = (info or {}).get('skins') or []
                        if len(skins) >= 2:
                            # Превью УЖЕ существующих текстур каждого стиля — чтобы
                            # при переключении стиля карточки были не пустыми.
                            info['skin_textures'] = self._build_skin_textures(pak, info, vtf_files)
                            logger.info(f"VPK мод: стилей определено: {len(skins)} ({info.get('roles')})")
                            self.skins_ready.emit(info)
            except Exception as exc:
                logger.debug(f"VPK мод: стили не определены: {exc}")

        except Exception as exc:
            logger.error(f"PreviewVpkModWorker: {exc}", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            if self._game_reader is not None:
                self._game_reader.close()

    # ── 2D-карточки: все основные текстуры мода из открытого pak ──────────── #

    def _build_cards_from_pak(self, pak, vtf_files: List[str], vmt_files: List[str]) -> list:
        """Строит карточки для ВСЕХ основных VTF мода прямо из открытого pak.

        Служебные VTF (lightwarp/bump/normal/…) отброшены через _is_base_vtf.
        Имя карточки = стебель VTF; при коллизии добавляется папка. Превью —
        первый кадр VTF. vmt_path привязывается по совпадению стебля.
        """
        # Индекс VMT по стеблю для привязки.
        vmt_by_stem = {}
        for vmt_rel in vmt_files:
            stem = os.path.splitext(os.path.basename(vmt_rel))[0].lower()
            vmt_by_stem.setdefault(stem, vmt_rel)

        base = sorted(v for v in vtf_files if _is_base_vtf(v))
        # Подсчёт коллизий стеблей для дизамбигуации.
        stems = [os.path.splitext(os.path.basename(v))[0] for v in base]
        counts: dict = {}
        for s in stems:
            counts[s] = counts.get(s, 0) + 1

        cards = []
        used: set = set()
        for vtf_rel in base:
            stem = os.path.splitext(os.path.basename(vtf_rel))[0]
            folder = os.path.basename(os.path.dirname(vtf_rel))
            name = stem if counts.get(stem, 0) <= 1 else f"{stem} [{folder}]"
            while name in used:
                name += "_"
            used.add(name)

            preview_png = None
            try:
                data = pak[vtf_rel].read()
                preview_png = self._vtf_bytes_first_frame_png(data, name)
            except Exception as exc:
                logger.debug(f"VPK мод: превью VTF не удалось ({vtf_rel}): {exc}")

            cards.append({
                'name': name,
                'display_name': name,
                'is_blue': stem.lower().endswith('_blue'),
                'preview_png': preview_png,
                'vmt_path': vmt_by_stem.get(stem.lower()),
            })

        # RED-материалы первыми, затем BLU (как в обычной раскладке карточек).
        return [c for c in cards if not c['is_blue']] + [c for c in cards if c['is_blue']]

    def _build_skin_textures(self, pak, info: dict, vtf_files: List[str]) -> dict:
        """Для каждого стиля (skinfamilies) — превью существующих текстур по
        базовому материалу: {raw_skin_idx: {base_material: preview_png}}.

        Строки $texturegroup: строка 0 — базовые материалы (колонки = меш-слоты),
        строка K — материалы стиля K в тех же колонках. Текстуру стиля берём по
        совпадению стебля материала с VTF-файлом мода.
        """
        rows = info.get('rows') or []
        skins = info.get('skins') or []
        if not rows or not skins:
            return {}
        base_row = rows[0]
        vtf_by_stem = {
            os.path.splitext(os.path.basename(v))[0].lower(): v for v in vtf_files
        }
        out: dict = {}
        for s in skins:
            ridx = s.get('index', 0)
            if ridx >= len(rows):
                continue
            row = rows[ridx]
            mp: dict = {}
            for col, base_mat in enumerate(base_row):
                if col >= len(row):
                    continue
                variant_mat = row[col]
                # В стиль включаем ТОЛЬКО материалы, которые отличаются от базовой
                # строки. Одинаковый материал (eyes/mouth и т.п.) наследует базу —
                # его не показываем как отдельную карточку стиля.
                if variant_mat.strip().lower() == base_mat.strip().lower():
                    continue
                stem = os.path.splitext(os.path.basename(variant_mat))[0].lower()
                vtf_rel = vtf_by_stem.get(stem)
                if not vtf_rel:
                    continue
                try:
                    data = pak[vtf_rel].read()
                    png = self._vtf_bytes_first_frame_png(data, f"skin{ridx}_{base_mat}")
                    if png:
                        mp[base_mat] = png
                except Exception:
                    continue
            if mp:
                out[ridx] = mp
        return out

    def _vtf_bytes_first_frame_png(self, vtf_data: bytes, key: str) -> Optional[str]:
        """Сохраняет первый кадр VTF в уникальный PNG (для превью карточки).

        Тонкая обёртка над общим vtf_preview_service.vtf_bytes_to_png — лишь
        санитайзит ключ в безопасное имя файла.
        """
        from src.services import vtf_preview_service as _vps
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', key)
        return _vps.vtf_bytes_to_png(
            vtf_data, os.path.join(self._preview_dir, f"_card_{safe}.png"), self._preview_dir)

    # ── MDL: декомпиляция из пользовательского VPK ───────────────────────── #

    def _decompile_mdl_from_pak(
        self,
        pak,
        mdl_rel: str,
        weapon_key: Optional[str],
    ) -> tuple:
        """
        Извлекает MDL + сопутствующие файлы (.vvd, .vtx, .phy) из VPK
        и декомпилирует через Crowbar.

        Returns:
            (obj_path, decomp_dir) — оба None если что-то пошло не так.
        """
        from src.services.model_build_service import ModelBuildService
        from src.services.tf2_paths import TF2Paths

        MDL_EXTS = (".mdl", ".vvd", ".dx90.vtx", ".vtx", ".phy",
                    ".dx80.vtx", ".sw.vtx")

        mdl_dir_in_pak = os.path.dirname(mdl_rel).replace("\\", "/").lower()
        extract_dir    = tempfile.mkdtemp(prefix="tf2sg_mdlmod_")
        mdl_file_local: Optional[str] = None

        try:
            for filepath in pak:
                fp_low = filepath.lower()
                if not any(fp_low.endswith(ext) for ext in MDL_EXTS):
                    continue
                fp_dir = os.path.dirname(fp_low).replace("\\", "/")
                if fp_dir != mdl_dir_in_pak:
                    continue
                try:
                    data       = pak[filepath].read()
                    local_name = os.path.basename(filepath)
                    local_path = os.path.join(extract_dir, local_name)
                    with open(local_path, "wb") as f:
                        f.write(data)
                    if fp_low.endswith(".mdl"):
                        mdl_file_local = local_path
                except Exception as exc:
                    logger.warning(f"Не удалось извлечь {filepath}: {exc}")

            if not mdl_file_local:
                logger.warning(f"MDL не извлечён из пака: {mdl_rel}")
                return None, None

            if self.isInterruptionRequested():
                return None, None

            crowbar    = TF2Paths.get_crowbar_path()
            decomp_dir = tempfile.mkdtemp(prefix="tf2sg_decomp_mod_")
            ModelBuildService.decompile(mdl_file_local, decomp_dir, crowbar)

            smd_path = self._find_reference_smd(decomp_dir, weapon_key)
            if not smd_path:
                logger.warning(f"Reference SMD не найден в {decomp_dir}")
                return None, decomp_dir   # dir есть, SMD нет — всё равно вернём dir для текстуры

            self.progress.emit(self._p['converting'])
            obj_path = os.path.join(self._preview_dir, "model.obj")
            from src.services.smd_to_obj_service import SmdToObjService
            ok, mat_names = SmdToObjService.convert(smd_path, obj_path)
            if ok:
                self._model_materials = list(mat_names or [])
            return (obj_path if ok else None), decomp_dir

        except Exception as exc:
            logger.error(f"Ошибка декомпиляции MDL из мода: {exc}", exc_info=True)
            return None, None
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    # ── Оригинальная TF2 модель ───────────────────────────────────────────── #

    def _load_original_model(self, weapon_key: str) -> tuple:
        """
        Берёт оригинальную модель оружия из tf2_misc_dir.vpk,
        декомпилирует, конвертирует в OBJ.
        Использует кэш декомпиляции если есть.

        Returns:
            (obj_path, decomp_dir) — оба None если что-то пошло не так.
        """
        if not self.misc_vpk_path:
            logger.warning(
                "misc_vpk_path не задан — невозможно загрузить оригинальную TF2 модель. "
                "Укажите путь к TF2 в настройках."
            )
            return None, None

        from src.data.weapons import WEAPON_MDL_PATHS
        from src.services import decompile_cache
        from src.services.extract_model_service import ExtractModelService
        from src.services.model_build_service import ModelBuildService
        from src.services.tf2_paths import TF2Paths
        from src.services.tf2_vpk_extract_service import TF2VPKExtractService

        mdl_rel = WEAPON_MDL_PATHS.get(
            weapon_key,
            f"models/weapons/c_models/{weapon_key}/{weapon_key}.mdl",
        )

        # Проверяем кэш
        decomp_dir: Optional[str] = None
        cached = decompile_cache.get_cached_decompile(
            weapon_key, self.misc_vpk_path, mdl_rel
        )
        if cached:
            logger.info(f"VPK мод preview: кэш декомпила для {weapon_key}")
            decomp_dir = cached
            smd_path   = self._find_reference_smd(cached, weapon_key)
        else:
            # Ищем MDL в игровом VPK
            fake_mode = f"scout_{weapon_key}"   # класс не важен, только weapon_key
            from src.data.weapon_model_index import tf2_root_from_misc_vpk
            _tf2_root = tf2_root_from_misc_vpk(self.misc_vpk_path)
            paths_to_try = ExtractModelService._build_paths_to_try(
                fake_mode, weapon_key, _tf2_root
            )

            found_rel: Optional[str] = None
            for path in paths_to_try:
                if self.isInterruptionRequested():
                    return None, None
                try:
                    if TF2VPKExtractService.check_mdl_exists(self.misc_vpk_path, path):
                        found_rel = path
                        break
                except Exception:
                    continue

            if not found_rel:
                logger.warning(f"Оригинальный MDL не найден в VPK для {weapon_key}")
                return None, None

            mdl_dir = tempfile.mkdtemp(prefix="tf2sg_mdl_")
            try:
                extracted = TF2VPKExtractService.extract_file_set(
                    self.misc_vpk_path, found_rel, mdl_dir, None
                )
                mdl_file = next((f for f in extracted if f.endswith(".mdl")), None)
                if not mdl_file:
                    return None, None

                if self.isInterruptionRequested():
                    return None, None

                self.progress.emit(self._p['decompiling_orig'])
                crowbar    = TF2Paths.get_crowbar_path()
                decomp_dir = tempfile.mkdtemp(prefix="tf2sg_decomp_")
                ModelBuildService.decompile(mdl_file, decomp_dir, crowbar)

                decompile_cache.save_to_cache(
                    weapon_key, self.misc_vpk_path, found_rel, decomp_dir
                )
                smd_path = self._find_reference_smd(decomp_dir, weapon_key)
            finally:
                shutil.rmtree(mdl_dir, ignore_errors=True)

        if not smd_path:
            # decomp_dir всё равно может помочь с определением текстуры
            return None, decomp_dir

        self.progress.emit(self._p['converting'])
        obj_path = os.path.join(self._preview_dir, "model.obj")
        from src.services.smd_to_obj_service import SmdToObjService
        ok, mat_names = SmdToObjService.convert(smd_path, obj_path)
        if ok:
            self._model_materials = list(mat_names or [])
        return (obj_path if ok else None), decomp_dir

    # ── Текстура из пользовательского VPK ────────────────────────────────── #

    def _find_qc_in_dir(self, directory: str) -> Optional[str]:
        """Находит первый .qc файл в директории декомпиляции."""
        matches = glob.glob(os.path.join(directory, "**", "*.qc"), recursive=True)
        return matches[0] if matches else None

    def _extract_texture_frames_from_pak(
        self,
        pak,
        vtf_files: List[str],
        basetexture_path: Optional[str],
        vmt_files: List[str],
        weapon_key: Optional[str] = None,
        decomp_dir: Optional[str] = None,
    ) -> tuple:
        """
        Ищет основную текстуру в VPK мода и возвращает все кадры.

        Возвращает (frame_paths: list[str], framerate: float).
        Приоритет выбора VTF:
          1. QC $texturegroup — строка 0, столбец 0 (авторитетная основная текстура)
          2. Файл с именем совпадающим с basename($basetexture)
          3. Файл с именем совпадающим с weapon_key (прямое совпадение стебля)
          4. Первый VTF без служебных слов в пути
        """
        vtf_data: Optional[bytes] = None

        # ── Приоритет 1: QC $texturegroup ────────────────────────────────────
        qc_main_stem: Optional[str] = None
        if decomp_dir:
            qc_path = self._find_qc_in_dir(decomp_dir)
            if qc_path:
                try:
                    from src.services.model_build_service import ModelBuildService
                    tg = ModelBuildService.extract_texturegroup_structure(qc_path)
                    raw = (tg.get('main_texture') or '').strip()
                    if raw:
                        qc_main_stem = os.path.splitext(os.path.basename(raw))[0].lower()
                        logger.info(f"QC main texture stem: {qc_main_stem!r}")
                except Exception as exc:
                    logger.debug(f"Не удалось прочитать QC texturegroup: {exc}")

        if qc_main_stem:
            for vtf_rel in vtf_files:
                vtf_stem = os.path.splitext(os.path.basename(vtf_rel))[0].lower()
                if vtf_stem == qc_main_stem:
                    try:
                        vtf_data = pak[vtf_rel].read()
                        logger.info(f"Текстура мода (by QC texturegroup): {vtf_rel}")
                        break
                    except Exception:
                        continue

        # ── Приоритет 2: $basetexture из VMT ─────────────────────────────────
        if not vtf_data and basetexture_path:
            bt_stem = os.path.splitext(os.path.basename(basetexture_path))[0].lower()
            for vtf_rel in vtf_files:
                vtf_stem = os.path.splitext(os.path.basename(vtf_rel))[0].lower()
                if vtf_stem == bt_stem and _is_base_vtf(vtf_rel):
                    try:
                        vtf_data = pak[vtf_rel].read()
                        logger.info(f"Текстура мода (by $basetexture): {vtf_rel}")
                        break
                    except Exception:
                        continue

        # ── Приоритет 3: точное совпадение стебля с weapon_key ───────────────
        if not vtf_data and weapon_key:
            wk_stem = weapon_key.lower()
            for vtf_rel in vtf_files:
                vtf_stem = os.path.splitext(os.path.basename(vtf_rel))[0].lower()
                if vtf_stem == wk_stem and _is_base_vtf(vtf_rel):
                    try:
                        vtf_data = pak[vtf_rel].read()
                        logger.info(f"Текстура мода (by weapon_key stem): {vtf_rel}")
                        break
                    except Exception:
                        continue

        # ── Приоритет 4: первый не-служебный VTF ─────────────────────────────
        if not vtf_data:
            for vtf_rel in vtf_files:
                if not _is_base_vtf(vtf_rel):
                    continue
                try:
                    vtf_data = pak[vtf_rel].read()
                    logger.info(f"Текстура мода (первый VTF): {vtf_rel}")
                    break
                except Exception:
                    continue

        if not vtf_data:
            return [], 0.0

        # Framerate из VMT мода (если анимированная)
        framerate = self._read_vmt_framerate_from_pak(pak, vmt_files)
        return self._vtf_bytes_to_frame_pngs(vtf_data, framerate)

    def _extract_game_texture_frames(self, weapon_key: str) -> tuple:
        """Извлекает текстуру оружия из игровых VPK (fallback). Возвращает (frames, fps)."""
        try:
            from src.data.weapons import WEAPON_TEXTURE_PATHS

            _standard = [
                f"materials/models/workshop_partner/weapons/c_models/{weapon_key}/{weapon_key}.vtf",
                f"materials/models/weapons/c_models/{weapon_key}/{weapon_key}.vtf",
                f"materials/models/weapons/c_items/{weapon_key}/{weapon_key}.vtf",
                f"materials/models/workshop/weapons/c_models/{weapon_key}/{weapon_key}.vtf",
            ]
            vtf_search = WEAPON_TEXTURE_PATHS.get(weapon_key, []) + _standard
            vmt_search = [p.replace(".vtf", ".vmt") for p in vtf_search]

            pak = self._game_textures_pak()
            if pak is None:
                return [], 0.0
            for path in vtf_search:
                try:
                    vtf_data = pak[path].read()
                    logger.info(f"Текстура из игры (fallback): {path}")
                    from src.services import vtf_preview_service as _vps
                    framerate = _vps.read_vmt_framerate(pak, vmt_search)
                    return self._vtf_bytes_to_frame_pngs(vtf_data, framerate)
                except KeyError:
                    continue
        except Exception as exc:
            logger.warning(f"Не удалось извлечь игровую текстуру: {exc}")
        return [], 0.0

    def _extract_blu_texture(
        self,
        pak,
        vtf_files: List[str],
        basetexture_path: Optional[str],
        weapon_key: Optional[str],
        red_framerate: float,
        decomp_dir: Optional[str] = None,
    ) -> tuple:
        """
        Ищет BLU-вариант текстуры.

        Стратегия (в моде):
          1. QC $texturegroup строка 0 столбец 0 + суффикс _blue
          2. basename($basetexture) + суффикс _blue
          3. weapon_key + суффикс _blue (точное совпадение стебля)
          4. Любой VTF у которого стебель ЗАКАНЧИВАЕТСЯ на _blue (не служебный)
        Затем:
          5. Игровой VPK — {weapon_key}_blue.vtf

        Возвращает (frame_paths, framerate) или ([], 0.0).
        """
        vtf_data: Optional[bytes] = None

        # ── Приоритет 1: QC $texturegroup ─────────────────────────────────────
        qc_blu_stem: Optional[str] = None
        if decomp_dir:
            qc_path = self._find_qc_in_dir(decomp_dir)
            if qc_path:
                try:
                    from src.services.model_build_service import ModelBuildService
                    tg = ModelBuildService.extract_texturegroup_structure(qc_path)
                    raw = (tg.get('main_texture') or '').strip()
                    if raw:
                        base_stem = os.path.splitext(os.path.basename(raw))[0]
                        qc_blu_stem = (base_stem + "_blue").lower()
                        logger.info(f"QC BLU texture stem: {qc_blu_stem!r}")
                except Exception as exc:
                    logger.debug(f"QC texturegroup для BLU: {exc}")

        if qc_blu_stem:
            for vtf_rel in vtf_files:
                vtf_stem = os.path.splitext(os.path.basename(vtf_rel))[0].lower()
                if vtf_stem == qc_blu_stem:
                    try:
                        vtf_data = pak[vtf_rel].read()
                        logger.info(f"BLU текстура мода (by QC texturegroup): {vtf_rel}")
                        break
                    except Exception:
                        continue

        # ── Приоритет 2: $basetexture + _blue ─────────────────────────────────
        if not vtf_data and basetexture_path:
            base_stem = os.path.splitext(os.path.basename(basetexture_path))[0]
            blu_bt_stem = (base_stem + "_blue").lower()
            for vtf_rel in vtf_files:
                vtf_stem = os.path.splitext(os.path.basename(vtf_rel))[0].lower()
                if vtf_stem == blu_bt_stem:
                    try:
                        vtf_data = pak[vtf_rel].read()
                        logger.info(f"BLU текстура мода (by $basetexture_blue): {vtf_rel}")
                        break
                    except Exception:
                        continue

        # ── Приоритет 3: weapon_key + _blue (точное совпадение стебля) ─────────
        if not vtf_data and weapon_key:
            wk_blu_stem = (weapon_key + "_blue").lower()
            for vtf_rel in vtf_files:
                vtf_stem = os.path.splitext(os.path.basename(vtf_rel))[0].lower()
                if vtf_stem == wk_blu_stem:
                    try:
                        vtf_data = pak[vtf_rel].read()
                        logger.info(f"BLU текстура мода (by weapon_key_blue): {vtf_rel}")
                        break
                    except Exception:
                        continue

        # ── Приоритет 4: стебель заканчивается на _blue (не служебный) ─────────
        if not vtf_data:
            for vtf_rel in vtf_files:
                stem = os.path.splitext(os.path.basename(vtf_rel))[0].lower()
                if stem.endswith("_blue") and _is_base_vtf(vtf_rel):
                    try:
                        vtf_data = pak[vtf_rel].read()
                        logger.info(f"BLU текстура мода (endswith _blue): {vtf_rel}")
                        break
                    except Exception:
                        continue

        # ── Приоритет 5: игровой VPK ──────────────────────────────────────────
        if not vtf_data and weapon_key and self.textures_vpk_path:
            try:
                from src.data.weapons import WEAPON_TEXTURE_PATHS
                game_pak = self._game_textures_pak()
                if game_pak is None:
                    raise FileNotFoundError(self.textures_vpk_path)
                # Строим BLU-варианты: нестандартные пути (stem + _blue) + стандартные
                _extra_blu = [
                    p.replace(".vtf", "_blue.vtf")
                    for p in WEAPON_TEXTURE_PATHS.get(weapon_key, [])
                ]
                _std_blu = [
                    f"materials/models/workshop_partner/weapons/c_models/{weapon_key}/{weapon_key}_blue.vtf",
                    f"materials/models/weapons/c_models/{weapon_key}/{weapon_key}_blue.vtf",
                    f"materials/models/weapons/c_items/{weapon_key}/{weapon_key}_blue.vtf",
                    f"materials/models/workshop/weapons/c_models/{weapon_key}/{weapon_key}_blue.vtf",
                ]
                blu_game_paths = _extra_blu + _std_blu
                for path in blu_game_paths:
                    try:
                        vtf_data = game_pak[path].read()
                        logger.info(f"BLU текстура из игры: {path}")
                        break
                    except KeyError:
                        continue
            except Exception as exc:
                logger.debug(f"BLU из игры: {exc}")

        if not vtf_data:
            return [], 0.0

        # Уникальное имя 'texture_blu', чтобы не конфликтовать с RED кадрами.
        from src.services import vtf_preview_service as _vps
        frame_paths = _vps.vtf_bytes_to_frame_pngs(
            vtf_data, self._preview_dir, "texture_blu", self._preview_dir)
        if not frame_paths:
            return [], 0.0
        fps = red_framerate if len(frame_paths) > 1 else 0.0
        return frame_paths, fps

    # ── VTF → PNG (все кадры) ─────────────────────────────────────────────── #

    def _vtf_bytes_to_frame_pngs(
        self, vtf_data: bytes, framerate: float = 15.0
    ) -> tuple:
        """
        Конвертирует VTF байты в PNG файлы (по одному на кадр) через общий
        vtf_preview_service. Возвращает (frame_paths: list[str], framerate: float);
        ([], 0.0) при ошибке/пустом VTF.

        Имена кадров совпадают со сервисом: один кадр → texture.png, несколько →
        texture_000.png, texture_001.png, …
        """
        from src.services import vtf_preview_service as _vps
        frame_paths = _vps.vtf_bytes_to_frame_pngs(
            vtf_data, self._preview_dir, "texture", self._preview_dir)
        if not frame_paths:
            return [], 0.0
        if len(frame_paths) > 1:
            logger.info(
                f"Анимированная текстура мода: {len(frame_paths)} кадров @ {framerate:.1f} fps")
        return frame_paths, framerate

    def _read_vmt_framerate_from_pak(self, pak, vmt_files: List[str]) -> float:
        """Ищет animatedtextureframerate в VMT файлах из пака мода (общий парсер)."""
        from src.services import vtf_preview_service as _vps
        return _vps.read_vmt_framerate(pak, vmt_files)

    # ── Поиск reference SMD ───────────────────────────────────────────────── #

    def _find_reference_smd(
        self, directory: str, weapon_key: Optional[str] = None
    ) -> Optional[str]:
        """Находит reference SMD, исключая physics/anim файлы."""
        def skip(p: str) -> bool:
            return any(kw in os.path.basename(p).lower() for kw in NON_REFERENCE_SMD_KEYWORDS)

        # *_reference.smd
        refs = [
            p for p in glob.glob(
                os.path.join(directory, "**", "*_reference.smd"), recursive=True
            )
            if not skip(p)
        ]
        if refs:
            return refs[0]

        # SMD с именем оружия
        if weapon_key:
            wk_smds = [
                p for p in glob.glob(
                    os.path.join(directory, "**", f"*{weapon_key}*.smd"), recursive=True
                )
                if not skip(p)
            ]
            if wk_smds:
                return wk_smds[0]

        # Любой SMD не physics
        all_smds = [
            p for p in glob.glob(
                os.path.join(directory, "**", "*.smd"), recursive=True
            )
            if not skip(p)
        ]
        return all_smds[0] if all_smds else None
