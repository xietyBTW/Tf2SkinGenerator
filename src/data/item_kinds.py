"""
Вид редактируемого предмета — один ответ вместо россыпи проверок по строке.

Режим (`mode`) в приложении — строка: 'hat', 'scout_c_scattergun',
'engineer_arms', 'spy_body', 'spy_masks'… По ней код 107 раз в 12 файлах
спрашивал одно и то же разными способами:

    if mode == "hat": ...
    if mode in HAND_MODE_KEYS: ...
    if mode in PLAYER_BODY_MODE_KEYS: ...
    if mode == SPY_MASK_MODE_KEY: ...

Каждый новый вид предмета (скайбокс, частицы, наборы шапок) означал найти и
поправить все такие места — и ничто не мешало одно пропустить. Здесь вид
определяется ОДИН раз, а вопросы к нему задаются по имени:

    kind = kind_of(mode)
    if kind.is_hat: ...
    if kind.multi_material: ...

Модуль знает только про КЛАССИФИКАЦИЮ. Данные конкретного предмета (пути
моделей, текстуры, классы) остаются в своих таблицах — weapons, player_hands,
player_characters и прочих; дублировать их здесь нельзя.
"""

from dataclasses import dataclass
from typing import Dict

#: Шапка/косметика: модель приходит из списка шапок, а не из таблицы оружия.
HAT = "hat"
#: Руки (вьюмодель): своя таблица материалов, несколько текстур на модель.
HANDS = "hands"
#: Тело персонажа: много материалов, командные пары имён.
CHARACTER = "character"
#: Маски маскировки шпиона: отдельная панель и свой набор текстур.
SPY_MASK = "spy_mask"
#: Оружие и всё остальное, что описано таблицей WEAPON_MDL_PATHS.
WEAPON = "weapon"


@dataclass(frozen=True)
class ItemKind:
    """Что это за предмет и как с ним обращаться."""

    key: str

    # ── Прямые вопросы ──────────────────────────────────────────────────── #
    @property
    def is_hat(self) -> bool:
        return self.key == HAT

    @property
    def is_hands(self) -> bool:
        return self.key == HANDS

    @property
    def is_character(self) -> bool:
        return self.key == CHARACTER

    @property
    def is_spy_mask(self) -> bool:
        return self.key == SPY_MASK

    @property
    def is_weapon(self) -> bool:
        return self.key == WEAPON

    # ── Производные свойства поведения ──────────────────────────────────── #
    @property
    def multi_material(self) -> bool:
        """У модели заведомо несколько материалов — текстуры собираются картой.

        Руки и тела персонажей: один общий кадр натянул бы текстуру лица на
        рукав. У шапок и оружия это решается по факту (сколько материалов
        нашлось в модели).
        """
        return self.key in (HANDS, CHARACTER)

    @property
    def model_is_z_up(self) -> bool:
        """SMD модели персонажа уже в мировой ориентации (не требует разворота)."""
        return self.key != CHARACTER

    @property
    def asks_game_paints(self) -> bool:
        """Перед сборкой спрашиваем, оставлять ли краски игры (см. VMT-прокси)."""
        return self.key == HAT


_BY_KEY: Dict[str, ItemKind] = {
    k: ItemKind(k) for k in (HAT, HANDS, CHARACTER, SPY_MASK, WEAPON)}


def kind_of(mode: str) -> ItemKind:
    """Вид предмета по режиму приложения. Неизвестный режим — оружие."""
    from src.data.player_characters import PLAYER_BODY_MODE_KEYS, SPY_MASK_MODE_KEY
    from src.data.player_hands import HAND_MODE_KEYS

    key = (mode or "").strip()
    if key == HAT:
        return _BY_KEY[HAT]
    if key == SPY_MASK_MODE_KEY:
        return _BY_KEY[SPY_MASK]
    if key in HAND_MODE_KEYS:
        return _BY_KEY[HANDS]
    if key in PLAYER_BODY_MODE_KEYS:
        return _BY_KEY[CHARACTER]
    return _BY_KEY[WEAPON]
