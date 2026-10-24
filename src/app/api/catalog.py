"""Каталог: категории, предметы, режим и его контролы, обложки"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, _t, endpoint, logger
from src.app.api.preview import tf2_paths


#: Ключи категорий в порядке показа
CATEGORY_KEYS = ('weapon', 'character', 'special', 'projectile',
                 'pickup', 'taunt', 'skybox', 'custom')

#: Категория -> режим сборки по умолчанию. Подтип может его уточнить
#: (персонаж: тело/руки/маски, специальное: спрей/critHIT)
_CATEGORY_MODE = {
    'weapon': 'normal',
    'character': 'body',
    'special': 'spray',
    'projectile': 'normal',
    'pickup': 'normal',
    'taunt': 'normal',
    'skybox': 'skybox',
    # Загруженный мод - режим 'custom'. По этому имени закрывается редактор
    # VMT и решается, что показывать
    'custom': 'custom',
}


@endpoint
def categories(lang: str = '') -> List[dict]:
    """Верхний уровень выбора: что вообще меняем"""
    lang = _lang(lang)
    t = _t(lang)
    return [{'key': k, 'name': t.get(f'category_{k}', k)} for k in CATEGORY_KEYS]


@endpoint
def classes(lang: str = '') -> List[dict]:
    """Классы TF2. Ключ - он же имя в данных, отдельного перевода у них нет"""
    from src.data.weapons import TF2_WEAPONS
    return [{'key': k, 'name': k} for k in TF2_WEAPONS]


@endpoint
def weapon_types(tf2_class: Optional[str] = None, lang: str = '') -> List[dict]:
    """
    Типы оружия, по которым можно фильтровать

    С классом - только те, что у него ЕСТЬ: часы есть у шпиона, КПК у инженера,
    и показывать всем полный перечень значило бы обещать пустые списки

    Без класса - все слоты, у которых хоть у кого-то есть оружие. Тип должен
    работать сам по себе: выбрать «Ближний бой» по всем классам - нормальное
    желание, и требовать сперва выбрать класс незачем
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
    from src.data.weapons import (
        TF2_WEAPONS, WEAPON_SKIN_ITEMS, WEAPON_SLOT_TYPES, get_weapon_name,
    )

    out: List[dict] = []
    class_names = [tf2_class] if tf2_class else list(TF2_WEAPONS)
    type_names = [weapon_type] if weapon_type else WEAPON_SLOT_TYPES
    garlands = _garland_keys()

    for cls in class_names:
        slots = TF2_WEAPONS.get(cls, {})
        for slot in type_names:
            for key in slots.get(slot, {}):
                if key.lower() in garlands:
                    continue
                out.append({
                    'key': key,
                    'name': get_weapon_name(cls, slot, key, lang),
                    'cls': cls,
                    'type': slot,
                    # Режим у оружия - «класс_ключ» (scout_c_scattergun). Просто ключ
                    # не подойдёт: weapon_key_from_mode отрежет первый сегмент
                    # и модель искалась бы по «scattergun»
                    'mode': f'{cls.lower()}_{key}',
                })
            # Другая строка скина той же модели (Критокола у модели Бонка):
            # своей строкой, превью открывается сразу на её стиле
            for key, skin, names, icon in WEAPON_SKIN_ITEMS.get(cls, {}).get(slot, ()):
                out.append({'key': key, 'name': names.get(lang) or names['en'],
                            'cls': cls, 'type': slot, 'mode': f'{cls.lower()}_{key}',
                            'skin': skin, 'icon': icon})
    return out


def _garland_keys() -> set:
    """
    Праздничные «оружия», которые на деле только гирлянда на обычной пушке

    В игре у них нет своей модели оружия: items_game вешает гирлянду на
    базовое через `attached_models` (у праздничного обреза `c_scattergun_xmas`
    - одни лампочки). Отдельным пунктом каталога такая гирлянда открылась бы
    без ствола и жила своей работой, поэтому она есть только у оружия с
    переключателем «Праздничная», где её красят вместе с пушкой. Цельные
    праздничные модели (Посол, Чёрный ящик…) остаются в каталоге

    Без пути к игре фильтровать не по чему - каталог показывает всё
    """
    from src.data.weapon_model_index import attachment_only_models
    paths = tf2_paths()
    return set() if 'error' in paths else attachment_only_models(paths['root'])


def _character_items(tf2_class: Optional[str], lang: str) -> List[dict]:
    """Тело и руки класса. Ключ режима строится как в приложении: класс_часть"""
    from src.data.weapons import TF2_WEAPONS, get_character_parts

    out: List[dict] = []
    for cls in ([tf2_class] if tf2_class else list(TF2_WEAPONS)):
        for key, name in get_character_parts(cls, lang):
            mode = f'{cls.lower()}_{key}'      # ключ режима как в приложении
            out.append({
                'key': key,
                'name': name,
                'cls': cls,
                'type': 'character',
                'mode': mode,
                'icon': _character_icon(mode, cls),
            })
    return out


def _character_icon(mode: str, cls: str) -> str:
    """
    Обложка карточки персонажа: у каждой части своя

    Текстура модели не годится: развёртка класса - простыня из лоскутов, по ней
    не читается ни класс, ни часть, а у половины классов руки лежат на общем
    листе с телом. Поэтому каждая отвечает на свой вопрос: тело - ЧЕЙ (портрет
    класса, тот же, что на странице звуков), руки - та самая текстура рук,
    которую карточка и правит, маски - значок маскировки
    """
    from src.data.player_characters import CLASS_ICON, DISGUISE_ICON, SPY_MASK_MODE_KEY
    from src.data.player_hands import hands_icon

    if mode == SPY_MASK_MODE_KEY:
        return DISGUISE_ICON
    return hands_icon(mode) or CLASS_ICON.format(cls.lower())


def _search(rows: List[dict], query: str) -> List[dict]:
    """
    Отбор по строке поиска - тем же правилом, что у косметики

    Слова, а не подстрока целиком: «обрез мал» обязано находить «Обрез
    Малыша», порядок слов человек помнить не должен. Ищем и по имени файла с
    классом: поле подписано «Название или файл», а классом удобно сузить
    список, когда фильтр стоит на «Все»
    """
    words = [w for w in str(query or '').lower().split() if w]
    if not words:
        return rows

    def haystack(row: dict) -> str:
        return ' '.join(str(row.get(field, '') or '').lower()
                        for field in ('name', 'key', 'label', 'cls'))

    return [row for row in rows if all(w in haystack(row) for w in words)]


@endpoint
def items(category: str = 'weapon', tf2_class: Optional[str] = None,
          weapon_type: Optional[str] = None, lang: str = '',
          query: str = '') -> List[dict]:
    """
    Предметы категории - то, из чего выбирают в каталоге

    Пустые ``tf2_class`` / ``weapon_type`` означают «все»: каталог показывает
    полный список, пока фильтры не сузили его

    ``query`` - строка поиска, для оружия так же, как для косметики
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
        # говорит («death_ice» вместо «Эффект смерти: Лёд»)
        labels = {'critHIT': 'special_crit', 'spray': 'special_spray',
                  'death_ice': 'special_death_ice',
                  'death_gold': 'special_death_gold',
                  'death_fire': 'special_death_fire'}
        return _search([{'key': m, 'name': t.get(labels.get(m, ''), m),
                         'cls': '', 'type': 'special', 'mode': m}
                        for m in SPECIAL_MODES], query)
    if category == 'skybox':
        from src.app.session import session
        from src.data.skyboxes import SKYBOX_MODE
        from src.services.skybox_service import SkyboxService

        # Список спрашиваем у УСТАНОВЛЕННОЙ игры: `STOCK_SKY_NAMES` - фолбэк на
        # случай ненастроенной папки, и с обновлениями Valve он стареет. Скан
        # ищет `materials/skybox/<имя>up.vmt` и объединяется с фолбэком, так
        # что список не может стать короче (см. enumerate_sky_names)
        paths = session().tf2_paths()
        names = SkyboxService.enumerate_sky_names(
            '' if 'error' in paths else str(paths.get('root') or ''))
        from src.data.skyboxes import SKY_ALL_MAPS_KEY
        # Обложка - боковая грань самого неба: иконки в рюкзаке у него нет и
        # быть не может, а узнают небо по горизонту.
        # Первым - «Все карты»: одно небо на всю игру, без обложки (своего
        # неба у пункта нет, превью показывает SKY_PREVIEW_DEFAULT). Пункт был
        # в окне приложения и потерялся при переезде на страницу
        return _search([{'key': SKY_ALL_MAPS_KEY, 'name': t['sky_all_maps'],
                         'cls': '', 'type': 'skybox', 'mode': SKYBOX_MODE,
                         'sky': SKY_ALL_MAPS_KEY, 'icon': ''}]
                       + [{'key': n, 'name': n, 'cls': '', 'type': 'skybox',
                           'mode': SKYBOX_MODE, 'sky': n, 'icon': f'skybox/{n}'}
                          for n in names], query)

    # Снаряды, пикапы и реквизит насмешек устроены одинаково: таблица
    # {ключ: {ru, en, mdl_path}} плюс префикс режима. Реестр общий с
    # приложением - новая такая категория подключится сама
    from src.data.simple_models import SIMPLE_MODEL_CATEGORIES, model_display_name
    from src.data.taunt_catalog import ensure as _ensure_taunts
    # Насмешек в игре вчетверо больше, чем в выверенной руками таблице;
    # остальные берутся из items_game при первом показе каталога
    _ensure_taunts()
    simple = SIMPLE_MODEL_CATEGORIES.get(category)
    if simple:
        return _search([{'key': key,
                         'name': model_display_name(simple.table, key, lang),
                         'cls': '', 'type': category,
                         # Режим у них - «префикс + ключ» (pickup_medkit_small):
                         # по нему дальше находится MDL, и ключ не годится
                         'mode': f'{simple.mode_prefix}{key}',
                         # Обложка - текстура самой модели: аптечки, патроны и
                         # снаряды это мировые объекты, в рюкзаке их нет, и
                         # карточки стояли пустыми. У насмешек иконка всё же
                         # есть - сам предмет-насмешка лежит в инвентаре
                         'icon': (simple.table[key].get('icon')
                                  or simple.table[key].get('mdl_path', ''))}
                        for key in simple.table], query)

    # Кастомный мод - не список: предмет здесь файл, его выбирают в каталоге
    if category != 'custom':
        logger.debug(f"api.items: категория {category!r} ещё не подключена")
    return []


@endpoint
def mode_for(category: str, subtype: Optional[str] = None) -> str:
    """
    Режим сборки по выбору в каталоге

    Подтип уточняет категорию там, где её мало: у персонажа это тело, руки или
    маски шпиона, у специального - спрей или critHIT. От режима зависит, какие
    контролы показывать, поэтому правило держим в одном месте
    """
    if subtype:
        return subtype
    return _CATEGORY_MODE.get(category, 'normal')


# Что показывать при этом режиме

@endpoint
def controls_for(mode: str, key: str = '') -> Dict[str, object]:
    """
    Видимость и доступность контролов для режима сборки

    Матрица выписана в frontend/CONTROLS.md. Считает её Python, а не
    представление: правило одно, и при замене интерфейса оно не переписывается
    заново

    Часть ответов зависит не только от режима, но и от загруженной модели
    (есть ли BLU-вариант, австралий, служебные материалы). Такие ключи здесь
    не выдумываются - их проставит контроллер превью, когда модель приедет

    ``key`` - ключ выбранного предмета, если он есть: у косметики режим один
    на всю категорию («hat»), и по нему предмет не назвать. Нужен только для
    предлагаемого имени VPK
    """
    from src.data.player_characters import PLAYER_BODY_MODE_KEYS, SPY_MASK_MODE_KEY
    from src.data.item_kinds import kind_of
    from src.data.player_hands import HAND_MODE_KEYS
    from src.data.simple_models import category_of_mode
    from src.data.skyboxes import SKYBOX_MODE
    from src.domain.format_choices import (
        VTF_FLAGS, VTF_FORMATS, allowed_flags_for_mode, allowed_formats_for_mode,
    )

    from src.data.weapons import VTF_ONLY_SPECIAL_MODES
    from src.shared.validators import suggest_vpk_name

    is_spray = mode == 'spray'
    # Эффекты смерти показываются ТОЙ ЖЕ сценой, что и крит (персонаж плюс
    # текстура), и в приложении их накрывает один флаг `_crithit_mode`. Значит
    # и правила показа у них общие: модель подменять нечем, стилей нет
    is_crit = mode == 'critHIT' or (bool(mode) and mode in VTF_ONLY_SPECIAL_MODES)
    is_skybox = mode == SKYBOX_MODE
    is_hands = bool(mode) and mode in HAND_MODE_KEYS
    is_body = bool(mode) and mode in PLAYER_BODY_MODE_KEYS
    is_spy_mask = mode == SPY_MASK_MODE_KEY
    is_normal = bool(mode) and not (is_spray or is_crit or is_skybox
                                    or is_hands or is_body)
    # Предмет оружия из каталога (не снаряд и не реквизит насмешки)
    held_weapon = (is_normal and kind_of(mode).is_weapon
                   and not category_of_mode(mode))
    # Надетое (ботинки, щит, парашют, рюкзак знамени): от первого лица его не
    # видно, вместо этого - «На персонаже». Горн знамени - своя запись каталога
    # со своим видом от первого лица
    worn_only = held_weapon and _worn(mode)

    # «Модельные» режимы: geometry идёт через декомпиляцию, материал -
    # VertexLitGeneric. От этого зависят Normal Map, карты и инструменты
    model_like = is_normal or is_hands or is_body

    allowed_flags = allowed_flags_for_mode(mode)

    return {
        'mode': mode,
        # Панель сборки
        'resolutions': ['256'] if is_spray else ['256', '512', '1024', '2048'],
        # Список ВСЕГДА конкретный. `allowed_formats_for_mode` возвращает None
        # там, где ограничений нет, и это значило «покажи полный список» -
        # окно приложения его знало (VTF_FORMATS), а страница держала свою
        # копию из четырёх штук в разметке. Итого из 26 форматов было видно 4
        'formats': allowed_formats_for_mode(mode) or list(VTF_FORMATS),
        'format_locked': is_spray,
        # Имя VPK по предмету: в разметке стояло одно на всех
        # («scattergun_mod.vpk»), и топор собирался под именем скаттергана.
        # Считаем здесь, потому что имя обязано пройти validate_vpk_filename
        'vpk_name': suggest_vpk_name(mode, key),
        # Галки флагов: ИМЯ (его ждёт сборка), подпись и разрешён ли флаг в
        # этом режиме. Список конкретный по той же причине, что и форматы:
        # копия в разметке разъезжается с доменной, и страница присылала в
        # сборку подписи вместо имён - флаги на них терялись
        'flags': [{'key': key, 'label': label, 'adv': adv,
                   'on': allowed_flags is None or key in allowed_flags}
                  for key, label, adv in VTF_FLAGS],
        'flags_enabled': not (is_spray or is_crit),
        'gamma': allowed_flags is None,
        'normal_map': model_like and not is_crit,
        'material_maps': model_like and not is_crit,
        'shoulders': is_hands,
        # Краски из игры - только у шапок: они красятся командным цветом через
        # VMT, и у оружия такой краски нет
        'hat_paints': mode == 'hat',
        # «На персонаже»: шапка, надетое оружие и оружие в руках - на классе
        'wear': mode == 'hat' or worn_only,
        # Инструменты
        'extract_model': model_like,
        'extract_texture': model_like,
        # Превью
        # Модель подменять можно только там, где она есть: у спрея, крита и
        # эффектов смерти её нет вовсе, у неба - грани вместо неё.
        # Пустой режим - предмет ещё не выбран: страница спрашивает правила
        # на старте, и без этого «Заменить модель» висела над пустым кадром
        'load_model': bool(mode) and not (is_crit or is_skybox or is_spray),
        # Руки сборка своей моделью не собирает (VPKService.build_vpk), и
        # кнопка обещала бы подмену, которой в моде не будет
        'replace_model': bool(mode) and not (is_crit or is_skybox or is_spray
                                             or is_body or is_hands),
        # Деление на части - про ГЕОМЕТРИЮ, а не про подмену модели: делить
        # можно всё, что приехало декомпиляцией, включая тела классов и руки
        # (у них своя геометрия и своя развёртка). Поэтому не вслед за
        # `replace_model`, которого у персонажей нет
        'split_parts': model_like,
        # Вьюмодель есть только у оружия В РУКАХ. Снаряд, аптечка и реквизит
        # насмешки - мировые модели: `kind_of` зовёт их оружием (pipeline тот
        # же), но вида от первого лица у них нет, и вкладка вела в ошибку
        'first_person': held_weapon and not worn_only,
        # Насмешка: персонаж играет тонт с реквизитом. Есть только у самого
        # реквизита - у оружия своего тонта нет, а у шапки нет и реквизита
        'taunt': category_of_mode(mode) == 'taunt',
        # War Paint игры: игра кладёт их на оружие в руках. Есть ли они у
        # этой пушки, страница узнаёт у каталога, когда модель приедет
        'warpaint': (is_normal and kind_of(mode).is_weapon
                     and not category_of_mode(mode)),
        'misc': not (is_hands or is_spy_mask),
        # Редактор VMT - там, где материал модели: у спрея, крита и неба
        # своего VMT нет (то же правило, что в `materials.vmt_target`). У мода из VPK
        # правится VMT самого мода. Без признака кнопка висела под пустым
        # альбомом до выбора предмета
        'vmt_editor': model_like,
        'styles': not (is_spray or is_crit or is_skybox),
        # Команды и вариант зависят от загруженной модели, не от режима:
        # маски шпиона прячут их безусловно, остальное решает контроллер
        'teams': not is_spy_mask,
    }


def _worn(mode: str) -> bool:
    """Предмет надевают, а не держат (viewmodel_anims.is_worn). Рюкзак знамени
    тоже: горн в руке - другая запись каталога. Игра не найдена - считаем,
    что держат: вкладка останется"""
    from src.config.app_config import AppConfig
    from src.data import viewmodel_anims
    from src.domain.preview.model_key import model_key_for

    root = (AppConfig.load_config().get('tf2_game_folder') or '').strip()
    key = model_key_for(mode)
    if not (root and key):
        return False
    return viewmodel_anims.is_worn(key, root)


def icon_png(key: str) -> Optional[bytes]:
    """
    PNG обложки предмета, либо None

    Ключ - то, что каталог знает о предмете: ``icon`` из items_game, ключ
    оружия, путь к модели или `skybox/<имя>`

    Источников два, и порядок важен. Сначала рюкзак: это готовая иконка на
    прозрачном фоне, ровно та, что игрок видит в инвентаре. Но она есть только
    у предметов инвентаря - у аптечек, патронов, снарядов, реквизита насмешек
    и неба её нет и не будет, и карточки стояли пустыми. Для них берём
    текстуру самой модели (у неба - грань), см. `model_icons`

    Персонажи сюда не попадают: развёртка класса не говорит, чей это класс, и
    каталог просит для них портрет (`mat/…`, см. `_character_items`)
    """
    from src.app.session import session
    from src.services import model_icons
    from src.services.backpack_icons import png_bytes

    paths = session().tf2_paths()
    if 'error' in paths:
        return None

    key = (key or '').replace('\\', '/').strip()
    if key.lower().startswith('skybox/'):
        # Все VPK с небесами, а не одна tf2_textures: у небес из hl2/ обложка
        # иначе не находилась и карточка оставалась пустой
        from src.services.tf2_paths import TF2Paths
        return model_icons.sky_png(key[len('skybox/'):],
                                   TF2Paths.skybox_vpks(paths['root']))
    # `mat/…` - прямая игровая картинка: портрет класса, значок постройки.
    # У звука предмета может не быть вовсе, а карточка без картинки пустая
    if key.lower().startswith('mat/'):
        from src.services.backpack_icons import material_png

        return material_png(key[len('mat/'):], paths['textures_vpk'])

    icon = png_bytes(key, paths['textures_vpk'])
    if icon is not None:
        return icon

    # Имя иконки не совпало с именем модели (Scottish Resistance, Sydney
    # Sleeper…) - спрашиваем items_game. Вторым, а не первым: модель делят и
    # золотые/промо-копии, и по ней иногда находится не та иконка
    from src.data.weapon_model_index import weapon_icon
    icon_path = weapon_icon(key, paths['root'])
    if icon_path:
        icon = png_bytes(icon_path, paths['textures_vpk'])
        if icon is not None:
            return icon

    from src.data.weapons import WEAPON_MDL_PATHS
    mdl = key if key.lower().endswith('.mdl') else WEAPON_MDL_PATHS.get(key, '')
    if not mdl:
        return None
    return model_icons.model_png(mdl, paths['misc_vpk'], paths['textures_vpk'])


#: Сколько иконок отдаём одним ответом. Страница просит по шестнадцать, предел
#: защищает сервер от запроса на весь каталог разом
ICON_BATCH_LIMIT = 64


@endpoint
def icons(keys: List[str]) -> Dict[str, str]:
    """
    Иконки пачкой: data-URL по ключу. Чего в игре нет, того в ответе нет

    Пока страницу крутят колесом, WebView2 придерживает каждый сетевой запрос
    на сотни миллисекунд, а картинку из data-URL не держит вовсе. Пачка ждёт
    один раз за шестнадцать иконок, а не каждая иконка по очереди
    """
    import base64

    out: Dict[str, str] = {}
    for key in list(keys or [])[:ICON_BATCH_LIMIT]:
        key = str(key)
        try:
            data = icon_png(key)
        except Exception as exc:                      # noqa: BLE001 - одна битая иконка не роняет пачку
            logger.debug(f"[icons] {key}: {exc}")
            data = None
        if data:
            out[key] = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
    return out
