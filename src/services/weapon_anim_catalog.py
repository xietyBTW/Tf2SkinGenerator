"""
Каталог анимаций класса: что вообще можно проиграть и как это найти

Модель `c_<class>_animations.mdl` держит 50-98 последовательностей на класс, и
их имена наружу не выводятся: у скаттергана idle зовётся `sg_idle`, у пистолета
`p_idle`, у Неумолимой силы `db_idle`. Подбирать эти префиксы руками не нужно -
у каждой последовательности в QC стоит активность, и она называет ровно то, что
требуется:

    sg_idle                ACT_PRIMARY_VM_IDLE
    p_idle                 ACT_SECONDARY_VM_IDLE
    ss_idle                ACT_SECONDARY_VM_IDLE_2      Прерыватель
    db_idle                ACT_ITEM2_VM_IDLE            Неумолимая сила
    b_idle                 ACT_MELEE_VM_IDLE
    sg_fire                ACT_PRIMARY_VM_PRIMARYATTACK
    sg_reload_start        ACT_PRIMARY_RELOAD_START
    primary_inspect_idle   ACT_PRIMARY_VM_INSPECT_IDLE

Какую из них играть, решает не грамматика имён, а тот же путь, что в движке
(source-sdk-2013, `CTFWeaponBase::TranslateViewmodelHandActivityInternal`):

  1. Оружие шлёт БАЗОВУЮ активность: idle - ACT_VM_IDLE, выстрел -
     ACT_VM_PRIMARYATTACK, удар ближнего боя - ACT_VM_HITCENTER, у кулаков -
     ACT_VM_HITLEFT / ACT_VM_HITRIGHT, крит - ACT_VM_SWINGHARD. Осмотр сразу
     назван слотом снаряжения: ACT_MELEE_VM_INSPECT_IDLE.
  2. Часть классов оружия переводит её сама: горны и парашют - в набор ITEM1,
     мечи подрывника - в *_SPECIAL.
  3. Подмена из items_game (`animation_replacement`). Нашлась - это и есть
     ответ, дальше игра не ищет.
  4. Таблица ролей `s_viewmodelacttable`: ACT_VM_IDLE у роли melee ->
     ACT_MELEE_VM_IDLE. Строки нет - активность остаётся базовой (так саппер
     шпиона играет просто ACT_VM_IDLE)

Запасных путей нет: чего у оружия нет в игре, того нет и здесь. Перебор
«слот -> без цифры -> всеклассовый набор» дал бы Кусай-хлебу на удар
замах сковородой (у кулаков удар не HITCENTER, и поиск доходил до
ACT_MELEE_ALLCLASS_VM_HITCENTER), а дробовику хэви - анимации минигана

Каталог - просто индекс уже декомпилированной папки, он ничего не скачивает и
не считает поз. Кадр из выбранной последовательности берёт [viewmodel_pose]
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Mapping, Optional

from src.data import viewmodel_anims
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_SEQUENCE_RE = re.compile(r'\$sequence\s+"([^"]+)"\s*\{(.*?)\n\}', re.S)
_ACTIVITY_RE = re.compile(r'^\s*activity\s+"([^"]+)"', re.M)
_SMD_RE = re.compile(r'"([^"]+\.smd)"', re.I)
_FPS_RE = re.compile(r'^\s*fps\s+([\d.]+)', re.M)
_LOOP_RE = re.compile(r'^\s*loop\s*$', re.M)

#: `{ event AE_WPN_HIDE 0 "" }` - кадр, на котором игра прячет или достаёт то,
#: что персонаж держит в руке. Насмешка ими показывает реквизит не с начала:
#: медик сперва лезет за пазуху и только на 23-м кадре достаёт снимок
_EVENT_RE = re.compile(r'\{\s*event\s+AE_WPN_(HIDE|UNHIDE)\s+(\d+)', re.I)

#: Слот, под которым разбирается собственная модель вида (см. VIEWMODEL_ONLY).
#: Ролей у такой модели нет: её `idle` помечен просто ACT_VM_IDLE
VIEWMODEL_SLOT = "viewmodel"


class Action(Enum):
    """Действие оружия, как его выбирает пользователь

    Какая активность за ним стоит, зависит от оружия (см. `activity_for`):
    FIRE у стрелкового - PRIMARYATTACK, у ближнего боя - HITCENTER, у кулаков -
    левый удар HITLEFT, а ALT_FIRE у них - правый HITRIGHT
    """

    IDLE = "IDLE"
    DRAW = "DRAW"
    HOLSTER = "HOLSTER"
    FIRE = "FIRE"
    ALT_FIRE = "ALT_FIRE"
    CRIT = "CRIT"
    RELOAD = "RELOAD"
    RELOAD_START = "RELOAD_START"
    RELOAD_FINISH = "RELOAD_FINISH"
    INSPECT_START = "INSPECT_START"
    INSPECT_IDLE = "INSPECT_IDLE"
    INSPECT_END = "INSPECT_END"

    @property
    def is_inspect(self) -> bool:
        return self.name.startswith("INSPECT_")


@dataclass(frozen=True)
class WeaponProfile:
    """Всё, от чего игра выбирает последовательность предмета"""

    #: Роль анимаций: `anim_slot` из items_game, иначе слот снаряжения класса
    slot: str
    #: Подмена активностей из items_game (`visuals -> animation_replacement`)
    replacement: Mapping[str, str] = field(default_factory=dict)
    #: Слот снаряжения у ЭТОГО класса. По нему игра выбирает осмотр
    #: (`GetInspectActivity`), и по нему же оружие считается ближним боем
    loadout_slot: str = ""
    #: Класс оружия в коде игры: от него зависят удары и собственный перевод
    item_class: str = ""
    #: Чьи руки: мечи у подрывника играют свой набор *_SPECIAL
    tf2_class: str = ""


@dataclass(frozen=True)
class AnimSequence:
    """Одна последовательность из QC модели анимаций"""

    name: str
    smd_path: str
    activity: str = ""
    fps: float = 30.0
    loop: bool = False
    #: ((кадр, спрятано), …) по возрастанию кадра - события AE_WPN_HIDE/UNHIDE
    hide_events: tuple = ()

    @property
    def exists(self) -> bool:
        return bool(self.smd_path) and os.path.isfile(self.smd_path)


@dataclass(frozen=True)
class AnimCatalog:
    """Все последовательности класса, проиндексированные для поиска"""

    sequences: List[AnimSequence]
    by_activity: Dict[str, AnimSequence]
    by_name: Dict[str, AnimSequence]

    def find(self, weapon: WeaponProfile,
             action: Action) -> Optional[AnimSequence]:
        """Последовательность для действия. None - у оружия его нет в игре"""
        activity = activity_for(weapon, action)
        found = self.by_activity.get(activity) if activity else None
        return found if found is not None and found.exists else None

    def actions_for(self, weapon: WeaponProfile) -> Dict[Action, AnimSequence]:
        """Все действия, которые у оружия есть. Из них интерфейс строит выбор"""
        found = {}
        for action in Action:
            seq = self.find(weapon, action)
            if seq is not None:
                found[action] = seq
        return found


def profile_for(weapon_key: str, tf2_root: str, tf2_class: str) -> WeaponProfile:
    """Профиль предмета в руках класса - из items_game ([viewmodel_anims])"""
    info = viewmodel_anims.anim_info(weapon_key, tf2_root)
    return WeaponProfile(
        slot=viewmodel_anims.slot_for(weapon_key, tf2_root, tf2_class),
        replacement=info.replacement if info else {},
        loadout_slot=viewmodel_anims.loadout_slot(weapon_key, tf2_root, tf2_class),
        item_class=info.item_class if info else "",
        tf2_class=(tf2_class or "").lower(),
    )


def load(decompiled_dir: str) -> Optional[AnimCatalog]:
    """
    Разбирает QC модели анимаций из папки декомпиляции

    Returns:
        AnimCatalog, либо None - если QC нет или в нём нет последовательностей
    """
    qc_path = _find_qc(decompiled_dir)
    if not qc_path:
        logger.warning(f"[anim] QC не найден в {decompiled_dir}")
        return None
    try:
        with open(qc_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        logger.warning(f"[anim] не прочитать {qc_path}: {exc}")
        return None

    qc_dir = os.path.dirname(qc_path)
    sequences: List[AnimSequence] = []
    for name, body in _SEQUENCE_RE.findall(text):
        smd = _SMD_RE.search(body)
        activity = _ACTIVITY_RE.search(body)
        fps = _FPS_RE.search(body)
        sequences.append(AnimSequence(
            name=name,
            smd_path=(os.path.join(qc_dir, smd.group(1).replace("\\", os.sep))
                      if smd else ""),
            activity=activity.group(1).upper() if activity else "",
            fps=float(fps.group(1)) if fps else 30.0,
            loop=bool(_LOOP_RE.search(body)),
            hide_events=tuple(sorted(
                (int(frame), kind.upper() == 'HIDE')
                for kind, frame in _EVENT_RE.findall(body))),
        ))

    if not sequences:
        logger.warning(f"[anim] в {os.path.basename(qc_path)} нет $sequence")
        return None

    # Первая последовательность с активностью выигрывает. У Valve бывает
    # несколько на одну активность (три idle у Кусай-хлеба) - игра выбирает
    # из них случайно по весу, превью берёт первую, чтобы кадр не прыгал
    by_activity: Dict[str, AnimSequence] = {}
    for seq in sequences:
        if seq.activity:
            by_activity.setdefault(seq.activity, seq)

    logger.info(
        f"[anim] {os.path.basename(qc_path)}: {len(sequences)} последовательностей, "
        f"{len(by_activity)} активностей"
    )
    return AnimCatalog(
        sequences=sequences,
        by_activity=by_activity,
        by_name={s.name: s for s in sequences},
    )


# Активность: путь движка

#: Базовая активность действия: то, что шлёт `SendWeaponAnim` обычное оружие
_BASE: Dict[Action, str] = {
    Action.IDLE: "ACT_VM_IDLE",
    Action.DRAW: "ACT_VM_DRAW",
    Action.HOLSTER: "ACT_VM_HOLSTER",
    Action.FIRE: "ACT_VM_PRIMARYATTACK",
    Action.ALT_FIRE: "ACT_VM_SECONDARYATTACK",
    Action.RELOAD: "ACT_VM_RELOAD",
    Action.RELOAD_START: "ACT_RELOAD_START",
    Action.RELOAD_FINISH: "ACT_RELOAD_FINISH",
}

#: Удары ближнего боя (`CTFWeaponBaseMelee::DoViewModelAnimation`): обычный -
#: HITCENTER, крит - SWINGHARD. Вторая кнопка анимации не шлёт вовсе
_MELEE_HITS: Dict[Action, Optional[str]] = {
    Action.FIRE: "ACT_VM_HITCENTER",
    Action.ALT_FIRE: None,
    Action.CRIT: "ACT_VM_SWINGHARD",
}

#: Оружие со своим `DoViewModelAnimation`
_OWN_HITS: Dict[str, Dict[Action, Optional[str]]] = {
    # Кулаки: левой, правой, крит (`CTFFists`)
    "tf_weapon_fists": {
        Action.FIRE: "ACT_VM_HITLEFT",
        Action.ALT_FIRE: "ACT_VM_HITRIGHT",
        Action.CRIT: "ACT_VM_SWINGHARD",
    },
    # Оружейник (`CTFRobotArm`): шлёт уже готовый набор ITEM2, третий удар
    # серии - SWINGHARD
    "tf_weapon_robot_arm": {
        Action.FIRE: "ACT_ITEM2_VM_HITCENTER",
        Action.ALT_FIRE: None,
        Action.CRIT: "ACT_ITEM2_VM_SWINGHARD",
    },
}
# Еда и напитки (`CTFLunchBox`) на выстрел запускают насмешку и анимацию вида
# не шлют: `ed_throw` того же набора ITEM1 - бросок Безумного молока
_OWN_HITS["tf_weapon_lunchbox"] = _OWN_HITS["tf_weapon_lunchbox_drink"] = {
    Action.FIRE: None, Action.ALT_FIRE: None, Action.CRIT: None,
}

_LOWERED = ("IDLE_TO_LOWERED", "IDLE_LOWERED", "LOWERED_TO_IDLE")

#: Горны и парашют переводят базовый набор в ITEM1 сами (`CTFBuffItem`)
_BUFF_ITEM = {f"ACT_VM_{x}": f"ACT_ITEM1_VM_{x}" for x in (
    "DRAW", "HOLSTER", "IDLE", "PULLBACK", "PRIMARYATTACK", "SECONDARYATTACK",
    *_LOWERED)}

#: Мечи у подрывника - в набор *_SPECIAL (`CTFDecapitationMeleeWeaponBase`)
_DEMO_SWORD = {f"ACT_VM_{x}": f"ACT_VM_{x}_SPECIAL" for x in (
    "DRAW", "HOLSTER", "IDLE", "PULLBACK", "PRIMARYATTACK", "HITCENTER",
    "SWINGHARD", *_LOWERED)}
_DEMO_SWORD["ACT_VM_SECONDARYATTACK"] = "ACT_VM_PRIMARYATTACK_SPECIAL"

#: Слоты снаряжения с набором осмотра (`GetInspectActivity`). У остальных
#: (ПДА, часы) осмотра в игре нет
INSPECT_SLOTS = ("PRIMARY", "SECONDARY", "MELEE", "BUILDING")

#: Роли, у которых есть строки в `s_viewmodelacttable`
_TABLE_ROLES = frozenset({
    "PRIMARY", "SECONDARY", "MELEE", "PDA", "ITEM1", "ITEM2", "ITEM3", "ITEM4",
    "MELEE_ALLCLASS", "SECONDARY2", "PRIMARY2"})
#: Что таблица переводит у каждой из них
_VM_ACTS = frozenset({
    "DRAW", "HOLSTER", "IDLE", "PULLBACK", "PRIMARYATTACK", "SECONDARYATTACK",
    "RELOAD", "DRYFIRE", *_LOWERED})
#: Удары переводятся только у ближнего боя
_MELEE_ROLES = frozenset({"MELEE", "MELEE_ALLCLASS"})
#: Перезарядка по патрону (`ACT_RELOAD_START` без `VM_`) есть не у всех ролей
_RELOAD_ROLES = frozenset({"PRIMARY", "SECONDARY", "SECONDARY2", "ITEM1",
                           "PRIMARY2"})

#: Наш собственный слот, которого ролью в игре нет: часы невидимости -
#: «вторая рука» шпиона
_PSEUDO_ROLES = {"WATCH": "OFFHAND"}

#: Роли без строк в таблице, которые всё же держат оружие: саппер шпиона и
#: ящик инженера (building), своя модель вида у часов. Их активность - базовая
_BASE_ROLES = frozenset({"BUILDING", VIEWMODEL_SLOT.upper()})


def activity_for(weapon: WeaponProfile, action: Action) -> Optional[str]:
    """
    Активность, которую игра проиграет у этого оружия на это действие

    None - действия у оружия нет вовсе (вторая кнопка ближнего боя, осмотр
    ПДА). Шаги - как в движке, см. описание модуля
    """
    role = (weapon.slot or "").strip().upper()
    if role not in _TABLE_ROLES and role not in _PSEUDO_ROLES \
            and role not in _BASE_ROLES:
        # Не оружие в руке: тело, маски, `force_not_used` у часов. Базовая
        # ACT_VM_IDLE у шпиона нашлась бы - это саппер
        return None
    if action.is_inspect:
        loadout = (weapon.loadout_slot or "").upper()
        if loadout not in INSPECT_SLOTS:
            return None
        base = f"ACT_{loadout}_VM_{action.name}"
    else:
        hits = _OWN_HITS.get(weapon.item_class)
        if hits is None and (weapon.loadout_slot or "").lower() == "melee":
            hits = _MELEE_HITS
        base = hits[action] if hits and action in hits else _BASE.get(action)
        if not base:
            return None

    base = _own_translation(weapon, base)
    swapped = (weapon.replacement or {}).get(base)
    if swapped:
        return swapped
    return translate(weapon.slot, base)


def _own_translation(weapon: WeaponProfile, activity: str) -> str:
    """Перевод, который класс оружия делает ДО подмены и таблицы ролей"""
    cls = weapon.item_class
    if cls == "tf_weapon_buff_item" or cls.startswith("tf_weapon_parachute"):
        return _BUFF_ITEM.get(activity, activity)
    if (cls in ("tf_weapon_sword", "tf_weapon_katana")
            and weapon.tf2_class == "demoman"
            and (weapon.slot or "").lower() != "melee_allclass"):
        return _DEMO_SWORD.get(activity, activity)
    return activity


def translate(slot: str, activity: str) -> str:
    """Базовая активность -> активность роли (`s_viewmodelacttable`)

    Неизвестная роль или активность без строки в таблице остаются как есть:
    так делает игра, и так саппер шпиона (роль building) играет ACT_VM_IDLE
    """
    role = (slot or "").strip().upper()
    if role in _PSEUDO_ROLES:
        return activity.replace("ACT_VM_", f"ACT_{_PSEUDO_ROLES[role]}_VM_", 1)
    if role not in _TABLE_ROLES:
        return activity
    # Коровья мясорубка: набор ракетомёта, но своя перезарядка `_3`
    target, reload_suffix = ("PRIMARY", "_3") if role == "PRIMARY2" else (role, "")
    if activity.startswith("ACT_VM_"):
        name = activity[len("ACT_VM_"):]
        if name in ("HITCENTER", "SWINGHARD"):
            return f"ACT_{target}_VM_{name}" if role in _MELEE_ROLES else activity
        if name not in _VM_ACTS or (role in ("SECONDARY2", "PRIMARY2")
                                    and name == "SECONDARYATTACK"):
            return activity
        suffix = reload_suffix if name == "RELOAD" else ""
        return f"ACT_{target}_VM_{name}{suffix}"
    if activity in ("ACT_RELOAD_START", "ACT_RELOAD_FINISH") \
            and role in _RELOAD_ROLES:
        return f"ACT_{target}_{activity[len('ACT_'):]}{reload_suffix}"
    return activity


def _find_qc(directory: str) -> Optional[str]:
    if not directory or not os.path.isdir(directory):
        return None
    hits = sorted(glob.glob(os.path.join(directory, "*.qc")))
    return hits[0] if hits else None
