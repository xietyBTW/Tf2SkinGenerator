"""
Сжатие VTF в фоне на время сборки текстур

Сжатие DXT в srctools отпускает GIL, поэтому независимые текстуры сжимаются
одновременно в потоках (2048 жмётся несколько секунд, подряд это десятки). Готовый
VTF появляется в папке мода только к концу задачи: код, который читает уже
собранный VTF (копия главной, нормаль для синего), сначала зовёт wait()
"""

import os
from concurrent.futures import ThreadPoolExecutor, wait as _wait_all


class VtfJobs:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=os.cpu_count() or 4,
                                        thread_name_prefix="vtf")
        self._futures = []
        self._by_key = {}

    def submit(self, fn, *args, key=None) -> None:
        """key - файл, который пишет задача. Одно имя материала бывает в строке
        скинов дважды: второе сжатие ждёт первое, как шло бы подряд"""
        if key in self._by_key:
            _wait_all([self._by_key[key]])
        future = self._pool.submit(fn, *args)
        self._futures.append(future)
        if key is not None:
            self._by_key[key] = future

    def wait(self) -> None:
        """Дождаться всех задач. Ошибку не бросает: ждать могут внутри
        try, который глотает ошибки, а сборку она должна уронить. Её
        поднимет finish()"""
        _wait_all(self._futures)

    def finish(self) -> None:
        """Дождаться всех задач и поднять первую ошибку в порядке постановки,
        как при сжатии подряд"""
        self.wait()
        self._pool.shutdown()
        for future in self._futures:
            future.result()
