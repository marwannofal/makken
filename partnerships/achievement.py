"""US-08 Partnership achievement reports by year, region, sector, activity, and status."""
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from access_control.enforcement import module_view
from access_control.regions import RegionalPolicy, scoped
from accounts.security import add_login_headers
from agreement_clauses.models import AgreementOption, ClauseAssignment, OptionKind, mean_progress
from care_states.models import DevelopmentState
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization

from .models import Partnership

GROUP_CHOICES = (
    ('region', 'حسب المنطقة'),
    ('year', 'حسب السنة'),
    ('sector', 'حسب القطاع'),
    ('activity', 'حسب النشاط / التخصص'),
    ('status', 'حسب الحالة'),
)
GROUP_LABELS = dict(GROUP_CHOICES)
GROUP_COLUMN_HEADERS = {
    'region': 'المنطقة',
    'year': 'السنة',
    'sector': 'القطاع',
    'activity': 'النشاط / التخصص',
    'status': 'الحالة',
}


def _allowed_regions(actor):
    reg = RegionalPolicy(actor)
    qs = Region.objects.filter(is_active=True).order_by('name')
    if actor.is_superuser or reg.unrestricted:
        return qs, None
    return qs.filter(pk__in=reg.ids), set(reg.ids)


def _partnership_year(partnership):
    if partnership.starts_on:
        return partnership.starts_on.year
    signed_years = []
    for agr in partnership.agreements.all():
        details = getattr(agr, 'details', None)
        if details and details.signed_on:
            signed_years.append(details.signed_on.year)
    if signed_years:
        return max(signed_years)
    return partnership.created_at.year if partnership.created_at else None


def _available_years(base_qs):
    years = set()
    for p in base_qs.prefetch_related('agreements__details'):
        yr = _partnership_year(p)
        if yr:
            years.add(yr)
        if p.starts_on:
            years.add(p.starts_on.year)
        for agr in p.agreements.all():
            details = getattr(agr, 'details', None)
            if details and details.signed_on:
                years.add(details.signed_on.year)
    return sorted(years, reverse=True)


def _bulk_progress(partnership_ids):
    """Return {partnership_id: (Decimal progress, clause_count)} matching workflow.partnership_progress."""
    if not partnership_ids:
        return {}
    totals = {}
    counts = {}
    rows = ClauseAssignment.objects.filter(
        Q(partnership_id__in=partnership_ids) | Q(agreement__partnership_id__in=partnership_ids)
    ).values_list('partnership_id', 'agreement__partnership_id', 'progress')
    for direct_pid, agr_pid, prog in rows:
        owner = direct_pid or agr_pid
        if owner is None:
            continue
        totals[owner] = totals.get(owner, 0) + (prog or 0)
        counts[owner] = counts.get(owner, 0) + 1
    return {
        pid: (mean_progress(totals.get(pid, 0), counts.get(pid, 0)), counts.get(pid, 0))
        for pid in partnership_ids
    }


def _decimal_mean(values):
    if not values:
        return Decimal('0.00')
    total = sum(values, Decimal('0'))
    return (total / Decimal(len(values))).quantize(Decimal('0.01'))


def build_achievement_report(actor, params):
    """Build filtered and grouped partnership achievement statistics within actor's regional scope."""
    errors = []
    base_qs = scoped(Partnership.objects.all(), actor)

    regions_qs, _ = _allowed_regions(actor)
    region_choices = list(regions_qs)
    allowed_region_ids = {r.pk for r in region_choices}
    sector_choices = list(Sector.objects.filter(is_active=True).order_by('name'))
    activity_choices = list(
        Specialization.objects.filter(is_active=True).select_related('sector').order_by('sector__name', 'name')
    )
    agreement_status_choices = list(
        AgreementOption.objects.filter(kind=OptionKind.STATUS, is_active=True).order_by('name')
    )
    year_choices = _available_years(base_qs)

    raw_year = (params.get('year') or '').strip()
    raw_region = (params.get('region') or '').strip()
    raw_sector = (params.get('sector') or '').strip()
    raw_activity = (params.get('activity') or '').strip()
    raw_status = (params.get('status') or '').strip()
    raw_group = (params.get('group_by') or 'region').strip()
    q = (params.get('q') or '').strip()[:120]

    group_by = raw_group if raw_group in GROUP_LABELS else 'region'

    selected_year = None
    if raw_year:
        if raw_year.isdigit() and 1900 <= int(raw_year) <= 2100:
            selected_year = int(raw_year)
        else:
            errors.append('قيمة السنة غير صالحة.')

    selected_region = None
    if raw_region:
        if raw_region.isdigit() and int(raw_region) in allowed_region_ids:
            selected_region = int(raw_region)
        else:
            errors.append('المنطقة المحددة غير متاحة ضمن نطاق صلاحياتك.')

    selected_sector = None
    if raw_sector:
        if raw_sector.isdigit() and any(s.pk == int(raw_sector) for s in sector_choices):
            selected_sector = int(raw_sector)
        else:
            errors.append('القطاع المحدد غير صالح.')

    selected_activity = None
    if raw_activity:
        if raw_activity.isdigit() and any(a.pk == int(raw_activity) for a in activity_choices):
            selected_activity = int(raw_activity)
        else:
            errors.append('النشاط / التخصص المحدد غير صالح.')

    valid_status_tokens = (
        {'active', 'inactive'}
        | {f'dev:{code}' for code in DevelopmentState.values}
        | {f'agr:{opt.pk}' for opt in agreement_status_choices}
    )
    selected_status = ''
    if raw_status:
        if raw_status in valid_status_tokens:
            selected_status = raw_status
        else:
            errors.append('الحالة المحددة غير صالحة.')

    empty_totals = {
        'partnership_count': 0,
        'active_count': 0,
        'agreement_count': 0,
        'clause_count': 0,
        'completed_count': 0,
        'in_progress_count': 0,
        'avg_progress': Decimal('0.00'),
    }
    result = {
        'rows': [],
        'groups': [],
        'totals': empty_totals,
        'errors': errors,
        'years': year_choices,
        'regions': region_choices,
        'sectors': sector_choices,
        'activities': activity_choices,
        'development_states': [(f'dev:{code}', label) for code, label in DevelopmentState.choices],
        'agreement_statuses': [(f'agr:{opt.pk}', opt.name) for opt in agreement_status_choices],
        'group_choices': GROUP_CHOICES,
        'group_by': group_by,
        'group_label': GROUP_LABELS[group_by],
        'group_column_header': GROUP_COLUMN_HEADERS[group_by],
        'selected_year': selected_year,
        'selected_region': selected_region,
        'selected_sector': selected_sector,
        'selected_activity': selected_activity,
        'selected_status': selected_status,
        'q': q,
    }
    if errors:
        return result

    qs = base_qs.select_related('entity', 'development_state').prefetch_related(
        'administrative_regions',
        'offerings__sector',
        'offerings__specializations',
        'agreements__details__status',
    )

    if selected_year is not None:
        qs = qs.filter(
            Q(starts_on__year=selected_year)
            | Q(agreements__details__signed_on__year=selected_year)
            | Q(starts_on__isnull=True, created_at__year=selected_year)
        )
    if selected_region is not None:
        qs = qs.filter(administrative_regions__pk=selected_region)
    if selected_sector is not None:
        qs = qs.filter(offerings__sector_id=selected_sector)
    if selected_activity is not None:
        qs = qs.filter(offerings__specializations__pk=selected_activity)
    if selected_status == 'active':
        qs = qs.filter(is_active=True)
    elif selected_status == 'inactive':
        qs = qs.filter(is_active=False)
    elif selected_status.startswith('dev:'):
        qs = qs.filter(development_state_id=selected_status.split(':', 1)[1])
    elif selected_status.startswith('agr:'):
        qs = qs.filter(agreements__details__status_id=int(selected_status.split(':', 1)[1]))
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(representative__icontains=q))

    partnerships = list(qs.distinct())
    progress_map = _bulk_progress([p.pk for p in partnerships])

    rows = []
    group_buckets = {}

    def _add_to_group(label, row):
        bucket = group_buckets.setdefault(label, {
            'label': label,
            'partnership_count': 0,
            'active_count': 0,
            'agreement_count': 0,
            'completed_count': 0,
            'progress_values': [],
        })
        bucket['partnership_count'] += 1
        if row['is_active']:
            bucket['active_count'] += 1
        bucket['agreement_count'] += row['agreement_count']
        if row['progress'] >= Decimal('100'):
            bucket['completed_count'] += 1
        bucket['progress_values'].append(row['progress'])

    total_agreements = 0
    total_clauses = 0
    completed_count = 0
    in_progress_count = 0
    active_count = 0
    all_progress = []

    for p in partnerships:
        progress, clause_count = progress_map.get(p.pk, (Decimal('0.00'), 0))
        agreements = list(p.agreements.all())
        agreement_count = len(agreements)
        yr = _partnership_year(p)

        region_names = sorted({r.name for r in p.administrative_regions.all()})
        sector_names = sorted({o.sector.name for o in p.offerings.all() if o.sector_id})
        activity_names = sorted({
            sp.name for o in p.offerings.all() for sp in o.specializations.all()
        })
        agr_status_names = sorted({
            agr.details.status.name
            for agr in agreements
            if getattr(agr, 'details', None) and agr.details.status_id
        })
        dev_label = p.development_state.get_state_display() if p.development_state_id else '—'
        active_label = 'نشطة' if p.is_active else 'غير نشطة'

        row = {
            'partnership': p,
            'pk': p.pk,
            'name': p.name,
            'year': yr,
            'year_label': str(yr) if yr else 'غير محدد',
            'regions_label': '، '.join(region_names) if region_names else 'غير محدد',
            'sectors_label': '، '.join(sector_names) if sector_names else 'غير محدد',
            'activities_label': '، '.join(activity_names) if activity_names else 'غير محدد',
            'status_label': f'{active_label} · {dev_label}',
            'agreement_statuses_label': '، '.join(agr_status_names) if agr_status_names else '—',
            'is_active': p.is_active,
            'agreement_count': agreement_count,
            'clause_count': clause_count,
            'progress': progress,
        }
        rows.append(row)

        total_agreements += agreement_count
        total_clauses += clause_count
        if p.is_active:
            active_count += 1
        if progress >= Decimal('100'):
            completed_count += 1
        elif progress > Decimal('0'):
            in_progress_count += 1
        all_progress.append(progress)

        if group_by == 'region':
            labels = region_names or ['غير محدد']
        elif group_by == 'year':
            labels = [row['year_label']]
        elif group_by == 'sector':
            labels = sector_names or ['غير محدد']
        elif group_by == 'activity':
            labels = activity_names or ['غير محدد']
        else:  # status
            labels = [row['status_label']]

        for lbl in labels:
            _add_to_group(lbl, row)

    rows.sort(key=lambda r: (-r['progress'], -r['agreement_count'], r['name']))

    groups = []
    for bucket in group_buckets.values():
        groups.append({
            'label': bucket['label'],
            'partnership_count': bucket['partnership_count'],
            'active_count': bucket['active_count'],
            'agreement_count': bucket['agreement_count'],
            'completed_count': bucket['completed_count'],
            'avg_progress': _decimal_mean(bucket['progress_values']),
        })
    if group_by == 'year':
        groups.sort(key=lambda g: (g['label'] == 'غير محدد', g['label']), reverse=True)
    else:
        groups.sort(key=lambda g: (-g['partnership_count'], -g['avg_progress'], g['label']))

    result['rows'] = rows
    result['groups'] = groups
    result['totals'] = {
        'partnership_count': len(rows),
        'active_count': active_count,
        'agreement_count': total_agreements,
        'clause_count': total_clauses,
        'completed_count': completed_count,
        'in_progress_count': in_progress_count,
        'avg_progress': _decimal_mean(all_progress),
    }
    return result


@module_view('partnerships')
@require_GET
def partnership_achievement_report(request):
    report = build_achievement_report(request.user, request.GET)
    name = request.user.get_short_name() or request.user.get_username()
    return add_login_headers(render(request, 'partnerships/achievement_report.html', {
        'display_name': name,
        'avatar_initial': name[:1],
        'active_page': 'partnership_achievement',
        'page_heading': 'تقرير إنجاز الشراكات',
        'report': report,
    }))
