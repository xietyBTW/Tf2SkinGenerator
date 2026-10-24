"""Карточка аддитивного материала: цвет на альфу, альфа растянута до полной"""

import base64
import io

from PIL import Image

from src.services.particle_editor.materials import additive_card_url


def _url(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _open(url):
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def test_faint_alpha_stretched_to_full():
    img = Image.new("RGBA", (2, 1), (200, 100, 50, 0))
    img.putpixel((1, 0), (200, 100, 50, 37))
    out = _open(additive_card_url(_url(img)))
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (0, 0, 0)
    assert out.getpixel((1, 0)) == (200, 100, 50)


def test_empty_alpha_means_plain_color():
    out = _open(additive_card_url(_url(Image.new("RGBA", (1, 1), (9, 8, 7, 0)))))
    assert out.getpixel((0, 0)) == (9, 8, 7)


def test_broken_url_returned_as_is():
    assert additive_card_url("data:image/png;base64,???") == "data:image/png;base64,???"
