/*
 * Узор конструктора блеска: слои и настройки прохода, правки слоёв и
 * история (Ctrl+Z / Ctrl+Y). Без DOM - окно (sheen-builder.js) зовёт методы
 * и само решает, что перерисовать.
 */

import { clone } from './sheen-ui.js';

const HISTORY_MAX = 80;
//: Пауза после правки, прежде чем она встанет в историю: протяжка ползунка -
//: один шаг отмены, а не сотня
const COMMIT_DELAY = 350;

export class SheenPattern {
  /**
   * `schema` - ответ sheenBuilderSchema, `fields` - id, name, layers, length,
   * streak, quality. selected - выбранный слой, solo - слой «только
   * этот в превью» (-1 - все), mask - превью показывает саму маску.
   */
  constructor(schema, fields) {
    this.types = Object.fromEntries(schema.types.map((x) => [x.id, x]));
    this.maxLayers = schema.max_layers;
    Object.assign(this, { selected: 0, solo: -1, mask: false }, fields);
    this.onHistory = () => {};
    this._history = [JSON.stringify(this.layers)];
    this._at = 0;
    this._timer = null;
  }

  get full() { return this.layers.length >= this.maxLayers; }
  get canUndo() { return this._at > 0; }
  get canRedo() { return this._at < this._history.length - 1; }

  /** Имя слоя в списке: у второго такого же - номер */
  layerName(i) {
    const layer = this.layers[i];
    const same = this.layers.slice(0, i + 1).filter((x) => x.type === layer.type).length;
    const label = this.types[layer.type].label;
    return same > 1 ? `${label} ${same}` : label;
  }

  // История
  /** Правку - в историю сразу */
  flush() {
    clearTimeout(this._timer);
    const snap = JSON.stringify(this.layers);
    if (snap === this._history[this._at]) return;
    this._history.splice(this._at + 1);
    this._history.push(snap);
    if (this._history.length > HISTORY_MAX) this._history.shift();
    this._at = this._history.length - 1;
    this.onHistory();
  }

  /** Правку - в историю, когда правки затихнут */
  commit() {
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this.flush(), COMMIT_DELAY);
  }

  /** Шаг по истории (-1 - отменить, 1 - вернуть). Отдаёт, сдвинулся ли узор */
  travel(d) {
    // Правка, что ещё ждёт записи, сначала встаёт в историю: иначе
    // Ctrl+Z сразу после неё терял бы её без возврата
    this.flush();
    const j = this._at + d;
    if (j < 0 || j >= this._history.length) return false;
    this._at = j;
    this.layers = JSON.parse(this._history[this._at]);
    this.selected = Math.min(this.selected, this.layers.length - 1);
    this.solo = -1;
    return true;
  }

  dispose() { clearTimeout(this._timer); }

  // Правки слоёв
  /** Новый слой в конец списка, выбранным */
  add(layer) {
    this.layers.push(layer);
    this.selected = this.layers.length - 1;
  }

  duplicate(i) {
    this.layers.splice(i + 1, 0, clone(this.layers[i]));
    this.selected = i + 1;
    if (this.solo > i) this.solo += 1;
  }

  remove(i) {
    this.layers.splice(i, 1);
    if (this.selected > i) this.selected -= 1;
    this.selected = Math.min(this.selected, this.layers.length - 1);
    if (this.solo === i) this.solo = -1;
    else if (this.solo > i) this.solo -= 1;
  }

  move(from, to) {
    const [moved] = this.layers.splice(from, 1);
    this.layers.splice(to, 0, moved);
    this.selected = to;
    this.solo = -1;
  }

  usePreset(layers) {
    this.layers = clone(layers);
    this.selected = 0;
    this.solo = -1;
  }

  toggleSolo(i) {
    this.solo = this.solo === i ? -1 : i;
  }

  /** Слои для превью: «только этот слой» в узор не уходит */
  previewLayers() {
    // Маску в одиночку показываем как обычный слой: под ней всё равно
    // ничего нет
    return this.solo >= 0
      ? this.layers.map((l, i) => ({ ...l, on: i === this.solo, blend: 'max' }))
      : this.layers;
  }

  /** Узор, как его сохраняет и считает Python */
  spec() {
    return { layers: this.layers, quality: this.quality };
  }
}
