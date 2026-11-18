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
