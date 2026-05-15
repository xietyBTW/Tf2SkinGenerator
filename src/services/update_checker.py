"""
Проверка актуальности версии через GitHub Releases API.

Выполняется в фоновом QThread чтобы не блокировать UI.
Сравнение версий: семантическое (major.minor.patch), без внешних зависимостей.

Использование:
    checker = UpdateChecker()
    checker.update_available.connect(lambda tag, url: ...)
    checker.start()
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from typing import Optional, Tuple

from PySide6.QtCore import QThread, Signal

from src.shared.version import __version__, GITHUB_OWNER, GITHUB_REPO
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_API_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
_TIMEOUT = 8  # секунды


def _parse_version(tag: str) -> Tuple[int, int, int]:
    """
    Преобразует строку тега/версии в кортеж (major, minor, patch).
    Нечисловые префиксы ('v', 'V') удаляются. Неполные версии дополняются нулями.
    Возвращает (0, 0, 0) если распарсить не удалось.
    """
    clean = re.sub(r"^[vV]", "", tag.strip())
    parts = clean.split(".")
    try:
        nums = [int(p) for p in parts[:3]]
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums)  # type: ignore[return-value]
    except ValueError:
        return (0, 0, 0)


def _is_newer(remote: str, local: str) -> bool:
    """Возвращает True если remote > local."""
    return _parse_version(remote) > _parse_version(local)


def fetch_latest_release() -> Optional[Tuple[str, str]]:
    """
    Синхронно запрашивает GitHub API и возвращает (tag_name, html_url)
    или None при ошибке / если версия актуальна.
    """
    try:
        req = urllib.request.Request(
            _API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"Tf2SkinGenerator/{__version__}",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag: str = data.get("tag_name", "")
        url: str = data.get("html_url", "")
        draft: bool = data.get("draft", False)
        prerelease: bool = data.get("prerelease", False)

        if draft or prerelease:
            return None  # игнорируем черновики и пре-релизы

        if not tag:
            return None

        if _is_newer(tag, __version__):
            return tag, url

        return None  # версия актуальна

    except urllib.error.URLError as exc:
        logger.debug(f"Проверка обновлений: нет доступа к сети — {exc}")
        return None
    except Exception as exc:
        logger.debug(f"Проверка обновлений: неожиданная ошибка — {exc}")
        return None


class UpdateChecker(QThread):
    """
    Фоновый поток для проверки обновлений.

    Signals:
        update_available(tag: str, url: str)  — новая версия найдена
        check_done()                           — проверка завершена (успешно или нет)
    """

    update_available: Signal = Signal(str, str)
    check_done: Signal = Signal()

    def run(self) -> None:  # type: ignore[override]
        result = fetch_latest_release()
        if result:
            tag, url = result
            logger.info(f"Доступна новая версия: {tag}")
            self.update_available.emit(tag, url)
        self.check_done.emit()
