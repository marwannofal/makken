from django import forms
from django.db.models import Q
from specializations.models import Specialization

from .models import Sector, normalize_name, validate_name


class SectorForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=200, label="اسم القطاع", validators=[validate_name],
        error_messages={"required": "أدخل اسم القطاع.", "max_length": "اسم القطاع يجب ألا يتجاوز 200 حرف."},
        widget=forms.TextInput(attrs={"id": "sector-name", "placeholder": "مثال: الصناعات التحويلية", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    is_active = forms.ChoiceField(choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect, error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر نشط أو غير نشط."})

    specializations = forms.ModelMultipleChoiceField(
        label="التخصصات / المهن", queryset=Specialization.objects.none(),
        error_messages={"required": "اختر تخصصًا واحدًا على الأقل.", "invalid_choice": "أحد التخصصات غير متاح أو مرتبط بقطاع آخر. أعد فتح النموذج."},
        widget=forms.SelectMultiple(attrs={"id": "sector-specializations", "aria-describedby": "specializations-help specializations-error", "size": "6"}),
    )

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id
        available = Q(sector__isnull=True)
        if instance_id is not None:
            available |= Q(sector_id=instance_id)
        self.fields["specializations"].queryset = Specialization.objects.filter(available).order_by("id")
        self.fields["specializations"].label_from_instance = lambda item: item.name + (" (غير نشط)" if not item.is_active else "")

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل اسم القطاع.")
        if len(name) > 200:
            raise forms.ValidationError("اسم القطاع يجب ألا يتجاوز 200 حرف.")
        existing = Sector.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد قطاع بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name
