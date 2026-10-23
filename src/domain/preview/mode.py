"""
Явная модель режима 3D/2D-превью (чистый Python, юнит-тестируется)

Режимы (своя модель, маски шпиона, CritHIT, эффект смерти) ВЗАИМОИСКЛЮЧАЮЩИЕ.
Россыпь булевых флагов этого не выражает, и тогда при переходе флаг забывают
сбросить (утечка состояния своя модель -> игра, австралий-как-команда)

`PreviewState.enter(mode)` - ЕДИНСТВЕННАЯ точка перехода: установка одного режима
автоматически гасит остальные. Режим читают через свойства (is_custom и т.д.).
Здесь только взаимоисключение самих режимов, сбросы карточек, команд и стилей -
в PreviewSession
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class PreviewMode(Enum):
    WEAPON = auto()      # обычная игровая модель (оружие/шапка/персонаж) - по умолчанию
    CUSTOM = auto()      # загруженная пользователем модель (SMD)
    SPY_MASKS = auto()   # маски маскировки шпиона
    CRITHIT = auto()     # спец-режим critHIT
    DEATH = auto()       # спец-режим эффекта смерти
    SKYBOX = auto()      # режим «Скайбокс»: фон-кубмапа вместо модели
    FIRST_PERSON = auto()  # вид от первого лица: руки класса с оружием


@dataclass
class PreviewState:
    """Текущий режим превью. Переход - только через enter()"""
    mode: PreviewMode = PreviewMode.WEAPON

    def enter(self, mode: PreviewMode) -> None:
        """Переключает режим. Остальные режимы автоматически становятся неактивны"""
        if not isinstance(mode, PreviewMode):
            raise TypeError(f"mode должен быть PreviewMode, не {type(mode)!r}")
        self.mode = mode

    def reset(self) -> None:
        """Возврат к обычной игровой модели (WEAPON)"""
        self.mode = PreviewMode.WEAPON

    # Взаимоисключающие предикаты (для чтения в виджете)
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
