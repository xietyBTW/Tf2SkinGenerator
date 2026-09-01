"""
Кто и когда сохраняет работу над предметом.

Само хранилище — `work_store`; здесь правила: какой у предмета ключ, когда
писать, когда возвращать. Вынесено отдельно, потому что хостов два — окно
приложения и веб-представление, — а правило должно быть одно. Второй такой же
код в панели означал бы, что рано или поздно окно и страница начнут понимать
«моя работа» по-разному.

Qt здесь нет: keeper работает с ``PreviewSession``, то есть с состоянием, а не
с виджетами.
"""

from __future__ import annotations

import os
from typing import Optional

from src.domain.preview.session import PreviewSession
from src.services import work_store
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def is_enabled() -> bool:
    """
    Сохранять ли правки молча.

    Умолчание — ДА: человек не должен помнить про «сохранить», а забытая
    работа — худший из исходов. Выключатель живёт в общем конфиге, поэтому
    решение одинаково в окне и на странице.
    """
    from src.config.app_config import AppConfig
    value = AppConfig.load_config().get('save_edits')
    return True if value is None else bool(value)


def key_for(mode: str, item: str = '', mod_path: str = '') -> str:
    """
    Ключ работы по предмету — или пустая строка, если предмет ещё не опознан.

    Пустой ключ важен: без него работа легла бы в папку, которую потом никто
    не найдёт, а тот же предмет с ключом завёл бы ВТОРУЮ.

    У мода из VPK предмета в каталоге нет — его опознаёт файл в библиотеке.
    """
    if not mode:
        return ''
    if mode == 'custom':
        name = os.path.basename(mod_path or '')
        return work_store.key_for('custom', name) if name else ''
    # '\x00' — sentinel панели «модель ещё не грузили».
    if not item or item == '\x00':
        return ''
    return work_store.key_for(mode, item)


def save(session: PreviewSession, key: str) -> bool:
    """
    Пишет правки предмета.

    Опустошённую работу удаляем, а не сохраняем пустой: иначе «сбросил всё»
    возвращалось бы при следующем открытии.
    """
    if not key or not is_enabled():
        return False
    if session.has_user_edits():
        return work_store.save(key, session.user_edits()) is not None
    if work_store.has(key):
        work_store.forget(key)
    return False


def restore(session: PreviewSession, key: str) -> bool:
    """
    Возвращает правки предмета в сеанс. True — что-то вернулось.

    Выключенное сохранение выключает и возврат: «я выключил, а оно всё равно
    подставляет вчерашнее» — не то, о чём просили.
    """
    if not key or not is_enabled():
        return False
    edits = work_store.load(key)
    if not edits:
        return False
    session.apply_user_edits(edits)
    logger.info(f"работа предмета возвращена: {key}")
    return True


def forget(session: Optional[PreviewSession], key: str) -> None:
    """Сбрасывает работу: и в сеансе, и на диске."""
    if session is not None:
        session.forget_user_edits()
    if key:
        work_store.forget(key)
