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
