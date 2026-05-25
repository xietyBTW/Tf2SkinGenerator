"""
Парсер шапок/косметики из items_game.txt (TF2).

Парсит:
  {tf2_root}/tf/scripts/items/items_game.txt  — данные предметов + MDL-пути
  {tf2_root}/tf/resource/tf_english.txt       — локализованные названия

Результат кэшируется в cache/hats_cache.json и инвалидируется по mtime.
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional, Callable

logger = logging.getLogger(__name__)

# ── Пути ─────────────────────────────────────────────────────────────────── #

_CACHE_FILE = Path("cache") / "hats_cache.json"

_CLASS_NAMES = [
    "scout", "soldier", "pyro", "demoman",
    "heavy", "engineer", "medic", "sniper", "spy",
]

_SLOT_COSMETIC = {"head", "misc", "hat", "secondary", "tertiary", "utility", "action"}


# ── Структура предмета ────────────────────────────────────────────────────── #

@dataclass
class HatItem:
    defindex: str
    name: str           # локализованное отображаемое имя
    internal_name: str  # поле "name" из items_game.txt
    mdl_path: str       # models/player/items/...
    classes: List[str]  # классы, которые могут носить
    slot: str           # head / misc / etc.

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
            # Предметы без ограничений (classes == [] или все 9 классов)
            # считаются «All classes» и показываются только при фильтре "all".
            if not self.classes or len(self.classes) >= 9:
                return False
            if class_filter.lower() not in [c.lower() for c in self.classes]:
                return False

        # Поисковый запрос — все слова должны встречаться в названии или классах
        if query_words:
            searchable = (self.name + " " + self.internal_name + " " + self.classes_str).lower()
            if not all(w in searchable for w in query_words):
                return False

        return True

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

def _skip_to_close_brace(content: str, pos: int) -> int:
    """
    Начиная с pos (на символе '{'), возвращает позицию ПОСЛЕ закрывающей '}'.
    Корректно обрабатывает вложенные блоки и строки в кавычках.
    """
    depth = 0
    i = pos
    n = len(content)
    while i < n:
        c = content[i]
        if c == '"':
            i += 1
            while i < n:
                if content[i] == '\\':
                    i += 2
                    continue
                if content[i] == '"':
                    i += 1
                    break
                i += 1
        elif c == '{':
            depth += 1
            i += 1
        elif c == '}':
            depth -= 1
            i += 1
            if depth == 0:
                return i
        elif c == '/' and i + 1 < n and content[i + 1] == '/':
            nl = content.find('\n', i)
            i = nl + 1 if nl != -1 else n
        else:
            i += 1
    return i


def _flat_value(block: str, key: str) -> Optional[str]:
    """Извлекает значение "key" "value" (не вложенное) из блока."""
    m = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', block, re.IGNORECASE)
    return m.group(1) if m else None


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


def _find_items_section(content: str) -> int:
    """
    Надёжно находит открывающую { секции "items" — прямого дочернего элемента
    "items_game". Не путает с вложенными секциями с тем же именем.

    Возвращает позицию { или -1 если не найдено.
    """
    # Шаг 1: найти корневой блок "items_game"
    root_idx = content.find('"items_game"')
    if root_idx == -1:
        logger.warning("Корневая секция 'items_game' не найдена")
        return -1

    root_brace = content.find('{', root_idx + len('"items_game"'))
    if root_brace == -1:
        return -1

    # Шаг 2: сканировать ТОЛЬКО глубину 1 внутри items_game,
    # пока не найдём ключ "items" на этом уровне.
    pos = root_brace + 1
    depth = 1
    n = len(content)

    while pos < n and depth > 0:
        c = content[pos]

        if c == '"':
            # Читаем quoted string
            pos += 1
            key_start = pos
            while pos < n:
                if content[pos] == '\\':
                    pos += 2
                    continue
                if content[pos] == '"':
                    key = content[key_start:pos]
                    pos += 1
                    break
                pos += 1
            else:
                break

            # Если мы на глубине 1 и ключ == "items" → нашли нужную секцию
            if depth == 1 and key == "items":
                # Пропускаем пробелы и ищем {
                while pos < n and content[pos] in ' \t\r\n':
                    pos += 1
                if pos < n and content[pos] == '{':
                    return pos
                # Если после "items" нет { — это значение, а не секция; продолжаем

        elif c == '{':
            depth += 1
            pos += 1
        elif c == '}':
            depth -= 1
            pos += 1
        elif c == '/' and pos + 1 < n and content[pos + 1] == '/':
            nl = content.find('\n', pos)
            pos = nl + 1 if nl != -1 else n
        else:
            pos += 1

    return -1


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

        results.append(HatItem(
            defindex=defindex,
            name=display_name,
            internal_name=internal_name,
            mdl_path=mdl_path,
            classes=classes,
            slot=slot or "head",
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
        f"класс не wearable={skipped_class})"
    )
    return results


# ── Парсинг локализации ───────────────────────────────────────────────────── #

def _parse_localization(tf2_root: str, lang: str = "english") -> Dict[str, str]:
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
    for m in re.finditer(r'"([^"]+)"\s+"([^"]*)"', content):
        key, val = m.group(1), m.group(2)
        tokens[key] = val
        tokens[key.lower()] = val

    logger.info(f"Загружено {len(tokens) // 2} токенов локализации")
    return tokens


# ── Кэш ──────────────────────────────────────────────────────────────────── #

def _cache_valid(tf2_root: str) -> bool:
    """Проверяет, актуален ли кэш (не устарел по mtime и не пустой)."""
    if not _CACHE_FILE.exists():
        return False
    # Пустой кэш считается невалидным — принудительно перепарсим
    try:
        if _CACHE_FILE.stat().st_size < 10:
            return False
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if not data:   # пустой список
            logger.warning("Кэш пустой — будет перепарсен")
            return False
    except Exception:
        return False
    cache_mtime = _CACHE_FILE.stat().st_mtime
    items_file = Path(tf2_root) / "tf" / "scripts" / "items" / "items_game.txt"
    if not items_file.exists():
        return False
    return items_file.stat().st_mtime <= cache_mtime


def _load_cache(tf2_root: str) -> Optional[List[HatItem]]:
    """Загружает список шапок из кэша если он актуален."""
    if not _cache_valid(tf2_root):
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        items = [HatItem(**d) for d in data]
        logger.info(f"Шапки загружены из кэша: {len(items)} предметов")
        return items
    except Exception as e:
        logger.warning(f"Ошибка чтения кэша: {e}")
        return None


def _save_cache(items: List[HatItem]) -> None:
    """Сохраняет список шапок в кэш."""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=None),
            encoding="utf-8"
        )
        logger.info(f"Кэш шапок сохранён: {len(items)} предметов → {_CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Не удалось сохранить кэш: {e}")


# ── Публичный API ─────────────────────────────────────────────────────────── #

def get_items_game_path(tf2_root: str) -> Optional[Path]:
    p = Path(tf2_root) / "tf" / "scripts" / "items" / "items_game.txt"
    return p if p.exists() else None


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
        cached = _load_cache(tf2_root)
        if cached is not None:
            return cached

    if progress_cb:
        progress_cb(0, "Loading localization...")

    lang_map = {"en": "english", "ru": "russian"}
    lang_filename = lang_map.get(language, "english")
    localization = _parse_localization(tf2_root, lang_filename)

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

    _save_cache(items)

    if progress_cb:
        progress_cb(100, f"Done — {len(items)} cosmetics found")

    return items


def invalidate_cache() -> None:
    """Удаляет кэш шапок (для принудительного пересчёта)."""
    if _CACHE_FILE.exists():
        _CACHE_FILE.unlink()
        logger.info("Кэш шапок удалён")
