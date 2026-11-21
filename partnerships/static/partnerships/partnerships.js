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
    button.textContent = 'جار التنفيذ…';
  }));
  const highlightedRow = $('[data-highlighted-row]');
  if (highlightedRow) {
    highlightedRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  const cpDialog = $('#clauses-progress-dialog');
  if (cpDialog) {
    const cpForm = $('[data-cp-form]', cpDialog);
    const cpPartner = $('[data-cp-partner]', cpDialog);
    const cpOverall = $('[data-cp-overall]', cpDialog);
    const cpUpdatedWrap = $('[data-cp-updated-wrap]', cpDialog);
    const cpUpdatedAt = $('[data-cp-updated-at]', cpDialog);
    const cpUpdatedBy = $('[data-cp-updated-by]', cpDialog);
    const cpList = $('[data-cp-list]', cpDialog);
    const cpTeamsList = $('[data-cp-teams-list]', cpDialog);
    const cpAddTeamBtn = $('[data-cp-add-team]', cpDialog);
    const cpError = $('[data-cp-error]', cpDialog);
    const cpToast = $('[data-cp-toast]', cpDialog);
    const cpToastText = $('[data-cp-toast-text]', cpDialog);
    const cpSaveBtn = $('[data-cp-save]', cpDialog);
    let cpUrl = '';
    let cpToastTimer = null;

    function hideCpToast() {
      if (cpToastTimer) {
        clearTimeout(cpToastTimer);
        cpToastTimer = null;
      }
      cpToast.hidden = true;
    }

    function showCpToast(message) {
      hideCpToast();
      cpToastText.textContent = message;
      cpToast.hidden = false;
      cpDialog.scrollTop = 0;
      cpToastTimer = setTimeout(() => {
        cpToast.hidden = true;
        cpToastTimer = null;
      }, 5500);
    }

    function makeTeamRow(member = {}) {
      const row = make('div', 'mk-cp-team-row');
      row.dataset.cpTeamRow = '1';

      const side = document.createElement('select');
      side.dataset.cpField = 'side';
      side.setAttribute('aria-label', 'الطرف');
      side.add(new Option('المؤسسة', 'institution'));
      side.add(new Option('الجهة', 'partner'));
      side.value = member.side === 'partner' ? 'partner' : 'institution';

      const role = document.createElement('select');
      role.dataset.cpField = 'role';
      role.setAttribute('aria-label', 'الصفة');
      role.add(new Option('ممثل', 'representative'));
      role.add(new Option('رئيس', 'lead'));
      role.add(new Option('ضابط اتصال', 'contact'));
      role.value = ['representative', 'lead', 'contact'].includes(member.role) ? member.role : 'contact';

      const name = document.createElement('input');
      name.type = 'text';
      name.dataset.cpField = 'name';
      name.placeholder = 'الاسم *';
      name.value = member.name || '';
      name.maxLength = 160;

      const phone = document.createElement('input');
      phone.type = 'text';
      phone.dataset.cpField = 'phone';
      phone.placeholder = 'رقم الجوال';
      phone.dir = 'ltr';
      phone.value = member.phone || '';
      phone.maxLength = 32;

      const email = document.createElement('input');
      email.type = 'email';
      email.dataset.cpField = 'email';
      email.placeholder = 'البريد الإلكتروني';
      email.dir = 'ltr';
      email.value = member.email || '';
      email.maxLength = 254;

      const org = document.createElement('input');
      org.type = 'text';
      org.dataset.cpField = 'organization';
      org.placeholder = 'الإدارة أو الجهة';
      org.value = member.organization || '';
      org.maxLength = 160;

      const rm = make('button', 'mk-cp-team-remove', 'حذف');
      rm.type = 'button';
      rm.addEventListener('click', () => row.remove());

      row.append(side, role, name, phone, email, org, rm);
      return row;
    }

    if (cpAddTeamBtn) {
      cpAddTeamBtn.addEventListener('click', () => {
        const empty = $('.mk-cp-empty', cpTeamsList);
        if (empty) empty.remove();
        cpTeamsList.append(makeTeamRow());
      });
    }

    function updateTableFollowupCell(data) {
      if (!data.partnership_id || !data.followup_updated_at_display) return;
      const cell = $(`[data-followup-cell="${data.partnership_id}"]`);
      if (!cell) return;
      cell.replaceChildren();
      const bdi = make('bdi', '', data.followup_updated_at_display);
      bdi.dir = 'ltr';
      cell.append(bdi);
      if (data.followup_updated_by_name) {
        cell.append(make('small', '', data.followup_updated_by_name));
      }
    }

    function renderCpClauses(data) {
      cpPartner.textContent = data.agreement_number && data.agreement_number !== '—'
        ? `${data.partnership_name} (${data.agreement_number})`
        : data.partnership_name;
      function paintOverallBadge(valText) {
        const pill = cpDialog.querySelector('[data-cp-overall-pill]');
        if (!pill) return;
        const num = parseFloat(String(valText || '0').replace(/[^0-9.]/g, '')) || 0;
        pill.classList.toggle('is-high', num >= 50);
        pill.classList.toggle('is-low', num < 50);
      }
      cpOverall.textContent = data.overall_display || '—';
      paintOverallBadge(cpOverall.textContent);
      if (data.followup_updated_at_display) {
        cpUpdatedAt.textContent = data.followup_updated_at_display;
        cpUpdatedBy.textContent = data.followup_updated_by_name || '';
        cpUpdatedWrap.hidden = false;
      } else {
        cpUpdatedWrap.hidden = true;
      }

      cpList.replaceChildren();
      const items = Array.isArray(data.clauses) ? data.clauses : [];
      const countEl = cpDialog.querySelector('[data-cp-clauses-count]');
      if (countEl) countEl.textContent = `${items.length} بند`;
      if (!items.length) {
        cpList.append(make('div', 'mk-cp-empty', 'لا توجد بنود اتفاقية مسندة لهذه الشراكة بعد.'));
      } else {
        items.forEach((item, idx) => {
          const row = make('div', 'mk-cp-row');
          row.dataset.cpClauseCard = String(item.id);
          const info = make('div', 'mk-cp-info');
          const head = make('div', 'mk-cp-clause-head');
          head.append(
            make('span', 'mk-cp-num', String(idx + 1)),
            make('span', 'mk-cp-clause-name', item.name)
          );
          info.append(
            head,
            make('span', 'mk-cp-resp', `المسؤولية: ${item.responsibility_label}`)
          );
          const inputWrap = make('div', 'mk-cp-input-wrap');
          const input = make('input', 'mk-cp-input');
          input.type = 'number';
          input.min = '0';
          input.max = '100';
          input.step = '1';
          input.required = true;
          input.value = String(item.progress ?? 0);
          input.dataset.cpAssignmentId = String(item.id);
          input.setAttribute('aria-label', `نسبة إنجاز ${item.name}`);
          inputWrap.append(input, make('span', 'mk-cp-pct', '%'));

          const bar = make('progress', 'mk-cp-progress');
          bar.max = 100;
          bar.value = Math.max(0, Math.min(100, Number(item.progress) || 0));
          input.addEventListener('input', () => {
            bar.value = Math.max(0, Math.min(100, Number(input.value) || 0));
            const allInputs = [...cpList.querySelectorAll('input[data-cp-assignment-id]')];
            if (allInputs.length) {
              const avg = allInputs.reduce((s, el) => s + Math.max(0, Math.min(100, Number(el.value) || 0)), 0) / allInputs.length;
              const formatted = (Number.isInteger(avg) ? String(avg) : avg.toFixed(2).replace(/\.00$/, '')) + '%';
              cpOverall.textContent = formatted;
              paintOverallBadge(formatted);
            }
          });

          const extras = make('div', 'mk-cp-extras');
          const notesWrap = make('div');
          const notesLabel = make('label', 'mk-cp-notes-label', 'ملاحظات البند');
          const notes = make('textarea', 'mk-cp-notes');
          notes.rows = 2;
          notes.maxLength = 2000;
          notes.placeholder = 'أضف ملاحظات المتابعة الخاصة بهذا البند…';
          notes.value = item.notes || '';
          notes.dataset.cpNotesFor = String(item.id);
          notesWrap.append(notesLabel, notes);

          const evWrap = make('div');
          const evLabel = make('label', 'mk-cp-ev-label', 'الشواهد والمرفقات (PDF / PNG / JPG)');
          evWrap.append(evLabel);
          const evList = make('div', 'mk-cp-ev-files');
          (item.evidences || []).forEach(ev => {
            const link = make('a', 'mk-cp-ev-chip', `${ev.name} (${ev.uploaded_at})`);
            link.href = ev.download_url;
            link.target = '_blank';
            link.rel = 'noopener';
            evList.append(link);
          });
          if (evList.childNodes.length) evWrap.append(evList);
          const uploadWrap = make('div', 'mk-cp-upload-wrap');
          const uploadBtn = make('label', 'mk-cp-upload-btn');
          uploadBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg><span>اختيار شواهد ومرفقات</span>';
          const fileInput = make('input', 'mk-cp-ev-input');
          fileInput.type = 'file';
          fileInput.multiple = true;
          fileInput.accept = '.pdf,.png,.jpg,.jpeg';
          fileInput.dataset.cpEvidenceFor = String(item.id);
          const uploadStatus = make('span', 'mk-cp-upload-status', 'لم يتم اختيار ملفات جديدة');
          fileInput.addEventListener('change', () => {
            const names = [...(fileInput.files || [])].map(f => f.name);
            uploadStatus.textContent = names.length ? `تم اختيار (${names.length}): ${names.join('، ')}` : 'لم يتم اختيار ملفات جديدة';
          });
          uploadBtn.append(fileInput);
          uploadWrap.append(uploadBtn, uploadStatus);
          evWrap.append(uploadWrap);

          extras.append(notesWrap, evWrap);
          row.append(info, inputWrap, bar, extras);
          cpList.append(row);
        });
      }

      cpTeamsList.replaceChildren();
      const teams = Array.isArray(data.teams) ? data.teams : [];
      if (!teams.length) {
        cpTeamsList.append(make('div', 'mk-cp-empty', 'لا يوجد أعضاء فرق عمل أو ضباط اتصال مسجلون بعد. اضغط على الزر أدناه للإضافة.'));
      } else {
        teams.forEach(m => cpTeamsList.append(makeTeamRow(m)));
      }
      cpSaveBtn.disabled = false;
    }

    cpDialog.addEventListener('close', hideCpToast);

    $$('[data-clauses-progress-trigger]').forEach(btn => {
      btn.addEventListener('click', async event => {
        event.stopPropagation();
        cpUrl = btn.dataset.progressUrl || '';
        if (!cpUrl) return;
        hideCpToast();
        cpError.textContent = '';
        cpPartner.textContent = 'جارٍ تحميل بطاقة المتابعة…';
        cpOverall.textContent = '—';
        cpUpdatedWrap.hidden = true;
        cpList.replaceChildren(make('div', 'mk-cp-empty', 'جارٍ تحميل بنود الشراكة…'));
        cpTeamsList.replaceChildren();
        cpSaveBtn.disabled = true;
        show(cpDialog);
        try {
          const res = await fetch(cpUrl, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}});
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'تعذّر تحميل بطاقة المتابعة.');
          renderCpClauses(data);
        } catch (err) {
          cpError.textContent = err.message || 'تعذّر تحميل بطاقة المتابعة.';
          cpList.replaceChildren();
        }
      });
    });

    cpForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (!cpUrl || !cpForm.reportValidity()) return;
      cpError.textContent = '';

      const items = $$('[data-cp-assignment-id]', cpList).map(inp => {
        const aid = Number(inp.dataset.cpAssignmentId);
        const notesEl = $(`[data-cp-notes-for="${aid}"]`, cpList);
        return {
          id: aid,
          progress: Number(inp.value),
          notes: notesEl ? notesEl.value.trim() : '',
        };
      });

      const teams = $$('[data-cp-team-row]', cpTeamsList).map(row => ({
        side: $('[data-cp-field="side"]', row).value,
        role: $('[data-cp-field="role"]', row).value,
        name: $('[data-cp-field="name"]', row).value.trim(),
        phone: $('[data-cp-field="phone"]', row).value.trim(),
        email: $('[data-cp-field="email"]', row).value.trim(),
        organization: $('[data-cp-field="organization"]', row).value.trim(),
      })).filter(m => m.name || m.phone || m.email || m.organization);

      const formData = new FormData();
      formData.append('items_json', JSON.stringify(items));
      formData.append('teams_json', JSON.stringify(teams));
      $$('[data-cp-evidence-for]', cpList).forEach(fileInput => {
        const aid = fileInput.dataset.cpEvidenceFor;
        [...(fileInput.files || [])].forEach(file => {
          formData.append(`evidence_${aid}`, file);
        });
      });

      const csrf = $('input[name=csrfmiddlewaretoken]', cpForm)?.value || '';
      cpSaveBtn.disabled = true;
      cpSaveBtn.textContent = 'جارٍ الحفظ…';
      try {
        const res = await fetch(cpUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'X-CSRFToken': csrf,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'تعذّر حفظ بطاقة المتابعة.');
        renderCpClauses(data);
        updateTableFollowupCell(data);
        showCpToast(data.message || 'تم حفظ بطاقة المتابعة بنجاح. يمكنك متابعة التعديل أو إغلاق النافذة.');
      } catch (err) {
        cpError.textContent = err.message || 'تعذّر حفظ بطاقة المتابعة.';
      } finally {
        cpSaveBtn.disabled = false;
        cpSaveBtn.textContent = 'حفظ بطاقة المتابعة';
      }
    });
  }

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
    window.MakkenDropdowns?.unwrap?.(select);
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
  const offeringToast = $('[data-offering-toast]');
  const offeringToastText = $('[data-offering-toast-text]');
  let offeringToastTimer = null;
  function hideOfferingToast() {
    if (offeringToastTimer) {
      clearTimeout(offeringToastTimer);
      offeringToastTimer = null;
    }
    if (offeringToast) offeringToast.hidden = true;
  }
  function showOfferingToast(message) {
    if (!offeringToast || !offeringToastText) return;
    hideOfferingToast();
    offeringToastText.textContent = message;
    offeringToast.hidden = false;
    lineDialog.scrollTop = 0;
    offeringToastTimer = setTimeout(() => {
      offeringToast.hidden = true;
      offeringToastTimer = null;
    }, 5000);
  }
  function resetOfferingFields(row = null) {
    lineForm.reset();
    lineError.textContent = '';
    sectorSelect.value = row ? String(row.sector) : '';
    shapeSelect.value = row ? String(row.shape) : '';
    controls.get(sectorSelect).update();
    controls.get(shapeSelect).update();
    filterSpecs(row?.specializations || []);
    $('#offering-description').value = catalog.shapes.find(s => String(s.id) === shapeSelect.value)?.description || '';
    const activeRadio = $(`input[name=offering_active][value="${row && !row.is_active ? '0' : '1'}"]`, lineForm);
    if (activeRadio) activeRadio.checked = true;
  }
  lineDialog.addEventListener('close', hideOfferingToast);
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
    hideOfferingToast();
    const row = index === null ? null : rows[index];
    $('#offering-title').textContent = row ? 'تعديل قطاع وشكل رعاية' : 'إضافة قطاع وشكل رعاية';
    $('button[type=submit]', lineForm).textContent = row ? 'مراجعة التعديل' : 'إضافة البند';
    resetOfferingFields(row);
    if (row && row.specializations.length > 1) {
      lineError.textContent = 'هذا بند سابق يحتوي على عدة تخصصات. اختر تخصصًا واحدًا لحفظ تعديله؛ الإلغاء يحتفظ بجميع بياناته السابقة.';
    }
    show(lineDialog);
    controls.get(sectorSelect).trigger.focus();
  }
  $('[data-add-offering]').addEventListener('click', () => openEditor());
  lineForm.addEventListener('submit', event => {
    event.preventDefault();
    if (!lineForm.reportValidity()) return;
    const activeInput = $('input[name=offering_active]:checked', lineForm);
    const row = {sector: Number(sectorSelect.value), specializations: [Number(specsSelect.value)], shape: Number(shapeSelect.value), is_active: activeInput ? activeInput.value === '1' : true};
    if (rows.some((old, index) => index !== editingIndex && old.sector === row.sector && old.shape === row.shape && old.specializations.some(id => row.specializations.includes(id)))) {
      lineError.textContent = 'هذا التخصص وشكل الرعاية موجودان بالفعل داخل القطاع نفسه.';
      return;
    }
    if (editingIndex === null && rows.length >= 100) {lineError.textContent = 'الحد الأقصى 100 بند.';return;}
    const index = editingIndex;
    const sector = catalog.sectors.find(s => s.id === row.sector)?.name || '';
    const spec = catalog.specializations.find(s => s.id === row.specializations[0])?.name || '';
    ask(index === null ? 'تأكيد إضافة البند' : 'تأكيد تعديل البند', `هل تريد ${index === null ? 'إضافة' : 'تعديل'} بند الشراكة للقطاع «${sector}»؟`, () => {
      if (index === null) {
        rows.push(row);
        renderRows();
        resetOfferingFields(null);
        showOfferingToast(`تمت إضافة بند الشراكة للقطاع «${sector}» والتخصص «${spec}» بنجاح. يمكنك إضافة بند آخر أو إغلاق النافذة.`);
        controls.get(sectorSelect).trigger.focus();
      } else {
        rows[index] = row;
        renderRows();
        lineDialog.close();
      }
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
  recordForm.addEventListener('invalid', event => {
    const acc = event.target.closest('details.mk-accordion');
    if (acc && !acc.open) acc.open = true;
  }, true);
  recordForm.addEventListener('submit', event => {
    draftField.value = JSON.stringify(rows);
    if (!rows.length) {
      event.preventDefault();
      const acc = $('[data-add-offering]')?.closest('details.mk-accordion');
      if (acc && !acc.open) acc.open = true;
      $('[data-offerings-error]').textContent = 'أضف قطاعًا واحدًا على الأقل قبل الحفظ.';
      $('[data-add-offering]').focus();
    }
  });
  
  // Inline popup editor for existing work assignments inside Section 04
  const workDialog = $('#partnership-work-dialog');
  if (workDialog) {
    const weForm = $('[data-work-edit-form]', workDialog);
    const weTitle = $('#we-title', workDialog);
    const weAssignees = $('[data-we-assignees]', workDialog);
    const weManager = $('#we-manager', workDialog);
    const weStatus = $('#we-status', workDialog);
    const weProgress = $('#we-progress', workDialog);
    const weDue = $('#we-due', workDialog);
    const weInstructions = $('#we-instructions', workDialog);
    const weError = $('[data-we-error]', workDialog);
    const weSubmit = $('[data-we-submit]', workDialog);
    let activeWorkUrl = '';
    let activeWorkRowId = '';

    weStatus?.addEventListener('change', () => {
      if (weStatus.value === 'complete') {
        weProgress.value = '100';
      } else if (Number(weProgress.value) >= 100) {
        weProgress.value = weStatus.value === 'new' ? '0' : '90';
      }
    });
    weProgress?.addEventListener('change', () => {
      if (Number(weProgress.value) >= 100) {
        weProgress.value = '100';
        weStatus.value = 'complete';
      } else if (weStatus.value === 'complete') {
        weStatus.value = 'running';
      }
    });

    $$('[data-edit-work-url]').forEach(btn => {
      btn.addEventListener('click', async () => {
        activeWorkUrl = btn.dataset.editWorkUrl;
        activeWorkRowId = btn.dataset.editWorkRow;
        weError.textContent = '';
        weSubmit.disabled = true;
        weSubmit.textContent = 'جار التحميل…';
        show(workDialog);
        try {
          const res = await fetch(activeWorkUrl, {headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}});
          const data = await res.json();
          if (!res.ok || !data.ok) throw new Error(data.error || 'تعذّر تحميل بيانات المهمة.');
          const w = data.work;
          weTitle.value = w.title || '';
          weInstructions.value = w.instructions || '';
          weDue.value = w.due_on || '';
          weProgress.value = String(w.progress ?? 0);

          weStatus.replaceChildren();
          (w.status_choices || []).forEach(ch => {
            const opt = new Option(ch.label, ch.value, false, ch.value === w.status);
            weStatus.append(opt);
          });

          weManager.replaceChildren();
          weManager.append(new Option('اختر المشرف / المدير', ''));
          (w.users || []).forEach(u => {
            const opt = new Option(u.name, String(u.id), false, u.id === w.manager_id);
            weManager.append(opt);
          });

          weAssignees.replaceChildren();
          const selectedSet = new Set(w.assignee_ids || []);
          (w.users || []).forEach(u => {
            const lbl = make('label', 'work-assignee-check');
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.name = 'we_assignee';
            cb.value = String(u.id);
            cb.checked = selectedSet.has(u.id);
            const sp = document.createElement('span');
            sp.textContent = u.name;
            lbl.append(cb, sp);
            weAssignees.append(lbl);
          });
          weSubmit.disabled = false;
          weSubmit.textContent = 'حفظ التعديلات';
        } catch (err) {
          weError.textContent = err.message || 'تعذّر تحميل بيانات المهمة.';
          weSubmit.disabled = false;
          weSubmit.textContent = 'حفظ التعديلات';
        }
      });
    });

    weForm?.addEventListener('submit', async event => {
      event.preventDefault();
      weError.textContent = '';
      if (!weForm.reportValidity()) return;
      const assigneeIds = $$('input[name="we_assignee"]:checked', weAssignees).map(cb => Number(cb.value));
      if (!assigneeIds.length) {
        weError.textContent = 'اختر موظفًا واحدًا على الأقل لإسناد المهمة.';
        return;
      }
      const csrf = $('input[name="csrfmiddlewaretoken"]')?.value || '';
      weSubmit.disabled = true;
      weSubmit.textContent = 'جار الحفظ…';
      try {
        const res = await fetch(activeWorkUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrf,
          },
          body: JSON.stringify({
            title: weTitle.value.trim(),
            assignee_ids: assigneeIds,
            manager_id: Number(weManager.value),
            status: weStatus.value,
            progress: Number(weProgress.value || 0),
            due_on: weDue.value || '',
            instructions: weInstructions.value || '',
          }),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || 'تعذّر حفظ التعديلات.');
        const w = data.work;
        const row = $(`tr[data-work-row="${activeWorkRowId}"]`);
        if (row) {
          const titleEl = $('[data-work-title]', row);
          if (titleEl) titleEl.textContent = w.title;
          const assEl = $('[data-work-assignees]', row);
          if (assEl) {
            assEl.replaceChildren();
            (w.assignees_names || []).forEach(n => {
              const badge = make('span', 'subtle-badge', n);
              assEl.append(badge, ' ');
            });
          }
          const mgrEl = $('[data-work-manager]', row);
          if (mgrEl) mgrEl.textContent = w.manager_name;
          const stEl = $('[data-work-status]', row);
          if (stEl) stEl.textContent = `${w.status_display} (${w.progress}%)`;
        }
        workDialog.close();
      } catch (err) {
        weError.textContent = err.message || 'تعذّر حفظ التعديلات.';
      } finally {
        weSubmit.disabled = false;
        weSubmit.textContent = 'حفظ التعديلات';
      }
    });
  }

  renderRows();
})();
