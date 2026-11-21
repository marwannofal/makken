(() => {
  'use strict';
  if (window.MakkenRowActionsMenu) return;

  const DOTS_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>';
  const TOGGLE_OFF_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6m0-6-6 6"/></svg>';
  const TOGGLE_ON_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/></svg>';

  const ACTION_CONTAINER_SELECTOR = [
    'table tbody td .row-actions',
    'table tbody td .level-row-actions',
    'table tbody td .entity-row-actions',
    'table tbody td .region-row-actions',
    'table tbody td .sector-row-actions',
    'table tbody td .specialization-row-actions',
    'table tbody td .expense-item-row-actions',
    'table tbody td .program-row-actions',
    'table tbody td .sponsorship-shape-row-actions',
  ].join(', ');

  const STATUS_BTN_SELECTOR = [
    'button.record-status',
    'button.level-status',
    'button.entity-status',
    'button.region-status',
    'button.sector-status',
    'button.specialization-status',
    'button.expense-item-status',
    'button.program-status',
    'button.sponsorship-shape-status',
  ].join(', ');

  let openMenu = null;
  let backdrop = null;

  function ensureBackdrop() {
    if (backdrop) return backdrop;
    backdrop = document.createElement('div');
    backdrop.className = 'mk-actions-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    backdrop.addEventListener('click', () => closeOpenMenu(false));
    document.body.append(backdrop);
    return backdrop;
  }

  function closeOpenMenu(returnFocus = false) {
    if (!openMenu) return;
    const {wrapper, trigger, dropdown, row, scroll} = openMenu;
    dropdown.hidden = true;
    dropdown.classList.remove('is-dropup');
    wrapper.classList.remove('is-open');
    trigger.setAttribute('aria-expanded', 'false');
    if (row) row.classList.remove('mk-has-open-menu');
    if (scroll) scroll.classList.remove('mk-scroll-unclipped');
    if (backdrop) backdrop.classList.remove('is-open');
    openMenu = null;
    if (returnFocus && trigger.isConnected) {
      trigger.focus({preventScroll: true});
    }
  }

  function toggleMenu(entry) {
    if (openMenu && openMenu.wrapper === entry.wrapper) {
      closeOpenMenu(false);
      return;
    }
    closeOpenMenu(false);
    const {wrapper, trigger, dropdown, row, scroll} = entry;

    const tbody = row?.closest('tbody');
    const allRows = tbody ? [...tbody.rows] : [];
    const rowIndex = row ? allRows.indexOf(row) : -1;
    const rect = trigger.getBoundingClientRect();
    const nearViewportBottom = window.innerHeight - rect.bottom < 240;
    const isBottomRow = allRows.length >= 3 && rowIndex >= allRows.length - 2;
    dropdown.classList.toggle('is-dropup', nearViewportBottom || isBottomRow);

    if (scroll && scroll.scrollWidth <= scroll.clientWidth + 2) {
      scroll.classList.add('mk-scroll-unclipped');
    }

    dropdown.hidden = false;
    wrapper.classList.add('is-open');
    trigger.setAttribute('aria-expanded', 'true');
    if (row) row.classList.add('mk-has-open-menu');
    ensureBackdrop().classList.add('is-open');
    openMenu = entry;
  }

  function createMenuWrapper(td) {
    const existing = td.querySelector('.mk-actions-menu');
    if (existing) {
      return {
        wrapper: existing,
        dropdown: existing.querySelector('.mk-actions-dropdown'),
      };
    }

    td.classList.add('mk-actions-cell');
    const wrapper = document.createElement('div');
    wrapper.className = 'mk-actions-menu';

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'mk-actions-trigger';
    trigger.setAttribute('aria-haspopup', 'menu');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-label', 'خيارات الإجراء');
    trigger.title = 'خيارات الإجراء';
    trigger.innerHTML = DOTS_SVG;

    const dropdown = document.createElement('div');
    dropdown.className = 'mk-actions-dropdown';
    dropdown.setAttribute('role', 'menu');
    dropdown.hidden = true;

    wrapper.append(trigger, dropdown);

    const entry = {
      wrapper,
      trigger,
      dropdown,
      row: td.closest('tr'),
      scroll: td.closest('.table-scroll, .table-wrapper, .states-table-wrapper, .table-responsive'),
    };

    trigger.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      toggleMenu(entry);
    });

    dropdown.addEventListener('click', event => {
      event.stopPropagation();
      const clickedAction = event.target.closest('a, button');
      if (clickedAction) {
        closeOpenMenu(false);
      }
    });

    return {wrapper, dropdown};
  }

  function collectActionNodes(container) {
    return [...container.children].filter(node => node.matches('a, button, form'));
  }

  function formatStatusToggleButton(btn) {
    if (!btn || btn.dataset.mkStatusRelabeled === '1') return;
    btn.dataset.mkStatusRelabeled = '1';
    const isActive = btn.classList.contains('status-active') || btn.classList.contains('is-enabled');
    btn.className = isActive ? 'mk-toggle-action is-deactivate' : 'mk-toggle-action is-activate';
    btn.innerHTML = (isActive ? TOGGLE_OFF_SVG : TOGGLE_ON_SVG)
      + '<span>' + (isActive ? 'إيقاف التفعيل' : 'تفعيل السجل') + '</span>';
  }

  function wrapContainer(container) {
    if (!container || container.dataset.mkMenuEnhanced === '1') return;
    if (container.closest('dialog, template, [data-ac-matrix], .mk-actions-menu')) return;

    const nodes = collectActionNodes(container);
    if (!nodes.length) return;

    container.dataset.mkMenuEnhanced = '1';
    const td = container.closest('td');
    if (!td) return;

    const {wrapper, dropdown} = createMenuWrapper(td);
    nodes.forEach(node => {
      const statusBtn = node.matches('form') ? node.querySelector(STATUS_BTN_SELECTOR) : (node.matches(STATUS_BTN_SELECTOR) ? node : null);
      if (statusBtn) formatStatusToggleButton(statusBtn);
      node.setAttribute('role', 'menuitem');
      dropdown.append(node);
    });

    if (!wrapper.isConnected) {
      container.replaceWith(wrapper);
    } else {
      container.remove();
    }
  }

  function enhanceDirectActionCell(td) {
    if (!td || td.dataset.mkMenuEnhanced === '1') return;
    if (td.closest('dialog, template, [data-ac-matrix]')) return;
    if (td.querySelector('.mk-actions-menu')) return;
    const nodes = collectActionNodes(td);
    if (!nodes.length) return;

    td.dataset.mkMenuEnhanced = '1';
    const {wrapper, dropdown} = createMenuWrapper(td);
    nodes.forEach(node => {
      const statusBtn = node.matches('form') ? node.querySelector(STATUS_BTN_SELECTOR) : (node.matches(STATUS_BTN_SELECTOR) ? node : null);
      if (statusBtn) formatStatusToggleButton(statusBtn);
      node.setAttribute('role', 'menuitem');
      dropdown.append(node);
    });
    td.append(wrapper);
  }

  function moveRowStatusTogglesIntoMenu(main) {
    main.querySelectorAll('table tbody tr').forEach(tr => {
      if (tr.closest('dialog, template, [data-ac-matrix]')) return;
      const statusForms = [...tr.querySelectorAll('td form')].filter(form => {
        if (form.dataset.mkStatusMoved === '1') return false;
        if (form.closest('.mk-actions-menu, .mk-actions-dropdown')) return false;
        return Boolean(form.querySelector(STATUS_BTN_SELECTOR));
      });
      if (!statusForms.length) return;

      // Target the row's action cell (prefer existing .mk-actions-menu, or td.action-cell, or last td)
      let actionTd = tr.querySelector('.mk-actions-menu')?.closest('td')
        || tr.querySelector('td.action-cell')
        || tr.cells[tr.cells.length - 1];
      if (!actionTd) return;

      const {wrapper, dropdown} = createMenuWrapper(actionTd);
      if (!wrapper.isConnected) {
        actionTd.append(wrapper);
      }

      statusForms.forEach(form => {
        const btn = form.querySelector(STATUS_BTN_SELECTOR);
        if (!btn) return;
        form.dataset.mkStatusMoved = '1';

        // Leave a clean non-clickable status pill in the original status column
        const pill = document.createElement('span');
        pill.className = btn.className;
        pill.innerHTML = btn.innerHTML;
        form.before(pill);

        // Relabel and move the live form (preserving CSRF & signed token) into the ⋮ menu
        formatStatusToggleButton(btn);
        form.setAttribute('role', 'menuitem');
        const deleteItem = dropdown.querySelector('.delete-action, .action-delete, [class*="delete"]')?.closest('form, a, button');
        if (deleteItem && deleteItem.parentElement === dropdown) {
          dropdown.insertBefore(form, deleteItem);
        } else {
          dropdown.append(form);
        }
      });
    });
  }

  function enhanceAll(root = document) {
    const main = root.querySelector?.('#main-content') || root;
    if (!main || !main.querySelectorAll) return;
    main.querySelectorAll(ACTION_CONTAINER_SELECTOR).forEach(wrapContainer);
    main.querySelectorAll('table tbody td.action-cell').forEach(enhanceDirectActionCell);
    moveRowStatusTogglesIntoMenu(main);
  }

  document.addEventListener('click', event => {
    if (openMenu && !openMenu.wrapper.contains(event.target)) {
      closeOpenMenu(false);
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && openMenu) {
      event.preventDefault();
      closeOpenMenu(true);
    }
  });

  window.addEventListener('resize', () => closeOpenMenu(false));

  window.MakkenRowActionsMenu = {enhanceAll, closeOpenMenu};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => enhanceAll(document));
  } else {
    enhanceAll(document);
  }

  let queued = false;
  new MutationObserver(records => {
    if (queued) return;
    const relevant = records.some(r => [...r.addedNodes].some(
      n => n.nodeType === 1 && (n.matches?.('tr, td, .row-actions') || n.querySelector?.('.row-actions, td.action-cell'))
    ));
    if (!relevant) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      enhanceAll(document);
    });
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
