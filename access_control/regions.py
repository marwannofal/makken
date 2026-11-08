"""User regional boundary, independent of page/operation grants and matching rules.

One overlapping region permits reading. Every region must be granted for a
mutation. Unassigned legacy records remain visible only to unrestricted users.
Never filter a record's regions before calculating write access.
"""
from contextlib import contextmanager
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import BooleanField, Exists, OuterRef, Q, Value
from .models import RegionScope, UserAccess

READ_ONLY = 'هذا السجل مشترك مع مناطق خارج نطاقك؛ يمكنك عرضه فقط. تعديل السجل يتطلب صلاحية على جميع مناطقه.'
OUTSIDE = 'السجل أو المناطق المحددة خارج نطاق المناطق المسموح لك بها.'


class RegionalPolicy:
    def __init__(self, user):
        self.user = user
        self.active = bool(user and user.is_authenticated and user.is_active)
        self.unrestricted = bool(self.active and user.is_superuser)
        self.ids = frozenset()
        if not self.active or self.unrestricted:
            return
        access = UserAccess.objects.filter(user_id=user.pk).first()
        if access:
            self.unrestricted = access.region_scope == RegionScope.ALL
            if not self.unrestricted:
                self.ids = frozenset(access.allowed_regions.values_list('pk', flat=True))

    def accepts(self, ids):
        return self.unrestricted or bool(ids) and set(ids).issubset(self.ids)


def relations(model):
    """Return the unfiltered ownership relation (including inactive/history)."""
    from market_needs.models import NeedRegion
    from partnerships.models import PartnershipRegion
    from service_providers.models import ProviderCoverage
    return {
        'market_needs.need': (NeedRegion, 'need_id'),
        'partnerships.partnership': (PartnershipRegion, 'partnership_id'),
        'service_providers.serviceprovider': (ProviderCoverage, 'provider_id'),
    }.get(model._meta.label_lower)


def scoped(query, user=None, *, policy=None, writable=False):
    # Optional user retains compatibility for internal, non-request reporting.
    # Every request and authoritative write passes a verified actor explicitly.
    if user is None and policy is None:
        return query
    policy = policy or RegionalPolicy(user)
    if not policy.active:
        return query.none()
    if policy.unrestricted:
        return query.annotate(region_writable=Value(True, output_field=BooleanField()))
    label = query.model._meta.label_lower
    relation = relations(query.model)
    if relation:
        model, owner = relation
        all_regions = model.objects.filter(**{owner: OuterRef('pk')})
        inside = all_regions.filter(region_id__in=policy.ids)
        outside = all_regions.exclude(region_id__in=policy.ids)
        query = query.annotate(region_writable=Exists(inside) & ~Exists(outside)).filter(Exists(inside))
        return query.filter(region_writable=True) if writable else query
    if label == 'regions.region':
        return query.filter(pk__in=policy.ids).annotate(region_writable=Value(True, output_field=BooleanField()))
    if label == 'market_needs.sponsorship':
        from market_needs.models import Need
        from partnerships.models import Partnership
        return query.filter(need_id__in=scoped(Need.objects.all(), policy=policy, writable=writable).values('pk'),
                            partnership_id__in=scoped(Partnership.objects.all(), policy=policy, writable=writable).values('pk'))
    if label == 'market_needs.needexecution':
        from market_needs.models import Need
        return query.filter(need_id__in=scoped(Need.objects.all(), policy=policy, writable=writable).values('pk'))
    # Shared reference catalogs retain their existing RBAC policy by decision.
    return query


def can_write(user, item, *, policy=None):
    if item is None or not item.pk:
        return False
    policy = policy or RegionalPolicy(user)
    if not policy.active:
        return False
    if policy.unrestricted:
        return True
    if relations(type(item)) or item._meta.label_lower in {'regions.region', 'market_needs.sponsorship', 'market_needs.needexecution'}:
        return scoped(type(item)._base_manager.filter(pk=item.pk), policy=policy, writable=True).exists()
    return True


def require_write(user, item, *, policy=None):
    if not can_write(user, item, policy=policy):
        raise PermissionDenied(READ_ONLY)


def require_regions(user, ids, *, policy=None):
    policy = policy or RegionalPolicy(user)
    if not policy.active or not policy.accepts(ids):
        raise PermissionDenied(OUTSIDE)


def region_choices(user, current=()):
    from regions.models import Region
    return scoped(Region.objects.filter(Q(is_active=True) | Q(pk__in=current)), user)


@contextmanager
def regional_transaction(user):
    """Serialize regional access changes with mutations, not reads.

    User administration writes this same access row before changing grants.
    A queued business write therefore rechecks the committed latest scope.
    """
    if not user or not user.is_authenticated:
        raise PermissionDenied('يجب تسجيل الدخول لتنفيذ هذه العملية.')
    with transaction.atomic():
        if not user.is_superuser:
            UserAccess.objects.select_for_update().filter(user_id=user.pk).first()
        fresh = get_user_model().objects.filter(pk=user.pk).first()
        if fresh is None:
            raise PermissionDenied('هذا الحساب غير متاح.')
        if not fresh.is_active:
            raise PermissionDenied('هذا الحساب غير نشط.')
        yield RegionalPolicy(fresh)


def locked_object(module, pk):
    from django.apps import apps
    labels = {'market_needs': 'market_needs.Need', 'partnerships': 'partnerships.Partnership',
              'service_providers': 'service_providers.ServiceProvider', 'regions': 'regions.Region',
              'provider_assignments': 'market_needs.Need'}
    return apps.get_model(labels[module]).objects.select_for_update().filter(pk=pk).first() if pk and module in labels else None


def guard_service(module, operation, values, policy):
    payload = values.get('payload', {})
    pk = values.get('pk') or payload.get('id')
    item = locked_object(module, pk)
    if pk and item is not None:
        require_write(policy.user, item, policy=policy)
    if module == 'market_needs' and operation == 'save_need':
        data = values.get('data', {})
        ids = data.getlist('regions') if hasattr(data, 'getlist') else data.get('regions', [])
        try:
            require_regions(policy.user, [int(i) for i in ids], policy=policy)
        except (ValueError, TypeError):
            raise PermissionDenied(OUTSIDE)
    if module == 'market_needs' and operation == 'add_candidates':
        from partnerships.models import Partnership
        ids = values['ids']
        list(Partnership.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
        allowed = scoped(Partnership.objects.filter(pk__in=ids), policy=policy, writable=True)
        if set(allowed.values_list('pk', flat=True)) != set(ids):
            raise PermissionDenied(OUTSIDE)
    if module == 'market_needs' and operation == 'followup':
        from market_needs.models import Sponsorship
        from partnerships.models import Partnership
        record = Sponsorship.objects.filter(pk=values['sponsorship_id'], need_id=pk).first()
        if record:
            organization = Partnership.objects.select_for_update().get(pk=record.partnership_id)
            require_write(policy.user, organization, policy=policy)


def guard_request(request, module, kwargs):
    """Protect direct editor/download URLs in addition to scoped list queries."""
    from django.apps import apps
    from django.http import Http404
    policy = RegionalPolicy(request.user)
    if policy.unrestricted:
        return
    labels = {'partnerships': 'partnerships.Partnership', 'market_needs': 'market_needs.Need',
              'service_providers': 'service_providers.ServiceProvider',
              'approved_programs': 'market_needs.Need', 'provider_assignments': 'market_needs.Need'}
    pk = kwargs.get('pk')
    mutation = request.method == 'POST' or request.resolver_match.url_name == 'edit'
    if module in labels and pk:
        model = apps.get_model(labels[module])
        item = scoped(model.objects.all(), policy=policy).filter(pk=pk).first()
        if item is None:
            raise Http404
        if mutation:
            require_write(request.user, item, policy=policy)
    if module == 'regions':
        from regions.models import Region
        edit = request.GET.get('edit')
        if edit == 'new':
            raise PermissionDenied('إضافة منطقة جديدة متاحة للحساب غير المقيّد بمناطق فقط.')
        if edit:
            if not str(edit).isascii() or not str(edit).isdigit() or not scoped(Region.objects.all(), policy=policy).filter(pk=edit).exists():
                raise Http404
        if request.method == 'POST':
            from regions import views
            action = request.POST.get('action')
            value = views._load(request.POST.get('snapshot' if action == 'preview' else 'token'), request.user, views.SNAPSHOT_SALT if action == 'preview' else views.CONFIRM_SALT)
            if value.get('operation') == 'add':
                raise PermissionDenied('إضافة منطقة جديدة متاحة للحساب غير المقيّد بمناطق فقط.')
            region = Region.objects.select_for_update().filter(pk=value.get('id')).first()
            require_write(request.user, region, policy=policy)


def history(query, user):
    """Do not leak out-of-scope organizations through sponsorship history."""
    from partnerships.models import Partnership
    return query.filter(Q(sponsorship__isnull=True) | Q(sponsorship__partnership_id__in=scoped(Partnership.objects.all(), user).values('pk')))


def execution_write(function):
    """Protect direct service callers and preserve hidden saved associations."""
    from functools import wraps

    @wraps(function)
    def wrapped(*args, **kwargs):
        from market_needs.models import NeedExecution
        from service_providers.models import ServiceProvider
        from partnerships.models import Partnership
        with regional_transaction(kwargs['actor']) as policy:
            need = locked_object('provider_assignments', kwargs['need_id'])
            require_write(policy.user, need, policy=policy)
            execution = NeedExecution.objects.filter(need=need).first()
            selected = kwargs['data']
            provider_ids = set(selected['providers'])
            employer_ids = set(selected['employers'])
            if execution:
                provider_ids.update(execution.provider_links.values_list('provider_id', flat=True))
                employer_ids.update(execution.employer_links.values_list('partnership_id', flat=True))
            for model, ids in ((ServiceProvider, provider_ids), (Partnership, employer_ids)):
                list(model.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
                visible = scoped(model.objects.filter(pk__in=ids), policy=policy, writable=True)
                if not policy.unrestricted and set(visible.values_list('pk', flat=True)) != ids:
                    raise PermissionDenied(READ_ONLY)
            return function(*args, **{**kwargs, 'actor': policy.user})
    return wrapped


def safe_event(event, user, cache=None):
    """Redact saved execution evidence rather than expose hidden parties via JSON."""
    import copy
    from partnerships.models import Partnership
    from service_providers.models import ServiceProvider
    cache = cache if cache is not None else {}
    if 'policy' not in cache:
        cache['policy'] = RegionalPolicy(user)
    if cache['policy'].unrestricted:
        return event
    clone = copy.copy(event)
    for side in ('before', 'after'):
        values = copy.deepcopy(getattr(event, side))
        for key, model in (('مزودو التدريب', ServiceProvider), ('جهات التوظيف', Partnership)):
            if key not in values:
                continue
            if key not in cache:
                cache[key] = set(scoped(model.objects.all(), policy=cache['policy']).values_list('name', flat=True))
            rows = values[key] if isinstance(values[key], list) else []
            values[key] = [row for row in rows if isinstance(row, dict) and row.get('name') in cache[key]]
        setattr(clone, side, values)
    return clone
