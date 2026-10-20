(() => {
  'use strict';
  if (window.MakkenTableExports) return;
  let rights = {xlsx: false, pdf: false};
  try {
    const config = document.getElementById('makken-table-export-access');
    if (config) {
      const values = JSON.parse(config.textContent);
      rights = {xlsx: values.xlsx === true, pdf: values.pdf === true};
    }
  } catch (_) { /* Missing/invalid configuration never grants access. */ }
  const formats = ['xlsx', 'pdf'].filter(format => rights[format]);
  const icons = {
    xlsx: '<path d="M14 2H5v20h14V7ZM14 2v6h5M8 12l5 6m0-6-5 6"/>',
    pdf: '<path d="M14 2H5v20h14V7ZM14 2v6h5M8 13h7m-7 4h5"/>',
    busy: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    done: '<path d="m5 12 4 4L19 6"/>',
    error: '<path d="m12 3 10 18H2Zm0 6v5m0 3v1"/>'
  };
  const svg = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name]}</svg>`;
  let busy = false, dialog, trigger, controller;
  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.className = 'mk-export-dialog';
    dialog.tabIndex = -1;
    dialog.setAttribute('aria-labelledby', 'mk-export-title');
    dialog.setAttribute('aria-describedby', 'mk-export-description');
    dialog.innerHTML = '<span class="mk-export-icon" aria-hidden="true"></span><h2 id="mk-export-title"></h2><p id="mk-export-description" role="status" aria-live="polite"></p><progress class="mk-export-progress" aria-label="جار تجهيز التقرير"></progress><div class="mk-export-actions"><button type="button" class="mk-export-button" data-export-close>إغلاق</button></div>';
    document.body.append(dialog);
    dialog.querySelector('[data-export-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('cancel', e => { if (busy) { e.preventDefault(); return; } });
    dialog.addEventListener('close', () => { if (trigger?.isConnected) trigger.focus({preventScroll: true}); });
    return dialog;
  }
  function state(kind, title, text) {
    const d = ensureDialog();
    d.dataset.state = kind;
    d.querySelector('.mk-export-icon').innerHTML = svg(kind);
    d.querySelector('h2').textContent = title;
    d.querySelector('p').textContent = text;
    d.querySelector('progress').hidden = kind !== 'busy';
    const close = d.querySelector('[data-export-close]');
    close.hidden = kind === 'busy';
    d.setAttribute('aria-busy', String(kind === 'busy'));
    if (!d.open) d.showModal();
    if (kind !== 'busy') close.focus({preventScroll: true});
  }
  function eligible(table) {
    if (!table.tHead || table.closest('dialog,template') || table.hasAttribute('data-no-export') || table.matches('[data-ac-matrix]')) return false;
    if (table.querySelector('tbody input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]):not([type=color]),tbody textarea,tbody select')) return false;
    // Unsaved editors start empty and populate their table using JavaScript.
    if (table.matches('.offerings-table,[data-expense-editor]') || table.querySelector('tbody[data-offerings-table],tbody[data-expense-lines],tbody[data-services-table],tbody[data-coverage-table]')) return false;
    return table.tHead.rows.length === 1;
  }
  async function download(button, table) {
    if (busy || !rights[button.dataset.mkFormat]) return;
    const main = document.querySelector('#main-content') || document.querySelector('main');
    const tables = [...main.querySelectorAll('table')].filter(t => !t.closest('dialog,template'));
    const index = tables.indexOf(table);
    if (index < 0) return;
    trigger = button;
    busy = true;
    document.querySelectorAll('.mk-export-button[data-mk-format]').forEach(b => b.disabled = true);
    state('busy', 'جار تجهيز التقرير', 'نجهّز جميع نتائج الجدول وفق البحث والفلاتر الحالية، مع كامل التفاصيل. انتظر اكتمال التنزيل.');
    const url = new URL(window.location.href);
    url.hash = '';
    url.searchParams.set('_mk_export', button.dataset.mkFormat);
    url.searchParams.set('_mk_table', String(index));
    controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal, headers: {'Accept': '*/*'}});
      const type = response.headers.get('Content-Type') || '';
      if (!response.ok || type.includes('json')) {
        let message = 'تعذّر تجهيز التقرير. حدّث الصفحة ثم أعد المحاولة.';
        if (type.includes('json')) {
          const data = await response.json();
          if (typeof data.error === 'string') message = data.error;
        } else if ([401, 403].includes(response.status)) message = 'لا تملك صلاحية تصدير هذه الصفحة أو انتهت جلسة الدخول.';
        throw new Error(message);
      }
      if (response.redirected || !type.includes(button.dataset.mkFormat === 'pdf' ? 'application/pdf' : 'spreadsheetml')) throw new Error('انتهت جلسة الدخول أو تغيّرت الصفحة. حدّث الصفحة وسجّل الدخول ثم أعد التصدير.');
      const blob = await response.blob();
      let filename = `مكّن-${new Date().toISOString().slice(0,10)}.${button.dataset.mkFormat}`;
      const header = response.headers.get('Content-Disposition') || '';
      const utf = header.match(/filename\*=utf-8''([^;]+)/i);
      const plain = header.match(/filename="([^"\r\n]+)"/i);
      if (utf) { try { filename = decodeURIComponent(utf[1]); } catch (_) {} }
      else if (plain) filename = plain[1];
      const link = document.createElement('a');
      const objectURL = URL.createObjectURL(blob);
      link.href = objectURL;
      link.download = filename.replace(/[\\/\x00-\x1f]/g, '-');
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(objectURL), 60000);
      state('done', 'التقرير جاهز', 'بدأ تنزيل الملف. ستجده في مجلد التنزيلات وفق إعدادات متصفحك.');
    } catch (e) {
      state('error', 'لم يكتمل التصدير', e.name === 'AbortError' ? 'استغرق التقرير وقتًا طويلًا. ضيّق الفلاتر وأعد المحاولة.' : e.message || 'تعذّر الاتصال بالخادم. تحقق من الاتصال وأعد المحاولة.');
    } finally {
      clearTimeout(timer); controller = null; busy = false;
      document.querySelectorAll('.mk-export-button[data-mk-format]').forEach(b => b.disabled = false);
    }
  }
  function refresh() {
    const main = document.querySelector('#main-content') || document.querySelector('main');
    if (!main || formats.length === 0) return;
    main.querySelectorAll('table').forEach(table => {
      if (table.dataset.mkExportReady || !eligible(table)) return;
      table.dataset.mkExportReady = '1';
      const tools = document.createElement('div');
      tools.className = 'mk-export-tools';
      tools.setAttribute('role', 'group');
      tools.setAttribute('aria-label', 'تصدير بيانات الجدول');
      const label = document.createElement('span');
      label.className = 'mk-export-label'; label.textContent = 'تصدير النتائج حسب الفلاتر'; tools.append(label);
      formats.forEach(format => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'mk-export-button'; button.dataset.mkFormat = format;
        button.innerHTML = svg(format);
        const text = document.createElement('span'); text.textContent = format === 'xlsx' ? 'تصدير Excel' : 'تصدير PDF'; button.append(text);
        button.addEventListener('click', () => download(button, table)); tools.append(button);
      });
      const scroll = table.closest('.table-scroll,.table-wrapper,.states-table-wrapper,.table-responsive');
      const anchor = scroll || table;
      anchor.before(tools);
    });
  }
  window.MakkenTableExports = {refresh};
  refresh();
  let queued = false;
  new MutationObserver(records => {
    if (queued || !records.some(r => [...r.addedNodes].some(n => n.nodeType === 1 && (n.matches('table') || n.querySelector('table'))))) return;
    queued = true; requestAnimationFrame(() => { queued = false; refresh(); });
  }).observe(document.body, {childList: true, subtree: true});
})();
