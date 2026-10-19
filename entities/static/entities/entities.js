(() => {
  "use strict";
  const editor = document.querySelector("#entity-editor");
  if (!editor || typeof editor.showModal !== "function") return;
  document.documentElement.setAttribute("data-color-enhanced", "true");
  const form = editor.querySelector("form");
  const kind = form.elements.namedItem("entity_type");
  const branch = form.elements.namedItem("branch");
  const branchField = document.querySelector("#entity-branch-field");
  const syncBranch = () => {
    const required = kind.value === "non_government";
    branchField.hidden = !required;
    branch.disabled = !required;
    branch.required = required;
    if (!required) branch.value = "";
  };
  kind.addEventListener("change", syncBranch);
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
    form.elements.namedItem("is_active").value = edit ? link.dataset.active : "1";
    kind.value = edit ? link.dataset.kind : "government";
    branch.value = edit ? link.dataset.branch : "";
    syncBranch();
    form.querySelector("[data-editor-title]").textContent = edit ? "تعديل الكيان" : "إضافة كيان جديد";
    form.querySelectorAll(".field-error").forEach(field => { field.textContent = ""; });
    open(editor);
    kind.focus();
  };
  document.querySelectorAll("[data-add-entity], [data-edit-entity]").forEach(link => link.addEventListener("click", event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    showEditor(link, link.hasAttribute("data-edit-entity"));
  }));
  document.querySelectorAll("[data-close-entity]").forEach(link => link.addEventListener("click", event => {
    if (editor.hasAttribute("data-return-on-close")) return;
    event.preventDefault();
    editor.close();
  }));
  document.querySelectorAll("[data-entity-dialog]").forEach(dialog => {
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
  syncBranch();
  document.querySelectorAll("[data-confirm-form]").forEach(confirmForm => confirmForm.addEventListener("submit", () => {
    const button = confirmForm.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "جارٍ التنفيذ…";
  }));
  window.addEventListener("pageshow", () => {
    const button = document.querySelector("[data-confirm-form] button[type=submit]");
    if (button) { button.disabled = false; button.textContent = button.dataset.confirmLabel; }
  });
})();
