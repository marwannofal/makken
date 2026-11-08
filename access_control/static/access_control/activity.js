(() => {
  'use strict';
  const dialog = document.getElementById('activity-detail');
  if (!dialog) return;
  const content = dialog.querySelector('[data-activity-content]');
  let opener = null, controller = null;
  async function open(url, source) {
    controller?.abort(); controller = new AbortController(); opener = source;
    content.textContent = 'جار تحميل تفاصيل النشاط…';
    content.setAttribute('aria-busy', 'true');
    if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch(url, {credentials:'same-origin', signal:controller.signal,
        headers:{'X-Requested-With':'XMLHttpRequest','Accept':'text/html'}});
      if (!response.ok || response.redirected) throw new Error('unavailable');
      const document = new DOMParser().parseFromString(await response.text(), 'text/html');
      const details = document.querySelector('[data-activity-detail]');
      if (!details) throw new Error('invalid');
      content.replaceChildren(details);
    } catch (error) {
      if (error.name !== 'AbortError') content.textContent = 'تعذّر عرض التفاصيل أو تغيّرت صلاحية الوصول. أغلق النافذة وحدّث الصفحة ثم أعد المحاولة.';
    } finally { content.removeAttribute('aria-busy'); }
  }
  document.querySelectorAll('[data-activity-url]').forEach(row => {
    row.addEventListener('click', event => {
      const link = event.target.closest('[data-activity-open]');
      if (!link && event.target.closest('a,button,input,select,textarea,summary,[data-mk-values-control]')) return;
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); open(row.dataset.activityUrl, link || row);
    });
    row.addEventListener('keydown', event => {
      if (event.target === row && ['Enter',' '].includes(event.key)) {
        event.preventDefault(); open(row.dataset.activityUrl, row);
      }
    });
  });
  dialog.querySelectorAll('[data-activity-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('close', () => {controller?.abort(); if (opener?.isConnected) opener.focus();});
})();
