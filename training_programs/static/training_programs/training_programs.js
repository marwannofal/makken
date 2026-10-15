(() => {
  "use strict";
  const editor = document.querySelector("#program-editor");
  if (!editor) return;
  const form = editor.querySelector("form");
  const select = form.elements.namedItem("expense_items");
  const multi = editor.querySelector("[data-multi-select]");
  const trigger = multi.querySelector("[data-multi-trigger]");
  const panel = multi.querySelector(".multi-panel");
  const search = multi.querySelector("[data-multi-search]");
  const options = multi.querySelector("[data-multi-options]");
  const tags = multi.querySelector("[data-selected-tags]");
  const summary = multi.querySelector("[data-multi-summary]");
  const error = editor.querySelector("[data-multi-error]");
  const entries = [...select.options].map(option => ({option, label: null, checkbox: null}));
  const normalize = text => text.normalize("NFKC").toLocaleLowerCase("ar").replace(/[\u064b-\u065f\u0670\u0640]/g, "").replace(/[أإآ]/g, "ا").replace(/ى/g, "ي").trim();
  const selected = () => entries.filter(entry => entry.option.selected);
  const closePanel = (focus = false) => {
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (focus) trigger.focus();
  };
  const filter = () => {
    const query = normalize(search.value);
    let visible = 0;
    entries.forEach(entry => {
      entry.label.hidden = !normalize(entry.option.textContent).includes(query);
      if (!entry.label.hidden) visible++;
    });
    multi.querySelector("[data-multi-empty]").hidden = visible > 0 || !entries.length;
  };
  const refresh = () => {
    const items = selected();
    summary.textContent = items.length ? `عدد البنود المختارة: ${items.length}` : "اختر بنود الصرف";
    multi.querySelector("[data-multi-count]").textContent = `${items.length} محدد من ${entries.length} بند صرف`;
    tags.replaceChildren();
    items.forEach(entry => {
      const tag = document.createElement("span");
      tag.className = "selected-tag";
      const text = document.createElement("span");
      text.textContent = entry.option.textContent;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "إزالة " + entry.option.textContent);
      remove.addEventListener("click", () => {
        entry.option.selected = false;
        entry.checkbox.checked = false;
        refresh();
        trigger.focus();
      });
      tag.append(text, remove);
      tags.append(tag);
    });
    if (items.length) {
      error.textContent = "";
      trigger.removeAttribute("aria-invalid");
    }
  };
  entries.forEach(entry => {
    const label = document.createElement("label");
    label.className = "multi-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = entry.option.selected;
    checkbox.dataset.expenseItemId = entry.option.value;
    const text = document.createElement("span");
    text.textContent = entry.option.textContent;
    label.append(checkbox, text);
    entry.label = label;
    entry.checkbox = checkbox;
    checkbox.addEventListener("change", () => {
      entry.option.selected = checkbox.checked;
      refresh();
    });
    options.append(label);
  });
  trigger.addEventListener("click", () => {
    if (!panel.hidden) { closePanel(); return; }
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    search.value = "";
    filter();
    search.focus();
  });
  search.addEventListener("input", filter);
  search.addEventListener("keydown", event => {
    if (event.key === "Enter") event.preventDefault();
    if (event.key === "ArrowDown") {
      const first = entries.find(entry => !entry.label.hidden);
      if (first) { event.preventDefault(); first.checkbox.focus(); }
    }
  });
  panel.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closePanel(true);
    }
  });
  editor.addEventListener("cancel", event => {
    if (!panel.hidden) { event.preventDefault(); closePanel(true); }
  });
  document.addEventListener("click", event => { if (!multi.contains(event.target)) closePanel(); });
  form.addEventListener("submit", event => {
    if (!selected().length) {
      event.preventDefault();
      error.textContent = "اختر بند صرفًا واحدًا على الأقل.";
      trigger.setAttribute("aria-invalid", "true");
      trigger.focus();
    }
  });
  const typeOptions = [...form.querySelectorAll('input[name="training_types"]')];
  const typeError = form.querySelector("[data-types-error]");
  form.addEventListener("submit", event => {
    if (!typeOptions.some(checkbox => checkbox.checked)) {
      event.preventDefault();
      typeError.textContent = "اختر نوع تدريب واحدًا فقط.";
      if (selected().length) typeOptions[0].focus();
    }
  });
  typeOptions.forEach(checkbox => checkbox.addEventListener("change", () => {
    if (typeOptions.some(item => item.checked)) typeError.textContent = "";
  }));
  // Preserve an accessible native multiple select if JavaScript is disabled.
  select.required = false;
  select.dataset.enhanced = "true";
  multi.hidden = false;
  multi.querySelector("[data-multi-availability]").hidden = entries.length > 0;
  editor.querySelector('label[for="program-expense-items"]').addEventListener("click", event => { event.preventDefault(); trigger.focus(); });
  refresh();
  if (typeof editor.showModal !== "function") return;
  document.documentElement.setAttribute("data-color-enhanced", "true");
  document.querySelectorAll("[data-program-dialog]").forEach(dialog => {
    dialog.addEventListener("click", event => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    });
    dialog.addEventListener("close", () => {
      document.documentElement.classList.remove("color-dialog-open");
      if (dialog.hasAttribute("data-return-on-close")) window.location.assign(form.getAttribute("action"));
    });
    if (dialog.open) {
      dialog.removeAttribute("open");
      dialog.showModal();
      document.documentElement.classList.add("color-dialog-open");
    }
  });
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
