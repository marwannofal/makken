import json
import re
import phonenumbers
from django import forms
from django.db.models import Q
from accounts.profile_forms import COUNTRIES
from entities.models import Entity, EntityType, normalize_name, validate_name
from regions.models import Region
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from partnerships.models import Scope
from partnerships.financial import MoneyField
from partnerships.willingness import WillingnessTransitionForm
from .models import ServiceProvider, ProviderType


def phone_value(raw, country):
    if not raw:
        return ""
    text = "".join(str(int(c)) if c.isdecimal() else c for c in raw)
    try:
        if not re.fullmatch(r"[+\d\s().-]+", text):
            raise ValueError
        number = phonenumbers.parse(text, country)
        if number.extension or not phonenumbers.is_valid_number_for_region(number, country) or phonenumbers.number_type(number) not in {phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE}:
            raise ValueError
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    except (ValueError, phonenumbers.NumberParseException):
        raise forms.ValidationError("أدخل رقم جوال صالحًا ومتوافقًا مع الدولة المختارة.")


def setup_fields(form, prefix="provider"):
    for name, field in form.fields.items():
        field.error_messages.update(required="هذا الحقل مطلوب.", invalid_choice="اختر قيمة متاحة من القائمة.")
        if isinstance(field, forms.CharField) and field.max_length:
            field.error_messages["max_length"] = f"الحد الأقصى {field.max_length} حرفًا."
        field.widget.attrs.update(id=f"{prefix}-{name}", **{"aria-describedby": f"error-{prefix}-{name}"})
        if isinstance(field.widget, forms.Select):
            field.widget.attrs["data-market-select"] = ""
        if isinstance(field.widget, forms.TextInput) and not isinstance(field.widget, forms.HiddenInput):
            field.widget.attrs.setdefault("dir", "rtl")


def coverage_data(item):
    if not item:
        return []
    rows = item.coverage.all()
    if "coverage" not in getattr(item, "_prefetched_objects_cache", {}):
        rows = rows.prefetch_related("specializations")
    return [{"region": row.region_id, "specializations": sorted(s.pk for s in row.specializations.all()), "is_active": row.is_active} for row in rows]


class ProviderForm(forms.Form):
    name = forms.CharField(label="اسم مزود الخدمة", max_length=200, validators=[validate_name])
    representative = forms.CharField(label="اسم الممثل عن مزود الخدمة", max_length=200, required=False, validators=[validate_name])
    phone_country = forms.ChoiceField(label="رمز الدولة", choices=COUNTRIES, initial="SA")
    phone = forms.CharField(label="هاتف التواصل لمزود الخدمة", required=False, max_length=40, widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel-national", "dir": "ltr", "placeholder": "050 123 4567"}))
    email = forms.EmailField(label="البريد الإلكتروني", required=False, max_length=254, error_messages={"invalid": "أدخل بريدًا إلكترونيًا صحيحًا."}, widget=forms.EmailInput(attrs={"dir": "ltr", "autocomplete": "email", "placeholder": "name@example.com"}))
    provider_type = forms.ChoiceField(label="نوع مزود الخدمة", choices=[("", "اختر نوع مزود الخدمة"), *ProviderType.choices])
    scope = forms.ChoiceField(label="نطاق مزود الخدمة", choices=[("", "اختر النطاق"), *Scope.choices])
    is_active = forms.ChoiceField(label="حالة السجل", choices=[("1", "نشط"), ("0", "غير نشط")], widget=forms.RadioSelect, initial="1")
    coverage = forms.CharField(max_length=60000, widget=forms.HiddenInput, initial="[]")

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        self.previous = {row["region"]: set(row["specializations"]) for row in coverage_data(instance)}
        super().__init__(*args, **kwargs)
        setup_fields(self)

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        validate_name(name)
        if len(name) > 200:
            raise forms.ValidationError("الحد الأقصى للاسم بعد تنسيقه هو 200 حرف.")
        query = ServiceProvider.objects.filter(name_key=name.casefold())
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError("يوجد مزود خدمة بهذا الاسم بالفعل.")
        return name

    def clean_representative(self):
        name = normalize_name(self.cleaned_data["representative"])
        validate_name(name)
        if len(name) > 200:
            raise forms.ValidationError("الحد الأقصى لاسم الممثل هو 200 حرف.")
        return name

    def clean_email(self):
        return self.cleaned_data["email"].casefold()

    def clean_coverage(self):
        try:
            rows = json.loads(self.cleaned_data["coverage"])
        except (ValueError, TypeError):
            raise forms.ValidationError("تعذّر قراءة المناطق والتخصصات. أعد فتح النموذج.")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 80:
            raise forms.ValidationError("أضف منطقة واحدة على الأقل، وبحد أقصى 80 منطقة.")
        regions = {r.pk: r for r in Region.objects.all()}
        specs = {s.pk: s for s in Specialization.objects.select_related("sector")}
        seen, cleaned = set(), []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"region", "specializations", "is_active"}:
                raise forms.ValidationError("بيانات أحد بنود المناطق غير صحيحة.")
            region, selected = row["region"], row["specializations"]
            if type(region) is not int or region not in regions or region in seen or type(row["is_active"]) is not bool:
                raise forms.ValidationError("اختر منطقة متاحة مرة واحدة فقط، وحدد حالة البند.")
            if not isinstance(selected, list) or not 1 <= len(selected) <= 50 or any(type(s) is not int for s in selected) or len(set(selected)) != len(selected):
                raise forms.ValidationError("اختر تخصصًا واحدًا على الأقل لكل منطقة دون تكرار، وبحد أقصى 50 تخصصًا.")
            if not regions[region].is_active and region not in self.previous:
                raise forms.ValidationError("لا يمكن إضافة منطقة غير نشطة إلى سجل جديد.")
            for key in selected:
                spec = specs.get(key)
                active = spec and spec.is_active and spec.sector_id and spec.sector.is_active
                if not spec or not active and key not in self.previous.get(region, set()):
                    raise forms.ValidationError("التخصص غير متاح، أو قطاعه غير نشط. حدّث الاختيارات.")
            seen.add(region)
            cleaned.append({"region": region, "specializations": sorted(selected), "is_active": row["is_active"]})
        return cleaned

    def clean(self):
        data = super().clean()
        if data.get("phone") and data.get("phone_country"):
            try:
                data["phone"] = phone_value(data["phone"], data["phone_country"])
            except forms.ValidationError as error:
                self.add_error("phone", error)
        return data


class ConversionForm(WillingnessTransitionForm):
    representative = forms.CharField(label="اسم الممثل عن الجهة", max_length=200, validators=[validate_name])
    phone_country = forms.ChoiceField(label="رمز الدولة", choices=COUNTRIES)
    phone = forms.CharField(label="هاتف التواصل", max_length=40, widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "dir": "ltr"}))
    email = forms.EmailField(label="البريد الإلكتروني", max_length=254, error_messages={"invalid": "أدخل بريدًا إلكترونيًا صحيحًا."}, widget=forms.EmailInput(attrs={"dir": "ltr"}))
    financial_capacity = MoneyField(label="القدرة المالية")
    entity = forms.ModelChoiceField(label="الكيان", queryset=Entity.objects.none(), required=False, empty_label="اختر الكيان")
    sponsorship_shape = forms.ModelChoiceField(label="شكل الرعاية للتخصصات المنقولة", queryset=SponsorshipShape.objects.none(), empty_label="اختر شكل الرعاية")

    def __init__(self, *args, provider, **kwargs):
        self.provider = provider
        super().__init__(*args, **kwargs)
        kind = EntityType.GOVERNMENT if provider.provider_type == ProviderType.GOVERNMENT else EntityType.NON_GOVERNMENT
        self.fields["entity"].queryset = Entity.objects.filter(is_active=True, entity_type=kind)
        self.fields["entity"].required = kind == EntityType.NON_GOVERNMENT
        self.fields["entity"].label_from_instance = lambda e: e.get_entity_type_display() + (" — " + e.get_branch_display() if e.branch else "")
        self.fields["sponsorship_shape"].queryset = SponsorshipShape.objects.filter(is_active=True)
        setup_fields(self, "conversion")

    def clean_representative(self):
        name = normalize_name(self.cleaned_data["representative"])
        validate_name(name)
        if len(name) > 200:
            raise forms.ValidationError("الحد الأقصى لاسم الممثل هو 200 حرف.")
        return name

    def clean(self):
        data = super().clean()
        if self.provider.provider_type == ProviderType.GOVERNMENT and not data.get("entity"):
            data["entity"] = self.fields["entity"].queryset.first()
            if not data["entity"]:
                self.add_error("entity", "أضف كيانًا حكوميًا نشطًا في الإعدادات قبل التحويل.")
        if data.get("phone") and data.get("phone_country"):
            try:
                data["phone"] = phone_value(data["phone"], data["phone_country"])
            except forms.ValidationError as error:
                self.add_error("phone", error)
        return data
