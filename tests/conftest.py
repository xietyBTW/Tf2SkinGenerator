"""Общие фикстуры pytest."""

import pytest


@pytest.fixture(autouse=True)
def _clear_vpk_cache_between_tests():
    """Сбрасывает общий кэш открытых VPK до и после каждого теста.

    `vpk_cache.open_vpk_cached` кэширует vpk-объекты по пути на весь запуск
    (им пользуются и TF2VPKExtractService, и GameVpkReader). В тестах пути часто
    временные и переиспользуются между прогонами; без сброса закэшированный
    (возможно замоканный) объект мог бы протечь в соседний тест.
    """
    from src.services import vpk_cache

    vpk_cache.clear_vpk_cache()
    yield
    vpk_cache.clear_vpk_cache()


# ── Заглушка PySide6: что от неё осталось ────────────────────────────────── #
#
# Раньше пять модулей (test_app_factory, test_base_worker, test_build_worker,
# test_extract_model_worker, test_extract_texture_worker) клали заглушку Qt
# прямо в sys.modules при импорте — иначе воркеры было не проверить, потому что
# они наследовались от QThread. Заглушка оставалась там навсегда, и всё, что
# импортировалось ПОСЛЕ, живого Qt уже не видело.
#
# Четыре из пяти больше не нужны: воркеры в `src/services` переведены на
# threading.Thread и собственный Signal (см. src/services/base_worker.py), Qt в
# этом слое нет вообще. Тесты работают с настоящими классами.
#
# Остался test_app_factory — он и правда проверяет Qt-код (QApplication, темы).
# Свою заглушку он теперь СНИМАЕТ в tearDown вместе с модулями, которые успели
# импортироваться под ней (_TAINTED), так что за пределы модуля она не течёт.
#
# Отдельная проблема окружения: если `import PySide6.QtWidgets` падает с
# «DLL load failed», Qt-зависимые модули отваливаются на сборе и прогон
# прерывается целиком. Это чинится переустановкой PySide6, а не тестами.
