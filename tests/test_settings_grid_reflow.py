"""Решение «две колонки или одна» для сеток панели экспорта.

QRadioButton и QCheckBox не сжимаются и не режут текст: если пара не влезает
по ширине, правая колонка молча уезжает за край панели, а горизонтальной
прокрутки там нет. Поэтому раскладка считается заранее — и считается по
максимумам колонок, а не по суммам пар: ширину колонки задаёт самый широкий
виджет в ней, даже если он стоит в другой строке.

Сам виджет здесь не поднимается: проверяется чистая арифметика решения.
"""

from src.ui.settings_panel import fits_two_columns


def test_empty_always_fits():
    assert fits_two_columns([], 8, 0) is True


def test_pair_fits_exactly():
    # 100 + 120 + 8 = 228 — ровно по ширине, значит влезает
    assert fits_two_columns([100, 120], 8, 228) is True
    assert fits_two_columns([100, 120], 8, 227) is False


def test_column_width_comes_from_widest_in_that_column():
    # Колонка 0 — max(60, 200) = 200; колонка 1 — max(50, 40) = 50
    widths = [60, 50, 200, 40]
    assert fits_two_columns(widths, 8, 258) is True
    assert fits_two_columns(widths, 8, 257) is False
    # Считать по самой широкой ПАРЕ было бы 240 и дало бы неверное «влезает»
    assert fits_two_columns(widths, 8, 248) is False


def test_odd_count_last_widget_still_counts():
    # Пятый виджет попадает в колонку 0 и может её расширить
    assert fits_two_columns([10, 10, 10, 10, 300], 8, 200) is False
    assert fits_two_columns([10, 10, 10, 10, 300], 8, 318) is True


def test_single_widget_needs_no_second_column():
    assert fits_two_columns([150], 8, 158) is True
    assert fits_two_columns([150], 8, 149) is False


def test_spacing_is_counted_once():
    assert fits_two_columns([100, 100], 0, 200) is True
    assert fits_two_columns([100, 100], 20, 200) is False
