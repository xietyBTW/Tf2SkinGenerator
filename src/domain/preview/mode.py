"""
Явная модель режима 3D/2D-превью (чистый Python, без Qt — юнит-тестируется).

Зачем: в preview_panel «что сейчас показываем» закодировано россыпью булевых
флагов (_custom_smd_mode / _spy_mask_mode / _crithit_mode / _death_effect_mode).
Они ВЗАИМОИСКЛЮЧАЮЩИЕ, но это нигде не выражено — отсюда баги «забыли сбросить
флаг при переходе» (утечка состояния кастом→игра, австралий-как-команда и т.п.).

`PreviewState.enter(mode)` — ЕДИНСТВЕННАЯ точка перехода: установка одного режима
автоматически гасит остальные. Виджет читает режим через свойства (is_custom и
т.д.). Сбросы вторичного состояния (карточки/команды/стили) остаются в виджете —
здесь только взаимоисключение самих режимов.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class PreviewMode(Enum):
    WEAPON = auto()      # обычная игровая модель (оружие/шапка/персонаж) — по умолчанию
    CUSTOM = auto()      # загруженная пользователем модель (SMD)
    SPY_MASKS = auto()   # маски маскировки шпиона
    CRITHIT = auto()     # спец-режим critHIT
    DEATH = auto()       # спец-режим эффекта смерти
    SKYBOX = auto()      # режим «Скайбокс»: фон-кубмапа вместо модели
    FIRST_PERSON = auto()  # вид от первого лица: руки класса с оружием


@dataclass
class PreviewState:
    """Текущий режим превью. Переход — только через enter()."""
    mode: PreviewMode = PreviewMode.WEAPON

    def enter(self, mode: PreviewMode) -> None:
        """Переключает режим. Остальные режимы автоматически становятся неактивны."""
        if not isinstance(mode, PreviewMode):
            raise TypeError(f"mode должен быть PreviewMode, не {type(mode)!r}")
        self.mode = mode

    def reset(self) -> None:
        """Возврат к обычной игровой модели (WEAPON)."""
        self.mode = PreviewMode.WEAPON

    # ── Взаимоисключающие предикаты (для чтения в виджете) ─────────────────── #
    @property
    def is_custom(self) -> bool:
        return self.mode == PreviewMode.CUSTOM

    @property
    def is_spy_masks(self) -> bool:
        return self.mode == PreviewMode.SPY_MASKS

    @property
    def is_crithit(self) -> bool:
        return self.mode == PreviewMode.CRITHIT

    @property
    def is_death(self) -> bool:
        return self.mode == PreviewMode.DEATH

    @property
    def is_skybox(self) -> bool:
        return self.mode == PreviewMode.SKYBOX

    @property
    def is_first_person(self) -> bool:
        return self.mode == PreviewMode.FIRST_PERSON
