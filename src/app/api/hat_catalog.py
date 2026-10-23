"""Шапки и косметика: поиск, фильтры, карточка шапки"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from src.app.api._common import _lang, _t, endpoint


# Шапки и косметика

#: Категории, которые можно скрыть: медали и шапки, которые игра рисует только
#: в Хэллоуин. Значение живёт в общем конфиге (`hats_hidden_tags`), прежние
#: «holiday», «smissmas», «summer» там игнорируются
HAT_TAGS = ('medals', 'halloween')

def _model_file_name(mdl_path: str) -> str:
    """Имя файла модели без пути и расширения - подпись карточки косметики"""
    return mdl_path.replace(chr(92), "/").rsplit("/", 1)[-1].removesuffix(".mdl")


@endpoint
def hat_filters(lang: str = '') -> List[dict]:
    """
    Какие категории косметики можно скрыть и что скрыто сейчас

    Имя короткое, подсказка полная: в ряду фильтров «Скрыть сезонные
    (Christmas и др.)» не помещается, а на кнопке нужно одно слово
    """
    from src.app.session import session
    from src.data.hats_parser import parse_hats

    lang = _lang(lang)
    t = _t(lang)
    hidden = hidden_hat_tags()
    # Число на кнопке объясняет её лучше подсказки: «Хэллоуин 473» - сразу
    # видно, что и сколько она прячет. Список в памяти, подсчёт дешёвый
    counts: Dict[str, int] = {}
    paths = session().tf2_paths()
    for h in ([] if 'error' in paths else parse_hats(paths['root'], lang)):
        tag = 'medals' if h.is_medal else 'halloween' if h.is_halloween else ''
        if tag:
            counts[tag] = counts.get(tag, 0) + 1
    return [{'key': k,
             'name': t.get(f'hat_filter_{k}', k),
             'tip': t.get(f'hat_filter_{k}_tip', ''),
             'count': counts.get(k, 0),
             'hidden': k in hidden}
            for k in HAT_TAGS]


def hidden_hat_tags() -> List[str]:
    """Скрытые категории из общего конфига приложения"""
    from src.config.app_config import AppConfig

    saved = AppConfig.load_config().get('hats_hidden_tags') or []
    return [t for t in saved if t in HAT_TAGS]


@endpoint
def set_hat_filter(tag: str, hidden: bool) -> List[dict]:
    """
    Прячет или возвращает категорию косметики

    Пишем в тот же ключ конфига, что и панель шапок: настройка у приложения и
    веб-интерфейса общая, иначе они разошлись бы по показанному списку
    """
    from src.config.app_config import AppConfig

    if tag not in HAT_TAGS:
        return hat_filters()
    current = set(hidden_hat_tags())
    current.add(tag) if hidden else current.discard(tag)
    AppConfig.set('hats_hidden_tags', sorted(current))
    return hat_filters()


@endpoint
def hats(query: str = '', tf2_class: Optional[str] = None,
         region: str = '', collection: str = '',
         lang: str = '') -> Dict[str, object]:
    """
    Косметика TF2 из items_game.txt: {items, regions, collections, suggest}

    Скрытые категории берём из конфига (`hats_hidden_tags`) - так же, как
    панель шапок. Отдаём ВСЁ, что прошло фильтры: косметики 9504, и отрисовка
    полного списка стоит 56 мс - обрезать было незачем, а обрезанный список
    молча врал, что предмета в игре нет

    Поиск ранжирует: имя целиком, с начала, по началам слов, подстрока;
    ищет и по английскому имени, когда интерфейс русский. `regions` - фасет
    «куда надевается» с числами под текущим запросом и классом (без своего
    фильтра, иначе из «Лица» нельзя было бы уйти). `collections` - то же для
    коллекций игры, новые сверху. `suggest` - похожие имена, когда ничего не
    нашлось
    """
    from src.app.session import session
    from src.data.hats_parser import REGION_ORDER, parse_hats

    lang = _lang(lang)
    t = _t(lang)
    paths = session().tf2_paths()
    if 'error' in paths:
        return {'items': [], 'regions': [], 'collections': [], 'suggest': []}

    hidden = set(hidden_hat_tags())
    region = (region or '').strip().lower()
    collection = (collection or '').strip()
    # {ключ: [номер, название, число]} - фасет коллекций
    col_counts: Dict[str, list] = {}
    words = _hat_plain(str(query)).split()
    english = _english_names(paths['root']) if words and lang != 'en' else {}
    counts: Dict[str, int] = {}
    found = []
    names: List[str] = []
    for h in parse_hats(paths['root'], lang):
        if 'medals' in hidden and h.is_medal:
            continue
        if 'halloween' in hidden and h.is_halloween:
            continue
        if not h.matches([], tf2_class or None):
            continue
        names.append(h.name)
        rank = _hat_rank(h, words, english.get(h.defindex, ''))
        if rank is None:
            continue
        # Каждый фасет считается под ЧУЖИМ фильтром, но не под своим: иначе
        # из выбранной коллекции нельзя было бы увидеть соседние
        in_region = not region or h.region == region
        in_collection = not collection or h.collection == collection
        if in_collection:
            counts[h.region] = counts.get(h.region, 0) + 1
        if in_region and h.collection:
            col = col_counts.setdefault(
                h.collection, [h.collection_rank, h.collection_name, 0])
            col[2] += 1
        if in_region and in_collection:
            found.append((rank, h.name.lower(), h))
    found.sort(key=lambda f: (f[0], f[1]))
    return {
        'items': [_hat_row(h, t) for _, _, h in found],
        'regions': [{'key': k, 'name': t.get(f'hat_region_{k}', k), 'count': n}
                    for k in REGION_ORDER if (n := counts.get(k))],
        'collections': [{'key': k, 'name': name, 'count': n}
                        for k, (_, name, n) in sorted(
                            col_counts.items(), key=lambda kv: -kv[1][0])],
        'suggest': _hat_suggest(words, names, english) if words and not found else [],
    }


def _hat_plain(text: str) -> str:
    """Строка для сравнения: регистр, ё и знаки не считаются, слова - через
    пробел («Газиров-очки» -> «газиров очки», чтобы «очки» было началом слова)"""
    return ' '.join(re.sub(r'[^0-9a-zA-Zа-яёА-ЯЁ]+', ' ', text or '')
                    .lower().replace('ё', 'е').split())


def _hat_rank(h, words: List[str], english: str) -> Optional[int]:
    """0 - имя целиком, 1 - с начала, 2 - по началам слов, 3 - подстрока
    где угодно (в имени, внутреннем имени, классах); None - мимо"""
    if not words:
        return 0
    q = ' '.join(words)
    names = [n for n in (_hat_plain(h.name), _hat_plain(english)) if n]
    if q in names:
        return 0
    if any(n.startswith(q) for n in names):
        return 1
    parts = [p for n in names for p in n.split()]
    if all(any(p.startswith(w) for p in parts) for w in words):
        return 2
    blob = ' '.join([*names, _hat_plain(h.internal_name), h.classes_str.lower()])
    if all(w in blob for w in words):
        return 3
    return None


def _hat_suggest(words: List[str], names: List[str],
                 english: Dict[str, str]) -> List[str]:
    """Похожие имена: «Fedra» -> «Fancy Fedora». По сжатому виду, показываем
    как пишут"""
    import difflib

    vocab = {_hat_plain(n): n for n in [*names, *english.values()] if n}
    q = ' '.join(words)
    close = difflib.get_close_matches(q, list(vocab), n=3, cutoff=0.6)
    if close:
        return [vocab[c] for c in close]
    # По одному слову против слов имён: «fedra» - «fedora» из «Fancy Fedora»
    owner: Dict[str, str] = {}
    for plain, name in vocab.items():
        for w in plain.split():
            owner.setdefault(w, name)
    out: List[str] = []
    for w in words:
        for hit in difflib.get_close_matches(w, list(owner), n=2, cutoff=0.75):
            if owner[hit] not in out:
                out.append(owner[hit])
    return out[:3]


def _english_names(root: str) -> Dict[str, str]:
    """{defindex: английское имя} - чтобы русский интерфейс находил «glasses»"""
    from src.data.hats_parser import parse_hats
    return {h.defindex: h.name for h in parse_hats(root, 'en')}


@endpoint
def hat_item(key: str = '', lang: str = '') -> Dict[str, object]:
    """
    Предмет косметики по ключу - как строка `hats()`, но мимо фильтров

    Нужен сохранённой работе: у стилевой шапки без списка стилей нечем
    переключить стиль. Ключом бывает и модель стиля или класса - так писались
    старые работы
    """
    from src.app.session import session
    from src.data.hats_parser import parse_hats

    lang = _lang(lang)
    paths = session().tf2_paths()
    want = str(key or '').replace(chr(92), '/').lower()
    if 'error' in paths or not want:
        return {}
    for h in parse_hats(paths['root'], lang):
        own = [h.mdl_path, *(h.per_class_models or {}).values()]
        for st in h.styles or ():
            own.extend((st.get('per_class_models') or {}).values())
        if any(str(p).replace(chr(92), '/').lower() == want for p in own):
            return _hat_row(h, _t(lang))
    return {}


def _hat_row(h, t) -> Dict[str, object]:
    """Строка каталога косметики"""
    return {
        'key': h.mdl_path,
        'name': h.name,
        'cls': ', '.join(h.classes),
        'type': 'hat',
        'mode': 'hat',
        'icon': h.icon,
        # Имя файла модели - то же, что у оружия показано ключом
        # (c_scattergun). Целиком путь в подпись не влезает: у косметики
        # он вида models/workshop/player/items/demo/…
        'label': _model_file_name(h.mdl_path),
        # Мультиклассовая шапка: у каждого класса СВОЯ модель. Сборке нужны
        # все выбранные, а превью - одна конкретная: путь с %s ей не годится
        'per_class': dict(h.per_class_models or {}),
        'slot': h.slot,
        # Модельные стили шапки: у каждого СВОЯ геометрия (у «Только
        # камень» нет оправы). Отдаём их с моделями - выбор стиля меняет и
        # показ, и то, что уйдёт в сборку. Числа мало: по нему стиль не
        # загрузить
        'styles': [
            {'name': (st.get('name')
                      or t.get('hat_style_n', 'Style {n}').format(n=i + 1)),
             'per_class': dict(st.get('per_class_models') or {})}
            for i, st in enumerate(h.styles or [])
        ],
    }
