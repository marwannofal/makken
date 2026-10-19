(() => {
  "use strict";
  const form = document.querySelector('[data-partnership-form]');
  if (!form) return;
  const kind = form.querySelector('#id_entity_type');
  const entity = form.querySelector('#id_entity');
  const entityField = form.querySelector('#partnership-entity-field');
  if (kind && entity && entityField) {
    function syncEntity() {
      const visible = kind.value === 'non_government';
      entityField.hidden = !visible;
      entity.required = visible;
      entity.disabled = !visible;
      if (!visible) entity.setCustomValidity('');
      // Refresh the existing searchable-select component after toggling it.
      entity.dispatchEvent(new Event('change', {bubbles: true}));
    }
    kind.addEventListener('change', syncEntity);
    syncEntity();
  }

  const amount = form.querySelector('#id_financial_capacity');
  if (!amount) return;
  let ownError = '';
  let fromPaste = false;
  const normalize = text => text.replace(/[٠-٩]/g, c => String(c.charCodeAt(0) - 1632))
    .replace(/[۰-۹]/g, c => String(c.charCodeAt(0) - 1776))
    .replace(/٬/g, ',').replace(/٫/g, '.');
  const plainDigits = text => normalize(text).replace(/[^\d.]/g, '');
  const message = 'أدخل مبلغًا صحيحًا؛ مثال: 1,250.50.';
  function setError(text) {
    // Do not clear validation belonging to another component.
    if (!amount.validity.customError || amount.validationMessage === ownError) {
      amount.setCustomValidity(text);
      ownError = text;
    }
  }
  function caretPosition(text, count) {
    if (count === 0) return 0;
    for (let i = 0, seen = 0; i < text.length; i++) {
      if (/[\d.]/.test(text[i]) && ++seen === count) return i + 1;
    }
    return text.length;
  }
  function format(final = false, strictGrouping = false) {
    const raw = normalize(amount.value);
    if (!raw.trim()) {setError(''); return;}
    const value = raw.trim();
    if (strictGrouping && value.includes(',') && !/^\d{1,3}(?:,\d{3})+(?:\.\d*)?$/.test(value)) {
      setError(message); return;
    }
    const plain = value.replace(/,/g, '');
    if (!/^\d+(?:\.\d*)?$/.test(plain)) {setError(message); return;}
    let [integer, fraction] = plain.split('.');
    if (integer.replace(/^0+/, '').length > 12) {setError('الحد الأقصى 12 رقمًا قبل الفاصلة العشرية.'); return;}
    if (fraction !== undefined && fraction.length > 2) {setError('استخدم منزلتين عشريتين كحد أقصى.'); return;}
    const start = amount.selectionStart, end = amount.selectionEnd;
    const startCount = start === null ? 0 : plainDigits(raw.slice(0, start)).length;
    const endCount = end === null ? startCount : plainDigits(raw.slice(0, end)).length;
    if (final) {
      integer = integer.replace(/^0+(?=\d)/, '');
      if (!fraction || /^0+$/.test(fraction)) fraction = undefined;
      else fraction = fraction.padEnd(2, '0');
    }
    const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    const formatted = grouped + (fraction !== undefined ? '.' + fraction : '');
    amount.value = formatted;
    if (!final && start !== null && document.activeElement === amount) {
      amount.setSelectionRange(caretPosition(formatted, startCount), caretPosition(formatted, endCount));
    }
    setError('');
  }
  amount.addEventListener('paste', () => {fromPaste = true;});
  amount.addEventListener('input', event => {
    if (event.isComposing) return;
    const strict = fromPaste || event.inputType === 'insertFromPaste' || event.inputType === 'insertFromDrop';
    fromPaste = false;
    format(false, strict);
  });
  amount.addEventListener('compositionend', () => format(false));
  amount.addEventListener('blur', () => format(true, true));
  // Format saved amounts and validation redisplays without altering invalid data.
  format(true, true);
})();
