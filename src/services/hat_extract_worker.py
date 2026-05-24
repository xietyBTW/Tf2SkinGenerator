"""
Воркер для извлечения и декомпиляции 3D-модели шапки из TF2 VPK.

Пайплайн:
  1. Резолвим tf2_misc_dir.vpk через TF2Paths
  2. Ищем MDL в VPK (основной путь + workshop-варианты)
  3. Извлекаем набор файлов (.mdl, .vvd, .vtx, .phy)
  4. Декомпилируем через Crowbar → SMD / QC
  5. Открываем папку с результатом
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from src.services.tf2_paths import TF2Paths
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.services.model_build_service import ModelBuildService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class HatExtractWorker(QThread):
    """
    Фоновый поток для извлечения 3D-модели шапки.

    Сигналы:
        progress(str)          — статусное сообщение
        finished(str)          — путь к папке с результатами
        error(str)             — сообщение об ошибке
    """

    progress = Signal(str)
    finished = Signal(str)   # путь к папке с SMD/QC файлами
    error    = Signal(str)

    def __init__(
        self,
        hat_mdl_path: str,      # относительный путь внутри VPK, напр. "models/player/items/..."
        hat_name: str,          # отображаемое имя (для имени папки)
        tf2_root_dir: str,      # корень TF2 (steamapps/common/Team Fortress 2)
        output_base_dir: str = "export/hats",
        parent=None,
    ):
        super().__init__(parent)
        self._mdl_path      = hat_mdl_path.replace("\\", "/")
        self._hat_name      = hat_name
        self._tf2_root      = tf2_root_dir
        self._output_base   = output_base_dir

    # ── Запуск ────────────────────────────────────────────────────────────── #

    def run(self) -> None:
        try:
            self._extract()
        except Exception as e:
            logger.error(f"Ошибка извлечения шапки: {e}", exc_info=True)
            self.error.emit(str(e))

    def _extract(self) -> None:
        # 1. Резолвим пути TF2
        self.progress.emit("Resolving TF2 paths...")
        try:
            _, tf2_misc_vpk, _ = TF2Paths.resolve(self._tf2_root)
        except FileNotFoundError as e:
            raise RuntimeError(str(e))

        # 2. Готовим папку вывода
        safe_name = _safe_folder_name(self._hat_name)
        out_dir = os.path.join(self._output_base, safe_name)
        extract_dir  = os.path.join(out_dir, "_raw")
        decompile_dir = os.path.join(out_dir, "model")
        os.makedirs(extract_dir, exist_ok=True)
        os.makedirs(decompile_dir, exist_ok=True)

        # 3. Ищем MDL в VPK (основной путь + workshop-варианты)
        self.progress.emit("Searching MDL in VPK...")
        found_path = self._find_mdl(tf2_misc_vpk)
        if not found_path:
            raise RuntimeError(
                f"MDL not found in VPK.\nTried: {self._mdl_path}\nVPK: {tf2_misc_vpk}"
            )
        logger.info(f"MDL найден: {found_path}")

        # 4. Извлекаем набор файлов (.mdl + .vvd + .vtx + .phy)
        self.progress.emit("Extracting model files from VPK...")
        extracted = TF2VPKExtractService.extract_file_set(
            tf2_misc_vpk, found_path, extract_dir
        )

        mdl_file = next((f for f in extracted if f.endswith(".mdl")), None)
        if not mdl_file:
            raise RuntimeError("MDL file not found among extracted files")

        # 5. Декомпилируем через Crowbar
        self.progress.emit("Decompiling with Crowbar...")
        crowbar_exe = TF2Paths.get_crowbar_path()
        if not os.path.exists(crowbar_exe):
            raise RuntimeError(
                f"Crowbar not found: {crowbar_exe}\n"
                "Put CrowbarCommandLineDecomp.exe into tools/crowbar/"
            )

        ModelBuildService.decompile(mdl_file, decompile_dir, crowbar_exe)

        self.progress.emit("Done!")
        logger.info(f"Шапка извлечена в: {decompile_dir}")
        self.finished.emit(os.path.abspath(decompile_dir))

    # ── MDL-поиск ─────────────────────────────────────────────────────────── #

    # Имена классов TF2 для подстановки вместо %s и перебора суффиксов
    _TF2_CLASSES = [
        "heavy", "scout", "soldier", "pyro",
        "demoman", "engineer", "medic", "sniper", "spy",
    ]

    def _find_mdl(self, vpk_path: str) -> Optional[str]:
        """
        Пробует несколько вариантов пути MDL в VPK и возвращает первый найденный.

        Обрабатывает:
        - %s-плейсхолдер (ghostly_gibus_%s.mdl → ghostly_gibus_heavy.mdl и т.д.)
        - Класс-суффиксы (_heavy, _scout, ...) если нужный не нашёлся
        - workshop / workshop_partner / основной prefix
        """
        norm = self._mdl_path.replace("\\", "/").lower()
        candidates: list[str] = []

        # ── Раскрываем %s → все варианты классов ──────────────────────────
        if "%s" in norm:
            for cls in self._TF2_CLASSES:
                try:
                    candidates.append(norm % cls)
                except (TypeError, ValueError):
                    candidates.append(norm.replace("%s", cls))
        else:
            candidates.append(norm)

        # ── Для каждого базового пути добавляем workshop-варианты ─────────
        expanded: list[str] = []
        for c in candidates:
            expanded.append(c)
            if "models/player/items" in c and "workshop" not in c:
                expanded.append(c.replace("models/player/items",
                                          "models/workshop_partner/player/items"))
                expanded.append(c.replace("models/player/items",
                                          "models/workshop/player/items"))
            elif "models/workshop/player/items" in c:
                expanded.append(c.replace("models/workshop/player/items",
                                          "models/workshop_partner/player/items"))
                expanded.append(c.replace("models/workshop/player/items",
                                          "models/player/items"))
            elif "models/workshop_partner/player/items" in c:
                expanded.append(c.replace("models/workshop_partner/player/items",
                                          "models/workshop/player/items"))
                expanded.append(c.replace("models/workshop_partner/player/items",
                                          "models/player/items"))

        # ── Если в пути есть суффикс класса — добавляем другие классы ─────
        import re as _re
        cls_pattern = _re.compile(
            r'_(heavy|scout|soldier|pyro|demoman|engineer|medic|sniper|spy)(\.mdl)$'
        )
        extra: list[str] = []
        for c in expanded:
            m = cls_pattern.search(c)
            if m:
                for cls in self._TF2_CLASSES:
                    variant = cls_pattern.sub(f'_{cls}\\2', c)
                    if variant not in expanded:
                        extra.append(variant)
        expanded += extra

        # ── Убираем дубли, сохраняем порядок ──────────────────────────────
        seen: set[str] = set()
        unique = [c for c in expanded if not (c in seen or seen.add(c))]

        for candidate in unique:
            try:
                if TF2VPKExtractService.check_mdl_exists(vpk_path, candidate):
                    logger.info(f"MDL найден: {candidate}")
                    return candidate
            except Exception:
                continue
        return None


# ── Утилиты ───────────────────────────────────────────────────────────────── #

def _safe_folder_name(name: str) -> str:
    """Превращает отображаемое имя шапки в безопасное имя папки."""
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-")
    cleaned = "".join(c if c in keep else "_" for c in name).strip()
    return cleaned[:60] or "hat"
