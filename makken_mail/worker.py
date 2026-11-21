"""Bounded delivery of committed notifications, with rechecked entitlements."""
from datetime import timedelta
import logging

from django.urls import reverse
from django.db import connection, transaction
from django.utils import timezone

from .events import can_receive, email_digest
from .models import Delivery, DeliveryStatus as Status, SMTPConfig, WorkStatus
from .registry import CATALOG, MODULES, PARTNERSHIP_EXPIRY
from .reminders import PARTNERSHIP_MODEL, business_date, can_receive_reminder, is_due, reminder_source
from .smtp import SendFailure, message_link, ready, send
from .targets import SCOPED_MODELS, record, record_label, record_path
from access_control.activity_data import audit_timezone, clean_text

logger = logging.getLogger(__name__)
RETRY_MINUTES = (5, 30, 120)
CLAIM_TIMEOUT = timedelta(minutes=10)
MAX_AGE = timedelta(days=2)


@transaction.atomic
def claim(now):
    pending = Delivery.objects.filter(status=Status.QUEUED, next_at__lte=now).order_by('next_at', 'pk')
    if connection.features.has_select_for_update:
        pending = pending.select_for_update(skip_locked=connection.features.has_select_for_update_skip_locked)
    delivery = pending.first()
    if delivery is None:
        return None
    changed = Delivery.objects.filter(pk=delivery.pk, status=Status.QUEUED).update(
        status=Status.SENDING, last_at=now, attempts=delivery.attempts + 1, reason='')
    return delivery.pk if changed else None


def safe_label(value):
    return ' '.join(clean_text(value, 240).split())


def build_context(delivery, item):
    recipient, event, work = delivery.recipient, delivery.activity, delivery.work
    code = delivery.rule_id
    title = CATALOG[code].label
    details = []
    when = event.created_at if event else delivery.created_at
    details.append(('الوقت (الرياض)', timezone.localtime(when, audit_timezone()).strftime('%d/%m/%Y %H:%M')))
    path = reverse('makken_home')
    if code == PARTNERSHIP_EXPIRY:
        description = 'اقترب موعد انتهاء الشراكة التي تتابعها في منصة مكّن. افتح سجل الشراكة لمراجعة الإجراءات اللازمة.'
        details += [('الشراكة', safe_label(item.name)), ('تاريخ نهاية الشراكة', item.ends_on.isoformat())]
        path = record_path(item, 'partnerships')
    elif code.startswith('work.') and work:
        description = 'سُجّل تحديث على عمل تتابعه في منصة مكّن.'
        snap = delivery.work_history.snapshot if delivery.work_history else {}
        status = dict(WorkStatus.choices).get(snap.get('status'), '')
        details += [('العمل', safe_label(snap.get('title', work.title))), ('الحالة عند التحديث', status),
                    ('الإنجاز عند التحديث', str(snap.get('progress', 0)) + '%')]
        path = reverse('makken_mail:work_detail', args=[work.pk])
    elif code == 'agreement.clause_progress' and item is not None:
        description = 'تم تحديث نسبة إنجاز بند ضمن إحدى الشراكات.'
        details += [('الشراكة', safe_label(item.name)), ('البند', safe_label(event.after.get('clause', ''))),
                    ('نسبة الإنجاز', str(event.after.get('progress', 0)) + '%')]
        number = event.after.get('agreement_number', '')
        if number:
            details.append(('الاتفاقية', safe_label(number)))
        path = reverse('partnerships:clauses', args=[item.pk])
    elif code == 'account.regions_assigned':
        from partnerships.models import Partnership
        description = 'تم تعيين أو تحديث نطاق المناطق المسموح لك بها في منصة مكّن، وفيما يلي ملخص الشراكات والاتفاقيات المرتبطة بنطاقك.'
        subject = delivery.subject_user
        access = getattr(subject, 'makken_access', None) if subject else None
        if access and access.region_scope == 'selected':
            region_ids = list(access.allowed_regions.order_by('name').values_list('id', flat=True))
            names = list(access.allowed_regions.order_by('name').values_list('name', flat=True))
            region_text = '، '.join(names) if names else 'لم تُحدد مناطق'
            regional_qs = Partnership.objects.filter(
                is_active=True, administrative_regions__id__in=region_ids
            ).distinct().order_by('-pk') if region_ids else Partnership.objects.none()
        else:
            region_text = 'جميع المناطق'
            regional_qs = Partnership.objects.filter(is_active=True).order_by('-pk')
        if subject:
            details.append(('الحساب', safe_label(subject.get_username())))
        details.append(('المناطق المعينة', safe_label(region_text)))
        partner_count = regional_qs.count()
        details.append(('عدد الشراكات والاتفاقيات في النطاق', str(partner_count)))
        if partner_count:
            sample = []
            for p in regional_qs[:5]:
                num = f' ({p.agreement_number})' if p.agreement_number else ''
                sample.append(f'{p.name}{num}')
            summary_text = '، '.join(sample)
            if partner_count > 5:
                summary_text += f' (+{partner_count - 5} أخرى)'
            details.append(('أبرز الشراكات والاتفاقيات', safe_label(summary_text)))
        if delivery.actor:
            details.append(('منفّذ الإجراء', safe_label(delivery.actor.get_full_name() or delivery.actor.get_username())))
        path = reverse('partnerships:agreement_inquiries')
    elif code.startswith('account.') or event.module in {'accounts', 'access_control'}:
        description = 'تم تسجيل هذا الإجراء في منصة مكّن.'
        if code == 'account.created' and recipient.pk == delivery.subject_user_id:
            description = 'أُنشئ حساب باسمك على منصة مكّن. يمكنك فتح صفحة الدخول والتواصل مع الإدارة لاستلام بيانات الدخول عبر القناة المعتمدة.'
        elif code == 'account.created' and recipient.pk == delivery.actor_id:
            description = 'تم إنشاء حساب المستخدم الذي أضفته إلى منصة مكّن بنجاح.'
        elif code == 'account.edited' and recipient.pk == delivery.subject_user_id:
            description = 'تم تحديث حسابك أو صلاحياته على منصة مكّن.'
        if recipient.is_superuser or recipient.pk in (delivery.actor_id, delivery.subject_user_id):
            if delivery.subject_user:
                details.append(('الحساب', safe_label(delivery.subject_user.get_username())))
            if event.actor_id:
                details.append(('منفّذ الإجراء', safe_label(event.actor_name)))
        path = reverse('accounts:login')
    else:
        description = 'تم تسجيل إجراء في ' + MODULES.get(event.module, 'منصة مكّن') + '. افتح المنصة لمراجعة التفاصيل المتاحة لك.'
        if item is not None:
            details.append(('السجل', safe_label(record_label(item))))
        if event.actor_id:
            details.append(('منفّذ الإجراء', safe_label(event.actor_name)))
        if work and recipient.pk in (work.employee_id, work.manager_id):
            details.append(('العمل المرتبط', safe_label(work.title)))
        path = record_path(item, event.module)
    return {'title': title, 'description': description, 'details': details,
            'recipient_name': safe_label(recipient.get_short_name() or recipient.get_username()), 'link': message_link(path)}


def selected_record(delivery):
    if delivery.record_model in SCOPED_MODELS and delivery.record_key:
        return record(delivery.record_model, delivery.record_key)
    event = delivery.activity
    if event and event.target_model == 'care_states.statecolor' and event.target_key:
        return record(event.target_model, event.target_key)
    return None


def set_result(delivery, status, reason='', next_at=None):
    fields = {'status': status, 'reason': reason}
    if next_at is not None:
        fields['next_at'] = next_at
    Delivery.objects.filter(pk=delivery.pk, status=Status.SENDING, attempts=delivery.attempts).update(**fields)


def process(delivery_id, now=None):
    now = now or timezone.now()
    row = Delivery.objects.select_related('rule', 'recipient', 'actor', 'subject_user', 'activity',
                                          'work', 'work_history').get(pk=delivery_id)
    if row.status != Status.SENDING:
        return
    if row.created_at < now - MAX_AGE:
        set_result(row, Status.SKIPPED, 'expired')
        return
    config = SMTPConfig.objects.filter(pk=1).first()
    if not config or not config.enabled or not ready(config):
        set_result(row, Status.QUEUED, 'config', now + timedelta(minutes=5))
        return
    if row.rule_id not in CATALOG or not row.rule.enabled or row.recipient is None:
        set_result(row, Status.SKIPPED, 'eligibility')
        return
    item = selected_record(row)
    # A changed mailbox must not turn into a notice to a different person.
    if email_digest(row.recipient.email) != row.email_digest:
        set_result(row, Status.SKIPPED, 'eligibility')
        return
    if row.rule_id == PARTNERSHIP_EXPIRY:
        if (row.record_model != PARTNERSHIP_MODEL or not is_due(item, business_date(now))
                or row.source != reminder_source(item)):
            set_result(row, Status.SKIPPED, 'reminder_obsolete')
            return
        eligible = can_receive_reminder(row.recipient, row.rule, item)
    else:
        eligible = not (
            row.record_key and item is None and (not row.activity or row.activity.action != 'delete')
            or row.rule_id.startswith('work.') and row.work_history is None
        ) and can_receive(row.recipient, row.rule, row.actor_id, row.subject_user_id, row.work, row.activity, item)
    if not eligible:
        set_result(row, Status.SKIPPED, 'eligibility')
        return
    try:
        context = build_context(row, item)
        send(config, row.recipient.email, context, f'<makken-event-{row.pk}@makken-notifications.invalid>')
    except SendFailure as exc:
        if exc.unknown:
            set_result(row, Status.UNKNOWN, exc.code)
        elif exc.retry and row.attempts <= len(RETRY_MINUTES):
            set_result(row, Status.QUEUED, exc.code, now + timedelta(minutes=RETRY_MINUTES[row.attempts - 1]))
        else:
            set_result(row, Status.FAILED, exc.code)
    except Exception as exc:
        logger.error('Makken email delivery error (%s)', type(exc).__name__)
        set_result(row, Status.FAILED, 'internal')
    else:
        set_result(row, Status.SENT)


def run_batch(limit=20, max_seconds=45):
    import time
    now = timezone.now()
    Delivery.objects.filter(status=Status.SENDING, last_at__lte=now - CLAIM_TIMEOUT).update(
        status=Status.UNKNOWN, reason='claim_expired')
    Delivery.objects.filter(status=Status.QUEUED, created_at__lt=now - MAX_AGE).update(
        status=Status.SKIPPED, reason='expired')
    config = SMTPConfig.objects.filter(pk=1, enabled=True).first()
    if not ready(config):
        return 0
    end = time.monotonic() + max_seconds
    count = 0
    for _ in range(limit):
        if time.monotonic() >= end:
            break
        key = claim(timezone.now())
        if key is None:
            break
        process(key)
        count += 1
    return count
