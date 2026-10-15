from django import forms

from .models import Level, normalize_name, validate_name


class LevelForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=100, label="اسم المستوى", validators=[validate_name],
        error_messages={"required": "أدخل اسم المستوى.", "max_length": "اسم المستوى يجب ألا يتجاوز 100 حرف."},
        widget=forms.TextInput(attrs={"id": "level-name", "placeholder": "مثال: برونزي", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    is_active = forms.ChoiceField(choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect)

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل اسم المستوى.")
        if len(name) > 100:
            raise forms.ValidationError("اسم المستوى يجب ألا يتجاوز 100 حرف.")
        existing = Level.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد مستوى بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name
