/* Self-Service BI Studio Controller for المؤشرات والتحليلات المرنة (CSP-Compliant) */
(function () {
  'use strict';

  const root = document.getElementById('flex-studio-root');
  if (!root) return;

  const URLS = {
    bootstrap: root.dataset.bootstrapUrl,
    compat: root.dataset.compatUrl,
    dashboards: root.dataset.dashboardsUrl,
    query: root.dataset.queryUrl,
    drilldown: root.dataset.drilldownUrl,
    exportUrl: root.dataset.exportUrl,
  };

  function getCsrf() {
    const inp = root.querySelector('input[name="csrfmiddlewaretoken"]');
    return inp ? inp.value : '';
  }

  async function apiFetch(url, opts) {
    const o = Object.assign({ headers: {} }, opts || {});
    o.headers['X-Requested-With'] = 'XMLHttpRequest';
    if (o.method && o.method !== 'GET') {
      o.headers['X-CSRFToken'] = getCsrf();
      if (o.body && typeof o.body === 'object' && !(o.body instanceof FormData)) {
        o.headers['Content-Type'] = 'application/json';
        o.body = JSON.stringify(o.body);
      }
    }
    const resp = await fetch(url, o);
    const data = await resp.json().catch(function () { return {}; });
    if (!resp.ok) {
      throw new Error(data.error || ('خطأ غير متوقع (' + resp.status + ')'));
    }
    return data;
  }

  function showToast(msg, isError) {
    const el = document.getElementById('flex-toast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'flex-toast' + (isError ? ' is-error' : '');
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(function () { el.hidden = true; }, 4200);
  }

  function stampRiyadhNow() {
    const el = document.getElementById('flex-last-updated');
    if (!el) return;
    try {
      const now = new Date();
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Riyadh',
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false
      }).formatToParts(now).reduce(function (acc, p) { acc[p.type] = p.value; return acc; }, {});
      const stamp = parts.day + '/' + parts.month + '/' + parts.year + ' ' + parts.hour + ':' + parts.minute + ':' + parts.second;
      el.dateTime = now.toISOString();
      el.innerHTML = 'وقت تحديث اللوحة: <bdi>' + stamp + '</bdi> · توقيت الرياض';
    } catch (_) {
      el.textContent = 'وقت تحديث اللوحة: الآن · توقيت الرياض';
    }
  }

  function fmtValue(val, fmtType, unit) {
    if (val === null || val === undefined || val === '') return '—';
    if (typeof val === 'boolean') return val ? 'نعم' : 'لا';
    if (typeof val === 'number') {
      const formatted = fmtType === 'integer'
        ? Math.round(val).toLocaleString('en-US')
        : val.toLocaleString('en-US', { maximumFractionDigits: 2 });
      return unit ? formatted + ' ' + unit : formatted;
    }
    return String(val);
  }

  function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  const STATE = {
    permissions: {},
    metadata: { entities: [], aggregations: [] },
    entityMap: {},
    kpiCatalog: [],
    dashboards: [],
    templates: [],
    filterOptions: { regions: [], sectors: [] },
    activeDashboard: null,
    draft: null,
    editMode: false,
    dirty: false,
    history: [],
    historyIdx: -1,
    activeFilters: {},
    dragPayload: null,
    // Widget modal state
    wmTab: 'kpi',
    wmEditing: null, // { sIdx, wIdx } or null
    wmSelectedKpi: null,
    tbCompat: null,
    tbCols: [],
    chCompat: null,
    chMeasures: [],
    // Section modal state
    secEditingIdx: null,
    shareTargets: { users: [], groups: [] },
  };

  function currentDoc() {
    return STATE.editMode && STATE.draft ? STATE.draft : STATE.activeDashboard;
  }

  function pushHistory() {
    if (!STATE.draft) return;
    STATE.history = STATE.history.slice(0, STATE.historyIdx + 1);
    STATE.history.push(deepClone(STATE.draft));
    if (STATE.history.length > 35) STATE.history.shift();
    STATE.historyIdx = STATE.history.length - 1;
    STATE.dirty = true;
    syncHeaderUI();
  }

  function syncHeaderUI() {
    const doc = currentDoc();
    if (!doc) return;
    document.getElementById('flex-dash-title').textContent = doc.title || 'المؤشرات والتحليلات المرنة';
    document.getElementById('flex-dash-desc').textContent = doc.description || '';

    const btnXlsx = document.getElementById('btn-export-xlsx');
    const btnPdf = document.getElementById('btn-export-pdf');
    if (btnXlsx) btnXlsx.hidden = !STATE.permissions.can_export_xlsx;
    if (btnPdf) btnPdf.hidden = !STATE.permissions.can_export_pdf;

    const hasManageAccess = Boolean(
      STATE.permissions.can_create || STATE.permissions.can_edit || STATE.permissions.can_delete
    );
    const toolbar = root.querySelector('.flex-toolbar');
    const filtersBar = document.getElementById('flex-filters-bar');
    const modeBadge = document.getElementById('flex-mode-badge');

    if (!hasManageAccess) {
      if (toolbar) toolbar.hidden = true;
      modeBadge.hidden = true;
      document.getElementById('flex-dirty-badge').hidden = true;
      document.getElementById('flex-edit-bar').hidden = true;
      if (filtersBar) filtersBar.hidden = false;
      return;
    }

    if (toolbar) toolbar.hidden = false;
    modeBadge.hidden = false;
    modeBadge.textContent = STATE.editMode ? 'وضع التخصيص' : 'وضع العرض';
    modeBadge.className = 'flex-badge ' + (STATE.editMode ? 'flex-badge-edit' : 'flex-badge-view');

    document.getElementById('flex-dirty-badge').hidden = !(STATE.editMode && STATE.dirty);
    document.getElementById('flex-edit-bar').hidden = !STATE.editMode;
    document.getElementById('btn-enter-edit').hidden = STATE.editMode || !doc.can_edit || !STATE.permissions.can_edit;
    const btnEdit = document.getElementById('btn-enter-edit');
    if (btnEdit) btnEdit.hidden = STATE.editMode || !doc.can_edit || !STATE.permissions.can_edit;

    document.getElementById('btn-undo').disabled = STATE.historyIdx <= 0;
    document.getElementById('btn-redo').disabled = STATE.historyIdx >= STATE.history.length - 1;
    if (STATE.editMode) {
      document.getElementById('flex-edit-title-input').value = doc.title || '';
    }
  }

  function populateDashSelect() {
    const sel = document.getElementById('flex-dash-select');
    if (!sel) return;
    sel.innerHTML = '';
    STATE.dashboards.forEach(function (d) {
      const opt = document.createElement('option');
      opt.value = d.id;
      opt.textContent = (d.is_favorite ? '★ ' : '') + d.title + (d.is_default ? ' (افتراضية)' : '');
      if (STATE.activeDashboard && d.id === STATE.activeDashboard.id) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  function populateFilterSelects() {
    const regSel = document.getElementById('gf-region');
    regSel.innerHTML = '<option value="">جميع المناطق المتاحة</option>';
    (STATE.filterOptions.regions || []).forEach(function (r) {
      const o = document.createElement('option');
      o.value = r.id;
      o.textContent = r.name;
      regSel.appendChild(o);
    });
    const secSel = document.getElementById('gf-sector');
    secSel.innerHTML = '<option value="">جميع القطاعات</option>';
    (STATE.filterOptions.sectors || []).forEach(function (s) {
      const o = document.createElement('option');
      o.value = s.id;
      o.textContent = s.name;
      secSel.appendChild(o);
    });
    const tplSel = document.getElementById('dm-template-select');
    tplSel.innerHTML = '<option value="blank">لوحة فارغة (ابدأ من الصفر)</option>';
    (STATE.templates || []).forEach(function (t) {
      const o = document.createElement('option');
      o.value = t.key;
      o.textContent = t.title + ' (' + t.category + ')';
      tplSel.appendChild(o);
    });
  }

  function readFiltersFromBar() {
    const f = {};
    const preset = document.getElementById('gf-date-preset').value;
    const dFrom = document.getElementById('gf-date-from').value;
    const dTo = document.getElementById('gf-date-to').value;
    const reg = document.getElementById('gf-region').value;
    const sec = document.getElementById('gf-sector').value;
    const srch = document.getElementById('gf-search').value.trim();
    if (preset) f.date_preset = preset;
    if (dFrom) f.date_from = dFrom;
    if (dTo) f.date_to = dTo;
    if (reg) f.region_id = reg;
    if (sec) f.sector_id = sec;
    if (srch) f.search = srch;
    return f;
  }

  function applyFiltersToBar(f) {
    const g = f || {};
    document.getElementById('gf-date-preset').value = g.date_preset || '';
    document.getElementById('gf-date-from').value = g.date_from || '';
    document.getElementById('gf-date-to').value = g.date_to || '';
    document.getElementById('gf-region').value = g.region_id || '';
    document.getElementById('gf-sector').value = g.sector_id || '';
    document.getElementById('gf-search').value = g.search || '';
  }

  // === Canvas & Independent Async Widget Rendering ===
  function renderCanvas() {
    stampRiyadhNow();
    const doc = currentDoc();
    const canvas = document.getElementById('flex-canvas');
    canvas.innerHTML = '';
    if (!doc) return;

    const sections = doc.sections || [];
    if (!sections.length) {
      const empty = document.createElement('div');
      empty.className = 'flex-section';
      empty.innerHTML = '<div class="fx-empty">هذه اللوحة لا تحتوي على أقسام بعد. انتقل إلى «تخصيص اللوحة» لإضافة أقسام وعناصر تحليلية.</div>';
      canvas.appendChild(empty);
      return;
    }

    sections.forEach(function (sec, sIdx) {
      const secEl = document.createElement('section');
      secEl.className = 'flex-section';
      secEl.dataset.secIdx = String(sIdx);

      // Allow dropping widgets onto this section
      if (STATE.editMode) {
        secEl.addEventListener('dragover', function (e) {
          e.preventDefault();
          secEl.classList.add('is-drag-over');
        });
        secEl.addEventListener('dragleave', function () {
          secEl.classList.remove('is-drag-over');
        });
        secEl.addEventListener('drop', function (e) {
          e.preventDefault();
          secEl.classList.remove('is-drag-over');
          if (!STATE.dragPayload || STATE.dragPayload.kind !== 'widget') return;
          moveWidget(STATE.dragPayload.sIdx, STATE.dragPayload.wIdx, sIdx, (STATE.draft.sections[sIdx].widgets || []).length);
          STATE.dragPayload = null;
        });
      }

      const head = document.createElement('div');
      head.className = 'flex-section-head';
      const titleWrap = document.createElement('div');
      const h2 = document.createElement('h2');
      h2.className = 'flex-section-title';
      h2.textContent = sec.title || ('قسم #' + (sIdx + 1));
      titleWrap.appendChild(h2);
      if (sec.description) {
        const p = document.createElement('p');
        p.className = 'flex-section-desc';
        p.textContent = sec.description;
        titleWrap.appendChild(p);
      }
      head.appendChild(titleWrap);

      const tools = document.createElement('div');
      tools.className = 'flex-section-tools';


      if (STATE.editMode) {
        function makeSecIconBtn(svgPath, label, extraClass, onClick) {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'fx-sec-icon-btn' + (extraClass ? ' ' + extraClass : '');
          b.title = label;
          b.setAttribute('aria-label', label);
          b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + svgPath + '</svg>';
          b.addEventListener('click', onClick);
          return b;
        }

        tools.appendChild(makeSecIconBtn(
          '<path d="M12 5v14M5 12h14"/>',
          'إضافة عنصر تحليلي',
          'is-primary',
          function () { openWidgetModal(sIdx, null); }
        ));

        tools.appendChild(makeSecIconBtn(
          '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.08a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.08a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
          'إعدادات القسم',
          '',
          function () { openSectionModal(sIdx); }
        ));

        if (sIdx > 0) {
          tools.appendChild(makeSecIconBtn(
            '<path d="M12 19V5M5 12l7-7 7 7"/>',
            'نقل القسم للأعلى',
            '',
            function () {
              const arr = STATE.draft.sections;
              const tmp = arr[sIdx - 1];
              arr[sIdx - 1] = arr[sIdx];
              arr[sIdx] = tmp;
              pushHistory();
              renderCanvas();
            }
          ));
        }

        if (sIdx < sections.length - 1) {
          tools.appendChild(makeSecIconBtn(
            '<path d="M12 5v14M19 12l-7 7-7-7"/>',
            'نقل القسم للأسفل',
            '',
            function () {
              const arr = STATE.draft.sections;
              const tmp = arr[sIdx + 1];
              arr[sIdx + 1] = arr[sIdx];
              arr[sIdx] = tmp;
              pushHistory();
              renderCanvas();
            }
          ));
        }

        tools.appendChild(makeSecIconBtn(
          '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14ZM10 11v6M14 11v6"/>',
          'حذف القسم',
          'is-danger',
          function () {
            STATE.draft.sections.splice(sIdx, 1);
            pushHistory();
            renderCanvas();
          }
        ));
      }

      head.appendChild(tools);
      secEl.appendChild(head);

      if (true) {
        const grid = document.createElement('div');
        grid.className = 'flex-grid';
        const widgets = sec.widgets || [];
        if (!widgets.length) {
          const emp = document.createElement('div');
          emp.className = 'fx-empty fx-span-12';
          emp.textContent = 'قسم فارغ — أضف مؤشرًا أو جدولًا أو رسمًا بيانيًا.';
          grid.appendChild(emp);
        } else {
          widgets.forEach(function (w, wIdx) {
            grid.appendChild(buildWidgetCard(sec, sIdx, w, wIdx));
          });
        }
        secEl.appendChild(grid);
      }
      canvas.appendChild(secEl);
    });
  }

  function moveWidget(fromS, fromW, toS, toW) {
    const srcArr = STATE.draft.sections[fromS].widgets;
    const item = srcArr.splice(fromW, 1)[0];
    if (!item) return;
    const dstArr = STATE.draft.sections[toS].widgets;
    const clamped = Math.max(0, Math.min(dstArr.length, toW));
    dstArr.splice(clamped, 0, item);
    pushHistory();
    renderCanvas();
  }

  function buildWidgetCard(sec, sIdx, w, wIdx) {
    const span = Math.max(1, Math.min(12, Number(w.col_span || 6)));
    const rowSpan = Math.max(1, Math.min(4, Number(w.row_span || (w.widget_type === 'kpi' || w.widget_type === 'custom_kpi' ? 1 : 2))));
    const card = document.createElement('article');
    card.className = 'flex-widget fx-span-' + span + ' fx-row-' + rowSpan +
      ((w.config && w.config.variant === 'accent') ? ' is-kpi-accent' : '');

    if (STATE.editMode) {
      card.draggable = true;
      card.addEventListener('dragstart', function (e) {
        STATE.dragPayload = { kind: 'widget', sIdx: sIdx, wIdx: wIdx };
        card.classList.add('is-dragging');
        e.dataTransfer.effectAllowed = 'move';
      });
      card.addEventListener('dragend', function () {
        card.classList.remove('is-dragging');
      });
      card.addEventListener('dragover', function (e) { e.preventDefault(); });
      card.addEventListener('drop', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (!STATE.dragPayload || STATE.dragPayload.kind !== 'widget') return;
        moveWidget(STATE.dragPayload.sIdx, STATE.dragPayload.wIdx, sIdx, wIdx);
        STATE.dragPayload = null;
      });
    }

    const head = document.createElement('div');
    head.className = 'flex-widget-head';
    const titleBox = document.createElement('div');
    const h3 = document.createElement('h3');
    h3.className = 'flex-widget-title';
    h3.textContent = w.title || 'عنصر تحليلي';
    titleBox.appendChild(h3);
    if (w.subtitle) {
      const sub = document.createElement('p');
      sub.className = 'flex-widget-sub';
      sub.textContent = w.subtitle;
      titleBox.appendChild(sub);
    }
    head.appendChild(titleBox);

    const actions = document.createElement('div');
    actions.className = 'flex-widget-actions';



    if (STATE.editMode) {
      function makeWIconBtn(svgPath, label, extraClass, onClick) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'fx-w-icon-btn' + (extraClass ? ' ' + extraClass : '');
        b.title = label;
        b.setAttribute('aria-label', label);
        b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + svgPath + '</svg>';
        b.addEventListener('click', onClick);
        return b;
      }

      const resizeSteps = [3, 4, 6, 8, 9, 12];
      actions.appendChild(makeWIconBtn(
        '<path d="M18 8l4 4-4 4M6 8l-4 4 4 4M2 12h20"/>',
        'تغيير عرض العنصر (' + span + '/12)',
        '',
        function () {
          const curIdx = resizeSteps.indexOf(span);
          w.col_span = resizeSteps[(curIdx + 1) % resizeSteps.length];
          pushHistory();
          renderCanvas();
        }
      ));

      actions.appendChild(makeWIconBtn(
        '<path d="M12 20h9M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4Z"/>',
        'تعديل العنصر',
        '',
        function () { openWidgetModal(sIdx, wIdx); }
      ));

      actions.appendChild(makeWIconBtn(
        '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
        'نسخ العنصر',
        '',
        function () {
          const copy = deepClone(w);
          copy.title = copy.title + ' (نسخة)';
          STATE.draft.sections[sIdx].widgets.splice(wIdx + 1, 0, copy);
          pushHistory();
          renderCanvas();
        }
      ));

      actions.appendChild(makeWIconBtn(
        '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14ZM10 11v6M14 11v6"/>',
        'حذف العنصر',
        'is-danger',
        function () {
          STATE.draft.sections[sIdx].widgets.splice(wIdx, 1);
          pushHistory();
          renderCanvas();
        }
      ));
    }

    head.appendChild(actions);
    card.appendChild(head);

    const body = document.createElement('div');
    body.className = 'flex-widget-body';
    body.innerHTML = '<div class="fx-skeleton"></div>';
    card.appendChild(body);

    const mergedFilters = Object.assign({}, STATE.activeFilters, sec.section_filters || {});
    loadWidgetData(w, mergedFilters, body);
    return card;
  }

  async function loadWidgetData(w, filters, container) {
    try {
      const res = await apiFetch(URLS.query, {
        method: 'POST',
        body: {
          widget_type: w.widget_type,
          config: w.config || {},
          global_filters: filters || {},
        },
      });
      renderWidgetBody(w, res.data, filters, container);
    } catch (err) {
      container.innerHTML = '';
      const errDiv = document.createElement('div');
      errDiv.className = 'fx-error';
      errDiv.textContent = err.message || 'تعذر تحميل بيانات هذا العنصر.';
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'fx-mini-btn';
      retry.textContent = 'إعادة المحاولة';
      retry.addEventListener('click', function () { loadWidgetData(w, filters, container); });
      errDiv.appendChild(document.createTextNode(' '));
      errDiv.appendChild(retry);
      container.appendChild(errDiv);
    }
  }

  function renderWidgetBody(w, data, filters, container) {
    container.innerHTML = '';
    if (w.widget_type === 'kpi' || w.widget_type === 'custom_kpi') {
      const valDiv = document.createElement('div');
      valDiv.className = 'fx-kpi-value';
      valDiv.textContent = fmtValue(data.value, data.format_type, '');
      if (data.unit) {
        const uSpan = document.createElement('span');
        uSpan.className = 'fx-kpi-unit';
        uSpan.textContent = data.unit;
        valDiv.appendChild(uSpan);
      }
      container.appendChild(valDiv);

      const meta = document.createElement('div');
      meta.className = 'fx-kpi-meta';
      if (data.delta_pct !== null && data.delta_pct !== undefined) {
        const isPos = data.delta_pct >= 0;
        const good = (data.trend_semantics === 'negative') ? !isPos : isPos;
        const badge = document.createElement('span');
        badge.className = 'fx-delta ' + (good ? 'is-good' : 'is-bad');
        badge.textContent = (isPos ? '▲ +' : '▼ ') + data.delta_pct + '% (30 يومًا)';
        meta.appendChild(badge);
      }
      if (data.target !== null && data.target !== undefined && data.target !== '') {
        const tSpan = document.createElement('span');
        tSpan.textContent = 'المستهدف: ' + fmtValue(Number(data.target), data.format_type, data.unit) +
          (data.target_pct !== null ? ' (' + data.target_pct + '%)' : '');
        meta.appendChild(tSpan);
      }
      if (data.description_ar) {
        const dSpan = document.createElement('span');
        dSpan.textContent = data.description_ar;
        meta.appendChild(dSpan);
      }
      container.appendChild(meta);

      if (data.target_pct !== null && data.target_pct !== undefined) {
        const prog = document.createElement('progress');
        prog.className = 'fx-progress-track';
        prog.max = 100;
        prog.value = Math.min(100, Math.max(0, Number(data.target_pct)));
        container.appendChild(prog);
      }
      return;
    }

    if (w.widget_type === 'chart') {
      window.MakkenFlexCharts.renderChart(container, data, function (clickedLabel) {
        if (!data.dimension) return;
        openDrilldown(w.config, data.dimension.entity, data.dimension.field, clickedLabel, filters, w.title + ' — ' + clickedLabel);
      });
      return;
    }

    // Table / Summary
    renderDataTable(container, data, function (row) {
      if (data.mode !== 'grouped') return;
      const firstDim = (data.columns || []).find(function (c) { return !c.aggregation; });
      if (!firstDim) return;
      openDrilldown(w.config, firstDim.entity, firstDim.field, row[firstDim.id], filters, w.title + ' — ' + row[firstDim.id]);
    });
  }

  function renderDataTable(container, data, onRowClick) {
    container.innerHTML = '';
    const cols = data.columns || [];
    const rows = data.rows || [];
    if (!rows.length) {
      const emp = document.createElement('div');
      emp.className = 'fx-empty';
      emp.textContent = 'لا توجد سجلات مطابقة للفلاتر الحالية.';
      container.appendChild(emp);
      return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'fx-table-wrap';
    const table = document.createElement('table');
    table.className = 'fx-table';
    table.dataset.mkExportReady = '1';

    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    cols.forEach(function (c) {
      const th = document.createElement('th');
      th.textContent = c.label;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach(function (r) {
      const tr = document.createElement('tr');
      if (onRowClick && data.mode === 'grouped') {
        tr.className = 'is-clickable';
        tr.title = 'انقر لعرض السجلات التفصيلية';
        tr.addEventListener('click', function () { onRowClick(r); });
      }
      cols.forEach(function (c) {
        const td = document.createElement('td');
        td.textContent = fmtValue(r[c.id], c.data_type, c.unit);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);

    const foot = document.createElement('div');
    foot.className = 'fx-table-foot';
    foot.textContent = 'عدد الصفوف المعروضة: ' + rows.length + ' من إجمالي ' + (data.total_count || rows.length);
    wrap.appendChild(foot);
    container.appendChild(wrap);
  }

  async function openDrilldown(config, fEntity, fField, fVal, filters, title) {
    const dlg = document.getElementById('flex-drilldown-modal');
    document.getElementById('dd-title').textContent = title || 'تفاصيل السجلات';
    const body = document.getElementById('dd-body');
    body.innerHTML = '<div class="fx-skeleton"></div>';
    dlg.showModal();
    try {
      const res = await apiFetch(URLS.drilldown, {
        method: 'POST',
        body: {
          config: config,
          filter_entity: fEntity,
          filter_field: fField,
          filter_value: fVal,
          global_filters: filters || {},
        },
      });
      renderDataTable(body, res.data, null);
    } catch (err) {
      body.innerHTML = '<div class="fx-error">' + err.message + '</div>';
    }
  }

  async function exportWidget(w, fmt) {
    try {
      const resp = await fetch(URLS.exportUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrf(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
          format: fmt,
          widget_type: w.widget_type,
          config: w.config || {},
          title: w.title,
          global_filters: STATE.activeFilters,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(function () { return {}; });
        throw new Error(err.error || 'تعذر تنفيذ التصدير.');
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = (w.title || 'report') + '.' + fmt;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast('تم تصدير الملف بنجاح.');
    } catch (err) {
      showToast(err.message, true);
    }
  }

  // === Widget Builder Modal ===
  function populateEntitySelect(selEl, allowedList) {
    selEl.innerHTML = '';
    const list = allowedList || STATE.metadata.entities;
    list.forEach(function (e) {
      const o = document.createElement('option');
      o.value = e.key;
      o.textContent = e.label_ar;
      selEl.appendChild(o);
    });
  }

  function populateFieldSelect(selEl, entityKey, numericOnly) {
    selEl.innerHTML = '';
    const ent = STATE.entityMap[entityKey];
    if (!ent) return;
    ent.fields.forEach(function (f) {
      if (numericOnly && !f.is_numeric) return;
      const o = document.createElement('option');
      o.value = f.name;
      o.textContent = f.label_ar;
      selEl.appendChild(o);
    });
  }

  function setWmTab(tab) {
    STATE.wmTab = tab;
    document.querySelectorAll('[data-wm-tab]').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.wmTab === tab);
    });
    ['kpi', 'custom_kpi', 'table', 'chart'].forEach(function (t) {
      document.getElementById('wm-panel-' + t).hidden = (t !== tab);
    });
  }

  function renderKpiPicker() {
    const q = (document.getElementById('wm-kpi-search').value || '').trim().toLowerCase();
    const cat = document.getElementById('wm-kpi-cat').value;
    const grid = document.getElementById('wm-kpi-grid');
    grid.innerHTML = '';
    const matches = STATE.kpiCatalog.filter(function (k) {
      if (cat && k.category_ar !== cat) return false;
      if (!q) return true;
      return k.title_ar.toLowerCase().includes(q) ||
        k.title_en.toLowerCase().includes(q) ||
        k.category_ar.toLowerCase().includes(q) ||
        k.description_ar.toLowerCase().includes(q);
    });
    if (!matches.length) {
      grid.innerHTML = '<div class="fx-empty">لا توجد مؤشرات مطابقة للبحث.</div>';
      return;
    }
    matches.forEach(function (k) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'fx-kpi-opt' + (STATE.wmSelectedKpi === k.key ? ' is-selected' : '');
      btn.innerHTML = '<span class="fx-kpi-opt-cat"></span><span class="fx-kpi-opt-title"></span><span class="fx-kpi-opt-desc"></span>';
      btn.querySelector('.fx-kpi-opt-cat').textContent = k.category_ar + ' · ' + k.entity_label_ar;
      btn.querySelector('.fx-kpi-opt-title').textContent = k.title_ar;
      btn.querySelector('.fx-kpi-opt-desc').textContent = k.description_ar;
      btn.addEventListener('click', function () {
        STATE.wmSelectedKpi = k.key;
        if (!document.getElementById('wm-widget-title').value.trim()) {
          document.getElementById('wm-widget-title').value = k.title_ar;
        }
        renderKpiPicker();
      });
      grid.appendChild(btn);
    });
  }

  async function refreshTableCompatibility(baseEntity) {
    const data = await apiFetch(URLS.compat + '?base=' + encodeURIComponent(baseEntity));
    STATE.tbCompat = data;
    const pills = document.getElementById('tb-compat-pills');
    pills.innerHTML = '';
    (data.compatible || []).forEach(function (c) {
      const sp = document.createElement('span');
      sp.className = 'fx-compat-pill';
      sp.textContent = '✓ ' + c.label_ar + (c.relation_type === 'indirect' ? ' (غير مباشر)' : '');
      pills.appendChild(sp);
    });
    (data.unrelated || []).forEach(function (u) {
      const sp = document.createElement('span');
      sp.className = 'fx-compat-pill is-unrelated';
      sp.textContent = '✕ ' + u.label_ar;
      sp.title = u.message_ar || data.unrelated_message_ar;
      pills.appendChild(sp);
    });
    renderTableColsBuilder();
  }

  function renderTableColsBuilder() {
    const list = document.getElementById('tb-cols-list');
    list.innerHTML = '';
    const compatEntities = (STATE.tbCompat && STATE.tbCompat.compatible) ? STATE.tbCompat.compatible : STATE.metadata.entities;
    STATE.tbCols.forEach(function (col, idx) {
      const row = document.createElement('div');
      row.className = 'fx-col-row';

      const eSel = document.createElement('select');
      eSel.className = 'flex-select';
      compatEntities.forEach(function (ce) {
        const o = document.createElement('option');
        o.value = ce.key;
        o.textContent = ce.label_ar;
        if (ce.key === col.entity) o.selected = true;
        eSel.appendChild(o);
      });

      const fSel = document.createElement('select');
      fSel.className = 'flex-select';
      function fillFields() {
        fSel.innerHTML = '';
        const ent = STATE.entityMap[col.entity];
        if (!ent) return;
        ent.fields.forEach(function (f) {
          const o = document.createElement('option');
          o.value = f.name;
          o.textContent = f.label_ar;
          if (f.name === col.field) o.selected = true;
          fSel.appendChild(o);
        });
      }
      fillFields();

      eSel.addEventListener('change', function () {
        col.entity = eSel.value;
        const ent = STATE.entityMap[col.entity];
        col.field = ent && ent.fields.length ? ent.fields[0].name : 'id';
        col.label = ent && ent.fields.length ? ent.fields[0].label_ar : col.field;
        fillFields();
        lInp.value = col.label;
      });
      fSel.addEventListener('change', function () {
        col.field = fSel.value;
        const ent = STATE.entityMap[col.entity];
        const fmeta = ent && ent.fields.find(function (x) { return x.name === col.field; });
        col.label = fmeta ? fmeta.label_ar : col.field;
        lInp.value = col.label;
      });

      const aSel = document.createElement('select');
      aSel.className = 'flex-select';
      [['', 'بُعد (تجميع حسب)'], ['count', 'العدد'], ['count_distinct', 'العدد الفريد'], ['sum', 'المجموع'], ['avg', 'المتوسط'], ['min', 'الأدنى'], ['max', 'الأعلى'], ['median', 'الوسيط']].forEach(function (pair) {
        const o = document.createElement('option');
        o.value = pair[0];
        o.textContent = pair[1];
        if (pair[0] === (col.aggregation || '')) o.selected = true;
        aSel.appendChild(o);
      });
      aSel.addEventListener('change', function () { col.aggregation = aSel.value; });

      const lInp = document.createElement('input');
      lInp.type = 'text';
      lInp.className = 'flex-input';
      lInp.value = col.label || '';
      lInp.placeholder = 'تسمية العمود';
      lInp.addEventListener('input', function () { col.label = lInp.value; });

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'fx-mini-btn is-danger';
      delBtn.textContent = '×';
      delBtn.addEventListener('click', function () {
        STATE.tbCols.splice(idx, 1);
        renderTableColsBuilder();
      });

      row.appendChild(eSel);
      row.appendChild(fSel);
      row.appendChild(aSel);
      row.appendChild(lInp);
      row.appendChild(delBtn);
      list.appendChild(row);
    });
  }

  async function refreshChartCompatibility(baseEntity) {
    const data = await apiFetch(URLS.compat + '?base=' + encodeURIComponent(baseEntity));
    STATE.chCompat = data;
    const dimEntSel = document.getElementById('ch-dim-entity');
    populateEntitySelect(dimEntSel, data.compatible || STATE.metadata.entities);
    dimEntSel.value = baseEntity;
    populateFieldSelect(document.getElementById('ch-dim-field'), baseEntity, false);
    renderChartMeasuresBuilder();
  }

  function renderChartMeasuresBuilder() {
    const list = document.getElementById('ch-measures-list');
    list.innerHTML = '';
    const compatEntities = (STATE.chCompat && STATE.chCompat.compatible) ? STATE.chCompat.compatible : STATE.metadata.entities;
    STATE.chMeasures.forEach(function (m, idx) {
      const row = document.createElement('div');
      row.className = 'fx-col-row';

      const eSel = document.createElement('select');
      eSel.className = 'flex-select';
      compatEntities.forEach(function (ce) {
        const o = document.createElement('option');
        o.value = ce.key;
        o.textContent = ce.label_ar;
        if (ce.key === m.entity) o.selected = true;
        eSel.appendChild(o);
      });

      const fSel = document.createElement('select');
      fSel.className = 'flex-select';
      function fillFields() {
        fSel.innerHTML = '';
        const ent = STATE.entityMap[m.entity];
        if (!ent) return;
        ent.fields.forEach(function (f) {
          const o = document.createElement('option');
          o.value = f.name;
          o.textContent = f.label_ar;
          if (f.name === m.field) o.selected = true;
          fSel.appendChild(o);
        });
      }
      fillFields();

      eSel.addEventListener('change', function () {
        m.entity = eSel.value;
        fillFields();
      });
      fSel.addEventListener('change', function () { m.field = fSel.value; });

      const aSel = document.createElement('select');
      aSel.className = 'flex-select';
      [['count', 'العدد'], ['count_distinct', 'العدد الفريد'], ['sum', 'المجموع'], ['avg', 'المتوسط'], ['min', 'الأدنى'], ['max', 'الأعلى']].forEach(function (pair) {
        const o = document.createElement('option');
        o.value = pair[0];
        o.textContent = pair[1];
        if (pair[0] === (m.aggregation || 'count')) o.selected = true;
        aSel.appendChild(o);
      });
      aSel.addEventListener('change', function () { m.aggregation = aSel.value; });

      const lInp = document.createElement('input');
      lInp.type = 'text';
      lInp.className = 'flex-input';
      lInp.value = m.label || '';
      lInp.placeholder = 'تسمية المقياس';
      lInp.addEventListener('input', function () { m.label = lInp.value; });

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'fx-mini-btn is-danger';
      delBtn.textContent = '×';
      delBtn.addEventListener('click', function () {
        if (STATE.chMeasures.length <= 1) return;
        STATE.chMeasures.splice(idx, 1);
        renderChartMeasuresBuilder();
      });

      row.appendChild(eSel);
      row.appendChild(fSel);
      row.appendChild(aSel);
      row.appendChild(lInp);
      row.appendChild(delBtn);
      list.appendChild(row);
    });
  }

  function buildWidgetConfigFromModal() {
    if (STATE.wmTab === 'kpi') {
      if (!STATE.wmSelectedKpi) throw new Error('يرجى اختيار مؤشر أداء من القائمة.');
      const targetVal = document.getElementById('wm-kpi-target').value;
      return {
        widget_type: 'kpi',
        config: {
          kpi_key: STATE.wmSelectedKpi,
          target: targetVal !== '' ? Number(targetVal) : null,
        },
      };
    }
    if (STATE.wmTab === 'custom_kpi') {
      const formula = document.getElementById('ck-formula').value;
      const cfg = {
        formula_type: formula,
        title: document.getElementById('wm-widget-title').value.trim() || 'مؤشر مخصص',
        primary: {
          entity: document.getElementById('ck-entity-1').value,
          field: document.getElementById('ck-field-1').value,
          aggregation: document.getElementById('ck-agg-1').value,
        },
      };
      if (formula !== 'single') {
        cfg.secondary = {
          entity: document.getElementById('ck-entity-2').value,
          field: document.getElementById('ck-field-2').value,
          aggregation: document.getElementById('ck-agg-2').value,
        };
      }
      const tgt = document.getElementById('ck-target').value;
      if (tgt !== '') cfg.target = Number(tgt);
      return { widget_type: 'custom_kpi', config: cfg };
    }
    if (STATE.wmTab === 'table') {
      if (!STATE.tbCols.length) throw new Error('يرجى إضافة عمود واحد على الأقل للجدول.');
      return {
        widget_type: 'table',
        config: {
          base_entity: document.getElementById('tb-base-entity').value,
          mode: document.getElementById('tb-mode').value,
          top_n: Number(document.getElementById('tb-top-n').value || 15),
          columns: STATE.tbCols.map(function (c, i) {
            return {
              id: c.id || ('col_' + i),
              entity: c.entity,
              field: c.field,
              aggregation: c.aggregation || '',
              label: c.label || c.field,
            };
          }),
        },
      };
    }
    return {
      widget_type: 'chart',
      config: {
        chart_type: document.getElementById('ch-type').value,
        base_entity: document.getElementById('ch-base-entity').value,
        dimension: {
          entity: document.getElementById('ch-dim-entity').value,
          field: document.getElementById('ch-dim-field').value,
          date_granularity: document.getElementById('ch-date-gran').value,
        },
        measures: STATE.chMeasures.map(function (m) {
          return {
            entity: m.entity,
            field: m.field,
            aggregation: m.aggregation || 'count',
            label: m.label || m.field,
          };
        }),
        top_n: Number(document.getElementById('ch-top-n').value || 10),
      },
    };
  }

  async function openWidgetModal(defaultSectionIdx, editWidgetIdx) {
    if (!STATE.editMode) enterEditMode();
    if (!STATE.draft.sections.length) {
      STATE.draft.sections.push({ title: 'قسم جديد', description: '', layout_preset: 'grid_12', widgets: [] });
    }
    const secSel = document.getElementById('wm-section-select');
    secSel.innerHTML = '';
    STATE.draft.sections.forEach(function (s, idx) {
      const o = document.createElement('option');
      o.value = String(idx);
      o.textContent = s.title || ('قسم #' + (idx + 1));
      if (idx === (defaultSectionIdx || 0)) o.selected = true;
      secSel.appendChild(o);
    });

    const isEdit = editWidgetIdx !== null && editWidgetIdx !== undefined;
    STATE.wmEditing = isEdit ? { sIdx: defaultSectionIdx, wIdx: editWidgetIdx } : null;
    document.getElementById('wm-title').textContent = isEdit ? 'تعديل العنصر التحليلي' : 'إضافة عنصر تحليلي';

    const existing = isEdit ? STATE.draft.sections[defaultSectionIdx].widgets[editWidgetIdx] : null;
    document.getElementById('wm-widget-title').value = existing ? (existing.title || '') : '';
    document.getElementById('wm-widget-subtitle').value = existing ? (existing.subtitle || '') : '';
    document.getElementById('wm-col-span').value = String(existing ? (existing.col_span || 6) : 6);

    const firstEntKey = (STATE.metadata.entities[0] || {}).key || 'market_needs';
    populateEntitySelect(document.getElementById('ck-entity-1'));
    populateEntitySelect(document.getElementById('ck-entity-2'));
    populateFieldSelect(document.getElementById('ck-field-1'), firstEntKey, false);
    populateFieldSelect(document.getElementById('ck-field-2'), firstEntKey, false);
    populateEntitySelect(document.getElementById('tb-base-entity'));
    populateEntitySelect(document.getElementById('ch-base-entity'));

    // KPI categories
    const catSel = document.getElementById('wm-kpi-cat');
    catSel.innerHTML = '<option value="">جميع التصنيفات</option>';
    const cats = Array.from(new Set(STATE.kpiCatalog.map(function (k) { return k.category_ar; })));
    cats.forEach(function (c) {
      const o = document.createElement('option');
      o.value = c;
      o.textContent = c;
      catSel.appendChild(o);
    });

    const targetTab = existing ? existing.widget_type : 'kpi';
    setWmTab(['kpi', 'custom_kpi', 'table', 'chart'].includes(targetTab) ? targetTab : 'kpi');

    if (existing && existing.widget_type === 'kpi') {
      STATE.wmSelectedKpi = existing.config.kpi_key || null;
      document.getElementById('wm-kpi-target').value = existing.config.target || '';
    } else {
      STATE.wmSelectedKpi = (STATE.kpiCatalog[0] || {}).key || null;
      document.getElementById('wm-kpi-target').value = '';
    }
    renderKpiPicker();

    const tbBase = (existing && existing.widget_type === 'table' && existing.config.base_entity) || firstEntKey;
    document.getElementById('tb-base-entity').value = tbBase;
    document.getElementById('tb-mode').value = (existing && existing.widget_type === 'table' && existing.config.mode) || 'grouped';
    document.getElementById('tb-top-n').value = String((existing && existing.widget_type === 'table' && existing.config.top_n) || 15);
    STATE.tbCols = (existing && existing.widget_type === 'table' && existing.config.columns)
      ? deepClone(existing.config.columns)
      : [
          { id: 'c0', entity: tbBase, field: (STATE.entityMap[tbBase].fields[1] || STATE.entityMap[tbBase].fields[0]).name, aggregation: '', label: (STATE.entityMap[tbBase].fields[1] || STATE.entityMap[tbBase].fields[0]).label_ar },
          { id: 'c1', entity: tbBase, field: 'id', aggregation: 'count', label: 'العدد' },
        ];
    await refreshTableCompatibility(tbBase);

    const chBase = (existing && existing.widget_type === 'chart' && existing.config.base_entity) || firstEntKey;
    document.getElementById('ch-base-entity').value = chBase;
    document.getElementById('ch-type').value = (existing && existing.widget_type === 'chart' && existing.config.chart_type) || 'bar';
    document.getElementById('ch-top-n').value = String((existing && existing.widget_type === 'chart' && existing.config.top_n) || 10);
    STATE.chMeasures = (existing && existing.widget_type === 'chart' && existing.config.measures)
      ? deepClone(existing.config.measures)
      : [{ entity: chBase, field: 'id', aggregation: 'count', label: 'العدد' }];
    await refreshChartCompatibility(chBase);
    if (existing && existing.widget_type === 'chart' && existing.config.dimension) {
      document.getElementById('ch-dim-entity').value = existing.config.dimension.entity || chBase;
      populateFieldSelect(document.getElementById('ch-dim-field'), document.getElementById('ch-dim-entity').value, false);
      document.getElementById('ch-dim-field').value = existing.config.dimension.field || 'id';
      document.getElementById('ch-date-gran').value = existing.config.dimension.date_granularity || '';
    }

    document.getElementById('tb-preview-box').innerHTML = '';
    document.getElementById('ch-preview-box').innerHTML = '';
    document.getElementById('ck-preview-box').innerHTML = '';
    document.getElementById('flex-widget-modal').showModal();
  }

  function openSectionModal(sIdx) {
    STATE.secEditingIdx = sIdx;
    const isEdit = sIdx !== null && sIdx !== undefined;
    const sec = isEdit ? STATE.draft.sections[sIdx] : { title: '', description: '', layout_preset: 'grid_12' };
    document.getElementById('sec-m-title').textContent = isEdit ? 'تعديل القسم' : 'إضافة قسم جديد';
    document.getElementById('sec-input-title').value = sec.title || '';
    document.getElementById('sec-input-desc').value = sec.description || '';
    document.getElementById('sec-input-layout').value = sec.layout_preset || 'grid_12';
    document.getElementById('flex-section-modal').showModal();
  }

  function enterEditMode() {
    if (!STATE.activeDashboard || !STATE.activeDashboard.can_edit) return;
    STATE.draft = deepClone(STATE.activeDashboard);
    STATE.editMode = true;
    STATE.dirty = false;
    STATE.history = [deepClone(STATE.draft)];
    STATE.historyIdx = 0;
    syncHeaderUI();
    renderCanvas();
  }

  function cancelEditMode() {
    if (STATE.dirty && !window.confirm('هل تريد إلغاء جميع التغييرات غير المحفوظة؟')) return;
    STATE.draft = null;
    STATE.editMode = false;
    STATE.dirty = false;
    STATE.history = [];
    STATE.historyIdx = -1;
    syncHeaderUI();
    renderCanvas();
  }

  async function saveEditMode() {
    if (!STATE.draft) return;
    STATE.draft.title = document.getElementById('flex-edit-title-input').value.trim() || STATE.draft.title;
    STATE.draft.global_filters = STATE.activeFilters;
    try {
      const res = await apiFetch(URLS.dashboards + STATE.draft.id + '/', {
        method: 'POST',
        body: {
          title: STATE.draft.title,
          description: STATE.draft.description,
          version: STATE.draft.version,
          global_filters: STATE.draft.global_filters,
          sections: STATE.draft.sections,
          revision_label: 'تحديث التخطيط والعناصر',
        },
      });
      STATE.activeDashboard = res.dashboard;
      STATE.draft = null;
      STATE.editMode = false;
      STATE.dirty = false;
      STATE.dashboards = STATE.dashboards.map(function (d) {
        return d.id === res.dashboard.id ? Object.assign({}, d, { title: res.dashboard.title, version: res.dashboard.version }) : d;
      });
      populateDashSelect();
      syncHeaderUI();
      renderCanvas();
      showToast('تم حفظ تغييرات اللوحة بنجاح (الإصدار v' + res.dashboard.version + ').');
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function loadBootstrap(dashboardId) {
    try {
      const url = dashboardId ? (URLS.bootstrap + '?dashboard_id=' + encodeURIComponent(dashboardId)) : URLS.bootstrap;
      const data = await apiFetch(url);
      STATE.permissions = data.permissions || {};
      STATE.metadata = data.metadata || { entities: [] };
      STATE.entityMap = {};
      (STATE.metadata.entities || []).forEach(function (e) { STATE.entityMap[e.key] = e; });
      STATE.kpiCatalog = data.kpi_catalog || [];
      STATE.dashboards = data.dashboards || [];
      STATE.templates = data.templates || [];
      STATE.filterOptions = data.filter_options || { regions: [], sectors: [] };
      STATE.activeDashboard = data.active_dashboard;
      STATE.activeFilters = deepClone((STATE.activeDashboard && STATE.activeDashboard.global_filters) || {});
      STATE.editMode = false;
      STATE.draft = null;
      STATE.dirty = false;

      populateDashSelect();
      populateFilterSelects();
      applyFiltersToBar(STATE.activeFilters);
      syncHeaderUI();
      renderCanvas();
    } catch (err) {
      document.getElementById('flex-canvas').innerHTML = '<div class="fx-error">' + err.message + '</div>';
    }
  }

  // === Event Bindings ===
  function bindEvents() {
    document.querySelectorAll('[data-close-dialog]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const dlg = document.getElementById(btn.dataset.closeDialog);
        if (dlg) dlg.close();
      });
    });

    (document.getElementById('flex-dash-select') || {addEventListener:function(){}}).addEventListener('change', function (e) {
      if (STATE.dirty && !window.confirm('لديك تغييرات غير محفوظة. هل تريد الانتقال للوحة أخرى؟')) {
        populateDashSelect();
        return;
      }
      loadBootstrap(e.target.value);
    });

    document.getElementById('btn-enter-edit').addEventListener('click', enterEditMode);
    document.getElementById('btn-cancel-edit').addEventListener('click', cancelEditMode);
    document.getElementById('btn-save-edit').addEventListener('click', saveEditMode);
    (document.getElementById('btn-refresh-all') || {addEventListener:function(){}}).addEventListener('click', renderCanvas);

    (document.getElementById('btn-toggle-filters') || {addEventListener:function(){}}).addEventListener('click', function (e) {
      const bar = document.getElementById('flex-filters-bar');
      bar.hidden = !bar.hidden;
      e.currentTarget.setAttribute('aria-expanded', String(!bar.hidden));
    });

    document.getElementById('btn-apply-filters').addEventListener('click', function () {
      STATE.activeFilters = readFiltersFromBar();
      renderCanvas();
    });

    document.getElementById('btn-reset-filters').addEventListener('click', function () {
      STATE.activeFilters = {};
      applyFiltersToBar({});
      renderCanvas();
    });

    async function exportDashboard(fmt) {
      const doc = currentDoc();
      if (!doc) return;
      try {
        const resp = await fetch(URLS.exportUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrf(),
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({
            dashboard_id: doc.id,
            format: fmt,
            global_filters: STATE.activeFilters,
          }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(function () { return {}; });
          throw new Error(err.error || 'تعذر تنفيذ التصدير.');
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = (doc.title || 'makken_analytics') + '.' + fmt;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showToast('تم تصدير اللوحة بنجاح.');
      } catch (err) {
        showToast(err.message, true);
      }
    }

    const topXlsx = document.getElementById('btn-export-xlsx');
    if (topXlsx) topXlsx.addEventListener('click', function () { exportDashboard('xlsx'); });
    const topPdf = document.getElementById('btn-export-pdf');
    if (topPdf) topPdf.addEventListener('click', function () { exportDashboard('pdf'); });

    document.getElementById('btn-undo').addEventListener('click', function () {
      if (STATE.historyIdx <= 0) return;
      STATE.historyIdx -= 1;
      STATE.draft = deepClone(STATE.history[STATE.historyIdx]);
      syncHeaderUI();
      renderCanvas();
    });

    document.getElementById('btn-redo').addEventListener('click', function () {
      if (STATE.historyIdx >= STATE.history.length - 1) return;
      STATE.historyIdx += 1;
      STATE.draft = deepClone(STATE.history[STATE.historyIdx]);
      syncHeaderUI();
      renderCanvas();
    });

    document.getElementById('btn-add-section').addEventListener('click', function () { openSectionModal(null); });
    document.getElementById('btn-open-widget-lib').addEventListener('click', function () { openWidgetModal(0, null); });

    document.getElementById('btn-sec-save').addEventListener('click', function () {
      const title = document.getElementById('sec-input-title').value.trim() || 'قسم تحليلي';
      const desc = document.getElementById('sec-input-desc').value.trim();
      const layout = document.getElementById('sec-input-layout').value;
      if (STATE.secEditingIdx !== null) {
        Object.assign(STATE.draft.sections[STATE.secEditingIdx], { title: title, description: desc, layout_preset: layout });
      } else {
        STATE.draft.sections.push({ title: title, description: desc, layout_preset: layout, widgets: [] });
      }
      pushHistory();
      renderCanvas();
      document.getElementById('flex-section-modal').close();
    });

    // Dashboard actions
    (document.getElementById('btn-new-dash') || {addEventListener:function(){}}).addEventListener('click', function () {
      document.getElementById('dm-input-title').value = '';
      document.getElementById('dm-input-desc').value = '';
      document.getElementById('flex-dashboard-modal').showModal();
    });

    document.getElementById('btn-dm-create').addEventListener('click', async function () {
      const title = document.getElementById('dm-input-title').value.trim();
      if (!title) { showToast('يرجى إدخال عنوان اللوحة.', true); return; }
      try {
        const res = await apiFetch(URLS.dashboards, {
          method: 'POST',
          body: {
            title: title,
            description: document.getElementById('dm-input-desc').value.trim(),
            template_key: document.getElementById('dm-template-select').value,
          },
        });
        document.getElementById('flex-dashboard-modal').close();
        showToast('تم إنشاء اللوحة بنجاح.');
        await loadBootstrap(res.dashboard.id);
      } catch (err) {
        showToast(err.message, true);
      }
    });

    (document.getElementById('btn-toggle-fav') || {addEventListener:function(){}}).addEventListener('click', async function () {
      if (!STATE.activeDashboard) return;
      try {
        const res = await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/action/', {
          method: 'POST',
          body: { action: 'toggle_favorite' },
        });
        STATE.activeDashboard = res.dashboard;
        await loadBootstrap(res.dashboard.id);
      } catch (err) { showToast(err.message, true); }
    });

    (document.getElementById('btn-duplicate-dash') || {addEventListener:function(){}}).addEventListener('click', async function () {
      if (!STATE.activeDashboard) return;
      try {
        const res = await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/action/', {
          method: 'POST',
          body: { action: 'duplicate' },
        });
        showToast('تم نسخ اللوحة بنجاح.');
        await loadBootstrap(res.dashboard.id);
      } catch (err) { showToast(err.message, true); }
    });

    (document.getElementById('btn-set-default') || {addEventListener:function(){}}).addEventListener('click', async function () {
      if (!STATE.activeDashboard) return;
      try {
        await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/action/', {
          method: 'POST',
          body: { action: 'set_default' },
        });
        showToast('تم تعيين هذه اللوحة كلوحة افتراضية.');
      } catch (err) { showToast(err.message, true); }
    });

    (document.getElementById('btn-save-template') || {addEventListener:function(){}}).addEventListener('click', async function () {
      if (!STATE.activeDashboard) return;
      const name = window.prompt('اسم القالب الجديد:', STATE.activeDashboard.title);
      if (!name) return;
      try {
        await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/action/', {
          method: 'POST',
          body: { action: 'save_as_template', title: name },
        });
        showToast('تم حفظ اللوحة كقالب قابل لإعادة الاستخدام.');
      } catch (err) { showToast(err.message, true); }
    });

    (document.getElementById('btn-delete-dash') || {addEventListener:function(){}}).addEventListener('click', async function () {
      if (!STATE.activeDashboard) return;
      if (!window.confirm('هل أنت متأكد من حذف هذه اللوحة نهائيًا؟')) return;
      try {
        await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/', { method: 'DELETE' });
        showToast('تم حذف اللوحة.');
        await loadBootstrap(null);
      } catch (err) { showToast(err.message, true); }
    });

    // Revisions modal
    (document.getElementById('btn-revisions') || {addEventListener:function(){}}).addEventListener('click', async function () {
      if (!STATE.activeDashboard) return;
      const list = document.getElementById('rm-list');
      list.innerHTML = '<div class="fx-skeleton"></div>';
      document.getElementById('flex-revisions-modal').showModal();
      try {
        const res = await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/revisions/');
        list.innerHTML = '';
        const wrap = document.createElement('div');
        wrap.className = 'fx-rev-list';
        (res.revisions || []).forEach(function (r) {
          const row = document.createElement('div');
          row.className = 'fx-list-row';
          row.innerHTML = '<div><strong>v' + r.version + ' — ' + r.label + '</strong><div class="flex-hint">' + r.created_by + ' · ' + r.created_at.slice(0, 16).replace('T', ' ') + '</div></div>';
          if (STATE.activeDashboard.can_edit) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'flex-btn flex-btn-secondary flex-btn-sm';
            btn.textContent = 'استعادة';
            btn.addEventListener('click', async function () {
              await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/revisions/', {
                method: 'POST',
                body: { revision_id: r.id },
              });
              document.getElementById('flex-revisions-modal').close();
              showToast('تمت استعادة الإصدار v' + r.version);
              await loadBootstrap(STATE.activeDashboard.id);
            });
            row.appendChild(btn);
          }
          wrap.appendChild(row);
        });
        list.appendChild(wrap);
      } catch (err) {
        list.innerHTML = '<div class="fx-error">' + err.message + '</div>';
      }
    });

    // Share modal
    async function loadSharesModal() {
      const res = await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/shares/');
      STATE.shareTargets = res.targets || { users: [], groups: [] };
      fillShareTargetSelect();
      const box = document.getElementById('sm-shares-list');
      box.innerHTML = '';
      (res.shares || []).forEach(function (s) {
        const row = document.createElement('div');
        row.className = 'fx-list-row';
        row.innerHTML = '<div><strong>' + s.target_name + '</strong> <span class="flex-badge flex-badge-view">' + s.permission_label + '</span></div>';
        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'fx-mini-btn is-danger';
        del.textContent = 'إزالة';
        del.addEventListener('click', async function () {
          await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/shares/', {
            method: 'DELETE',
            body: { share_id: s.id },
          });
          loadSharesModal();
        });
        row.appendChild(del);
        box.appendChild(row);
      });
    }

    function fillShareTargetSelect() {
      const tType = document.getElementById('sm-target-type').value;
      const sel = document.getElementById('sm-target-id');
      sel.innerHTML = '';
      const arr = tType === 'group' ? STATE.shareTargets.groups : STATE.shareTargets.users;
      arr.forEach(function (it) {
        const o = document.createElement('option');
        o.value = it.id;
        o.textContent = it.label;
        sel.appendChild(o);
      });
    }

    document.getElementById('sm-target-type').addEventListener('change', fillShareTargetSelect);
    (document.getElementById('btn-share-dash') || {addEventListener:function(){}}).addEventListener('click', async function () {
      if (!STATE.activeDashboard) return;
      document.getElementById('flex-share-modal').showModal();
      await loadSharesModal();
    });
    document.getElementById('btn-sm-add').addEventListener('click', async function () {
      try {
        await apiFetch(URLS.dashboards + STATE.activeDashboard.id + '/shares/', {
          method: 'POST',
          body: {
            target_type: document.getElementById('sm-target-type').value,
            target_id: document.getElementById('sm-target-id').value,
            permission: document.getElementById('sm-perm').value,
          },
        });
        showToast('تمت إضافة المشاركة.');
        await loadSharesModal();
      } catch (err) { showToast(err.message, true); }
    });

    // Widget modal tabs & builders
    document.querySelectorAll('[data-wm-tab]').forEach(function (btn) {
      btn.addEventListener('click', function () { setWmTab(btn.dataset.wmTab); });
    });
    document.getElementById('wm-kpi-search').addEventListener('input', renderKpiPicker);
    document.getElementById('wm-kpi-cat').addEventListener('change', renderKpiPicker);

    document.getElementById('ck-formula').addEventListener('change', function (e) {
      document.getElementById('ck-secondary-box').hidden = (e.target.value === 'single');
    });
    document.getElementById('ck-entity-1').addEventListener('change', function (e) {
      populateFieldSelect(document.getElementById('ck-field-1'), e.target.value, false);
    });
    document.getElementById('ck-entity-2').addEventListener('change', function (e) {
      populateFieldSelect(document.getElementById('ck-field-2'), e.target.value, false);
    });

    document.getElementById('tb-base-entity').addEventListener('change', async function (e) {
      const base = e.target.value;
      const ent = STATE.entityMap[base];
      STATE.tbCols = [
        { id: 'c0', entity: base, field: (ent.fields[1] || ent.fields[0]).name, aggregation: '', label: (ent.fields[1] || ent.fields[0]).label_ar },
        { id: 'c1', entity: base, field: 'id', aggregation: 'count', label: 'العدد' },
      ];
      await refreshTableCompatibility(base);
    });

    document.getElementById('btn-tb-add-col').addEventListener('click', function () {
      const base = document.getElementById('tb-base-entity').value;
      const ent = STATE.entityMap[base];
      STATE.tbCols.push({ id: 'c_' + Date.now(), entity: base, field: ent.fields[0].name, aggregation: '', label: ent.fields[0].label_ar });
      renderTableColsBuilder();
    });

    document.getElementById('ch-base-entity').addEventListener('change', async function (e) {
      const base = e.target.value;
      STATE.chMeasures = [{ entity: base, field: 'id', aggregation: 'count', label: 'العدد' }];
      await refreshChartCompatibility(base);
    });
    document.getElementById('ch-dim-entity').addEventListener('change', function (e) {
      populateFieldSelect(document.getElementById('ch-dim-field'), e.target.value, false);
    });
    document.getElementById('btn-ch-add-measure').addEventListener('click', function () {
      const base = document.getElementById('ch-base-entity').value;
      STATE.chMeasures.push({ entity: base, field: 'id', aggregation: 'count', label: 'مقياس جديد' });
      renderChartMeasuresBuilder();
    });

    // Live previews
    document.getElementById('btn-preview-ck').addEventListener('click', async function () {
      const box = document.getElementById('ck-preview-box');
      box.innerHTML = '<div class="fx-skeleton"></div>';
      try {
        const built = buildWidgetConfigFromModal();
        const res = await apiFetch(URLS.query, { method: 'POST', body: { widget_type: 'custom_kpi', config: built.config, global_filters: STATE.activeFilters } });
        renderWidgetBody({ widget_type: 'custom_kpi', config: built.config }, res.data, STATE.activeFilters, box);
      } catch (err) { box.innerHTML = '<div class="fx-error">' + err.message + '</div>'; }
    });

    document.getElementById('btn-preview-table').addEventListener('click', async function () {
      const box = document.getElementById('tb-preview-box');
      box.innerHTML = '<div class="fx-skeleton"></div>';
      try {
        const built = buildWidgetConfigFromModal();
        const res = await apiFetch(URLS.query, { method: 'POST', body: { widget_type: 'table', config: built.config, global_filters: STATE.activeFilters } });
        renderDataTable(box, res.data, null);
      } catch (err) { box.innerHTML = '<div class="fx-error">' + err.message + '</div>'; }
    });

    document.getElementById('btn-preview-chart').addEventListener('click', async function () {
      const box = document.getElementById('ch-preview-box');
      box.innerHTML = '<div class="fx-skeleton"></div>';
      try {
        const built = buildWidgetConfigFromModal();
        const res = await apiFetch(URLS.query, { method: 'POST', body: { widget_type: 'chart', config: built.config, global_filters: STATE.activeFilters } });
        window.MakkenFlexCharts.renderChart(box, res.data, null);
      } catch (err) { box.innerHTML = '<div class="fx-error">' + err.message + '</div>'; }
    });

    document.getElementById('btn-wm-commit').addEventListener('click', function () {
      try {
        const built = buildWidgetConfigFromModal();
        const secIdx = Number(document.getElementById('wm-section-select').value || 0);
        const title = document.getElementById('wm-widget-title').value.trim() || 'عنصر تحليلي';
        const subtitle = document.getElementById('wm-widget-subtitle').value.trim();
        const colSpan = Number(document.getElementById('wm-col-span').value || 6);
        const rowSpan = (built.widget_type === 'kpi' || built.widget_type === 'custom_kpi') ? 1 : 2;
        const widgetObj = {
          widget_type: built.widget_type,
          title: title,
          subtitle: subtitle,
          col_span: colSpan,
          row_span: rowSpan,
          config: built.config,
          is_visible: true,
        };
        if (STATE.wmEditing) {
          STATE.draft.sections[STATE.wmEditing.sIdx].widgets[STATE.wmEditing.wIdx] = widgetObj;
        } else {
          STATE.draft.sections[secIdx].widgets.push(widgetObj);
        }
        pushHistory();
        renderCanvas();
        document.getElementById('flex-widget-modal').close();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    window.addEventListener('beforeunload', function (e) {
      if (STATE.editMode && STATE.dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  }

  bindEvents();
  loadBootstrap(null);
})();
