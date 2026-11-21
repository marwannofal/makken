/* A retry is a GET navigation: never resubmit an interrupted POST. */
(() => {
  "use strict";
  const root = document.body;
  const timer = document.querySelector("[data-countdown]");
  const progress = document.querySelector("[data-progress]");
  const button = document.querySelector("[data-retry]");
  const label = document.querySelector("[data-retry-label]");
  const toggle = document.querySelector("[data-auto-toggle]");
  const status = document.querySelector("[data-retry-status]");
  const hint = document.querySelector("[data-retry-hint]");
  if (!timer || !progress || !button || !label || !toggle || !status) return;
  const seconds = Math.max(20, Number(root.dataset.retrySeconds) || 20);
  const deadline = Date.now() + seconds * 1000;
  const key = "makken:error-retry:" + window.location.pathname;
  let auto = root.dataset.autoRefresh === "1" && ["GET", "HEAD"].includes(root.dataset.requestMethod);
  let remaining = seconds;
  let navigating = false;
  try {
    const last = Number(sessionStorage.getItem(key) || 0);
    if (last > 0 && Date.now() - last < 120000) {
      auto = false;
      status.textContent = "أجرينا محاولة تلقائية ولم تكتمل. انتظر العدّاد ثم حاول يدويًا، أو تواصل مع مسؤول المنصة إذا استمر الخلل.";
    }
  } catch (_) {
    auto = false;
    status.textContent = "التحديث التلقائي غير متاح في إعدادات هذا المتصفح. يمكنك إعادة فتح الصفحة بعد انتهاء العدّاد.";
  }
  toggle.checked = auto;
  const updateHint = () => {
    if (hint && root.dataset.autoRefresh === "1") {
      hint.textContent = auto ? "ستُفتح الصفحة تلقائيًا بعد انتهاء العدّاد، ويمكنك إيقاف التحديث التلقائي." : "انتظر انتهاء العدّاد ثم أعد فتح الصفحة يدويًا باستخدام الزر أدناه.";
    }
  };
  updateHint();
  const navigate = (automatic) => {
    if (remaining > 0 || navigating) return;
    navigating = true;
    button.disabled = true;
    label.textContent = "جار فتح الصفحة…";
    if (automatic) {
      try { sessionStorage.setItem(key, String(Date.now())); }
      catch (_) {
        navigating = false;
        button.disabled = false;
        label.textContent = "إعادة فتح الصفحة";
        auto = false;
        toggle.checked = false;
        updateHint();
        status.textContent = "تعذّر بدء التحديث التلقائي. استخدم زر إعادة فتح الصفحة للمحاولة يدويًا.";
        return;
      }
    }
    // assign() starts a fresh GET even when this error followed a form POST.
    window.location.assign(window.location.href);
  };
  button.addEventListener("click", () => navigate(false));
  toggle.addEventListener("change", () => {
    auto = toggle.checked;
    updateHint();
    status.textContent = auto ? "سيتم فتح الصفحة تلقائيًا عند انتهاء العدّاد." : "تم إيقاف التحديث التلقائي. استخدم زر إعادة فتح الصفحة عند انتهاء العدّاد.";
  });
  const tick = () => {
    remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    timer.textContent = String(remaining);
    progress.value = remaining;
    if (remaining !== 0) return;
    clearInterval(interval);
    document.removeEventListener("visibilitychange", tick);
    button.disabled = false;
    label.textContent = "إعادة فتح الصفحة";
    status.textContent = "يمكنك الآن إعادة فتح الصفحة. إذا تكرر الخطأ، راجع مسؤول المنصة.";
    if (auto && toggle.checked) navigate(true);
  };
  const interval = setInterval(tick, 250);
  document.addEventListener("visibilitychange", tick);
  tick();
})();
