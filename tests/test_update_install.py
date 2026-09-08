"""
Скачивание и запуск обновления.

Проверяем ровно то, из-за чего обновление может испортить установку: битый
файл не должен доехать до запуска установщика, а недокачанный — остаться на
диске под именем готового.
"""

import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import update_checker as uc


class _FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, headers=None):
        super().__init__(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


PAYLOAD = b"pretend this is Setup.exe" * 100
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch("tempfile.gettempdir", return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name) / "tf2sg_update"

    def test_good_download_verified_and_renamed(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse(PAYLOAD)):
            dest = uc.download_update("http://example/setup.exe",
                                      expected_digest=DIGEST,
                                      expected_size=len(PAYLOAD))
        self.assertEqual(dest.name, uc.ASSET_NAME)
        self.assertEqual(dest.read_bytes(), PAYLOAD)
        # .part не должен остаться рядом с готовым файлом
        self.assertFalse((self.out_dir / (uc.ASSET_NAME + ".part")).exists())

    def test_wrong_digest_rejected_and_nothing_left(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse(PAYLOAD)):
            with self.assertRaises(RuntimeError):
                uc.download_update("http://example/setup.exe",
                                   expected_digest="0" * 64)
        self.assertFalse((self.out_dir / uc.ASSET_NAME).exists())
        self.assertFalse((self.out_dir / (uc.ASSET_NAME + ".part")).exists())

    def test_short_download_rejected(self):
        """Оборвалась закачка — размер не сойдётся, ставить нельзя."""
        with patch("urllib.request.urlopen", return_value=_FakeResponse(PAYLOAD)):
            with self.assertRaises(RuntimeError):
                uc.download_update("http://example/setup.exe",
                                   expected_size=len(PAYLOAD) + 1)
        self.assertFalse((self.out_dir / uc.ASSET_NAME).exists())

    def test_progress_reported(self):
        seen = []
        with patch("urllib.request.urlopen", return_value=_FakeResponse(PAYLOAD)):
            uc.download_update("http://example/setup.exe",
                               expected_digest=DIGEST,
                               progress=lambda done, total: seen.append(done))
        self.assertTrue(seen)
        self.assertEqual(seen[-1], len(PAYLOAD))

    def test_install_refuses_missing_file(self):
        with self.assertRaises(RuntimeError):
            uc.install_update(str(Path(self._tmp.name) / "нет-такого.exe"))

    def test_install_passes_command_as_one_string(self):
        """
        Регресс: команда уходит СТРОКОЙ, а не списком.

        Списком её собирает list2cmdline, и тот экранирует наши кавычки —
        cmd отвечает «синтаксическая ошибка в имени файла», причём молча:
        Popen отработал, установщик не запустился. Ловится только так,
        потому что исключения нет.
        """
        setup = Path(self._tmp.name) / "путь с пробелом" / uc.ASSET_NAME
        setup.parent.mkdir(parents=True)
        setup.write_bytes(b"MZ")

        with patch("subprocess.Popen") as popen:
            uc.install_update(str(setup))

        args = popen.call_args.args[0]
        self.assertIsInstance(args, str, "команда должна быть одной строкой")
        self.assertIn(f'"{setup}"', args, "путь обязан быть в кавычках")
        self.assertIn("ping", args, "пауза перед запуском обязана остаться")


class CheckForUpdateTests(unittest.TestCase):
    def _release(self, **over):
        data = {
            "tag_name": "v99.0.0",
            "html_url": "http://example/release",
            "body": "что нового",
            "draft": False,
            "prerelease": False,
            "assets": [{
                "name": uc.ASSET_NAME,
                "browser_download_url": "http://example/setup.exe",
                "size": 1234,
                "digest": "sha256:" + "a" * 64,
            }],
        }
        data.update(over)
        return _FakeResponse(json.dumps(data).encode("utf-8"))

    def test_new_version_with_asset(self):
        with patch("urllib.request.urlopen", return_value=self._release()):
            with patch.object(uc, "is_frozen", return_value=True):
                r = uc.check_for_update()
        self.assertTrue(r["available"])
        self.assertTrue(r["can_install"])
        self.assertEqual(r["version"], "99.0.0")
        self.assertEqual(r["asset_digest"], "a" * 64)   # префикс sha256: снят

    def test_cannot_install_from_sources(self):
        """Из репозитория обновляются через git, а не запуском Setup.exe."""
        with patch("urllib.request.urlopen", return_value=self._release()):
            with patch.object(uc, "is_frozen", return_value=False):
                r = uc.check_for_update()
        self.assertTrue(r["available"])
        self.assertFalse(r["can_install"])

    def test_release_without_installer(self):
        with patch("urllib.request.urlopen", return_value=self._release(assets=[])):
            with patch.object(uc, "is_frozen", return_value=True):
                r = uc.check_for_update()
        self.assertTrue(r["available"])
        self.assertFalse(r["can_install"])
        self.assertTrue(r["page_url"])          # остаётся ссылка «открыть релиз»

    def test_offline_is_not_an_update(self):
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("offline")):
            r = uc.check_for_update()
        self.assertFalse(r["checked"])
        self.assertFalse(r["available"])


class ProgressTests(unittest.TestCase):
    """
    Ход обновления: страница спрашивает его опросом, пока идёт скачивание.

    Установщик носит приложение внутри себя — это десятки мегабайт, и молча
    ждать ответа страница не может.
    """

    def setUp(self):
        from src.app import api
        self.api = api
        api._update_run.clear()
        api._update_run['state'] = 'idle'
        self.addCleanup(lambda: (api._update_run.clear(),
                                 api._update_run.update({'state': 'idle'})))

    def _info(self, **over):
        data = {'can_install': True, 'version': '99.0.0',
                'asset_url': 'http://example/setup.exe',
                'asset_digest': 'd' * 64, 'asset_size': 1000}
        data.update(over)
        return data

    def test_call_returns_at_once_and_progress_follows(self):
        import time
        released = threading.Event()

        def slow_download(url, expected_digest='', expected_size=0,
                          progress=None, cancelled=None):
            progress(500, 1000)
            released.wait(5)
            progress(1000, 1000)
            return Path('setup.exe')

        with patch.object(self.api, 'update_status', return_value=self._info()), \
             patch('src.services.update_checker.download_update', slow_download), \
             patch('src.services.update_checker.install_update'), \
             patch.object(self.api, '_quit_soon'):
            started = time.perf_counter()
            answer = self.api.install_update()
            elapsed = time.perf_counter() - started

            self.assertTrue(answer.get('started'))
            self.assertLess(elapsed, 1.0, 'вызов обязан вернуться сразу')

            for _ in range(50):
                if self.api.update_progress().get('done'):
                    break
                time.sleep(0.02)
            mid = self.api.update_progress()
            self.assertEqual(mid['state'], 'downloading')
            self.assertEqual((mid['done'], mid['total']), (500, 1000))

            released.set()
            for _ in range(100):
                if self.api.update_progress().get('state') == 'done':
                    break
                time.sleep(0.02)
            self.assertEqual(self.api.update_progress()['state'], 'done')

    def test_second_press_does_not_start_second_download(self):
        calls = []

        def counting(url, **kw):
            calls.append(url)
            return Path('setup.exe')

        with patch.object(self.api, 'update_status', return_value=self._info()), \
             patch('src.services.update_checker.download_update', counting), \
             patch('src.services.update_checker.install_update'), \
             patch.object(self.api, '_quit_soon'):
            self.api.install_update()
            import time
            for _ in range(100):
                if self.api.update_progress().get('state') == 'done':
                    break
                time.sleep(0.02)
            self.api.install_update()          # второе нажатие
            time.sleep(0.1)
        self.assertEqual(len(calls), 1)

    def test_failure_is_reported_not_swallowed(self):
        import time

        def boom(url, **kw):
            raise RuntimeError('контрольная сумма не совпала')

        with patch.object(self.api, 'update_status', return_value=self._info()), \
             patch('src.services.update_checker.download_update', boom), \
             patch.object(self.api, '_quit_soon'):
            self.api.install_update()
            for _ in range(100):
                if self.api.update_progress().get('state') == 'error':
                    break
                time.sleep(0.02)
        state = self.api.update_progress()
        self.assertEqual(state['state'], 'error')
        self.assertIn('контрольная сумма', state['error'])

    def test_nothing_to_install_is_refused_before_any_thread(self):
        with patch.object(self.api, 'update_status',
                          return_value=self._info(can_install=False)):
            answer = self.api.install_update()
        self.assertIn('error', answer)
        self.assertEqual(self.api.update_progress()['state'], 'idle')

if __name__ == "__main__":
    unittest.main()
