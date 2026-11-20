(() => {
  'use strict';
  const form = document.querySelector('[data-target-search]');
  if (!form) return;
  const kind = form.querySelector('[data-target-kind]');
  const key = form.querySelector('[data-target-key]');
  const panel = form.querySelector('[data-target-panel]');
  const term = form.querySelector('#target-term');
  const results = form.querySelector('#target-results');
  const message = form.querySelector('[data-target-message]');
  const run = form.querySelector('[data-target-run]');
  let request = null;
  const reset = () => results.replaceChildren(new Option('اختر نتيجة', ''));
  const change = () => {
    request?.abort();
    key.value = '';
    panel.hidden = !kind.value;
    reset();
    message.textContent = '';
    run.disabled = false;
  };
  panel.hidden = !kind.value;
  kind.addEventListener('change', change);
  results.addEventListener('change', () => { if (results.value) key.value = results.value; });
  const search = async () => {
    if (!kind.value) return;
    request?.abort();
    const controller = new AbortController();
    request = controller;
    run.disabled = true;
    message.textContent = 'جار البحث…';
    reset();
    const url = new URL(form.dataset.targetSearch, window.location.origin);
    url.searchParams.set('model', kind.value);
    url.searchParams.set('q', term.value);
    try {
      const response = await fetch(url, {signal: controller.signal, headers: {'Accept': 'application/json'}});
      if (!response.ok) throw new Error();
      const {results: rows} = await response.json();
      if (controller.signal.aborted) return;
      for (const row of rows) results.add(new Option(row.label, row.id));
      message.textContent = rows.length ? 'اختر سجلًا من النتائج.' : 'لا توجد نتائج مطابقة.';
    } catch (error) {
      if (error.name !== 'AbortError') message.textContent = 'تعذّر البحث الآن.';
    } finally {
      if (request === controller) run.disabled = false;
    }
  };
  run.addEventListener('click', search);
  term.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); search(); } });
})();

(() => {
  'use strict';
  const bar = document.querySelector('[data-mail-tabs]');
  if (!bar) return;
  const buttons = Array.from(bar.querySelectorAll('[data-mail-tab]'));
  const panels = Array.from(document.querySelectorAll('[data-mail-panel]'));
  const activate = (name, pushUrl) => {
    buttons.forEach(btn => {
      const on = btn.dataset.mailTab === name;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    panels.forEach(panel => {
      panel.hidden = panel.dataset.mailPanel !== name;
    });
    if (pushUrl && window.history && window.history.replaceState) {
      const url = new URL(window.location.href);
      url.searchParams.set('tab', name);
      window.history.replaceState(null, '', url.toString());
    }
  };
  buttons.forEach(btn => btn.addEventListener('click', () => activate(btn.dataset.mailTab, true)));
})();
