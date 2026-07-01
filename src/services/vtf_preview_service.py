"""
Утилиты превью VTF: открыть VPK, прочитать файл, декодировать VTF → PNG.

Вынесено из дублей в preview_3d_worker / preview_panel — раньше связка
«temp .vtf → VTFLib.read_vtf_all_frames → Image.frombytes → .png» повторялась
в десятке мест. Теперь один источник.
"""

import os
import re
import tempfile
from typing import List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_RE_ANIM_FPS = re.compile(r'"animatedtextureframerate"\s+"?([0-9.]+)"?', re.IGNORECASE)


def open_vpks(paths: List[Optional[str]]) -> list:
    """Открывает существующие VPK из списка путей (несуществующие/битые пропускает).

    Хэндлы берутся из общего потоко-локального кэша (один парсинг индекса на
    поток) и принадлежат ему — закрывать их нельзя. Использовать только для
    ИГРОВЫХ VPK: кэш держит файл открытым до конца потока, для временных
    пользовательских VPK это мешало бы их удалению.
    """
    from src.services.vpk_cache import open_vpk_cached
    paks: list = []
    for p in paths:
        if p and os.path.exists(p):
            try:
                pak = open_vpk_cached(p)
                if pak is not None:
                    paks.append(pak)
            except Exception as exc:
                logger.debug(f"[VTF] не удалось открыть VPK {p}: {exc}")
    return paks


def read_from_vpks(paks: list, vpk_path: str) -> Optional[bytes]:
    """Возвращает байты файла по пути внутри первого VPK, где он есть."""
    for pak in paks:
        try:
            return pak[vpk_path].read()
        except KeyError:
            continue
        except Exception:
            continue
    return None


def parse_animated_framerate(vmt_content: str) -> Optional[float]:
    """Парсит animatedtextureframerate из текста VMT (None если ключа нет)."""
    m = _RE_ANIM_FPS.search(vmt_content)
    return max(0.1, float(m.group(1))) if m else None


def read_vmt_framerate(pak, vmt_paths: List[str], default: float = 15.0) -> float:
    """animatedtextureframerate из первого ЧИТАЕМОГО VMT в pak; default если нет.

    Раньше эта связка («перебрать VMT-пути в паке → найти framerate») повторялась
    в preview_3d_worker и preview_vpk_mod_worker (в т.ч. инлайн) — теперь один
    источник. Первый успешно прочитанный VMT определяет результат (как и раньше:
    нашли framerate → он; VMT есть, но без ключа → default).
    """
    if pak is None:
        return default
    for path in vmt_paths:
        try:
            content = pak[path].read().decode("utf-8", errors="replace")
        except KeyError:
            continue
        except Exception:
            continue
        fps = parse_animated_framerate(content)
        return fps if fps is not None else default
    return default


def vtf_bytes_to_png(data: Optional[bytes], out_png_path: str,
                     tmp_dir: Optional[str] = None) -> Optional[str]:
    """
    Декодирует байты VTF и сохраняет первый кадр как RGBA-PNG в out_png_path.
    Возвращает out_png_path или None при ошибке/пустых данных.
    """
    if not data:
        return None
    from PIL import Image
    from src.services.vtflib_wrapper import VTFLib

    tmp_dir = tmp_dir or os.path.dirname(out_png_path) or tempfile.gettempdir()
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_vtf = os.path.join(tmp_dir, f"_tmp_{os.path.basename(out_png_path)}.vtf")
    frames = w = h = None
    try:
        with open(tmp_vtf, "wb") as f:
            f.write(data)
        frames, w, h = VTFLib.read_vtf_all_frames(tmp_vtf)
    except Exception as exc:
        logger.warning(f"[VTF] декодирование не удалось ({out_png_path}): {exc}")
        return None
    finally:
        try:
            os.remove(tmp_vtf)
        except OSError:
            pass
    if not frames:
        return None
    Image.frombytes("RGBA", (w, h), frames[0]).save(out_png_path)
    return out_png_path


def vtf_bytes_to_frame_pngs(data: Optional[bytes], out_dir: str, base_name: str,
                            tmp_dir: Optional[str] = None) -> List[str]:
    """
    Декодирует VTF и сохраняет ВСЕ кадры как PNG (для анимированных текстур).
    Один кадр → {base}.png; несколько → {base}_000.png, {base}_001.png, …
    Возвращает список путей по порядку (пустой при ошибке/нет кадров).
    """
    if not data:
        return []
    from PIL import Image
    from src.services.vtflib_wrapper import VTFLib

    tmp_dir = tmp_dir or out_dir
    os.makedirs(out_dir, exist_ok=True)
    tmp_vtf = os.path.join(tmp_dir, f"_tmp_{base_name}.vtf")
    frames = w = h = None
    try:
        with open(tmp_vtf, "wb") as f:
            f.write(data)
        frames, w, h = VTFLib.read_vtf_all_frames(tmp_vtf)
    except Exception as exc:
        logger.warning(f"[VTF] декодирование кадров не удалось ({base_name}): {exc}")
        return []
    finally:
        try:
            os.remove(tmp_vtf)
        except OSError:
            pass
    if not frames:
        return []
    multi = len(frames) > 1
    paths: List[str] = []
    for i, rgba in enumerate(frames):
        name = f"{base_name}_{i:03d}.png" if multi else f"{base_name}.png"
        path = os.path.join(out_dir, name)
        Image.frombytes("RGBA", (w, h), rgba).save(path)
        paths.append(path)
    return paths
