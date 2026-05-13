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
from src.services.model_build_service import ModelBuildService
from src.services.tf2_paths import TF2Paths
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class Preview3DWorker(QThread):
    """Готовит OBJ + текстуру для 3D Preview."""

    # Модель и первый кадр текстуры готовы
    ready    = Signal(str, str)
    # Анимированная текстура: список путей к PNG кадрам + framerate
    # Эмитируется ПОСЛЕ ready если кадров > 1
    animated = Signal(object, float)
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
            if self.isInterruptionRequested():
                return

            # ── 2. OBJ ────────────────────────────────────────────────────── #
            self.progress.emit(self._p['converting'])
            obj_path = os.path.join(self._preview_dir, "model.obj")
            from src.services.smd_to_obj_service import SmdToObjService
            if not SmdToObjService.convert(smd_path, obj_path):
                self.failed.emit(self._p['conv_error'])
                return
            if self.isInterruptionRequested():
                return

            # ── 3. Текстура ───────────────────────────────────────────────── #
            self.progress.emit(self._p['texture'])
            frame_paths, framerate = self._extract_texture_frames()

            first_tex = frame_paths[0] if frame_paths else ""
            self.ready.emit(obj_path, first_tex)

            # Если анимированная — отправляем все кадры отдельным сигналом
            if len(frame_paths) > 1:
                self.animated.emit(frame_paths, framerate)

        except Exception as exc:
            logger.error(f"Preview3DWorker: {exc}", exc_info=True)
            self.failed.emit(str(exc))

    # ── Получение SMD ─────────────────────────────────────────────────────── #

    def _get_reference_smd(self) -> Optional[str]:
        """Возвращает reference SMD из кэша или после декомпиляции."""
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

        paths_to_try = ExtractModelService._build_paths_to_try(
            self.mode, self.weapon_key
        )

        found_rel: Optional[str] = None
        for path in paths_to_try:
            if self.isInterruptionRequested():
                return None
            try:
                if TF2VPKExtractService.check_mdl_exists(self.misc_vpk_path, path):
                    found_rel = path
                    break
            except Exception:
                continue

        if not found_rel:
            logger.warning(f"MDL не найден в VPK для {self.weapon_key}")
            return None

        try:
            mdl_dir = tempfile.mkdtemp(prefix="tf2sg_mdl_")
            extracted = TF2VPKExtractService.extract_file_set(
                self.misc_vpk_path, found_rel, mdl_dir, None
            )
            mdl_file = next((f for f in extracted if f.endswith(".mdl")), None)
            if not mdl_file:
                shutil.rmtree(mdl_dir, ignore_errors=True)
                return None

            if self.isInterruptionRequested():
                shutil.rmtree(mdl_dir, ignore_errors=True)
                return None

            self.progress.emit(self._p['decompiling'])
            crowbar     = TF2Paths.get_crowbar_path()
            decomp_dir  = tempfile.mkdtemp(prefix="tf2sg_decomp_")
            ModelBuildService.decompile(mdl_file, decomp_dir, crowbar)

            # Сохраняем в кэш, чтобы следующий раз был мгновенным
            decompile_cache.save_to_cache(
                self.weapon_key, self.misc_vpk_path, found_rel, decomp_dir
            )

            shutil.rmtree(mdl_dir, ignore_errors=True)
            return self._find_reference_smd(decomp_dir)

        except Exception as exc:
            logger.error(f"Ошибка декомпиляции для 3D Preview: {exc}", exc_info=True)
            return None

    def _find_reference_smd(self, directory: str) -> Optional[str]:
        """Находит reference SMD (исключая physics/anim) в директории."""
        _SKIP = ("physics", "phys", "anim", "idle", "pose")

        def skip(path: str) -> bool:
            return any(kw in os.path.basename(path).lower() for kw in _SKIP)

        # Лучший вариант — *_reference.smd
        refs = [p for p in glob.glob(os.path.join(directory, "*_reference.smd"))
                if not skip(p)]
        if refs:
            return refs[0]

        # SMD с weapon_key в имени
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

    # ── Извлечение текстуры ───────────────────────────────────────────────── #

    def _extract_texture_frames(self) -> tuple:
        """
        Извлекает VTF текстуру из VPK.

        Если VTF содержит несколько кадров (анимированная текстура) —
        сохраняет каждый кадр отдельным PNG и читает framerate из VMT.

        Returns:
            (frame_paths: list[str], framerate: float)
            frame_paths пустой если текстура не найдена.
        """
        try:
            import vpk as vpklib

            vtf_search = [
                f"materials/models/workshop_partner/weapons/c_models/{self.weapon_key}/{self.weapon_key}.vtf",
                f"materials/models/weapons/c_models/{self.weapon_key}/{self.weapon_key}.vtf",
                f"materials/models/weapons/c_items/{self.weapon_key}/{self.weapon_key}.vtf",
                f"materials/models/workshop/weapons/c_models/{self.weapon_key}/{self.weapon_key}.vtf",
            ]
            vmt_search = [p.replace(".vtf", ".vmt") for p in vtf_search]

            pak = vpklib.open(self.textures_vpk_path)
            vtf_data: Optional[bytes] = None
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

            # Сохраняем VTF во временный файл
            vtf_file = os.path.join(self._preview_dir, "_tmp.vtf")
            with open(vtf_file, "wb") as f:
                f.write(vtf_data)

            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image

            # Читаем все кадры
            all_frames_rgba, w, h = VTFLib.read_vtf_all_frames(vtf_file)
            os.remove(vtf_file)

            frame_paths: list[str] = []
            for i, rgba in enumerate(all_frames_rgba):
                img  = Image.frombytes("RGBA", (w, h), rgba)
                name = f"texture_{i:03d}.png" if len(all_frames_rgba) > 1 else "texture.png"
                path = os.path.join(self._preview_dir, name)
                img.save(path)
                frame_paths.append(path)

            # Framerate из VMT
            framerate = 0.0
            if len(frame_paths) > 1:
                framerate = self._read_vmt_framerate(pak, vmt_search)
                logger.info(
                    f"Анимированная текстура: {len(frame_paths)} кадров "
                    f"@ {framerate:.1f} fps для {self.weapon_key}"
                )

            return frame_paths, framerate

        except Exception as exc:
            logger.warning(f"Не удалось извлечь текстуру для 3D Preview: {exc}")
            return [], 0.0

    def _read_vmt_framerate(self, pak, vmt_search: list) -> float:
        """Ищет animatedtextureframerate в VMT файле из VPK."""
        import re
        DEFAULT_FPS = 15.0
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
