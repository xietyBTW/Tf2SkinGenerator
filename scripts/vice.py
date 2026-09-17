"""
ICE — шифр, которым Valve закрывает скрипты оружия (`scripts/tf_weapon_*.ctx`).

Алгоритм Мэттью Квана (1997), уровень 0: 64-битный ключ, 8 раундов — ровно
так его зовёт движок (`IceKey ice(0)` в UTIL_DecodeICE). Ключ TF2 общеизвестен
и один на всю игру. Нужен только сборщику таблицы источников эффектов
(scripts/particle_sources_build.py): приложение расшифровывать ничего не
должно, ему достаётся готовая таблица.

Проверка: расшифрованный скрипт начинается с `WeaponData`.
"""

from __future__ import annotations

#: Ключ скриптов оружия TF2.
TF2_KEY = b'E2NcUkG2'

_SMOD = ((333, 313, 505, 369), (379, 375, 319, 391),
         (361, 445, 451, 397), (397, 425, 395, 505))
_SXOR = ((0x83, 0x85, 0x9b, 0xcd), (0xcc, 0xa7, 0xad, 0x41),
         (0x4b, 0x2e, 0xd4, 0x33), (0xea, 0xcb, 0x2e, 0x04))
_PBOX = (0x00000001, 0x00000080, 0x00000400, 0x00002000,
         0x00080000, 0x00200000, 0x01000000, 0x40000000,
         0x00000008, 0x00000020, 0x00000100, 0x00004000,
         0x00010000, 0x00800000, 0x04000000, 0x20000000,
         0x00000004, 0x00000010, 0x00000200, 0x00008000,
         0x00020000, 0x00400000, 0x08000000, 0x10000000,
         0x00000002, 0x00000040, 0x00000800, 0x00001000,
         0x00040000, 0x00100000, 0x02000000, 0x80000000)
_KEYROT = (0, 1, 2, 3, 2, 1, 3, 0)


def _gf_mult(a: int, b: int, m: int) -> int:
    res = 0
    while b:
        if b & 1:
            res ^= a
        a <<= 1
        b >>= 1
        if a >= 256:
            a ^= m
    return res


def _gf_exp7(b: int, m: int) -> int:
    if b == 0:
        return 0
    x = _gf_mult(b, b, m)
    x = _gf_mult(b, x, m)
    x = _gf_mult(x, x, m)
    return _gf_mult(b, x, m)


def _perm32(x: int) -> int:
    res, i = 0, 0
    while x:
        if x & 1:
            res |= _PBOX[i]
        i += 1
        x >>= 1
    return res


def _sboxes():
    boxes = [[0] * 1024 for _ in range(4)]
    for i in range(1024):
        col = (i >> 1) & 0xff
        row = (i & 1) | ((i & 0x200) >> 8)
        for n, shift in enumerate((24, 16, 8, 0)):
            boxes[n][i] = _perm32(
                _gf_exp7(col ^ _SXOR[n][row], _SMOD[n][row]) << shift)
    return boxes


_SBOX = _sboxes()


def _round(p: int, sk) -> int:
    tl = ((p >> 16) & 0x3ff) | (((p >> 14) | (p << 18)) & 0xffc00)
    tr = (p & 0x3ff) | ((p << 2) & 0xffc00)
    al = sk[2] & (tl ^ tr)
    ar = al ^ tr
    al ^= tl
    al ^= sk[0]
    ar ^= sk[1]
    return (_SBOX[0][al >> 10] | _SBOX[1][al & 0x3ff]
            | _SBOX[2][ar >> 10] | _SBOX[3][ar & 0x3ff])


def schedule(key: bytes):
    """Раундовые ключи уровня 0 из 8 байт ключа."""
    if len(key) != 8:
        raise ValueError('ключ ICE уровня 0 — ровно 8 байт')
    kb = [0] * 4
    for j in range(4):
        kb[3 - j] = (key[j * 2] << 8) | key[j * 2 + 1]
    ks = [[0, 0, 0] for _ in range(8)]
    for i in range(8):
        kr = _KEYROT[i]
        isk = ks[i]
        for j in range(15):
            cur = j % 3
            for k in range(4):
                idx = (kr + k) & 3
                bit = kb[idx] & 1
                isk[cur] = ((isk[cur] << 1) | bit) & 0xffffffff
                kb[idx] = ((kb[idx] >> 1) | ((bit ^ 1) << 15)) & 0xffff
    return ks


def decrypt(data: bytes, key: bytes = TF2_KEY) -> bytes:
    """Расшифровывает блоками по 8 байт; неполный хвост отдаётся как есть."""
    ks = schedule(key)
    out = bytearray()
    for i in range(0, len(data) - len(data) % 8, 8):
        left = int.from_bytes(data[i:i + 4], 'big')
        right = int.from_bytes(data[i + 4:i + 8], 'big')
        for r in range(7, 0, -2):
            left ^= _round(right, ks[r])
            right ^= _round(left, ks[r - 1])
        out += right.to_bytes(4, 'big') + left.to_bytes(4, 'big')
    out += data[len(data) - len(data) % 8:]
    return bytes(out)


if __name__ == '__main__':
    import sys

    print(decrypt(open(sys.argv[1], 'rb').read()).decode('utf-8', 'replace'))
