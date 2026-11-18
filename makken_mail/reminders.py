"""Schedule partnership expiry notifications in business calendar time."""
from calendar import monthrange
from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from access_control.activity_data import audit_timezone
from partnerships.models import Partnership

from .events import email_digest, has_address
from .models import Delivery, EventRule, RecipientMute, SMTPConfig, WorkAssignment, WorkStatus
from .registry import PARTNERSHIP_EXPIRY
from .smtp import ready
from .targets import can_read_record

PARTNERSHIP_MODEL = 'partnerships.partnership'


def business_date(now=None):
    return timezone.localdate(now, audit_timezone())


def shifted_month(day, months, *, last_day=False):
    year, month_index = divmod(day.year * 12 + day.month - 1 + months, 12)
    month = month_index + 1
    length = monthrange(year, month)[1]
    return date(year, month, length if last_day else min(day.day, length))


def reminder_source(partnership):
    return f'partnership-expiry:{partnership.pk}:{partnership.ends_on.isoformat()}'


def is_due(partnership, today):
    return bool(partnership and partnership.is_active and partnership.ends_on and
                today < partnership.ends_on and shifted_month(partnership.ends_on, -2) <= today)


def open_assignments(partnership_id):
    return WorkAssignment.objects.filter(
        target_model=PARTNERSHIP_MODEL, target_key=partnership_id,
        status__in=(WorkStatus.NEW, WorkStatus.RUNNING),
    ).order_by()


def can_receive_reminder(user, rule, partnership):
    if not user.is_active or not has_address(user):
        return False
    routes = Q(pk__in=[])
    if rule.to_employee:
        routes |= Q(employee_id=user.pk)
    if rule.to_manager:
        routes |= Q(manager_id=user.pk)
    return (
        open_assignments(partnership.pk).filter(routes).exists()
        and not RecipientMute.objects.filter(rule=rule, user=user).exists()
        and can_read_record(user, partnership, 'partnerships')
    )


def queue_due_reminders(now=None):
    rule = EventRule.objects.filter(pk=PARTNERSHIP_EXPIRY, enabled=True).first()
    if not rule or not (rule.to_employee or rule.to_manager):
        return 0
    if not ready(SMTPConfig.objects.filter(pk=1, enabled=True).first()):
        return 0

    today = business_date(now)
    # At month end all later days in the target month can map back to today
    # (e.g. April 29 and 30 both map to February 28 in a non-leap year).
    candidates = Partnership.objects.filter(
        is_active=True, ends_on__gt=today, ends_on__lte=shifted_month(today, 2, last_day=True),
    ).filter(Exists(open_assignments(OuterRef('pk')))).order_by('pk')
    queued = 0
    for partnership in candidates.iterator(chunk_size=200):
        if not is_due(partnership, today):
            continue
        source = reminder_source(partnership)
        assignments = open_assignments(partnership.pk)
        recipient_ids = set()
        if rule.to_employee:
            recipient_ids.update(assignments.values_list('employee_id', flat=True))
        if rule.to_manager:
            recipient_ids.update(assignments.values_list('manager_id', flat=True))
        recipient_ids.difference_update(Delivery.objects.filter(source=source).values_list('recipient_key', flat=True))
        users = get_user_model().objects.filter(pk__in=recipient_ids, is_active=True)
        for user in users.order_by('pk').iterator(chunk_size=200):
            if not can_receive_reminder(user, rule, partnership):
                continue
            # MySQL's unique constraint on (source, recipient_key) also
            # protects against two scheduler invocations running concurrently.
            _, created = Delivery.objects.get_or_create(
                source=source, recipient_key=user.pk,
                defaults={
                    'rule': rule, 'recipient': user, 'email_digest': email_digest(user.email),
                    'record_model': PARTNERSHIP_MODEL, 'record_key': partnership.pk,
                },
            )
            queued += int(created)
    return queued
