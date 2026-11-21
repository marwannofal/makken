(() => {
  "use strict";

  const expiry = (start, length) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !Number.isInteger(length) || length < 1 || length > 600) return "—";
    const [year, month, day] = start.split("-").map(Number);
    const offset = year * 12 + month - 1 + length;
    const endYear = Math.floor(offset / 12);
    const endMonth = offset % 12 + 1;
    if (year < 1 || endYear > 9999) return "—";
    const leap = endYear % 4 === 0 && (endYear % 100 !== 0 || endYear % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][endMonth - 1];
    return [String(Math.min(day, days)).padStart(2, "0"), String(endMonth).padStart(2, "0"), String(endYear).padStart(4, "0")].join("/");
  };

  for (const section of document.querySelectorAll("[data-agreement-period]")) {
    const start = section.querySelector("#id_signed_on");
    const months = section.querySelector('input[name$="duration_months"]');
    const output = section.querySelector("[data-expiry-preview]");
    if (!months || !output) continue;
    const update = () => { output.value = expiry(start?.value || section.dataset.startDate || "", Number(months.value)); };
    section.addEventListener("input", update);
    update();
  }

  for (const section of document.querySelectorAll("[data-agreement-team]")) {
    const add = section.querySelector("[data-add-member]");
    const template = section.querySelector("[data-empty-member]");
    const container = section.querySelector("[data-team-members]");
    const total = section.querySelector('input[name$="-TOTAL_FORMS"]');
    const feedback = section.querySelector("[data-team-feedback]");
    if (!add || !template || !container || !total || !feedback) continue;
    add.hidden = false;
    add.addEventListener("click", () => {
      const current = Number(total.value);
      const removed = container.querySelectorAll('input[name$="-DELETE"]:checked').length;
      if (current - removed >= 30 || current >= 60) {
        feedback.textContent = "الحد الأقصى 30 عضوًا محفوظًا لكل فريق. احفظ تعديلاتك قبل الإضافة مجددًا.";
        return;
      }
      const fragment = template.content.cloneNode(true);
      for (const field of fragment.querySelectorAll("[name], [id], [for]")) {
        for (const attr of ["name", "id", "for"]) {
          if (field.hasAttribute(attr)) field.setAttribute(attr, field.getAttribute(attr).replaceAll("__prefix__", String(current)));
        }
      }
      const focus = fragment.querySelector('input[name$="-name"]');
      container.append(fragment);
      total.value = String(current + 1);
      feedback.textContent = "أُضيفت حقول عضو جديد. احفظ الاتفاقية لتسجيله.";
      focus?.focus();
    });
  }
})();
