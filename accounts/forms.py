from django import forms
from django.contrib.auth.forms import AuthenticationForm, UsernameField


INVALID_CREDENTIALS = "اسم المستخدم أو البريد الإلكتروني أو كلمة المرور غير صحيحة."


class SiteAuthenticationForm(AuthenticationForm):
    username = UsernameField(
        label="البريد الإلكتروني أو اسم المستخدم",
        max_length=254,
        widget=forms.TextInput(attrs={
            "placeholder": "البريد الإلكتروني أو اسم المستخدم",
            "autocomplete": "username",
            "autocapitalize": "none",
            "spellcheck": "false",
            "dir": "auto",
            "maxlength": "254",
            "aria-describedby": "username-error",
        }),
        error_messages={
            "required": "أدخل البريد الإلكتروني أو اسم المستخدم.",
            "max_length": "يجب ألا تتجاوز البيانات 254 حرفًا.",
            "null_characters_not_allowed": "تحتوي البيانات على محارف غير مسموح بها.",
        },
    )
    password = forms.CharField(
        label="كلمة المرور",
        strip=False,
        max_length=1024,
        widget=forms.PasswordInput(attrs={
            "placeholder": "أدخل كلمة المرور",
            "autocomplete": "current-password",
            "dir": "auto",
            "maxlength": "1024",
            "aria-describedby": "password-error",
        }, render_value=False),
        error_messages={
            "required": "أدخل كلمة المرور.",
            "max_length": "كلمة المرور أطول من الحد المسموح.",
            "null_characters_not_allowed": "تحتوي البيانات على محارف غير مسموح بها.",
        },
    )
    remember_me = forms.BooleanField(
        label="تذكرني",
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "remember-checkbox"}),
    )
    error_messages = {
        "invalid_login": INVALID_CREDENTIALS,
        "inactive": INVALID_CREDENTIALS,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # AuthenticationForm otherwise resets this to the username model's max length.
        self.fields["username"].max_length = 254
        self.fields["username"].widget.attrs["maxlength"] = "254"
        for name in ("username", "password"):
            if self.is_bound and self.errors.get(name):
                self.fields[name].widget.attrs["aria-invalid"] = "true"
