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
    "envmapmask": {
        "suffix": "_envmask",
        "format": "DXT1",          # маска отражения — оттенки серого, альфа не нужна
        "flags": (),
        "path_param": "$envmapmask",
        # $envmapmask работает только при включённом отражении кубмапа.
        "extra_vmt": {"$envmap": "env_cubemap"},
        "numeric": (),
        "needs_alpha": False,
        # «Авто»: маска из яркости базы (металл/светлое блестит сильнее).
        "derive_kind": "envmapmask",
    },
    # ── Rim light (параметрический, без своей текстуры) ───────────────────────
    # Обводка светом по контуру. Маску берёт из АЛЬФЫ $phongexponenttexture
    # (если включена phong-карта), иначе применяется равномерно. Требует $phong.
    "rimlight": {
        "vmt_only": True,          # текстуры нет — пишем только параметры VMT
        "format": "VMT",           # для бейджа в диалоге
        "path_param": None,
        "extra_vmt": {
            "$phong": "1",
            "$rimlight": "1",
            "$rimlightexponent": "4",
            "$rimlightboost": "2",
        },
        "numeric": ("$rimlightexponent", "$rimlightboost"),
        # Rim считается phong-шейдером, а phong требует $bumpmap — без карты
        # нополей эффект НЕ виден. Поэтому гарантируем нормаль (не затирая
        # существующую): генерим из базы, если в VMT ещё нет $bumpmap.
        "derive_auto_normal": True,
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
        "size": (256, 256),            # 2D-lookup (fresnel × half-angle) — фикс. размер
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
        # $lightwarptexture в Source — 1D-рампа 256×1 (освещённость 0..1 берётся
        # как координата X). Игнорируем глобальный размер сборки и всегда делаем
        # 256×1, иначе ремап освещения искажается / раздувается память.
        "size": (256, 1),
        "path_param": "$lightwarptexture",
        "extra_vmt": {},               # lightwarp работает самостоятельно
        "numeric": (),
        "needs_alpha": False,
    },
}

# Порядок ОБРАБОТКИ при сборке (стабильный, не влияет на UI).
MAP_ORDER = ("detail", "selfillum", "phongexp", "envmapmask", "rimlight",
             "phongwarp", "lightwarp")

# Порядок ОТОБРАЖЕНИЯ в диалоге (сетка 2 столбца, ряд за рядом).
MAP_DISPLAY_ORDER = ("phongexp", "rimlight", "envmapmask", "selfillum",
                     "detail", "phongwarp", "lightwarp")
