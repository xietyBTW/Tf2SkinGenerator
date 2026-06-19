"""Общие фикстуры pytest."""

import pytest


@pytest.fixture(autouse=True)
def _clear_vpk_cache_between_tests():
    """Сбрасывает общий потоко-локальный кэш открытых VPK до и после каждого теста.

    `vpk_cache.open_vpk_cached` кэширует vpk-объекты по пути в пределах потока
    (им пользуются и TF2VPKExtractService, и GameVpkReader). В тестах пути часто
    временные и переиспользуются между прогонами; без сброса закэшированный
    (возможно замоканный) объект мог бы протечь в соседний тест.
    """
    from src.services import vpk_cache

    vpk_cache.clear_vpk_cache()
    yield
    vpk_cache.clear_vpk_cache()
