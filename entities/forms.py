from django import forms
from .models import Entity, EntityType, EntityBranch, normalize_name, validate_name


class EntityForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=200, label="اسم الكيان", validators=[validate_name],
        error_messages={"required": "أدخل اسم الكيان.", "max_length": "اسم الكيان يجب ألا يتجاوز 200 حرف."},
        widget=forms.TextInput(attrs={"id": "entity-name", "placeholder": "أدخل اسم الكيان", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    entity_type = forms.ChoiceField(
        label="الكيان", choices=EntityType.choices,
        error_messages={"required": "اختر الكيان.", "invalid_choice": "اختر حكومي أو غير حكومي فقط."},
        widget=forms.Select(attrs={"id": "entity-type", "aria-controls": "entity-branch-field", "aria-describedby": "type-error"}),
    )
    branch = forms.ChoiceField(
        label="فرع الكيان", choices=[("", "اختر فرع الكيان"), *EntityBranch.choices], required=False,
        error_messages={"required": "اختر فرع الكيان للكيان غير الحكومي.", "invalid_choice": "اختر فرعًا صحيحًا من القائمة."},
        widget=forms.Select(attrs={"id": "entity-branch", "aria-describedby": "branch-error"}),
    )
    is_active = forms.ChoiceField(
        choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect,
        error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر حالة صحيحة: نشط أو غير نشط."},
    )

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id
        kind = self.data.get("entity_type") if self.is_bound else self.initial.get("entity_type", EntityType.GOVERNMENT)
        self.show_branch = kind == EntityType.NON_GOVERNMENT
        self.fields["branch"].required = self.show_branch
        # For government entities, discard even forged or stale posted branches.
        self.fields["branch"].disabled = not self.show_branch
        if not self.show_branch:
            self.initial["branch"] = ""

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل اسم الكيان.")
        if len(name) > 200:
            raise forms.ValidationError("اسم الكيان يجب ألا يتجاوز 200 حرف.")
        existing = Entity.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد كيان بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name

    def clean(self):
        data = super().clean()
        if data.get("entity_type") == EntityType.GOVERNMENT:
            data["branch"] = ""
        return data
