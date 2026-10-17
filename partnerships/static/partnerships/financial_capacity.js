(() => {
  "use strict";
  const range = document.querySelector('[data-financial-range]');
  if (!range) return;
  const lower = range.querySelector('#capacity-min');
  const upper = range.querySelector('#capacity-max');
  if (!lower || !upper) return;
  const parse = input => {
    const value = input.value.trim();
    if (!value) return null;
    return Number(value.replace(/[٠-٩]/g, c => String(c.charCodeAt(0) - 1632))
      .replace(/[۰-۹]/g, c => String(c.charCodeAt(0) - 1776))
      .replace(/[٬,]/g, '').replace(/٫/g, '.'));
  };
  function validate() {
    const low = parse(lower), high = parse(upper);
    upper.setCustomValidity(Number.isFinite(low) && Number.isFinite(high) && low > high
      ? 'الحد الأعلى يجب ألا يقل عن الحد الأدنى.' : '');
  }
  lower.addEventListener('input', validate);
  upper.addEventListener('input', validate);
  validate();
})();
