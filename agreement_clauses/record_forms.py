import re

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from access_control.models import RegionScope
from access_control.policy import AccessPolicy
from access_control.regions import scoped
from expense_items.models import normalize_name
from regions.models import Region

from .calendar import end_after_months
from .models import Agreement, AgreementDetails, AgreementMember, AgreementOption, OptionKind, RenewalRule

OPTION_FIELDS = {
    'entity_type': OptionKind.ENTITY, 'status': OptionKind.STATUS,
    'partnership_type': OptionKind.PARTNERSHIP_TYPE, 'classification': OptionKind.CLASSIFICATION,
    'headquarters_city': OptionKind.CITY, 'signing_city': OptionKind.CITY,
}
STAFF_FIELDS = ('responsible_employee', 'department_representative')
DETAIL_FIELDS = [
    *OPTION_FIELDS, 'departments', 'signing_region', *STAFF_FIELDS, 'institution_signatory',
    'institution_signatory_title', 'partner_signatory', 'partner_signatory_title',
    'partner_phone', 'partner_email', 'signed_on', 'duration_months', 'renewal_rule',
    'objective', 'announcement', 'audience', 'expected_results',
]
SELECT = {'data-market-select': ''}
PHONE = forms.TextInput(attrs={'type': 'tel', 'dir': 'ltr', 'autocomplete': 'off'})


def clean_phone(value):
    if not value:
        return ''
    value = value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789'))
    if not re.fullmatch(r'\+?[0-9(). -]+', value) or not 7 <= sum(c.isdigit() for c in value) <= 15:
        raise forms.ValidationError('أدخل رقم هاتف صالحًا (من 7 إلى 15 رقمًا).')
    return value


def name_of(user):
    return user.get_full_name() or user.get_username()


class DepartmentChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} · {obj.get_department_type_display()}'


class StaffChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return name_of(obj)


class LocalErrors:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.error_messages.update(
                required='هذا الحقل مطلوب.',
                invalid='القيمة المدخلة غير صالحة.',
                invalid_choice='اختر قيمة من القائمة المتاحة.',
            )
            if isinstance(field.widget, forms.EmailInput):
                field.widget.attrs['dir'] = 'ltr'


class DetailsForm(LocalErrors, forms.ModelForm):
    signed_on = forms.DateField(
        label='تاريخ التوقيع', required=False, input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'dir': 'ltr'}),
    )
    departments = DepartmentChoice(
        label='الإدارات المعنية', queryset=AgreementOption.objects.none(),
        required=False, widget=forms.SelectMultiple(attrs=SELECT),
    )

    class Meta:
        model = AgreementDetails
        fields = DETAIL_FIELDS
        field_classes = {field: StaffChoice for field in STAFF_FIELDS}
        widgets = {
            'partner_phone': PHONE,
            'duration_months': forms.NumberInput(attrs={'min': 1, 'max': 600, 'inputmode': 'numeric', 'dir': 'ltr'}),
            **{field: forms.Textarea(attrs={'rows': 3}) for field in ('objective', 'announcement', 'audience', 'expected_results')},
        }

    def __init__(self, *args, agreement, **kwargs):
        super().__init__(*args, **kwargs)
        self.agreement = agreement
        for field, kind in OPTION_FIELDS.items():
            self.fields[field].queryset = AgreementOption.objects.filter(kind=kind).filter(
                Q(is_active=True) | Q(pk=getattr(self.instance, f'{field}_id'))
            )
        selected = self.instance.departments.values_list('pk', flat=True) if self.instance.pk else []
        self.fields['departments'].queryset = AgreementOption.objects.filter(kind=OptionKind.DEPARTMENT).filter(
            Q(is_active=True) | Q(pk__in=selected)
        )
        self.fields['signing_region'].queryset = Region.objects.filter(
            Q(is_active=True) | Q(pk=self.instance.signing_region_id)
        ).order_by('name')
        users = get_user_model().objects.order_by('first_name', 'last_name', get_user_model().USERNAME_FIELD)
        regions = agreement.partnership.administrative_regions.values('pk')
        in_scope = (
            Q(is_superuser=True) | Q(makken_access__region_scope=RegionScope.ALL)
            | Q(makken_access__allowed_regions__in=regions)
        )
        for field in STAFF_FIELDS:
            self.fields[field].queryset = users.filter(
                (Q(is_active=True) & in_scope) | Q(pk=getattr(self.instance, f'{field}_id'))
            ).distinct()
        for field in [*OPTION_FIELDS, *STAFF_FIELDS, 'signing_region']:
            self.fields[field].widget.attrs.update(SELECT)
        if agreement.renewals.exists():
            for field in ('signed_on', 'duration_months'):
                self.fields[field].disabled = True
        self.expiry_preview = self.instance.initial_expiry

    def clean_partner_phone(self):
        return clean_phone(self.cleaned_data['partner_phone'])

    def clean(self):
        data = super().clean()
        start, months = data.get('signed_on'), data.get('duration_months')
        if 'signed_on' in data and 'duration_months' in data:
            if start and not months:
                self.add_error('duration_months', 'أدخل المدة لحساب تاريخ الانتهاء.')
            elif months and not start:
                self.add_error('signed_on', 'أدخل تاريخ التوقيع لحساب تاريخ الانتهاء.')
            elif start and months:
                try:
                    self.expiry_preview = end_after_months(start, months)
                except ValueError:
                    self.add_error('duration_months', 'ينتج عن هذه المدة تاريخ انتهاء خارج النطاق المدعوم.')
        for field in STAFF_FIELDS:
            user = data.get(field)
            if user and user.pk != getattr(self.instance, f'{field}_id'):
                if not (AccessPolicy(user).can('partnerships') and
                        scoped(type(self.agreement.partnership).objects.filter(pk=self.agreement.partnership_id), user).exists()):
                    self.add_error(field, 'يجب أن يملك المستخدم صلاحية عرض هذه الشراكة ومنطقتها.')
        return data


class MemberForm(LocalErrors, forms.ModelForm):
    class Meta:
        model = AgreementMember
        fields = ['name', 'organization', 'role', 'phone', 'email']
        widgets = {'phone': PHONE}

    def clean_name(self):
        return normalize_name(self.cleaned_data['name'])

    def clean_phone(self):
        return clean_phone(self.cleaned_data['phone'])


class TeamFormSet(BaseInlineFormSet):
    default_error_messages = {
        'missing_management_form': 'بيانات الفريق غير مكتملة. حدّث الصفحة وحاول مجددًا.',
        'too_many_forms': 'يمكن حفظ 30 عضوًا كحد أقصى لكل فريق.',
    }

    def __init__(self, *args, side, **kwargs):
        self.side = side
        super().__init__(*args, **kwargs)

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields['id'].queryset = self.get_queryset()
        form.fields['DELETE'].label = 'إزالة هذا العضو عند الحفظ'

    def save_new(self, form, commit=True):
        form.instance.side = self.side
        return super().save_new(form, commit=commit)


TeamForms = inlineformset_factory(
    Agreement, AgreementMember, form=MemberForm, formset=TeamFormSet,
    fields=MemberForm.Meta.fields, max_num=30, validate_max=True, absolute_max=60,
    extra=1, can_delete=True,
)


class RenewalForm(LocalErrors, forms.Form):
    duration_months = forms.IntegerField(label='مدة التجديد بالأشهر', min_value=1, max_value=600)
    approval_reference = forms.CharField(label='مرجع الموافقة المسبقة', max_length=160, required=False)

    def __init__(self, *args, start, rule, **kwargs):
        super().__init__(*args, **kwargs)
        self.start, self.rule = start, rule
        if rule != RenewalRule.PRIOR_APPROVAL:
            del self.fields['approval_reference']

    def clean(self):
        data = super().clean()
        if 'approval_reference' in data and not data['approval_reference']:
            self.add_error('approval_reference', 'أدخل مرجع الموافقة لتسجيل هذا التجديد.')
        if self.start and data.get('duration_months'):
            try:
                data['expires_on'] = end_after_months(self.start, data['duration_months'])
            except ValueError:
                self.add_error('duration_months', 'ينتج عن هذه المدة تاريخ انتهاء خارج النطاق المدعوم.')
        return data


class OptionForm(LocalErrors, forms.ModelForm):
    class Meta:
        model = AgreementOption
        fields = ['name', 'department_type']

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.kind = kind
        if kind == OptionKind.DEPARTMENT:
            self.fields['department_type'].required = True
        else:
            del self.fields['department_type']

    def clean_name(self):
        name = normalize_name(self.cleaned_data['name'])
        if AgreementOption.objects.filter(kind=self.instance.kind, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('هذا الاسم موجود بالفعل في القائمة.')
        return name
