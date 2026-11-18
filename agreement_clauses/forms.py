from django import forms

from expense_items.models import normalize_name, validate_name
from .models import AgreementClause, Responsibility


class AgreementClauseForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=200, label="بند الاتفاقية", validators=[validate_name],
        error_messages={"required": "أدخل بند الاتفاقية.", "max_length": "بند الاتفاقية يجب ألا يتجاوز 200 حرف."},
        widget=forms.TextInput(attrs={"id": "expense-item-name", "placeholder": "مثال: تقديم تقرير متابعة دوري", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    is_active = forms.ChoiceField(choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect, error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر نشط أو غير نشط."})

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل بند الاتفاقية.")
        if len(name) > 200:
            raise forms.ValidationError("بند الاتفاقية يجب ألا يتجاوز 200 حرف.")
        existing = AgreementClause.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد بند اتفاقية بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name


class AgreementTitleForm(forms.Form):
    title = forms.CharField(label="عنوان الاتفاقية", max_length=200, validators=[validate_name],
        error_messages={"required": "أدخل عنوان الاتفاقية.", "max_length": "العنوان يجب ألا يتجاوز 200 حرف."})

    def clean_title(self):
        return normalize_name(self.cleaned_data["title"])


class ClausePicker(forms.ModelMultipleChoiceField):
    def __init__(self, **kwargs):
        super().__init__(queryset=AgreementClause.objects.none(), label="بنود الاتفاقية",
            widget=forms.SelectMultiple(attrs={"data-market-select": "", "data-label": "بنود الاتفاقية"}),
            error_messages={"required": "اختر بند اتفاقية واحدًا على الأقل.",
                            "invalid_choice": "أحد البنود المحددة غير متاح.",
                            "invalid_pk_value": "معرّف بند الاتفاقية غير صحيح.",
                            "invalid_list": "أرسل قائمة صالحة لبنود الاتفاقية."}, **kwargs)

    def limit(self, current=(), excluded=()):
        from django.db.models import Q
        self.queryset = AgreementClause.objects.filter(Q(is_active=True) | Q(pk__in=current)).exclude(pk__in=excluded)

    def label_from_instance(self, item):
        return item.name + (" (غير نشط)" if not item.is_active else "")

    def clean(self, value):
        if isinstance(value, (list, tuple)) and (len(value) > 100 or any(not isinstance(pk, (str, int)) for pk in value) or len(value) != len(set(map(str, value)))):
            raise forms.ValidationError("يمكن اختيار 100 بند على الأكثر دون تكرار.")
        return super().clean(value)


class AssignForm(forms.Form):
    clauses = ClausePicker()
    responsibility = forms.ChoiceField(label="المسؤولية", choices=Responsibility.choices,
        error_messages={"required": "حدّد المسؤولية.", "invalid_choice": "اختر مسؤولية من القائمة."})

    def __init__(self, *args, assigned=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["clauses"].limit(excluded=assigned)


class ProgressForm(forms.Form):
    responsibility = forms.ChoiceField(label="المسؤولية", choices=Responsibility.choices,
        error_messages={"required": "حدّد المسؤولية.", "invalid_choice": "اختر مسؤولية من القائمة."})
    progress = forms.IntegerField(label="نسبة الإنجاز", min_value=0, max_value=100,
        error_messages={"required": "أدخل نسبة الإنجاز.", "invalid": "أدخل عددًا صحيحًا.",
                        "min_value": "النسبة لا تقل عن 0%%.", "max_value": "النسبة لا تتجاوز 100%%."})
