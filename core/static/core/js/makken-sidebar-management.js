(() => {
  "use strict";
  const reveal = navigation => {
    if (!navigation || !navigation.clientHeight) return;
    const active = navigation.querySelector('.nav-link[aria-current="page"]');
    if (!active || !active.getClientRects().length) return;
    const item = active.getBoundingClientRect(), box = navigation.getBoundingClientRect();
    if (item.bottom > box.bottom) navigation.scrollTop += item.bottom - box.bottom + 10;
    else if (item.top < box.top) navigation.scrollTop -= box.top - item.top + 10;
  };
  document.querySelectorAll("[data-management-group]").forEach(group => {
    group.addEventListener("toggle", () => {
      if (group.open) requestAnimationFrame(() => reveal(group.closest(".sidebar-navigation")));
    });
  });
  const trigger = document.querySelector("[data-menu-open]");
  if (trigger) trigger.addEventListener("click", () => {
    requestAnimationFrame(() => reveal(document.querySelector("#mobile-sidebar .sidebar-navigation")));
  });
  requestAnimationFrame(() => document.querySelectorAll(".sidebar-navigation").forEach(reveal));
})();
