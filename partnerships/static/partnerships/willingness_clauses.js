(() => {
  'use strict';

  function resetDialogScrollTop() {
    document.querySelectorAll('dialog.willingness-big-dialog[open]').forEach(dlg => {
      dlg.scrollTop = 0;
      const body = dlg.querySelector('.dialog-body');
      if (body) body.scrollTop = 0;
      requestAnimationFrame(() => {
        dlg.scrollTop = 0;
        if (body) body.scrollTop = 0;
      });
    });
  }

  function initExpiryCalculator(root) {
    const signedInput = root.querySelector('[data-signed-on]');
    const monthsInput = root.querySelector('[data-duration-months]');
    const output = root.querySelector('[data-calculated-expiry]');
    if (!signedInput || !monthsInput || !output) return;

    function compute() {
      const rawDate = signedInput.value;
      const months = parseInt(monthsInput.value, 10);
      if (!rawDate || !months || months < 1 || months > 600) {
        output.textContent = 'يُحسب تلقائيًا عند إدخال تاريخ التوقيع والمدة';
        return;
      }
      const parts = rawDate.split('-').map(Number);
      if (parts.length !== 3 || parts.some(Number.isNaN)) return;
      const [y, m, d] = parts;
      const totalMonths = (m - 1) + months;
      const targetYear = y + Math.floor(totalMonths / 12);
      const targetMonth = (totalMonths % 12) + 1;
      const lastDay = new Date(Date.UTC(targetYear, targetMonth, 0)).getUTCDate();
      const targetDay = Math.min(d, lastDay);
      const pad = n => String(n).padStart(2, '0');
      output.textContent = `${pad(targetDay)}/${pad(targetMonth)}/${targetYear}`;
    }

    signedInput.addEventListener('input', compute);
    signedInput.addEventListener('change', compute);
    monthsInput.addEventListener('input', compute);
    monthsInput.addEventListener('change', compute);
    compute();
  }

  function initTeamBuilders(root) {
    const hidden = root.querySelector('[data-teams-input]');
    if (!hidden) return;
    const catalogEl = document.getElementById('clause-catalog-data');
    const catalog = catalogEl ? JSON.parse(catalogEl.textContent || '{}') : {};
    const roles = catalog.team_roles || [
      { value: 'representative', label: 'ممثل' },
      { value: 'lead', label: 'رئيس' },
      { value: 'contact', label: 'ضابط اتصال' },
    ];
    const roleMap = new Map(roles.map(r => [r.value, r.label]));

    let members = [];
    try {
      const parsed = JSON.parse(hidden.value || '[]');
      if (Array.isArray(parsed)) members = parsed;
    } catch {
      members = [];
    }

    const sides = root.querySelectorAll('[data-team-side]');

    function syncAll() {
      hidden.value = JSON.stringify(members);
      sides.forEach(box => {
        const side = box.dataset.teamSide;
        const tbody = box.querySelector('[data-team-tbody]');
        const emptyEl = box.querySelector('[data-team-empty]');
        if (!tbody) return;
        tbody.replaceChildren();
        const sideItems = members.map((m, i) => ({ m, i })).filter(x => x.m.side === side);
        if (emptyEl) emptyEl.hidden = sideItems.length > 0;
        sideItems.forEach(({ m, i }) => {
          const tr = document.createElement('tr');
          const addCell = (text, dir) => {
            const td = document.createElement('td');
            if (dir) td.dir = dir;
            td.textContent = text || '—';
            tr.appendChild(td);
          };
          addCell(m.name);
          addCell(m.phone, 'ltr');
          addCell(m.email, 'ltr');
          addCell(m.organization);
          addCell(roleMap.get(m.role) || m.role);
          const tdAct = document.createElement('td');
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'row-action delete-action';
          btn.textContent = 'حذف';
          btn.addEventListener('click', () => {
            members.splice(i, 1);
            syncAll();
          });
          tdAct.appendChild(btn);
          tr.appendChild(tdAct);
          tbody.appendChild(tr);
        });
      });
    }

    sides.forEach(box => {
      const side = box.dataset.teamSide;
      const roleSelect = box.querySelector('[data-team-role]');
      if (roleSelect && roleSelect.options.length <= 1) {
        roles.forEach(r => {
          const opt = document.createElement('option');
          opt.value = r.value;
          opt.textContent = r.label;
          roleSelect.appendChild(opt);
        });
      }
      const addBtn = box.querySelector('[data-add-team-row]');
      const errEl = box.querySelector('[data-team-error]');
      if (!addBtn) return;
      addBtn.addEventListener('click', () => {
        if (errEl) errEl.textContent = '';
        const nameEl = box.querySelector('[data-team-name]');
        const phoneEl = box.querySelector('[data-team-phone]');
        const emailEl = box.querySelector('[data-team-email]');
        const orgEl = box.querySelector('[data-team-org]');
        const name = (nameEl?.value || '').trim();
        const role = roleSelect?.value || '';
        if (!name) {
          if (errEl) errEl.textContent = 'أدخل اسم العضو أولًا.';
          return;
        }
        if (!role) {
          if (errEl) errEl.textContent = 'اختر صفة العضو.';
          return;
        }
        members.push({
          side,
          name,
          phone: (phoneEl?.value || '').trim(),
          email: (emailEl?.value || '').trim(),
          organization: (orgEl?.value || '').trim(),
          role,
        });
        if (nameEl) nameEl.value = '';
        if (phoneEl) phoneEl.value = '';
        if (emailEl) emailEl.value = '';
        if (orgEl) orgEl.value = '';
        if (roleSelect) roleSelect.value = '';
        syncAll();
      });
    });

    syncAll();
  }

  function initClauseBuilder(root) {
    const catalogEl = document.getElementById(root.dataset.clauseCatalog || 'clause-catalog-data');
    if (!catalogEl) return;
    const catalog = JSON.parse(catalogEl.textContent || '{}');
    const clauses = catalog.clauses || [];
    const responsibilities = catalog.responsibilities || [];
    const allowProgress = root.dataset.allowProgress === '1';

    const hiddenInput = root.querySelector('[data-clauses-input]');
    const clauseSelect = root.querySelector('[data-clause-select]');
    const respSelect = root.querySelector('[data-responsibility-select]');
    const addBtn = root.querySelector('[data-add-clause-row]');
    const tbody = root.querySelector('[data-clauses-tbody]');
    const emptyEl = root.querySelector('[data-clauses-empty]');
    const errorEl = root.querySelector('[data-clauses-error]');
    const avgBadge = document.querySelector('[data-clauses-avg]');

    if (!hiddenInput || !clauseSelect || !respSelect || !addBtn || !tbody) return;

    const clauseMap = new Map(clauses.map(c => [String(c.id), c]));
    const respMap = new Map(responsibilities.map(r => [String(r.value), r.label]));

    clauses.forEach(c => {
      if (!c.is_active) return;
      const opt = document.createElement('option');
      opt.value = String(c.id);
      opt.textContent = c.name;
      clauseSelect.appendChild(opt);
    });
    responsibilities.forEach(r => {
      const opt = document.createElement('option');
      opt.value = String(r.value);
      opt.textContent = r.label;
      respSelect.appendChild(opt);
    });

    let rows = [];
    try {
      const parsed = JSON.parse(hiddenInput.value || '[]');
      if (Array.isArray(parsed)) rows = parsed;
    } catch {
      rows = [];
    }

    function sync() {
      const serialized = rows.map(r => ({
        clause_id: Number(r.clause_id),
        responsibility: String(r.responsibility),
        ...(allowProgress ? { progress: Math.max(0, Math.min(100, Number(r.progress) || 0)) } : {}),
      }));
      hiddenInput.value = JSON.stringify(serialized);
      tbody.replaceChildren();
      if (emptyEl) emptyEl.hidden = rows.length > 0;

      if (avgBadge) {
        if (!rows.length) {
          avgBadge.textContent = '0%';
        } else {
          const sum = rows.reduce((acc, r) => acc + (Math.max(0, Math.min(100, Number(r.progress) || 0))), 0);
          avgBadge.textContent = (sum / rows.length).toFixed(2).replace(/\.00$/, '') + '%';
        }
      }

      rows.forEach((row, idx) => {
        const tr = document.createElement('tr');

        const tdName = document.createElement('th');
        tdName.scope = 'row';
        const info = clauseMap.get(String(row.clause_id));
        const numBadge = document.createElement('span');
        numBadge.className = 'mk-clause-num';
        numBadge.textContent = String(idx + 1);
        const nameText = document.createTextNode(row.clause_name || (info ? info.name : '#' + row.clause_id));
        tdName.append(numBadge, nameText);
        tr.appendChild(tdName);

        const tdResp = document.createElement('td');
        const sel = document.createElement('select');
        sel.className = 'clause-inline-select';
        sel.setAttribute('aria-label', 'المسؤولية');
        responsibilities.forEach(r => {
          const o = document.createElement('option');
          o.value = r.value;
          o.textContent = r.label;
          if (r.value === row.responsibility) o.selected = true;
          sel.appendChild(o);
        });
        sel.addEventListener('change', () => {
          rows[idx].responsibility = sel.value;
          sync();
        });
        tdResp.appendChild(sel);
        tr.appendChild(tdResp);

        if (allowProgress) {
          const tdProg = document.createElement('td');
          const wrap = document.createElement('div');
          wrap.className = 'clause-progress-wrap';
          const num = document.createElement('input');
          num.type = 'number';
          num.min = '0';
          num.max = '100';
          num.step = '1';
          num.className = 'clause-progress-input';
          num.value = String(Math.max(0, Math.min(100, Number(row.progress) || 0)));
          num.setAttribute('aria-label', 'نسبة الإنجاز');
          num.addEventListener('input', () => {
            let val = parseInt(num.value, 10);
            if (Number.isNaN(val)) val = 0;
            val = Math.max(0, Math.min(100, val));
            rows[idx].progress = val;
            hiddenInput.value = JSON.stringify(rows.map(r => ({
              clause_id: Number(r.clause_id),
              responsibility: String(r.responsibility),
              progress: Math.max(0, Math.min(100, Number(r.progress) || 0)),
            })));
            if (avgBadge && rows.length) {
              const sum = rows.reduce((acc, r) => acc + (Math.max(0, Math.min(100, Number(r.progress) || 0))), 0);
              avgBadge.textContent = (sum / rows.length).toFixed(2).replace(/\.00$/, '') + '%';
            }
          });
          const pct = document.createElement('span');
          pct.textContent = '%';
          wrap.append(num, pct);
          tdProg.appendChild(wrap);
          tr.appendChild(tdProg);
        }

        const tdAct = document.createElement('td');
        const rm = document.createElement('button');
        rm.type = 'button';
        rm.className = 'row-action delete-action';
        rm.textContent = 'حذف';
        rm.addEventListener('click', () => {
          rows.splice(idx, 1);
          if (errorEl) errorEl.textContent = '';
          sync();
        });
        tdAct.appendChild(rm);
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
      });
    }

    addBtn.addEventListener('click', () => {
      if (errorEl) errorEl.textContent = '';
      const cid = clauseSelect.value;
      const resp = respSelect.value;
      if (!cid) {
        if (errorEl) errorEl.textContent = 'اختر بند الاتفاقية أولًا.';
        return;
      }
      if (!resp || !respMap.has(resp)) {
        if (errorEl) errorEl.textContent = 'اختر المسؤولية للبند.';
        return;
      }
      if (rows.some(r => String(r.clause_id) === String(cid))) {
        if (errorEl) errorEl.textContent = 'هذا البند مضاف بالفعل.';
        return;
      }
      const info = clauseMap.get(String(cid));
      rows.push({
        clause_id: Number(cid),
        clause_name: info ? info.name : '',
        responsibility: resp,
        progress: 0,
      });
      clauseSelect.value = '';
      respSelect.value = '';
      sync();
    });

    sync();
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-clause-builder]').forEach(initClauseBuilder);
    document.querySelectorAll('[data-expiry-scope]').forEach(initExpiryCalculator);
    document.querySelectorAll('[data-teams-scope]').forEach(initTeamBuilders);
    resetDialogScrollTop();
  });
})();
