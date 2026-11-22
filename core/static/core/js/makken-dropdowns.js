/* Makken Global Searchable Dropdowns — single & multi-select, Arabic-normalized multi-word search, CSP-safe. */
(() => {
  'use strict';

  const enhanced = new WeakMap();
  let openCtrl = null;

  function normalizeText(value) {
    return String(value || '')
      .normalize('NFKC')
      .toLocaleLowerCase()
      .replace(/[\u064b-\u065f\u0670\u0640]/g, '')
      .replace(/[أإآٱ]/g, 'ا')
      .replace(/ة/g, 'ه')
      .replace(/ى/g, 'ي')
      .replace(/[٠-٩]/g, (c) => String(c.charCodeAt(0) - 1632))
      .replace(/[۰-۹]/g, (c) => String(c.charCodeAt(0) - 1776))
      .replace(/\s+/g, ' ')
      .trim();
  }

  function matchesQuery(text, value, query) {
    const tokens = normalizeText(query).split(' ').filter(Boolean);
    if (!tokens.length) return true;
    const hay = `${normalizeText(text)} ${normalizeText(value)}`;
    return tokens.every((tok) => hay.includes(tok));
  }

  function hasCustomPicker(select) {
    if (!select) return false;
    if (select.classList.contains('native-enhanced')) return true;
    if (select.dataset.providerPicker) return true;
    if (select.hasAttribute('data-market-select')) return true;
    if (select.closest('.search-select, .market-select, .multi-select, .multi-field')) return true;
    const next = select.nextElementSibling;
    if (next && (next.classList.contains('search-select') || next.classList.contains('multi-select') || next.hasAttribute('data-multi-select'))) return true;
    if (select.parentElement && select.parentElement.querySelector(':scope > .search-select, :scope > .multi-select, :scope > [data-multi-select]')) return true;
    return false;
  }

  function unwrapSelect(select) {
    if (!select) return;
    const ctrl = enhanced.get(select);
    if (ctrl) {
      ctrl.destroy();
      enhanced.delete(select);
    }
    select.classList.remove('mk-ss-native');
  }

  function shouldEnhance(select) {
    if (!select || select.tagName !== 'SELECT') return false;
    if (enhanced.has(select)) return false;
    if (hasCustomPicker(select)) return false;
    if (select.hasAttribute('data-no-search-select')) return false;
    if (select.closest('.mk-ss-wrap, #mk-a11y-drawer')) return false;
    if (select.hidden || select.style.display === 'none') return false;
    return true;
  }

  function make(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function enhanceSelect(select) {
    if (!shouldEnhance(select)) return;

    const wrap = make('div', 'mk-ss-wrap' + (select.multiple ? ' is-multi' : ''));
    const trigger = make('button', 'mk-ss-trigger');
    trigger.type = 'button';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');

    const labelSpan = make('span', 'mk-ss-label');
    const chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chevron.setAttribute('viewBox', '0 0 24 24');
    chevron.setAttribute('aria-hidden', 'true');
    chevron.classList.add('mk-ss-arrow');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'm6 9 6 6 6-6');
    chevron.appendChild(path);
    trigger.append(labelSpan, chevron);

    const panel = make('div', 'mk-ss-panel');
    panel.hidden = true;

    const searchWrap = make('div', 'mk-ss-search-wrap');
    const searchInput = make('input', 'mk-ss-search');
    searchInput.type = 'search';
    searchInput.placeholder = 'ابحث داخل القائمة...';
    searchInput.autocomplete = 'off';
    searchInput.setAttribute('aria-label', 'ابحث داخل القائمة');
    searchWrap.appendChild(searchInput);

    const list = make('div', 'mk-ss-list');
    list.setAttribute('role', 'listbox');
    if (select.multiple) list.setAttribute('aria-multiselectable', 'true');

    const emptyMsg = make('div', 'mk-ss-empty', 'لا توجد نتائج مطابقة');
    emptyMsg.hidden = true;

    panel.append(searchWrap, list, emptyMsg);

    if (select.multiple) {
      const footer = make('div', 'mk-ss-footer');
      const doneBtn = make('button', 'mk-ss-done', 'تم');
      doneBtn.type = 'button';
      const clearBtn = make('button', 'mk-ss-clear', 'مسح التحديد');
      clearBtn.type = 'button';
      doneBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        close();
        trigger.focus();
      });
      clearBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        Array.from(select.options).forEach((o) => { o.selected = false; });
        select.dispatchEvent(new Event('change', { bubbles: true }));
        select.dispatchEvent(new Event('input', { bubbles: true }));
        renderOptions();
        updateTrigger();
      });
      footer.append(doneBtn, clearBtn);
      panel.appendChild(footer);
    }

    select.classList.add('mk-ss-native');
    select.setAttribute('tabindex', '-1');
    select.setAttribute('aria-hidden', 'true');
    select.after(wrap);
    wrap.append(trigger, panel);

    let activeIndex = -1;

    function updateTrigger() {
      trigger.disabled = select.disabled;
      wrap.classList.toggle('is-disabled', select.disabled);
      const selected = Array.from(select.selectedOptions);
      if (select.multiple) {
        const nonEmpty = selected.filter((o) => o.value !== '');
        if (!nonEmpty.length) {
          labelSpan.textContent = select.dataset.placeholder || 'اختر من القائمة';
          labelSpan.classList.add('is-placeholder');
        } else if (nonEmpty.length <= 2) {
          labelSpan.textContent = nonEmpty.map((o) => o.textContent.trim()).join('، ');
          labelSpan.classList.remove('is-placeholder');
        } else {
          labelSpan.textContent = `${nonEmpty.length} اختيارات محددة`;
          labelSpan.classList.remove('is-placeholder');
        }
      } else {
        const cur = selected[0] || select.options[0];
        if (!cur || cur.value === '') {
          labelSpan.textContent = cur ? cur.textContent.trim() : 'اختر من القائمة';
          labelSpan.classList.add('is-placeholder');
        } else {
          labelSpan.textContent = cur.textContent.trim();
          labelSpan.classList.remove('is-placeholder');
        }
      }
    }

    function renderOptions() {
      const query = searchInput.value;
      list.replaceChildren();
      activeIndex = -1;
      let visibleCount = 0;

      Array.from(select.options).forEach((opt) => {
        if (opt.hidden) return;
        if (select.multiple && opt.value === '') return;
        const text = (opt.textContent || '').trim();
        if (!matchesQuery(text, opt.value, query)) return;

        visibleCount += 1;
        const btn = make('button', 'mk-ss-opt');
        btn.type = 'button';
        btn.setAttribute('role', 'option');
        btn.setAttribute('aria-selected', opt.selected ? 'true' : 'false');
        btn.disabled = opt.disabled;
        if (opt.selected) btn.classList.add('is-selected');
        if (opt.value === '') btn.classList.add('is-empty-opt');

        if (select.multiple) {
          const box = make('span', 'mk-ss-check', opt.selected ? '✓' : '');
          box.setAttribute('aria-hidden', 'true');
          const txt = make('span', 'mk-ss-opt-text', text);
          btn.append(box, txt);
        } else {
          btn.textContent = text;
        }

        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (opt.disabled) return;
          if (select.multiple) {
            opt.selected = !opt.selected;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            select.dispatchEvent(new Event('input', { bubbles: true }));
            renderOptions();
            updateTrigger();
            searchInput.focus();
          } else {
            select.value = opt.value;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            select.dispatchEvent(new Event('input', { bubbles: true }));
            updateTrigger();
            close();
            trigger.focus();
          }
        });

        list.appendChild(btn);
      });

      emptyMsg.hidden = visibleCount > 0;
    }

    function open() {
      if (select.disabled) return;
      if (openCtrl && openCtrl !== ctrl) openCtrl.close();
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      wrap.classList.add('is-open');

      const rect = trigger.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      wrap.classList.toggle('is-dropup', spaceBelow < 280 && rect.top > 280);

      searchInput.value = '';
      renderOptions();
      openCtrl = ctrl;
      requestAnimationFrame(() => searchInput.focus());
    }

    function close() {
      panel.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      wrap.classList.remove('is-open', 'is-dropup');
      if (openCtrl === ctrl) openCtrl = null;
    }

    trigger.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (panel.hidden) open();
      else close();
    });

    searchInput.addEventListener('input', () => {
      renderOptions();
    });

    searchInput.addEventListener('keydown', (e) => {
      const opts = Array.from(list.querySelectorAll('.mk-ss-opt:not(:disabled)'));
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
        trigger.focus();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (!opts.length) return;
        activeIndex = (activeIndex + 1) % opts.length;
        opts.forEach((o, i) => o.classList.toggle('is-focus', i === activeIndex));
        opts[activeIndex].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (!opts.length) return;
        activeIndex = activeIndex <= 0 ? opts.length - 1 : activeIndex - 1;
        opts.forEach((o, i) => o.classList.toggle('is-focus', i === activeIndex));
        opts[activeIndex].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const target = activeIndex >= 0 ? opts[activeIndex] : opts[0];
        if (target) target.click();
      }
    });

    select.addEventListener('change', () => {
      updateTrigger();
      if (!panel.hidden) renderOptions();
    });

    const mo = new MutationObserver(() => {
      if (hasCustomPicker(select)) {
        unwrapSelect(select);
        return;
      }
      updateTrigger();
      if (!panel.hidden) renderOptions();
    });
    mo.observe(select, { childList: true, attributes: true, subtree: true, attributeFilter: ['disabled', 'selected', 'hidden', 'class', 'data-provider-picker'] });

    const formEl = select.form;
    if (formEl) {
      formEl.addEventListener('reset', () => {
        setTimeout(() => {
          updateTrigger();
          if (!panel.hidden) renderOptions();
        }, 0);
      });
    }

    function destroy() {
      mo.disconnect();
      if (openCtrl === ctrl) openCtrl = null;
      wrap.remove();
    }

    const ctrl = { open, close, updateTrigger, renderOptions, destroy };
    enhanced.set(select, ctrl);
    updateTrigger();
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('select').forEach((sel) => {
      if (hasCustomPicker(sel)) {
        unwrapSelect(sel);
      } else {
        enhanceSelect(sel);
      }
    });
  }

  window.MakkenDropdowns = { unwrap: unwrapSelect, scan };

  document.addEventListener('click', (e) => {
    if (openCtrl && e.target.isConnected && !e.target.closest('.mk-ss-wrap')) {
      openCtrl.close();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && openCtrl) {
      openCtrl.close();
    }
  });

  function init() {
    scan(document);
    const bodyObserver = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.classList && (node.classList.contains('search-select') || node.classList.contains('multi-select') || node.hasAttribute('data-multi-select'))) {
            const parentSelect = node.parentElement && node.parentElement.querySelector(':scope > select');
            if (parentSelect) unwrapSelect(parentSelect);
            continue;
          }
          if (node.tagName === 'SELECT') enhanceSelect(node);
          else if (node.querySelectorAll) scan(node);
        }
      }
    });
    bodyObserver.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
