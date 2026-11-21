(() => {
  'use strict';
  if (window.MakkenDateFormat) return;

  const CALENDAR_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>';
  const INVALID_MSG = 'أدخل التاريخ بصيغة DD/MM/YYYY مثل 25/11/2026.';

  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  function isoToDmy(iso) {
    if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '';
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  }

  function dmyToIso(dmy) {
    const clean = (dmy || '').trim();
    if (!clean) return '';
    const match = clean.match(/^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$/);
    if (!match) return null;
    const day = parseInt(match[1], 10);
    const month = parseInt(match[2], 10);
    const year = parseInt(match[3], 10);
    if (year < 1900 || year > 2100 || month < 1 || month > 12 || day < 1 || day > 31) return null;
    const probe = new Date(Date.UTC(year, month - 1, day));
    if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) {
      return null;
    }
    return `${year}-${pad2(month)}-${pad2(day)}`;
  }

  function formatTyping(raw) {
    const digits = raw.replace(/\D/g, '').slice(0, 8);
    if (digits.length <= 2) return digits;
    if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
    return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
  }

  function enhanceInput(nativeInput) {
    if (!nativeInput || nativeInput.dataset.mkDateEnhanced === '1') return;
    if (nativeInput.closest('template')) return;
    nativeInput.dataset.mkDateEnhanced = '1';

    const wrapper = document.createElement('div');
    wrapper.className = 'mk-date-field';
    nativeInput.before(wrapper);

    const display = document.createElement('input');
    display.type = 'text';
    display.className = 'mk-date-display';
    display.dir = 'ltr';
    display.inputMode = 'numeric';
    display.maxLength = 10;
    display.autocomplete = 'off';
    display.placeholder = 'DD/MM/YYYY';
    display.dataset.mkDateDisplay = '1';
    if (nativeInput.required) display.required = true;
    if (nativeInput.disabled) display.disabled = true;
    if (nativeInput.readOnly) display.readOnly = true;

    // Transfer label association to the visible display input while keeping native input's id intact if referenced by JS
    const label = nativeInput.id ? document.querySelector(`label[for="${CSS.escape(nativeInput.id)}"]`) : null;
    if (label) {
      display.setAttribute('aria-label', label.textContent.replace(/\*/g, '').trim());
      label.addEventListener('click', event => {
        event.preventDefault();
        display.focus();
      });
    } else if (nativeInput.getAttribute('aria-label')) {
      display.setAttribute('aria-label', nativeInput.getAttribute('aria-label'));
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'mk-date-picker-btn';
    button.setAttribute('aria-label', 'اختيار التاريخ من التقويم');
    button.innerHTML = CALENDAR_SVG;
    if (nativeInput.disabled || nativeInput.readOnly) button.disabled = true;

    nativeInput.classList.add('mk-date-native');
    nativeInput.tabIndex = -1;
    nativeInput.setAttribute('aria-hidden', 'true');

    wrapper.append(display, button, nativeInput);

    // Initialize from existing ISO value
    if (nativeInput.value) {
      display.value = isoToDmy(nativeInput.value);
    }

    function syncFromDisplay(strict) {
      const val = display.value.trim();
      if (!val) {
        nativeInput.value = '';
        display.setCustomValidity('');
        nativeInput.dispatchEvent(new Event('input', {bubbles: true}));
        nativeInput.dispatchEvent(new Event('change', {bubbles: true}));
        return;
      }
      const iso = dmyToIso(val);
      if (iso) {
        nativeInput.value = iso;
        display.setCustomValidity('');
        if (strict) display.value = isoToDmy(iso);
        nativeInput.dispatchEvent(new Event('input', {bubbles: true}));
        nativeInput.dispatchEvent(new Event('change', {bubbles: true}));
      } else if (strict || val.length === 10) {
        nativeInput.value = '';
        display.setCustomValidity(INVALID_MSG);
      } else {
        display.setCustomValidity('');
      }
    }

    display.addEventListener('input', event => {
      const prev = display.value;
      if (event.inputType !== 'deleteContentBackward' && event.inputType !== 'deleteContentForward') {
        const formatted = formatTyping(prev);
        if (formatted !== prev) {
          display.value = formatted;
        }
      }
      syncFromDisplay(false);
    });

    display.addEventListener('blur', () => syncFromDisplay(true));

    nativeInput.addEventListener('change', () => {
      const formatted = isoToDmy(nativeInput.value);
      if (display.value !== formatted) {
        display.value = formatted;
        display.setCustomValidity('');
      }
    });

    button.addEventListener('click', () => {
      if (nativeInput.disabled || nativeInput.readOnly) return;
      if (typeof nativeInput.showPicker === 'function') {
        try {
          nativeInput.showPicker();
          return;
        } catch (_) {
          // Fallback below
        }
      }
      nativeInput.focus();
      nativeInput.click();
    });

    const form = nativeInput.form;
    if (form && !form.dataset.mkDateFormBound) {
      form.dataset.mkDateFormBound = '1';
      form.addEventListener('submit', () => {
        form.querySelectorAll('input[data-mk-date-display]').forEach(el => {
          el.dispatchEvent(new Event('blur'));
        });
      });
    }
  }

  function enhanceAll(root = document) {
    root.querySelectorAll('input[type="date"]').forEach(enhanceInput);
  }

  window.MakkenDateFormat = {enhanceAll, isoToDmy, dmyToIso};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => enhanceAll(document));
  } else {
    enhanceAll(document);
  }

  let queued = false;
  new MutationObserver(records => {
    if (queued) return;
    const hasDate = records.some(r => [...r.addedNodes].some(
      n => n.nodeType === 1 && (n.matches('input[type="date"]') || n.querySelector('input[type="date"]'))
    ));
    if (!hasDate) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      enhanceAll(document);
    });
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
