"""Оценка веса будущего VTF для сводки под превью.

Число показывается пользователю до сборки, поэтому важнее не абсолютная
точность, а верный порядок: DXT1 вчетверо легче RGBA8888, мип-уровни
добавляют треть, флаг NOMIP их убирает.
"""

import pytest

from src.services.vtf_size import human_size, vtf_bytes

BPP = {'DXT1': 4, 'DXT5': 8, 'RGB888': 24, 'RGBA16161616': 64}


def test_dxt1_is_half_byte_per_pixel():
    # 512*512 * 4 бита = 131072 байт, плюс треть на мипы
    assert vtf_bytes(512, 512, 'DXT1', [], BPP) == 131072 * 4 // 3


def test_nomip_drops_the_third():
    with_mips = vtf_bytes(512, 512, 'DXT1', [], BPP)
    without = vtf_bytes(512, 512, 'DXT1', ['NOMIP'], BPP)
    assert without == 131072
    assert with_mips > without


def test_other_flags_do_not_affect_size():
    assert (vtf_bytes(256, 256, 'DXT5', ['CLAMPS', 'CLAMPT'], BPP)
            == vtf_bytes(256, 256, 'DXT5', [], BPP))


def test_unknown_format_falls_back_to_32_bits():
    # Формат не из таблицы не должен ронять сводку
    assert vtf_bytes(64, 64, 'НЕТ ТАКОГО', ['NOMIP'], BPP) == 64 * 64 * 4


def test_flags_may_be_none():
    assert vtf_bytes(64, 64, 'DXT1', None, BPP) > 0


def test_relative_weights_hold():
    args = (1024, 1024, )
    dxt1 = vtf_bytes(*args, 'DXT1', ['NOMIP'], BPP)
    dxt5 = vtf_bytes(*args, 'DXT5', ['NOMIP'], BPP)
    deep = vtf_bytes(*args, 'RGBA16161616', ['NOMIP'], BPP)
    assert dxt5 == dxt1 * 2
    assert deep == dxt1 * 16


@pytest.mark.parametrize("num, expected", [
    (0, "0 KB"),
    (1024, "1 KB"),
    (700 * 1024, "700 KB"),
    (1024 * 1024, "1.0 MB"),
    (3 * 1024 * 1024 + 512 * 1024, "3.5 MB"),
])
def test_human_size(num, expected):
    assert human_size(num) == expected
