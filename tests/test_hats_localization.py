"""
Названия косметики из локализации игры.

Строки в tf_<язык>.txt бывают с экранированными кавычками и управляющими
символами. Наивный разбор ломался на них молча: у «Рыцаря Туфорта» вместо
названия оставался одинокий слеш, а следующая строка съезжала.
"""

import unittest

from src.data.hats_parser import _clean_display, _LOC_LINE


def parse(text: str) -> dict:
    """То же, что делает _parse_localization, но без чтения файла."""
    return {m.group(1).lower(): _clean_display(m.group(2))
            for m in _LOC_LINE.finditer(text)}


class LocalizationParsingTests(unittest.TestCase):

    def test_escaped_quotes_survive(self):
        """У предмета кавычки — часть названия («"Рыцарь Туфорта"»)."""
        tokens = parse('"TF_bak_teufort_knight"\t"\\"Рыцарь Туфорта\\""\n')
        self.assertEqual(tokens['tf_bak_teufort_knight'], '"Рыцарь Туфорта"')

    def test_escaped_quote_does_not_shift_the_next_line(self):
        """Обрыв на кавычке уводил разбор в соседнюю строку."""
        text = ('"TF_a"\t"\\"Имя\\""\n'
                '"TF_b"\t"Соседняя строка"\n')
        tokens = parse(text)
        self.assertEqual(tokens['tf_b'], 'Соседняя строка')

    def test_control_characters_are_stripped(self):
        """Цветовые коды чата в названии предмета выглядят как мусор."""
        self.assertEqual(_clean_display('\x05Турецкий огурчик'), 'Турецкий огурчик')
        self.assertEqual(_clean_display('Капюшон ниндзя\n'), 'Капюшон ниндзя')

    def test_value_does_not_swallow_a_line_break(self):
        """`[^"]*` захватывал перевод строки, склеивая две записи в одну."""
        tokens = parse('"TF_a"\t"Первое"\n"TF_b"\t"Второе"\n')
        self.assertEqual(tokens['tf_a'], 'Первое')
        self.assertEqual(tokens['tf_b'], 'Второе')

    def test_plain_names_are_untouched(self):
        tokens = parse('"TF_hat"\t"Шляпа"\n')
        self.assertEqual(tokens['tf_hat'], 'Шляпа')


if __name__ == '__main__':
    unittest.main()
