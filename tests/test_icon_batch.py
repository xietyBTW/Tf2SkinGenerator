"""Пачка иконок для каталога: data-URL по ключу, отсутствующих нет в ответе"""

import base64
import unittest
from unittest import mock

from src.app.api import catalog


def _fake_icon(key):
    if key == 'boom':
        raise OSError('битый архив')
    return {'hat': b'\x89PNG-hat', 'mat/scout': b'\x89PNG-mat'}.get(key)


class IconBatchTest(unittest.TestCase):
    def test_found_icons_come_as_data_urls(self):
        with mock.patch.object(catalog, 'icon_png', side_effect=_fake_icon):
            out = catalog.icons(['hat', 'mat/scout'])
        self.assertEqual(set(out), {'hat', 'mat/scout'})
        head, b64 = out['hat'].split(',', 1)
        self.assertEqual(head, 'data:image/png;base64')
        self.assertEqual(base64.b64decode(b64), b'\x89PNG-hat')

    def test_missing_and_broken_icons_are_left_out(self):
        with mock.patch.object(catalog, 'icon_png', side_effect=_fake_icon):
            out = catalog.icons(['hat', 'nothing', 'boom'])
        self.assertEqual(list(out), ['hat'])

    def test_batch_is_capped(self):
        keys = [f'k{i}' for i in range(catalog.ICON_BATCH_LIMIT + 10)]
        with mock.patch.object(catalog, 'icon_png', return_value=b'png') as png:
            out = catalog.icons(keys)
        self.assertEqual(png.call_count, catalog.ICON_BATCH_LIMIT)
        self.assertEqual(len(out), catalog.ICON_BATCH_LIMIT)

    def test_endpoint_is_open_to_the_page(self):
        from src.app import api
        self.assertIn('icons', api.ENDPOINTS)


if __name__ == '__main__':
    unittest.main()
