(() => {
  "use strict";
  const normalizeDigits = raw => String(raw || '').trim()
    .replace(/[٠-٩]/g, c => String(c.charCodeAt(0) - 1632))
    .replace(/[۰-۹]/g, c => String(c.charCodeAt(0) - 1776))
    .replace(/[٬,]/g, '')
    .replace(/٫/g, '.');

  const formatMoneyInput = input => {
    if (!input || input.type === 'number') return;
    const cleaned = normalizeDigits(input.value);
    if (!cleaned) return;
    if (!/^-?\d+(?:\.\d+)?$/.test(cleaned)) return;
    const parts = cleaned.split('.');
    const intPart = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    input.value = parts.length > 1 ? `${intPart}.${parts[1].slice(0, 2)}` : intPart;
  };

  const moneyInputs = document.querySelectorAll('#id_financial_capacity, #capacity-min, #capacity-max, [data-money-format]');
  moneyInputs.forEach(input => {
    formatMoneyInput(input);
    input.addEventListener('blur', () => formatMoneyInput(input));
  });

  const range = document.querySelector('[data-financial-range]');
  if (!range) return;
  const lower = range.querySelector('#capacity-min');
  const upper = range.querySelector('#capacity-max');
  if (!lower || !upper) return;
  const parse = input => {
    const value = normalizeDigits(input.value);
    if (!value) return null;
    return Number(value);
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
