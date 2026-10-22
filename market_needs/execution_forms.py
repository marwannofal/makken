import json
from django import forms
from .models import ExecutionStatus


class ExecutionForm(forms.Form):
    status = forms.ChoiceField(label="حالة التنفيذ", choices=ExecutionStatus.choices)
    notes = forms.CharField(label="ملاحظات التنفيذ", max_length=4000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    selection = forms.CharField(max_length=10000, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.error_messages.update(required="هذا الحقل مطلوب.", invalid_choice="اختر حالة تنفيذ صحيحة.", max_length="تجاوزت القيمة الحد المسموح.")
            field.widget.attrs.update(id="execution-" + name)

    def clean_selection(self):
        try:
            data = json.loads(self.cleaned_data["selection"])
        except (ValueError, TypeError):
            raise forms.ValidationError("تعذّر قراءة الاختيارات. حدّث الصفحة.")
        if not isinstance(data, dict) or set(data) != {"providers", "employers"}:
            raise forms.ValidationError("بيانات اختيار الجهات غير صحيحة.")
        for ids in data.values():
            if not isinstance(ids, list) or len(ids) > 200 or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
                raise forms.ValidationError("اختر جهات متاحة دون تكرار، وبحد أقصى 200 لكل قائمة.")
        return data

    def proposal(self):
        return {"status": self.cleaned_data["status"], "notes": self.cleaned_data["notes"], **self.cleaned_data["selection"]}
