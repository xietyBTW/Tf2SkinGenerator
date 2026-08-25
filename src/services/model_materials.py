"""
Текстуры материалов модели для превью частиц.

Меш в окно превью попадает из reference-SMD, а имена его материалов — просто
строки вроде `c_sniperrifle`. Путь к VMT собирается из `$cdmaterials` в QC
(их бывает несколько, с разными слэшами), дальше обычная цепочка Source:
VMT → `$basetexture` → VTF → PNG. Скины (`$texturegroup`) не разбираем: меш
ссылается на материал первого скина, он и грузится.

Отдаётся data URL, потому что превью — это страница в QWebEngine и файловые
пути ей недоступны.
"""

import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from src.services import vmt_parse
from src.services.tf2_paths import TF2Paths
from src.services.vtf_preview_service import (
    open_vpks, read_from_vpks, vtf_bytes_to_png,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_RE_CDMATERIALS = re.compile(r'^\s*\$cdmaterials\s+"?([^"\r\n]*)"?', re.IGNORECASE)

#: Потолок стороны текстуры в превью: 2К-текстура в base64 — это мегабайты,
#: которые незачем гнать через runJavaScript ради серого силуэта под эффектом.
_MAX_SIDE = 1024


def cdmaterials_from_qc(qc_text: str) -> List[str]:
    """Пути $cdmaterials из QC, приведённые к виду `models/weapons/foo/`."""
    out: List[str] = []
    for line in qc_text.splitlines():
        m = _RE_CDMATERIALS.match(line)
        if m is None:
            continue
        path = m.group(1).replace("\\", "/").strip().strip('"').lower()
        # Ведущий слэш и задвоенные разделители встречаются в живых QC
        path = re.sub(r"/+", "/", path).lstrip("/")
        if path and not path.endswith("/"):
            path += "/"
        if path not in out:
            out.append(path)
    if "" not in out:
        out.append("")      # материал может лежать прямо в materials/
    return out


def _png_data_url(vtf_raw: bytes) -> Optional[str]:
    """VTF-байты → data URL PNG (первый кадр, с ограничением стороны)."""
    tmp_dir = tempfile.mkdtemp(prefix="tf2sg_modeltex_")
    png_path = os.path.join(tmp_dir, "tex.png")
    try:
        if vtf_bytes_to_png(vtf_raw, png_path) is None:
            return None
        from PIL import Image
        with Image.open(png_path) as img:
            if max(img.size) > _MAX_SIDE:
                img = img.copy()
                img.thumbnail((_MAX_SIDE, _MAX_SIDE))
                img.save(png_path)
        with open(png_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as exc:
        logger.warning(f"Текстура модели не подготовлена: {exc}")
        return None
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def resolve_model_textures(qc_path: str, mat_names: List[str],
                           tf2_root_dir: str) -> Dict[str, str]:
    """{имя материала: data URL PNG} для материалов меша.

    Материалы, которых нет в игровых VPK (мод, отсутствующий скин), просто
    не попадают в результат — меш покажется серым, но не пропадёт.
    """
    if not tf2_root_dir or not mat_names:
        return {}
    try:
        qc_text = Path(qc_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    try:
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
    except FileNotFoundError:
        return {}
    paks = open_vpks([TF2Paths.resolve_textures_vpk(tf2_root_dir), misc_vpk])
    if not paks:
        return {}

    cds = cdmaterials_from_qc(qc_text)
    out: Dict[str, str] = {}
    for name in mat_names:
        clean = name.replace("\\", "/").strip().lower()
        if clean.endswith(".vmt"):
            clean = clean[:-4]
        vmt_raw = None
        for cd in cds:
            vmt_raw = read_from_vpks(paks, f"materials/{cd}{clean}.vmt")
            if vmt_raw is not None:
                break
        if vmt_raw is None:
            logger.debug(f"VMT материала {name} не найден в VPK")
            continue
        vtf_rel = vmt_parse.basetexture(
            vmt_raw.decode("utf-8", errors="replace"))
        if not vtf_rel:
            continue
        if not vtf_rel.endswith(".vtf"):
            vtf_rel += ".vtf"
        if not vtf_rel.startswith("materials/"):
            vtf_rel = "materials/" + vtf_rel
        vtf_raw = read_from_vpks(paks, vtf_rel)
        if vtf_raw is None:
            logger.debug(f"VTF {vtf_rel} не найден в VPK")
            continue
        data_url = _png_data_url(vtf_raw)
        if data_url:
            out[name] = data_url
    return out
