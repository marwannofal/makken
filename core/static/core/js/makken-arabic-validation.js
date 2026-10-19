(() => {
  "use strict";
  if (document.documentElement.dataset.makkenArabicValidation === "ready") return;
  document.documentElement.dataset.makkenArabicValidation = "ready";
  const ownedMessages = new WeakMap();
  const isField = field => field instanceof HTMLInputElement ||
    field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement;

  function nativeMessage(field) {
    const state = field.validity;
    if (state.valueMissing) {
      if (field instanceof HTMLSelectElement) {
        return field.multiple ? "اختر خيارًا واحدًا على الأقل." : "اختر قيمة من القائمة.";
      }
      if (field.type === "checkbox") return "يجب تحديد هذا الخيار للمتابعة.";
      if (field.type === "radio") return "اختر أحد الخيارات.";
      if (field.type === "file") return "اختر ملفًا للمتابعة.";
      return "هذا الحقل مطلوب.";
    }
    if (state.typeMismatch) {
      if (field.type === "email") return "أدخل بريدًا إلكترونيًا صحيحًا، مثل name@example.com.";
      if (field.type === "url") return "أدخل رابطًا صحيحًا وكاملًا، مثل https://example.com.";
      return "أدخل قيمة صحيحة لهذا الحقل.";
    }
    if (state.badInput) return field.type === "number" ? "أدخل رقمًا صحيحًا." : "أدخل قيمة صحيحة لهذا الحقل.";
    if (state.patternMismatch) return "أدخل القيمة بالتنسيق المطلوب لهذا الحقل.";
    if (state.tooShort) return `أدخل ${field.minLength} أحرف على الأقل.`;
    if (state.tooLong) return `الحد الأقصى المسموح هو ${field.maxLength} حرفًا.`;
    if (state.rangeUnderflow) return `يجب ألا تقل القيمة عن ${field.min}.`;
    if (state.rangeOverflow) return `يجب ألا تزيد القيمة على ${field.max}.`;
    if (state.stepMismatch) return "أدخل قيمة توافق الزيادة المسموح بها في هذا الحقل.";
    return "";
  }

  function localize(field) {
    if (!isField(field)) return;
    const previous = ownedMessages.get(field);
    // Form-specific validators own their errors (password confirmation, money,
    // attachments, etc.); never clear or replace those messages here.
    if (field.validity.customError && field.validationMessage !== previous) return;
    if (previous !== undefined) {
      field.setCustomValidity("");
      ownedMessages.delete(field);
    }
    if (!field.willValidate) return;
    const message = nativeMessage(field);
    if (message) {
      field.setCustomValidity(message);
      ownedMessages.set(field, message);
    }
  }

  // Capture invalid: it does not bubble. Native tooltips and existing inline
  // handlers receive the Arabic message, including dynamically-created fields.
  document.addEventListener("invalid", event => localize(event.target), true);
  document.addEventListener("input", event => localize(event.target), true);
  document.addEventListener("change", event => localize(event.target), true);
  document.addEventListener("reset", event => {
    if (!(event.target instanceof HTMLFormElement)) return;
    for (const field of event.target.elements) {
      if (!isField(field)) continue;
      const previous = ownedMessages.get(field);
      if (previous !== undefined && field.validationMessage === previous) field.setCustomValidity("");
      ownedMessages.delete(field);
    }
  }, true);
})();
