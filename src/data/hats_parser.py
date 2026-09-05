"""
Парсер шапок/косметики из items_game.txt (TF2).

Парсит:
  {tf2_root}/tf/scripts/items/items_game.txt  — данные предметов + MDL-пути
  {tf2_root}/tf/resource/tf_english.txt       — локализованные названия

Результат кэшируется в cache/ (имя файла — в _cache_file) и инвалидируется
по mtime. Кэш свой на каждый язык: имена в нём уже локализованы.
"""

from __future__ import annotations

import json
import re
import time
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Optional, Callable

from src.data import items_game_kv
from src.data.weapon_model_index import get_items_game_path

logger = logging.getLogger(__name__)

# ── Пути ─────────────────────────────────────────────────────────────────── #

# v8: добавлено поле icon (image_inventory) — иконка предмета из рюкзака.
# v9: %s раскрывается токеном КЛАССА ИЗ ПУТЕЙ («demo», а не «demoman»).
# Смена версии форсирует одноразовый перепарс старого кэша.
_CACHE_VERSION = "v9"
_CACHE_DIR = Path("cache")

#: Как называется файл локализации у языка приложения. Один словарь на модуль:
#: по нему и читают tf_*.txt, и разводят кэши — иначе первый разобранный язык
#: становился единственным, и переключение в настройках ничего не меняло.
_LANG_FILES = {"en": "english", "ru": "russian"}


def _lang_file(language: str) -> str:
    return _LANG_FILES.get(language, "english")


def _cache_file(language: str = "en") -> Path:
    """Кэш этого языка. Имена в нём локализованы, общий файл их бы смешал."""
    return _CACHE_DIR / f"hats_cache_{_CACHE_VERSION}_{_lang_file(language)}.json"

_CLASS_NAMES = [
    "scout", "soldier", "pyro", "demoman",
    "heavy", "engineer", "medic", "sniper", "spy",
]

_SLOT_COSMETIC = {"head", "misc", "hat", "secondary", "tertiary", "utility", "action"}

#: Как класс называется В ПУТЯХ К МОДЕЛЯМ. Совпадает с именем класса везде,
#: кроме подрывника: файлы у него `..._demo.mdl` (в игре 910 таких моделей и ни
#: одной `_demoman`). Раскрывая %s именем класса, мы получали несуществующий
#: путь — и подрывник молча оставался без шапки в собранном моде.
_MODEL_CLASS_TOKEN = {"demoman": "demo"}


def _model_token(class_name: str) -> str:
    return _MODEL_CLASS_TOKEN.get(class_name.lower(), class_name)


# ── Структура предмета ────────────────────────────────────────────────────── #

@dataclass
class HatItem:
    defindex: str
    name: str           # локализованное отображаемое имя
    internal_name: str  # поле "name" из items_game.txt
    mdl_path: str       # models/player/items/... (primary — для превью/одиночной сборки)
    classes: List[str]  # классы, которые могут носить
    slot: str           # head / misc / etc.
    # Карта класс → mdl-путь для мультиклассовых шапок (разные модели на класс,
    # либо %s-шаблон, раскрытый по классам). Пустой dict = одна общая модель.
    per_class_models: Dict[str, str] = field(default_factory=dict)
    # Модельные стили из items_game (styles { N { model_player(_per_class) } }):
    # [{'name': str, 'per_class_models': {class: mdl}}]. Только стили, задающие СВОЮ
    # модель (геометрию). Скиновые стили ("skin" "N") сюда НЕ входят. Пусто = без
    # модельных стилей. У мультикласс-шапки каждый стиль несёт per-class карту.
    styles: List[dict] = field(default_factory=list)
    # Токен типа предмета ("item_type_name"), напр. "#TF_Wearable_CommunityMedal".
    item_type: str = ""
    # "prefab" из блока — у турнирных медалей это "tournament_medal" (сам
    # item_type_name наследуется от prefab и в блоке отсутствует).
    prefab: str = ""
    # Токен "item_name", напр. "#TF_TournamentMedal_AFC_Div1_1st".
    item_name_token: str = ""
    # Праздничное ограничение ("holiday_restriction"), напр.
    # "halloween_or_fullmoon" / "christmas" — по нему фильтруем сезонное.
    holiday: str = ""
    # "image_inventory" — иконка рюкзака без расширения, напр.
    # "backpack/player/items/soldier/soldier_officer". Пусто = не объявлена,
    # тогда иконку ищут по имени модели (см. services/backpack_icons).
    icon: str = ""

    @property
    def is_medal(self) -> bool:
        """Медаль/турнирный значок. Признак ищем по нескольким полям, т.к.
        item_type_name часто наследуется через prefab и в блоке отсутствует:
        prefab (tournament_medal), item_name (#TF_TournamentMedal…), item_type.
        Подстрока «medal» покрывает и Medal, и Medallion, и TournamentMedal."""
        blob = f"{self.item_type} {self.prefab} {self.item_name_token}".lower()
        return "medal" in blob

    @property
    def is_halloween(self) -> bool:
        return "halloween" in self.holiday.lower()

    @property
    def is_holiday(self) -> bool:
        """Любое сезонное ограничение (Halloween, Christmas, birthday…)."""
        return bool(self.holiday)

    @property
    def classes_str(self) -> str:
        if not self.classes:
            return "All classes"
        if len(self.classes) >= 9:
            return "All classes"
        return ", ".join(c.title() for c in self.classes)

    def matches(self, query_words: List[str], class_filter: Optional[str]) -> bool:
        """Возвращает True если предмет подходит под запрос и фильтр класса."""
        # Фильтр по классу
        if class_filter and class_filter != "all":
            wanted = class_filter.lower().replace("_", "-")
            # Предметы без ограничений (classes == [] или все 9 классов) —
            # это и есть «All-Class»: под фильтром класса их быть не должно,
            # а под своим собственным — только они.
            all_class = not self.classes or len(self.classes) >= 9
            if wanted == "all-class":
                return all_class and self._matches_query(query_words)
            if all_class:
                return False
            if wanted not in [c.lower() for c in self.classes]:
                return False

        return self._matches_query(query_words)

    def _matches_query(self, query_words: List[str]) -> bool:
        """Все слова запроса должны встречаться в названии или классах."""
        if not query_words:
            return True
        searchable = (self.name + " " + self.internal_name + " "
                      + self.classes_str).lower()
        return all(w in searchable for w in query_words)

    def relevance(self, query_words: List[str]) -> int:
        """Оценка релевантности (меньше — выше в списке)."""
        name_lower = self.name.lower()
        q = " ".join(query_words)
        if name_lower == q:
            return 0
        if name_lower.startswith(q):
            return 1
        if q in name_lower:
            return 2
        return 3


# ── Низкоуровневые хелперы парсера KV ─────────────────────────────────────── #

# Разбор самого формата KeyValues живёт в items_game_kv: тот же файл читают
# анимации вьюмодели, и две копии скобочного парсера расходились бы молча.
_skip_to_close_brace = items_game_kv.skip_to_close_brace
_flat_value = items_game_kv.flat_value


def _extract_classes(block: str) -> List[str]:
    """Извлекает список классов из used_by_classes { ... }."""
    start = block.find('"used_by_classes"')
    if start == -1:
        return []
    brace = block.find('{', start)
    if brace == -1:
        return []
    end = _skip_to_close_brace(block, brace)
    sub = block[brace:end]
    return [m.lower() for m in re.findall(r'"(\w+)"\s+"1"', sub, re.IGNORECASE)
            if m.lower() in _CLASS_NAMES]


def _extract_per_class_model(block: str) -> Optional[str]:
    """
    Извлекает первый MDL-путь из блока model_player_per_class { ... }.
    Используется как fallback когда нет прямого model_player.
    """
    start = block.find('"model_player_per_class"')
    if start == -1:
        return None
    brace = block.find('{', start)
    if brace == -1:
        return None
    end = _skip_to_close_brace(block, brace)
    sub = block[brace:end]
    # Ищем любую пару "class" "path.mdl"
    m = re.search(r'"[^"]+"\s+"([^"]*\.mdl)"', sub, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_per_class_models(block: str) -> Dict[str, str]:
    """
    Извлекает ВСЕ пары класс→MDL из блока model_player_per_class { ... }.

    Возвращает {класс: нормализованный_путь} только для известных классов TF2.
    """
    start = block.find('"model_player_per_class"')
    if start == -1:
        return {}
    brace = block.find('{', start)
    if brace == -1:
        return {}
    end = _skip_to_close_brace(block, brace)
    sub = block[brace:end]
    result: Dict[str, str] = {}
    for cls, path in re.findall(r'"([^"]+)"\s+"([^"]*\.mdl)"', sub, re.IGNORECASE):
        cls_l = cls.lower()
        if cls_l in _CLASS_NAMES and cls_l not in result:
            result[cls_l] = path.replace("\\", "/").lower()
    return result


def _extract_style_models(block: str, classes: List[str],
                          localization: Dict[str, str]) -> List[dict]:
    """
    Извлекает МОДЕЛЬНЫЕ стили из блока styles { "N" { ... } }.

    Берём только стили, задающие свою модель (model_player / model_player_per_class).
    Скиновые стили ("skin" "N") пропускаем — они меняют скин, а не геометрию.

    Returns:
        [{'name': str, 'per_class_models': {class: mdl}}] в порядке индексов стилей.
    """
    start = block.find('"styles"')
    if start == -1:
        return []
    brace = block.find('{', start)
    if brace == -1:
        return []
    end = _skip_to_close_brace(block, brace)
    sub = block[brace + 1:end - 1]   # содержимое styles { ... }

    out: List[dict] = []
    for m in re.finditer(r'"(\d+)"\s*\{', sub):
        idx = m.group(1)
        b = m.end() - 1                      # позиция '{' под-блока стиля
        e = _skip_to_close_brace(sub, b)
        styleblk = sub[b:e]

        # Модели стиля: per-class → карта; иначе flat model_player (общая/%s).
        pcm = _extract_per_class_models(styleblk)
        if not pcm:
            flat = _flat_value(styleblk, "model_player")
            if flat and flat.lower().endswith(".mdl"):
                flat = flat.replace("\\", "/").lower()
                target = classes if classes else list(_CLASS_NAMES)
                if "%s" in flat:
                    pcm = {c: flat.replace("%s", _model_token(c)) for c in target}
                else:
                    pcm = {c: flat for c in target}   # одна общая модель на все классы
        if not pcm:
            continue   # скиновый стиль — без своей модели, пропускаем

        token = _flat_value(styleblk, "name")
        name = None
        if token:
            key = token[1:] if token.startswith("#") else token
            name = localization.get(key) or localization.get(key.lower())
        out.append({"name": name or f"Style {idx}", "per_class_models": pcm})
    return out


def _find_items_section(content: str) -> int:
    """Позиция '{' секции "items" — прямого потомка "items_game" (или -1)."""
    return items_game_kv.find_section(content, "items")


# ── Парсинг items_game.txt ─────────────────────────────────────────────────── #

def _parse_items_game(filepath: str,
                      localization: Dict[str, str],
                      progress_cb: Optional[Callable[[int, str], None]] = None,
                      ) -> List[HatItem]:
    """
    Парсит items_game.txt и возвращает список косметических предметов с MDL-путями.
    """
    logger.info(f"Парсинг items_game.txt: {filepath}")
    t0 = time.time()

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        logger.error(f"Не удалось открыть items_game.txt: {e}")
        return []

    file_size = len(content)
    logger.info(f"Размер items_game.txt: {file_size // 1024} КБ")

    # Надёжно находим секцию "items" как прямой дочерний элемент "items_game"
    items_brace = _find_items_section(content)
    if items_brace == -1:
        logger.error("Секция 'items' не найдена в items_game.txt")
        return []

    logger.info(f"Секция 'items' найдена на позиции {items_brace}")

    results: List[HatItem] = []
    pos = items_brace + 1  # сразу после {

    n = len(content)
    items_parsed   = 0
    skipped_no_mdl = 0
    skipped_path   = 0
    skipped_slot   = 0
    skipped_class  = 0
    skipped_case   = 0

    while pos < n:
        # Пропускаем пробелы и комментарии
        while pos < n and content[pos] in ' \t\r\n':
            pos += 1
        if pos >= n:
            break
        if content[pos] == '/' and pos + 1 < n and content[pos + 1] == '/':
            nl = content.find('\n', pos)
            pos = nl + 1 if nl != -1 else n
            continue

        # Секция items заканчивается
        if content[pos] == '}':
            break

        # Читаем ключ (defindex) — должен быть в кавычках
        if content[pos] != '"':
            pos += 1
            continue

        key_end = content.find('"', pos + 1)
        if key_end == -1:
            break
        defindex = content[pos + 1:key_end]
        pos = key_end + 1

        # Пропускаем до открывающей {
        while pos < n and content[pos] in ' \t\r\n':
            pos += 1
        if pos >= n or content[pos] != '{':
            continue

        block_start = pos
        block_end = _skip_to_close_brace(content, block_start)
        block = content[block_start:block_end]
        pos = block_end

        items_parsed += 1

        # Быстрая предфильтрация: пропускаем блоки без каких-либо признаков косметики.
        # Многие предметы наследуют item_class "tf_wearable" через prefab (напр. "prefab" "hat"),
        # поэтому строки "tf_wearable" в самом блоке может не быть.
        # Достаточно убедиться, что блок хотя бы содержит ссылку на модель или явно помечен.
        has_model_ref = ('"model_player"' in block or
                         '"model_player_per_class"' in block or
                         '"model_world"' in block)
        if not has_model_ref and "tf_wearable" not in block:
            continue

        # Если item_class явно указан и это не tf_wearable — точно не косметика.
        # Если item_class не указан (унаследован через prefab) — продолжаем проверку.
        item_class = _flat_value(block, "item_class")
        if item_class and item_class.lower() != "tf_wearable":
            skipped_class += 1
            continue

        # ── MDL-путь ─────────────────────────────────────────────────────── #
        # Приоритет: model_player → model_player_per_class → model_world
        mdl_path = _flat_value(block, "model_player")

        # TF2 использует %s как плейсхолдер для имени класса (напр. ghostly_gibus_%s.mdl).
        # Сохраняем %s как есть — vpk_service раскрывает его в пути для каждого класса при сборке.

        if not mdl_path:
            mdl_path = _extract_per_class_model(block)

        if not mdl_path:
            mdl_path = _flat_value(block, "model_world")

        if not mdl_path:
            skipped_no_mdl += 1
            continue

        # Нормализуем слеши
        mdl_path = mdl_path.replace("\\", "/").lower()

        # Только player items
        if not (mdl_path.startswith("models/player/items") or
                mdl_path.startswith("models/workshop/player/items") or
                mdl_path.startswith("models/workshop_partner/player/items")):
            skipped_path += 1
            continue

        # Слот предмета (пустой слот = старый предмет без слота, пропускаем не-косметику)
        slot = (_flat_value(block, "item_slot") or "").lower()
        if slot and slot not in _SLOT_COSMETIC:
            skipped_slot += 1
            continue

        # Кейсы/ящики/крафт-инструменты — это НЕ носибельные предметы (их открывают,
        # а не носят). Признаки: prefab с «case»/«crate», блок "tool" { … } или
        # модель в crafting/. Прячем их из списка шапок.
        prefab = (_flat_value(block, "prefab") or "").lower()
        is_case = (
            "case" in prefab or "crate" in prefab
            or '"tool"' in block
            or "/crafting/" in mdl_path
        )
        if is_case:
            skipped_case += 1
            continue

        # Внутреннее имя
        internal_name = _flat_value(block, "name") or defindex

        # Локализованное название
        item_name_token = _flat_value(block, "item_name") or ""
        token_key = item_name_token.lstrip("#")
        display_name = (localization.get(token_key)
                        or localization.get(token_key.lower())
                        or internal_name)

        if not display_name or display_name.startswith("TF_") or display_name.startswith("#"):
            display_name = internal_name

        # Классы
        classes = _extract_classes(block)

        # Пер-классовые модели (мультиклассовые шапки).
        # %s в пути (mdl_path уже раскрыт из model_player ИЛИ из basename внутри
        # model_player_per_class) → all-class шаблон: раскрываем по классам.
        # Если used_by_classes пуст — значит все 9 классов.
        # Иначе — явные пары класс→MDL из model_player_per_class.
        per_class_models: Dict[str, str] = {}
        if "%s" in mdl_path:
            target_classes = classes if classes else list(_CLASS_NAMES)
            for cls in target_classes:
                token = _model_token(cls)
                try:
                    per_class_models[cls] = mdl_path % token
                except (TypeError, ValueError):
                    per_class_models[cls] = mdl_path.replace("%s", token)
        else:
            per_class_models = _extract_per_class_models(block)

        # Модельные стили (styles { N { model_player(_per_class) } }).
        styles = _extract_style_models(block, classes, localization)

        # Метки для фильтрации: тип предмета (медали) и сезонность (Halloween).
        item_type = _flat_value(block, "item_type_name") or ""
        prefab = _flat_value(block, "prefab") or ""
        holiday = _flat_value(block, "holiday_restriction") or ""
        icon = _flat_value(block, "image_inventory") or ""

        results.append(HatItem(
            defindex=defindex,
            name=display_name,
            internal_name=internal_name,
            mdl_path=mdl_path,
            classes=classes,
            slot=slot or "head",
            per_class_models=per_class_models,
            styles=styles,
            item_type=item_type,
            prefab=prefab,
            item_name_token=item_name_token,
            holiday=holiday,
            icon=icon,
        ))

        if progress_cb and items_parsed % 500 == 0:
            pct = min(90, int(items_parsed / max(len(results) + 1, 1) * 10))
            pct = min(90, items_parsed // 100)
            progress_cb(pct, f"Parsing... ({len(results)} cosmetics found)")

    elapsed = time.time() - t0
    logger.info(
        f"Итого: {len(results)} косметики за {elapsed:.1f}s "
        f"(пропущено: нет MDL={skipped_no_mdl}, "
        f"не player/items={skipped_path}, "
        f"не косметика slot={skipped_slot}, "
        f"класс не wearable={skipped_class}, "
        f"кейсы/крафт={skipped_case})"
    )
    return results


# ── Парсинг локализации ───────────────────────────────────────────────────── #

#: Строка локализации: ключ и значение, кавычки внутри значения экранированы.
#: Наивное `"([^"]*)"` обрывалось на первой же такой кавычке — «"Рыцарь
#: Туфорта"» превращался в одинокий слеш, а разбор дальше съезжал на строку.
#: Якорь на начало строки не даёт значению перескочить перевод строки.
_LOC_LINE = re.compile(r'^\s*"((?:[^"\\]|\\.)+)"\s+"((?:[^"\\]|\\.)*)"', re.M)


def _clean_display(value: str) -> str:
    """Название предмета для показа: без экранирования и управляющих символов.

    В локализации встречаются и то, и другое (цветовые коды чата, переносы
    строк внутри описаний). В списке предметов они выглядят как мусор перед
    именем.
    """
    text = value.replace('\\"', '"').replace('\\\\', '\\')
    text = ''.join(ch for ch in text if ord(ch) >= 32 or ch == ' ')
    return text.strip()


def parse_localization(tf2_root: str, lang: str = "english") -> Dict[str, str]:
    """
    Парсит tf_english.txt (или tf_{lang}.txt) и возвращает {token: display_name}.
    """
    lang_file = Path(tf2_root) / "tf" / "resource" / f"tf_{lang}.txt"
    if not lang_file.exists():
        lang_file = Path(tf2_root) / "tf" / "resource" / "tf_english.txt"
    if not lang_file.exists():
        logger.warning(f"Файл локализации не найден: {lang_file}")
        return {}

    logger.info(f"Парсинг локализации: {lang_file}")
    try:
        content = lang_file.read_text(encoding="utf-16", errors="replace")
    except (UnicodeDecodeError, OSError):
        try:
            content = lang_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {}

    tokens: Dict[str, str] = {}
    for m in _LOC_LINE.finditer(content):
        key, val = m.group(1), _clean_display(m.group(2))
        tokens[key] = val
        tokens[key.lower()] = val

    logger.info(f"Загружено {len(tokens) // 2} токенов локализации")
    return tokens


# ── Кэш ──────────────────────────────────────────────────────────────────── #

def _cache_valid(tf2_root: str, language: str = "en") -> bool:
    """Проверяет, актуален ли кэш (не устарел по mtime и не пустой)."""
    cache = _cache_file(language)
    if not cache.exists():
        return False
    # Пустой кэш считается невалидным — принудительно перепарсим
    try:
        if cache.stat().st_size < 10:
            return False
        data = json.loads(cache.read_text(encoding="utf-8"))
        if not data:   # пустой список
            logger.warning("Кэш пустой — будет перепарсен")
            return False
    except Exception:
        return False
    cache_mtime = cache.stat().st_mtime
    items_file = Path(tf2_root) / "tf" / "scripts" / "items" / "items_game.txt"
    if not items_file.exists():
        return False
    return items_file.stat().st_mtime <= cache_mtime


def _load_cache(tf2_root: str, language: str = "en") -> Optional[List[HatItem]]:
    """Загружает список шапок из кэша если он актуален."""
    if not _cache_valid(tf2_root, language):
        return None
    try:
        data = json.loads(_cache_file(language).read_text(encoding="utf-8"))
        items = [HatItem(**d) for d in data]
        logger.info(f"Шапки загружены из кэша: {len(items)} предметов")
        return items
    except Exception as e:
        logger.warning(f"Ошибка чтения кэша: {e}")
        return None


def _save_cache(items: List[HatItem], language: str = "en") -> None:
    """Сохраняет список шапок в кэш."""
    cache = _cache_file(language)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=None),
            encoding="utf-8"
        )
        logger.info(f"Кэш шапок сохранён: {len(items)} предметов → {cache}")
        _drop_old_caches()
    except Exception as e:
        logger.warning(f"Не удалось сохранить кэш: {e}")


def _drop_old_caches() -> None:
    """Убирает кэши прошлых версий парсера.

    Имя файла содержит версию, и при её смене старый файл просто оставался
    лежать: у пользователей копились hats_cache_v3…v7 по несколько мегабайт
    каждый, и было неясно, какой из них живой.

    Кэши ДРУГИХ ЯЗЫКОВ текущей версии не трогаем: иначе переключение языка
    туда-обратно каждый раз стоило бы полного перепарса items_game.
    """
    alive = f"hats_cache_{_CACHE_VERSION}_"
    for old in _CACHE_DIR.glob("hats_cache_v*.json"):
        if old.name.startswith(alive):
            continue
        try:
            old.unlink()
            logger.info(f"Старый кэш шапок удалён: {old.name}")
        except OSError:
            pass


# ── Публичный API ─────────────────────────────────────────────────────────── #

def parse_hats(
    tf2_root: str,
    language: str = "en",
    force_reparse: bool = False,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> List[HatItem]:
    """
    Возвращает список всех косметических предметов TF2 с MDL-путями.
    """
    if not force_reparse:
        cached = _load_cache(tf2_root, language)
        if cached is not None:
            return cached

    if progress_cb:
        progress_cb(0, "Loading localization...")

    localization = parse_localization(tf2_root, _lang_file(language))

    items_path = get_items_game_path(tf2_root)
    if not items_path:
        logger.error(f"items_game.txt не найден в {tf2_root}")
        return []

    if progress_cb:
        progress_cb(10, "Parsing items_game.txt...")

    items = _parse_items_game(str(items_path), localization, progress_cb)

    # Сортируем по алфавиту
    items.sort(key=lambda x: x.name.lower())

    if progress_cb:
        progress_cb(95, "Saving cache...")

    _save_cache(items, language)

    if progress_cb:
        progress_cb(100, f"Done — {len(items)} cosmetics found")

    return items
