"use strict";

(() => {
    const form = document.querySelector("[data-login-form]");
    if (!form) return;
    const username = form.elements.username;
    const password = form.elements.password;
    const toggle = form.querySelector("[data-password-toggle]");
    const submit = form.querySelector("[data-submit]");
    const label = form.querySelector("[data-submit-label]");
    const status = form.querySelector("[data-submit-status]");
    const caps = form.querySelector("[data-caps-hint]");

    const resetButton = () => {
        submit.disabled = false;
        label.textContent = "تسجيل الدخول";
        status.textContent = "";
        form.removeAttribute("aria-busy");
    };

    window.addEventListener("pageshow", resetButton);
    if (toggle) {
        toggle.hidden = false;
        toggle.addEventListener("click", () => {
            const reveal = password.type === "password";
            const start = password.selectionStart;
            const end = password.selectionEnd;
            password.type = reveal ? "text" : "password";
            toggle.setAttribute("aria-pressed", String(reveal));
            toggle.setAttribute("aria-label", reveal ? "إخفاء كلمة المرور" : "إظهار كلمة المرور");
            password.focus({ preventScroll: true });
            try {
                if (start !== null && end !== null) password.setSelectionRange(start, end);
            } catch (_) {
                // Selection APIs can be unavailable on older mobile browsers.
            }
        });
    }
    ["keyup", "keydown"].forEach((event) => {
        password.addEventListener(event, (e) => {
            caps.hidden = !e.getModifierState || !e.getModifierState("CapsLock");
        });
    });
    password.addEventListener("blur", () => { caps.hidden = true; });

    const showError = (input, message) => {
        const error = document.getElementById(input.name + "-error");
        error.textContent = message;
        error.hidden = !message;
        if (message) input.setAttribute("aria-invalid", "true");
        else input.removeAttribute("aria-invalid");
    };
    [username, password].forEach((input) => {
        input.addEventListener("input", () => showError(input, ""));
    });
    form.addEventListener("submit", (event) => {
        let firstInvalid = null;
        showError(username, "");
        showError(password, "");
        if (!username.value.trim()) {
            showError(username, "أدخل البريد الإلكتروني أو اسم المستخدم.");
            firstInvalid = username;
        } else if (username.value.length > 254) {
            showError(username, "يجب ألا تتجاوز البيانات 254 حرفًا.");
            firstInvalid = username;
        }
        if (!password.value) {
            showError(password, "أدخل كلمة المرور.");
            firstInvalid = firstInvalid || password;
        } else if (password.value.length > 1024) {
            showError(password, "كلمة المرور أطول من الحد المسموح.");
            firstInvalid = firstInvalid || password;
        }
        if (firstInvalid) {
            event.preventDefault();
            firstInvalid.focus();
            return;
        }
        password.type = "password";
        toggle.setAttribute("aria-pressed", "false");
        toggle.setAttribute("aria-label", "إظهار كلمة المرور");
        submit.disabled = true;
        form.setAttribute("aria-busy", "true");
        label.textContent = "جار تسجيل الدخول…";
        status.textContent = "يرجى الانتظار…";
    });
    const alert = document.querySelector("[data-form-alert]");
    if (alert) alert.focus({ preventScroll: true });
})();
