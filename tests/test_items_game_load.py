"""
Один разбор items_game.txt на процесс.

Его читают краски, иконки каталога, анимации вьюмодели, стоковое оружие и
модели War Paint. При старте иконки каталога приходили параллельно, и каждая
разбирала 8 МБ сама: в консоли четыре раза «items_game: … предметов», а окно,
чьи обработчики сообщений на Python, замирало без GIL.
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data import items_game_kv as kv

ITEMS = '"items_game"\n{\n\t"prefabs"\n\t{\n\t}\n\t"items"\n\t{\n%s\t}\n}\n'


def items_file(path, count):
    body = "".join(f'\t\t"{i}"\n\t\t{{\n\t\t\t"name" "item{i}"\n\t\t}}\n' for i in range(count))
    Path(path).write_text(ITEMS % body, encoding="utf-8")


class LoadTests(unittest.TestCase):
    def setUp(self):
        kv._loaded.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "items_game.txt")
        items_file(self.path, 3)

    def tearDown(self):
        kv._loaded.clear()
        self.tmp.cleanup()

    def test_parallel_callers_share_one_parse(self):
        real = kv.ItemsGame.parse
        calls = []

        def slow(content):
            calls.append(1)
            time.sleep(0.05)          # пока первый разбирает, приходят остальные
            return real(content)

        got = []
        with patch.object(kv.ItemsGame, "parse", side_effect=slow):
            threads = [threading.Thread(target=lambda: got.append(kv.ItemsGame.load(self.path)))
                       for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(g is got[0] for g in got))
        self.assertEqual(len(got[0].items), 3)

    def test_changed_file_is_parsed_again(self):
        self.assertEqual(len(kv.ItemsGame.load(self.path).items), 3)
        items_file(self.path, 5)
        os.utime(self.path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
        self.assertEqual(len(kv.ItemsGame.load(self.path).items), 5)

    def test_missing_file(self):
        self.assertIsNone(kv.ItemsGame.load(os.path.join(self.tmp.name, "nope.txt")))


if __name__ == "__main__":
    unittest.main()
