"""Тесты базовых воркеров (StandardWorker.run-шаблон, BaseWorker.stop, Signal)."""

import unittest
from unittest.mock import Mock

from src.services.base_worker import BaseWorker, Signal, StandardWorker, UiRequest


class _OkWorker(StandardWorker):
    def work(self):
        self.progress.emit(50, "half")
        return True, "done"


class _FailWorker(StandardWorker):
    def work(self):
        raise RuntimeError("boom")


class SignalTests(unittest.TestCase):
    def test_slots_are_per_instance(self):
        """Сигнал объявлен в классе, но слоты у каждого экземпляра свои."""
        a, b = _OkWorker(), _OkWorker()
        seen = []
        a.progress.connect(lambda pct, msg: seen.append((pct, msg)))
        b.progress.emit(1, "b")
        self.assertEqual(seen, [])
        a.progress.emit(2, "a")
        self.assertEqual(seen, [(2, "a")])

    def test_disconnect(self):
        w = _OkWorker()
        slot = Mock()
        w.progress.connect(slot)
        w.progress.disconnect(slot)
        w.progress.emit(1, "x")
        slot.assert_not_called()

    def test_slot_exception_does_not_break_emit(self):
        """Падение одного обработчика не должно ронять воркер и глушить остальные."""
        w = _OkWorker()
        good = Mock()
        w.progress.connect(Mock(side_effect=RuntimeError("slot boom")))
        w.progress.connect(good)
        w.progress.emit(1, "x")
        good.assert_called_once_with(1, "x")


class StandardWorkerTests(unittest.TestCase):
    def test_work_success_emits_finished(self):
        w = _OkWorker()
        finished = Mock()
        w.finished.connect(finished)
        w.run()
        finished.assert_called_once_with(True, "done")

    def test_work_exception_becomes_error_and_finished_false(self):
        w = _FailWorker()
        error, finished = Mock(), Mock()
        w.error.connect(error)
        w.finished.connect(finished)
        w.run()
        error.assert_called_once_with("boom")
        finished.assert_called_once_with(False, "boom")

    def test_stop_when_not_running_returns_true(self):
        self.assertTrue(_OkWorker().stop())


class InterruptionTests(unittest.TestCase):
    def test_stop_interrupts_running_worker(self):
        """stop() должен и попросить прерваться, и дождаться выхода из run()."""
        import threading

        started = threading.Event()

        class _Spin(BaseWorker):
            def run(self):
                started.set()
                while not self.isInterruptionRequested():
                    pass

        w = _Spin()
        w.start()
        self.assertTrue(started.wait(2))
        self.assertTrue(w.stop(2000))
        self.assertFalse(w.isRunning())


class UiRequestTests(unittest.TestCase):
    """Протокол emit → ожидание → answer из другого потока."""

    class _Asker(BaseWorker):
        question = Signal(str)

    def test_answer_from_other_thread_unblocks_ask(self):
        import threading

        w = self._Asker()
        req = UiRequest(w.question, timeout_ms=5000)
        w.question.connect(lambda _q: threading.Thread(
            target=req.answer, args=("ответ",), daemon=True).start())
        self.assertEqual(req.ask("вопрос?"), "ответ")

    def test_answer_before_wait_is_not_lost(self):
        """UI ответил синхронно внутри emit — ask() не должен уйти в ожидание."""
        w = self._Asker()
        req = UiRequest(w.question, timeout_ms=5000)
        w.question.connect(lambda _q: req.answer(None))
        self.assertIsNone(req.ask("вопрос?"))

    def test_timeout_returns_none(self):
        w = self._Asker()
        req = UiRequest(w.question, timeout_ms=50)
        self.assertIsNone(req.ask("никто не ответит"))


if __name__ == "__main__":
    unittest.main()
