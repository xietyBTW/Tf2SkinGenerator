"""
Прикладной API для представления.

То, что вызывает фронт: список категорий, список предметов, запуск загрузки
превью. Транспорта здесь нет — это обычные функции и обычные значения. Мост
(pywebview, dev-сервер, что угодно ещё) только перекладывает вызовы сюда и
сериализует результат.

Почему без транспорта: хост ещё не выбран окончательно, а правила выбора
предмета и режима меняться от способа доставки не должны. Плюс так их можно
проверить без окна и без браузера.

Правила режима повторяют приложение: режим следует из категории и подтипа
(см. frontend/CONTROLS.md), а от режима зависит, какие контролы показывать.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Ключи категорий в том же порядке, что в MainWindow._category_keys.
CATEGORY_KEYS = ('weapon', 'character', 'special', 'projectile',
                 'pickup', 'taunt', 'skybox', 'custom')

#: Категория → режим сборки по умолчанию. Подтип может его уточнить
#: (персонаж: тело/руки/маски; специальное: спрей/critHIT).
_CATEGORY_MODE = {
    'weapon': 'normal',
    'character': 'body',
    'special': 'spray',
    'projectile': 'normal',
    'pickup': 'normal',
    'taunt': 'normal',
    'skybox': 'skybox',
    # Загруженный мод — режим 'custom' (так его называет
    # MainWindow.apply_selection_auto). Имя должно совпадать: по нему
    # закрывается редактор VMT и решается, что показывать.
    'custom': 'custom',
}


def _lang(lang: str = '') -> str:
    """
    Язык ответа: тот, что назвали, иначе — из настроек.

    Раньше умолчанием стояло 'ru', и страница его ни разу не переопределяла:
    настройка «Язык приложения» писалась в конфиг и не значила ничего.
    Спрашивать конфиг здесь, а не на странице, потому что отвечает на языке
    Python: знать о выборе должен один, и это он.
    """
    if lang:
        return lang
    from src.config.app_config import AppConfig
    return AppConfig.load_config().get('language') or 'en'


def _t(lang: str) -> dict:
    from src.data.translations import TRANSLATIONS
    return TRANSLATIONS.get(lang, TRANSLATIONS['en'])


def categories(lang: str = '') -> List[dict]:
    """Верхний уровень выбора: что вообще меняем."""
    lang = _lang(lang)
    t = _t(lang)
    return [{'key': k, 'name': t.get(f'category_{k}', k)} for k in CATEGORY_KEYS]


def classes(lang: str = '') -> List[dict]:
    """Классы TF2. Ключ — он же имя в данных, отдельного перевода у них нет."""
    from src.data.weapons import TF2_WEAPONS
    return [{'key': k, 'name': k} for k in TF2_WEAPONS]


def weapon_types(tf2_class: Optional[str] = None, lang: str = '') -> List[dict]:
    """
    Типы оружия, по которым можно фильтровать.

    С классом — только те, что у него ЕСТЬ: часы есть у шпиона, КПК у инженера,
    и показывать всем полный перечень значило бы обещать пустые списки.

    Без класса — все слоты, у которых хоть у кого-то есть оружие. Тип должен
    работать сам по себе: выбрать «Ближний бой» по всем классам — нормальное
    желание, и требовать сперва выбрать класс незачем.
    """
    from src.data.weapons import (
        TF2_WEAPONS, WEAPON_SLOT_TYPES, get_weapon_type_name,
    )

    lang = _lang(lang)
    if tf2_class:
        have = TF2_WEAPONS.get(tf2_class, {})
        keys = [k for k in WEAPON_SLOT_TYPES if have.get(k)]
    else:
        keys = [k for k in WEAPON_SLOT_TYPES
                if any(cls.get(k) for cls in TF2_WEAPONS.values())]
    return [{'key': k, 'name': get_weapon_type_name(k, lang)} for k in keys]


def _weapon_items(tf2_class: Optional[str], weapon_type: Optional[str],
                  lang: str) -> List[dict]:
    from src.data.weapons import TF2_WEAPONS, WEAPON_SLOT_TYPES, get_weapon_name

    out: List[dict] = []
    class_names = [tf2_class] if tf2_class else list(TF2_WEAPONS)
    type_names = [weapon_type] if weapon_type else WEAPON_SLOT_TYPES

    for cls in class_names:
        slots = TF2_WEAPONS.get(cls, {})
        for slot in type_names:
            for key in slots.get(slot, {}):
                out.append({
                    'key': key,
                    'name': get_weapon_name(cls, slot, key, lang),
                    'cls': cls,
                    'type': slot,
                    # Режим у оружия — «класс_ключ» (scout_c_scattergun), как
                    # его строит MainWindow.apply_selection_auto. Просто ключ
                    # не подойдёт: weapon_key_from_mode отрежет первый сегмент
                    # и модель искалась бы по «scattergun».
                    'mode': f'{cls.lower()}_{key}',
                })
    return out


def _character_items(tf2_class: Optional[str], lang: str) -> List[dict]:
    """Тело и руки класса. Ключ режима строится как в приложении: класс_часть."""
    from src.data.weapons import TF2_WEAPONS, get_character_parts
    from src.domain.preview.model_key import model_key_for

    out: List[dict] = []
    for cls in ([tf2_class] if tf2_class else list(TF2_WEAPONS)):
        for key, name in get_character_parts(cls, lang):
            mode = f'{cls.lower()}_{key}'
            out.append({
                'key': key,
                'name': name,
                'cls': cls,
                'type': 'character',
                'mode': mode,
                # Обложка — текстура той же модели, что грузится в превью: ни
                # тела, ни рук в рюкзаке нет.
                'icon': model_key_for(mode) or '',
            })
    return out


def _search(rows: List[dict], query: str) -> List[dict]:
    """
    Отбор по строке поиска — тем же правилом, что у косметики.

    Слова, а не подстрока целиком: «обрез мал» обязано находить «Обрез
    Малыша», порядок слов человек помнить не должен. Ищем и по имени файла с
    классом: поле подписано «Название или файл», а классом удобно сузить
    список, когда фильтр стоит на «Все».
    """
    words = [w for w in str(query or '').lower().split() if w]
    if not words:
        return rows

    def haystack(row: dict) -> str:
        return ' '.join(str(row.get(field, '') or '').lower()
                        for field in ('name', 'key', 'label', 'cls'))

    return [row for row in rows if all(w in haystack(row) for w in words)]


def items(category: str = 'weapon', tf2_class: Optional[str] = None,
          weapon_type: Optional[str] = None, lang: str = '',
          query: str = '') -> List[dict]:
    """
    Предметы категории — то, из чего выбирают в каталоге.

    Пустые ``tf2_class`` / ``weapon_type`` означают «все»: каталог показывает
    полный список, пока фильтры не сузили его.

    ``query`` — строка поиска. Раньше её принимала только косметика, и поле над
    списком оружия не делало ничего.
    """
    lang = _lang(lang)
    t = _t(lang)

    if category == 'weapon':
        return _search(_weapon_items(tf2_class, weapon_type, lang), query)
    if category == 'character':
        return _search(_character_items(tf2_class, lang), query)
    if category == 'special':
        from src.data.weapons import SPECIAL_MODES
        # Подписи те же, что в приложении: ключ режима человеку ничего не
        # говорит («death_ice» вместо «Эффект смерти: Лёд»).
        labels = {'critHIT': 'special_crit', 'spray': 'special_spray',
                  'death_ice': 'special_death_ice',
                  'death_gold': 'special_death_gold',
                  'death_fire': 'special_death_fire'}
        return _search([{'key': m, 'name': t.get(labels.get(m, ''), m),
                         'cls': '', 'type': 'special', 'mode': m}
                        for m in SPECIAL_MODES], query)
    if category == 'skybox':
        from src.data.skyboxes import SKYBOX_MODE, STOCK_SKY_NAMES
        # Обложка — боковая грань самого неба: иконки в рюкзаке у него нет и
        # быть не может, а узнают небо по горизонту.
        return _search([{'key': n, 'name': n, 'cls': '', 'type': 'skybox',
                         'mode': SKYBOX_MODE, 'sky': n, 'icon': f'skybox/{n}'}
                        for n in STOCK_SKY_NAMES], query)

    # Снаряды, пикапы и реквизит насмешек устроены одинаково: таблица
    # {ключ: {ru, en, mdl_path}} плюс префикс режима. Реестр общий с
    # приложением — новая такая категория подключится сама.
    from src.data.simple_models import SIMPLE_MODEL_CATEGORIES, model_display_name
    from src.data.taunt_catalog import ensure as _ensure_taunts
    # Насмешек в игре вчетверо больше, чем в выверенной руками таблице;
    # остальные берутся из items_game при первом показе каталога.
    _ensure_taunts()
    simple = SIMPLE_MODEL_CATEGORIES.get(category)
    if simple:
        return _search([{'key': key,
                         'name': model_display_name(simple.table, key, lang),
                         'cls': '', 'type': category,
                         # Режим у них — «префикс + ключ» (pickup_medkit_small):
                         # по нему дальше находится MDL, и ключ не годится.
                         'mode': f'{simple.mode_prefix}{key}',
                         # Обложка — текстура самой модели: аптечки, патроны и
                         # снаряды это мировые объекты, в рюкзаке их нет, и
                         # карточки стояли пустыми. У насмешек иконка всё же
                         # есть — сам предмет-насмешка лежит в инвентаре.
                         'icon': (simple.table[key].get('icon')
                                  or simple.table[key].get('mdl_path', ''))}
                        for key in simple.table], query)

    # Кастомный мод — не список: предмет здесь файл, его выбирают в каталоге.
    if category != 'custom':
        logger.debug(f"api.items: категория {category!r} ещё не подключена")
    return []


def mode_for(category: str, subtype: Optional[str] = None) -> str:
    """
    Режим сборки по выбору в каталоге.

    Подтип уточняет категорию там, где её мало: у персонажа это тело, руки или
    маски шпиона, у специального — спрей или critHIT. От режима зависит, какие
    контролы показывать, поэтому правило держим в одном месте.
    """
    if subtype:
        return subtype
    return _CATEGORY_MODE.get(category, 'normal')


# ═══════════════════════════════════════════════════════════════════════════ #
# Что показывать при этом режиме
# ═══════════════════════════════════════════════════════════════════════════ #

def controls_for(mode: str) -> Dict[str, object]:
    """
    Видимость и доступность контролов для режима сборки.

    Условия те же, что в ``settings_panel.apply_mode_restrictions`` и
    ``preview_panel._update_*_visibility`` — матрица выписана в
    frontend/CONTROLS.md. Считает их Python, а не представление: правило одно,
    и при замене интерфейса оно не переписывается заново.

    Часть ответов зависит не только от режима, но и от загруженной модели
    (есть ли BLU-вариант, австралий, служебные материалы). Такие ключи здесь
    не выдумываются — их проставит контроллер превью, когда модель приедет.
    """
    from src.data.player_characters import PLAYER_BODY_MODE_KEYS, SPY_MASK_MODE_KEY
    from src.data.item_kinds import kind_of
    from src.data.player_hands import HAND_MODE_KEYS
    from src.data.skyboxes import SKYBOX_MODE
    from src.domain.format_choices import (
        allowed_flags_for_mode, allowed_formats_for_mode,
    )

    from src.data.weapons import VTF_ONLY_SPECIAL_MODES

    is_spray = mode == 'spray'
    # Эффекты смерти показываются ТОЙ ЖЕ сценой, что и крит (персонаж плюс
    # текстура), и в приложении их накрывает один флаг `_crithit_mode`. Значит
    # и правила показа у них общие: модель подменять нечем, стилей нет.
    is_crit = mode == 'critHIT' or (bool(mode) and mode in VTF_ONLY_SPECIAL_MODES)
    is_skybox = mode == SKYBOX_MODE
    is_hands = bool(mode) and mode in HAND_MODE_KEYS
    is_body = bool(mode) and mode in PLAYER_BODY_MODE_KEYS
    is_spy_mask = mode == SPY_MASK_MODE_KEY
    is_normal = bool(mode) and not (is_spray or is_crit or is_skybox
                                    or is_hands or is_body)

    # «Модельные» режимы: geometry идёт через декомпиляцию, материал —
    # VertexLitGeneric. От этого зависят Normal Map, карты и инструменты.
    model_like = is_normal or is_hands or is_body

    allowed_flags = allowed_flags_for_mode(mode)

    return {
        'mode': mode,
        # ── Панель сборки ───────────────────────────────────────────────── #
        'resolutions': ['256'] if is_spray else ['256', '512', '1024', '2048'],
        'formats': allowed_formats_for_mode(mode),      # None → полный список
        'format_locked': is_spray,
        'flags': allowed_flags,                          # None → весь набор
        'flags_enabled': not (is_spray or is_crit),
        'gamma': allowed_flags is None,
        'normal_map': model_like and not is_crit,
        'material_maps': model_like and not is_crit,
        'shoulders': is_hands,
        # Краски из игры — только у шапок: они красятся командным цветом через
        # VMT, и у оружия такой краски нет.
        'hat_paints': mode == 'hat',
        # ── Инструменты ─────────────────────────────────────────────────── #
        'extract_model': model_like,
        'extract_texture': model_like,
        # ── Превью ──────────────────────────────────────────────────────── #
        # Модель подменять можно только там, где она есть: у спрея, крита и
        # эффектов смерти её нет вовсе, у неба — грани вместо неё.
        'load_model': not (is_crit or is_skybox or is_spray),
        'replace_model': not (is_crit or is_skybox or is_spray or is_body),
        'first_person': is_normal and kind_of(mode).is_weapon,
        # Насмешка: персонаж играет тонт с реквизитом. Есть только у самого
        # реквизита — у оружия своего тонта нет, а у шапки нет и реквизита.
        'taunt': mode.startswith('taunt_'),
        'misc': not (is_hands or is_spy_mask),
        'styles': not (is_spray or is_crit or is_skybox),
        # Команды и вариант зависят от загруженной модели, не от режима:
        # маски шпиона прячут их безусловно, остальное решает контроллер.
        'teams': not is_spy_mask,
    }


# ═══════════════════════════════════════════════════════════════════════════ #
# Действия над сеансом
# ═══════════════════════════════════════════════════════════════════════════ #

def tf2_paths() -> Dict[str, object]:
    """Где лежит игра. Ошибку отдаём текстом — её показывает страница."""
    from src.app.session import session
    return session().tf2_paths()


def load_preview(mode: str, lang: str = '',  # noqa: PLR0913 — зеркало сеанса
                 model_key: Optional[str] = None,
                 per_class: Optional[Dict[str, str]] = None,
                 style: Optional[int] = None,
                 restore: bool = False) -> Dict[str, object]:
    """Начинает загрузку 3D-превью. Модель приезжает событиями, не ответом.

    restore — открыть с сохранённой работой. Из каталога предмет открывается
    игровым; работы живут своим списком (`works`).
    """
    from src.app.session import session

    lang = _lang(lang)
    return session().load_preview(mode, lang=lang, model_key=model_key,
                                  per_class=per_class, style=style,
                                  restore=restore)


def icon_png(key: str) -> Optional[bytes]:
    """
    PNG обложки предмета, либо None.

    Ключ — то, что каталог знает о предмете: ``icon`` из items_game, ключ
    оружия, путь к модели или `skybox/<имя>`.

    Источников два, и порядок важен. Сначала рюкзак: это готовая иконка на
    прозрачном фоне, ровно та, что игрок видит в инвентаре. Но она есть только
    у предметов инвентаря — у аптечек, патронов, снарядов, реквизита насмешек,
    тел, рук и неба её нет и не будет, и карточки стояли пустыми. Для них
    берём текстуру самой модели (у неба — грань), см. `model_icons`.
    """
    from src.app.session import session
    from src.services import model_icons
    from src.services.backpack_icons import png_bytes

    paths = session().tf2_paths()
    if 'error' in paths:
        return None

    key = (key or '').replace('\\', '/').strip()
    if key.lower().startswith('skybox/'):
        return model_icons.sky_png(key[len('skybox/'):], paths['textures_vpk'])

    icon = png_bytes(key, paths['textures_vpk'])
    if icon is not None:
        return icon

    from src.data.weapons import WEAPON_MDL_PATHS
    mdl = key if key.lower().endswith('.mdl') else WEAPON_MDL_PATHS.get(key, '')
    if not mdl:
        return None
    return model_icons.model_png(mdl, paths['misc_vpk'], paths['textures_vpk'])


def load_taunt(tf2_class: str = '', lang: str = '') -> Dict[str, object]:
    """Собирает сцену насмешки: персонаж играет тонт с этим реквизитом."""
    from src.app.session import session

    lang = _lang(lang)
    return session().load_taunt(tf2_class, lang=lang)


def stop_preview() -> Dict[str, object]:
    from src.app.session import session
    return session().stop_preview()


def view_state() -> Dict[str, object]:
    """Что показывать сейчас: текстуры, команда, доступные варианты."""
    from src.app.session import session
    return session().view_state()


def set_team(team: str) -> Dict[str, object]:
    from src.app.session import session
    return session().set_team(team)


def set_australium(active: bool) -> Dict[str, object]:
    from src.app.session import session
    return session().set_australium(active)


def toggle_misc(on: Optional[bool] = None) -> Dict[str, object]:
    """Переключает просмотр служебных материалов («Прочее»)."""
    from src.app.session import session
    return session().toggle_misc(on)


def force_team() -> Dict[str, object]:
    """Включает «сделать командным»: сборка синтезирует BLU-строку."""
    from src.app.session import session
    return session().force_team()


def set_skin(index: int) -> Dict[str, object]:
    """Переключает вариантный стиль модели."""
    from src.app.session import session
    return session().set_skin(index)


def set_part_detail(material: str = '', detail: float = 0.0) -> Dict[str, object]:
    """Раздробить все куски одинаково (0 — геометрия, 1 — швы развёртки)."""
    from src.app.session import session
    return session().set_part_detail(material, detail)


def toggle_part_island(material: str = '', group: int = 0,
                       island: int = 0) -> Dict[str, object]:
    """Отрезать названный остров развёртки или прирастить его обратно."""
    from src.app.session import session
    return session().toggle_part_island(material, group, island)


def part_mask(material: str = '', part: int = 0) -> Dict[str, object]:
    """Картинка-подсветка части: её форма на развёртке."""
    from src.app.session import session
    return session().part_mask(material, part)


def part_shape(material: str = '', part: int = 0) -> Dict[str, object]:
    """Развёртка одной части — для окна посадки картинки."""
    from src.app.session import session
    return session().part_shape(material, part)


def merge_part_islands(material: str = '', group: int = 0,
                       islands: Optional[List[int]] = None) -> Dict[str, object]:
    """Свести отрезки в один: их острова становятся одной частью."""
    from src.app.session import session
    return session().merge_part_islands(material, group, islands)


def leave_first_person() -> Dict[str, object]:
    """Возврат из вида от первого лица: снимает сцену рук."""
    from src.app.session import session
    return session().leave_first_person()


def load_first_person(action: str = 'IDLE', lang: str = '',
                      full: bool = False) -> Dict[str, object]:
    """Собирает сцену «руки класса с оружием».

    full — собрать целиком, даже если сцена уже в кадре: обычная смена
    анимации обходится одними дорожками.
    """
    from src.app.session import session

    lang = _lang(lang)
    return session().load_first_person(action, lang=lang, full=full)


def load_skybox(sky_name: str) -> Dict[str, object]:
    """Готовит грани стокового неба."""
    from src.app.session import session
    return session().load_skybox(sky_name)


def set_texture(material: str, path: Optional[str] = None) -> Dict[str, object]:
    """Кладёт пользовательскую текстуру на материал (path=None — снимает)."""
    from src.app.session import session
    return session().set_texture(material, path)


def build(params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Собирает VPK. Прогресс и результат приходят событиями."""
    from src.app.session import session
    return session().build(dict(params or {}))


def vtf_estimate(size: int = 512, format: str = 'DXT5',
                 flags: Optional[List[str]] = None) -> Dict[str, object]:
    """Сколько примерно займёт VTF при этих настройках.

    Оценка, а не измерение: считать по-настоящему значит прогнать кодировщик,
    а число нужно на каждое движение переключателя. Единственное в сводке, что
    нельзя увидеть глазами: 2048 DXT5 весит 5.3 МБ, а 1024 DXT5 — 1.3 МБ, и
    это решает, влезет мод в раздачу или нет.
    """
    from src.services.vtf_size import human_size, vtf_bytes

    side = max(1, int(size or 512))
    total = vtf_bytes(side, side, str(format or 'DXT5'), flags or ())
    return {'bytes': total, 'text': human_size(total)}


def cancel_build() -> Dict[str, object]:
    """Просит идущую сборку остановиться."""
    from src.app.session import session
    return session().cancel_build()


def material_map_schema(lang: str = '') -> Dict[str, object]:
    """Какие карты материала бывают и что у них настраивается."""
    from src.data.material_maps import MAP_DISPLAY_ORDER, MATERIAL_MAPS

    lang = _lang(lang)
    t = _t(lang)

    def numeric_fields(cfg: dict) -> List[dict]:
        out = []
        for param in cfg.get('numeric', ()):
            field = {
                'param': param,
                'label': t.get('map_' + param.lstrip('$').lower(), param.lstrip('$')),
                'default': str(cfg.get('extra_vmt', {}).get(param, '')),
                'choices': None,
            }
            # Режим смешивания detail — не число, а три именованных варианта.
            if param == '$detailblendmode':
                field['choices'] = [
                    {'value': '1', 'label': t.get('map_blend_additive', 'Additive')},
                    {'value': '7', 'label': t.get('map_blend_multiply', 'Multiply')},
                    {'value': '5', 'label': t.get('map_blend_overlay', 'Overlay')},
                ]
            out.append(field)
        return out

    return {
        'title': t.get('material_maps_title', 'Material Maps'),
        'intro': t.get('material_maps_intro', ''),
        'auto_label': t.get('map_auto', 'Auto from texture (no file)'),
        'auto_tip': t.get('map_auto_tip', ''),
        'threshold_label': t.get('map_threshold', 'Threshold'),
        'maps': [
            {
                'id': map_id,
                'title': t.get(f'map_{map_id}', map_id.capitalize()),
                'tip': t.get(f'map_{map_id}_tip', ''),
                'badge': MATERIAL_MAPS[map_id]['format'],
                'vmt_only': bool(MATERIAL_MAPS[map_id].get('vmt_only')),
                'derive': bool(MATERIAL_MAPS[map_id].get('derive_kind')),
                'numeric': numeric_fields(MATERIAL_MAPS[map_id]),
            }
            for map_id in MAP_DISPLAY_ORDER
        ],
    }


def texture_maps(material: str = '') -> Dict[str, object]:
    """Карты, назначенные материалу."""
    from src.app.session import session
    return session().texture_maps(material)


def set_texture_maps(material: str = '',
                     maps: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Записывает карты материала (пустой набор — снять)."""
    from src.app.session import session
    return session().set_texture_maps(material, maps)


def works(lang: str = '') -> List[dict]:
    """
    Сохранённые работы — списком, как предметы каталога.

    Раньше работа возвращалась молча при открытии предмета: каталог показывал
    «Обрез», а на экране был ТВОЙ обрез, и вернуться к игровому можно было
    только через «Забыть правки». Теперь список оружия показывает игру, а свои
    работы открываются отсюда — осознанно.

    Имя и обложку берём по опознанию, записанному в самой работе: показывать
    человеку `scout_c_scattergun__c_scattergun` незачем.
    """
    from src.services import work_store

    lang = _lang(lang)
    return [{
        **row,
        'type': 'work',
        # Обложка — иконка предмета: без неё все работы выглядят одинаково.
        # У косметики это объявленная иконка, у оружия — ключ модели: слаг из
        # имени папки не годился ни там, ни там.
        'icon': row['item_icon'] or row['item_key'] or row['work_item'],
        # Открывается как обычный предмет, только с восстановлением.
        'mode': row['work_mode'],
    } for row in _named(work_store.list_saved(), lang)]


def _named(rows: List[dict], lang: str) -> List[dict]:
    """
    Работы с человеческим именем предмета и тем, из чего они открываются.

    Опознание пишется в саму работу (`work_store.item_of`). Работы, записанные
    до этого, его не имеют — для них остаётся разбор имени папки: у оружия он
    даёт верный ключ, у шапки — слаг пути к модели.
    """
    hats = _hat_index(lang) if any(
        (r.get('item') or {}).get('mode') == 'hat' for r in rows) else {}

    out: List[dict] = []
    for row in rows:
        item = row.get('item') or {}
        mode, _, slug = str(row['key']).partition('__')
        mode = item.get('mode') or mode
        key = item.get('key') or ''
        name, icon = hats.get(key.lower(), ('', ''))
        out.append({**row,
                    'work_mode': mode,
                    'work_item': slug,
                    # Ключ модели и покласcовые модели: без них шапка не
                    # открывается — из режима «hat» её путь не вывести.
                    'item_key': key,
                    'per_class': dict(item.get('per_class') or {}),
                    'mod': item.get('mod') or '',
                    # Иконка косметики объявлена в items_game: по имени модели
                    # её не найти — у покласcовой шапки оно с суффиксом класса
                    # (`all_domination_scout`), а иконка одна на предмет.
                    'item_icon': icon,
                    'name': (name
                             or _work_title(mode, key.lower() or slug, lang))})
    return out


def _hat_index(lang: str) -> Dict[str, tuple]:
    """
    Косметика по пути к модели: (имя, иконка из items_game).

    Собирается один раз на список: косметики 9504, и спрашивать каталог на
    каждую работу значило бы разбирать items_game по разу на карточку.

    Путей у предмета несколько. В работе лежит тот, что показывали: у
    мультиклассовой шапки это модель КЛАССА, у стиля — модель стиля, и ни та,
    ни другая не равна основной (`all_domination_%s.mdl`). Поэтому в указателе
    все, а основная кладётся последней — при совпадении верна она.
    """
    from src.app.session import session
    from src.data.hats_parser import parse_hats

    paths = session().tf2_paths()
    if 'error' in paths:
        return {}

    index: Dict[str, tuple] = {}
    for hat in parse_hats(paths['root'], lang):
        entry = (hat.name, hat.icon)
        for style in hat.styles or ():
            for path in (style.get('per_class_models') or {}).values():
                index[str(path).lower()] = entry
        for path in (hat.per_class_models or {}).values():
            index[str(path).lower()] = entry
        index[hat.mdl_path.lower()] = entry
    return index


def drafts(lang: str = '') -> List[dict]:
    """
    Черновики автосохранения — для уборки.

    В библиотеке их нет намеренно: оно пишет всё, к чему прикоснулись, и
    «просто открыл предмет» становилось модом. Но копии текстур при этом
    остаются на диске, и добраться до них можно было только заново открыв тот
    же предмет — то есть на практике никак. Размер отдаём рядом: «удалить 12
    черновиков» и «удалить 12 черновиков на 280 МБ» — разные решения.
    """
    from src.services import work_store

    lang = _lang(lang)
    return [{**row, 'size': work_store.size_of(row['key'])}
            for row in _named(work_store.list_drafts(), lang)]


def forget_drafts(keys: Optional[List[str]] = None) -> Dict[str, object]:
    """Удаляет черновики (пустой список — все). Сохранённые работы не трогает."""
    from src.app.session import session
    return session().forget_drafts(keys)


def _work_title(mode: str, item: str, lang: str) -> str:
    """Человеческое имя предмета работы; не нашли — показываем ключ.

    Ищем по тому же каталогу, что и список оружия: у работы своего имени нет,
    а показывать `scout_c_scattergun__c_scattergun` человеку незачем.

    Косметику здесь не ищем — она приходит из items_game, и для списка её имена
    собирает `_hat_titles` один раз. Сюда шапка попадает, только когда предмет
    в игре не нашёлся: тогда имя файла модели честнее полного пути.
    """
    from src.data.weapons import TF2_WEAPONS

    for groups in TF2_WEAPONS.values():
        for weapons in groups.values():
            for key, names in weapons.items():
                if key.lower() == item:
                    return names.get(lang) or names.get('en') or key
    if item.endswith('.mdl'):
        return _model_file_name(item)
    return item or mode


def work_state() -> Dict[str, object]:
    """Есть ли у предмета правки и сохраняются ли они молча."""
    from src.app.session import session
    return session().work_state()


def keep_work() -> Dict[str, object]:
    """Сохраняет работу над предметом в библиотеку — по нажатию, не молча."""
    from src.app.session import session
    return session().keep_work()


def restore_work() -> Dict[str, object]:
    """Возвращает отложенную работу над открытым сейчас предметом."""
    from src.app.session import session
    return session().restore_work()


def forget_work() -> Dict[str, object]:
    """Сбрасывает правки предмета — и в сеансе, и на диске."""
    from src.app.session import session
    return session().forget_work()


def add_to_style(material: str = '') -> Dict[str, object]:
    """Добавляет материал в активный вариантный стиль."""
    from src.app.session import session
    return session().add_to_style(material)


def drop_from_style(material: str = '') -> Dict[str, object]:
    """Убирает материал из стиля — он вернётся к базовой текстуре."""
    from src.app.session import session
    return session().drop_from_style(material)


def texture_settings(material: str = '') -> Dict[str, object]:
    """Свои настройки сборки у материала."""
    from src.app.session import session
    return session().texture_settings(material)


def set_texture_settings(material: str = '',
                         settings: Optional[Dict[str, object]] = None
                         ) -> Dict[str, object]:
    """Задаёт материалу свои настройки (пустые — вернуть глобальные)."""
    from src.app.session import session
    return session().set_texture_settings(material, settings)


def texture_badges() -> Dict[str, object]:
    """У каких материалов свои настройки — для пометок на карточках."""
    from src.app.session import session
    return session().texture_badges()


def parts(material: str = '', known_shape: str = '') -> Dict[str, object]:
    """Части модели: список кусков и номер части для каждого треугольника.

    ``known_shape`` — отпечаток разбиения, который уже есть у страницы. Совпал —
    карты треугольников не отдаются: они занимают почти весь ответ, а меняются
    только от резки.
    """
    from src.app.session import session
    return session().parts(material, known_shape)


def set_part_texture(material: str = '', part: int = 0,
                     path: Optional[str] = None,
                     options: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Кладёт картинку на одну часть модели (path=None — убирает).

    options — посадка: вписать/заполнить/растянуть, поворот, масштаб, сдвиг.
    Без пути, но с настройкой, — правка уже положенной картинки.
    """
    from src.app.session import session
    return session().set_part_texture(material, part, path, options)


def set_part_colors(material: str = '',
                    colors: Optional[Dict[str, str]] = None,
                    strength: Optional[float] = None) -> Dict[str, object]:
    """Красит части: {часть: '#rrggbb'}; значение None снимает цвет."""
    from src.app.session import session
    return session().set_part_colors(material, colors, strength)


def set_part_edge(material: str = '', width: float = 0.0,
                  color: str = '') -> Dict[str, object]:
    """Окантовка частей: ширина полосы по краю (в долях стороны) и её цвет."""
    from src.app.session import session
    return session().set_part_edge(material, width, color)


def clear_parts(material: str = '') -> Dict[str, object]:
    """Снимает с частей все картинки и цвета."""
    from src.app.session import session
    return session().clear_parts(material)


def undo_parts(material: str = '') -> Dict[str, object]:
    """Откатывает последнее изменение покраски частей."""
    from src.app.session import session
    return session().undo_parts(material)


#: Что страница вправе менять. Остальное в конфиге (геометрия окна, последние
#: флаги) относится к окну приложения и правится не отсюда.
_SETTINGS_KEYS = (
    'tf2_game_folder', 'export_folder', 'export_image_format', 'language',
    'theme', 'sv_pure_bypass', 'particles_group_tree', 'keep_temp_files',
    'debug_mode', 'material_blacklist', 'save_edits',
    # Раскладка окна: раньше жила кнопкой в шапке и не переживала перезапуск.
    'panels_pinned',
)


def settings(lang: str = '') -> Dict[str, object]:
    """
    Текущие настройки приложения и варианты выбора для них.

    Те же ключи, что правит окно настроек: конфиг общий, поэтому изменение
    здесь видно и в приложении.
    """
    from src.config.app_config import AppConfig
    from src.shared.constants import SVPURE_BYPASS_DEFAULT

    lang = _lang(lang)
    t = _t(lang)
    cfg = AppConfig.load_config()
    values = {key: cfg.get(key) for key in _SETTINGS_KEYS}
    values['export_folder'] = values.get('export_folder') or 'export'
    values['export_image_format'] = values.get('export_image_format') or 'VTF'
    values['language'] = values.get('language') or 'en'
    values['theme'] = values.get('theme') or 'dark'
    values['sv_pure_bypass'] = values.get('sv_pure_bypass') or SVPURE_BYPASS_DEFAULT
    values['material_blacklist'] = list(values.get('material_blacklist') or [])
    values['tf2_game_folder'] = values.get('tf2_game_folder') or ''
    # Умолчания у галок ТЕ ЖЕ, что в окне: незаполненный ключ означает не
    # «выключено», а «как принято». Иначе первое же сохранение со страницы
    # молча выключало бы группировку дерева частиц.
    if values.get('particles_group_tree') is None:
        values['particles_group_tree'] = True
    values['keep_temp_files'] = bool(values.get('keep_temp_files'))
    values['debug_mode'] = bool(values.get('debug_mode'))
    # Сохранение правок по умолчанию ВКЛЮЧЕНО: забытая работа — худший исход,
    # а человек не должен помнить про «сохранить».
    if values.get('save_edits') is None:
        values['save_edits'] = True
    # Плавающие панели — умолчание: прибитые требуют широкого окна, и в узком
    # они всё равно откажутся. None здесь ломал круг «прочитал → сохранил»:
    # чтение отдавало None, запись — False, и настройки «менялись» сами.
    if values.get('panels_pinned') is None:
        values['panels_pinned'] = False

    return {
        'values': values,
        'formats': ['VTF', 'PNG', 'TGA', 'JPG'],
        'languages': [{'value': 'ru', 'label': 'Русский'},
                      {'value': 'en', 'label': 'English'}],
        # Темы страницы, а не бывшего Qt-окна: другого интерфейса больше нет,
        # и предлагать «синюю» из старого тулкита было бы обещанием впустую.
        'themes': [{'value': 'light', 'label': t.get('theme_light', 'Light')},
                   {'value': 'dark', 'label': t.get('theme_dark', 'Dark')}],
        # Куда класть материалы, чтобы их пропустил sv_pure в казуале. Оба
        # способа рабочие; переключатель — страховка, если одну папку прикроют.
        'bypass': [
            {'value': 'console', 'label': t.get('bypass_console', 'console\\')},
            {'value': 'vgui',
             'label': t.get('bypass_vgui', 'vgui\\replay\\thumbnails\\')},
        ],
        'bypass_tip': t.get('bypass_tooltip', ''),
        # Размер кэша декомпиляции — рядом с кнопкой очистки: «очистить»
        # без числа не подсказывает, надо ли вообще это делать.
        'cache_mb': _cache_mb(),
        'support_url': SUPPORT_URL,
    }


#: Куда ведёт «Поддержать автора». Тот же адрес, что в окне приложения.
SUPPORT_URL = ('https://steamcommunity.com/tradeoffer/new/'
               '?partner=394814324&token=GNGCagXk')


def _cache_mb() -> float:
    """Размер кэша декомпилированных моделей в мегабайтах."""
    try:
        from src.services.decompile_cache import get_cache_size_mb
        return round(float(get_cache_size_mb()), 1)
    except Exception:                                         # noqa: BLE001
        return 0.0


def clear_model_cache() -> Dict[str, object]:
    """Удаляет кэш декомпилированных моделей.

    Нужен после обновления игры: старые разобранные модели остаются в кэше и
    собираются с прежней геометрией. Первая сборка каждого оружия после этого
    будет медленнее — кэш ради того и живёт.
    """
    from src.services.decompile_cache import clear_cache

    was = _cache_mb()
    removed = int(clear_cache())
    return {'removed': removed, 'freed_mb': was}


def vmt_snippets(lang: str = '') -> Dict[str, object]:
    """Что предлагает меню «Вставить» в редакторе VMT.

    Категории → пункты. `snippet` пустой означает ПОЛНЫЙ шаблон: он заменяет
    весь документ, а не вставляется под курсор, и страница обязана спросить.
    Тексты живут в `src/data/vmt_snippets.py` — общие с окном приложения.
    """
    from src.data.vmt_snippets import VMT_FULL_TEMPLATES, VMT_SNIPPETS

    groups = []
    for category, items in VMT_SNIPPETS.items():
        groups.append({
            'name': category,
            'items': [{'label': label, 'snippet': snippet or '',
                       'hint': hint or '',
                       'template': bool(snippet is None)}
                      for label, snippet, hint in items],
        })
    return {'groups': groups, 'templates': dict(VMT_FULL_TEMPLATES)}


def set_settings(values: Optional[Dict[str, object]] = None,
                 lang: str = '') -> Dict[str, object]:
    """
    Сохраняет настройки. Принимаются только известные ключи.

    Блэклист приходит текстом (как в окне) и разбирается общим правилом.
    Пустая папка экспорта — это 'export': безымянная папка сломала бы сборку
    молча, на этапе записи файла.
    """
    from src.config.app_config import AppConfig
    from src.data.material_filter import parse_blacklist

    lang = _lang(lang)
    cfg = AppConfig.load_config()
    for key, value in (values or {}).items():
        if key not in _SETTINGS_KEYS:
            continue
        if key == 'material_blacklist':
            cfg[key] = (parse_blacklist(value) if isinstance(value, str)
                        else list(value or []))
        elif key == 'export_folder':
            cfg[key] = str(value or '').strip() or 'export'
        elif key in ('particles_group_tree', 'keep_temp_files', 'debug_mode',
                     'save_edits', 'panels_pinned'):
            cfg[key] = bool(value)
        else:
            cfg[key] = str(value or '').strip()
    AppConfig.save_config(cfg)
    return settings(lang)


def diagnose(path: str = '', lang: str = '') -> Dict[str, object]:
    """Проверяет собранный мод; находки приходят событием diagnostics."""
    from src.app.session import session

    lang = _lang(lang)
    return session().diagnose(path, lang=lang)


def mod_library() -> List[dict]:
    """Что лежит в библиотеке модов (новые сверху)."""
    from src.services import mod_library_service
    return mod_library_service.items()


def mod_icon(name: str = '') -> Dict[str, object]:
    """
    Обложка мода — его основная текстура, при первом запросе строится.

    Отдельным вызовом, а не в списке: декодировать VTF всей библиотеки ради
    открытия каталога незачем, а карточки и без обложек показываются сразу.
    """
    from src.services import mod_library_service

    path = mod_library_service.icon(name)
    return {'name': name, 'icon': str(path) if path else ''}


def add_mod(path: str = '') -> Dict[str, object]:
    """Кладёт открытый мод в библиотеку и отдаёт его постоянный путь."""
    from src.services import mod_library_service

    saved = mod_library_service.add(path)
    if saved is None:
        return {'error': 'VPK-файл не найден'}
    return {'name': saved.name, 'path': str(saved)}


def remove_mod(name: str = '') -> Dict[str, object]:
    """Удаляет мод из библиотеки. Принимается только ИМЯ файла в ней."""
    from src.services import mod_library_service

    if not mod_library_service.remove(name):
        return {'error': f'«{name}» в библиотеке нет'}
    return {'removed': name}


def load_vpk_mod(path: str = '', lang: str = '') -> Dict[str, object]:
    """Показывает чужой мод из VPK: его модель и его текстуры."""
    from src.app.session import session

    lang = _lang(lang)
    return session().load_vpk_mod(path, lang=lang)


def load_custom_model(path: str = '', keep: Optional[bool] = None,
                      lang: str = '') -> Dict[str, object]:
    """Подставляет свою геометрию (SMD) вместо игровой."""
    from src.app.session import session

    lang = _lang(lang)
    return session().load_custom_model(path, keep, lang=lang)


def drop_custom_model() -> Dict[str, object]:
    """Забывает свою модель."""
    from src.app.session import session
    return session().drop_custom_model()


def qc_text() -> Dict[str, object]:
    """QC своей модели для правки."""
    from src.app.session import session
    return session().qc_text()


def save_qc(text: str = '') -> Dict[str, object]:
    """Сохраняет правку QC (пустой текст — вернуть авто-QC)."""
    from src.app.session import session
    return session().save_qc(text)


def vmt_params(lang: str = '') -> List[dict]:
    """
    Известные $-параметры VMT с описанием — для подсказок в редакторе.

    Тот же словарь, что показывает окно приложения при наведении на параметр
    (``vmt_snippets.param_doc``): второго списка заводить нельзя, иначе
    подсказки разойдутся с тем, что редактор действительно знает.
    """
    from src.data.vmt_snippets import all_param_names, param_doc

    lang = _lang(lang)
    return [{'param': name, 'doc': param_doc(name, lang)}
            for name in all_param_names()]


def open_vmt(material: str = '', lang: str = '') -> Dict[str, object]:
    """Текст VMT материала: сохранённая правка либо игровой оригинал."""
    from src.app.session import session

    lang = _lang(lang)
    return session().open_vmt(material, lang=lang)


def save_vmt(material: str = '', content: str = '',
             original: str = '') -> Dict[str, object]:
    """Сохраняет правку VMT."""
    from src.app.session import session
    return session().save_vmt(material, content, original)


def reset_vmt(material: str = '') -> Dict[str, object]:
    """Удаляет правку VMT — материал вернётся к игровому оригиналу."""
    from src.app.session import session
    return session().reset_vmt(material)


def extract_model(lang: str = '') -> Dict[str, object]:
    """Декомпилирует модель; список файлов приходит событием extract_files."""
    from src.app.session import session

    lang = _lang(lang)
    return session().extract_model(lang=lang)


def export_model_files(files: Optional[List[str]] = None,
                       lang: str = '') -> Dict[str, object]:
    """Сохраняет выбранные файлы модели (пустой список — отказ и уборка)."""
    from src.app.session import session

    lang = _lang(lang)
    return session().export_model_files(files, lang=lang)


def extract_texture(textures: Optional[List[str]] = None,
                    lang: str = '') -> Dict[str, object]:
    """Извлекает оригинальные текстуры предмета в папку экспорта."""
    from src.app.session import session

    lang = _lang(lang)
    return session().extract_texture(textures, lang=lang)


def export_vpks() -> List[str]:
    """Собранные моды в папке экспорта."""
    from src.app.session import session
    return session().export_vpks()


def merge_vpk(files: Optional[List[str]] = None, name: str = '',
              confirmed: bool = False, lang: str = '') -> Dict[str, object]:
    """Сливает выбранные моды в один VPK."""
    from src.app.session import session

    lang = _lang(lang)
    return session().merge_vpk(files, name, confirmed=confirmed, lang=lang)


def answer_texture(choice: str = 'game', path: str = '',
                   apply_all: bool = False) -> Dict[str, object]:
    """Ответ на need_texture: игровой оригинал, главная текстура или своя."""
    from src.app.session import session
    return session().answer_texture(choice, path, apply_all)


def export_uv(size: int = 1024) -> Dict[str, object]:
    """Рисует UV-шаблон модели в папку экспорта. Путь придёт событием."""
    from src.app.session import session
    return session().export_uv(size)


# ═══════════════════════════════════════════════════════════════════════════ #
# Частицы
# ═══════════════════════════════════════════════════════════════════════════ #

def particle_files() -> List[dict]:
    """PCF из игры — то, из чего выбирают эффект."""
    from src.app.session import session
    from src.services.particle_editor_service import ParticleEditorService

    paths = session().tf2_paths()
    if 'error' in paths:
        return []
    return [{'key': p, 'name': p.rsplit('/', 1)[-1].removesuffix('.pcf')}
            for p in ParticleEditorService.list_game_pcfs(paths['root'])]


def load_particles(source: str) -> Dict[str, object]:
    """Разбирает PCF: системы, материалы и дерево — всё, что рисует превью."""
    from src.app.session import session
    return session().load_particles(source)


def particle_params(system: str, lang: str = '') -> List[dict]:
    """Крутилки простого режима для системы частиц."""
    from src.app.session import session

    lang = _lang(lang)
    return session().particle_params(system, lang)


def particle_system(system: str, lang: str = '') -> Dict[str, object]:
    """Модули и атрибуты системы целиком — экспертный режим."""
    from src.app.session import session

    lang = _lang(lang)
    return session().particle_system(system, lang)


def set_particle_attr(system: str, group, index: int, attr: str,
                      value) -> Dict[str, object]:
    """Правка одного атрибута системы или её модуля."""
    from src.app.session import session
    return session().set_particle_attr(system, group, index, attr, value)


def particle_module_catalog(group: str) -> List[str]:
    """Модули, которые можно добавить в группу."""
    from src.app.session import session
    return session().particle_module_catalog(group)


def add_particle_module(system: str, group: str,
                        function_name: str) -> Dict[str, object]:
    from src.app.session import session
    return session().add_particle_module(system, group, function_name)


def remove_particle_module(system: str, group: str,
                           index: int) -> Dict[str, object]:
    from src.app.session import session
    return session().remove_particle_module(system, group, index)


def particle_missing_attrs(system: str, group=None, index: int = 0,
                           lang: str = '') -> List[dict]:
    """Параметры, которых у модуля ещё нет, со значениями как в игре."""
    from src.app.session import session

    lang = _lang(lang)
    return session().particle_missing_attrs(system, group, index, lang)


def add_particle_attr(system: str, group, index: int, attr: str,
                      attr_type: str, value) -> Dict[str, object]:
    from src.app.session import session
    return session().add_particle_attr(system, group, index, attr,
                                       attr_type, value)


def remove_particle_attr(system: str, group, index: int,
                         attr: str) -> Dict[str, object]:
    from src.app.session import session
    return session().remove_particle_attr(system, group, index, attr)


def copy_particle_params(system: str, group=None, index=None,
                         attr=None) -> Dict[str, object]:
    """Набор параметров для буфера: один параметр, модуль, группа или всё."""
    from src.app.session import session
    return session().copy_particle_params(system, group, index, attr)


def paste_particle_params(system: str, payload: dict,
                          mode: str = 'overwrite') -> Dict[str, object]:
    from src.app.session import session
    return session().paste_particle_params(system, payload, mode)


def duplicate_particle_system(system: str, new_name: str) -> Dict[str, object]:
    from src.app.session import session
    return session().duplicate_particle_system(system, new_name)


def rename_particle_system(system: str, new_name: str) -> Dict[str, object]:
    from src.app.session import session
    return session().rename_particle_system(system, new_name)


def remove_particle_system(system: str) -> Dict[str, object]:
    from src.app.session import session
    return session().remove_particle_system(system)


def particle_children(system: str) -> List[dict]:
    from src.app.session import session
    return session().particle_children(system)


def add_particle_child(parent: str, child: str,
                       delay: float = 0.0) -> Dict[str, object]:
    from src.app.session import session
    return session().add_particle_child(parent, child, delay)


def remove_particle_child(parent: str, index: int) -> Dict[str, object]:
    from src.app.session import session
    return session().remove_particle_child(parent, index)


def add_particle_layer(parent: str) -> Dict[str, object]:
    from src.app.session import session
    return session().add_particle_layer(parent)


def particle_history() -> Dict[str, object]:
    """Есть ли куда откатываться и возвращаться."""
    from src.app.session import session
    return session().particle_history()


def undo_particles(delta: int = -1) -> Dict[str, object]:
    """Откат (-1) или возврат (+1) правки эффекта."""
    from src.app.session import session
    return session().undo_particles(delta)


def particle_control_points(system: str) -> Dict[str, object]:
    """Какие контрольные точки нужны этому эффекту."""
    from src.app.session import session
    return session().particle_control_points(system)


def particle_models() -> List[dict]:
    """Модели из кэша декомпиляции — на них сажают контрольную точку."""
    from src.app.session import AppSession
    return AppSession.particle_models()


def particle_model_scene(qc: str) -> Dict[str, object]:
    """Меш модели и её точки крепления."""
    from src.app.session import session
    return session().particle_model_scene(qc)


def particle_materials(system: str = '') -> List[dict]:
    """Материалы выбранного эффекта с картинками — карточки 2D."""
    from src.app.session import session
    return session().particle_materials(system)


def set_particle_texture(material: str, path: str,
                         max_size: int = 512) -> Dict[str, object]:
    from src.app.session import session
    return session().set_particle_texture(material, path, max_size)


def reset_particle_texture(material: str) -> Dict[str, object]:
    from src.app.session import session
    return session().reset_particle_texture(material)


def game_particle_materials() -> List[str]:
    """Материалы всех эффектов игры — работают в казуале без нового файла."""
    from src.app.session import session
    return session().game_particle_materials()


def set_particle_material_to_game(material: str,
                                  game_material: str) -> Dict[str, object]:
    from src.app.session import session
    return session().set_particle_material_to_game(material, game_material)


def rename_particle_material(material: str,
                             new_material: str) -> Dict[str, object]:
    from src.app.session import session
    return session().rename_particle_material(material, new_material)


def use_particle_texture_colors(system: str) -> Dict[str, object]:
    from src.app.session import session
    return session().use_particle_texture_colors(system)


def particle_lint(system: str = '', lang: str = '') -> Dict[str, object]:
    """Что в эффекте сломает его в игре."""
    from src.app.session import session

    lang = _lang(lang)
    return session().particle_lint(system, lang)


def fix_particle_lint(system: str = '') -> Dict[str, object]:
    from src.app.session import session
    return session().fix_particle_lint(system)


def save_particles(path: str) -> Dict[str, object]:
    from src.app.session import session
    return session().save_particles(path)


def export_particles_vpk(name: str = 'particles_mod.vpk',
                         lang: str = '') -> Dict[str, object]:
    from src.app.session import session

    lang = _lang(lang)
    return session().export_particles_vpk(name, lang)


def particle_param_reference(path: str = '',
                             for_ai: bool = False) -> Dict[str, object]:
    from src.app.session import session
    return session().particle_param_reference(path, for_ai)


def set_particle_param(system: str, key: str, value) -> Dict[str, object]:
    """Меняет параметр эффекта; в ответе — обновлённые системы для превью."""
    from src.app.session import session
    return session().set_particle_param(system, key, value)


# ═══════════════════════════════════════════════════════════════════════════ #
# Шапки и косметика
# ═══════════════════════════════════════════════════════════════════════════ #

#: Категории, которые можно скрыть — те же, что в панели шапок приложения.
#: Значение живёт в общем конфиге (`hats_hidden_tags`), поэтому фильтр
#: одинаков и в окне, и здесь.
HAT_TAGS = ('medals', 'halloween', 'holiday')

def _model_file_name(mdl_path: str) -> str:
    """Имя файла модели без пути и расширения — подпись карточки косметики."""
    return mdl_path.replace(chr(92), "/").rsplit("/", 1)[-1].removesuffix(".mdl")


def hat_filters(lang: str = '') -> List[dict]:
    """
    Какие категории косметики можно скрыть и что скрыто сейчас.

    Имя короткое, подсказка полная: в ряду фильтров «Скрыть сезонные
    (Christmas и др.)» не помещается, а на кнопке нужно одно слово.
    """
    lang = _lang(lang)
    t = _t(lang)
    hidden = hidden_hat_tags()
    return [{'key': k,
             'name': t.get(f'hat_filter_{k}', k),
             'tip': t.get(f'hat_filter_{k}_tip', ''),
             'hidden': k in hidden}
            for k in HAT_TAGS]


def hidden_hat_tags() -> List[str]:
    """Скрытые категории из общего конфига приложения."""
    from src.config.app_config import AppConfig

    saved = AppConfig.load_config().get('hats_hidden_tags') or []
    return [t for t in saved if t in HAT_TAGS]


def set_hat_filter(tag: str, hidden: bool) -> List[dict]:
    """
    Прячет или возвращает категорию косметики.

    Пишем в тот же ключ конфига, что и панель шапок: настройка у приложения и
    веб-интерфейса общая, иначе они разошлись бы по показанному списку.
    """
    from src.config.app_config import AppConfig

    if tag not in HAT_TAGS:
        return hat_filters()
    current = set(hidden_hat_tags())
    current.add(tag) if hidden else current.discard(tag)
    AppConfig.set('hats_hidden_tags', sorted(current))
    return hat_filters()


def hats(query: str = '', tf2_class: Optional[str] = None,
         lang: str = '') -> List[dict]:
    """
    Косметика TF2 из items_game.txt.

    Скрытые категории берём из конфига (`hats_hidden_tags`) — так же, как
    панель шапок. Отдаём ВСЁ, что прошло фильтры: косметики 9504, и отрисовка
    полного списка стоит 56 мс — обрезать было незачем, а обрезанный список
    молча врал, что предмета в игре нет.
    """
    from src.app.session import session
    from src.data.hats_parser import parse_hats

    lang = _lang(lang)
    t = _t(lang)
    paths = session().tf2_paths()
    if 'error' in paths:
        return []

    hidden = set(hidden_hat_tags())
    words = [w for w in str(query).lower().split() if w]
    out: List[dict] = []
    for h in parse_hats(paths['root'], lang):
        if 'medals' in hidden and h.is_medal:
            continue
        if 'halloween' in hidden and h.is_halloween:
            continue
        if 'holiday' in hidden and h.is_holiday:
            continue
        if not h.matches(words, tf2_class or None):
            continue
        out.append({
            'key': h.mdl_path,
            'name': h.name,
            'cls': ', '.join(h.classes),
            'type': 'hat',
            'mode': 'hat',
            'icon': h.icon,
            # Имя файла модели — то же, что у оружия показано ключом
            # (c_scattergun). Целиком путь в подпись не влезает: у косметики
            # он вида models/workshop/player/items/demo/…
            'label': _model_file_name(h.mdl_path),
            # Мультиклассовая шапка: у каждого класса СВОЯ модель. Сборке нужны
            # все выбранные, а превью — одна конкретная: путь с %s ей не годится.
            'per_class': dict(h.per_class_models or {}),
            'slot': h.slot,
            # Модельные стили шапки: у каждого СВОЯ геометрия (у «Только
            # камень» нет оправы). Отдаём их с моделями — выбор стиля меняет и
            # показ, и то, что уйдёт в сборку. Числа мало: по нему стиль не
            # загрузить.
            'styles': [
                {'name': (st.get('name')
                          or t.get('hat_style_n', 'Style {n}').format(n=i + 1)),
                 'per_class': dict(st.get('per_class_models') or {})}
                for i, st in enumerate(h.styles or [])
            ],
        })
    return out
