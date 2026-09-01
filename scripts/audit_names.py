"""
Аудит названий предметов: сверка каталога с самой игрой.

Названия в `src/data/weapons.py` набивались руками, и часть из них разъехалась
с ключами — сдвиг на одну строку внутри слота (у c_holymackerel оказалось имя
соседа, у c_bonk_bat — следующего за ним). Глазами такое не ловится: список
длинный, а имена правдоподобные.

Источник истины — установленная игра:
  • tf/scripts/items/items_game.txt — какой предмет какой моделью рисуется
    (с наследованием prefab, иначе стоковое оружие не опознаётся);
  • tf/resource/tf_russian.txt и tf_english.txt — как игра называет предмет.

Запуск:
  python scripts/audit_names.py                 # путь к игре из настроек
  python scripts/audit_names.py "D:/.../Team Fortress 2"
  python scripts/audit_names.py --json fixes.json   # выгрузить расхождения

Ничего не меняет: печатает расхождения. Правки вносятся руками — данные
локализации у Valve иногда меняются, и слепая замена не всегда желательна.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.weapons import TF2_WEAPONS, WEAPON_SLOT_TYPES, get_weapon_name

#: Токен KeyValues: строка (с экранированием), скобка или комментарий.
_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\{)|(\})|(//[^\n]*)')
#: Строка локализации. Кавычки внутри значения экранированы — обрывать разбор
#: по первой нельзя, иначе «Плитка "Далокош"» превращается в «Плитка \».
_LOC_LINE = re.compile(r'^\s*"((?:[^"\\]|\\.)+)"\s+"((?:[^"\\]|\\.)*)"', re.M)


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace('\\\\', '\\')


def parse_keyvalues(text: str) -> dict:
    """KeyValues → вложенные словари; повторные ключи собираются в список."""
    stack, pending = [{}], None

    def put(container: dict, key: str, value) -> None:
        if key in container:
            old = container[key]
            container[key] = old + [value] if isinstance(old, list) else [old, value]
        else:
            container[key] = value

    for match in _TOKEN.finditer(text):
        raw, open_brace, close_brace, comment = match.groups()
        if comment:
            continue
        if open_brace:
            child: dict = {}
            if pending is not None:
                put(stack[-1], pending, child)
                pending = None
            stack.append(child)
        elif close_brace:
            if len(stack) > 1:
                stack.pop()
        elif pending is None:
            pending = raw.lower()
        else:
            put(stack[-1], pending, raw)
            pending = None
    return stack[0]


def read_localization(tf2_root: Path, language: str) -> dict:
    """{токен: строка} из tf_<язык>.txt (файл в UTF-16)."""
    name = "russian" if language == "ru" else "english"
    path = tf2_root / "tf" / "resource" / f"tf_{name}.txt"
    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = path.read_text(encoding=encoding)
        except (UnicodeError, OSError):
            continue
        if '"tokens"' in text.lower():
            return {m.group(1).lower(): _unescape(m.group(2))
                    for m in _LOC_LINE.finditer(text)}
    return {}


def models_to_tokens(tf2_root: Path) -> dict:
    """{стебель модели: токен item_name}. Первый предмет с моделью выигрывает."""
    items_path = tf2_root / "tf" / "scripts" / "items" / "items_game.txt"
    if not items_path.exists():
        return {}
    root = parse_keyvalues(items_path.read_text(encoding="utf-8", errors="replace"))
    root = root.get("items_game", root)
    items = root.get("items") or {}
    prefabs = root.get("prefabs") or {}

    def field(block, name, depth=0):
        """Значение поля с учётом наследования prefab (стоковое оружие)."""
        if depth > 6 or not isinstance(block, dict):
            return None
        if name in block:
            return block[name]
        for parent in str(block.get("prefab") or "").split():
            got = field(prefabs.get(parent) or {}, name, depth + 1)
            if got:
                return got
        return None

    out: dict = {}
    for block in items.values():
        if not isinstance(block, dict):
            continue
        token = field(block, "item_name")
        if not isinstance(token, str):
            continue
        models = []
        model = field(block, "model_player")
        if isinstance(model, str):
            models.append(model)
        per_class = field(block, "model_player_per_class")
        if isinstance(per_class, dict):
            models += [v for v in per_class.values() if isinstance(v, str)]
        for path in models:
            stem = Path(path.replace("\\", "/")).stem.lower()
            out.setdefault(stem, token.lstrip("#").lower())
    return out


def audit(tf2_root: Path) -> dict:
    """Расхождения по языкам плюс список неопознанных ключей."""
    tokens = models_to_tokens(tf2_root)
    loc = {lang: read_localization(tf2_root, lang) for lang in ("ru", "en")}
    result = {"ru": [], "en": [], "unknown": [], "ok": 0, "models": len(tokens)}

    # Часть ключей по модели не опознаётся: у праздничных вариантов и часов
    # своя раскладка моделей. Их находим по английскому названию — оно у нас
    # совпадает с игрой, и обратный поиск однозначен.
    by_english = {}
    for token, value in loc["en"].items():
        by_english.setdefault(value.strip().lower(), set()).add(token)

    for cls, slots in TF2_WEAPONS.items():
        for slot in WEAPON_SLOT_TYPES:
            for key in slots.get(slot, {}):
                token = tokens.get(key.lower())
                if not token:
                    ours_en = get_weapon_name(cls, slot, key, "en").strip().lower()
                    candidates = by_english.get(ours_en) or set()
                    token = next(iter(candidates)) if len(candidates) >= 1 else None
                if not token:
                    result["unknown"].append(key)
                    continue
                good = True
                for lang in ("ru", "en"):
                    theirs = (loc[lang].get(token) or "").strip()
                    ours = get_weapon_name(cls, slot, key, lang).strip()
                    if theirs and ours.lower() != theirs.lower():
                        result[lang].append((cls, slot, key, ours, theirs))
                        good = False
                result["ok"] += 1 if good else 0
    return result


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--json"]
    dump = "--json" in sys.argv
    if args and not args[0].startswith("-") and not dump:
        root = Path(args[0])
    elif dump and len(args) > 1:
        root = Path(args[1])
    else:
        from src.config.app_config import AppConfig
        root = Path(AppConfig.load_config().get("tf2_game_folder") or "")

    if not (root / "tf" / "scripts" / "items" / "items_game.txt").exists():
        print(f"Игра не найдена: {root}\nУкажите путь аргументом.")
        return 1

    report = audit(root)
    print(f"моделей в items_game: {report['models']}, совпало: {report['ok']}, "
          f"расходится ru: {len(report['ru'])}, en: {len(report['en'])}, "
          f"не опознано: {len(report['unknown'])}\n")
    for lang in ("ru", "en"):
        if not report[lang]:
            continue
        print(f"── {lang.upper()} ──")
        for _cls, _slot, key, ours, theirs in report[lang]:
            print(f"{key:26} у нас: {ours:36} в игре: {theirs}")
        print()
    if report["unknown"]:
        print("── не опознано (праздничные варианты, часы и т.п.) ──")
        print(", ".join(report["unknown"]))

    if dump:
        fixes: dict = {}
        for lang in ("ru", "en"):
            for _cls, _slot, key, _ours, theirs in report[lang]:
                fixes.setdefault(key, {})[lang] = theirs
        target = Path(args[0]) if args else Path("name_fixes.json")
        target.write_text(json.dumps(fixes, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"\nрасхождения выгружены: {target}")
    return 0 if not (report["ru"] or report["en"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
