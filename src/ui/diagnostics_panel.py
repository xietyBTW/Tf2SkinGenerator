"""Вкладка «Диагностика»: пользователь даёт готовый VPK-мод, приложение
осматривает его на типовые причины поломок и показывает находки с подсказками.

UI-слой: вся логика проверок — в src/services/diagnostics (без Qt). Здесь только
выбор файла (кнопка/drag-drop), фоновый прогон и рендер находок в стиле приложения.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFrame, QFileDialog, QSizePolicy,
)

from src.services.diagnostics.models import DiagnosticReport, Finding, Severity
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_I18N = {
    "ru": {
        "title":       "ДИАГНОСТИКА",
        "hint":        "Проверьте готовый VPK-мод на типовые причины поломок "
                       "(фиолетовые текстуры, невидимые модели, конфликты).",
        "drop":        "Перетащите .vpk сюда",
        "or_choose":   "или выберите файл",
        "choose":      "Выбрать VPK",
        "recheck":     "Проверить заново",
        "checking":    "Проверяю мод…",
        "healthy":     "Проблем не найдено",
        "summary_bad": "{e} ошибок · {w} предупреждений",
        "no_report":   "Выберите VPK-мод для проверки.",
        "fix":         "Как починить:",
        "dialog":      "Выберите VPK-мод",
    },
    "en": {
        "title":       "DIAGNOSTICS",
        "hint":        "Check a finished VPK mod for common breakage "
                       "(purple textures, invisible models, conflicts).",
        "drop":        "Drop a .vpk here",
        "or_choose":   "or pick a file",
        "choose":      "Choose VPK",
        "recheck":     "Re-check",
        "checking":    "Inspecting mod…",
        "healthy":     "No problems found",
        "summary_bad": "{e} errors · {w} warnings",
        "no_report":   "Pick a VPK mod to check.",
        "fix":         "How to fix:",
        "dialog":      "Select a VPK mod",
    },
}

_SEV_COLOR = {
    Severity.ERROR:   "#d85a4a",
    Severity.WARNING: "#d0902f",
    Severity.INFO:    "#6a9a6a",
}
_SEV_ICON = {Severity.ERROR: "✕", Severity.WARNING: "!", Severity.INFO: "✓"}


class DiagnosticsPanel(QWidget):
    """Вкладка проверки чужого/своего VPK-мода."""

    def __init__(self, parent=None, language: str = "en"):
        super().__init__(parent)
        self._lang = language if language in _I18N else "en"
        self._t = _I18N[self._lang]
        self._accent = self._get_accent()
        self._vpk_path: Optional[str] = None
        self._worker = None
        self._run_token = 0        # монотонный токен запуска — отсекает устаревшие результаты
        self.setAcceptDrops(True)
        self._build_ui()

    @staticmethod
    def _get_accent() -> str:
        from src.utils.themes import get_accent_color
        return get_accent_color()

    # ── UI ───────────────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        # На всю ширину вкладки, но содержимое — в читаемой колонке по центру
        # (иначе на широком экране находки растянулись бы неудобно широко).
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(860)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(content, 6)
        outer.addStretch(1)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel(self._t["title"])
        title.setStyleSheet(
            f"color:{self._accent}; font-size:11px; font-weight:700;"
            " letter-spacing:3px; background:transparent;")
        lay.addWidget(title)

        hint = QLabel(self._t["hint"])
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px; background:transparent;")
        lay.addWidget(hint)

        # ── Зона выбора файла (drop / кнопка) ────────────────────────────── #
        self._drop = QFrame()
        self._drop.setObjectName("diag_drop")
        self._drop.setStyleSheet(
            "QFrame#diag_drop { border:1px dashed #333; border-radius:6px;"
            " background:rgba(255,255,255,0.02); }")
        dlay = QVBoxLayout(self._drop)
        dlay.setContentsMargins(14, 16, 14, 16)
        dlay.setSpacing(8)
        dlay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._drop_label = QLabel(self._t["drop"])
        self._drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_label.setWordWrap(True)
        self._drop_label.setStyleSheet("color:#999; font-size:12px; background:transparent;")
        dlay.addWidget(self._drop_label)

        self._choose_btn = QPushButton(self._t["choose"])
        self._choose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._choose_btn.setStyleSheet(self._accent_btn_style())
        self._choose_btn.clicked.connect(self._choose_file)
        dlay.addWidget(self._choose_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._drop)

        # ── Статус/сводка ────────────────────────────────────────────────── #
        self._status = QLabel(self._t["no_report"])
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#777; font-size:12px; background:transparent;")
        lay.addWidget(self._status)

        # ── Список находок (скролл) ──────────────────────────────────────── #
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._results = QWidget()
        self._results.setStyleSheet("background:transparent;")
        self._results_lay = QVBoxLayout(self._results)
        self._results_lay.setContentsMargins(0, 0, 0, 0)
        self._results_lay.setSpacing(6)
        self._results_lay.addStretch()
        self._scroll.setWidget(self._results)
        lay.addWidget(self._scroll, 1)

    def _accent_btn_style(self) -> str:
        return (
            f"QPushButton {{ background:{self._accent}22; border:1px solid {self._accent};"
            f" border-radius:4px; color:{self._accent}; padding:6px 16px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{self._accent}33; }}"
            f"QPushButton:disabled {{ color:#555; border-color:#333; background:transparent; }}"
        )

    # ── Выбор / drag-drop файла ──────────────────────────────────────────── #

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self._t["dialog"], "", "VPK (*.vpk)")
        if path:
            self._set_file(path)

    def dragEnterEvent(self, e) -> None:
        if self._urls_vpk(e):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        vpk = self._urls_vpk(e)
        if vpk:
            self._set_file(vpk)
            e.acceptProposedAction()

    @staticmethod
    def _urls_vpk(e) -> Optional[str]:
        md = e.mimeData()
        if not md.hasUrls():
            return None
        for url in md.urls():
            p = url.toLocalFile()
            if p.lower().endswith(".vpk"):
                return p
        return None

    def _set_file(self, path: str) -> None:
        self._vpk_path = path
        self._drop_label.setText(os.path.basename(path))
        self._choose_btn.setText(self._t["recheck"])
        self._run()

    # ── Прогон ───────────────────────────────────────────────────────────── #

    def _run(self) -> None:
        if not self._vpk_path:
            return
        from src.services.diagnostics_worker import DiagnosticsWorker
        self._run_token += 1
        token = self._run_token
        self._choose_btn.setEnabled(False)
        self._set_status(self._t["checking"], "#d0902f")
        self._clear_results()
        # Каждый воркер сам себя удаляет по завершении; результат применяем только
        # если это САМЫЙ свежий запрос — быстрый повторный drop не должен
        # отрисовать устаревший отчёт и не течёт потоками.
        worker = DiagnosticsWorker(self._vpk_path, self._lang, self)
        worker.finished.connect(lambda rep, t=token, w=worker: self._on_finished(rep, t, w))
        worker.error.connect(lambda msg, t=token, w=worker: self._on_error(msg, t, w))
        self._worker = worker
        worker.start()

    def _on_finished(self, report: DiagnosticReport, token: int, worker) -> None:
        worker.deleteLater()
        if token != self._run_token:
            return   # пришёл более новый запрос — игнорируем устаревший результат
        self._choose_btn.setEnabled(True)
        self._render(report)

    def _on_error(self, msg: str, token: int, worker) -> None:
        worker.deleteLater()
        if token != self._run_token:
            return
        self._choose_btn.setEnabled(True)
        self._set_status(f"✕ {msg}", _SEV_COLOR[Severity.ERROR])

    def closeEvent(self, event) -> None:
        # Дожидаемся фонового прогона, чтобы поток не разрушился «на ходу».
        w = self._worker
        if w is not None and w.isRunning():
            w.wait(3000)
        super().closeEvent(event)

    # ── Рендер находок ───────────────────────────────────────────────────── #

    def _render(self, report: DiagnosticReport) -> None:
        self._clear_results()
        if report.is_healthy:
            self._set_status("✓ " + self._t["healthy"], _SEV_COLOR[Severity.INFO])
        else:
            self._set_status(
                self._t["summary_bad"].format(e=len(report.errors), w=len(report.warnings)),
                _SEV_COLOR[Severity.ERROR] if report.has_errors else _SEV_COLOR[Severity.WARNING])
        for f in report.sorted():
            self._results_lay.insertWidget(self._results_lay.count() - 1, self._card(f))

    def _card(self, f: Finding) -> QWidget:
        color = _SEV_COLOR[f.severity]
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:#151515; border:none; border-left:3px solid {color};"
            f" border-radius:0; }}")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(3)

        head = QLabel(f"<b>{_SEV_ICON[f.severity]} {_esc(f.title)}</b>")
        head.setStyleSheet(f"color:{color}; font-size:12px; background:transparent;")
        cl.addWidget(head)

        if f.location:
            loc = QLabel(_esc(f.location))
            loc.setStyleSheet("color:#666; font-size:10px; background:transparent;")
            loc.setWordWrap(True)
            cl.addWidget(loc)
        if f.detail:
            det = QLabel(_esc(f.detail))
            det.setWordWrap(True)
            det.setStyleSheet("color:#bbb; font-size:11px; background:transparent;")
            cl.addWidget(det)
        if f.fix_hint:
            fix = QLabel(f"<b>{self._t['fix']}</b> {_esc(f.fix_hint)}")
            fix.setWordWrap(True)
            fix.setStyleSheet(f"color:{self._accent}; font-size:11px; background:transparent;")
            cl.addWidget(fix)
        return card

    # ── Помощники ────────────────────────────────────────────────────────── #

    def _set_status(self, text: str, color: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{color}; font-size:12px; background:transparent;")

    def _clear_results(self) -> None:
        while self._results_lay.count() > 1:   # оставляем финальный stretch
            item = self._results_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def update_language(self, language: str) -> None:
        self._lang = language if language in _I18N else "en"
        self._t = _I18N[self._lang]
        self._drop_label.setText(
            os.path.basename(self._vpk_path) if self._vpk_path else self._t["drop"])
        self._choose_btn.setText(self._t["recheck"] if self._vpk_path else self._t["choose"])
        if self._vpk_path:
            # Тексты находок локализуются в бэкенде → переосматриваем с новым языком.
            self._run()
        else:
            self._status.setText(self._t["no_report"])


def _esc(s: str) -> str:
    """Экранирует текст для использования в rich-text QLabel."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
