import json
import re

import phonenumbers
from django import forms
from django.db.models import Q
from entities.models import Entity, EntityType, normalize_name, validate_name
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .models import Partnership, Scope


COUNTRIES = [(code, f"{code} +{phonenumbers.country_code_for_region(code)}") for code in sorted(phonenumbers.SUPPORTED_REGIONS)]


def offering_data(item):
    if not item:
        return []
    return [{"sector": row.sector_id, "specializations": list(row.specializations.values_list("id", flat=True)), "shape": row.sponsorship_shape_id, "is_active": row.is_active} for row in item.offerings.all()]


class PartnershipForm(forms.Form):
    name = forms.CharField(label="اسم الجهة", max_length=200, validators=[validate_name])
    representative = forms.CharField(label="اسم الممثل عن الجهة", max_length=200, validators=[validate_name])
    phone_country = forms.ChoiceField(label="رمز الدولة", choices=COUNTRIES, initial="SA")
    phone = forms.CharField(label="هاتف التواصل", max_length=40, widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel-national", "dir": "ltr", "placeholder": "050 123 4567"}))
    email = forms.EmailField(label="البريد الإلكتروني", max_length=254, error_messages={"invalid": "أدخل بريدًا إلكترونيًا صحيحًا."}, widget=forms.EmailInput(attrs={"autocomplete": "email", "dir": "ltr", "placeholder": "name@example.com"}))
    entity_type = forms.ChoiceField(label="نوع الكيان", choices=[("", "اختر نوع الكيان"), *EntityType.choices])
    entity = forms.ModelChoiceField(label="الكيان", queryset=Entity.objects.none(), empty_label="اختر الكيان")
    scope = forms.ChoiceField(label="النطاق", choices=[("", "اختر النطاق"), *Scope.choices])
    is_active = forms.ChoiceField(label="حالة السجل", choices=[("1", "نشط"), ("0", "غير نشط")], widget=forms.RadioSelect, initial="1")
    offerings = forms.CharField(max_length=60000, widget=forms.HiddenInput, initial="[]")

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.existing_rows = offering_data(instance)
        self.fields["entity"].queryset = Entity.objects.filter(Q(is_active=True) | Q(pk=instance.entity_id if instance else None)).order_by("name")
        self.fields["entity"].label_from_instance = lambda e: e.name + (" (غير نشط)" if not e.is_active else "")
        for name, field in self.fields.items():
            if field.required:
                field.error_messages["required"] = "هذا الحقل مطلوب."
            field.error_messages["invalid_choice"] = "اختر قيمة متاحة من القائمة."
            if getattr(field, "max_length", None):
                field.error_messages["max_length"] = f"الحد الأقصى {field.max_length} حرفًا."
            field.widget.attrs["aria-describedby"] = f"error-{name}"
            if name in {"name", "representative"}:
                field.widget.attrs.update({"dir": "auto", "autocomplete": "organization" if name == "name" else "name"})

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        if not name:
            raise forms.ValidationError("أدخل اسم الجهة.")
        exists = Partnership.objects.filter(name_key=name.casefold())
        if self.instance:
            exists = exists.exclude(pk=self.instance.pk)
        if exists.exists():
            raise forms.ValidationError("يوجد سجل بهذا الاسم بالفعل.")
        return name

    def clean_representative(self):
        name = normalize_name(self.cleaned_data["representative"])
        if not name:
            raise forms.ValidationError("أدخل اسم الممثل عن الجهة.")
        return name

    def clean_offerings(self):
        raw = self.cleaned_data["offerings"]
        try:
            rows = json.loads(raw)
        except (ValueError, TypeError):
            raise forms.ValidationError("بيانات القطاعات غير صالحة. أعد إضافتها.")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise forms.ValidationError("أضف قطاعًا واحدًا على الأقل، وبحد أقصى 100 بند.")
        old_sectors = {r["sector"] for r in self.existing_rows}
        old_shapes = {r["shape"] for r in self.existing_rows}
        old_specs = {s for r in self.existing_rows for s in r["specializations"]}
        sectors = {s.pk: s for s in Sector.objects.filter(Q(is_active=True) | Q(pk__in=old_sectors))}
        shapes = {s.pk: s for s in SponsorshipShape.objects.filter(Q(is_active=True) | Q(pk__in=old_shapes))}
        specs = {s.pk: s for s in Specialization.objects.filter(Q(is_active=True) | Q(pk__in=old_specs))}
        result, seen = [], set()
        for number, row in enumerate(rows, 1):
            if not isinstance(row, dict) or set(row) != {"sector", "shape", "specializations", "is_active"}:
                raise forms.ValidationError(f"البند {number}: بيانات غير صالحة.")
            sector, shape, selected = row["sector"], row["shape"], row["specializations"]
            if type(sector) is not int or type(shape) is not int or type(row["is_active"]) is not bool or not isinstance(selected, list) or not 1 <= len(selected) <= 100 or any(type(s) is not int for s in selected) or len(set(selected)) != len(selected):
                raise forms.ValidationError(f"البند {number}: اختر القطاع والتخصصات وشكل الرعاية وحالة السجل.")
            if sector not in sectors or shape not in shapes or any(s not in specs or specs[s].sector_id != sector for s in selected):
                raise forms.ValidationError(f"البند {number}: بعض الاختيارات غير متاحة، أو التخصص غير مرتبط بالقطاع المحدد.")
            for spec in selected:
                key = (sector, spec, shape)
                if key in seen:
                    raise forms.ValidationError("لا يمكن تكرار التخصص وشكل الرعاية داخل القطاع نفسه.")
                seen.add(key)
            result.append({"sector": sector, "shape": shape, "specializations": sorted(selected), "is_active": row["is_active"]})
        return result

    def clean(self):
        data = super().clean()
        entity, kind = data.get("entity"), data.get("entity_type")
        if entity and kind and entity.entity_type != kind:
            self.add_error("entity", "الكيان المحدد لا يتبع نوع الكيان المختار.")
        country, raw = data.get("phone_country"), data.get("phone")
        if country and raw:
            normalized = "".join(str(int(c)) if c.isdecimal() else c for c in raw)
            try:
                if not re.fullmatch(r"[+\d\s().-]+", normalized):
                    raise ValueError
                number = phonenumbers.parse(normalized, country)
                if number.extension or not phonenumbers.is_valid_number_for_region(number, country) or phonenumbers.number_type(number) not in {phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE}:
                    raise ValueError
                data["phone"] = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
            except (ValueError, phonenumbers.NumberParseException):
                self.add_error("phone", "أدخل رقم جوال صالحًا ومتوافقًا مع الدولة المختارة.")
        return data
