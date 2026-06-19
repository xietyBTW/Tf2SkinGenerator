"""
Единый потоко-локальный кэш открытых VPK-объектов.

vpk.open() парсит ВЕСЬ индекс архива (десятки тысяч записей в
tf2_textures_dir.vpk), поэтому открывать его на каждый материал × путь × VPK —
дорого. Здесь ОДИН общий кэш для всех потребителей (TF2VPKExtractService и
GameVpkReader): один и тот же игровой VPK открывается один раз на поток, а не по
разу в каждой подсистеме (раньше за один прогон preview-воркера misc_dir.vpk
открывался и кэшем извлечения, и GameVpkReader — два дорогих парсинга индекса).

Кэш ПОТОКО-ЛОКАЛЬНЫЙ: vpk-объект (общий seek+read по файлу архива) НЕ
потокобезопасен, а потребители работают в разных QThread-воркерах
(build / preview / skin-detect), которые могут идти параллельно. Свой хэндл на
поток исключает гонку данных, сохраняя переиспользование в пределах одного
прогона воркера. Когда поток завершается, его хэндлы освобождаются вместе с
thread-local хранилищем. Поэтому хэндлы НИКОГДА не закрываются вручную —
владелец кэш, а не вызывающий код.
"""

import threading

try:
    import vpk as _vpk
    _VPK_AVAILABLE = True
except ImportError:
    _VPK_AVAILABLE = False
    _vpk = None

_TLS = threading.local()


def vpk_available() -> bool:
    """Доступна ли библиотека vpk."""
    return _VPK_AVAILABLE


def open_vpk_cached(dir_vpk_path: str):
    """Открывает VPK один раз НА ПОТОК и переиспользует хэндл.

    Возвращает открытый vpk-объект или None, если библиотека vpk недоступна.
    Кэшированный хэндл закрывать НЕЛЬЗЯ — им владеет кэш.
    """
    if not _VPK_AVAILABLE:
        return None
    cache = getattr(_TLS, "cache", None)
    if cache is None:
        cache = {}
        _TLS.cache = cache
    v = cache.get(dir_vpk_path)
    if v is None:
        v = _vpk.open(dir_vpk_path)
        cache[dir_vpk_path] = v
    return v


def clear_vpk_cache() -> None:
    """Сбрасывает потоко-локальный кэш VPK текущего потока.

    Нужен в первую очередь тестам (изоляция): без сброса замоканный/устаревший
    vpk-объект мог бы протечь между тестами в одном потоке.
    """
    if hasattr(_TLS, "cache"):
        _TLS.cache = {}
