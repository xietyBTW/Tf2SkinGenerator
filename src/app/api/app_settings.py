"""Настройки приложения, раскладка экрана, окно, кэш моделей"""

from __future__ import annotations

import re
import threading
from typing import Dict, Optional

from src.app.api._common import _lang, _t, endpoint, logger


#: Что страница вправе менять. Остальное в конфиге (геометрия окна, последние
#: флаги) относится к окну приложения и правится не отсюда
_SETTINGS_KEYS = (
    'tf2_game_folder', 'export_folder', 'export_image_format', 'language',
    'theme', 'sv_pure_bypass', 'particles_group_tree', 'keep_temp_files',
    'debug_mode', 'material_blacklist', 'save_edits',
    # Раскладка окна: хранится, чтобы пережить перезапуск
    'panels_pinned',
    # Особые флаги VTF: по умолчанию их нет на панели (см. VTF_FLAGS)
    'advanced_vtf_flags',
    # Гифка на части крутится и в 3D. Выключено: это секунды расчёта и сотни
    # мегабайт на видеокарте после каждого мазка (см. AppSession._animate_parts)
    'parts_animation',
    # Анимации интерфейса (панели, камера, разъезд половин). Включены
    'ui_animations',
    # Как выглядит сборка в нижней полосе: вариант на каждую группу
    'build_fx',
    # Потолок кэша разобранных моделей, МБ; 0 - без ограничения
    'model_cache_mb',
)

#: Какие потолки кэша моделей предлагает настройка. Меньше 512 МБ нет: кэш -
#: это и рабочая папка открытой модели, а модель класса с анимациями для
#: «На модели» одна весит до 165 МБ. Удали её посреди работы - превью и
#: сборка не нашли бы свои файлы
_CACHE_CAPS = (512, 1024, 2048, 5120, 10240, 0)


def _cache_cap(value: object) -> int:
    """Потолок кэша из списка, чужое значение - умолчание (1 ГБ)"""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 1024
    return value if value in _CACHE_CAPS else 1024

#: Группы выбора в разделе «Кастомизация» (frontend/mockup/buildfx.js).
#: Сами варианты знает страница, и чужое значение она заменит умолчанием;
#: здесь только форма - в конфиг не должно лечь что попало
_BUILD_FX_GROUPS = ('text', 'line', 'pct', 'btn', 'fx', 'end', 'err', 'sound')


def _build_fx(value: object) -> Dict[str, str]:
    """Выбор анимации сборки в том виде, в каком его можно хранить"""
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in _BUILD_FX_GROUPS
            if isinstance(value.get(key), str)
            and re.fullmatch(r'[a-z]{1,16}', value[key])}

#: Мелочи раскладки, которые правят НЕ в окне настроек, а прямо на экране:
#: край панели тянут мышью, громкость двигают ползунком. Читаются вместе с
#: настройками, пишутся по одной (`set_ui_state`)
#:
#: Через конфиг, а не localStorage: порт локального сервера постоянный, но
#: если он занят, берётся случайный (frontend/app.py), и с ним меняется
#: origin - браузерное хранилище тогда не пережило бы перезапуск
#:
#: Ключ -> (минимум, максимум, умолчание)
_UI_STATE = {
    # 0 - «край не трогали». Ширину панели частиц задаёт тогда CSS, а она
    # разная у прибитого режима (280) и у плавающего (300): подставить сюда
    # одно число значило бы сломать один из двух
    'params_width': (0, 2000, 0),
    # Ширины прибитых каталога слева и панели сборки справа; 0 - край не
    # тянули, ширину задаёт CSS (230 и 280)
    'catalog_width': (0, 2000, 0),
    'build_width': (0, 2000, 0),
    # Доля левой половины работы в процентах; 0 - границу не трогали, поровну
    'split_percent': (0, 85, 0),
    'sound_volume': (0, 100, 100),
    # Ширина консоли; 0 - край не тянули, ширину задаёт CSS
    'console_width': (0, 2000, 0),
    # Какие категории показывает консоль - битовой маской. Значения битов
    # заданы в одном месте, frontend/mockup/log.js (BIT): Python их не
    # толкует, ему это просто число, которое надо запомнить.
    # Умолчание 7 - обмен + ошибки + предупреждения
    'console_filter': (0, 31, 7),
    # Потолок размера своей картинки в редакторе частиц. Меньшие картинки
    # не растягиваются, не-степень двойки сервер округлит вниз сам
    'particle_tex_size': (256, 1024, 512),
    # Какие туры обучения пройдены - битовой маской. Биты заданы в одном
    # месте, frontend/mockup/tour.js (TOURS[…].bit); 0 - не пройден ни один,
    # и главный тур запустится при старте
    'tours_done': (0, 255, 0),
    # Встречающее окно первого запуска (welcome.js) уже показано или не нужно
    'welcome_done': (0, 1, 0),
    # Предупреждения при первом входе в раздел - битовой маской. Биты заданы
    # в frontend/mockup/notices.js (NOTICES[…].bit)
    'notices_done': (0, 255, 0),
}


def _ui_value(key: str, raw: object) -> int:
    """Число из конфига в границах ключа. Мусор и пустота - умолчание"""
    low, high, default = _UI_STATE[key]
    try:
        return min(high, max(low, int(raw)))          # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


@endpoint
def set_ui_state(key: str = '', value: object = 0) -> Dict[str, object]:
    """
    Запоминает мелочь раскладки: ширину панели, громкость проигрывателя

    Отдельно от `set_settings`: то окно сохраняют кнопкой и целиком, а эти
    значения меняются движением мыши. Гонять через него весь конфиг и обход
    кэша моделей (`_cache_mb`) ради одного числа незачем
    """
    from src.config.app_config import AppConfig

    if key not in _UI_STATE:
        logger.debug(f"api.set_ui_state: неизвестный ключ {key!r}")
        return {'error': f'неизвестная настройка: {key}'}
    AppConfig.set(key, _ui_value(key, value))
    return {'saved': True}


#: Системный диалог выбора папки: (начальная папка) -> путь или ''. Ставит окно
#: приложения (frontend/app.py), страница в обычном браузере его не получает
_folder_picker = None


def set_folder_picker(picker) -> None:
    """Подключает диалог выбора папки окна приложения"""
    global _folder_picker
    _folder_picker = picker


@endpoint
def pick_folder(start: str = '') -> Dict[str, object]:
    """
    Выбор папки системным диалогом - для путей в настройках

    Путь из поля бывает относительным («export»): диалог открываем там, куда
    он на самом деле ведёт, то есть от папки данных. Пустой `path` - отмена
    """
    from pathlib import Path

    from src.shared.paths import data_dir

    if _folder_picker is None:
        return {'error': 'Выбор папки доступен только в окне приложения'}
    folder = Path(str(start or '').strip() or '.')
    if not folder.is_absolute():
        folder = data_dir() / folder
    folder = folder.resolve()
    while not folder.is_dir() and folder.parent != folder:
        folder = folder.parent                 # диалог открывается у ближайшей
    try:
        return {'path': _folder_picker(str(folder)) or ''}
    except Exception as exc:                    # noqa: BLE001 - граница с окном
        logger.warning(f"диалог выбора папки: {exc}")
        return {'error': str(exc)}


#: Кнопки окна в шапке страницы: (действие, тема) -> состояние окна. Ставит
#: окно приложения со своим заголовком (frontend/titlebar.py)
_window_control = None


def set_window_control(control) -> None:
    """Подключает кнопки окна приложения"""
    global _window_control
    _window_control = control


@endpoint
def window_control(action: str = '', theme: str = '') -> Dict[str, object]:
    """
    Свернуть, развернуть или закрыть окно, без действия - только его состояние

    `custom: False` - заголовок у окна системный (или это браузер), и своих
    кнопок странице не нужно
    """
    if _window_control is None:
        return {'custom': False}
    try:
        return _window_control(action, theme)
    except Exception as exc:                    # noqa: BLE001 - граница с окном
        logger.warning(f"кнопка окна: {exc}")
        return {'error': str(exc)}


@endpoint
def settings(lang: str = '') -> Dict[str, object]:
    """
    Текущие настройки приложения и варианты выбора для них

    Те же ключи, что правит окно настроек: конфиг общий, поэтому изменение
    здесь видно и в приложении
    """
    from src.config.app_config import AppConfig
    from src.shared.constants import SVPURE_BYPASS_DEFAULT
    from src.services.tf2_paths import TF2Paths

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
    # молча выключало бы группировку дерева частиц
    if values.get('particles_group_tree') is None:
        values['particles_group_tree'] = True
    values['keep_temp_files'] = bool(values.get('keep_temp_files'))
    # Особые флаги VTF по умолчанию спрятаны: скину они либо безразличны, либо
    # (SSBump) вредны, а выглядят такой же безобидной галкой, как остальные
    values['advanced_vtf_flags'] = bool(values.get('advanced_vtf_flags'))
    values['debug_mode'] = bool(values.get('debug_mode'))
    values['parts_animation'] = bool(values.get('parts_animation'))
    # Анимации по умолчанию ВКЛЮЧЕНЫ: None здесь ломал бы круг «прочитал ->
    # сохранил» так же, как у panels_pinned
    if values.get('ui_animations') is None:
        values['ui_animations'] = True
    # Сохранение правок по умолчанию ВКЛЮЧЕНО: забытая работа - худший исход,
    # а человек не должен помнить про «сохранить»
    if values.get('save_edits') is None:
        values['save_edits'] = True
    # Плавающие панели - умолчание: прибитые требуют широкого окна, и в узком
    # они всё равно откажутся. None здесь ломал круг «прочитал -> сохранил»:
    # чтение отдавало None, запись - False, и настройки «менялись» сами
    if values.get('panels_pinned') is None:
        values['panels_pinned'] = False
    values['build_fx'] = _build_fx(values.get('build_fx'))
    values['model_cache_mb'] = _cache_cap(values.get('model_cache_mb'))
    # Мелочи раскладки правят на экране, а не здесь, но читает их страница
    # тем же запросом: настройки внешнего вида она спрашивает один раз
    for key in _UI_STATE:
        values[key] = _ui_value(key, cfg.get(key))

    return {
        'values': values,
        # Работает ли сохранённый путь к игре. Решает Python: проверка та же
        # (`TF2Paths.is_valid`), по которой работает всё остальное, и второй
        # её копии на странице быть не должно. Нужно, чтобы не показывать
        # кнопку автопоиска там, где искать уже нечего
        'tf2_ok': TF2Paths.is_valid(values['tf2_game_folder']),
        # Есть ли системный выбор папки: он есть только в окне приложения, в
        # обычном браузере путь вводят руками
        'folder_picker': _folder_picker is not None,
        'formats': ['VTF', 'PNG', 'TGA', 'JPG'],
        'languages': [{'value': 'ru', 'label': 'Русский'},
                      {'value': 'en', 'label': 'English'}],
        # Только темы, которые есть у страницы
        'themes': [{'value': 'light', 'label': t.get('theme_light', 'Light')},
                   {'value': 'dark', 'label': t.get('theme_dark', 'Dark')}],
        # Куда класть материалы, чтобы их пропустил sv_pure в казуале. Оба
        # способа рабочие, переключатель - страховка, если одну папку прикроют
        'bypass': [
            {'value': 'console', 'label': t.get('bypass_console', 'console\\')},
            {'value': 'vgui',
             'label': t.get('bypass_vgui', 'vgui\\replay\\thumbnails\\')},
        ],
        'bypass_tip': t.get('bypass_tooltip', ''),
        'cache_caps': list(_CACHE_CAPS),
        'support_url': SUPPORT_URL,
    }


@endpoint
def cache_size() -> Dict[str, object]:
    """
    Размер кэша декомпилированных моделей - отдельным вызовом

    Считается обходом всей папки кэша со `stat` на каждый файл: у меня 44 МБ
    кэша давали 0.2 с, у человека с большой библиотекой это уже секунды. Пока
    число входило в `settings()`, на него блокировалось открытие окна настроек
    и первый запрос страницы при старте - хотя нужно оно ровно для подписи
    рядом с кнопкой «очистить». Страница спрашивает его после отрисовки
    """
    return {'cache_mb': _cache_mb()}


#: Куда ведёт «Поддержать автора». Тот же адрес, что в окне приложения
SUPPORT_URL = ('https://steamcommunity.com/tradeoffer/new/'
               '?partner=394814324&token=GNGCagXk')


def _cache_mb() -> float:
    """Размер кэша декомпилированных моделей в мегабайтах"""
    try:
        from src.services.decompile_cache import get_cache_size_mb
        return round(float(get_cache_size_mb()), 1)
    except Exception:                                         # noqa: BLE001
        return 0.0


@endpoint
def clear_model_cache() -> Dict[str, object]:
    """Удаляет кэш декомпилированных моделей

    Нужен после обновления игры: старые разобранные модели остаются в кэше и
    собираются с прежней геометрией. Первая сборка каждого оружия после этого
    будет медленнее - кэш ради того и живёт
    """
    from src.services.decompile_cache import clear_cache

    was = _cache_mb()
    removed = int(clear_cache())
    return {'removed': removed, 'freed_mb': was}


@endpoint
def set_settings(values: Optional[Dict[str, object]] = None,
                 lang: str = '') -> Dict[str, object]:
    """
    Сохраняет настройки. Принимаются только известные ключи

    Блэклист приходит текстом (как в окне) и разбирается общим правилом.
    Пустая папка экспорта - это 'export': безымянная папка сломала бы сборку
    молча, на этапе записи файла
    """
    from src.config.app_config import AppConfig
    from src.data.material_filter import parse_blacklist

    lang = _lang(lang)
    # Под замком конфига: set_ui_state из другого потока между чтением и
    # записью потерялся бы
    with AppConfig.lock:
        cfg = AppConfig.load_config()
        was_cap = _cache_cap(cfg.get('model_cache_mb'))
        for key, value in (values or {}).items():
            if key not in _SETTINGS_KEYS:
                continue
            if key == 'material_blacklist':
                cfg[key] = (parse_blacklist(value) if isinstance(value, str)
                            else list(value or []))
            elif key == 'export_folder':
                cfg[key] = str(value or '').strip() or 'export'
            elif key == 'build_fx':
                cfg[key] = _build_fx(value)
            elif key == 'model_cache_mb':
                cfg[key] = _cache_cap(value)
            elif key in ('particles_group_tree', 'keep_temp_files', 'debug_mode',
                         'save_edits', 'panels_pinned', 'advanced_vtf_flags',
                         'parts_animation', 'ui_animations'):
                cfg[key] = bool(value)
            else:
                cfg[key] = str(value or '').strip()
        AppConfig.save_config(cfg)
    # «Режим отладки» включает уровень DEBUG, а не только сохранение временных
    # папок сборки
    from src.shared.logging_config import set_debug
    set_debug(bool(cfg.get('debug_mode')))
    cap = _cache_cap(cfg.get('model_cache_mb'))
    if cap and (not was_cap or cap < was_cap):
        # Потолок стал теснее: кэш ужимается сразу, а не при следующей
        # распаковке. Фоном - обход кэша идёт stat'ом по каждому файлу
        from src.services.decompile_cache import enforce_cache_limit
        threading.Thread(target=enforce_cache_limit, daemon=True).start()
    from src.app.session import session
    session().parts.refresh_parts_animation()
    return settings(lang)
