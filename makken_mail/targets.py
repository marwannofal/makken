"""Only registered models and internal URLs can be used in email or work links."""
from dataclasses import dataclass
from django.apps import apps
from django.urls import reverse
from access_control.enforcement import MODELS
from access_control.policy import AccessPolicy
from access_control.regions import RegionalPolicy, scoped


@dataclass(frozen=True)
class Target:
    label: str
    module: str


WORK_TARGETS = {
    'agreement_clauses.agreement': Target('اتفاقية', 'partnerships'),
    'partnerships.partnership': Target('شراكة', 'partnerships'),
    'market_needs.need': Target('بطاقة حاجة السوق', 'market_needs'),
    'market_needs.sponsorship': Target('متابعة رعاية', 'market_needs'),
    'market_needs.needexecution': Target('تنفيذ برنامج', 'provider_assignments'),
    'service_providers.serviceprovider': Target('مزود خدمة', 'service_providers'),
}
SCOPED_MODELS = {label.lower() for label in MODELS.values()} | set(WORK_TARGETS) | {'care_states.statecolor', 'access_control.useractivity'}


def record(model, pk):
    if model not in SCOPED_MODELS or pk is None:
        return None
    if model != 'care_states.statecolor':
        key = str(pk)
        if not key.isascii() or not key.isdigit() or len(key) > 19 or not 0 < int(key) < 2**63:
            return None
        pk = int(key)
    return apps.get_model(model)._base_manager.filter(pk=pk).first()


def can_read_record(user, item, module=None):
    if item is None or not user or not user.is_active:
        return False
    kind = item._meta.label_lower
    spec = WORK_TARGETS.get(kind)
    module = module or (spec.module if spec else None)
    policy = AccessPolicy(user)
    if not module or not policy.can(module):
        return False
    if kind == 'access_control.useractivity':
        return audit_scope(user, item)
    if kind == 'agreement_clauses.agreement':
        from partnerships.models import Partnership
        return scoped(Partnership._base_manager.filter(pk=item.partnership_id), user).exists()
    # An execution activity imported from the audit source points at its need.
    # Its view permission remains the execution module, not the market card.
    return scoped(type(item)._base_manager.filter(pk=item.pk), user).exists()


def is_assignee(user, work):
    if not user or not user.pk or not work:
        return False
    if user.pk == work.employee_id:
        return True
    if not work.pk:
        return False
    cache = getattr(work, '_prefetched_objects_cache', {})
    if 'assignees' in cache:
        return any(person.pk == user.pk for person in cache['assignees'])
    return work.assignees.filter(pk=user.pk).exists()


def can_read_work(user, work):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    policy = AccessPolicy(user)
    participates = (
        user.pk == work.manager_id
        or is_assignee(user, work)
        or (user.pk == work.created_by_id and (policy.can('work_assignments', 'create') or policy.can('work_assignments', 'edit')))
    )
    if not participates:
        return False
    return not work.target_model or can_read_record(user, record(work.target_model, work.target_key))


def can_manage_work(user, work):
    """Superusers or authorized work managers can edit/reassign open work within scope."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    policy = AccessPolicy(user)
    if not policy.can('work_assignments', 'edit'):
        return False
    if work is None:
        return True
    if user.pk not in (work.manager_id, work.created_by_id):
        return False
    return not work.target_model or can_read_record(user, record(work.target_model, work.target_key))


def audit_scope(user, event):
    policy = RegionalPolicy(user)
    if not policy.active:
        return False
    if policy.unrestricted or event.scope == 'global':
        return True
    if event.scope != 'regional':
        return False
    regions = set(event.region_snapshots.values_list('region_key', flat=True))
    return bool(regions and regions <= policy.ids)


def record_label(item):
    if item is None:
        return ''
    kind = item._meta.label_lower
    if kind == 'access_control.useractivity':
        return f'حدث رقم {item.pk}'
    if kind == 'agreement_clauses.agreement':
        return f'{item.number} · {item.title}'
    if kind == 'market_needs.sponsorship':
        return item.need.number + ' · ' + item.partnership.name
    if kind == 'market_needs.needexecution':
        return item.need.number + ' · ' + item.need.title
    return str(item)[:240]


def record_path(item, module):
    if item is not None and item._meta.label_lower == 'agreement_clauses.agreement':
        return reverse('partnerships:agreement', args=[item.partnership_id, item.pk])
    if module == 'provider_assignments' and item is not None:
        pk = item.need_id if item._meta.label_lower == 'market_needs.needexecution' else item.pk
        return reverse('program_execution:assignment', args=[pk])
    if module == 'market_needs' and item is not None and item._meta.label_lower == 'market_needs.sponsorship':
        return reverse('market_needs:followup', args=[item.need_id])
    if module in {'partnerships', 'market_needs', 'service_providers'} and item is not None:
        return reverse(module + ':index') + '?detail=' + str(item.pk)
    from access_control.registry import DEFINITIONS
    return reverse(DEFINITIONS[module].route_name) if module in DEFINITIONS else reverse('makken_home')
