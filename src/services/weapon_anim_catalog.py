"""
Каталог анимаций класса: что вообще можно проиграть и как это найти.

Модель `c_<class>_animations.mdl` держит 50-98 последовательностей на класс, и
их имена наружу не выводятся: у скаттергана idle зовётся `sg_idle`, у пистолета
`p_idle`, у Неумолимой силы `db_idle`. Подбирать эти префиксы руками не нужно —
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

Отсюда и правило поиска: слот берётся из items_game ([viewmodel_anims]),
действие задаёт вызывающий, а имя активности собирается по грамматике
`ACT_{СЛОТ}_VM_{ДЕЙСТВИЕ}` (у перезарядки — без `VM_`). Проверено на всех девяти
классах: 209 разных активностей, все разбираются этой грамматикой, без активности
остаётся только служебная `r_handposes`.

Каталог — просто индекс уже декомпилированной папки, он ничего не скачивает и
не считает поз. Кадр из выбранной последовательности берёт [viewmodel_pose].

Модуль без Qt.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_SEQUENCE_RE = re.compile(r'\$sequence\s+"([^"]+)"\s*\{(.*?)\n\}', re.S)
_ACTIVITY_RE = re.compile(r'^\s*activity\s+"([^"]+)"', re.M)
_SMD_RE = re.compile(r'"([^"]+\.smd)"', re.I)
_FPS_RE = re.compile(r'^\s*fps\s+([\d.]+)', re.M)
_LOOP_RE = re.compile(r'^\s*loop\s*$', re.M)

#: `{ event AE_WPN_HIDE 0 "" }` — кадр, на котором игра прячет или достаёт то,
#: что персонаж держит в руке. Насмешка ими показывает реквизит не с начала:
#: медик сперва лезет за пазуху и только на 23-м кадре достаёт снимок.
_EVENT_RE = re.compile(r'\{\s*event\s+AE_WPN_(HIDE|UNHIDE)\s+(\d+)', re.I)


#: Слоты, чьи активности названы не по слоту. Инструменты инженера единственные
#: выбиваются из общей грамматики, и это видно прямо в QC:
#:   pda_idle  ACT_ENGINEER_PDA1_VM_IDLE   ПДА строительства
#:   bld_idle  ACT_ENGINEER_PDA2_VM_IDLE   ПДА разрушения
#:   box_idle  ACT_ENGINEER_BLD_VM_IDLE    ящик с постройками
#: Пробуются ПОСЛЕ буквального имени слота: у шпиона тот же слот `building`
#: пользуется обычным ACT_BUILDING_*.
#: Часы невидимости — «вторая рука» шпиона (offhand_idle), а саппер назван
#: вообще без слота (`ACT_VM_IDLE`); пустая строка и означает «без слота».
SLOT_ACTIVITY_ALIASES: Dict[str, tuple] = {
    "PDA": ("ENGINEER_PDA1",),
    "PDA2": ("ENGINEER_PDA2",),
    "BUILDING": ("ENGINEER_BLD", ""),
    "WATCH": ("OFFHAND",),
    # Модель ВИДА (часы шпиона) держит свои последовательности сама, и слота у
    # её активностей нет: `idle` там помечен просто ACT_VM_IDLE.
    "VIEWMODEL": ("",),
}

#: Слот, под которым разбирается собственная модель вида (см. VIEWMODEL_ONLY).
VIEWMODEL_SLOT = "viewmodel"


class Action(Enum):
    """Действие оружия. Значение — токены действия в имени активности.

    Токенов может быть несколько: у стрелкового оружия атака зовётся
    PRIMARYATTACK, а у ближнего боя тот же удар — HITCENTER. Перечисляем оба и
    берём то, что нашлось в модели анимаций класса.
    """

    IDLE = ("IDLE",)
    DRAW = ("DRAW",)
    HOLSTER = ("HOLSTER",)
    FIRE = ("PRIMARYATTACK", "HITCENTER")
    ALT_FIRE = ("SECONDARYATTACK", "SWINGHARD")
    RELOAD = ("RELOAD",)
    RELOAD_START = ("RELOAD_START",)
    RELOAD_FINISH = ("RELOAD_FINISH",)
    INSPECT_START = ("INSPECT_START",)
    INSPECT_IDLE = ("INSPECT_IDLE",)
    INSPECT_END = ("INSPECT_END",)

    @property
    def tokens(self) -> tuple:
        return self.value


@dataclass(frozen=True)
class AnimSequence:
    """Одна последовательность из QC модели анимаций."""

    name: str
    smd_path: str
    activity: str = ""
    fps: float = 30.0
    loop: bool = False
    #: ((кадр, спрятано), …) по возрастанию кадра — события AE_WPN_HIDE/UNHIDE.
    hide_events: tuple = ()

    @property
    def exists(self) -> bool:
        return bool(self.smd_path) and os.path.isfile(self.smd_path)


@dataclass(frozen=True)
class AnimCatalog:
    """Все последовательности класса, проиндексированные для поиска."""

    sequences: List[AnimSequence]
    by_activity: Dict[str, AnimSequence]
    by_name: Dict[str, AnimSequence]

    def find(self, slot: str, action: Action,
             replacement: Optional[Dict[str, str]] = None
             ) -> Optional[AnimSequence]:
        """Последовательность для слота и действия. None — такой в модели нет.

        Args:
            replacement: подмена активностей из items_game
                (`visuals → animation_replacement`). Это самый точный источник:
                у куная слот остаётся melee, но играет он набор ITEM2.
        """
        for activity in activity_candidates(slot, action, replacement):
            found = self.by_activity.get(activity)
            if found is not None and found.exists:
                return found
        return None

    def actions_for(self, slot: str,
                    replacement: Optional[Dict[str, str]] = None
                    ) -> Dict[Action, AnimSequence]:
        """Все действия, доступные оружию этого слота.

        То, из чего интерфейс может собрать список: у одного оружия есть
        перезарядка, у другого только бросок.
        """
        found = {}
        for action in Action:
            seq = self.find(slot, action, replacement)
            if seq is not None:
                found[action] = seq
        return found


def load(decompiled_dir: str) -> Optional[AnimCatalog]:
    """
    Разбирает QC модели анимаций из папки декомпиляции.

    Returns:
        AnimCatalog, либо None — если QC нет или в нём нет последовательностей.
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

    # Первая последовательность с активностью выигрывает: у Valve дубликатов
    # активностей в одной модели нет, но чужой QC на это полагаться не даёт.
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


def activity_candidates(slot: str, action: Action,
                        replacement: Optional[Dict[str, str]] = None
                        ) -> List[str]:
    """
    Имена активностей для слота и действия, от точного к общему.

    Порядок:
      1. слот как есть:      item2      → ACT_ITEM2_VM_IDLE
      2. цифра как вариант:  secondary2 → ACT_SECONDARY_VM_IDLE_2
      3. слот без цифры:     secondary2 → ACT_SECONDARY_VM_IDLE
      4. у ближнего боя — всеклассовый набор: ACT_MELEE_ALLCLASS_VM_IDLE
      5. вообще без слота:   ACT_VM_IDLE

    Затем КАЖДОЕ из этих имён пропускается через подмену из items_game, и
    замена встаёт перед оригиналом: она точнее слота. У куная, Большого
    добытчика и Сосульки слот остаётся melee, но `animation_replacement`
    переписывает активности на набор ITEM2 — без этого все ножи шпиона
    показывали анимацию обычного ножа-бабочки.

    Ключи подмены бывают и голыми (`ACT_VM_IDLE`), и со слотом
    (`ACT_MELEE_VM_INSPECT_IDLE` — как раз осмотр у тех же ножей), поэтому
    список кандидатов включает обе формы.

    Пункты 1 и 2 именно в этом порядке: цифра в конце слота значит разное.
    `item2` — самостоятельный слот (Неумолимая сила), а `secondary2` — второй
    вариант вторичного (Прерыватель: `ACT_SECONDARY_VM_IDLE_2`). Отличить их по
    написанию нельзя, поэтому сначала пробуем буквальное имя.

    У перезарядки `VM_` в активности нет (`ACT_PRIMARY_RELOAD_START`), поэтому
    оба написания пробуются всегда: перечислять исключения дороже, чем проверить
    лишний ключ словаря.
    """
    literal, variant = split_slot(slot)
    if not literal:
        return []

    # (имя слота, суффикс варианта) — от точного к общему.
    forms = [(literal, "")]
    forms += [(alias, "") for alias in SLOT_ACTIVITY_ALIASES.get(literal, ())]
    if variant:
        base = literal[: -len(variant.lstrip("_"))]
        forms.append((base, variant))
        forms.append((base, ""))
    if literal == "MELEE":
        forms.append(("MELEE_ALLCLASS", ""))

    base_names: List[str] = []
    for token in action.tokens:
        for slot_name, suffix in forms:
            for infix in ("VM_", ""):
                # Пустой алиас — активность вообще без слота: так назван саппер
                # шпиона (`ACT_VM_IDLE` → c_sapper_idle).
                prefix = f"{slot_name}_" if slot_name else ""
                name = f"ACT_{prefix}{infix}{token}{suffix}"
                if name not in base_names:
                    base_names.append(name)

    # Ключи подмены бывают двух видов: голые (`ACT_VM_IDLE` → набор целиком) и
    # со слотом (`ACT_MELEE_VM_INSPECT_IDLE` → осмотр у ножей шпиона). Ищем по
    # обоим, и найденное встаёт впереди — подмена точнее слота.
    sources = list(base_names)
    for token in action.tokens:
        sources += [f"ACT_VM_{token}", f"ACT_{token}"]

    names: List[str] = []
    for source in sources:
        swapped = (replacement or {}).get(source)
        if swapped and swapped not in names:
            names.append(swapped)
    for name in base_names:
        if name not in names:
            names.append(name)
    return names


def split_slot(slot: str) -> tuple:
    """`secondary2` → ("SECONDARY2", "_2"); `melee_allclass` → ("MELEE_ALLCLASS", "").

    Первый элемент — слот как записан, второй — суффикс варианта, если слот
    оканчивается цифрой. Что из этого верно, решает наличие активности.
    """
    text = (slot or "").strip().upper()
    if not text or text == "FORCE_NOT_USED":
        return "", ""
    return text, f"_{text[-1]}" if text[-1].isdigit() else ""


def _find_qc(directory: str) -> Optional[str]:
    if not directory or not os.path.isdir(directory):
        return None
    hits = sorted(glob.glob(os.path.join(directory, "*.qc")))
    return hits[0] if hits else None
