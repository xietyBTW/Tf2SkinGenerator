"""
Страница звуков: каталог записей игры, свои файлы вместо игровых и мод из них

Живёт отдельно от предмета: звуки выбирают на своей странице, и в состоянии
превью им места нет. От сеанса нужны только пути к игре (`tf2_paths`) и
папка экспорта (`_export_settings`)

Доступ - `session().sounds`; `api.py` зовёт его методы напрямую
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.shared.logging_config import get_logger
from src.shared.text_search import plain as _plain
from src.shared.validators import vpk_file_name

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


def _sound_title(entry, items: List[str], known: str,
                 classes: Dict[str, str]) -> str:
    """Подпись строки: чей это звук, человеческими словами

    Порядок источников - от точного к догадке. Предмет называет items_game,
    оружие опознаётся по имени субъекта, у реплики класс стоит прямо в имени
    записи (`Scout.PainSharp01`) или выведен из пути к файлу. Если молчат все
    - само имя субъекта
    """
    from src.data.sound_catalog import WHO_NAMES

    # Класс-субъект - раньше локализации: там он «ПОДРЫВНИК» капслоком с
    # экрана выбора класса, а в каталоге классы зовутся как в данных
    if entry.subject.lower() in classes:
        return classes[entry.subject.lower()]
    if items:
        return items[0]
    if known:
        return known
    who = entry.who[0] if entry.who else ''
    if who in classes:
        return classes[who]
    if '.' in entry.name:
        return entry.subject.replace('_', ' ')
    return WHO_NAMES.get(who) or entry.name.replace('_', ' ')


#: Строка без разделителей и регистра - для поиска. В именах записей звука
#: Valve непоследователен: `Weapon_Scatter_Gun` рядом с `Weapon_Shotgun`, и
#: буквальное совпадение подстроки половину названий не находит. «ё» и «е»
#: тоже одно и то же: «ракетомет» обязан находить «Ракетомёт»
def _score(row: Dict[str, Any], words: List[str]) -> float:
    """Насколько строка отвечает запросу. Меньше нуля - не отвечает вовсе

    Каждое слово обязано найтись, вес - по тому, ГДЕ нашлось: целый термин
    (имя предмета, класс, слот, группа) дороже его начала, начало - дороже
    вхождения в середину, а имя записи и путь файла - самое дешёвое. Так
    «bat» ставит биту выше «BatSaber», а тот - выше «combat»
    """
    total = 0.0
    terms = row['terms']
    for w in words:
        if w in terms:
            total += 8
        elif any(t.startswith(w) for t in terms):
            total += 4
        elif any(w in t for t in terms):
            total += 2
        elif w in row['name_plain']:
            total += 1
        elif w in row['blob']:
            total += 0.5
        else:
            return -1
    return total


class SoundsEditor:
    """Каталог звуков игры и свои файлы вместо игровых"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Свои звуки: {путь файла в игре: файл человека}. Только по файлам,
        #: не по записям: игра подменяет файл, а один файл бывает у девяти
        #: записей (`bat_miss.wav` - промах у девяти оружий), и хранить
        #: выбор по записи значило бы врать остальным восьми, что они
        #: нетронуты
        self._wave_picks: Dict[str, str] = {}
        #: Строки каталога на языке `_sound_lang` - разбор скриптов игры дорог
        self._sound_cache: List[Dict[str, Any]] = []
        self._sound_lang: Optional[str] = None
        self._sound_vocab_cache = None

    #: Сколько строк отдаём за раз. Записей в игре десять с половиной тысяч,
    #: и рисовать их все - секунды на пустом месте, дальше страница просит
    #: следующую порцию сама
    SOUND_PAGE = 400

    #: Фасеты страницы звуков - в том порядке, в каком их показывает колонка
    SOUND_FACETS = ('section', 'who', 'group', 'variant', 'format')

    def sounds(self, section: str = '', who: str = '', group: str = '',
               variant: str = '', fmt: str = '', own: bool = False,
               query: str = '', offset: int = 0,
               lang: str = 'ru') -> Dict[str, Any]:
        """Записи под фильтрами страницы и сами фильтры со счётчиками

        Один ответ на всё: строки, сколько их всего, и для каждого фасета -
        сколько записей стоит за каждым его значением. Счётчик фасета
        считается БЕЗ его собственного фильтра: выбрав «Scout», человек
        видит, сколько у солдата, а не ноль у всех, кроме разведчика.
        Раздел - ось главная, и его счётчики не зависят от остальных
        фасетов вовсе: словари групп у разделов разные, и «Выстрел» иначе
        гасил бы «Реплики»
        """
        from src.data import sound_catalog as sc

        rows = self._sound_rows(lang)
        section = (section or '').strip().lower()
        who = (who or '').strip().lower()
        group = (group or '').strip().lower()
        variant = (variant or '').strip().lower()
        fmt = (fmt or '').strip().lower()
        # Разделители убираем с обеих сторон: скаттерган в игре записан
        # `Weapon_Scatter_Gun`, и поиск «scattergun» его не находил
        words = [_plain(w) for w in (query or '').split() if _plain(w)]
        picks = self._wave_picks

        def is_own(row: Dict[str, Any]) -> bool:
            return any(w in picks for w in row['waves'])

        scores: Dict[str, float] = {}
        counts: Dict[str, Dict[str, int]] = {f: {} for f in self.SOUND_FACETS}
        #: Сколько записей стоит за «Все» в каждом фасете: сумма по значениям
        #: не годится, у дробовика четыре класса, и он считался бы четырежды
        every: Dict[str, int] = {f: 0 for f in self.SOUND_FACETS}
        hits: List[Dict[str, Any]] = []
        #: Разделы, которые прочитались вовсе. Вкладка раздела стоит всегда,
        #: даже когда под поиском в нём пусто: исчезающие вкладки читаются
        #: как поломка, а ноль при слове - как ответ
        present: set = set()
        for row in rows:
            present.add(row['section'])
            if own and not is_own(row):
                continue
            if words:
                score = _score(row, words)
                if score < 0:
                    continue
                scores[row['name']] = score
            ok = {
                'section': not section or row['section'] == section,
                'who': not who or who in row['who'],
                'group': not group or row['group'] == group,
                'variant': not variant or (variant == 'mvm') == row['mvm'],
                'format': not fmt or fmt in row['formats'],
            }
            if all(ok.values()):
                hits.append(row)
            tally = counts['section']
            tally[row['section']] = tally.get(row['section'], 0) + 1
            every['section'] += 1
            if not ok['section']:
                continue
            for facet in ('who', 'group', 'variant', 'format'):
                if not all(v for k, v in ok.items() if k != facet):
                    continue
                every[facet] += 1
                keys = ({'who': row['who'], 'group': (row['group'],),
                         'variant': ('mvm' if row['mvm'] else 'normal',),
                         'format': row['formats']})[facet]
                tally = counts[facet]
                for key in keys:
                    tally[key] = tally.get(key, 0) + 1

        classes = {c['key'].lower(): c['name'] for c in self._classes(lang)}
        who_names = {**{k: classes[k] for k in sc.CLASSES if k in classes},
                     **sc.WHO_NAMES}
        chosen = {'section': section, 'who': who, 'group': group,
                  'variant': variant, 'format': fmt}
        labels = {'section': sc.SECTION_NAMES, 'who': who_names,
                  'group': sc.GROUP_NAMES, 'variant': sc.VARIANT_NAMES,
                  'format': sc.FORMAT_NAMES}
        facets = {
            facet: [{'key': key, 'name': name, 'count': counts[facet].get(key, 0)}
                    for key, name in labels[facet].items()
                    if counts[facet].get(key) or key == chosen[facet]
                    or (facet == 'section' and key in present)]
            for facet in self.SOUND_FACETS}

        # Под поиском - по убыванию совпадения: «pistol» должен начинаться с
        # пистолета, а не с ракетницы, у которой пистолетный звук пустого
        # магазина. Без поиска - порядок скрипта: он и так группирует
        if words:
            hits.sort(key=lambda row: -scores[row['name']])
        # `own` подставляем ЗДЕСЬ, а не храним в строках: иначе выбор одного
        # звука обесценивал весь разобранный каталог, и следующий же список
        # стоил секунду на пересборку десяти тысяч записей. Копию делаем
        # только для порции, что уедет наружу
        offset = max(0, int(offset or 0))
        hidden = ('blob', 'terms', 'labels', 'name_plain')
        page = [{k: v for k, v in row.items() if k not in hidden}
                | self._own_state(row)
                for row in hits[offset:offset + self.SOUND_PAGE]]
        return {'rows': page, 'total': len(hits), 'offset': offset,
                'facets': facets, 'all': every,
                # Ничего не нашлось - может, опечатка: «scatergun»
                'suggest': (self._suggest(words, section, lang)
                            if words and not hits else []),
                # Пустой список сам по себе ничего не объясняет: страница по
                # этому флагу отличает «сузил до нуля» от «скрипты игры не
                # прочитались»
                'loaded': bool(rows),
                # Сколько своих звуков выбрано ВСЕГО. Страница видит только
                # свою порцию списка, и считать по ней - значит терять
                # выбранное, как только сменишь фильтр
                'picked': self._picked_total(),
                'files': len(picks)}

    def _own_state(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Что у записи заменено: {own, own_waves, partial}

        `own` - свой файл, если он один на все файлы записи; `own_waves` -
        по каждому файлу, откуда бы замена ни пришла (и через другую
        запись с тем же файлом); `partial` - заменена часть
        """
        picks = self._wave_picks
        own_waves = {w: picks[w] for w in row['waves'] if w in picks}
        paths = set(own_waves.values())
        whole = len(own_waves) == len(row['waves']) and len(paths) == 1
        return {'own': next(iter(paths)) if whole else '',
                'own_waves': own_waves,
                'partial': bool(own_waves) and not whole}

    def _suggest(self, words: List[str], section: str,
                 lang: str) -> List[str]:
        """Похожие слова из словаря раздела: «scatergun» -> «scattergun»

        Словарь - как записи ЗОВУТ (имена предметов, классы, группы), без
        имён файлов и ключей моделей: там мусора больше, чем подсказок.
        Сравниваем по сжатому виду, показываем как пишут
        """
        import difflib

        vocab = self._sound_vocab(section, lang)
        out: List[str] = []
        # Сначала запрос целиком: «rocket lancher» - это «rocket launcher»,
        # а не «rocket» и «launcher» по отдельности
        whole = ''.join(words)
        for near in difflib.get_close_matches(whole, vocab, n=2, cutoff=0.8):
            if near != whole and vocab[near] not in out:
                out.append(vocab[near])
        for w in words if not out else ():
            for near in difflib.get_close_matches(w, vocab, n=2, cutoff=0.72):
                label = vocab[near]
                if near != w and label not in out:
                    out.append(label)
        return out[:3]

    def _sound_vocab(self, section: str, lang: str) -> Dict[str, str]:
        """{сжатое слово: как пишут} по разделу - один раз на язык и раздел"""
        key = (section, lang)
        cache = getattr(self, '_sound_vocab_cache', None)
        if cache is None:
            cache = self._sound_vocab_cache = {}
        if key not in cache:
            vocab: Dict[str, str] = {}
            for row in self._sound_rows(lang):
                if section and row['section'] != section:
                    continue
                for label in row['labels']:
                    plain = _plain(label)
                    # С цифрами - имена файлов-сирот (`rocket1`), не слова
                    if (len(plain) > 2 and '_' not in label
                            and not any(c.isdigit() for c in plain)):
                        vocab.setdefault(plain, label)
            cache[key] = vocab
        return cache[key]

    def _classes(self, lang: str) -> List[Dict[str, str]]:
        from src.app.api import classes as api_classes
        return [c for c in api_classes(lang) if c.get('key')]

    def _by_item(self, guess: Dict[str, tuple], item: str):
        """Предмет по его имени в игре. None - такого имени нет

        Половина названий в игре с артиклем («The Buff Banner»), а называют их
        без него - пробуем оба вида
        """
        for stem in (_plain(item), 'the' + _plain(item)):
            found = guess.get(stem)
            if found and found[2]:
                return found
        return None

    def _rows_any(self) -> List[Dict[str, Any]]:
        """Каталог на ТОМ языке, что уже разобран

        Проверке формата и сборке язык безразличен - им нужны имена и файлы.
        Спросив каталог на своём языке, они выбрасывали чужой разбор, и
        страница платила за него ещё раз: две лишних секунды на каждый выбор
        """
        return self._sound_rows(self._sound_lang or 'en')

    def _sound_rows(self, lang: str = 'ru') -> List[Dict[str, Any]]:
        """Каталог звуков как словари. Считается один раз на язык"""

        from src.data import sound_catalog
        from src.data.hats_parser import parse_localization
        from src.data.weapon_model_index import get_items_game_path

        if getattr(self, '_sound_lang', None) == lang:
            return self._sound_cache
        paths = self._host.tf2_paths()
        if 'error' in paths:
            return []
        # Сам звук лежит в своём VPK: скрипты в общем, файлы в `tf2_sound_*`.
        # Без него не нашлись бы «ничьи» файлы - те, чью связку с событием
        # Valve держит в зашифрованных `tf_weapon_*.ctx`
        entries = sound_catalog.load(
            [*self.sound_vpks(paths['tf_dir']),
             paths['misc_vpk'], paths['textures_vpk']],
            get_items_game_path(paths['root']))
        # Предметы в items_game названы токенами (`TF_HamShank`) - человеку
        # нужно имя из игры
        loc = parse_localization(paths['root'],
                                 'russian' if lang == 'ru' else 'english')
        # Английские имена - в поиск: их знают и те, кто играет по-русски
        loc_en = (loc if lang != 'ru'
                  else parse_localization(paths['root'], 'english'))
        titles = sound_catalog.GROUP_NAMES
        # items_game называет предмет лишь у каждой шестой записи. Остальные
        # опознаём по имени субъекта: `Weapon_Ambassador` - это `TF_Ambassador`
        # в локализации и `c_ambassador` в каталоге оружия. Без этого «посол» и
        # «нож» в поиске не находились вовсе: имена записей латинские
        guess = self._subject_index(loc, lang)
        classes = {c['key'].lower(): c['name'] for c in self._classes(lang)}
        who_names = {**classes, **sound_catalog.WHO_NAMES}
        rows = []
        for entry in entries:
            items = [loc.get(token, loc.get(token.lower(), token))
                     for token in entry.items]
            items_en = [loc_en.get(token, loc_en.get(token.lower(), ''))
                        for token in entry.items]
            stem = _plain(entry.subject.removeprefix('Weapon_')
                          .removeprefix('Weapon'))
            found = guess.get(stem, ('', (), '', ()))
            named = ''
            if not found[2]:
                # Рабочее имя Valve в звуке и имя предмета в игре сходятся не
                # всегда: миниган там `Gatling`, «Мачина» - `SniperRailgun`
                named = sound_catalog.SUBJECT_ITEMS.get(entry.subject, '')
                if named:
                    found = self._by_item(guess, named) or found
            known, cls, weapon_key = found[:3]
            aliases = found[3] if len(found) > 3 else ()
            if not known:
                # Постройки: предмета нет, имя в игре есть
                for word in sound_catalog.words_of(entry.subject):
                    token = sound_catalog.BUILDING_TOKENS.get(word)
                    if token:
                        known = loc.get(token, '')
                        aliases = (loc_en.get(token, ''),)
                        break
            # Чей звук - от точного к догадке: items_game, каталог оружия,
            # имя записи. Нет ничего - «прочие»: без ключа под фильтром до
            # строки не добраться
            who = list(entry.classes or cls or entry.who) or ['other']
            # У звуков мира говорящего нет (см. `make_entry`), а догадка по
            # имени субъекта тут ложная: `Grenade.Roll` - не чья-то граната
            if entry.section == 'world':
                who = ['other']
            title = _sound_title(entry, items, known, classes)
            row = {
                'name': entry.name, 'event': entry.event,
                'group': entry.group, 'section': entry.section,
                'group_name': titles.get(entry.group, entry.group),
                'waves': list(entry.waves),
                # Дубли, свёрнутые в запись: по ним страница подписывает
                # файлы именами записей игры
                'takes': list(entry.takes),
                'channel': entry.channel, 'volume': entry.volume,
                'level': entry.level, 'pitch': entry.pitch,
                'formats': sorted({w.rsplit('.', 1)[-1].lower()
                                   for w in entry.waves}),
                'items': items,
                'who': who,
                'mvm': entry.mvm,
                # У предмета берём его иконку из рюкзака, у остального -
                # картинку по субъекту: портрет класса, значок постройки
                'icon': weapon_key or sound_catalog.icon_for(
                    entry.subject, entry.section, who[0]),
                # Подпись карточки: у связанной записи это сам предмет, иначе
                # опознанное по имени, иначе класс или само имя субъекта
                'title': title,
            }
            # Слова для поиска - один раз здесь, а не на каждую букву. Термины
            # - то, по чему запись ЗОВУТ: имя предмета на обоих языках, ключ
            # модели, класс, слот, группа, совпадение с ними весит больше,
            # чем случайное вхождение в путь файла (см. `_score`).
            # `labels` - те же слова, но как их пишут люди: из них
            # собираются подсказки «возможно, вы имели в виду»
            row['labels'] = tuple(dict.fromkeys(
                t.strip().lower() for t in (
                    title, *items, *items_en, *aliases, named,
                    *(who_names.get(w, '') for w in who), row['group_name'],
                    entry.group)
                if t.strip()))
            row['terms'] = tuple(dict.fromkeys(
                _plain(t) for t in (
                    title, *items, *items_en, *aliases, named, stem,
                    *(who_names.get(w, '') for w in who),
                    entry.group, row['group_name'])
                if _plain(t)))
            # Поля через пробел, внутри поля разделителей нет: скаттерган в
            # игре записан `Weapon_Scatter_Gun`, и «scattergun» обязан
            # находиться, а склеивать соседние поля в одно слово незачем
            row['name_plain'] = _plain(entry.name)
            row['blob'] = ' '.join(
                [*row['terms'], row['name_plain'],
                 *(_plain(w) for w in entry.waves)])
            rows.append(row)
        # Общие файлы: у кого ещё стоит тот же файл. Игра подменяет файл, и
        # заменив «промах» у биты, человек заменил его и у бутылки - об этом
        # надо сказать до сборки, а не после
        owners: Dict[str, List[str]] = {}
        for row in rows:
            for wave in row['waves']:
                owners.setdefault(wave, []).append(row['name'])
        for row in rows:
            shared = {w: [n for n in owners[w] if n != row['name']]
                      for w in row['waves'] if len(owners[w]) > 1}
            row['shared'] = shared
            row['shared_count'] = len({n for names in shared.values()
                                       for n in names})
        self._sound_lang, self._sound_cache = lang, rows
        self._sound_vocab_cache = {}
        return rows

    def _subject_index(self, loc: Dict[str, str],
                       lang: str) -> Dict[str, tuple]:
        """{сжатое имя субъекта: (название предмета, классы, иконка)}

        Два источника: локализация знает больше всего названий
        (`Weapon_Scatter_Gun` -> «Обрез»), каталог оружия - единственный, кто
        знает КЛАСС и картинку. Чего нет ни там, ни там, получает значок
        раздела (`icon_for`) - на строку без картинки это не похоже

        Каталог индексируется и по ключу модели, и по имени на ОБОИХ языках:
        `SUBJECT_ITEMS` называет предметы по-английски, и в русском
        интерфейсе «Machina» иначе не находилась. Классов у предмета
        бывает несколько - дробовик носят четверо, - и копятся все
        """
        from src.data.weapons import (
            TF2_WEAPONS, WEAPON_SLOT_TYPES, get_weapon_type_name,
        )

        out: Dict[str, tuple] = {}
        for token, value in loc.items():
            if not token.lower().startswith('tf_'):
                continue
            stem = _plain(token[3:].removeprefix('Weapon_').removeprefix('weapon_'))
            if stem and stem not in out:
                out[stem] = (value, (), '', ())

        for cls_name, slots in TF2_WEAPONS.items():
            cls = cls_name.lower()
            for slot, weapons in slots.items():
                # Тело и руки класса - не оружие
                if slot not in WEAPON_SLOT_TYPES:
                    continue
                # Слот на обоих языках - тоже слово для поиска: «scout melee»
                # должен находить биту, а «основное» - обрез
                slot_terms = (slot, get_weapon_type_name(slot, 'ru'),
                              get_weapon_type_name(slot, 'en'))
                for key, names in weapons.items():
                    if isinstance(names, dict):
                        title = names.get(lang, names.get('ru', key))
                        aliases = tuple(dict.fromkeys(names.values()))
                    else:
                        title, aliases = names, (names,)
                    bare = key.removeprefix('c_').removeprefix('v_')
                    # Ключ каталога часто с хвостом класса (`c_flaregun_pyro`),
                    # а в звуке его нет - заводим и укороченный вид
                    stems = {_plain(bare), _plain(bare.removesuffix('_' + cls)),
                             *(_plain(a) for a in aliases)}
                    terms = (*aliases, bare, *slot_terms)
                    for stem in stems:
                        if not stem:
                            continue
                        was_name, was_cls, was_key, was_terms = out.get(
                            stem, ('', (), '', ()))
                        out[stem] = (was_name or title,
                                     tuple(dict.fromkeys((*was_cls, cls))),
                                     was_key or key,
                                     tuple(dict.fromkeys((*was_terms, *terms))))
        return out


    def set_sound(self, name: str, path: Optional[str],
                  wave: str = '') -> Dict[str, Any]:
        """Кладёт свой файл на запись целиком или на один её файл

        `wave` - путь файла в игре. Пусто - замена на всю запись: у неё файлов
        бывает несколько, и обычно это варианты одного звука, которые меняют
        разом
        """
        name = (name or '').strip()
        wave = (wave or '').strip()
        from src.services.sound_build_service import check_wav

        if not name:
            return {'error': 'Не выбран звук'}
        if wave:
            return self._set_wave(name, wave, path)
        # Записи с таким именем может не быть вовсе: тогда сборка её
        # молча пропустит, а в подвале будет висеть «Своих звуков: 1»
        row = self._row(name)
        if row is None:
            return {'error': 'Такой записи в игре нет'}
        skipped = 0
        if not path:
            for w in row['waves']:
                self._wave_picks.pop(w, None)
        else:
            trouble = (self._wrong_format(row['waves'], path)
                       or check_wav(path))
            if trouble:
                return {'error': f'Файл не подойдёт: {trouble}'}
            # Только совпавшие по расширению: у части записей файлы разных
            # форматов вперемешку, и WAV, положенный под именем `.mp3`,
            # дал бы в игре тишину вместо звука
            kind = path.rsplit('.', 1)[-1].lower()
            fit = [w for w in row['waves'] if w.lower().endswith('.' + kind)]
            skipped = len(row['waves']) - len(fit)
            self._wave_picks.update({w: path for w in fit})
        return {'name': name, **self._own_state(row),
                'total': self._picked_total(), 'files': len(self._wave_picks),
                'skipped': skipped, 'affected': self._affected(row['waves'])}

    def _affected(self, waves: List[str]) -> Dict[str, Dict[str, Any]]:
        """Состояние всех записей, где стоят эти файлы, включая чужие

        Заменив «промах» у биты, человек заменил его и у бутылки: её строка
        на странице обязана это показать сразу, а не после перезагрузки
        """
        touched = set(waves)
        return {r['name']: self._own_state(r) for r in self._rows_any()
                if touched.intersection(r['waves'])}

    def _row(self, name: str) -> Optional[Dict[str, Any]]:
        """Запись каталога по имени. None - такой в игре нет"""
        return next((r for r in self._rows_any() if r['name'] == name), None)

    def _picked_total(self) -> int:
        """Сколько записей затронуто заменами - включая те, до которых
        замена дошла через общий файл"""
        picks = self._wave_picks
        if not picks:
            return 0
        return sum(1 for r in self._rows_any()
                   if any(w in picks for w in r['waves']))

    def clear_sounds(self) -> Dict[str, Any]:
        """Снимает все свои звуки разом"""
        self._wave_picks.clear()
        return {'total': 0, 'files': 0}

    def _set_wave(self, name: str, wave: str,
                  path: Optional[str]) -> Dict[str, Any]:
        """То же, но для ОДНОГО файла записи"""
        row = self._row(name)
        if row is None or wave not in row['waves']:
            return {'error': 'Такого файла у этой записи нет'}
        if not path:
            self._wave_picks.pop(wave, None)
        else:
            from src.services.sound_build_service import check_wav

            trouble = self._wrong_format([wave], path) or check_wav(path)
            if trouble:
                return {'error': f'Файл не подойдёт: {trouble}'}
            self._wave_picks[wave] = path
        return {'name': name, 'wave': wave, **self._own_state(row),
                'total': self._picked_total(), 'files': len(self._wave_picks),
                'affected': self._affected([wave])}

    @staticmethod
    def _wrong_format(waves: List[str], path: str) -> str:
        """Пусто, если расширение файла подходит этим путям. Иначе - чем плохо

        Игра зовёт файл по имени из записи, вместе с расширением: положив WAV
        под именем `.mp3`, мы получим в игре тишину. Реплики почти все в MP3,
        оружие почти всё в WAV - перепутать легко

        У полусотни записей файлы РАЗНЫХ расширений вперемешку (у моторки
        разведчика и wav, и mp3). Годится файл, совпавший хоть с одним: свои
        достанутся им, чужие останутся игровыми (см. `build_sounds`)
        """
        want = {w.rsplit('.', 1)[-1].lower() for w in waves}
        got = (path or '').rsplit('.', 1)[-1].lower()
        if not want or got in want:
            return ''
        return ('игра ждёт здесь {}, а это {} - звук просто не зазвучит'
                .format('/'.join(sorted(k.upper() for k in want)),
                        got.upper() or '?'))

    def sound_vpks(self, tf_dir: str) -> List[str]:
        """Все звуковые VPK игры плюс общий

        Скрипты лежат в `tf2_misc`, а сами файлы - в отдельных архивах, и их
        несколько: `tf2_sound_misc` и по одному на язык озвучки
        (`tf2_sound_vo_english`). Имена не перечисляем - у человека может быть
        поставлена другая озвучка, и реплики из неё молчали бы
        """
        import os

        out: List[str] = []
        # Рядом с `tf` лежит `hl2` - общее содержимое движка. Часть звуков
        # игрока и мира (`common/wpn_select.wav`, `items/smallmedkit1.wav`)
        # взята оттуда, и в архивах TF2 их нет вовсе
        for folder in (tf_dir, os.path.join(os.path.dirname(tf_dir), 'hl2')):
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                continue
            out += [os.path.join(folder, name) for name in names
                    if name.endswith('_dir.vpk') and '_sound' in name]
        return out

    def sound_bytes(self, wave_path: str) -> Optional[bytes]:
        """Игровой звуковой файл как есть - странице его проигрывать"""

        from src.services import vtf_preview_service as vps

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return None
        name = 'sound/' + (wave_path or '').replace(chr(92), '/').lstrip('/')
        # Скрипт пишет имя как попало (`vo/heavy_PainSevere01.mp3`), а в архиве
        # всё лежит строчными: у Valve так во всех звуковых VPK. Игра при
        # поиске регистр не различает, библиотека - различает
        for pak in vps.open_vpks([*self.sound_vpks(paths['tf_dir']),
                                  paths['misc_vpk']]):
            for candidate in (name, name.lower()):
                try:
                    return pak[candidate].read()
                except KeyError:
                    continue
        return None

    def save_sound(self, name: str, wave: str = '') -> Dict[str, Any]:
        """Кладёт игровой звук записи в папку экспорта

        Чтобы переделать звук, его сперва надо достать. Сохраняем ИГРОВОЙ
        звук, а не выбранный: свой у человека и так на диске
        """
        row = self._row(name)
        if row is None:
            return {'error': 'Такой записи в игре нет'}

        # Один файл или все - у записи их бывает до восьмидесяти
        wanted = ([wave] if wave in row['waves'] else
                  [] if wave else list(row['waves']))
        if not wanted:
            return {'error': 'Такого файла у этой записи нет'}

        export_folder, _ = self._host._export_settings()
        os.makedirs(export_folder, exist_ok=True)
        saved: List[str] = []
        for wave in wanted:
            data = self.sound_bytes(wave)
            if not data:
                continue
            # Только имя файла: путь внутри игры сюда переносить незачем, а
            # `..` в нём увёл бы запись мимо папки экспорта
            target = os.path.join(export_folder, os.path.basename(wave))
            try:
                with open(target, 'wb') as f:
                    f.write(data)
            except OSError as exc:
                return {'error': f'Не удалось сохранить: {exc}'}
            saved.append(target)
        if not saved:
            return {'error': 'Файла этого звука в игре нет'}
        logger.info(f"[звук] сохранено из игры: {len(saved)} в {export_folder}")
        return {'path': saved[0], 'files': len(saved)}

    def build_sounds(self, filename: str = '') -> Dict[str, Any]:
        """Собирает VPK из выбранных звуков

        Заменяем ВСЕ файлы записи: у полутора сотен записей их несколько, игра
        берёт случайный, и подменив один мы бы слышали свой звук через раз
        """
        from src.services import sound_build_service as builder

        if not self._wave_picks:
            return {'error': 'Не выбрано ни одного своего звука'}
        by_wave = dict(self._wave_picks)

        from src.shared.validators import validate_vpk_filename

        export_folder, _ = self._host._export_settings()
        name = vpk_file_name(filename, 'sounds_mod')
        # Имя приходит из поля на странице и становится путём файла: тем же
        # правилом, что у сборки текстур, отсекаем слэши и точки-родители
        good, trouble = validate_vpk_filename(name)
        if not good:
            return {'error': trouble}
        try:
            path = builder.build(by_wave, name, export_folder)
        except Exception as exc:                          # noqa: BLE001
            logger.error(f"[звук] сборка не удалась: {exc}", exc_info=True)
            return {'error': str(exc)}
        logger.info(f"[звук] собрано: {path}")
        return {'path': path, 'files': len(by_wave),
                'sounds': self._picked_total()}
