/* Makken Profile & Password Page Interactions (CSP-safe) */
(function () {
  "use strict";

  var input = document.querySelector("[data-avatar-input]");
  var wrap = document.querySelector("[data-avatar-preview-wrap]");
  if (input && wrap) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var url = URL.createObjectURL(file);
      var img = wrap.querySelector("[data-avatar-preview-img]");
      if (!img) {
        var initial = wrap.querySelector("[data-avatar-preview-initial]");
        if (initial) initial.remove();
        img = document.createElement("img");
        img.className = "mk-prof-avatar-img";
        img.setAttribute("data-avatar-preview-img", "");
        img.alt = "معاينة الصورة الشخصية";
        wrap.appendChild(img);
      }
      img.src = url;
    });
  }

  document.querySelectorAll("[data-pw-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var field = btn.parentElement && btn.parentElement.querySelector("input");
      if (!field) return;
      var show = field.type === "password";
      field.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "إخفاء كلمة المرور" : "إظهار كلمة المرور");
    });
  });

  var errBox = document.querySelector("[data-profile-errors]");
  if (errBox) {
    errBox.focus();
  }
})();
