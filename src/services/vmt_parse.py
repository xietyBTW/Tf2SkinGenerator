"""
Разбор VMT как дерева KeyValues — единственный способ ЧИТАТЬ материалы.

Почему не регулярки. VMT — это не строки вида «$param значение», а дерево:
у материала есть шейдер, параметры, вложенные блоки (`proxies`, `>=DX90`,
`replace`), комментарии `//` и значения в кавычках с пробелами и обратными
слэшами. Регулярка по строке не отличает настоящий параметр от
закомментированного и от упоминания внутри прокси. Так и было: шесть
независимых наборов регулярок в разных модулях расходились на одних и тех же
файлах — два из трёх парсеров $basetexture возвращали ЗАКОММЕНТИРОВАННОЕ
значение, а часть не нормализовала обратные слэши.

Здесь один разбор и типизированный доступ к нему. Модуль только ЧИТАЕТ:
правка VMT остаётся текстовой (VMTService), потому что там важно сохранить
исходное форматирование файла пользователя.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Токены: строка в кавычках, скобки блока, либо голое слово.
_TOKEN = re.compile(r'"([^"]*)"|([{}])|([^\s{}"]+)')
#: Комментарий до конца строки; внутри кавычек `//` комментарием НЕ является,
#: поэтому режем построчно с учётом чётности кавычек (см. _strip_comments).
_LINE_COMMENT = "//"


def _strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        in_quotes = False
        cut = None
        for i, ch in enumerate(line):
            if ch == '"':
                in_quotes = not in_quotes
            elif (not in_quotes and ch == "/" and i + 1 < len(line)
                  and line[i + 1] == "/"):
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def _tokenize(text: str) -> List[Tuple[str, str]]:
    """[(вид, значение)] где вид — 'str' | 'brace'.

    Идём по finditer, а не по findall: у findall несовпавшие группы тоже
    пустые строки, и отличить `""` от голого слова становится нельзя.
    """
    tokens: List[Tuple[str, str]] = []
    for m in _TOKEN.finditer(_strip_comments(text)):
        quoted, brace, bare = m.group(1), m.group(2), m.group(3)
        if brace is not None:
            tokens.append(("brace", brace))
        elif quoted is not None:
            tokens.append(("str", quoted))
        else:
            tokens.append(("str", bare))
    return tokens


@dataclass
class VmtNode:
    """Блок VMT: параметры и вложенные блоки, оба с сохранением порядка."""

    #: {имя в нижнем регистре: значение} — при повторе побеждает ПЕРВОЕ,
    #: как и при чтении KeyValues движком.
    params: Dict[str, str] = field(default_factory=dict)
    #: {имя в нижнем регистре: [блоки]} — блоков с одним именем может быть
    #: несколько (`replace` в разных ветках качества).
    blocks: Dict[str, List["VmtNode"]] = field(default_factory=dict)

    def add_param(self, key: str, value: str) -> None:
        # Ключ нормализуем ТАК ЖЕ, как при чтении (_key): без $ и в нижнем
        # регистре — иначе запись «$basetexture» не найдётся по «basetexture»
        self.params.setdefault(_key(key), value)

    def add_block(self, key: str, node: "VmtNode") -> None:
        self.blocks.setdefault(_key(key), []).append(node)

    # ── Чтение ───────────────────────────────────────────────────────────── #

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Параметр этого уровня. Имя можно писать с $ и в любом регистре."""
        return self.params.get(_key(name), default)

    def find(self, name: str) -> Optional[str]:
        """Параметр ГДЕ УГОДНО в дереве: свой уровень, затем вложенные блоки.

        Нужен для параметров, которые живут внутри прокси
        (`animatedtextureframerate`) или в ветке качества (`>=DX90`).
        """
        key = _key(name)
        if key in self.params:
            return self.params[key]
        for children in self.blocks.values():
            for child in children:
                found = child.find(key)
                if found is not None:
                    return found
        return None

    def block(self, name: str) -> Optional["VmtNode"]:
        found = self.blocks.get(_key(name))
        return found[0] if found else None


def _key(name: str) -> str:
    return name.strip().lstrip("$").lower()


@dataclass
class VmtDoc:
    """Разобранный VMT: имя шейдера и корневой блок."""

    shader: str = ""
    root: VmtNode = field(default_factory=VmtNode)

    # Делегаты, чтобы вызывающему не приходилось знать про root
    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.root.get(name, default)

    def find(self, name: str) -> Optional[str]:
        return self.root.find(name)

    def block(self, name: str) -> Optional[VmtNode]:
        return self.root.block(name)

    # ── Типизированный доступ ────────────────────────────────────────────── #

    def path(self, name: str) -> Optional[str]:
        """Значение-путь: прямые слэши, нижний регистр, без крайних слэшей."""
        raw = self.get(name)
        if raw is None:
            return None
        return raw.strip().replace("\\", "/").lower().strip("/")

    def number(self, name: str, default: Optional[float] = None,
               deep: bool = False) -> Optional[float]:
        raw = self.find(name) if deep else self.get(name)
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            return default

    def flag(self, name: str, default: bool = False) -> bool:
        """«1»/«0» из VMT в bool; всё непонятное — default."""
        raw = self.get(name)
        if raw is None:
            return default
        text = str(raw).strip().strip('"')
        if not text:
            return default
        try:
            return float(text) != 0.0
        except ValueError:
            return default

    def color(self, name: str) -> Optional[Tuple[int, int, int]]:
        """«{ 189 59 59 }» → (189, 59, 59); «[.74 .23 .23]» → доли единицы."""
        return parse_color(self.get(name))


_RE_TRIPLE = re.compile(r"[-+]?\d*\.?\d+")


def parse_color(value: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """Цвет VMT → (r, g, b) 0-255.

    Скобки решают масштаб: фигурные — уже 0-255, квадратные — доли единицы.
    Ориентируемся именно на скобку, а не на «есть ли значение больше 1»:
    [1 1 1] — это белый, а не почти чёрный.
    """
    if not value:
        return None
    nums = _RE_TRIPLE.findall(value)
    if len(nums) < 3:
        return None
    floats = [float(n) for n in nums[:3]]
    if "[" in value:
        floats = [f * 255.0 for f in floats]
    return tuple(max(0, min(255, int(round(f)))) for f in floats)


def parse(text: str) -> VmtDoc:
    """Разбирает текст VMT. Битый файл даёт пустой документ, а не исключение."""
    doc = VmtDoc()
    if not text:
        return doc
    tokens = _tokenize(text)
    if not tokens:
        return doc

    i = 0
    # Заголовок: имя шейдера — только если СРАЗУ за ним открывается блок.
    # Иначе перед нами обрывок VMT без обёртки («$basetexture models/x»), и
    # первый токен — обычный ключ, а не шейдер.
    if (tokens[0][0] == "str" and len(tokens) > 1
            and tokens[1] == ("brace", "{")):
        doc.shader = tokens[0][1].strip().lower()
        i = 2
    elif tokens[0] == ("brace", "{"):
        i = 1
    _fill(doc.root, tokens, i)
    return doc


def _fill(node: VmtNode, tokens: List[Tuple[str, str]], i: int) -> int:
    """Наполняет node токенами начиная с i; возвращает позицию после блока."""
    while i < len(tokens):
        kind, value = tokens[i]
        if kind == "brace":
            # Закрывающая — конец блока; лишняя открывающая — пропускаем
            i += 1
            if value == "}":
                return i
            continue
        # Ключ; дальше либо значение, либо вложенный блок
        i += 1
        if i >= len(tokens):
            break
        nxt_kind, nxt_value = tokens[i]
        if nxt_kind == "brace" and nxt_value == "{":
            child = VmtNode()
            i = _fill(child, tokens, i + 1)
            node.add_block(value, child)
        elif nxt_kind == "brace":
            i += 1          # «}» сразу после ключа — мусор, пропускаем
        else:
            node.add_param(value, nxt_value)
            i += 1
    return i


# ── Частые запросы одной строкой ─────────────────────────────────────────── #

def basetexture(text: str) -> Optional[str]:
    """$basetexture как путь относительно materials/ (или None)."""
    return parse(text).path("basetexture")


def animated_framerate(text: str) -> Optional[float]:
    """animatedtextureframerate из прокси AnimatedTexture (или None).

    Ищем по всему дереву: параметр лежит внутри `proxies { AnimatedTexture }`.
    """
    fps = parse(text).number("animatedtextureframerate", deep=True)
    return max(0.1, fps) if fps is not None else None
