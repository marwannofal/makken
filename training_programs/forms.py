from django import forms
from expense_items.models import ExpenseItem, normalize_name, validate_name
from .models import TrainingProgram


class TrainingProgramForm(forms.Form):
    operation = forms.ChoiceField(choices=[("add", "add"), ("edit", "edit")], widget=forms.HiddenInput)
    snapshot = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    name = forms.CharField(
        max_length=200, label="البرنامج التدريبي", validators=[validate_name],
        error_messages={"required": "أدخل اسم البرنامج التدريبي.", "max_length": "اسم البرنامج يجب ألا يتجاوز 200 حرف."},
        widget=forms.TextInput(attrs={"id": "program-name", "placeholder": "مثال: إدارة المستودعات", "autocomplete": "off", "dir": "auto", "aria-describedby": "name-help name-error"}),
    )
    category = forms.ChoiceField(
        label="تصنيف البرامج", choices=[("", "اختر تصنيف البرنامج"), *TrainingProgram.Category.choices],
        error_messages={"required": "اختر تصنيفًا واحدًا للبرنامج.", "invalid_choice": "اختر تصنيفًا من القائمة المعتمدة."},
        widget=forms.Select(attrs={"id": "program-category", "aria-describedby": "category-error"}),
    )
    expense_items = forms.ModelMultipleChoiceField(
        label="بنود الصرف", queryset=ExpenseItem.objects.none(),
        error_messages={"required": "اختر بند صرف واحدًا على الأقل.", "invalid_choice": "أحد بنود الصرف لم يعد موجودًا. أعد فتح النموذج."},
        widget=forms.SelectMultiple(attrs={"id": "program-expense-items", "aria-describedby": "expenses-help expenses-error", "size": "6"}),
    )
    training_types = forms.ChoiceField(
        label="نوع التدريب للبرنامج", choices=TrainingProgram.TrainingType.choices,
        widget=forms.RadioSelect(attrs={"aria-describedby": "types-help types-error"}),
        error_messages={"required": "اختر نوع تدريب واحدًا فقط.", "invalid_choice": "اختر تدريبي أو تشغيلي فقط."},
    )
    is_active = forms.ChoiceField(choices=[("1", "نشط"), ("0", "غير نشط")], label="حالة السجل", widget=forms.RadioSelect,
                                error_messages={"required": "حدّد حالة السجل.", "invalid_choice": "اختر نشط أو غير نشط."})

    def __init__(self, *args, instance_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_id = instance_id
        # Shared catalogue: assignment to another program never hides an expense item.
        self.fields["expense_items"].queryset = ExpenseItem.objects.all().order_by("id")
        self.fields["expense_items"].label_from_instance = lambda item: item.name + (" (غير نشط)" if not item.is_active else "")

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if not name:
            raise forms.ValidationError("أدخل اسم البرنامج التدريبي.")
        if len(name) > 200:
            raise forms.ValidationError("اسم البرنامج يجب ألا يتجاوز 200 حرف.")
        existing = TrainingProgram.objects.filter(name_key=name.casefold())
        if self.instance_id is not None:
            existing = existing.exclude(pk=self.instance_id)
        if existing.exists():
            raise forms.ValidationError("يوجد برنامج بهذا الاسم بالفعل. اختر اسمًا آخر.")
        return name

    def clean_training_types(self):
        # Reject repeated submitted values; ChoiceField alone would accept the last value.
        if hasattr(self.data, "getlist"):
            submitted = self.data.getlist("training_types")
        else:
            value = self.data.get("training_types")
            submitted = value if isinstance(value, (list, tuple)) else [value]
        if len(submitted) != 1:
            raise forms.ValidationError("اختر نوع تدريب واحدًا فقط.")
        return [self.cleaned_data["training_types"]]
