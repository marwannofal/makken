(() => {
  "use strict";
  document.querySelectorAll('a[href^="#edit-clause-"]').forEach(link => {
    link.addEventListener("click", () => {
      const panel = document.getElementById(link.hash.slice(1));
      if (panel instanceof HTMLDetailsElement) {
        panel.open = true;
        panel.querySelector("select")?.focus({preventScroll: true});
      }
    });
  });
})();
