"""Precise SAR amounts and server-side filtering for partnership registers."""
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlencode

from django import forms
from django.db.models import Min, Max, Q
from django.http import HttpResponseRedirect
from django.urls import reverse

MAX_CAPACITY = Decimal('999999999999.99')


def normalize_money(value):
    text = str(value).strip()
    if len(text) > 40:
        raise forms.ValidationError('أدخل مبلغًا صحيحًا دون تجاوز الحد المسموح.')
    text = ''.join(str(int(char)) if char.isdecimal() else char for char in text)
    text = text.replace('٬', ',').replace('٫', '.')
    if ',' in text:
        if not re.fullmatch(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?', text):
            raise forms.ValidationError('أدخل مبلغًا صحيحًا؛ مثال: 1,250.50.')
        text = text.replace(',', '')
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', text):
        raise forms.ValidationError('أدخل مبلغًا صحيحًا دون حروف أو صيغة أسية.')
    return text


class MoneyField(forms.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 14)
        kwargs.setdefault('decimal_places', 2)
        kwargs.setdefault('min_value', Decimal('0'))
        kwargs.setdefault('max_value', MAX_CAPACITY)
        kwargs.setdefault('error_messages', {
            'required': 'أدخل القدرة المالية بالريال السعودي.',
            'invalid': 'أدخل مبلغًا صحيحًا بالريال السعودي.',
            'min_value': 'لا يمكن أن تكون القدرة المالية أقل من صفر.',
            'max_value': 'المبلغ يتجاوز الحد الأقصى 999,999,999,999.99 ريال.',
            'max_digits': 'المبلغ يتجاوز عدد الأرقام المسموح.',
            'max_decimal_places': 'استخدم منزلتين عشريتين كحد أقصى.',
            'max_whole_digits': 'الحد الأقصى 12 رقمًا قبل الفاصلة العشرية.',
        })
        kwargs.setdefault('widget', forms.TextInput(attrs={'inputmode': 'decimal', 'dir': 'ltr', 'maxlength': '40', 'autocomplete': 'off', 'placeholder': '0.00'}))
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value in self.empty_values or (isinstance(value, str) and not value.strip()):
            return None
        return super().to_python(normalize_money(value))


def amount_string(value):
    return format(value, '.2f') if value is not None else ''


class FinancialRangeForm(forms.Form):
    capacity_min = MoneyField(required=False, label='من', widget=forms.TextInput(attrs={'id': 'capacity-min', 'inputmode': 'decimal', 'dir': 'ltr', 'maxlength': '40', 'placeholder': 'بدون حد أدنى', 'aria-describedby': 'capacity-filter-errors'}))
    capacity_max = MoneyField(required=False, label='إلى', widget=forms.TextInput(attrs={'id': 'capacity-max', 'inputmode': 'decimal', 'dir': 'ltr', 'maxlength': '40', 'placeholder': 'بدون حد أعلى', 'aria-describedby': 'capacity-filter-errors'}))

    def clean(self):
        data = super().clean()
        low, high = data.get('capacity_min'), data.get('capacity_max')
        if low is not None and high is not None and low > high:
            raise forms.ValidationError('الحد الأدنى يجب ألا يتجاوز الحد الأعلى للقدرة المالية.')
        return data


def financial_search_clause(value):
    try:
        amount = MoneyField(required=False).clean(value)
    except forms.ValidationError:
        return Q(pk__in=[])
    return Q(financial_capacity=amount) if amount is not None else Q(pk__in=[])


class FinancialRange:
    def __init__(self, request, queryset):
        self.form = FinancialRangeForm(request.GET)
        self.valid = self.form.is_valid()
        bounds = queryset.aggregate(low=Min('financial_capacity'), high=Max('financial_capacity'))
        self.queryset = queryset
        self.params = {}
        self.active = any(request.GET.get(key, '').strip() for key in ('capacity_min', 'capacity_max'))
        low = self.form.cleaned_data.get('capacity_min')
        high = self.form.cleaned_data.get('capacity_max')
        if not self.valid:
            self.queryset = queryset.none()
            self.params = {key: request.GET.get(key, '')[:40] for key in ('capacity_min', 'capacity_max') if request.GET.get(key, '')}
        else:
            for key, value, lookup in [('capacity_min', low, 'financial_capacity__gte'), ('capacity_max', high, 'financial_capacity__lte')]:
                if value is not None:
                    self.queryset = self.queryset.filter(**{lookup: value})
                    self.params[key] = amount_string(value)
        minimum, maximum = bounds['low'], bounds['high']
        self.context = {
            'financial_range_form': self.form,
            'financial_filter_active': self.active,
            'financial_has_bounds': minimum is not None,
            'financial_bounds_min': amount_string(minimum),
            'financial_bounds_max': amount_string(maximum),
            'financial_slider_min': amount_string(max(minimum, min(maximum, low))) if minimum is not None and low is not None else amount_string(minimum),
            'financial_slider_max': amount_string(max(minimum, min(maximum, high))) if minimum is not None and high is not None else amount_string(maximum),
            'financial_slider_disabled': minimum is None or minimum == maximum,
        }


def financial_redirect(request):
    params = {}
    for key in ('q', 'status', 'page', 'capacity_min', 'capacity_max', 'development_state'):
        value = request.GET.get(key, '')[:200 if key == 'q' else 40]
        if value:
            params[key] = value
    return HttpResponseRedirect(reverse('partnerships:index') + ('?' + urlencode(params) if params else ''))
