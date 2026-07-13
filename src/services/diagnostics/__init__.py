"""
Диагностика модов (VPK): осмотр готового мода на типовые причины поломок
(фиолетовые текстуры, невидимые модели, конфликты) и подсказки по починке.

Публичный API:
    from src.services.diagnostics import inspect_vpk, DiagnosticReport, Severity

Пакет НЕ зависит от Qt — вся логика чистая и юнит-тестируемая. UI (вкладка
«Диагностика») лежит отдельно в src/ui/diagnostics_panel.py, а фоновый прогон —
в src/services/diagnostics_worker.py.
"""

from src.services.diagnostics.models import (
    Severity,
    Finding,
    DiagnosticReport,
)
from src.services.diagnostics.inspector import inspect_vpk, build_inspected_mod
from src.services.diagnostics.runner import run_all_checks

__all__ = [
    "Severity",
    "Finding",
    "DiagnosticReport",
    "inspect_vpk",
    "build_inspected_mod",
    "run_all_checks",
]
