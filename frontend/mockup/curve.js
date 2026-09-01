/*
 * Кривая ползунка — порт services/simple_params.curve_fraction/curve_value.
 *
 * Считается здесь, а не в Python: при перетаскивании дорожки это десятки
 * запросов в секунду. Отдельным модулем — чтобы формулы можно было сверить
 * с оригиналом в тесте (tests/test_particle_curve_js.py гоняет обе стороны
 * на одних значениях). Менять только парой с тем модулем.
 */

const CURVE = {
  linear: { to: (t) => t, from: (f) => f },
  // Мелкие значения занимают половину дорожки: половина стоковых гравитаций
  // лежит в ±50 при размахе ±800 — на линейной дорожке это 6% хода.
  sqrt: { to: (t) => Math.sqrt(t), from: (f) => f * f },
  // То же, но симметрично относительно середины — для знаковых величин.
  signed_sqrt: {
    to: (t) => ((Math.sign(t * 2 - 1) * Math.sqrt(Math.abs(t * 2 - 1))) + 1) / 2,
    from: (f) => ((f * 2 - 1) * Math.abs(f * 2 - 1) + 1) / 2,
  },
};

/** Значение → доля хода ползунка [0..1]. */
export function curveFraction(param, value) {
  const span = param.max - param.min;
  if (span <= 0) return 0;
  const t = Math.min(1, Math.max(0, (value - param.min) / span));
  return (CURVE[param.curve] || CURVE.linear).to(t);
}

/** Доля хода ползунка [0..1] → значение параметра. */
export function curveValue(param, fraction) {
  const f = Math.min(1, Math.max(0, fraction));
  const t = (CURVE[param.curve] || CURVE.linear).from(f);
  return param.min + (param.max - param.min) * t;
}
