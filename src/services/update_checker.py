"""
Обновление приложения: проверка, скачивание, установка.

Механика намеренно опирается на то, что уже есть, и не тянет в проект новый
фреймворк:

  проверка     GitHub Releases API отдаёт последний релиз. Версии сравниваем
               семантически, без внешних зависимостей.
  скачивание   тот самый Setup.exe, что лежит в релизе. GitHub отдаёт для
               каждого файла поле `digest` — SHA-256; сверяем по нему, чтобы
               оборванная закачка не поехала в установку.
  установка    Setup.exe запускается тихо и делает всё сам: закрывает
               приложение, заменяет файлы, ставит ярлыки, чинит запись в
               «Программах и компонентах». Своего кода подмены файлов у нас
               нет и не надо.

Что даёт `digest`: он приходит по тому же TLS-соединению, что и сам файл,
поэтому это проверка ЦЕЛОСТНОСТИ (обрыв, битый прокси, кэш), а не подпись.
Защита от подмены самого релиза — это подпись кода у Setup.exe; она ставится
при сборке, здесь её проверяет Windows.

Данные человека при обновлении не страдают: они лежат отдельно от папки
установки (см. src/shared/paths.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from src.services.base_worker import BaseWorker, Signal

from src.shared.version import __version__, GITHUB_OWNER, GITHUB_REPO
from src.shared.logging_config import get_logger
from src.shared.paths import is_frozen

logger = get_logger(__name__)

_API_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
_TIMEOUT = 8  # секунды

#: Какой файл релиза ставим. Установщик, а не zip: он умеет закрыть работающее
#: приложение, обновить ярлыки и запись в «Программах и компонентах» — всё то,
#: что при ручной распаковке zip делать некому.
ASSET_NAME = "Tf2SkinGenerator-Setup.exe"

#: Тихая установка. /SILENT (а не /VERYSILENT) намеренно: человек видит полоску
#: и понимает, что происходит. /NOCANCEL — чтобы не бросить обновление на
#: середине замены файлов.
_SETUP_FLAGS = ("/SILENT", "/NOCANCEL", "/RESTARTAPPLICATIONS")

#: Сколько ждать перед запуском установщика. Приложение за это время успевает
#: закрыться и отпустить мьютекс и свои файлы — иначе Setup упрётся в занятые
#: .exe и .dll (см. AppMutex в installer/*.iss).
#:
#: Пауза делается через `ping -n`, а не через `timeout`: у отвязанного процесса
#: нет консоли, а timeout.exe в таком окружении отказывается работать («Input
#: redirection is not supported»). ping ждёт одинаково в любом.
_HANDOFF_DELAY_SEC = 3

_CHUNK = 64 * 1024


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


def _fetch_release() -> Optional[dict]:
    """Последний релиз как есть, или None (сеть, черновик, пре-релиз)."""
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
    except urllib.error.URLError as exc:
        logger.debug(f"Проверка обновлений: нет доступа к сети — {exc}")
        return None
    except Exception as exc:                                  # noqa: BLE001
        logger.debug(f"Проверка обновлений: неожиданная ошибка — {exc}")
        return None

    if data.get("draft") or data.get("prerelease"):
        return None                      # игнорируем черновики и пре-релизы
    if not data.get("tag_name"):
        return None
    return data


def fetch_latest_release() -> Optional[Tuple[str, str]]:
    """
    Синхронно запрашивает GitHub API и возвращает (tag_name, html_url)
    или None при ошибке / если версия актуальна.
    """
    data = _fetch_release()
    if data is None:
        return None
    tag = data.get("tag_name", "")
    if _is_newer(tag, __version__):
        return tag, data.get("html_url", "")
    return None                                       # версия актуальна


def _digest_of(asset: dict) -> str:
    """SHA-256 файла из ответа GitHub. Формат бывает и 'sha256:<hex>', и голым."""
    raw = (asset.get("digest") or "").strip().lower()
    return raw.split(":", 1)[1] if raw.startswith("sha256:") else raw


def check_for_update() -> Dict[str, object]:
    """
    Что показывать в интерфейсе: есть ли новая версия и чем её ставить.

    Всегда возвращает словарь — «нет обновления» и «не дозвонились» страница
    показывает по-разному, поэтому молчаливого None здесь быть не должно.
    """
    result: Dict[str, object] = {
        "current": __version__,
        "available": False,
        "checked": False,
        "can_install": False,
    }

    data = _fetch_release()
    if data is None:
        return result

    result["checked"] = True
    tag = str(data.get("tag_name", ""))
    result["version"] = tag.lstrip("vV")
    result["page_url"] = data.get("html_url", "")
    result["notes"] = data.get("body") or ""

    if not _is_newer(tag, __version__):
        return result
    result["available"] = True

    asset = next((a for a in data.get("assets") or []
                  if a.get("name") == ASSET_NAME), None)
    if asset is None:
        # Релиз есть, установщика в нём нет — предлагаем открыть страницу.
        logger.info(f"В релизе {tag} нет {ASSET_NAME}: ставить нечем")
        return result

    result["asset_name"] = asset.get("name")
    result["asset_url"] = asset.get("browser_download_url")
    result["asset_size"] = int(asset.get("size") or 0)
    result["asset_digest"] = _digest_of(asset)
    # Ставить умеет только собранное приложение: из репозитория обновляются
    # через git, и запуск Setup.exe поверх исходников был бы бессмыслицей.
    result["can_install"] = bool(result["asset_url"]) and is_frozen()
    return result


def download_update(
    url: str,
    expected_digest: str = "",
    expected_size: int = 0,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Path:
    """
    Качает установщик во временную папку и проверяет SHA-256.

    Возвращает путь к файлу. Бросает RuntimeError, если хэш или размер не
    сошлись — ставить недокачанный установщик нельзя ни при каких условиях.
    """
    out_dir = Path(tempfile.gettempdir()) / "tf2sg_update"
    out_dir.mkdir(parents=True, exist_ok=True)
    # .part, пока качается: прерванный файл не должен выглядеть готовым.
    part = out_dir / (ASSET_NAME + ".part")
    dest = out_dir / ASSET_NAME

    sha = hashlib.sha256()
    done = 0
    req = urllib.request.Request(
        url, headers={"User-Agent": f"Tf2SkinGenerator/{__version__}"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        total = int(resp.headers.get("Content-Length") or expected_size or 0)
        with open(part, "wb") as fh:
            while True:
                if cancelled is not None and cancelled():
                    part.unlink(missing_ok=True)
                    raise RuntimeError("отменено")
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)

    if expected_size and done != expected_size:
        part.unlink(missing_ok=True)
        raise RuntimeError(
            f"размер не совпал: {done} вместо {expected_size}")
    if expected_digest and sha.hexdigest() != expected_digest:
        part.unlink(missing_ok=True)
        raise RuntimeError("контрольная сумма не совпала — файл повреждён")

    os.replace(part, dest)
    logger.info(f"Установщик скачан: {dest} ({done} байт)")
    return dest


def install_update(setup_path: str) -> None:
    """
    Запускает установщик отдельным процессом и оставляет его работать.

    Ждём перед запуском: Windows не даст заменить .exe и .dll работающего
    приложения, поэтому сначала должны закрыться мы. Отсюда `cmd /c timeout &
    setup` — процесс отвязан от нашего (DETACHED_PROCESS) и переживёт выход.

    Вызывающий обязан после этого завершить приложение (см. api.install_update).
    """
    setup = Path(setup_path)
    if not setup.is_file():
        raise RuntimeError(f"установщик не найден: {setup}")
    if sys.platform != "win32":
        raise RuntimeError("установка поддерживается только на Windows")

    # Команда передаётся ОДНОЙ СТРОКОЙ, а не списком. Список Python собирает
    # через list2cmdline, и тот экранирует наши кавычки обратными слэшами:
    # cmd получает «break > \"C:\...\"» и отвечает «синтаксическая ошибка в
    # имени файла». Ошибки при этом не видно — Popen отработал, процесс
    # запустился, установщик не запустился НИКОГДА. Со строкой Windows отдаёт
    # командную строку в CreateProcess как есть.
    command = (f'cmd /c ping -n {_HANDOFF_DELAY_SEC + 1} 127.0.0.1 >nul & '
               f'"{setup}" {" ".join(_SETUP_FLAGS)}')
    subprocess.Popen(
        command,
        creationflags=subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    logger.info("Установщик запущен, приложение закрывается")


class UpdateChecker(BaseWorker):
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
