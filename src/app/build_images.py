"""
Свои картинки сборки: какая на каком материале, у какой части и стиля

Сеанс собирает их из состояния превью, а потом дважды подменяет пути:
испечёнными склейками частей (`PartsEditor.baked_path`) и картинками,
исправленными под краску игры (`_fix_tint`). Обход всех мест, где лежит
картинка, - здесь, один раз: с тремя обходами новое место легко добавить в
один и забыть в другом
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class BuildImages:
    #: Главная текстура; None - своей нет (сборка возьмёт игровую или её нет вовсе)
    image: Optional[str]
    #: {материал: картинка} доп. материалов (без материалов частей)
    extra: Dict[str, str]
    #: {материал: картинка} синей команды (без материалов частей)
    blu: Dict[str, str]
    #: Правленые гирлянды: {'kind', 'mdl', 'textures': {материал: {команда: картинка}}, ...}
    decor: List[Dict[str, Any]]
    #: Спеки материалов частей: 'image', 'image_blu', 'style_images': {строка: картинка}
    parts: List[Dict[str, Any]]
    #: Стили своей модели: 'variant_files': {имя: картинка}; None - их нет
    styles: Optional[Dict[str, Any]]
    #: Небо: 'equirect' (панорама) и 'face_overrides' (грани)
    sky: Dict[str, Any] = field(default_factory=dict)
    #: Своей главной нет, но мод собирается с игровой
    main_from_game: bool = False

    def decor_paths(self) -> List[str]:
        return [p for d in self.decor for teams in d['textures'].values()
                for p in teams.values()]

    def part_paths(self) -> List[str]:
        return [*(s[k] for s in self.parts for k in ('image', 'image_blu') if s[k]),
                *(p for s in self.parts for p in s['style_images'].values())]

    def style_paths(self) -> List[str]:
        return list((self.styles or {}).get('variant_files', {}).values())

    def own_paths(self) -> List[Optional[str]]:
        """Свои картинки оружия (без гирлянд) - их проверяет краска игры"""
        return [self.image, *self.extra.values(), *self.blu.values(),
                *self.part_paths(), *self.style_paths()]

    def remap(self, fn: Callable[[Any], Any], decor: bool = False) -> None:
        """Подменяет каждый путь на fn(путь), гирлянды - только с `decor`"""
        self.image = fn(self.image)
        self.extra = {mat: fn(p) for mat, p in self.extra.items()}
        self.blu = {mat: fn(p) for mat, p in self.blu.items()}
        if decor:
            for d in self.decor:
                d['textures'] = {mat: {team: fn(p) for team, p in teams.items()}
                                 for mat, teams in d['textures'].items()}
        for s in self.parts:
            s['image'], s['image_blu'] = fn(s['image']), fn(s['image_blu'])
            s['style_images'] = {row: fn(p) for row, p in s['style_images'].items()}
        if self.styles:
            self.styles['variant_files'] = {name: fn(p) for name, p
                                            in self.styles['variant_files'].items()}
