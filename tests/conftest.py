"""Общие фикстуры pytest"""

import atexit
import shutil
import tempfile

import pytest

# Временные файлы всего прогона - в одну папку, которая удаляется в конце.
# Два десятка тестов зовут mkdtemp() без уборки, и в %TEMP% копились десятки
# тысяч папок tmp* (13 865 штук на 105 МБ). Ставится ДО импорта тестовых
# модулей: devserver считает разрешённые корни от gettempdir() при импорте
_RUN_TMP = tempfile.mkdtemp(prefix='tf2sg_tests_')
tempfile.tempdir = _RUN_TMP
atexit.register(shutil.rmtree, _RUN_TMP, True)

# Работы - тоже во временную папку. Без этого тест, забывший подменить
# WORK_DIR, писал черновик в НАСТОЯЩУЮ папку работ (в разработке это work/
# репозитория) и мог затереть живой черновик человека своим мусором
from pathlib import Path  # noqa: E402

from src.services import work_store  # noqa: E402

work_store.WORK_DIR = Path(_RUN_TMP) / 'work'


@pytest.fixture(autouse=True)
def _clear_vpk_cache_between_tests():
    """Сбрасывает общий кэш открытых VPK до и после каждого теста

    `vpk_cache.open_vpk_cached` кэширует vpk-объекты по пути на весь запуск
    (им пользуются и TF2VPKExtractService, и GameVpkReader). В тестах пути часто
    временные и переиспользуются между прогонами, без сброса закэшированный
    (возможно замоканный) объект мог бы протечь в соседний тест
    """
    from src.services import texture_compose_service, vpk_cache, vtf_preview_service

    vpk_cache.clear_vpk_cache()
    # Кэш склейки частей держит основы и готовые окна по пути файла, тест,
    # перезаписавший основу, не должен получить картинку соседа
    texture_compose_service.clear_caches()
    # PNG текстур помнятся по содержимому VTF, а фальшивые VTF у тестов одни
    # и те же при разных подменах декодера
    vtf_preview_service.clear_png_cache()
    yield
    vpk_cache.clear_vpk_cache()

