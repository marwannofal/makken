(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const show = dialog => {
    if (!dialog || dialog.open) return;
    dialog.showModal();
  };
  $$('[data-server-dialog]').forEach(dialog => {
    dialog.removeAttribute('open');
    show(dialog);
    dialog.addEventListener('cancel', event => {
      if (dialog.dataset.closeUrl) {
        event.preventDefault();
        location.assign(dialog.dataset.closeUrl);
      }
    });
  });
  $$('[data-dismiss-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  $$('[data-confirm-form]').forEach(form => form.addEventListener('submit', () => {
    if (form.matches('[data-willingness-form]')) return;
    const button = $('button[type=submit]', form);
    button.disabled = true;
    button.textContent = 'جارٍ التنفيذ…';
  }));
  $$('[data-partnership-row]').forEach(row => row.addEventListener('click', event => {
    if (event.target.closest('a,button,input,select,textarea,label,form,[data-development-cell]') || getSelection()?.toString()) return;
    location.assign(row.dataset.rowUrl);
  }));

  const source = $('#partnership-catalog');
  if (!source) return;
  const catalog = JSON.parse(source.textContent);
  const rawDrafts = JSON.parse($('#partnership-drafts').textContent);
  let rows = rawDrafts.filter(row => row && Number.isInteger(row.sector) && Number.isInteger(row.shape) && Array.isArray(row.specializations) && row.specializations.every(Number.isInteger) && typeof row.is_active === 'boolean');
  const draftField = $('#id_offerings');
  const recordForm = $('[data-partnership-form]');
  const controls = new Map();
  let selectSequence = 0;
  let openSelect = null;
  const names = new Intl.DisplayNames(['ar'], {type: 'region'});
  const countryLabel = code => {
    const country = catalog.countries.find(c => c.id === code);
    const flag = [...code].map(c => String.fromCodePoint(127397 + c.charCodeAt())).join('');
    return `${flag} ${names.of(code) || code} (${country?.dial || ''})`;
  };
  const normal = value => value.normalize('NFKC').toLocaleLowerCase().replace(/[\u064b-\u065f\u0670]/g, '');

  function enhance(select, placeholder, labelFor = option => option.textContent) {
    const wrapper = make('div', 'search-select');
    select.after(wrapper);
    const trigger = make('button', 'search-select-trigger');
    trigger.type = 'button';
    const summary = make('span');
    const arrow = make('span', '', '⌄');
    arrow.setAttribute('aria-hidden', 'true');
    trigger.append(summary, arrow);
    const panel = make('div', 'search-select-panel');
    panel.hidden = true;
    panel.id = 'partnership-select-' + (++selectSequence);
    trigger.setAttribute('aria-controls', panel.id);
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-haspopup', select.multiple ? 'true' : 'listbox');
    const search = make('input');
    search.type = 'search';
    search.autocomplete = 'off';
    search.placeholder = 'ابحث هنا…';
    search.setAttribute('aria-label', 'البحث في ' + (select.labels[0]?.textContent || placeholder));
    const options = make('div', 'search-select-options');
    options.setAttribute('role', select.multiple ? 'group' : 'listbox');
    options.setAttribute('aria-label', select.labels[0]?.textContent || placeholder);
    const empty = make('p', 'search-select-empty', 'لا توجد خيارات مطابقة أو متاحة.');
    const selectedTags = make('div', 'selected-summary');
    selectedTags.hidden = !select.multiple;
    const error = make('p', 'field-error');
    error.setAttribute('role', 'alert');
    panel.append(search, options, empty);
    wrapper.append(trigger, panel, selectedTags, error);
    select.classList.add('native-enhanced');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    const label = select.labels[0];
    trigger.setAttribute('aria-label', (label?.textContent || placeholder).trim());
    label?.addEventListener('click', event => {event.preventDefault(); trigger.focus();});
    function close() {
      panel.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (openSelect === control) openSelect = null;
    }
    function filter() {
      const term = normal(search.value);
      $$('[data-select-option]', options).forEach(button => button.hidden = !normal(button.textContent).includes(term));
      empty.hidden = $$('[data-select-option]', options).some(b => !b.hidden);
    }
    function update() {
      options.replaceChildren();
      [...select.options].filter(option => option.value && !option.disabled && !option.hidden).forEach(option => {
        const button = make('button', 'search-select-option');
        button.type = 'button';
        button.dataset.selectOption = option.value;
        button.setAttribute(select.multiple ? 'aria-pressed' : 'aria-selected', String(option.selected));
        if (!select.multiple) button.setAttribute('role', 'option');
        button.append(make('span', '', (select.multiple ? (option.selected ? '☑ ' : '☐ ') : '') + labelFor(option)));
        button.addEventListener('click', () => {
          if (select.multiple) option.selected = !option.selected;
          else select.value = option.value;
          error.textContent = '';
          select.dispatchEvent(new Event('change', {bubbles: true}));
          update();
          if (!select.multiple) {close(); trigger.focus();}
          else {const next = $(`[data-select-option="${option.value}"]`, options); next?.focus();}
        });
        options.append(button);
      });
      const selected = [...select.selectedOptions].filter(o => o.value);
      summary.textContent = select.multiple ? (selected.length ? `${selected.length} تخصص محدد` : placeholder) : (selected[0] ? labelFor(selected[0]) : placeholder);
      if (select.id === 'id_phone_country' && selected[0]) {
        const country = catalog.countries.find(c => c.id === selected[0].value);
        summary.textContent = `${selected[0].value} ${country?.dial || ''}`;
      }
      selectedTags.textContent = select.multiple ? selected.map(o => o.textContent).join('، ') : '';
      trigger.disabled = select.disabled;
      filter();
    }
    const control = {update, close, trigger};
    trigger.addEventListener('click', () => {
      if (!panel.hidden) {close(); return;}
      openSelect?.close();
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      openSelect = control;
      search.value = '';
      filter();
      search.focus();
    });
    trigger.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown') {event.preventDefault();if (panel.hidden) trigger.click();else search.focus();}
    });
    search.addEventListener('input', filter);
    wrapper.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !panel.hidden) {event.preventDefault();event.stopPropagation();close();trigger.focus();}
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) && !panel.hidden) {
        const buttons = $$('[data-select-option]', options).filter(button => !button.hidden);
        if (!buttons.length) return;
        if (event.target === search && !['ArrowDown', 'ArrowUp'].includes(event.key)) return;
        event.preventDefault();
        let index = buttons.indexOf(document.activeElement);
        index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length;
        buttons[index].focus();
      }
    });
    select.addEventListener('change', update);
    select.addEventListener('invalid', event => {
      event.preventDefault();
      error.textContent = 'اختر قيمة من القائمة.';
      trigger.focus();
    });
    controls.set(select, control);
    update();
    return control;
  }
  document.addEventListener('click', event => {if (!event.target.closest('.search-select')) openSelect?.close();});
  document.addEventListener('focusin', event => {if (!event.target.closest('.search-select')) openSelect?.close();});
  enhance($('#id_phone_country'), 'اختر الدولة', option => countryLabel(option.value));
  const entitySelect = $('#id_entity');
  const entityType = $('#id_entity_type');
  enhance(entitySelect, 'اختر الكيان');
  function filterEntities() {
    const current = entitySelect.value;
    const matching = catalog.entities.filter(entity => entity.entity_type === entityType.value);
    entitySelect.replaceChildren(new Option('اختر الكيان', ''));
    matching.forEach(entity => entitySelect.add(new Option(entity.name + (entity.is_active ? '' : ' (غير نشط)'), entity.id)));
    entitySelect.value = matching.some(e => String(e.id) === current) ? current : '';
    controls.get(entitySelect).update();
  }
  entityType.addEventListener('change', filterEntities);
  filterEntities();
  const sectorSelect = $('#offering-sector'), specsSelect = $('#offering-specializations'), shapeSelect = $('#offering-shape');
  catalog.sectors.forEach(sector => sectorSelect.add(new Option(sector.name + (sector.is_active ? '' : ' (غير نشط)'), sector.id)));
  catalog.shapes.forEach(shape => shapeSelect.add(new Option(shape.name + (shape.is_active ? '' : ' (غير نشط)'), shape.id)));
  enhance(sectorSelect, 'اختر القطاع');
  enhance(specsSelect, 'اختر التخصص');
  enhance(shapeSelect, 'اختر شكل الرعاية');
  function filterSpecs(selected = []) {
    specsSelect.replaceChildren(new Option('اختر التخصص', ''));
    catalog.specializations.filter(spec => String(spec.sector_id) === sectorSelect.value).forEach(spec => {
      const option = new Option(spec.name + (spec.is_active ? '' : ' (غير نشط)'), spec.id);
      option.selected = selected.length === 1 && selected.includes(spec.id);
      specsSelect.add(option);
    });
    specsSelect.value = selected.length === 1 ? String(selected[0]) : '';
    controls.get(specsSelect).update();
  }
  sectorSelect.addEventListener('change', () => filterSpecs());
  shapeSelect.addEventListener('change', () => {$('#offering-description').value = catalog.shapes.find(s => String(s.id) === shapeSelect.value)?.description || '';});
  const lineDialog = $('#offering-editor'), lineForm = $('[data-offering-form]'), confirmation = $('#offering-confirmation');
  let editingIndex = null, confirmAction = null;
  const lineError = $('[data-offering-error]');
  function ask(title, text, callback) {
    $('#offering-confirm-title').textContent = title;
    $('[data-line-confirm-description]').textContent = text;
    confirmAction = callback;
    show(confirmation);
  }
  $('[data-confirm-offering]').addEventListener('click', () => {
    const action = confirmAction;
    confirmAction = null;
    confirmation.close();
    action?.();
  });
  confirmation.addEventListener('close', () => {confirmAction = null;});
  function openEditor(index = null) {
    editingIndex = index;
    lineForm.reset();
    lineError.textContent = '';
    const row = index === null ? null : rows[index];
    $('#offering-title').textContent = row ? 'تعديل قطاع وشكل رعاية' : 'إضافة قطاع وشكل رعاية';
    $('button[type=submit]', lineForm).textContent = row ? 'مراجعة التعديل' : 'إضافة البند';
    sectorSelect.value = row ? String(row.sector) : '';
    shapeSelect.value = row ? String(row.shape) : '';
    controls.get(sectorSelect).update();
    controls.get(shapeSelect).update();
    filterSpecs(row?.specializations || []);
    if (row && row.specializations.length > 1) {
      lineError.textContent = 'هذا بند سابق يحتوي على عدة تخصصات. اختر تخصصًا واحدًا لحفظ تعديله؛ الإلغاء يحتفظ بجميع بياناته السابقة.';
    }
    $('#offering-description').value = catalog.shapes.find(s => String(s.id) === shapeSelect.value)?.description || '';
    $(`input[name=offering_active][value="${row && !row.is_active ? '0' : '1'}"]`, lineForm).checked = true;
    show(lineDialog);
    controls.get(sectorSelect).trigger.focus();
  }
  $('[data-add-offering]').addEventListener('click', () => openEditor());
  lineForm.addEventListener('submit', event => {
    event.preventDefault();
    if (!lineForm.reportValidity()) return;
    const row = {sector: Number(sectorSelect.value), specializations: [Number(specsSelect.value)], shape: Number(shapeSelect.value), is_active: $('input[name=offering_active]:checked', lineForm).value === '1'};
    if (rows.some((old, index) => index !== editingIndex && old.sector === row.sector && old.shape === row.shape && old.specializations.some(id => row.specializations.includes(id)))) {
      lineError.textContent = 'هذا التخصص وشكل الرعاية موجودان بالفعل داخل القطاع نفسه.';
      return;
    }
    if (editingIndex === null && rows.length >= 100) {lineError.textContent = 'الحد الأقصى 100 بند.';return;}
    const index = editingIndex;
    const sector = catalog.sectors.find(s => s.id === row.sector)?.name || '';
    ask(index === null ? 'تأكيد إضافة البند' : 'تأكيد تعديل البند', `هل تريد ${index === null ? 'إضافة' : 'تعديل'} بند الشراكة للقطاع «${sector}»؟`, () => {
      if (index === null) rows.push(row);else rows[index] = row;
      renderRows();lineDialog.close();
    });
  });
  function actionButton(text, action, cls = '') {
    const button = make('button', 'row-action ' + cls, text);
    button.type = 'button';
    button.addEventListener('click', action);
    return button;
  }
  function renderRows() {
    const body = $('[data-offerings-table]');
    body.replaceChildren();
    rows.forEach((row, index) => {
      const tr = make('tr');
      tr.dataset.offeringRow = String(index);
      const sector = catalog.sectors.find(s => s.id === row.sector)?.name || 'قطاع غير متاح';
      tr.append(make('td', '', sector));
      const specializations = make('td'), tags = make('div', 'tags');
      row.specializations.forEach(id => tags.append(make('bdi', 'tag', catalog.specializations.find(s => s.id === id)?.name || 'تخصص غير متاح')));
      specializations.append(tags);tr.append(specializations);
      const shapeCell = make('td');
      const shape = catalog.shapes.find(s => s.id === row.shape);
      shapeCell.append(make('bdi', '', shape?.name || 'شكل غير متاح'), make('small', 'shape-description', shape?.description || 'لا يوجد وصف'));
      tr.append(shapeCell);
      const statusCell = make('td');
      const status = make('button', 'record-status ' + (row.is_active ? 'is-enabled' : 'is-disabled'), row.is_active ? 'نشط' : 'غير نشط');
      status.type = 'button';status.setAttribute('aria-label', 'تغيير حالة البند ' + (index + 1));
      status.addEventListener('click', () => ask('تأكيد تغيير حالة البند', `هل تريد ${row.is_active ? 'إيقاف' : 'تفعيل'} بند «${sector}»؟`, () => {rows[index].is_active = !row.is_active;renderRows();}));
      statusCell.append(status);tr.append(statusCell);
      const actionsCell = make('td'), actions = make('div', 'row-actions');
      actions.append(actionButton('تعديل', () => openEditor(index)), actionButton('حذف', () => ask('تأكيد حذف البند', `هل تريد إزالة بند «${sector}» من هذه الجهة؟`, () => {rows.splice(index, 1);renderRows();}), 'delete-action'));
      actionsCell.append(actions);tr.append(actionsCell);body.append(tr);
    });
    draftField.value = JSON.stringify(rows);
    $('[data-offerings-empty]').hidden = rows.length > 0;
    if (rows.length) $('[data-offerings-error]').textContent = '';
  }
  recordForm.addEventListener('submit', event => {
    draftField.value = JSON.stringify(rows);
    if (!rows.length) {
      event.preventDefault();
      $('[data-offerings-error]').textContent = 'أضف قطاعًا واحدًا على الأقل قبل حفظ الجهة.';
      $('[data-add-offering]').focus();
    }
  });
  renderRows();
})();
