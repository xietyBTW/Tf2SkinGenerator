"""
Фейковый VPK для тестов: словарь «путь → байты» вместо архива на диске.

Общая версия того, что раньше жило копиями в test_game_vpk_reader и
test_vtf_preview_service. Нужна не ради экономии двадцати строк, а чтобы
покрывать тестами то, что раньше не покрывалось вовсе: код поиска материалов
и текстур работает ТОЛЬКО против VPK, и без такого дублёра его приходилось
проверять руками на установленной игре.

Пример:

    reader = fake_reader({
        "materials/models/hat/hat.vmt": vmt(basetexture="models/hat/hat_color"),
        "materials/models/hat/hat_color.vtf": b"VTF...",
    })
"""

from typing import Dict, List, Optional

CR = chr(13)


class FakeEntry:
    """Запись архива: у vpklib у неё есть .read()."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakePak:
    """Архив: pak[path] → FakeEntry, иначе KeyError (как у vpklib).

    Считает обращения — по ним видно, не ходит ли код в архив по десять раз
    за одним и тем же файлом.
    """

    def __init__(self, files: Dict[str, bytes]):
        self._files = dict(files)
        self.reads: List[str] = []
        self.closed = False

    def __getitem__(self, path: str) -> FakeEntry:
        self.reads.append(path)
        if path in self._files:
            return FakeEntry(self._files[path])
        raise KeyError(path)

    def __contains__(self, path: str) -> bool:
        return path in self._files

    def close(self) -> None:
        self.closed = True

    @property
    def hits(self) -> List[str]:
        """Только удачные обращения, по порядку."""
        return [p for p in self.reads if p in self._files]


def fake_reader(files: Dict[str, bytes], extra: Optional[Dict[str, bytes]] = None):
    """GameVpkReader поверх фейковых архивов (без открытия файлов на диске).

    extra — второй архив: в игре VMT лежат в tf2_misc, а VTF в tf2_textures,
    и код обязан искать в обоих.
    """
    from src.services.game_vpk_reader import GameVpkReader

    reader = GameVpkReader([])
    paks = [FakePak(files)]
    if extra is not None:
        paks.append(FakePak(extra))
    reader._paks = paks
    return reader


def vmt(shader: str = "VertexLitGeneric", **params) -> bytes:
    """Текст VMT в формате Valve: табы, кавычки и CRLF-концы строк.

    Имена параметров пишутся как есть, с подчёркиваниями: `blendtintbybasealpha`
    → `$blendtintbybasealpha`.
    """
    lines = [f'"{shader}"', "{"]
    for key, value in params.items():
        lines.append(f'\t"${key}"\t\t"{value}"')
    lines.append("}")
    return (CR + "\n").join(lines).encode("utf-8")
