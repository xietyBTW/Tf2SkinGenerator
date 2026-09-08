"""
Хранилище правок: что человек сделал над предметом, между запусками.

Зачем. Положенная текстура, своя геометрия и правленый QC не берутся ниоткуда:
их либо сохранили, либо потеряли. Всё остальное (имена материалов, игровые
оригиналы, кадры команд) модель отдаёт заново при каждой загрузке, и хранить
его нельзя — замёрзнут пути во временные папки.

Ключ — ПРЕДМЕТ, а не мод: та же потеря происходит с обычным оружием, и второй
такой же механизм для него заводить незачем.

Файлы, на которые ссылаются правки, копируются к себе. Причина та же, что у
библиотеки модов: текстура, пришедшая через браузер, лежит во временной папке
системы, и сохранённая работа рассыпалась бы при первой же её чистке.
"""

from __future__ import annotations

import filecmp
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

from src.shared.logging_config import get_logger
from src.shared.paths import data_dir

logger = get_logger(__name__)

#: Рядом с export и mods: это данные пользователя, а не служебный кэш.
WORK_DIR = data_dir() / 'work'

#: Версия формата. Файл от другой версии не читаем — правила «моё/производное»
#: могут разойтись, и молча применённый чужой формат хуже потерянной работы.
FORMAT = 1


def work_dir() -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    return WORK_DIR


#: Потолок длины имени папки. Не про красоту: путь работы уходит вглубь
#: (`work/<ключ>/files/<файл>`), а у Windows есть предел на путь целиком.
_KEY_MAX = 120


def key_for(mode: str, item: str = '') -> str:
    """
    Имя папки работы по предмету.

    Режим плюс ключ предмета: у оружия это `scout_c_scattergun` + `c_scattergun`,
    у мода — `custom` + имя файла в библиотеке. Всё, что не буква и не цифра,
    сводим к подчёркиванию: ключом бывает и путь к MDL.

    Слишком длинное имя дополняем отпечатком полного ключа. Раньше оно просто
    обрезалось, а у мастерской пути длинные и различаются В КОНЦЕ
    (`…/hwn2019_horns/hwn2019_horns_demo.mdl`): два предмета сходились в одну
    папку, и работа над вторым молча открывалась поверх первого.
    """
    raw = f"{mode}__{item}" if item else str(mode)
    slug = re.sub(r'[^a-zA-Z0-9._-]+', '_', raw).strip('_').lower()
    if len(slug) > _KEY_MAX:
        mark = hashlib.sha1(slug.encode('utf-8')).hexdigest()[:8]
        slug = f"{slug[:_KEY_MAX - len(mark) - 1]}_{mark}"
    return slug or 'unknown'


def _folder(key: str) -> Path:
    folder = work_dir() / key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _own_part_image(spec, files_dir: Path):
    """Копия картинки части рядом с работой; настройка посадки сохраняется."""
    if isinstance(spec, dict):
        owned = _own_file(spec.get('path'), files_dir)
        return {**spec, 'path': owned} if owned else None
    return _own_file(spec, files_dir)


def _own_file(path: Optional[str], files_dir: Path) -> Optional[str]:
    """
    Кладёт файл рядом с работой и отдаёт новый путь.

    Файл, который уже внутри нашей папки, не копируется: иначе каждое
    сохранение плодило бы копию копии.
    """
    if not path or not os.path.isfile(path):
        return None
    src = Path(path).resolve()
    files_dir.mkdir(parents=True, exist_ok=True)
    if src.parent == files_dir.resolve():
        return str(src)

    target = files_dir / src.name
    # Разные материалы могут ссылаться на разные файлы с одинаковым именем.
    # Сравниваем СОДЕРЖИМОЕ, а не размер: два `texture.png` одного размера —
    # обычное дело (одна программа, одни размеры), и работа тогда молча
    # показывала на месте второй текстуры первую.
    if target.exists() and not filecmp.cmp(str(src), str(target), shallow=False):
        stem, suffix = target.stem, target.suffix
        for i in range(1, 1000):
            candidate = files_dir / f"{stem}_{i}{suffix}"
            if not candidate.exists() or filecmp.cmp(str(src), str(candidate),
                                                     shallow=False):
                target = candidate
                break
    if not target.exists():
        shutil.copy2(src, target)
    return str(target)


def _own_paths(edits: Dict[str, object], files_dir: Path) -> Dict[str, object]:
    """
    Заменяет пути в правках на свои копии.

    Места перечислены явно, а не обходом по всему словарю: так видно, что
    именно считается файлом, и случайная строка не превратится в копию.
    """
    out = dict(edits)

    out['textures'] = {
        team: {mat: owned for mat, path in (paths or {}).items()
               if (owned := _own_file(path, files_dir))}
        for team, paths in (edits.get('textures') or {}).items()
    }
    out['skin_overrides'] = {
        skin: {mat: owned for mat, path in (paths or {}).items()
               if (owned := _own_file(path, files_dir))}
        for skin, paths in (edits.get('skin_overrides') or {}).items()
    }
    # Картинки частей: без своей копии «покрасил ствол» пропадало бы, стоило
    # человеку переложить исходник в другую папку. Запись бывает и строкой (так
    # писали до окна посадки), и словарём с настройкой — копируем файл, а
    # остальное оставляем как есть.
    out['part_textures'] = {
        mat: {part: owned for part, spec in (items or {}).items()
              if (owned := _own_part_image(spec, files_dir))}
        for mat, items in (edits.get('part_textures') or {}).items()
    }
    out['australium_user_tex'] = _own_file(
        edits.get('australium_user_tex'), files_dir)
    out['custom_smd_path'] = _own_file(edits.get('custom_smd_path'), files_dir)

    maps: Dict[str, dict] = {}
    for mat, by_id in (edits.get('texture_maps') or {}).items():
        clean = {}
        for map_id, spec in (by_id or {}).items():
            spec = dict(spec or {})
            if spec.get('image'):
                owned = _own_file(spec['image'], files_dir)
                if not owned:
                    continue          # картинки больше нет — карта без неё пуста
                spec['image'] = owned
            clean[map_id] = spec
        if clean:
            maps[mat] = clean
    out['texture_maps'] = maps
    return out


def _strings(node: object) -> Iterator[str]:
    """Все строки из правок — вглубь по словарям и спискам.

    Обход общий, а не по перечисленным местам, как в `_own_paths`: там ошибка
    означала бы лишнюю копию, здесь — удалённый файл. Лишняя строка, принятая
    за путь, всего лишь оставит файл на диске, и это правильная сторона.
    """
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _strings(value)


def _same(path: str) -> str:
    """Путь в виде, годном для сравнения: Windows не различает регистр."""
    return os.path.normcase(str(Path(path).resolve()))


def _sweep(files_dir: Path, owned: Dict[str, object],
           keep: Iterable[str] = ()) -> int:
    """
    Убирает копии, на которые больше никто не ссылается.

    Склейка частей приходит каждый раз НОВЫМ именем (`parts_7.png`) — иначе
    браузер показал бы предыдущую из кэша. Копия оставалась здесь навсегда: у
    одного пистолета накопилось 24 МБ, из которых работе нужен был один файл.

    Ходим только по своей папке и только после успешной записи: удалять по
    правкам, которые не легли на диск, значило бы стирать живую работу.
    """
    if not files_dir.is_dir():
        return 0
    # Сравниваем разрешёнными путями: `_own_file` отдаёт resolve(), а обход
    # папки — то, что склеено из WORK_DIR (он относительный). Одна и та же
    # копия в двух видах выглядела бы разными файлами — и была бы удалена.
    alive = {_same(p) for p in list(_strings(owned)) + [k for k in keep if k]}
    dropped = 0
    for file in files_dir.iterdir():
        if not file.is_file():
            continue
        if _same(str(file)) in alive:
            continue
        try:
            file.unlink()
            dropped += 1
        except OSError:
            pass          # занят или уже нет — не повод рушить сохранение
    return dropped


def item_of(key: str) -> Dict[str, object]:
    """
    Чем предмет работы опознаётся, кроме имени папки. Пусто — не записано.

    Имя папки — слаг: у шапки от `models/player/items/…/hat.mdl` в нём
    остаётся `models_player_items_…_hat.mdl`, и по такому ключу не найти ни
    имени в каталоге, ни иконки, ни самой модели. Поэтому рядом с правками
    лежит то, из чего работа открывается.
    """
    path = WORK_DIR / key / 'edits.json'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    item = payload.get('item')
    return dict(item) if isinstance(item, dict) else {}


def save(key: str, edits: Dict[str, object],
         keep: Iterable[str] = (),
         item: Optional[Dict[str, object]] = None) -> Optional[Path]:
    """Сохраняет правки предмета. Пишем через временный файл: две вкладки
    могут сохранять одновременно, и половина файла хуже его отсутствия.

    ``keep`` — файлы, которых в этих правках нет, но которые всё ещё нужны
    (снимки неактивных стилей шапки живут только в памяти сеанса). Без этой
    подсказки уборка забрала бы картинку соседнего стиля.

    ``item`` — чем опознаётся предмет (см. `item_of`). None означает «не знаю»,
    и тогда записанное раньше остаётся: терять опознание из-за вызова, который
    про него не думал, работа не должна.
    """
    if not key or not edits:
        return None

    folder = _folder(key)
    files_dir = folder / 'files'
    owned = _own_paths(edits, files_dir)
    payload = {'format': FORMAT, 'edits': owned}
    item = dict(item) if item else item_of(key)
    if item:
        payload['item'] = item
    target = folder / 'edits.json'
    tmp = folder / 'edits.json.tmp'
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding='utf-8')
        os.replace(tmp, target)
    except OSError as exc:
        logger.warning(f"работа «{key}» не сохранена: {exc}")
        return None
    _sweep(files_dir, owned, keep)
    return target


def load(key: str) -> Optional[Dict[str, object]]:
    """
    Возвращает правки предмета или None.

    Пути, файлов по которым уже нет, отбрасываются: лучше вернуть три текстуры
    из четырёх, чем упасть или показать пустой кадр вместо картинки.
    """
    path = work_dir() / key / 'edits.json'
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        logger.warning(f"работа «{key}» не прочитана: {exc}")
        return None
    if payload.get('format') != FORMAT:
        logger.info(f"работа «{key}» от другой версии формата — пропущена")
        return None

    edits = payload.get('edits') or {}
    for team, paths in list((edits.get('textures') or {}).items()):
        edits['textures'][team] = {m: p for m, p in paths.items()
                                   if os.path.isfile(p)}
    for skin, paths in list((edits.get('skin_overrides') or {}).items()):
        edits['skin_overrides'][skin] = {m: p for m, p in paths.items()
                                         if os.path.isfile(p)}
    if edits.get('custom_smd_path') and not os.path.isfile(edits['custom_smd_path']):
        edits['custom_smd_path'] = None
    return edits


def forget(key: str) -> bool:
    """Удаляет работу над предметом вместе с её файлами."""
    folder = work_dir() / key
    if not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    logger.info(f"работа «{key}» удалена")
    return not folder.exists()


#: Метка «эту работу человек сохранил сам». Пустой файл, а не поле в
#: edits.json: автосохранение переписывает файл на каждую правку, и поле
#: пришлось бы вычитывать и переносить при каждой записи — а метку не трогает
#: никто, кроме `keep` и `forget`.
KEPT = 'kept'


def keep(key: str) -> bool:
    """Помечает работу сохранённой — в библиотеке видны только такие."""
    folder = work_dir() / key
    if not key or not (folder / 'edits.json').is_file():
        return False
    try:
        (folder / KEPT).write_bytes(b'')
    except OSError as exc:
        logger.warning(f"работа «{key}» не помечена сохранённой: {exc}")
        return False
    return True


def is_kept(key: str) -> bool:
    """Сохранял ли человек эту работу сам (а не автосохранение молча)."""
    return bool(key) and (work_dir() / key / KEPT).is_file()


def _listing(kept: bool) -> list:
    """Работы с меткой `kept` или без неё: (ключ, когда сохранено).

    Ключ разбирается обратно вызывающим — здесь про предметы ничего не знают.
    Папка без `edits.json` работой не считается: такие остаются от прерванной
    записи и от `forget`, который не смог убрать каталог.
    """
    root = WORK_DIR
    if not root.is_dir():
        return []
    out = []
    for folder in sorted(root.iterdir()):
        edits = folder / 'edits.json'
        if not edits.is_file() or (folder / KEPT).is_file() is not kept:
            continue
        try:
            when = edits.stat().st_mtime
        except OSError:
            when = 0.0
        out.append({'key': folder.name, 'saved_at': when,
                    'item': item_of(folder.name)})
    out.sort(key=lambda w: w['saved_at'], reverse=True)
    return out


def list_saved() -> list:
    """Сохранённые человеком работы.

    Черновиков автосохранения здесь нет: оно пишет всё, к чему человек
    прикоснулся, и библиотека заросла бы предметами, которые просто открывали.
    Черновик возвращается кнопкой на самом предмете.
    """
    return _listing(kept=True)


def list_drafts() -> list:
    """Черновики автосохранения: работы, которые никто не сохранял сам.

    Нужны для уборки. Каждый открытый и хоть раз тронутый предмет оставляет
    здесь папку с копиями текстур, и добраться до неё можно было только заново
    открыв тот же предмет — то есть на практике никак.
    """
    return _listing(kept=False)


def has(key: str) -> bool:
    """Лежит ли на диске файл работы. Про его содержимое — `holds_edits`."""
    return (work_dir() / key / 'edits.json').is_file()


def holds_edits(key: str) -> bool:
    """Есть ли в записанной работе то, что стоит предлагать вернуть.

    Наличия файла мало: `edits.json` остаётся и от старых версий формата, и
    от работы, в которой не осталось ничего, кроме настроек сборки. По нему
    приложение всю жизнь предмета предлагало «вернуть правки», хотя в
    текстуре человек ничего не менял. Правило то же, что у сеанса, — одно на
    двоих, иначе они снова разъедутся.
    """
    from src.domain.preview.session import has_real_edits
    return has_real_edits(load(key))


def size_of(key: str) -> int:
    """Сколько места занимает работа, байтами. Нет работы — ноль.

    Показывается перед удалением черновиков: «удалить 12 черновиков» и
    «удалить 12 черновиков (280 МБ)» — это два разных решения.
    """
    folder = WORK_DIR / key
    if not folder.is_dir():
        return 0
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total
