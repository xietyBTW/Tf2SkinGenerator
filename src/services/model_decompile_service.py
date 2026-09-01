"""
Получение декомпилированной модели: кэш → VPK → Crowbar.

Один и тот же путь «найти MDL в VPK, распаковать набор файлов, прогнать через
Crowbar, положить в кэш» нужен 3D-превью, определению скинов и превью
вьюмодели. Раньше он был скопирован в каждый воркер отдельно — вместе с
проверками отмены, чисткой temp-папок и порядком «сначала кэш».

Что здесь НЕ решается: какой именно MDL искать. Список путей-кандидатов у
каждого вызывающего свой (шапки раскрываются по классам, персонажи идут прямым
путём, оружие — через ExtractModelService), и он остаётся снаружи. Сервис
получает готовый список и берёт первый существующий.

Прогресс отдаётся стадиями (`Stage`), а не текстом: сервис не знает языка
интерфейса, а вызывающий уже имеет свои переводы.

Модуль без Qt.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

from src.services import decompile_cache
from src.services.model_build_service import ModelBuildService
from src.services.tf2_paths import TF2Paths
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class Stage(Enum):
    """Долгий шаг, о котором стоит сказать пользователю."""
    EXTRACTING = "extracting"
    DECOMPILING = "decompiling"


class DecompileError(Exception):
    """Декомпиляция невозможна: нет VPK, нет Crowbar, Crowbar упал.

    Отсутствие самой модели в VPK ошибкой НЕ считается — это обычный «нечего
    показывать», и `ensure_decompiled` возвращает на него None.
    """


@dataclass(frozen=True)
class Decompiled:
    """Результат: папка с QC и SMD."""

    directory: str
    #: Путь MDL внутри VPK, который реально нашёлся (может отличаться от первого
    #: кандидата — например у шапки, лежащей в workshop/).
    mdl_rel: str
    #: True — папка живёт в кэше и переживёт процесс. False — temp-папка,
    #: которую сохранить не удалось; вызывающий волен удалить её после себя.
    cached: bool


def ensure_decompiled(
    weapon_key: str,
    misc_vpk_path: str,
    mdl_candidates: Sequence[str],
    *,
    cancelled: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[Stage], None]] = None,
) -> Optional[Decompiled]:
    """
    Папка с декомпилированной моделью — из кэша или после Crowbar.

    Args:
        weapon_key:     Ключ записи кэша и метка для логов. Для общих ресурсов
                        (руки, анимации классов) годится синтетический ключ.
        misc_vpk_path:  tf2_misc_dir.vpk — из него извлекается модель.
        mdl_candidates: Пути MDL внутри VPK в порядке приоритета.
        cancelled:      Проверка отмены; вызывается между долгими шагами.
        on_progress:    Уведомление о стадии перед долгим шагом.

    Returns:
        Decompiled, либо None — если модель не нашлась в VPK или работу отменили.

    Raises:
        DecompileError: нет VPK, нет Crowbar или Crowbar завершился с ошибкой.
    """
    stop = cancelled or (lambda: False)

    def progress(stage: Stage) -> None:
        if on_progress is not None:
            on_progress(stage)

    if not misc_vpk_path or not os.path.exists(misc_vpk_path):
        raise DecompileError(f"VPK not found: {misc_vpk_path}")

    crowbar = os.path.abspath(TF2Paths.get_crowbar_path())
    if not os.path.exists(crowbar):
        raise DecompileError(f"Crowbar not found: {crowbar}")

    # ── Кэш: проверяем КАЖДОГО кандидата ─────────────────────────────────── #
    # Ключ кэша включает путь MDL, а сохраняется запись под тем путём, который
    # реально нашёлся. Проверка только первого кандидата означала бы вечный
    # промах для всего, что лежит не по своему прямому пути (шапки в workshop/,
    # мультиклассовые модели): такие модели декомпилировались заново каждый раз.
    # Промах стоит один stat(), так что перебор здесь бесплатный.
    for candidate in mdl_candidates:
        hit = decompile_cache.get_cached_decompile(
            weapon_key, misc_vpk_path, candidate
        )
        if hit:
            logger.info(f"[decomp] кэш: {weapon_key} ({candidate})")
            return Decompiled(directory=hit, mdl_rel=candidate, cached=True)

    if stop():
        return None

    found_rel = _first_existing(misc_vpk_path, mdl_candidates, stop)
    if not found_rel:
        logger.warning(
            f"[decomp] MDL не найден в VPK для {weapon_key}. "
            f"Пробовали: {list(mdl_candidates)[:3]}"
        )
        return None

    return _extract_and_decompile(
        weapon_key, misc_vpk_path, found_rel, crowbar, stop, progress
    )


def _first_existing(
    misc_vpk_path: str,
    candidates: Sequence[str],
    stop: Callable[[], bool],
) -> Optional[str]:
    """Первый кандидат, который есть в VPK. None — ни одного (или отмена)."""
    for path in candidates:
        if stop():
            return None
        try:
            if TF2VPKExtractService.check_mdl_exists(misc_vpk_path, path):
                logger.info(f"[decomp] MDL найден: {path}")
                return path
        except Exception as exc:
            logger.debug(f"[decomp] check_mdl_exists({path}): {exc}")
    return None


def _extract_and_decompile(
    weapon_key: str,
    misc_vpk_path: str,
    mdl_rel: str,
    crowbar: str,
    stop: Callable[[], bool],
    progress: Callable[[Stage], None],
) -> Optional[Decompiled]:
    """Распаковка набора файлов модели + Crowbar + сохранение в кэш."""
    mdl_dir: Optional[str] = None
    decomp_dir: Optional[str] = None
    cached_dir: Optional[str] = None
    try:
        progress(Stage.EXTRACTING)
        mdl_dir = tempfile.mkdtemp(prefix="tf2sg_mdl_")
        extracted = TF2VPKExtractService.extract_file_set(
            misc_vpk_path, mdl_rel, mdl_dir
        )
        mdl_file = next((f for f in extracted if f.endswith(".mdl")), None)
        if not mdl_file:
            raise DecompileError(
                f"MDL file missing after extraction: {extracted}"
            )
        if stop():
            return None

        progress(Stage.DECOMPILING)
        decomp_dir = tempfile.mkdtemp(prefix="tf2sg_decomp_")
        logger.info(f"[decomp] Crowbar: {os.path.basename(mdl_file)} → {decomp_dir}")
        ModelBuildService.decompile(mdl_file, decomp_dir, crowbar)

        cached_dir = decompile_cache.save_to_cache(
            weapon_key, misc_vpk_path, mdl_rel, decomp_dir
        )
        return Decompiled(
            directory=cached_dir or decomp_dir,
            mdl_rel=mdl_rel,
            cached=bool(cached_dir),
        )

    except DecompileError:
        raise
    except Exception as exc:
        logger.error(f"[decomp] ошибка для {weapon_key}: {exc}", exc_info=True)
        raise DecompileError(f"Decompile error: {exc}") from exc
    finally:
        if mdl_dir:
            shutil.rmtree(mdl_dir, ignore_errors=True)
        # temp-папку убираем только когда её содержимое уже лежит в кэше:
        # иначе вызывающий продолжает читать SMD именно из неё.
        if decomp_dir and cached_dir:
            shutil.rmtree(decomp_dir, ignore_errors=True)
