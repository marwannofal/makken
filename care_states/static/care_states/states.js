(() => {
  "use strict";
  const editor = document.querySelector("#color-editor");
  if (!editor || typeof editor.showModal !== "function") return;
  document.documentElement.setAttribute("data-color-enhanced", "true");
  const form = editor.querySelector("form");
  const picker = form.querySelector("[data-color-picker]");
  const hex = form.querySelector("[data-color-hex]");
  let opener = null;
  const open = dialog => {
    if (dialog.open) dialog.removeAttribute("open");
    dialog.showModal();
    document.documentElement.classList.add("color-dialog-open");
  };
  document.querySelectorAll("[data-edit-color]").forEach(link => {
    link.addEventListener("click", event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      opener = link;
      form.elements.state.value = link.dataset.state;
      form.elements.snapshot.value = link.dataset.snapshot;
      picker.value = link.dataset.color;
      hex.value = link.dataset.color;
      hex.setCustomValidity("");
      editor.querySelector("[data-edit-label]").textContent = link.dataset.label;
      open(editor);
      hex.focus();
    });
  });
  picker.addEventListener("input", () => { hex.value = picker.value.toUpperCase(); hex.setCustomValidity(""); });
  hex.addEventListener("input", () => {
    hex.setCustomValidity("");
    if (/^#[0-9a-fA-F]{6}$/.test(hex.value)) picker.value = hex.value;
  });
  hex.addEventListener("invalid", () => hex.setCustomValidity("أدخل لونًا صحيحًا مثل #24B3AF."));
  document.querySelectorAll("[data-close-editor]").forEach(link => link.addEventListener("click", event => {
    if (editor.hasAttribute("data-return-on-close")) return;
    event.preventDefault();
    editor.close();
  }));
  document.querySelectorAll("[data-color-dialog]").forEach(dialog => {
    dialog.addEventListener("click", event => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    });
    dialog.addEventListener("close", () => {
      document.documentElement.classList.remove("color-dialog-open");
      if (dialog.hasAttribute("data-return-on-close")) {
        window.location.assign(form.getAttribute("action"));
      } else if (opener) opener.focus();
    });
    if (dialog.open) open(dialog);
  });
  document.querySelectorAll("[data-confirm-form]").forEach(confirmForm => {
    confirmForm.addEventListener("submit", () => {
      const button = confirmForm.querySelector("button[type=submit]");
      button.disabled = true;
      button.textContent = "جار الحفظ…";
    });
  });
  window.addEventListener("pageshow", () => {
    const button = document.querySelector("[data-confirm-form] button[type=submit]");
    if (button) { button.disabled = false; button.textContent = "تأكيد التغيير"; }
  });
})();
