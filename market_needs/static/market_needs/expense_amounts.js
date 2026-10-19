/* Need-card amounts: grouped expense/support display, exact decimal strings. */
(() => {
  'use strict';
  const editor = document.querySelector('[data-need-editor]');
  const rows = editor?.querySelector('[data-expense-rows]');
  if (!rows) return;
  const selector = 'input[data-amount], #id_requested_support';
  const states = new WeakMap();
  const normalize = value => value.trim()
    .replace(/[٠-٩۰-۹]/g, digit => String(digit.charCodeAt(0) - (digit <= '٩' ? 1632 : 1776)))
    .replace(/٬/g, ',').replace(/٫/g, '.');
  const semanticLength = value => normalize(value).replace(/,/g, '').length;
  const invalidMessage = 'أدخل مبلغًا صحيحًا، بفواصل آلاف صحيحة ومنزلتين عشريتين كحد أقصى.';
  function validity(input, message) {
    const state = states.get(input) || {};
    // Leave validation messages owned by other components intact.
    if (!input.validationMessage || input.validationMessage === state.error) {
      input.setCustomValidity(message);
      state.error = message;
    }
    states.set(input, state);
  }
  function format(input, finish = false, editing = false) {
    const value = normalize(input.value);
    if (!value) {
      validity(input, '');
      input.value = '';
      states.get(input).display = '';
      return;
    }
    if (value.includes(',') && !editing && !/^\d{1,3}(?:,\d{3})+(?:\.\d{0,2})?$/.test(value)) {
      validity(input, invalidMessage);
      return;
    }
    const raw = value.replace(/,/g, '');
    if (!/^(?:\d+(?:\.\d{0,2})?|\.\d{0,2})$/.test(raw) || raw === '.') {
      validity(input, invalidMessage);
      return;
    }
    validity(input, '');
    const position = input.selectionStart;
    const offset = position === null ? null : semanticLength(input.value.slice(0, position));
    let [whole, fraction] = raw.split('.');
    whole = (whole || '0').replace(/^0+(?=\d)/, '');
    if (finish && (fraction === '' || fraction === '00')) fraction = undefined;
    const display = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction === undefined ? '' : '.' + fraction);
    input.value = display;
    states.get(input).display = display;
    if (offset !== null && document.activeElement === input) {
      let caret = 0, seen = 0;
      while (caret < display.length && seen < offset) {
        if (display[caret] !== ',') seen++;
        caret++;
      }
      input.setSelectionRange(caret, caret);
    }
  }
  editor.addEventListener('beforeinput', event => {
    if (!event.target.matches(selector)) return;
    const input = event.target;
    const state = states.get(input) || {};
    const replacement = /paste|drop|replacement/i.test(event.inputType || '');
    state.editing = !replacement && input.value === state.display && !/[٬,]/.test(event.data || '');
    states.set(input, state);
  }, true);
  editor.addEventListener('input', event => {
    if (!event.target.matches(selector) || event.isComposing) return;
    const state = states.get(event.target);
    format(event.target, false, Boolean(state?.editing));
    if (state) state.editing = false;
    // Capture runs before market.js calculates totals and serializes amounts.
  }, true);
  editor.addEventListener('compositionend', event => {
    if (!event.target.matches(selector)) return;
    format(event.target);
    event.target.dispatchEvent(new Event('input', {bubbles: true}));
  });
  editor.addEventListener('focusout', event => {
    if (!event.target.matches(selector)) return;
    format(event.target, true);
    event.target.dispatchEvent(new Event('input', {bubbles: true}));
  });
  const prepare = root => {
    if (!(root instanceof Element)) return;
    if (root.matches(selector)) format(root, true);
    root.querySelectorAll(selector).forEach(input => format(input, true));
  };
  prepare(editor);
  // Program changes recreate expense rows. Observe only direct additions.
  new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(prepare)))
    .observe(rows, {childList: true});
  window.addEventListener('pageshow', () => prepare(editor));
})();
