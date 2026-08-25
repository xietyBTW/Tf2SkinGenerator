/**
 * Материал меша из свойств VMT.
 *
 * Раньше конструктор материала был скопирован по вьюверу шесть раз, всегда
 * непрозрачный и всегда двусторонний. Из-за этого стекло банки Мутировавшего
 * молока ($additive в VMT, базовая текстура — пузырьковый шлем пиро) выглядело
 * серым пластиковым бубликом.
 *
 * Свойства приходят из Python (src/services/vmt_render.py) и привязаны к
 * МАТЕРИАЛУ, а не к картинке: пользователь может бросить свою текстуру на
 * стекло, и оно обязано остаться стеклом.
 *
 * Блика и отражений здесь намеренно нет: в Source они ограничены маской из
 * текстуры, а без неё покрывают модель ровной белёсой плёнкой (см. док-строку
 * vmt_render.py).
 *
 * THREE передаётся аргументом, а не импортируется: так модуль проверяется
 * тестом в Node с заглушкой вместо WebGL.
 */

/**
 * Параметры материала по подсказке из VMT — чистая функция, без THREE.
 *
 * @param {object|null} hint  {blend, opacity, alphaTest, twoSided}
 * @returns {object} нормализованные поля для материала.
 */
export function materialParams(hint) {
  const p = { doubleSide: true };
  if (!hint) return p;

  switch (hint.blend) {
    case 'add':
      p.transparent = true;
      p.additive    = true;
      p.depthWrite  = false;
      break;
    case 'alpha':
      p.transparent = true;
      p.opacity     = (hint.opacity === undefined) ? 1 : hint.opacity;
      p.depthWrite  = false;
      break;
    case 'cutout':
      p.alphaTest = hint.alphaTest || 0.5;
      break;
  }
  // Двусторонними оставляем непрозрачные: у декомпилированных моделей
  // попадаются вывернутые нормали, и односторонний материал дал бы дыры.
  // Прозрачным изнанка вредна — грань смешивается сама с собой дважды.
  if (p.transparent && !hint.twoSided) p.doubleSide = false;
  return p;
}

/** Ищет подсказку для материала (имена из QC приходят в любом регистре). */
export function hintFor(hints, name) {
  if (!hints || !name) return null;
  return hints[name] || hints[String(name).toLowerCase()] || null;
}

/**
 * Создаёт готовый материал меша.
 *
 * @param {object} THREE
 * @param {object} opts  {map, color, name}
 * @param {object} hints {имя материала: подсказка}
 */
export function makeMeshMaterial(THREE, opts, hints) {
  const name = (opts && opts.name) || '';
  const p    = materialParams(hintFor(hints, name));

  const params = { side: p.doubleSide ? THREE.DoubleSide : THREE.FrontSide };
  if (opts && opts.map) params.map = opts.map;
  else params.color = (opts && opts.color !== undefined) ? opts.color : 0x888888;

  if (p.transparent) params.transparent = true;
  if (p.additive)    params.blending    = THREE.AdditiveBlending;
  if (p.depthWrite === false) params.depthWrite = false;
  if (p.opacity !== undefined) params.opacity = p.opacity;
  if (p.alphaTest) params.alphaTest = p.alphaTest;

  const mat = new THREE.MeshLambertMaterial(params);
  if (name) mat.name = name;
  return mat;
}
