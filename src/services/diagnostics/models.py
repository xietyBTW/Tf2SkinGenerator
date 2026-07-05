"""Данные диагностики: находки (Finding) и отчёт (DiagnosticReport).

Чистые dataclass'ы без зависимостей — легко создавать в тестах и сериализовать
для UI. Проверки (checks.py) возвращают списки Finding; runner собирает их в
DiagnosticReport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Severity(Enum):
    """Уровень находки. Порядок важен для сортировки (ошибки выше)."""

    ERROR = "error"      # мод почти наверняка сломан (фиолет / невидимо / не грузится)
    WARNING = "warning"  # потенциальная проблема или плохая практика
    INFO = "info"        # успешная проверка / справочная информация

    @property
    def rank(self) -> int:
        return {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}[self]


@dataclass(frozen=True)
class Finding:
    """Одна находка диагностики.

    severity  — уровень (ошибка/предупреждение/инфо);
    code      — стабильный машинный код проверки (для тестов/фиксов), напр.
                "vmt.missing_texture";
    title     — короткий заголовок для UI;
    detail    — пояснение «почему это проблема»;
    fix_hint  — что сделать, чтобы починить (пусто, если нечего советовать);
    location  — путь внутри мода, к которому относится находка (или "").
    """

    severity: Severity
    code: str
    title: str
    detail: str = ""
    fix_hint: str = ""
    location: str = ""


@dataclass
class DiagnosticReport:
    """Результат диагностики: список находок + удобные срезы для UI."""

    findings: List[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def extend(self, findings: List[Finding]) -> None:
        self.findings.extend(findings)

    # ── Срезы по уровню ──────────────────────────────────────────────────── #

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def infos(self) -> List[Finding]:
        return [f for f in self.findings if f.severity is Severity.INFO]

    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def is_healthy(self) -> bool:
        """True, если нет ни ошибок, ни предупреждений."""
        return not any(
            f.severity in (Severity.ERROR, Severity.WARNING) for f in self.findings
        )

    def sorted(self) -> List[Finding]:
        """Находки, отсортированные по важности (ошибки → предупреждения → инфо)."""
        return sorted(self.findings, key=lambda f: f.severity.rank)
