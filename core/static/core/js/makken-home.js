(() => {
  "use strict";
  const drawer = document.querySelector("#mobile-sidebar");
  const trigger = document.querySelector("[data-menu-open]");
  if (drawer && trigger && typeof drawer.showModal === "function") {
    document.documentElement.setAttribute("data-sidebar-enhanced", "true");
    trigger.hidden = false;
    const close = () => { if (drawer.open) drawer.close(); };
    trigger.addEventListener("click", () => {
      if (drawer.open) return;
      drawer.showModal();
      trigger.setAttribute("aria-expanded", "true");
      document.documentElement.classList.add("menu-is-open");
    });
    drawer.querySelector("[data-menu-close]").addEventListener("click", close);
    drawer.addEventListener("click", event => {
      if (event.target !== drawer) return;
      const box = drawer.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close();
    });
    drawer.addEventListener("close", () => {
      trigger.setAttribute("aria-expanded", "false");
      document.documentElement.classList.remove("menu-is-open");
      if (trigger.getClientRects().length) trigger.focus();
    });
    const desktop = window.matchMedia("(min-width: 901px)");
    desktop.addEventListener("change", event => { if (event.matches) close(); });
  }
  document.querySelectorAll(".logout-form").forEach(form => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button");
      button.disabled = true;
      button.querySelector("span").textContent = "جار تسجيل الخروج…";
    });
  });
  window.addEventListener("pageshow", () => {
    document.querySelectorAll(".logout-form button").forEach(button => {
      button.disabled = false;
      button.querySelector("span").textContent = "تسجيل الخروج";
    });
  });
})();


(function () {
  const clockEl = document.querySelector('[data-makken-clock]');
  if (!clockEl) return;
  const days = ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'];
  function renderClock() {
    const now = new Date();
    try {
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Riyadh',
        weekday: 'short',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
      }).formatToParts(now);
      const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
      const wkIdx = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(map.weekday);
      const arDay = wkIdx >= 0 ? days[wkIdx] : '';
      const period = (map.dayPeriod || '').toLowerCase() === 'pm' ? 'م' : 'ص';
      clockEl.textContent = `${arDay} ${map.day}/${map.month}/${map.year} — ${map.hour}:${map.minute} ${period}`;
    } catch {
      const d = String(now.getDate()).padStart(2, '0');
      const m = String(now.getMonth() + 1).padStart(2, '0');
      const y = now.getFullYear();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      clockEl.textContent = `${d}/${m}/${y} — ${hh}:${mm}`;
    }
  }
  renderClock();
  setInterval(renderClock, 15000);
})();


(function () {
  const btn = document.querySelector('[data-sidebar-toggle]');
  if (!btn) return;
  const KEY = 'makken_sidebar_collapsed_v1';

  function applyState(collapsed) {
    document.body.classList.toggle('mk-sidebar-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.setAttribute('aria-label', collapsed ? 'إظهار القائمة الجانبية' : 'إخفاء القائمة الجانبية');
    btn.setAttribute('title', collapsed ? 'إظهار القائمة الجانبية' : 'إخفاء القائمة الجانبية');
  }

  try {
    if (localStorage.getItem(KEY) === '1') applyState(true);
  } catch {}

  btn.addEventListener('click', () => {
    const next = !document.body.classList.contains('mk-sidebar-collapsed');
    applyState(next);
    try { localStorage.setItem(KEY, next ? '1' : '0'); } catch {}
  });
})();

/* Topbar Greeting Dropdown Menu */
(function () {
  var menu = document.querySelector("[data-account-menu]");
  if (!menu) return;
  var trigger = menu.querySelector("[data-account-menu-trigger]");
  var panel = menu.querySelector("[data-account-menu-panel]");
  if (!trigger || !panel) return;

  function setOpen(open) {
    menu.classList.toggle("is-open", open);
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
    panel.hidden = !open;
  }

  trigger.addEventListener("click", function (e) {
    e.stopPropagation();
    setOpen(panel.hidden);
  });

  document.addEventListener("click", function (e) {
    if (!panel.hidden && !menu.contains(e.target)) {
      setOpen(false);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) {
      setOpen(false);
      trigger.focus();
    }
  });
})();

/* Promote server-opened <dialog class="color-dialog" open> to true modal so ::backdrop blurs & darkens */
(function () {
  function promoteOpenColorDialogs() {
    document.querySelectorAll('dialog.color-dialog[open]').forEach(function (dlg) {
      if (typeof dlg.showModal !== 'function') return;
      try {
        if (dlg.matches(':modal')) return;
      } catch (e) {}
      dlg.removeAttribute('open');
      try {
        dlg.showModal();
      } catch (e) {
        dlg.setAttribute('open', '');
      }
      dlg.addEventListener('cancel', function (ev) {
        var closeLink = dlg.querySelector('a.dialog-close, .dialog-actions a.button-secondary');
        if (closeLink && closeLink.href) {
          ev.preventDefault();
          window.location.assign(closeLink.href);
        }
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', promoteOpenColorDialogs);
  } else {
    promoteOpenColorDialogs();
  }
})();
