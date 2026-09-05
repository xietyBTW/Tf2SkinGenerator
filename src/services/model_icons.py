"""
Обложка карточки для того, чего нет в рюкзаке.

Аптечки, патроны, снаряды, реквизит насмешек и небо — мировые объекты, а не
предметы инвентаря: иконки в `materials/backpack` у них нет и не будет, и
карточки в каталоге стояли пустыми. Показать при этом есть что — их
собственную текстуру.

Цепочка обычная для Source и целиком по заголовкам, без декомпиляции:
MDL (таблица материалов и `$cdmaterials`) → VMT → `$basetexture` → VTF → PNG.
У неба модели нет: берём переднюю грань (`<имя>ft.vtf`) — по ней небо и
узнают.

Готовые PNG лежат рядом с иконками рюкзака и переживают запуск: декодирование
VTF стоит дорого, а картинка предмета не меняется, пока не обновят игру.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Там же, где иконки рюкзака: это один и тот же кэш обложек каталога.
#: Имена с приставкой — иначе `medkit_small` от модели и от рюкзака сошлись бы.
_CACHE_DIR = Path("cache") / "icons"

#: Потолок стороны. Карточка каталога — 150 пикселей, а игровая текстура бывает
#: 2048x2048: без этого кэш обложек весил бы сотни мегабайт.
_MAX_SIDE = 256


def _cache_path(name: str) -> Path:
    slug = re.sub(r'[^a-zA-Z0-9._-]+', '_', name).strip('_').lower()
    return _CACHE_DIR / f"{slug[:100]}.png"


def _render(vtf: Optional[bytes], cache: Path) -> Optional[bytes]:
    """VTF-байты → PNG в кэше. None — если декодировать не удалось."""
    from src.services.vtf_preview_service import vtf_bytes_to_png

    if not vtf:
        return None
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if vtf_bytes_to_png(vtf, str(cache)) is None:
        return None
    _shrink(cache)
    return cache.read_bytes()


def _shrink(png: Path) -> None:
    """Ужимает картинку до размера карточки. Ошибка здесь не фатальна."""
    from PIL import Image

    try:
        with Image.open(png) as im:
            if max(im.size) <= _MAX_SIDE:
                return
            im.thumbnail((_MAX_SIDE, _MAX_SIDE))
            im.save(png)
    except Exception as exc:                          # noqa: BLE001
        logger.debug(f"[icons] не ужать {png.name}: {exc}")


def _basetexture(paks: list, material: str, cdmaterials: List[str]) -> Optional[str]:
    """Путь VTF (без `materials/` и расширения) для материала модели."""
    from src.services import vmt_parse
    from src.services.vtf_preview_service import read_from_vpks

    material = material.replace('\\', '/').strip('/').lower()
    # Папок поиска у модели несколько, и порядок их перечисления в MDL — это и
    # есть порядок поиска движка. Пустая строка в конце: материал бывает
    # прописан полным путём прямо в имени.
    for cd in list(cdmaterials) + ['']:
        # В MDL пути пишут по-виндовому и с ведущим слэшем (`\models\items\`):
        # без чистки выходило `materials//models/items/…`, и не находилось
        # ничего — ни у одной аптечки.
        cd = cd.replace('\\', '/').strip().strip('/').lower()
        if cd:
            cd += '/'
        raw = read_from_vpks(paks, f"materials/{cd}{material}.vmt")
        if raw is None:
            continue
        base = vmt_parse.basetexture(raw.decode('utf-8', 'ignore'))
        if base:
            # В живых VMT встречается «$basetexture …/foo.vtf» с расширением
            # (у Valve так написаны ботинки и бампер-кар): без обрезки путь
            # получался `foo.vtf.vtf`, и обложка не находилась.
            return base.replace('\\', '/').strip('/').lower().removesuffix('.vtf')
    return None


def model_png(mdl_path: str, misc_vpk: str, textures_vpk: str) -> Optional[bytes]:
    """PNG первой текстуры модели, либо None.

    Материал берём ПЕРВЫЙ подходящий: у карточки одна картинка, а разбирать
    скины и группы материалов ради обложки незачем.
    """
    from src.services.diagnostics.mdl_reader import parse_mdl
    from src.services.vtf_preview_service import open_vpks, read_from_vpks

    mdl_path = (mdl_path or '').replace('\\', '/').strip('/').lower()
    if not mdl_path.endswith('.mdl'):
        return None

    cache = _cache_path('model_' + mdl_path)
    if cache.exists():
        return cache.read_bytes()

    paks = open_vpks([misc_vpk, textures_vpk])
    if not paks:
        return None
    header = parse_mdl(read_from_vpks(paks, mdl_path) or b'')
    if not header.valid:
        return None

    for material in header.material_names:
        base = _basetexture(paks, material, header.cdmaterials)
        if not base:
            continue
        png = _render(read_from_vpks(paks, f"materials/{base}.vtf"), cache)
        if png:
            return png
    return None


def sky_png(name: str, textures_vpk: str) -> Optional[bytes]:
    """PNG боковой грани неба, либо None.

    Одна грань, а не панорама: карточке нужна узнаваемая картинка, а панораму
    собирает превью, когда небо уже выбрали. Именно боковая — небо узнают по
    горизонту, а верх у половины стоковых это ровная заливка.

    Имена берём общим правилом (`stock_face_stems`): VMT грани для этого не
    годятся — у стоковых небес они ссылаются на текстуру, которой в игре нет.
    """
    from src.data.skyboxes import stock_face_stems
    from src.services.vtf_preview_service import open_vpks, read_from_vpks

    name = (name or '').strip().lower()
    if not name:
        return None

    cache = _cache_path('sky_' + name)
    if cache.exists():
        return cache.read_bytes()

    paks = open_vpks([textures_vpk])
    if not paks:
        return None
    for stem in stock_face_stems(name, 'ft'):
        # HDR-версии лежат рядом и в игре главнее, но в обложке дают пересвет:
        # берём LDR и показываем как есть.
        png = _render(read_from_vpks(paks, f"materials/skybox/{stem}.vtf"), cache)
        if png:
            return png
    return None
