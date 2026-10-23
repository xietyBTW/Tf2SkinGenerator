"""Работы: библиотека сохранённого, черновики, история правок"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, endpoint
from src.app.api.hat_catalog import _model_file_name


@endpoint
def works(lang: str = '') -> List[dict]:
    """
    Сохранённые работы - списком, как предметы каталога

    Работа не возвращается молча при открытии предмета: список оружия
    показывает игру, а свои работы открываются отсюда. Иначе каталог показывал
    бы «Обрез», а на экране был бы ТВОЙ обрез

    Имя и обложку берём по опознанию, записанному в самой работе: показывать
    человеку `scout_c_scattergun__c_scattergun` незачем
    """
    from src.services import work_store

    lang = _lang(lang)
    return [{
        **row,
        'type': 'work',
        # Обложка - иконка предмета: без неё все работы выглядят одинаково.
        # У косметики это объявленная иконка, у оружия - ключ модели: слаг из
        # имени папки не годился ни там, ни там
        'icon': row['item_icon'] or row['item_key'] or row['work_item'],
        # Открывается как обычный предмет, только с восстановлением
        'mode': row['work_mode'],
    } for row in _named(work_store.list_saved(), lang)]


def _named(rows: List[dict], lang: str) -> List[dict]:
    """
    Работы с человеческим именем предмета и тем, из чего они открываются

    Опознание пишется в саму работу (`work_store.item_of`). Работы, записанные
    до этого, его не имеют - для них остаётся разбор имени папки: у оружия он
    даёт верный ключ, у шапки - слаг пути к модели
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
                    # открывается - из режима «hat» её путь не вывести
                    'item_key': key,
                    'per_class': dict(item.get('per_class') or {}),
                    'style': int(item.get('style') or 0),
                    'mod': item.get('mod') or '',
                    # Иконка косметики объявлена в items_game: по имени модели
                    # её не найти - у покласcовой шапки оно с суффиксом класса
                    # (`all_domination_scout`), а иконка одна на предмет
                    'item_icon': icon,
                    'name': (name
                             or _work_title(mode, key.lower() or slug, lang))})
    return out


def _hat_index(lang: str) -> Dict[str, tuple]:
    """
    Косметика по пути к модели: (имя, иконка из items_game)

    Собирается один раз на список: косметики 9504, и спрашивать каталог на
    каждую работу значило бы разбирать items_game по разу на карточку

    Путей у предмета несколько. В работе лежит тот, что показывали: у
    мультиклассовой шапки это модель КЛАССА, у стиля - модель стиля, и ни та,
    ни другая не равна основной (`all_domination_%s.mdl`). Поэтому в указателе
    все, а основная кладётся последней - при совпадении верна она
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


@endpoint
def drafts(lang: str = '') -> List[dict]:
    """
    Черновики автосохранения - для уборки

    В библиотеке их нет намеренно: оно пишет всё, к чему прикоснулись, и
    «просто открыл предмет» становилось модом. Но копии текстур при этом
    остаются на диске, и добраться до них можно было только заново открыв тот
    же предмет - то есть на практике никак. Размер отдаём рядом: «удалить 12
    черновиков» и «удалить 12 черновиков на 280 МБ» - разные решения
    """
    from src.services import work_store

    lang = _lang(lang)
    return [{**row, 'size': work_store.size_of(row['key'])}
            for row in _named(work_store.list_drafts(), lang)]


@endpoint
def forget_drafts(keys: Optional[List[str]] = None) -> Dict[str, object]:
    """Удаляет черновики (пустой список - все). Сохранённые работы не трогает"""
    from src.app.session import session
    return session().forget_drafts(keys)


def _work_title(mode: str, item: str, lang: str) -> str:
    """Человеческое имя предмета работы, не нашли - показываем ключ

    Ищем по тому же каталогу, что и список оружия: у работы своего имени нет,
    а показывать `scout_c_scattergun__c_scattergun` человеку незачем

    Косметику здесь не ищем - она приходит из items_game, и для списка её имена
    собирает `_hat_titles` один раз. Сюда шапка попадает, только когда предмет
    в игре не нашёлся: тогда имя файла модели честнее полного пути
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


@endpoint
def work_state() -> Dict[str, object]:
    """Есть ли у предмета правки и сохраняются ли они молча"""
    from src.app.session import session
    return session().work_state()


@endpoint
def keep_work() -> Dict[str, object]:
    """Сохраняет работу над предметом в библиотеку - по нажатию, не молча"""
    from src.app.session import session
    return session().keep_work()


@endpoint
def restore_work(lang: str = '') -> Dict[str, object]:
    """Возвращает отложенную работу над открытым сейчас предметом"""
    from src.app.session import session
    return session().restore_work(lang=_lang(lang))


@endpoint
def delete_work(key: str = '') -> Dict[str, object]:
    """Удаляет сохранённую работу из библиотеки вместе с её файлами

    Только то, что есть в списке сохранённых: ключ - имя папки, и чужой
    путь вроде «../» сюда не пройдёт. Открытый сейчас предмет не трогаем:
    его правки на экране остаются, в библиотеку они вернутся только по
    «Положить работу»
    """
    from src.services import work_store
    if key not in {w['key'] for w in work_store.list_saved()}:
        return {'error': 'Такой работы нет'}
    return {'deleted': work_store.forget(key)}


@endpoint
def forget_work(lang: str = '') -> Dict[str, object]:
    """Сбрасывает правки предмета - и в сеансе, и на диске"""
    from src.app.session import session
    return session().forget_work(lang=_lang(lang))


@endpoint
def undo_edits(delta: int = -1, lang: str = '') -> Dict[str, object]:
    """Шаг по истории правок предмета: -1 - отменить, 1 - вернуть.
    В ответе - состояние показа плюс `undo`/`redo`: есть ли куда ещё"""
    from src.app.session import session
    return session().undo_edits(delta, lang=_lang(lang))
