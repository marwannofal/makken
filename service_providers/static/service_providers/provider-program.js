(() => {
  'use strict';
  const select = document.getElementById('provider-program');
  const source = document.getElementById('provider-catalog');
  if (!select || !source) return;
  let programs = [];
  try { programs = JSON.parse(source.textContent).programs || []; } catch { return; }
  function update() {
    const program = programs.find(item => String(item.id) === select.value);
    for (const [selector, value] of [
      ['[data-provider-program-category]', program?.category],
      ['[data-provider-program-type]', program?.type],
      ['[data-provider-program-expenses]', program?.expenses.join('، ')],
    ]) {
      const output = document.querySelector(selector);
      if (output) output.textContent = value || '—';
    }
  }
  select.addEventListener('change', update);
  update();
})();
