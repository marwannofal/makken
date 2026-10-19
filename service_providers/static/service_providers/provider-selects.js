/* Service-provider region/specialty pickers. Native selects remain authoritative. */
(() => {
  'use strict';
  const LIMIT = 80;
  const normalize = value => String(value).normalize('NFKC').toLocaleLowerCase().replace(/[\u064b-\u065f\u0670]/g, '');
  const create = (tag, className, text) => {
    const node = document.createElement(tag);
    node.className = className || '';
    if (text !== undefined) node.textContent = text;
    return node;
  };
  ['provider-region', 'provider-specializations'].forEach(id => {
    const select = document.getElementById(id);
    if (!select || select.dataset.providerPicker) return;
    // Claim only these two controls before the shared market enhancer runs.
    select.removeAttribute('data-market-select');
    select.dataset.providerPicker = '1';
    const label = select.labels[0];
    const labelText = label?.textContent.trim() || 'الاختيارات';
    const wrapper = create('div', 'search-select market-select');
    const trigger = create('button', 'search-select-trigger market-select-trigger');
    const summary = create('span');
    const panel = create('div', 'search-select-panel');
    const search = create('input');
    const options = create('div', 'search-select-options');
    const tags = create('div', 'selected-summary');
    const error = create('p', 'field-error');
    trigger.type = 'button';
    trigger.setAttribute('aria-label', labelText);
    trigger.setAttribute('aria-haspopup', 'true');
    trigger.setAttribute('aria-expanded', 'false');
    panel.id = id + '-provider-options';
    trigger.setAttribute('aria-controls', panel.id);
    panel.hidden = true;
    search.type = 'search';
    search.placeholder = 'ابحث هنا…';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', 'البحث في ' + labelText);
    options.setAttribute('role', 'group');
    options.setAttribute('aria-label', labelText);
    error.setAttribute('role', 'alert');
    trigger.append(summary);
    panel.append(search, options);
    wrapper.append(trigger, panel, tags, error);
    select.after(wrapper);
    select.classList.add('native-enhanced');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');

    let entries = [], references = [], shown = LIMIT;
    function close() {
      panel.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }
    function refresh(force = false) {
      const current = [...select.options];
      if (!force && current.length === references.length && current.every((option, i) => option === references[i])) return false;
      references = current;
      entries = current.filter(option => option.value && !option.hidden && !option.disabled).map(option => ({option, text: option.textContent, key: normalize(option.textContent)}));
      return true;
    }
    function updateSelection() {
      const chosen = [...select.selectedOptions].filter(option => option.value);
      summary.textContent = select.multiple ? (chosen.length ? chosen.length + ' اختيار محدد' : 'اختر من القائمة') : (chosen[0]?.textContent || 'اختر من القائمة');
      tags.textContent = select.multiple ? chosen.map(option => option.textContent).join('، ') : '';
      trigger.disabled = select.disabled || select.dataset.marketLocked === '1';
      const selected = new Set(chosen.map(option => option.value));
      options.querySelectorAll('[data-option]').forEach(button => {
        const active = selected.has(button.dataset.option);
        button.setAttribute('aria-pressed', String(active));
        button.textContent = (select.multiple ? (active ? '☑ ' : '☐ ') : '') + button.dataset.label;
      });
    }
    function render() {
      const term = normalize(search.value);
      const matches = entries.filter(entry => entry.key.includes(term));
      const fragment = document.createDocumentFragment();
      matches.slice(0, shown).forEach(entry => {
        const button = create('button', 'search-select-option');
        button.type = 'button';
        button.dataset.option = entry.option.value;
        button.dataset.label = entry.text;
        fragment.append(button);
      });
      if (!matches.length) fragment.append(create('p', 'market-select-options-empty', 'لا توجد خيارات مطابقة.'));
      if (matches.length > shown) {
        const hint = create('p', 'market-select-options-empty', 'عرض ' + shown + ' من ' + matches.length + '؛ استخدم البحث أو اعرض المزيد.');
        const more = create('button', 'search-select-option', 'عرض المزيد');
        more.type = 'button';
        more.dataset.providerMore = '1';
        fragment.append(hint, more);
      }
      options.replaceChildren(fragment);
      updateSelection();
    }
    options.addEventListener('click', event => {
      const more = event.target.closest('[data-provider-more]');
      if (more) {
        const previous = shown;
        shown += LIMIT;
        render();
        options.querySelectorAll('[data-option]')[previous]?.focus({preventScroll: true});
        return;
      }
      const button = event.target.closest('[data-option]');
      if (!button || select.disabled) return;
      const entry = entries.find(row => row.option.value === button.dataset.option);
      if (!entry) return;
      if (select.multiple) entry.option.selected = !entry.option.selected;
      else select.value = entry.option.value;
      // Incremental selection updates keep the clicked button and focus intact.
      select.dispatchEvent(new Event('change', {bubbles: true}));
      error.textContent = '';
      if (!select.multiple) { close(); trigger.focus(); }
    });
    select.addEventListener('change', () => {
      if (refresh()) render();
      else updateSelection();
    });
    new MutationObserver(() => {
      const changed = refresh(true);
      if (!panel.hidden && changed) render();
      else updateSelection();
    }).observe(select, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['disabled', 'hidden', 'label', 'value', 'multiple']});
    trigger.addEventListener('click', () => {
      if (!panel.hidden) { close(); return; }
      document.querySelectorAll('.market-select-trigger[aria-expanded="true"]').forEach(other => { if (other !== trigger) other.click(); });
      refresh(); shown = LIMIT; search.value = ''; render();
      panel.hidden = false; trigger.setAttribute('aria-expanded', 'true'); search.focus();
    });
    search.addEventListener('input', () => { shown = LIMIT; render(); });
    trigger.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown') { event.preventDefault(); if (panel.hidden) trigger.click(); else search.focus(); }
    });
    wrapper.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); event.stopPropagation(); close(); trigger.focus(); return; }
      if (panel.hidden || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      if (event.target === search && ['Home', 'End'].includes(event.key)) return;
      const buttons = [...options.querySelectorAll('[data-option], [data-provider-more]')];
      if (!buttons.length) return;
      event.preventDefault();
      const current = buttons.indexOf(document.activeElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length;
      buttons[next].focus();
    });
    wrapper.addEventListener('click', event => event.stopPropagation());
    label?.addEventListener('click', event => { event.preventDefault(); trigger.focus(); });
    select.addEventListener('invalid', event => { event.preventDefault(); error.textContent = 'اختر قيمة متاحة من القائمة.'; trigger.focus(); });
    document.addEventListener('click', event => { if (!wrapper.contains(event.target)) close(); }, true);
    document.addEventListener('focusin', event => { if (!wrapper.contains(event.target)) close(); }, true);
    window.addEventListener('resize', close);
    refresh(); updateSelection();
  });
})();
