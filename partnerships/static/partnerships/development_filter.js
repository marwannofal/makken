"use strict";
document.querySelectorAll("[data-development-filter]").forEach((select) => {
  select.addEventListener("change", () => {
    if (select.form) select.form.requestSubmit();
  });
});
