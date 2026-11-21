"""US-01 employee agreement summaries and onboarding/regional notifications."""
import logging
from uuid import uuid4

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from agreement_clauses.models import Agreement, ClauseAssignment, mean_progress
from agreement_clauses.record_forms import name_of
from makken_mail.events import enqueue, has_address
from makken_mail.models import SMTPConfig, WorkAssignment
from makken_mail.smtp import SendFailure, message_link, ready, send
from partnerships.models import Partnership, PartnershipTeamMember

logger = logging.getLogger(__name__)
PARTNERSHIP_TARGET_MODEL = 'partnerships.partnership'


def _partnership_links_for_users(user_ids, emails_by_uid=None):
    """Map user_id -> {partnership_id: [role labels]} from WorkAssignment and team memberships."""
    links = {uid: {} for uid in user_ids}
    if not user_ids:
        return links

    def add_role(uid, pid, label):
        if uid not in links or not pid:
            return
        roles = links[uid].setdefault(pid, [])
        if label not in roles:
            roles.append(label)

    works = (
        WorkAssignment.objects.filter(target_model=PARTNERSHIP_TARGET_MODEL, target_key__isnull=False)
        .filter(Q(employee_id__in=user_ids) | Q(manager_id__in=user_ids) | Q(assignees__id__in=user_ids))
        .prefetch_related('assignees')
        .distinct()
    )
    for work in works:
        pid = work.target_key
        if work.employee_id in links:
            add_role(work.employee_id, pid, 'الموظف المسؤول')
        if work.manager_id in links:
            add_role(work.manager_id, pid, 'المشرف / المدير')
        for assignee in work.assignees.all():
            if assignee.pk in links and assignee.pk != work.employee_id:
                add_role(assignee.pk, pid, 'عضو مسند له')

    if emails_by_uid:
        uid_by_email = {
            email.strip().casefold(): uid
            for uid, email in emails_by_uid.items()
            if email and email.strip()
        }
        if uid_by_email:
            email_q = Q()
            for addr in uid_by_email:
                email_q |= Q(email__iexact=addr)
            for member in PartnershipTeamMember.objects.filter(email_q).only('partnership_id', 'email', 'role'):
                uid = uid_by_email.get((member.email or '').strip().casefold())
                if uid:
                    add_role(uid, member.partnership_id, member.get_role_display())

    return links


def employee_agreement_counts(users):
    """Return {user_id: total_unique_partnerships_and_agreements} for the US-01 user list."""
    user_list = list(users)
    user_ids = [u.pk for u in user_list]
    if not user_ids:
        return {}
    emails_by_uid = {u.pk: (u.email or '') for u in user_list}
    partner_links = _partnership_links_for_users(user_ids, emails_by_uid)

    from agreement_clauses.models import AgreementDetails
    seen = {uid: set(pids.keys()) for uid, pids in partner_links.items()}
    legacy_rows = AgreementDetails.objects.filter(
        Q(responsible_employee_id__in=user_ids) | Q(department_representative_id__in=user_ids)
    ).values_list('responsible_employee_id', 'department_representative_id', 'agreement__partnership_id', 'agreement_id')
    for resp_id, rep_id, pid, agr_id in legacy_rows:
        key = pid or f'agr:{agr_id}'
        if resp_id in seen:
            seen[resp_id].add(key)
        if rep_id in seen:
            seen[rep_id].add(key)
    return {uid: len(items) for uid, items in seen.items()}


def employee_agreements_summary(user):
    """Return unified partnerships and legacy agreements linked to the employee with progress and last follow-up."""
    if not user or not user.pk:
        return []

    rows = []
    seen_partnership_ids = set()

    # 1. Unified Partnership (رغبة / شراكة) records linked via WorkAssignment or PartnershipTeamMember
    partner_roles = _partnership_links_for_users([user.pk], {user.pk: user.email or ''}).get(user.pk, {})
    if partner_roles:
        pids = list(partner_roles.keys())
        clause_totals = {}
        clause_counts = {}
        latest_clause_updates = {}
        clause_qs = ClauseAssignment.objects.filter(
            Q(partnership_id__in=pids) | Q(agreement__partnership_id__in=pids)
        ).select_related('updated_by')
        for ca in clause_qs:
            owner_pid = ca.partnership_id or (ca.agreement.partnership_id if ca.agreement_id else None)
            if owner_pid not in partner_roles:
                continue
            clause_totals[owner_pid] = clause_totals.get(owner_pid, 0) + (ca.progress or 0)
            clause_counts[owner_pid] = clause_counts.get(owner_pid, 0) + 1
            prev = latest_clause_updates.get(owner_pid)
            if ca.updated_at and (prev is None or ca.updated_at > prev[0]):
                latest_clause_updates[owner_pid] = (ca.updated_at, ca.updated_by)

        partnerships = (
            Partnership.objects.filter(pk__in=pids)
            .select_related('partnership_type', 'development_state', 'followup_updated_by', 'created_by')
            .order_by('-pk')
        )
        inquiries_base = reverse('partnerships:agreement_inquiries')
        for p in partnerships:
            seen_partnership_ids.add(p.pk)
            if p.followup_updated_at:
                last_at, last_by = p.followup_updated_at, p.followup_updated_by
            elif p.pk in latest_clause_updates:
                last_at, last_by = latest_clause_updates[p.pk]
            else:
                last_at, last_by = p.updated_at or p.created_at, p.created_by

            c_count = clause_counts.get(p.pk, 0)
            c_total = clause_totals.get(p.pk, 0)
            subtitle = (
                p.partnership_type.name
                if p.partnership_type_id
                else (p.development_state.name if p.development_state_id else 'شراكة')
            )
            rows.append({
                'kind': 'partnership',
                'agreement': None,
                'partnership': p,
                'details': None,
                'number': p.agreement_number or f'#{p.pk}',
                'title': p.name,
                'subtitle': subtitle,
                'roles': partner_roles.get(p.pk, []),
                'progress': mean_progress(c_total, c_count),
                'clause_count': c_count,
                'last_followup_at': last_at,
                'last_followup_by': name_of(last_by) if last_by else '—',
                'detail_url': f'{inquiries_base}?detail={p.pk}',
                'secondary_url': reverse('partnerships:edit', args=[p.pk]),
                'secondary_label': 'بيانات الشراكة',
            })

    # 2. Legacy Agreement records (retained for backwards compatibility)
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
    agreements = (
        Agreement.objects.filter(
            Q(details__responsible_employee=user) | Q(details__department_representative=user)
        )
        .annotate(
            clause_count=Coalesce(Subquery(counts, output_field=IntegerField()), Value(0)),
            clause_total=Coalesce(Subquery(totals, output_field=IntegerField()), Value(0)),
        )
        .select_related(
            'partnership',
            'details',
            'details__status',
            'details__updated_by',
            'created_by',
            'followup_state',
            'followup_state__updated_by',
        )
        .prefetch_related('clause_assignments__updated_by')
        .order_by('-pk')
    )
    for agreement in agreements:
        if agreement.partnership_id in seen_partnership_ids:
            continue
        details = getattr(agreement, 'details', None)
        state = getattr(agreement, 'followup_state', None)
        if state:
            last_at, last_by = state.updated_at, state.updated_by
        else:
            candidates = [(agreement.created_at, agreement.created_by)]
            if details and details.updated_at:
                candidates.append((details.updated_at, details.updated_by))
            for row in agreement.clause_assignments.all():
                candidates.append((row.updated_at, row.updated_by))
            last_at, last_by = max(candidates, key=lambda pair: pair[0])

        roles = []
        if details and details.responsible_employee_id == user.pk:
            roles.append('الموظف المسؤول')
        if details and details.department_representative_id == user.pk:
            roles.append('ممثل الإدارة المعنية')

        rows.append({
            'kind': 'agreement',
            'agreement': agreement,
            'partnership': agreement.partnership,
            'details': details,
            'number': agreement.number,
            'title': agreement.title,
            'subtitle': agreement.partnership.name,
            'roles': roles,
            'progress': mean_progress(agreement.clause_total, agreement.clause_count),
            'clause_count': agreement.clause_count,
            'last_followup_at': last_at,
            'last_followup_by': name_of(last_by) if last_by else '—',
            'detail_url': reverse('partnerships:agreement', args=[agreement.partnership.pk, agreement.pk]),
            'secondary_url': reverse('partnerships:agreement_details', args=[agreement.partnership.pk, agreement.pk]),
            'secondary_label': 'بيانات الاتفاقية',
        })
    return rows


@sensitive_variables('initial_password')
def send_welcome_credentials_email(user, initial_password, *, must_change_password=True, region_summary=''):
    """Send onboarding credentials via makken_mail SMTP without persisting the password."""
    if not user or not has_address(user):
        return 'skipped'
    config = SMTPConfig.objects.filter(pk=1, enabled=True).first()
    if not config or not ready(config):
        return 'smtp_disabled'

    from access_control.activity_data import audit_timezone
    details = [
        ('البريد الإلكتروني', user.email),
        ('اسم المستخدم', user.get_username()),
        ('كلمة المرور الأولية', initial_password),
    ]
    if region_summary:
        details.append(('نطاق المناطق', region_summary))
    details.append((
        'الوقت (الرياض)',
        timezone.localtime(timezone.now(), audit_timezone()).strftime('%d/%m/%Y %H:%M'),
    ))

    if must_change_password:
        description = (
            'تم إنشاء حسابك في منصة مكّن بنجاح. استخدم بيانات الدخول أدناه لتسجيل الدخول، '
            'ويجب تغيير كلمة المرور فور دخولك الأول إلى المنصة.'
        )
    else:
        description = 'تم إنشاء حسابك في منصة مكّن بنجاح. يمكنك استخدام بيانات الدخول أدناه للوصول إلى المنصة.'

    context = {
        'title': 'بيانات الدخول لحسابك الجديد في مكّن',
        'description': description,
        'details': details,
        'recipient_name': user.get_short_name() or user.get_username(),
        'link': message_link(reverse('accounts:login')),
    }
    domain = config.sender.rsplit('@', 1)[-1] if '@' in config.sender else 'makken.local'
    message_id = f'<welcome-{user.pk}-{uuid4().hex}@{domain}>'
    try:
        send(config, user.email, context, message_id)
        return 'sent'
    except SendFailure as exc:
        logger.warning('Welcome email delivery failed for user %s (%s)', user.pk, exc.code)
        return 'failed'


def enqueue_regional_assignment_email(actor_id, target_user_id, version):
    """Queue a makken_mail notification when an employee's regional scope is assigned/updated."""
    return enqueue(
        'account.regions_assigned',
        f'regions:{target_user_id}:v{version}',
        actor_id=actor_id,
        subject_id=target_user_id,
    )
