"""Превью предмета: загрузка, показ, команда, стили, краска, скайбокс"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, endpoint, logger


# Действия над сеансом

@endpoint
def tf2_paths() -> Dict[str, object]:
    """Где лежит игра. Ошибку отдаём текстом - её показывает страница"""
    from src.app.session import session
    return session().tf2_paths()


@endpoint
def find_tf2() -> Dict[str, object]:
    """Ищет установленную TF2 сам: путь к игре - первое, без чего ничего

    Отдаёт `found` - список годных папок (обычно одну) в порядке от самого
    вероятного. Пустой список означает «не нашлось», и тогда страница просит
    указать папку руками: догадываться дальше нечем

    Проверка та же, по которой работает всё приложение (`TF2Paths.is_valid`),
    так что предложенный путь заведомо рабочий
    """
    from src.services.tf2_paths import TF2Paths
    found = TF2Paths.autodetect()
    logger.info(f"Автопоиск TF2: найдено {len(found)}")
    return {'found': found}


@endpoint
def check_tf2(path: str = '') -> Dict[str, object]:
    """Годится ли папка как путь к игре - без сохранения (встречающее окно
    проверяет выбор до того, как записать его вместе с остальными)"""
    from src.services.tf2_paths import TF2Paths
    return {'ok': TF2Paths.is_valid((path or '').strip())}


@endpoint
def load_preview(mode: str, lang: str = '',  # noqa: PLR0913 - зеркало сеанса
                 model_key: Optional[str] = None,
                 per_class: Optional[Dict[str, str]] = None,
                 style: Optional[int] = None,
                 restore: bool = False,
                 hat: str = '') -> Dict[str, object]:
    """Начинает загрузку 3D-превью. Модель приезжает событиями, не ответом

    restore - открыть с сохранённой работой. Из каталога предмет открывается
    игровым, работы живут своим списком (`works`)
    """
    from src.app.session import session

    lang = _lang(lang)
    return session().load_preview(mode, lang=lang, model_key=model_key,
                                  per_class=per_class, style=style,
                                  restore=restore, hat=hat or '')


@endpoint
def load_taunt(tf2_class: str = '', lang: str = '') -> Dict[str, object]:
    """Собирает сцену насмешки: персонаж играет тонт с этим реквизитом"""
    from src.app.session import session

    lang = _lang(lang)
    return session().load_taunt(tf2_class, lang=lang)


def warm_up() -> None:
    """Прогрев игровых архивов в фоне - зовёт хост сразу после старта"""
    from src.app.session import session

    session().warm_up()


@endpoint
def stop_preview() -> Dict[str, object]:
    from src.app.session import session
    return session().stop_preview()


@endpoint
def view_state() -> Dict[str, object]:
    """Что показывать сейчас: текстуры, команда, доступные варианты"""
    from src.app.session import session
    return session().view_state()


@endpoint
def set_team(team: str) -> Dict[str, object]:
    from src.app.session import session
    return session().set_team(team)


@endpoint
def set_bodygroup(name: str = '', variant: int = 0, lang: str = '') -> Dict[str, object]:
    """Показывает вариант бодигруппы модели (разбитая бутылка) - только показ"""
    from src.app.session import session
    return session().set_bodygroup(name, int(variant), lang=_lang(lang))


@endpoint
def set_australium(active: bool) -> Dict[str, object]:
    from src.app.session import session
    return session().set_australium(active)


@endpoint
def set_festive(kind: str = '', lang: str = '') -> Dict[str, object]:
    """Гирлянда поверх оружия: 'xmas', 'festivizer' или '' - только показ"""
    from src.app.session import session
    return session().decor.set_festive(kind, lang=_lang(lang))


@endpoint
def bake_festive(kind: str = '', lang: str = '') -> Dict[str, object]:
    """«Сделать праздничным»: гирлянда вида `kind` - в модель оружия; '' - снять"""
    from src.app.session import session
    return session().decor.bake(kind, lang=_lang(lang))


@endpoint
def set_decor_fit(fit: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Подгонка показанной гирлянды под свою модель: масштаб, поворот, сдвиг"""
    from src.app.session import session
    return session().decor.set_decor_fit(fit)


@endpoint
def set_decor_bends(bends: Optional[List[dict]] = None) -> Dict[str, object]:
    """Изгибы показанной гирлянды: [{c, r, d}] в осях SMD, по порядку"""
    from src.app.session import session
    return session().decor.set_decor_bends(bends)


@endpoint
def paints(lang: str = '') -> List[dict]:
    """Банки краски игры для превью шапки: [{key, name, red, blu}]"""
    from src.app.session import session
    return session().paints(_lang(lang))


@endpoint
def set_paint(key: str = '') -> Dict[str, object]:
    """Красит превью выбранной банкой, пусто - без краски"""
    from src.app.session import session
    return session().set_paint(key)


@endpoint
def toggle_misc(on: Optional[bool] = None) -> Dict[str, object]:
    """Переключает просмотр служебных материалов («Прочее»)"""
    from src.app.session import session
    return session().toggle_misc(on)


@endpoint
def force_team() -> Dict[str, object]:
    """Включает «сделать командным»: сборка синтезирует BLU-строку"""
    from src.app.session import session
    return session().force_team()


@endpoint
def set_skin(index: int) -> Dict[str, object]:
    """Переключает вариантный стиль модели"""
    from src.app.session import session
    return session().set_skin(index)


@endpoint
def load_wear(tf2_class: str = '', slot: str = '',
              lang: str = '') -> Dict[str, object]:
    """Сцена «На модели»: шапка на персонаже, класс и слот оружия - по выбору"""
    from src.app.session import session

    return session().load_wear(tf2_class, slot, lang=_lang(lang))


@endpoint
def leave_first_person() -> Dict[str, object]:
    """Возврат из вида от первого лица: снимает сцену рук"""
    from src.app.session import session
    return session().leave_first_person()


@endpoint
def load_first_person(action: str = 'IDLE', lang: str = '',
                      full: bool = False) -> Dict[str, object]:
    """Собирает сцену «руки класса с оружием»

    full - собрать целиком, даже если сцена уже в кадре: обычная смена
    анимации обходится одними дорожками
    """
    from src.app.session import session

    lang = _lang(lang)
    return session().load_first_person(action, lang=lang, full=full)


@endpoint
def load_skybox(sky_name: str) -> Dict[str, object]:
    """Готовит грани стокового неба"""
    from src.app.session import session
    return session().load_skybox(sky_name)


@endpoint
def set_texture(material: str, path: Optional[str] = None) -> Dict[str, object]:
    """Кладёт пользовательскую текстуру на материал (path=None - снимает)"""
    from src.app.session import session
    return session().set_texture(material, path)


@endpoint
def class_icons() -> Dict[str, object]:
    """Значки классов из игры: {icons: {класс: путь PNG}}"""
    from src.app.session import session
    return session().class_icons()
