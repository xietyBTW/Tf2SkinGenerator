"""
Конфиг файловых карт материала (Фаза 2)

Пользователь грузит обычную картинку -> приложение само:
  1) генерит VTF с ПРАВИЛЬНЫМ форматом/флагами под тип карты,
  2) вписывает путь карты в VMT (путь авто-патчится под console/..., как у normal map),
  3) добавляет сопутствующие параметры ($detailscale, $selfillum, $phong …)

Почему это нельзя сделать через редактор VMT:
  • пользователь физически не знает авто-патченный путь console\…,
  • редактор не генерит VTF и не выставляет формат под тип карты
    (например phong-exp нельзя в DXT1 - потеряется альфа)

Карты имеют смысл только на VertexLitGeneric (модели). На UnlitGeneric
(spray/crit) - игнорируются (см. VMTService.add_material_map_params)
"""

# id_карты -> правила. format/flags - для генерации VTF; path_param - параметр
# VMT с путём к карте; extra_vmt - сопутствующие скалярные параметры;
# numeric - какие из extra_vmt можно переопределить из UI; settings - свои
# настройки карты, которые не параметры VMT (их разбирает сборка):
#   {"choices": (…), "default"} | {"min", "max", "default"} (+ "float",
#   "step", "slider") | {"color": True} | {"file": True}; "show_if":
#   {настройка: значение или список значений} - когда поле видно; "display"
#   - что показать, пока поле не тронуто (пусто = «как у материала», в VMT
#   ничего не пишется: иначе первое же «Применить» переписало бы родное)
#
# Phong-карта ($phongexponenttexture) у движка поканальная (source-sdk-2013,
# skin_ps20b.fxc): R - размер блика (1 + 149·R, но $phongexponent > 0 его
# ПЕРЕКРЫВАЕТ - skin_dx9_helper.cpp), G - сила окраски блика цветом текстуры
# ($phongalbedotint), A - маска обводки ($rimmask). Поэтому «Цвет блика» и
# маска Rim light собираются в ту же текстуру {mat}_exp
MATERIAL_MAPS = {
    "detail": {
        "suffix": "_detail",
        "format": "DXT1",          # detail тайлится, альфа не нужна
        "flags": (),               # без CLAMP - иначе тайлинг сломается
        "path_param": "$detail",
        "extra_vmt": {
            "$detailscale": "8",
            # 0 - DecalModulate: темнее 128 затемняет, светлее высветляет.
            # Им пользуется Valve в своих detail (developer.valvesoftware.com/
            # wiki/$detail). 1 только высветляет
            "$detailblendmode": "0",
            "$detailblendfactor": "1",
        },
        "numeric": ("$detailscale", "$detailblendmode", "$detailblendfactor"),
        # Режимы, что работают на VertexLitGeneric С $bumpmap (а он у оружия
        # TF2 почти всегда): 0-4 всегда, 5-6 при $phong. 7-9 без $bumpmap не
        # рисуются вовсе («Missing Shader Combo» - материал пропадает), поэтому
        # их в выборе нет. 7 - это Two-Pattern DecalModulate, а не Multiply;
        # 5 - Unlit Additive, а не Overlay
        "choices": {"$detailblendmode": ("0", "1", "2", "5")},
        "preview": "detail",
        # Режим 2 накладывает цветную деталь по её альфе - DXT1 альфу теряет
        "format_by": {"$detailblendmode": {"2": "DXT5"}},
        "needs_alpha": False,
    },
    "selfillum": {
        "suffix": "_illum",
        "format": "DXT1",          # маска свечения - оттенки серого
        "flags": (),
        "path_param": "$selfillummask",
        "extra_vmt": {"$selfillum": "1"},
        "numeric": (),
        "needs_alpha": False,
        "derive_kind": "selfillum",   # можно вывести из базовой текстуры
        "preview": "glow",
        # Цвет, пульсация и затухание свечения (вики Valve: $selfillumtint,
        # $selfillumfresnel; у Valve в TF2 790 и 292 материалов). Пульсация -
        # прокси Sine и Multiply, как у Valve (68 материалов TF2 пульсируют
        # $selfillumtint через Sine)
        "settings": {
            "glow_color": {"color": True, "default": "", "display": "#ffffff"},
            "glow_power": {"min": 0, "max": 400, "slider": True, "default": "", "display": 100},
            "glow_pulse": {"choices": ("off", "slow", "medium", "fast"), "default": "off"},
            "glow_pulse_min": {"min": 0, "max": 100, "slider": True, "default": "", "display": 30,
                               "show_if": {"glow_pulse": ["slow", "medium", "fast"]}},
            "glow_edge": {"choices": ("off", "on"), "default": "off"},
            "edge_bright": {"min": 1, "max": 20, "slider": True, "default": "", "display": 5,
                            "show_if": {"glow_edge": "on"}},
            "edge_sharp": {"min": 1, "max": 20, "slider": True, "default": "", "display": 8,
                           "show_if": {"glow_edge": "on"}},
        },
    },
    "phongexp": {
        "suffix": "_exp",
        "format": "DXT5",          # альфа критична (rim/маска) -> НЕ DXT1
        "flags": (),
        "path_param": "$phongexponenttexture",
        "extra_vmt": {"$phong": "1", "$phongboost": "2"},
        # Вики Valve: без $phongfresnelranges phong может не показаться, из
        # 8511 phong-материалов TF2 без него только 7. Только если его нет -
        # у оружия он свой
        "vmt_defaults": {"$phongfresnelranges": "[0 0.5 1]"},
        "numeric": ("$phongboost",),
        "needs_alpha": True,
        "derive_kind": "phong",       # «Авто-блеск» из базовой текстуры
        "preview": "gloss",
        # Для phong нужен bumpmap (иначе Source не считает блик) + добавляем
        # отражение мира для «вау». Эти параметры доклеиваются при derive-режиме
        "derive_auto_normal": True,
        "derive_extra_vmt": {"$envmap": "env_cubemap", "$envmaptint": "[ .3 .3 .3 ]"},
    },
    # Цвет блика ($phongalbedotint / $phongtint)
    # Блик цветом самой текстуры - главный приём металла в TF2 (468 материалов
    # Valve), либо одним цветом (285). $phongtint отключает окраску текстурой,
    # поэтому режимы взаимоисключающие
    "phongcolor": {
        "vmt_only": True,
        "format": "VMT",
        "path_param": None,
        "extra_vmt": {"$phong": "1"},
        "vmt_defaults": {"$phongfresnelranges": "[0 0.5 1]"},
        "numeric": (),
        # Своё превью - шар с бликом (phongwarp.js)
        "preview": "phong",
        "settings": {
            "tint": {"choices": ("keep", "albedo", "color"), "default": "keep"},
            "tint_amount": {"min": 0, "max": 100, "default": 100,
                            "show_if": {"tint": "albedo"}},
            "tint_color": {"color": True, "default": "#ffc864",
                           "show_if": {"tint": "color"}},
            # Где ярче блик: $phongfresnelranges [центр середина край] - у
            # каждого оружия TF2 свои (чаще всего [.25 .5 1]). Пусто - как у
            # предмета
            "fres_center": {"min": 0, "max": 10, "float": True, "step": 0.05,
                            "default": "", "display": 0.25},
            "fres_mid": {"min": 0, "max": 10, "float": True, "step": 0.05,
                         "default": "", "display": 0.5},
            "fres_edge": {"min": 0, "max": 10, "float": True, "step": 0.05,
                          "default": "", "display": 1},
        },
    },
    "envmapmask": {
        "suffix": "_envmask",
        "format": "DXT1",          # маска отражения - оттенки серого, альфа не нужна
        "flags": (),
        "path_param": "$envmapmask",
        "extra_vmt": {},
        # Маска работает только при включённом отражении - но окружение
        # предмета не трогаем: у золотых оно своё (cubemap_gold001), и карта
        # не должна подменять его обычным env_cubemap
        "vmt_defaults": {"$envmap": "env_cubemap"},
        "numeric": (),
        "needs_alpha": False,
        # «Авто»: маска из яркости базы (металл/светлое блестит сильнее)
        "derive_kind": "envmapmask",
        "preview": "env",
        # Окружение, цвет, сила и френель отражения (вики Valve, $envmap)
        "settings": {
            "env_cubemap": {"choices": ("keep", "map", "specular", "gold", "saxxy", "sunset"),
                            "default": "keep"},
            "env_tint": {"color": True, "default": "", "display": "#ffffff"},
            "env_strength": {"min": 0, "max": 300, "slider": True, "default": "", "display": 100},
            "env_fresnel": {"min": 0, "max": 100, "slider": True, "default": "", "display": 0},
        },
    },
    # Rim light (параметрический, без своей текстуры)
    # Обводка светом по контуру. Маску берёт из АЛЬФЫ $phongexponenttexture
    # (если включена phong-карта), иначе применяется равномерно. Требует $phong
    "rimlight": {
        "vmt_only": True,          # текстуры нет - пишем только параметры VMT
        "format": "VMT",           # для бейджа в диалоге
        "path_param": None,
        "extra_vmt": {
            "$phong": "1",
            "$rimlight": "1",
            "$rimlightexponent": "4",
            "$rimlightboost": "2",
        },
        "vmt_defaults": {"$phongfresnelranges": "[0 0.5 1]"},
        "numeric": ("$rimlightexponent", "$rimlightboost"),
        "preview": "rim",
        # Где светится обводка: везде или по маске (альфа Phong-карты +
        # $rimmask 1; так у 1713 материалов Valve)
        "settings": {
            "rim_mask": {"choices": ("all", "auto", "file"), "default": "all"},
            "rim_threshold": {"min": 0, "max": 255, "default": "",
                              "show_if": {"rim_mask": "auto"}},
            "rim_image": {"file": True, "show_if": {"rim_mask": "file"}},
        },
        # Rim считается phong-шейдером, а phong требует $bumpmap - без карты
        # нополей эффект НЕ виден. Поэтому гарантируем нормаль (не затирая
        # существующую): генерим из базы, если в VMT ещё нет $bumpmap
        "derive_auto_normal": True,
    },
    # Warp-карты (градиенты-lookup)
    # Это не обычные текстуры, а градиенты: lightwarp ремапит освещённость,
    # phongwarp - цвет/градиент блика. Им нужны CLAMP (без тайлинга) + NOMIP
    # (иначе градиент размывается мип-уровнями) и формат без DXT-бандинга
    "phongwarp": {
        "suffix": "_phongwarp",
        "format": "BGR888",            # градиент -> без DXT-бандинга
        "flags": ("CLAMPS", "CLAMPT"), # без тайлинга
        "options": {"nomipmaps": True},
        "size": (256, 256),            # 2D-lookup (fresnel × half-angle) - фикс. размер
        "path_param": "$phongwarptexture",
        "extra_vmt": {"$phong": "1"},  # phongwarp работает только при $phong
        "vmt_defaults": {"$phongfresnelranges": "[0 0.5 1]"},
        "numeric": (),
        "needs_alpha": False,
        # Градиент блика собирается в приложении (services/phongwarp.py)
        "generator": "phongwarp",
    },
    "lightwarp": {
        "suffix": "_lightwarp",
        "format": "BGR888",
        "flags": ("CLAMPS", "CLAMPT"),
        "options": {"nomipmaps": True},
        # $lightwarptexture в Source - 1D-рампа 256×1 (освещённость 0..1 берётся
        # как координата X). Игнорируем глобальный размер сборки и всегда делаем
        # 256×1, иначе ремап освещения искажается / раздувается память
        "size": (256, 1),
        "path_param": "$lightwarptexture",
        "extra_vmt": {},               # lightwarp работает самостоятельно
        "numeric": (),
        "needs_alpha": False,
        # Полоску можно собрать в приложении (services/lightwarp.py), а не
        # рисовать файл 256×1 вручную
        "generator": "lightwarp",
    },
}

# Порядок ОБРАБОТКИ при сборке (стабильный, не влияет на UI)
MAP_ORDER = ("detail", "selfillum", "phongexp", "phongcolor", "envmapmask",
             "rimlight", "phongwarp", "lightwarp")

# Порядок ОТОБРАЖЕНИЯ в диалоге (сетка 2 столбца, ряд за рядом)
MAP_DISPLAY_ORDER = ("phongexp", "phongcolor", "rimlight", "envmapmask",
                     "selfillum", "detail", "phongwarp", "lightwarp")


#: Окружения отражения: свои у TF2 (сколько материалов Valve их берёт -
#: по tf2_misc/tf2_textures)
CUBEMAPS = {
    "map": "env_cubemap",                         # окружение карты (1349)
    "specular": "cubemaps/cubemap_specular001",   # студийный блик (132)
    "gold": "cubemaps/cubemap_gold001",           # золото австралия (56)
    "saxxy": "effects/saxxy/saxxy_gold",          # золото Saxxy (200)
    "sunset": "cubemaps/cubemap_sunset001",       # закат (7)
}


def generator(name: str):
    """Модуль конструктора карты (clean_params, write_png) по имени"""
    if name == "lightwarp":
        from src.services import lightwarp
        return lightwarp
    if name == "phongwarp":
        from src.services import phongwarp
        return phongwarp
    return None


def clean_settings(cfg: dict, entry: dict) -> dict:
    """Свои настройки карты из присланного - по правилам `settings`"""
    import os
    import re

    out = {}
    for key, rule in cfg.get("settings", {}).items():
        value = entry.get(key)
        if value is None or str(value).strip() == "":
            continue
        value = str(value).strip()
        if "choices" in rule:
            if value in rule["choices"]:
                out[key] = value
        elif rule.get("float"):
            try:
                out[key] = f"{min(rule['max'], max(rule['min'], float(value))):g}"
            except ValueError:
                pass
        elif rule.get("color"):
            if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                out[key] = value.lower()
        elif rule.get("file"):
            if os.path.isfile(value):
                out[key] = value
        else:
            try:
                out[key] = str(int(min(rule["max"], max(rule["min"], round(float(value))))))
            except ValueError:
                pass
    return out


def normalize_maps(maps) -> dict:
    """
    Оставляет от присланного набора карт только осмысленное

    Проверка нужна не «на всякий случай»: запись уходит в генератор VTF и в
    VMT, и мусорный ключ там превращается в сломанный материал. Правила те же,
    что складывает диалог приложения (``MaterialMapsDialog.get_maps``):

      • параметрическая карта (rimlight) - только ``{"enabled": True}``;
      • авто-режим - ``{"derive": True}`` и необязательный порог;
      • файл - существующий путь в ``image``; у полоски из конструктора
        рядом её параметры ``generate`` (чтобы открыть конструктор снова);
      • ``{"mod": True}`` - карта, что уже стоит в VMT мода, остаётся как есть;
      • ``{"off": True}`` - карту мода сняли: сборка уберёт её из VMT. Явная
        отметка, а не отсутствие записи: «не трогал» и «снял» сборка обязана
        различать, и пустая запись в работе не сохраняется;
      • числовые параметры - только те, что карта объявила в ``numeric``
    """
    import os

    result = {}
    for map_id, entry in (maps or {}).items():
        cfg = MATERIAL_MAPS.get(map_id)
        if not cfg or not isinstance(entry, dict):
            continue

        image = str(entry.get('image', '')).strip()
        if entry.get('off'):
            result[map_id] = {'off': True}
            continue
        if cfg.get('vmt_only'):
            if not entry.get('enabled'):
                continue
            clean = {'enabled': True}
            if entry.get('mod'):
                clean['mod'] = True      # rim light мода: сборка его не переписывает
            clean.update(clean_settings(cfg, entry))
        elif entry.get('derive') and cfg.get('derive_kind'):
            clean = {'derive': True}
            threshold = str(entry.get('threshold', '')).strip()
            if threshold:
                clean['threshold'] = threshold
        elif image and os.path.isfile(image):
            clean = {'image': image}
            module = generator(cfg.get('generator', ''))
            if module and isinstance(entry.get('generate'), dict):
                clean['generate'] = module.clean_params(entry['generate'])
        elif entry.get('mod'):
            clean = {'mod': True}
        else:
            continue

        if not cfg.get('vmt_only'):
            clean.update(clean_settings(cfg, entry))
        choices = cfg.get('choices', {})
        for param in cfg.get('numeric', ()):
            value = str(entry.get(param, '')).strip()
            # Значение вне списка (старый «Multiply» = 7) - к умолчанию карты
            if value and (param not in choices or value in choices[param]):
                clean[param] = value
        result[map_id] = clean
    return result


def detect_maps(vmt_text: str) -> dict:
    """
    Карты, которые уже стоят в VMT (чужого мода): {map_id: запись}

    Запись - как у страницы: ``{"mod": True, "texture": путь из VMT, …}`` и
    значения числовых параметров карты, если VMT их задаёт. Rim light -
    ``{"enabled": True}`` при ``$rimlight 1``. Читаем деревом (vmt_parse):
    закомментированная строка картой не считается
    """
    from src.services import vmt_parse

    doc = vmt_parse.parse(vmt_text or '')
    found = {}
    for map_id in MAP_DISPLAY_ORDER:
        cfg = MATERIAL_MAPS[map_id]
        if map_id == 'rimlight':
            if not doc.flag('$rimlight'):
                continue
            entry = {'enabled': True, 'mod': True}
        elif map_id == 'phongcolor':
            colour = vmt_parse.parse_color(doc.get('$phongtint'))
            if colour and any(colour):
                entry = {'enabled': True, 'mod': True, 'tint': 'color',
                         'tint_color': '#%02x%02x%02x' % colour}
            elif doc.flag('$phongalbedotint'):
                entry = {'enabled': True, 'mod': True, 'tint': 'albedo'}
            else:
                continue
        elif cfg.get('vmt_only'):
            continue
        else:
            texture = doc.path(cfg['path_param'])
            if not texture:
                continue
            entry = {'mod': True, 'texture': texture}
        for param in cfg.get('numeric', ()):
            value = doc.get(param)
            if value is not None and str(value).strip():
                entry[param] = str(value).strip()
        found[map_id] = entry
    return found
