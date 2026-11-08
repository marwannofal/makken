"""Commit-aware audit capture for existing MVT services and direct admin edits.

Known business audit records take precedence over generic model callbacks.
No SQL trace, request body, raw URL, session, token or password is persisted.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field
import uuid
import hashlib
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db import transaction
from django.db.models.signals import pre_save, post_save, pre_delete, m2m_changed
from .activity_data import sanitize, clean_text

current = ContextVar('makken_activity', default=None)

# Only parent business records; owned rows are rolled into parent snapshots.
MODELS = {
    'levels.level': 'levels', 'regions.region': 'regions', 'entities.entity': 'entities',
    'specializations.specialization': 'specializations', 'sectors.sector': 'sectors',
    'expense_items.expenseitem': 'expense_items', 'training_programs.trainingprogram': 'training_programs',
    'sponsorship_shapes.sponsorshipshape': 'sponsorship_shapes', 'care_states.statecolor': 'care_states',
    'partnerships.partnership': 'partnerships', 'service_providers.serviceprovider': 'service_providers',
    'market_needs.need': 'market_needs', 'market_needs.sponsorship': 'market_needs',
    'market_needs.needexecution': 'provider_assignments', 'auth.user': 'accounts',
    'accounts.userprofile': 'accounts',
}
FIELDS = {'name', 'title', 'representative', 'is_active', 'scope', 'financial_capacity', 'entity', 'entity_type',
          'branch', 'sector', 'specialization', 'description', 'color', 'development_state',
          'program', 'category', 'is_training', 'is_operational', 'training_type', 'provider_type',
          'beneficiaries', 'duration', 'duration_unit', 'source', 'observed_on', 'total_cost',
          'requested_support', 'approved_support', 'status', 'amount', 'notes', 'rejection_reason',
          'level', 'completed_at', 'first_name', 'last_name', 'username', 'is_superuser', 'development_state_at', 'is_employment', 'preliminary_agreement_type'}


@dataclass
class Capture:
    request: object
    request_id: object = field(default_factory=uuid.uuid4)
    pending: dict = field(default_factory=dict)
    covered: set = field(default_factory=set)
    emitted: set = field(default_factory=set)
    private_before: dict = field(default_factory=dict)
    coverage_sources: dict = field(default_factory=dict)


def regions_for(item):
    from .regions import relations
    if item is None or item.pk is None:
        return {}
    label = item._meta.label_lower
    if label == 'regions.region':
        return {item.pk: item.name}
    if label in {'market_needs.sponsorship', 'market_needs.needexecution'}:
        result = regions_for(item.need)
        if label.endswith('sponsorship'):
            result.update(regions_for(item.partnership))
        return result
    if label == 'auth.user':
        from .models import UserAccess
        access = UserAccess.objects.filter(user_id=item.pk, region_scope='selected').first()
        return dict(access.allowed_regions.values_list('pk','name')) if access else {}
    if label == 'accounts.userprofile':
        return regions_for(item.user)
    relation = relations(type(item))
    if relation:
        model, owner = relation
        return dict(model.objects.filter(**{owner: item.pk}).values_list('region_id','region__name'))
    return {}


def snapshot(item):
    if item is None:
        return {}
    result = {}
    for f in item._meta.concrete_fields:
        if f.name not in FIELDS:
            continue
        value = f.value_from_object(item)
        if f.is_relation and value is not None:
            related = getattr(item, f.name, None)
            value = str(related) if related is not None else None
        result[f.name] = value
    label = item._meta.label_lower
    if label in {'partnerships.partnership', 'market_needs.need', 'service_providers.serviceprovider'}:
        result['regions'] = list(regions_for(item).values())
    if label == 'partnerships.partnership':
        result['offerings'] = [{'sector': r.sector.name, 'shape': r.sponsorship_shape.name,
            'specializations': list(r.specializations.values_list('name', flat=True)), 'is_active': r.is_active}
            for r in item.offerings.select_related('sector','sponsorship_shape').prefetch_related('specializations')]
        result['attachment_count'] = item.willingness_attachments.count()
    if label == 'service_providers.serviceprovider':
        result['coverage'] = [{'region': r.region.name, 'is_active': r.is_active,
            'specializations': list(r.specializations.values_list('name', flat=True))}
            for r in item.coverage.select_related('region').prefetch_related('specializations')]
    if label == 'auth.user':
        result['roles'] = list(item.groups.values_list('name', flat=True))
    if label == 'sectors.sector':
        result['specializations'] = list(item.specializations.values_list('name', flat=True))
    if label == 'training_programs.trainingprogram':
        result['expense_items'] = list(item.expense_items.values_list('name', flat=True))
    return sanitize(result)


def record_label(item):
    label = item._meta.label_lower
    if label == 'accounts.userprofile':
        return 'الملف الشخصي: '+item.user.get_username()
    if label == 'market_needs.sponsorship':
        return item.need.number+' / '+item.partnership.name
    if label == 'market_needs.needexecution':
        return 'تنفيذ البرنامج: '+item.need.number
    return str(item)


def actor_data(actor):
    if actor is None or not getattr(actor, 'is_authenticated', False):
        return {'actor': None, 'actor_key': None, 'actor_name': 'عملية نظام مسجلة', 'actor_username': ''}
    return {'actor': actor, 'actor_key': actor.pk,
            'actor_name': clean_text(actor.get_full_name() or actor.get_username(), 200),
            'actor_username': clean_text(actor.get_username(), 150)}


def emit(*, actor=None, regions=None, scope=None, context=None, **values):
    from .models import UserActivity, ActivityRegion
    regions = regions or {}
    identity = actor_data(actor)
    if values.get('actor_name'):
        identity['actor_name'] = clean_text(values['actor_name'], 200)
    if values.get('actor_username'):
        identity['actor_username'] = clean_text(values['actor_username'], 150)
    values.update(identity)
    values['before'] = sanitize(values.get('before', {}))
    values['after'] = sanitize(values.get('after', {}))
    values['scope'] = scope or ('regional' if regions else 'global')
    if context:
        values.setdefault('request_id', context.request_id)
        match = getattr(context.request, 'resolver_match', None)
        values.setdefault('route', clean_text(match.view_name if match else '', 150))
    source = values.get('source_key')
    with transaction.atomic():
        if source:
            defaults = {k:v for k,v in values.items() if k != 'source_key'}
            event, created = UserActivity.objects.get_or_create(source_key=source, defaults=defaults)
            if not created:
                return None
        else:
            event = UserActivity.objects.create(**values)
        ActivityRegion.objects.bulk_create([ActivityRegion(event=event, region_key=pk,
            name=clean_text(name, 100)) for pk, name in sorted(regions.items())])
    return event


def private_digests(item):
    if item is None:
        return {}
    fields = ('email','phone') + (('password',) if isinstance(item,get_user_model()) else ())
    result = {}
    for name in fields:
        if hasattr(item,name):
            value = str(getattr(item,name))
            if name == 'phone':
                value += '|' + str(getattr(item,'phone_country',''))
            result[name] = hashlib.sha256(value.encode()).digest()
    return result


def queue(instance, before, old_regions, *, deleted=False, using='default', private_before=None):
    ctx = current.get()
    if ctx is None:
        return
    model, pk = type(instance), instance.pk
    key = (instance._meta.label_lower, str(pk))
    # The first snapshot belongs to the pre-mutation row, not the last save in
    # the transaction. Callback reads the final committed M2M/owned rows.
    pending = ctx.pending.setdefault(key, (before, old_regions, record_label(instance)))
    private = ctx.private_before.setdefault(key, {})
    for name, digest in (private_before or {}).items():
        private.setdefault(name,digest)
    def committed():
        if key in ctx.emitted:
            return
        if key in ctx.covered and any(apps.get_model(label)._base_manager.using(using).filter(pk=source_pk).exists()
                for label, source_pk in ctx.coverage_sources.get(key, ())):
            return
        item = None if deleted else model._base_manager.using(using).filter(pk=pk).first()
        previous, regions, label = pending
        after = snapshot(item)
        final_private = private_digests(item)
        if item is not None:
            after.update({name+'_changed': True for name, digest in private.items() if final_private.get(name) != digest})
        if previous == after and not deleted:
            return
        ctx.emitted.add(key)
        action = ('delete' if deleted else 'create' if previous is None else
                  'status' if previous.get('is_active') != after.get('is_active')
                  or previous.get('status') != after.get('status')
                  or previous.get('development_state') != after.get('development_state') else 'update')
        current_regions = regions_for(item)
        # Keep both sides of a geographic move; old values cannot leak into a
        # region that was newly assigned to the record.
        region_union = {**regions, **current_regions}
        from .models import ActivityAction
        emit(actor=ctx.request.user, module=MODELS[key[0]], action=action,
             description=dict(ActivityAction.choices)[action], target_model=key[0],
             target_key=str(pk), target_label=clean_text(label, 300),
             before=previous or {}, after=after, regions=region_union,
             scope='unknown' if not region_union and key[0] in {
                 'partnerships.partnership', 'market_needs.need', 'service_providers.serviceprovider',
                 'market_needs.sponsorship', 'market_needs.needexecution'} else None,
             context=ctx, source_key=f'request:{ctx.request_id}:{key[0]}:{pk}')
    transaction.on_commit(committed, using=using, robust=True)


def before_save(sender, instance, raw=False, using='default', **kwargs):
    if raw or current.get() is None:
        return
    old = sender._base_manager.using(using).filter(pk=instance.pk).first() if instance.pk else None
    # Only irreversible, request-local comparison digests cross the callback.
    # No contact values, credential hashes or these digests are persisted.
    instance._activity_before = (snapshot(old) if old else None, regions_for(old), private_digests(old))


def after_save(sender, instance, raw=False, using='default', **kwargs):
    if not raw and hasattr(instance, '_activity_before'):
        before, regions, private = instance._activity_before
        queue(instance, before, regions, using=using, private_before=private)
        del instance._activity_before


def before_delete(sender, instance, using='default', **kwargs):
    if current.get():
        queue(instance, snapshot(instance), regions_for(instance), deleted=True, using=using)


def relation_change(sender, instance, action, reverse=False, using='default', **kwargs):
    if current.get() and instance._meta.label_lower in MODELS and action in {'pre_add','pre_remove','pre_clear'} and not reverse:
        queue(instance, snapshot(instance), regions_for(instance), using=using)


def authenticated(sender, request, user, **kwargs):
    if request is None or user is None:
        return
    action = 'login' if kwargs.get('_login') else 'logout'
    ctx = current.get()
    transaction.on_commit(lambda: emit(actor=user, module='accounts', action=action,
        description='تسجيل الدخول' if action == 'login' else 'تسجيل الخروج',
        regions=regions_for(user), context=ctx), robust=True)


def login(sender, request, user, **kwargs):
    authenticated(sender, request, user, _login=True)


def source_saved(sender, instance, raw=False, using='default', **kwargs):
    if raw:
        return
    ctx = current.get()
    if ctx:
        def cover(model_label, pk):
            key = (model_label, str(pk))
            ctx.covered.add(key)
            ctx.coverage_sources.setdefault(key, set()).add((sender._meta.label_lower, instance.pk))
        label = sender._meta.label_lower
        if label == 'market_needs.auditevent':
            cover('market_needs.need', instance.need_id)
            if instance.sponsorship_id:
                cover('market_needs.sponsorship', instance.sponsorship_id)
        elif label == 'service_providers.provideraudit':
            cover('service_providers.serviceprovider', instance.provider_id)
        elif instance.target_user_id:
            cover('auth.user', instance.target_user_id)
    from .activity_history import import_event
    transaction.on_commit(lambda: import_event(instance, context=ctx), using=using, robust=True)


def connect():
    for label in MODELS:
        model = apps.get_model(label)
        pre_save.connect(before_save, sender=model, dispatch_uid='activity.pre.'+label, weak=False)
        post_save.connect(after_save, sender=model, dispatch_uid='activity.post.'+label, weak=False)
        pre_delete.connect(before_delete, sender=model, dispatch_uid='activity.delete.'+label, weak=False)
    for label in ('market_needs.AuditEvent','service_providers.ProviderAudit','access_control.SecurityAudit'):
        post_save.connect(source_saved, sender=apps.get_model(label), dispatch_uid='activity.source.'+label, weak=False)
    m2m_changed.connect(relation_change, dispatch_uid='activity.m2m', weak=False)
    user_logged_in.connect(login, dispatch_uid='activity.login', weak=False)
    user_logged_out.connect(authenticated, dispatch_uid='activity.logout', weak=False)
