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
from makken_mail.models import SMTPConfig
from makken_mail.smtp import SendFailure, message_link, ready, send

logger = logging.getLogger(__name__)


def employee_agreements_summary(user):
    """Return agreements where the employee is responsible or department representative."""
    if not user or not user.pk:
        return []
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
    rows = []
    for agreement in agreements:
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
            'agreement': agreement,
            'partnership': agreement.partnership,
            'details': details,
            'roles': roles,
            'progress': mean_progress(agreement.clause_total, agreement.clause_count),
            'clause_count': agreement.clause_count,
            'last_followup_at': last_at,
            'last_followup_by': name_of(last_by) if last_by else '—',
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
