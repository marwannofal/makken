from django import forms
from .models import Entity, EntityType, EntityBranch


class EntityForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
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

    def __init__(self, *args, instance_id=None, stored_name=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id
        # Only the view supplies stored_name from a verified confirmation token.
        self.stored_name = stored_name
        kind = self.data.get("entity_type") if self.is_bound else self.initial.get("entity_type", EntityType.GOVERNMENT)
        self.show_branch = kind == EntityType.NON_GOVERNMENT
        self.fields["branch"].required = self.show_branch
        # For government entities, discard even forged or stale posted branches.
        self.fields["branch"].disabled = not self.show_branch
        if not self.show_branch:
            self.initial["branch"] = ""

    def clean(self):
        data = super().clean()
        if data.get("entity_type") == EntityType.GOVERNMENT:
            data["branch"] = ""
        if self.errors:
            return data
        if self.instance_id is not None:
            # Preserve historical names and all foreign-key relationships.
            data["name"] = Entity.objects.get(pk=self.instance_id).name
        elif self.stored_name is not None:
            if Entity.objects.filter(name_key=self.stored_name.casefold()).exists():
                raise forms.ValidationError("تغيّرت بيانات الكيانات منذ المراجعة. أعد فتح النموذج وحاول مجددًا.")
            data["name"] = self.stored_name
        else:
            label = EntityBranch(data["branch"]).label if data["entity_type"] == EntityType.NON_GOVERNMENT else EntityType.GOVERNMENT.label
            # Classification can recur; keep the existing unique-name schema.
            used = set(Entity.objects.filter(name_key__startswith=label.casefold()).values_list("name_key", flat=True))
            name, number = label, 2
            while name.casefold() in used:
                name = f"{label} ({number})"
                number += 1
            data["name"] = name
        return data
