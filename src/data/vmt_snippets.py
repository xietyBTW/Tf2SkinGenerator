"""
Готовые VMT-сниппеты для меню «Готовые эффекты» в редакторе и справочник
$-параметров для подсказок и списка «Справочник».

Сниппеты отформатированы с одним табом отступа — рассчитаны на вставку
внутрь корневого блока шейдера { ... }.

Источники справочника — первоисточники, а не пересказ:
  • объявления параметров шейдера VertexLitGeneric в коде Valve
    (ValveSoftware/source-sdk-2013, stdshaders/vertexlitgeneric_dx9.cpp —
    там же TF2-проходы невидимости и блеска Killstreak);
  • клиентские прокси TF2 (game/client/tf/c_tf_player.cpp: YellowLevel,
    BurnLevel, ModelGlowColor, AnimatedWeaponSheen, CommunityWeapon);
  • Valve Developer Community: $phong, $rimlight, $detail, $envmap,
    $selfillum, $color, VertexLitGeneric.
Набор параметров — те, что реально встречаются в материалах моделей TF2
(tf2_misc_dir.vpk, materials/models/*.vmt), а не всё, что знает движок.
"""

# ── Справочник $-параметров ─────────────────────────────────────────────── #
# (группа_ru, группа_en, [(параметр, описание_ru, описание_en), ...])
# Описание — что параметр делает и что ему нужно, одной-двумя фразами.
# Порядок групп и параметров — порядок показа в справочнике редактора.

VMT_PARAM_GROUPS = [
    ("Основа", "Basics", [
        ("$basetexture",
         "Главная текстура материала — то, что видно на модели.",
         "The main texture of the material, what you see on the model."),
        ("$basetexturetransform",
         "Сдвиг, поворот и масштаб $basetexture: center, scale, rotate, translate.",
         "Moves, rotates and scales $basetexture: center, scale, rotate, translate."),
        ("$frame",
         "Кадр многокадровой $basetexture. Обычно его крутит прокси AnimatedTexture.",
         "Frame of a multi-frame $basetexture. Usually driven by the AnimatedTexture proxy."),
        ("$bumpmap",
         "Карта нормалей: рельеф поверхности. Её альфа по умолчанию — маска бликов $phong.",
         "Normal map: surface relief. Its alpha is the default $phong mask."),
        ("$bumpframe",
         "Кадр многокадровой $bumpmap.",
         "Frame of a multi-frame $bumpmap."),
        ("$color2",
         "Тонировка модели [R G B], 1 — без изменений. В оружии и шапках TF2 его каждый кадр перезаписывают прокси (свечение крита, Банкате), так что своё значение не удержится.",
         "Model tint [R G B], 1 means unchanged. On TF2 weapons and hats proxies overwrite it every frame (crit glow, Jarate), so your own value won't stick."),
        ("$color",
         "Тонировка [R G B]. На моделях работает $color2, этот — для UnlitGeneric и браши.",
         "Tint [R G B]. On models use $color2; this one is for UnlitGeneric and brushes."),
        ("$surfaceprop",
         "Материал поверхности для звуков и частиц попаданий: metal, wood, flesh…",
         "Surface type for impact sounds and particles: metal, wood, flesh…"),
        ("$model",
         "1 — материал для модели. Движок обычно ставит это сам.",
         "1 means the material is for a model. The engine usually sets it itself."),
    ]),

    ("Прозрачность", "Transparency", [
        ("$translucent",
         "Плавная прозрачность по альфе $basetexture. Дорогая; полупрозрачные слои могут рисоваться не в том порядке.",
         "Smooth transparency from the $basetexture alpha. Expensive; overlapping layers can sort wrong."),
        ("$alphatest",
         "Резкая прозрачность: тёмные пиксели альфы просто исчезают. Дешевле $translucent, для сеток и листвы.",
         "Hard cutout: dark alpha pixels just disappear. Cheaper than $translucent, good for grates and foliage."),
        ("$alphatestreference",
         "Порог для $alphatest (0..1): всё, что ниже, вырезается.",
         "Threshold for $alphatest (0..1): anything below is cut out."),
        ("$allowalphatocoverage",
         "Сглаживает края $alphatest при включённом сглаживании.",
         "Smooths $alphatest edges when anti-aliasing is on."),
        ("$additive",
         "Цвет прибавляется к фону: чёрное невидимо, светлое светится.",
         "Color is added to what's behind: black is invisible, bright glows."),
        ("$alpha",
         "Общая непрозрачность материала (0..1). Работает не во всех версиях движка.",
         "Overall opacity of the material (0..1). Doesn't work in every engine version."),
        ("$nocull",
         "Рисовать обе стороны полигонов.",
         "Draw both sides of polygons."),
        ("$vertexalpha",
         "Брать прозрачность из вершин модели.",
         "Take transparency from the model's vertices."),
        ("$vertexcolor",
         "Брать цвет из вершин модели.",
         "Take color from the model's vertices."),
        ("$ignorez",
         "Рисовать поверх всего, не глядя на глубину.",
         "Draw on top of everything, ignoring depth."),
        ("$nofog",
         "Туман карты материал не затрагивает.",
         "Map fog doesn't affect the material."),
        ("$nodecal",
         "На материал не ложатся декали (следы от пуль, кровь).",
         "No decals (bullet holes, blood) land on the material."),
        ("$decal",
         "Материал — это декаль.",
         "The material is a decal."),
    ]),

    ("Свет", "Lighting", [
        ("$halflambert",
         "Мягкое освещение: тень не уходит в чёрное. Основа вида TF2; с $phong включается само.",
         "Soft lighting: shadows don't go pitch black. The basis of the TF2 look; turns on by itself with $phong."),
        ("$lightwarptexture",
         "Градиент, по которому перекрашивается освещение: тёмное — цветом слева, светлое — справа. Отсюда мультяшный вид TF2. Без $bumpmap движок подставит стандартный. Текстуре нужны флаги Clamp S и Clamp T.",
         "A gradient that recolors the lighting: dark areas take the left color, bright ones the right. This gives TF2 its cartoon look. Without $bumpmap the engine uses a default one. The texture needs the Clamp S and Clamp T flags."),
        ("$flashlightnolambert",
         "Фонарик освещает поверхность, не глядя на её нормаль.",
         "The flashlight lights the surface regardless of its normal."),
    ]),

    ("Блики (phong)", "Highlights (phong)", [
        ("$phong",
         "Включает блики. Маска силы — альфа $bumpmap или $basetexture ($basemapalphaphongmask).",
         "Turns on highlights. Strength mask is the $bumpmap alpha or the $basetexture alpha ($basemapalphaphongmask)."),
        ("$phongexponent",
         "Размер блика: больше — меньше и резче, как у металла. Перекрывает $phongexponenttexture.",
         "Highlight size: higher is smaller and sharper, like metal. Overrides $phongexponenttexture."),
        ("$phongexponenttexture",
         "Текстура для бликов: красный — размер блика по пикселям, зелёный — маска $phongalbedotint, альфа — маска контура ($rimmask).",
         "Highlight texture: red is per-pixel highlight size, green is the $phongalbedotint mask, alpha is the rim mask ($rimmask)."),
        ("$phongexponentfactor",
         "Множитель к значению из $phongexponenttexture. По умолчанию 0; разумно около 150.",
         "Multiplier for $phongexponenttexture values. Defaults to 0; around 150 is sensible."),
        ("$phongboost",
         "Яркость блика.",
         "Highlight brightness."),
        ("$phongfresnelranges",
         "[прямо середина край] — сила блика в зависимости от угла взгляда. По умолчанию [0 0.5 1].",
         "[facing middle edge]: highlight strength by viewing angle. Defaults to [0 0.5 1]."),
        ("$phongtint",
         "Цвет блика [R G B]. Красит и подсветку контура; отключает $phongalbedotint.",
         "Highlight color [R G B]. Also tints the rim light; disables $phongalbedotint."),
        ("$phongalbedotint",
         "Красит блик цветом текстуры по зелёному каналу $phongexponenttexture.",
         "Tints the highlight with the texture color, using the green channel of $phongexponenttexture."),
        ("$phongwarptexture",
         "Текстура, которой окрашивается блик: переливы, перламутр.",
         "A texture that colors the highlight: iridescence, pearl."),
        ("$basemapalphaphongmask",
         "Маска бликов — альфа $basetexture, а не $bumpmap.",
         "Use the $basetexture alpha as the highlight mask instead of $bumpmap."),
        ("$invertphongmask",
         "Инвертирует маску бликов.",
         "Inverts the highlight mask."),
        ("$bumpmapalphaphongmask",
         "В коде шейдера Valve такого параметра нет: маска бликов и так берётся из альфы $bumpmap.",
         "Valve's shader code has no such parameter: the highlight mask already comes from the $bumpmap alpha."),
        ("$normalmapalphaphongmask",
         "В коде шейдера Valve такого параметра нет: маска бликов и так берётся из альфы $bumpmap.",
         "Valve's shader code has no such parameter: the highlight mask already comes from the $bumpmap alpha."),
    ]),

    ("Подсветка контура", "Rim light", [
        ("$rimlight",
         "Светлая кайма по краю модели от окружающего света. Нужен $phong.",
         "A light rim along the model's edge from ambient light. Needs $phong."),
        ("$rimlightexponent",
         "Ширина каймы: больше — тоньше.",
         "Rim width: higher is thinner."),
        ("$rimlightboost",
         "Яркость каймы.",
         "Rim brightness."),
        ("$rimmask",
         "Маскировать кайму альфой $phongexponenttexture.",
         "Mask the rim with the $phongexponenttexture alpha."),
    ]),

    ("Отражения", "Reflections", [
        ("$envmap",
         "Отражение окружения (кубмапа). env_cubemap — ближайшая на карте, или путь к своей.",
         "Environment reflection (cubemap). env_cubemap picks the nearest one on the map, or give a path to your own."),
        ("$envmaptint",
         "Цвет и сила отражения [R G B]. Шкала нелинейная: 0.25 — это около 5%.",
         "Reflection color and strength [R G B]. The scale isn't linear: 0.25 is about 5%."),
        ("$envmapmask",
         "Маска отражения. На моделях не работает вместе с $bumpmap и $phong.",
         "Reflection mask. On models it doesn't work together with $bumpmap or $phong."),
        ("$normalmapalphaenvmapmask",
         "Маска отражения — альфа $bumpmap.",
         "Use the $bumpmap alpha as the reflection mask."),
        ("$basealphaenvmapmask",
         "Маска отражения — альфа $basetexture.",
         "Use the $basetexture alpha as the reflection mask."),
        ("$envmapcontrast",
         "0 — как есть, 1 — остаются только яркие места. Не работает с $phong.",
         "0 is as is, 1 keeps only the bright spots. Doesn't work with $phong."),
        ("$envmapsaturation",
         "Насыщенность отражения: 0 — ч/б, 1 — как есть. Не работает с $phong.",
         "Reflection saturation: 0 is grayscale, 1 is as is. Doesn't work with $phong."),
        ("$envmapfresnel",
         "Отражение сильнее на краях, чем в лоб.",
         "Reflection is stronger at the edges than head-on."),
        ("$envmapframe",
         "Кадр анимированной кубмапы.",
         "Frame of an animated cubemap."),
    ]),

    ("Свечение", "Glow", [
        ("$selfillum",
         "Светится независимо от света сцены. Маска — альфа $basetexture или $selfillummask. Не работает с $translucent и $alphatest.",
         "Glows regardless of scene lighting. Mask is the $basetexture alpha or $selfillummask. Doesn't work with $translucent or $alphatest."),
        ("$selfillummask",
         "Отдельная маска свечения: белое светится.",
         "A separate glow mask: white glows."),
        ("$selfillumtint",
         "Цвет свечения [R G B]. В оружии TF2 его ставит прокси (свечение крита).",
         "Glow color [R G B]. On TF2 weapons a proxy sets it (crit glow)."),
        ("$selfillumfresnel",
         "Свечение зависит от угла взгляда (настройка — $selfillumfresnelminmaxexp). Нужен $bumpmap.",
         "Glow depends on viewing angle (see $selfillumfresnelminmaxexp). Needs $bumpmap."),
        ("$selfillumfresnelminmaxexp",
         "[минимум максимум степень] для $selfillumfresnel.",
         "[min max exponent] for $selfillumfresnel."),
        ("$selfillum_envmapmask_alpha",
         "Маска свечения — альфа $envmapmask. Вместо $selfillum, не вместе.",
         "Glow mask from the $envmapmask alpha. Use instead of $selfillum, not together."),
    ]),

    ("Второй слой (detail)", "Detail layer", [
        ("$detail",
         "Вторая текстура поверх основной: узор, свечение, грязь.",
         "A second texture on top of the main one: pattern, glow, grime."),
        ("$detailscale",
         "Сколько раз слой повторяется на модели. По умолчанию 4; можно [X Y].",
         "How many times the layer repeats on the model. Defaults to 4; can be [X Y]."),
        ("$detailblendmode",
         "Как смешать слой: 0 — затемнить/осветлить, 1 — прибавить, 2 — наложить по альфе, 5 — светится, 8 — умножить (без $bumpmap).",
         "How to blend the layer: 0 darken/lighten, 1 add, 2 overlay by alpha, 5 glow, 8 multiply (without $bumpmap)."),
        ("$detailblendfactor",
         "Сила слоя: 0 — не видно, 1 — полностью.",
         "Layer strength: 0 is invisible, 1 is full."),
        ("$detailtint",
         "Цвет слоя [R G B].",
         "Layer color [R G B]."),
        ("$detailframe",
         "Кадр многокадровой detail-текстуры.",
         "Frame of a multi-frame detail texture."),
        ("$detailtexturetransform",
         "Сдвиг, поворот и масштаб слоя.",
         "Moves, rotates and scales the layer."),
    ]),

    ("TF2: краска", "TF2: paint", [
        ("$blendtintbybasealpha",
         "Краска ложится только там, где альфа $basetexture белая. Не работает с $selfillum, $translucent и $alphatest.",
         "Paint applies only where the $basetexture alpha is white. Doesn't work with $selfillum, $translucent or $alphatest."),
        ("$blendtintcoloroverbase",
         "0 — краска умножается на цвет текстуры, 1 — заменяет его.",
         "0 multiplies paint with the texture color, 1 replaces it."),
        ("$colortint_base",
         "Цвет предмета без краски. Прокси подставляет его в $color2, пока предмет не покрашен.",
         "The item's color without paint. A proxy puts it into $color2 while the item is unpainted."),
        ("$colortint_tmp",
         "Сюда прокси ItemTintColor пишет цвет краски. Сам ничего не делает.",
         "The ItemTintColor proxy writes the paint color here. Does nothing by itself."),
    ]),

    ("TF2: эффекты игры", "TF2: game effects", [
        ("$cloakpassenabled",
         "Материал исчезает вместе с невидимым шпионом. Без него предмет может остаться видимым.",
         "The material fades with a cloaked Spy. Without it the item may stay visible."),
        ("$cloakfactor",
         "0 — видно, 1 — полностью невидимо. Ставит прокси невидимости.",
         "0 is visible, 1 is fully invisible. Set by the cloak proxy."),
        ("$cloakcolortint",
         "Цвет искажения при невидимости.",
         "Color of the cloak distortion."),
        ("$refractamount",
         "Сила искажения при частичной невидимости. По умолчанию 2.",
         "Distortion strength while partly cloaked. Defaults to 2."),
        ("$sheenpassenabled",
         "Блеск Killstreak на этом материале.",
         "Killstreak sheen on this material."),
        ("$sheenmap",
         "Кубмапа блеска Killstreak. У предмета с Killstreak её ставит игра.",
         "Killstreak sheen cubemap. On a Killstreak item the game sets it."),
        ("$sheenmapmask",
         "Бегущая маска блеска. Её кадры крутит прокси AnimatedWeaponSheen.",
         "The moving sheen mask. The AnimatedWeaponSheen proxy flips its frames."),
        ("$sheenmapmaskframe",
         "Текущий кадр маски блеска.",
         "Current frame of the sheen mask."),
        ("$sheenmaptint",
         "Цвет блеска Killstreak. Ставит игра по выбранному цвету.",
         "Killstreak sheen color. The game sets it from the chosen color."),
        ("$sheenindex",
         "Вид блеска (сложение, замена цвета…). Ставит игра.",
         "Sheen type (additive, color override…). Set by the game."),
        ("$sheenmapmaskdirection",
         "Вдоль какой оси бежит блеск: 0 — X, 1 — Y, 2 — Z.",
         "Which axis the sheen runs along: 0 X, 1 Y, 2 Z."),
        ("$yellow",
         "Жёлтый оттенок от Банкате. Прокси YellowLevel пишет сюда цвет, и он умножается на $color2.",
         "Jarate yellow. The YellowLevel proxy writes a color here, which is multiplied into $color2."),
        ("$glowcolor",
         "Цвет свечения при критах (прокси ModelGlowColor). Обычно копируется в $selfillumtint и $color2.",
         "Crit glow color (ModelGlowColor proxy). Usually copied into $selfillumtint and $color2."),
        ("$burnlevel",
         "Насколько обгорел игрок: 0..1, ставит прокси BurnLevel.",
         "How burnt the player is: 0..1, set by the BurnLevel proxy."),
        ("$invulnlevel",
         "Убер на модели игрока: прокси InvulnLevel ставит 0, когда убер заканчивается.",
         "Übercharge on the player model: the InvulnLevel proxy sets 0 when it wears off."),
        ("$commweapon",
         "1 — оружие качества «Сообщество». Ставит прокси CommunityWeapon; блики усиливаются на $commadd_*.",
         "1 on Community quality weapons. Set by the CommunityWeapon proxy; highlights get boosted by $commadd_*."),
        ("$commadd_phongexponent",
         "Сколько прибавить к $phongexponent у оружия «Сообщества».",
         "How much to add to $phongexponent on Community weapons."),
        ("$commadd_phongboost",
         "Сколько прибавить к $phongboost у оружия «Сообщества».",
         "How much to add to $phongboost on Community weapons."),
        ("$basephongexponent",
         "Обычный $phongexponent, от которого считают прибавку «Сообщества».",
         "The normal $phongexponent the Community bonus is added to."),
        ("$basephongboost",
         "Обычный $phongboost, от которого считают прибавку «Сообщества».",
         "The normal $phongboost the Community bonus is added to."),
        ("$tempvar",
         "Служебная переменная для прокси. Сама ничего не делает.",
         "A scratch variable for proxies. Does nothing by itself."),
        ("$one",
         "Служебная переменная для прокси (обычно 1). Сама ничего не делает.",
         "A scratch variable for proxies (usually 1). Does nothing by itself."),
    ]),
]

VMT_PARAM_DOCS = {p: ru for _, _, items in VMT_PARAM_GROUPS for p, ru, _ in items}
VMT_PARAM_DOCS_EN = {p: en for _, _, items in VMT_PARAM_GROUPS for p, _, en in items}


def param_doc(param: str, lang: str = "en") -> str:
    """Описание $-параметра на языке приложения ('' если параметр неизвестен).
    Регистр не важен: в VMT пишут и $cloakPassEnabled, и $cloakpassenabled."""
    key = (param or "").lower()
    if lang == "ru":
        return VMT_PARAM_DOCS.get(key, "")
    return VMT_PARAM_DOCS_EN.get(key) or VMT_PARAM_DOCS.get(key, "")


def all_param_names() -> list:
    """Отсортированный список всех известных $-параметров (для автодополнения)."""
    return sorted(VMT_PARAM_DOCS.keys())


def param_reference(lang: str = "en") -> list:
    """Справочник по группам — в порядке показа: [{'group', 'params': [...]}]."""
    ru = lang == "ru"
    return [{"group": g_ru if ru else g_en,
             "params": [{"param": p, "doc": d_ru if ru else d_en}
                        for p, d_ru, d_en in items]}
            for g_ru, g_en, items in VMT_PARAM_GROUPS]


# ── Готовые эффекты ─────────────────────────────────────────────────────── #
# Структура: {категория: [(подпись, текст_сниппета, пояснение)]}
# Сниппет None — шаблон, заменяющий ВЕСЬ документ (VMT_FULL_TEMPLATES).
# Блок "Proxies" в сниппете вливается в уже существующий блок документа:
# материал читает только первый "Proxies", и второй молча не работал бы.

VMT_SNIPPETS = {
    "Эффекты": [
        (
            "Свечение",
            '"$selfillum" "1"\n\t"$selfillummask" "path/to/mask"',
            "Части текстуры светятся в темноте. Маска — ч/б текстура: белое светится.",
        ),
        (
            "Блики как у металла",
            '"$phong" "1"\n\t"$phongexponent" "20"\n\t"$phongboost" "1"\n\t"$phongfresnelranges" "[.25 .5 1]"',
            "Блестящие блики. exponent — резкость, boost — яркость.",
        ),
        (
            "Подсветка контура",
            '"$rimlight" "1"\n\t"$rimlightexponent" "4"\n\t"$rimlightboost" "2"',
            "Светлая кайма по краю модели, как у стоковых предметов. Нужны блики ($phong).",
        ),
        (
            "Отражение",
            '"$envmap" "env_cubemap"\n\t"$envmaptint" "[.3 .3 .3]"',
            "Отражает окружение. $envmaptint — сила отражения.",
        ),
        (
            "Второй слой (detail)",
            '"$detail" "effects/tiledfire/fireLayeredSlowTiled512"\n'
            '\t"$detailscale" "8"\n'
            '\t"$detailblendmode" "5"\n'
            '\t"$detailblendfactor" "1"',
            "Вторая текстура поверх основной. Режим: 0 — затемнить/осветлить, 1 — прибавить, 5 — светится, 8 — умножить.",
        ),
        (
            "Австралий — золотой металл",
            '"$envmap" "cubemaps/cubemap_gold001"\n'
            '\t"$envmaptint" "[2.5 2.5 1.15]"\n'
            '\t"$phong" "1"\n'
            '\t"$phongexponent" "90"\n'
            '\t"$phongboost" "10"\n'
            '\t"$phongfresnelranges" "[.5 .5 3]"\n'
            '\t"$basemapalphaphongmask" "1"\n'
            '\t"$lightwarptexture" "models/lightwarps/weapon_lightwarp"\n'
            '\t"$rimlight" "1"\n'
            '\t"$rimlightexponent" "50"\n'
            '\t"$rimlightboost" "0"\n'
            '\t"$halflambert" "1"',
            "Блеск как у австралиевого оружия Valve. Цвет даёт ваша текстура — перекрасьте её в золото.",
        ),
    ],
    "Прозрачность": [
        (
            "Плавная прозрачность",
            '"$translucent" "1"',
            "Прозрачность по альфа-каналу текстуры.",
        ),
        (
            "Вырезать по альфе",
            '"$alphatest" "1"',
            "Резкая прозрачность: тёмное в альфе исчезает. Для сеток и листвы.",
        ),
        (
            "Светится поверх фона",
            '"$additive" "1"',
            "Цвет прибавляется к фону: чёрное невидимо, светлое светится.",
        ),
        (
            "Видно с обеих сторон",
            '"$nocull" "1"',
            "Рисует обе стороны полигонов.",
        ),
    ],
    "Анимация": [
        (
            "Покадровая анимация",
            '"$frame" "0"\n'
            '\t"Proxies"\n'
            '\t{\n'
            '\t\t"AnimatedTexture"\n'
            '\t\t{\n'
            '\t\t\t"animatedtexturevar" "$basetexture"\n'
            '\t\t\t"animatedtextureframenumvar" "$frame"\n'
            '\t\t\t"animatedtextureframerate" "24"\n'
            '\t\t}\n'
            '\t}',
            "Проигрывает кадры многокадровой текстуры. 24 — кадров в секунду.",
        ),
        (
            "Прокрутка текстуры",
            '"Proxies"\n'
            '\t{\n'
            '\t\t"TextureScroll"\n'
            '\t\t{\n'
            '\t\t\t"texturescrollvar" "$basetexturetransform"\n'
            '\t\t\t"texturescrollrate" "0.5"\n'
            '\t\t\t"texturescrollangle" "90"\n'
            '\t\t}\n'
            '\t}',
            "Текстура бесконечно едет в сторону: конвейеры, потоки энергии.",
        ),
    ],
    "Краска TF2": [
        (
            # Как у Valve: ItemTintColor отдаёт (0 0 0), пока предмет не
            # покрашен (econ_wearable.cpp), поэтому цвет идёт через
            # SelectFirstIfNonZero с запасным $colortint_base. Прямо в $color2
            # непокрашенный предмет выходил бы чёрным по маске.
            "Краска из игры",
            '"$blendtintbybasealpha" "1"\n'
            '\t"$blendtintcoloroverbase" "0"\n'
            '\t"$colortint_base" "{255 255 255}"\n'
            '\t"$colortint_tmp" "[0 0 0]"\n'
            '\t"Proxies"\n'
            '\t{\n'
            '\t\t"ItemTintColor"\n'
            '\t\t{\n'
            '\t\t\t"resultVar" "$colortint_tmp"\n'
            '\t\t}\n'
            '\t\t"SelectFirstIfNonZero"\n'
            '\t\t{\n'
            '\t\t\t"srcVar1" "$colortint_tmp"\n'
            '\t\t\t"srcVar2" "$colortint_base"\n'
            '\t\t\t"resultVar" "$color2"\n'
            '\t\t}\n'
            '\t}',
            "Предмет красится краской из инвентаря там, где альфа текстуры белая. Без краски — цвет $colortint_base.",
        ),
    ],
    "Заменить весь материал": [
        (
            "VertexLitGeneric (базовый)",
            None,
            "Стандартный материал модели. Заменяет весь VMT.",
        ),
        (
            "UnlitGeneric (без освещения)",
            None,
            "Материал без освещения: всегда одинаково яркий. Заменяет весь VMT.",
        ),
        (
            "Хром / зеркало",
            None,
            "Сильно отражающий металл. Заменяет весь VMT.",
        ),
    ],
}

# Английские подписи меню: {русская подпись или категория: английская}.
VMT_SNIPPETS_EN = {
    "Эффекты": "Effects",
    "Прозрачность": "Transparency",
    "Анимация": "Animation",
    "Краска TF2": "TF2 paint",
    "Заменить весь материал": "Replace the whole material",
    "Свечение": ("Glow", "Parts of the texture glow in the dark. The mask is a black-and-white texture: white glows."),
    "Блики как у металла": ("Metal highlights", "Shiny highlights. exponent is sharpness, boost is brightness."),
    "Подсветка контура": ("Rim light", "A light rim along the model's edge, like stock items. Needs highlights ($phong)."),
    "Отражение": ("Reflection", "Reflects the surroundings. $envmaptint is the reflection strength."),
    "Второй слой (detail)": ("Detail layer", "A second texture on top of the main one. Mode: 0 darken/lighten, 1 add, 5 glow, 8 multiply."),
    "Австралий — золотой металл": ("Australium gold", "Shine like Valve's Australium weapons. Color comes from your texture, so repaint it gold."),
    "Плавная прозрачность": ("Smooth transparency", "Transparency from the texture's alpha channel."),
    "Вырезать по альфе": ("Cut out by alpha", "Hard transparency: dark alpha disappears. For grates and foliage."),
    "Светится поверх фона": ("Glow over background", "Color is added to what's behind: black is invisible, bright glows."),
    "Видно с обеих сторон": ("Visible from both sides", "Draws both sides of polygons."),
    "Покадровая анимация": ("Frame animation", "Plays the frames of a multi-frame texture. 24 is frames per second."),
    "Прокрутка текстуры": ("Scrolling texture", "The texture keeps sliding: conveyors, energy streams."),
    "Краска из игры": ("In-game paint", "The item takes paint from the inventory where the texture alpha is white. Unpainted, it uses $colortint_base."),
    "VertexLitGeneric (базовый)": ("VertexLitGeneric (basic)", "The standard model material. Replaces the whole VMT."),
    "UnlitGeneric (без освещения)": ("UnlitGeneric (unlit)", "A material without lighting: always equally bright. Replaces the whole VMT."),
    "Хром / зеркало": ("Chrome / mirror", "Highly reflective metal. Replaces the whole VMT."),
}

# Сниппеты-СЛИЯНИЯ: не вставляются под курсор, а правят документ — у ключа,
# который уже есть, меняется значение (в VMT последний одноимённый ключ
# перекрывает первые: KeyValues::FindKey(name, true) переиспользует узел, и
# простая вставка в начало блока ничего бы не меняла), перечисленные ключи
# гасятся комментарием. Австралию мешает $phongexponenttexture: пока
# текстура-маска подключена, шейдер берёт её, а не $phongexponent.
VMT_MERGE_REMOVES = {
    "Австралий — золотой металл": [
        "$phongexponenttexture", "$phongexponentfactor", "$phongalbedotint",
    ],
}

# Полные шаблоны (категория «Заменить весь материал» — заменяют весь документ)
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
