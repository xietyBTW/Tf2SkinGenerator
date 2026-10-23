"""Sheet-данные (спрайт-лист частиц) из ресурса VTF 0x10"""

import struct
from typing import Dict, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def parse_vtf_sheet(raw: bytes) -> Optional[dict]:
    """
    Извлекает sheet-данные (спрайт-лист частиц) из ресурса VTF 0x10

    Формат VTF 7.3+: numResources по смещению 0x44, записи ресурсов с 0x50
    по 8 байт: тег (3 байта + флаг) и смещение данных. Тег 0x10 - sheet.
    Формат sheet: version(u32 0|1), sequenceCount(u32), на секвенцию:
    seqNo, clamp, frameCount (u32×3), totalDuration(f32), на кадр:
    duration(f32) + N×(u0,v0,u1,v1) f32, где N=4 при version=1 иначе 1

    Returns:
        {"sequences": {seqNo: {"clamp": bool, "duration": float,
         "frames": [{"duration": float, "coords": [[u0,v0,u1,v1], ...]}]}}}
        либо None (нет ресурса / старая версия VTF / битые данные)
    """
    try:
        if len(raw) < 0x50 or raw[:4] != b"VTF\x00":
            return None
        ver_major, ver_minor = struct.unpack_from("<II", raw, 4)
        if ver_major != 7 or ver_minor < 3:
            return None
        (num_resources,) = struct.unpack_from("<I", raw, 0x44)
        sheet_offs = None
        for i in range(num_resources):
            entry = 0x50 + i * 8
            tag = raw[entry:entry + 3]
            flag = raw[entry + 3]
            (data_offs,) = struct.unpack_from("<I", raw, entry + 4)
            if tag == b"\x10\x00\x00" and flag != 0x02:
                sheet_offs = data_offs
                break
        if sheet_offs is None:
            return None

        (size,) = struct.unpack_from("<I", raw, sheet_offs)
        buf = raw[sheet_offs + 4: sheet_offs + 4 + size]
        pos = 0

        def u32():
            nonlocal pos
            (v,) = struct.unpack_from("<I", buf, pos)
            pos += 4
            return v

        def f32():
            nonlocal pos
            (v,) = struct.unpack_from("<f", buf, pos)
            pos += 4
            return v

        version = u32()
        if version not in (0, 1):
            return None
        coords_per_frame = 4 if version == 1 else 1
        sequences: Dict[int, dict] = {}
        for _ in range(u32()):
            seq_no = u32()
            clamp = u32() != 0
            frame_count = u32()
            total_duration = f32()
            frames = []
            for _f in range(frame_count):
                duration = f32()
                coords = []
                for _c in range(coords_per_frame):
                    coords.append([f32(), f32(), f32(), f32()])
                frames.append({"duration": duration, "coords": coords})
            sequences[seq_no] = {
                "clamp": clamp, "duration": total_duration, "frames": frames,
            }
        return {"sequences": sequences}
    except (struct.error, IndexError) as exc:
        logger.warning(f"Sheet-данные VTF не распарсились: {exc}")
        return None
