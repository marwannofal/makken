"""US-07 task assignment statistics per employee over a date range."""
from datetime import date, datetime, time, timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Q, Subquery
from django.utils import timezone

from access_control.models import RegionScope
from access_control.policy import AccessPolicy
from access_control.regions import RegionalPolicy, scoped
from regions.models import Region

from .models import WorkAssignment, WorkStatus
from .targets import WORK_TARGETS

User = get_user_model()


def _parse_date(raw, label):
    text = (raw or '').strip()
    if not text:
        return None, None
    try:
        return date.fromisoformat(text), None
    except ValueError:
        return None, f'صيغة {label} غير صحيحة. استخدم الصيغة YYYY-MM-DD.'


def _allowed_regions(actor):
    reg = RegionalPolicy(actor)
    qs = Region.objects.filter(is_active=True).order_by('name')
    if actor.is_superuser or reg.unrestricted:
        return qs, None
    return qs.filter(pk__in=reg.ids), set(reg.ids)


def _visible_assignments(actor):
    qs = WorkAssignment.objects.select_related('employee', 'manager').prefetch_related('assignees')
    if actor.is_superuser:
        return qs
    policy = AccessPolicy(actor)
    from partnerships.models import Partnership

    visible = Q(target_model='')
    for model, spec in WORK_TARGETS.items():
        if policy.can(spec.module):
            if model == 'agreement_clauses.agreement':
                from agreement_clauses.models import Agreement
                p_ids = scoped(Partnership._base_manager.all(), actor).order_by().values('pk')
                ids = Agreement._base_manager.filter(partnership_id__in=Subquery(p_ids)).order_by().values('pk')
            else:
                ids = scoped(apps.get_model(model)._base_manager.all(), actor).order_by().values('pk')
            visible |= Q(target_model=model, target_key__in=Subquery(ids))
    return qs.filter(visible).distinct()


def _employee_regions_label(user):
    access = getattr(user, 'makken_access', None)
    if user.is_superuser or (access and access.region_scope == RegionScope.ALL):
        return 'جميع المناطق'
    if not access:
        return '—'
    names = [r.name for r in access.allowed_regions.all()]
    return '، '.join(names) if names else '—'


def _employee_department(user):
    profile = getattr(user, 'makken_profile', None)
    if profile and profile.department:
        return profile.department.name
    return '—'


def build_work_stats(actor, params):
    """Return scoped per-employee assignment statistics for the requested filters."""
    errors = []
    date_from, err_from = _parse_date(params.get('date_from'), 'تاريخ البداية')
    date_to, err_to = _parse_date(params.get('date_to'), 'تاريخ النهاية')
    if err_from:
        errors.append(err_from)
    if err_to:
        errors.append(err_to)
    if date_from and date_to and date_from > date_to:
        errors.append('تاريخ البداية يجب أن يسبق تاريخ النهاية أو يساويه.')

    regions_qs, restricted_region_ids = _allowed_regions(actor)
    region_choices = list(regions_qs)
    allowed_region_id_set = {r.pk for r in region_choices}

    raw_region = (params.get('region') or '').strip()
    selected_region = None
    if raw_region:
        if raw_region.isdigit() and int(raw_region) in allowed_region_id_set:
            selected_region = int(raw_region)
        else:
            errors.append('المنطقة المحددة غير متاحة ضمن نطاق صلاحياتك.')

    q = (params.get('q') or '').strip()[:120]
    show_empty = params.get('show_empty') in {'1', 'true', 'on'}

    empty_totals = {
        'distinct_tasks': 0,
        'total_assignments': 0,
        'new': 0,
        'running': 0,
        'complete': 0,
        'cancelled': 0,
        'overdue': 0,
        'avg_progress': 0,
        'completion_rate': 0,
        'employee_count': 0,
    }
    base_result = {
        'rows': [],
        'totals': empty_totals,
        'errors': errors,
        'regions': region_choices,
        'selected_region': selected_region,
        'date_from': params.get('date_from', '').strip(),
        'date_to': params.get('date_to', '').strip(),
        'q': q,
        'show_empty': show_empty,
    }
    if errors:
        return base_result

    # Scope candidate employees strictly by regional policy + optional region/search filters.
    employees_qs = (
        User.objects.select_related('makken_profile__department', 'makken_access')
        .prefetch_related('makken_access__allowed_regions')
    )
    if restricted_region_ids is not None:
        if not restricted_region_ids:
            return base_result
        employees_qs = employees_qs.filter(
            makken_access__allowed_regions__in=restricted_region_ids
        ).distinct()

    if selected_region is not None:
        employees_qs = employees_qs.filter(
            Q(makken_access__allowed_regions__pk=selected_region)
            | Q(makken_access__region_scope=RegionScope.ALL)
            | Q(is_superuser=True)
        ).distinct()

    if q:
        employees_qs = employees_qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(username__icontains=q)
            | Q(email__icontains=q)
        )

    scoped_employees = {u.pk: u for u in employees_qs}
    if not scoped_employees:
        return base_result

    # Filter visible work assignments by date range (timezone-aware local day boundaries).
    assignments_qs = _visible_assignments(actor)
    tz = timezone.get_current_timezone()
    if date_from:
        start_dt = timezone.make_aware(datetime.combine(date_from, time.min), tz)
        assignments_qs = assignments_qs.filter(created_at__gte=start_dt)
    if date_to:
        end_dt = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), tz)
        assignments_qs = assignments_qs.filter(created_at__lt=end_dt)

    today = timezone.localdate()
    buckets = {}
    counted_task_ids = set()

    def _bucket(uid):
        if uid not in buckets:
            buckets[uid] = {
                'user': scoped_employees[uid],
                'total': 0,
                'new': 0,
                'running': 0,
                'complete': 0,
                'cancelled': 0,
                'overdue': 0,
                'progress_sum': 0,
            }
        return buckets[uid]

    for task in assignments_qs:
        assignee_ids = {u.pk for u in task.assignees.all()}
        if not assignee_ids and task.employee_id:
            assignee_ids = {task.employee_id}
        matched_ids = [uid for uid in assignee_ids if uid in scoped_employees]
        if not matched_ids:
            continue
        counted_task_ids.add(task.pk)
        is_overdue = bool(
            task.due_on
            and task.due_on < today
            and task.status in {WorkStatus.NEW, WorkStatus.RUNNING}
        )
        for uid in matched_ids:
            b = _bucket(uid)
            b['total'] += 1
            if task.status == WorkStatus.NEW:
                b['new'] += 1
            elif task.status == WorkStatus.RUNNING:
                b['running'] += 1
            elif task.status == WorkStatus.COMPLETE:
                b['complete'] += 1
            elif task.status == WorkStatus.CANCELLED:
                b['cancelled'] += 1
            if is_overdue:
                b['overdue'] += 1
            b['progress_sum'] += task.progress

    if show_empty:
        for uid, user in scoped_employees.items():
            if user.is_active and uid not in buckets:
                _bucket(uid)

    rows = []
    tot_assignments = tot_new = tot_running = tot_complete = tot_cancelled = tot_overdue = tot_progress = 0
    for b in buckets.values():
        user = b['user']
        total = b['total']
        avg_progress = round(b['progress_sum'] / total) if total else 0
        completion_rate = round((b['complete'] / total) * 100) if total else 0
        display_name = user.get_full_name().strip() or user.get_username()
        rows.append({
            'user': user,
            'display_name': display_name,
            'username': user.get_username(),
            'department': _employee_department(user),
            'regions_label': _employee_regions_label(user),
            'total': total,
            'new': b['new'],
            'running': b['running'],
            'complete': b['complete'],
            'cancelled': b['cancelled'],
            'overdue': b['overdue'],
            'avg_progress': avg_progress,
            'completion_rate': completion_rate,
        })
        tot_assignments += total
        tot_new += b['new']
        tot_running += b['running']
        tot_complete += b['complete']
        tot_cancelled += b['cancelled']
        tot_overdue += b['overdue']
        tot_progress += b['progress_sum']

    rows.sort(key=lambda r: (-r['total'], -r['complete'], r['display_name']))

    base_result['rows'] = rows
    base_result['totals'] = {
        'distinct_tasks': len(counted_task_ids),
        'total_assignments': tot_assignments,
        'new': tot_new,
        'running': tot_running,
        'complete': tot_complete,
        'cancelled': tot_cancelled,
        'overdue': tot_overdue,
        'avg_progress': round(tot_progress / tot_assignments) if tot_assignments else 0,
        'completion_rate': round((tot_complete / tot_assignments) * 100) if tot_assignments else 0,
        'employee_count': len(rows),
    }
    return base_result
