/*
 * Свой файл человека → звук, который играет Source.
 *
 * Движок читает WAV с 16-битным PCM: 24-битный, float и частоты выше 44100 он
 * молча не воспроизводит — в игре на месте звука тишина. Требовать готовый
 * файл значит отправлять человека в Audacity за каждым звуком, поэтому
 * приводим здесь: mp3, ogg, flac, m4a, opus и любой WAV браузер декодирует
 * сам (WebAudio), и сторонний кодек не нужен.
 *
 * Обратной дороги нет: кодировать MP3 браузер не умеет. Записи, которые в игре
 * лежат в MP3 (почти все реплики), берут только готовый MP3 — см. sounds.js.
 */

//: Частота звуков TF2. Выше движок не берёт; меньшие (11025, 22050) он играет
//: тоже, но приводить к ним значило бы терять верх без нужды — в VPK эти
//: файлы всё равно секундные.
export const RATE = 44100;

/**
 * WAV (RIFF, 16-битный PCM, моно) из отсчётов -1…1.
 *
 * Заголовок пишем руками: сорок четыре байта, и ради них не нужна библиотека.
 */
export function encodeWav(samples, rate = RATE) {
  const bytes = samples.length * 2;
  const out = new DataView(new ArrayBuffer(44 + bytes));
  const tag = (at, text) => {
    for (let i = 0; i < text.length; i++) out.setUint8(at + i, text.charCodeAt(i));
  };
  tag(0, 'RIFF');  out.setUint32(4, 36 + bytes, true);  tag(8, 'WAVE');
  tag(12, 'fmt '); out.setUint32(16, 16, true);         // длина этого блока
  out.setUint16(20, 1, true);                           // PCM, без сжатия
  out.setUint16(22, 1, true);                           // каналов: моно
  out.setUint32(24, rate, true);
  out.setUint32(28, rate * 2, true);                    // байт в секунду
  out.setUint16(32, 2, true);                           // байт на кадр
  out.setUint16(34, 16, true);                          // бит на отсчёт
  tag(36, 'data'); out.setUint32(40, bytes, true);
  for (let i = 0; i < samples.length; i++) {
    // Обрезка обязательна: ресемплер даёт выбросы за единицу, и без неё
    // громкое место ушло бы в переполнение — щелчком вместо пика.
    const level = Math.max(-1, Math.min(1, samples[i]));
    out.setInt16(44 + i * 2, Math.round(level * 32767), true);
  }
  return out.buffer;
}

/** Любой звуковой файл → моно-WAV 44100/16. Бросает, если формат не разобрать. */
export async function toGameWav(file) {
  const raw = await file.arrayBuffer();
  // Декодируем в offline-контексте: звуковое устройство для этого не нужно, а
  // обычный AudioContext его открывает и остаётся висеть до перезагрузки.
  const clip = await new OfflineAudioContext(1, 1, RATE).decodeAudioData(raw);
  // Пересчёт частоты и сведение в один канал делает сам движок WebAudio —
  // руками это вышло бы хуже его ресемплера. Моно тут не прихоть: в точку
  // выстрела игра ставит один канал, стерео она играет «в голове», без
  // направления.
  const mix = new OfflineAudioContext(
    1, Math.max(1, Math.ceil(clip.duration * RATE)), RATE);
  const source = mix.createBufferSource();
  source.buffer = clip;
  source.connect(mix.destination);
  source.start();
  const mono = await mix.startRendering();
  const stem = file.name.replace(/\.[^.]*$/, '') || 'sound';
  return new File([encodeWav(mono.getChannelData(0))], `${stem}.wav`,
                  { type: 'audio/wav' });
}
