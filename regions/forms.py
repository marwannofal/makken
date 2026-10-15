from django import forms

from .models import Region, normalize_name, validate_name, region_name_key


class RegionForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=100, label="اسم المنطقة", validators=[validate_name],
        error_messages={"required": "أدخل اسم المنطقة.", "max_length": "اسم المنطقة يجب ألا يتجاوز 100 حرف."},
        widget=forms.TextInput(attrs={"id": "region-name", "placeholder": "مثال: منطقة الرياض", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    is_active = forms.ChoiceField(
        choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect,
        error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر حالة صحيحة: نشط أو غير نشط."},
    )

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل اسم المنطقة.")
        if region_name_key(name) in {"منطقة", "المنطقة"}:
            raise forms.ValidationError("أدخل اسم المنطقة كاملًا، مثل منطقة الرياض.")
        if len(name) > 100:
            raise forms.ValidationError("اسم المنطقة يجب ألا يتجاوز 100 حرف.")
        existing = Region.objects.filter(name_key=region_name_key(name))
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("توجد منطقة بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name
