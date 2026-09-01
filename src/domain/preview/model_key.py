"""
Ключ модели для 3D-превью: что искать в VPK при этом режиме.

Правило неочевидное и раньше жило внутри MainWindow. Само по себе имя режима
воркеру не годится: у рук нужна модель предплечья, у тела персонажа — полный
путь к MDL, у масок шпиона — MDL шпиона. Ошибиться легко и заметно: воркер
просто отвечает «модель не найдена в VPK».

Правило от Qt не зависит, поэтому живёт в домене — им пользуются и панель
превью, и веб-фронт.
"""

from __future__ import annotations

from typing import Optional


def model_key_for(mode: str) -> Optional[str]:
    """
    Ключ, по которому воркер ищет модель, либо None — показывать нечего.

    None означает не ошибку, а «для этого режима 3D-модели нет»: спрей,
    пустой выбор и режимы, где геометрию задаёт сам пользователь.
    """
    if not mode:
        return None

    from src.data.player_characters import (
        PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS, SPY_MASK_MODE_KEY, SPY_MDL_PATH,
    )
    from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
    from src.data.weapons import SPECIAL_MODES, weapon_key_from_mode

    if mode in HAND_MODE_KEYS:
        # Руки: модель предплечья, а не сам режим.
        return HAND_MODES.get(mode, {}).get('arm_model') or None

    if mode in PLAYER_BODY_MODE_KEYS:
        # Тело персонажа: полный путь к MDL, как у шапок.
        return PLAYER_CHARACTERS.get(mode, {}).get('mdl_path') or None

    if mode == SPY_MASK_MODE_KEY:
        # Маски маскировки: та же модель, что у скина шпиона.
        return SPY_MDL_PATH

    if mode in SPECIAL_MODES:
        return None            # спрей, critHIT, эффекты смерти — модели нет

    if '_' in mode:
        # Обычное оружие: режим «класс_ключ», нужен только ключ.
        return weapon_key_from_mode(mode)

    return None
