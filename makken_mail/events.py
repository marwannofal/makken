"""Route live activity without copying audit payloads or recipient addresses."""
import hashlib
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from access_control.policy import AccessPolicy
from .models import Delivery, EventRule, RecipientMute, SMTPConfig, WorkAssignment
from .registry import CATALOG, activity_code
from .targets import SCOPED_MODELS, audit_scope, can_read_record, can_read_work, is_assignee, record

User = get_user_model()


def email_digest(value):
    return hashlib.sha256(value.strip().casefold().encode()).hexdigest()


def has_address(user):
    try:
        validate_email(user.email)
    except ValidationError:
        return False
    return True


def can_receive(user, rule, actor_id=None, subject_id=None, work=None, event=None, item=None):
    if not user.is_active or not has_address(user):
        return False
    if rule.recipients.filter(pk=user.pk).exists():
        routed = True
    else:
        routed = (
            (rule.to_actor and user.pk == actor_id) or
            (rule.to_subject and user.pk == subject_id) or
            (work and rule.to_employee and is_assignee(user, work)) or
            (work and rule.to_manager and user.pk == work.manager_id)
        )
    if not routed or RecipientMute.objects.filter(rule=rule, user=user).exists():
        return False
    if rule.code.startswith('work.'):
        return bool(work and can_read_work(user, work))
    if rule.code == 'account.regions_assigned':
        return True
    if event is None:
        return False
    if rule.code.startswith('account.') or event.module in {'accounts', 'access_control'}:
        return True  # Message renderer redacts account events for other recipients.
    if not AccessPolicy(user).can(event.module) or not audit_scope(user, event):
        return False
    if (work and work.target_model and not can_read_work(user, work) and
        user.pk not in (actor_id, subject_id) and not rule.recipients.filter(pk=user.pk).exists()):
        return False
    if item is not None:
        return can_read_record(user, item, event.module)
    return not event.target_key or event.action == 'delete'


@transaction.atomic
def enqueue(code, source, *, actor_id=None, subject_id=None, event=None, item=None, history=None, assignments=()):
    event_type = CATALOG.get(code)
    if not event_type or not SMTPConfig.objects.filter(pk=1, enabled=True).exists():
        return 0
    rule = EventRule.objects.filter(pk=code, enabled=True).first()
    if rule is None:
        return 0
    assigned = tuple(assignments) if event_type.work else ()
    ids = set(rule.recipients.values_list('pk', flat=True))
    if rule.to_actor and actor_id:
        ids.add(actor_id)
    if rule.to_subject and subject_id:
        ids.add(subject_id)
    for work in assigned:
        if rule.to_employee:
            ids.add(work.employee_id)
            ids.update(work.assignees.values_list('pk', flat=True))
        if rule.to_manager:
            ids.add(work.manager_id)
    if not ids:
        return 0
    queued = 0
    for user in User.objects.filter(pk__in=ids, is_active=True).order_by('pk').iterator(chunk_size=200):
        # A fixed subscriber receives one message even if they are also the
        # actor, account subject, employee or manager.
        candidates = [w for w in assigned if user.pk == w.manager_id or is_assignee(user, w)]
        if history:
            candidates = [history.assignment]
        for work in [*candidates, None]:
            if not can_receive(user, rule, actor_id, subject_id, work, event, item):
                continue
            _, created = Delivery.objects.get_or_create(source=source, recipient_key=user.pk, defaults={
                'rule': rule, 'recipient': user, 'email_digest': email_digest(user.email),
                'actor_id': actor_id, 'subject_user_id': subject_id, 'activity': event,
                'record_model': item._meta.label_lower if item else '',
                'record_key': item.pk if item and isinstance(item.pk, int) else None,
                'work': work, 'work_history': history,
            })
            queued += int(created)
            break
    return queued


def consume_activity(event_id, sponsorship_id=None):
    from access_control.models import UserActivity
    if not SMTPConfig.objects.filter(pk=1, enabled=True).exists():
        return 0
    event = UserActivity.objects.filter(pk=event_id).first()
    if event is None:
        return 0
    code = activity_code(event, sponsorship_id)
    rule = EventRule.objects.filter(pk=code, enabled=True).first()
    if rule is None:
        return 0
    # Specializations etc. may use noninteger keys. Work links are integer-only.
    pk = event.target_key
    model = event.target_model
    if sponsorship_id:
        model, pk = 'market_needs.sponsorship', sponsorship_id
    item = record(model, pk) if model in SCOPED_MODELS and pk else None
    subject_id = int(event.target_key) if event.target_model == 'auth.user' and event.target_key.isascii() and event.target_key.isdigit() and event.action != 'delete' else None
    work = ()
    if code not in CATALOG:
        return 0
    if CATALOG[code].work and (rule.to_employee or rule.to_manager) and item:
        lookup = Q(target_model=model, target_key=item.pk)
        if model == 'market_needs.sponsorship':
            lookup |= Q(target_model='market_needs.need', target_key=item.need_id)
        elif model == 'market_needs.need' and event.module == 'provider_assignments':
            if hasattr(item, 'execution'):
                lookup |= Q(target_model='market_needs.needexecution', target_key=item.execution.pk)
        work = WorkAssignment.objects.filter(lookup, status__in=['new', 'running'])
    return enqueue(code, f'activity:{event.pk}', actor_id=event.actor_id, subject_id=subject_id,
                   item=item, event=event, assignments=work)
