from django import forms

from .models import Specialization, normalize_name, validate_name


class SpecializationForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=200, label="اسم التخصص", validators=[validate_name],
        error_messages={"required": "أدخل اسم التخصص.", "max_length": "اسم التخصص يجب ألا يتجاوز 200 حرف."},
        widget=forms.TextInput(attrs={"id": "specialization-name", "placeholder": "مثال: هندسة الميكاترونكس", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    is_active = forms.ChoiceField(choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect, error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر نشط أو غير نشط."})

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل اسم التخصص.")
        if len(name) > 200:
            raise forms.ValidationError("اسم التخصص يجب ألا يتجاوز 200 حرف.")
        existing = Specialization.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد تخصص بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name
