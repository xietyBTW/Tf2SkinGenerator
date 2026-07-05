"""Оркестратор проверок: прогоняет все зарегистрированные checks по InspectedMod.

Реестр CHECKS — единственная точка расширения: добавил функцию-проверку сюда,
и она автоматически участвует в диагностике. Каждая проверка изолирована, её
падение не роняет остальные (логируем и продолжаем).
"""

from __future__ import annotations

from typing import Callable, List

from src.services.diagnostics import checks
from src.services.diagnostics.context import InspectedMod
from src.services.diagnostics.models import Finding
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

CheckFn = Callable[..., List[Finding]]   # (InspectedMod, lang) → List[Finding]

# Порядок не важен — находки сортируются по серьёзности в DiagnosticReport.
CHECKS: List[CheckFn] = [
    checks.check_structure,
    checks.check_vmt_syntax,
    checks.check_vmt_textures_exist,
    checks.check_vtf_dimensions,
    checks.check_vtf_corrupt,
    checks.check_models,
    checks.check_conflicts,
    checks.check_summary,
]


def run_all_checks(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """Прогоняет все проверки; сбой одной не мешает остальным."""
    out: List[Finding] = []
    for check in CHECKS:
        try:
            out.extend(check(mod, lang))
        except Exception as e:                   # noqa: BLE001 — изолируем проверки
            logger.error(f"Проверка {check.__name__} упала: {e}", exc_info=True)
    return out
