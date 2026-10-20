(() => {
  "use strict";
  const editor = document.querySelector("#sponsorship-shape-editor");
  if (!editor || typeof editor.showModal !== "function") return;
  document.documentElement.setAttribute("data-color-enhanced", "true");
  const form = editor.querySelector("form");
  document.querySelectorAll(".sidebar-navigation .nav-link[aria-current=page]").forEach(link => {
    const navigation = link.closest(".sidebar-navigation");
    if (!navigation.clientHeight) return;
    const bounds = navigation.getBoundingClientRect(), item = link.getBoundingClientRect();
    if (item.bottom > bounds.bottom) navigation.scrollTop += item.bottom - bounds.bottom + 10;
    else if (item.top < bounds.top) navigation.scrollTop -= bounds.top - item.top + 10;
  });
  let opener = null;
  const open = dialog => {
    if (dialog.open) dialog.removeAttribute("open");
    dialog.showModal();
    document.documentElement.classList.add("color-dialog-open");
  };
  const showEditor = (link, edit) => {
    opener = link;
    form.elements.namedItem("operation").value = edit ? "edit" : "add";
    form.elements.namedItem("snapshot").value = link.dataset.snapshot;
    form.elements.namedItem("name").value = edit ? link.dataset.name : "";
    form.elements.namedItem("description").value = edit ? link.dataset.description : "";
    form.elements.namedItem("is_employment").value = edit ? link.dataset.employment : "0";
    form.elements.namedItem("is_active").value = edit ? link.dataset.active : "1";
    form.querySelector("[data-editor-title]").textContent = edit ? "تعديل شكل الرعاية" : "إضافة شكل رعاية جديد";
    form.querySelector("#name-error").textContent = "";
    form.querySelector("#description-error").textContent = "";
    form.elements.namedItem("name").setCustomValidity("");
    open(editor);
    form.elements.namedItem("name").focus();
  };
  document.querySelectorAll("[data-add-sponsorship-shape], [data-edit-sponsorship-shape]").forEach(link => link.addEventListener("click", event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    showEditor(link, link.hasAttribute("data-edit-sponsorship-shape"));
  }));
  document.querySelectorAll("[data-close-sponsorship-shape]").forEach(link => link.addEventListener("click", event => {
    if (editor.hasAttribute("data-return-on-close")) return;
    event.preventDefault();
    editor.close();
  }));
  document.querySelectorAll("[data-sponsorship-shape-dialog]").forEach(dialog => {
    dialog.addEventListener("click", event => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    });
    dialog.addEventListener("close", () => {
      document.documentElement.classList.remove("color-dialog-open");
      if (dialog.hasAttribute("data-return-on-close")) window.location.assign(form.getAttribute("action"));
      else if (opener) opener.focus();
    });
    if (dialog.open) open(dialog);
  });
  document.querySelectorAll("[data-confirm-form]").forEach(confirmForm => confirmForm.addEventListener("submit", () => {
    const button = confirmForm.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "جار التنفيذ…";
  }));
  window.addEventListener("pageshow", () => {
    const button = document.querySelector("[data-confirm-form] button[type=submit]");
    if (button) { button.disabled = false; button.textContent = button.dataset.confirmLabel; }
  });
})();
