"""
Насмешки с реквизитом — прямо из items_game.

Руками выверенная таблица [taunt_props] знает два десятка самых заметных
насмешек, а в игре их девять десятков: почти каждая насмешка мастерской носит
с собой модель (гармошка, метла, банджо, вертолётик шпиона). Все они
реквизит того же рода — MDL с текстурами, и перекрашиваются тем же путём.
Держать такой список в коде смысла нет: он устаревает с каждым обновлением
игры, а items_game лежит рядом и всегда свежий.

Оттуда же берутся две вещи, которых у ручной таблицы не было:

  * имя — официальное, из `tf_russian.txt` / `tf_english.txt` по токену
    `item_name`, а не придуманное нами;
  * иконка — `image_inventory`, та самая картинка из рюкзака. Раньше карточке
    насмешки рисовали обложку из текстуры модели: у пачки денег это зелёное
    пятно, у гармошки — развёртка. Иконка узнаётся с одного взгляда.

Разбор один на процесс: items_game — восемь мегабайт, и перечитывать его на
каждое открытие каталога незачем.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Dict, List

from src.data import taunt_scenes
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Начало предмета в items_game: номер на двух табуляциях и скобка.
_ITEM_HEAD = re.compile(r'\n\t\t"\d+"\s*\n\t\t\{')
_ITEM_NAME = re.compile(r'"item_name"\s+"([^"]+)"')
_IMAGE = re.compile(r'"image_inventory"\s+"([^"]+)"')

_lock = threading.Lock()
#: Папка игры, для которой список уже влит. Второй раз работу не делаем.
_merged_root = ''


def _item_bodies(text: str) -> List[str]:
    """Тела всех предметов верхнего уровня — по балансу скобок.

    Регуляркой «до отступа» такой блок не взять: внутри предмета вложены
    `visuals`, `styles` и `attributes`, и первая же закрывающая скобка
    оборвала бы его на середине.
    """
    out: List[str] = []
    for head in _ITEM_HEAD.finditer(text):
        start = head.end() - 1
        depth, i = 0, start
        while i < len(text):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if not depth:
                    break
            i += 1
        out.append(text[start:i])
    return out


def _display(loc: Dict[str, str], token: str, fallback: str) -> str:
    """Имя предмета из локализации, без приставки «Насмешка: ».

    В игре все они называются «Taunt: The Shred Alert» — на карточке каталога
    приставка занимает половину строки и ничего не говорит: категория и так
    называется реквизитом насмешек.
    """
    name = loc.get(token.lstrip('#'), '') or loc.get(token.lstrip('#').lower(), '')
    if not name:
        return fallback
    _, sep, tail = name.partition(': ')
    return tail if sep and tail else name


def _pick(props: Dict[str, str]) -> str:
    """Модель, по которой зовётся насмешка.

    У всеклассовых моделей девять — по одной на класс, и различаются они только
    размером (`_xl` у здоровяков). Берём разведчика: он есть у всех таких
    насмешек, и ключ выходит тот же, что был выверен руками.
    """
    return props.get('scout') or sorted(props.values())[0]


def load(tf2_root: str) -> Dict[str, dict]:
    """{ключ: {ru, en, mdl_path, icon}} — все насмешки с реквизитом."""
    from src.data.hats_parser import parse_localization
    from src.data.weapon_model_index import get_items_game_path

    path = get_items_game_path(tf2_root)
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError as exc:
        logger.warning(f"[taunt] items_game не прочитан: {exc}")
        return {}

    names = {lang: parse_localization(tf2_root, lang)
             for lang in ('russian', 'english')}
    out: Dict[str, dict] = {}
    for body in _item_bodies(text):
        if 'custom_taunt_prop_per_class' not in body:
            continue
        # Читаем ИМЕННО этот блок, а не весь предмет: строка вида
        # `"scout" "models/….mdl"` есть и в `model_player_per_class`, и во
        # втором реквизите насмешки, и по всему телу разом класс получил бы
        # чужую модель.
        props = {cls.lower(): mdl.replace('\\', '/').strip().lower()
                 for cls, mdl in taunt_scenes.per_class(
                     body, 'custom_taunt_prop_per_class').items()
                 if mdl.lower().endswith('.mdl')}
        if not props:
            continue
        mdl = _pick(props)
        key = os.path.basename(mdl).removesuffix('.mdl')
        if key in out:
            continue
        token = _ITEM_NAME.search(body)
        icon = _IMAGE.search(body)
        token = token.group(1) if token else ''
        out[key] = {
            'ru': _display(names['russian'], token, key),
            'en': _display(names['english'], token, key),
            'mdl_path': mdl,
            'icon': (icon.group(1).replace('\\', '/').lower() if icon else ''),
        }
    logger.info(f"[taunt] в items_game насмешек с реквизитом: {len(out)}")
    return out


def ensure() -> int:
    """Влить список, если папка игры задана. Дёшево при повторном вызове.

    Зовут её оба пути, которым таблица нужна: каталог (показать насмешки) и
    `AppSession.tf2_paths` (найти MDL при сборке). Первый до путей игры не
    добирается вовсе, второй — до каталога, и одной точки на двоих нет.
    """
    from src.config.app_config import AppConfig

    root = (AppConfig.load_config().get('tf2_game_folder') or '').strip()
    return merge(root) if root else 0


def merge(tf2_root: str) -> int:
    """Вливает найденное в общие таблицы. Возвращает, сколько добавлено.

    Своим записям имена не трогаем — они переведены руками и короче
    официальных, — но иконку берём и им: у ручной таблицы её не было.

    Зовётся из `AppSession.tf2_paths`: через него проходит всё, чему нужна
    игра, и другого места, где путь к ней уже известен, а таблицы ещё нет, в
    приложении нет.
    """
    global _merged_root

    from src.data.taunt_props import TAUNT_PROP_MDL_PATHS, TAUNT_PROPS
    from src.data.weapons import WEAPON_MDL_PATHS

    with _lock:
        if _merged_root == tf2_root:
            return 0
        added = 0
        for key, row in load(tf2_root).items():
            known = TAUNT_PROPS.get(key)
            if known is not None:
                known.setdefault('icon', row['icon'])
                continue
            TAUNT_PROPS[key] = row
            TAUNT_PROP_MDL_PATHS[key] = row['mdl_path']
            WEAPON_MDL_PATHS[key] = row['mdl_path']
            added += 1
        _merged_root = tf2_root
        logger.info(f"[taunt] добавлено насмешек из items_game: {added}")
        return added
