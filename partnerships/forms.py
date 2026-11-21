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
from regions.models import Region
from access_control.regions import RegionalPolicy, region_choices

from .financial import MoneyField


COUNTRIES = [(code, f"{code} +{phonenumbers.country_code_for_region(code)}") for code in sorted(phonenumbers.SUPPORTED_REGIONS - {"IL"})]


def term_date_field(label):
    return forms.DateField(
        label=label,
        required=False,
        input_formats=["%d/%m/%Y", "%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "dir": "ltr"}),
        error_messages={"invalid": "أدخل تاريخًا صحيحًا."},
    )


def offering_data(item):
    if not item:
        return []
    return [{"sector": row.sector_id, "specializations": list(row.specializations.values_list("id", flat=True)), "shape": row.sponsorship_shape_id, "is_active": row.is_active} for row in item.offerings.all()]


class PartnershipForm(forms.Form):
    administrative_regions = forms.ModelMultipleChoiceField(label="المناطق الإدارية للجهة",queryset=Region.objects.none(),required=False,widget=forms.SelectMultiple(attrs={'data-market-select':'','data-label':'المناطق الإدارية للجهة'}),help_text='تحدد صلاحيات الوصول فقط ولا تغيّر شروط مطابقة الرعاة. الجهة بلا مناطق لا تظهر للمستخدم المقيّد.')
    name = forms.CharField(label="اسم الجهة", max_length=200, validators=[validate_name])
    representative = forms.CharField(label="اسم الممثل عن الجهة", max_length=200, validators=[validate_name])
    phone_country = forms.ChoiceField(label="رمز الدولة", choices=COUNTRIES, initial="SA")
    phone = forms.CharField(label="هاتف التواصل", max_length=40, widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel-national", "dir": "ltr", "placeholder": "050 123 4567"}))
    email = forms.EmailField(label="البريد الإلكتروني", max_length=254, error_messages={"invalid": "أدخل بريدًا إلكترونيًا صحيحًا."}, widget=forms.EmailInput(attrs={"autocomplete": "email", "dir": "ltr", "placeholder": "name@example.com"}))
    financial_capacity = MoneyField(label="القدرة المالية")
    entity_type = forms.ChoiceField(label="نوع الكيان", choices=[("", "اختر نوع الكيان"), *EntityType.choices])
    entity = forms.ModelChoiceField(label="الكيان", queryset=Entity.objects.none(), empty_label="اختر الكيان")
    scope = forms.ChoiceField(label="النطاق", choices=[("", "اختر النطاق"), *Scope.choices])
    partnership_date = forms.CharField(label="تاريخ الشراكة", max_length=7, required=False, widget=forms.TextInput(attrs={"type": "month", "dir": "ltr", "placeholder": "YYYY-MM"}), help_text="اختر الشهر والسنة فقط (بدون يوم).")
    starts_on = term_date_field("تاريخ بداية الشراكة")
    ends_on = term_date_field("تاريخ نهاية الشراكة")
    is_active = forms.ChoiceField(label="حالة السجل", choices=[("1", "نشط"), ("0", "غير نشط")], widget=forms.RadioSelect, initial="1")
    offerings = forms.CharField(max_length=60000, widget=forms.HiddenInput, initial="[]")

    def __init__(self, *args, instance=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        previous_regions=list(instance.administrative_regions.values_list('pk',flat=True)) if instance else []
        self.fields['administrative_regions'].queryset=region_choices(actor,previous_regions) if actor is not None else Region.objects.filter(Q(is_active=True)|Q(pk__in=previous_regions))
        self.fields['administrative_regions'].required=actor is not None and not RegionalPolicy(actor).unrestricted
        self.fields['administrative_regions'].label_from_instance=lambda region: region.name + (' (غير نشط — محفوظ سابقًا)' if not region.is_active else '')
        self.existing_rows = offering_data(instance)
        kind = self.data.get("entity_type") if self.is_bound else self.initial.get("entity_type", "")
        self.show_entity = kind == EntityType.NON_GOVERNMENT
        self.fields["entity"].required = self.show_entity
        self.fields["entity"].queryset = Entity.objects.filter(Q(is_active=True) | Q(pk=instance.entity_id if instance else None)).order_by("name")
        self.fields['administrative_regions'].error_messages.update(invalid_list='اختر المناطق من القائمة.', invalid_pk_value='أحد معرّفات المناطق غير صحيح.')
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
            # Retain historical multi-specialty rows without allowing new ones.
            unchanged_legacy = any(
                old["sector"] == sector and old["shape"] == shape
                and set(old["specializations"]) == set(selected)
                for old in self.existing_rows
            )
            if len(selected) != 1 and not unchanged_legacy:
                raise forms.ValidationError(f"البند {number}: اختر تخصصًا واحدًا فقط لكل بند شراكة.")
            if sector not in sectors or shape not in shapes or any(s not in specs or specs[s].sector_id != sector for s in selected):
                raise forms.ValidationError(f"البند {number}: بعض الاختيارات غير متاحة، أو التخصص غير مرتبط بالقطاع المحدد.")
            for spec in selected:
                key = (sector, spec, shape)
                if key in seen:
                    raise forms.ValidationError("لا يمكن تكرار التخصص وشكل الرعاية داخل القطاع نفسه.")
                seen.add(key)
            result.append({"sector": sector, "shape": shape, "specializations": sorted(selected), "is_active": row["is_active"]})
        return result

    def clean_partnership_date(self):
        raw = (self.cleaned_data.get("partnership_date") or "").strip()
        if not raw:
            return ""
        if not re.fullmatch(r"[12]\d{3}-(?:0[1-9]|1[0-2])", raw):
            raise forms.ValidationError("أدخل تاريخ الشراكة بصيغة الشهر والسنة فقط (YYYY-MM).")
        return raw

    def clean(self):
        data = super().clean()
        if self.instance and self.add_prefix("partnership_date") not in self.data:
            data["partnership_date"] = self.instance.partnership_date
        if self.instance and not any(self.add_prefix(name) in self.data for name in ("starts_on", "ends_on")):
            # An editor opened before the update may still submit a form without dates.
            data["starts_on"], data["ends_on"] = self.instance.starts_on, self.instance.ends_on
        if "starts_on" in data and "ends_on" in data:
            start, end = data["starts_on"], data["ends_on"]
            if start and not end:
                self.add_error("ends_on", "أدخل تاريخ نهاية الشراكة عند تحديد تاريخ البداية.")
            elif end and not start:
                self.add_error("starts_on", "أدخل تاريخ بداية الشراكة عند تحديد تاريخ النهاية.")
            elif start and end < start:
                self.add_error("ends_on", "لا يمكن أن يسبق تاريخ نهاية الشراكة تاريخ بدايتها.")

        entity, kind = data.get("entity"), data.get("entity_type")
        if kind == EntityType.GOVERNMENT and not entity and "entity" not in self.errors:
            # The hidden field still needs a valid FK; retain a legacy government
            # reference on edit, otherwise use an existing active classification.
            if self.instance and self.instance.entity.entity_type == EntityType.GOVERNMENT:
                entity = self.instance.entity
            else:
                entity = Entity.objects.filter(entity_type=EntityType.GOVERNMENT, is_active=True).order_by("pk").first()
            if entity is None:
                self.add_error("entity_type", "فعّل كيانًا حكوميًا في إدارة الكيانات قبل حفظ جهة حكومية.")
            else:
                data["entity"] = entity
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
