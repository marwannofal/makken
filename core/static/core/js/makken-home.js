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
