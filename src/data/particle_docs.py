"""
Справочник параметров частиц: что делает модуль, что значит атрибут и какие
значения осмысленны у числовых перечислений.

Зачем отдельный файл, а не translations.py: это не строки интерфейса, а
предметный справочник по формату Source — сотни коротких пояснений, привязанных
к именам атрибутов из PCF. В общем словаре переводов они утроили бы файл и
перемешались бы с подписями кнопок. Здесь пара (ru, en) лежит рядом с ключом,
поэтому пояснение и перевод правятся одной строкой.

Ключи — имена атрибутов В НИЖНЕМ РЕГИСТРЕ: systems_json отдаёт их casefold-нутыми
(srctools), а в самих PCF регистр гуляет от файла к файлу.

Источники: заголовки particles.h/particles_internal.h (индексы полей),
DMXELEMENT_UNPACK-блоки движка Source и срез 134 стоковых PCF игры
(10 426 систем) — по нему выбрано, какие параметры вообще стоит описывать.
"""

from typing import Dict, Optional, Tuple

#: Индексы полей частицы (PARTICLE_ATTRIBUTE_* из particles.h). На них
#: ссылаются все remap/oscillate/noise-модули через «output field» и т.п.
PARTICLE_FIELDS: Dict[int, Tuple[str, str]] = {
    0: ("позиция XYZ", "position XYZ"),
    1: ("время жизни", "lifetime"),
    2: ("прошлая позиция XYZ", "previous position XYZ"),
    3: ("радиус", "radius"),
    4: ("поворот (roll)", "rotation (roll)"),
    5: ("скорость поворота", "rotation speed"),
    6: ("цвет RGB", "color RGB"),
    7: ("прозрачность", "alpha"),
    8: ("время рождения", "creation time"),
    9: ("кадр спрайт-листа", "sprite sheet sequence"),
    10: ("длина шлейфа", "trail length"),
    11: ("номер частицы", "particle id"),
    12: ("поворот (yaw)", "rotation (yaw)"),
    13: ("кадр второго листа", "second sheet sequence"),
    14: ("индекс хитбокса", "hitbox index"),
    15: ("позиция в хитбоксе", "hitbox relative XYZ"),
    16: ("прозрачность 2", "alpha 2"),
    17: ("временный вектор", "scratch vector"),
    18: ("временное число", "scratch float"),
    20: ("наклон (pitch)", "pitch"),
}

_AXIS = {
    0: ("X", "X"),
    1: ("Y", "Y"),
    2: ("Z", "Z"),
}

_ORIENTATION = {
    0: ("к камере", "face the camera"),
    1: ("по скорости в мире", "along world velocity"),
    2: ("в плоскости CP", "in the control point plane"),
    3: ("по оси CP", "aligned to the control point axis"),
}

_COLLISION_MODE = {
    0: ("трассы каждый кадр", "per-frame traces"),
    1: ("кэш трасс", "cached traces"),
    2: ("только точка CP", "control point only"),
    3: ("плоскости из кэша", "cached planes"),
}

_COLLISION_GROUP = {
    "NONE": ("сталкивается со всем", "collides with everything"),
    "DEBRIS": ("как мусор — только мир", "debris: world only"),
    "PROJECTILE": ("как снаряд", "projectile"),
    "ROCKETS": ("как ракета", "rocket"),
}

_SCALE_EMISSION = {
    0: ("не масштабировать", "no scaling"),
    1: ("по числу занятых CP", "by number of used control points"),
    2: ("по числу частиц родителя", "by parent particle count"),
}

#: Атрибуты с фиксированным набором значений: имя → {значение: (ru, en)}.
#: Редактор показывает их списком, а не голым числом.
ENUMS: Dict[str, dict] = {
    "output field": PARTICLE_FIELDS,
    "input field": PARTICLE_FIELDS,
    "oscillation field": PARTICLE_FIELDS,
    "field": PARTICLE_FIELDS,
    "input field 0-2 x/y/z": _AXIS,
    "output field 0-2 x/y/z": _AXIS,
    "emission count scale control point field": _AXIS,
    "orientation_type": _ORIENTATION,
    "collision mode": _COLLISION_MODE,
    "collision group": _COLLISION_GROUP,
    "scale emission to used control points": _SCALE_EMISSION,
}

#: Пояснения к атрибутам: имя → (ru, en). Покрывают верх частотного среза
#: стоковых PCF — то, что пользователь видит в дереве чаще всего.
ATTRS: Dict[str, Tuple[str, str]] = {
    # ── Сама система ──────────────────────────────────────────────────────
    "max_particles": (
        "Потолок одновременно живущих частиц. Пока он забит, эмиттер молчит.",
        "Cap on particles alive at once. While it is full the emitter stalls."),
    "initial_particles": (
        "Сколько частиц система создаёт в момент запуска, помимо эмиттеров.",
        "Particles the system creates at start, on top of its emitters."),
    "material": (
        "VMT-материал частицы. Определяет текстуру, свечение и спрайт-лист.",
        "The particle VMT material: texture, glow and sprite sheet."),
    "radius": (
        "Радиус спрайта в юнитах, если инициализатор размера не задан.",
        "Sprite radius in units when no size initializer is present."),
    "color": (
        "Базовый цвет и прозрачность частиц до модулей цвета.",
        "Base particle color and alpha before any color module."),
    "rotation": (
        "Стартовый поворот спрайта в градусах.",
        "Initial sprite rotation in degrees."),
    "rotation_speed": (
        "Постоянная скорость поворота спрайта, градусов в секунду.",
        "Constant sprite rotation speed, degrees per second."),
    "sequence_number": (
        "Номер последовательности спрайт-листа (кадр анимации).",
        "Sprite sheet sequence number to play."),
    "sequence_number 1": (
        "Номер последовательности во втором спрайт-листе материала.",
        "Sequence number in the material second sprite sheet."),
    # Границы игра считает по самим частицам (CParticleCollection::
    # RecomputeBounds) и лишь РАСШИРЯЕТ на эту коробку — это запас, а не
    # ограничение: маленькая коробка эффект не обрезает.
    "bounding_box_min": (
        "Запас к нижнему углу границ эффекта. Границы игра считает по "
        "частицам, а эту коробку добавляет сверху.",
        "Padding for the lower corner of the effect bounds. The game computes "
        "bounds from the particles and adds this box on top."),
    "bounding_box_max": (
        "Запас к верхнему углу границ эффекта (см. bounding_box_min).",
        "Padding for the upper corner of the effect bounds (see bounding_box_min)."),
    "view model effect": (
        "Эффект рисуется только на вьюмодели (руки от первого лица).",
        "The effect draws on the view model (first-person hands) only."),
    "control point to disable rendering if it is the camera": (
        "Если на этой контрольной точке камера — эффект не рисуется. "
        "-1 отключает проверку.",
        "Hides the effect when the camera sits on this control point. "
        "-1 turns the check off."),
    "maximum time step": (
        "Потолок шага симуляции. Большие шаги ломают физику движения.",
        "Cap on the simulation step. Large steps break the movement physics."),
    "time to sleep when not drawn": (
        "Через сколько секунд вне поля зрения система засыпает.",
        "Seconds off-screen before the system goes to sleep."),
    "maximum draw distance": (
        "Дальше этого расстояния эффект не рисуется.",
        "Beyond this distance the effect is not drawn."),
    "sort particles": (
        "Сортировать частицы по глубине. Выключение ускоряет, но ломает "
        "порядок полупрозрачных спрайтов.",
        "Sort particles by depth. Turning it off is faster but breaks the "
        "order of translucent sprites."),
    "group id": (
        "Группа системы: по ней операторы адресуют дочерние системы.",
        "System group id: operators address child systems by it."),
    "cull_radius": (
        "Радиус, внутри которого одинаковые эффекты схлопываются в один. "
        "0 — не схлопывать.",
        "Radius within which identical effects collapse into one. "
        "0 disables it."),
    # ── Эмиттеры ──────────────────────────────────────────────────────────
    "emission_rate": (
        "Частиц в секунду.",
        "Particles per second."),
    "emission_duration": (
        "Сколько секунд идёт эмиссия. 0 — бесконечно.",
        "How long emission lasts, in seconds. 0 means forever."),
    "emission_start_time": (
        "Задержка перед началом эмиссии, секунды.",
        "Delay before emission starts, in seconds."),
    "num_to_emit": (
        "Сколько частиц выпускается одним залпом.",
        "How many particles a single burst releases."),
    "num_to_emit_minimum": (
        "Нижняя граница залпа при масштабировании. -1 — не ограничивать.",
        "Lower bound of the burst when scaled. -1 means no bound."),
    "maximum emission per frame": (
        "Потолок частиц за кадр: залп растянется на несколько кадров. "
        "-1 — без ограничения.",
        "Cap on particles per frame: a burst spreads over several frames. "
        "-1 means no cap."),
    "emission minimum": (
        "Нижняя граница шумового темпа эмиссии.",
        "Lower bound of the noisy emission rate."),
    "emission maximum": (
        "Верхняя граница шумового темпа эмиссии.",
        "Upper bound of the noisy emission rate."),
    # ── Позиция и движение ────────────────────────────────────────────────
    "control_point_number": (
        "Контрольная точка, от которой считается модуль. 0 — начало эффекта.",
        "Control point the module works from. 0 is the effect origin."),
    "control point number": (
        "Контрольная точка, от которой считается модуль. 0 — начало эффекта.",
        "Control point the module works from. 0 is the effect origin."),
    "distance_min": (
        "Ближняя граница области рождения от контрольной точки.",
        "Near edge of the spawn area, measured from the control point."),
    "distance_max": (
        "Дальняя граница области рождения от контрольной точки.",
        "Far edge of the spawn area, measured from the control point."),
    "distance_bias": (
        "Сплющивание сферы спавна по осям. Ноль по оси даёт плоский диск.",
        "Squashes the spawn sphere per axis. A zero axis gives a flat disc."),
    "distance_bias_absolute_value": (
        "Ненулевая ось складывает сферу в полусферу по этой оси.",
        "A non-zero axis folds the sphere into a hemisphere along it."),
    "bias in local system": (
        "Считать сплющивание в осях контрольной точки, а не мира.",
        "Apply the bias in control point axes instead of world axes."),
    "speed_min": (
        "Нижняя граница стартовой скорости частицы.",
        "Lower bound of the initial particle speed."),
    "speed_max": (
        "Верхняя граница стартовой скорости частицы.",
        "Upper bound of the initial particle speed."),
    "speed_in_local_coordinate_system_min": (
        "Добавка к скорости по осям контрольной точки (вперёд/вбок/вверх).",
        "Extra speed along control point axes (forward/right/up)."),
    "speed_in_local_coordinate_system_max": (
        "Верхняя граница добавки по осям контрольной точки.",
        "Upper bound of the extra speed along control point axes."),
    "gravity": (
        "Постоянное ускорение по осям мира. Z вниз — падение.",
        "Constant acceleration in world axes. Negative Z falls down."),
    "drag": (
        "Торможение средой за 1/30 секунды: 0 — инерция, 1 — мгновенный стоп.",
        "Medium drag per 1/30 s: 0 coasts, 1 stops almost instantly."),
    "maximum velocity": (
        "Потолок скорости частицы, юнитов в секунду.",
        "Cap on particle speed, units per second."),
    "offset min": (
        "Нижняя граница случайного смещения от уже заданной позиции.",
        "Lower bound of the random offset from the position already set."),
    "offset max": (
        "Верхняя граница случайного смещения.",
        "Upper bound of the random offset."),
    "offset in local space 0/1": (
        "Считать смещение в осях контрольной точки.",
        "Apply the offset in control point axes."),
    "offset proportional to radius 0/1": (
        "Умножать смещение на радиус частицы.",
        "Scale the offset by the particle radius."),
    "start_fadeout_min": (
        "Доля жизни, с которой привязка к контрольной точке начинает слабеть.",
        "Life fraction at which the control point lock starts to weaken."),
    "end_fadeout_max": (
        "Доля жизни, к которой привязка к контрольной точке пропадает.",
        "Life fraction by which the control point lock is gone."),
    "distance fade range": (
        "На каком удалении от точки привязка сходит на нет.",
        "Distance from the control point over which the lock fades out."),
    "lock rotation": (
        "Тянуть частицы и за поворотом контрольной точки, не только за позицией.",
        "Follow the control point rotation too, not just its position."),
    # ── Жизнь, цвет, прозрачность ─────────────────────────────────────────
    "lifetime_min": (
        "Нижняя граница времени жизни частицы, секунды.",
        "Lower bound of the particle lifetime, in seconds."),
    "lifetime_max": (
        "Верхняя граница времени жизни частицы, секунды.",
        "Upper bound of the particle lifetime, in seconds."),
    "alpha_min": (
        "Нижняя граница стартовой непрозрачности, 0-255.",
        "Lower bound of the initial opacity, 0-255."),
    "alpha_max": (
        "Верхняя граница стартовой непрозрачности, 0-255.",
        "Upper bound of the initial opacity, 0-255."),
    "color1": (
        "Первый цвет: цвет частицы выбирается между color1 и color2.",
        "First color: each particle picks a color between color1 and color2."),
    "color2": (
        "Второй цвет диапазона (см. color1).",
        "Second color of the range (see color1)."),
    "color_fade": (
        "Цвет, к которому частица приходит к концу жизни.",
        "The color a particle fades to by the end of its life."),
    "fade_start_time": (
        "Доля жизни, с которой начинается переход цвета.",
        "Life fraction at which the color transition starts."),
    "fade_end_time": (
        "Доля жизни, к которой переход цвета закончен.",
        "Life fraction by which the color transition is done."),
    "tint_perc": (
        "Насколько сильно цвет подмешивается от контрольной точки (0-1).",
        "How strongly the control point tint is mixed in (0-1)."),
    "fade in time min": (
        "Нижняя граница длительности проявления.",
        "Lower bound of the fade-in duration."),
    "fade in time max": (
        "Верхняя граница длительности проявления.",
        "Upper bound of the fade-in duration."),
    "fade out time min": (
        "Нижняя граница длительности угасания ПЕРЕД смертью частицы.",
        "Lower bound of the fade-out duration BEFORE the particle dies."),
    "fade out time max": (
        "Верхняя граница длительности угасания перед смертью.",
        "Upper bound of the fade-out duration before death."),
    "proportional 0/1": (
        "Время задано долей жизни частицы (иначе — секундами).",
        "Times are fractions of the particle life (otherwise seconds)."),
    "start_alpha": (
        "Непрозрачность в начале жизни (доля от стартовой).",
        "Opacity at birth, as a fraction of the initial alpha."),
    "end_alpha": (
        "Непрозрачность в конце жизни (доля от стартовой).",
        "Opacity at death, as a fraction of the initial alpha."),
    "start_fade_in_time": (
        "Доля жизни, с которой начинается проявление.",
        "Life fraction at which the fade-in starts."),
    "end_fade_in_time": (
        "Доля жизни, к которой проявление закончено.",
        "Life fraction by which the fade-in is done."),
    "start_fade_out_time": (
        "Доля жизни, с которой начинается угасание.",
        "Life fraction at which the fade-out starts."),
    "end_fade_out_time": (
        "Доля жизни, к которой частица полностью погасла.",
        "Life fraction by which the particle is fully faded."),
    "ease in and out": (
        "Сглаживать начало и конец перехода вместо линейного.",
        "Smooth the start and end of the transition instead of linear."),
    "ease_in_and_out": (
        "Сглаживать начало и конец перехода вместо линейного.",
        "Smooth the start and end of the transition instead of linear."),
    # ── Размер и вращение ─────────────────────────────────────────────────
    "radius_min": (
        "Нижняя граница радиуса частицы при рождении.",
        "Lower bound of the particle radius at birth."),
    "radius_max": (
        "Верхняя граница радиуса частицы при рождении.",
        "Upper bound of the particle radius at birth."),
    "radius_start_scale": (
        "Во сколько раз масштабируется радиус в начале интервала.",
        "Radius multiplier at the start of the interval."),
    "radius_end_scale": (
        "Во сколько раз масштабируется радиус в конце интервала.",
        "Radius multiplier at the end of the interval."),
    "start_time": (
        "Доля жизни, с которой оператор начинает действовать.",
        "Life fraction at which the operator starts acting."),
    "end_time": (
        "Доля жизни, к которой оператор заканчивает действовать.",
        "Life fraction at which the operator stops acting."),
    "scale_bias": (
        "Смещение кривой перехода: <0.5 — быстрее в начале, >0.5 — в конце.",
        "Bias of the transition curve: <0.5 front-loaded, >0.5 back-loaded."),
    "spin_rate_degrees": (
        "Скорость вращения спрайта вокруг оси взгляда, градусов в секунду.",
        "Sprite spin speed around the view axis, degrees per second."),
    "spin_stop_time": (
        "Доля жизни, к которой вращение останавливается. 0 — не тормозить.",
        "Life fraction by which the spin stops. 0 never stops."),
    "rotation_initial": (
        "Базовый угол поворота спрайта, градусы.",
        "Base sprite rotation angle, in degrees."),
    "rotation_offset_min": (
        "Нижняя граница случайной добавки к углу поворота.",
        "Lower bound of the random rotation offset."),
    "rotation_offset_max": (
        "Верхняя граница случайной добавки к углу поворота.",
        "Upper bound of the random rotation offset."),
    "flip percentage": (
        "Доля частиц, у которых спрайт зеркалится по горизонтали (0-1).",
        "Fraction of particles whose sprite is mirrored horizontally (0-1)."),
    # ── Рендеринг ─────────────────────────────────────────────────────────
    "animation rate": (
        "Скорость анимации спрайт-листа: кадров в секунду или циклов в "
        "секунду — зависит от «use animation rate as fps».",
        "Sprite sheet animation speed: frames per second or cycles per "
        "second, depending on 'use animation rate as fps'."),
    "use animation rate as fps": (
        "Считать «animation rate» кадрами в секунду, а не циклами.",
        "Read 'animation rate' as frames per second instead of cycles."),
    "animation_fit_lifetime": (
        "Растянуть весь спрайт-лист ровно на время жизни частицы.",
        "Stretch the whole sprite sheet over the particle lifetime."),
    "orientation_type": (
        "Как развёрнут спрайт в пространстве.",
        "How the sprite is oriented in space."),
    "orientation control point": (
        "Контрольная точка, задающая плоскость спрайта при orientation_type 2/3.",
        "Control point defining the sprite plane for orientation_type 2/3."),
    "forward_angle": (
        "Куда у текстуры «нос»: доворот спрайта по направлению движения на экране.",
        "Where the texture front points: extra turn for on-screen velocity."),
    "min length": (
        "Минимальная длина шлейфа в юнитах.",
        "Minimum trail length in units."),
    "max length": (
        "Максимальная длина шлейфа в юнитах.",
        "Maximum trail length in units."),
    "subdivision_count": (
        "Сколько промежуточных сегментов сглаживают ленту.",
        "How many extra segments smooth the rope."),
    "texel_size": (
        "Размер текселя текстуры вдоль ленты.",
        "Texture texel size along the rope."),
    # ── Remap / шум ───────────────────────────────────────────────────────
    "input field": (
        "Какое поле частицы берётся входом пересчёта.",
        "Which particle field is used as the remap input."),
    "output field": (
        "В какое поле частицы кладётся результат.",
        "Which particle field receives the result."),
    "oscillation field": (
        "Какое поле частицы колеблется.",
        "Which particle field oscillates."),
    "input field 0-2 x/y/z": (
        "Какая координата контрольной точки берётся входом.",
        "Which control point coordinate is used as the input."),
    "output field 0-2 x/y/z": (
        "В какую координату кладётся результат.",
        "Which coordinate receives the result."),
    "input minimum": (
        "Нижняя граница входного диапазона пересчёта.",
        "Lower bound of the remap input range."),
    "input maximum": (
        "Верхняя граница входного диапазона пересчёта.",
        "Upper bound of the remap input range."),
    "output minimum": (
        "Значение поля при минимуме входа.",
        "Field value at the input minimum."),
    "output maximum": (
        "Значение поля при максимуме входа.",
        "Field value at the input maximum."),
    "output is scalar of initial random range": (
        "Умножать результат на исходное значение поля, а не заменять его.",
        "Multiply the field by the result instead of replacing it."),
    "spatial noise coordinate scale": (
        "Масштаб шума по пространству: больше — мельче узор.",
        "Noise scale in space: larger means a finer pattern."),
    "time noise coordinate scale": (
        "Масштаб шума по времени: больше — быстрее меняется.",
        "Noise scale in time: larger means faster change."),
    "absolute value": (
        "Брать модуль шума — узор становится «складчатым».",
        "Take the absolute value of the noise, folding the pattern."),
    "invert absolute value": (
        "Брать 1 минус модуль шума.",
        "Take one minus the absolute value of the noise."),
    # ── Общая часть всех операторов ───────────────────────────────────────
    "operator start fadein": (
        "Секунда жизни ЭФФЕКТА, с которой оператор начинает включаться.",
        "Effect time in seconds at which the operator starts ramping up."),
    "operator end fadein": (
        "Секунда, к которой оператор работает в полную силу.",
        "Effect time by which the operator reaches full strength."),
    "operator start fadeout": (
        "Секунда, с которой оператор начинает выключаться.",
        "Effect time at which the operator starts ramping down."),
    "operator end fadeout": (
        "Секунда, к которой оператор выключен.",
        "Effect time by which the operator is off."),
    "operator fade oscillate": (
        "Период мигания силы оператора между включением и выключением.",
        "Period of oscillation of the operator strength."),
    # ── Столкновения ──────────────────────────────────────────────────────
    "amount of bounce": (
        "Доля скорости, сохраняемая при отскоке от поверхности.",
        "Fraction of speed kept when bouncing off a surface."),
    "amount of slide": (
        "Доля скорости, сохраняемая вдоль поверхности.",
        "Fraction of speed kept along the surface."),
    "kill particle on collision": (
        "Убивать частицу при первом же касании.",
        "Kill the particle on the first contact."),
    "brush only": (
        "Сталкиваться только с геометрией карты, игнорируя модели.",
        "Collide with map brushes only, ignoring models."),
    "collision mode": (
        "Как считаются столкновения: точнее или дешевле.",
        "How collisions are computed: more accurate or cheaper."),
    "collision group": (
        "С чем частица сталкивается.",
        "What the particle collides with."),
    "minimum distance": (
        "Ближе этого расстояния до точки частицу не пускать.",
        "Particles are kept no closer than this to the point."),
    "maximum distance": (
        "Дальше этого расстояния от точки частицу не пускать.",
        "Particles are kept no farther than this from the point."),
    # ── Форсы ─────────────────────────────────────────────────────────────
    "amount of force": (
        "Величина силы. Знак задаёт направление.",
        "Force magnitude. The sign sets the direction."),
    "twist axis": (
        "Ось, вокруг которой закручивается поток частиц.",
        "Axis the particle flow twists around."),
    "output force min": (
        "Нижняя граница случайной силы по осям.",
        "Lower bound of the random force per axis."),
    "output force max": (
        "Верхняя граница случайной силы по осям.",
        "Upper bound of the random force per axis."),
}

#: Что делает модуль: (группа, functionName в нижнем регистре) → (ru, en).
MODULES: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("emitters", "emit_continuously"): (
        "Ровный поток частиц с заданным темпом.",
        "A steady stream of particles at a fixed rate."),
    ("emitters", "emit_instantaneously"): (
        "Один залп частиц в заданный момент.",
        "A single burst of particles at a given moment."),
    ("emitters", "emit noise"): (
        "Поток с темпом, гуляющим по шуму между минимумом и максимумом.",
        "A stream whose rate wanders on noise between min and max."),
    ("initializers", "position within sphere random"): (
        "Рождение в шаре вокруг контрольной точки плюс скорость наружу.",
        "Spawn inside a sphere around the control point, with outward speed."),
    ("initializers", "position within box random"): (
        "Рождение в прямоугольной области вокруг контрольной точки.",
        "Spawn inside a box around the control point."),
    ("initializers", "position modify offset random"): (
        "Сдвигает уже заданную позицию на случайную величину.",
        "Shifts the already assigned position by a random amount."),
    ("initializers", "position from parent particles"): (
        "Рождение на позициях частиц родительской системы.",
        "Spawn at the positions of the parent system particles."),
    ("initializers", "lifetime random"): (
        "Случайное время жизни в заданных пределах.",
        "Random lifetime within the given bounds."),
    ("initializers", "radius random"): (
        "Случайный радиус частицы при рождении.",
        "Random particle radius at birth."),
    ("initializers", "alpha random"): (
        "Случайная стартовая прозрачность.",
        "Random initial opacity."),
    ("initializers", "color random"): (
        "Случайный цвет между двумя заданными.",
        "Random color between the two given ones."),
    ("initializers", "rotation random"): (
        "Случайный стартовый угол поворота спрайта.",
        "Random initial sprite rotation."),
    ("initializers", "sequence random"): (
        "Случайный кадр спрайт-листа при рождении.",
        "Random sprite sheet sequence at birth."),
    ("initializers", "velocity random"): (
        "Случайная стартовая скорость, в том числе по осям точки.",
        "Random initial velocity, optionally in control point axes."),
    ("initializers", "velocity noise"): (
        "Стартовая скорость из шумового поля — вихри и разнобой.",
        "Initial velocity from a noise field: swirls and variety."),
    ("initializers", "trail length random"): (
        "Случайная длина шлейфа (для render_sprite_trail).",
        "Random trail length (for render_sprite_trail)."),
    ("initializers", "remap initial scalar"): (
        "Пересчитывает одно поле частицы в другое один раз при рождении.",
        "Remaps one particle field into another once at birth."),
    ("operators", "movement basic"): (
        "Физика движения: гравитация, сопротивление, все силы.",
        "Movement physics: gravity, drag and every force."),
    ("operators", "lifespan decay"): (
        "Убивает частицу, когда её время вышло. Без него частицы вечные.",
        "Kills a particle when its time is up. Without it they never die."),
    ("operators", "radius scale"): (
        "Меняет радиус за жизнь частицы: рост или усадка.",
        "Scales the radius over the particle life: growth or shrink."),
    ("operators", "color fade"): (
        "Переводит цвет частицы к заданному за её жизнь.",
        "Fades the particle color to a target over its life."),
    ("operators", "alpha fade in random"): (
        "Плавное проявление в начале жизни.",
        "Smooth fade-in at the start of the life."),
    ("operators", "alpha fade out random"): (
        "Плавное угасание перед смертью.",
        "Smooth fade-out before death."),
    ("operators", "alpha fade and decay"): (
        "Проявление, угасание и смерть частицы одним оператором.",
        "Fade-in, fade-out and death in a single operator."),
    ("operators", "movement lock to control point"): (
        "Тянет частицы за контрольной точкой; привязка слабеет с возрастом.",
        "Drags particles after the control point; the lock weakens with age."),
    ("operators", "movement rotate particle around axis"): (
        "Крутит частицы вокруг оси, проходящей через контрольную точку.",
        "Spins particles around an axis through the control point."),
    ("operators", "movement max velocity"): (
        "Ограничивает скорость частиц сверху.",
        "Caps the particle speed."),
    ("operators", "rotation basic"): (
        "Крутит спрайт с его собственной скоростью вращения.",
        "Spins the sprite at its own rotation speed."),
    ("operators", "rotation spin roll"): (
        "Постоянное вращение спрайта вокруг оси взгляда.",
        "Constant sprite spin around the view axis."),
    ("operators", "rotation spin yaw"): (
        "Постоянное вращение спрайта по рысканью.",
        "Constant sprite spin in yaw."),
    ("operators", "oscillate scalar"): (
        "Колеблет одно числовое поле частицы (радиус, альфу, угол).",
        "Oscillates one scalar particle field (radius, alpha, angle)."),
    ("operators", "oscillate vector"): (
        "Колеблет векторное поле — обычно позицию: трепет, дрожание.",
        "Oscillates a vector field, usually position: flutter and jitter."),
    ("operators", "set child control points from particle positions"): (
        "Ставит контрольные точки дочерних систем на позиции своих частиц.",
        "Places child system control points at its own particle positions."),
    ("forces", "random force"): (
        "Случайный толчок по осям каждый кадр.",
        "A random push along the axes every frame."),
    ("forces", "pull towards control point"): (
        "Притягивает или отталкивает частицы от точки.",
        "Pulls particles toward a point, or pushes them away."),
    ("forces", "twist around axis"): (
        "Закручивает частицы вокруг оси — воронка.",
        "Twists particles around an axis: a vortex."),
    ("constraints", "collision via traces"): (
        "Столкновения с миром: отскок, скольжение или смерть.",
        "World collisions: bounce, slide or die."),
    ("constraints", "constrain distance to control point"): (
        "Держит частицы в кольце заданных расстояний от точки.",
        "Keeps particles within a distance ring around the point."),
    ("renderers", "render_animated_sprites"): (
        "Обычный рендер частиц спрайтами с анимацией спрайт-листа.",
        "The usual particle renderer: sprites with sheet animation."),
    ("renderers", "render_sprite_trail"): (
        "Рисует частицы вытянутыми по движению — искры, капли.",
        "Draws particles stretched along their motion: sparks, drops."),
    ("renderers", "render_rope"): (
        "Соединяет частицы лентой — лучи, струи, кровь.",
        "Connects particles with a rope: beams, jets, blood."),
    ("renderers", "render_screen_velocity_rotate"): (
        "Доворачивает спрайт по направлению движения НА ЭКРАНЕ.",
        "Turns the sprite to face its ON-SCREEN direction of travel."),
}

_LANGS = {"ru": 0, "en": 1}


def _pick(pair: Optional[Tuple[str, str]], lang: str) -> Optional[str]:
    return None if pair is None else pair[_LANGS.get(lang, 1)]


def attr_help(attr_name: str, lang: str = "en") -> Optional[str]:
    """Пояснение к атрибуту либо None, если его нет в справочнике."""
    return _pick(ATTRS.get((attr_name or "").strip().lower()), lang)


def module_help(group: str, function_name: str,
                lang: str = "en") -> Optional[str]:
    """Пояснение к модулю либо None."""
    key = ((group or "").strip().lower(),
           (function_name or "").strip().lower())
    return _pick(MODULES.get(key), lang)


def enum_values(attr_name: str) -> Optional[dict]:
    """Набор значений атрибута-перечисления либо None."""
    return ENUMS.get((attr_name or "").strip().lower())


def enum_label(attr_name: str, value, lang: str = "en") -> Optional[str]:
    """Подпись значения перечисления («альфа» для output field = 7)."""
    values = enum_values(attr_name)
    if not values:
        return None
    if isinstance(value, bool):     # bool — не перечисление, хоть и int
        return None
    return _pick(values.get(value), lang)
