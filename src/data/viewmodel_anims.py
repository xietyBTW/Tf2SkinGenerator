"""
Данные для вида от первого лица: какие модели брать и какую анимацию играть.

Три источника, каждый со своей ролью:

  1. Модели классов — руки и анимации. Имена файлов НЕ выводятся из названия
     класса склейкой: у подрывника класс зовётся demoman, а модели — c_demo_*.
  2. items_game.txt — авторитетные `item_class` и `anim_slot` каждого предмета.
     Именно по ним игра решает, какой набор анимаций проигрывать, и без них
     треть оружия получила бы чужую позу: у Неумолимой силы `anim_slot` =
     item2, а не primary; у Шотландского сопротивления — primary, хотя лежит
     оно во вторичном слоте.
  3. Модель анимаций класса — что вообще есть в наличии (разбирает
     [weapon_anim_catalog]).

Здесь — первые два. Соответствие «набор анимаций → конкретная
последовательность» живёт отдельно: оно требует сверки глазами, а не вывода
из данных.

Модуль без Qt.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from re import IGNORECASE, compile as _compile
from typing import Dict, Optional, Tuple

from src.data import items_game_kv
from src.data.weapon_model_index import get_items_game_path
from src.shared.logging_config import get_logger
from src.shared.paths import data_dir

logger = get_logger(__name__)

#: Каталог моделей вьюмодели внутри VPK.
_C_MODELS = "models/weapons/c_models"

#: Каталог моделей ВИДА — наследие TF2 до перехода на c_models в 2011 году.
_V_MODELS = "models/weapons/v_models"

#: Предметы, которые от первого лица показываются СВОЕЙ моделью вида, а не
#: собираются из рук класса и c_model. В живой игре это только часы шпиона:
#: в `v_watch_*.mdl` уже лежат и руки, и часы, и свои последовательности
#: (draw / idle / holster), а `c_*_watch` — модель для мира и рюкзака, у неё
#: одна кость `static_prop`, и в руку её сажать нечем.
#:
#: Соответствие «наш ключ → модель вида» из данных не выводится: его задают
#: скрипты оружия (`scripts/tf_weapon_invis.ctx`), а они зашифрованы.
VIEWMODEL_ONLY: Dict[str, str] = {
    "c_spy_watch": f"{_V_MODELS}/v_watch_spy.mdl",
    "c_leather_watch": f"{_V_MODELS}/v_watch_leather_spy.mdl",
    "c_pocket_watch": f"{_V_MODELS}/v_watch_pocket_spy.mdl",
}

#: Класс TF2 → основа имени его моделей. Совпадает не всегда: demoman → demo.
CLASS_MODEL_STEM: Dict[str, str] = {
    "scout": "scout",
    "soldier": "soldier",
    "pyro": "pyro",
    "demoman": "demo",
    "heavy": "heavy",
    "engineer": "engineer",
    "medic": "medic",
    "sniper": "sniper",
    "spy": "spy",
}

#: Меши в модели РУК, которые руками не являются. У солдата в `c_soldier_arms`
#: лежит ракета для перезарядки: в покое её в руке быть не должно, а вот в
#: самой перезарядке — должна, поэтому прячется она не всегда (см. воркер).
ARMS_PROP_MATERIALS = frozenset({"w_rocket01"})

#: Суффиксы, которые не меняют набор анимаций: праздничные и фестивайзер-версии
#: оружия анимируются как база. В items_game таких моделей нет вовсе.
_VARIANT_SUFFIXES = ("_xmas", "_festivizer", "_festive")

_MODEL_RE = _compile(r'"model_player[^"]*"\s+"([^"]+\.mdl)"', IGNORECASE)
_PER_CLASS_RE = _compile(r'"([^"]+)"\s+"([^"]*\.mdl)"', IGNORECASE)
#: Пара «активность → чем её подменить» внутри animation_replacement.
_ACT_PAIR_RE = _compile(r'"(ACT_[A-Z0-9_]+)"\s+"(ACT_[A-Z0-9_]+)"', IGNORECASE)
#: Любой путь до .mdl внутри вложенного блока.
_MODEL_PATH_RE = _compile(r'"([^"]+\.mdl)"', IGNORECASE)

_CACHE_FILE = data_dir() / "cache" / "weapon_anim_slots.json"

#: Версия формата кэша. Растёт, когда в записи добавляется поле: старый файл
#: тогда не «почти подходит», а просто разбирается заново.
#: 2 — добавлена подмена активностей (animation_replacement).
#: 3 — добавлена модель-носитель праздничных гирлянд (carried_on).
_CACHE_VERSION = 3

#: tf2_root → индекс (чтобы не разбирать 8 МБ повторно за сессию).
_MEM: Dict[str, Dict[str, "WeaponAnimInfo"]] = {}


@dataclass(frozen=True)
class WeaponAnimInfo:
    """Что items_game говорит про анимации предмета."""

    #: Класс оружия в коде игры: tf_weapon_scattergun, tf_weapon_minigun…
    #: По нему игра выбирает НАБОР анимаций.
    item_class: str = ""
    #: Слот анимаций, если он отличается от слота инвентаря. Пусто — совпадает.
    anim_slot: str = ""
    #: Слот инвентаря: primary / secondary / melee / …
    item_slot: str = ""
    #: Подмена активностей из `visuals → animation_replacement`:
    #: {ACT_VM_IDLE: ACT_ITEM2_VM_IDLE, …}. Это самый точный источник, какая
    #: анимация у предмета: у куная, Большого добытчика и Сосульки слот
    #: остаётся melee, но играют они набор ITEM2, а вовсе не обычный нож.
    animation_replacement: Tuple[Tuple[str, str], ...] = ()
    #: Модель, НА КОТОРОЙ висит эта. Праздничное оружие — не отдельная пушка, а
    #: гирлянда: `c_minigun_xmas` в items_game записан в `attached_models`, а
    #: `model_player` у предмета остаётся минигановским. Без носителя вид от
    #: первого лица показывал бы огоньки, висящие в пустой руке.
    carried_on: str = ""

    @property
    def replacement(self) -> Dict[str, str]:
        """Подмена активностей словарём (в самом поле — кортеж ради hashable)."""
        return dict(self.animation_replacement)

    @property
    def slot(self) -> str:
        """Слот, по которому выбирается последовательность осмотра.

        `anim_slot` сильнее: он для того и заведён, чтобы переопределить слот
        инвентаря там, где анимация взята от другого оружия.
        """
        return self.anim_slot or self.item_slot


def arms_mdl(tf2_class: str) -> Optional[str]:
    """Путь модели рук класса внутри VPK."""
    stem = CLASS_MODEL_STEM.get((tf2_class or "").lower())
    return f"{_C_MODELS}/c_{stem}_arms.mdl" if stem else None


def animations_mdl(tf2_class: str) -> Optional[str]:
    """Путь модели анимаций класса внутри VPK (геометрии в ней нет)."""
    stem = CLASS_MODEL_STEM.get((tf2_class or "").lower())
    return f"{_C_MODELS}/c_{stem}_animations.mdl" if stem else None


def viewmodel_mdl(weapon_key: str) -> Optional[str]:
    """Путь модели ВИДА внутри VPK, если предмет показывается только ею.

    None — обычное оружие: его вид собирается из рук класса и c_model.
    """
    return VIEWMODEL_ONLY.get((weapon_key or "").lower())


def anim_info(weapon_key: str, tf2_root: str) -> Optional[WeaponAnimInfo]:
    """
    Данные об анимациях оружия из items_game. None — предмет не найден.

    Праздничные версии (`*_xmas`) в items_game отдельными моделями не значатся
    и берут данные базового оружия.
    """
    if not weapon_key:
        return None
    index = anim_index(tf2_root)
    key = weapon_key.lower()
    found = index.get(key)
    if found is not None:
        return found
    for suffix in _VARIANT_SUFFIXES:
        if key.endswith(suffix):
            base = index.get(key[: -len(suffix)])
            if base is not None:
                logger.debug(f"[vm] {weapon_key}: анимации взяты от базового оружия")
                return base
    if key.startswith("w_"):
        # У части оружия в нашем списке стоит МИРОВАЯ модель (`w_sd_sapper`), а
        # items_game знает вьюмодельную (`c_sd_sapper`). Без этого Записыватель
        # шпиона играл анимации револьвера вместо набора сапёра.
        found = index.get("c_" + key[2:])
        if found is not None:
            logger.debug(f"[vm] {weapon_key}: анимации взяты от c_-модели")
            return found
    return None


def slot_for(weapon_key: str, tf2_root: str) -> str:
    """
    Слот анимаций оружия: `anim_slot` → `item_slot` → слот из нашей таблицы.

    Порядок не произволен. items_game авторитетнее нашего разбиения по вкладкам:
    у шпиона револьвер лежит в нашем списке под «Primary», а в игре это
    secondary — и последовательности `primary_*` у шпиона попросту нет. Своя
    таблица остаётся последним рубежом для того оружия, чью модель items_game
    называет иначе, чем мы (Ганслингер, Батальонный дух и ещё десяток).

    Returns:
        Имя слота в нижнем регистре, либо "" — если определить нечем.
    """
    info = anim_info(weapon_key, tf2_root)
    if info and info.slot:
        return info.slot
    return _own_slot(weapon_key)


#: Раздел приложения со всеклассовым оружием — сам по себе не класс.
ALL_CLASS_MODE = "all-class"

#: Чьи руки показывать у всеклассового оружия. Набор `melee_allclass_*` есть у
#: всех девяти классов, так что подходит любой; берём один и тот же, чтобы
#: картинка не менялась от раза к разу.
ALL_CLASS_HANDS = "scout"


def class_from_mode(mode: str) -> str:
    """Класс TF2 из режима приложения ("scout_c_scattergun" → "scout").

    Для оружия конкретного класса это единственный надёжный источник: ключ
    вроде `c_shotgun` принадлежит сразу четырём классам, а в руках его надо
    показать у того, кого выбрал пользователь. У всеклассового раздела выбора
    нет вовсе — отдаём руки по умолчанию, иначе вида от первого лица у Саксти
    и сковороды не было бы совсем.

    Returns:
        Имя класса или "" — если в режиме его нет (шапки, снаряды, пикапы).
    """
    head = (mode or "").split("_", 1)[0].lower()
    if head == ALL_CLASS_MODE:
        return ALL_CLASS_HANDS
    return head if head in CLASS_MODEL_STEM else ""


def class_of(weapon_key: str) -> str:
    """Класс TF2, которому принадлежит оружие ("scout"…). "" — не нашли.

    Нужен, чтобы понять, ЧЬИ руки и чью модель анимаций брать: наборы у классов
    разные, и оружие всеклассового ближнего боя всё равно показывается в руках
    конкретного класса.
    """
    return _lookup(weapon_key)[0]


def _own_slot(weapon_key: str) -> str:
    """Слот из нашей таблицы оружия (по вкладке, на которой оно лежит)."""
    return _lookup(weapon_key)[1]


def _lookup(weapon_key: str) -> tuple:
    """(класс, слот) из нашей таблицы оружия."""
    from src.data.weapons import TF2_WEAPONS
    if not weapon_key:
        return "", ""
    for tf2_class, by_slot in TF2_WEAPONS.items():
        for slot, weapons in by_slot.items():
            if weapon_key in weapons:
                name = tf2_class.lower()
                return (ALL_CLASS_HANDS if name == ALL_CLASS_MODE else name,
                        slot.lower())
    return "", ""


def anim_index(tf2_root: str) -> Dict[str, WeaponAnimInfo]:
    """{имя модели без расширения: WeaponAnimInfo}. Пустой, если items_game нет."""
    if not tf2_root:
        return {}
    cached = _MEM.get(tf2_root)
    if cached is not None:
        return cached

    items_path = get_items_game_path(tf2_root)
    if not items_path:
        return {}

    index = _load_cache(items_path) or _build_index(items_path)
    _MEM[tf2_root] = index
    return index


# ── Разбор и кэш ──────────────────────────────────────────────────────────── #

def _build_index(items_path: Path) -> Dict[str, WeaponAnimInfo]:
    try:
        content = items_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning(f"[vm] не прочитать items_game: {exc}")
        return {}

    game = items_game_kv.ItemsGame.parse(content)
    index: Dict[str, WeaponAnimInfo] = {}
    for _defindex, block in game.items:
        info = WeaponAnimInfo(
            item_class=(game.inherited(block, "item_class") or "").lower(),
            anim_slot=(game.inherited(block, "anim_slot") or "").lower(),
            item_slot=(game.inherited(block, "item_slot") or "").lower(),
            animation_replacement=_replacement(game, block),
        )
        stems = _model_stems(game, block)
        for stem in stems:
            index.setdefault(stem, info)   # первый предмет с моделью выигрывает
        for stem in _attached_stems(game, block):
            index.setdefault(stem, replace(info, carried_on=stems[0] if stems else ""))

    logger.info(f"[vm] индекс анимаций из items_game: {len(index)} моделей")
    _save_cache(items_path, index)
    return index


def _replacement(game: "items_game_kv.ItemsGame", block: str) -> tuple:
    """Подмена активностей из `visuals → animation_replacement`.

    Слот предмета при этом не меняется: у куная он остаётся melee, а вот
    активности переписаны на набор ITEM2. Без этой таблицы почти все ножи
    шпиона показывали анимацию обычного ножа-бабочки.
    """
    nested = game.inherited_block(block, "animation_replacement")
    if not nested:
        return ()
    return tuple((src.upper(), dst.upper())
                 for src, dst in _ACT_PAIR_RE.findall(nested))


def _attached_stems(game: "items_game_kv.ItemsGame", block: str) -> list:
    """Имена моделей из `visuals → attached_models` без расширения.

    Так задано всё праздничное оружие: сама пушка остаётся в `model_player`, а
    `c_*_xmas` — навесная гирлянда. Отдельной моделью она не выглядит никак:
    в `c_medigun_xmas` лежат только огоньки, габарит 21 против 68 у медигана.
    """
    nested = game.inherited_block(block, "attached_models")
    if not nested:
        return []
    return [_stem(path) for path in _MODEL_PATH_RE.findall(nested)]


def _model_stems(game: "items_game_kv.ItemsGame", block: str) -> list:
    """Имена моделей предмета без расширения.

    Обычно модель одна, но у части оружия она задана картой «класс → модель»
    (`model_player_per_class`): у Хандзо это две РАЗНЫЕ модели, солдатская и
    подрывника, и обеим нужны свои данные об анимации.
    """
    single = game.inherited_match(block, _MODEL_RE)
    if single:
        return [_stem(single)]
    per_class = game.inherited_block(block, "model_player_per_class")
    if not per_class:
        return []
    return [_stem(path) for _cls, path in _PER_CLASS_RE.findall(per_class)]


def _stem(model_path: str) -> str:
    return os.path.splitext(
        os.path.basename(model_path.replace("\\", "/")))[0].lower()


def _load_cache(items_path: Path) -> Optional[Dict[str, WeaponAnimInfo]]:
    """Кэш действителен, пока items_game не переписали (сравнение по mtime)."""
    try:
        if not _CACHE_FILE.exists():
            return None
        if items_path.stat().st_mtime > _CACHE_FILE.stat().st_mtime:
            return None
        raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != _CACHE_VERSION:
            return None            # формат сменился — разберём items_game заново
        items = raw.get("items") or {}
        if not items:
            return None
        # JSON не знает кортежей: подмена активностей вернётся списками пар.
        return {k: WeaponAnimInfo(
                    **{**v, "animation_replacement": tuple(
                        tuple(pair) for pair in v.get("animation_replacement") or ())})
                for k, v in items.items()}
    except Exception as exc:
        logger.debug(f"[vm] кэш анимаций не прочитан: {exc}")
        return None


def _save_cache(items_path: Path, index: Dict[str, WeaponAnimInfo]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({"version": _CACHE_VERSION,
                        "items": {k: asdict(v) for k, v in index.items()}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug(f"[vm] кэш анимаций не сохранён: {exc}")
