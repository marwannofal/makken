from django import forms

from .models import ExpenseItem, normalize_name, validate_name


class ExpenseItemForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=200, label="بند الصرف", validators=[validate_name],
        error_messages={"required": "أدخل بند الصرف.", "max_length": "بند الصرف يجب ألا يتجاوز 200 حرف."},
        widget=forms.TextInput(attrs={"id": "expense-item-name", "placeholder": "مثال: شراء المعدات والأجهزة", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    is_active = forms.ChoiceField(choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect, error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر نشط أو غير نشط."})

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل بند الصرف.")
        if len(name) > 200:
            raise forms.ValidationError("بند الصرف يجب ألا يتجاوز 200 حرف.")
        existing = ExpenseItem.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد بند صرف بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name
