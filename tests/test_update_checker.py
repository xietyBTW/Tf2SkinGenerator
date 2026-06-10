import io
import json
import unittest
from unittest.mock import patch

from src.services.update_checker import _parse_version, _is_newer, fetch_latest_release


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _response(payload: dict) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"))


class ParseVersionTests(unittest.TestCase):
    def test_plain_and_prefixed(self):
        self.assertEqual(_parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(_parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(_parse_version("V2.0"), (2, 0, 0))

    def test_invalid_returns_zero(self):
        self.assertEqual(_parse_version("garbage"), (0, 0, 0))
        self.assertEqual(_parse_version(""), (0, 0, 0))

    def test_is_newer(self):
        self.assertTrue(_is_newer("1.0.3", "1.0.2"))
        self.assertTrue(_is_newer("2.0.0", "1.9.9"))
        self.assertFalse(_is_newer("1.0.2", "1.0.2"))
        self.assertFalse(_is_newer("1.0.1", "1.0.2"))


class FetchLatestReleaseTests(unittest.TestCase):
    def test_newer_release_returned(self):
        payload = {"tag_name": "v99.0.0", "html_url": "http://example/release",
                   "draft": False, "prerelease": False}
        with patch("urllib.request.urlopen", return_value=_response(payload)):
            result = fetch_latest_release()
        self.assertEqual(result, ("v99.0.0", "http://example/release"))

    def test_current_version_returns_none(self):
        payload = {"tag_name": "v0.0.1", "html_url": "x",
                   "draft": False, "prerelease": False}
        with patch("urllib.request.urlopen", return_value=_response(payload)):
            self.assertIsNone(fetch_latest_release())

    def test_prerelease_and_draft_ignored(self):
        for flags in ({"draft": True, "prerelease": False},
                      {"draft": False, "prerelease": True}):
            payload = {"tag_name": "v99.0.0", "html_url": "x", **flags}
            with patch("urllib.request.urlopen", return_value=_response(payload)):
                self.assertIsNone(fetch_latest_release())

    def test_missing_tag_returns_none(self):
        payload = {"html_url": "x", "draft": False, "prerelease": False}
        with patch("urllib.request.urlopen", return_value=_response(payload)):
            self.assertIsNone(fetch_latest_release())

    def test_network_error_returns_none(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            self.assertIsNone(fetch_latest_release())


if __name__ == "__main__":
    unittest.main()
