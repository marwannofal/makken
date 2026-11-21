(() => {
  'use strict';
  if (window.MakkenCompactTables) return;

  function isSkippedCard(card) {
    return !card || card.closest('dialog,template,.dash-page');
  }

  function hasSearchForm(card) {
    return Boolean(card.querySelector('form[method="get" i]'));
  }

  function hasDataTable(card) {
    const table = card.querySelector('table');
    return Boolean(table && !table.closest('dialog,template'));
  }

  function enhanceFilterCard(filterCard) {
    if (!filterCard || filterCard.dataset.mkCompactFilter) return;
    filterCard.dataset.mkCompactFilter = '1';
    filterCard.classList.add('mk-unified-filter-card');

    // If it already has a settings_filters kicker, leave it in place.
    if (!filterCard.querySelector('.mk-section-kicker')) {
      const heading = filterCard.querySelector(':scope > .card-heading');
      const hasActionButton = heading && heading.querySelector('a.button, button');
      if (heading && !hasActionButton) {
        heading.classList.add('mk-header-compact-hidden');
      } else if (heading && hasActionButton) {
        heading.querySelectorAll('.eyebrow, .muted').forEach(el => el.classList.add('mk-header-compact-hidden'));
      }
      const kicker = document.createElement('p');
      kicker.className = 'mk-section-kicker';
      kicker.textContent = 'معايير البحث';
      if (heading && hasActionButton) {
        heading.after(kicker);
      } else {
        filterCard.prepend(kicker);
      }
    }

    // Visually hide redundant "البحث في السجل" label while preserving screen-reader accessibility.
    filterCard.querySelectorAll('label').forEach(label => {
      const text = label.textContent.trim();
      if (text === 'البحث في السجل') {
        label.classList.add('visually-hidden');
      }
    });
  }

  function buildResultsBar(tableCard) {
    if (!tableCard || tableCard.dataset.mkCompactTable) return;
    tableCard.dataset.mkCompactTable = '1';

    const header = tableCard.querySelector(':scope > .states-card-header, :scope > .card-heading');
    if (!header) return;

    const bar = document.createElement('div');
    bar.className = 'mk-results-bar';
    bar.dataset.mkResultsBar = '1';

    const start = document.createElement('div');
    start.className = 'mk-results-start';

    const title = document.createElement('span');
    title.className = 'mk-section-kicker mk-results-title';
    title.textContent = 'نتائج البحث';
    start.append(title);

    const end = document.createElement('div');
    end.className = 'mk-results-end';
    end.dataset.mkResultsEnd = '1';

    // Move record count badge into the compact start group.
    const countBadge = header.querySelector('.fixed-tag, .subtle-badge');
    if (countBadge) {
      start.append(countBadge);
    }

    // Preserve any action buttons (e.g., "إضافة إدارة" on departments tab) in the end group.
    header.querySelectorAll('a.button, button.button').forEach(btn => {
      end.append(btn);
    });

    // If table-exports.js already ran before us, move its toolbar right into the end group.
    const existingExports = tableCard.querySelector(':scope > .mk-export-tools');
    if (existingExports) {
      end.append(existingExports);
    }

    bar.append(start, end);
    header.classList.add('mk-header-compact-hidden');
    header.after(bar);
  }

  function init() {
    const main = document.querySelector('#main-content') || document.querySelector('main');
    if (!main || main.querySelector('.dash-page')) return;

    const cards = [...main.querySelectorAll('.settings-filters-card, .states-card, .partnership-card')];
    cards.forEach(card => {
      if (isSkippedCard(card)) return;

      // Case 1: Settings filter card followed by a states-card table
      if (card.classList.contains('settings-filters-card')) {
        const next = card.nextElementSibling;
        if (next && next.classList.contains('states-card') && !isSkippedCard(next)) {
          enhanceFilterCard(card);
          next.classList.add('mk-unified-table-card');
          buildResultsBar(next);
        } else {
          enhanceFilterCard(card);
        }
        return;
      }

      // Case 2: Partnership/list filter card followed by a results table card
      if (card.classList.contains('partnership-card') && hasSearchForm(card) && !hasDataTable(card)) {
        const next = card.nextElementSibling;
        if (next && next.classList.contains('partnership-card') && hasDataTable(next) && !isSkippedCard(next)) {
          enhanceFilterCard(card);
          next.classList.add('mk-unified-table-card');
          buildResultsBar(next);
        }
        return;
      }

      // Case 3: Standalone results table card (not already handled above)
      if ((card.classList.contains('states-card') || card.classList.contains('partnership-card'))
          && hasDataTable(card) && !hasSearchForm(card)) {
        buildResultsBar(card);
      }
    });
  }

  window.MakkenCompactTables = {init};
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
