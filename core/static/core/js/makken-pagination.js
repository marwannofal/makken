(() => {
  'use strict';
  document.addEventListener('change', (event) => {
    const select = event.target && event.target.closest('select[data-mk-per-page-select]');
    if (!select) return;
    const option = select.options[select.selectedIndex];
    const url = option && option.getAttribute('data-url');
    if (url) window.location.assign(url);
  });
})();
