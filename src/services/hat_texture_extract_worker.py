"""
Воркер для извлечения текстуры шапки из TF2 VPK.

Использует ту же цепочку что и 3D Preview:
  QC → VMT → $baseTexture → VTF

Порядок:
  1. Ищем декомпилированный QC в кэше (если пользователь уже смотрел шапку в 3D).
  2. Если кэша нет — извлекаем MDL из VPK и декомпилируем через Crowbar.
  3. Парсим QC → $cdmaterials.
  4. Парсим SMD → имена материалов.
  5. Ищем VMT в обоих VPK (misc + textures).
  6. Читаем $baseTexture из VMT → ищем VTF в обоих VPK.
  7. Сохраняем VTF, при необходимости конвертируем в PNG/TGA/JPG.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal

from src.services.base_worker import BaseWorker
from src.services.game_vpk_reader import GameVpkReader
from src.services.material_resolver import MaterialResolver
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class HatTextureExtractWorker(BaseWorker):
    # Многоточечный emit finished внутри _extract → не шаблонный work(),
    # наследуем BaseWorker только ради безопасного stop().
    finished = Signal(bool, str)   # (success, message)
    progress = Signal(int, str)    # (pct, status)
    error    = Signal(str)

    def __init__(
        self,
        hat_mdl_path: str,        # полный относительный путь MDL внутри VPK
        tf2_root_dir: str,
        export_folder: str,
        export_format: str = "PNG",
        language: str = "en",
        parent=None,
    ):
        super().__init__(parent)
        self._hat_mdl  = hat_mdl_path.replace("\\", "/").lower()
        self._tf2_root = tf2_root_dir
        self._export   = export_folder
        self._fmt      = export_format.upper()
        self._lang     = language

    # ── Точка входа ──────────────────────────────────────────────────────── #

    def run(self) -> None:
        try:
            self._extract()
        except Exception as exc:
            logger.error(f"[hat-tex] Ошибка: {exc}", exc_info=True)
            self.error.emit(str(exc))
            self.finished.emit(False, str(exc))

    # ── Основная логика ───────────────────────────────────────────────────── #

    def _extract(self) -> None:
        from src.services.tf2_paths import TF2Paths

        self.progress.emit(5, "Resolving TF2 paths...")
        _, misc_vpk, _ = TF2Paths.resolve(self._tf2_root)
        textures_vpk   = TF2Paths.resolve_textures_vpk(self._tf2_root)

        # ── 1. Ищем декомпилированный QC ─────────────────────────────────── #
        self.progress.emit(15, "Looking for cached decompile...")
        decomp_dir = self._get_decomp_dir(misc_vpk)
        if not decomp_dir:
            self.finished.emit(False, "Failed to decompile model (Crowbar required)")
            return

        if self.isInterruptionRequested():
            return

        # ── 2. Разбираем QC (один раз, общим разбором) ─────────────────────── #
        self.progress.emit(35, "Parsing QC file...")
        from src.services import qc_skin_parser
        model = qc_skin_parser.load_model(decomp_dir)
        if model is None:
            self.finished.emit(False, f"QC not found in: {decomp_dir}")
            return

        cdmaterials = model.cdmaterials
        skin0_textures = model.skin0
        if not cdmaterials:
            self.finished.emit(False, "No $cdmaterials in QC")
            return

        logger.info(f"[hat-tex] cdmaterials={cdmaterials}, skin0={skin0_textures}")

        # ── 3. Имена материалов из SMD или из $texturegroup ──────────────── #
        mat_names = self._get_mat_names(decomp_dir, skin0_textures)
        if not mat_names:
            self.finished.emit(False, "No material names found in SMD/QC")
            return

        logger.info(f"[hat-tex] mat_names={mat_names}")

        # ── 4-5. QC → VMT → $baseTexture → VTF через кэширующий reader ────── #
        # misc первым (VMT обычно там), textures вторым (VTF). GameVpkReader
        # открывает каждый VPK один раз и переиспользует ту же цепочку поиска,
        # что и 3D Preview.
        self.progress.emit(45, "Opening VPK archives...")
        os.makedirs(self._export, exist_ok=True)

        extracted: list[str] = []
        seen_basetex: set = set()   # избегаем дублей если несколько mat → одна VTF
        painted = False             # у текстуры есть маска командной окраски
        total = max(len(mat_names), 1)

        with GameVpkReader([misc_vpk, textures_vpk]) as reader:
            if not reader.paks:
                self.finished.emit(False, "Could not open any VPK file")
                return

            # Цепочка VMT → $basetexture → VTF — общая (MaterialResolver);
            # краску НЕ впечатываем: экспорт отдаёт исходный файл игры
            materials = MaterialResolver(reader, self._export, apply_tint=False)

            self.progress.emit(55, "Searching VMT/VTF in VPK...")
            for idx, mat_name in enumerate(mat_names):
                if self.isInterruptionRequested():
                    break

                pct = 55 + int(idx / total * 35)
                self.progress.emit(pct, f"Extracting: {mat_name}...")

                info = materials.describe(mat_name, cdmaterials)
                basetexture = info.basetexture
                if not basetexture:
                    logger.info(f"[hat-tex] no $basetexture for '{mat_name}'")
                    continue
                if basetexture in seen_basetex:
                    continue
                seen_basetex.add(basetexture)

                vtf_data = materials.vtf_bytes(mat_name, cdmaterials)
                if not vtf_data:
                    logger.warning(f"[hat-tex] VTF not found for $baseTexture={basetexture}")
                    continue

                if info.tint is not None and not info.tint.is_neutral:
                    painted = True

                out = self._save_vtf(vtf_data, basetexture)
                if out:
                    extracted.append(out)
                    logger.info(f"[hat-tex] Extracted: {out}")

        if not extracted:
            self.finished.emit(False, "Textures not found in VPK (VMT/VTF chain returned nothing)")
            return

        self.progress.emit(100, "Done")
        msg = extracted[0] if len(extracted) == 1 else "\n".join(extracted)
        if painted:
            # Файл отдаём сырым: в игре краску накладывает сам движок, и
            # впечатывать её значило бы получить двойную окраску. Но тёмные
            # пятна маски выглядят как испорченная текстура — поясняем.
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get(self._lang, TRANSLATIONS["en"])
            note = t.get("hat_tex_paint_mask_note")
            if note:
                msg = f"{msg}\n\n{note}"
        self.finished.emit(True, msg)

    # ── Вспомогательные методы ────────────────────────────────────────────── #

    def _get_decomp_dir(self, misc_vpk: str) -> Optional[str]:
        """
        Возвращает путь к папке с декомпилированной шапкой.
        Сначала ищет в кэше, затем декомпилирует через ExtractModelService.
        """
        from src.services import decompile_cache
        cached = decompile_cache.get_cached_decompile(
            self._hat_mdl, misc_vpk, self._hat_mdl
        )
        if cached and os.path.isdir(cached):
            logger.info(f"[hat-tex] Используем кэш декомпила: {cached}")
            return cached

        # Декомпилируем через ExtractModelService (тот же код что и в 3D preview)
        self.progress.emit(20, "Decompiling model (Crowbar)...")
        from src.services.extract_model_service import ExtractModelService

        def _prog(pct: int, msg: str) -> None:
            mapped = 20 + int(pct * 0.15)   # 20-35%
            self.progress.emit(mapped, msg)
            if self.isInterruptionRequested():
                raise InterruptedError()

        try:
            success, msg, cancelled, data = (
                ExtractModelService.prepare_decompiled_model_files_with_progress(
                    self._tf2_root,
                    "hat",
                    self._hat_mdl,
                    self._lang,
                    progress_callback=_prog,
                    cancel_callback=self.isInterruptionRequested,
                )
            )
        except InterruptedError:
            return None

        if not success or not data:
            logger.warning(f"[hat-tex] Деком. не удался: {msg}")
            return None

        return data.get("decompile_dir")

    def _get_mat_names(self, decomp_dir: str, skin0_textures: list) -> list:
        """
        Возвращает имена материалов.
        Приоритет: $texturegroup из QC → имена материалов из SMD.
        """
        if skin0_textures:
            return list(skin0_textures)

        # Парсим SMD — ищем имена материалов из секции triangles
        smd_files = sorted(glob.glob(os.path.join(decomp_dir, "*.smd")))
        # Предпочитаем reference SMD (не "idle", не "_anims")
        ref_smds = [s for s in smd_files if
                    "idle" not in os.path.basename(s).lower()
                    and "anim" not in os.path.basename(s).lower()]
        target = ref_smds[0] if ref_smds else (smd_files[0] if smd_files else None)
        if not target:
            return []

        import re
        seen: list = []
        try:
            with open(target, encoding="utf-8", errors="replace") as f:
                content = f.read()
            m = re.search(r"\btriangles\b(.*?)\bend\b", content, re.DOTALL | re.IGNORECASE)
            if m:
                lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
                i = 0
                while i < len(lines):
                    mat = lines[i]
                    i += 4   # material + 3 verts
                    if mat and mat not in seen:
                        seen.append(mat)
        except Exception as exc:
            logger.warning(f"[hat-tex] Ошибка парсинга SMD {target}: {exc}")

        return seen

    def _save_vtf(self, vtf_data: bytes, basetexture: str) -> Optional[str]:
        """Сохраняет VTF-байты в export_folder. Конвертирует если нужно."""
        stem = Path(basetexture).stem
        vtf_path = os.path.join(self._export, f"{stem}.vtf")
        try:
            with open(vtf_path, "wb") as f:
                f.write(vtf_data)
        except OSError as exc:
            logger.warning(f"[hat-tex] Ошибка записи VTF {vtf_path}: {exc}")
            return None

        if self._fmt == "VTF":
            return vtf_path

        # Конвертируем
        from src.services.tf2_vpk_extract_service import TF2VPKExtractService
        converted = TF2VPKExtractService._convert_vtf_to_image(
            vtf_path, self._export, self._fmt
        )
        try:
            os.remove(vtf_path)
        except OSError:
            pass
        return converted or vtf_path
