from django import forms

from .models import SponsorshipShape, normalize_name, validate_name, normalize_description, validate_description


class SponsorshipShapeForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=200, label="شكل الرعاية", validators=[validate_name],
        error_messages={"required": "أدخل شكل الرعاية.", "max_length": "شكل الرعاية يجب ألا يتجاوز 200 حرف."},
        widget=forms.TextInput(attrs={"id": "sponsorship-shape-name", "placeholder": "مثال: رعاية مالية كاملة", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    description = forms.CharField(
        label="وصف شكل الرعاية", required=False, max_length=2000, validators=[validate_description],
        error_messages={"max_length": "الوصف يجب ألا يتجاوز 2000 حرف."},
        widget=forms.Textarea(attrs={"id": "sponsorship-shape-description", "rows": "4", "placeholder": "اكتب وصفًا مختصرًا لشكل الرعاية", "dir": "auto", "aria-describedby": "description-help description-error"}),
    )
    is_employment = forms.ChoiceField(
        label="هل الرعاية توظيف؟", choices=[("1", "نعم"), ("0", "لا")], widget=forms.RadioSelect,
        error_messages={"required": "حدّد ما إذا كانت الرعاية توظيفًا.", "invalid_choice": "اختر نعم أو لا فقط."},
    )
    is_active = forms.ChoiceField(choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect, error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر نشط أو غير نشط."})

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل شكل الرعاية.")
        if len(name) > 200:
            raise forms.ValidationError("شكل الرعاية يجب ألا يتجاوز 200 حرف.")
        existing = SponsorshipShape.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد شكل رعاية بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name

    def clean_description(self):
        value = normalize_description(self.cleaned_data.get("description", ""))
        validate_description(value)
        if len(value) > 2000:
            raise forms.ValidationError("الوصف يجب ألا يتجاوز 2000 حرف.")
        return value

    def clean(self):
        cleaned = super().clean()
        if hasattr(self.data, "getlist"):
            for field in ("is_employment", "is_active"):
                if len(self.data.getlist(field)) > 1:
                    self.add_error(field, "اختر قيمة واحدة فقط.")
        return cleaned
