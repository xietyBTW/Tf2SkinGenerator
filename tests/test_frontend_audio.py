"""
Заголовок WAV, который страница отдаёт игре.

Сам разбор чужих форматов делает браузер (WebAudio), и проверить его здесь
нечем. А вот сорок четыре байта заголовка написаны руками, и ошибка в них
даёт ровно то, ради чего конвертер и заводился: файл, который выглядит
исправным, а в игре молчит. Их и проверяем — вместе с обрезкой выбросов,
без которой громкое место уходит в переполнение щелчком.

Тест пропускается, если node не установлен: это проверка разработчика.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path("frontend")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="нет node")

CHECK = """
import assert from 'node:assert';
import { encodeWav, RATE } from './mockup/audio.js';

const wav = new DataView(encodeWav(Float32Array.from([0, 1, -1, 2]), RATE));
const tag = (at) => String.fromCharCode(
  ...[0, 1, 2, 3].map((i) => wav.getUint8(at + i)));

assert.equal(tag(0), 'RIFF');
assert.equal(tag(8), 'WAVE');
assert.equal(tag(12), 'fmt ');
assert.equal(tag(36), 'data');
assert.equal(wav.getUint32(4, true), wav.byteLength - 8, 'размер RIFF');
assert.equal(wav.getUint16(20, true), 1, 'PCM без сжатия');
assert.equal(wav.getUint16(22, true), 1, 'моно');
assert.equal(wav.getUint32(24, true), 44100, 'частота');
assert.equal(wav.getUint32(28, true), 44100 * 2, 'байт в секунду');
assert.equal(wav.getUint16(32, true), 2, 'байт на кадр');
assert.equal(wav.getUint16(34, true), 16, '16 бит');
assert.equal(wav.getUint32(40, true), 8, 'длина данных');
assert.equal(wav.byteLength, 44 + 8);

assert.equal(wav.getInt16(46, true), 32767, 'единица — максимум');
assert.equal(wav.getInt16(48, true), -32767, 'минус единица — минимум');
assert.equal(wav.getInt16(50, true), 32767, 'выброс обрезан, а не переполнен');
console.log('ok');
"""


def test_wav_header_is_what_source_reads() -> None:
    done = subprocess.run(["node", "--input-type=module", "-e", CHECK],
                          cwd=str(FRONTEND), capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, (done.stdout or '') + (done.stderr or '')
