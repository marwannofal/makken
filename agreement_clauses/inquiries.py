"""Unified partnership/agreement inquiry and multi-criteria search (US-18)."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode

from django import forms
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from core.pagination import resolve_page_size
from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Subquery, Sum
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from access_control.enforcement import module_view
from access_control.models import RegionScope
from access_control.policy import for_request
from access_control.regions import RegionalPolicy, scoped
from accounts.models import Department
from accounts.security import add_login_headers
from care_states.models import DevelopmentState
from makken_mail.models import WorkAssignment
from partnerships.models import Partnership, PartnershipTeamMember, TeamMemberRole
from regions.models import Region

from .models import ClauseAssignment, mean_progress
from .record_forms import name_of

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


def scoped_partnerships(user, *, policy=None):
    return scoped(
        Partnership.objects.filter(development_state_id=DevelopmentState.WILLINGNESS),
        user,
        policy=policy,
    )


def scoped_employee_queryset(base_qs, policy):
    User = get_user_model()
    p_ids = list(base_qs.values_list('pk', flat=True))
    works = WorkAssignment.objects.filter(target_model='partnerships.partnership', target_key__in=p_ids)
    existing_ids = set(works.values_list('employee_id', flat=True)) | set(works.values_list('manager_id', flat=True))
    existing_ids |= set(works.values_list('assignees__pk', flat=True))
    existing_ids.discard(None)
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


def scoped_region_queryset(policy):
    qs = Region.objects.filter(is_active=True).order_by('id')
    if policy.unrestricted:
        return qs
    return qs.filter(pk__in=policy.ids)


class EmployeeFilterChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return name_of(obj) + ('' if obj.is_active else ' (غير نشط)')


class DepartmentFilterChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name + ('' if obj.is_active else ' (غير نشط)')


class AgreementInquiryForm(forms.Form):
    q = forms.CharField(
        label='جهة الشراكة أو رقم الاتفاقية',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={'placeholder': 'ابحث باسم الجهة أو رقم الاتفاقية...'}),
    )
    year = forms.CharField(
        label='سنة الشراكة',
        required=False,
        max_length=10,
        widget=forms.NumberInput(attrs={'min': '1900', 'max': '2100', 'step': '1', 'inputmode': 'numeric', 'placeholder': 'مثال: 2026', 'dir': 'ltr'}),
    )
    region = forms.ModelChoiceField(
        label='المنطقة',
        queryset=Region.objects.none(),
        required=False,
        empty_label='جميع المناطق',
        widget=forms.Select(attrs={**SELECT_ATTRS, 'data-label': 'المنطقة'}),
    )
    signatory = forms.CharField(
        label='مسؤول التوقيع',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={'placeholder': 'اسم الموقّع عن المؤسسة أو الجهة...'}),
    )
    department = DepartmentFilterChoice(
        label='الإدارة المعنية',
        queryset=Department.objects.none(),
        required=False,
        empty_label='جميع الإدارات',
        widget=forms.Select(attrs={**SELECT_ATTRS, 'data-label': 'الإدارة المعنية'}),
    )
    team = forms.CharField(
        label='فريق العمل',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={'placeholder': 'الاسم، البريد، الجوال، أو الجهة...'}),
    )
    contact = forms.CharField(
        label='ضابط الاتصال',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={'placeholder': 'اسم ضابط الاتصال، البريد، أو الهاتف...'}),
    )
    representative = forms.CharField(
        label='ممثلو الإدارة والجهة',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={'placeholder': 'اسم ممثل الإدارة أو المؤسسة أو الجهة...'}),
    )
    employee = EmployeeFilterChoice(
        label='الموظف',
        queryset=get_user_model().objects.none(),
        required=False,
        empty_label='جميع الموظفين',
        widget=forms.Select(attrs={**SELECT_ATTRS, 'data-label': 'الموظف'}),
    )
    progress_min = forms.CharField(
        label='نسبة الإنجاز من (%)',
        required=False,
        max_length=10,
        widget=forms.NumberInput(attrs={'min': '0', 'max': '100', 'step': 'any', 'inputmode': 'decimal', 'placeholder': '0', 'dir': 'ltr'}),
    )
    progress_max = forms.CharField(
        label='نسبة الإنجاز إلى (%)',
        required=False,
        max_length=10,
        widget=forms.NumberInput(attrs={'min': '0', 'max': '100', 'step': 'any', 'inputmode': 'decimal', 'placeholder': '100', 'dir': 'ltr'}),
    )

    def __init__(self, *args, regions, departments, employees, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['region'].queryset = regions
        self.fields['department'].queryset = departments
        self.fields['employee'].queryset = employees
        for field in self.fields.values():
            field.error_messages.setdefault('invalid_choice', 'اختر قيمة صحيحة من القائمة.')

    def clean_year(self):
        return parse_year(self.cleaned_data.get('year'))

    def clean_progress_min(self):
        return parse_percentage(self.cleaned_data.get('progress_min'))

    def clean_progress_max(self):
        return parse_percentage(self.cleaned_data.get('progress_max'))

    def clean(self):
        cleaned = super().clean()
        for key in ('q', 'signatory', 'team', 'contact', 'representative'):
            cleaned[key] = ' '.join((cleaned.get(key) or '').split())
        low = cleaned.get('progress_min')
        high = cleaned.get('progress_max')
        if low is not None and high is not None and low > high:
            self.add_error('progress_max', 'يجب أن تكون النسبة القصوى أكبر من أو تساوي النسبة الدنيا.')
        return cleaned


def apply_inquiry_filters(queryset, cleaned):
    q = cleaned.get('q')
    if q:
        queryset = queryset.filter(
            Q(name__icontains=q)
            | Q(agreement_number__icontains=q)
            | Q(representative__icontains=q)
        )

    year = cleaned.get('year')
    if year is not None:
        queryset = queryset.filter(
            Q(signed_on__year=year)
            | Q(starts_on__year=year)
            | Q(partnership_date__startswith=f'{year}-')
        )

    region = cleaned.get('region')
    if region is not None:
        queryset = queryset.filter(
            Q(administrative_regions=region) | Q(signing_region=region)
        )

    signatory = cleaned.get('signatory')
    if signatory:
        queryset = queryset.filter(
            Q(institution_signatory__icontains=signatory)
            | Q(partner_signatory__icontains=signatory)
        )

    department = cleaned.get('department')
    if department is not None:
        queryset = queryset.filter(concerned_departments=department)

    team = cleaned.get('team')
    if team:
        team_match = PartnershipTeamMember.objects.filter(partnership_id=OuterRef('pk')).filter(
            Q(name__icontains=team)
            | Q(organization__icontains=team)
            | Q(email__icontains=team)
            | Q(phone__icontains=team)
        )
        queryset = queryset.filter(Exists(team_match))

    contact = cleaned.get('contact')
    if contact:
        contact_match = PartnershipTeamMember.objects.filter(
            partnership_id=OuterRef('pk'),
            role=TeamMemberRole.CONTACT,
        ).filter(
            Q(name__icontains=contact)
            | Q(organization__icontains=contact)
            | Q(email__icontains=contact)
            | Q(phone__icontains=contact)
        )
        queryset = queryset.filter(Exists(contact_match))

    rep = cleaned.get('representative')
    if rep:
        rep_match = PartnershipTeamMember.objects.filter(
            partnership_id=OuterRef('pk'),
            role=TeamMemberRole.REPRESENTATIVE,
        ).filter(
            Q(name__icontains=rep)
            | Q(organization__icontains=rep)
            | Q(email__icontains=rep)
            | Q(phone__icontains=rep)
        )
        queryset = queryset.filter(
            Exists(rep_match)
            | Q(institution_rep_name__icontains=rep)
            | Q(representative__icontains=rep)
        )

    employee = cleaned.get('employee')
    if employee is not None:
        emp_work = WorkAssignment.objects.filter(
            target_model='partnerships.partnership',
            target_key=OuterRef('pk'),
        ).filter(
            Q(employee=employee) | Q(manager=employee) | Q(assignees=employee)
        )
        queryset = queryset.filter(Exists(emp_work) | Q(responsible_employee=employee))

    clause_stats = (
        ClauseAssignment.objects.filter(partnership_id=OuterRef('pk'), agreement__isnull=True)
        .values('partnership_id')
        .annotate(c=Count('pk'), s=Sum('progress'))
    )
    queryset = queryset.annotate(
        clause_count_ann=Subquery(clause_stats.values('c')[:1]),
        clause_sum_ann=Subquery(clause_stats.values('s')[:1]),
    )

    low = cleaned.get('progress_min')
    high = cleaned.get('progress_max')
    if low is not None or high is not None:
        # Filter in Python-safe exact decimal math on annotated totals
        matching_ids = []
        for pk, c_count, c_sum in queryset.values_list('pk', 'clause_count_ann', 'clause_sum_ann'):
            pct = mean_progress(c_sum or 0, c_count or 0)
            if pct is None:
                continue
            if low is not None and pct < low:
                continue
            if high is not None and pct > high:
                continue
            matching_ids.append(pk)
        queryset = queryset.filter(pk__in=matching_ids)

    return queryset.distinct()


def _serialize_row(partnership, works_by_pk):
    clauses = list(partnership.agreement_clause_assignments.all())
    direct_clauses = [c for c in clauses if c.agreement_id is None]
    clause_count = len(direct_clauses)
    progress = mean_progress(sum(c.progress for c in direct_clauses), clause_count)
    teams = list(partnership.team_members.all())
    contacts = [m for m in teams if m.role == TeamMemberRole.CONTACT]
    reps = [m for m in teams if m.role == TeamMemberRole.REPRESENTATIVE]
    works = works_by_pk.get(partnership.pk, [])
    employees = []
    seen_emp = set()
    for w in works:
        for u in list(w.assignees.all()) or ([w.employee] if w.employee else []):
            if u and u.pk not in seen_emp:
                seen_emp.add(u.pk)
                employees.append(name_of(u))

    return {
        'partnership': partnership,
        'agreement_number': partnership.agreement_number or partnership.format_agreement_number(),
        'signed_on': partnership.signed_on,
        'expiry': partnership.calculated_expiry or partnership.ends_on,
        'signing_region': partnership.signing_region.name if partnership.signing_region else '',
        'admin_regions': list(partnership.administrative_regions.all()),
        'departments': list(partnership.concerned_departments.all()),
        'partnership_type': partnership.partnership_type.name if partnership.partnership_type else (partnership.get_preliminary_agreement_type_display() if partnership.preliminary_agreement_type else ''),
        'classification': partnership.agreement_classification.name if partnership.agreement_classification else '',
        'partnership_status': partnership.partnership_status.name if partnership.partnership_status else '',
        'teams': teams,
        'contacts': contacts,
        'representatives': reps,
        'employees': employees,
        'works': works,
        'clauses': direct_clauses,
        'clause_count': clause_count,
        'progress': progress,
    }


@module_view('agreement_inquiries')
@require_GET
def agreement_inquiries(request):
    policy = RegionalPolicy(request.user)
    base = scoped_partnerships(request.user, policy=policy)
    regions = scoped_region_queryset(policy)
    departments = Department.objects.all().order_by('id')
    employees = scoped_employee_queryset(base, policy)

    has_query = any(
        request.GET.get(k, '').strip()
        for k in ('q', 'year', 'region', 'signatory', 'department', 'team', 'contact', 'representative', 'employee', 'progress_min', 'progress_max')
    )
    form = AgreementInquiryForm(
        request.GET if has_query else None,
        regions=regions,
        departments=departments,
        employees=employees,
    )
    filter_error = False
    status_code = 200
    if has_query:
        if form.is_valid():
            filtered = apply_inquiry_filters(base, form.cleaned_data)
        else:
            filter_error = True
            status_code = 400
            filtered = base.none()
    else:
        filtered = apply_inquiry_filters(base, {})

    # Compute KPI statistics across ALL matching partnerships (US-18 stats for year, region, employee, etc.)
    stat_rows = [] if filter_error else list(filtered.values_list('pk', 'clause_count_ann', 'clause_sum_ann'))
    total_count = len(stat_rows)
    total_clauses = sum((c or 0) for _, c, _ in stat_rows)
    pct_values = [mean_progress(s or 0, c or 0) for _, c, s in stat_rows if c]
    avg_progress = (
        (sum(pct_values) / Decimal(len(pct_values))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if pct_values
        else None
    )
    completed_count = sum(1 for v in pct_values if v == Decimal('100.00'))
    stats = {
        'total_count': total_count,
        'avg_progress': avg_progress,
        'completed_count': completed_count,
        'total_clauses': total_clauses,
    }

    ordered = filtered.select_related(
        'entity', 'partnership_type', 'partnership_status', 'agreement_classification', 'signing_region'
    ).prefetch_related(
        'administrative_regions',
        'concerned_departments',
        'team_members',
        Prefetch('agreement_clause_assignments', queryset=ClauseAssignment.objects.filter(agreement__isnull=True).select_related('clause').order_by('id')),
    ).order_by('-pk')

    page_obj = Paginator(ordered, resolve_page_size(request, PAGE_SIZE)).get_page(request.GET.get('page'))
    page_ids = [p.pk for p in page_obj]
    works_by_pk = {}
    for w in WorkAssignment.objects.filter(target_model='partnerships.partnership', target_key__in=page_ids).select_related('employee', 'manager').prefetch_related('assignees'):
        works_by_pk.setdefault(w.target_key, []).append(w)

    rows = [_serialize_row(p, works_by_pk) for p in page_obj]

    detail_row = None
    if detail_id := request.GET.get('detail', '').strip():
        if detail_id.isascii() and detail_id.isdigit() and len(detail_id) < 19:
            detail_obj = get_object_or_404(
                base.select_related('entity', 'partnership_type', 'partnership_status', 'agreement_classification', 'signing_region').prefetch_related(
                    'administrative_regions',
                    'concerned_departments',
                    'team_members',
                    'willingness_attachments',
                    Prefetch('agreement_clause_assignments', queryset=ClauseAssignment.objects.filter(agreement__isnull=True).select_related('clause').order_by('id')),
                ),
                pk=int(detail_id),
            )
            detail_works = list(
                WorkAssignment.objects.filter(target_model='partnerships.partnership', target_key=detail_obj.pk)
                .select_related('employee', 'manager')
                .prefetch_related('assignees')
            )
            detail_row = _serialize_row(detail_obj, {detail_obj.pk: detail_works})

    query_params = {k: v for k, v in request.GET.items() if k not in {'page', 'detail'} and v.strip()}
    filter_query = urlencode(query_params)

    access = for_request(request)
    display_name = request.user.get_short_name() or request.user.get_username()
    context = {
        'page_heading': 'الاستعلامات',
        'active_page': 'agreement_inquiries',
        'display_name': display_name,
        'avatar_initial': display_name[:1],
        'form': form,
        'filter_error': filter_error,
        'has_query': has_query,
        'stats': stats,
        'rows': rows,
        'page_obj': page_obj,
        'detail_row': detail_row,
        'filter_query': filter_query,
        'can_edit': access.can('partnerships', 'edit'),
    }
    return add_login_headers(render(request, 'agreement_clauses/inquiries.html', context, status=status_code))
