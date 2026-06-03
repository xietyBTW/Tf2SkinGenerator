"""
Готовые VMT-сниппеты для палитры вставки в редакторе и справочник
$-параметров для тултипов/автодополнения.

Сниппеты отформатированы с одним табом отступа — рассчитаны на вставку
внутрь корневого блока шейдера { ... }.
"""

# ── Сниппеты для палитры «Вставить» ──────────────────────────────────────── #
# Структура: {категория: [(подпись, текст_сниппета, тултип)]}

VMT_SNIPPETS = {
    "Параметры": [
        (
            "$basetexture — базовая текстура",
            '"$basetexture" "path/to/texture"',
            "Основная (диффузная) текстура материала.",
        ),
        (
            "$bumpmap — карта нормалей",
            '"$bumpmap" "path/to/normal"',
            "Карта нормалей (бамп-маппинг) для рельефа поверхности.",
        ),
        (
            "$translucent — прозрачность",
            '"$translucent" "1"',
            "Включает альфа-прозрачность (сортируемую). Для решёток/стекла.",
        ),
        (
            "$additive — аддитивность",
            '"$additive" "1"',
            "Аддитивное смешивание: чёрный невидим, светлое светится.",
        ),
        (
            "$nocull — двусторонний рендер",
            '"$nocull" "1"',
            "Рендерит обе стороны полигонов (отключает отсечение задних граней).",
        ),
    ],
    "Эффекты": [
        (
            "$selfillum — самосвечение",
            '"$selfillum" "1"\n\t"$selfillummask" "path/to/mask"',
            "Самосвечение по маске (белое в маске = светится, не зависит от света сцены).",
        ),
        (
            "$detail — detail-слой",
            '"$detail" "effects/tiledfire/fireLayeredSlowTiled512"\n'
            '\t"$detailscale" "8"\n'
            '\t"$detailblendmode" "1"\n'
            '\t"$detailblendfactor" "1"',
            "Второй слой текстуры. blendmode: 1=Additive, 7=Multiply, 4=UnlitAdditive.",
        ),
        (
            "$envmap — отражение (cubemap)",
            '"$envmap" "env_cubemap"\n\t"$envmaptint" "[.3 .3 .3]"',
            "Отражение окружения. env_cubemap — авто-кубмапа уровня.",
        ),
        (
            "$phong — блеск (металл)",
            '"$phong" "1"\n\t"$phongexponent" "20"\n\t"$phongboost" "1"\n\t"$phongfresnelranges" "[.25 .5 1]"',
            "Phong-блики. exponent — резкость блика (выше = металл), boost — сила.",
        ),
        (
            "$color — тонировка",
            '"$color" "[1 .5 .5]"',
            "Умножение цвета текстуры на RGB (значения 0..1).",
        ),
    ],
    "Прокси": [
        (
            "AnimatedTexture — анимация $basetexture",
            '"Proxies"\n'
            '\t{\n'
            '\t\t"AnimatedTexture"\n'
            '\t\t{\n'
            '\t\t\t"animatedtexturevar" "$basetexture"\n'
            '\t\t\t"animatedtextureframenumvar" "$frame"\n'
            '\t\t\t"animatedtextureframerate" "24"\n'
            '\t\t}\n'
            '\t}',
            "Покадровая анимация многокадровой VTF. Требует \"$frame\" \"0\" в параметрах.",
        ),
        (
            "$frame — кадр для анимации",
            '"$frame" "0"',
            "Текущий кадр анимированной текстуры (управляется прокси AnimatedTexture).",
        ),
        (
            "Paint — поддержка краски TF2",
            '"$blendtintbybasealpha" "1"\n'
            '\t"$blendtintcoloroverbase" "0"\n'
            '\t"Proxies"\n'
            '\t{\n'
            '\t\t"ItemTintColor"\n'
            '\t\t{\n'
            '\t\t\t"resultVar" "$color2"\n'
            '\t\t}\n'
            '\t}',
            "Окрашивание предмета краской из инвентаря TF2 (ItemTintColor).",
        ),
        (
            "TextureScroll — прокрутка текстуры",
            '"Proxies"\n'
            '\t{\n'
            '\t\t"TextureScroll"\n'
            '\t\t{\n'
            '\t\t\t"texturescrollvar" "$basetexturetransform"\n'
            '\t\t\t"texturescrollrate" "0.5"\n'
            '\t\t\t"texturescrollangle" "90"\n'
            '\t\t}\n'
            '\t}',
            "Бесконечная прокрутка текстуры (конвейеры, потоки энергии).",
        ),
    ],
    "Шаблоны": [
        (
            "VertexLitGeneric (базовый)",
            None,  # None = заменить ВЕСЬ документ
            "Стандартный шейдер для моделей. Заменяет весь VMT.",
        ),
        (
            "UnlitGeneric (без освещения)",
            None,
            "Шейдер без освещения (HUD, спреи, светящееся). Заменяет весь VMT.",
        ),
        (
            "Хром / зеркало",
            None,
            "Сильно отражающий металл через $envmap. Заменяет весь VMT.",
        ),
    ],
}

# Полные шаблоны (для категории «Шаблоны» — заменяют весь документ)
VMT_FULL_TEMPLATES = {
    "VertexLitGeneric (базовый)": (
        '"VertexLitGeneric"\n'
        '{\n'
        '\t"$basetexture" "path/to/texture"\n'
        '}\n'
    ),
    "UnlitGeneric (без освещения)": (
        '"UnlitGeneric"\n'
        '{\n'
        '\t"$basetexture" "path/to/texture"\n'
        '\t"$translucent" "1"\n'
        '}\n'
    ),
    "Хром / зеркало": (
        '"VertexLitGeneric"\n'
        '{\n'
        '\t"$basetexture" "path/to/texture"\n'
        '\t"$envmap" "env_cubemap"\n'
        '\t"$envmaptint" "[1 1 1]"\n'
        '\t"$normalmapalphaenvmapmask" "1"\n'
        '\t"$envmapcontrast" "1"\n'
        '}\n'
    ),
}

# ── Справочник $-параметров (тултипы / будущее автодополнение) ────────────── #

VMT_PARAM_DOCS = {
    "$basetexture": "Основная (диффузная) текстура.",
    "$basetexture2": "Вторая базовая текстура (для blend-материалов).",
    "$bumpmap": "Карта нормалей (рельеф).",
    "$detail": "Detail-текстура (второй слой).",
    "$detailscale": "Масштаб тайлинга detail-слоя.",
    "$detailblendmode": "Режим смешивания detail: 0=DecalModulate, 1=Additive, 7=Multiply.",
    "$detailblendfactor": "Сила detail-эффекта (0..1).",
    "$selfillum": "Самосвечение (по альфе $basetexture или маске).",
    "$selfillummask": "Маска самосвечения (отдельная текстура).",
    "$envmap": "Карта отражения окружения (env_cubemap или путь к кубмапе).",
    "$envmaptint": "Цвет/сила отражения [R G B].",
    "$envmapmask": "Маска отражения (где блестит).",
    "$phong": "Phong-блики (1=вкл).",
    "$phongexponent": "Резкость блика (выше = металличнее).",
    "$phongboost": "Усиление силы блика.",
    "$phongfresnelranges": "Френель блика [близко середина далеко].",
    "$translucent": "Альфа-прозрачность (сортируемая).",
    "$alphatest": "Альфа-тест (резкая прозрачность по порогу).",
    "$additive": "Аддитивное смешивание (свечение).",
    "$nocull": "Двусторонний рендер (без отсечения).",
    "$color": "Тонировка цвета [R G B] (0..1).",
    "$color2": "Вторичный цвет (используется краской).",
    "$frame": "Текущий кадр анимированной текстуры.",
    "$nofog": "Отключить туман на материале.",
    "$ignorez": "Рендерить поверх геометрии (игнор глубины).",
    "$vertexcolor": "Использовать цвет вершин.",
    "$vertexalpha": "Использовать альфу вершин.",
    "$surfaceprop": "Свойство поверхности (звук шагов/попаданий).",
    "$model": "1 = материал для модели (не для браша).",
    "$decal": "Материал-декаль (наклейка).",

    # ── TF2: рендеринг персонажей (phong / rim / lightwarp) ──────────────── #
    "$lightwarptexture": "Тонировка по яркости (основа «мультяшного» вида TF2). Требует $bumpmap.",
    "$phongexponenttexture": "Текстура-маска phong: R=сила блика, G=маска $phongalbedotint, A=маска $rimlight.",
    "$phongalbedotint": "Тонировать блик цветом из $basetexture (по маске G phong-текстуры).",
    "$basemapalphaphongmask": "Использовать альфу $basetexture как маску силы phong.",
    "$rimlight": "Подсветка краёв модели (rim light). Требует $phong=1 и $bumpmap.",
    "$rimlightexponent": "Резкость/ширина rim-подсветки (выше = уже). Напр. 10.",
    "$rimlightboost": "Сила rim-подсветки. Напр. 2..3.",
    "$rimmask": "1 = маскировать rim альфой $phongexponenttexture.",

    # ── TF2: краска (paint) ─────────────────────────────────────────────── #
    "$blendtintbybasealpha": "Окрашивать только там, где альфа $basetexture (маска краски).",
    "$blendtintcoloroverbase": "0..1: насколько краска перекрывает базовый цвет.",

    # ── Маски/контраст envmap (отражения) ───────────────────────────────── #
    "$normalmapalphaenvmapmask": "Использовать альфу $bumpmap как маску отражения.",
    "$basealphaenvmapmask": "Использовать альфу $basetexture как маску отражения.",
    "$envmapcontrast": "Контраст отражения (1 = только самые яркие участки).",
    "$envmapsaturation": "Насыщенность отражения (0 = ч/б).",

    # ── TF2: невидимость шпиона ──────────────────────────────────────────── #
    "$cloakpassenabled": "Включает проход невидимости (маскировка шпиона). Нужен прокси Invisibility.",
}


def all_param_names() -> list:
    """Отсортированный список всех известных $-параметров (для автодополнения)."""
    return sorted(VMT_PARAM_DOCS.keys())
