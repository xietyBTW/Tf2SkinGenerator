"""
Прикладной API для представления

То, что вызывает фронт: список категорий, список предметов, запуск загрузки
превью. Транспорта здесь нет - это обычные функции и обычные значения. Мост
(pywebview, dev-сервер, что угодно ещё) только перекладывает вызовы сюда и
сериализует результат

Почему без транспорта: хост ещё не выбран окончательно, а правила выбора
предмета и режима меняться от способа доставки не должны. Плюс так их можно
проверить без окна и без браузера

Правила режима повторяют приложение: режим следует из категории и подтипа
(см. frontend/CONTROLS.md), а от режима зависит, какие контролы показывать

Модули пакета - по областям (каталог, превью, сборка, звуки, частицы...).
Здесь их имена собраны в одно пространство, поэтому `from src.app import api`
и `api.foo(...)` работают как с одним модулем. Что видно странице, решает не этот
список, а декоратор `@endpoint` (см. `_common.ENDPOINTS`)
"""

from __future__ import annotations

from src.app.api import (
    app_log,
    app_settings,
    app_update,
    audio,
    building,
    catalog,
    custom_model,
    hat_catalog,
    materials,
    model_parts,
    particles,
    preview,
    saved_works,
    sheen,
    tools,
    war_paint,
)
from src.app.api._common import ENDPOINTS, endpoint, logger  # noqa: F401 - реэкспорт

# Имена модулей областей - в пространство пакета: новая функция появляется в
# `api.` сама, вписывать её сюда не нужно. Подменять в тестах - в её модуле
for _module in (app_log, app_settings, app_update, audio, building, catalog,
                custom_model, hat_catalog, materials, model_parts, particles,
                preview, saved_works, sheen, tools, war_paint):
    globals().update({k: v for k, v in vars(_module).items()
                      if not k.startswith('__')})
del _module
