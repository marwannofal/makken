/* MAKKEN TABLE VALUES v1 — progressive, read-only table collections. */
(() => {
  'use strict';
  if (window.MakkenTableValues || typeof HTMLDialogElement === 'undefined' ||
      typeof HTMLDialogElement.prototype.showModal !== 'function') return;

  const LIMIT = 3;
  const CELL = 'td, [role="cell"]';
  const SKIP = '[data-table-values-skip], [data-mk-values-dialog]';
  const CONTROL = '[data-mk-values-control]';
  const knownGroup = '[data-table-values], [data-cell-values], .tags, [class$="-tags"], [class*="-tags "], .chips, .badges, .market-match-reasons';
  const forbidden = 'button, input, select, textarea, form, details, [contenteditable="true"], [role="button"], [role="checkbox"]';
  const groups = new WeakMap();
  const buttons = new WeakMap();
  const pending = new Set();
  let scheduled = false;
  let panel = null;
  let opened = null;
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const plain = text => String(text || '').replace(/\s+/g, ' ').trim();
  function readable(node) {
    if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';
    if (node.nodeType !== Node.ELEMENT_NODE || node.matches('svg, script, style, [aria-hidden="true"], [data-mk-values-control]')) return '';
    return plain(Array.from(node.childNodes, readable).join(' '));
  }
  function icon(path) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const line = document.createElementNS(svg.namespaceURI, 'path');
    line.setAttribute('d', path);
    svg.append(line);
    return svg;
  }
  function heading(cell, group) {
    if (group.dataset.valuesLabel) return plain(group.dataset.valuesLabel);
    if (cell.dataset.label) return plain(cell.dataset.label);
    const table = cell.closest('table');
    const header = table?.tHead?.rows[table.tHead.rows.length - 1];
    let column = 0;
    for (const sibling of cell.parentElement.children) {
      if (sibling === cell) break;
      column += Number(sibling.getAttribute('colspan') || 1);
    }
    if (header) {
      let index = 0;
      for (const item of header.cells) {
        index += item.colSpan;
        if (index > column) return readable(item) || 'العناصر المرتبطة';
      }
    }
    return 'العناصر المرتبطة';
  }
  function context(cell) {
    const row = cell.closest('tr, [role="row"]');
    const label = row?.querySelector('th[scope="row"], .sector-name, .provider-name, .organization-name');
    if (label) return readable(label);
    const first = row && Array.from(row.children).find(node => !node.matches('.action-cell') && readable(node));
    return first && first !== cell ? readable(first).slice(0, 220) : '';
  }
  function itemsOf(group) {
    return Array.from(group.children).filter(node => !node.matches(CONTROL) &&
      !node.hidden && node.getAttribute('aria-hidden') !== 'true' &&
      node.style.display !== 'none');
  }
  function isCollection(group, cell) {
    if (group.closest(SKIP) || group.closest(CELL) !== cell ||
        group.matches('table, thead, tbody, tr, form, button, a, select, details, dialog') ||
        Array.from(group.querySelectorAll(forbidden)).some(node => !node.closest(CONTROL))) return false;
    const items = itemsOf(group);
    if (items.length < 4) return groups.has(group);
    if (Array.from(group.childNodes).some(node => node.nodeType === Node.TEXT_NODE && plain(node.nodeValue))) return false;
    if (!items.every(node => node.matches('bdi, span, li, a, div') && plain(readable(node)))) return false;
    if (group.matches('ul, ol')) return items.every(node => node.tagName === 'LI');
    if (group.matches(knownGroup)) return true;
    const tag = items[0].tagName;
    if (['BDI', 'SPAN'].includes(tag) && items.every(node => node.tagName === tag)) return true;
    const repeated = Array.from(items[0].classList).filter(name => /tag|chip|item|entry|coverage|offering|value/.test(name));
    return repeated.length > 0 && items.every(node => node.tagName === tag && repeated.some(name => node.classList.contains(name)));
  }

  function ensurePanel() {
    if (panel) return panel;
    const dialog = make('dialog', 'mk-values-dialog');
    dialog.id = 'makken-table-values-dialog';
    dialog.dataset.mkValuesDialog = '';
    dialog.dir = 'rtl';
    dialog.setAttribute('aria-labelledby', 'mk-values-title');
    dialog.setAttribute('aria-describedby', 'mk-values-description');
    const body = make('div', 'mk-values-body');
    const top = make('div', 'mk-values-top');
    const symbol = make('span', 'mk-values-symbol');
    symbol.append(icon('M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01'));
    const close = make('button', 'mk-values-close');
    close.type = 'button';
    close.setAttribute('aria-label', 'إغلاق النافذة');
    close.append(icon('m6 6 12 12M18 6 6 18'));
    close.addEventListener('click', dismiss);
    top.append(symbol, close);
    const eyebrow = make('p', 'mk-values-eyebrow', 'تفاصيل السجل');
    const title = make('h2', 'mk-values-title');
    title.id = 'mk-values-title';
    const description = make('p', 'mk-values-description');
    description.id = 'mk-values-description';
    const searchLabel = make('label', 'mk-values-search-label', 'البحث في العناصر');
    searchLabel.htmlFor = 'mk-values-search';
    const search = make('input', 'mk-values-search');
    search.id = 'mk-values-search';
    search.type = 'search';
    search.autocomplete = 'off';
    search.placeholder = 'اكتب للبحث في القائمة…';
    search.setAttribute('aria-controls', 'mk-values-list');
    const count = make('p', 'mk-values-count');
    count.setAttribute('aria-live', 'polite');
    count.setAttribute('role', 'status');
    const list = make('ul', 'mk-values-list');
    list.id = 'mk-values-list';
    const empty = make('p', 'mk-values-empty', 'لا توجد عناصر مطابقة. جرّب كلمة أخرى.');
    empty.hidden = true;
    const footer = make('div', 'mk-values-footer');
    const done = make('button', 'mk-values-done', 'إغلاق');
    done.type = 'button';
    done.addEventListener('click', dismiss);
    footer.append(done);
    body.append(top, eyebrow, title, description, searchLabel, search, count, list, empty, footer);
    dialog.append(body);
    const normalize = value => String(value).normalize('NFKC').toLocaleLowerCase('ar').replace(/[\u064b-\u065f\u0670]/g, '');
    search.addEventListener('input', () => {
      const term = normalize(search.value.trim());
      let visible = 0;
      for (const item of list.children) {
        item.hidden = !normalize(item.textContent).includes(term);
        if (!item.hidden) visible++;
      }
      count.textContent = term ? `نتائج البحث: ${visible} من ${list.children.length}` : `عدد العناصر: ${list.children.length}`;
      empty.hidden = visible !== 0;
    });
    let outside = false;
    const beyond = event => {
      const rect = dialog.getBoundingClientRect();
      return event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
    };
    dialog.addEventListener('pointerdown', event => { outside = event.target === dialog && beyond(event); });
    dialog.addEventListener('click', event => { if (outside && event.target === dialog && beyond(event)) dismiss(); outside = false; });
    dialog.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); dismiss(); }
      if (event.key === 'Tab') {
        const focusable = Array.from(dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'))
          .filter(node => !node.hidden && node.getClientRects().length);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    });
    function finish() {
      if (!opened) return;
      document.documentElement.classList.remove('mk-values-open');
      const previous = opened?.button;
      previous?.setAttribute('aria-expanded', 'false');
      opened = null;
      list.replaceChildren();
      const ancestor = previous?.closest('dialog');
      if (previous?.isConnected && previous.getClientRects().length && (!ancestor || ancestor.open)) previous.focus({preventScroll: true});
      else document.getElementById('main-content')?.focus({preventScroll: true});
    }
    function dismiss() { dialog.close(); finish(); }
    dialog.addEventListener('close', () => { if (!dialog.open) finish(); });
    document.body.append(dialog);
    panel = {dialog, title, description, search, count, list, empty, close};
    return panel;
  }

  function show(state) {
    if (!state.group.isConnected) return;
    refresh(state.group, state.cell);
    const current = groups.get(state.group);
    if (!current || current.items.length <= LIMIT) return;
    const modal = ensurePanel();
    const title = heading(current.cell, current.group);
    modal.title.textContent = title;
    const rowLabel = context(current.cell);
    modal.description.textContent = rowLabel ? `جميع العناصر المرتبطة بـ «${rowLabel}».` : 'جميع عناصر هذه الخانة، بالترتيب الظاهر في السجل.';
    modal.list.setAttribute('aria-label', title);
    const content = document.createDocumentFragment();
    for (const source of current.items) {
      const item = make('li', 'mk-values-item');
      item.append(make('bdi', '', readable(source)));
      if (/inactive|disabled/.test(source.className)) item.classList.add('mk-values-item-inactive');
      // Preserve ordinary document links without copying IDs or event handlers.
      const link = source.matches('a[href]') ? source : source.querySelector('a[href]');
      if (link && source.querySelectorAll('a[href]').length <= 1) {
        try {
          const url = new URL(link.getAttribute('href'), location.href);
          if (['https:', 'http:'].includes(url.protocol)) {
            const anchor = make('a', '', readable(source));
            anchor.href = url.href;
            if (link.target === '_blank') { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; }
            if (link.hasAttribute('download')) anchor.setAttribute('download', link.getAttribute('download'));
            item.replaceChildren(anchor);
          }
        } catch { /* Invalid links remain readable text. */ }
      }
      content.append(item);
    }
    modal.list.replaceChildren(content);
    modal.search.value = '';
    modal.empty.hidden = true;
    modal.count.textContent = `عدد العناصر: ${current.items.length}`;
    opened = current;
    current.button.setAttribute('aria-expanded', 'true');
    document.documentElement.classList.add('mk-values-open');
    modal.dialog.showModal();
    modal.close.focus({preventScroll: true});
    modal.list.scrollTop = 0;
  }

  function refresh(group, cell) {
    const items = itemsOf(group);
    const previous = groups.get(group);
    if (previous) {
      for (const item of previous.items) if (!items.includes(item)) item.classList.remove('mk-cell-value-overflow');
    }
    if (items.length <= LIMIT) {
      for (const item of items) item.classList.remove('mk-cell-value-overflow');
      previous?.control.remove();
      groups.delete(group);
      return;
    }
    let state = previous;
    if (!state || state.control.parentElement !== group) {
      // Cloned/replaced table fragments get one working toggle, never two.
      for (const old of Array.from(group.children).filter(node => node.matches(CONTROL))) old.remove();
      const button = make('button', 'mk-cell-values-more');
      button.type = 'button';
      button.dataset.mkValuesMore = '';
      button.setAttribute('aria-haspopup', 'dialog');
      button.setAttribute('aria-controls', 'makken-table-values-dialog');
      button.setAttribute('aria-expanded', 'false');
      const control = group.matches('ul, ol') ? make('li', 'mk-cell-values-toggle') : button;
      control.dataset.mkValuesControl = '';
      if (control !== button) control.append(button);
      group.append(control);
      state = {group, cell, button, control, items: [], label: ''};
      buttons.set(button, state);
      groups.set(group, state);
    }
    state.items = items;
    for (const [index, item] of items.entries()) item.classList.toggle('mk-cell-value-overflow', index >= LIMIT);
    const label = `عرض المزيد (+${items.length - LIMIT})`;
    if (state.label !== label) {
      const count = make('bdi', '', `(+${items.length - LIMIT})`);
      count.dir = 'ltr';
      state.button.replaceChildren(make('span', '', 'عرض المزيد'), count, icon('m6 9 6 6 6-6'));
      state.label = label;
    }
    state.button.setAttribute('aria-label', `${heading(cell, group)}: عرض جميع العناصر وعددها ${items.length}`);
  }

  function splitTextGroups(cell) {
    // Existing region summaries are Arabic-comma-delimited <small> nodes.
    // Never split money, descriptions, inputs, or arbitrary cell text.
    for (const node of cell.querySelectorAll('small, [data-table-values-text]')) {
      if (node.closest(SKIP) || node.children.length || !node.textContent.includes('،')) continue;
      const values = node.textContent.split('،').map(plain).filter(Boolean);
      if (values.length <= LIMIT) continue;
      node.dataset.tableValues = '';
      node.classList.add('mk-cell-text-values');
      const content = document.createDocumentFragment();
      for (const value of values) content.append(make('bdi', 'mk-cell-text-value', value));
      node.replaceChildren(content);
    }
  }
  function scanCell(cell) {
    if (!cell.isConnected || cell.closest(SKIP)) return;
    splitTextGroups(cell);
    const candidates = [cell, ...cell.querySelectorAll('div, span, small, ul, ol, [data-table-values], [data-cell-values]')];
    for (const group of candidates) if (isCollection(group, cell)) refresh(group, cell);
  }
  function scan(root = document) {
    if (root.nodeType === Node.ELEMENT_NODE && root.matches(CELL)) scanCell(root);
    for (const cell of root.querySelectorAll(CELL)) scanCell(cell);
  }
  function flush() {
    scheduled = false;
    const work = Array.from(pending);
    pending.clear();
    for (const node of work) {
      if (!node.isConnected) continue;
      if (node.matches(CELL)) scanCell(node);
      else scan(node);
    }
  }
  const observer = new MutationObserver(records => {
    for (const record of records) {
      const target = record.target.nodeType === Node.ELEMENT_NODE ? record.target : record.target.parentElement;
      if (!target || target.closest('[data-mk-values-dialog], [data-mk-values-control]')) continue;
      const cell = target.closest(CELL);
      if (cell) pending.add(cell);
      else for (const node of record.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE && !node.closest(SKIP) &&
            (node.matches('table, tr, tbody, [role="grid"], [role="row"], td') || node.querySelector(CELL))) pending.add(node);
      }
    }
    if (pending.size && !scheduled) { scheduled = true; requestAnimationFrame(flush); }
  });
  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-mk-values-more]');
    const state = button && buttons.get(button);
    if (!state) return;
    event.preventDefault();
    event.stopPropagation();
    show(state);
  }, true);
  document.addEventListener('keydown', event => {
    if (event.target.matches?.('[data-mk-values-more]') && ['Enter', ' '].includes(event.key)) event.stopPropagation();
  }, true);
  window.MakkenTableValues = Object.freeze({refresh: scan, limit: LIMIT});
  scan();
  observer.observe(document.body, {subtree: true, childList: true, characterData: true});
})();
