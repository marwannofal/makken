(() => {
  'use strict';

  const catalogEl = document.getElementById('pub-catalog-data');
  const form = document.querySelector('[data-public-register-form]');
  if (!catalogEl || !form) return;

  let catalog = { entities: [], sectors: [], specializations: [], shapes: [] };
  try {
    catalog = JSON.parse(catalogEl.textContent || '{}');
  } catch {
    return;
  }

  const entitiesById = new Map((catalog.entities || []).map((e) => [String(e.id), e]));
  const sectorsById = new Map((catalog.sectors || []).map((s) => [String(s.id), s]));
  const specsById = new Map((catalog.specializations || []).map((sp) => [String(sp.id), sp]));
  const shapesById = new Map((catalog.shapes || []).map((sh) => [String(sh.id), sh]));

  // 1. Cascading نوع الكيان -> الكيان
  const typeSelect = form.querySelector('#id_entity_type');
  const entitySelect = form.querySelector('#id_entity');

  function populateEntities(selectedType, keepValue) {
    if (!entitySelect) return;
    const currentVal = keepValue !== undefined ? String(keepValue || '') : String(entitySelect.value || '');
    const matching = (catalog.entities || []).filter((e) => !selectedType || e.entity_type === selectedType);
    entitySelect.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = selectedType ? 'اختر الكيان' : 'اختر نوع الكيان أولًا';
    entitySelect.appendChild(placeholder);
    for (const ent of matching) {
      const opt = document.createElement('option');
      opt.value = String(ent.id);
      opt.textContent = ent.name;
      if (String(ent.id) === currentVal) opt.selected = true;
      entitySelect.appendChild(opt);
    }
  }

  if (typeSelect && entitySelect) {
    // Pre-sync entity_type if entity is preselected (e.g. after POST validation error)
    if (!typeSelect.value && entitySelect.value && entitiesById.has(String(entitySelect.value))) {
      typeSelect.value = entitiesById.get(String(entitySelect.value)).entity_type || '';
    }
    populateEntities(typeSelect.value, entitySelect.value);
    typeSelect.addEventListener('change', () => {
      populateEntities(typeSelect.value, '');
    });
  }

  // 2. Multi-row القطاعات والتخصصات وأشكال الرعاية
  const hiddenInput = form.querySelector('#id_offerings_json');
  const listEl = form.querySelector('[data-pub-offerings-list]');
  const addBtn = form.querySelector('[data-pub-add-offering]');
  const dialog = document.getElementById('pub-offering-dialog');
  const sectorSel = dialog ? dialog.querySelector('[data-pub-off-sector]') : null;
  const specsBox = dialog ? dialog.querySelector('[data-pub-off-specs]') : null;
  const shapeSel = dialog ? dialog.querySelector('[data-pub-off-shape]') : null;
  const errEl = dialog ? dialog.querySelector('[data-pub-off-error]') : null;
  const toastEl = dialog ? dialog.querySelector('[data-pub-offering-toast]') : null;
  const saveBtn = dialog ? dialog.querySelector('[data-pub-save-offering]') : null;

  let rows = [];
  try {
    const initial = JSON.parse((hiddenInput && hiddenInput.value) || '[]');
    if (Array.isArray(initial)) rows = initial;
  } catch {
    rows = [];
  }

  function syncHidden() {
    if (hiddenInput) hiddenInput.value = JSON.stringify(rows);
  }

  function renderRows() {
    if (!listEl) return;
    listEl.innerHTML = '';
    if (!rows.length) {
      const p = document.createElement('p');
      p.className = 'pub-offerings-empty';
      p.textContent = 'لم تتم إضافة قطاعات وأشكال رعاية بعد.';
      listEl.appendChild(p);
      syncHidden();
      return;
    }
    rows.forEach((row, idx) => {
      const card = document.createElement('div');
      card.className = 'pub-offering-row';
      const sec = sectorsById.get(String(row.sector));
      const sh = shapesById.get(String(row.shape));
      const specNames = (row.specializations || [])
        .map((sid) => specsById.get(String(sid)))
        .filter(Boolean)
        .map((sp) => sp.name);

      const info = document.createElement('div');
      info.className = 'pub-offering-info';
      const title = document.createElement('strong');
      title.textContent = `${sec ? sec.name : 'قطاع'} · ${sh ? sh.name : 'شكل رعاية'}`;
      info.appendChild(title);
      if (specNames.length) {
        const sub = document.createElement('span');
        sub.className = 'pub-offering-specs';
        sub.textContent = `التخصصات: ${specNames.join('، ')}`;
        info.appendChild(sub);
      }

      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'pub-offering-remove';
      rm.textContent = 'حذف';
      rm.addEventListener('click', () => {
        rows.splice(idx, 1);
        renderRows();
      });

      card.append(info, rm);
      listEl.appendChild(card);
    });
    syncHidden();
  }

  function populateDialogCatalog() {
    if (!sectorSel || !shapeSel) return;
    sectorSel.innerHTML = '<option value="">اختر القطاع</option>';
    for (const s of catalog.sectors || []) {
      const opt = document.createElement('option');
      opt.value = String(s.id);
      opt.textContent = s.name;
      sectorSel.appendChild(opt);
    }
    shapeSel.innerHTML = '<option value="">اختر شكل الرعاية</option>';
    for (const sh of catalog.shapes || []) {
      const opt = document.createElement('option');
      opt.value = String(sh.id);
      opt.textContent = sh.name;
      shapeSel.appendChild(opt);
    }
  }

  function renderSpecsForSector(sectorId) {
    if (!specsBox) return;
    specsBox.innerHTML = '';
    if (!sectorId) {
      specsBox.innerHTML = '<span class="pub-hint">اختر القطاع أولًا لعرض التخصصات المرتبطة به.</span>';
      return;
    }
    const matching = (catalog.specializations || []).filter((sp) => String(sp.sector_id) === String(sectorId));
    if (!matching.length) {
      specsBox.innerHTML = '<span class="pub-hint">لا توجد تخصصات مضافة لهذا القطاع.</span>';
      return;
    }
    for (const sp of matching) {
      const lbl = document.createElement('label');
      lbl.className = 'pub-region-item';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = String(sp.id);
      const span = document.createElement('span');
      span.textContent = sp.name;
      lbl.append(cb, span);
      specsBox.appendChild(lbl);
    }
  }

  if (dialog && addBtn && saveBtn && sectorSel && shapeSel) {
    populateDialogCatalog();
    sectorSel.addEventListener('change', () => renderSpecsForSector(sectorSel.value));

    addBtn.addEventListener('click', () => {
      sectorSel.value = '';
      shapeSel.value = '';
      renderSpecsForSector('');
      if (errEl) { errEl.textContent = ''; errEl.hidden = true; }
      if (toastEl) { toastEl.textContent = ''; toastEl.hidden = true; }
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    });

    dialog.querySelectorAll('[data-pub-close-dialog]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (typeof dialog.close === 'function') dialog.close();
        else dialog.removeAttribute('open');
      });
    });

    saveBtn.addEventListener('click', () => {
      const secId = Number(sectorSel.value);
      const shapeId = Number(shapeSel.value);
      if (!secId || !shapeId) {
        if (errEl) {
          errEl.textContent = 'اختر القطاع وشكل الرعاية قبل الإضافة.';
          errEl.hidden = false;
        }
        return;
      }
      if (rows.some((r) => Number(r.sector) === secId && Number(r.shape) === shapeId)) {
        if (errEl) {
          errEl.textContent = 'تمت إضافة هذا القطاع وشكل الرعاية مسبقًا.';
          errEl.hidden = false;
        }
        return;
      }
      const specIds = Array.from(specsBox.querySelectorAll('input[type="checkbox"]:checked')).map((el) => Number(el.value));
      rows.push({ sector: secId, specializations: specIds, shape: shapeId });
      renderRows();
      // Reset fields and stay open with formal Arabic toast
      sectorSel.value = '';
      shapeSel.value = '';
      renderSpecsForSector('');
      if (errEl) { errEl.textContent = ''; errEl.hidden = true; }
      if (toastEl) {
        toastEl.textContent = 'تمت إضافة القطاع وشكل الرعاية بنجاح. يمكنك إضافة عنصر آخر أو إغلاق النافذة.';
        toastEl.hidden = false;
      }
    });
  }

  const attInput = document.getElementById('pub-attachments-input');
  const attStatus = form.querySelector('[data-pub-attachments-status]');
  if (attInput && attStatus) {
    attInput.addEventListener('change', () => {
      const names = Array.from(attInput.files || []).map((f) => f.name);
      attStatus.textContent = names.length
        ? `تم اختيار (${names.length}): ${names.join('، ')}`
        : 'لم يتم اختيار ملفات بعد';
    });
  }

  renderRows();
})();
