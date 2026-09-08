"""
Отсечка чужого источника у локального сервера.

Сервер локальный, но не изолированный: страница в браузере может перебрать
эфемерные порты и постучаться в него. Проверяем, что запрос со стороны не
доходит до `build`, `set_settings` и /upload, а свой — доходит.
"""

import unittest

from frontend import devserver


class _FakeHandler:
    def __init__(self, headers):
        self.headers = headers


def _req(**headers):
    return _FakeHandler(headers)


class SameOriginTest(unittest.TestCase):
    HOST = "127.0.0.1:51234"

    def test_own_page_passes(self):
        """POST со своей страницы: Origin наш, Sec-Fetch-Site same-origin."""
        self.assertTrue(devserver._same_origin(_req(
            Host=self.HOST,
            Origin=f"http://{self.HOST}",
            **{"Sec-Fetch-Site": "same-origin"},
        )))

    def test_navigation_passes(self):
        """Открытие самой страницы: Origin нет, Sec-Fetch-Site none."""
        self.assertTrue(devserver._same_origin(_req(
            Host=self.HOST, **{"Sec-Fetch-Site": "none"})))

    def test_no_browser_headers_passes(self):
        """Свой <img>/SSE и не-браузерный клиент: заголовков нет вовсе."""
        self.assertTrue(devserver._same_origin(_req(Host=self.HOST)))

    def test_foreign_origin_blocked(self):
        self.assertFalse(devserver._same_origin(_req(
            Host=self.HOST,
            Origin="https://evil.example",
            **{"Sec-Fetch-Site": "cross-site"},
        )))

    def test_foreign_origin_blocked_without_fetch_metadata(self):
        """Старый браузер без Sec-Fetch-*: ловим по одному Origin."""
        self.assertFalse(devserver._same_origin(_req(
            Host=self.HOST, Origin="https://evil.example")))

    def test_simple_post_without_origin_blocked(self):
        """
        POST с text/plain обходит preflight и МОЖЕТ прийти без Origin.
        Ловим его по Sec-Fetch-Site — Chromium шлёт его всегда.
        """
        self.assertFalse(devserver._same_origin(_req(
            Host=self.HOST, **{"Sec-Fetch-Site": "cross-site"})))

    def test_other_port_on_localhost_blocked(self):
        """Соседний порт — уже чужой источник."""
        self.assertFalse(devserver._same_origin(_req(
            Host=self.HOST, Origin="http://127.0.0.1:9999")))

    def test_cors_wildcard_is_off_by_default(self):
        """`Access-Control-Allow-Origin: *` включает только dev-запуск."""
        self.assertFalse(devserver.DEV_CORS)


if __name__ == "__main__":
    unittest.main()
