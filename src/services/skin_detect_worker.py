"""
Воркер определения стилей (skinfamilies) оригинальной игровой модели.

Используется при замене модели кастомной: чтобы приложение узнало, сколько
стилей (skin 0/1/2…) и какие роли (Bloody/Clean/команды/австралий) есть у
оригинала, и предложило пользователю их переопределить.

Источник истины — QC декомпилированной игровой модели:
  1. Сначала ищем готовый QC в кэше декомпиляции (мгновенно).
  2. Если кэша нет — извлекаем MDL из VPK и декомпилируем через Crowbar
     (тот же путь, что и 3D-превью; результат тоже кладётся в кэш).

НИЧЕГО не трогает в дефолтном пути сборки — только читает QC и отдаёт
структуру стилей наверх через сигнал.
"""

import os
import glob
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


class SkinDetectWorker(QThread):
    """Определяет skinfamilies оригинальной модели в фоне."""

    # dict из ModelBuildService.extract_skin_info (num_skins, roles, is_team, …)
    detected = Signal(object)
    # Не удалось (модель не найдена / ошибка декомпиляции) — UI просто не
    # показывает стили, кастомная замена продолжает работать как одно-скиновая.
    failed = Signal(str)

    def __init__(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        lang: str = 'en',
        parent=None,
    ):
        super().__init__(parent)
        self.weapon_key = weapon_key
        self.mode = mode
        self.misc_vpk_path = misc_vpk_path
        self._lang = lang

    def run(self) -> None:
        try:
            qc_path = self._get_qc()
            if not qc_path or not os.path.exists(qc_path):
                self.failed.emit("qc_not_found")
                return
            info = ModelBuildService.extract_skin_info(qc_path)
            if not info:
                self.failed.emit("no_skin_info")
                return
            logger.info(
                f"[SKIN] {self.weapon_key}: num_skins={info.get('num_skins')} "
                f"roles={info.get('roles')} is_team={info.get('is_team')} "
                f"australium={info.get('has_australium')}"
            )
            self.detected.emit(info)
        except Exception as exc:
            logger.warning(f"[SKIN] detect failed for {self.weapon_key}: {exc}", exc_info=True)
            self.failed.emit(str(exc))

    # ── получение QC ─────────────────────────────────────────────────────── #

    def _get_qc(self) -> Optional[str]:
        """QC из кэша или после декомпиляции (cache miss)."""
        # 1) Быстрый путь — любой кэш для этого weapon_key.
        cached_qc = decompile_cache.find_cached_qc_for_weapon(self.weapon_key)
        if cached_qc:
            logger.info(f"[SKIN] кэш QC для {self.weapon_key}")
            return cached_qc

        # 2) Cache miss — извлекаем и декомпилируем (как 3D-превью).
        return self._extract_and_decompile()

    def _mdl_rel(self) -> str:
        from src.data.weapons import PREVIEW_MDL_OVERRIDE
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS as _PBK, SPY_MASK_MODE_KEY as _SMK
        override = PREVIEW_MDL_OVERRIDE.get(self.weapon_key)
        if self.mode == "hat" or self.mode in _PBK or self.mode == _SMK:
            return self.weapon_key
        if override:
            return override
        return WEAPON_MDL_PATHS.get(
            self.weapon_key,
            f"models/weapons/c_models/{self.weapon_key}/{self.weapon_key}.mdl",
        )

    def _extract_and_decompile(self) -> Optional[str]:
        if not self.misc_vpk_path or not os.path.exists(self.misc_vpk_path):
            logger.warning(f"[SKIN] misc VPK не найден: {self.misc_vpk_path}")
            return None
        crowbar = os.path.abspath(TF2Paths.get_crowbar_path())
        if not os.path.exists(crowbar):
            logger.warning(f"[SKIN] Crowbar не найден: {crowbar}")
            return None

        mdl_rel = self._mdl_rel()
        from src.data.weapons import PREVIEW_MDL_OVERRIDE
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS as _PBK
        from src.services.extract_model_service import ExtractModelService

        if self.mode == "hat" or self.mode in _PBK or self.weapon_key in PREVIEW_MDL_OVERRIDE:
            paths_to_try = [mdl_rel]
        else:
            paths_to_try = ExtractModelService._build_paths_to_try(self.mode, self.weapon_key)

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
            logger.warning(f"[SKIN] MDL не найден в VPK для {self.weapon_key}")
            return None

        mdl_dir = decomp_dir = None
        cached_dir = None
        try:
            mdl_dir = tempfile.mkdtemp(prefix="tf2sg_skin_mdl_")
            extracted = TF2VPKExtractService.extract_file_set(
                self.misc_vpk_path, found_rel, mdl_dir
            )
            mdl_file = next((f for f in extracted if f.endswith(".mdl")), None)
            if not mdl_file:
                return None
            if self.isInterruptionRequested():
                return None
            decomp_dir = tempfile.mkdtemp(prefix="tf2sg_skin_decomp_")
            ModelBuildService.decompile(mdl_file, decomp_dir, crowbar)
            cached_dir = decompile_cache.save_to_cache(
                self.weapon_key, self.misc_vpk_path, found_rel, decomp_dir
            )
            # QC читаем из кэш-копии, чтобы temp-папку можно было удалить.
            search_dir = cached_dir or decomp_dir
            qcs = glob.glob(os.path.join(search_dir, "*.qc"))
            return qcs[0] if qcs else None
        except Exception as exc:
            logger.warning(f"[SKIN] decompile error для {self.weapon_key}: {exc}")
            return None
        finally:
            if mdl_dir:
                shutil.rmtree(mdl_dir, ignore_errors=True)
            # temp-папку декомпиляции удаляем только если QC сохранён в кэш —
            # иначе вызывающий код продолжает читать из decomp_dir.
            if decomp_dir and cached_dir:
                shutil.rmtree(decomp_dir, ignore_errors=True)
