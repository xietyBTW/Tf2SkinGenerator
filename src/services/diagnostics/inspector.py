"""Осмотр VPK: распаковка → сбор InspectedMod → прогон проверок.

`build_inspected_mod(root)` работает с УЖЕ распакованной папкой и полностью
юнит-тестируем. `inspect_vpk(path)` — обёртка: распаковывает VPK во временную
папку (через существующий CustomVPKService), собирает слепок, гоняет проверки,
чистит за собой.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from src.services.diagnostics.context import InspectedMod, MdlInfo, parse_vmt
from src.services.diagnostics.mdl_reader import read_mdl, MdlHeader
from src.services.diagnostics.vtf_reader import read_vtf_size
from src.services.diagnostics.models import (
    DiagnosticReport, Finding, Severity,
)
from src.services.diagnostics.runner import run_all_checks
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_VTX_SUFFIXES = (".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".vtx")


def build_inspected_mod(root: Path) -> InspectedMod:
    """Собирает слепок мода из распакованной директории `root`."""
    root = Path(root)
    mod = InspectedMod(root=root)

    if not root.exists():
        return mod

    mod.top_entries = sorted(p.name for p in root.iterdir()) if root.is_dir() else []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix().lower()
        mod.all_rel.add(rel)
        ext = path.suffix.lower()

        if ext == ".vmt":
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            mod.vmts.append(parse_vmt(rel, content))
        elif ext == ".vtf":
            key = rel[: -len(".vtf")]
            mod.vtf_rel.add(key)
            size = read_vtf_size(str(path))
            if size is not None:
                mod.vtf_sizes[key] = size
            else:
                mod.bad_vtf.add(key)   # заголовок не прочитался → битый/пустой VTF
        elif ext == ".mdl":
            mod.mdls.append(_build_mdl_info(path, root, rel))

    return mod


def _build_mdl_info(path: Path, root: Path, rel: str) -> MdlInfo:
    header = read_mdl(str(path)) or MdlHeader()
    stem_path = path.with_suffix("")   # …/model (без .mdl)
    has_vvd = stem_path.with_suffix(".vvd").exists()
    has_vtx = any(
        (stem_path.parent / (stem_path.name + suf)).exists() for suf in _VTX_SUFFIXES
    )
    return MdlInfo(rel_path=rel, header=header, has_vvd=has_vvd, has_vtx=has_vtx)


def _gather_other_mod_paths(inspected_vpk: str) -> set:
    """Собирает пути файлов из ДРУГИХ модов в tf/custom (для поиска конфликтов).

    Best-effort: если путь к TF2 не задан, папки нет или что-то не открылось —
    возвращаем пусто (проверка конфликтов просто не сработает). Многотомные VPK
    (`_NNN.vpk`) пропускаем — их читает `_dir.vpk`. Себя исключаем."""
    import re

    paths: set = set()
    try:
        from src.config.app_config import AppConfig
        tf2_root = AppConfig.get_tf2_game_folder()
    except Exception:
        return paths
    if not tf2_root:
        return paths

    custom = Path(tf2_root) / "tf" / "custom"
    if not custom.is_dir():
        return paths

    try:
        self_real = os.path.realpath(inspected_vpk)
    except OSError:
        self_real = inspected_vpk

    part_re = re.compile(r"_\d{3}\.vpk$", re.IGNORECASE)
    try:
        import vpk as vpklib
    except ImportError:
        return paths

    for entry in custom.glob("*.vpk"):
        if part_re.search(entry.name):
            continue                      # том многотомного VPK — пропускаем
        try:
            if os.path.realpath(str(entry)) == self_real:
                continue                  # это осматриваемый мод
            pak = vpklib.open(str(entry))
            for f in pak:
                paths.add(f.replace("\\", "/").lower())
        except Exception:                 # noqa: BLE001 — один битый мод не мешает
            continue
        if len(paths) > 400_000:          # разумный предел памяти
            break
    return paths


def inspect_vpk(vpk_path: str) -> DiagnosticReport:
    """Полный осмотр VPK-файла. Возвращает DiagnosticReport (никогда не бросает —
    ошибку распаковки оформляет как ERROR-находку)."""
    report = DiagnosticReport()

    if not vpk_path or not os.path.exists(vpk_path):
        report.add(Finding(
            Severity.ERROR, "vpk.not_found", "Файл VPK не найден",
            detail=f"Путь не существует: {vpk_path}",
        ))
        return report

    from src.services.custom_vpk_service import CustomVPKService

    tmp = Path(tempfile.mkdtemp(prefix="tf2sg_diag_"))
    try:
        extract_dir = tmp / "mod"
        ok = CustomVPKService.extract_vpk_to_dir(vpk_path, str(extract_dir))
        if not ok:
            report.add(Finding(
                Severity.ERROR, "vpk.extract_failed", "Не удалось распаковать VPK",
                detail="Файл повреждён или это не однофайловый VPK-мод.",
                fix_hint="Проверьте, что это корректный .vpk (не _dir/_000).",
            ))
            return report

        mod = build_inspected_mod(extract_dir)
        mod.external_paths = _gather_other_mod_paths(vpk_path)
        report.extend(run_all_checks(mod))
        return report
    except Exception as e:                       # noqa: BLE001 — диагностика не должна падать
        logger.error(f"Диагностика VPK упала: {e}", exc_info=True)
        report.add(Finding(
            Severity.ERROR, "diag.crashed", "Ошибка при диагностике",
            detail=str(e),
        ))
        return report
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
