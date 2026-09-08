"""
Сборка мода звуков: свои файлы под игровыми путями.

Тут всё проще, чем у текстур: конвертировать нечего, VMT писать не надо.
Игра зовёт звук по имени записи, запись называет файл, и достаточно положить
свой файл ПО ТОМУ ЖЕ пути внутри `sound/` — движок возьмёт его вместо
исходного.

Единственная строгость — формат. Source играет WAV с 16-битным PCM; 24-битный,
float или ADPCM он молча не воспроизведёт, и в игре на месте звука будет
тишина. Поэтому файл проверяется здесь, а не выясняется на карте.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Dict

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Что Source точно проигрывает. MP3 он тоже умеет, но только там, где файл в
#: игре сам был MP3: имя в записи звука указывает на конкретное расширение.
PCM_WIDTH = 2
GOOD_RATES = (11025, 22050, 44100)


def check_wav(path: str) -> str:
    """Пусто, если файл годится. Иначе — что с ним не так, по-русски."""
    if not os.path.isfile(path):
        return 'файла нет'
    if path.lower().endswith('.mp3'):
        # Расширению верить нельзя: конвертеры охотно сохраняют WAV под именем
        # `.mp3`, а движок выбирает читалку именно по имени — в игре будет
        # тишина. Смотрим начало файла: тег ID3 или синхрослово кадра.
        head = _head(path)
        if head[:3] == b'ID3' or (head[:1] == b'\xff' and head[1:2] >= b'\xe0'):
            return ''
        return 'внутри не MP3, а другой формат — игра его не прочитает'
    try:
        with wave.open(path, 'rb') as snd:
            if snd.getsampwidth() != PCM_WIDTH:
                return (f'{snd.getsampwidth() * 8}-битный звук — '
                        f'игра играет только 16-битный')
            if snd.getframerate() not in GOOD_RATES:
                return (f'частота {snd.getframerate()} Гц — '
                        f'игре нужна одна из {GOOD_RATES}')
    except wave.Error as exc:
        return f'не WAV с обычным PCM: {exc}'
    except OSError as exc:
        return f'не прочитать: {exc}'
    return ''


def _head(path: str, size: int = 4) -> bytes:
    """Первые байты файла. Пусто, если не прочитать."""
    try:
        with open(path, 'rb') as f:
            return f.read(size)
    except OSError:
        return b''


def build(replacements: Dict[str, str], filename: str,
          export_folder: str = 'export', language: str = 'en') -> str:
    """
    VPK со звуками. `replacements` — {путь файла в игре: файл человека}.

    Путь в игре идёт от корня `sound/` — ровно так, как его называет запись
    звукового скрипта.

    Returns:
        Путь к собранному VPK.

    Raises:
        ValueError: заменять нечего.
    """
    from src.services.packaging_service import PackagingService

    if not replacements:
        raise ValueError('Не выбрано ни одного своего звука')

    root = tempfile.mkdtemp(prefix='tf2sg_sound_')
    try:
        # Имя папки становится именем VPK у vpk.exe — кладём содержимое в
        # подпапку с осмысленным именем, а не в случайную временную.
        vpkroot = os.path.join(root, os.path.splitext(filename)[0] or 'sounds')
        for wave_path, own in replacements.items():
            # Строчными: у Valve все звуковые архивы такие, и движок ищет файл
            # так же. Своя раскладка регистра работала бы не везде.
            target = os.path.join(vpkroot, 'sound',
                                  *wave_path.lower().split('/'))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(own, target)
        logger.info(f"[звук] в мод кладём файлов: {len(replacements)}")
        return PackagingService.pack_directory(
            vpkroot_dir=Path(vpkroot),
            filename=filename, export_folder=export_folder, language=language)
    finally:
        shutil.rmtree(root, ignore_errors=True)
