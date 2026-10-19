(() => {
  'use strict';
  const dialog = document.getElementById('dependency-block');
  if (!dialog) return;
  const previous = document.activeElement;
  // Existing forms may reopen their own editor; the explanatory alert stays on top.
  dialog.removeAttribute('open');
  dialog.showModal();
  dialog.querySelectorAll('[data-dependency-close]').forEach(button => {
    button.addEventListener('click', () => dialog.close());
  });
  dialog.addEventListener('close', () => {
    if (previous?.isConnected && previous.getClientRects().length) previous.focus();
    else document.getElementById('main-content')?.focus();
  });
})();
