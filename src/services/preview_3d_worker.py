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

    # Модель и текстура готовы (texture_path может быть пустой строкой)
    ready    = Signal(str, str)
    # Ошибка
    failed   = Signal(str)
    # Текстовый прогресс для UI
    progress = Signal(str)

    def __init__(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
        parent=None,
    ):
        super().__init__(parent)
        self.weapon_key        = weapon_key
        self.mode              = mode
        self.misc_vpk_path     = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self._preview_dir: Optional[str] = None

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
        try:
            self._preview_dir = tempfile.mkdtemp(prefix="tf2sg_3d_")

            # ── 1. SMD ────────────────────────────────────────────────────── #
            self.progress.emit("Поиск модели...")
            smd_path = self._get_reference_smd()
            if not smd_path:
                self.failed.emit("Модель не найдена в VPK")
                return
            if self.isInterruptionRequested():
                return

            # ── 2. OBJ ────────────────────────────────────────────────────── #
            self.progress.emit("Конвертация модели...")
            obj_path = os.path.join(self._preview_dir, "model.obj")
            from src.services.smd_to_obj_service import SmdToObjService
            if not SmdToObjService.convert(smd_path, obj_path):
                self.failed.emit("Ошибка конвертации модели")
                return
            if self.isInterruptionRequested():
                return

            # ── 3. Текстура ───────────────────────────────────────────────── #
            self.progress.emit("Загрузка текстуры...")
            texture_path = self._extract_texture()

            self.ready.emit(obj_path, texture_path or "")

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

        self.progress.emit("Извлечение модели из VPK...")

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

            self.progress.emit("Декомпиляция модели...")
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

    def _extract_texture(self) -> Optional[str]:
        """Извлекает основную VTF текстуру → texture.png в preview_dir."""
        try:
            import vpk as vpklib

            search_paths = [
                f"materials/models/weapons/c_models/{self.weapon_key}/{self.weapon_key}.vtf",
                f"materials/models/weapons/c_items/{self.weapon_key}/{self.weapon_key}.vtf",
                f"materials/models/workshop_partner/weapons/c_models/{self.weapon_key}/{self.weapon_key}.vtf",
                f"materials/models/workshop/weapons/c_models/{self.weapon_key}/{self.weapon_key}.vtf",
            ]

            pak = vpklib.open(self.textures_vpk_path)
            vtf_data: Optional[bytes] = None
            for path in search_paths:
                try:
                    vtf_data = pak[path].read()
                    logger.debug(f"3D Preview текстура: {path}")
                    break
                except KeyError:
                    continue

            if not vtf_data:
                logger.warning(f"Текстура для {self.weapon_key} не найдена в VPK")
                return None

            vtf_file = os.path.join(self._preview_dir, "_tmp.vtf")
            with open(vtf_file, "wb") as f:
                f.write(vtf_data)

            from src.services.vtflib_wrapper import VTFLib
            rgba, w, h = VTFLib.read_vtf_as_rgba(vtf_file)

            from PIL import Image
            img      = Image.frombytes("RGBA", (w, h), rgba)
            png_path = os.path.join(self._preview_dir, "texture.png")
            img.save(png_path)
            os.remove(vtf_file)
            return png_path

        except Exception as exc:
            logger.warning(f"Не удалось извлечь текстуру для 3D Preview: {exc}")
            return None
