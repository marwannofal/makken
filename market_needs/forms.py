import json
from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from entities.models import normalize_name, validate_name
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from training_programs.models import TrainingProgram
from sponsorship_shapes.models import SponsorshipShape, validate_description
from partnerships.financial import MoneyField, MAX_CAPACITY
from partnerships.models import Scope
from partnerships.willingness import MultipleAttachmentInput
from care_states.models import DevelopmentState
from .attachments import validate_support_attachment


class SARAmountField(MoneyField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("min_value", Decimal(".01"))
        kwargs.setdefault("error_messages", {
            "required": "أدخل المبلغ بالريال السعودي.", "invalid": "أدخل مبلغًا صحيحًا بالريال السعودي.",
            "min_value": "أدخل مبلغًا أكبر من صفر.", "max_value": "المبلغ يتجاوز الحد الأقصى المسموح.",
            "max_digits": "المبلغ يتجاوز عدد الأرقام المسموح.", "max_decimal_places": "استخدم منزلتين عشريتين كحد أقصى.",
            "max_whole_digits": "الحد الأقصى 12 رقمًا قبل الفاصلة العشرية.",
        })
        super().__init__(*args, **kwargs)


class NeedForm(forms.Form):
    title = forms.CharField(label="حاجة السوق", max_length=200, validators=[validate_name])
    sector = forms.ModelChoiceField(label="القطاع", queryset=Sector.objects.none())
    specialization = forms.ModelChoiceField(label="التخصص", queryset=Specialization.objects.none())
    regions = forms.ModelMultipleChoiceField(label="المناطق", queryset=Region.objects.none())
    description = forms.CharField(label="وصف الحاجة", max_length=4000, widget=forms.Textarea(attrs={"rows": 3}), validators=[validate_description])
    duration = forms.IntegerField(label="المدة الزمنية", min_value=1, max_value=100000)
    duration_unit = forms.ChoiceField(label="وحدة المدة", choices=[("day", "يوم"), ("month", "شهر"), ("year", "سنة")])
    source = forms.CharField(label="مصدر الحاجة", max_length=300, validators=[validate_name])
    beneficiaries = forms.IntegerField(label="عدد المستفيدين", min_value=1, max_value=1000000000)
    requested_support = SARAmountField(label="قيمة الدعم المطلوبة")
    observed_on = forms.DateField(label="تاريخ الرصد", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), input_formats=["%Y-%m-%d"])
    is_active = forms.ChoiceField(label="حالة السجل", choices=[("1", "نشط"), ("0", "غير نشط")], initial="1")
    program = forms.ModelChoiceField(label="البرنامج التدريبي", queryset=TrainingProgram.objects.none())
    lines = forms.CharField(widget=forms.HiddenInput, max_length=60000, initial="[]")
    dependencies_confirmed = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        for field, model in [("sector", Sector), ("specialization", Specialization), ("program", TrainingProgram)]:
            old_id = getattr(instance, field + "_id", None)
            self.fields[field].queryset = model.objects.filter(Q(is_active=True) | Q(pk=old_id)).order_by("name")
            self.fields[field].label_from_instance = lambda obj: obj.name + (" (غير نشط — محفوظ سابقًا)" if not obj.is_active else "")
            self.fields[field].empty_label = "اختر من القائمة"
        old_regions = list(instance.regions.values_list("pk", flat=True)) if instance else []
        self.fields["regions"].queryset = Region.objects.filter(Q(is_active=True) | Q(pk__in=old_regions)).order_by("name")
        self.fields["regions"].label_from_instance = lambda obj: obj.name + (" (غير نشط — محفوظ سابقًا)" if not obj.is_active else "")
        for name, field in self.fields.items():
            field.error_messages["required"] = "هذا الحقل مطلوب."
            field.error_messages["invalid_choice"] = "اختر قيمة متاحة من القائمة."
            if isinstance(field, forms.IntegerField) and not isinstance(field, forms.DecimalField):
                field.error_messages.update(invalid="أدخل عددًا صحيحًا.", min_value="أدخل قيمة لا تقل عن %(limit_value)s.", max_value="أدخل قيمة لا تتجاوز %(limit_value)s.")
            if isinstance(field, forms.DateField):
                field.error_messages["invalid"] = "أدخل تاريخًا صحيحًا."
            if getattr(field, "max_length", None):
                field.error_messages["max_length"] = "الحد الأقصى %(limit_value)s حرفًا."
            field.widget.attrs["aria-describedby"] = "error-" + name
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["data-market-select"] = ""
            if isinstance(field, forms.IntegerField):
                field.widget.attrs["inputmode"] = "numeric"

    def clean_title(self):
        text = normalize_name(self.cleaned_data["title"])
        if not text:
            raise forms.ValidationError("أدخل عنوان الحاجة.")
        return text

    def clean(self):
        data = super().clean()
        sector, spec, program = data.get("sector"), data.get("specialization"), data.get("program")
        if sector and spec and spec.sector_id != sector.pk:
            self.add_error("specialization", "التخصص لا يتبع القطاع المختار.")
        if self.instance and not data.get("dependencies_confirmed") and (sector and sector.pk != self.instance.sector_id or program and program.pk != self.instance.program_id):
            self.add_error("dependencies_confirmed", "أكد تغيير القطاع أو البرنامج وإعادة مراجعة البيانات المرتبطة.")
        try:
            raw = json.loads(data.get("lines", "[]"))
            if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
                raise ValueError
        except (ValueError, TypeError):
            self.add_error("lines", "أضف بند صرف واحدًا على الأقل، وبحد أقصى 100 بند.")
            return data
        old_lines = {line.expense_item_id: line for line in self.instance.expense_lines.all()} if self.instance else {}
        old_shapes = {line.sponsorship_shape_id for line in old_lines.values()}
        shapes = {obj.pk: obj for obj in SponsorshipShape.objects.filter(Q(is_active=True) | Q(pk__in=old_shapes))}
        allowed = set(program.expense_items.filter(is_active=True).values_list("pk", flat=True)) if program else set()
        if self.instance and program and program.pk == self.instance.program_id:
            allowed.update(old_lines)
        result, seen, total = [], set(), Decimal("0.00")
        try:
            for row in raw:
                if not isinstance(row, dict) or set(row) != {"expense", "shape", "amount"}:
                    raise ValueError
                expense, shape = row["expense"], row["shape"]
                if type(expense) is not int or type(shape) is not int or expense not in allowed or shape not in shapes or expense in seen:
                    raise ValueError
                # An inactive historical shape can only remain on its original line.
                if shape in old_shapes and not shapes[shape].is_active and (expense not in old_lines or old_lines[expense].sponsorship_shape_id != shape):
                    raise ValueError
                amount = SARAmountField().clean(row["amount"])
                result.append({"expense": expense, "shape": shape, "amount": amount})
                seen.add(expense)
                total += amount
            if total > MAX_CAPACITY:
                raise forms.ValidationError("إجمالي البنود يتجاوز الحد الأقصى المالي المسموح.")
        except (ValueError, TypeError, forms.ValidationError) as exc:
            self.add_error("lines", exc if isinstance(exc, forms.ValidationError) else "راجع البنود وأشكال الرعاية؛ توجد قيمة غير متاحة أو بند مكرر.")
            return data
        data["lines"] = result
        data["total_cost"] = total
        if data.get("requested_support") and data["requested_support"] > total:
            self.add_error("requested_support", "الدعم المطلوب لا يمكن أن يتجاوز إجمالي تكلفة الحاجة.")
        return data


class MatchFilterForm(forms.Form):
    states = forms.MultipleChoiceField(label="حالة تطور الجهة", choices=DevelopmentState.choices, required=False, widget=forms.CheckboxSelectMultiple)
    scopes = forms.MultipleChoiceField(label="نطاق الكيان", choices=Scope.choices, required=False, widget=forms.CheckboxSelectMultiple)
    q = forms.CharField(label="البحث في الجهات المطابقة", max_length=200, required=False)


class OptionalAttachments(forms.FileField):
    widget = MultipleAttachmentInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data] if data else []
        if len(files) > getattr(settings, "MAKKEN_SUPPORT_MAX_FILES", 20):
            raise forms.ValidationError("تجاوزت العدد المسموح للمرفقات.")
        result = []
        for upload in files:
            result.append(validate_support_attachment(upload))
        return result


class FollowupForm(forms.Form):
    notes = forms.CharField(label="نتيجة التواصل / الملاحظات", required=False, max_length=4000, widget=forms.Textarea(attrs={"rows": 3}), validators=[validate_description])
    amount = SARAmountField(label="قيمة الدعم المعتمد", required=False)
    support_percent = MoneyField(label="نسبة الدعم في الرعاية %", required=False, min_value=Decimal(".01"), max_value=Decimal("100"), max_digits=5, decimal_places=2)
    rejection_reason = forms.CharField(label="سبب الرفض", required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}), validators=[validate_description])
    attachments = OptionalAttachments(label="مستندات إثبات الدعم", required=False, widget=MultipleAttachmentInput(attrs={"accept": ".pdf,.png,.jpg,.jpeg"}))

    def __init__(self, *args, operation="notes", need=None, record=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.operation = operation
        self.need, self.record = need, record
        if operation == "allocate" and record is not None:
            self.initial.update(amount=record.amount, support_percent=record.percent)
        self.allocation_lines = []
        self.allowed_shapes = None
        self.fields["support_percent"].widget.attrs.update(inputmode="decimal", dir="ltr", maxlength="6")
        if need is not None:
            from .funding import expense_funding
            self.allocation_lines = expense_funding(need)
            if operation == "approve" and record is not None:
                from .matching import matching_offerings
                self.allowed_shapes = set(matching_offerings(need).filter(partnership_id=record.partnership_id).values_list("sponsorship_shape_id", flat=True))
            for line in self.allocation_lines:
                name = f"allocation_{line.pk}"
                self.fields[name] = SARAmountField(label=f"الدعم لبند {line.expense_item.name}", required=False)
                self.fields[name].widget.attrs.update({"inputmode": "decimal", "dir": "ltr", "data-allocation-input": "", "data-line-id": str(line.pk), "data-remaining": format(line.remaining_amount, ".2f")})
                if self.allowed_shapes is not None and line.sponsorship_shape_id not in self.allowed_shapes:
                    self.fields[name].widget.attrs["disabled"] = True
                line.allocation_field_name = name
            self.fields["amount"].widget.attrs["readonly"] = True
        self.fields["rejection_reason"].required = operation == "reject"
        for name, field in self.fields.items():
            field.error_messages["required"] = "هذا الحقل مطلوب."
            if getattr(field, "max_length", None):
                field.error_messages["max_length"] = "الحد الأقصى %(limit_value)s حرفًا."
            field.widget.attrs["aria-describedby"] = "error-" + name

    def clean(self):
        data = super().clean()
        if self.operation != "approve" and data.get("attachments"):
            self.add_error("attachments", "تُرفق مستندات الدعم عند الاعتماد فقط.")
        if self.operation not in {"approve", "allocate"}:
            return data
        if self.operation == "allocate":
            amount = self.record.amount if self.record else None
            data["amount"] = amount
        else:
            amount = data.get("amount")
            percent = data.get("support_percent")
            if percent is not None and self.need is not None:
                calculated = (self.need.total_cost * percent / 100).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
                if calculated <= 0:
                    self.add_error("support_percent", "النسبة صغيرة جدًا؛ يجب أن تعادل المساهمة هللة واحدة على الأقل.")
                elif amount is not None and amount != calculated:
                    self.add_error("amount", "المبلغ لا يطابق النسبة المدخلة وتكلفة الحاجة.")
                amount = calculated
                data["amount"] = calculated
            if amount is None:
                self.add_error("amount", "أدخل نسبة الدعم لحساب مبلغ المساهمة.")
        if self.need is not None:
            allowed = {line.allocation_field_name for line in self.allocation_lines}
            if any(name.startswith("allocation_") and name not in allowed for name in self.data):
                self.add_error(None, "يوجد بند توزيع لا يتبع بطاقة الحاجة.")
            allocations = []
            for line in self.allocation_lines:
                value = data.get(line.allocation_field_name)
                if value is not None:
                    if self.operation == "approve" and self.allowed_shapes is not None and line.sponsorship_shape_id not in self.allowed_shapes:
                        self.add_error(line.allocation_field_name, "شكل رعاية هذه الجهة لا يغطي هذا البند.")
                    if value > line.remaining_amount:
                        self.add_error(line.allocation_field_name, "المبلغ يتجاوز المتبقي لهذا البند.")
                    allocations.append((line, value))
            if not allocations or sum((value for _, value in allocations), Decimal("0")) != amount:
                self.add_error(None, "وزّع مبلغ المساهمة كاملًا على بنود الصرف؛ يجب أن يساوي مجموع التوزيع مبلغ الدعم تمامًا.")
            data["allocations"] = allocations
        return data

    @property
    def allocation_rows(self):
        return [{"line": line, "field": self[line.allocation_field_name]} for line in self.allocation_lines]
