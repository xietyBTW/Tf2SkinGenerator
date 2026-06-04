"""
Конфиг файловых карт материала (Фаза 2).

Пользователь грузит обычную картинку → приложение само:
  1) генерит VTF с ПРАВИЛЬНЫМ форматом/флагами под тип карты,
  2) вписывает путь карты в VMT (путь авто-патчится под console/..., как у normal map),
  3) добавляет сопутствующие параметры ($detailscale, $selfillum, $phong …).

Почему это нельзя сделать через редактор VMT:
  • пользователь физически не знает авто-патченный путь console\…,
  • редактор не генерит VTF и не выставляет формат под тип карты
    (например phong-exp нельзя в DXT1 — потеряется альфа).

Карты имеют смысл только на VertexLitGeneric (модели). На UnlitGeneric
(spray/crit) — игнорируются (см. VMTService.add_material_map_params).
"""

# id_карты → правила. format/flags — для генерации VTF; path_param — параметр
# VMT с путём к карте; extra_vmt — сопутствующие скалярные параметры;
# numeric — какие из extra_vmt можно переопределить из UI.
MATERIAL_MAPS = {
    "detail": {
        "suffix": "_detail",
        "format": "DXT1",          # detail тайлится, альфа не нужна
        "flags": (),               # без CLAMP — иначе тайлинг сломается
        "path_param": "$detail",
        "extra_vmt": {
            "$detailscale": "8",
            "$detailblendmode": "1",      # 1 = additive
            "$detailblendfactor": "1",
        },
        "numeric": ("$detailscale", "$detailblendmode", "$detailblendfactor"),
        "needs_alpha": False,
    },
    "selfillum": {
        "suffix": "_illum",
        "format": "DXT1",          # маска свечения — оттенки серого
        "flags": (),
        "path_param": "$selfillummask",
        "extra_vmt": {"$selfillum": "1"},
        "numeric": (),
        "needs_alpha": False,
        "derive_kind": "selfillum",   # можно вывести из базовой текстуры
    },
    "phongexp": {
        "suffix": "_exp",
        "format": "DXT5",          # альфа критична (rim/маска) → НЕ DXT1
        "flags": (),
        "path_param": "$phongexponenttexture",
        "extra_vmt": {"$phong": "1", "$phongboost": "2"},
        "numeric": ("$phongboost",),
        "needs_alpha": True,
        "derive_kind": "phong",       # «Авто-блеск» из базовой текстуры
        # Для phong нужен bumpmap (иначе Source не считает блик) + добавляем
        # отражение мира для «вау». Эти параметры доклеиваются при derive-режиме.
        "derive_auto_normal": True,
        "derive_extra_vmt": {"$envmap": "env_cubemap", "$envmaptint": "[ .3 .3 .3 ]"},
    },
    # ── Warp-карты (градиенты-lookup) ────────────────────────────────────────
    # Это не обычные текстуры, а градиенты: lightwarp ремапит освещённость,
    # phongwarp — цвет/градиент блика. Им нужны CLAMP (без тайлинга) + NOMIP
    # (иначе градиент размывается мип-уровнями) и формат без DXT-бандинга.
    "phongwarp": {
        "suffix": "_phongwarp",
        "format": "BGR888",            # градиент → без DXT-бандинга
        "flags": ("CLAMPS", "CLAMPT"), # без тайлинга
        "options": {"nomipmaps": True},
        "path_param": "$phongwarptexture",
        "extra_vmt": {"$phong": "1"},  # phongwarp работает только при $phong
        "numeric": (),
        "needs_alpha": False,
    },
    "lightwarp": {
        "suffix": "_lightwarp",
        "format": "BGR888",
        "flags": ("CLAMPS", "CLAMPT"),
        "options": {"nomipmaps": True},
        "path_param": "$lightwarptexture",
        "extra_vmt": {},               # lightwarp работает самостоятельно
        "numeric": (),
        "needs_alpha": False,
    },
}

# Порядок ОБРАБОТКИ при сборке (стабильный, не влияет на UI).
MAP_ORDER = ("detail", "selfillum", "phongexp", "phongwarp", "lightwarp")

# Порядок ОТОБРАЖЕНИЯ в диалоге (сетка 2 столбца, ряд за рядом).
# Подобран так, чтобы в одном ряду стояли карты схожей высоты:
#   ряд1: phongexp + selfillum (обе с «авто» и порогом),
#   ряд2: detail + phongwarp,
#   ряд3: lightwarp (на всю ширину).
MAP_DISPLAY_ORDER = ("phongexp", "selfillum", "detail", "phongwarp", "lightwarp")
