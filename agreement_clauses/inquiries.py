"""Agreement inquiry and multi-criteria search (US-18)."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import forms
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Exists, ExpressionWrapper, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.views.decorators.http import require_GET

from access_control.enforcement import module_view
from access_control.models import RegionScope
from access_control.policy import for_request
from access_control.regions import RegionalPolicy, scoped
from accounts.security import add_login_headers
from partnerships.models import Partnership, PartnershipRegion
from regions.models import Region

from .models import (
    Agreement,
    AgreementDetails,
    AgreementMember,
    AgreementOption,
    ClauseAssignment,
    OptionKind,
    TeamRole,
    mean_progress,
)
from .record_forms import name_of
from .records import current_expiry

ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫', '01234567890123456789.')
SELECT_ATTRS = {'data-market-select': ''}
PAGE_SIZE = 15
MIN_YEAR = 1900
MAX_YEAR = 2100


def normalize_digits(value):
    return (value or '').strip().translate(ARABIC_DIGITS)


def parse_year(raw):
    text = normalize_digits(raw)
    if not text:
        return None
    if not text.isascii() or not text.isdigit():
        raise forms.ValidationError('أدخل سنة صالحة مكوّنة من أربعة أرقام.')
    year = int(text)
    if not (MIN_YEAR <= year <= MAX_YEAR):
        raise forms.ValidationError(f'أدخل سنة بين {MIN_YEAR} و{MAX_YEAR}.')
    return year


def parse_percentage(raw):
    text = normalize_digits(raw).replace('%', '').replace('٪', '').strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise forms.ValidationError('أدخل نسبة مئوية صالحة بين 0 و100.') from None
    if not value.is_finite() or value < Decimal('0') or value > Decimal('100'):
        raise forms.ValidationError('يجب أن تكون النسبة بين 0 و100.')
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise forms.ValidationError('يُسمح بحد أقصى منزلتين عشريتين لنسبة الإنجاز.')
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def scoped_agreements(user, *, policy=None):
    partnerships = scoped(Partnership.objects.all(), user, policy=policy)
    return Agreement.objects.filter(partnership_id__in=partnerships.values('pk'))


def scoped_employee_queryset(base_agreements, policy):
    User = get_user_model()
    assigned_ids = (
        AgreementDetails.objects.filter(agreement_id__in=base_agreements.values('pk'))
        .values_list('responsible_employee_id', 'department_representative_id')
    )
    existing_ids = {pk for pair in assigned_ids for pk in pair if pk}
    if policy.unrestricted:
        return User.objects.filter(Q(is_active=True) | Q(pk__in=existing_ids)).order_by(
            'first_name', 'last_name', User.USERNAME_FIELD
        ).distinct()
    in_scope = (
        Q(is_superuser=True)
        | Q(makken_access__region_scope=RegionScope.ALL)
        | Q(makken_access__allowed_regions__in=policy.ids)
    )
    return User.objects.filter((Q(is_active=True) & in_scope) | Q(pk__in=existing_ids)).order_by(
        'first_name', 'last_name', User.USERNAME_FIELD
    ).distinct()


def department_queryset(base_agreements):
    used_ids = AgreementDetails.objects.filter(
        agreement_id__in=base_agreements.values('pk'),
        departments__isnull=False,
    ).values('departments')
    return AgreementOption.objects.filter(kind=OptionKind.DEPARTMENT).filter(
        Q(is_active=True) | Q(pk__in=used_ids)
    ).order_by('name', 'pk')


class DepartmentFilterChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        label = f'{obj.name} · {obj.get_department_type_display()}'
        return label if obj.is_active else f'{label} (غير نشط)'


class EmployeeFilterChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return name_of(obj)


class AgreementInquiryForm(forms.Form):
    year = forms.CharField(
        label='سنة الاتفاقية',
        required=False,
        max_length=4,
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric',
            'dir': 'ltr',
            'placeholder': 'مثال: 2026',
            'list': 'agreement-inquiry-years',
            'autocomplete': 'off',
        }),
    )
    region = forms.ModelChoiceField(
        label='المنطقة',
        queryset=Region.objects.none(),
        required=False,
        empty_label='جميع المناطق',
        widget=forms.Select(attrs=SELECT_ATTRS),
        error_messages={'invalid_choice': 'اختر منطقة متاحة ضمن نطاق صلاحياتك.'},
    )
    signatory = forms.CharField(
        label='الموقّع',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={
            'placeholder': 'اسم الموقّع عن المؤسسة أو الجهة…',
            'autocomplete': 'off',
        }),
    )
    department = DepartmentFilterChoice(
        label='الإدارة المعنية',
        queryset=AgreementOption.objects.none(),
        required=False,
        empty_label='جميع الإدارات والوحدات',
        widget=forms.Select(attrs=SELECT_ATTRS),
        error_messages={'invalid_choice': 'اختر إدارة أو وحدة صالحة من القائمة.'},
    )
    team = forms.CharField(
        label='فريق العمل',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={
            'placeholder': 'الاسم، الجهة، البريد، أو الهاتف…',
            'autocomplete': 'off',
        }),
    )
    contact = forms.CharField(
        label='ضابط الاتصال',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={
            'placeholder': 'اسم ضابط الاتصال، البريد، أو الهاتف…',
            'autocomplete': 'off',
        }),
    )
    employee = EmployeeFilterChoice(
        label='الموظف',
        queryset=get_user_model().objects.none(),
        required=False,
        empty_label='جميع الموظفين',
        widget=forms.Select(attrs=SELECT_ATTRS),
        error_messages={'invalid_choice': 'اختر موظفًا صالحًا من القائمة.'},
    )
    progress_min = forms.CharField(
        label='نسبة الإنجاز من (%)',
        required=False,
        max_length=8,
        widget=forms.TextInput(attrs={
            'inputmode': 'decimal',
            'dir': 'ltr',
            'placeholder': '0',
            'autocomplete': 'off',
        }),
    )
    progress_max = forms.CharField(
        label='نسبة الإنجاز إلى (%)',
        required=False,
        max_length=8,
        widget=forms.TextInput(attrs={
            'inputmode': 'decimal',
            'dir': 'ltr',
            'placeholder': '100',
            'autocomplete': 'off',
        }),
    )

    def __init__(self, *args, regions, departments, employees, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['region'].queryset = regions
        self.fields['department'].queryset = departments
        self.fields['employee'].queryset = employees

    def clean_year(self):
        return parse_year(self.cleaned_data.get('year'))

    def clean_signatory(self):
        return ' '.join((self.cleaned_data.get('signatory') or '').split())

    def clean_team(self):
        return ' '.join((self.cleaned_data.get('team') or '').split())

    def clean_contact(self):
        return ' '.join((self.cleaned_data.get('contact') or '').split())

    def clean_progress_min(self):
        return parse_percentage(self.cleaned_data.get('progress_min'))

    def clean_progress_max(self):
        return parse_percentage(self.cleaned_data.get('progress_max'))

    def clean(self):
        data = super().clean()
        low = data.get('progress_min')
        high = data.get('progress_max')
        if low is not None and high is not None and low > high:
            self.add_error('progress_max', 'يجب أن تكون النسبة العليا أكبر من أو تساوي النسبة الدنيا.')
        return data

    def has_active_filters(self):
        if not self.is_bound:
            return False
        return any(bool((self.data.get(name) or '').strip()) for name in self.fields)


def _member_match_subquery(term, *, role=None):
    members = AgreementMember.objects.filter(agreement_id=OuterRef('pk'))
    if role is not None:
        members = members.filter(role=role)
    for word in term.split()[:10]:
        ascii_word = normalize_digits(word)
        clause = (
            Q(name__icontains=word)
            | Q(organization__icontains=word)
            | Q(email__icontains=word)
            | Q(phone__icontains=word)
        )
        if ascii_word and ascii_word != word:
            clause |= Q(phone__icontains=ascii_word)
        members = members.filter(clause)
    return Exists(members)


def _annotate_progress(queryset):
    counts = (
        ClauseAssignment.objects.filter(agreement_id=OuterRef('pk'))
        .values('agreement_id')
        .annotate(value=Count('pk'))
        .values('value')[:1]
    )
    totals = (
        ClauseAssignment.objects.filter(agreement_id=OuterRef('pk'))
        .values('agreement_id')
        .annotate(value=Sum('progress'))
        .values('value')[:1]
    )
    return queryset.annotate(
        clause_count=Coalesce(Subquery(counts, output_field=IntegerField()), Value(0)),
        clause_total=Coalesce(Subquery(totals, output_field=IntegerField()), Value(0)),
    )


def apply_inquiry_filters(queryset, cleaned):
    queryset = _annotate_progress(queryset)

    year = cleaned.get('year')
    if year is not None:
        queryset = queryset.filter(details__signed_on__year=year)

    region = cleaned.get('region')
    if region is not None:
        partner_region = PartnershipRegion.objects.filter(
            partnership_id=OuterRef('partnership_id'),
            region_id=region.pk,
        )
        queryset = queryset.filter(Exists(partner_region) | Q(details__signing_region_id=region.pk))

    signatory = cleaned.get('signatory')
    if signatory:
        for word in signatory.split()[:10]:
            queryset = queryset.filter(
                Q(details__institution_signatory__icontains=word)
                | Q(details__partner_signatory__icontains=word)
                | Q(details__institution_signatory_title__icontains=word)
                | Q(details__partner_signatory_title__icontains=word)
            )

    department = cleaned.get('department')
    if department is not None:
        dept_match = AgreementDetails.objects.filter(
            agreement_id=OuterRef('pk'),
            departments=department,
        )
        queryset = queryset.filter(Exists(dept_match))

    team = cleaned.get('team')
    if team:
        queryset = queryset.filter(_member_match_subquery(team))

    contact = cleaned.get('contact')
    if contact:
        queryset = queryset.filter(_member_match_subquery(contact, role=TeamRole.CONTACT))

    employee = cleaned.get('employee')
    if employee is not None:
        queryset = queryset.filter(
            Q(details__responsible_employee=employee) | Q(details__department_representative=employee)
        )

    low = cleaned.get('progress_min')
    high = cleaned.get('progress_max')
    if low is not None or high is not None:
        # Agreements without clauses have no progress percentage (None) and do not match numeric ranges.
        queryset = queryset.filter(clause_count__gt=0).annotate(
            progress_scaled=ExpressionWrapper(F('clause_total') * Value(200), output_field=IntegerField()),
        )
        # Exact integer-hundredths equivalent of ROUND_HALF_UP(total / count, 2) in mean_progress().
        if low is not None:
            low_h = int((low * Decimal('100')).to_integral_value(rounding=ROUND_HALF_UP))
            if low_h > 0:
                queryset = queryset.annotate(
                    progress_low_bound=ExpressionWrapper(
                        F('clause_count') * Value(2 * low_h - 1),
                        output_field=IntegerField(),
                    ),
                ).filter(progress_scaled__gte=F('progress_low_bound'))
        if high is not None:
            high_h = int((high * Decimal('100')).to_integral_value(rounding=ROUND_HALF_UP))
            queryset = queryset.annotate(
                progress_high_bound=ExpressionWrapper(
                    F('clause_count') * Value(2 * high_h + 1),
                    output_field=IntegerField(),
                ),
            ).filter(progress_scaled__lt=F('progress_high_bound'))

    return queryset


def build_result_row(agreement):
    details = getattr(agreement, 'details', None)
    members = list(agreement.members.all())
    contacts = [member for member in members if member.role == TeamRole.CONTACT]
    departments = list(details.departments.all()) if details else []
    regions = list(agreement.partnership.administrative_regions.all())
    progress = mean_progress(agreement.clause_total, agreement.clause_count)
    expiry = current_expiry(agreement, details) if details else None
    return {
        'agreement': agreement,
        'partnership': agreement.partnership,
        'details': details,
        'regions': regions,
        'departments': departments,
        'members': members,
        'contacts': contacts,
        'team_count': len(members),
        'progress': progress,
        'clause_count': agreement.clause_count,
        'expiry': expiry,
        'responsible_name': name_of(details.responsible_employee) if details and details.responsible_employee else '',
        'representative_name': name_of(details.department_representative) if details and details.department_representative else '',
    }


@module_view('partnerships')
@require_GET
def agreement_inquiries(request):
    regional_policy = RegionalPolicy(request.user)
    base = scoped_agreements(request.user, policy=regional_policy)

    regions = scoped(Region.objects.all(), policy=regional_policy).order_by('name')
    departments = department_queryset(base)
    employees = scoped_employee_queryset(base, regional_policy)
    available_years = [
        item.year
        for item in AgreementDetails.objects.filter(
            agreement_id__in=base.values('pk'),
            signed_on__isnull=False,
        ).dates('signed_on', 'year', order='DESC')
    ]

    form = AgreementInquiryForm(
        request.GET or None,
        regions=regions,
        departments=departments,
        employees=employees,
    )

    filter_active = form.has_active_filters()
    filter_error = False
    if form.is_bound:
        if form.is_valid():
            queryset = apply_inquiry_filters(base, form.cleaned_data)
        else:
            queryset = base.none()
            filter_error = True
    else:
        queryset = _annotate_progress(base)

    queryset = queryset.select_related(
        'partnership',
        'details',
        'details__status',
        'details__signing_region',
        'details__responsible_employee',
        'details__department_representative',
    ).prefetch_related(
        'partnership__administrative_regions',
        'details__departments',
        'members',
        'renewals',
    ).order_by('-pk')

    status = 400 if filter_error and getattr(request, '_makken_export_internal', False) else 200
    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get('page'))
    rows = [build_result_row(item) for item in page_obj.object_list]

    params = request.GET.copy()
    for key in ('page', '_mk_export', '_mk_table'):
        params.pop(key, None)

    policy = for_request(request)
    name = request.user.get_short_name() or request.user.get_username()
    context = {
        'page_heading': 'الاستعلامات',
        'active_page': 'agreement_inquiries',
        'display_name': name,
        'avatar_initial': name[:1],
        'form': form,
        'rows': rows,
        'page_obj': page_obj,
        'pagination_query': params.urlencode(),
        'filter_active': filter_active,
        'filter_error': filter_error,
        'available_years': available_years,
        'can_open_agreement': policy.can('partnerships', 'view'),
    }
    return add_login_headers(render(request, 'agreement_clauses/inquiries.html', context, status=status))
