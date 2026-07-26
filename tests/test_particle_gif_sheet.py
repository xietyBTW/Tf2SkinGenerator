"""Гифка как текстура партикла: спрайт-лист + sheet-данные для превью.

Отдельный файл, а не test_particle_editor_service.py: тот целиком
пропускается без srctools, а этим проверкам srctools не нужен.
"""

import pytest

from src.services.particle_editor_service import ParticleEditorService


def test_gif_to_sheet_layout(tmp_path):
    """Гифка → спрайт-лист POT + sheet-данные того же формата, что у игровых
    листов (иначе движок превью её не заанимирует)."""
    from PIL import Image

    gif = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (40, 40), c)
              for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    frames[0].save(gif, save_all=True, append_images=frames[1:],
                   duration=100, loop=0)

    sheet_img, sheet = ParticleEditorService._gif_to_sheet(str(gif), 512)

    # 3 кадра → сетка 2x2, лист целиком укладывается в заданный размер (512)
    assert sheet_img.size == (512, 512)
    seq = sheet["sequences"][0]
    assert seq["clamp"] is False
    assert len(seq["frames"]) == 3
    assert seq["duration"] == pytest.approx(3.0)
    # Кадр 1 — правая верхняя клетка; v-координаты сверху вниз, как в Source
    assert seq["frames"][1]["coords"][0] == [0.5, 0.0, 1.0, 0.5]
    assert seq["frames"][2]["coords"][0] == [0.0, 0.5, 0.5, 1.0]
    # Кадры действительно легли в свои клетки (цвет в центре клетки)
    assert sheet_img.getpixel((128, 128))[:3] == (255, 0, 0)
    assert sheet_img.getpixel((384, 128))[:3] == (0, 255, 0)
    assert sheet_img.getpixel((128, 384))[:3] == (0, 0, 255)
    # Свободная 4-я клетка прозрачна и ни одним кадром не адресуется
    assert sheet_img.getpixel((384, 384))[3] == 0


def test_image_to_vtf_gif_keeps_full_res_frame(tmp_path):
    """У анимации в превью уходит лист, а в VTF — первый кадр в полном
    разрешении (в игре без ресурса .sht анимации всё равно нет)."""
    from PIL import Image

    gif = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (256, 256), c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(gif, save_all=True, append_images=frames[1:],
                   duration=100, loop=0)

    built = ParticleEditorService._image_to_vtf(str(gif), 256, uncompressed=True)
    if built is None:
        pytest.skip("VTFLib недоступен")
    assert (built["w"], built["h"]) == (256, 256)   # клетка листа была бы 128
    assert built["sheet"] is not None
    assert built["fps"] == 10                       # 100 мс на кадр
    # VTF многокадровый: RGBA8888 256x256 x2 кадра (в игре крутит прокси)
    assert len(built["vtf"]) > 256 * 256 * 4


def test_gif_material_gets_animated_texture_proxy(tmp_path):
    """Гифка → в VMT материала прокси AnimatedTexture: тот же механизм, что
    крутит анимированные текстуры оружия в игре."""
    from PIL import Image

    svc = ParticleEditorService()
    svc._resolve_texture_path = lambda material_name, tf2_root_dir: (
        '"SpriteCard"\n{\n\t"$basetexture" "effects/test"\n}\n', "effects/test")

    gif = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (64, 64), c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(gif, save_all=True, append_images=frames[1:],
                   duration=100, loop=0)

    info = svc._overwrite_texture("effects/test.vmt", str(gif), "", 256, False)
    if info is None:
        pytest.skip("VTFLib недоступен")

    vmt = svc.custom_files["materials/effects/test.vmt"].decode().lower()
    assert '"animatedtexturevar" "$basetexture"' in vmt
    assert '"animatedtextureframenumvar" "$frame"' in vmt
    assert '"animatedtextureframerate" "10"' in vmt
    assert '"$frame" "0"' in vmt
    # Превью получает лист, а не первый кадр
    assert info["sheet"] is not None
